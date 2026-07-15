# SKILL · MeloTTS Chinese (Full NPU — App Builder Pack)

> Audience: this file is injected into the system prompt **only** when
> the user has selected the `melotts-zh` Pack in App Builder and starts
> an LLM conversation. It teaches the model how to *interpret*
> MeloTTS-zh output (audio file + alignment), not how to *call* it.
>
> This Pack runs on-device. Both flows are valid: you MAY call
> `appbuilder_run` yourself to verify the model's I/O shape, and the
> user's generated WebUI calls it over the HTTP API — and a Run result
> (audio file + alignment) may already be in the conversation. This file
> teaches you how to *interpret* that output.

---

## 1. What this Pack does

MeloTTS-zh is a Chinese text-to-speech model from myshell-ai's MeloTTS
family, fully ported to Snapdragon X Elite NPU (QNN HTP FP16). The
pipeline runs **four QNN context binaries entirely on the NPU**:

1. **bert_wrapper** — BERT prosody/polyphone predictor
2. **encoder** — text encoder (phoneme embeddings → hidden states)
3. **flow** — normalizing flow (adds expressiveness to latent)
4. **decoder** — T=128 HiFiGAN-class waveform decoder with
   flow_short dual-path optimization

There is no CPU vocoder — all inference is on-device NPU.

**Input:** one text string — primarily Mandarin Chinese, may contain
ASCII digits (auto-spelled-out in Chinese) and incidental English
words (best-effort pronunciation via embedded G2P). Max 500 characters.

**Output:** JSON with `audio_path`, `duration_s`, `sample_rate` (fixed
44100 Hz), and an `alignment[]` array (see schema in §3).

The Pack ships **one voice** (speaker_id=1, female), continuous speed
control 0.5x–2.0x via the `length_scale` parameter. It does **not**
support multiple voices, emotion control, voice cloning, SSML,
multilingual synthesis, English-only input, dialects, or singing —
see §6 for the full limitations list.

**Performance:** ~284 ms for short sentences; ~1018 ms for long
sentences producing ~5.6 s of audio.

---

## 2. Parameters (what the user can tune before Running)

| Param | Type | Default | Meaning |
|-------|------|---------|---------|
| `speed` | number 0.5–2.0, step 0.1 | `1.0` | Controls the duration predictor's `length_scale`. `1.0` is the model's natural pace. `<1.0` slows playback by lengthening each phoneme proportionally. `>1.0` speeds it up by shortening each phoneme. Quality stays usable across the whole 0.5–2.0 range; below 0.6 the audio starts sounding mechanically stretched, above 1.7 some final-syllable consonants get clipped. **Speed scales the alignment timestamps too** — they are always in *output* (post-stretch) seconds. |

There is only one voice (female, speaker_id=1) and one output sample
rate (44100 Hz). These are not user-configurable parameters.

When the user complains "it's reading too fast / too slow", recommend
nudging `speed` by ±0.2 at a time. Don't push past 0.5 or 2.0; the
slider clamps there for quality reasons.

---

## 3. Output JSON Schema (canonical contract)

```jsonc
{
  "audio_path": "data/outputs/<runId>.wav",  // repo-relative path; mono PCM-16
  "duration_s": 5.6,                          // seconds, float
  "sample_rate": 44100,                       // always 44100 Hz
  "alignment": [
    { "text": "今",      "start": 0.000, "end": 0.180 },
    { "text": "天",      "start": 0.180, "end": 0.350 },
    { "text": " ",       "start": 0.350, "end": 0.380 },
    { "text": "八",      "start": 0.380, "end": 0.560 },
    { "text": "点",      "start": 0.560, "end": 0.720 },
    { "text": "三",      "start": 0.720, "end": 0.880 },
    { "text": "十",      "start": 0.880, "end": 1.020 },
    { "text": "分",      "start": 1.020, "end": 1.200 },
    { "text": "，",      "start": 1.200, "end": 1.420 },
    ...
    { "text": "meeting", "start": 2.600, "end": 3.080 },
    ...
  ]
}
```

### 3.1 `audio_path` field

- A repo-relative path string. The backend writes the WAV to
  `data/outputs/<runId>.wav`; the front-end audio player in the App
  Builder UI is the primary playback surface.
