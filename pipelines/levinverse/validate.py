"""Validate corpus artifacts and provenance without making scientific truth claims."""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .store import read_jsonl


def validate(root: Path) -> dict:
    errors = []
    files = list((root / "catalog").glob("*.jsonl"))
    for path in files:
        try:
            read_jsonl(path)
        except (ValueError, OSError) as exc:
            errors.append(str(exc))
    videos = read_jsonl(root / "catalog/videos.jsonl")
    if len(videos) != len({v["video_id"] for v in videos}):
        errors.append("Duplicate video IDs in catalog")
    for video in videos:
        ident = video["video_id"]
        parsed = urlparse(video.get("canonical_url", ""))
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", ident) or parse_qs(parsed.query).get("v", [None])[0] != ident:
            errors.append("Invalid canonical YouTube identity: " + ident)
    stored = 0
    registered_paths = set()
    for record in read_jsonl(root / "catalog/transcripts.jsonl"):
        if record.get("status") != "stored":
            continue
        stored += 1
        path = (root / record.get("text_path", "MISSING")).resolve()
        if not path.is_relative_to((root / "transcripts/permitted").resolve()) or not path.is_file():
            errors.append("Missing or out-of-root transcript: " + record["transcript_id"])
            continue
        text = path.read_text(encoding="utf-8")
        registered_paths.add(path)
        if hashlib.sha256(text.encode()).hexdigest() != record.get("text_sha256"):
            errors.append("Text checksum mismatch: " + record["transcript_id"])
        if not record.get("source_url") or not record.get("authorization_basis"):
            errors.append("Missing source or authorization: " + record["transcript_id"])
    texts = list((root / "transcripts/permitted").glob("*.txt"))
    for path in texts:
        if not path.with_suffix(".json").is_file():
            errors.append("Missing structured companion: " + path.name)
        if path.resolve() not in registered_paths:
            errors.append("Transcript text has no stored source record: " + path.name)
    asr = 0
    overlaps = 0
    maximum_overlap = 0.0
    for path in (root / "transcripts/permitted").glob("*.whisper.json"):
        asr += 1
        data = json.loads(path.read_text(encoding="utf-8"))
        previous_start = -1
        previous_end = 0
        for segment in data["segments"]:
            if not (0 <= segment["start"] <= segment["end"] <= data["duration_seconds"] + 1) or segment["start"] < previous_start - 0.2:
                errors.append("Invalid ASR timing: " + path.name)
                break
            overlap = previous_end - segment["start"]
            if overlap > 0.001:
                overlaps += 1
                maximum_overlap = max(maximum_overlap, overlap)
            previous_start, previous_end = segment["start"], segment["end"]
            if any(not (0 <= w["start"] <= w["end"] <= data["duration_seconds"] + 1) for w in segment.get("words", [])):
                errors.append("Invalid word timing: " + path.name)
        if data.get("device") != "cuda" or not data.get("runtime_versions"):
            errors.append("Missing CUDA/runtime provenance: " + path.name)
    for path in files:
        text = path.read_text(encoding="utf-8")
        if re.search(r"[?&](?:X-Amz-Security-Token|X-Amz-Signature|access_token)=", text, re.I):
            errors.append("Ephemeral token URL in public metadata: " + path.name)
    result = {"valid": not errors, "catalog_jsonl_files_checked": len(files), "unique_video_ids": len({v["video_id"] for v in videos}), "stored_transcript_source_records_checked": stored, "text_files_checked": len(texts), "cuda_transcripts_checked": asr, "overlapping_asr_segment_boundaries": overlaps, "max_asr_segment_overlap_seconds": round(maximum_overlap, 3), "timing_note": "Source ASR boundary overlaps are retained; start order and duration bounds are validated without claiming diarization or human accuracy.", "errors": errors}
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / "reports/validation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = validate(args.root.resolve())
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["valid"] else 1)
