# Multilingual Meeting Assistant — Chat Context & Change Log

This document is a complete, detailed record of everything discussed and built
in this chat. Intended for picking the project back up in a new session with
zero context loss.

---

## Project overview

Final-year/capstone project: a real-time multilingual meeting assistant that
performs speech transcription, speaker diarization, speaker-attributed
transcript generation, language/code-mix detection, Hinglish normalization,
meeting summarization, action-item extraction, speaker statistics, and
meeting metadata generation.

- Two-person team:
  - **Person 1 (the user, Rushikesh Giri)** owns ASR, audio capture/chunking,
    diarization, speaker segmentation, temporal alignment, and the core
    transcript data structure.
  - **Person 2 (teammate)** owns language/code-mix detection and meeting
    intelligence (summarization, action items, stats).
- Positioned as an **integration + evaluation** project — using pretrained
  models (Whisper, pyannote, an LLM via Ollama) rather than training new
  models from scratch.
- Working directory: `C:\Users\rushi\whisper-project` (flat layout, all
  scripts directly in the project root, not nested under `backend/`).
- Windows machine, PowerShell, using a Python virtual environment.

### Original 8-phase plan
1. Phase 1 — Speech (Whisper/ASR)
2. Phase 2 — Speaker (pyannote diarization)
3. Phase 3 — Integration/alignment
4. Phase 4 — Language/code-mix detection + Hinglish normalization
5. Phase 5 — Meeting intelligence (summarization, action items)
6. Phase 6 — Meeting stats/metadata
7. Phase 7 — Real-time (live capture)
8. Phase 8 — UI/export (explicitly deferred — not started, not a current
   priority)

---

## Full module inventory (all code-verified from actual pasted/uploaded files)

### `transcribe.py` — Phase 1: ASR
- Uses `faster_whisper.WhisperModel`.
- `load_model(model_size="large-v3", device="cpu", compute_type="int8")`.
- `transcribe_audio(model, audio_path, language=None)` — auto language
  detection left on (`language=None`) deliberately, since forcing a single
  language hurts accuracy on Hindi-English code-mixed audio.
- `beam_size=5`, `vad_filter=True` (Whisper's built-in VAD to avoid
  hallucinated text over silence).
- Ignores empty segments; rounds timestamps to 2 decimals.
- Originally used `model_size="medium"`; **switched to `large-v3`** after
  `medium` produced real transcription errors (mis-heard words like "kyun"
  instead of "kaun", garbled phrases) on Hindi/code-mixed test audio.
  Switching fixed the accuracy problem — confirmed by the user.
- Standalone `__main__` block: hardcoded `audio_file = "test.wav"`, prints
  transcript, saves to `transcript.json` (note: saves to project root, not
  `data/outputs/`, in the user's actual script — a minor inconsistency vs.
  the originally suggested structure).
- User's actual local filename for this script is **`transcribe.py`**, NOT
  `asr.py` as originally suggested — corrected early in the chat.

### `diarization.py` — Phase 2: Speaker diarization
- Uses `pyannote.audio.Pipeline`, model
  `"pyannote/speaker-diarization-3.1"`.
- `load_pipeline(hf_token)` calls `Pipeline.from_pretrained(..., token=hf_token)`.
- `diarize_audio(pipeline, audio_path, num_speakers=None)` returns
  `[{"start", "end", "speaker"}, ...]`.
- **Windows-specific fix baked into the file**: at the very top, before
  importing `pyannote.audio`, the code does:
  ```python
  FFMPEG_BIN = r"C:\Users\rushi\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg.Shared_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build-shared\bin"
  if os.path.exists(FFMPEG_BIN):
      os.add_dll_directory(FFMPEG_BIN)
  from pyannote.audio import Pipeline
  ```
  This was necessary because TorchCodec (used internally by pyannote to
  decode audio) could not find FFmpeg's DLLs on Windows even though
  `ffmpeg -version` worked fine in a terminal. The fix was later centralized
  into `config.py`'s `resolve_ffmpeg_bin_dir()` (auto-detect via
  `shutil.which("ffmpeg")` first, falling back to an env var
  `FFMPEG_BIN`), removing the hardcoded path from live_capture-related code,
  though `diarization.py` itself still has the hardcoded version as
  originally written by the user.
- `annotation = diarization.speaker_diarization` must be accessed before
  calling `.itertracks(yield_label=True)` — the installed pyannote version
  (4.x) returns a `DiarizeOutput` wrapper, not a raw `Annotation` object
  directly.
- **Known cosmetic issue, not yet cleaned up**: "Diarizing {audio_path} ..."
  is printed twice — once inside `diarize_audio()` and once in the
  `__main__` block.
- A `UserWarning: std(): degrees of freedom is <= 0` appears during
  diarization on short clips — harmless, comes from pyannote's internal
  embedding clustering step on very short audio, does not affect
  correctness.

### `alignment.py` — Phase 3: Integration
- Pure timestamp-overlap alignment. No text/content analysis — deliberately
  content-agnostic so it stays robust regardless of language.
- `compute_overlap(w_start, w_end, s_start, s_end)` — standard interval
  overlap: `max(0, min(w_end, s_end) - max(w_start, s_start))`.
- `find_best_speaker(whisper_seg, speaker_segments)` — for each Whisper
  segment, finds the speaker segment with maximum overlap. Falls back to
  `"UNKNOWN"` if no overlap at all — a deliberate design choice: an honest
  gap is better than a confident wrong guess.
- `align_transcript(whisper_segments, speaker_segments)` — builds the
  merged `{"start", "end", "speaker", "text"}` list.
- `merge_consecutive_same_speaker(aligned)` — cosmetic pass that merges
  consecutive segments from the same speaker into one turn (Whisper often
  splits one sentence into multiple segments).
- Output saved to `data/outputs/final_transcript.json`.

