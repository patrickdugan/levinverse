# Levinverse

For the full publisher crawl, channel candidate review, local CUDA audio fallback and continuation workflow, see [COLLECTION.md](COLLECTION.md). Actual counts and remaining video IDs are in `reports/coverage.json` and `catalog/backlog.jsonl`.

An incremental, evidence-grounded catalog of Michael Levin's public spoken work. The first collection pass is a verified seed set from the Levin Lab's [Audio & Video Interviews archive](https://www.drmichaellevin.org/presentations/audiovideo.html). It is not an exhaustive inventory.

## Quick start

```powershell
python -m pip install -e .
python -m levinverse discover
python -m levinverse discover --metadata
python -m levinverse report
```

Discovery is checkpointed and idempotent: rerunning it upserts records by canonical URL. It only reads public source pages and records metadata. It does not download media or captions by default.

`discover --metadata` calls `yt-dlp --dump-single-json --skip-download` once per discovered video, with bounded retries and a one-second inter-video delay. Source index state and per-record JSONL upserts make discovery resumable. The configured sources include the Levin Lab audio/video index and Levin's Thoughtforms sites; the latter are filtered for Levin-related entries.

To inspect caption availability, install the collector dependency with `python -m pip install -e ".[collector]"` and run:

```powershell
python -m levinverse discover --metadata
python -m levinverse ingest --captions --store-captions
```

Caption files are written under `transcripts/permitted/` and committed only when the source record is marked `caption_storage_authorized: true`. The pipeline records caption languages, unavailable status, rights skips, failures, retry times, and source links. It never downloads full audiovisual media. Respect source terms, rate limits, copyright, and privacy. Private/local transcripts should not be included unless redistribution is authorized.

For permitted local recordings, create a JSON permission record containing `permission_confirmed: true`, a `permission_basis`, and a `source_url`; put media under `media/permitted/`. Then install `python -m pip install -e ".[whisper]"` and run:

```powershell
python -m levinverse transcribe --media media/permitted/example.mp4 --permission-file transcripts/metadata/example-permission.json
```

The optional `faster-whisper` worker uses CUDA FP16 by default, records word and segment timestamps, and writes authorized text and JSON under `transcripts/permitted/` for repository storage. Set `LEVINVERSE_WHISPER_MODEL` or pass `--model`; the default model is `turbo`. Speaker diarization is not performed. Local media and downloaded model files are ignored by Git.

## Data

- `catalog/videos.jsonl`: one upload per video, including source, role (original/mirror/excerpt/dub/unknown), transcript status, and retrieval provenance.
- `catalog/appearances.jsonl`: one public event or appearance; multiple uploads may refer to one appearance.
- `catalog/provenance.jsonl`: append-only discovery and ingestion events.
- `transcripts/metadata/`: rights and availability notes, not transcript text.
- `reports/coverage.md`: generated coverage and backlog snapshot.
- `reports/coverage.json`: machine-readable counts and uncertainty.
- `catalog/source_state.json`: per-source checkpoint and retry time.

Records with unknown details remain explicitly unknown. Never infer event dates from upload dates or treat duplicate uploads as separate appearances without evidence.

## Commands

```text
levinverse discover [--source URL] [--limit N]
levinverse ingest [--captions] [--limit N] [--delay SECONDS]
levinverse report
```

Set `LEVINVERSE_USER_AGENT` to identify a responsible crawler. Network failures are recorded and retried with bounded exponential backoff on later runs. No background worker is configured or started.

## Research policy

Claims, interpretations, and hypotheses belong in separate records. Every claim should link to a source and time range and be labeled as empirical, interpretive, or speculative. Mathematical extensions developed here must not be attributed to Levin without a primary-source citation.
