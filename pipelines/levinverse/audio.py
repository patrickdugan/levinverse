"""Local CUDA transcription of explicitly permitted publisher audio enclosures."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import os
import socket
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from .harvest import Fetcher, authorization_basis, merge_video, soup, timestamp, tls_context
from .store import read_jsonl, upsert
from .transcribe import transcribe_media

FEED = "https://feeds.transistor.fm/thoughtforms-life"


def publisher_id(url: str) -> str | None:
    match = re.search(r"/(?:e|s)/([a-f0-9]{8})(?:/|$)", urlparse(url).path)
    return match.group(1) if match else None


def plan(root: Path, client: Fetcher) -> dict:
    permission = json.loads((root / "config/permissions.json").read_text(encoding="utf-8"))
    if permission.get("audio_processing_authorized") is not True:
        raise PermissionError("Audio processing requires explicit configuration authorization")
    feed = ET.fromstring(client.get(FEED))
    episodes = {publisher_id(i.findtext("link", "")): i for i in feed.findall("./channel/item")}
    transcripts = read_jsonl(root / "catalog/transcripts.jsonl")
    covered = {vid for r in transcripts if r.get("status") == "stored" for vid in r.get("video_ids", [])}
    queued = 0
    for row in transcripts:
        if row.get("status") != "no_publisher_transcript" or not row.get("relevance_confirmed") or any(v in covered for v in row.get("video_ids", [])):
            continue
        page = soup(client.get(row["source_url"]))
        frame = page.find("iframe", src=re.compile(r"share\.transistor\.fm"))
        if frame is None:
            continue
        ident = publisher_id(frame.get("src", ""))
        if not ident:
            upsert(root / "catalog/harvest-errors.jsonl", [{"url": row["source_url"], "attempted_at": timestamp(), "reason": "Publisher page contains a malformed audio-player URL"}], "url")
            continue
        item = episodes.get(ident)
        media_url, duration = None, None
        if item is not None:
            enclosure = item.find("enclosure")
            media_url = enclosure.get("url") if enclosure is not None else None
            duration_text = next((n.text for n in item if n.tag.endswith("duration")), None)
            duration = int(duration_text) if duration_text and duration_text.isdigit() else None
        if not media_url:
            try:
                player = client.get(frame["src"]).decode("utf-8")
            except Exception as exc:
                upsert(root / "catalog/harvest-errors.jsonl", [{"url": row["source_url"], "attempted_at": timestamp(), "reason": "Audio-player retrieval failed: " + str(exc)}], "url")
                continue
            match = re.search(r'https://media\.transistor\.fm/[a-f0-9]+/[a-f0-9]+\.mp3', player)
            media_url = match.group(0) if match else None
        if not media_url or urlparse(media_url).hostname != "media.transistor.fm":
            continue
        video_id = row["video_ids"][0] if row.get("video_ids") else "audio-" + str(ident)
        previous = next((r for r in read_jsonl(root / "catalog/audio-queue.jsonl") if r.get("job_id") == ident), {})
        job = {**previous, "job_id": ident, "video_id": video_id, "title": row["title"], "source_url": row["source_url"], "audio_url": media_url, "duration_seconds": duration, "authorization_basis": authorization_basis(root), "status": previous.get("status", "pending"), "queued_at": previous.get("queued_at", timestamp())}
        upsert(root / "catalog/audio-queue.jsonl", [job], "job_id")
        queued += 1
    return {"publisher_audio_jobs": queued, "feed_episodes": len(episodes)}


def download(job: dict, root: Path) -> Path:
    suffix = Path(urlparse(job["audio_url"]).path).suffix.lower()
    suffix = suffix if suffix in {".mp3", ".m4a", ".ogg", ".opus", ".wav"} else ".mp3"
    # Episode identity, rather than a referenced upload, isolates distinct recordings.
    destination = root / "media/permitted" / ((job.get("media_id") or job["job_id"]) + suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    partial = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(job["audio_url"], headers={"User-Agent": "LevinverseCorpusBuilder/0.2 (authorized publisher audio)"})
    total = 0
    with urllib.request.urlopen(request, timeout=60, context=tls_context()) as response, partial.open("wb") as stream:
        expected = int(response.headers.get("Content-Length", "0"))
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > 1024 * 1024 * 1024:
                raise ValueError("Audio enclosure exceeds the 1 GiB job limit")
            stream.write(chunk)
        if not total or (expected and expected != total):
            raise IOError("Incomplete audio enclosure download")
    partial.replace(destination)
    return destination


@contextmanager
def worker_lock(root: Path):
    path = root / ".cache/audio-worker.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if not path.stat().st_size:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("An audio worker is already running for this corpus") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def run(root: Path, limit: int = 1, model: str = "turbo") -> dict:
    with worker_lock(root):
        return run_batch(root, limit, model)


def run_batch(root: Path, limit: int, model: str) -> dict:
    permissions = json.loads((root / "config/permissions.json").read_text(encoding="utf-8"))
    if permissions.get("audio_processing_authorized") is not True or not authorization_basis(root):
        raise PermissionError("Audio processing and transcript storage must both be authorized")
    result = {"attempted": 0, "transcribed": 0, "reused": 0, "failed": 0}
    consecutive_dns_failures = 0
    worker_path = root / "reports/audio-worker.json"
    worker_path.parent.mkdir(parents=True, exist_ok=True)
    def checkpoint_worker(status="running", job_id=None):
        worker_path.write_text(json.dumps({"pid": os.getpid(), "status": status, "heartbeat_at": timestamp(), "current_job": job_id, "counts": result}, indent=2) + "\n", encoding="utf-8")
    checkpoint_worker()
    for job in read_jsonl(root / "catalog/audio-queue.jsonl"):
        if job.get("status") in {"transcribed", "covered_by_stored_transcript", "duplicate_reused", "participation_review_required"} or result["attempted"] >= limit:
            continue
        retry = job.get("retry_after")
        if retry and datetime.fromisoformat(retry) > datetime.now(timezone.utc):
            continue
        result["attempted"] += 1
        checkpoint_worker(job_id=job["job_id"])
        try:
            job.update(status="downloading", attempted_at=timestamp())
            upsert(root / "catalog/audio-queue.jsonl", [job], "job_id")
            media = download(job, root)
            job.update(status="transcribing", media_sha256=hashlib.sha256(media.read_bytes()).hexdigest())
            upsert(root / "catalog/audio-queue.jsonl", [job], "job_id")
            permission = {"permission_confirmed": True, "permission_basis": authorization_basis(root), "source_url": job["source_url"], "audio_url": job["audio_url"], "media_sha256": job["media_sha256"]}
            record_path = root / "transcripts/metadata" / ((job.get("media_id") or job["job_id"]) + "-permission.json")
            record_path.parent.mkdir(parents=True, exist_ok=True)
            record_path.write_text(json.dumps(permission, indent=2) + "\n", encoding="utf-8")
            duplicate = next((r for r in read_jsonl(root / "catalog/audio-queue.jsonl") if r.get("job_id") != job["job_id"] and r.get("status") == "transcribed" and r.get("media_sha256") == job["media_sha256"] and r.get("transcript_path") and (root / r["transcript_path"]).is_file()), None)
            print(json.dumps({"job_id": job["job_id"], "status": "reusing" if duplicate else "transcribing", "model": duplicate.get("model") if duplicate else model}), flush=True)
            output = (root / duplicate["transcript_path"]).with_suffix(".json") if duplicate else transcribe_media(media, root, permission, model)
            text_path = output.with_suffix(".txt")
            payload = json.loads(output.read_text(encoding="utf-8"))
            text = text_path.read_text(encoding="utf-8")
            job.update(status="duplicate_reused" if duplicate else "transcribed", completed_at=timestamp(), transcript_path=text_path.relative_to(root).as_posix(), model=payload["model"])
            registry = {"transcript_id": "whisper-" + job["job_id"], "source_url": job["source_url"], "audio_url": job["audio_url"], "title": job["title"], "video_ids": [job["video_id"]] if job.get("video_id") else [], "status": "stored", "text_path": job["transcript_path"], "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "word_count": len(text.split()), "segment_count": len(payload["segments"]), "transcript_quality": "local Whisper ASR; not human verified; speaker diarization not performed", "model": model, "device": "cuda", "relevance_confirmed": True, "authorization_basis": authorization_basis(root), "retrieved_at": timestamp()}
            registry["source_kind"] = "local_whisper"
            registry["model"] = payload["model"]
            registry["device"] = payload["device"]
            registry["language"] = payload["language"]
            registry["media_sha256"] = job["media_sha256"]
            registry["publisher_feed_url"] = job.get("publisher_feed_url")
            registry["episode_guid"] = job.get("episode_guid")
            if duplicate:
                registry["duplicate_of"] = "whisper-" + duplicate["job_id"]
                job["duplicate_of"] = duplicate["job_id"]
            upsert(root / "catalog/transcripts.jsonl", [registry], "transcript_id")
            if job.get("video_id"):
                merge_video(root, {"video_id": job["video_id"], "transcript_status": "local_whisper_stored", "transcript_path": job["transcript_path"], "transcript_url": job["source_url"], "audio_duration_seconds": payload["duration_seconds"], "discovery_sources": [job["source_url"]]}, True)
            else:
                upsert(root / "catalog/appearances.jsonl", [{"appearance_id": job["job_id"], "video_ids": [], "title": job["title"], "source_url": job["source_url"], "transcript_status": "local_whisper_stored", "transcript_path": job["transcript_path"], "appearance_type": "publisher_audio"}], "appearance_id")
            result["reused" if duplicate else "transcribed"] += 1
            consecutive_dns_failures = 0
        except Exception as exc:
            job.update(status="failed", reason=str(exc), retry_after=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
            result["failed"] += 1
            cause = exc.reason if isinstance(exc, urllib.error.URLError) else exc
            consecutive_dns_failures = consecutive_dns_failures + 1 if isinstance(cause, socket.gaierror) else 0
            print(json.dumps({"job_id": job["job_id"], "status": "failed", "reason": str(exc)}, ensure_ascii=True), flush=True)
        upsert(root / "catalog/audio-queue.jsonl", [job], "job_id")
        checkpoint_worker(job_id=job["job_id"])
        if consecutive_dns_failures >= 2:
            result["stopped_reason"] = "Two consecutive DNS resolution failures; remaining jobs deferred"
            break
    checkpoint_worker(status="completed")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--model", default="turbo")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.plan:
        print(json.dumps(plan(root, Fetcher(root, args.cache))), flush=True)
    if args.run:
        print(json.dumps(run(root, args.limit, args.model)), flush=True)


if __name__ == "__main__":
    main()
