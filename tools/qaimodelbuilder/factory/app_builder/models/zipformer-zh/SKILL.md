# SKILL · Zipformer (Chinese) (App Builder Pack)

> Audience: this file is injected into the system prompt **only** when the
> user has selected the `zipformer-zh` Pack in App Builder and starts an
> LLM conversation (e.g. clicks **Send to Chat** after a Run). It teaches
> the model how to *interpret* zipformer-zh output, not how to *call* it.
>
> This Pack runs on-device. Both flows are valid: you MAY call `appbuilder_run`
> yourself to verify the model's I/O shape, and the user's generated WebUI calls
> it over the HTTP API — and a Run result may already be in the conversation
> (e.g. after **Send to Chat**). This file teaches you how to *interpret* that
> output.

---

## 1. What this Pack does (one-liner)

Zipformer-zh is a streaming RNN-T (Recurrent Neural Network Transducer)
speech recognition model from k2-fsa / sherpa-onnx, specialized for
Mandarin Chinese. It runs on Snapdragon QNN HTP with INT8 quantization
through three QNN binaries: `encoder.bin` (streaming Zipformer encoder),
`decoder.bin` (RNN-T prediction network), and `joiner.bin` (the joiner
that combines encoder embedding × decoder state into a token
distribution). It accepts a single audio clip (WAV or WEBM, mono 16 kHz
internal representation, ≤120 s) and returns a structured JSON document
with the full concatenated text and a list of time-aligned segments.

**Input:** one audio file. Microphone capture is allowed
(`allowMic=true`); the front end records WAV @ 16 kHz mono and uploads
it as if it were a normal file.

**Output:** JSON with `fullText`, `segments[]` (see schema below).

The output language is **always Mandarin Chinese (Simplified)** — there
is no `language` field and no `task` parameter. If the user wants
translation or English output, they should switch to `whisper-base`
(see §6).

---

## 2. Parameters (what the user can tune before Running)

| Param | Type | Default | Meaning |
|-------|------|---------|---------|
| `language` | select `zh` | `zh` | Fixed at `zh`. Present only for forward compatibility (other zipformer variants might add `yue` / `en` later); today this Pack is Mandarin-only and the dropdown has a single option. |
| `vad` | boolean | `true` | When `true`, the runner uses a lightweight voice-activity-detection pass to strip silence and bound memory by chunking long audio at speech boundaries. The streaming RNN-T itself accepts arbitrary-length input, so VAD here is for memory bounds and silence skipping, not for context-window quantization. Turn off only when you know the clip is short and continuous; with `vad=false` very long silences get fed to the encoder and may produce hallucinated tokens. |
| `hotwords` | text (multiline, advanced) | `""` | Newline-separated list of words/phrases to bias the decoder toward. Each line is a single hotword, no quotes, no commas. The decoder will score-boost token sequences that match any hotword, increasing the chance of correct recognition for proper nouns, technical terms, project names, etc. Use sparingly — adding too many hotwords (>50) makes the bias too diffuse. Empty string disables biasing. |

When the user complains "the company / project name comes out wrong",
the standard fix is to add it to `hotwords` and re-Run.

When the user complains "lots of garbage during silent parts of the
clip", check whether `vad=false` was set and suggest re-enabling.

---

## 3. Output JSON Schema (canonical contract)

```jsonc
{
  "fullText": "segment0 text segment1 text ...",
  "segments": [
    {
      "start": 0.00,                    // seconds, from start of input audio
      "end": 3.42,                      // seconds, from start of input audio
      "text": "..."                     // recognized Mandarin text for this segment
    },
    ...
  ]
}
```

### 3.1 No `language` field

Unlike `whisper-base`, this Pack's output has **no** `language`
field — the language is implicitly always Mandarin Chinese
(`zh`, Simplified). Don't invent one. If a downstream consumer needs
a language tag, hard-code `"zh"` based on the Pack identity, not based
on a non-existent output field.

### 3.2 No `task` field

