import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from tts_cli import main
from tts_core import GenerationResult


class CommandLineTests(unittest.TestCase):
    def test_existing_output_is_protected_unless_force_is_given(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "test.mp3"
            output.write_bytes(b"original")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(["--text", "hello", "--output", str(output)])
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(output.read_bytes(), b"original")

    def test_utf8_file_and_delivery_options_reach_speech_engine(self):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "script.txt"
            script.write_text("مرحبا بالعالم", encoding="utf-8-sig")
            output = Path(folder) / "test.mp3"
            generate = AsyncMock(return_value=GenerationResult(output, None, 1))
            with patch("tts_core.generate_speech", new=generate), contextlib.redirect_stdout(io.StringIO()):
                code = main(["--file", str(script), "--output", str(output), "--rate", "-20"])
            self.assertEqual(code, 0)
            self.assertEqual(generate.call_args.args[0], "مرحبا بالعالم")
            self.assertEqual(generate.call_args.args[1].rate, -20)
