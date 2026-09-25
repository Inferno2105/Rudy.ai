# Multilingual Meeting Assistant

A local, offline meeting assistant for **Hindi-English code-mixed (Hinglish)**
meetings. It transcribes speech, works out who spoke when, tags the language of
each segment, rewrites Devanagari into Roman-script Hinglish, then produces a
summary, action items and speaker statistics — all on one machine, with no audio
or transcript ever leaving it.

The project is positioned as an **integration and evaluation** contribution: it
composes pretrained models rather than training new ones, and its substance is
in the pipeline design and the measured evaluation of the result.

> **Status:** mid-rebuild. The pipeline is being restructured from exploratory
> scripts into the `backend/` package described below. See `docs/` for the
> architecture and `legacy/README.md` for what the earlier prototype produced
> and why its outputs are not usable as results.

## Stack

| Stage | Component |
|---|---|
| Speech recognition | `faster-whisper`, `large-v3`, int8 on CPU |
| Speaker diarization | `pyannote.audio` 4.x, `speaker-diarization-3.1` |
| Cross-chunk speaker identity | `pyannote/embedding` + cosine matching |
| Voice activity detection | `webrtcvad` (trained classifier, not an energy threshold) |
| Language / code-mix tagging | Unicode script heuristic |
| Hinglish normalization, summary, action items | Ollama, `qwen2.5:7b`, local |

## Layout

```
backend/     Python package (meeting_assistant) + tests
frontend/    React + Vite + TypeScript UI over the REST API
data/        audio, per-run artifacts, evaluation set, SQLite index
paper/       generated tables and figures — never hand-edited
docs/        architecture, artifact contract, evaluation methodology
legacy/      archived pre-rebuild scratch code (gitignored, reference only)
```

## Setup

Requires **Python 3.12** (not 3.13+ or 3.14 — several packages in the
torch/pyannote/webrtcvad stack have no prebuilt Windows wheels there), a running
[Ollama](https://ollama.com) server, and a **shared-build** FFmpeg on PATH.

```powershell
python -m venv venv312
.\venv312\Scripts\Activate.ps1
pip install -e ".\backend[eval,dev]"

Copy-Item .env.example .env     # then fill in HF_TOKEN
ollama pull qwen2.5:7b

meeting-assistant doctor        # verifies every prerequisite before you run anything
```

You also need to accept the terms for the gated pyannote model repositories on
Hugging Face; `doctor` will tell you which ones if access fails.

## Usage

```powershell
meeting-assistant batch .\data\audio\meeting.wav    # process a recording end to end
meeting-assistant live                              # record and process from the microphone
meeting-assistant runs --list                        # list previous runs
meeting-assistant eval --all                         # run the evaluation study
```

Each invocation writes an isolated, self-describing run directory under
`data/runs/<run_id>/` containing every intermediate artifact plus a manifest
recording the exact models, configuration and git commit that produced it.
Runs never overwrite each other.

## Troubleshooting

**`OSError: [WinError 126]` during diarization.** TorchCodec cannot find
FFmpeg's DLLs. A *static* `ffmpeg.exe` on PATH is not enough — the shared build
is required, because the DLLs are what get loaded. Run `meeting-assistant
doctor`, and if it cannot locate them, set `FFMPEG_BIN` in `.env` to the folder
containing `avcodec-*.dll`.

## License

MIT
