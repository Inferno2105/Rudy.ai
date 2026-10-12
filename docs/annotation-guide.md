# Annotator guide

How to label one evaluation recording, step by step. Every number the paper
reports about accuracy is measured against these labels, so they have to be
careful, consistent between the two of you, and made **without looking at what
the app produced** for that recording.

Allow about **1–1½ hours per recording** of 1–3 minutes:

| Step | What you make | Time |
|---|---|---|
| 1 | The clip's folder and its details (`meta.json`) | 5 min |
| 2 | What was said (`transcript.txt`) | 30–40 min |
| 3 | Who spoke when (`turns.txt`) | 20–30 min |
| 4 | Which language each stretch is in (`languages.txt`) | 10 min |
| 5 | A short summary (`summary.txt`) | 5 min |
| 6 | The action items (`action_items.txt`) | 5 min |
| 7 | Run the check and fix what it reports | 5 min |
| 8 | *Second annotator, some clips only:* label languages again, blind | 10 min |

## Before you start

**Tools**

- **Audacity** 3.x (free) for steps 3, 4 and 8.
- A text editor that saves **UTF-8**: VS Code, or Notepad (which saves UTF-8
  by default on Windows 11).
- A way to type Devanagari, such as the Windows *Hindi Phonetic* keyboard
  (Settings › Time & language › Language › Hindi › Keyboard options) or
  Google Input Tools.
- Headphones. Most labelling mistakes come from laptop speakers.

**Running the commands.** From the repository root in PowerShell, after
`.\venv312\Scripts\Activate.ps1`. If you use Docker instead, put
`docker compose exec app` in front of each command, for example
`docker compose exec app meeting-assistant dataset check`.

**Where files go**

- The recording is `data/audio/<clip_id>.wav`, for example `data/audio/clip01.wav`.
- The labels are in `data/eval/references/<clip_id>/`.
- **Labels go into git; recordings never do.** Share recordings only through a
  private folder restricted to the team, because participants consented to
  research use, not to publication.

**Three rules that keep the labels valid**

1. **Do not open the app's output for a recording before its labels are
   finished.** Seeing the system's transcript, tags or summary pulls you
   towards agreeing with it, and the measurement stops meaning anything.
2. **Follow the decisions recorded in this guide, even where you would choose
   differently.** Consistency between the two of you matters more than any
   single choice. If a rule is unclear, write the case down, agree on it
   together, and add it here before continuing.
3. **Label what was said, not what was meant.** Do not correct grammar, finish
   sentences or translate.

## Decisions to agree before labelling

These are the cases where two careful people would otherwise label
differently. A recommendation is given for each; **agree on one, write it in
the "Agreed" line, and never change it once labelling has begun.**

**D1. English words inside Hindi speech** (*meeting, office, plan, time,
phone, deadline*).
Recommended: write them in Latin script, and they count as English words when
choosing a language tag. So *"आज की meeting में plan discuss करेंगे"* is
Code-Mixed. The alternative treats everyday borrowings as Hindi (*"मीटिंग"*);
that is harder to apply consistently, because which words count as
"everyday" is a judgement call.
Agreed: ______________________

**D2. Hesitation sounds and filler words.**
Recommended: leave out pure hesitation sounds (*umm, uh, hmm*), and write words
that carry meaning or structure (*haan, accha, okay, matlab, yaani, actually*).
Agreed: ______________________

**D3. Repetitions and false starts** (*"we we need"*, *"kal — nahi, parso"*).
Recommended: write them as spoken, including the corrected part.
Agreed: ______________________

## Step 1 — Create the clip's folder

```powershell
meeting-assistant dataset new clip01
```

This creates `data/eval/references/clip01/` with templates for every file. Lines
starting with `#` in them are instructions; leave them or delete them, they
are ignored.

Fill in `meta.json`:

| Field | What to write |
|---|---|
| `condition` | One of `hindi-dominant`, `english-dominant`, `code-mixed`, `adverse` (noisy room or distant microphone) |
| `speakers` | How many people spoke (must match the speakers in `turns.txt`) |
| `device` | The microphone or phone used, e.g. `"Pixel 7 on the table"` |
| `recorded_on` | The date, as `"2026-10-14"` |
| `participants` | Consent-form ids, e.g. `["P01", "P02"]`. **Never names.** |
| `notes` | Anything unusual: a fan, someone joining late |

## Step 2 — What was said (`transcript.txt`)

Listen and type everything said, in order, as continuous text. Line breaks are
ignored, so starting a new line for each speaker turn is fine and makes
checking easier.

- **Write each word in the script it was spoken in:** Devanagari for Hindi,
  Latin letters for English (see D1). Never write Hindi in Latin letters here;
  the evaluation does its own transliteration.
- **Numbers as words, the way they were said:** *"पाँच बजे"*, *"five thirty"*.
- **Names** in Latin script, spelled as the person spells them.
- **Fillers, repetitions:** as agreed in D2 and D3.
- **A word you cannot make out:** write your best guess. If you have no guess,
  write `[?]` for that word.
- **Two people talking at once:** write the main speaker's words first, then
  the other person's.
- **Punctuation and capital letters do not matter.** They are removed before
  scoring.
- **No speaker names and no timestamps** in this file.

Listen once through first, then type, then listen once more while reading
along to catch mistakes.

