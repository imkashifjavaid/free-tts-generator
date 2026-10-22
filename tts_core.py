"""Speech services and file handling, independent of the desktop interface."""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from typing import Callable

import aiohttp
import edge_tts

LOGGER = logging.getLogger(__name__)
MAX_CHUNK_CHARS = 1800
MIN_EDGE_VERSION = (7, 3, 1)
DEFAULT_VOICE = "en-US-AriaNeural"
TICKS_PER_SECOND = 10_000_000
MP3_BYTES_PER_SECOND = 6000  # Edge's fixed 48 kbps, 24 kHz mono stream.


class GenerationCancelled(Exception):
    """The caller stopped a job before publishing its output."""


@dataclass(frozen=True)
class Voice:
    id: str
    locale: str
    gender: str
    name: str
    categories: tuple[str, ...] = ()
    locale_name: str = ""

    @property
    def locale_label(self) -> str:
        return self.locale_name or self.locale

    @property
    def language(self) -> str:
        if self.locale_name:
            return self.locale_name.partition(" (")[0].strip()
        return self.locale.split("-", 1)[0]

    @classmethod
    def from_service(cls, data: dict) -> Voice:
        voice_id = data["ShortName"]
        locale = data["Locale"]
        if not all(isinstance(item, str) and item for item in (voice_id, locale)):
            raise ValueError("Invalid voice identifier or language")
        tags = data.get("VoiceTag", {})
        categories = tags.get("ContentCategories", []) if isinstance(tags, dict) else []
        locale_name = data.get("LocaleName")
        if not isinstance(locale_name, str) or not locale_name.strip():
            friendly_name = data.get("FriendlyName", "")
            locale_name = friendly_name.partition(" - ")[2] if isinstance(friendly_name, str) else ""
        return cls(voice_id, locale, str(data.get("Gender", "Unknown")),
                   voice_id.removeprefix(locale + "-").removesuffix("Neural"),
                   tuple(str(value) for value in categories), locale_name.strip())

    def matches(self, query: str = "", locale: str = "", gender: str = "", *,
                language: str = "") -> bool:
        searchable = " ".join((self.id, self.name, self.locale_label, self.gender, *self.categories)).casefold()
        return (not locale or self.locale == locale) and (
            not gender or self.gender == gender
        ) and (not language or self.language == language) and all(
            word in searchable for word in query.casefold().split())


@dataclass(frozen=True)
class SpeechOptions:
    voice: str = DEFAULT_VOICE
    rate: int = 0
    pitch: int = 0
    volume: int = 0
    subtitles: bool = False

    def __post_init__(self) -> None:
        if not self.voice.strip():
            raise ValueError("Select a voice first.")
        for label, value, minimum, maximum in (
            ("Speed", self.rate, -90, 100),
            ("Pitch", self.pitch, -100, 100),
            ("Volume", self.volume, -100, 100),
        ):
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{label} must be an integer from {minimum} to {maximum}.")


@dataclass(frozen=True)
class Progress:
    fraction: float
    message: str


@dataclass(frozen=True)
class GenerationResult:
    audio_path: Path
    subtitle_path: Path | None
    chunks: int


def check_dependency() -> None:
    version = importlib.metadata.version("edge-tts")
    numbers = tuple(int(value) for value in version.split(".")[:3] if value.isdigit())
    if numbers < MIN_EDGE_VERSION:
        raise RuntimeError(
            f"edge-tts {version} is too old for Microsoft's current service. "
            "Run: python -m pip install --upgrade -r requirements.txt"
        )


def clean_text(text: str) -> str:
    # XML 1.0 cannot represent control characters, lone surrogates or FFFE/FFFF.
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", " ", text).strip()


