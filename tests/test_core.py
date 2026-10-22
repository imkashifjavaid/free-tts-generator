import asyncio
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, patch

import aiohttp
import edge_tts

from tts_core import (
    GenerationCancelled, SpeechOptions, check_dependency, clean_text,
    generate_speech, load_voices, parse_voices, split_text, write_json,
)


CATALOG = [
    {"ShortName": "en-US-AriaNeural", "Locale": "en-US", "Gender": "Female",
     "LocaleName": "English (United States)",
     "VoiceTag": {"ContentCategories": ["News", "Novel"]}},
    {"ShortName": "ur-PK-AsadNeural", "Locale": "ur-PK", "Gender": "Male",
     "LocaleName": "Urdu (Pakistan)"},
]


class TextTests(unittest.TestCase):
    def test_long_multilingual_script_preserves_content_with_bounded_chunks(self):
        text = ("Hello, world! مرحبا بالعالم۔ नमस्ते दुनिया। 你好世界。\n" * 200) + "x" * 4000
        chunks = split_text(text)
        self.assertTrue(all(0 < len(chunk) <= 1800 for chunk in chunks))
        self.assertEqual("".join("".join(chunks).split()), "".join(text.split()))

    def test_prefers_word_and_sentence_boundaries(self):
        self.assertEqual(split_text("One sentence. Another one. Final.", 26),
                         ["One sentence. Another one.", "Final."])
        self.assertEqual(split_text("alpha beta gamma delta", 12), ["alpha beta", "gamma delta"])

    def test_tiny_chunks_empty_and_invalid_limits(self):
        self.assertEqual(split_text("abcd", 1), list("abcd"))
        self.assertEqual(split_text(" \n\t"), [])
        for limit in (0, -1, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                split_text("text", limit)

    def test_removes_xml_control_characters_without_losing_other_languages(self):
        self.assertEqual(clean_text("\x00Hello\x0b مرحبا\ud800"), "Hello  مرحبا")

    def test_voice_catalog_validation_and_filtering(self):
        voices = parse_voices([*CATALOG, CATALOG[0], {}, None, {"Locale": "bad"}])
        self.assertEqual(len(voices), 2)
        self.assertTrue(voices[0].matches("ARIA news", "en-US", "Female"))
        self.assertFalse(voices[0].matches("aria", "ur-PK"))
        self.assertFalse(voices[0].matches("aria", gender="Male"))
        self.assertEqual(parse_voices({"bad": "data"}), [])

    def test_search_accepts_full_language_and_country_names_and_codes(self):
        voice = parse_voices(CATALOG)[0]
        self.assertTrue(voice.matches("English United States news"))
        self.assertTrue(voice.matches("en-US"))
        self.assertTrue(voice.matches(language="English"))
        self.assertFalse(voice.matches(language="Urdu"))
        self.assertFalse(voice.matches("Pakistan"))

    def test_locale_names_prefer_metadata_with_friendly_name_and_code_fallbacks(self):
        record = {**CATALOG[0], "FriendlyName": "Microsoft Aria Online (Natural) - Wrong name"}
        self.assertEqual(parse_voices([record])[0].locale_label, "English (United States)")
        record.update(LocaleName=None, FriendlyName="Microsoft Aria Online (Natural) - English (United States)")
        voice = parse_voices([record])[0]
        self.assertEqual(voice.language, "English")
        self.assertEqual(voice.locale_label, "English (United States)")
        record.update(LocaleName=" ", FriendlyName=None)
        self.assertEqual(parse_voices([record])[0].locale_label, "en-US")

    def test_rejects_invalid_delivery_settings(self):
        for settings in ({"voice": ""}, {"rate": -100}, {"pitch": 101}, {"volume": 1.5}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                SpeechOptions(**settings)

    def test_outdated_dependency_has_upgrade_instructions(self):
        with patch("tts_core.importlib.metadata.version", return_value="7.2.8"):
            with self.assertRaisesRegex(RuntimeError, "pip install --upgrade"):
                check_dependency()


class GenerationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.output = self.folder / "speech.mp3"
        self.options = SpeechOptions(subtitles=True)

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def fake_communicate(text, voice, **kwargs):
        class Stream:
            async def stream(self):
                yield {"type": "audio", "data": b"a" * 6000}
                yield {"type": "SentenceBoundary", "text": text,
                       "offset": 0, "duration": 5_000_000}
        return Stream()

    async def test_multichunk_audio_and_subtitle_offsets(self):
        progress = []
        with patch("tts_core.edge_tts.Communicate", side_effect=self.fake_communicate):
            result = await generate_speech("one. two. three.", self.options, self.output,
                                           max_chars=6, on_progress=progress.append)
        self.assertEqual(result.chunks, 3)
        self.assertEqual(self.output.stat().st_size, 18_000)
        srt = result.subtitle_path.read_text(encoding="utf-8")
        self.assertIn("00:00:00,000 --> 00:00:00,500", srt)
        self.assertIn("00:00:01,000 --> 00:00:01,500", srt)
        self.assertIn("00:00:02,000 --> 00:00:02,500", srt)
        self.assertEqual(progress[-1].fraction, 1)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["speech.mp3", "speech.srt"])

    async def test_retry_discards_partial_audio_and_duplicate_captions(self):
        calls = 0

        def flaky(text, voice, **kwargs):
            nonlocal calls
            calls += 1
            attempt = calls

            class Stream:
                async def stream(self):
                    yield {"type": "audio", "data": b"bad" if attempt == 1 else b"good"}
                    yield {"type": "SentenceBoundary", "text": text, "offset": 0, "duration": 1000}
                    if attempt == 1:
                        raise aiohttp.ClientConnectionError("Disconnected")
            return Stream()

        with patch("tts_core.edge_tts.Communicate", side_effect=flaky), patch(
            "tts_core.asyncio.sleep", new=AsyncMock()
        ):
            result = await generate_speech("hello", self.options, self.output)
        self.assertEqual(calls, 2)
        self.assertEqual(self.output.read_bytes(), b"good")
        self.assertEqual(result.subtitle_path.read_text().count("-->"), 1)

    async def test_failed_generation_keeps_previous_files_and_cleans_work_files(self):
        self.output.write_bytes(b"previous audio")
        self.output.with_suffix(".srt").write_text("previous captions")
        with patch("tts_core.edge_tts.Communicate", side_effect=ValueError("Invalid voice")):
            with self.assertRaisesRegex(ValueError, "Invalid voice"):
                await generate_speech("hello", self.options, self.output)
        self.assertEqual(self.output.read_bytes(), b"previous audio")
        self.assertEqual(self.output.with_suffix(".srt").read_text(), "previous captions")
        self.assertEqual(len(list(self.folder.iterdir())), 2)

    async def test_cancels_waiting_network_request_promptly_and_cleans_up(self):
        cancelled = threading.Event()
        stream_closed = asyncio.Event()

        class Waiting:
            async def stream(self):
                try:
                    await asyncio.sleep(30)
                    yield {"type": "audio", "data": b"late"}
                finally:
                    stream_closed.set()

        asyncio.get_running_loop().call_later(.05, cancelled.set)
        with patch("tts_core.edge_tts.Communicate", return_value=Waiting()):
            with self.assertRaises(GenerationCancelled):
                await asyncio.wait_for(generate_speech("hello", self.options, self.output,
                                                       cancel=cancelled), timeout=1)
        self.assertTrue(stream_closed.is_set())
        self.assertEqual(list(self.folder.iterdir()), [])

    async def test_cancel_before_start_keeps_original_audio(self):
        self.output.write_bytes(b"original")
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(GenerationCancelled):
            await generate_speech("hello", self.options, self.output, cancel=cancelled)
        self.assertEqual(self.output.read_bytes(), b"original")
        self.assertEqual(len(list(self.folder.iterdir())), 1)

    async def test_missing_audio_or_subtitles_cannot_publish_an_incomplete_export(self):
        class AudioOnly:
            async def stream(self):
                yield {"type": "audio", "data": b"audio"}

        class Empty:
            async def stream(self):
                if False:
                    yield

        with patch("tts_core.edge_tts.Communicate", return_value=AudioOnly()):
            with self.assertRaisesRegex(RuntimeError, "no subtitle timing"):
                await generate_speech("hello", self.options, self.output)
        with patch("tts_core.edge_tts.Communicate", return_value=Empty()):
            with self.assertRaises(edge_tts.exceptions.NoAudioReceived):
                await generate_speech("hello", self.options, self.output, attempts=1)
        self.assertEqual(list(self.folder.iterdir()), [])

    async def test_rolls_back_audio_if_subtitle_publication_fails(self):
        import os
        original_replace = os.replace
        self.output.write_bytes(b"original audio")
        self.output.with_suffix(".srt").write_text("original captions")

        def fail_caption(source, destination):
            if Path(source).name == "complete.srt":
                raise PermissionError("Subtitles in use")
            return original_replace(source, destination)

        with patch("tts_core.edge_tts.Communicate", side_effect=self.fake_communicate), patch(
            "tts_core.os.replace", side_effect=fail_caption
        ):
            with self.assertRaises(PermissionError):
                await generate_speech("hello", self.options, self.output)
        self.assertEqual(self.output.read_bytes(), b"original audio")
        self.assertEqual(self.output.with_suffix(".srt").read_text(), "original captions")
        self.assertEqual(len(list(self.folder.iterdir())), 2)

    async def test_failed_subtitle_publish_removes_a_new_audio_export(self):
        import os
        original_replace = os.replace

        def fail_caption(source, destination):
            if Path(source).name == "complete.srt":
                raise PermissionError("Subtitles in use")
            return original_replace(source, destination)

        with patch("tts_core.edge_tts.Communicate", side_effect=self.fake_communicate), patch(
            "tts_core.os.replace", side_effect=fail_caption
        ):
            with self.assertRaises(PermissionError):
                await generate_speech("hello", self.options, self.output)
        self.assertEqual(list(self.folder.iterdir()), [])

    async def test_invalid_input_cannot_create_output(self):
        for text, output in (("\x00\n ", self.output), ("hello", self.folder / "bad.wav")):
            with self.subTest(text=text), self.assertRaises(ValueError):
                await generate_speech(text, self.options, output)
        self.assertEqual(list(self.folder.iterdir()), [])


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_catalog_cached_and_used_during_outage(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "voices.json"
            with patch("tts_core.edge_tts.list_voices", new=AsyncMock(return_value=CATALOG)):
                fresh, warning = await load_voices(path)
            self.assertEqual(len(fresh), 2)
            self.assertIsNone(warning)
            with patch("tts_core.edge_tts.list_voices", new=AsyncMock(side_effect=TimeoutError())):
                cached, warning = await load_voices(path)
            self.assertEqual(cached, fresh)
            self.assertIn("saved voices", warning)

    async def test_corrupt_cache_is_not_treated_as_a_catalog(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "voices.json"
            write_json(path, {"bad": "cache"})
            with patch("tts_core.edge_tts.list_voices", new=AsyncMock(side_effect=TimeoutError())):
                with self.assertRaisesRegex(RuntimeError, "Could not load voices"):
                    await load_voices(path)
