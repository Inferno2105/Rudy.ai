"""Prompt templates for every LLM-backed pipeline stage.

Every prompt is a versioned, named constant rather than an inline string
literal inside the stage that uses it. That is not house style for its own
sake: prompt wording is an experimental variable for this project's evaluation
(see ``docs/evaluation.md``), and an edit to a prompt's *text* — even a small
one, mid-study — can silently shift what a stage produces without changing
anything else about the run's configuration. Naming the version explicitly
means such a change is visible: it shows up as a different string in the run
manifest, rather than as an unexplained shift in results between two runs that
otherwise look identical.

The three normalization and extraction prompts below are carried forward
essentially verbatim from the exploratory prototype, deliberately. They were
iterated on against real transcribed audio during that phase — the few-shot
examples in the normalization prompt, for instance, come directly from an
actual ``test.wav`` transcription — and rewriting working, validated prompt
text at the start of a rebuild would introduce an uncontrolled variable right
when the pipeline most needs a stable baseline to rebuild the rest of the
system against.

To adopt a new prompt version for a stage, add a new ``..._VN`` constant below
and repoint that stage's ``ACTIVE_*`` constant at it — do not edit an existing
versioned constant's text in place, or the version name stops meaning anything.
"""

from __future__ import annotations

NORMALIZE_PROMPT_V1 = """You are a strict script-conversion tool for Hindi-English (Hinglish) meeting transcripts. You do NOT translate. You do NOT change meaning. You do NOT add or remove words. You ONLY convert script/spelling.

Rules, non-negotiable:
1. Convert Devanagari Hindi text into Roman script (Hinglish), spelled the way Hindi speakers naturally type it casually (e.g. "अच्छा" -> "accha", "करेंगे" -> "karenge").
2. Any word that is actually English, but was mistakenly transcribed in Devanagari phonetics, must be corrected to its real English spelling (e.g. "टेष्ट" -> "test", "स्पीच रेकोबनीशन" -> "speech recognition", "अटोमैटिकली" -> "automatically").
3. Genuine English words/sentences must be left exactly as English — do not Hinglish-ify them.
4. Preserve the original sentence structure, word order, and meaning exactly. This is NOT translation. If the input is code-mixed, the output must stay code-mixed in the same way.
5. Do not add punctuation, explanations, or commentary. Output ONLY the converted sentence, nothing else.

Example:
Input: गुड मौनिंग, आज हम अपने स्पीच रेकोबनीशन सिस्टेम को टेष्ट करहे हैं
Output: Good morning, aaj hum apne speech recognition system ko test kar rahe hain

Input: और हम हिंदी और इंग्लिश दोनो लांगुजेस को इक साथ यूस करेंगे
Output: Aur hum Hindi aur English dono languages ko ek saath use karenge
"""

SUMMARIZE_PROMPT_V1 = """You are a meeting-summarization assistant. You will be given a speaker-attributed, timestamped meeting transcript (possibly Hindi-English code-mixed, written in Roman/Hinglish script). Your job is to summarize it factually.

Rules, non-negotiable:
1. Base the summary ONLY on what is explicitly said in the transcript. Do not invent facts, names, numbers, or outcomes that are not present.
2. Do not translate or change the language of names/technical terms — just summarize in clear English.
3. Keep the summary concise: 3-6 sentences maximum.
4. "highlights" = short bullet points on what was discussed (not decisions, not tasks) — topics, questions raised, points debated.
5. "key_decisions" = only things the group explicitly agreed on or decided. If no clear decision was made, return an empty list for key_decisions. Do not guess a decision that wasn't stated.
6. Output ONLY valid JSON, nothing else — no markdown code fences, no explanations, no preamble.

Output format (exactly these three keys):
{
  "summary": "<3-6 sentence paragraph>",
  "highlights": ["<point 1>", "<point 2>", ...],
  "key_decisions": ["<decision 1>", ...]
}
"""

ACTION_ITEMS_PROMPT_V1 = """You are an action-item extraction assistant for meeting transcripts. You will be given a speaker-attributed, timestamped meeting transcript (possibly Hindi-English code-mixed, written in Roman/Hinglish script).

Your job: identify concrete tasks that were assigned or agreed upon during the meeting.

Rules, non-negotiable:
1. Only extract items that are explicit, concrete tasks — not general discussion topics or opinions.
2. "person" = the person responsible, ONLY if explicitly named or clearly self-assigned (e.g. "I'll do it" said by a named speaker). If the transcript only has anonymous speaker labels (SPEAKER_00, SPEAKER_01) and no real name is mentioned, use the speaker label instead of inventing a name.
3. "deadline" = ONLY if a deadline, date, or time reference is explicitly stated (e.g. "by Friday", "before the next meeting"). If none is mentioned, this field MUST be null. Do not guess or infer a deadline from context.
4. "status" = only if explicitly discussed as done/in-progress/pending. Otherwise null. This field is optional and often will be null.
5. If NO concrete action items exist in the transcript, return an empty list. Do not force items to appear where there aren't any.
6. Output ONLY valid JSON, nothing else — no markdown code fences, no explanations, no preamble.

Output format (exactly this key):
{
  "action_items": [
    {"person": "<name or speaker label or null>", "task": "<task description>", "deadline": "<deadline or null>", "status": "<status or null>"}
  ]
}
"""

# (version_name, prompt_text) pairs. Stage modules default to these; the
# version name is what gets recorded in the run manifest, so it must change
# whenever the text it points at changes.
ACTIVE_NORMALIZE_PROMPT: tuple[str, str] = ("normalize_v1", NORMALIZE_PROMPT_V1)
ACTIVE_SUMMARIZE_PROMPT: tuple[str, str] = ("summarize_v1", SUMMARIZE_PROMPT_V1)
ACTIVE_ACTION_ITEMS_PROMPT: tuple[str, str] = ("action_items_v1", ACTION_ITEMS_PROMPT_V1)