def split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Bound requests, preferring sentences and words without dropping text."""
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError("Chunk length must be a positive integer.")
    text = clean_text(text)
    chunks = []
    while len(text) > max_chars:
        window = text[:max_chars + 1]
        boundaries = list(re.finditer(r"(?<=[.!?।。！？])\s+|\n+", window))
        split_at = boundaries[-1].start() if boundaries else 0
        if split_at < max_chars // 2:
            spaces = list(re.finditer(r"\s+", window))
            split_at = spaces[-1].start() if spaces else 0
        if split_at < max_chars // 2 or split_at == 0:
            split_at = max_chars
        chunk = text[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        text = text[split_at:].lstrip()
    if text:
        chunks.append(text)
    return chunks


def user_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "FreeTTSGenerator"


def write_json(path: Path, value: object) -> None:
    """Atomic persistence: a crash must not truncate the previous settings/cache."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".tts-", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_json(path: Path, default: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def parse_voices(data: object) -> list[Voice]:
    if not isinstance(data, list):
        return []
    voices = {}
    for item in data:
        try:
            voice = Voice.from_service(item)
            voices[voice.id] = voice
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return sorted(voices.values(), key=lambda voice: voice.id)


async def load_voices(cache_path: Path) -> tuple[list[Voice], str | None]:
    """Refresh from the service; use a validated cached catalog during outages."""
    check_dependency()
    try:
        raw = await asyncio.wait_for(edge_tts.list_voices(), timeout=25)
        voices = parse_voices(raw)
        if not voices:
            raise RuntimeError("The service returned an empty voice catalog.")
    except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError, OSError, RuntimeError, ValueError) as error:
        cached = parse_voices(read_json(cache_path, []))
        if not cached:
            raise RuntimeError(f"Could not load voices. {friendly_error(error)}") from error
        return cached, "Using saved voices; the online catalog is unavailable. " + friendly_error(error)
    try:
        write_json(cache_path, raw)
    except OSError:
        LOGGER.warning("Could not save the voice cache", exc_info=True)
    return voices, None


def friendly_error(error: BaseException) -> str:
    status = getattr(error, "status", None)
    if status in (401, 403):
        return ("Microsoft refused the connection. Update with "
                "'python -m pip install --upgrade -r requirements.txt', check your "
                "computer's clock, then retry. The service may also be temporarily unavailable.")
    if status == 429:
        return "The speech service is busy or limiting requests. Wait a moment and try again."
    if isinstance(error, edge_tts.exceptions.NoAudioReceived):
        return "The service returned no audio. Try another voice or check that the text matches its language."
    if isinstance(error, (asyncio.TimeoutError, TimeoutError, aiohttp.ClientConnectionError)):
        return "Cannot reach the speech service. Check your internet connection, VPN or proxy and retry."
    if isinstance(error, PermissionError):
        return "Cannot write the file. Choose a writable folder and close any player using the existing file."
    return str(error) or type(error).__name__


async def _cancellable(awaitable, cancel: threading.Event):
    task = asyncio.ensure_future(awaitable)
    try:
        while not task.done():
            if cancel.is_set():
                raise GenerationCancelled()
            await asyncio.wait({task}, timeout=0.1)
        if cancel.is_set():
            raise GenerationCancelled()
        return task.result()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def _retryable(error: BaseException) -> bool:
    if isinstance(error, aiohttp.ClientResponseError):
        return error.status in (403, 408, 429) or error.status >= 500
    return isinstance(error, (asyncio.TimeoutError, TimeoutError, aiohttp.ClientConnectionError,
                              edge_tts.exceptions.NoAudioReceived,
                              edge_tts.exceptions.WebSocketError))


def _publish_files(files: list[tuple[Path, Path]], work_dir: Path) -> None:
    """Roll back both exports if publishing either one fails."""
    backups = {}
    published = []
    try:
        for index, (source, destination) in enumerate(files):
            backup = work_dir / f"backup-{index}"
            if destination.exists():
                shutil.copy2(destination, backup)
                backups[destination] = backup
            os.replace(source, destination)
            published.append(destination)
    except OSError:
        for destination in reversed(published):
            if destination in backups:
                os.replace(backups[destination], destination)
            else:
                destination.unlink(missing_ok=True)
        raise


