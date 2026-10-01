# Evaluation: dataset, labelling protocol, and metric methodology

This document is the specification for the evaluation study this project's
paper reports. It has two audiences: it tells a reviewer exactly what was
measured and how, and it tells whoever is building the dataset exactly what
to record and how to label it. The metric code described here
(`backend/src/meeting_assistant/evaluation/`) is built and unit-tested; the
dataset itself is not yet collected — see **Current status** at the end.

## Why this document exists

Three properties are non-negotiable for a published result (see the
project's own design notes for the reasoning): every number must be
**traceable** to a run id, git commit and config hash; every number must be
**regenerable** by re-running `meeting-assistant eval`, never produced by a
manual step; and **provenance must be explicit** — this project already had
one incident where a hand-authored 22-segment mock transcript's derived
outputs sat in an output folder looking exactly like genuine results (see
`legacy/README.md`). Nothing in `data/eval/` is ever synthetic for the same
reason: every clip here must be a real recording with a real reference
someone actually checked.

## Dataset composition target

**8-12 clips, 1-3 minutes each, 2-4 speakers**, spanning:

| Condition | Purpose |
|---|---|
| Hindi-dominant | tests ASR/normalization on mostly-Devanagari speech |
| English-dominant | baseline, and confirms code-mixing handling doesn't degrade pure English |
| Balanced code-mixed | the project's actual target use case |
| Adverse (background noise / distant mic) | tests robustness, not just the happy path |

Three short clips (`data/audio/test.wav`, `test1.wav`, `test_hindi.wav`) exist
today and were used throughout development to verify the pipeline runs
correctly on real audio. They are **not** a sufficient evaluation set — three
clips give no meaningful variance, and a reviewer will ask for more. They can
be included in the 8-12 if properly labelled, but the set needs to grow well
beyond them.

Record each clip as a mono WAV (whatever sample rate `sounddevice`/the mic
gives; the pipeline resamples as needed) into `data/audio/<clip_id>.wav`,
where `<clip_id>` is a short slug (`clip01`, `standup_hindi`, whatever is
memorable) — the eval CLI matches a reference bundle to a run by this exact
filename.

Keep a table of every clip's duration, speaker count, language mix and
recording condition. That table is what a reviewer expects in the paper's
dataset section — start it as clips are added, rather than reconstructing it
from memory later.

## Labelling protocol

Each clip needs some subset of these references, depending on which metric
families it is meant to exercise. None are required for every clip — a clip
can be labelled incrementally, and `generate_clip_report` skips a family
cleanly when its reference is absent (see
`backend/src/meeting_assistant/evaluation/report.py`).

### Speaker turns, for DER (`turns.rttm`)

1. Open the clip in **Audacity**.
2. Add a label track (`Tracks > Add New > Label Track`).
3. Mark each speaker turn boundary by ear, labelling each region with a
   speaker identifier (`A`, `B`, a real name — the labeller's choice, since
   DER matches labels by optimal overlap, not by name).
4. Export: `File > Export > Export Labels`. This produces a tab-separated
   `start\tend\tlabel` file.
5. Convert it with `meeting_assistant.evaluation.rttm.labels_to_rttm(path)`
   and write the result to `data/eval/references/<clip_id>/turns.rttm` via
   `meeting_assistant.evaluation.rttm.write_rttm` (or just save the raw
   Audacity export as `turns.rttm`-shaped by hand for a short clip — the
   reader (`read_rttm`) only needs valid RTTM `SPEAKER` lines).

Budget roughly 20-30 minutes of labelling per clip — this is the slowest
label to produce, which is exactly why the conversion tooling exists rather
than requiring RTTM syntax to be typed by hand.

### Reference transcript, for WER/CER (`transcript.txt`)

One continuous plain-text file: listen to the clip and type what was
actually said, in whatever script feels natural per word (Devanagari for
Hindi, Latin for English — do not pre-romanize; that is what
`WER_romanized` is for). Punctuation and casing do not matter — both sides
of every WER/CER comparison go through
`meeting_assistant.evaluation.text_norm.normalize_text` first.

### Language tags, for language-ID accuracy (`languages.json`)

A JSON list of labels (`"English"` / `"Hindi"` / `"Code-Mixed"`), **one per
segment of the run's own tagged transcript**, in the same order. Practically:
run the clip through `meeting-assistant batch <clip>.wav` first, open its
`05_tagged.json`, and label each segment's *true* language next to the
tagger's guess — this is a manual per-segment agree/disagree pass, not
independent labelling from scratch, and is quick (a few minutes per clip).

**Double-label a ~20% subset with a second annotator** and compute Cohen's
kappa (`meeting_assistant.evaluation.langid_metrics.cohens_kappa`) between
the two label sets for those clips. This is cheap and is exactly the kind of
check a reviewer asks for on any human-labelled categorical task — it
answers "is this a reliable ground truth" independently of how well the
tagger did against it.

### Reference summary, for ROUGE (`summary.txt`)

A few sentences, written after reading the reference transcript, summarizing
what the meeting was actually about. Independent of what the pipeline
produces — write it before looking at the pipeline's own summary, or the
comparison is not measuring anything.

### Reference action items, for extraction P/R/F1 (`action_items.json`)

A JSON list of `{"person": ..., "task": ..., "deadline": ...}` objects (any
field may be `null`), one per real commitment made in the meeting. See
`meeting_assistant.evaluation.intel_metrics.action_item_metrics` for exactly
how a predicted item is matched to a reference one (person must agree when
both are named; task is matched by normalized word overlap, not exact text).

### True speaker identity, for the speaker registry (`true_speakers.json`)

Only meaningful for a **live** run spanning multiple chunks, where cross-chunk
identity resolution is actually exercised. A JSON list of real names/ids, one
per segment of the run's resolved transcript, in the same order — walk the
run's stitched output and write down who each segment's speaker actually was.
`meta.json`'s `true_speaker_count` should record the true number of distinct
speakers in the meeting (not inferred from however many labels happen to
appear, in case someone spoke too briefly to ever be resolved).

### Per-clip metadata (`meta.json`)

```json
{ "true_speaker_count": 2 }
```

Currently just the one field the registry metrics need; extend as needed.

## The reference directory contract

```
data/eval/
├── clips/                          # (reserved; audio itself lives in data/audio/)
├── references/
│   └── <clip_id>/                  # clip_id matches data/audio/<clip_id>.wav
│       ├── transcript.txt
│       ├── turns.rttm
│       ├── languages.json
│       ├── summary.txt
│       ├── action_items.json
│       ├── true_speakers.json
│       └── meta.json
└── reports/
    └── latest.json                 # written by `meeting-assistant eval`
```

Run `meeting-assistant eval` once a clip has both a labelled reference
directory and a completed run (`meeting-assistant batch data/audio/<clip_id>.wav`)
under `data/runs/`. It matches each reference to the most recent *eligible*
run whose input filename matches, scores every metric family both sides have
data for, and writes `data/eval/reports/latest.json` — the full per-clip
breakdown plus a cross-clip aggregate
(`meeting_assistant.evaluation.report.aggregate_reports`).

A run is eligible only if its manifest says `data_origin: real_audio` and its
`consistency` block shows every stage on disk was produced under one
configuration and, if the run was resumed, one clean commit. A batch run can be
resumed (`--resume`, or `POST /api/runs/{id}/resume`), so its stages may come
from more than one process; each resume is recorded in the manifest's
`resumes` list and every stage entry names the `execution` that produced it.
Resuming under a changed output-affecting configuration is refused outright
unless `--allow-mixed-config` is passed, and such a run is never scored.
Resuming against a different recording (sha256 mismatch) is always refused.
Runs passed over are printed with the reason, so a clip silently scored against
an older run cannot go unnoticed. For reported numbers, run each clip fresh in
one execution on a clean, committed tree.

## Metric methodology

### ASR: three WER numbers, not one

A code-mixed transcript can legitimately render a Hindi word as Devanagari
(what Whisper emits) or Latin script (what normalization produces).
Comparing across scripts makes every correctly-transcribed Hindi word look
like a total substitution — a scoring artifact, not an ASR failure. So three
numbers are reported per clip:

- **`WER_raw`** — hypothesis and reference compared as-is. Measures ASR
  alone, including script differences.
- **`WER_romanized`** — both sides deterministically transliterated to
  ITRANS (`indic_transliteration`) before comparison, removing the script
  mismatch. **Never** computed using this project's own Ollama-based
  normalizer for that transliteration step — scoring the system under test
  with a reference the same system helped produce would be circular.
- **`CER_raw`** — character error rate, more informative than WER for
  morphologically rich Hindi and for Romanized spelling variance
  ("kya"/"kyaa" carry no fixed convention).

All three normalize text through a shared policy
(`evaluation/text_norm.py`) before comparison: NFKC normalization,
Devanagari digits mapped to ASCII, Latin lowercased, punctuation stripped
except an intra-word apostrophe or hyphen. That normalization is careful to
treat Devanagari combining marks (matras, virama) as word characters, not
strippable punctuation — an earlier version of this policy used Python's
regex `\w`, which does not match those Unicode categories, and silently
deleted them from every Hindi word. See `text_norm.py`'s docstring for the
full story.

### Diarization: DER with its components, collar 0.25s

Via `pyannote.metrics`. Reported as confusion / missed detection / false
alarm separately, not just the combined rate, so which failure mode
dominates a clip is visible. Labels are matched by optimal one-to-one mapping
(the Hungarian algorithm, via `pyannote.metrics` internally), not by name —
confirmed against real permuted labels during development.

### Speaker registry: identity accuracy, duration-weighted

The same "match by content, not by name" principle, applied to
`SPEAKER_G01`-style resolved ids against real names, computed via
`scipy.optimize.linear_sum_assignment` over a duration-weighted contingency
table (`evaluation/registry_metrics.py`). Also reports the unresolved rate
(fraction of segments the registry declined to guess on, because their
embedding window was too short) and mean match similarity.

### Language ID: accuracy, per-class P/R/F1, confusion matrix, kappa

Standard classification metrics via `scikit-learn`
(`evaluation/langid_metrics.py`). `cohens_kappa` is `nan`, not `1.0`, when
both annotators used only one label throughout their overlap — with a single
possible label, chance agreement is also 100%, making the statistic
mathematically undefined rather than perfect. Report the `nan` as-is; do not
substitute a number for it.

### Summarization: ROUGE + human rubric

ROUGE-1/2/L F-measure (`rouge_score`) is a content-overlap proxy, always
meant to be read alongside a human rubric (faithfulness, coverage, no
hallucination) scored by reading the pipeline's summary against the
reference — ROUGE alone cannot detect a fluent, confident hallucination.

### Action items: precision/recall/F1 on (person, task, deadline)

Matching is greedy in predicted order: each predicted item matches its best
remaining, person-compatible reference item if their task similarity
(normalized word-overlap / Jaccard) clears a threshold (default 0.5,
configurable). See `intel_metrics.py`'s docstring for the exact
precision/recall convention on empty-prediction/empty-reference edge cases.

### System metrics: RTF, latency

Pulled straight from each run's manifest (stage timings,
`live_stats.realtime_factor` for live runs) — no separate computation
needed; `_load_clip_hypothesis` in `cli/main.py` just reads them through.

## Current status

The metric code above is implemented and unit-tested (100+ test cases
against small hand-computed examples, `backend/tests/test_*_metrics.py`,
`test_der.py`, `test_rttm.py`, `test_report.py`) — every metric's
*correctness* is verified. The dataset itself — the 8-12 real, labelled
clips this document specifies — has not yet been collected. `meeting-assistant
eval` runs correctly today and reports "no labelled clips found" honestly,
rather than against fabricated data, until that collection happens.
