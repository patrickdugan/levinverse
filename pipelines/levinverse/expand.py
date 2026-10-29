"""Import channel metadata and enumerate the author's public blog without guest misattribution."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .discover import youtube_id
from .harvest import Fetcher, merge_video, parse_podcast, save_transcript, soup, timestamp, authorization_basis
from .store import read_jsonl, upsert, write_jsonl

CHANNEL = "https://www.youtube.com/@drmichaellevin/videos"


def safe_url(url: str) -> str:
    parsed = urlsplit(url)
    if any(key in parsed.query.lower() for key in ("x-amz-", "signature=", "token=")):
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return url


def import_channel(root: Path, path: Path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("channel_id") != "UC3pVafx6EZqXVI2V_Efu2uw":
        raise ValueError("Input is not the verified official Michael Levin channel")
    known = {r["video_id"]: r for r in read_jsonl(root / "catalog/videos.jsonl")}
    candidates, promoted = [], 0
    for entry in data.get("entries", []):
        vid = entry.get("id", "")
        if not re.fullmatch(r"[\w-]{11}", vid):
            continue
        title = entry.get("title") or ""
        explicit = bool(re.search(r"\b(?:Michael|Mike) Levin\b", title, re.I))
        existing = known.get(vid)
        record = {"candidate_id": "channel:" + vid, "video_id": vid, "canonical_url": f"https://www.youtube.com/watch?v={vid}", "title": title, "duration_seconds": entry.get("duration"), "discovery_source": CHANNEL, "retrieved_at": timestamp(), "participation_status": "confirmed_by_other_source" if existing else "explicit_title" if explicit else "requires_review"}
        candidates.append(record)
        if existing or explicit:
            video = {"video_id": vid, "canonical_url": record["canonical_url"], "title": existing.get("title") if existing else title, "metadata_video_title": title, "duration_seconds": entry.get("duration"), "channel": "Michael Levin's Academic Content", "channel_id": data["channel_id"], "discovery_sources": [CHANNEL], "flat_metadata_retrieved_at": timestamp(), "availability": entry.get("availability")}
            if explicit and not existing:
                video["participation_evidence"] = "Michael Levin named in official channel upload title"
                promoted += 1
            merge_video(root, video, bool(authorization_basis(root)))
    upsert(root / "catalog/discovery_candidates.jsonl", candidates, "candidate_id")
    result = {"source_url": CHANNEL, "source_type": "yt_dlp_flat_channel", "retrieved_at": timestamp(), "entries_enumerated": len(candidates), "new_named_appearances": promoted, "raw_metadata_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    upsert(root / "catalog/discovery-runs.jsonl", [result], "source_url")
    return result


def discover_blog(root: Path, client: Fetcher):
    posts, candidates, documents = [], [], []
    for page in range(1, 101):
        url = f"https://thoughtforms.life/wp-json/wp/v2/posts?per_page=100&page={page}"
        batch = json.loads(client.get(url))
        posts.extend(batch)
        if len(batch) < 100:
            break
    known = {r["video_id"] for r in read_jsonl(root / "catalog/videos.jsonl")}
    for post in posts:
        body = soup(post["content"]["rendered"].encode())
        for node in body.find_all(["iframe", "a"]):
            href = node.get("href") or node.get("src") or ""
            vid = youtube_id(href)
            if vid:
                ident = hashlib.sha256((post["link"] + "|" + vid).encode()).hexdigest()[:20]
                candidates.append({"candidate_id": ident, "video_id": vid, "canonical_url": f"https://www.youtube.com/watch?v={vid}", "discovery_source": post["link"], "source_title": post["title"]["rendered"], "source_publication_date": post["date"][:10], "anchor_text": node.get_text(" ", strip=True), "participation_status": "confirmed_by_other_source" if vid in known else "requires_review"})
            if ".pdf" in href.lower() or "transcript" in href.lower():
                clean = safe_url(href)
                documents.append({"document_id": hashlib.sha256((clean + post["link"]).encode()).hexdigest()[:20], "source_url": clean, "discovery_source": post["link"], "source_title": post["title"]["rendered"], "anchor_text": node.get_text(" ", strip=True), "content_not_acquired": True})
    upsert(root / "catalog/discovery_candidates.jsonl", candidates, "candidate_id")
    upsert(root / "catalog/related-documents.jsonl", documents, "document_id")
    result = {"source_url": "https://thoughtforms.life/wp-json/wp/v2/posts", "source_type": "official_wordpress_index", "retrieved_at": timestamp(), "posts_scanned": len(posts), "video_link_records": len(candidates), "unique_video_ids": len({c["video_id"] for c in candidates}), "related_document_links": len(documents)}
    upsert(root / "catalog/discovery-runs.jsonl", [result], "source_url")
    return result


def reconcile_publishers(root: Path, client: Fetcher):
    registry = read_jsonl(root / "catalog/transcripts.jsonl")
    for row in registry:
        if row["source_url"].startswith("https://thoughtforms-life.aipodcast.ing/") and len(row.get("video_ids", [])) > 1:
            item = parse_podcast(client.get(row["source_url"]), row["source_url"])
            save_transcript(root, item, row.get("authorization_basis") or authorization_basis(root))
    registry = {r["source_url"]: r for r in read_jsonl(root / "catalog/transcripts.jsonl")}
    videos, removed = [], []
    for video in read_jsonl(root / "catalog/videos.jsonl"):
        source = video.get("transcript_url")
        if source in registry and video["video_id"] not in registry[source].get("video_ids", []):
            video.pop("transcript_path", None)
            video.pop("transcript_url", None)
            video["transcript_status"] = "unknown"
        sources = video.get("discovery_sources", [])
        if sources and all(s in registry and video["video_id"] not in registry[s].get("video_ids", []) for s in sources):
            removed.append(video)
        else:
            videos.append(video)
    for video in removed:
        upsert(root / "catalog/discovery_candidates.jsonl", [{"candidate_id": "related:" + video["video_id"], "video_id": video["video_id"], "canonical_url": video["canonical_url"], "title": video.get("title"), "discovery_sources": video.get("discovery_sources"), "participation_status": "related_link_requires_review"}], "candidate_id")
    write_jsonl(root / "catalog/videos.jsonl", videos, "video_id")
    removed_ids = {r["video_id"] for r in removed}
    appearances = [a for a in read_jsonl(root / "catalog/appearances.jsonl") if a.get("appearance_id") not in removed_ids]
    write_jsonl(root / "catalog/appearances.jsonl", appearances, "appearance_id")
    return {"related_links_removed_from_appearance_catalog": len(removed)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--channel-json", type=Path)
    parser.add_argument("--blog", action="store_true")
    parser.add_argument("--reconcile", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    client = Fetcher(root, args.cache)
    if args.reconcile:
        print(json.dumps(reconcile_publishers(root, client)), flush=True)
    if args.channel_json:
        print(json.dumps(import_channel(root, args.channel_json)), flush=True)
    if args.blog:
        print(json.dumps(discover_blog(root, client)), flush=True)


if __name__ == "__main__":
    main()
