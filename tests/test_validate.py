import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from levinverse.store import upsert
from levinverse.validate import validate
from levinverse.report import generate_report


class ValidationTests(unittest.TestCase):
    def fixture(self, root, segments):
        path = root / "transcripts/permitted/fixture.whisper.txt"
        path.parent.mkdir(parents=True)
        text = "Fixture speech.\n"
        path.write_text(text, encoding="utf-8")
        path.with_suffix(".json").write_text(json.dumps({"segments": segments, "duration_seconds": 3, "device": "cuda", "runtime_versions": {"av": "fixture"}}))
        upsert(root / "catalog/transcripts.jsonl", [{"transcript_id": "fixture", "status": "stored", "text_path": path.relative_to(root).as_posix(), "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "source_url": "https://example.org/episode", "authorization_basis": "Fixture permission"}], "transcript_id")

    def test_small_asr_boundary_overlap_is_retained_and_reported(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            self.fixture(root, [{"start": 0, "end": 2}, {"start": 1.77, "end": 3}])
            result = validate(root)
            self.assertTrue(result["valid"])
            self.assertEqual(1, result["overlapping_asr_segment_boundaries"])
            self.assertEqual(0.23, result["max_asr_segment_overlap_seconds"])

    def test_reversed_segment_order_is_rejected(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            self.fixture(root, [{"start": 1, "end": 2}, {"start": 0, "end": 1}])
            self.assertFalse(validate(root)["valid"])

    def test_unregistered_text_cannot_inflate_verified_coverage(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            path = root / "transcripts/permitted/orphan.txt"
            path.parent.mkdir(parents=True)
            path.write_text("Unregistered text")
            path.with_suffix(".json").write_text("{}")
            self.assertFalse(validate(root)["valid"])

    def test_retained_review_text_is_validated_but_excluded_from_coverage(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            self.fixture(root, [{"start": 0, "end": 1}])
            path = root / "transcripts/permitted/commentary.txt"
            text = "A discussion requiring participation review.\n"
            path.write_text(text, encoding="utf-8")
            path.with_suffix(".json").write_text("{}")
            upsert(root / "catalog/transcripts.jsonl", [{"transcript_id": "review", "status": "participation_review_required", "text_path": path.relative_to(root).as_posix(), "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "source_url": "https://example.org/review", "authorization_basis": "Fixture permission"}], "transcript_id")
            result = validate(root)
            generate_report(root)
            coverage = json.loads((root / "reports/coverage.json").read_text(encoding="utf-8"))
            self.assertTrue(result["valid"])
            self.assertEqual(1, result["review_transcript_source_records_checked"])
            self.assertEqual(2, coverage["transcript_text_files_retained_total"])
            self.assertEqual(1, coverage["transcript_text_files_requiring_participation_review"])
            self.assertEqual(1, coverage["transcripts_stored_locally"])


if __name__ == "__main__":
    unittest.main()
