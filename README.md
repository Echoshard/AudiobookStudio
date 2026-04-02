# 📖 Audiobook Studio

Turn any text into a narrated audiobook — right from your desktop, no GPU required.

Load a PDF, EPUB, plain text file, or paste content directly. Pick a voice (or clone your own from a short audio clip), tweak the speed and tone, and generate a full MP3 audiobook. The app intelligently splits your text at sentence boundaries, generates each section, and merges everything into one file.

Powered by [PocketTTS](https://github.com/kyutai-labs/pocket-tts) by Kyutai — a lightweight text-to-speech model that runs entirely on CPU. This is the current choice as new open source models come out it will be updated.


## ✨ Features

- **Audiobook Generation** — Convert entire books and long documents into spoken audio
- **Voice Cloning** — Clone any voice from a short `.wav` or `.mp3` sample
- **8 Built-in Voices** — alba, marius, javert, jean, fantine, cosette, eponine, azelma
- **Import Anything** — PDFs, EPUBs, TXT files, or scrape text from any URL
- **Smart Chunking** — Splits at sentence boundaries for natural-sounding breaks
- **Tone & Speed Control** — Adjust expressiveness and playback speed
- **Auto MP3 Export** — Merges all chunks into a single MP3 file
- **Stop & Resume** — Pause generation and pick up from any chapter/chunk
- **No GPU Needed** — Runs entirely on CPU
- **One-Click Install** — No Python setup required

## 🚀 Quick Start

Double-click **`run_pocket_embedded.bat`** — it downloads everything automatically then `installTinkerEmbbeded.bat` then `run_pocket_embedded.bat` again.

## 🛠️ Manual Setup

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python PocketTTSUI.py
```

## 🖱️ Controls

| Button | What it does |
|---|---|
| **Browse** (Ref Audio) | Select an audio clip to clone that voice |
| **Browse** (Output Dir) | Choose where your audiobook is saved |
| **📄 Load PDF/Text/EPUB** | Import text from a document |
| **🌐 Scrape from URL** | Pull article or chapter text from a web page |
| **Export Chunk / Export All** | Save chunk text to `.txt` files for review |
| **📁 Open Folder** | Open the output directory |
| **▶ Generate Speech** | Start generating your audiobook |
| **⏹ Stop** | Cancel after the current chunk finishes |
| **🔊 Quick Sample** | Preview your voice + settings before committing |

| Setting | What it controls |
|---|---|
| **Voice Name** | Built-in voice (used when no audio clip is provided) |
| **Chunk Size** | Words per section — smaller = better quality |
| **Temperature** | Lower = consistent narration, Higher = expressive |
| **Speed** | 0.5x to 2.0x playback speed |
| **Start Chunk** | Resume from a specific section |
| **Combine into MP3** | Merge all sections into one audiobook file |

## 📖 Tips

- **Best chunk size**: 50–200 words for natural-sounding narration
- **Temperature**: 0.3–0.5 for audiobooks, 0.8+ for dramatic reads
- **Interrupted?** Set "Start Chunk" to resume where you left off
- Files save to the app's folder if no output directory is set

## 📄 License

Uses [PocketTTS](https://github.com/kyutai-labs/pocket-tts) by Kyutai Labs — see their repo for model licensing.

## ⚠️ Ethics & Responsibility

*Please use this tool responsibly.**

Voice cloning technology is powerful but carries ethical risks.
*   Do not clone voices without consent.
*   Do not generate content intended to deceive, defraud, or harass.
*   Always label AI-generated content appropriately.


