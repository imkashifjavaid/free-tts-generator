"""Free TTS Studio: a responsive Tk desktop interface for Edge neural voices."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import queue
from subprocess import SubprocessError
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from tts_core import (
        DEFAULT_VOICE, GenerationCancelled, SpeechOptions, clean_text,
        friendly_error, generate_speech, load_voices, open_path,
        read_json, user_data_dir, write_json,
    )
except ImportError as error:
    DEPENDENCY_ERROR = error
else:
    DEPENDENCY_ERROR = None

LOGGER = logging.getLogger(__name__)
BG = "#10141d"
PANEL = "#191f2b"
FIELD = "#111722"
TEXT = "#e6ecf5"
MUTED = "#98a7bd"
ACCENT = "#79a9ff"


class TTSApp:
    def __init__(self, root: tk.Tk, *, data_dir: Path | None = None,
                 auto_load: bool = True):
        self.root = root
        self.data_dir = data_dir if data_dir is not None else user_data_dir()
        saved = read_json(self.data_dir / "session.json", {})
        self.settings = saved if isinstance(saved, dict) else {}
        self.voices = []
        self.voice_by_id = {}
        favorites = self.settings.get("favorites", [])
        self.favorites = {item for item in favorites if isinstance(item, str)} if isinstance(favorites, list) else set()
        preferred = self.settings.get("voice", DEFAULT_VOICE)
        self.preferred_voice = preferred if isinstance(preferred, str) else DEFAULT_VOICE
        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.busy = False
        self.loading = False
        self.closing = False
        self.last_output = None
        self.worker = None
        self.preview_dir = None
        self.preview_count = 0
        self.pending_filter = None
        self.pending_stats = None
        self._timers = set()
        self._destroyed = False

        root.title("Free TTS Studio · Kashif Javaid")
        root.geometry("1180x850")
        root.minsize(960, 740)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Destroy>", self._on_root_destroy, add="+")
        self._styles()
        self._build()
        draft = self.settings.get("draft", "")
        if isinstance(draft, str):
            self.editor.insert("1.0", draft)
        self._update_stats()
        root.bind("<Control-Return>", lambda event: self.generate())
        root.bind("<Control-o>", lambda event: self.import_text())
        self._after(80, self._poll)
        if auto_load:
            self._after(100, self.reload_voices)

    def _after(self, milliseconds, callback):
        def invoke():
            self._timers.discard(token)
            if not self._destroyed:
                callback()

        token = self.root.after_idle(invoke) if milliseconds is None else self.root.after(milliseconds, invoke)
        self._timers.add(token)
        return token

    def _cancel_after(self, token):
        self._timers.discard(token)
        try:
            self.root.after_cancel(token)
        except tk.TclError:
            pass

    def _on_root_destroy(self, event):
        if event.widget is self.root:
            self._destroyed = True
            self.cancel_event.set()
            for token in tuple(self._timers):
                self._cancel_after(token)

    def _styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=PANEL, foreground=TEXT, font=("Segoe UI", 10),
                        bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL)
        style.configure("TFrame", background=PANEL)
        style.configure("Base.TFrame", background=BG)
        style.configure("TLabel", background=PANEL, foreground=TEXT)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Section.TLabel", font=("Segoe UI", 10, "bold"), foreground=ACCENT)
        style.configure("TButton", background="#283448", padding=(12, 8), borderwidth=0)
        style.map("TButton", background=[("active", "#354764"), ("disabled", "#222a38")],
                  foreground=[("disabled", "#68778c")])
        style.configure("Accent.TButton", background="#3479ee", foreground="white",
                        font=("Segoe UI", 11, "bold"), padding=(22, 12))
        style.map("Accent.TButton", background=[("active", "#4b8cff"), ("disabled", "#263b5a")])
        style.configure("TEntry", fieldbackground=FIELD, insertcolor=TEXT, padding=7)
        style.configure("TCombobox", fieldbackground=FIELD, background="#283448", padding=5)
        style.map("TCombobox", fieldbackground=[("readonly", FIELD)],
                  foreground=[("readonly", TEXT)])
        style.configure("TCheckbutton", background=PANEL, padding=(0, 3))
        style.map("TCheckbutton", background=[("active", PANEL)])
        style.configure("Treeview", background=FIELD, fieldbackground=FIELD,
                        foreground=TEXT, rowheight=31, borderwidth=0)
        style.configure("Treeview.Heading", background="#242e3e", foreground=MUTED,
                        padding=7, font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", "#264c7f")],
                  foreground=[("selected", "white")])
        style.configure("Horizontal.TProgressbar", background="#4b8cff", troughcolor=FIELD,
                        borderwidth=0, thickness=6)
        style.configure("Horizontal.TScale", background="#79a9ff", troughcolor=FIELD,
                        lightcolor="#79a9ff", darkcolor="#79a9ff", bordercolor=FIELD,
                        sliderlength=16)
        style.map("Horizontal.TScale", background=[("active", "#a9c9ff")])
        style.configure("TScrollbar", background="#35465e", troughcolor=FIELD,
                        arrowcolor=MUTED, bordercolor=FIELD, lightcolor="#35465e",
                        darkcolor="#35465e", arrowsize=12)
        style.map("TScrollbar", background=[("active", "#536b8c")])
        self.root.option_add("*TCombobox*Listbox.background", FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#264c7f")

    def _build(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        header = tk.Frame(self.root, bg=BG)
        header.grid(row=0, column=0, sticky="ew", padx=26, pady=(23, 20))
        tk.Label(header, text="Free TTS Studio", font=("Segoe UI", 25, "bold"),
                 bg=BG, fg=TEXT).pack(side="left")
        tk.Label(header, text="TEXT IN.  VOICE OUT.", font=("Segoe UI", 9, "bold"),
                 bg=BG, fg=MUTED).pack(side="left", padx=20, pady=(10, 0))
        tk.Label(header, text="EDGE NEURAL  /  NO API KEY", font=("Segoe UI", 9),
                 bg="#1e3042", fg="#9ac4ff", padx=12, pady=7).pack(side="right")

        body = ttk.Frame(self.root, style="Base.TFrame")
        body.grid(row=1, column=0, sticky="nsew", padx=26)
        body.columnconfigure(0, weight=3, minsize=440)
        body.columnconfigure(1, weight=2, minsize=370)
        body.rowconfigure(0, weight=1)
        script = ttk.Frame(body, padding=18)
        script.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        script.columnconfigure(0, weight=1)
        script.rowconfigure(2, weight=1)
        script_top = ttk.Frame(script)
        script_top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(script_top, text="01  YOUR SCRIPT", style="Section.TLabel").pack(side="left")
        ttk.Button(script_top, text="Import text", command=self.import_text).pack(side="right")
        ttk.Button(script_top, text="Clear", command=self.clear_text).pack(side="right", padx=6)
        ttk.Label(script, text="Paste a voiceover, an article, or a whole chapter.",
                  style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 12))
        editor_frame = ttk.Frame(script)
        editor_frame.grid(row=2, column=0, sticky="nsew")
        editor_frame.rowconfigure(0, weight=1)
        editor_frame.columnconfigure(0, weight=1)
        self.editor = tk.Text(editor_frame, wrap="word", undo=True, font=("Segoe UI", 12),
                              bg=FIELD, fg=TEXT, insertbackground=ACCENT, selectbackground="#264c7f",
                              relief="flat", padx=16, pady=14, height=10, width=30,
                              spacing1=3, spacing3=5)
        self.editor.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(editor_frame, command=self.editor.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.editor.configure(yscrollcommand=scroll.set)
        self.editor.bind("<<Modified>>", self._text_changed)
        self.stats = ttk.Label(script, text="", style="Muted.TLabel")
        self.stats.grid(row=3, column=0, sticky="w", pady=(8, 18))
        ttk.Label(script, text="02  SHAPE THE DELIVERY", style="Section.TLabel").grid(
            row=4, column=0, sticky="w", pady=(0, 8))
        self.rate = tk.IntVar(value=self._saved_int("rate", -90, 100))
        self.pitch = tk.IntVar(value=self._saved_int("pitch", -100, 100))
        self.volume = tk.IntVar(value=self._saved_int("volume", -100, 100))
        controls = ttk.Frame(script)
        controls.grid(row=5, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)
        self._slider(controls, 0, "Speed", self.rate, -90, 100, "%")
        self._slider(controls, 1, "Pitch", self.pitch, -100, 100, " Hz")
        self._slider(controls, 2, "Volume", self.volume, -100, 100, "%")
        ttk.Button(controls, text="Reset", command=self.reset_delivery).grid(row=0, column=3, rowspan=3, padx=(10, 0))

        voices = ttk.Frame(body, padding=18)
        voices.grid(row=0, column=1, sticky="nsew")
        voices.columnconfigure(0, weight=1)
        voices.rowconfigure(5, weight=1)
        voice_top = ttk.Frame(voices)
        voice_top.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(voice_top, text="03  FIND YOUR VOICE", style="Section.TLabel").pack(side="left")
        self.reload_button = ttk.Button(voice_top, text="Refresh", command=self.reload_voices)
        self.reload_button.pack(side="right")
        self.search = tk.StringVar()
        self.search.trace_add("write", self._schedule_filter)
        ttk.Entry(voices, textvariable=self.search).grid(row=1, column=0, sticky="ew")
        ttk.Label(voices, text="Search name, language code, or category", style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", pady=(5, 10))
        filters = ttk.Frame(voices)
        filters.grid(row=3, column=0, sticky="ew")
        filters.columnconfigure(0, weight=1)
        filters.columnconfigure(1, weight=1)
        self.locale = tk.StringVar(value="All languages")
        self.gender = tk.StringVar(value="All genders")
        self.locale_box = ttk.Combobox(filters, textvariable=self.locale,
                                       values=["All languages"], state="readonly", width=15)
        self.locale_box.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.gender_box = ttk.Combobox(filters, textvariable=self.gender,
                                       values=["All genders", "Female", "Male"], state="readonly", width=13)
        self.gender_box.grid(row=0, column=1, sticky="ew")
        self.locale_box.bind("<<ComboboxSelected>>", self._filter_voices)
        self.gender_box.bind("<<ComboboxSelected>>", self._filter_voices)
        favorites_row = ttk.Frame(voices)
        favorites_row.grid(row=4, column=0, sticky="ew", pady=8)
        self.only_favorites = tk.BooleanVar(value=False)
        ttk.Checkbutton(favorites_row, text="Favorites", variable=self.only_favorites,
                        command=self._filter_voices).pack(side="left")
        self.voice_count = ttk.Label(favorites_row, text="Loading voices...", style="Muted.TLabel")
        self.voice_count.pack(side="right")
        tree_frame = ttk.Frame(voices)
        tree_frame.grid(row=5, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.voice_tree = ttk.Treeview(tree_frame, columns=("name", "locale", "gender"),
                                       show="headings", selectmode="browse", height=8)
        for key, label, width in (("name", "Voice", 155), ("locale", "Language", 85), ("gender", "Gender", 65)):
            self.voice_tree.heading(key, text=label)
            self.voice_tree.column(key, width=width, minwidth=55)
        self.voice_tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll = ttk.Scrollbar(tree_frame, command=self.voice_tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.voice_tree.configure(yscrollcommand=tree_scroll.set)
        self.voice_tree.bind("<<TreeviewSelect>>", self._voice_selected)
        self.voice_tree.bind("<Double-1>", lambda event: self.preview())
        self.selected_label = ttk.Label(voices, text="Select a voice to begin", style="Muted.TLabel", wraplength=330)
        self.selected_label.grid(row=6, column=0, sticky="w", pady=(10, 8))
        voice_actions = ttk.Frame(voices)
        voice_actions.grid(row=7, column=0, sticky="ew")
        self.preview_button = ttk.Button(voice_actions, text="Preview voice", command=self.preview, state="disabled")
        self.preview_button.pack(side="left")
        self.favorite_button = ttk.Button(voice_actions, text="☆ Favorite", command=self.toggle_favorite, state="disabled")
        self.favorite_button.pack(side="right")

        footer = ttk.Frame(self.root, padding=18)
        footer.grid(row=2, column=0, sticky="ew", padx=26, pady=(14, 22))
        footer.columnconfigure(0, weight=1)
        options = ttk.Frame(footer)
        options.grid(row=0, column=0, sticky="w")
        self.export_subtitles = tk.BooleanVar(value=self.settings.get("subtitles") is True)
        self.auto_play = tk.BooleanVar(value=self.settings.get("auto_play") is True)
        ttk.Checkbutton(options, text="Export subtitles (.srt)", variable=self.export_subtitles).pack(side="left")
        ttk.Checkbutton(options, text="Play after export", variable=self.auto_play).pack(side="left", padx=18)
        actions = ttk.Frame(footer)
        actions.grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 0))
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=(0, 8))
        self.generate_button = ttk.Button(actions, text="Export MP3", style="Accent.TButton",
                                          command=self.generate, state="disabled")
        self.generate_button.pack(side="left")
        self.status = ttk.Label(footer, text="Connecting to the voice catalog...", style="Muted.TLabel", wraplength=650)
        self.status.grid(row=1, column=0, sticky="ew", pady=(7, 10))
        self.status.bind("<Configure>", lambda event: self.status.configure(wraplength=max(200, event.width)))
        self.progress = ttk.Progressbar(footer, maximum=100)
        self.progress.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        lower = ttk.Frame(footer)
        lower.grid(row=3, column=0, columnspan=2, sticky="ew")
        ttk.Label(lower, text="No app character cap · Online speech · by Kashif Javaid", style="Muted.TLabel").pack(side="left")
        self.folder_button = ttk.Button(lower, text="Open folder", command=self.open_output_folder, state="disabled")
        self.folder_button.pack(side="right")
        self.play_button = ttk.Button(lower, text="Play last export", command=self.play_last, state="disabled")
        self.play_button.pack(side="right", padx=8)

    def _saved_int(self, key, minimum, maximum):
        value = self.settings.get(key, 0)
        return value if type(value) is int and minimum <= value <= maximum else 0

    def _slider(self, frame, row, label, variable, minimum, maximum, suffix):
        ttk.Label(frame, text=label, width=8).grid(row=row, column=0, sticky="w", pady=3)
        display = ttk.Label(frame, width=8, anchor="e", style="Muted.TLabel")
        display.grid(row=row, column=2)

        def changed(value=None):
            if value is not None:
                variable.set(round(float(value)))
            display.configure(text=f"{variable.get():+d}{suffix}")
            self._update_stats()

        scale = ttk.Scale(frame, from_=minimum, to=maximum, variable=variable, command=changed)
        scale.grid(row=row, column=1, sticky="ew", padx=8)
        variable.trace_add("write", lambda *args: display.configure(text=f"{variable.get():+d}{suffix}"))
        display.configure(text=f"{variable.get():+d}{suffix}")

    def reset_delivery(self):
        for variable in (self.rate, self.pitch, self.volume):
            variable.set(0)
        self._update_stats()

    def _text_changed(self, event=None):
        if self.editor.edit_modified():
            self.editor.edit_modified(False)
            if self.pending_stats:
                self._cancel_after(self.pending_stats)
            self.pending_stats = self._after(200, self._update_stats)

    def _update_stats(self):
        self.pending_stats = None
        text = self.editor.get("1.0", "end-1c").strip()
        words = len(text.split())
        rate = self.rate.get() if hasattr(self, "rate") else 0
        seconds = round(words / (150 * (1 + rate / 100)) * 60)
        self.stats.configure(text=f"{len(text):,} characters  ·  {words:,} words  ·  ~{seconds // 60}:{seconds % 60:02d} audio")

    def _schedule_filter(self, *args):
        if self.pending_filter:
            self._cancel_after(self.pending_filter)
        self.pending_filter = self._after(120, self._filter_voices)

    def _filter_voices(self, event=None):
        self.pending_filter = None
        selected = self.selected_voice() or self.preferred_voice
        children = self.voice_tree.get_children()
        if children:
            self.voice_tree.delete(*children)
        locale = "" if self.locale.get() == "All languages" else self.locale.get()
        gender = "" if self.gender.get() == "All genders" else self.gender.get()
        for voice in self.voices:
            if voice.matches(self.search.get(), locale, gender) and (
                not self.only_favorites.get() or voice.id in self.favorites
            ):
                name = ("★ " if voice.id in self.favorites else "") + voice.name
                self.voice_tree.insert("", "end", iid=voice.id, values=(name, voice.locale, voice.gender))
        count = len(self.voice_tree.get_children())
        self.voice_count.configure(text=f"{count} of {len(self.voices)} voices")
        if self.voice_tree.exists(selected):
            self.voice_tree.selection_set(selected)
            self.voice_tree.see(selected)
            self._after(None, lambda: self.voice_tree.see(selected)
                        if self.voice_tree.exists(selected) else None)
        self._voice_selected()

    def selected_voice(self):
        selection = self.voice_tree.selection()
        return selection[0] if selection else None

    def _voice_selected(self, event=None):
        selected = self.selected_voice()
        if selected:
            self.preferred_voice = selected
        self.selected_label.configure(text=selected or "No matching voice selected. Try clearing your filters.")
        self.favorite_button.configure(state="normal" if selected else "disabled",
                                       text="★ Saved" if selected in self.favorites else "☆ Favorite")
        self._update_buttons()

    def toggle_favorite(self):
        selected = self.selected_voice()
        if selected:
            if selected in self.favorites:
                self.favorites.remove(selected)
            else:
                self.favorites.add(selected)
            self._filter_voices()

    def _update_buttons(self):
        enabled = bool(self.selected_voice()) and not self.busy
        self.generate_button.configure(state="normal" if enabled else "disabled")
        self.preview_button.configure(state="normal" if enabled else "disabled")
        self.cancel_button.configure(state="normal" if self.busy else "disabled")
        self.reload_button.configure(state="disabled" if self.loading or self.busy else "normal")

    def reload_voices(self):
        if self.loading or self.busy:
            return
        self.loading = True
        self.status.configure(text="Refreshing the online voice catalog...")
        self._update_buttons()

        def work():
            try:
                result = asyncio.run(load_voices(self.data_dir / "voices.json"))
                self.events.put(("voices", result))
            except Exception as error:
                LOGGER.exception("Voice catalog failed")
                self.events.put(("voice_error", friendly_error(error)))

        threading.Thread(target=work, daemon=True, name="voice-catalog").start()

    def import_text(self):
        path = filedialog.askopenfilename(parent=self.root, title="Import a script",
                                          filetypes=[("Text and Markdown", "*.txt *.md"), ("All files", "*.*")])
        if not path:
            return
        try:
            raw = Path(path).read_bytes()
            text = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
        except (OSError, UnicodeError) as error:
            messagebox.showerror("Cannot import text", f"Use a UTF-8 or UTF-16 text file.\n\n{error}", parent=self.root)
            return
        if self.editor.get("1.0", "end-1c").strip() and not messagebox.askyesno(
            "Replace script?", "Replace the current script with this file?", parent=self.root
        ):
            return
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)
        self._update_stats()

    def clear_text(self):
        if self.editor.get("1.0", "end-1c").strip() and messagebox.askyesno(
            "Clear script?", "Clear the current script? You can undo with Ctrl+Z.", parent=self.root
        ):
            self.editor.delete("1.0", "end")

    def _options(self, subtitles=False):
        return SpeechOptions(voice=self.selected_voice() or "", rate=self.rate.get(),
                             pitch=self.pitch.get(), volume=self.volume.get(), subtitles=subtitles)

    def generate(self):
        if self.busy:
            return
        text = clean_text(self.editor.get("1.0", "end-1c"))
        if not text:
            messagebox.showinfo("Add your script", "Type, paste, or import some text first.", parent=self.root)
            return
        if not self.selected_voice():
            messagebox.showinfo("Choose a voice", "Select a voice from the catalog first.", parent=self.root)
            return
        last_folder = self.settings.get("output_dir", "")
        initial_dir = last_folder if isinstance(last_folder, str) and Path(last_folder).is_dir() else str(Path.home())
        filename = filedialog.asksaveasfilename(
            parent=self.root, title="Export your voiceover", defaultextension=".mp3",
            initialdir=initial_dir, initialfile=f"voiceover-{self.selected_voice()}.mp3",
            filetypes=[("MP3 audio", "*.mp3")],
        )
        if not filename:
            return
        output = Path(filename)
        if self.export_subtitles.get() and output.with_suffix(".srt").exists():
            if not messagebox.askyesno("Replace subtitles?", f"Replace {output.with_suffix('.srt').name}?", parent=self.root):
                return
        self.settings["output_dir"] = str(output.parent)
        self._save_session()
        self._start_job(text, self._options(self.export_subtitles.get()), output, preview=False)

    def preview(self):
        if self.busy or not self.selected_voice():
            return
        text = clean_text(self.editor.get("1.0", "end-1c"))[:280]
        if not text:
            text = "Hello! This is a preview of your selected voice. Add your own script to hear it here."
        try:
            if self.preview_dir is None:
                self.data_dir.mkdir(parents=True, exist_ok=True)
                self.preview_dir = tempfile.TemporaryDirectory(prefix=".tts-preview-", dir=self.data_dir)
            self.preview_count += 1
            output = Path(self.preview_dir.name) / f"preview-{self.preview_count}.mp3"
            self._start_job(text, self._options(), output, preview=True)
        except OSError as error:
            messagebox.showerror("Cannot preview", friendly_error(error), parent=self.root)

    def _start_job(self, text, options, output, *, preview):
        self.busy = True
        self.cancel_event = threading.Event()
        self.progress["value"] = 0
        self.status.configure(text="Preparing voice preview..." if preview else "Preparing your voiceover...")
        self._update_buttons()
        auto_play = preview or self.auto_play.get()

        def work():
            try:
                result = asyncio.run(generate_speech(
                    text, options, output, cancel=self.cancel_event,
                    on_progress=lambda progress: self.events.put(("progress", progress)),
                ))
                self.events.put(("done", (result, preview, auto_play)))
            except GenerationCancelled:
                self.events.put(("cancelled", None))
            except Exception as error:
                LOGGER.exception("Speech generation failed")
                self.events.put(("job_error", friendly_error(error)))

        self.worker = threading.Thread(target=work, daemon=True, name="speech-generation")
        self.worker.start()

    def cancel(self):
        if self.busy:
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.status.configure(text="Cancelling and cleaning up...")

    def _poll(self):
        # This is the only bridge from workers to Tk. Workers never touch a widget.
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            self._handle_event(kind, value)
            if self.closing and not self.busy:
                self._destroy()
                return
        self._after(80, self._poll)

    def _handle_event(self, kind, value):
        if kind == "progress":
            if not self.cancel_event.is_set():
                self.progress["value"] = value.fraction * 100
                self.status.configure(text=value.message)
        elif kind == "voices":
            self.loading = False
            self.voices, warning = value
            self.voice_by_id = {voice.id: voice for voice in self.voices}
            locales = sorted({voice.locale for voice in self.voices})
            self.locale_box.configure(values=["All languages", *locales])
            if self.locale.get() not in locales:
                self.locale.set("All languages")
            genders = sorted({voice.gender for voice in self.voices})
            self.gender_box.configure(values=["All genders", *genders])
            if self.gender.get() not in genders:
                self.gender.set("All genders")
            if self.preferred_voice not in self.voice_by_id:
                self.preferred_voice = self.voices[0].id
            self._filter_voices()
            if not self.busy:
                self.status.configure(text=warning or f"Ready · {len(self.voices)} voices across {len(locales)} locales")
        elif kind == "voice_error":
            self.loading = False
            self.voice_count.configure(text="Catalog unavailable" if not self.voices else f"{len(self.voices)} saved voices")
            if not self.busy:
                self.status.configure(text=value)
        elif kind in ("done", "cancelled", "job_error"):
            self.busy = False
            if kind == "done":
                result, preview, auto_play = value
                self.progress["value"] = 100
                self.status.configure(text="Preview ready" if preview else f"Saved: {result.audio_path.name}" + (
                    " + subtitles" if result.subtitle_path else ""))
                if not preview:
                    self.last_output = result.audio_path
                    self.play_button.configure(state="normal")
                    self.folder_button.configure(state="normal")
                if auto_play and not self.closing:
                    self._open(result.audio_path)
            else:
                self.progress["value"] = 0
                self.status.configure(text="Cancelled. Your existing files are unchanged." if kind == "cancelled" else value)
                if kind == "job_error" and not self.closing:
                    messagebox.showerror("Could not generate speech", value, parent=self.root)
        self._update_buttons()

    def _open(self, path):
        try:
            open_path(path)
        except (OSError, RuntimeError, SubprocessError) as error:
            self.status.configure(text=f"Audio is saved, but could not open it: {friendly_error(error)}")

    def play_last(self):
        if self.last_output:
            self._open(self.last_output)

    def open_output_folder(self):
        if self.last_output:
            self._open(self.last_output.parent)

    def _save_session(self):
        self.settings.update({
            "draft": self.editor.get("1.0", "end-1c"), "voice": self.preferred_voice,
            "rate": self.rate.get(), "pitch": self.pitch.get(), "volume": self.volume.get(),
            "favorites": sorted(self.favorites), "subtitles": self.export_subtitles.get(),
            "auto_play": self.auto_play.get(),
        })
        try:
            write_json(self.data_dir / "session.json", self.settings)
        except OSError:
            LOGGER.warning("Could not save this session", exc_info=True)

    def close(self):
        if self.closing:
            return
        self._save_session()
        self.closing = True
        if self.busy:
            self.cancel()
            self.status.configure(text="Finishing cleanup before closing...")
        else:
            self._destroy()

    def _destroy(self):
        if self.preview_dir is not None:
            try:
                self.preview_dir.cleanup()
            except OSError:
                LOGGER.warning("Preview audio is still in use by a player", exc_info=True)
        self.root.destroy()


def main():
    root = tk.Tk()
    if DEPENDENCY_ERROR is not None:
        root.withdraw()
        messagebox.showerror("Install the app dependencies", "Run this command in the project folder:\n\n"
                             "python -m pip install --upgrade -r requirements.txt\n\n"
                             f"Details: {DEPENDENCY_ERROR}", parent=root)
        root.destroy()
        return
    try:
        folder = user_data_dir()
        folder.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=folder / "app.log", level=logging.WARNING,
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    except OSError:
        logging.basicConfig(level=logging.WARNING)
    TTSApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
