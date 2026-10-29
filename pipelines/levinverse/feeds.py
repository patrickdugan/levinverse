"""Collect explicitly named Levin episodes from configured public publisher RSS feeds."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from pathlib import Path
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, quote, urlencode, urlparse
from xml.etree import ElementTree as ET

from .discover import VIDEO_RE, youtube_id
from .expand import safe_url
from .harvest import Fetcher, authorization_basis, merge_video, save_transcript, timestamp
from .store import read_jsonl, upsert


def commentary_title(title: str) -> bool:
    return bool(re.search(r"\b(?:reaction|reacting|review|analysis|summary|critique)\b.{0,80}\b(?:Michael|Mike) Levin\b|\b(?:Michael|Mike) Levin['’]s\b", title, re.I))


def match_video(title: str, references: list[str], known: dict, allow_single_reference: bool = True) -> str | None:
    stop = {"michael", "mike", "levin", "the", "of", "and", "with", "on", "a", "is", "what", "how", "why", "podcast", "dr", "prof"}
    words = lambda text: set(re.findall(r"[a-z0-9]+", text.lower())) - stop
    target = words(title)
    matches = []
    for ident in references:
        if ident not in known:
            continue
        other = words(known[ident].get("metadata_video_title") or known[ident].get("title", ""))
        common = len(target & other)
        if common >= 3 and common / max(1, len(target | other)) >= 0.45:
            matches.append(ident)
    return matches[0] if len(matches) == 1 else references[0] if allow_single_reference and len(references) == 1 and references[0] in known else None


def publisher_title_match(title: str, show: str, known: dict) -> str | None:
    def words(value):
        return set(re.findall(r"[a-z0-9]+", value.casefold())) - {"podcast", "the", "with", "interview"}
    publisher = words(show)
    candidates = [ident for ident, record in known.items() if publisher and publisher.issubset(words(record.get("host") or ""))]
    return match_video(title, candidates, known, allow_single_reference=False)


def stored_episode(title: str, source: str, audio: str, feed: dict, records: list[dict]) -> dict | None:
    def source_key(url):
        parsed = urlparse(url)
        query = sorted((key, value) for key, value in parse_qsl(parsed.query) if not key.startswith("utm_") and key not in {"si", "fbclid", "gclid"})
        return ((parsed.hostname or "").removeprefix("www."), parsed.path.rstrip("/"), urlencode(query), parsed.fragment)
    def words(value):
        return {word for word in re.findall(r"[a-z0-9]+", value.casefold()) if not word.isdigit()} - {"transcript", "transcripts", "for", "the", "show", "podcast", "dr", "michael", "mike", "levin", "and", "with", "on"}
    target = words(title)
    matches = []
    for record in records:
        if source_key(source) == source_key(record["source_url"]) or (audio and audio == record.get("audio_url")):
            return record
        domain = source_key(record["source_url"])[0]
        if domain not in feed.get("transcript_publisher_domains", []):
            continue
        other = words(record.get("title", ""))
        if len(target & other) >= 4 and len(target & other) / max(1, len(target | other)) >= 0.8:
            matches.append(record)
    return matches[0] if len(matches) == 1 else None


def episode_source(feed_url: str, guid: str, link: str | None) -> str:
    generic_pages = {"", "/", "/theoriesofeverything", "/podcast", "/episodes", "/show"}
    if link and urlparse(link).path.rstrip("/").casefold() not in generic_pages:
        return safe_url(link)
    return feed_url + "#episode=" + quote(guid, safe="")


def parse_srt(raw: bytes) -> list[dict]:
    segments = []
    def clock(value):
        result = 0.0
        for part in value.replace(",", ".").split(":"):
            result = result * 60 + float(part)
        return result
    for block in re.split(r"\r?\n\s*\r?\n", raw.decode("utf-8-sig")):
        lines = block.splitlines()
        match = next(((i, re.search(r"([\d:,.]+)\s+-->\s+([\d:,.]+)", line)) for i, line in enumerate(lines) if "-->" in line), None)
        if not match or not match[1]:
            continue
        index, timing = match
        text = html.unescape(re.sub(r"<[^>]+>", "", " ".join(lines[index + 1:]))).strip()
        if text:
            segments.append({"start_seconds": clock(timing.group(1)), "end_seconds": clock(timing.group(2)), "speaker": None, "text": text})
    if not segments:
        raise ValueError("Publisher caption track contains no timed cues")
    return segments


def episode_duration(item) -> float | None:
    value = next((n.text for n in item if n.tag.rsplit("}", 1)[-1] == "duration"), None)
    if not value:
        return None
    try:
        result = 0.0
        for part in value.strip().split(":"):
            result = result * 60 + float(part)
        return result if result >= 0 else None
    except ValueError:
        return None


def collect(root: Path, client: Fetcher, limit: int | None = None, feed_urls: list[str] | None = None):
    permissions = json.loads((root / "config/permissions.json").read_text(encoding="utf-8"))
    if permissions.get("audio_processing_authorized") is not True or not authorization_basis(root):
        raise PermissionError("Feed collection requires processing and transcript storage authorization")
    feeds = json.loads((root / "config/podcast-feeds.json").read_text(encoding="utf-8"))["feeds"]
    if feed_urls:
        feeds = [feed for feed in feeds if feed["url"] in feed_urls]
    known = {v["video_id"]: v for v in read_jsonl(root / "catalog/videos.jsonl")}
    stored_records = [r for r in read_jsonl(root / "catalog/transcripts.jsonl") if r.get("status") == "stored" and (root / r.get("text_path", "MISSING")).is_file()]
    existing_sources = {r["source_url"]: r for r in stored_records}
    existing_jobs = {j["job_id"]: j for j in read_jsonl(root / "catalog/audio-queue.jsonl")}
    result = {"matched_episodes": 0, "captions_stored": 0, "audio_queued": 0, "already_covered": 0, "errors": 0}
    for feed in feeds:
        try:
            document = ET.fromstring(client.get(feed["url"]))
        except Exception as exc:
            result["errors"] += 1
            print(json.dumps({"feed_url": feed["url"], "error": str(exc)}), flush=True)
            continue
        items = document.findall("./channel/item")
        for item in items:
            title = item.findtext("title") or ""
            if commentary_title(title):
                guid = item.findtext("guid") or item.findtext("link") or title
                ident = "rss-" + hashlib.sha256((feed["url"] + guid).encode()).hexdigest()[:16]
                event = {"episode_id": ident, "episode_guid": guid, "title": title, "show": feed["show"], "feed_url": feed["url"], "source_url": episode_source(feed["url"], guid, item.findtext("link")), "status": "participation_review_required", "reason": "Commentary title does not establish Levin's participation", "retrieved_at": timestamp()}
                upsert(root / "catalog/rss-episodes.jsonl", [event], "episode_id")
                continue
            explicitly_named = re.search(r"\b(?:Michael|Mike) Levin\b", title, re.I)
            verified_title = any(term.casefold() in title.casefold() for term in feed.get("confirmed_title_contains", []))
            reviewed_evidence = feed.get("reviewed_episode_guids", {}).get(item.findtext("guid") or "")
            if not explicitly_named and not verified_title and not reviewed_evidence:
                continue
            if limit is not None and result["captions_stored"] + result["audio_queued"] >= limit:
                return result
            enclosure = item.find("enclosure")
            if enclosure is None:
                continue
            result["matched_episodes"] += 1
            guid = item.findtext("guid") or enclosure.get("url", "")
            reviewed_evidence = feed.get("reviewed_episode_guids", {}).get(guid)
            ident = "rss-" + hashlib.sha256((feed["url"] + guid).encode()).hexdigest()[:16]
            source = episode_source(feed["url"], guid, item.findtext("link"))
            description = (item.findtext("description") or "") + " " + next((n.text or "" for n in item if n.tag.endswith("encoded")), "")
            refs = list(dict.fromkeys(VIDEO_RE.findall(description)))
            # Multiple links often include related talks; do not assign their transcripts to every ID.
            video_id = match_video(title, refs, known)
            if not refs:
                video_id = publisher_title_match(title, feed["show"], known)
            publication = item.findtext("pubDate")
            try:
                publication_iso = parsedate_to_datetime(publication).isoformat() if publication else None
            except (TypeError, ValueError):
                publication_iso = None
            event = {"episode_id": ident, "source_url": source, "episode_guid": guid, "title": title, "show": feed["show"], "feed_url": feed["url"], "source_publication_date": publication, "source_publication_date_iso": publication_iso, "duration_seconds": episode_duration(item), "referenced_video_ids": refs, "confirmed_video_id": video_id, "retrieved_at": timestamp()}
            if reviewed_evidence:
                event["subject_review_evidence"] = reviewed_evidence
            if not video_id and not reviewed_evidence and not (verified_title and feed.get("participation_evidence_urls")) and not re.search(r"\b(Tufts|drmichaellevin|thoughtforms|bioelectric\w*|xenobot\w*|anthrobot\w*|morphogen\w*|regenerat\w*|cellular|biolog\w*)\b", title + " " + description, re.I):
                event["status"] = "subject_identity_review_required"
                upsert(root / "catalog/rss-episodes.jsonl", [event], "episode_id")
                continue
            direct_video = youtube_id(item.findtext("link") or "")
            if direct_video:
                video_id = direct_video
                event["confirmed_video_id"] = video_id
                if video_id not in known:
                    merge_video(root, {"video_id": video_id, "canonical_url": f"https://www.youtube.com/watch?v={video_id}", "title": title, "host": feed["show"], "publication_date": None, "publisher_publication_date": publication_iso, "duration_seconds": None, "publisher_duration_seconds": event["duration_seconds"], "discovery_sources": [feed["url"], source], "participation_evidence": "confirmed biologist episode; publisher RSS links directly to this video", "transcript_status": "unknown"}, True)
                    known[video_id] = {"title": title, "host": feed["show"]}
            covered_record = stored_episode(title, source, enclosure.get("url", ""), feed, stored_records)
            covered = covered_record or source in existing_sources or (video_id and known[video_id].get("transcript_path") and (root / known[video_id]["transcript_path"]).is_file())
            if covered:
                event["status"] = "covered_by_stored_transcript"
                if covered_record:
                    event.update(transcript_path=covered_record["text_path"], stored_transcript_id=covered_record["transcript_id"])
                    if ident in existing_jobs and existing_jobs[ident].get("status") in {"pending", "failed", "covered_by_stored_transcript"}:
                        upsert(root / "catalog/audio-queue.jsonl", [{**existing_jobs[ident], "status": "covered_by_stored_transcript", "transcript_path": covered_record["text_path"], "completed_at": timestamp()}], "job_id")
                result["already_covered"] += 1
                upsert(root / "catalog/rss-episodes.jsonl", [event], "episode_id")
                continue
            tracks = [n for n in item if n.tag.endswith("transcript") and n.get("url")]
            stored = False
            for track in tracks:
                if track.get("type") not in {"application/x-subrip", "text/srt", "text/vtt"}:
                    continue
                try:
                    raw = client.get(track.get("url"))
                    segments = parse_srt(raw)
                    raw_path = Path("transcripts/permitted") / (ident + ".srt")
                    (root / raw_path).parent.mkdir(parents=True, exist_ok=True)
                    (root / raw_path).write_bytes(raw)
                    relevance_evidence = reviewed_evidence.get("basis") if reviewed_evidence else ("configured episode title verified against the official appearance index" if verified_title else "publisher RSS episode explicitly identifies Michael Levin")
                    payload = {"source_url": source, "transcript_track_url": track.get("url"), "raw_transcript_path": raw_path.as_posix(), "source_kind": "platform_caption", "title": title, "publication_date": None, "video_ids": [video_id] if video_id else [], "segments": segments, "relevance_confirmed": True, "relevance_evidence": relevance_evidence, "transcript_quality": "publisher RSS-supplied caption track; speaker identity not inferred", "host": feed["show"], "language": track.get("language") or document.findtext("./channel/language"), "episode_guid": guid, "publisher_feed_url": feed["url"]}
                    record = save_transcript(root, payload, authorization_basis(root))
                    stored = record["status"] == "stored"
                    event.update(status=record["status"], transcript_path=record.get("text_path"))
                    result["captions_stored"] += int(stored)
                    if stored and ident in existing_jobs and existing_jobs[ident].get("status") in {"pending", "failed", "covered_by_stored_transcript"}:
                        upsert(root / "catalog/audio-queue.jsonl", [{**existing_jobs[ident], "status": "covered_by_stored_transcript", "transcript_path": record["text_path"], "completed_at": timestamp()}], "job_id")
                    break
                except Exception as exc:
                    event["caption_error"] = str(exc)
            if not stored:
                audio_url = enclosure.get("url", "")
                if safe_url(audio_url) != audio_url:
                    event.update(status="ephemeral_audio_url_requires_source_review")
                    result["errors"] += 1
                else:
                    previous = existing_jobs.get(ident, {})
                    relevance_evidence = reviewed_evidence.get("basis") if reviewed_evidence else ("configured episode title verified against the official appearance index" if verified_title else "publisher RSS episode explicitly identifies Michael Levin")
                    job = {**previous, "job_id": ident, "media_id": ident, "video_id": video_id, "title": title, "source_url": source, "audio_url": audio_url, "duration_seconds": event["duration_seconds"], "source_publication_date": publication_iso, "authorization_basis": authorization_basis(root), "status": previous.get("status", "pending"), "queued_at": previous.get("queued_at", timestamp()), "relevance_evidence": relevance_evidence, "publisher_feed_url": feed["url"], "episode_guid": guid}
                    upsert(root / "catalog/audio-queue.jsonl", [job], "job_id")
                    event["status"] = "audio_queued"
                    result["audio_queued"] += int(not previous)
            upsert(root / "catalog/rss-episodes.jsonl", [event], "episode_id")
            print(json.dumps({"show": feed["show"], "title": title, "status": event["status"]}, ensure_ascii=True), flush=True)
        upsert(root / "catalog/discovery-runs.jsonl", [{"source_url": feed["url"], "source_type": "publisher_rss", "items_scanned": len(items), "retrieved_at": timestamp()}], "source_url")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--limit", type=int)
    parser.add_argument("--feed", action="append", help="Collect only this configured feed URL; repeatable")
    args = parser.parse_args()
    root = args.root.resolve()
    print(json.dumps(collect(root, Fetcher(root), args.limit, args.feed)), flush=True)


if __name__ == "__main__":
    main()
