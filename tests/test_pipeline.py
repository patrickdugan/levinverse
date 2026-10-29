from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from levinverse.discover import discover, parse_index, youtube_id, yt_dlp_metadata
from levinverse.ingest import ingest
from levinverse.report import generate_report
from levinverse.store import read_jsonl, upsert
from levinverse.transcribe import transcribe_media


class PipelineTests(unittest.TestCase):
    def test_youtube_id_variants(self):
        self.assertEqual(youtube_id("https://youtu.be/abcdefghijk"), "abcdefghijk")
        self.assertEqual(youtube_id("https://www.youtube.com/watch?v=abcdefghijk"), "abcdefghijk")
        self.assertIsNone(youtube_id("https://example.org/watch?v=abcdefghijk"))

    def test_parse_curated_index(self):
        html = b'<ul><li><a href="https://youtu.be/abcdefghijk">Talk title</a> (1 hour 20 minutes) (Host | March 2, 2024)</li></ul>'
        rows = parse_index(html, "https://example.org/index", "2026-01-01T00:00:00+00:00")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["publication_date"], "2024-03-02")
        self.assertEqual(rows[0]["duration_seconds"], 4800)
        self.assertEqual(rows[0]["host"], "Host")

    def test_upsert_is_idempotent(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            path = Path(folder) / "rows.jsonl"
            record = {"id": "one", "value": 1}
            self.assertEqual(upsert(path, [record], "id"), 1)
            self.assertEqual(upsert(path, [record], "id"), 0)
            self.assertEqual(read_jsonl(path), [record])

    def test_ytdlp_metadata_is_metadata_only(self):
        completed = type("Completed", (), {"returncode": 0, "stdout": '{"id":"abcdefghijk","webpage_url":"https://www.youtube.com/watch?v=abcdefghijk","title":"Talk","upload_date":"20250302","duration":120,"channel":"Host","subtitles":{"en":[]},"automatic_captions":{}}', "stderr": ""})()
        with patch("levinverse.discover.shutil.which", return_value="yt-dlp"), patch("levinverse.discover.subprocess.run", return_value=completed) as run:
            metadata = yt_dlp_metadata("https://youtu.be/abcdefghijk")
        self.assertEqual(metadata["publication_date"], "2025-03-02")
        self.assertEqual(metadata["duration_seconds"], 120)
        self.assertIn("--skip-download", run.call_args.args[0])

    def test_discovery_records_source_failure_checkpoint(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            with patch("levinverse.discover.fetch", side_effect=URLError("offline")):
                found, added = discover(root, "https://example.org/index")
            self.assertEqual((found, added), (0, 0))
            state = __import__("json").loads((root / "catalog/source_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["https://example.org/index"]["status"], "failed")
            self.assertTrue(state["https://example.org/index"]["retry_after"])

    def test_discovery_limit_bounds_batch_size(self):
        page = b'<ul><li><a href="https://youtu.be/abcdefghijk">First</a> (Host | March 2, 2024)</li><li><a href="https://youtu.be/lmnopqrstuv">Second</a> (Host | March 3, 2024)</li></ul>'
        with tempfile.TemporaryDirectory(dir="tests") as folder, patch("levinverse.discover.fetch", return_value=page):
            found, added = discover(Path(folder), "https://example.org/index", limit=1)
            self.assertEqual((found, added), (1, 1))
            self.assertEqual(len(read_jsonl(Path(folder) / "catalog/videos.jsonl")), 1)

    def test_caption_storage_requires_source_authorization(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            record = {"video_id": "abcdefghijk", "canonical_url": "https://youtu.be/abcdefghijk", "transcript_status": "unknown"}
            upsert(root / "catalog/videos.jsonl", [record], "video_id")
            result = ingest(root, captions=True, delay=0, store_captions=True)
            self.assertEqual(result["rights_skipped"], 1)
            saved = read_jsonl(root / "catalog/videos.jsonl")[0]
            self.assertEqual(saved["ingest"]["status"], "rights_review_required")

    def test_authorized_caption_download_is_local_and_checkpointed(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            record = {"video_id": "abcdefghijk", "canonical_url": "https://youtu.be/abcdefghijk", "transcript_status": "available_metadata_only", "caption_storage_authorized": True}
            upsert(root / "catalog/videos.jsonl", [record], "video_id")

            def fake_download(command, **kwargs):
                output_template = Path(command[command.index("-o") + 1])
                caption = Path(str(output_template).replace("%(id)s", "abcdefghijk").replace("%(language)s", "en").replace("%(ext)s", "vtt"))
                caption.parent.mkdir(parents=True, exist_ok=True)
                caption.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nExample\n", encoding="utf-8")
                return type("Completed", (), {"returncode": 0, "stderr": "", "stdout": ""})()

            with patch("levinverse.ingest.shutil.which", return_value="yt-dlp"), patch("levinverse.ingest.subprocess.run", side_effect=fake_download):
                result = ingest(root, captions=True, delay=0, store_captions=True)
            self.assertEqual(result["acquired"], 1)
            saved = read_jsonl(root / "catalog/videos.jsonl")[0]
            self.assertEqual(saved["transcript_status"], "captions_stored_locally")
            self.assertTrue((root / saved["transcript_path"]).exists())

    def test_whisper_rejects_unpermitted_media(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            media = root / "media/permitted/sample.wav"
            media.parent.mkdir(parents=True)
            media.write_bytes(b"placeholder")
            with self.assertRaises(PermissionError):
                transcribe_media(media, root, {"permission_confirmed": False})

    def test_caption_rate_limit_checkpoints_and_stops_batch(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            ids = ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]
            upsert(root / "catalog/videos.jsonl", [{"video_id": v, "canonical_url": f"https://youtu.be/{v}", "caption_storage_authorized": True} for v in ids], "video_id")
            def request(command, **kwargs):
                if ids[0] in command[-1]:
                    template = command[command.index("-o") + 1]
                    target = Path(template.replace("%(id)s", ids[0]).replace("%(language)s", "en").replace("%(ext)s", "vtt"))
                    target.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nExample\n", encoding="utf-8")
                    return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()
                return type("Result", (), {"returncode": 1, "stderr": "HTTP Error 429: Too Many Requests", "stdout": ""})()
            with patch("levinverse.ingest.shutil.which", return_value="yt-dlp"), patch("levinverse.ingest.subprocess.run", side_effect=request) as run:
                result = ingest(root, captions=True, store_captions=True, delay=0)
            self.assertEqual(2, run.call_count)
            self.assertEqual(1, result["acquired"])
            rows = {r["video_id"]: r for r in read_jsonl(root / "catalog/videos.jsonl")}
            self.assertEqual("acquired", rows[ids[0]]["ingest"]["status"])
            self.assertNotIn("ingest", rows[ids[2]])
            self.assertTrue((root / "catalog/provider-state.json").is_file())

    def test_report_does_not_overclaim(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            (root / "catalog").mkdir()
            (root / "reports").mkdir()
            (root / "catalog/videos.jsonl").write_text('{"video_id":"x","transcript_status":"unknown"}\n', encoding="utf-8")
            (root / "catalog/appearances.jsonl").write_text('{"appearance_id":"x"}\n', encoding="utf-8")
            report = generate_report(root)
            self.assertIn("not a completeness claim", report)
            self.assertIn("**1**", report)
            self.assertTrue((root / "reports/coverage.json").exists())


if __name__ == "__main__":
    unittest.main()
