import os
import gc
import threading
import time
import random
import traceback
import re
import subprocess
import sys
import webbrowser

# Heavy imports are deferred so the GUI window appears instantly.
# These get populated by _ensure_libs_loaded() on first use.
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
DEFAULT_CHUNK_SIZE = 100  # Words per chunk — PocketTTS works best with smaller, sentence-aware chunks
SAMPLE_TEXT = "Greetings Human, I am here to tell you a cat fact. Did you know that cats sleep for 70% of their lives?"

def _ensure_libs_loaded():
    """Lazily import heavy libraries on first use."""
    global np, fitz, requests, BeautifulSoup, ebooklib, epub
    global sf, scipy_wav, torch, TTSModel, POCKET_AVAILABLE, _libs_loaded
    if _libs_loaded:
        return
    
    import numpy
    np = numpy
    
    import fitz as _fitz
    fitz = _fitz
    
    import requests as _req
    requests = _req
    
    from bs4 import BeautifulSoup as _bs
    BeautifulSoup = _bs
    
    import ebooklib as _ebl
    ebooklib = _ebl
    from ebooklib import epub as _epub
    epub = _epub
    
    import soundfile
    sf = soundfile
    
    import scipy.io.wavfile
    scipy_wav = scipy.io.wavfile
    
    try:
        from pocket_tts import TTSModel as _TTS
        import torch as _torch
        TTSModel = _TTS
        torch = _torch
        POCKET_AVAILABLE = True
    except ImportError:
        POCKET_AVAILABLE = False
        print("WARNING: PocketTTS or Torch not found. Install them first.")
    
    _libs_loaded = True

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QLabel, QLineEdit, QPushButton,
    QTextEdit, QComboBox, QSlider, QCheckBox, QFileDialog,
    QProgressBar, QInputDialog, QSpinBox, QDoubleSpinBox,
    QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QObject, QThread
from PySide6.QtGui import QFont, QColor, QPalette

# ─── Global State ──────────────────────────────────────────────────────────────

pocket_model = None
is_model_loading = False
stop_event = threading.Event()

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
    except Exception as e:
        print(f"[System] Failed to load model: {e}")
        pocket_model = None
    finally:
        is_model_loading = False
    
    return pocket_model is not None

# ─── Helper Functions ──────────────────────────────────────────────────────────

def split_text_into_chunks(words, original_chunk_size, wiggle_room=20):
    """Split words into chunks, preferring to break at sentence boundaries (. ! ?)."""
    def is_sentence_end(word):
        return word[-1] in '.!?' if word else False

    chunks = []
    current_chunk = []
    word_count = 0
    i = 0

    while i < len(words):
        current_chunk.append(words[i])
        word_count += 1
        i += 1

        if word_count >= original_chunk_size:
            if is_sentence_end(words[i-1]):
                chunks.append(current_chunk)
                current_chunk = []
                word_count = 0
            else:
                found = False
                for j in range(wiggle_room):
                    if i + j < len(words) and is_sentence_end(words[i + j]):
                        current_chunk.extend(words[i : i + j + 1])
                        i += (j + 1)
                        found = True
                        break

                if not found:
                    for k in range(len(current_chunk) - 1, 0, -1):
                        if is_sentence_end(current_chunk[k]):
                            leftover = current_chunk[k+1:]
                            chunks.append(current_chunk[:k+1])
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
            sf.write(temp_file, data, samplerate, subtype='PCM_16')
            final_prompt = temp_file
            print(f"[System] Using processed ref audio: {temp_file}")
            
        except Exception as e:
            print(f"[Warning] Failed to process ref audio: {e}. Falling back to name.")
            final_prompt = voice_name
            
    state = pocket_model.get_state_for_audio_prompt(final_prompt)
    return state, temp_file

def _generate_pocket_safe(state, text):
    global pocket_model
    chunk_size = 200

    raw_chunks = re.split(r'([.!?]+)', text)
    chunks = []
    current = ""
    for part in raw_chunks:
        if len(current) + len(part) < chunk_size:
            current += part
        else:
            if current: chunks.append(current)
            current = part
    if current: chunks.append(current)

    final_chunks = []
    for c in chunks:
        if not c.strip(): continue
        while len(c) > chunk_size:
            split = c[:chunk_size].rfind(" ")
            if split == -1: split = chunk_size
            final_chunks.append(c[:split])
            c = c[split:]
        final_chunks.append(c)

    full_audio = []
    for c in final_chunks:
        c = c.strip()
        if not c: continue
        tensor = pocket_model.generate_audio(state, c)
        if tensor is not None:
             full_audio.append(tensor.numpy())
    
    if not full_audio: return None
    return np.concatenate(full_audio)

