import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from levinverse.audio import download, run, worker_lock
from levinverse.store import read_jsonl, upsert


class AudioTests(unittest.TestCase):
    def test_one_audio_worker_per_corpus_and_lock_releases(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            with worker_lock(root):
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    with worker_lock(root):
                        self.fail("Second worker acquired the lock")
            with worker_lock(root):
                pass

    def test_two_recordings_referencing_one_upload_use_separate_cache_files(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            media = root / "media/permitted"
            media.mkdir(parents=True)
            for ident in ("first", "second"):
                (media / (ident + ".mp3")).write_bytes(ident.encode())
            with patch("urllib.request.urlopen", side_effect=AssertionError("Cache should be used")):
                files = [download({"job_id": ident, "video_id": "abcdefghijk", "audio_url": "https://example.org/" + ident + ".mp3"}, root) for ident in ("first", "second")]
            self.assertNotEqual(files[0], files[1])
            self.assertEqual([b"first", b"second"], [p.read_bytes() for p in files])

    def test_identical_audio_reuses_text_and_resumes_without_gpu(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            (root / "config").mkdir()
            (root / "config/permissions.json").write_text(json.dumps({"audio_processing_authorized": True, "transcript_storage_authorized": True, "authorization_basis": "Fixture permission"}))
            media = root / "media/permitted/second.mp3"
            media.parent.mkdir(parents=True)
            media.write_bytes(b"identical audio fixture")
            text = root / "transcripts/permitted/first.whisper.txt"
            text.parent.mkdir(parents=True)
            text.write_text("[0.00 --> 1.00] Fixture speech.\n", encoding="utf-8")
            text.with_suffix(".json").write_text(json.dumps({"segments": [{"start": 0, "end": 1, "text": "Fixture speech."}], "model": "turbo", "device": "cuda", "language": "en", "duration_seconds": 1}))
            digest = hashlib.sha256(media.read_bytes()).hexdigest()
            upsert(root / "catalog/audio-queue.jsonl", [
                {"job_id": "first", "status": "transcribed", "media_sha256": digest, "transcript_path": text.relative_to(root).as_posix()},
                {"job_id": "second", "status": "pending", "media_id": "second", "title": "Example", "source_url": "https://example.org/second", "audio_url": "https://example.org/second.mp3"},
            ], "job_id")
            with patch("levinverse.audio.transcribe_media", side_effect=AssertionError("Duplicate must not use GPU")):
                result = run(root, model="large-v3")
                repeated = run(root)
            self.assertEqual({"attempted": 1, "transcribed": 0, "reused": 1, "failed": 0}, result)
            self.assertEqual(0, repeated["attempted"])
            record = read_jsonl(root / "catalog/transcripts.jsonl")[0]
            self.assertEqual("whisper-first", record["duplicate_of"])
            self.assertEqual("turbo", record["model"])
            self.assertEqual("duplicate_reused", read_jsonl(root / "catalog/audio-queue.jsonl")[1]["status"])
            self.assertEqual("completed", json.loads((root / "reports/audio-worker.json").read_text())["status"])


if __name__ == "__main__":
    unittest.main()
