"""
Free TTS Generator (Edge-TTS) - All Voices, Unlimited Length
Made by: Kashif Javaid
GitHub: https://github.com/imkashifjavaid
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import asyncio
import threading
import re
import os
import sys
import subprocess
import edge_tts

MAX_CHUNK_CHARS = 1800

def play_audio(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass

def split_text(text, max_chars=MAX_CHUNK_CHARS):
    sentences = re.split(r'(?<=[.?!।])\s+', text)
    chunks = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_chars:
            current = (current + " " + sentence).strip()
        else:
            if current:
                chunks.append(current)
            while len(sentence) > max_chars:
                chunks.append(sentence[:max_chars])
                sentence = sentence[max_chars:]
            current = sentence
    if current:
        chunks.append(current)
    return chunks

def generate_audio(text, voice, out_path, status_label, generate_btn, progress_bar, auto_play):
    async def run_chunk(chunk_text, chunk_path):
        communicate = edge_tts.Communicate(chunk_text, voice)
        await communicate.save(chunk_path)

    try:
        base, ext = os.path.splitext(out_path)
        final_path = f"{base}__{voice}{ext}"

        chunks = split_text(text)
        total = len(chunks)
        temp_files = []

        for i, chunk in enumerate(chunks, start=1):
            status_label.config(text=f"Generating part {i}/{total}...", fg="blue")
            progress_bar["value"] = (i - 1) / total * 100
            progress_bar.update()

            temp_path = f"{final_path}.part{i}.mp3"
            asyncio.run(run_chunk(chunk, temp_path))
            temp_files.append(temp_path)

        status_label.config(text="Merging audio parts...", fg="blue")
        progress_bar["value"] = 95
        progress_bar.update()

        with open(final_path, "wb") as outfile:
            for temp_path in temp_files:
                with open(temp_path, "rb") as infile:
                    outfile.write(infile.read())

        for temp_path in temp_files:
            os.remove(temp_path)

        progress_bar["value"] = 100
        status_label.config(text=f"Done! Saved: {os.path.basename(final_path)}", fg="green")

        if auto_play:
            play_audio(final_path)

    except Exception as e:
        status_label.config(text=f"Error: {e}", fg="red")
    finally:
        generate_btn.config(state="normal")

def on_generate():
    text = text_box.get("1.0", tk.END).strip()
    if not text:
        messagebox.showwarning("Empty Text", "Please type or paste some text first.")
        return

    selection = voice_listbox.curselection()
    if not selection:
        messagebox.showwarning("No Voice Selected", "Please select a voice from the list below.")
        return

    voice_label = voice_listbox.get(selection[0])
    voice_code = voice_map[voice_label]

    out_path = filedialog.asksaveasfilename(
        defaultextension=".mp3",
        filetypes=[("MP3 files", "*.mp3")],
        title="Save audio as"
    )
    if not out_path:
        return

    status_label.config(text="Starting...", fg="blue")
    progress_bar["value"] = 0
    generate_btn.config(state="disabled")

    thread = threading.Thread(
        target=generate_audio,
        args=(text, voice_code, out_path, status_label, generate_btn, progress_bar, auto_play_var.get())
    )
    thread.start()

def refresh_list(*args):
    """Real-time filter based on ticked language checkboxes + gender checkboxes + free text search."""
    query = search_var.get().lower().strip()

    active_langs = [code for code, var in lang_vars.items() if var.get()]
    active_genders = [g for g, var in gender_vars.items() if var.get()]

    voice_listbox.delete(0, tk.END)
    count = 0
    for label, code in voice_map.items():
        locale = voice_locale.get(label, "")
        gender = voice_gender.get(label, "")

        if active_langs and locale not in active_langs:
            continue
        if active_genders and gender not in active_genders:
            continue
        if query and query not in label.lower():
            continue

        voice_listbox.insert(tk.END, label)
        count += 1

    result_count_label.config(text=f"{count} voice(s) match")

def load_voices():
    async def fetch():
        return await edge_tts.list_voices()

    try:
        all_voices = asyncio.run(fetch())
        all_voices.sort(key=lambda v: v["ShortName"])
        for v in all_voices:
            label = f"{v['ShortName']}  |  {v['Locale']}  |  {v['Gender']}"
            voice_map[label] = v["ShortName"]
            voice_locale[label] = v["Locale"]
            voice_gender[label] = v["Gender"]

        status_label.config(text=f"{len(voice_map)} voices loaded.", fg="green")
        refresh_list()
    except Exception as e:
        status_label.config(text=f"Could not load voice list: {e}", fg="red")

# --- GUI Layout ---
root = tk.Tk()
root.title("Free TTS Generator (Edge-TTS) by imkashifjavaid")
root.geometry("680x780")
root.resizable(False, False)

voice_map = {}      # label -> ShortName
voice_locale = {}   # label -> Locale (e.g. en-US)
voice_gender = {}   # label -> Gender

tk.Label(root, text="Paste Your Script Here (no length limit):", font=("Arial", 12, "bold")).pack(pady=(15, 5))
tk.Label(root, text="by imkashifjavaid", font=("Arial", 9), fg="gray").pack()

text_box = tk.Text(root, height=10, width=75, font=("Arial", 11), wrap="word")
text_box.pack(padx=15, pady=5)

# --- Filters ---
filter_frame = tk.LabelFrame(root, text="Filters (tick to narrow down)", font=("Arial", 11, "bold"), padx=10, pady=10)
filter_frame.pack(padx=15, pady=(15, 5), fill="x")

lang_row = tk.Frame(filter_frame)
lang_row.pack(anchor="w", pady=(0, 5))
tk.Label(lang_row, text="Language:", font=("Arial", 10, "bold"), width=10, anchor="w").pack(side="left")

lang_vars = {
    "en-US": tk.BooleanVar(value=False),
    "en-GB": tk.BooleanVar(value=False),
    "hi-IN": tk.BooleanVar(value=False),
}
for code, var in lang_vars.items():
    cb = tk.Checkbutton(lang_row, text=code, variable=var, command=refresh_list, font=("Arial", 10))
    cb.pack(side="left", padx=5)

gender_row = tk.Frame(filter_frame)
gender_row.pack(anchor="w")
tk.Label(gender_row, text="Gender:", font=("Arial", 10, "bold"), width=10, anchor="w").pack(side="left")

gender_vars = {
    "Male": tk.BooleanVar(value=False),
    "Female": tk.BooleanVar(value=False),
}
for g, var in gender_vars.items():
    cb = tk.Checkbutton(gender_row, text=g, variable=var, command=refresh_list, font=("Arial", 10))
    cb.pack(side="left", padx=5)

search_row = tk.Frame(filter_frame)
search_row.pack(anchor="w", pady=(8, 0), fill="x")
tk.Label(search_row, text="Search:", font=("Arial", 10, "bold"), width=10, anchor="w").pack(side="left")
search_var = tk.StringVar()
search_var.trace_add("write", refresh_list)
tk.Entry(search_row, textvariable=search_var, width=40, font=("Arial", 10)).pack(side="left", fill="x", expand=True)

result_count_label = tk.Label(filter_frame, text="", font=("Arial", 9), fg="gray")
result_count_label.pack(anchor="w", pady=(5, 0))

# --- Voice list ---
tk.Label(root, text="Select a Voice:", font=("Arial", 12, "bold")).pack(pady=(10, 5))

list_frame = tk.Frame(root)
list_frame.pack(padx=15, fill="both")

scrollbar = tk.Scrollbar(list_frame, orient="vertical")
voice_listbox = tk.Listbox(list_frame, height=10, width=80, font=("Consolas", 10),
                            yscrollcommand=scrollbar.set, exportselection=False)
scrollbar.config(command=voice_listbox.yview)
voice_listbox.pack(side="left", fill="both", expand=True)
scrollbar.pack(side="right", fill="y")

# --- Generate ---
auto_play_var = tk.BooleanVar(value=True)
tk.Checkbutton(root, text="Auto-play after generating (for quick testing)",
               variable=auto_play_var, font=("Arial", 10)).pack(pady=(12, 0))

generate_btn = tk.Button(root, text="Generate & Save MP3", font=("Arial", 12, "bold"),
                          bg="#4CAF50", fg="white", padx=10, pady=8, command=on_generate)
generate_btn.pack(pady=12)

progress_bar = ttk.Progressbar(root, orient="horizontal", length=400, mode="determinate")
progress_bar.pack(pady=5)

status_label = tk.Label(root, text="Loading voice list...", font=("Arial", 10))
status_label.pack(pady=5)

credits_label = tk.Label(root, text="github.com/imkashifjavaid", font=("Arial", 9), fg="gray")
credits_label.pack(pady=(5, 10))

threading.Thread(target=load_voices, daemon=True).start()

root.mainloop()
