"""Discover podcast episode metadata from the public Apple directory search index."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlencode

from .expand import safe_url
from .feeds import commentary_title, publisher_title_match
from .harvest import Fetcher, timestamp
from .store import read_jsonl, upsert


def mentions_levin(item: dict) -> bool:
    return bool(re.search(r"\b(?:Michael|Mike) Levin\b", (item.get("trackName") or "") + " " + (item.get("description") or ""), re.I))


def classify(item: dict, configured_ids: set[int], known: dict, review_episodes: set[tuple[str, str]] | None = None, confirmed_episodes: dict[tuple[str, str], dict] | None = None) -> tuple[str, str]:
    title = item.get("trackName") or ""
    description = item.get("description") or ""
    if (item.get("feedUrl"), item.get("episodeGuid")) in (review_episodes or set()):
        return "participation_review_required", "Recording has been retained for participation review based on its transcript opening"
    reviewed = (confirmed_episodes or {}).get((item.get("feedUrl"), item.get("episodeGuid")))
    if reviewed:
        return "subject_confirmed", reviewed["basis"]
    if re.search(r"\b(congressman|congresswoman|congressional|representative)\b|\bRep\.?\s+(?:Mike|Michael) Levin\b", title, re.I):
        return "unrelated_name", "Episode identifies a political officeholder"
    if not re.search(r"\b(?:Michael|Mike) Levin\b", title, re.I):
        return "reference_review_required", "Name not explicit in episode title; search mentions alone do not establish participation"
    if commentary_title(title) or re.search(r"\b(?:speaks|talks|discusses) about (?:the )?(?:work|research) (?:of|or) (?:Michael|Mike) Levin\b", description[:700], re.I):
        return "participation_review_required", "Title or description indicates commentary on Levin; his participation is not established"
    if re.search(r"\b(Tufts|drmichaellevin|bioelectric\w*|xenobot\w*|anthrobot\w*|morphogen\w*)\b", title + " " + description[:700], re.I):
        return "subject_confirmed", "Episode names Michael Levin and identifies his institution or distinctive research"
    if item.get("collectionId") in configured_ids:
        return "subject_confirmed", "Episode names Michael Levin in a verified publisher feed"
    if publisher_title_match(title, item.get("collectionName", ""), known):
        return "subject_confirmed", "Episode title and publisher match the official appearance catalog"
    return "subject_identity_review_required", "Matching name without sufficient biologist identity evidence"


def discover(root: Path, client: Fetcher, terms: list[str] | None = None, add_feeds: bool = False) -> dict:
    config_path = root / "config/podcast-feeds.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    ids = {f["directory_collection_id"] for f in config["feeds"] if f.get("directory_collection_id")}
    review_episodes = {(f["url"], guid) for f in config["feeds"] for guid in f.get("participation_review_episode_guids", {})}
    confirmed_episodes = {(f["url"], guid): review for f in config["feeds"] for guid, review in f.get("reviewed_episode_guids", {}).items()}
    feed_urls = {f["url"] for f in config["feeds"]}
    # Its complete publisher sitemap has a separate participation-aware harvester.
    handled = {"https://feeds.transistor.fm/thoughtforms-life"}
    known = {v["video_id"]: v for v in read_jsonl(root / "catalog/videos.jsonl")}
    previous = {r["directory_episode_id"]: r for r in read_jsonl(root / "catalog/podcast-directory.jsonl")}
    covered_ids = {r["transcript_id"] for r in read_jsonl(root / "catalog/transcripts.jsonl") if r.get("status") == "stored" and (root / r.get("text_path", "MISSING")).is_file()}
    result = {"search_results": 0, "candidate_records": 0, "subject_confirmed": 0, "feeds_added": 0, "errors": 0}
    for term in terms or ["Michael Levin", "Mike Levin"]:
        url = "https://itunes.apple.com/search?" + urlencode({"term": term, "entity": "podcastEpisode", "limit": 200})
        try:
            items = json.loads(client.get(url)).get("results", [])
        except Exception as exc:
            upsert(root / "catalog/discovery-runs.jsonl", [{"source_url": url, "status": "failed", "reason": str(exc), "retrieved_at": timestamp()}], "source_url")
            result["errors"] += 1
            continue
        for item in items:
            result["search_results"] += 1
            if not item.get("trackId"):
                continue
            item_key = (item.get("feedUrl"), item.get("episodeGuid"))
            if not mentions_levin(item) and item_key not in confirmed_episodes and item_key not in review_episodes:
                continue
            status, basis = classify(item, ids, known, review_episodes, confirmed_episodes)
            prior = previous.get(item["trackId"], {})
            if prior.get("status") == "covered_by_primary_source" and prior.get("covered_by_transcript_id") in covered_ids:
                status, basis = prior["status"], prior["identity_basis"]
            record = {**prior, "directory_episode_id": item["trackId"], "episode_guid": item.get("episodeGuid"), "title": item.get("trackName"), "show": item.get("collectionName"), "directory_collection_id": item.get("collectionId"), "source_url": safe_url(item.get("trackViewUrl") or url), "feed_url": safe_url(item.get("feedUrl") or ""), "publication_date": item.get("releaseDate"), "duration_seconds": (item.get("trackTimeMillis") or 0) / 1000 or None, "status": status, "identity_basis": basis, "discovery_source": url, "retrieved_at": timestamp()}
            audio = item.get("episodeUrl", "")
            if audio and safe_url(audio) == audio:
                record["public_audio_url"] = audio
            upsert(root / "catalog/podcast-directory.jsonl", [record], "directory_episode_id")
            result["candidate_records"] += 1
            result["subject_confirmed"] += status == "subject_confirmed"
            feed = record["feed_url"]
            if add_feeds and status == "subject_confirmed" and feed.startswith("https://") and feed not in feed_urls | handled:
                config["feeds"].append({"show": record["show"], "url": feed, "directory_collection_id": item.get("collectionId"), "directory_episode_evidence": record["source_url"], "verification_basis": basis, "verified_at": timestamp()})
                feed_urls.add(feed)
                result["feeds_added"] += 1
        upsert(root / "catalog/discovery-runs.jsonl", [{"source_url": url, "source_type": "public_podcast_directory_search", "status": "retrieved", "items_scanned": len(items), "result_limit": 200, "exhaustive": False, "retrieved_at": timestamp()}], "source_url")
    if add_feeds:
        config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--term", action="append")
    parser.add_argument("--add-confirmed-feeds", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    print(json.dumps(discover(root, Fetcher(root), args.term, args.add_confirmed_feeds)), flush=True)


if __name__ == "__main__":
    main()