- Always mono, always PCM-16, always 44100 Hz.
- Do **not** offer to re-encode it (mp3 / ogg / opus) — this Pack
  only outputs WAV.

### 3.2 `duration_s` field

- Float, seconds. Equals `len(waveform) / 44100` exactly.
- The last alignment entry's `end` should be within ~50 ms of
  `duration_s`.

### 3.3 `sample_rate` field

Always 44100. Fixed — not user-selectable. Echoed in the output so
downstream consumers don't have to read the WAV header.

### 3.4 `alignment[]` array

This enables subtitle / karaoke / word-highlight features downstream.

#### 3.4.1 Tokenization rule

Each entry is one of:
- A single **Chinese character**
- A **punctuation mark** (`，` `。` `？` `！` `；` `：`) representing a
  model-predicted pause (silent)
- An **ASCII space** (~20–40 ms silent)
- A **single English word** kept whole (internal phoneme expansion is
  remapped to word level)
- A **spelled-out digit** — input `8` appears as `"text": "八"` (the
  spoken form)

#### 3.4.2 Time-stamp semantics

- `start` and `end` are in seconds from the start of the audio file,
  in *output* (post-`speed`) time.
- Alignment is sorted by `start` ascending and is non-overlapping.
- Per-character precision is roughly ±20 ms at speed 1.0.
- `start[0]` is typically not exactly 0.0 (50–150 ms warm-up breath).

---

## 4. Chinese frontend rewrites — set user expectations

### 4.1 Number-to-words (`cn2an`)

ASCII digits get spelled out in Chinese:
- `8` → `八`
- `30` in `8 点 30 分` → `三十`
- `2026` → `两千零二十六` or `二零二六` depending on context

### 4.2 Tone sandhi

Applied phonetically (3rd-tone sandhi, `一`/`不` sandhi, neutral-tone
particles). Not visible in alignment but audible in output.

### 4.3 Polyphone disambiguation (BERT-driven)

The bert_wrapper NPU model resolves polyphones in context:
- `重要` → `zhòng yào`, not `chóng yào`
- `银行` → `yín háng`, not `yín xíng`

When BERT is wrong (rare, mainly Internet slang / classical Chinese),
suggest replacing the character with a synonym or inserting a space.

### 4.4 Embedded English words

ASCII letters pass through to a small English G2P (`g2p_en`). Common
words (`meeting`, `email`, `OK`, `iPhone`) sound reasonable; rare
technical jargon may be mispronounced. **MeloTTS-zh is not a bilingual
TTS** — for mostly-English input, suggest a different model.

### 4.5 Length cap

Inputs above 500 characters are rejected. Suggest splitting into
chunks and concatenating WAVs client-side (re-offset alignment
timestamps per chunk).

---

## 5. Typical user requests and how to handle them

### 5.1 "Read this text aloud"

The Run already happened — the WAV is at `audio_path`. Don't pretend
you ran it. The user clicks ▶ in the App Builder UI.

### 5.2 "Make the speed slower / faster"

Suggest `speed=0.8` to slow down or `speed=1.2` to speed up. They
need to **re-Run** — speed is an input parameter, not a playback
control. The model preserves pitch when adjusting speed.

### 5.3 "Export as SRT / VTT subtitles"

Walk `alignment[]` and start a new cue at every punctuation token.
Per-character accuracy is ~20 ms so 3-decimal precision is honest.

### 5.4 "Why does it read 8 as 八?"

Explain number-to-words frontend (§4.1). Alignment shows the spoken
form to keep subtitles in sync with audio.

### 5.5 "I want a different voice / male voice"

**Not available.** This Pack ships one female voice only
(speaker_id=1). State this honestly.

### 5.6 "I want emotion / sad / cheerful tone"

**Not supported.** The single voice has a fixed prosodic prior. Best
the user can do is adjust speed. Do not promise emotion control.

---

## 6. Known limitations (be honest with the user)

- **Single voice only** — one female voice (speaker_id=1). No male
  voice, no voice selection, no voice cloning.
- **No emotion control** — fixed neutral prosodic style.
- **No SSML** — `<break>`, `<emphasis>`, `<phoneme>` tags are not
  supported and will be read literally.
