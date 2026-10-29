# Corpus coverage report

Generated: 2026-10-29 (UTC)

> The catalog contains a bounded set of public video appearances and does not claim exhaustive coverage. Appearance records remain provisional until mirrors and duplicate recordings are reconciled.

## Coverage

- Cataloged unique video uploads: **35**
- Provisional appearance records: **36**
- Unique appearance count: **not verified**
- Duplicate video-ID rows merged: **0**
- Confirmed cross-upload duplicates: **0 (identity review pending)**
- Transcript text files stored in the repository: **1** (publisher-hosted University of Chicago transcript)
- Video transcript panels captured: **0**
- Video pages checked: **34**; no visible transcript control was available on those rendered pages
- Video page deferred by a previously recorded 24-hour YouTube retry window: **1**
- External transcript links identified: **2**
- Source index fetch failures: **1**
- Persistent worker running: **no**

The 34 unavailable panel checks mean the transcript control was not exposed in the rendered page during this run; they do not prove that no transcript exists elsewhere. The machine-readable event log records each video ID, URL, attempt time, and outcome in `reports/transcriptpuller-status.jsonl`. The deferred video is recorded with its retry time in the catalog.

## Transcript files

- `transcripts/permitted/uchicago-big-brains-2023-04-27.txt` — 79 paragraphs, approximately 4,836 words, captured from the publisher's transcript page.
- `transcripts/permitted/uchicago-big-brains-2023-04-27.json` — paragraph-ordered text and source metadata.

## Existing summary and source links

- The source-linked scientific summary is in `research/summaries/uchicago-big-brains-2023.md`.
- [Levin Lab Audio & Video Interviews](https://www.drmichaellevin.org/presentations/audiovideo.html)
- [Lex Fridman transcript for episode 486](https://lexfridman.com/michael-levin-2-transcript)
- [Thoughtforms Life Podcast](https://thoughtforms-life.aipodcast.ing/)

## Next collection run

Run `TranscriptPuller` from its standalone project directory against this repository. It skips already completed outcomes by default, retries failed or unavailable entries only with `--retry-existing`, respects recorded `retry_after` values, and stops when a provider rate limit is detected. Install the optional `faster-whisper` extra and use permission-marked local media for CUDA transcription on the RTX 5080.

No background worker is configured or running. See `reports/coverage.json` for the current machine-readable counts.