### `language_detection.py` — Member 2's Task 1 (built by the user to
help/hand off to teammate)
- Task spec (from an uploaded slide image, "MEMBER 2 — TASK 1: LANGUAGE
  DETECTION"): input = text, output = one of `English` / `Hindi` /
  `Code-Mixed`. Spec's own examples were written in **Roman/Hinglish
  script** (e.g. `"Aaj hum meeting start karte hain." → Hindi`).
- **Actual implementation is a rule-based heuristic**, NOT a trained
  classifier (explicitly documented in the file's own docstring as "a
  heuristic, not a trained classifier"), and specifically NOT XLM-RoBERTa
  (an earlier assumption from before code was pasted/verified — corrected
  once the real code was seen).
- Method: word-level script classification using Unicode ranges —
  `DEVANAGARI_RE = re.compile(r'[\u0900-\u097F]+')` vs
  `LATIN_WORD_RE = re.compile(r'[A-Za-z]+')`.
- `classify_word(word)` → `"devanagari"` / `"latin"` / `"other"`.
- `detect_language(text)`:
  - Strips punctuation, splits into words.
  - Empty/no-scripted-words → defaults to `"English"` (arbitrary edge case
    default).
  - `MIN_WORDS_FOR_MIX_CHECK = 2` — segments shorter than this skip the
    ratio logic and just go with whichever script appeared.
  - `CODE_MIX_THRESHOLD = 0.15` — if the minority script is ≥15% of words,
    classify as `"Code-Mixed"`; otherwise round to the majority
    (`"Hindi"` or `"English"`).
- **Important documented caveat/limitation**: pure script detection CANNOT
  correctly classify already-Romanized Hindi (Hinglish) as `"Hindi"`,
  because Hinglish and English both use Latin script with no distinguishing
  signal for this method. This directly means the task spec's own second
  example (`"Aaj hum meeting start karte hain." → Hindi`) would NOT be
  correctly classified by this implementation if run on already-Romanized
  text. This is why pipeline **ordering** matters (see below).
- **Deliberate pipeline positioning decision**: `language_detection.py`
  must run BEFORE `normalize.py` (Hinglish conversion), while the script
  signal (Devanagari vs Latin) is still intact in the raw Whisper output.
  This was an explicit user decision ("i am thinking to run this before
  the normalise.py so that it is easy for it to tag and once the transcript
  is tagged i can normalize it") — confirmed as the right call.
- `detect_language_for_segments(segments)` — applies `detect_language` to
  each segment's `"text"`, adds a `"language"` key, returns the updated
  list.
- `__main__` block has two modes:
  - No args → runs a few hardcoded example sentences through
    `detect_language()` for a quick sanity check.
  - `--pipeline` flag → reads `data/outputs/final_transcript.json`, tags
    every segment, prints readable output, saves to
    `data/outputs/final_transcript_tagged.json`.

### `normalize.py` — Phase 4: Hinglish normalization
- Problem it solves: Whisper's Hindi mode outputs pure Devanagari script,
  and even mis-transcribes spoken English words into Devanagari phonetics
  (e.g. "test" → "टेष्ट"). The project needs Hinglish/Roman script output
  instead — Hindi spelled phonetically in Roman letters, English left as
  English, meaning unchanged, no translation.
- Uses **Ollama** (local LLM, chosen explicitly over a paid API like
  Anthropic's for cost/privacy/offline reasons) with model
  **`qwen2.5:7b`** (switched from an initial `llama3.1:8b` default after
  testing — Qwen models are noticeably better at Hindi/Devanagari).
  `llama3.1:8b` is still mentioned in a code comment as a fallback option.
- `SYSTEM_PROMPT` is a strict script-conversion prompt with 5 non-negotiable
  rules: (1) Devanagari→Roman Hinglish spelling, (2) fix
  Devanagari-mis-transcribed English back to correct English spelling, (3)
  leave genuine English alone, (4) preserve meaning/word order exactly —
  this is NOT translation, (5) output only the converted sentence, no
  commentary. Includes 2 few-shot examples built directly from the user's
  own real test.wav transcription output.
- `normalize_text(text, model)` — one Ollama chat call per segment,
  `temperature=0.1` (low, for faithful conversion not creativity). Falls
  back to the original text on any exception, so one bad segment never
  kills the whole run.
- `normalize_transcript(segments, model)` — loops over all segments, only
  changes `"text"`, passes through `start`/`end`/`speaker`/`language`
  untouched.
- `__main__` block: prefers reading
  `data/outputs/final_transcript_tagged.json` (the language-detection
  output) if it exists, falls back to untagged
  `data/outputs/final_transcript.json` otherwise. Saves to
  `data/outputs/final_transcript_hinglish.json`.
- **Known, deliberately out-of-scope limitation**: normalization cannot
  and should not try to fix genuine ASR transcription errors (e.g.
  Whisper mishearing "kaun" as "kyun") — that's a source-accuracy problem,
  not a script-conversion problem, and was explicitly diagnosed as two
  separate issues during testing (see Timeline below).
- Performance note (flagged but not yet acted on): running Ollama
  segment-by-segment on CPU with a 7-8B model is slow; batching multiple
  segments into fewer LLM calls was suggested as a future optimization,
  not yet implemented.

### `summarization.py` — Phase 5: LLM-based meeting summarization
- Also uses Ollama + `qwen2.5:7b` (same pattern as `normalize.py`).
- `build_transcript_text(segments)` — flattens segments into
  `[MM:SS] SPEAKER: text` lines for the LLM prompt.
- `chunk_segments(...)` / `summarize_long_transcript(...)` — chunking logic
  for transcripts too long for one LLM call, wired in but **off by
  default** (`CHUNK_IF_TOO_LONG = False`), since capstone-scale test
  meetings are short enough not to need it yet.
- `_extract_json(raw)` — strips markdown code fences and extracts the
  first `{...}` block, since LLMs sometimes wrap JSON output despite
  instructions not to.
- `SYSTEM_PROMPT` rules: summarize only from what's explicitly said (no
  invented facts), don't translate, 3-6 sentence summary, `highlights` =
  discussion points, `key_decisions` = only explicit agreements (empty
  list if none — never force a decision that wasn't stated).
- Output: `{"summary": ..., "highlights": [...], "key_decisions": [...]}`,
  saved to `data/outputs/meeting_summary.json`.
- Reads from `final_transcript_hinglish.json`, falls back to
  `final_transcript_tagged.json`.

### `action_items.py` — Phase 5b: Action item extraction
- Reuses `summarization.py`'s `build_transcript_text`, `_extract_json`, and
  `MODEL_NAME` directly (imported, not duplicated) — same Ollama call
  pattern, deliberately kept in a separate file so each module still has
  one job.
- `SYSTEM_PROMPT` rules: only extract explicit, concrete tasks; `person` =
  named person OR the raw speaker label if no name was mentioned (never
  invent a name); `deadline` = only if explicitly stated, else `null`
  (never inferred/guessed); `status` = optional, often `null`; empty
  `action_items` list is a valid, correct output if no real action items
  exist — the prompt explicitly forbids forcing items to appear.
- `extract_action_items(segments, model)` — normalizes every returned item
  to always have all 4 keys (`person`, `task`, `deadline`, `status`) even
  if the model omitted one; drops any item with no actual task text.
- Output: `{"action_items": [...]}`, saved to
  `data/outputs/action_items.json`.

### `speaker_statistics.py` — Phase 6a: Speaker stats
- Pure computation, no LLM, no external dependencies — deterministic and
  fast.
- Computes per speaker: `speaking_time_sec` (sum of segment durations),
  `participation_pct` (% of total speaking time across all speakers, NOT %
  of meeting wall-clock time), `utterance_count`, `word_count` (simple
  whitespace split).
- Explicitly does NOT try to apportion overlapping speech between
  speakers if segments genuinely overlap — out of scope, each speaker just
  gets full credit for their own segment duration.
- Output saved to `data/outputs/speaker_statistics.json`.

### `meeting_metadata.py` — Phase 6b: Meeting metadata
- Computes: `meeting_id` (auto-generated as `MTG-YYYYMMDD-HHMMSS` if not
  passed in), `date`, `time`, `duration_sec`/`duration_readable` (wall-clock
  span: last segment's end minus first segment's start — explicitly NOT
  the same as summed speaking time from `speaker_statistics.py`, expected
  to differ due to silences/gaps), `num_speakers` (excludes `"UNKNOWN"`),
  `languages_used` (reads each segment's `"language"` tag if present, in a
  preferred order: English, Hindi, Code-Mixed, then anything else
  alphabetically — returns empty list if no segments are tagged yet),
  `total_word_count`.
- `meeting_id`/`date`/`time` explicitly documented as NOT derivable from
  the transcript content itself — they describe when/what the meeting
  *was*, and can be passed in as overrides by the backend/UI later.
- Output saved to `data/outputs/meeting_metadata.json`.

---

## Files built in THIS chat (the integration/live-capture work)

### `config.py` — centralized configuration
- Created to remove all hardcoded values scattered across the other
  modules (Windows FFmpeg path, HF token, duplicated `"qwen2.5:7b"` model
  name string, duplicated `"data/outputs/..."` path strings).
- Uses `python-dotenv`'s `load_dotenv()` to read a local `.env` file.
- `HF_TOKEN` — read from `os.environ.get("HF_TOKEN")` only, no fallback
  string baked into code (earlier chat had a real HF token pasted in
  plaintext by the user — flagged as compromised, user was told to revoke
  and rotate it on Hugging Face).
- `WHISPER_MODEL_SIZE` (default `"large-v3"`), `WHISPER_DEVICE` (default
  `"cpu"`), `WHISPER_COMPUTE_TYPE` (default `"int8"`).
- `DIARIZATION_MODEL` (default `"pyannote/speaker-diarization-3.1"`).
- `OLLAMA_MODEL` (default `"qwen2.5:7b"`).
- `resolve_ffmpeg_bin_dir()` — tries `shutil.which("ffmpeg")` first (PATH
  auto-detection); only falls back to a configured `FFMPEG_BIN` env var if
  auto-detection fails. The user's actual hardcoded WinGet path lives only
  as a *commented example* in `.env.example`, not in live code.
- Centralized output paths: `TRANSCRIPT_PATH`, `DIARIZATION_PATH`,
  `ALIGNED_PATH`, `TAGGED_PATH`, `HINGLISH_PATH`, `SUMMARY_PATH`,
  `ACTION_ITEMS_PATH`, `SPEAKER_STATS_PATH`, `METADATA_PATH`, all derived
  from `DATA_DIR`/`OUTPUT_DIR`.
- `ensure_output_dir()` — creates the output directory if missing.
- `validate_config(require_hf_token=True)` — explicit function, NOT run on
  import, so importing `config` for testing doesn't blow up before `.env`
  is set up. Checks for missing `HF_TOKEN` and missing ffmpeg
  (PATH-or-configured), raises one clear `RuntimeError` listing all
  problems found, rather than failing cryptically deep inside pyannote or
  Whisper later.
- Confirmed working: user ran
  `python -c "import config; config.validate_config(); print('Config OK')"`
  and got `Config OK` (with a harmless `SyntaxWarning: invalid escape
  sequence '\p'` from the `.env.example` path example inside the
  docstring — cosmetic only, fix suggested but not yet applied: change the
  module docstring's opening `"""` to `r"""`).

### `.env.example` — template for the real `.env` file
- Contains commented-out example values for every config key, including
  the original hardcoded FFmpeg path as a commented reference, and a note
  that `.env` should be added to `.gitignore` and never committed.

### `live_capture.py` — live microphone recording with VAD-based chunking
- **Two versions exist in this chat's history** — see Timeline below for
  why. The FINAL, correct version uses **`webrtcvad`** (WebRTC's trained
  speech/non-speech classifier), NOT an energy/RMS-threshold heuristic.
  An energy-based version was written and then explicitly reverted after
  the user pushed back with a stronger, correct argument (see Timeline).
- `SAMPLE_RATE = 16000` (required by webrtcvad: must be 8000/16000/32000/
  48000), `FRAME_DURATION_MS = 30` (webrtcvad requires exactly 10/20/30ms
  frames), `FRAME_SIZE` derived from those.
- `VAD_AGGRESSIVENESS = 2` (0-3 scale, 0=least aggressive filtering of
  non-speech, 3=most aggressive).
- `PAUSE_DURATION_SEC = 1.2` — silence duration needed to end/cut a chunk.
- `MIN_CHUNK_DURATION_SEC = 1.0` — chunks shorter than this are discarded
  as likely noise/false triggers.
- `MAX_CHUNK_DURATION_SEC = 45` — hard cap so one long monologue doesn't
  become one giant chunk.
- `save_wav(path, audio, sample_rate)` — writes int16 PCM to a `.wav`
  file using the standard library `wave` module.
- `record_chunks(on_chunk_ready, chunk_dir=None, device=None)` — the core
  function. Uses a `collections.deque` ring buffer sized to
  `PAUSE_DURATION_SEC` worth of frames. State machine: not-triggered
  (waiting for enough voiced frames in the recent buffer to start a chunk)
  → triggered (accumulating frames until enough recent frames are
  unvoiced, i.e. a pause is detected, OR max duration is hit) → chunk
  saved, callback fired, state resets.
  - `on_chunk_ready(chunk_path: str, offset_sec: float)` callback
    signature — `offset_sec` is how many seconds into the overall
    recording session this chunk started, needed later for timestamp
    stitching.
  - Runs until `KeyboardInterrupt` (Ctrl+C); on interrupt, flushes any
    in-progress chunk if it's long enough before exiting.
- Design rationale documented in the file's own docstring: silence-based
  (VAD-triggered) chunking was chosen over fixed-size chunking because
  fixed windows would cut sentences/speaker turns mid-word, hurting both
  Whisper (garbled boundary output) and pyannote (worse speaker embeddings
  on truncated speech).
- Rationale for webrtcvad specifically over energy-threshold VAD (added
  back into the docstring after the revert): this project's core subject
  matter IS ASR+diarization quality, so the VAD stage should be a real
  trained classifier, not a heuristic more easily fooled by background
  noise, quiet/distant speech, keyboard sounds, fans/AC, etc.
- `__main__` block: minimal standalone test that just prints each chunk
  path/offset as it's captured, without running the full pipeline.

### `stitch.py` — combines per-chunk outputs into one continuous transcript
- `offset_segments(segments, offset_sec, chunk_index)` — shifts every
  segment's `start`/`end` by `offset_sec` to place it correctly on the
  overall meeting timeline. Also prefixes speaker labels with the chunk
  index (e.g. `"C2_SPEAKER_00"`) — this was the FIRST (documented,
  explicit) fix for the fact that pyannote's speaker labels are
  chunk-local and NOT guaranteed consistent across chunks. This
  prefixing approach was later superseded by `speaker_registry.py`'s
  proper cross-chunk identity resolution (see below), but the prefixing
  logic still exists in `stitch.py` as-is — it hasn't been removed or
  made conditional; `run_live.py` now overwrites the `"speaker"` field
  with the globally-resolved label AFTER `stitch.py` does its own
  offsetting, so in the current wired-up pipeline the chunk-prefixing
  effectively gets overwritten downstream. (This is a loose end — see
  Open Items below.)
- `TranscriptStitcher` class:
  - `add_chunk(aligned_segments, offset_sec)` — increments
    `chunk_count`, calls `offset_segments`, extends `self.all_segments`,
    returns the shifted segments (for immediate printing).
  - `get_full_transcript()` — returns `self.all_segments` sorted by
    `start` time (defensive sort; chunks should already arrive in order
    since processing is sequential per-chunk, but sorted just in case).
  - `save(path=None)` — defaults to `config.ALIGNED_PATH`
    (`data/outputs/final_transcript.json`), writes JSON.
- Explicit documented limitation in the file's docstring: proper
  cross-chunk speaker continuity needs voice embedding comparison, which
  is out of scope for `stitch.py` itself (it was later built separately as
  `speaker_registry.py`).

### `run_live.py` — live pipeline entry point
- **Two versions exist in this chat's history** (see Timeline). The FIRST
  version had a real, serious bug: it called
  `process_chunk()` — which runs Whisper transcription, pyannote
  diarization, and alignment (several seconds of work per chunk) —
  **synchronously, inline, inside the `on_chunk_ready` callback that
  `record_chunks()` calls from its own mic-reading loop**. This meant mic
  capture was completely frozen while any chunk was being processed;
  anything said during that window was silently lost. Confirmed via a
  real test run (see Timeline) — chunk 2 didn't start processing until
  55.7s into the recording even though chunk 1 audio ended around 10.7s,
  meaning roughly 45 seconds of the recording session were being wasted /
  audio was not being captured properly during that gap.
- **THE CURRENT, FIXED VERSION** uses a producer-consumer architecture:
  - Main thread runs `record_chunks(on_chunk_ready=...)` continuously,
    uninterrupted. The `on_chunk_ready` callback now ONLY does
    `chunk_queue.put((chunk_path, offset_sec))` — an near-instant
    operation — so the mic-reading loop is never blocked.
  - A separate **daemon background thread** (`threading.Thread(...,
    daemon=True)`) runs `processing_worker(...)`, which pulls
    `(chunk_path, offset_sec)` tuples off a `queue.Queue()` in a loop and
    does the actual slow work: `transcribe_audio()` →
    `diarize_audio()` → `align_transcript()` →
    `merge_consecutive_same_speaker()` → speaker-registry resolution →
    `stitcher.add_chunk()` → prints the resulting segments.
  - If processing falls behind real-time mic input, chunks simply queue
    up (a "(processing backlog: N chunk(s) waiting)" message is printed
    when the queue has a backlog) rather than audio being dropped.
  - Uses a sentinel object `_STOP` pushed onto the queue to cleanly signal
    the worker thread to exit; `worker.join()` is called before saving, so
    the program waits for all queued chunks to finish processing (drains
    the queue) before writing the final combined transcript — meaning the
    tail end of a meeting isn't lost when the user hits Ctrl+C.
  - `main()` sequence: `config.validate_config()` → load Whisper model
    once → load pyannote diarization pipeline once → load
    `SpeakerRegistry` (which itself loads the `pyannote/embedding` model)
    once → start the worker thread → call `record_chunks()` on the main
    thread → on `KeyboardInterrupt`/exit, push `_STOP`, join the worker,
    save the stitched transcript via `stitcher.save()` to
    `config.ALIGNED_PATH`.
  - Final printed instruction reminds the user to run
    `language_detection.py` / `normalize.py` / `summarization.py` etc. on
    the saved output next — these downstream scripts are UNCHANGED and
    still work as before, since the live pipeline writes to the same
    `data/outputs/final_transcript.json` path they already read from.
- **This fixed version has NOT yet been tested live by the user** — it
  was the most recent code delivered in this chat, and the conversation
  moved to a memory-update request before a test run happened. Confirming
  this actually fixes both bugs (continuous non-blocking recording +
  consistent speaker IDs across chunks) is the immediate next step.

### `speaker_registry.py` — cross-chunk speaker identity via voice embeddings
- Built as the proper fix for the speaker-label-inconsistency bug (see
  Timeline) — a real, standard technique (used in production diarization
  systems), not an ad-hoc heuristic.
- Uses `pyannote.audio.Model` + `pyannote.audio.Inference` with model
  `"pyannote/embedding"`, loaded via the same `HF_TOKEN` already used for
  the diarization pipeline (no new credential needed).
- `SIMILARITY_THRESHOLD = 0.75` — cosine similarity above this counts as
  "the same speaker".
- `SpeakerRegistry` class:
  - `__init__(hf_token=None)` — loads the embedding model, sets up
    `self.known_speakers: dict[str, np.ndarray]` (global speaker ID →
    representative embedding vector) and `self.next_speaker_num = 0`.
  - `_cosine_similarity(a, b)` — standard cosine similarity between two
    flattened vectors, returns 0.0 if either vector has zero norm
    (guards against division by zero).
  - `_match_or_register(embedding)` — compares the given embedding
    against every known speaker's stored embedding, picks the
    highest-similarity match. If that best match clears
    `SIMILARITY_THRESHOLD`, reuses that speaker's global ID AND updates
    their stored embedding with a running weighted average (`0.7 * old +
    0.3 * new`) so the reference embedding adapts slightly over time
    rather than freezing on the very first sample. If no match clears
    the threshold, mints a brand new global ID (`f"SPEAKER_{n:02d}"`) and
    registers it.
  - `resolve_chunk(chunk_audio_path, local_segments)` — given one chunk's
    audio file path and its locally-diarized segments (with
    chunk-local `"speaker"` values like `"SPEAKER_00"`), computes ONE
    embedding for the WHOLE chunk audio (not per-segment) and maps every
    distinct local speaker label found in that chunk to the same
    resolved global label. Returns a `{local_label: global_label}` dict.
- **Explicitly documented known simplification**: embedding the whole
  chunk as a single vector is a reasonable approximation for
  VAD-triggered chunks (which tend to be short and dominated by one
  speaker), but would NOT correctly handle a chunk that genuinely
  contains multiple different speakers talking within it — a more
  precise per-segment embedding approach would be needed for that case.
  This is called out as a known limitation, not silently glossed over.
- Wired into `run_live.py`'s `processing_worker`: after alignment, calls
  `speaker_registry.resolve_chunk(chunk_path, aligned)`, then rewrites
  each segment's `"speaker"` field using the returned mapping — this
  OVERWRITES whatever chunk-prefixed label `stitch.py`'s
  `offset_segments()` had already applied, so the global resolution wins
  in the end (see Open Items below about this being slightly redundant
  layering that hasn't been cleaned up).

---

## Key decisions & their reasoning (in chronological order of when decided)

1. **Local/offline deployment over cloud/API-based deployment** — chosen
   because: (a) the pipeline already works end-to-end locally, migrating
   now risks breaking things before the final deadline; (b) zero cost vs.
   API/cloud GPU bills; (c) meeting audio privacy — nothing leaves the
   machine; (d) capstone rubrics reward a working, demonstrable system
   over infrastructure sophistication; (e) can be framed as a deliberate,
   defensible architecture choice in the report (privacy, offline
   capability, zero operating cost) rather than an apologized-for
   limitation, with cloud/GPU deployment mentioned as "future work."

2. **Drop the "each phase independently CLI-runnable" design constraint**
   — the user explicitly decided to move away from testing each phase in
   isolation via separate `python x.py` invocations, in favor of a
   unified integrated pipeline. This directly motivated building
   `config.py` and the live-capture orchestration rather than a simple
   per-phase test harness.

3. **Chose Ollama (local LLM) over a paid API** (e.g. Anthropic's API) for
   both the Hinglish normalization pass and summarization/action-item
   extraction — free, no rate limits, offline-capable, and keeps meeting
   audio content from leaving the machine, consistent with the
   local-deployment decision above.

4. **Chose `qwen2.5:7b` over `llama3.1:8b`** as the actual Ollama model
   used in both `normalize.py` and `summarization.py`, after testing
   showed Qwen models handle Hindi/Devanagari noticeably better. This was
   a real correction during the project — an earlier assumption (before
   code was actually pasted/verified) had incorrectly attributed the
   summarization step to "Llama 3" based on an older tools slide; this was
   corrected once the real `summarization.py`/`normalize.py` code was
   directly inspected.

5. **Language detection method: rule-based Unicode-script heuristic, NOT
   a trained classifier (NOT XLM-RoBERTa)** — chosen for simplicity,
   speed, zero extra dependency, offline operation, and easy
   explainability/defensibility in a review ("why did you classify this
   as code-mixed — here's the exact word split"), consistent with the
   project's "integration, not new model training" positioning. This was
   also a real correction: an earlier, less-verified assumption had
   attributed this step to XLM-RoBERTa before the actual
   `language_detection.py` code was inspected and found to be a simple
   regex/Unicode-range heuristic instead.

6. **`language_detection.py` must run BEFORE `normalize.py`** — the
   user's own explicit reasoning, confirmed correct: script-based
   detection only has a usable signal (Devanagari vs Latin) on the raw
   Whisper output; once Hinglish normalization converts everything to
   Roman script, that signal is destroyed. So tagging happens first, then
   normalization happens on the already-tagged transcript, preserving the
   `"language"` field through untouched.

7. **Silence/VAD-based chunk boundaries over fixed-size chunks** for live
   audio — fixed-size windows (e.g. "cut every 30 seconds") would slice
   through sentences and speaker turns arbitrarily, degrading both Whisper
   and pyannote's output quality. VAD-based cutting produces chunks that
   align with natural utterance/pause boundaries instead.

8. **webrtcvad (trained VAD model) over energy/RMS-threshold heuristic
   VAD** — see full Timeline entry below; this was a real back-and-forth
   where the assistant initially proposed switching to an energy-based
   heuristic to avoid a Windows compiler dependency, and the user
   correctly pushed back that this would degrade a core signal-processing
   component on a project whose entire subject matter is ASR+diarization
   quality. The assistant agreed this was the better call and reversed
   course.

9. **Fix the Python version (3.14 → 3.12) rather than work around
   webrtcvad's build failure** — same reasoning as #8: fixing the root
   cause (bleeding-edge Python version lacking prebuilt wheel support for
   compiled C-extension packages across the whole ML/audio dependency
   stack) is more robust than patching around one symptom, and avoids
   likely future breakage with other compiled dependencies too.

10. **Voice-embedding-based cross-chunk speaker identity resolution
    (`speaker_registry.py`) over the simpler chunk-prefix labeling
    (`stitch.py`'s original approach)** — the prefix approach
    (`C1_SPEAKER_00`, `C2_SPEAKER_00`) was always documented as an
    honest "we don't know" placeholder, not a real fix. Once live testing
    confirmed this was a real, visible problem (same actual speaker
    showing under three different labels across three chunks), the
    proper fix (embedding similarity matching) was built.

11. **Producer-consumer threading architecture (queue + background
    worker thread) over synchronous inline processing** — the original
    `run_live.py` design processed each chunk synchronously inside the
    mic-reading callback, which silently dropped audio during processing
    time. This is being fixed with recording on the main thread and
    processing on a separate daemon thread connected by a `queue.Queue`.

---

## Timeline of problems encountered & how they were solved

### 1. HF token exposure
User pasted their real Hugging Face token in plaintext directly into the
chat while sharing their `diarization.py` code for review. Flagged
immediately as compromised; user was told to revoke it on Hugging Face
and generate a new one, and to keep tokens out of committed code going
forward (env-var-only, later formalized via `config.py` + `.env`).

### 2. Pyannote API changes (resolved by the user, independently, before
bringing the working code back to this chat)
- `Pipeline.from_pretrained(..., use_auth_token=hf_token)` raised
  `TypeError: unexpected keyword argument 'use_auth_token'` → fixed by
  renaming the parameter to `token=hf_token` (matches the currently
  installed pyannote version's API).
- `403 Forbidden` on `pyannote/speaker-diarization-community-1` → fixed by
  accepting the gated model's terms/conditions on Hugging Face (a
  dependency of the diarization pipeline that also needed separate
  access acceptance beyond the two originally-mentioned gated models).
- `RuntimeError: Could not load libtorchcodec` → pyannote's internal audio
  decoding (via TorchCodec) couldn't find FFmpeg's DLLs on Windows, even
  though `ffmpeg -version` worked fine in a normal terminal (the initial
  auto-detected DLL directory pointed at a WinGet *link* location, not the
  real DLL folder). Fixed by installing the `Gyan.FFmpeg.Shared` package
  specifically (not the non-shared `Gyan.FFmpeg` the user had originally),
  locating its real `bin` directory (containing `avcodec-63.dll`), and
  calling `os.add_dll_directory(FFMPEG_BIN)` explicitly before importing
  `pyannote.audio`.
- `AttributeError: 'DiarizeOutput' object has no attribute 'itertracks'`
  → the installed pyannote version wraps its diarization result in a
  `DiarizeOutput` object rather than returning a raw `Annotation`
  directly; fixed by accessing `.speaker_diarization` on the result
  before calling `.itertracks(yield_label=True)`.
- All four fixes were verified correct by the assistant as matching the
  real, current pyannote API — not guesswork.

### 3. Whisper "medium" model transcription accuracy problems on Hindi/
code-mixed audio
User's `medium`-model transcription of a real test clip produced Whisper
output that was mostly-correct but garbled in places: "kyun" instead of
"kaun" (who vs why), "doon sppeakers" (garbled), "hukhphuli" instead of
"hopefully", "karekli" instead of "correctly", "let started destination"
instead of "perfect, let's start the test". This surfaced while testing
the Hinglish normalization pass, and required carefully separating TWO
distinct problems that were tangled together in the same output:
  - Problem A: genuine Whisper mis-transcription (wrong words entirely) —
    NOT fixable by normalization, since normalization must never guess at
    or "correct" meaning, only convert script.
  - Problem B: correct normalization of whatever Whisper actually
    produced, including faithfully transliterating Whisper's own errors.
This was explicitly diagnosed as a root-cause-at-the-ASR-layer problem,
not a normalization-layer problem. Fix: switched Whisper model from
`medium` to `large-v3` — user confirmed this resolved the accuracy
problems on the same test clip. (Audio quality/recording setup and an
`initial_prompt` vocabulary-hinting technique were also suggested as
additional levers, but switching to `large-v3` alone was sufficient and
is what was actually adopted.)

### 4. Language detection task spec vs. actual implementation gap
An uploaded slide image specified Member 2's language detection task with
example inputs/outputs written in already-Romanized Hinglish text (e.g.
`"Aaj hum meeting start karte hain." → Hindi`). The assistant built a
script-based Unicode heuristic (`language_detection.py`) that, when
run standalone on already-Romanized text, technically CANNOT achieve the
spec's own example outputs, because Devanagari-vs-Latin script comparison
has no signal once everything is in Latin script. This gap was explicitly
flagged to the user as a caveat before they made the (correct) call to
run the script BEFORE Hinglish normalization instead, where the
Devanagari signal is still present and the heuristic actually works
correctly — resolving the apparent conflict via pipeline ordering rather
than needing a different (dictionary-based or model-based) detection
method.

### 5. Python 3.14 vs. webrtcvad build failure — a genuine back-and-forth
where the assistant's first instinct was wrong
- The user's `pip install webrtcvad-wheels` failed with a clear
  compiler error: `Microsoft Visual C++ 14.0 or greater is required`,
  building against `cpython-314` — meaning the user's actual environment
  was Python 3.14 (not 3.13 as might otherwise have been assumed), and no
  prebuilt wheel exists yet for `webrtcvad`/`webrtcvad-wheels` on that
  Python version on Windows.
- The assistant's FIRST proposed fix was to abandon `webrtcvad` entirely
  and rewrite `live_capture.py` to use a pure-Python energy/RMS-threshold
  VAD instead, to avoid the compiler dependency. This was actually
  implemented (a full alternate version of `live_capture.py` was written
  and delivered) before the user pushed back.
- The user correctly objected: webrtcvad is a real, validated trained
  model (not a heuristic being substituted in as a workaround), and for a
  project whose whole subject matter IS ASR+diarization quality,
  downgrading to a cruder heuristic that's more easily fooled by
  background noise, quiet/distant speech, keyboard sounds, and fans/AC
  is the wrong tradeoff for a "controlled demo" project like this. The
  user proposed instead fixing the root cause: use the Python 3.12
  environment already installed on their machine
  (`C:\Users\rushi\AppData\Local\Programs\Python\Python312\python.exe`),
  which has proper prebuilt-wheel compatibility for the whole ML/audio
  stack (Faster-Whisper, pyannote, sounddevice, webrtcvad, FFmpeg
  integration), rather than rewriting a core signal-processing component
  to dodge a packaging problem.
- The assistant agreed this was the better call, explicitly reversed
  course, reverted `live_capture.py` back to its original
  `webrtcvad`-based implementation (removing the energy-threshold
  version entirely), and walked the user through creating a fresh
  `venv312` virtual environment pinned to the 3.12 interpreter,
  reinstalling all dependencies there (`faster-whisper`,
  `pyannote.audio`, `python-dotenv`, `sounddevice`, `numpy`,
  `webrtcvad`, `ollama`).
- Outcome, confirmed by the user: all dependencies installed successfully
  in `venv312` (most were already present from an earlier partial
  attempt; `ollama` was the only genuinely new install in that batch, and
  `webrtcvad` was confirmed separately installed by the user), and
  `config.validate_config()` printed `Config OK` (HF_TOKEN present,
  ffmpeg found on PATH).

### 6. First live end-to-end test run of `run_live.py` — surfaced two
real, distinct bugs
User ran `python run_live.py`, spoke three short lines with pauses
between them, and Ctrl+C'd. The pipeline successfully loaded FFmpeg DLLs,
validated config, loaded the Whisper `large-v3` model, loaded the
diarization pipeline, listened, captured 3 chunks, transcribed and
diarized each one, and saved a combined `final_transcript.json` with 3
segments. Example real output line: `[3.46s - 9.62s] C1_SPEAKER_00: Good
morning, आज हम अपने speech recognition system को test कर रहे हैं.`
(showing the still-not-yet-normalized Devanagari-mixed Whisper output,
as expected at this pipeline stage — normalization hadn't been run yet
on this live-capture output). A `UserWarning: std(): degrees of freedom
is <= 0` from pyannote appeared again (same harmless warning as before,
on short chunk audio).

Two real problems were identified directly from this output, both
raised by the user and confirmed by the assistant as legitimate:

- **Problem 1 — speaker label inconsistency across chunks (predicted
  and explicitly documented as a known limitation earlier, now
  empirically confirmed)**: all three chunks showed
  `C1_SPEAKER_00`/`C2_SPEAKER_00`/`C3_SPEAKER_00` despite being spoken by
  the same actual person — because diarization runs independently per
  chunk with zero memory of prior chunks, so "SPEAKER_00" is only
  meaningful within a single chunk, not globally.
- **Problem 2 — recording blocks during processing (a genuine
  architecture bug, not previously anticipated in this specific form)**:
  the user observed that after a chunk finished recording, the program
  would NOT capture the next spoken line until the current chunk had
  finished being fully processed (transcribed + diarized) — meaning
  speech occurring during that processing window was being lost
  entirely, not merely delayed. Concretely evidenced by chunk 2 not
  starting processing until 55.7 seconds into the session despite chunk
  1's audio having ended around 10.7 seconds — roughly 45 seconds during
  which the recording loop was frozen inside the synchronous
  `on_chunk_ready` callback.

Both were diagnosed with precise root causes and fixed as described
above under "Files built in this chat": Problem 1 via
`speaker_registry.py` (voice embedding cosine-similarity matching across
chunks), Problem 2 via rewriting `run_live.py` into a producer-consumer
architecture (recording on the main thread, processing on a separate
daemon worker thread connected by a `queue.Queue`).

**As of the end of this chat, the fixed versions of `speaker_registry.py`
and `run_live.py` have been written and delivered but NOT YET TESTED
live by the user.** Confirming both fixes actually work in practice
(continuous uninterrupted recording + consistent speaker IDs across
chunks) is the clear, explicit next step.

---

## Open items / not yet resolved, explicitly flagged

1. **`run_live.py`'s threaded, speaker-registry-integrated version has
   not been tested live yet.** This is the single most important
   immediate next step.

2. **Minor architectural redundancy, not yet cleaned up**: `stitch.py`'s
   `offset_segments()` still prefixes speaker labels with the chunk index
   (e.g. `C2_SPEAKER_00`) as it did before `speaker_registry.py` existed.
   `run_live.py`'s `processing_worker` now overwrites that prefixed label
   with the globally-resolved speaker ID from `speaker_registry.py`
   immediately afterward, so the end result is correct, but the
   chunk-prefixing logic in `stitch.py` is now somewhat vestigial/dead
   weight in the current pipeline shape. Not a bug, but worth simplifying
   later — could remove the prefixing from `stitch.py` now that
   `speaker_registry.py` does the real resolution, or keep it as a
   fallback/debug label if `speaker_registry.py` resolution ever fails
   for a chunk (currently, if `speaker_registry.resolve_chunk()` doesn't
   return a mapping entry for a given local label for any reason, the
   code just leaves that segment's original — chunk-prefixed — label
   alone, so the prefixing does still serve as an implicit fallback,
   just not a deliberately-designed one).

3. **`diarization.py` still has the original hardcoded Windows FFmpeg
   path** (`FFMPEG_BIN = r"C:\Users\rushi\AppData\Local\..."`) baked into
   the top of the file, even though `config.py`'s
   `resolve_ffmpeg_bin_dir()` was built specifically to replace this
   pattern with auto-detection. `diarization.py` itself was never
   actually updated to import from `config.py` — only the new
   live-capture-related files (`live_capture.py`, `run_live.py`,
   `stitch.py`) consume `config.py`. This means `diarization.py`, if run
   completely standalone (`python diarization.py test.wav`), still uses
   its own separate hardcoded path and its own separate
   `HF_TOKEN = os.environ.get("HF_TOKEN", "PASTE_YOUR_TOKEN_HERE")`
   pattern rather than `config.HF_TOKEN`.

4. **Duplicate "Diarizing..." print statement in `diarization.py`**
   (once inside `diarize_audio()`, once in the `__main__` block) —
   flagged as a known cosmetic issue early in the chat, suggested fix
   (remove the `__main__` block's copy) was given but not confirmed
   applied by the user.

5. **`normalize.py` and `summarization.py` both still hardcode
   `MODEL_NAME = "qwen2.5:7b"` as a local module-level constant**, rather
   than importing `OLLAMA_MODEL` from `config.py` — this duplication was
   one of the original motivations for building `config.py` in the first
   place, but the actual `normalize.py`/`summarization.py`/
   `action_items.py` files (as pasted/uploaded by the user) have not yet
   been edited to import from `config.py`. `action_items.py` additionally
   imports `MODEL_NAME` directly from `summarization` (`from
   summarization import ..., MODEL_NAME`), so fixing this centralization
   only requires editing `summarization.py`'s constant, which would then
   propagate.

6. **`normalize.py`'s per-segment Ollama call performance** — flagged as
   slow (loading/calling the LLM once per segment rather than batching),
   with batching suggested as a future optimization. Not implemented.
   This is a separate performance concern from the `run_live.py`
   threading fix — even with threading, `normalize.py` itself (run as a
   separate downstream step after live capture, not currently wired into
   `run_live.py`'s real-time loop at all) would still be slow
   per-segment.

7. **`normalize.py` and `summarization.py`/`action_items.py` are NOT
   currently wired into the live pipeline (`run_live.py`) at all.**
   `run_live.py` only runs transcribe → diarize → align →
   speaker-resolution, and saves the raw (still Devanagari-mixed, not yet
   language-tagged) transcript to `final_transcript.json`. The
   user is expected to manually run `language_detection.py --pipeline`,
   then `normalize.py`, then `summarization.py`/`action_items.py`/
   `speaker_statistics.py`/`meeting_metadata.py` as separate subsequent
   steps after a live recording session ends — none of these downstream
   phases have been integrated into a single unified end-to-end script
   yet, despite "integrate the whole pipeline into one unified process"
   being the stated current top-level priority at the start of this
   chat's live-capture work. The live-capture/threading/speaker-identity
   work accomplished so far is a (large, necessary) SUBSET of that full
   integration goal — specifically the recording+ASR+diarization+
   alignment portion — not the complete unified pipeline across all
   phases.

8. **`.env` file's `FFMPEG_BIN` line** — user confirmed `ffmpeg` was found
   via PATH auto-detection (no `FFMPEG_BIN` override needed in their
   actual working `.env`), so this fallback path is currently unused in
   their setup, though it remains available if needed on a different
   machine/environment.

9. **Cosmetic `SyntaxWarning` in `config.py`** (`invalid escape sequence
   '\p'` from the example FFmpeg path written inside the module's
   plain, non-raw docstring) — fix suggested (change opening `"""` to
   `r"""`) but not confirmed applied.

10. **UI/frontend (Phase 8) and TXT/PDF export** — explicitly deferred
    throughout this entire chat, per the user's stated priority ("i dont
    need to immediately start with the ui"). Not discussed further beyond
    that deferral.

---

## Environment / dependency summary (current, as of end of this chat)

- OS: Windows.
- Two Python installs on the machine: 3.14 (original, now considered
  legacy/problematic for this project) and 3.12 (the one now actually
  being used, at
  `C:\Users\rushi\AppData\Local\Programs\Python\Python312\python.exe`).
- Active virtual environment: **`venv312`**, created via
  `python -m venv venv312` using the 3.12 interpreter specifically. An
  older `venv` (3.14-based) also still exists on disk but is being
  phased out / ignored.
- Installed packages (confirmed working in `venv312`): `faster-whisper`,
  `pyannote.audio` (version 4.0.7 per the pip output — this is the
  version whose diarization result needs `.speaker_diarization` accessed
  before `.itertracks()`, and whose gated dependencies include
  `pyannote/speaker-diarization-community-1`), `python-dotenv`,
  `sounddevice`, `numpy`, `webrtcvad`, `ollama` (the Python client for a
  locally-running Ollama server).
- Ollama itself: installed separately (not a pip package) as a background
  service, exposing a local API at `localhost:11434`; model
  `qwen2.5:7b` pulled and in active use.
- FFmpeg: available via PATH on the user's machine (confirmed by
  `config.validate_config()` passing without needing the `FFMPEG_BIN`
  fallback) — separately, the Gyan.FFmpeg.Shared WinGet package was
  specifically installed earlier for the TorchCodec DLL-loading fix (see
  Timeline #2), and that path is preserved as a comment/fallback option
  in `.env.example` and still hardcoded directly inside `diarization.py`
  itself (see Open Items #3).
- Hugging Face: account created, terms accepted for the required gated
  model repos (`pyannote/speaker-diarization-3.1`,
  `pyannote/segmentation-3.0`, and
  `pyannote/speaker-diarization-community-1`), an access token generated
  and stored in `.env` as `HF_TOKEN` (the original token pasted in chat
  was flagged as compromised and the user was instructed to rotate it —
  not confirmed whether the token currently in their `.env` is the
  rotated one or a further subsequent one).
- Project file layout: flat, all `.py` files directly in
  `C:\Users\rushi\whisper-project\`, NOT nested under a `backend/`
  subfolder as an earlier, more elaborate suggested structure had
  proposed. Output JSON files go to `data/outputs/` under the project
  root. Live-capture audio chunks go to `data/audio_chunks/` (created by
  `live_capture.py` via `config.DATA_DIR`).

---

## Immediate next step (explicit, as of end of this chat)

Run `python run_live.py` again with the new threaded +
speaker-registry-integrated version, using a similar test (a few spoken
sentences with pauses, ideally including one case of speaking again
immediately as a previous chunk starts processing, to specifically
stress-test the non-blocking fix), and confirm:
1. The mic keeps capturing continuously without gaps/drops during
   processing (fixing the "doesn't capture the next line until
   processing finishes" bug).
2. The same real speaker now receives the same global `SPEAKER_XX` label
   across multiple chunks (fixing the `C1_SPEAKER_00` vs
   `C2_SPEAKER_00` inconsistency bug).

No code changes are pending on the assistant's side until this test
run's results come back.
