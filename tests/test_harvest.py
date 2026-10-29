import json
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path

from levinverse.harvest import merge_video, parse_podcast, parse_publisher, save_transcript
from levinverse.report import generate_report
from levinverse.store import read_jsonl
from levinverse.publishers import extract, transcript_link


@unittest.skipUnless(find_spec("bs4"), "install the collector extra")
class HarvestTests(unittest.TestCase):
    def test_timestamp_links_select_episode_not_related_video(self):
        html = b'''<script type="application/ld+json">{"@type":"PodcastEpisode","name":"Test talk","datePublished":"2025-01-02"}</script><article><header><a href="/tag/michael-levin-s-talks">Michael Levin's talks</a></header><div><a href="https://youtu.be/related0001">Related talk</a><h2>Transcript</h2><p><a href="https://youtube.com/watch?v=abcdefghijk&amp;t=62s">[01:02]</a> Example text.</p></div></article>'''
        item = parse_podcast(html, "https://example.org/episode")
        self.assertTrue(item["relevance_confirmed"])
        self.assertEqual(["abcdefghijk"], item["video_ids"])
        self.assertEqual(62, item["segments"][0]["start_seconds"])
        self.assertIsNone(item["segments"][0]["speaker"])

    def test_lex_retains_speakers_and_short_turn_timestamps(self):
        html = b'''<h1>Site name</h1><article><h1>Interview title</h1><div class="entry-content"><div class="ts-segment"><span class="ts-name">Michael Levin</span><span class="ts-timestamp">(01:02:03)</span><span class="ts-text">Example.</span></div></div></article>'''
        item = parse_publisher(html, "https://lexfridman.com/test")
        self.assertEqual("Interview title", item["title"])
        self.assertEqual({"speaker": "Michael Levin", "start_seconds": 3723, "text": "Example."}, item["segments"][0])

    def test_storage_gating_and_exact_duplicate_source(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            item = {"source_url": "https://example.org/a", "title": "Example", "video_ids": [], "segments": [{"text": "A transcript paragraph.", "speaker": None, "start_seconds": 0}], "relevance_confirmed": True}
            self.assertEqual("available_metadata_only", save_transcript(root, item, None)["status"])
            self.assertFalse(list(root.rglob("*.txt")))
            first = save_transcript(root, item, "Fixture permission")
            second = save_transcript(root, {**item, "source_url": "https://example.org/b"}, "Fixture permission")
            self.assertEqual(first["transcript_id"], second["duplicate_of"])
            self.assertEqual(1, len(list(root.rglob("*.txt"))))

    def test_rediscovery_preserves_permissions_and_ingest_checkpoints(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            merge_video(root, {"video_id": "abcdefghijk", "title": "Known", "publication_date": "2025-01-02", "ingest": {"retry_after": "future"}, "transcript_path": "saved.txt"}, True)
            merge_video(root, {"video_id": "abcdefghijk", "title": "New source title", "publication_date": None})
            saved = read_jsonl(root / "catalog/videos.jsonl")[0]
            self.assertEqual("2025-01-02", saved["publication_date"])
            self.assertEqual("saved.txt", saved["transcript_path"])
            self.assertTrue(saved["caption_storage_authorized"])
            self.assertEqual({"retry_after": "future"}, saved["ingest"])

    def test_report_counts_actual_text_and_does_not_infer_missing_captions(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            merge_video(root, {"video_id": "abcdefghijk", "transcript_status": "unavailable"})
            output = root / "transcripts/permitted"
            output.mkdir(parents=True)
            (output / "source.txt").write_text("A source transcript.", encoding="utf-8")
            generate_report(root)
            report = json.loads((root / "reports/coverage.json").read_text())
            self.assertEqual(1, report["transcripts_stored_locally"])
            self.assertEqual(0, report["caption_availability_confirmed_missing"])

    def test_plain_article_is_not_collected_as_speech(self):
        raw = ("<article><h1>Michael Levin profile</h1><p>" + "Ordinary article prose. " * 350 + "</p></article>").encode()
        self.assertIsNone(extract(raw, {"source_url": "https://example.org/profile", "title": "Profile"}))

    def test_transcript_link_filter_excludes_navigation_and_related_cards(self):
        from bs4 import BeautifulSoup
        doc = BeautifulSoup('<a href="/all">All transcripts</a><a href="/unrelated">' + 'Other episode text ' * 10 + ' Transcript</a><a href="/specific">Download transcript</a>', "html.parser")
        links = [transcript_link(a, "https://example.org/episode") for a in doc.find_all("a")]
        self.assertEqual([None, None, "https://example.org/specific"], links)


if __name__ == "__main__":
    unittest.main()
