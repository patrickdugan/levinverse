"""Read explicitly linked transcript fallbacks with conservative source identity checks."""
import argparse
import json
import re
from pathlib import Path

from .harvest import Fetcher, authorization_basis, save_transcript, seconds, soup
from .store import read_jsonl


def parse_podscripts(raw: bytes, source: dict, known_video: dict) -> dict:
    page = soup(raw)
    title = page.find("h1").get_text(" ", strip=True)
    if "michael levin" not in title.lower() or source["episode_number"] not in title:
        raise ValueError("Fallback source episode identity does not match the configured appearance")
    region = page.select_one(".podcast-transcript")
    if not region:
        raise ValueError("No public transcript region found")
    segments = []
    seen = set()
    for group in region.select(".single-sentence"):
        stamp = group.select_one(".pod_timestamp_indicator")
        texts, source_ids = [], []
        for node in group.select(".transcript-text"):
            if node.get("id") in seen:
                continue
            seen.add(node.get("id"))
            texts.append(node.get_text(" ", strip=True))
            source_ids.append(node.get("id"))
        if texts:
            segments.append({"start_seconds": seconds(stamp.get_text()) if stamp else None, "speaker": None, "text": " ".join(texts), "source_span_ids": source_ids})
    if len(segments) < 20:
        raise ValueError("Transcript source is incomplete or its markup changed")
    return {"source_url": source["source_url"], "original_publisher_url": source["original_publisher_url"], "source_kind": "third_party_transcript", "title": known_video["title"], "publication_date": None, "video_ids": [source["video_id"]], "segments": segments, "relevance_confirmed": True, "relevance_evidence": "officially indexed video ID plus matching original publisher episode number and fallback page title", "transcript_quality": source["quality"], "host": known_video.get("host"), "language": "en"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    client = Fetcher(root)
    videos = {r["video_id"]: r for r in read_jsonl(root / "catalog/videos.jsonl")}
    config = json.loads((root / "config/fallback-transcripts.json").read_text(encoding="utf-8"))
    for source in config["sources"]:
        video = videos[source["video_id"]]
        if video.get("transcript_path") and (root / video["transcript_path"]).is_file():
            continue
        item = parse_podscripts(client.get(source["source_url"]), source, video)
        record = save_transcript(root, item, authorization_basis(root))
        print(json.dumps({"source_url": source["source_url"], "status": record["status"], "segments": record.get("segment_count"), "words": record.get("word_count")}), flush=True)


if __name__ == "__main__":
    main()
