"""Command-line export for scripts and automation: python tts_cli.py --help."""

import argparse
import asyncio
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description="Free TTS Studio — export Edge neural speech as MP3.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--text", help="Text to speak (quote it in your shell)")
    source.add_argument("--file", type=Path, help="UTF-8 script file; use - to read standard input")
    parser.add_argument("--output", "-o", type=Path, help="Exact output .mp3 path")
    parser.add_argument("--voice", default="en-US-AriaNeural", help="Voice identifier")
    parser.add_argument("--rate", type=int, default=0, help="Speed adjustment, -90 to 100 percent")
    parser.add_argument("--pitch", type=int, default=0, help="Pitch adjustment, -100 to 100 Hz")
    parser.add_argument("--volume", type=int, default=0, help="Volume adjustment, -100 to 100 percent")
    parser.add_argument("--subtitles", action="store_true", help="Export a matching .srt file")
    parser.add_argument("--list-voices", action="store_true", help="List voices without generating audio")
    parser.add_argument("--search", default="", help="Filter voice listing by name, locale, gender, or category")
    parser.add_argument("--force", action="store_true", help="Replace existing output files")
    args = parser.parse_args(argv)
    try:
        from tts_core import (SpeechOptions, friendly_error, generate_speech, load_voices, user_data_dir)
    except ImportError as error:
        parser.exit(1, f"Missing dependency: {error}. Run: python -m pip install -r requirements.txt\n")
    try:
        if args.list_voices:
            voices, warning = asyncio.run(load_voices(user_data_dir() / "voices.json"))
            if warning:
                print(warning, file=sys.stderr)
            for voice in voices:
                if voice.matches(args.search):
                    print(f"{voice.id:42} {voice.locale:12} {voice.gender}")
            return 0
        if args.text is None and args.file is None:
            parser.error("Provide --text or --file, or use --list-voices.")
        if args.output is None:
            parser.error("--output is required when generating speech.")
        if not args.force:
            destinations = [args.output]
            if args.subtitles:
                destinations.append(args.output.with_suffix(".srt"))
            for path in destinations:
                if path.exists():
                    parser.error(f"Output already exists: {path}. Use --force to replace it.")
        text = args.text
        if args.file is not None:
            text = sys.stdin.read() if str(args.file) == "-" else args.file.read_text(encoding="utf-8-sig")
        options = SpeechOptions(args.voice, args.rate, args.pitch, args.volume, args.subtitles)
        last_message = None

        def progress(update):
            nonlocal last_message
            if update.message != last_message:
                print(update.message, file=sys.stderr)
                last_message = update.message

        result = asyncio.run(generate_speech(text, options, args.output, on_progress=progress))
        print(f"Saved {result.audio_path}")
        if result.subtitle_path:
            print(f"Saved {result.subtitle_path}")
        return 0
    except KeyboardInterrupt:
        print("Cancelled. Incomplete output was discarded.", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"Error: {friendly_error(error)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