def apply_speed_to_audio(file_path, speed):
    if speed == 1.0:
        return True
    
    temp_file = file_path + ".speed.wav"
    try:
        command = [
            'ffmpeg', '-y', '-i', file_path,
            '-filter:a', f'atempo={speed}',
            temp_file
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            os.replace(temp_file, file_path)
            return True
        else:
            print(f"[System] FFmpeg speed error: {result.stderr}")
            return False
    except Exception as e:
        print(f"[System] Failed to apply speed: {e}")
        return False
    finally:
        if os.path.exists(temp_file):
            try: os.remove(temp_file)
            except: pass

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
        with open(list_file, 'w', encoding='utf-8') as f:
            for file_path in output_files:
                abs_path = os.path.abspath(file_path).replace("'", "'\\''")
                f.write(f"file '{abs_path}'\n")
        
        print(f"[System] Merging {len(output_files)} files into {output_mp3}...")
        
        command = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', list_file, '-acodec', 'libmp3lame', '-q:a', '2',
            output_mp3
        ]
        
        result = subprocess.run(command, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("[System] MP3 merge successful. Cleaning up WAV files...")
            for f_path in output_files:
                if os.path.exists(f_path):
                    try: os.remove(f_path)
                    except: pass
            return output_mp3
        else:
            print(f"[System] FFmpeg error: {result.stderr}")
            return None
            
    except Exception as e:
        print(f"[System] Failed to merge MP3: {e}")
        return None
    finally:
        if os.path.exists(list_file):
            try: os.remove(list_file)
            except: pass


# ─── Worker Signals ────────────────────────────────────────────────────────────

class WorkerSignals(QObject):
    status = Signal(str)
    progress = Signal(int, int)  # value, maximum
    chunk_info = Signal(str)
    finished = Signal()


# ─── Dark Theme Stylesheet ────────────────────────────────────────────────────

DARK_STYLE = """
QMainWindow {
    background-color: #1e1e2e;
}
QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 10pt;
}
QGroupBox {
    border: 1px solid #45475a;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 18px;
    font-weight: bold;
    font-size: 11pt;
    color: #89b4fa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QLabel {
    color: #bac2de;
    font-size: 10pt;
}
QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 10px;
    color: #cdd6f4;
    selection-background-color: #89b4fa;
}
QLineEdit:focus, QTextEdit:focus {
    border: 1px solid #89b4fa;
}
QComboBox {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 10px;
    color: #cdd6f4;
    min-width: 100px;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #313244;
    border: 1px solid #45475a;
    color: #cdd6f4;
    selection-background-color: #89b4fa;
}
QPushButton {
    background-color: #45475a;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    color: #cdd6f4;
    font-weight: 600;
    font-size: 10pt;
}
QPushButton:hover {
    background-color: #585b70;
}
QPushButton:pressed {
    background-color: #6c7086;
}
QPushButton#generateBtn {
    background-color: #a6e3a1;
    color: #1e1e2e;
}
QPushButton#generateBtn:hover {
    background-color: #94e2d5;
}
QPushButton#stopBtn {
    background-color: #f38ba8;
    color: #1e1e2e;
}
QPushButton#stopBtn:hover {
    background-color: #eba0ac;
}
QPushButton#sampleBtn {
    background-color: #89b4fa;
    color: #1e1e2e;
}
QPushButton#sampleBtn:hover {
    background-color: #74c7ec;
}
QSlider::groove:horizontal {
    background: #45475a;
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #89b4fa;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}
QSlider::sub-page:horizontal {
    background: #89b4fa;
    border-radius: 3px;
}
QProgressBar {
    background-color: #313244;
    border: none;
    border-radius: 6px;
    height: 20px;
    text-align: center;
    color: #cdd6f4;
    font-weight: 600;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #89b4fa, stop:1 #a6e3a1);
    border-radius: 6px;
}
QCheckBox {
    spacing: 8px;
    color: #bac2de;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 2px solid #45475a;
    background-color: #313244;
}
QCheckBox::indicator:checked {
    background-color: #89b4fa;
    border-color: #89b4fa;
}
QScrollBar:vertical {
    background: #1e1e2e;
    width: 10px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #585b70;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
"""


# ─── Main Window ───────────────────────────────────────────────────────────────

class PocketTTSWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PocketTTS Generator")
        self.setMinimumSize(850, 900)
        self.resize(750, 900)
        
        self.signals = WorkerSignals()
        self.signals.status.connect(self._set_status)
        self.signals.progress.connect(self._set_progress)
        self.signals.chunk_info.connect(self._set_chunk_info)
        self.signals.finished.connect(self._on_finished)
        
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(16, 16, 16, 16)
        
        # Title
        title = QLabel("PocketTTS Generator")
        title.setStyleSheet("font-size: 17pt; font-weight: bold; color: #89b4fa; margin-bottom: 4px;")
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)
        
        subtitle = QLabel("CPU-Optimized Text-to-Speech")
        subtitle.setStyleSheet("font-size: 9pt; color: #6c7086; margin-bottom: 8px;")
        subtitle.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(subtitle)
        
        # ── Inputs Group ──
        inputs_group = QGroupBox("Inputs")
        inputs_layout = QGridLayout(inputs_group)
        inputs_layout.setSpacing(8)
        
        inputs_layout.addWidget(QLabel("Ref Audio (.wav/.mp3):"), 0, 0)
        self.ref_audio_edit = QLineEdit()
        self.ref_audio_edit.setPlaceholderText("Optional — leave blank to use voice name below")
        inputs_layout.addWidget(self.ref_audio_edit, 0, 1)
        ref_browse = QPushButton("Browse")
        ref_browse.clicked.connect(self.browse_ref_file)
        inputs_layout.addWidget(ref_browse, 0, 2)
        
        inputs_layout.addWidget(QLabel("Output Directory:"), 1, 0)
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("Default: script folder")
        inputs_layout.addWidget(self.output_dir_edit, 1, 1)
        out_browse = QPushButton("Browse")
        out_browse.clicked.connect(self.browse_output_dir)
        inputs_layout.addWidget(out_browse, 1, 2)
        
        inputs_layout.setColumnStretch(1, 1)
        main_layout.addWidget(inputs_group)
        
        # ── Text Input ──
        text_group = QGroupBox("Text to Speak")
        text_layout = QVBoxLayout(text_group)
        
        self.text_input = QTextEdit()
        self.text_input.setPlaceholderText("Paste or type your text here, or load from a file...")
        self.text_input.setMinimumHeight(150)
        text_layout.addWidget(self.text_input)
        
        load_row = QHBoxLayout()
        load_pdf_btn = QPushButton("📄 Load PDF/Text/EPUB")
        load_pdf_btn.clicked.connect(self.load_text)
        load_row.addWidget(load_pdf_btn)
        
        load_url_btn = QPushButton("🌐 Scrape from URL")
        load_url_btn.clicked.connect(self.load_url)
        load_row.addWidget(load_url_btn)
        load_row.addStretch()
        text_layout.addLayout(load_row)
        
        main_layout.addWidget(text_group)
        
        # ── Settings Group ──
        settings_group = QGroupBox("Settings")
        settings_layout = QGridLayout(settings_group)
        settings_layout.setSpacing(8)
        
        # Row 0: Voice & Chunk Size
        settings_layout.addWidget(QLabel("Voice Name:"), 0, 0)
        self.voice_combo = QComboBox()
        self.voice_combo.addItems(["alba", "marius", "javert", "jean", "fantine", "cosette", "eponine", "azelma"])
        settings_layout.addWidget(self.voice_combo, 0, 1)
        
        settings_layout.addWidget(QLabel("Chunk Size (words):"), 0, 2)
        self.chunk_size_spin = QSpinBox()
        self.chunk_size_spin.setRange(10, 5000)
        self.chunk_size_spin.setValue(DEFAULT_CHUNK_SIZE)
        settings_layout.addWidget(self.chunk_size_spin, 0, 3)
        
        # Row 1: Temp & Speed
        settings_layout.addWidget(QLabel("Temperature:"), 1, 0)
        temp_row = QHBoxLayout()
        self.temp_slider = QSlider(Qt.Horizontal)
        self.temp_slider.setRange(1, 20)  # 0.1 to 2.0
        self.temp_slider.setValue(7)      # 0.7
        self.temp_slider.setTickPosition(QSlider.TicksBelow)
        self.temp_label = QLabel("0.7")
        self.temp_label.setFixedWidth(30)
        self.temp_slider.valueChanged.connect(lambda v: self.temp_label.setText(f"{v/10:.1f}"))
        temp_row.addWidget(self.temp_slider)
        temp_row.addWidget(self.temp_label)
        settings_layout.addLayout(temp_row, 1, 1)
        
        settings_layout.addWidget(QLabel("Speed:"), 1, 2)
        speed_row = QHBoxLayout()
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(10, 40)  # 0.50 to 2.00
        self.speed_slider.setValue(20)       # 1.0
        self.speed_slider.setTickPosition(QSlider.TicksBelow)
        self.speed_label = QLabel("1.00")
        self.speed_label.setFixedWidth(35)
        self.speed_slider.valueChanged.connect(lambda v: self.speed_label.setText(f"{v/20:.2f}"))
        speed_row.addWidget(self.speed_slider)
        speed_row.addWidget(self.speed_label)
        settings_layout.addLayout(speed_row, 1, 3)
        
        # Row 2: Start Chunk & MP3
        settings_layout.addWidget(QLabel("Start Chunk:"), 2, 0)
        self.start_chunk_spin = QSpinBox()
        self.start_chunk_spin.setRange(1, 9999)
        self.start_chunk_spin.setValue(1)
        settings_layout.addWidget(self.start_chunk_spin, 2, 1)
        
        mp3_row = QHBoxLayout()
        self.combine_mp3_check = QCheckBox("Combine into MP3:")
        self.combine_mp3_check.setChecked(True)
        mp3_row.addWidget(self.combine_mp3_check)
        self.mp3_name_edit = QLineEdit("final_output")
        self.mp3_name_edit.setFixedWidth(150)
        mp3_row.addWidget(self.mp3_name_edit)
        settings_layout.addLayout(mp3_row, 2, 2, 1, 2)
        
        main_layout.addWidget(settings_group)
        
        # ── Actions ──
        actions_group = QGroupBox("Actions")
        actions_layout = QHBoxLayout(actions_group)
        actions_layout.setSpacing(8)
        
        export_btn = QPushButton("Export Chunk")
        export_btn.clicked.connect(lambda: self.export_chunk(False))
        actions_layout.addWidget(export_btn)
        
        export_all_btn = QPushButton("Export All")
        export_all_btn.clicked.connect(lambda: self.export_chunk(True))
        actions_layout.addWidget(export_all_btn)
        
        open_btn = QPushButton("📁 Open Folder")
        open_btn.clicked.connect(self.open_output_folder)
        actions_layout.addWidget(open_btn)
        
        self.generate_btn = QPushButton("▶  Generate Speech")
        self.generate_btn.setObjectName("generateBtn")
        self.generate_btn.clicked.connect(self.start_generation)
        actions_layout.addWidget(self.generate_btn)
        
        self.stop_btn = QPushButton("⏹  Stop")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.clicked.connect(self.stop_generation)
        actions_layout.addWidget(self.stop_btn)
        
        self.sample_btn = QPushButton("🔊 Quick Sample")
        self.sample_btn.setObjectName("sampleBtn")
        self.sample_btn.clicked.connect(self.generate_quick_sample)
        actions_layout.addWidget(self.sample_btn)
        
        main_layout.addWidget(actions_group)
        
        # ── Progress ──
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)
        
        self.chunk_info_label = QLabel("")
        self.chunk_info_label.setStyleSheet("color: #a6adc8; font-size: 9pt;")
        progress_layout.addWidget(self.chunk_info_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #a6e3a1; font-weight: 600; font-size: 11pt;")
        self.status_label.setAlignment(Qt.AlignCenter)
        progress_layout.addWidget(self.status_label)
        
        main_layout.addWidget(progress_group)
        main_layout.addStretch()

    # ── Thread-safe UI updates ──
    def _set_status(self, text):
        self.status_label.setText(text)
    
    def _set_progress(self, value, maximum):
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(value)
    
    def _set_chunk_info(self, text):
        self.chunk_info_label.setText(text)
    
    def _on_finished(self):
        self.generate_btn.setEnabled(True)

    # ── File Browsing ──
    def browse_ref_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select Reference Audio",
            "", "Audio Files (*.wav *.mp3);;All Files (*.*)"
        )
        if filename:
            self.ref_audio_edit.setText(filename)
    
    def browse_output_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if directory:
            self.output_dir_edit.setText(directory)

    # ── Text Loading ──
    def load_text(self):
        file, _ = QFileDialog.getOpenFileName(
            self, "Select Document",
            "", "Documents (*.pdf *.txt *.epub);;All Files (*.*)"
        )
        if not file:
            return

        loaded_text = ""
        if file.endswith('.pdf'):
            doc = fitz.open(file)
            for page in doc:
                loaded_text += page.get_text()
        elif file.endswith('.txt'):
            with open(file, 'r', encoding='utf-8') as f:
                loaded_text = f.read()
        elif file.endswith('.epub'):
            book = epub.read_epub(file)
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    soup = BeautifulSoup(item.get_body_content(), 'html.parser')
                    loaded_text += soup.get_text()

        self.text_input.setPlainText(loaded_text)

    def load_url(self):
        url, ok = QInputDialog.getText(self, "Scrape URL", "Enter URL:")
        if not ok or not url:
            return
        try:
            response = requests.get(url)
            soup = BeautifulSoup(response.content, 'html.parser')
            scraped = '\n'.join(p.get_text() for p in soup.find_all('p'))
            self.text_input.setPlainText(scraped)
            self.signals.status.emit("Text loaded from URL.")
        except Exception as e:
            self.signals.status.emit(f"Error loading URL: {e}")

    # ── Export ──
    def export_chunk(self, all_chunks=False):
        try:
            full_text = self.text_input.toPlainText().strip()
            words = full_text.split()
            chunk_size = self.chunk_size_spin.value()
            chunks = split_text_into_chunks(words, chunk_size)

            script_dir = os.path.dirname(os.path.abspath(__file__))
            if all_chunks:
                for i, ch in enumerate(chunks, start=1):
                    path = os.path.join(script_dir, f"chunk_{i}.txt")
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(' '.join(ch))
                self.signals.status.emit(f"All {len(chunks)} chunks exported.")
            else:
                chunk_id = self.start_chunk_spin.value()
                if 1 <= chunk_id <= len(chunks):
                    path = os.path.join(script_dir, f"chunk_{chunk_id}.txt")
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(' '.join(chunks[chunk_id - 1]))
                    self.signals.status.emit(f"Chunk {chunk_id} exported.")
                else:
                    self.signals.status.emit("Invalid chunk ID.")
        except Exception as e:
            self.signals.status.emit(f"Export error: {e}")

    def open_output_folder(self):
        output_dir = self.output_dir_edit.text()
        if not output_dir:
            output_dir = os.path.dirname(os.path.abspath(__file__))
        webbrowser.open(f"file://{output_dir}")

    # ── Generation ──
    def start_generation(self):
        stop_event.clear()
        self.generate_btn.setEnabled(False)
        thread = threading.Thread(target=self._generate_speech, daemon=True)
        thread.start()

    def stop_generation(self):
        stop_event.set()
        self.signals.status.emit("Stopping after current chunk...")

    def _generate_speech(self):
        try:
            output_directory = self.output_dir_edit.text()
            if not output_directory:
                output_directory = os.path.dirname(os.path.abspath(__file__))
                self.output_dir_edit.setText(output_directory)
            os.makedirs(output_directory, exist_ok=True)

            self.signals.status.emit("Loading Model...")
            if not ensure_model_loaded():
                self.signals.status.emit("Failed to load PocketTTS Model.")
                self.signals.finished.emit()
                return

            ref_path = self.ref_audio_edit.text()
            voice_name = self.voice_combo.currentText()
            
            state = None
            temp_file = None
            try:
                state, temp_file = prepare_voice_state(ref_path, voice_name)
            except Exception as e:
                self.signals.status.emit(f"Voice Load Error: {e}")
                self.signals.finished.emit()
                return

            chunk_size = self.chunk_size_spin.value()
            full_text = self.text_input.toPlainText().strip()
            if not full_text:
                self.signals.status.emit("No text found to synthesize.")
                self.signals.finished.emit()
                return

            words = full_text.split()
            all_chunks = split_text_into_chunks(words, chunk_size)

            start_chunk_idx = self.start_chunk_spin.value() - 1
            if start_chunk_idx < 0 or start_chunk_idx >= len(all_chunks):
                self.signals.status.emit("Invalid start chunk.")
                self.signals.finished.emit()
                return

            total_chunks = len(all_chunks[start_chunk_idx:])
            self.signals.progress.emit(0, len(all_chunks))

            temp_val = self.temp_slider.value() / 10.0
            speed_val = self.speed_slider.value() / 20.0

            times = []
            output_files = []

            for idx, chunk in enumerate(all_chunks[start_chunk_idx:], start=start_chunk_idx):
                if stop_event.is_set():
                    self.signals.status.emit(f"Stopped. Saved {len(output_files)} files so far.")
                    break

                start_time = time.time()
                chunk_text = ' '.join(chunk)

                if times:
                    avg_time = (sum(times) / len(times)) / 60
                    remaining_chunks = total_chunks - (idx - start_chunk_idx + 1)
                    remaining_time = avg_time * remaining_chunks
                else:
                    avg_time = 0.0
                    remaining_time = 0.0

                info = f"Processing chunk {idx+1}/{len(all_chunks)}"
                if avg_time > 0:
                    info += f"  |  Avg: {avg_time:.2f}m  |  Est. Remaining: {remaining_time:.2f}m"
                self.signals.chunk_info.emit(info)
                self.signals.status.emit(f"Generating chunk {idx+1}...")

                out_path = os.path.join(output_directory, f"output_{idx+1}.wav")
                max_retries = 3
                attempt = 0
                success = False

                while attempt < max_retries and not success:
                    attempt += 1
                    try:
                        synthesize_chunk_to_file(state, chunk_text, out_path, temp_val, speed_val)
                        success = True
                    except Exception as chunk_error:
                        print(f"[Chunk {idx+1}] Attempt {attempt} failed: {chunk_error}")
                        if attempt >= max_retries:
                            print(f"[Chunk {idx+1}] Skipping.")
                            break
                        time.sleep(1)

                if not success:
                    continue

                output_files.append(out_path)
                self.signals.progress.emit(idx + 1, len(all_chunks))

                end_time = time.time()
                times.append(end_time - start_time)
                print(f"[Chunk {idx+1}] Done in {end_time - start_time:.2f}s")

                gc.collect()

            # Cleanup
            if temp_file and os.path.exists(temp_file):
                try: os.remove(temp_file)
                except: pass

            if not stop_event.is_set():
                self.signals.status.emit(f"Done. Saved {len(output_files)} files.")

            # Merge to MP3
            if self.combine_mp3_check.isChecked() and output_files:
                self.signals.status.emit("Merging to MP3...")
                custom_name = self.mp3_name_edit.text().strip() or "final_output"
                mp3_path = combine_output_to_mp3(output_files, output_directory, custom_name)
                if mp3_path:
                    self.signals.status.emit(f"Done. MP3 saved: {os.path.basename(mp3_path)}")
                else:
                    self.signals.status.emit("Done. Files saved, but MP3 merge failed.")

            print("\n--- All Tasks Complete ---")

        except Exception as e:
            print("\nUncaught error in generate_speech():")
            traceback.print_exc()
            self.signals.status.emit(f"An error occurred: {e}")
        finally:
            self.signals.finished.emit()

    # ── Quick Sample ──
    def generate_quick_sample(self):
        def task():
            try:
                self.signals.status.emit("Generating Quick Sample...")
                if not ensure_model_loaded():
                    self.signals.status.emit("Failed to load PocketTTS Model.")
                    return

                ref_path = self.ref_audio_edit.text()
                voice_name = self.voice_combo.currentText()
                state, temp_ref = prepare_voice_state(ref_path, voice_name)

                sample_text = SAMPLE_TEXT
                temp_out = os.path.abspath("quick_sample.wav")

                temp_val = self.temp_slider.value() / 10.0
                speed_val = self.speed_slider.value() / 20.0

                synthesize_chunk_to_file(state, sample_text, temp_out, temp_val, speed_val)

                if temp_ref and os.path.exists(temp_ref):
                    try: os.remove(temp_ref)
                    except: pass

                self.signals.status.emit("Playing Quick Sample...")
                
                # Use platform-appropriate playback
                if sys.platform == 'win32':
                    import winsound
                    winsound.PlaySound(temp_out, winsound.SND_FILENAME)
                else:
                    subprocess.run(['aplay', temp_out], capture_output=True)

                if os.path.exists(temp_out):
                    try: os.remove(temp_out)
                    except: pass

                self.signals.status.emit("Quick Sample Done.")

            except Exception as e:
                print(f"[Quick Sample] Error: {e}")
                traceback.print_exc()
                self.signals.status.emit(f"Quick Sample Error: {e}")

        threading.Thread(target=task, daemon=True).start()


# ─── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)
    
    window = PocketTTSWindow()
    window.show()
    
    sys.exit(app.exec())
