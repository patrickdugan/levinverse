"""Link stored publisher transcripts to cataloged videos using conservative title evidence."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .feeds import publisher_title_match
from .harvest import merge_video, timestamp
from .store import read_jsonl, upsert


def title_contains_video_title(episode_title: str, video_title: str) -> bool:
    stop = {"michael", "mike", "levin", "dr", "prof", "professor", "the", "of", "and", "with", "on", "a", "podcast", "interview"}
    words = lambda title: {word for word in re.findall(r"[a-z0-9]+", title.casefold()) if not word.isdigit()} - stop
    video_words = words(video_title)
    return len(video_words) >= 3 and video_words.issubset(words(episode_title))


def reconcile(root: Path) -> dict:
    videos = {v["video_id"]: v for v in read_jsonl(root / "catalog/videos.jsonl")}
    records = read_jsonl(root / "catalog/transcripts.jsonl")
    jobs = {j["job_id"]: j for j in read_jsonl(root / "catalog/audio-queue.jsonl")}
    result = {"inferred_video_links": 0, "ambiguous_sources_skipped": 0}
    for episode in read_jsonl(root / "catalog/rss-episodes.jsonl"):
        if episode.get("confirmed_video_id") or episode.get("inferred_video_id"):
            continue
        sources = [r for r in records if r.get("status") == "stored" and r.get("source_url") == episode.get("source_url") and (root / r.get("text_path", "MISSING")).is_file()]
        if len(sources) != 1:
            if len(sources) > 1:
                result["ambiguous_sources_skipped"] += 1
            continue
        record = sources[0]
        if record.get("video_ids") or record.get("recording_role") in {"excerpt", "public_preview", "compilation"}:
            continue
        title, show = episode.get("title", ""), episode.get("show", "")
        ident = publisher_title_match(title, show, videos)
        if not ident or videos[ident].get("transcript_path"):
            continue
        video_title = videos[ident].get("metadata_video_title") or videos[ident].get("title", "")
        if not title_contains_video_title(title, video_title):
            continue
        evidence = {"method": "publisher_and_title_match", "confidence": "inferred; audio/video edits and mirrors have not been compared", "feed_url": episode["feed_url"], "episode_title": title, "video_title": video_title, "publisher": show, "matched_at": timestamp()}
        record.update(video_ids=[ident], video_link_evidence=evidence)
        upsert(root / "catalog/transcripts.jsonl", [record], "transcript_id")
        episode.update(inferred_video_id=ident, video_link_evidence=evidence)
        upsert(root / "catalog/rss-episodes.jsonl", [episode], "episode_id")
        job = jobs.get(episode["episode_id"])
        if job:
            job.update(video_id=ident, video_link_evidence=evidence)
            upsert(root / "catalog/audio-queue.jsonl", [job], "job_id")
        status = {"local_whisper": "local_whisper_stored", "platform_caption": "captions_stored_locally", "third_party_transcript": "third_party_transcript_stored"}.get(record.get("source_kind"), "publisher_transcript_stored")
        merge_video(root, {"video_id": ident, "transcript_status": status, "transcript_path": record["text_path"], "transcript_url": record["source_url"], "transcript_language": record.get("language"), "transcript_video_link_method": "publisher_and_title_match", "transcript_video_link_confidence": evidence["confidence"], "discovery_sources": [record["source_url"]]}, True)
        videos[ident]["transcript_path"] = record["text_path"]
        appearance = next((a for a in read_jsonl(root / "catalog/appearances.jsonl") if a.get("appearance_id") == episode["episode_id"]), None)
        if appearance:
            appearance.update(video_ids=[ident], video_link_evidence=evidence)
            upsert(root / "catalog/appearances.jsonl", [appearance], "appearance_id")
        result["inferred_video_links"] += 1
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(reconcile(args.root.resolve())), flush=True)


if __name__ == "__main__":
    main()
