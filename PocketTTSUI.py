import gc
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
import tkinter as tk

from tkinter import filedialog, messagebox, simpledialog, ttk

np = None
fitz = None
requests = None
BeautifulSoup = None
ebooklib = None
epub = None
sf = None
scipy_wav = None
torch = None
TTSModel = None
POCKET_AVAILABLE = False
_libs_loaded = False

DEFAULT_CHUNK_SIZE = 100
SAMPLE_TEXT = (
    "Greetings Human, I am here to tell you a cat fact. "
    "Did you know that cats sleep for 70% of their lives?"
)
VOICE_OPTIONS = [
    "alba",
    "marius",
    "javert",
    "jean",
    "fantine",
    "cosette",
    "eponine",
    "azelma",
]

pocket_model = None
is_model_loading = False
stop_event = threading.Event()


def _ensure_libs_loaded():
    global np, fitz, requests, BeautifulSoup, ebooklib, epub
    global sf, scipy_wav, torch, TTSModel, POCKET_AVAILABLE, _libs_loaded
    if _libs_loaded:
        return

    import numpy
    np = numpy

    import fitz as _fitz
    fitz = _fitz

    import requests as _requests
    requests = _requests

    from bs4 import BeautifulSoup as _bs
    BeautifulSoup = _bs

    import ebooklib as _ebooklib
    ebooklib = _ebooklib
    from ebooklib import epub as _epub
    epub = _epub

    import soundfile as _soundfile
    sf = _soundfile

    import scipy.io.wavfile as _wavfile
    scipy_wav = _wavfile

    try:
        from pocket_tts import TTSModel as _tts_model
        import torch as _torch

        TTSModel = _tts_model
        torch = _torch
        POCKET_AVAILABLE = True
    except ImportError:
        POCKET_AVAILABLE = False
        print("WARNING: PocketTTS or Torch not found. Install them first.")

    _libs_loaded = True


def ensure_model_loaded():
    global pocket_model, is_model_loading
    if pocket_model is not None:
        return True

    if is_model_loading:
        while is_model_loading:
            time.sleep(0.5)
        return pocket_model is not None

    is_model_loading = True
    _ensure_libs_loaded()
    try:
        print("[System] Loading PocketTTS model...")
        pocket_model = TTSModel.load_model()
        print("[System] Model loaded successfully (CPU).")
    except Exception as exc:
        print(f"[System] Failed to load model: {exc}")
        pocket_model = None
    finally:
        is_model_loading = False

    return pocket_model is not None


def split_text_into_chunks(words, original_chunk_size, wiggle_room=20):
    def is_sentence_end(word):
        return word[-1] in ".!?" if word else False

    chunks = []
    current_chunk = []
    word_count = 0
    i = 0

    while i < len(words):
        current_chunk.append(words[i])
        word_count += 1
        i += 1

        if word_count >= original_chunk_size:
            if is_sentence_end(words[i - 1]):
                chunks.append(current_chunk)
                current_chunk = []
                word_count = 0
            else:
                found = False
                for j in range(wiggle_room):
                    if i + j < len(words) and is_sentence_end(words[i + j]):
                        current_chunk.extend(words[i : i + j + 1])
                        i += j + 1
                        found = True
                        break

                if not found:
                    for k in range(len(current_chunk) - 1, 0, -1):
                        if is_sentence_end(current_chunk[k]):
                            leftover = current_chunk[k + 1 :]
                            chunks.append(current_chunk[: k + 1])
                            current_chunk = leftover
                            word_count = len(leftover)
                            found = True
                            break

                if found and word_count != len(current_chunk):
                    chunks.append(current_chunk)
                    current_chunk = []
                    word_count = 0
                elif not found:
                    chunks.append(current_chunk)
                    current_chunk = []
                    word_count = 0

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def prepare_voice_state(ref_audio_path, voice_name):
    global pocket_model
    final_prompt = voice_name
    temp_file = None

    if ref_audio_path and os.path.exists(ref_audio_path):
        try:
            data, samplerate = sf.read(ref_audio_path)
            max_samples = 5 * samplerate
            if len(data) > max_samples:
                print(f"[System] Truncating ref audio from {len(data)} to {max_samples} samples.")
                data = data[:max_samples]

            temp_file = os.path.abspath("temp_pocket_ref.wav")
            sf.write(temp_file, data, samplerate, subtype="PCM_16")
            final_prompt = temp_file
            print(f"[System] Using processed ref audio: {temp_file}")
        except Exception as exc:
            print(f"[Warning] Failed to process ref audio: {exc}. Falling back to name.")
            final_prompt = voice_name

    state = pocket_model.get_state_for_audio_prompt(final_prompt)
    return state, temp_file


