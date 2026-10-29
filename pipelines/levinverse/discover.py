from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

from .store import read_jsonl, upsert

VIDEO_RE = re.compile(r"(?:youtube(?:-nocookie)?\.com/(?:watch\?v=|embed/|shorts/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})")
DATE_RE = re.compile(r"\b(Jan(?:uary)?|Feb(?:ruary|raury)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s*(\d{1,2}),\s*(\d{4})\b", re.I)


def youtube_id(url: str) -> str | None:
    match = VIDEO_RE.search(url)
    if match:
        return match.group(1)
    parsed = urlparse(url)
    if parsed.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        value = parse_qs(parsed.query).get("v", [None])[0]
        if value and re.fullmatch(r"[\w-]{11}", value):
            return value
    return None


def yt_dlp_metadata(url: str, timeout: int = 90) -> dict[str, Any]:
    """Read one YouTube item's public metadata without downloading media."""
    executable = shutil.which("yt-dlp")
    if executable:
        command = [executable]
    else:
        from importlib.util import find_spec
        if find_spec("yt_dlp") is None:
            raise FileNotFoundError("yt-dlp is not installed; install the 'collector' extra")
        command = [sys.executable, "-m", "yt_dlp"]
    runtime = os.getenv("LEVINVERSE_JS_RUNTIME")
    if runtime:
        command += ["--js-runtimes", runtime]
    result = subprocess.run(
        [*command, "--dump-single-json", "--skip-download", "--no-warnings", "--no-playlist", url],
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip()[-1200:])
    metadata = json.loads(result.stdout)
    upload_date = metadata.get("upload_date")
    if isinstance(upload_date, str) and re.fullmatch(r"\d{8}", upload_date):
        upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
    return {
        "video_id": metadata.get("id"),
        "canonical_url": metadata.get("webpage_url") or url,
        "title": metadata.get("title"),
        "publication_date": upload_date,
        "duration_seconds": metadata.get("duration"),
        "host": metadata.get("channel") or metadata.get("uploader"),
        "channel": metadata.get("channel"),
        "language": metadata.get("language"),
        "availability": metadata.get("availability"),
        "subtitles": sorted((metadata.get("subtitles") or {}).keys()),
        "automatic_captions": sorted((metadata.get("automatic_captions") or {}).keys()),
    }


def fetch(url: str, attempts: int = 3) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": os.getenv("LEVINVERSE_USER_AGENT", "LevinverseCorpusBuilder/0.1 (research metadata; contact: repository maintainer)"), "Accept": "text/html"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError):
            if attempt + 1 == attempts:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


class _IndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[tuple[list[tuple[str, str]], str]] = []
        self._li_depth = 0
        self._item_links: list[tuple[str, str]] = []
        self._item_text: list[str] = []
        self._active_href: str | None = None
        self._active_text: list[str] = []
        self._global_links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        if tag == "li":
            self._li_depth += 1
            if self._li_depth == 1:
                self._item_links, self._item_text = [], []
        if tag == "a" and attrs_map.get("href"):
            self._active_href = str(attrs_map["href"])
            self._active_text = []
        if tag == "iframe" and attrs_map.get("src"):
            self._global_links.append((str(attrs_map["src"]), str(attrs_map.get("title") or "Embedded official presentation")))

    def handle_data(self, data: str) -> None:
        if self._li_depth:
            self._item_text.append(data)
        if self._active_href is not None:
            self._active_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._active_href is not None:
            item = (self._active_href, " ".join(" ".join(self._active_text).split()))
            self._global_links.append(item)
            if self._li_depth:
                self._item_links.append(item)
            self._active_href = None
            self._active_text = []
        if tag == "li" and self._li_depth:
            self._li_depth -= 1
            if self._li_depth == 0:
                self.items.append((self._item_links, " ".join(" ".join(self._item_text).split())))


def parse_index(html: bytes, source_url: str, retrieved_at: str, include_terms: list[str] | None = None) -> list[dict[str, Any]]:
    parser = _IndexParser()
    parser.feed(html.decode("utf-8", errors="replace"))
    results: dict[str, dict[str, Any]] = {}
    pairs = [(href, title, context) for links, context in parser.items for href, title in links]
    listed = {href for href, _, _ in pairs}
    pairs.extend((href, title, title) for href, title in parser._global_links if href not in listed)
    for href, anchor_title, context in pairs:
        vid = youtube_id(href)
        if not vid:
            continue
        title = anchor_title or context[:200]
        if include_terms and not any(term.casefold() in context.casefold() for term in include_terms):
            continue
        date_match = DATE_RE.search(context)
        publication_date = None
        if date_match:
            month = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(date_match.group(1)[:3].lower()) + 1
            publication_date = datetime(int(date_match.group(3)), month, int(date_match.group(2))).date().isoformat()
        duration = re.search(r"\([^)]*\d+\s*(?:hours?|minutes?)[^)]*\)", context, re.I)
        hours = re.search(r"(\d+)\s*hours?", duration.group(0), re.I) if duration else None
        minutes = re.search(r"(\d+)\s*minutes?", duration.group(0), re.I) if duration else None
        duration_minutes = (int(hours.group(1)) if hours else 0) * 60 + (int(minutes.group(1)) if minutes else 0) if duration else None
        host_match = re.search(r"\(([^()|]+)\s*\|\s*[^)]+\)", context, re.I)
        role = "excerpt" if re.search(r"\bexcerpt\b", context, re.I) else "dub" if re.search(r"dubbed\b", context, re.I) else "unknown"
        results[vid] = {
            "video_id": vid,
            "canonical_url": f"https://www.youtube.com/watch?v={vid}",
            "title": title,
            "publication_date": publication_date,
            "duration_seconds": duration_minutes * 60 if duration_minutes is not None else None,
            "host": host_match.group(1).strip() if host_match else None,
            "channel": None,
            "event_date": None,
            "role": role,
            "transcript_status": "unknown",
            "transcript_language": None,
            "transcript_url": None,
            "topics": [],
            "related_publications": [],
            "discovery_sources": [source_url],
            "retrieved_at": retrieved_at,
            "source_context": context[:500],
        }
    return list(results.values())