## Step 3 — Who spoke when (`turns.txt`)

In Audacity:

1. **File › Open** the recording.
2. **Tracks › Add New › Label Track.** Use *one* label track (see the note below).
3. For each turn, **drag across the waveform** from where the person starts
   speaking to where they stop, press **Ctrl+B**, type the speaker's
   consent-form id (`P01`), and press Enter. Zoom in with **Ctrl+1** to place
   the edges on the first and last word.
4. When done, **File › Export › Export Labels…** and save as
   `data/eval/references/clip01/turns.txt`.

What counts as a turn:

- **One person speaking without being interrupted.** A pause under about a
  second inside it is still the same turn.
- **A short reply from someone else** (*"haan"*, *"okay"*) is its own short
  turn for that person.
- **Overlapping speech:** mark both people's regions; turns may overlap.
- **Silence between turns:** leave it unlabelled.
- **Use the same id for the same person** throughout the recording.

> **Audacity exports every label track into the same file.** Before step 4,
> remove this label track (click its name › *Delete Track*) or start a new
> project, so the language labels do not end up in `turns.txt`.

## Step 4 — Language of each stretch (`languages.txt`)

New label track, same way as step 3. Mark the speech as consecutive stretches,
each in **one** language mode, labelled:

| Label | When | Short form |
|---|---|---|
| `Hindi` | Only Hindi words (names do not count) | `H` |
| `English` | Only English words | `E` |
| `Code-Mixed` | Hindi and English words in the same sentence | `M` |

- **A stretch is usually one sentence or one turn.** Join neighbouring
  sentences in the same mode into one stretch if you like. Split a turn when
  its mode changes, e.g. an English sentence followed by a Hindi one.
- **Every moment of speech gets exactly one label:** stretches never overlap.
  Silence stays unlabelled.
- **Judge by listening and by your transcript, never by the app's tags.**

Export to `data/eval/references/clip01/languages.txt`.

## Step 5 — Summary (`summary.txt`)

3–5 sentences on what the meeting was about and what was decided, written from
your transcript **before** you look at the app's summary. Write it in plain
English, or in Hinglish if that is how you would naturally summarize it; keep
to one choice across all clips.

## Step 6 — Action items (`action_items.txt`)

One line for every commitment someone made in the meeting:

```text
person | task | deadline
```

- **`person`:** who will do it. Use the consent-form id if it was a
  participant, or the name or role as said ("the design team"). Write `-` if
  nobody was named.
- **`task`:** what will be done, in a few words.
- **`deadline`:** as said ("Friday", "kal", "end of month"), or `-` if none.
- **If nobody committed to anything,** write the single word `none`, so an
  empty list is distinguished from "not done yet".

Example:

```text
P02 | finish testing the release | kal
P01 | send the updated build to everyone | Friday
- | book the meeting room | -
```

## Step 7 — Run the check

```powershell
meeting-assistant dataset check clip01
```

```text
clip    length  audio  transcript  turns  languages  summary  actions  meta  2nd
clip01  2:14    ok     ok          ok     ERR        ok       ok       ok    --

clip01
  fix:   languages.txt: two labels overlap at 1:02; each moment has exactly one language label
```

`ok` is done, `--` is not done yet, `ERR` needs fixing. Fix every `fix:` line;
read every `check:` line and fix it if it is a real mistake. Run
`meeting-assistant dataset check` without a clip id to see the whole dataset.

## Step 8 — Second annotator (about 20% of clips)

So that the paper can report how reliable the language labels are, a second
person labels the languages of about one clip in five **independently**. Choose
those clips before labelling starts (for example `clip02`, `clip07`, `clip12`),
not after seeing which were hard.

The first annotator finishes steps 1–7 for the clip. Then:

```powershell
meeting-assistant dataset blind-copy clip02
```

This writes `languages_b.txt`: the same stretches as `languages.txt`, each
labelled `?`. The second annotator:

1. Opens the recording in Audacity, then **File › Import › Labels…**
   `languages_b.txt`.
2. Listens to each stretch and replaces its `?` with `H`, `E` or `M`
   (double-click a label to edit it). **Never moves a label's edges**, and
   **never opens `languages.txt`** or the app's output.
3. **File › Export › Export Labels…** over `languages_b.txt`.
4. Runs `meeting-assistant dataset check`, which now also shows the agreement
   between the two of you (Cohen's kappa).

Do not discuss these clips' labels with each other until both are exported.
After that, disagreements are useful: if they come from an unclear rule, agree
on the rule, add it to the Decisions above, and apply it to every clip. Never
edit either file to make the two agree.

## Worked example

A made-up 10-second exchange between P01 and P02, to show the shape of each
file:

`transcript.txt`
```text
नमस्ते सबको, आज की meeting शुरू करते हैं
let us review the release plan first
release Friday को होगा, testing कल तक
```

`turns.txt` (as Audacity exports it: start, end, label, separated by tabs)
```text
0.000000	3.200000	P01
3.200000	7.500000	P02
7.500000	11.000000	P01
```

`languages.txt`
```text
0.000000	3.200000	M
3.200000	7.500000	E
7.500000	11.000000	M
```

`action_items.txt`
```text
P01 | finish testing | कल
```

`summary.txt`
```text
The team opened the meeting and reviewed the release plan. They agreed the
release goes out on Friday, with testing finished by tomorrow.
```
