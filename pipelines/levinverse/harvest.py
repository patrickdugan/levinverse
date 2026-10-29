"""Resumable harvesting of official indexes and publisher-hosted transcripts."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

from .discover import parse_index, youtube_id
from .store import read_jsonl, upsert

PRIMARY_INDEXES = [
    "https://www.drmichaellevin.org/presentations/audiovideo.html",
    "https://www.drmichaellevin.org/presentations/",
    "https://www.drmichaellevin.org/resources/guests.html",
]
PODCAST = "https://thoughtforms-life.aipodcast.ing/"
PUBLISHERS = [
    "https://lexfridman.com/michael-levin-2-transcript/",
    "https://tim.blog/2026/01/21/dr-michael-levin-transcript/",
]
AUTHORIZATION = "User authorized storage and repository redistribution of Michael Levin public-appearance transcripts on 2026-10-29."


def authorization_basis(root: Path) -> str | None:
    path = root / "config/permissions.json"
    if not path.exists():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    return record.get("authorization_basis") if record.get("transcript_storage_authorized") is True else None


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def seconds(label: str) -> int | None:
    value = re.search(r"\b(\d{1,2}:\d{2}(?::\d{2})?)\b", label)
    if not value:
        return None
    result = 0
    for part in value.group(1).split(":"):
        result = result * 60 + int(part)
    return result


class Fetcher:
    def __init__(self, root: Path, cache: Path | None = None, delay: float = 0.5, max_age_seconds: float = 86400):
        self.root = root
        self.cache = cache or root / ".cache/harvest"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.path = root / "catalog/harvest-state.json"
        self.state = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.delay = delay
        self.max_age_seconds = max_age_seconds
        self.blocked_hosts: set[str] = set()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def get(self, url: str) -> bytes:
        cached = self.cache / (hashlib.sha256(url.encode()).hexdigest()[:16] + ".html")
        if cached.exists() and time.time() - cached.stat().st_mtime < self.max_age_seconds:
            raw = cached.read_bytes()
            if url not in self.state:
                self.state[url] = {"status": "fetched", "checked_at": timestamp(), "cache_hit": True, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                self.save()
            return raw
        host = urlparse(url).netloc
        prior = self.state.get(url, {})
        retry = prior.get("retry_after")
        if host in self.blocked_hosts or (retry and datetime.fromisoformat(retry) > datetime.now(timezone.utc)):
            raise RuntimeError("source cooldown has not elapsed")
        time.sleep(self.delay)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "LevinverseCorpusBuilder/0.2 (public research archive)", "Accept": "text/html,application/json,application/xml"})
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read()
            temporary = cached.with_suffix(".tmp")
            temporary.write_bytes(raw)
            temporary.replace(cached)
            self.state[url] = {"status": "fetched", "checked_at": timestamp(), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            self.save()
            return raw
        except Exception as exc:
            code = getattr(exc, "code", None)
            retry = datetime.now(timezone.utc) + timedelta(hours=24 if code in (403, 429) else 1)
            self.state[url] = {"status": "failed", "checked_at": timestamp(), "reason": str(exc), "http_status": code, "retry_after": retry.isoformat()}
            if code in (403, 429):
                self.blocked_hosts.add(host)
            self.save()
            raise


def soup(raw: bytes):
    from bs4 import BeautifulSoup
    return BeautifulSoup(raw, "html.parser")


def merge_video(root: Path, record: dict, authorized: bool = False):
    existing = {v["video_id"]: v for v in read_jsonl(root / "catalog/videos.jsonl")}
    old = existing.get(record["video_id"], {})
    merged = dict(old)
    for key, value in record.items():
        if key == "duration_seconds" and old.get("flat_metadata_retrieved_at") and not record.get("flat_metadata_retrieved_at"):
            if value is not None:
                merged["index_duration_seconds"] = value
            continue
        if value not in (None, "", [], "unknown") or key not in merged:
            merged[key] = value
    merged["discovery_sources"] = sorted(set(old.get("discovery_sources", []) + record.get("discovery_sources", [])))
    if authorized:
        merged["caption_storage_authorized"] = True
        merged["caption_authorization_basis"] = AUTHORIZATION
    upsert(root / "catalog/videos.jsonl", [merged], "video_id")
    appearance = {"appearance_id": merged["video_id"], "video_ids": [merged["video_id"]], "title": merged.get("title"), "publication_date": merged.get("publication_date"), "event_date": merged.get("event_date"), "source_url": merged.get("canonical_url"), "host": merged.get("host"), "appearance_type": "unknown"}
    upsert(root / "catalog/appearances.jsonl", [appearance], "appearance_id")


def index_records(raw: bytes, url: str) -> list[dict]:
    records = {r["video_id"]: r for r in parse_index(raw, url, timestamp())}
    doc = soup(raw)
    main = doc.select_one("main, #content, .content") or doc
    # Embedded conversations are outside list items on the official guests page.
    for node in main.find_all(["iframe", "a"]):
        vid = youtube_id(node.get("src") or node.get("href") or "")
        if not vid or vid in records:
            continue
        context = node.get("title") or node.get_text(" ", strip=True)
        if not context:
            heading = node.find_previous(["h2", "h3", "h4"])
            context = heading.get_text(" ", strip=True) if heading else "Officially indexed conversation"
        records[vid] = {"video_id": vid, "canonical_url": f"https://www.youtube.com/watch?v={vid}", "title": context, "publication_date": None, "duration_seconds": None, "discovery_sources": [url], "retrieved_at": timestamp(), "transcript_status": "unknown", "role": "unknown", "participation_evidence": "official Michael Levin appearance index"}
    return list(records.values())


def index_other_links(root: Path, raw: bytes, url: str):
    candidates, documents = [], []
    for li in soup(raw).find_all("li"):
        context = li.get_text(" ", strip=True)
        if not re.search(r"\d+\s*(?:hours?|minutes?)", context, re.I):
            continue
        for anchor in li.find_all("a", href=True):
            href = urljoin(url, anchor["href"])
            if youtube_id(href) or not href.startswith(("https://", "http://")):
                continue
            ident = "source-" + hashlib.sha256(href.encode()).hexdigest()[:16]
            row = {"source_id": ident, "source_url": href, "title": anchor.get_text(" ", strip=True) or context, "discovery_source": url, "source_context": context, "retrieved_at": timestamp()}
            if re.search(r"\.(?:pdf|pptx?|docx?)(?:[?#]|$)", href, re.I):
                documents.append({**row, "document_id": ident})
            else:
                candidates.append(row)
    upsert(root / "catalog/nonvideo-sources.jsonl", candidates, "source_id")
    upsert(root / "catalog/related-documents.jsonl", documents, "document_id")


def parse_podcast(raw: bytes, url: str) -> dict | None:
    doc = soup(raw)
    metadata = None
    for node in doc.select('script[type="application/ld+json"]'):
        try:
            item = json.loads(node.get_text())
            if item.get("@type") == "PodcastEpisode":
                metadata = item
                break
        except (ValueError, AttributeError):
            continue
    if not metadata:
        return None
    article = doc.select_one("article")
    if article is None:
        return None
    header = article.find("header")
    tags = [a.get_text(" ", strip=True) for a in header.find_all("a") if "/tag/" in a.get("href", "")] if header else []
    title = metadata.get("name") or article.find("h1").get_text(" ", strip=True)
    relevance = any("michael levin" in t.lower() or "conversations and working" in t.lower() for t in tags)
    relevance = relevance or bool(re.search(r"\b(?:Michael|Mike) Levin\b", title, re.I))
    heading = next((h for h in article.find_all(["h2", "h3"]) if h.get_text(" ", strip=True).casefold() == "transcript"), None)
    segments = []
    quality = None
    if heading:
        for node in heading.next_siblings:
            if not getattr(node, "name", None):
                continue
            if node.name == "footer":
                break
            if node.name != "p":
                continue
            text = node.get_text(" ", strip=True)
            if "transcript is automatically generated" in text.lower():
                quality = text
                continue
            if not text:
                continue
            anchor = node.find("a", href=re.compile(r"(?:youtu|youtube)"))
            start = seconds(anchor.get_text()) if anchor else None
            speaker = re.match(r"^(?:\[[\d:]+\]\s*)?([^:]{2,50}):\s", text)
            segments.append({"start_seconds": start, "speaker": speaker.group(1) if speaker else None, "text": text})
    ids = []
    for node in article.find_all(["iframe", "a"]):
        value = youtube_id(node.get("src") or node.get("href") or "")
        if value and value not in ids:
            ids.append(value)
    timestamp_ids = Counter(youtube_id(a.get("href", "")) for a in article.find_all("a") if re.search(r"[?&]t=", a.get("href", "")) and youtube_id(a.get("href", "")))
    main_ids = [timestamp_ids.most_common(1)[0][0]] if timestamp_ids else ids[:1]
    related_ids = [vid for vid in ids if vid not in main_ids]
    return {"source_url": url, "title": title, "publication_date": (metadata.get("datePublished") or "")[:10] or None, "video_ids": main_ids, "related_video_ids": related_ids, "segments": segments, "relevance_confirmed": relevance, "relevance_evidence": "official podcast category: " + ", ".join(tags) if relevance else "guest-only or unclassified episode; participation review required", "tags": tags, "transcript_quality": quality or "publisher transcript; method unspecified", "host": "Thoughtforms Life Podcast", "language": "en"}


def parse_publisher(raw: bytes, url: str) -> dict:
    doc = soup(raw)
    article = doc.select_one(".entry-content") or doc.select_one("article")
    title = (doc.select_one("article h1") or doc.find("h1")).get_text(" ", strip=True)
    segments = []
    if "lexfridman.com" in url:
        for node in article.select(".ts-segment"):
            speaker = node.select_one(".ts-name")
            stamp = node.select_one(".ts-timestamp")
            text = node.select_one(".ts-text")
            if text:
                segments.append({"speaker": speaker.get_text(strip=True) if speaker else None, "start_seconds": seconds(stamp.get_text()) if stamp else None, "text": text.get_text(" ", strip=True)})
    elif "tim.blog" in url:
        started = False
        speaker = None
        for node in article.find_all(["p", "h3"]):
            if node.name == "h3" and "legal-conditions" in node.get("id", ""):
                break
            text = node.get_text(" ", strip=True)
            match = re.match(r"^(Tim Ferriss|Michael Levin):\s*(.*)", text, re.S)
            if match:
                started = True
                speaker, text = match.groups()
            if started and text:
                segments.append({"speaker": speaker, "start_seconds": None, "text": text})
    ids = list(dict.fromkeys(v for node in article.find_all(["a", "iframe"]) if (v := youtube_id(node.get("href") or node.get("src") or ""))))
    date = doc.select_one('meta[property="article:published_time"]')
    return {"source_url": url, "title": title, "publication_date": date.get("content", "")[:10] if date else None, "video_ids": ids[:1], "segments": segments, "relevance_confirmed": True, "relevance_evidence": "publisher identifies Michael Levin as interview guest", "transcript_quality": "human generated" if "lexfridman" in url else "publisher transcript", "host": urlparse(url).netloc, "language": "en"}


def save_transcript(root: Path, item: dict, authorization: str | None) -> dict:
    source = item["source_url"]
    known = read_jsonl(root / "catalog/videos.jsonl")
    indexed = [v for v in known if v["video_id"] in item["video_ids"] and any("drmichaellevin.org/" in s for s in v.get("discovery_sources", []))]
    if indexed and not item["relevance_confirmed"]:
        item["relevance_confirmed"] = True
        item["relevance_evidence"] = "video appears in an official Michael Levin appearance index"
    if not item["video_ids"] and "tim.blog" in source:
        item["video_ids"] = [v["video_id"] for v in known if "tim ferriss" in (v.get("host") or "").lower() and v.get("publication_date") == item.get("publication_date")]
    ident = "publisher-" + hashlib.sha256(source.encode()).hexdigest()[:16]
    record = {k: v for k, v in item.items() if k != "segments"}
    record.update(transcript_id=ident, retrieved_at=timestamp(), status="available_metadata_only", source_kind="publisher_hosted")
    if not item["relevance_confirmed"]:
        record.update(status="participation_review_required")
    elif not item["segments"]:
        record.update(status="no_publisher_transcript", reason="No transcript paragraphs were present in the source HTML")
    elif authorization:
        text = "\n\n".join((f"{s['speaker']}: " if s.get("speaker") else "") + s["text"] for s in item["segments"]) + "\n"
        digest = hashlib.sha256(text.encode()).hexdigest()
        duplicates = [t for t in read_jsonl(root / "catalog/transcripts.jsonl") if t.get("text_sha256") == digest and t.get("transcript_id") != ident]
        text_path = Path(duplicates[0]["text_path"]) if duplicates else Path("transcripts/permitted") / f"{ident}.txt"
        if not duplicates:
            (root / text_path).parent.mkdir(parents=True, exist_ok=True)
            (root / text_path).write_text(text, encoding="utf-8")
            payload = {**record, "status": "stored", "authorization_basis": authorization, "segments": item["segments"], "text_path": text_path.as_posix(), "text_sha256": digest, "word_count": len(text.split()), "segment_count": len(item["segments"])}
            (root / text_path.with_suffix(".json")).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        record.update(status="stored", text_path=text_path.as_posix(), text_sha256=digest, word_count=len(text.split()), segment_count=len(item["segments"]), authorization_basis=authorization)
        if duplicates:
            record["duplicate_of"] = duplicates[0]["transcript_id"]
    upsert(root / "catalog/transcripts.jsonl", [record], "transcript_id")
    if item["relevance_confirmed"] and not item["video_ids"]:
        upsert(root / "catalog/appearances.jsonl", [{"appearance_id": ident, "video_ids": [], "title": item["title"], "source_url": source, "publication_date": item.get("publication_date"), "appearance_type": "publisher_hosted_interview", "transcript_status": record["status"], "transcript_path": record.get("text_path")}], "appearance_id")
    for vid in item["video_ids"] if item["relevance_confirmed"] else []:
        video = {"video_id": vid, "canonical_url": f"https://www.youtube.com/watch?v={vid}", "title": item["title"], "publication_date": None, "publisher_publication_date": item.get("publication_date"), "duration_seconds": None, "role": "unknown", "discovery_sources": [source], "host": item.get("host"), "transcript_url": source, "transcript_status": "publisher_transcript_stored" if record["status"] == "stored" else record["status"], "transcript_language": "en", "participation_evidence": item["relevance_evidence"]}
        if record.get("text_path"):
            video["transcript_path"] = record["text_path"]
        # The publisher page date is recorded separately; do not replace a known upload date.
        prior = next((v for v in read_jsonl(root / "catalog/videos.jsonl") if v["video_id"] == vid), {})
        if prior.get("publication_date"):
            video["publication_date"] = prior["publication_date"]
        merge_video(root, video, bool(authorization))
    return record


def sitemap_urls(client: Fetcher, url: str) -> list[str]:
    document = ET.fromstring(client.get(url))
    urls = [node.text for node in document.iter() if node.tag.endswith("loc") and node.text]
    if document.tag.endswith("sitemapindex"):
        return [entry for child in urls for entry in sitemap_urls(client, child)]
    return urls


def harvest(root: Path, cache: Path | None = None, limit: int | None = None, store: bool = False, delay: float = 0.5):
    client = Fetcher(root, cache, delay)
    authorization = None
    permissions = root / "config/permissions.json"
    if store and permissions.exists():
        config = json.loads(permissions.read_text(encoding="utf-8"))
        if config.get("transcript_storage_authorized") is True:
            authorization = config.get("authorization_basis")
    for url in PRIMARY_INDEXES:
        try:
            raw = client.get(url)
            records = index_records(raw, url)
            index_other_links(root, raw, url)
            for record in records:
                merge_video(root, record, bool(authorization))
            print(json.dumps({"index": url, "video_ids": len(records)}), flush=True)
        except Exception as exc:
            print(json.dumps({"index": url, "error": str(exc)}), flush=True)
    urls = sitemap_urls(client, urljoin(PODCAST, "sitemap-index.xml"))
    urls = [u for u in urls if urlparse(u).path.strip("/") and not urlparse(u).path.startswith(("/tag/", "/episodes", "/about"))]
    if limit is not None:
        urls = urls[:limit]
    for number, url in enumerate(urls + PUBLISHERS, 1):
        try:
            item = parse_podcast(client.get(url), url) if url.startswith(PODCAST) else parse_publisher(client.get(url), url)
            if item:
                record = save_transcript(root, item, authorization)
                print(json.dumps({"n": number, "total": len(urls) + len(PUBLISHERS), "url": url, "status": record["status"], "words": record.get("word_count", 0)}, ensure_ascii=True), flush=True)
        except Exception as exc:
            upsert(root / "catalog/harvest-errors.jsonl", [{"url": url, "attempted_at": timestamp(), "reason": str(exc)}], "url")
            print(json.dumps({"url": url, "error": str(exc)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--store-transcripts", action="store_true")
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()
    harvest(args.root.resolve(), args.cache.resolve() if args.cache else None, args.limit, args.store_transcripts, args.delay)


if __name__ == "__main__":
    main()
