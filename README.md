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
pip install -e ".\backend[eval,api,dev]"

Copy-Item .env.example .env     # then fill in HF_TOKEN
ollama pull qwen2.5:7b

meeting-assistant doctor        # verifies every prerequisite before you run anything

cd frontend; npm install; npm run build; cd ..   # the web UI (Node 22+)
```

You also need to accept the terms for the gated pyannote model repositories on
Hugging Face; `doctor` will tell you which ones if access fails.

## Run with Docker

Everything (UI, API, speech models on the GPU, and Ollama) in containers:

```powershell
powershell -File docker/up.ps1     # then open http://127.0.0.1:8000/
```

See [docs/docker.md](docs/docker.md) for requirements, GPU memory, data
volumes and limitations (no live microphone inside Docker on Windows).

## Usage

### Web UI

```powershell
meeting-assistant serve                   # UI at http://127.0.0.1:8000/ (this machine only)
meeting-assistant serve --host 0.0.0.0    # also reachable from other devices on the network
```

The UI lists every meeting, processes uploaded recordings with live stage
progress, records live sessions from the server's microphone, and shows each
run's transcript (Romanized or original script, with click-to-seek audio),
summary, action items, speaker statistics and full provenance, plus the
evaluation report. See `frontend/README.md` for development.

**Accounts.** Open `http://127.0.0.1:8000/` for the landing page, then sign in.
On the very first visit the sign-in page asks you to create the first account.
After that, anyone who can reach the server can make their own account with
**Create an account** on the sign-in page (turn this off with
`ALLOW_SIGNUP=false`), or you can add accounts from the terminal:

```powershell
meeting-assistant users add <name>              # prompts for a password
meeting-assistant users list
meeting-assistant users reset-password <name>
meeting-assistant users remove <name>
meeting-assistant users claim-runs <name>       # give runs with no owner to <name>
```

**Each account sees only its own data.** Every run records the account that
created it, and uploads go to that account's own folder
(`data/audio/users/<id>/`). Meetings, transcripts, recordings, jobs and live
sessions of other accounts are invisible: the API answers exactly as if they
did not exist. Ownership uses a random id per account, not the username, so a
deleted account re-created under the same name starts empty. The evaluation
report is about the system, not anyone's meetings, so every account sees it.

Runs made from the command line belong to `--user <name>`, or to the only
account when there is just one. Meetings from before accounts existed went to
the first account. With several accounts, a run with no owner is hidden from
all of them until `users claim-runs`. One browser is signed in as one account
at a time (the session is a cookie); use another browser or a private window
for a second account.

Passwords are stored hashed (scrypt) in `data/users.sqlite`; sessions are an
HttpOnly cookie that lasts 14 days (`SESSION_TTL_DAYS`). Every page and API
route except the landing page, sign-in, sign-up and `/api/health` requires an
account.

### Command line

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
