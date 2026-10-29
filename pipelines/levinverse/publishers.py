"""Discover explicit transcripts and public audio on officially indexed publisher pages."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .harvest import Fetcher, authorization_basis, save_transcript, seconds, soup, timestamp
from .store import read_jsonl, upsert
from .expand import safe_url


def transcript_link(anchor, base: str) -> str | None:
    label = anchor.get_text(" ", strip=True)
    if len(label) > 80 or not re.search(r"\btranscript\b", label, re.I) or re.search(r"\ball transcripts\b", label, re.I):
        return None
    href = urljoin(base, anchor.get("href", ""))
    return safe_url(href) if href.startswith("http") else None


def extract(raw: bytes, source: dict) -> dict | None:
    doc = soup(raw)
    main = doc.select_one("article,.entry-content,main") or doc
    paragraphs = []
    # Prefer explicitly marked transcript regions over article prose.
    regions = [n for n in doc.select('[class*="transcript"],[id*="transcript"]') if len(n.get_text(" ", strip=True)) > 1500 and n.name in {"div", "section", "details", "textarea"}]
    if regions:
        region = min(regions, key=lambda n: len(n.get_text()))
        paragraphs = [p.get_text(" ", strip=True) for p in region.find_all(["p", "li"])]
        if not paragraphs:
            paragraphs = [line.strip() for line in region.get_text("\n", strip=True).splitlines() if line.strip()]
    else:
        heading = next((h for h in main.find_all(["h2", "h3", "h4"]) if h.get_text(" ", strip=True).lower() in {"transcript", "episode transcript", "full transcript", "read the transcript"}), None)
        if heading:
            for node in heading.next_siblings:
                if not getattr(node, "name", None):
                    continue
                if node.name in {"h2", "h3", "footer"}:
                    break
                if node.name in {"p", "div", "section"}:
                    paragraphs.extend(p.get_text(" ", strip=True) for p in node.find_all("p")) if node.name != "p" else paragraphs.append(node.get_text(" ", strip=True))
    if not paragraphs:
        speech = []
        started = False
        for p in main.find_all("p"):
            text = p.get_text(" ", strip=True)
            if re.match(r"^(?:[\d:.]+\s+)?(?:Sean Carroll|Michael Levin|SC|ML):", text):
                started = True
            if started:
                speech.append(text)
        if sum(bool(re.match(r"^(?:[\d:.]+\s+)?(?:Sean Carroll|Michael Levin|SC|ML):", p)) for p in speech) >= 8:
            paragraphs = speech
    if len(" ".join(paragraphs).split()) < 300:
        return None
    segments = []
    for paragraph in paragraphs:
        if not paragraph:
            continue
        label = re.match(r"^(?:[\d:.]+\s+)?(Sean Carroll|Michael Levin|SC|ML):\s*(.*)", paragraph, re.S)
        segments.append({"speaker": label.group(1) if label else None, "start_seconds": seconds(paragraph[:15]), "text": label.group(2) if label else paragraph})
    date = doc.select_one('meta[property="article:published_time"]')
    return {"source_url": source["source_url"], "title": source["title"], "publication_date": date.get("content", "")[:10] if date else None, "video_ids": [], "segments": segments, "relevance_confirmed": True, "relevance_evidence": "official Michael Levin interview/presentation index links this publisher page", "transcript_quality": "publisher transcript extracted from explicit transcript region or speaker-labelled dialogue; verify against source audio", "host": urlparse(source["source_url"]).netloc, "language": "en"}


def queue_audio(root: Path, source: dict, media_url: str):
    permission = json.loads((root / "config/permissions.json").read_text(encoding="utf-8"))
    if permission.get("audio_processing_authorized") is not True:
        return
    ident = "publisher-audio-" + hashlib.sha256(media_url.encode()).hexdigest()[:16]
    previous = next((r for r in read_jsonl(root / "catalog/audio-queue.jsonl") if r["job_id"] == ident), {})
    job = {**previous, "job_id": ident, "media_id": ident, "video_id": None, "title": source["title"], "source_url": source["source_url"], "audio_url": media_url, "authorization_basis": authorization_basis(root), "status": previous.get("status", "pending"), "queued_at": previous.get("queued_at", timestamp()), "relevance_evidence": "official Michael Levin appearance index"}
    upsert(root / "catalog/audio-queue.jsonl", [job], "job_id")


def collect(root: Path, client: Fetcher, limit: int | None = None, source_urls: list[str] | None = None):
    sources = read_jsonl(root / "catalog/nonvideo-sources.jsonl")
    if source_urls:
        sources = [source for source in sources if source["source_url"] in source_urls]
    known_records = {r.get("source_url", "").rstrip("/"): r for r in read_jsonl(root / "catalog/transcripts.jsonl") if r.get("status") == "stored"}
    known = set(known_records)
    result = {"scanned": 0, "stored": 0, "failed": 0, "audio_queued": 0, "already_stored": 0}
    for source in sources:
        url = source["source_url"]
        if url.rstrip("/") in known:
            record = known_records[url.rstrip("/")]
            upsert(root / "catalog/publisher-pages.jsonl", [{"source_url": url, "title": source["title"], "checked_at": timestamp(), "status": "stored", "transcript_id": record["transcript_id"], "transcript_path": record.get("text_path")}], "source_url")
            result["already_stored"] += 1
            continue
        if limit is not None and result["scanned"] >= limit:
            continue
        result["scanned"] += 1
        event = {"source_url": url, "title": source["title"], "checked_at": timestamp()}
        try:
            if re.search(r"\.(mp3|m4a|ogg|wav)(?:[?#]|$)", url, re.I):
                queue_audio(root, source, url)
                result["audio_queued"] += 1
                event["status"] = "public_audio_queued"
            else:
                raw = client.get(url)
                item = extract(raw, source)
                if item:
                    record = save_transcript(root, item, authorization_basis(root))
                    event.update(status=record["status"], transcript_id=record["transcript_id"])
                    result["stored"] += int(record["status"] == "stored")
                else:
                    event["status"] = "transcript_not_identified_in_html"
                    doc = soup(raw)
                    links = []
                    for anchor in doc.find_all("a", href=True):
                        clean = transcript_link(anchor, url)
                        if clean:
                            links.append(clean)
                            upsert(root / "catalog/publisher-transcript-links.jsonl", [{"link_id": hashlib.sha256((url + clean).encode()).hexdigest()[:20], "source_url": clean, "discovery_source": url, "title": source["title"], "already_stored": clean.rstrip("/") in known}], "link_id")
                    event["transcript_links"] = sorted(set(links))
                    media = []
                    for node in doc.select("audio[src],source[src],a[href]"):
                        href = urljoin(url, node.get("src") or node.get("href") or "")
                        if re.search(r"\.(mp3|m4a|ogg)(?:[?#]|$)", href, re.I) and href not in media and safe_url(href) == href:
                            media.append(href)
                    for node in doc.select('meta[name="twitter:player:stream"],meta[property="og:audio"],meta[property="og:audio:secure_url"]'):
                        href = urljoin(url, node.get("content") or "")
                        if re.search(r"\.(mp3|m4a|ogg)(?:[?#]|$)", href, re.I) and href not in media and safe_url(href) == href:
                            media.append(href)
                    # Avoid guessing among multiple recordings or ad/media assets.
                    if len(media) == 1:
                        queue_audio(root, source, media[0])
                        result["audio_queued"] += 1
                        event["status"] = "public_audio_queued"
                    event["public_audio_candidates"] = media
        except Exception as exc:
            event.update(status="request_failed", reason=str(exc))
            result["failed"] += 1
        upsert(root / "catalog/publisher-pages.jsonl", [event], "source_url")
        print(json.dumps({"source_url": url, "status": event["status"]}, ensure_ascii=True), flush=True)
    return result


def collect_pdf_links(root: Path, client: Fetcher):
    from pypdf import PdfReader
    result = {"stored": 0, "failed": 0}
    for link in read_jsonl(root / "catalog/publisher-transcript-links.jsonl"):
        if link.get("already_stored"):
            continue
        url = link["source_url"]
        download_url = url
        drive = re.match(r"https://drive\.google\.com/file/d/([\w-]+)/", url)
        if drive:
            download_url = "https://drive.google.com/uc?export=download&id=" + drive.group(1)
        elif not urlparse(url).path.lower().endswith(".pdf"):
            continue
        try:
            raw = client.get(download_url)
            if not raw.lstrip().startswith(b"%PDF"):
                raise ValueError("Public download returned a non-PDF response; sign-in or different source format may be required")
            reader = PdfReader(BytesIO(raw))
            segments = [{"page": i + 1, "start_seconds": None, "speaker": None, "text": page.extract_text() or ""} for i, page in enumerate(reader.pages)]
            if sum(len(s["text"].split()) for s in segments) < 300:
                raise ValueError("PDF has too little extractable transcript text; OCR or source review required")
            item = {"source_url": url, "discovery_source": link["discovery_source"], "title": link["title"], "publication_date": None, "video_ids": [], "segments": segments, "source_sha256": hashlib.sha256(raw).hexdigest(), "relevance_confirmed": True, "relevance_evidence": "officially indexed publisher links this PDF as the episode transcript", "transcript_quality": "publisher-linked PDF transcript; page extraction may affect line breaks; structured time and speaker fields not inferred", "host": urlparse(link["discovery_source"]).netloc, "language": "en"}
            record = save_transcript(root, item, authorization_basis(root))
            link.update(already_stored=record["status"] == "stored", status=record["status"], transcript_id=record["transcript_id"])
            result["stored"] += int(record["status"] == "stored")
        except Exception as exc:
            link.update(status="request_or_extraction_failed", reason=str(exc))
            result["failed"] += 1
        upsert(root / "catalog/publisher-transcript-links.jsonl", [link], "link_id")
        print(json.dumps({"source_url": url, "status": link["status"]}, ensure_ascii=True), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--limit", type=int)
    parser.add_argument("--linked-pdfs", action="store_true")
    parser.add_argument("--source", action="append", help="Scan only this officially indexed source URL; repeatable")
    args = parser.parse_args()
    root = args.root.resolve()
    client = Fetcher(root)
    print(json.dumps(collect_pdf_links(root, client) if args.linked_pdfs else collect(root, client, args.limit, args.source)), flush=True)


if __name__ == "__main__":
    main()
