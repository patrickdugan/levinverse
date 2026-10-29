"""Validate the first Levinverse text-audited evaluation fixture."""
import argparse
import hashlib
import json
from pathlib import Path

CASE = Path(__file__).resolve().parent / "hpl_2026_10_28"
KINDS = {
    "operational_definition", "methodological_position", "theoretical_interpretation",
    "empirical_report", "conceptual_taxonomy", "philosophical_argument",
    "speculative_metaphysics", "first_person_report", "historical_reference",
}
MODES = {"source_fidelity", "boundary_check", "transfer", "adversarial"}


def jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def validate(case=CASE, source=None):
    meta = json.loads((case / "source.json").read_text(encoding="utf-8"))
    src = meta["source"]
    claims = jsonl(case / "claims.jsonl")
    corrections = jsonl(case / "corrections.jsonl")
    questions = jsonl(case / "questions.jsonl")
    assert src["training_exclusion"] is True
    assert src["provenance"]["media_playback_verification"] == "pending"
    assert src["publication"]["full_transcript_in_repo"] is False
    assert meta["record_counts"] == {
        "claims": len(claims),
        "transcript_correction_candidates": len(corrections),
        "questions": len(questions),
    }
    claim_ids = [c["id"] for c in claims]
    assert len(claim_ids) == len(set(claim_ids))
    for c in claims:
        assert c["source_id"] == src["id"]
        assert c["kind"] in KINDS
        assert c["speaker"] == "Michael Levin"
        assert isinstance(c["start_s"], int) and 0 <= c["start_s"] < c["end_s"] <= 3750
        assert c["text_reviewed"] is True and c["audio_verified"] is False
        assert c["scientifically_independently_verified"] is False
        assert len(c["paraphrase"]) > 40 and c["boundary"]
    correction_ids = [n["id"] for n in corrections]
    assert len(correction_ids) == len(set(correction_ids))
    for n in corrections:
        assert n["source_id"] == src["id"]
        assert 0 <= n["near_s"] < 3750
        assert n["recognized"] and n["normalization_or_note"]
        assert n["status"] in {
            "text_level_candidate_audio_pending", "audio_review_required",
            "factual_note_not_transcript_edit",
        }
    question_ids = [q["id"] for q in questions]
    assert len(question_ids) == len(set(question_ids))
    for q in questions:
        assert q["source_id"] == src["id"]
        assert q["mode"] in MODES
        assert q["required_claim_ids"]
        assert set(q["required_claim_ids"]).issubset(set(claim_ids))
        assert q["prompt"] and q["required_elements"] and q["critical_failure"]
        assert q["audio_verified"] is False
    if source is not None:
        digest = hashlib.sha256(Path(source).read_bytes()).hexdigest()
        expected = src["provenance"]["sha256"]
        assert digest == expected, f"source fingerprint mismatch: {digest} != {expected}"
    return {"claims": len(claims), "corrections": len(corrections), "questions": len(questions)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(source=args.source), indent=2))


if __name__ == "__main__":
    main()
