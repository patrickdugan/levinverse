"""Offline tests for Levinverse evaluation data."""
import json
import tempfile
import unittest
from pathlib import Path
from evals.validate import CASE, jsonl, validate


class EvalTests(unittest.TestCase):
    def test_fixture(self):
        self.assertEqual(validate(), {"claims": 28, "corrections": 16, "questions": 16})

    def test_all_claims_pending_audio(self):
        self.assertTrue(all(not c["audio_verified"] for c in jsonl(CASE / "claims.jsonl")))

    def test_speculation_classified(self):
        cs = jsonl(CASE / "claims.jsonl")
        self.assertGreaterEqual(sum(c["kind"] == "speculative_metaphysics" for c in cs), 2)

    def test_source_training_exclusion(self):
        src = json.loads((CASE / "source.json").read_text(encoding="utf-8"))["source"]
        self.assertTrue(src["training_exclusion"])
        self.assertFalse(src["publication"]["full_transcript_in_repo"])

    def test_invalid_claim_ref_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp)
            for name in ("source.json", "claims.jsonl", "corrections.jsonl", "questions.jsonl"):
                (case / name).write_bytes((CASE / name).read_bytes())
            questions = jsonl(case / "questions.jsonl")
            questions[0]["required_claim_ids"] = ["HPL26-C999"]
            (case / "questions.jsonl").write_text(
                "\n".join(json.dumps(q) for q in questions) + "\n", encoding="utf-8"
            )
            with self.assertRaises(AssertionError):
                validate(case=case)

    def test_sha_shape(self):
        src = json.loads((CASE / "source.json").read_text(encoding="utf-8"))["source"]
        sha = src["provenance"]["sha256"]
        self.assertEqual(len(sha), 64)
        self.assertTrue(all(x in "0123456789abcdef" for x in sha))


if __name__ == "__main__":
    unittest.main()
