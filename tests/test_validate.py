import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from levinverse.store import upsert
from levinverse.validate import validate


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


if __name__ == "__main__":
    unittest.main()
