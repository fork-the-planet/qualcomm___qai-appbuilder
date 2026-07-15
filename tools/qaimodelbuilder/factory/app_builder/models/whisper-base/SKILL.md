# SKILL · Whisper Base (App Builder Pack)

> Audience: this file is injected into the system prompt **only** when the
> user has selected the `whisper-base` Pack in App Builder and starts an
> LLM conversation (e.g. clicks **Send to Chat** after a Run). It teaches
> the model how to *interpret* Whisper-base output, not how to *call* it.
>
> This Pack runs on-device. Both flows are valid: you MAY call `appbuilder_run`
> yourself to verify the model's I/O shape, and the user's generated WebUI calls
> it over the HTTP API — and a Run result may already be in the conversation
> (e.g. after **Send to Chat**). This file teaches you how to *interpret* that
> output.

---

## 1. What this Pack does (one-liner)

Whisper-base is a 74 M-parameter encoder/decoder speech recognition
model from OpenAI, running on Snapdragon QNN HTP with INT8 quantization.
It accepts a single audio clip (WAV/MP3/FLAC/WEBM, mono 16 kHz internal
representation, ≤120 s) and returns a structured JSON document with the
detected language, the requested task (transcribe or translate), the
full concatenated text, and a list of time-aligned segments.

**Input:** one audio file. Microphone capture is allowed
(`allowMic=true`); the front end records WAV @ 16 kHz mono and uploads
it as if it were a normal file.

**Output:** JSON with `language`, `task`, `fullText`,
`segments[]` (see schema below).

It supports two operating modes via the `task` parameter:

- `transcribe` (default) — produce text in the **source** language. The
  model internally detects the language (or uses `params.language` if
  the user forced it) and emits text in that language. A Chinese clip
  becomes Chinese text, an English clip becomes English text.
- `translate` — produce **English** text regardless of the source
  language. This is **one-way**: Whisper can translate any of its
  ~99 supported languages **to English only**. Translation in the
  other direction (English → Chinese, Chinese → Japanese, etc.) is
  not supported by this model and the user must use a separate
  text-translation step downstream.

---

## 2. Parameters (what the user can tune before Running)

| Param | Type | Default | Meaning |
|-------|------|---------|---------|
| `language` | select `auto` / `zh` / `en` / `ja` / `ko` / `fr` / `de` / `es` / `ru` | `auto` | Forces the source language. `auto` lets Whisper's built-in language-ID head pick — best for unknown clips, but can mis-fire on very short / noisy audio. Force a specific language when you know it; this skips LID and is slightly faster + more reliable, especially for `task=translate`. |
| `task` | select `transcribe` / `translate` | `transcribe` | See §1. `translate` only goes **to English**. For an English audio clip, `translate` is effectively a no-op (you get English back). |
| `vad` | boolean | `true` | When `true`, the runner first uses a lightweight voice-activity-detection pass to split long audio into ≤30 s speech windows (Whisper's encoder has a fixed 30 s context) and skips silence. Turn off only when you know the clip is ≤30 s and contains continuous speech — saves a small amount of preprocessing time. For audio ≥30 s, leaving VAD on is essentially mandatory; with `vad=false` only the first 30 s is transcribed. |
| `beam_size` | number 1–10 | `5` | Decoder beam width. **Lower** (e.g. `1` = greedy) is faster but more prone to hallucinations / repetition loops on noisy audio. **Higher** (e.g. `8`–`10`) reduces hallucinations and slightly improves WER but is roughly linearly slower. `5` is the standard Whisper default and a good general-purpose choice. Advanced. |

When the user complains "transcript repeats the same phrase forever",
the most likely fix is `beam_size ↑` to `8`–`10` — repetition loops
are a classic greedy-decode failure mode.

When the user complains "result is in the wrong language", check
whether `language=auto` mis-detected (especially on clips <5 s or with
heavy background music) and suggest forcing `language=<actual lang>`.

---

## 3. Output JSON Schema (canonical contract)

```jsonc
{
  "language": "zh",                     // ISO 639-1 code of the source audio
  "task": "transcribe" | "translate",   // mirrors params.task
  "fullText": "segment0 text segment1 text ...",
  "segments": [
    {
      "start": 0.00,                    // seconds, from start of input audio
      "end": 3.42,                      // seconds, from start of input audio
      "text": "...",                    // recognized / translated text for this segment
      "conf": 0.91                      // average decoder log-prob mapped to [0,1]
    },
    ...
  ]
}
```

### 3.1 `language` field

- A 2-letter ISO 639-1 code (`zh`, `en`, `ja`, `ko`, `fr`, `de`, `es`,
  `ru`, …). For Mandarin Chinese specifically it is `zh` (Whisper does
  not distinguish `zh-CN` / `zh-TW` here).
- When `params.language != "auto"`, this field always equals
  `params.language`. When `params.language == "auto"`, it reflects
  Whisper's LID prediction — a single guess for the **whole** clip,
  not per-segment. For code-switched audio (e.g. Chinese with English
  technical terms) this is the **dominant** language; the segment
  texts may still contain words from the other language.
- Don't use this field to gate downstream logic that requires hard
  guarantees — treat it as a hint.

### 3.2 `task` field

Always equals `params.task`. Included in the output explicitly so
downstream consumers can branch without re-reading the request.

### 3.3 `segments[]` time-stamp precision

Whisper segment timestamps are **second-level**, not frame-level.
Concretely:

- The decoder emits timestamp tokens at a 20 ms grid, but the typical
  end-to-end accuracy is closer to **±0.3–0.5 s** because of:
  - 30 s encoder window quantization (segments near a window boundary
    can shift by up to ±0.5 s after stitching).
  - VAD chunk boundaries (when `vad=true`), which snap to silence
    detection rather than to actual word edges.
  - Decoder hallucinations on noisy audio that produce monotonically
    incorrect timestamp drift inside a single chunk.
- `start` and `end` are always **absolute seconds from the start of
  the input audio**, not relative to a chunk. The runner has already
  added the per-chunk offset.
- `segments[]` is sorted by `start` ascending and is **non-
  overlapping** in normal cases. Tiny overlaps (<50 ms) at chunk
  boundaries are possible after stitching — clip them client-side if
  you need strict non-overlap.
- A typical segment is 2–10 s of audio. Whisper does not produce
  per-word timestamps in this Pack — if the user asks for word-level
  alignment, explain that they'd need a forced-aligner pass (e.g.
  WhisperX) on top, which this Pack does not include.

