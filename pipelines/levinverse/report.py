from __future__ import annotations

import json
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from .store import read_jsonl, write_jsonl


def active_worker(root: Path) -> bool:
    for path in (root / "reports").glob("*worker.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("status") != "running":
                continue
            if os.name == "nt":
                import ctypes
                kernel = ctypes.windll.kernel32
                kernel.OpenProcess.restype = ctypes.c_void_p
                kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                handle = kernel.OpenProcess(0x1000, False, int(record["pid"]))
                if handle:
                    code = ctypes.c_ulong()
                    try:
                        if kernel.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value == 259:
                            return True
                    finally:
                        kernel.CloseHandle(handle)
            else:
                os.kill(int(record["pid"]), 0)
                return True
        except (OSError, ValueError, KeyError):
            continue
    return False


def generate_report(root: Path) -> str:
    videos = read_jsonl(root / "catalog/videos.jsonl")
    appearances = read_jsonl(root / "catalog/appearances.jsonl")
    provenance = read_jsonl(root / "catalog/provenance.jsonl")
    registry = read_jsonl(root / "catalog/transcripts.jsonl")
    text_files = list((root / "transcripts/permitted").glob("*.txt"))
    texts = [p.read_text(encoding="utf-8") for p in text_files]
    hashes = {hashlib.sha256(" ".join(t.split()).encode()).hexdigest() for t in texts}
    stored_registry = [r for r in registry if r.get("status") == "stored" and (root / r.get("text_path", "MISSING")).is_file()]
    stored_video_ids = {v["video_id"] for v in videos if v.get("transcript_path") and (root / v["transcript_path"]).is_file()}
    stored_video_ids.update(v["video_id"] for v in videos if (root / "transcripts/permitted" / (v["video_id"] + ".txt")).is_file())
    panels = {e["video_id"]: e for e in read_jsonl(root / "reports/transcriptpuller-status.jsonl")}
    candidates = read_jsonl(root / "catalog/discovery_candidates.jsonl")
    video_ids = {v["video_id"] for v in videos}
    publisher_pages = read_jsonl(root / "catalog/publisher-pages.jsonl")
    audio_jobs = read_jsonl(root / "catalog/audio-queue.jsonl")
    directory = read_jsonl(root / "catalog/podcast-directory.jsonl")
    status: dict[str, int] = {}
    role: dict[str, int] = {}
    for video in videos:
        key = video.get("transcript_status", "unknown")
        status[key] = status.get(key, 0) + 1
        key = video.get("role", "unknown")
        role[key] = role.get(key, 0) + 1
    failures = sum(event.get("status") == "failed" for event in provenance if event.get("event") == "caption_attempt")
    blocked = sum(v.get("ingest", {}).get("status") == "blocked" for v in videos)
    metadata_failures = sum(v.get("metadata_status") == "failed" for v in videos)
    metadata_blocked = sum(v.get("metadata_status") == "blocked" for v in videos)
    source_failures = sum(e.get("event") == "source_fetch_failed" for e in provenance)
    rights_skipped = sum(v.get("ingest", {}).get("status") == "rights_review_required" for v in videos)
    transcript_urls = {v.get("transcript_url") for v in videos if v.get("transcript_url")}
    for metadata_file in (root / "transcripts/metadata").glob("*.json"):
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            link = metadata.get("source_url")
            if link and metadata.get("text_stored") is False:
                transcript_urls.add(link)
        except (OSError, json.JSONDecodeError):
            continue
    coverage = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Expanded official indexes and publisher sitemap; not a completeness claim",
        "cataloged_video_uploads": len(videos),
        "provisional_appearance_records": len(appearances),
        "unique_appearance_count": None,
        "duplicate_video_id_rows_merged": None,
        "duplicate_video_id_source_references": sum(max(0, len(v.get("discovery_sources", [])) - 1) for v in videos),
        "cross_upload_duplicate_recordings_confirmed": 0,
        "duplicate_identity_review_complete": False,
        "transcripts_stored_locally": len(text_files),
        "unique_transcript_texts": len(hashes),
        "stored_transcript_words": sum(len(t.split()) for t in texts),
        "word_count_definition": "Whitespace-delimited tokens in stored TXT, including source speaker labels and timestamps",
        "publisher_transcript_records_stored": sum(not r.get("model") and r.get("source_kind") not in {"local_whisper", "platform_caption", "third_party_transcript"} for r in stored_registry),
        "third_party_transcripts_stored": len({r["text_path"] for r in stored_registry if r.get("source_kind") == "third_party_transcript"}),
        "platform_caption_transcripts_stored": len({r["text_path"] for r in stored_registry if r.get("source_kind") == "platform_caption"}),
        "local_whisper_transcripts_stored": len({r["text_path"] for r in stored_registry if r.get("model") or r.get("source_kind") == "local_whisper"}),
        "local_whisper_source_records": sum(bool(r.get("model")) or r.get("source_kind") == "local_whisper" for r in stored_registry),
        "stored_transcript_source_records": len(stored_registry),
        "publisher_duplicate_sources": sum(bool(r.get("duplicate_of")) for r in stored_registry),
        "video_ids_with_stored_transcripts": len(stored_video_ids),
        "video_ids_without_stored_transcripts": len(videos) - len(stored_video_ids),
        "publisher_records_requiring_participation_review": sum(r.get("status") == "participation_review_required" for r in registry),
        "publisher_records_without_transcript": sum(r.get("status") == "no_publisher_transcript" for r in registry),
        "discovery_candidate_records": len(read_jsonl(root / "catalog/discovery_candidates.jsonl")),
        "unverified_additional_video_ids": len({c["video_id"] for c in candidates if c.get("video_id") not in video_ids}),
        "official_non_youtube_source_links": len(read_jsonl(root / "catalog/nonvideo-sources.jsonl")),
        "publisher_pages_scanned": len(publisher_pages),
        "publisher_rss_episode_records": len(read_jsonl(root / "catalog/rss-episodes.jsonl")),
        "podcast_directory_candidate_records": len(directory),
        "podcast_directory_confirmed_subject_records": sum(r.get("status") == "subject_confirmed" for r in directory),
        "public_audio_job_statuses": {status: sum(j.get("status") == status for j in audio_jobs) for status in sorted({j.get("status", "unknown") for j in audio_jobs})},
        "publisher_page_request_failures": sum(p.get("status") == "request_failed" for p in publisher_pages),
        "video_transcript_checks_failed": sum(e.get("status") == "failed" for e in panels.values()),
        "video_transcript_panels_saved": sum(e.get("status") == "saved" for e in panels.values()),
        "video_transcript_panels_unavailable": sum(e.get("status") == "unavailable" and e.get("collector_version", 1) >= 3 for e in panels.values()),
        "older_negative_ui_results_requiring_retry": sum(e.get("status") == "unavailable" and e.get("collector_version", 1) < 3 for e in panels.values()),
        "video_transcript_checks_deferred": sum(e.get("status") == "deferred" for e in panels.values()),
        "external_transcript_links": len(transcript_urls),
        "caption_availability_confirmed_missing": sum(v.get("metadata_status") == "retrieved" and not any((v.get("caption_languages") or {}).values()) for v in videos),
        "caption_availability_not_checked": sum(v.get("metadata_status") != "retrieved" and not v.get("caption_languages") for v in videos),
        "caption_retrieval_failures": failures,
        "metadata_enrichment_failures": metadata_failures,
        "metadata_checks_blocked_by_missing_tools": metadata_blocked,
        "source_index_fetch_failures": source_failures,
        "caption_checks_blocked_by_missing_tools": blocked,
        "caption_storage_skipped_pending_rights_review": rights_skipped,
        "local_batch_worker_running": active_worker(root),
        "persistent_worker_running": False,
        "scheduled_continuation_status": "not_configured",
    }
    (root / "reports").mkdir(parents=True, exist_ok=True)
    backlog = []
    for video in videos:
        if video["video_id"] in stored_video_ids:
            continue
        event = panels.get(video["video_id"], {})
        backlog.append({"video_id": video["video_id"], "canonical_url": video.get("canonical_url"), "title": video.get("title"), "status": "transcript_pending", "last_browser_outcome": event.get("status"), "reason": event.get("reason"), "collector_version": event.get("collector_version", 1) if event else None, "retry_after": max([r for r in [event.get("retry_after"), video.get("ingest", {}).get("retry_after")] if r], default=None), "discovery_sources": video.get("discovery_sources", [])})
    write_jsonl(root / "catalog/backlog.jsonl", backlog, "video_id")
    (root / "reports/coverage.json").write_text(json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Corpus coverage report", "", f"Generated: {datetime.now(timezone.utc).isoformat()}", "",
        "> This is an expanded public-source catalog, not a completeness claim. Appearance counts are provisional until mirrors and duplicate recordings are reconciled.", "",
        "## Coverage", "", f"- Cataloged video uploads: **{len(videos)}**", f"- Provisional appearance records (not deduplicated): **{len(appearances)}**", "- Unique appearance count: **not verified**", "- Duplicate video-ID rows merged: **0**", "- Confirmed cross-upload duplicates: **0 (identity review pending)**", f"- Transcript text files stored in this repository: **{coverage['transcripts_stored_locally']}**", f"- External transcript links identified: **{coverage['external_transcript_links']}**", f"- Caption availability confirmed missing: **{coverage['caption_availability_confirmed_missing']}**", f"- Caption availability not checked: **{coverage['caption_availability_not_checked']}**", f"- Caption retrieval failures: **{failures}**", f"- Metadata enrichment failures: **{metadata_failures}**", f"- Metadata checks blocked by missing local tooling: **{metadata_blocked}**", f"- Source index fetch failures: **{source_failures}**", f"- Caption checks blocked by missing local tooling: **{blocked}**", f"- Caption stores skipped pending rights review: **{rights_skipped}**", "",
        "### Transcript status", "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in sorted(status.items()))
    lines.extend(["", f"- Distinct transcript texts: **{coverage['unique_transcript_texts']}**", f"- Words in stored text files: **{coverage['stored_transcript_words']:,}**", f"- Publisher transcript source records stored: **{coverage['publisher_transcript_records_stored']}**", f"- Video IDs with stored text: **{coverage['video_ids_with_stored_transcripts']}**", f"- Video IDs still awaiting text: **{coverage['video_ids_without_stored_transcripts']}**", f"- Publisher entries requiring participation review: **{coverage['publisher_records_requiring_participation_review']}**", f"- Publisher episode pages without transcript text: **{coverage['publisher_records_without_transcript']}**", "", "Missing transcript controls are access outcomes, not proof that captions do not exist. Collector version 1 checked before description expansion; its negative outcomes require retry. Speaker labels are retained only when present in the source. Publisher dates are distinct from video upload dates."])
    lines.extend(["", "### Upload role", ""])
    lines.extend(f"- {key}: {value}" for key, value in sorted(role.items()))
    lines.extend(["", "## Backlog", "", "- Run `levinverse discover --metadata` in a permitted network environment to refresh index records using yt-dlp.", "- Check each item for accessible English captions; status `unknown` means no metadata check has run.", "- Review duplicates, excerpts, compilations, and mirrors before merging video records into appearance records.", "- Assess rights before marking source records `caption_storage_authorized` and using `--store-captions`.", "- The RTX 5080 is available; install the optional faster-whisper extra and use permission-marked local media for CUDA transcription.", "- Check active job status and scheduled continuation before launching another worker.", "", "## Machine-readable report", "", "See `reports/coverage.json` for counts and unresolved uncertainty.", "", "## Sources", "", "- [Levin Lab Audio & Video Interviews](https://www.drmichaellevin.org/presentations/audiovideo.html)", "- [Lex Fridman transcript for episode 486](https://lexfridman.com/michael-levin-2-transcript) (authorized publisher text stored)", "- [Thoughtforms Life Podcast](https://thoughtforms-life.aipodcast.ing/)", ""])
    report = "\n".join(lines)
    target = root / "reports/coverage.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding="utf-8")
    return report
