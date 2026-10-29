import hashlib
import json
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch

from levinverse.feeds import collect, episode_duration, episode_source, match_video, parse_srt, publisher_title_match, stored_episode
from levinverse.fallbacks import parse_podscripts
from levinverse.podcast_audio import resolve
from levinverse.directory import classify
from levinverse.harvest import render_transcript, save_transcript
from levinverse.platforms import collect as collect_platforms
from levinverse.reconcile import reconcile, title_contains_video_title
from levinverse.store import read_jsonl, upsert


@unittest.skipUnless(find_spec("bs4"), "install the collector extra")
class SourceTests(unittest.TestCase):
    def test_render_preserves_source_labels_without_duplicating_them(self):
        self.assertEqual("[00:00] Michael Levin: Source words.\n", render_transcript([{"speaker": "Michael Levin", "text": "[00:00] Michael Levin: Source words."}]))
        self.assertEqual("Michael Levin: Source words.\n", render_transcript([{"speaker": "Michael Levin", "text": "Source words."}]))

    def test_a_page_without_text_keeps_previously_stored_video_coverage(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            item = {"source_url": "https://example.org/transcript", "title": "Michael Levin", "video_ids": ["abcdefghijk"], "segments": [{"text": "Source words.", "speaker": None}], "relevance_confirmed": True, "relevance_evidence": "Fixture"}
            saved = save_transcript(root, item, "Fixture permission")
            save_transcript(root, {**item, "source_url": "https://example.org/older-page", "segments": []}, "Fixture permission")
            video = read_jsonl(root / "catalog/videos.jsonl")[0]
            self.assertEqual("publisher_transcript_stored", video["transcript_status"])
            self.assertEqual(saved["text_path"], video["transcript_path"])

    def test_native_caption_is_stored_without_fabricating_a_youtube_identity(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            (root / "config").mkdir()
            (root / "config/permissions.json").write_text(json.dumps({"transcript_storage_authorized": True, "authorization_basis": "Fixture permission"}))
            source = {"platform": "kaltura", "media_id": "1_fixture", "source_url": "https://university.example.org/lecture", "extractor_url": "kaltura:1:1_fixture", "host": "University", "participation_evidence_url": "https://example.org/official-index"}
            (root / "config/external-platforms.json").write_text(json.dumps({"sources": [source]}))
            info = {"id": "1_fixture", "title": "Michael Levin lecture", "duration": 60, "subtitles": {"en": [{"ext": "srt", "url": "https://university.example.org/captions.srt"}]}}
            class Client:
                def get(self, url):
                    return b"1\n00:00:00,000 --> 00:00:01,000\nFixture speech.\n\n"
            with patch("levinverse.platforms.metadata", return_value=info):
                result = collect_platforms(root, Client())
            self.assertEqual(1, result["captions_stored"])
            self.assertEqual([], read_jsonl(root / "catalog/videos.jsonl"))
            self.assertEqual("kaltura:1_fixture", read_jsonl(root / "catalog/external-media.jsonl")[0]["recording_id"])
    def test_directory_rejects_political_names_and_unverified_mentions(self):
        self.assertEqual("unrelated_name", classify({"trackName": "Mike Levin - United States Congressman"}, set(), {})[0])
        self.assertEqual("unrelated_name", classify({"trackName": "A Coequal Branch (feat. Rep. Mike Levin)", "description": "Unrelated news about Tufts"}, set(), {})[0])
        self.assertEqual("participation_review_required", classify({"trackName": "Reaction to Michael Levin: Bioelectricity", "description": "Michael Levin researches bioelectricity at Tufts"}, set(), {})[0])
        self.assertEqual("participation_review_required", classify({"trackName": "Michael Levin's Unseen World", "description": "A discussion of bioelectricity"}, set(), {})[0])
        self.assertEqual("reference_review_required", classify({"trackName": "Another guest", "description": "Michael Levin at Tufts"}, set(), {})[0])
        self.assertEqual("subject_identity_review_required", classify({"trackName": "Michael Levin interview"}, set(), {})[0])
        self.assertEqual("subject_confirmed", classify({"trackName": "Michael Levin interview", "description": "Professor of biology at Tufts"}, set(), {})[0])

    def test_srt_preserves_times_and_does_not_guess_speakers(self):
        segments = parse_srt(b"1\n00:00:01,500 --> 00:00:02,750\nA &amp; B.\n\n")
        self.assertEqual({"start_seconds": 1.5, "end_seconds": 2.75, "text": "A & B.", "speaker": None}, segments[0])

    def test_rss_duration_handles_clock_and_numeric_formats(self):
        from xml.etree import ElementTree as ET
        for value, expected in [("01:02:03", 3723), ("62:03", 3723), ("3723", 3723), ("unknown", None)]:
            self.assertEqual(expected, episode_duration(ET.fromstring(f'<item xmlns:i="https://example.org"><i:duration>{value}</i:duration></item>')))

    def test_shared_channel_link_does_not_clobber_episode_identity(self):
        feed = "https://example.org/rss"
        channel = "https://youtube.com/TheoriesOfEverything"
        self.assertNotEqual(episode_source(feed, "one", channel), episode_source(feed, "two", channel))
        self.assertNotEqual(episode_source(feed, "one", "https://example.org/podcast/"), episode_source(feed, "two", "https://example.org/podcast/"))

    def test_related_video_links_require_specific_title_match(self):
        known = {"primary": {"title": "Michael Levin Karl Friston Chris Fields on The Meta Hard Problem"}, "related": {"title": "Michael Levin on Morphogenetics and Xenobots"}}
        self.assertEqual("primary", match_video("Michael Levin, Karl Friston, Chris Fields: The Meta-Hard Problem", ["primary", "related"], known))
        self.assertIsNone(match_video("Michael Levin: A different conversation", ["primary", "related"], known))

    def test_publisher_title_matching_requires_title_and_publisher_evidence(self):
        known = {"match": {"title": "Mark Solms and Michael Levin discuss Consciousness, Cognition and Opponent Processing", "host": "Podcast: The Meaning Code"}}
        self.assertEqual("match", publisher_title_match("Dr. Michael Levin and Dr. Mark Solms on Consciousness, Cognition and Opponent Processing", "The Meaning Code", known))
        self.assertIsNone(publisher_title_match("Michael Levin on another topic", "The Meaning Code", known))
        self.assertIsNone(publisher_title_match("Dr. Michael Levin and Mark Solms on Consciousness, Cognition and Opponent Processing", "Different publisher", known))

    def test_title_reconciliation_requires_the_distinctive_whole_video_title(self):
        self.assertTrue(title_contains_video_title("187 - Michael Levin: The New Era of Cognitive Biorobotics", "The New Era of Cognitive Biorobotics"))
        self.assertFalse(title_contains_video_title("Michael Levin on Cognitive Biorobotics", "The New Era of Cognitive Biorobotics"))

    def test_stored_episode_links_only_a_matching_publisher_and_title(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            text = root / "transcripts/permitted/fixture.txt"
            text.parent.mkdir(parents=True)
            text.write_text("Fixture speech.", encoding="utf-8")
            video = {"video_id": "abcdefghijk", "canonical_url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "The New Era of Cognitive Biorobotics", "host": "Robinson's Podcast"}
            upsert(root / "catalog/videos.jsonl", [video], "video_id")
            episode = {"episode_id": "episode-1", "source_url": "https://example.org/episode", "feed_url": "https://example.org/feed", "title": "187 - Michael Levin: The New Era of Cognitive Biorobotics", "show": "Robinson's Podcast"}
            upsert(root / "catalog/rss-episodes.jsonl", [episode], "episode_id")
            upsert(root / "catalog/transcripts.jsonl", [{"transcript_id": "whisper-episode-1", "source_url": episode["source_url"], "status": "stored", "text_path": text.relative_to(root).as_posix(), "video_ids": [], "source_kind": "local_whisper"}], "transcript_id")
            self.assertEqual(1, reconcile(root)["inferred_video_links"])
            self.assertEqual(0, reconcile(root)["inferred_video_links"])
            self.assertEqual(["abcdefghijk"], read_jsonl(root / "catalog/transcripts.jsonl")[0]["video_ids"])
            self.assertEqual("publisher_and_title_match", read_jsonl(root / "catalog/videos.jsonl")[0]["transcript_video_link_method"])

    def test_existing_episode_match_requires_publisher_or_identical_enclosure(self):
        record = {"transcript_id": "fixture", "source_url": "https://publisher.org/transcript", "title": "Michael Levin on Growth Form Information Cognition and Self", "audio_url": "https://media.example.org/one.mp3"}
        self.assertIs(record, stored_episode("Michael Levin on Growth Form Information Cognition and Self", "https://another.org/episode", "", {"transcript_publisher_domains": ["publisher.org"]}, [record]))
        self.assertIsNone(stored_episode(record["title"], "https://another.org/episode", "", {}, [record]))
        self.assertIs(record, stored_episode("A retitled episode", "https://another.org/episode", record["audio_url"], {}, [record]))

    def test_source_matching_keeps_episode_fragments_and_video_query_ids(self):
        for first, second in [("https://example.org/feed#episode=one", "https://example.org/feed#episode=two"), ("https://www.youtube.com/watch?v=abcdefghijk", "https://www.youtube.com/watch?v=lmnopqrstuv")]:
            record = {"source_url": first, "title": "Different event"}
            self.assertIsNone(stored_episode("New event", second, "", {}, [record]))
        record = {"source_url": "https://example.org/episode/", "title": "Known event"}
        self.assertIs(record, stored_episode("Known event", "https://example.org/episode?utm_source=rss", "", {}, [record]))

    def test_rss_caption_track_is_saved_and_pending_audio_is_skipped(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            (root / "config").mkdir()
            (root / "config/permissions.json").write_text(json.dumps({"transcript_storage_authorized": True, "audio_processing_authorized": True, "authorization_basis": "Fixture permission"}))
            feed = "https://example.org/rss"
            track = "https://example.org/transcript.srt"
            (root / "config/podcast-feeds.json").write_text(json.dumps({"feeds": [{"show": "Example", "url": feed}]}))
            upsert(root / "catalog/videos.jsonl", [{"video_id": "abcdefghijk", "canonical_url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "Original title"}], "video_id")
            ident = "rss-" + hashlib.sha256((feed + "episode-guid").encode()).hexdigest()[:16]
            upsert(root / "catalog/audio-queue.jsonl", [{"job_id": ident, "status": "pending"}], "job_id")
            rss = f'<rss xmlns:podcast="https://podcastindex.org/namespace/1.0"><channel><item><title>Michael Levin on bioelectricity</title><guid>episode-guid</guid><link>https://example.org/episode</link><description>https://youtu.be/abcdefghijk</description><enclosure url="https://example.org/audio.mp3"/><podcast:transcript url="{track}" type="application/x-subrip"/></item></channel></rss>'.encode()
            class Client:
                def get(self, url):
                    return rss if url == feed else b"1\n00:00:00,000 --> 00:00:01,000\nFixture speech.\n\n"
            result = collect(root, Client())
            self.assertEqual(1, result["captions_stored"])
            self.assertEqual(0, result["audio_queued"])
            self.assertEqual("covered_by_stored_transcript", read_jsonl(root / "catalog/audio-queue.jsonl")[0]["status"])
            self.assertEqual("Original title", read_jsonl(root / "catalog/videos.jsonl")[0]["title"])

    def test_rss_commentary_is_kept_for_review_without_queueing_audio(self):
        with tempfile.TemporaryDirectory(dir="tests") as folder:
            root = Path(folder)
            (root / "config").mkdir()
            (root / "config/permissions.json").write_text(json.dumps({"transcript_storage_authorized": True, "audio_processing_authorized": True, "authorization_basis": "Fixture permission"}))
            feed = "https://example.org/rss"
            (root / "config/podcast-feeds.json").write_text(json.dumps({"feeds": [{"show": "Example", "url": feed}]}))
            class Client:
                def get(self, url):
                    return b'<rss><channel><item><title>Reaction to Michael Levin and bioelectricity</title><guid>commentary-1</guid><enclosure url="https://example.org/audio.mp3"/></item></channel></rss>'
            collect(root, Client())
            self.assertEqual([], read_jsonl(root / "catalog/audio-queue.jsonl"))
            self.assertEqual("participation_review_required", read_jsonl(root / "catalog/rss-episodes.jsonl")[0]["status"])

    def test_fallback_uses_published_group_clock_not_guessed_element_ids(self):
        groups = ''.join(f'<div class="single-sentence"><span class="pod_timestamp_indicator">Starting point is 00:00:{i:02d}</span><span class="transcript-text" id="sentenceid_{i + 1}">Fixture text.</span></div>' for i in range(20))
        raw = ('<h1>#325 Michael Levin</h1><div class="podcast-transcript">' + groups + '</div>').encode()
        item = parse_podscripts(raw, {"episode_number": "325", "source_url": "https://example.org/325", "original_publisher_url": "https://example.org/original", "video_id": "abcdefghijk", "quality": "Unverified fixture"}, {"title": "Original episode", "host": "Example"})
        self.assertEqual(0, item["segments"][0]["start_seconds"])
        self.assertEqual(["sentenceid_1"], item["segments"][0]["source_span_ids"])
        self.assertIsNone(item["segments"][0]["speaker"])

    @unittest.skipUnless(find_spec("yt_dlp"), "install the collector extra")
    def test_native_audio_resolver_never_follows_youtube_embed(self):
        with patch("yt_dlp.YoutubeDL") as factory:
            with self.assertRaisesRegex(ValueError, "YouTube embed deferred"):
                resolve("https://www.youtube.com/watch?v=abcdefghijk")
            factory.return_value.__enter__.return_value.extract_info.assert_not_called()


if __name__ == "__main__":
    unittest.main()