There is no `task` parameter and no `task` field in the output.
Zipformer-zh **only transcribes** — it cannot translate. If the user
wants translation, they need `whisper-base` with `task=translate` (see §6).

### 3.3 No `conf` field — and why

This is the most-likely-to-trip-up-LLMs difference vs. whisper-base.

Whisper's decoder is a softmax-over-vocabulary autoregressive language
model, so its per-token log-probabilities can be averaged into an
approximate per-segment confidence (whisper-base ships that as `conf`).

RNN-T with **greedy** decoding (which this Pack uses) does **not**
expose comparable per-token probabilities in a meaningful way:

- The joiner emits a softmax over `vocab + {blank}`, but the per-frame
  decision is "did I emit a non-blank token here", not "how sure am I
  about this token". Most frames emit blank.
- Aggregating the non-blank-frame probabilities across a segment
  produces a number that tracks **frame rate / blank ratio** more than
  recognition correctness. Reporting it as a `conf` field would
  mislead downstream consumers into thresholding on it.
- A calibrated RNN-T confidence requires an extra "confidence
  estimation module" (CEM) head, which this model does not include.

**Operational consequence for the LLM:** do **not** speculate about
per-segment confidence, do **not** invent a `conf` field when emitting
SRT or markdown, and do **not** suggest the user "filter low-confidence
segments" — that filter doesn't exist here. If the user asks "how
confident is the model?", answer honestly: this model's output does
not include per-segment confidence. To detect probable errors, the
user can re-Run with `vad=true` (already default), check whether the
audio segment in question is intelligible by ear, or cross-check with
`whisper-base` which does provide `conf`.

### 3.4 `segments[]` time-stamp precision

Zipformer streaming RNN-T emits per-frame decisions on a 40 ms grid
(downsampled from the 10 ms frame shift through the encoder
subsampler). The runner converts emission frames to absolute seconds:

- `start` and `end` are **absolute seconds from the start of the
  input audio**, not relative to a chunk. The runner has already
  added the per-chunk offset.
- A "segment" boundary is heuristic: silence ≥ ~0.5 s OR a sentence-
  final punctuation token (when the model emits one). Typical segment
  duration is 1–8 s.