def _generate_pocket_safe(state, text):
    global pocket_model
    chunk_size = 200

    raw_chunks = re.split(r"([.!?]+)", text)
    chunks = []
    current = ""
    for part in raw_chunks:
        if len(current) + len(part) < chunk_size:
            current += part
        else:
            if current:
                chunks.append(current)
            current = part
    if current:
        chunks.append(current)

    final_chunks = []
    for chunk in chunks:
        if not chunk.strip():
            continue
        while len(chunk) > chunk_size:
            split = chunk[:chunk_size].rfind(" ")
            if split == -1:
                split = chunk_size
            final_chunks.append(chunk[:split])
            chunk = chunk[split:]
        final_chunks.append(chunk)

    full_audio = []
    for chunk in final_chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        tensor = pocket_model.generate_audio(state, chunk)
        if tensor is not None:
            full_audio.append(tensor.numpy())

    if not full_audio:
        return None
    return np.concatenate(full_audio)


def apply_speed_to_audio(file_path, speed):
    if speed == 1.0:
        return True

    temp_file = file_path + ".speed.wav"
    try:
        command = [
            "ffmpeg",
            "-y",
            "-i",
            file_path,
            "-filter:a",
            f"atempo={speed}",
            temp_file,
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            os.replace(temp_file, file_path)
            return True

        print(f"[System] FFmpeg speed error: {result.stderr}")
        return False
    except Exception as exc:
        print(f"[System] Failed to apply speed: {exc}")
        return False
    finally:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError:
                pass


def synthesize_chunk_to_file(state, text, out_path, temp_val=0.7, speed_val=1.0):
    global pocket_model
    pocket_model.temp = temp_val

    audio_np = _generate_pocket_safe(state, text)
    if audio_np is None:
        raise RuntimeError("No audio generated.")

    scipy_wav.write(out_path, pocket_model.sample_rate, audio_np)

    if speed_val != 1.0:
        apply_speed_to_audio(out_path, speed_val)


def combine_output_to_mp3(output_files, output_dir, custom_name="final_output"):
    if not output_files:
        return None

    if not custom_name.lower().endswith(".mp3"):
        custom_name += ".mp3"

    list_file = os.path.join(output_dir, "file_list.txt")
    output_mp3 = os.path.join(output_dir, custom_name)

    try:
        with open(list_file, "w", encoding="utf-8") as handle:
            for file_path in output_files:
                abs_path = os.path.abspath(file_path).replace("'", "'\\''")
                handle.write(f"file '{abs_path}'\n")

        print(f"[System] Merging {len(output_files)} files into {output_mp3}...")
        command = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            list_file,
            "-acodec",
            "libmp3lame",
            "-q:a",
            "2",
            output_mp3,
        ]
        result = subprocess.run(command, capture_output=True, text=True)

        if result.returncode == 0:
            print("[System] MP3 merge successful. Cleaning up WAV files...")
            for file_path in output_files:
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
            return output_mp3

        print(f"[System] FFmpeg error: {result.stderr}")
        return None
    except Exception as exc:
        print(f"[System] Failed to merge MP3: {exc}")
        return None
    finally:
        if os.path.exists(list_file):
            try:
                os.remove(list_file)
            except OSError:
                pass


class PocketTTSWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PocketTTS Generator")
        self.geometry("920x760")
        self.minsize(850, 760)
        self.configure(bg="#171a21")

        self.ref_audio_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.voice_var = tk.StringVar(value=VOICE_OPTIONS[0])
        self.chunk_size_var = tk.IntVar(value=DEFAULT_CHUNK_SIZE)
        self.temp_var = tk.DoubleVar(value=0.7)
        self.speed_var = tk.DoubleVar(value=1.0)
        self.start_chunk_var = tk.IntVar(value=1)
        self.combine_mp3_var = tk.BooleanVar(value=True)
        self.mp3_name_var = tk.StringVar(value="final_output")
        self.status_var = tk.StringVar(value="Ready")
        self.chunk_info_var = tk.StringVar(value="")

        self._configure_theme()
        self._build_layout()

    def _configure_theme(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Root.TFrame", background="#171a21")
        style.configure("Card.TFrame", background="#1f2430")
        style.configure("Title.TLabel", background="#171a21", foreground="#8ec5ff", font=("Segoe UI", 18, "bold"))
        style.configure("Sub.TLabel", background="#171a21", foreground="#8c98b8", font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background="#1f2430", foreground="#8ec5ff", font=("Segoe UI", 11, "bold"))
        style.configure("Body.TLabel", background="#1f2430", foreground="#d7deed")
        style.configure("Info.TLabel", background="#1f2430", foreground="#b1bbd1")
        style.configure("Status.TLabel", background="#1f2430", foreground="#9ee6a8", font=("Segoe UI", 11, "bold"))
        style.configure("TEntry", fieldbackground="#2a3142", foreground="#edf2ff")
        style.configure("TCombobox", fieldbackground="#2a3142", foreground="#edf2ff")
        style.map("TCombobox", fieldbackground=[("readonly", "#2a3142")], foreground=[("readonly", "#edf2ff")])
        style.configure("TSpinbox", fieldbackground="#2a3142", foreground="#edf2ff")
        style.configure("TCheckbutton", background="#1f2430", foreground="#d7deed")
        style.configure("TButton", background="#36415a", foreground="#f4f7ff", padding=8)
        style.map("TButton", background=[("active", "#475675")])
        style.configure("Accent.TButton", background="#8ec5ff", foreground="#102030", padding=9)
        style.map("Accent.TButton", background=[("active", "#a6d4ff")])
        style.configure("Danger.TButton", background="#f08ea2", foreground="#201419", padding=9)
        style.map("Danger.TButton", background=[("active", "#ffabc0")])
        style.configure("Sample.TButton", background="#7fd9c5", foreground="#112822", padding=9)
        style.map("Sample.TButton", background=[("active", "#93ead6")])
        style.configure("TProgressbar", troughcolor="#2a3142", background="#8ec5ff", bordercolor="#2a3142")

    def _build_layout(self):
        root = ttk.Frame(self, style="Root.TFrame", padding=18)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        ttk.Label(root, text="PocketTTS Generator", style="Title.TLabel").grid(row=0, column=0, sticky="ew")

        content = ttk.Frame(root, style="Root.TFrame")
        content.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        content.columnconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)

        self._build_inputs_card(content).grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self._build_text_card(content).grid(row=1, column=0, sticky="nsew", pady=(0, 12))
        self._build_settings_card(content).grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self._build_actions_card(content).grid(row=3, column=0, sticky="ew", pady=(0, 12))
        self._build_progress_card(content).grid(row=4, column=0, sticky="ew")

    def _card(self, parent, title):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=14)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text=title, style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))
        return frame

    def _build_inputs_card(self, parent):
        frame = self._card(parent, "Inputs")
        body = ttk.Frame(frame, style="Card.TFrame")
        body.grid(row=1, column=0, sticky="ew")
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="Ref Audio (.wav/.mp3):", style="Body.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=5)
        ttk.Entry(body, textvariable=self.ref_audio_var).grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Button(body, text="Browse", command=self.browse_ref_file).grid(row=0, column=2, padx=(10, 0), pady=5)

        ttk.Label(body, text="Output Directory:", style="Body.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=5)
        ttk.Entry(body, textvariable=self.output_dir_var).grid(row=1, column=1, sticky="ew", pady=5)
        ttk.Button(body, text="Browse", command=self.browse_output_dir).grid(row=1, column=2, padx=(10, 0), pady=5)
        return frame

    def _build_text_card(self, parent):
        frame = self._card(parent, "Text to Speak")
        frame.rowconfigure(1, weight=1)

        text_frame = ttk.Frame(frame, style="Card.TFrame")
        text_frame.grid(row=1, column=0, sticky="nsew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)

        self.text_input = tk.Text(
            text_frame,
            wrap="word",
            height=5,
            bg="#2a3142",
            fg="#edf2ff",
            insertbackground="#edf2ff",
            relief="flat",
            padx=10,
            pady=10,
        )
        self.text_input.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.text_input.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.text_input.configure(yscrollcommand=scrollbar.set)

        actions = ttk.Frame(frame, style="Card.TFrame")
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(actions, text="Load PDF/Text/EPUB", command=self.load_text).pack(side="left")
        ttk.Button(actions, text="Scrape from URL", command=self.load_url).pack(side="left", padx=(8, 0))
        return frame

    def _build_settings_card(self, parent):
        frame = self._card(parent, "Settings")
        body = ttk.Frame(frame, style="Card.TFrame")
        body.grid(row=1, column=0, sticky="ew")
        for col in range(4):
            body.columnconfigure(col, weight=1 if col in (1, 3) else 0)

        ttk.Label(body, text="Voice Name:", style="Body.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=5)
        ttk.Combobox(body, textvariable=self.voice_var, values=VOICE_OPTIONS, state="readonly").grid(row=0, column=1, sticky="ew", pady=5)

        ttk.Label(body, text="Chunk Size (words):", style="Body.TLabel").grid(row=0, column=2, sticky="w", padx=(12, 10), pady=5)
        ttk.Spinbox(body, from_=10, to=5000, textvariable=self.chunk_size_var, width=10).grid(row=0, column=3, sticky="w", pady=5)

        ttk.Label(body, text="Temperature:", style="Body.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=5)
        tk.Scale(body, from_=0.1, to=2.0, resolution=0.1, orient="horizontal", variable=self.temp_var, bg="#1f2430", fg="#d7deed", highlightthickness=0, troughcolor="#2a3142").grid(row=1, column=1, sticky="ew", pady=5)

        ttk.Label(body, text="Speed:", style="Body.TLabel").grid(row=1, column=2, sticky="w", padx=(12, 10), pady=5)
        tk.Scale(body, from_=0.5, to=2.0, resolution=0.05, orient="horizontal", variable=self.speed_var, bg="#1f2430", fg="#d7deed", highlightthickness=0, troughcolor="#2a3142").grid(row=1, column=3, sticky="ew", pady=5)

        ttk.Label(body, text="Start Chunk:", style="Body.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=5)
        ttk.Spinbox(body, from_=1, to=9999, textvariable=self.start_chunk_var, width=10).grid(row=2, column=1, sticky="w", pady=5)

        mp3_row = ttk.Frame(body, style="Card.TFrame")
        mp3_row.grid(row=2, column=2, columnspan=2, sticky="w", pady=5)
        ttk.Checkbutton(mp3_row, text="Combine into MP3", variable=self.combine_mp3_var).pack(side="left")
        ttk.Entry(mp3_row, textvariable=self.mp3_name_var, width=22).pack(side="left", padx=(10, 0))
        return frame

    def _build_actions_card(self, parent):
        frame = self._card(parent, "Actions")
        body = ttk.Frame(frame, style="Card.TFrame")
        body.grid(row=1, column=0, sticky="ew")

        ttk.Button(body, text="Export Chunk", command=lambda: self.export_chunk(False)).pack(side="left")
        ttk.Button(body, text="Export All", command=lambda: self.export_chunk(True)).pack(side="left", padx=(8, 0))
        ttk.Button(body, text="Open Folder", command=self.open_output_folder).pack(side="left", padx=(8, 0))

        self.generate_btn = ttk.Button(body, text="Generate Speech", style="Accent.TButton", command=self.start_generation)
        self.generate_btn.pack(side="left", padx=(8, 0))
        ttk.Button(body, text="Stop", style="Danger.TButton", command=self.stop_generation).pack(side="left", padx=(8, 0))
        ttk.Button(body, text="Quick Sample", style="Sample.TButton", command=self.generate_quick_sample).pack(side="left", padx=(8, 0))
        return frame

    def _build_progress_card(self, parent):
        frame = self._card(parent, "Progress")
        body = ttk.Frame(frame, style="Card.TFrame")
        body.grid(row=1, column=0, sticky="ew")
        body.columnconfigure(0, weight=1)

        ttk.Label(body, textvariable=self.chunk_info_var, style="Info.TLabel").grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.progress_bar = ttk.Progressbar(body, mode="determinate", maximum=1)
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(body, textvariable=self.status_var, style="Status.TLabel").grid(row=2, column=0, sticky="ew")
        return frame

    def _get_text(self):
        return self.text_input.get("1.0", "end-1c")

    def _set_text(self, value):
        self.text_input.delete("1.0", "end")
        self.text_input.insert("1.0", value)

    def _ui(self, callback, *args):
        self.after(0, lambda: callback(*args))

    def _set_status(self, text):
        self._ui(self.status_var.set, text)

    def _set_chunk_info(self, text):
        self._ui(self.chunk_info_var.set, text)

    def _set_progress(self, value, maximum):
        self._ui(self.progress_bar.configure, maximum=max(maximum, 1), value=value)

    def _set_generate_enabled(self, enabled):
        self._ui(self.generate_btn.configure, state=("normal" if enabled else "disabled"))

    def browse_ref_file(self):
        filename = filedialog.askopenfilename(title="Select Reference Audio", filetypes=[("Audio Files", "*.wav *.mp3"), ("All Files", "*.*")])
        if filename:
            self.ref_audio_var.set(filename)

    def browse_output_dir(self):
        directory = filedialog.askdirectory(title="Select Output Directory")
        if directory:
            self.output_dir_var.set(directory)

    def load_text(self):
        file_path = filedialog.askopenfilename(title="Select Document", filetypes=[("Documents", "*.pdf *.txt *.epub"), ("All Files", "*.*")])
        if not file_path:
            return

        try:
            _ensure_libs_loaded()
            loaded_text = ""
            lower_path = file_path.lower()

            if lower_path.endswith(".pdf"):
                with fitz.open(file_path) as doc:
                    loaded_text = "".join(page.get_text() for page in doc)
            elif lower_path.endswith(".txt"):
                with open(file_path, "r", encoding="utf-8") as handle:
                    loaded_text = handle.read()
            elif lower_path.endswith(".epub"):
                book = epub.read_epub(file_path)
                parts = []
                for item in book.get_items():
                    if item.get_type() == ebooklib.ITEM_DOCUMENT:
                        soup = BeautifulSoup(item.get_body_content(), "html.parser")
                        parts.append(soup.get_text(" ", strip=True))
                loaded_text = "\n\n".join(part for part in parts if part)

            self._set_text(loaded_text)
            self.status_var.set(f"Loaded text from {os.path.basename(file_path)}.")
        except Exception as exc:
            traceback.print_exc()
            messagebox.showerror("Load Error", f"Failed to load document:\n{exc}")
            self.status_var.set(f"Load error: {exc}")

    def load_url(self):
        url = simpledialog.askstring("Scrape URL", "Enter URL:", parent=self)
        if not url:
            return

        def task():
            try:
                _ensure_libs_loaded()
                response = requests.get(url, timeout=20)
                response.raise_for_status()
                soup = BeautifulSoup(response.content, "html.parser")
                scraped = "\n".join(p.get_text(" ", strip=True) for p in soup.find_all("p"))
                self._ui(self._set_text, scraped)
                self._set_status("Text loaded from URL.")
            except Exception as exc:
                self._set_status(f"Error loading URL: {exc}")

        threading.Thread(target=task, daemon=True).start()

    def export_chunk(self, all_chunks=False):
        try:
            full_text = self._get_text().strip()
            words = full_text.split()
            chunk_size = self.chunk_size_var.get()
            chunks = split_text_into_chunks(words, chunk_size)

            script_dir = os.path.dirname(os.path.abspath(__file__))
            if all_chunks:
                for index, chunk in enumerate(chunks, start=1):
                    path = os.path.join(script_dir, f"chunk_{index}.txt")
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write(" ".join(chunk))
                self.status_var.set(f"All {len(chunks)} chunks exported.")
            else:
                chunk_id = self.start_chunk_var.get()
                if 1 <= chunk_id <= len(chunks):
                    path = os.path.join(script_dir, f"chunk_{chunk_id}.txt")
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write(" ".join(chunks[chunk_id - 1]))
                    self.status_var.set(f"Chunk {chunk_id} exported.")
                else:
                    self.status_var.set("Invalid chunk ID.")
        except Exception as exc:
            self.status_var.set(f"Export error: {exc}")

    def open_output_folder(self):
        output_dir = self.output_dir_var.get().strip() or os.path.dirname(os.path.abspath(__file__))
        try:
            if sys.platform == "win32":
                os.startfile(output_dir)
            else:
                webbrowser.open(f"file://{output_dir}")
        except Exception as exc:
            self.status_var.set(f"Open folder error: {exc}")

    def start_generation(self):
        stop_event.clear()
        self._set_generate_enabled(False)
        threading.Thread(target=self._generate_speech, daemon=True).start()

    def stop_generation(self):
        stop_event.set()
        self.status_var.set("Stopping after current chunk...")

    def _generate_speech(self):
        temp_file = None
        try:
            output_directory = self.output_dir_var.get().strip() or os.path.dirname(os.path.abspath(__file__))
            self._ui(self.output_dir_var.set, output_directory)
            os.makedirs(output_directory, exist_ok=True)

            self._set_status("Loading model...")
            if not ensure_model_loaded():
                self._set_status("Failed to load PocketTTS model.")
                return

            ref_path = self.ref_audio_var.get().strip()
            voice_name = self.voice_var.get().strip()

            try:
                state, temp_file = prepare_voice_state(ref_path, voice_name)
            except Exception as exc:
                self._set_status(f"Voice load error: {exc}")
                return

            full_text = self._get_text().strip()
            if not full_text:
                self._set_status("No text found to synthesize.")
                return

            all_chunks = split_text_into_chunks(full_text.split(), self.chunk_size_var.get())
            start_chunk_idx = self.start_chunk_var.get() - 1
            if start_chunk_idx < 0 or start_chunk_idx >= len(all_chunks):
                self._set_status("Invalid start chunk.")
                return

            total_chunks = len(all_chunks[start_chunk_idx:])
            self._set_progress(0, len(all_chunks))
            temp_val = float(self.temp_var.get())
            speed_val = float(self.speed_var.get())
            times = []
            output_files = []

            for idx, chunk in enumerate(all_chunks[start_chunk_idx:], start=start_chunk_idx):
                if stop_event.is_set():
                    self._set_status(f"Stopped. Saved {len(output_files)} files so far.")
                    break

                started = time.time()
                chunk_text = " ".join(chunk)
                if times:
                    avg_time = (sum(times) / len(times)) / 60.0
                    remaining_chunks = total_chunks - (idx - start_chunk_idx + 1)
                    remaining_time = avg_time * remaining_chunks
                else:
                    avg_time = 0.0
                    remaining_time = 0.0

                info = f"Processing chunk {idx + 1}/{len(all_chunks)}"
                if avg_time > 0:
                    info += f" | Avg: {avg_time:.2f}m | Est. Remaining: {remaining_time:.2f}m"
                self._set_chunk_info(info)
                self._set_status(f"Generating chunk {idx + 1}...")

                out_path = os.path.join(output_directory, f"output_{idx + 1}.wav")
                success = False
                for attempt in range(1, 4):
                    try:
                        synthesize_chunk_to_file(state, chunk_text, out_path, temp_val, speed_val)
                        success = True
                        break
                    except Exception as chunk_error:
                        print(f"[Chunk {idx + 1}] Attempt {attempt} failed: {chunk_error}")
                        if attempt >= 3:
                            print(f"[Chunk {idx + 1}] Skipping.")
                            break
                        time.sleep(1)

                if not success:
                    continue

                output_files.append(out_path)
                self._set_progress(idx + 1, len(all_chunks))
                elapsed = time.time() - started
                times.append(elapsed)
                print(f"[Chunk {idx + 1}] Done in {elapsed:.2f}s")
                gc.collect()

            if not stop_event.is_set():
                self._set_status(f"Done. Saved {len(output_files)} files.")

            if self.combine_mp3_var.get() and output_files:
                self._set_status("Merging to MP3...")
                custom_name = self.mp3_name_var.get().strip() or "final_output"
                mp3_path = combine_output_to_mp3(output_files, output_directory, custom_name)
                if mp3_path:
                    self._set_status(f"Done. MP3 saved: {os.path.basename(mp3_path)}")
                else:
                    self._set_status("Done. Files saved, but MP3 merge failed.")
        except Exception as exc:
            print("\nUncaught error in generate_speech():")
            traceback.print_exc()
            self._set_status(f"An error occurred: {exc}")
        finally:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError:
                    pass
            self._set_generate_enabled(True)

    def generate_quick_sample(self):
        def task():
            temp_ref = None
            temp_out = os.path.abspath("quick_sample.wav")
            try:
                self._set_status("Generating quick sample...")
                if not ensure_model_loaded():
                    self._set_status("Failed to load PocketTTS model.")
                    return

                state, temp_ref = prepare_voice_state(self.ref_audio_var.get().strip(), self.voice_var.get().strip())
                synthesize_chunk_to_file(state, SAMPLE_TEXT, temp_out, float(self.temp_var.get()), float(self.speed_var.get()))

                if temp_ref and os.path.exists(temp_ref):
                    try:
                        os.remove(temp_ref)
                    except OSError:
                        pass
                    temp_ref = None

                self._set_status("Playing quick sample...")
                if sys.platform == "win32":
                    import winsound
                    winsound.PlaySound(temp_out, winsound.SND_FILENAME)
                else:
                    subprocess.run(["aplay", temp_out], capture_output=True)
                self._set_status("Quick sample done.")
            except Exception as exc:
                traceback.print_exc()
                self._set_status(f"Quick sample error: {exc}")
            finally:
                if temp_ref and os.path.exists(temp_ref):
                    try:
                        os.remove(temp_ref)
                    except OSError:
                        pass
                if os.path.exists(temp_out):
                    try:
                        os.remove(temp_out)
                    except OSError:
                        pass

        threading.Thread(target=task, daemon=True).start()


def main():
    app = PocketTTSWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