- **Dialects / non-Mandarin Chinese** — Cantonese, Wu, Min, etc. are
  not supported. The model assumes Standard Mandarin (Putonghua).
- **Pure English text** — the embedded G2P is for incidental English
  words only, not a real English TTS.
- **Singing** — TTS only, not singing voice synthesis.
- **Whispering / shouting** — not modeled; fixed loudness range.
- **Emoji / pictographs** — skipped silently.
- **Very short input** (1–2 chars) — works but prosody may sound
  clipped; pad with punctuation.
- **Output is always WAV mono PCM-16 at 44100 Hz** — no MP3 / Opus /
  stereo / alternate sample rates.
- **500-character limit** per Run.

When the user reports "wrong pronunciation", check:
1. Is it a polyphone? (§4.3)
2. Is it a number/digit? (§4.1)
3. Is it an English word at the edge of the G2P? (§4.4)
4. Is it dialect text being read in Mandarin?

---

## 7. Architecture note (full NPU)

All four models run on the Snapdragon X Elite NPU via QNN HTP FP16:

| Model | Role | Notes |
|-------|------|-------|
| bert_wrapper | Prosody + polyphone prediction | Context-aware BERT |
| encoder | Phoneme → latent | Text encoder |
| flow | Latent refinement | Normalizing flow |
| decoder | Latent → waveform (44100 Hz) | T=128, flow_short dual-path |

The T=128 decoder with flow_short dual-path optimization enables
real-time synthesis: ~284 ms for short sentences, ~1018 ms for long
sentences producing ~5.6 s of audio. No CPU fallback vocoder is
needed.

---

## 8. What you (the LLM) should NOT do

- **Do not re-run just to interpret an existing result.** If a Run result is
  already in your context, interpret it rather than re-running. You MAY call
  `appbuilder_run` to verify I/O when building a WebUI, but re-running is the
  user's job.
- **Do NOT MODIFY** these files (developer-maintained). You MAY `read`
  `runner.py` READ-ONLY to understand the model's input/output when
  building a WebUI. Run inference via the HTTP API / the `appbuilder_run`
  tool — do not execute `runner.py` inside the generated app.
- **Do not invent fields** not in the schema. Stick to `audio_path`,
  `duration_s`, `sample_rate`, `alignment[].{text,start,end}`.
- **Do not promise multiple voices, emotion control, dialect support,
  voice cloning, SSML, or English-only TTS** — none of these exist in
  this Pack.
- **Do not rewrite or "improve" the audio.** You can summarize what
  was synthesized, generate subtitles from alignment, or recommend
  re-running with different speed, but you cannot edit the WAV.
- **Do not silently translate the audio's language.** Output is
  Mandarin Chinese. If the user wants English audio, tell them this
  Pack can't do that.
- **Do not promise sub-character timestamp precision.** Alignment is
  per-character (or per-English-word, or per-spelled-out-digit).
- **Do not suggest sample rate changes.** Output is always 44100 Hz;
  there is no 16 kHz / 24 kHz option.

---

## 9. Quick reference — example output

For input `今天 8 点 30 分有个 meeting，请准时参加。` with `speed=1.0`:

```jsonc
{
  "audio_path":  "data/outputs/r-abc123.wav",
  "duration_s":  4.32,
  "sample_rate": 44100,
  "alignment": [
    { "text": "今",       "start": 0.080, "end": 0.260 },
    { "text": "天",       "start": 0.260, "end": 0.420 },
    { "text": " ",        "start": 0.420, "end": 0.450 },
    { "text": "八",       "start": 0.450, "end": 0.640 },
    { "text": "点",       "start": 0.640, "end": 0.810 },
    { "text": "三",       "start": 0.810, "end": 0.970 },
    { "text": "十",       "start": 0.970, "end": 1.120 },
    { "text": "分",       "start": 1.120, "end": 1.310 },
    "...",
    { "text": "meeting",  "start": 1.900, "end": 2.460 },
    { "text": "，",       "start": 2.460, "end": 2.700 },
    "...",
    { "text": "。",       "start": 3.620, "end": 4.320 }
  ]
}
```

Note: digits are spelled out as Chinese; English words stay whole;
punctuation tokens have non-zero spans (model-generated pauses).
