from __future__ import annotations

import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .store import read_jsonl, upsert


def _yt_dlp_command() -> list[str] | None:
    executable = shutil.which("yt-dlp")
    if executable:
        return [executable]
    try:
        from importlib.util import find_spec
        if find_spec("yt_dlp") is not None:
            return [sys.executable, "-m", "yt_dlp"]
    except (ImportError, ValueError):
        pass
    return None


def ingest(root: Path, captions: bool = False, limit: int | None = None, delay: float = 3.0, store_captions: bool = False) -> dict[str, int]:
    path = root / "catalog/videos.jsonl"
    videos = read_jsonl(path)
    if limit is not None:
        videos = videos[:limit]
    result = {"checked": 0, "acquired": 0, "missing_or_failed": 0, "tooling_blocked": 0, "rights_skipped": 0, "skipped": 0}
    events: list[dict[str, Any]] = []
    for video in videos:
        result["checked"] += 1
        vid = video["video_id"]
        output_dir = root / "transcripts/permitted"
        existing = list(output_dir.glob(f"{vid}.en*.vtt"))
        if existing:
            video["transcript_status"] = "captions_stored_locally"
            video["transcript_path"] = str(existing[0].relative_to(root)).replace("\\", "/")
            result["skipped"] += 1
            continue
        if not captions:
            result["skipped"] += 1
            continue
        if not store_captions or not video.get("caption_storage_authorized", False):
            timestamp = datetime.now(timezone.utc).isoformat()
            video["ingest"] = {"status": "rights_review_required", "checked_at": timestamp, "reason": "Caption storage was not explicitly marked authorized for this source."}
            events.append({"event_id": f"rights-skip:{vid}", "event": "caption_storage_skipped", "video_id": vid, "status": "rights_review_required", "timestamp": timestamp, "reason": video["ingest"]["reason"]})
            result["rights_skipped"] += 1
            continue
        yt_dlp = _yt_dlp_command()
        if not yt_dlp:
            timestamp = datetime.now(timezone.utc).isoformat()
            video["ingest"] = {"status": "blocked", "error": "yt-dlp is not installed", "checked_at": timestamp, "retry_after": None}
            events.append({"event_id": f"ingest:{vid}:{timestamp}", "event": "caption_attempt", "video_id": vid, "status": "blocked", "timestamp": timestamp})
            result["tooling_blocked"] += 1
            continue
        previous = video.get("ingest", {})
        retry_after = previous.get("retry_after")
        now = datetime.now(timezone.utc)
        if retry_after and datetime.fromisoformat(retry_after) > now:
            result["skipped"] += 1
            continue
        root.joinpath("transcripts/permitted").mkdir(parents=True, exist_ok=True)
        command = [*yt_dlp, "--skip-download", "--write-subs", "--write-auto-subs", "--sub-langs", "en,en.*", "--sub-format", "vtt", "-o", str(output_dir / "%(id)s.%(language)s.%(ext)s"), video["canonical_url"]]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        timestamp = datetime.now(timezone.utc).isoformat()
        captions_found = list(output_dir.glob(f"{vid}.en*.vtt"))
        if completed.returncode == 0 and captions_found:
            video["transcript_status"] = "captions_stored_locally"
            video["transcript_language"] = captions_found[0].name.removeprefix(f"{vid}.").removesuffix(".vtt")
            video["transcript_path"] = str(captions_found[0].relative_to(root)).replace("\\", "/")
            video["ingest"] = {"status": "acquired", "attempted_at": timestamp, "retry_after": None}
            result["acquired"] += 1
        else:
            prior_failures = int(previous.get("failures", 0)) + 1
            backoff_hours = min(24 * (2 ** (prior_failures - 1)), 24 * 30)
            video["ingest"] = {"status": "failed", "failures": prior_failures, "attempted_at": timestamp, "retry_after": (now + timedelta(hours=backoff_hours)).isoformat(), "error": (completed.stderr.strip() or completed.stdout.strip())[-1200:]}
            video["transcript_status"] = "unavailable" if "subtitle" in (completed.stderr or "").lower() else video.get("transcript_status", "unknown")
            result["missing_or_failed"] += 1
        events.append({"event_id": f"ingest:{vid}:{timestamp}", "event": "caption_attempt", "video_id": vid, "status": video["ingest"]["status"], "timestamp": timestamp})
        time.sleep(max(0, delay))
    upsert(path, videos, "video_id")
    upsert(root / "catalog/provenance.jsonl", events, "event_id")
    return result
