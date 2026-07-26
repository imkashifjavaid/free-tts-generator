# Free TTS Generator (Edge-TTS)

A free, unlimited Text-to-Speech desktop app built with Python and [edge-tts](https://github.com/rany2/edge-tts). Uses Microsoft Edge's neural voices — no API key, no signup, no character limits.

Made for content creators who need free voiceovers for YouTube tutorials, without paying for ElevenLabs or other paid TTS tools.

## Features

- 🎙️ 300+ voices across many languages and accents
- 🔍 Real-time filters — tick language (en-US, en-GB, hi-IN) and gender (Male/Female)
- ♾️ No text length limit — long scripts are auto-split into chunks and merged
- ▶️ Auto-play generated audio for quick testing
- 🏷️ Output file auto-named with the voice model used
- 💻 Simple Tkinter GUI — no command line needed after setup

## Requirements

- Python 3.8+
- Windows, macOS, or Linux

## Installation

```bash
git clone https://github.com/imkashifjavaid/free-tts-generator.git
cd free-tts-generator
pip install -r requirements.txt
```

### Verify installation

Make sure edge-tts installed correctly before running the GUI:

```bash
pip install edge-tts
```

Test that it's working:

```bash
edge-tts --list-voices
```

This should print a list of all available voices. If you see the list, you're good to go.

## Usage

```bash
python tts_gui.py
```

1. Paste your script into the text box
2. Tick filters (language / gender) to narrow the voice list
3. Select a voice from the list
4. Click **Generate & Save MP3**
5. Audio auto-plays when ready (can be toggled off)

## Credits

Made by [imkashifjavaid](https://github.com/imkashifjavaid)

## License

MIT License — free to use, modify, and share.
