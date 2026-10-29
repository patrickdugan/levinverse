"""Metadata and publicly exposed captions for configured non-YouTube video platforms."""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .expand import safe_url
from .feeds import parse_srt
from .harvest import Fetcher, authorization_basis, save_transcript, timestamp
from .podcast_audio import QuietLog
from .store import read_jsonl, upsert


def metadata(root: Path, source: dict) -> dict:
    from yt_dlp import YoutubeDL
    path = root / ".cache/platforms" / f"{source['platform']}-{source['media_id']}.json"
    if path.is_file() and time.time() - path.stat().st_mtime < 86400:
        info = json.loads(path.read_text(encoding="utf-8"))
    else:
        with YoutubeDL({"quiet": True, "skip_download": True, "noplaylist": True, "socket_timeout": 25, "retries": 0, "extractor_retries": 0, "logger": QuietLog()}) as client:
            info = client.extract_info(source["extractor_url"], download=False, process=False)
        if not info or str(info.get("id")) != source["media_id"] or info.get("_type") in {"playlist", "url", "url_transparent"}:
            raise ValueError("Native platform metadata does not identify the configured recording")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    if str(info.get("id")) != source["media_id"]:
        raise ValueError("Cached metadata identity mismatch")
    return info


def collect(root: Path, client: Fetcher) -> dict:
    basis = authorization_basis(root)
    if not basis:
        raise PermissionError("Transcript storage authorization is required")
    prior = {r["recording_id"]: r for r in read_jsonl(root / "catalog/external-media.jsonl")}
    result = {"attempted": 0, "captions_stored": 0, "not_retrieved": 0, "already_stored": 0}
    for source in json.loads((root / "config/external-platforms.json").read_text(encoding="utf-8"))["sources"]:
        ident = source["platform"] + ":" + source["media_id"]
        previous = prior.get(ident, {})
        if previous.get("transcript_path") and (root / previous["transcript_path"]).is_file():
            result["already_stored"] += 1
            continue
        if previous.get("retry_after") and datetime.fromisoformat(previous["retry_after"]) > datetime.now(timezone.utc):
            continue
        result["attempted"] += 1
        record = {**source, "recording_id": ident, "checked_at": timestamp()}
        try:
            info = metadata(root, source)
            date = info.get("upload_date")
            if not date and info.get("timestamp"):
                date = datetime.fromtimestamp(info["timestamp"], timezone.utc).strftime("%Y%m%d")
            subtitles = info.get("subtitles") or {}
            record.update(title=info.get("title"), duration_seconds=info.get("duration"), upload_date=f"{date[:4]}-{date[4:6]}-{date[6:]}" if date and re.fullmatch(r"\d{8}", date) else None, caption_languages=sorted(subtitles), metadata_status="retrieved")
            tracks = [(language, track) for language, group in subtitles.items() if language.startswith("en") for track in group if track.get("ext") in {"srt", "vtt"}]
            if not tracks:
                raise ValueError("No English SRT/VTT track listed by the native platform extractor; availability remains unresolved")
            language, track = tracks[0]
            if safe_url(track["url"]) != track["url"]:
                raise ValueError("Listed caption URL is temporary; source review required before retaining retrieval metadata")
            raw = client.get(track["url"])
            segments = parse_srt(raw)
            raw_path = Path("transcripts/permitted") / (source["platform"] + "-" + source["media_id"] + "." + track["ext"])
            (root / raw_path).parent.mkdir(parents=True, exist_ok=True)
            (root / raw_path).write_bytes(raw)
            stored = save_transcript(root, {"source_url": source["source_url"], "title": info["title"], "host": source["host"], "publication_date": None, "upload_date": record["upload_date"], "duration_seconds": record["duration_seconds"], "video_ids": [], "external_recording_id": ident, "source_kind": "platform_caption", "language": language, "segments": segments, "raw_transcript_path": raw_path.as_posix(), "transcript_track_url": track["url"], "relevance_confirmed": True, "relevance_evidence": "recording linked from official appearance index: " + source["participation_evidence_url"], "transcript_quality": "public platform caption track; not human verified; speaker identity not inferred"}, basis)
            record.update(status="captions_stored", transcript_path=stored["text_path"], transcript_id=stored["transcript_id"])
            result["captions_stored"] += 1
        except Exception as exc:
            reason = re.sub(r"https?://\S+", lambda m: safe_url(m.group(0)), str(exc))
            record.update(status="not_retrieved", reason=reason[-1200:], retry_after=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat())
            result["not_retrieved"] += 1
        upsert(root / "catalog/external-media.jsonl", [record], "recording_id")
        print(json.dumps({"recording_id": ident, "status": record["status"]}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    print(json.dumps(collect(root, Fetcher(root))), flush=True)


if __name__ == "__main__":
    main()
