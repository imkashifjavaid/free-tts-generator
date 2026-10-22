# Free TTS Studio

Turn scripts into voiceovers with Microsoft Edge's neural voices. A free Python desktop app with voice previews, delivery controls, long-script export, and timed subtitles. Powered by [edge-tts](https://github.com/rany2/edge-tts), with no API key or account required.

## What changed

The original app depended on an unspecified `edge-tts` version. Microsoft changed its connection protocol in October 2026, and older clients can fail with HTTP 403 even when voice listing works. [edge-tts 7.3.0](https://github.com/rany2/edge-tts/releases/tag/7.3.0) added the updated protocol; this app requires **7.3.1 or newer**.

This rebuild also fixes missing installation files, the incorrect launch command, unsafe Tk updates from worker threads, incomplete export cleanup, and silently swallowed playback errors. The original `Free TTS Generator.py` filename remains a working launcher.

## Features

- Resizable desktop studio with a script editor, undo, word/character counts, and estimated narration time.
- The live Edge voice catalog with full language and accent names, language grouping, optional accent and gender filters, search, and favorites.
- Preview the first part of your own script before exporting.
- Adjustable speed, pitch, and volume.
- Import UTF-8 or UTF-16 `.txt` and `.md` scripts.
- Long scripts split at sentence or word boundaries, streamed to disk, and exported as one MP3.
- Optional sentence-level `.srt` subtitles with timing carried across chunks.
- Automatic retries for temporary connection failures, responsive cancellation, and useful error messages.
- Existing output is replaced only after generation succeeds. Temporary files are cleaned up on failure or cancellation.
- Draft, voice, favorites, and delivery settings remembered between sessions. A cached catalog remains browsable during a catalog outage.
- Command-line exports for repeatable workflows.

The choices in the catalog are **voices from one speech service**, rather than separately installed AI models. There is no app-imposed character cap. Speech generation requires internet access and depends on Microsoft's service availability and limits; unlimited service access cannot be guaranteed. A saved catalog does not enable offline synthesis.

## Start on Windows

Install **Python 3.10+** with Tkinter and make `python` available on PATH. Then double-click **`start.bat`**. It creates a `.venv` in this folder, installs or updates the speech dependency, and opens the studio. If an update check fails, it can still open using an installed compatible version.

The startup dependency check is normal. Pip's `Requirement already satisfied` messages mean the packages are installed, with no action needed. The launcher hides this routine output while keeping warnings and errors visible.

To run manually from PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt
.\.venv\Scripts\python.exe tts_gui.py
```

Use the virtual environment's Python, as shown above, to avoid accidentally launching with an older globally installed dependency. No activation or PowerShell execution-policy change is needed.

## macOS / Linux

Use Python 3.10+ with Tk support. Some Linux distributions package Tk separately, for example `python3-tk` on Ubuntu/Debian. The desktop app needs a graphical session; the CLI does not.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade -r requirements.txt
.venv/bin/python tts_gui.py
```

MP3 export does not require FFmpeg. Playback opens your system's default audio application (`open` on macOS, `xdg-open` on Linux).

## Desktop workflow

1. Paste a script or choose **Import text**. `Ctrl+O` opens the importer.
2. Choose a **Language**, such as **English**, to see voices from all its available accents. Leave **Accent / region** on **All accents**, or narrow it to a full name such as **English (United Kingdom)**. Search also accepts voice names, full languages and countries (for example `Urdu`, `Pakistan`, or `English India`), locale codes, and categories. Select a voice and use **Favorite** to save voices you like.
3. Adjust delivery and choose **Preview voice**. Preview uses up to 280 characters of your script, or a short sample when the editor is empty.
4. Optionally enable subtitles and playback after export.
5. Choose **Export MP3** (`Ctrl+Enter`) and a destination. The file is saved with the exact name you choose. A matching `.srt` is saved beside it when enabled.

**Cancel** discards an incomplete job. **Play last export** and **Open folder** provide access to the most recent successful export in this session. Playback runs in your usual audio player; control playback there.

The service outputs 24 kHz, 48 kbps mono MP3. Delivery controls change speech characteristics, not the provider's audio encoding quality. Narration duration is an estimate and varies by language and voice.

## Command line

Examples below use `python` from the configured virtual environment; on Windows you can substitute `.\.venv\Scripts\python.exe`.

```bash
python tts_cli.py --list-voices --search "ur-PK"
python tts_cli.py --text "Hello, world." --voice en-US-AriaNeural --output hello.mp3
python tts_cli.py --file script.txt --voice ur-PK-AsadNeural --rate -15 --subtitles --output narration.mp3
python tts_cli.py --file - --output narration.mp3
python tts_cli.py --help
```

`--file -` reads standard input. CLI files use UTF-8, optionally with a BOM. Existing MP3 or requested SRT files are protected unless you pass `--force`. `Ctrl+C` cancels generation. Exit codes: `0` success, `1` generation/setup error, `2` invalid arguments, `130` interrupted.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Missing dependency or old version | Run `python -m pip install --upgrade -r requirements.txt` with the same Python used to launch the app. On Windows, `start.bat` does this for its local environment. |
| HTTP 403 / connection refused | Update first, check your system clock, and retry. Upstream changes or a service outage may require a later `edge-tts` release. |
| Catalog won't load | Check your connection, proxy, or VPN, then choose **Refresh**. A previously downloaded catalog is used when available. |
| No audio received | Try another voice and text in that voice's language. Some voices may be temporarily unavailable. |
| Can't save or overwrite | Choose a writable folder and close players holding the destination file open. |
| Audio saved but won't play | Open the MP3 from the destination folder and check your system's default MP3 application. |
| Linux reports no display | Run in a graphical session or use `tts_cli.py`. |

The app stores `session.json` (including your draft), `voices.json`, and diagnostic `app.log` locally in:

- Windows: `%LOCALAPPDATA%\FreeTTSGenerator`
- macOS: `~/Library/Application Support/FreeTTSGenerator`
- Linux: `$XDG_STATE_HOME/FreeTTSGenerator`, defaulting to `~/.local/state/FreeTTSGenerator`

Text used for speech and previews is sent to Microsoft's online speech service. Exports stay in the folder you choose.

## Debugging guide

Run the commands below from the repository folder in PowerShell. Use the project's Python so you inspect the same dependencies as the app.

### 1. Reproduce the issue

Note what you were doing, the selected voice, language and accent filters, and the exact error message. Try a short sample script to check whether the issue also happens with simple input. If no voices appear, clear search, select **All languages**, **All accents**, and **All genders**, and turn off **Favorites**.

### 2. Read the application log

On Windows, press **Win + R**, enter `%LOCALAPPDATA%\FreeTTSGenerator\app.log`, and open it with a text editor. Or read the latest entries in PowerShell:

```powershell
Get-Content "$env:LOCALAPPDATA\FreeTTSGenerator\app.log" -Tail 100
```

To follow new entries while reproducing an issue:

```powershell
Get-Content "$env:LOCALAPPDATA\FreeTTSGenerator\app.log" -Tail 30 -Wait
```

Press `Ctrl+C` to stop following the log. The log records warnings and failures, including catalog and speech generation exceptions; it does not record every action. If the app fails before logging is configured, the file may not exist or contain the startup error. Use the terminal steps below in that case. See the storage paths above for macOS and Linux.

### 3. Show startup errors in the terminal

```powershell
.\.venv\Scripts\python.exe tts_gui.py
```

Keep PowerShell open and reproduce the issue. Copy any traceback printed there. To save terminal output as well:

```powershell
.\.venv\Scripts\python.exe tts_gui.py 2>&1 | Tee-Object -FilePath debug-console.txt
```

The launcher's **Checking speech dependencies...** message is normal. **Requirement already satisfied** means a package is installed. Routine pip output is hidden by `start.bat`; warnings and errors remain visible.

### 4. Check dependencies and isolate speech problems

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip show edge-tts aiohttp
.\.venv\Scripts\python.exe -m pip check
```

For missing or outdated dependencies, update them and retry:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt
```

To check voice loading and speech generation without the desktop interface:

```powershell
.\.venv\Scripts\python.exe tts_cli.py --list-voices --search "English"
.\.venv\Scripts\python.exe tts_cli.py --text "This is a speech test." --voice en-US-AriaNeural --output debug-speech.mp3
```

These commands use the online service, although voice listing can fall back to the saved catalog. Choose another output filename if `debug-speech.mp3` already exists. If the CLI also fails, inspect its error for dependency, connection, service, or file permission problems. If it succeeds, focus on the desktop filters, selected voice, script, and export settings.

### 5. Run tests and report the issue

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
git rev-parse --short HEAD
```

When asking for help or opening an issue, include:

- Steps to reproduce, expected behavior, and what actually happened.
- Your operating system, Python and `edge-tts` versions, and commit ID.
- The selected voice and relevant filters or delivery settings.
- The exact error, relevant log entries, and any failing test output.

Review logs and terminal output before sharing them, and remove private text or paths. `session.json` contains your saved script draft; share only the specific settings needed to explain the issue.

## Development and checks

The UI is in `tts_gui.py`, speech and persistence in `tts_core.py`, and the command-line entry point in `tts_cli.py`. Importing these modules does not create a window or make network requests.

```bash
python -m unittest discover -v
```

Tests cover multilingual chunking, retries after partial downloads, cancellation during network waits, preservation of existing files, subtitle timing, cache recovery, CLI overwrite protection, and desktop state. They mock the speech service and run without internet access. GUI tests require a display; on headless Linux use `xvfb-run -a python -m unittest discover -v`. CI runs on Windows and Linux with Python 3.10 and 3.14.

For a real service check, export a short script through the app or CLI. No network synthesis is run by CI.

## Credits and license

Made by [Kashif Javaid](https://github.com/imkashifjavaid). App source is MIT licensed; see [LICENSE](LICENSE). The `edge-tts` dependency has its own license.
