"""Resolve public podcast audio with native extractors, without following YouTube embeds."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from .expand import safe_url
from .harvest import timestamp
from .publishers import queue_audio
from .store import read_jsonl, upsert


class QuietLog:
    def debug(self, *args): pass
    def warning(self, *args): pass
    def error(self, *args): pass


def youtube_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith(("youtube.com", "youtu.be", "youtube-nocookie.com"))


def resolve(source_url: str) -> dict:
    from yt_dlp import YoutubeDL
    options = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True, "socket_timeout": 20, "retries": 0, "extractor_retries": 0, "logger": QuietLog()}
    with YoutubeDL(options) as client:
        url = source_url
        for _ in range(3):
            if youtube_url(url):
                raise ValueError("YouTube embed deferred to its provider-specific queue")
            info = client.extract_info(url, download=False, process=False)
            if not info:
                raise ValueError("Extractor returned no public media metadata")
            if info.get("_type") in {"url", "url_transparent"}:
                if info.get("ie_key", "").lower() == "youtube":
                    raise ValueError("YouTube embed deferred to its provider-specific queue")
                url = info["url"]
                continue
            if info.get("_type") == "playlist":
                entries = list(info.get("entries") or [])
                if len(entries) != 1:
                    raise ValueError("Multiple recordings require episode identity review")
                info = entries[0]
            if info.get("has_drm"):
                raise ValueError("Protected media is not eligible for this public-audio worker")
            formats = info.get("formats") or [info]
            audio = [f for f in formats if f.get("url", "").startswith("http") and not youtube_url(f["url"]) and (f.get("ext") in {"mp3", "m4a", "ogg", "opus", "wav"} or re.search(r"\.(mp3|m4a|ogg|opus|wav)(?:[?#]|$)", f["url"])) and safe_url(f["url"]) == f["url"] and not f.get("has_drm")]
            if not audio:
                raise ValueError("No durable public audio enclosure identified; signed streams or access may require source review")
            selected = max(audio, key=lambda f: f.get("abr") or 0)
            return {"audio_url": selected["url"], "title": info.get("title"), "duration_seconds": info.get("duration"), "extractor": info.get("extractor_key") or info.get("extractor")}
    raise ValueError("Public media redirect depth exceeded")


def discover(root: Path, limit: int | None = None) -> dict:
    permissions = json.loads((root / "config/permissions.json").read_text(encoding="utf-8"))
    if permissions.get("audio_processing_authorized") is not True:
        raise PermissionError("Audio processing is not authorized")
    stored = {r.get("source_url", "").rstrip("/") for r in read_jsonl(root / "catalog/transcripts.jsonl") if r.get("status") == "stored"}
    queued = {r["source_url"].rstrip("/") for r in read_jsonl(root / "catalog/audio-queue.jsonl")}
    state_path = root / "catalog/audio-probes.jsonl"
    previous = {r["source_url"]: r for r in read_jsonl(state_path)}
    requests = json.loads((root / "catalog/harvest-state.json").read_text(encoding="utf-8"))
    result = {"attempted": 0, "queued": 0, "unresolved": 0}
    allowed_hosts = ("libsyn.com", "podbean.com", "spreaker.com", "acast.com", "iheart.com", "captivate.fm", "soundcloud.com", "computingup.com", "musingmind.org", "externalmedicinepodcast.com")
    for source in read_jsonl(root / "catalog/nonvideo-sources.jsonl"):
        url = source["source_url"]
        host = urlparse(url).hostname or ""
        if url.rstrip("/") in stored | queued or not any(host == h or host.endswith("." + h) for h in allowed_hosts):
            continue
        if limit is not None and result["attempted"] >= limit:
            break
        retries = [r.get("retry_after") for r in (previous.get(url, {}), requests.get(url, {})) if r.get("retry_after")]
        if retries and datetime.fromisoformat(max(retries)) > datetime.now(timezone.utc):
            continue
        result["attempted"] += 1
        event = {"source_url": url, "title": source["title"], "checked_at": timestamp()}
        try:
            media = resolve(url)
            queue_audio(root, source, media["audio_url"])
            event.update(status="public_audio_queued", **media)
            result["queued"] += 1
        except Exception as exc:
            reason = re.sub(r"https?://\S+", lambda m: safe_url(m.group(0)), str(exc))
            event.update(status="unresolved", reason=reason[-1200:], retry_after=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat())
            result["unresolved"] += 1
        upsert(state_path, [event], "source_url")
        print(json.dumps({"source_url": url, "status": event["status"]}, ensure_ascii=True), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    print(json.dumps(discover(args.root.resolve(), args.limit)), flush=True)


if __name__ == "__main__":
    main()