- `segments[]` is sorted by `start` ascending and is non-overlapping.
- Real-world end-to-end timestamp accuracy is **±0.2–0.4 s** —
  better than whisper-base on the chunk-boundary axis (no 30 s
  encoder window) but worse on absolute frame alignment (40 ms grid
  vs. whisper's 20 ms grid).

For SRT / VTT output, round `start` and `end` to the nearest 100 ms
and emit:

```
1
00:00:00,000 --> 00:00:03,400
First segment text

2
00:00:03,400 --> 00:00:07,200
Second segment text
```

Do **not** trust millisecond precision in the `,XXX` slot — round to
3 decimals only because SRT requires that format, not because the
model is that accurate.

### 3.5 `text` field — Chinese-specific notes

- Always Mandarin Chinese, **Simplified** characters. The model is
  trained on Simplified-character corpora; Traditional characters do
  not appear in the output even if the speaker uses Taiwanese
  Mandarin pronunciation.
- Punctuation: full-width Chinese punctuation (`，` `。` `？` `！`
  `：` `；`). The model emits punctuation tokens during decoding —
  this is **not** a separate post-processing step. Quality is OK but
  not human-level; expect occasional missing periods at segment ends.
- No spaces between Chinese characters.
- For **code-switched audio** (Chinese with English technical terms
  like "今天我们用 React"), the English words get **transliterated
  into Chinese characters** ("锐艾克特" or similar phonetic mush) or
  occasionally output as best-guess Pinyin characters. This is the
  model's #1 known weakness — see §5 and §6. Suggest `whisper-base`
  for any clip with non-trivial English content.
- Numbers: typically transcribed as Chinese-character numerals
  (`三百二十`) for spoken-out numbers, Arabic numerals (`320`) for
  digit-by-digit reads. Inconsistent — don't rely on either form.
- Empty segments (`text == ""`) are filtered by the runner.

### 3.6 `fullText` field

All segment `text`s concatenated with **a single space** between
adjacent segments (not `\n`, not empty). The single-space separator is
preserved even though Chinese itself doesn't use spaces, so downstream
tools can split on whitespace if they want segment-level chunks back.
For prose output, replace the space with empty string when quoting
back to a Chinese-reading user; for time-aligned use cases iterate
`segments[]` instead.

---

## 4. Typical user requests and how to handle them

### 4.1 "Summarize the transcript"

1. Read `fullText` for the prose content. Output the summary in
   **Chinese** unless the user explicitly asks for another language —
   the source language is Chinese, default behavior is to match.
2. Use `segments[]` time anchors to spot **topic shifts**: long
   pauses (`segments[i+1].start − segments[i].end > 5 s`) are good
   section-break candidates.
3. Structure the summary as:
   - **Key topics** — bullet list of the main subjects
     covered, each with a `[mm:ss]` timestamp from the segment it
     came from.
   - **Decisions** — anything the speakers explicitly agreed
     on or committed to (look for cues like `决定`, `同意`, `就这么定`,
     `下周之前`).
   - **Open items** — unresolved questions (cues:
     `回头讨论`, `再说`, `等确认`, `??`).
4. Quote each bullet with the original text + timestamp, so the user
   can verify against the audio.
5. **Do NOT add speaker labels** — zipformer-zh does not do speaker
   diarization. State this honestly if the user asks "who said X".

### 4.2 "Output as SRT subtitles"

Walk `segments[]` and emit the standard format from §3.4. Notes:

- For **SRT**, sequential 1-based index lines, `,` time separator
  (`00:00:00,000 --> 00:00:03,400`).
- For **VTT**, use `.` separator and a `WEBVTT` header line.
- Long segments (>7 s) are uncomfortable to read on a single subtitle
  cue. If the user asks for "broadcast-quality" subtitles, mention
  that you can heuristically split long Chinese segments at
  `。` / `？` / `！` boundaries, but the timestamps for the split
  pieces will then be **estimated** (linear interpolation on character
  count), not model-emitted.
- The output is always Mandarin Chinese — make sure the user knows
  this if they expected English subtitles. Suggest re-Running with
  `whisper-base` + `task=translate` if they wanted English.

### 4.3 "Translate the same audio with Whisper"

- This is a **redirect** request. The user wants to:
  1. Switch the selected Pack from `zipformer-zh` to `whisper-base`.
  2. Re-Run with the same audio and `task=translate`.
- You (the LLM) **cannot translate the Chinese transcript yourself**
  to fulfill this request — well, you technically can produce
  English text, but the user explicitly asked for Whisper's
  translation, which is jointly trained with the audio embeddings
  and is generally higher quality than a transcribe-then-translate
  pipeline (especially for proper nouns).
- Tell the user how to switch:
  > To have Whisper translate this audio directly into English, go to the
  > App Builder model selector and switch the model from `zipformer-zh` to
  > `whisper-base`, then set the `task` parameter to `translate` and click
  > Run. The same audio will produce an English translation plus
  > time-stamped segments.
- If the user just wants a rough English version *now* and doesn't
  want to re-Run, you may translate `fullText` yourself, but **flag
  it as a downstream LLM translation, not Whisper's native
  translation**, and mention the quality caveat.

### 4.4 "Find the key decisions"

- Search `segments[]` for Chinese decision-language cues:
  `决定`, `同意`, `我们就`, `下周之前`, `负责`, `跟进`, `定了`,
  `没问题`, `就这样`, `OK`/`ok` (the model often transliterates this
  but sometimes preserves it).
- For each match, return `[mm:ss] text` (format `start` as
  `MM:SS` for clips <1 h, else `HH:MM:SS`).
- Group by topic if there are >5 matches; otherwise flat list.
- Always quote `text` verbatim — do not paraphrase. The user wants
  a verifiable audio pointer.

### 4.5 "Add hotwords and re-Run"

- The user wants better recognition for specific names / terms.
- Tell them to:
  1. In the App Builder params panel, expand "Advanced".
  2. Add each hotword on its own line in the `hotwords` text field.
     One word/phrase per line, no quotes, no commas. Example:
     ```
     高通骁龙
     React.js
     张三
     XP-pen
     ```
  3. Re-Run.
- Caveat: hotwords work best for proper nouns / technical terms
  that the base model would otherwise mis-recognize. Don't bias
  on common words (`你好`, `谢谢`) — that hurts more than it helps.
- Also mention the upper bound: ~50 hotwords is a soft cap; beyond
  that the bias becomes too diffuse and quality degrades.

---

## 5. Known limitations (be honest with the user)

Zipformer-zh is specialized for clean Mandarin. Quality drops on:

- **Non-Mandarin languages** — English, Japanese, Korean, Cantonese
  proper. The model has no training data for these and produces
  Chinese-character mush. **Switch to `whisper-base`.**
- **Heavy code-switching (zh+en)** — Chinese with frequent English
  technical terms is the most common real-world failure. The English
  words get transliterated into phonetic Chinese (`锐艾克特` for
  "React") or replaced with similar-sounding common Chinese words.
  **Switch to `whisper-base` with `language=auto`** for any clip
  with >10% English content.
- **Strong regional accents / dialects** — Cantonese, Min, Hakka,
  Wu (Shanghainese), heavy Sichuan / northeastern accents. Light
  Putonghua-flavored regional accents are usually OK; full dialect
  is not. The `mandarin-light-accent.wav` example covers the
  acceptable end of the spectrum.
- **Noisy / far-field audio** — heavy background music, simultaneous
  speakers, distance >2 m from the mic. Common failure modes:
  hallucinated tokens during noise, dropped segments, repetition.
  Suggest the user re-record closer to the mic or run a denoiser
  first.
- **Singing / music with lyrics** — possible but unreliable.
- **Very long audio (>120 s)** — the input schema caps at 120 s.
  For longer clips, suggest splitting client-side before uploading;
  running this Pack repeatedly on chunks then concatenating
  `fullText` works but timestamps reset per chunk and the user must
  re-offset them.
- **Speaker identification / diarization** — **not supported.** The
  output has no `speaker` field. If the user asks "who said X", say
  honestly that this Pack can't tell you. (Whisper-base also can't.)
