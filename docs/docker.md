# Running in Docker

The whole system (web UI, API, speech models and the Ollama language model)
runs in two containers on this laptop's GPU.

## What you need

- **Docker Desktop** with the WSL 2 backend (installed).
- An **NVIDIA GPU** with a current Windows driver; Docker Desktop passes it
  through to the containers. Tested on an RTX 4060 Laptop GPU (8 GB).
- A `.env` file at the repository root with your Hugging Face token:
  `HF_TOKEN=hf_...` (copy `.env.example`). It is read at start-up and never
  copied into an image.

Recommended: give Docker more memory. By default WSL 2 gets half of the RAM
(about 7.4 GB here). With 16 GB in the laptop, create
`C:\Users\<you>\.wslconfig` containing:

```ini
[wsl2]
memory=12GB
```

then run `wsl --shutdown` and restart Docker Desktop.

## Start, stop, update

```powershell
powershell -File docker/up.ps1        # build if needed, then start in the background
docker compose logs -f app            # follow the app's log
docker compose down                   # stop (recordings, runs, accounts and models are kept)
powershell -File docker/up.ps1 -Rebuild   # after pulling new code
```

Then open **http://127.0.0.1:8000/**. The first visit to the sign-in page
creates the first account; after that, **Create an account** on the sign-in
page adds more, and each account sees only its own meetings and recordings.
Accounts can also be managed inside the container:

```powershell
docker compose exec app meeting-assistant users add <name>
docker compose exec app meeting-assistant doctor
```

**First start takes a while.** The `ollama-model` service downloads
`qwen2.5:7b` (about 4.7 GB) before the app starts, and the first meeting you
process downloads Whisper large-v3 and the pyannote models (about 3 GB). Both
are kept in Docker volumes, so later starts take seconds.

## How it is put together

| Container | Image | Role |
|---|---|---|
| `app` | built from `Dockerfile` | UI + API (`meeting-assistant serve`), Whisper and pyannote on the GPU |
| `ollama` | `ollama/ollama` | the language model, on the GPU |
| `ollama-model` | `ollama/ollama` | one-shot: pulls the model, then exits |

| Storage | Where | Contents |
|---|---|---|
| `./data` (bind mount) | your repository's `data/` | recordings, run directories, index, accounts: the **same** data the native app uses |
| `model-cache` volume | `/cache` | Hugging Face downloads (Whisper, pyannote) |
| `ollama` volume | `/root/.ollama` | the Ollama model |

The port is published on `127.0.0.1` only, so the app is reachable from this
computer and not from the network. To expose it on the LAN, change
`"127.0.0.1:8000:8000"` to `"8000:8000"` in `compose.yaml`; every page except
the landing and sign-in pages still requires an account.

## GPU memory on an 8 GB card

Whisper runs as `int8_float16` (about 1.5 GB) and pyannote on CUDA (under
1 GB). Ollama unloads the language model two minutes after its last use
(`OLLAMA_KEEP_ALIVE`) and keeps at most one model loaded. In a batch run the
stages take turns (speech models first, the language model last), so they fit
on the card together. If memory is short, Ollama places part of the model on
the CPU automatically; it gets slower, but it does not fail.

Translating a transcript into Hindi uses a second model, `aya-expanse:8b`
(about 5 GB, downloaded on first start with the other one). Only one model is
loaded at a time, so switching between the pipeline's model and the
translation model costs a few seconds of loading, not extra memory.

## Results and the paper

The Docker configuration is recorded like any other: `whisper_device=cuda`,
`whisper_compute_type=int8_float16` and `diarization_device=cuda` give it a
**different config hash** from the native CPU (int8) configuration. The
evaluation therefore never mixes GPU and CPU runs, and the GPU-vs-CPU
comparison is itself a reportable result.

There is no `.git` inside the image, so `docker/up.ps1` records the commit
(and whether the working tree had uncommitted changes) at build time. Every
run's manifest names that commit, with `"source": "build"`. Build from a clean,
committed tree for runs you intend to report.

## Limitations

- **No live recording in Docker on Windows.** Docker Desktop cannot pass the
  laptop's microphone into a Linux container, so the Live page reports that
  the server has no input device. Uploading and processing recordings works
  fully. For live sessions, run the app natively (`meeting-assistant serve`).
- The image is large (about 13 GB), mostly the CUDA and cuDNN libraries that
  come with PyTorch.

## Package versions

The image installs every Python package at the exact version listed in
`backend/constraints.txt`: the versions the test suite and the native runs
used. Without it, `pip` would take the newest releases on the day of the build,
and the container could run different code from what was tested (this happened
once: PyAV 19 removed an argument faster-whisper still passes). torch,
torchaudio and torchcodec are the exception: they come from PyTorch's CUDA 12.6
package index at the same versions (set in the `Dockerfile`), because their
PyPI builds target CUDA 13 and do not load together with CUDA 12. After upgrading
packages natively and re-running the tests, regenerate the file as its header
describes, then rebuild with `docker/up.ps1 -Rebuild`.
