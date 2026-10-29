# Corpus coverage report

Generated: 2026-10-29T17:05:22.055778+00:00

> This is an expanded public-source catalog, not a completeness claim. Appearance counts are provisional until mirrors and duplicate recordings are reconciled.

## Coverage

- Cataloged video uploads: **388**
- Provisional appearance records (not deduplicated): **461**
- Unique appearance count: **not verified**
- Duplicate video-ID rows merged: **0**
- Confirmed cross-upload duplicates: **0 (identity review pending)**
- Transcript text files stored in this repository: **301**
- External transcript links identified: **218**
- Caption availability confirmed missing: **0**
- Caption availability not checked: **387**
- Caption retrieval failures: **2**
- Metadata enrichment failures: **0**
- Metadata checks blocked by missing local tooling: **0**
- Source index fetch failures: **1**
- Caption checks blocked by missing local tooling: **0**
- Caption stores skipped pending rights review: **0**

### Transcript status

- captions_stored_locally: 1
- deferred: 1
- local_whisper_stored: 22
- publisher_transcript_stored: 194
- retrieval_failed: 1
- third_party_transcript_stored: 1
- unavailable: 29
- unknown: 139

- Distinct transcript texts: **301**
- Words in stored text files: **3,152,369**
- Publisher transcript source records stored: **203**
- Video IDs with stored text: **218**
- Video IDs still awaiting text: **170**
- Publisher entries requiring participation review: **11**
- Publisher episode pages without transcript text: **25**

Missing transcript controls are access outcomes, not proof that captions do not exist. Collector version 1 checked before description expansion; its negative outcomes require retry. Speaker labels are retained only when present in the source. Publisher dates are distinct from video upload dates.

### Upload role

- dub: 1
- excerpt: 3
- unknown: 384

## Backlog

- Run `levinverse discover --metadata` in a permitted network environment to refresh index records using yt-dlp.
- Check each item for accessible English captions; status `unknown` means no metadata check has run.
- Review duplicates, excerpts, compilations, and mirrors before merging video records into appearance records.
- Assess rights before marking source records `caption_storage_authorized` and using `--store-captions`.
- The RTX 5080 is available; install the optional faster-whisper extra and use permission-marked local media for CUDA transcription.
- Check active job status and scheduled continuation before launching another worker.

## Machine-readable report

See `reports/coverage.json` for counts and unresolved uncertainty.

## Sources

- [Levin Lab Audio & Video Interviews](https://www.drmichaellevin.org/presentations/audiovideo.html)
- [Lex Fridman transcript for episode 486](https://lexfridman.com/michael-levin-2-transcript) (authorized publisher text stored)
- [Thoughtforms Life Podcast](https://thoughtforms-life.aipodcast.ing/)