- **Word-level timestamps** — **not supported.** Only segment-level.
- **Per-segment confidence** — **not supported.** See §3.3.

When the user reports "wrong text", check the segment's duration and
ask whether the corresponding audio is clean Mandarin. Very short
segments (<1 s) and any segment with non-Chinese content are the
usual suspects.

---

## 6. Zipformer-zh vs. whisper-base — when to redirect

This Pack and `whisper-base` overlap for Chinese audio. Brief
comparison (mirror of the table in `whisper-base/SKILL.md`):

| Dimension | `zipformer-zh` | `whisper-base` |
|-----------|-----------------|----------------|
| Languages | Mandarin Chinese only | ~99 (multilingual) |
| Translate-to-English | ❌ | ✅ via `task=translate` |
| Speed | ~3 s for 30 s audio | ~6 s for 30 s audio (HTP, beam=5) |
| Quality on clean Mandarin | Slightly better, plus better with hotwords | Good |
| Quality on code-switched zh+en | Poor (English words butchered) | OK (multilingual) |
| Hotword bias | ✅ via `hotwords` param | ❌ |
| Per-segment confidence (`conf`) | ❌ | ✅ |
| Long-audio support | Same (≤120 s; VAD chunking) | Same |

Redirect logic when the user is *currently on this Pack* but the
question implies they need different behavior:

- "Translate to English" / any non-Chinese output
  language → **redirect to `whisper-base`** with `task=translate`.
  Offer the exact switch instructions (see §4.3).