For SRT / VTT output, round `start` and `end` to the nearest 100 ms
and emit:

```
1
00:00:00,000 --> 00:00:03,420
First segment text

2
00:00:03,420 --> 00:00:07,800
Second segment text
```

Do **not** trust millisecond precision in the `,XXX` slot — round to
3 decimals only because SRT requires that format, not because the
model is that accurate.

### 3.4 `text` field — language and content notes

- For `task=transcribe`, `text` is in the **source** language as
  reported by `language`. Punctuation and casing are model-generated
  and follow Whisper's house style:
  - Chinese: full-width punctuation (`，` `。` `？` `！`), no spaces
    between characters.
  - English: standard ASCII punctuation, sentence-cased.
  - Japanese: mixed kana / kanji as the model produces them; no
    spaces.
- For `task=translate`, `text` is **English** regardless of `language`,
  with standard English punctuation.
- Whisper occasionally inserts non-speech annotations like
  `[Music]`, `(applause)`, `(笑い)` — these are real model outputs,
  not injected by the runner. Strip them with a regex if you want
  pure speech text.
- Empty segments (`text == ""`) are filtered by the runner; you
  shouldn't see them.

### 3.5 `conf` field

- Range: `[0, 1]`. Computed as `exp(avg_logprob)` clipped to that
  range, then averaged over the segment's tokens.
- Typical "good" reads land at `0.85`–`0.97`. Below `0.6` the segment
  is often a hallucination on silence / music / unclear speech.
- This is **not** a calibrated probability and should not be
  compared across audio clips of different SNR — use it as a
  **relative** quality signal within a single Run.

### 3.6 `fullText` field

All segment `text`s concatenated with **a single space** between
adjacent segments (not `\n`). For prose output this is what you'd
quote back to the user; for time-aligned use cases iterate
`segments[]` instead.

---

## 4. Typical user requests and how to handle them

### 4.1 "Turn this into a meeting summary"

1. Read `fullText` for the prose content. Use `language` to decide
   the summary language (default to matching the source unless the
   user said otherwise).
2. Use `segments[]` time anchors to spot **topic shifts**: long
   pauses (`segments[i+1].start − segments[i].end > 5 s`) are good
   section-break candidates.
3. Structure the summary as:
   - **Participants** — Whisper does NOT do speaker diarization
     here. State this honestly: "I can identify topics and timestamps
     but not who spoke." If the user needs speaker labels, suggest a
     separate diarization pass.
   - **Key points** — bullet list of decisions / action items,
     each one quoted with a `[mm:ss]` timestamp from the segment it
     came from.
   - **Open questions** — anything the participants explicitly said
     was unresolved (look for "??", "TBD", "回头讨论", etc.).
