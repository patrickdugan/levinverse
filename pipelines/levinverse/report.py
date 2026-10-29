from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .store import read_jsonl


def generate_report(root: Path) -> str:
    videos = read_jsonl(root / "catalog/videos.jsonl")
    appearances = read_jsonl(root / "catalog/appearances.jsonl")
    provenance = read_jsonl(root / "catalog/provenance.jsonl")
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
        "scope": "bounded seed catalog; not an exhaustive crawl",
        "cataloged_video_uploads": len(videos),
        "provisional_appearance_records": len(appearances),
        "unique_appearance_count": None,
        "duplicate_video_id_rows_merged": 0,
        "cross_upload_duplicate_recordings_confirmed": 0,
        "duplicate_identity_review_complete": False,
        "transcripts_stored_locally": sum(bool(v.get("transcript_path")) for v in videos),
        "external_transcript_links": len(transcript_urls),
        "caption_availability_confirmed_missing": sum(v.get("transcript_status") == "unavailable" for v in videos),
        "caption_availability_not_checked": sum(v.get("transcript_status", "unknown") == "unknown" for v in videos),
        "caption_retrieval_failures": failures,
        "metadata_enrichment_failures": metadata_failures,
        "metadata_checks_blocked_by_missing_tools": metadata_blocked,
        "source_index_fetch_failures": source_failures,
        "caption_checks_blocked_by_missing_tools": blocked,
        "caption_storage_skipped_pending_rights_review": rights_skipped,
        "persistent_worker_running": False,
    }
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / "reports/coverage.json").write_text(json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Corpus coverage report", "", f"Generated: {datetime.now(timezone.utc).isoformat()}", "",
        "> This is a bounded seed catalog, not a completeness claim. Appearance counts are provisional until mirrors and duplicate recordings are reconciled.", "",
        "## Coverage", "", f"- Cataloged video uploads: **{len(videos)}**", f"- Provisional appearance records (not deduplicated): **{len(appearances)}**", "- Unique appearance count: **not verified**", "- Duplicate video-ID rows merged: **0**", "- Confirmed cross-upload duplicates: **0 (identity review pending)**", f"- Caption files acquired into this repository: **{coverage['transcripts_stored_locally']}**", f"- External transcript links identified: **{coverage['external_transcript_links']}**", f"- Caption availability confirmed missing: **{coverage['caption_availability_confirmed_missing']}**", f"- Caption availability not checked: **{coverage['caption_availability_not_checked']}**", f"- Caption retrieval failures: **{failures}**", f"- Metadata enrichment failures: **{metadata_failures}**", f"- Metadata checks blocked by missing local tooling: **{metadata_blocked}**", f"- Source index fetch failures: **{source_failures}**", f"- Caption checks blocked by missing local tooling: **{blocked}**", f"- Caption stores skipped pending rights review: **{rights_skipped}**", "",
        "### Transcript status", "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in sorted(status.items()))
    lines.extend(["", "### Upload role", ""])
    lines.extend(f"- {key}: {value}" for key, value in sorted(role.items()))
    lines.extend(["", "## Backlog", "", "- Run `levinverse discover --metadata` in a permitted network environment to refresh index records using yt-dlp.", "- Check each item for accessible English captions; status `unknown` means no metadata check has run.", "- Review duplicates, excerpts, compilations, and mirrors before merging video records into appearance records.", "- Assess rights before marking source records `caption_storage_authorized` and using `--store-captions`.", "- The RTX 5080 is available; install the optional faster-whisper extra and use permission-marked local media for CUDA transcription.", "- No persistent worker is running or configured.", "", "## Machine-readable report", "", "See `reports/coverage.json` for counts and unresolved uncertainty.", "", "## Sources", "", "- [Levin Lab Audio & Video Interviews](https://www.drmichaellevin.org/presentations/audiovideo.html)", "- [Lex Fridman transcript for episode 486](https://lexfridman.com/michael-levin-2-transcript) (linked externally; text not copied)", "- [Thoughtforms Life Podcast](https://thoughtforms-life.aipodcast.ing/)", ""])
    report = "\n".join(lines)
    target = root / "reports/coverage.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding="utf-8")
    return report