- "this audio has a lot of English" / clip is code-switched →
  **redirect to `whisper-base`**. Don't try to fix the
  transliterated English in zipformer-zh's output — it's lossy.
- "I need a confidence score per segment" → **redirect to
  `whisper-base`** (only it has `conf`). Or accept that zipformer-zh
  doesn't expose one (see §3.3).
- "I need it to handle Cantonese / Japanese / English" → **redirect
  to `whisper-base`**.
- User has **domain hotwords** (technical terms, names) and the audio
  is **clean Mandarin** → **stay on zipformer-zh** and use the
  `hotwords` param. This is zipformer-zh's strength.
- Speed-critical and **clean Mandarin only** → **stay on
  zipformer-zh**. This is also where it shines.

Don't volunteer this comparison unless the user is choosing between
the two or has hit a clear limitation; just answering "the
recognition didn't work because the audio was English, switch to
Whisper" is fine when the question doesn't come up.

---

## 7. What you (the LLM) should NOT do

- **Do not re-run just to interpret an existing result.** If a Run result is
  already in your context, interpret it rather than re-running. You MAY call
  `appbuilder_run` to verify I/O when building a WebUI, but re-running with
  changed params is the user's job (they click Run again).
- **Do NOT MODIFY** these files (developer-maintained). You MAY `read`
  `runner.py` READ-ONLY to understand the model's input/output when
  building a WebUI. Run inference via the HTTP API / the `appbuilder_run`
  tool — do not execute `runner.py` inside the generated app.
- ❌ **Do not invent fields** that aren't in the schema. The output
  has only `fullText` and `segments[].{start, end, text}`. There is
  **no** `conf`, **no** `language`, **no** `task`, **no** `speaker`,
  **no** `words`. Stick to the schema or you'll cause downstream
  tools to break.
- ❌ **Do not "fix" the recognized text** silently. If the transcript
  says "我们用锐艾克特" and you suspect the user actually said
  "我们用 React", you may **suggest** the correction but must flag
  it as a guess and quote the original `text` + `[start–end]`
  timestamp so the user can verify against the audio. The "right"
  fix is usually to redirect to `whisper-base` (see §6).
- ❌ **Do not promise word-level timestamps, speaker labels, or
  per-segment confidence** — they are not in the output, and lying
  about them will cause the user to build broken downstream tools.
- ❌ **Do not pretend zipformer-zh can translate.** It can't. If the
  user wants translation, redirect to `whisper-base` with
  `task=translate`.

---

## 8. Quick reference — example output

For a 30 s clean Mandarin clip (`mandarin-reading.wav` style),
`vad=true`, `hotwords=""`:

```json
{
  "fullText": "今天的天气非常好。 我们去公园散步吧。 顺便买点水果回来。",
  "segments": [
    { "start": 0.00,  "end": 3.40,  "text": "今天的天气非常好。" },
    { "start": 3.40,  "end": 7.20,  "text": "我们去公园散步吧。" },
    { "start": 7.20,  "end": 11.60, "text": "顺便买点水果回来。" }
  ]
}
```

Same audio shape but with hotwords used (e.g. user added `骁龙` and
`高通` to the `hotwords` text field, audio is a tech-talk clip):

```json
{
  "fullText": "高通骁龙处理器在端侧大模型上有优势。 这是因为 NPU 的能效比很高。",
  "segments": [
    { "start": 0.00, "end": 4.20, "text": "高通骁龙处理器在端侧大模型上有优势。" },
    { "start": 4.20, "end": 8.10, "text": "这是因为 NPU 的能效比很高。" }
  ]
}
```

Note: no `language` field, no `task` field, no `conf` field on the
segments. That's by design — see §3.1, §3.2, §3.3 above.

If you ever see one of those fields in a Run result, it's NOT from
this Pack — likely the user pasted output from `whisper-base` into
the conversation. Read the Pack identity from the Run metadata
header, not from inferring based on output shape.
