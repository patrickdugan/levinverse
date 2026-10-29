# Collection runbook

The corpus targets Michael Levin, the Tufts biologist. Public guest-only lectures on his channel stay in the candidate queue until his participation is established. The configured authorization is recorded in `config/permissions.json`.

## Publisher collection

Install `python -m pip install -e ".[collector]"`, then run:

```powershell
python -m levinverse.harvest --store-transcripts
python -m levinverse.expand --blog --reconcile
python -m levinverse report
```

The harvest enumerates the complete official interview, presentation and conversation indexes and the podcast sitemap. Source HTTP responses are cached for 24 hours. Each source is checkpointed; HTTP 403 and 429 responses impose a 24-hour cooldown. Cached source HTML remains under the ignored `.cache/` directory. A supplied `--cache` path can reuse an existing local cache.

The publisher transcript registry is `catalog/transcripts.jsonl`. Plain text and structured segment JSON are committed under `transcripts/permitted/`. Exact text duplicates share a path. The source, date, authorization basis, quality notes, original timestamp granularity and explicit speaker labels are retained. Unknown speaker labels remain unknown.

## Official YouTube channel

Enumerate metadata without downloading media:

```powershell
python -m yt_dlp --flat-playlist --dump-single-json --skip-download https://www.youtube.com/@drmichaellevin/videos > .cache/channel.json
python -m levinverse.expand --channel-json .cache/channel.json
```

All uploads enter the discovery-candidate ledger. Existing confirmed videos and new titles explicitly naming Michael or Mike Levin enter the appearance catalog. A channel upload alone does not establish participation. `LEVINVERSE_JS_RUNTIME` can identify an installed yt-dlp JavaScript runtime, for example `node:C:\path\to\node.exe`.

`TranscriptPuller` is a separate local project. Its current collector waits for the description to load, expands the description itself, activates Show transcript, and reads the panel. Older collector version 1 checked too early, so its negative results are superseded and require retry. The current environment returned HTTP 400 from YouTube's transcript request; that is a request failure, not proof that captions are absent. Stop repeated provider failures and retain cooldowns.

## Permitted local audio transcription

```powershell
python -m pip install -e ".[whisper,cuda-windows]"
python -m levinverse.audio --plan
python -m levinverse.audio --run --limit 1 --model turbo
```

The planner only queues confirmed appearances without already stored text, using public publisher audio enclosures. Media stays in ignored `media/permitted/`; model files stay in ignored `.cache/`. Processing requires the audio and transcript authorizations in configuration. The worker records audio hashes, the permission record, CUDA/FP16 model settings, word and segment timestamps, failures and retry eligibility. ASR output is labeled unverified and does not invent speaker diarization. PyAV is pinned below version 19 because faster-whisper 1.2.1 uses its removed `metadata_errors` argument; see the [upstream compatibility issue](https://github.com/SYSTRAN/faster-whisper/issues/1589).

## Continuation and counts

`catalog/backlog.jsonl` lists video IDs without stored text. `catalog/discovery_candidates.jsonl` retains links requiring participation review, and `catalog/nonvideo-sources.jsonl` retains other officially indexed media links. Publisher references to other videos are kept separate from the actual episode video.

Before launching a job, check whether an earlier local process is still running. Keep source requests conservative and GPU concurrency at one. Never launch paid cloud compute. After a completed batch, regenerate reports, validate changed records, run relevant tests when code changed, commit only this task's files, and update the existing isolated PR branch. Leave unrelated changes untouched.

Use `python -m levinverse.validate` for checksums, source/authorization fields, canonical IDs, companion files and ASR timing validation. `python -m levinverse.publishers` scans officially linked non-YouTube pages; `--linked-pdfs` follows explicit public transcript PDF links and records access failures. Provider-wide cooldowns are stored in `catalog/provider-state.json` and apply to TranscriptPuller too.

Report cataloged uploads, distinct text files, source records, covered video IDs, unresolved candidates and failed requests separately. Uploads and transcript sources are not a verified count of distinct appearances. Exhaustive coverage remains unproven until the known queues and source reviews are resolved.