def discover(root: Path, source_url: str | None = None, limit: int | None = None, enrich_metadata: bool = False) -> tuple[int, int]:
    if source_url:
        sources = [{"url": source_url, "include_terms": None}]
    else:
        config = json.loads((root / "config/sources.yaml").read_text(encoding="utf-8"))
        sources = [s for s in config["sources"] if s.get("enabled")]
    videos_path = root / "catalog/videos.jsonl"
    existing = {row["video_id"]: row for row in read_jsonl(videos_path)}
    found: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    state_path = root / "catalog/source_state.json"
    source_states = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    for source in sources:
        if limit is not None and len(found) >= limit:
            break
        url = source["url"]
        timestamp = datetime.now(timezone.utc).isoformat()
        previous_state = source_states.get(url, {})
        retry_after = previous_state.get("retry_after")
        if retry_after and datetime.fromisoformat(retry_after) > datetime.now(timezone.utc):
            continue
        try:
            page = fetch(url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            failures = int(previous_state.get("failures", 0)) + 1
            backoff_hours = min(2 ** (failures - 1), 24 * 7)
            source_states[url] = {"status": "failed", "failures": failures, "last_checked": timestamp, "retry_after": (datetime.now(timezone.utc) + timedelta(hours=backoff_hours)).isoformat(), "error": str(exc)[-800:]}
            event_id = hashlib.sha256(f"source-failure:{url}:{failures}".encode()).hexdigest()[:20]
            events.append({"event_id": event_id, "event": "source_fetch_failed", "source_url": url, "timestamp": timestamp, "status": "failed", "retry_after": source_states[url]["retry_after"], "reason": str(exc)[-800:]})
            continue
        source_states[url] = {"status": "succeeded", "failures": 0, "last_checked": timestamp, "last_success": timestamp, "retry_after": None}
        for record in parse_index(page, url, timestamp, source.get("include_terms")):
            if limit is not None and len(found) >= limit:
                break
            prior = existing.get(record["video_id"])
            if prior:
                for field in ("title", "publication_date", "duration_seconds", "role", "source_context"):
                    if record.get(field) is None or record.get(field) == "unknown":
                        record[field] = prior.get(field)
                record["discovery_sources"] = sorted(set(record["discovery_sources"] + prior.get("discovery_sources", [])))
                for field in ("host", "channel", "event_date", "transcript_status", "transcript_language", "transcript_url", "topics", "related_publications"):
                    if prior.get(field) not in (None, [], "unknown"):
                        record[field] = prior[field]
                record = {**prior, **record}
            if enrich_metadata:
                try:
                    last_error: Exception | None = None
                    for attempt in range(3):
                        try:
                            detail = yt_dlp_metadata(record["canonical_url"])
                            last_error = None
                            break
                        except (FileNotFoundError, RuntimeError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                            last_error = exc
                            if isinstance(exc, FileNotFoundError) or attempt == 2:
                                break
                            time.sleep(2 ** attempt)
                    if last_error is not None:
                        raise last_error
                    for field in ("canonical_url", "title", "publication_date", "duration_seconds", "host", "channel"):
                        if detail.get(field) is not None:
                            record[field] = detail[field]
                    record["caption_languages"] = {"manual": detail["subtitles"], "automatic": detail["automatic_captions"]}
                    has_en = any(lang == "en" or lang.startswith("en-") or lang.startswith("en_") for lang in detail["subtitles"] + detail["automatic_captions"])
                    record["transcript_status"] = "available_metadata_only" if has_en else "unavailable"
                    record["transcript_language"] = "en" if has_en else None
                    record["metadata_status"] = "retrieved"
                except (FileNotFoundError, RuntimeError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                    record["metadata_status"] = "blocked" if isinstance(exc, FileNotFoundError) else "failed"
                    record["metadata_error"] = str(exc)[-1200:]
                time.sleep(1)
                metadata_event_id = hashlib.sha256(f"metadata:{url}:{record['video_id']}:{record.get('metadata_status')}".encode()).hexdigest()[:20]
                events.append({"event_id": metadata_event_id, "event": "metadata_checked", "video_id": record["video_id"], "source_url": record["canonical_url"], "status": record.get("metadata_status"), "timestamp": timestamp, "reason": record.get("metadata_error")})
            found.append(record)
            event_id = hashlib.sha256(f"discover:{url}:{record['video_id']}".encode()).hexdigest()[:20]
            events.append({"event_id": event_id, "event": "discovered", "video_id": record["video_id"], "source_url": url, "timestamp": timestamp})
    if limit is not None:
        found = found[:limit]
    previous_ids = set(existing)
    upsert(videos_path, found, "video_id")
    appearances = []
    for video in found:
        appearances.append({"appearance_id": video["video_id"], "video_ids": [video["video_id"]], "title": video["title"], "event_date": video.get("event_date"), "publication_date": video.get("publication_date"), "host": video.get("host"), "channel": video.get("channel"), "appearance_type": "unknown", "source_url": video["canonical_url"]})
    upsert(root / "catalog/appearances.jsonl", appearances, "appearance_id")
    upsert(root / "catalog/provenance.jsonl", events, "event_id")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(source_states, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(found), sum(v["video_id"] not in previous_ids for v in found)