4. Keep the original language unless asked otherwise — don't
   translate Chinese minutes to English by default just because you
   (the LLM) are more fluent in English.

### 4.2 "Output as SRT / VTT subtitles"

Walk `segments[]` and emit the standard format from §3.3. Notes:

- For **VTT**, the time-stamp separator is `.` not `,`:
  `00:00:00.000 --> 00:00:03.420`. Header line: `WEBVTT`.
- For **SRT**, sequential 1-based index lines and `,` separator.
- If `task == "translate"`, the subtitle language is **English** even
  if `language` is `zh` / `ja` — make sure the user knows that.
- Long segments (>7 s) are uncomfortable to read on a single subtitle
  cue; if the user asks for "broadcast-quality" subtitles, mention
  that you can heuristically split long segments at sentence
  boundaries (`。` / `.` / `!` / `?`) but the timestamps will then
  be **estimated** (linear interpolation), not model-emitted.

### 4.3 "Find the key decision points"

- Search `segments[]` for decision-language cues:
  - en: `decide(d)`, `agree(d)`, `we'll`, `let's`, `action item`,
    `commit to`, `by Friday`, etc.
  - zh: `决定`, `同意`, `我们就`, `下周之前`, `负责`, `跟进`, etc.
- For each match, return `[mm:ss] text` (format `start` as
  `HH:MM:SS` for clips ≥1 h, else `MM:SS`).
- Group by topic if there are >5 matches; otherwise list flat.
- Always quote the `text` verbatim — do not paraphrase the decision,
  the user wants a verifiable timestamp pointer.

### 4.4 "Translate this audio to English" (when source is non-English)

- If the original Run was `task=transcribe`, you have source-language
  text in `fullText`. Translating that text downstream is fine for
  many use cases.
- However, for highest quality, suggest the user **re-Run** with
  `task=translate` — Whisper's native translation path is jointly
  trained with the audio embeddings and often beats a two-step
  (transcribe → text-translate) pipeline, especially for proper
  nouns and idioms.
- If the source is already English (`language == "en"`), don't
  re-Run; just point that out.

### 4.5 "Translate this audio to Japanese / Chinese / German"

- Whisper-base supports translate-to-English **only**. State this
  clearly. Suggested workflow:
  1. Run with `task=translate` to get English text, **or**
  2. Run with `task=transcribe` to get source-language text.
  3. Pipe either result through a separate text-translation tool
     (the user's choice — this Pack doesn't ship one).
- Don't pretend you can do `task=translate` to a non-English target
  by post-processing — that would silently drop quality.

---

## 5. Known limitations (be honest with the user)

Whisper-base is a small (74 M params) general-purpose model. Quality
drops on:

- **Noisy / far-field audio** — heavy background music, simultaneous
  speakers, distance >2 m from the mic. Common failure modes:
  hallucinated text on silence segments, repetition loops, and wrong-
  language LID. Suggest the user re-record closer to the mic or run
  a denoiser first.
- **Very long audio (>120 s)** — the input schema caps at 120 s. For
  longer clips, suggest splitting client-side (or using an external
  VAD+chunking script) before uploading; running this Pack repeatedly
  on chunks then concatenating `fullText` works but timestamps reset
  per chunk and the user must re-offset them.
- **Heavy code-switching** — Whisper handles single-language audio
  well; clips that switch language every few seconds confuse the LID
  head. Force `language=<dominant>` for better results, but expect
  some words in the other language to be transliterated rather than
  preserved.
- **Specialized vocabulary** — medical, legal, very technical jargon
  (e.g. esoteric chemistry names, internal product code-names) is
  poorly covered. Whisper-base in particular (vs. the larger Whisper
  variants) is more prone to "guessing" a phonetically similar
  common word. Cross-check `conf` for suspicious lines.
- **Speaker identification / diarization** — **not supported.** The
  output has no `speaker` field. If the user asks "who said X", say
  honestly that this Pack can't tell you.
- **Word-level timestamps** — **not supported.** Only segment-level.
- **Singing / music with lyrics** — possible but unreliable; treat
  the result as best-effort.
- **Languages outside the 99 Whisper supports** — the model will
  fall back to a related language (often English) and produce
  garbage. The `params.language` enum is intentionally limited to
  the most-common 8 languages plus `auto` for this Pack; for less
  common languages, the underlying model may still work via
  `auto` but it's not a tested path here.

