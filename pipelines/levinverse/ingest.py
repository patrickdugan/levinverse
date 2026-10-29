from __future__ import annotations

import shutil
import subprocess
import sys
import os
import re
import json
import html
import hashlib
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


def caption_text(path: Path, video: dict) -> Path:
    segments = []
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8-sig")):
        lines = block.splitlines()
        timing = next((i for i, line in enumerate(lines) if " --> " in line), None)
        if timing is None:
            continue
        stamp = lines[timing].split(" --> ")
        text = html.unescape(re.sub(r"<[^>]+>", "", " ".join(lines[timing + 1:]))).strip()
        if text and (not segments or text != segments[-1]["text"]):
            segments.append({"start": stamp[0], "end": stamp[1].split()[0], "text": text, "speaker": None})
    if not segments:
        raise ValueError("Downloaded caption file contains no timed cues")
    output = path.with_suffix(".txt")
    output.write_text("\n".join(f"[{s['start']} --> {s['end']}] {s['text']}" for s in segments) + "\n", encoding="utf-8")
    output.with_suffix(".json").write_text(json.dumps({"video_id": video["video_id"], "source_url": video["canonical_url"], "authorization_basis": video.get("caption_authorization_basis"), "raw_caption_file": path.name, "segments": segments}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def register_caption(root: Path, video: dict, raw: Path):
    output = caption_text(raw, video)
    payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    text = output.read_text(encoding="utf-8")
    language = raw.name.removeprefix(video["video_id"] + ".").removesuffix(".vtt")
    video.update(transcript_status="captions_stored_locally", transcript_language=language, transcript_path=output.relative_to(root).as_posix())
    upsert(root / "catalog/transcripts.jsonl", [{"transcript_id": f"captions:{video['video_id']}:{language}", "source_kind": "platform_caption", "source_url": video["canonical_url"], "title": video.get("title"), "video_ids": [video["video_id"]], "status": "stored", "text_path": video["transcript_path"], "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "word_count": len(text.split()), "segment_count": len(payload["segments"]), "authorization_basis": video.get("caption_authorization_basis"), "retrieved_at": datetime.now(timezone.utc).isoformat(), "transcript_quality": "platform captions; speaker identity not inferred", "relevance_confirmed": True}], "transcript_id")


def ingest(root: Path, captions: bool = False, limit: int | None = None, delay: float = 3.0, store_captions: bool = False, video_ids: set[str] | None = None) -> dict[str, int]:
    path = root / "catalog/videos.jsonl"
    videos = read_jsonl(path)
    if video_ids:
        videos = [v for v in videos if v["video_id"] in video_ids]
    result = {"checked": 0, "attempted": 0, "acquired": 0, "missing_or_failed": 0, "tooling_blocked": 0, "rights_skipped": 0, "skipped": 0}
    provider_path = root / "catalog/provider-state.json"
    provider = json.loads(provider_path.read_text(encoding="utf-8")) if provider_path.exists() else {}
    cooldown = provider.get("youtube", {}).get("retry_after")
    if cooldown and datetime.fromisoformat(cooldown) > datetime.now(timezone.utc):
        result["skipped"] = len(videos)
        result["provider_cooldown"] = cooldown
        return result
    worker_path = root / "reports/caption-worker.json"
    worker_path.parent.mkdir(parents=True, exist_ok=True)
    def checkpoint(video=None, event=None, status="running"):
        if video is not None:
            upsert(path, [video], "video_id")
        if event is not None:
            upsert(root / "catalog/provenance.jsonl", [event], "event_id")
        worker_path.write_text(json.dumps({"pid": os.getpid(), "status": status, "heartbeat_at": datetime.now(timezone.utc).isoformat(), "counts": result}, indent=2) + "\n", encoding="utf-8")
    checkpoint()
    events: list[dict[str, Any]] = []
    for video in videos:
        result["checked"] += 1
        vid = video["video_id"]
        output_dir = root / "transcripts/permitted"
        existing = list(output_dir.glob(f"{vid}.en*.vtt"))
        if existing:
            register_caption(root, video, existing[0])
            checkpoint(video)
            result["skipped"] += 1
            continue
        if not captions:
            result["skipped"] += 1
            continue
        if video.get("transcript_path") and (root / video["transcript_path"]).is_file():
            result["skipped"] += 1
            continue
        if not store_captions or not video.get("caption_storage_authorized", False):
            timestamp = datetime.now(timezone.utc).isoformat()
            video["ingest"] = {"status": "rights_review_required", "checked_at": timestamp, "reason": "Caption storage was not explicitly marked authorized for this source."}
            events.append({"event_id": f"rights-skip:{vid}", "event": "caption_storage_skipped", "video_id": vid, "status": "rights_review_required", "timestamp": timestamp, "reason": video["ingest"]["reason"]})
            result["rights_skipped"] += 1
            checkpoint(video, events[-1])
            continue
        yt_dlp = _yt_dlp_command()
        if not yt_dlp:
            timestamp = datetime.now(timezone.utc).isoformat()
            video["ingest"] = {"status": "blocked", "error": "yt-dlp is not installed", "checked_at": timestamp, "retry_after": None}
            events.append({"event_id": f"ingest:{vid}:{timestamp}", "event": "caption_attempt", "video_id": vid, "status": "blocked", "timestamp": timestamp})
            result["tooling_blocked"] += 1
            checkpoint(video, events[-1])
            continue
        previous = video.get("ingest", {})
        retry_after = previous.get("retry_after")
        now = datetime.now(timezone.utc)
        if retry_after and datetime.fromisoformat(retry_after) > now:
            result["skipped"] += 1
            continue
        if limit is not None and result["attempted"] >= limit:
            break
        result["attempted"] += 1
        root.joinpath("transcripts/permitted").mkdir(parents=True, exist_ok=True)
        runtime = ["--js-runtimes", os.environ["LEVINVERSE_JS_RUNTIME"]] if os.getenv("LEVINVERSE_JS_RUNTIME") else []
        languages = video.get("caption_languages", {})
        preferred = "en-orig" if "en-orig" in languages.get("automatic", []) and not any(l.startswith("en") for l in languages.get("manual", [])) else "en"
        command = [*yt_dlp, *runtime, "--skip-download", "--write-subs", "--write-auto-subs", "--sub-langs", preferred, "--sub-format", "vtt", "--retries", "1", "--extractor-retries", "1", "-o", str(output_dir / "%(id)s.%(language)s.%(ext)s"), video["canonical_url"]]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=120)
        except subprocess.TimeoutExpired:
            completed = subprocess.CompletedProcess(command, 1, "", "Caption request timed out after 120 seconds")
        timestamp = datetime.now(timezone.utc).isoformat()
        captions_found = list(output_dir.glob(f"{vid}.en*.vtt"))
        if completed.returncode == 0 and captions_found:
            register_caption(root, video, captions_found[0])
            video["ingest"] = {"status": "acquired", "attempted_at": timestamp, "retry_after": None}
            result["acquired"] += 1
        else:
            prior_failures = int(previous.get("failures", 0)) + 1
            backoff_hours = min(24 * (2 ** (prior_failures - 1)), 24 * 30)
            video["ingest"] = {"status": "failed", "failures": prior_failures, "attempted_at": timestamp, "retry_after": (now + timedelta(hours=backoff_hours)).isoformat(), "error": (completed.stderr.strip() or completed.stdout.strip())[-1200:]}
            video["transcript_status"] = "retrieval_failed"
            result["missing_or_failed"] += 1
        events.append({"event_id": f"ingest:{vid}:{timestamp}", "event": "caption_attempt", "video_id": vid, "status": video["ingest"]["status"], "timestamp": timestamp})
        checkpoint(video, events[-1])
        print(json.dumps({"video_id": vid, "status": video["ingest"]["status"], "attempted": result["attempted"], "acquired": result["acquired"]}), flush=True)
        if "429" in (completed.stderr or ""):
            provider["youtube"] = {"retry_after": video["ingest"]["retry_after"], "reason": "HTTP 429 during authorized caption retrieval", "checked_at": timestamp}
            provider_path.write_text(json.dumps(provider, indent=2) + "\n", encoding="utf-8")
            break
        time.sleep(max(0, delay))
    checkpoint(status="completed")
    return result
