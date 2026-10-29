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

`python -m levinverse.podcast_audio` resolves native public podcast players and refuses YouTube embed redirects. `python -m levinverse.feeds` reads the verified feeds in `config/podcast-feeds.json`, prefers RSS-supplied transcript tracks, and queues public audio otherwise. Related-video links are separated from episode identity; a matching known title or an unambiguous reference is required before attaching text to an upload. `python -m levinverse.fallbacks` handles explicitly configured third-party sources and labels their text unverified. Their source class remains distinct from original-publisher text.

`python -m levinverse.directory --add-confirmed-feeds` searches the public Apple podcast episode index for Michael and Mike Levin, retains source-linked candidate metadata, and adds feeds only for episodes with biologist identity evidence. Matching political officeholders and search mentions remain outside confirmed appearances. Search ranking, result limits and a publisher's current RSS window do not establish exhaustive coverage. `feeds --feed URL` restricts a run to selected configured feeds. Verified publisher domains and exact enclosure matches let the feed collector reuse already stored episodes.

`python -m levinverse.reconcile` links an existing transcript to an uncovered video when the publisher and a distinctive full video title match an RSS episode. These links are marked inferred: edits and mirrors have not been compared. The coverage report counts them separately, and the underlying publisher and episode evidence is retained.

Set `$env:LEVINVERSE_WHISPER_BATCH_SIZE='8'` to use the optional [faster-whisper batched inference path](https://github.com/SYSTRAN/faster-whisper#batched-transcription). The default is one; accepted values are 1 through 16. The chosen batch size is recorded in each ASR companion. Keep GPU job concurrency at one. Exact audio hashes reuse existing text, while distinct recordings referencing the same upload receive separate media filenames. Local batch manifests under `reports/*worker.json` are ignored runtime state; they do not configure a scheduler.

`python -m levinverse.platforms` records configured external-platform IDs separately from YouTube uploads and stores public native caption tracks. The collector uses Windows' native certificate store through `truststore`; TLS certificate verification remains enabled. ASR boundary overlaps are preserved and reported separately from reversed timestamp order or duration errors.

The user authorized hourly unattended collection, local CUDA processing, commits and updates to PR #1. The originating Codex chat has an active hourly follow-up; `config/continuation.json` records the app automation ID and last verified status. This is separate from a running finite audio batch. Local [Codex automations require the desktop app and computer to remain running](https://learn.chatgpt.com/docs/automations?surface=app). Verify the worker PID before launching another batch, and validate/commit completed acquisitions after the batch finishes.

On Windows, `tools/start-audio-worker.ps1 -Limit 100 -BatchSize 8` starts a hidden finite worker with durable logs under `.cache/workers/`; `-Python` selects the interpreter when needed. It checks the prior worker PID, and the Python worker independently enforces the OS lock. It does not install an OS scheduled task.

Report cataloged uploads, distinct text files, source records, covered video IDs, unresolved candidates and failed requests separately. Uploads and transcript sources are not a verified count of distinct appearances. Exhaustive coverage remains unproven until the known queues and source reviews are resolved.
