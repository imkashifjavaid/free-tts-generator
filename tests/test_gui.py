from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from tts_core import GenerationResult, parse_voices, write_json
from tts_gui import TTSApp
from tests.test_core import CATALOG


MULTILINGUAL_CATALOG = [
    *CATALOG,
    {"ShortName": "en-GB-LibbyNeural", "Locale": "en-GB", "Gender": "Female",
     "LocaleName": "English (United Kingdom)"},
    {"ShortName": "en-AU-WilliamNeural", "Locale": "en-AU", "Gender": "Male",
     "LocaleName": "English (Australia)"},
    {"ShortName": "en-IN-NeerjaNeural", "Locale": "en-IN", "Gender": "Female",
     "LocaleName": "English (India)"},
    {"ShortName": "ur-IN-GulNeural", "Locale": "ur-IN", "Gender": "Female",
     "LocaleName": "Urdu (India)"},
]


class DesktopTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"No graphical display: {error}")
        self.root.withdraw()
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.app = TTSApp(self.root, data_dir=self.folder, auto_load=False)
        self.app._handle_event("voices", (parse_voices(CATALOG), None))
        self.root.update_idletasks()

    def tearDown(self):
        if hasattr(self, "temporary"):
            self.root.destroy()
            self.temporary.cleanup()

    def test_filter_preserves_selection_and_never_generates_with_a_hidden_voice(self):
        self.assertEqual(self.app.selected_voice(), "en-US-AriaNeural")
        self.app.search.set("Asad")
        self.app._filter_voices()
        self.assertIsNone(self.app.selected_voice())
        self.assertIn("disabled", self.app.generate_button.state())
        self.app.search.set("")
        self.app._filter_voices()
        self.assertEqual(self.app.selected_voice(), "en-US-AriaNeural")

    def test_language_filter_groups_all_english_accents_with_readable_labels(self):
        self.app._handle_event("voices", (parse_voices(MULTILINGUAL_CATALOG), None))
        self.assertEqual(self.app.language_box["values"], ("All languages", "English", "Urdu"))
        self.app.language.set("English")
        self.app.language_box.event_generate("<<ComboboxSelected>>")
        expected = {item["ShortName"] for item in MULTILINGUAL_CATALOG if item["Locale"].startswith("en-")}
        self.assertEqual(set(self.app.voice_tree.get_children()), expected)
        self.assertEqual(self.app.accent_box["values"], (
            "All accents", "English (Australia)", "English (India)",
            "English (United Kingdom)", "English (United States)"))
        self.assertEqual(self.app.voice_tree.item("en-US-AriaNeural", "values")[1], "English (United States)")
        self.assertIn("English (United States)", self.app.selected_label["text"])

    def test_accent_resets_when_switching_languages_and_other_filters_combine(self):
        self.app._handle_event("voices", (parse_voices(MULTILINGUAL_CATALOG), None))
        self.app.language.set("Urdu")
        self.app._language_changed()
        self.app.accent.set("Urdu (Pakistan)")
        self.app.accent_box.event_generate("<<ComboboxSelected>>")
        self.assertEqual(self.app.voice_tree.get_children(), ("ur-PK-AsadNeural",))
        self.app.language.set("English")
        self.app._language_changed()
        self.assertEqual(self.app.accent.get(), "All accents")
        self.assertEqual(len(self.app.voice_tree.get_children()), 4)
        self.app.gender.set("Female")
        self.app.favorites.add("en-GB-LibbyNeural")
        self.app.only_favorites.set(True)
        self.app.search.set("English United Kingdom")
        self.app._filter_voices()
        self.assertEqual(self.app.voice_tree.get_children(), ("en-GB-LibbyNeural",))
        self.app.only_favorites.set(False)
        self.app.search.set("")
        self.app.accent.set("English (Australia)")
        self.app._filter_voices()
        self.assertEqual(self.app.voice_tree.get_children(), ())
        self.assertIn("disabled", self.app.generate_button.state())

    def test_refresh_retains_valid_filters_and_resets_removed_accents(self):
        self.app._handle_event("voices", (parse_voices(MULTILINGUAL_CATALOG), None))
        self.app.language.set("English")
        self.app._language_changed()
        self.app.accent.set("English (United Kingdom)")
        self.app._handle_event("voices", (parse_voices(MULTILINGUAL_CATALOG), None))
        self.assertEqual(self.app.language.get(), "English")
        self.assertEqual(self.app.accent.get(), "English (United Kingdom)")
        self.assertEqual(self.app.voice_tree.get_children(), ("en-GB-LibbyNeural",))
        self.app._handle_event("voices", (parse_voices(CATALOG), None))
        self.assertEqual(self.app.language.get(), "English")
        self.assertEqual(self.app.accent.get(), "All accents")
        self.assertEqual(self.app.voice_tree.get_children(), ("en-US-AriaNeural",))
        self.app._handle_event("voices", (parse_voices(CATALOG[1:]), None))
        self.assertEqual(self.app.language.get(), "All languages")
        self.assertEqual(self.app.accent.get(), "All accents")

    def test_job_completion_and_cancellation_restore_controls(self):
        self.app.busy = True
        self.app._update_buttons()
        self.assertIn("disabled", self.app.generate_button.state())
        self.app._handle_event("cancelled", None)
        self.assertNotIn("disabled", self.app.generate_button.state())
        self.app._handle_event("done", (GenerationResult(self.folder / "test.mp3", None, 1), False, False))
        self.assertEqual(self.app.last_output.name, "test.mp3")
        self.assertNotIn("disabled", self.app.play_button.state())

    def test_preview_and_export_use_current_script_and_delivery(self):
        self.app.editor.insert("1.0", "My custom preview script.")
        self.app.rate.set(25)
        with patch.object(self.app, "_start_job") as start:
            self.app.preview()
            self.assertEqual(start.call_args.args[0], "My custom preview script.")
            self.assertEqual(start.call_args.args[1].rate, 25)
        self.app.preview_dir.cleanup()
        self.app.preview_dir = None

    def test_session_restores_draft_voice_favorites_and_controls(self):
        self.app.editor.insert("1.0", "A script that survives restart.")
        self.app.favorites.add("ur-PK-AsadNeural")
        self.app.rate.set(-20)
        self.app._save_session()
        second = tk.Toplevel(self.root)
        restored = TTSApp(second, data_dir=self.folder, auto_load=False)
        self.assertEqual(restored.editor.get("1.0", "end-1c"), "A script that survives restart.")
        self.assertEqual(restored.rate.get(), -20)
        self.assertIn("ur-PK-AsadNeural", restored.favorites)
        second.destroy()

    def test_malformed_saved_settings_fall_back_to_defaults(self):
        write_json(self.folder / "session.json", {"voice": {}, "rate": 10000,
                                                 "favorites": None, "draft": []})
        second = tk.Toplevel(self.root)
        restored = TTSApp(second, data_dir=self.folder, auto_load=False)
        restored._handle_event("voices", (parse_voices(CATALOG), None))
        self.assertEqual(restored.rate.get(), 0)
        self.assertEqual(restored.selected_voice(), "en-US-AriaNeural")
        second.destroy()