async def generate_speech(
    text: str,
    options: SpeechOptions,
    output: Path,
    *,
    cancel: threading.Event | None = None,
    on_progress: Callable[[Progress], None] | None = None,
    max_chars: int = MAX_CHUNK_CHARS,
    attempts: int = 3,
) -> GenerationResult:
    """Stream bounded requests to disk and publish only complete exports."""
    check_dependency()
    chunks = split_text(text, max_chars)
    if not chunks:
        raise ValueError("Please enter some text first.")
    if type(attempts) is not int or not 1 <= attempts <= 5:
        raise ValueError("Attempts must be an integer between 1 and 5.")
    output = Path(output).expanduser().absolute()
    if output.suffix.lower() != ".mp3":
        raise ValueError("Choose an output filename ending in .mp3.")
    if not output.parent.is_dir():
        raise ValueError("The output folder does not exist.")
    cancel = cancel if cancel is not None else threading.Event()
    total_chars = sum(map(len, chunks))
    completed_chars = 0
    completed_bytes = 0
    subtitles = edge_tts.SubMaker()

    def report(fraction: float, message: str) -> None:
        if on_progress:
            on_progress(Progress(min(1.0, max(0.0, fraction)), message))

    with tempfile.TemporaryDirectory(prefix=".tts-", dir=output.parent) as temporary:
        work_dir = Path(temporary)
        audio = work_dir / "complete.mp3"
        with audio.open("wb") as merged:
            for index, chunk in enumerate(chunks, 1):
                if cancel.is_set():
                    raise GenerationCancelled()
                part = work_dir / "part.mp3"

                async def stream_part() -> list[dict]:
                    communicate = edge_tts.Communicate(
                        chunk, options.voice, rate=f"{options.rate:+d}%",
                        pitch=f"{options.pitch:+d}Hz", volume=f"{options.volume:+d}%",
                        boundary="SentenceBoundary", connect_timeout=10, receive_timeout=45,
                    )
                    cues = []
                    spoken = 0
                    with part.open("wb") as handle:
                        async for event in communicate.stream():
                            if event["type"] == "audio":
                                handle.write(event["data"])
                            elif event["type"] == "SentenceBoundary":
                                spoken += len(event["text"])
                                cues.append(event)
                                report((completed_chars + min(spoken, len(chunk))) / total_chars * .98,
                                       f"Generating part {index} of {len(chunks)}...")
                    if part.stat().st_size == 0:
                        raise edge_tts.exceptions.NoAudioReceived("Empty audio stream")
                    return cues

                for attempt in range(attempts):
                    report(completed_chars / total_chars * .98,
                           f"Generating part {index} of {len(chunks)}...")
                    try:
                        cues = await _cancellable(stream_part(), cancel)
                        break
                    except Exception as error:
                        if not _retryable(error) or attempt + 1 == attempts:
                            raise
                        report(completed_chars / total_chars * .98,
                               f"Connection interrupted. Retrying part {index} ({attempt + 2}/{attempts})...")
                        await _cancellable(asyncio.sleep(2 ** attempt), cancel)
                offset = completed_bytes * TICKS_PER_SECOND // MP3_BYTES_PER_SECOND
                if options.subtitles:
                    for cue in cues:
                        subtitles.feed({**cue, "offset": cue["offset"] + offset})
                with part.open("rb") as handle:
                    shutil.copyfileobj(handle, merged)
                completed_bytes += part.stat().st_size
                completed_chars += len(chunk)
                report(completed_chars / total_chars * .98,
                       f"Completed part {index} of {len(chunks)}")

        if cancel.is_set():
            raise GenerationCancelled()
        files = [(audio, output)]
        subtitle_path = None
        if options.subtitles:
            if not subtitles.cues:
                raise RuntimeError("The service returned no subtitle timing. Retry or disable subtitles.")
            subtitle_path = output.with_suffix(".srt")
            subtitle_file = work_dir / "complete.srt"
            subtitle_file.write_text(subtitles.get_srt(), encoding="utf-8")
            files.append((subtitle_file, subtitle_path))
        report(.99, "Saving your audio...")
        if cancel.is_set():
            raise GenerationCancelled()
        _publish_files(files, work_dir)
    report(1, "Audio saved")
    return GenerationResult(output, subtitle_path, len(chunks))


def open_path(path: Path) -> None:
    """Open an audio file/folder with the OS default application; surface failures."""
    if sys.platform == "win32":
        os.startfile(str(path))
    else:
        command = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.run([command, str(path)], check=True, capture_output=True, timeout=10)
