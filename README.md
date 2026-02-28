# 🎙️ PocketTTS-Studio

A desktop GUI for [PocketTTS](https://github.com/kyutai-labs/pocket-tts) — CPU-optimized text-to-speech with voice cloning.

## 🚀 Quick Start

Double-click **`run_pocket_embedded.bat`** — it downloads Python, FFmpeg, and all dependencies automatically.

> First run takes a few minutes. Subsequent launches are instant.

## 🛠️ Manual Setup

```bash
python -m venv venv
venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python PocketTTSUI.py
```

## 📖 Tips

- **Chunk Size**: ~100 words gives best quality
- **Temperature**: Lower = consistent, Higher = expressive
- **Speed**: 0.5x–2.0x (via FFmpeg)

## 📄 License

Uses [PocketTTS](https://github.com/kyutai-labs/pocket-tts) by Kyutai Labs — see their repo for model licensing.