When the user reports "wrong text", check `conf` and the segment's
duration: very short segments (<1 s) and conf <0.6 are the usual
suspects.

---

## 6. Whisper-base vs. zipformer-zh — when to recommend which

This Pack and `zipformer-zh` (the other ASR Pack) overlap for Chinese
audio. Brief comparison:

| Dimension | `whisper-base` | `zipformer-zh` |
|-----------|----------------|-----------------|
| Languages | ~99 (multilingual) | Mandarin Chinese only |
| Translate-to-English | ✅ via `task=translate` | ❌ |
| Speed | ~6 s for 30 s audio (HTP, beam=5) | ~3 s for 30 s audio |
| Quality on clean Mandarin | Good | Slightly better, plus better with hotwords |
| Quality on code-switched zh+en | OK (multilingual) | Poor (English words butchered) |
| Hotword bias | ❌ | ✅ |
| Long-audio support | Same (VAD chunking ≤120 s) | Same |

Recommendation logic when the user asks "which should I use":

- Audio is **clean Mandarin only** + speed matters → **zipformer-zh**.
- Audio contains **non-Chinese languages** at any point → **whisper-base**.
- User wants the result in **English** (translation) → **whisper-base**
  with `task=translate`.
- User has **domain hotwords** (technical terms, names) →
  **zipformer-zh** with the `hotwords` parameter.
- Unsure → **whisper-base** (safer default for unknown audio).

Don't volunteer this comparison unless the user is choosing between
the two; just answering "use whisper-base because that's what's
selected" is fine when the question doesn't come up.

---

## 7. What you (the LLM) should NOT do

- **Do not re-run just to interpret an existing result.** If a Run result is
  already in your context, interpret it rather than re-running. You MAY call
  `appbuilder_run` to verify I/O when building a WebUI, but re-running to change
  parameters is the user's job (they click Run again).
- **Do NOT MODIFY** these files (developer-maintained). You MAY `read`
  `runner.py` READ-ONLY to understand the model's input/output when
  building a WebUI. Run inference via the HTTP API / the `appbuilder_run`
  tool — do not execute `runner.py` inside the generated app.
- ❌ **Do not invent fields** that aren't in the schema (no
  `speaker`, no `words`, no `confidence_avg`, no `language_per_segment`).
  Stick to `language`, `task`, `fullText`, `segments[].{start,end,text,conf}`.
- ❌ **Do not "fix" the recognized text** silently. If the transcript
  says "我们用 React" and you suspect the user actually said
  "我们用 react.js", you may **suggest** the correction but you must
  flag it as a guess and quote the original `text` + `[start–end]`
  timestamp so the user can verify against the audio.
- ❌ **Do not promise word-level timestamps or speaker labels** — they
  are not in the output, and lying about them will cause the user to
  build broken downstream tools.
- ❌ **Do not translate when the user only asked for transcription**,
  and vice versa. The `task` field tells you which one happened — if
  the user wants the other behavior, tell them to re-Run with the
  flipped `task` parameter (don't try to translate post-hoc unless
  they explicitly ask, and even then prefer suggesting the re-Run for
  better quality).

---

## 8. Quick reference — example output

For a 30 s Chinese news clip, `task=transcribe`, `language=auto`:

```json
{
  "language": "zh",
  "task": "transcribe",
  "fullText": "今天的天气非常好。 我们去公园散步吧。 顺便买点水果回来。",
  "segments": [
    { "start": 0.00,  "end": 3.42,  "text": "今天的天气非常好。",       "conf": 0.94 },
    { "start": 3.42,  "end": 7.80,  "text": "我们去公园散步吧。",       "conf": 0.91 },
    { "start": 7.80,  "end": 12.10, "text": "顺便买点水果回来。",       "conf": 0.89 }
  ]
}
```

Same audio with `task=translate`:

```json
{
  "language": "zh",
  "task": "translate",
  "fullText": "The weather is great today. Let's go for a walk in the park. We can pick up some fruit on the way back.",
  "segments": [
    { "start": 0.00,  "end": 3.42,  "text": "The weather is great today.",                       "conf": 0.92 },
    { "start": 3.42,  "end": 7.80,  "text": "Let's go for a walk in the park.",                  "conf": 0.90 },
    { "start": 7.80,  "end": 12.10, "text": "We can pick up some fruit on the way back.",        "conf": 0.88 }
  ]
}
```

Note that `language` stays `zh` even in the `translate` case — it
describes the **source** audio, not the output text. The output
language is implied by `task`: `transcribe` ⇒ source language,
`translate` ⇒ English.
