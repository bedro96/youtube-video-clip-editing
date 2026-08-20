---
name: youtube-video-clip-editing
description: End-to-end 8-stage pipeline that registers a run in MEMORY.md, downloads a YouTube clip with Edge cookies, transcribes English audio, corrects Microsoft/Azure/GitHub product-name spellings, translates to Korean, QAs the Korean for mistranslated product names and 높임말 speech level, wraps every cue to 2 lines max, burns the subtitles in at FontSize 24, and brackets the result with a Microsoft-logo intro/outro bumper. Intermediates live under work/NNN/ (per-run subfolder). Orchestrates four sibling skills (youtube-downloader, wjs-transcribing-audio, wjs-translating-subtitles, wjs-burning-subtitles) plus MEMORY.md registration, product-name review, Korean translation QA, subtitle wrapping, and FFmpeg normalization/concatenation into outcome/final_outputNNN.mp4. Use when the user asks to "download a YouTube clip and add Korean subtitles", "make a localized clip with our Microsoft intro/outro", or similar multi-step video-localization + branding requests.
metadata:
  tags:
    - video
    - youtube
    - subtitles
    - korean
    - localization
    - ffmpeg
    - branding
  pairs-with:
    - skill: youtube-downloader
      reason: Step 2 — fetches the source clip from YouTube into work/NNN/sourceNNN.mp4
    - skill: wjs-transcribing-audio
      reason: Step 3 — produces the source-language SRT at work/NNN/sourceNNN.en.raw.srt
    - skill: wjs-translating-subtitles
      reason: Step 5 — translates the corrected English SRT to Korean at work/NNN/sourceNNN.ko.srt
    - skill: wjs-burning-subtitles
      reason: Step 7 — burns the wrapped Korean SRT into work/NNN/sourceNNN.subtitled.mp4
    - skill: video-processing-editing
      reason: Step 8 — normalizes and concatenates intro, main, and outro into outcome/final_outputNNN.mp4
---

# YouTube Video Clip Editing (Register → Download → Term-Review → Korean Subs → QA → Microsoft Bumper)

## Overview

This skill turns a YouTube URL or local video file into a branded, Korean-subtitled deliverable. It allocates a run id, produces `sourceNNN.*` intermediates inside a **per-run `work/NNN/` subfolder**, and writes the finished clip to `outcome/final_outputNNN.mp4`.

```
YouTube URL (or local file path)
  → (1) register-run in /MEMORY.md   → allocates NNN, logs "NNN - <origin>"
  → (2) youtube-downloader           → work/NNN/sourceNNN.mp4
  → (3) wjs-transcribing-audio       → work/NNN/sourceNNN.en.raw.srt
  → (4) product-name review          → work/NNN/sourceNNN.en.srt
        (Microsoft / Azure / GitHub / Copilot / .NET / VS Code / ...)
  → (5) wjs-translating-subtitles    → work/NNN/sourceNNN.ko.raw.srt
  → (6) Korean translation QA        → work/NNN/sourceNNN.ko.qa.srt
        (product names restored: 직물→Fabric, 부조종사→Copilot;
         speech level normalized to 높임말/합쇼체;
         wrap_srt.py then hard-caps every cue to 2 lines → sourceNNN.ko.srt)
  → (7) wjs-burning-subtitles        → work/NNN/sourceNNN.subtitled.mp4
        (FontSize 24, Apple SD Gothic Neo, WrapStyle=2)
  → (8) video-processing-editing     → outcome/final_outputNNN.mp4
        (FFmpeg concat: intro + subtitled + outro)
```

**Hard rules:**

- Default subtitle font size is **24** and MUST NOT exceed 2 lines per cue.
- Default vertical margin is **`MarginV=15`** so subtitles sit close to the bottom of the frame (bottom-anchored, YouTube-style burn-in).
- Product names Microsoft, Azure, GitHub, Copilot, .NET, VS Code, etc. MUST be correctly capitalized (never generic-lowercased) before translation.
- Korean subtitles MUST be in **높임말** (합쇼체, `~습니다`/`~입니다`) and MUST NOT contain product names translated as common nouns.

## Prerequisites

- macOS with Homebrew.
- `yt-dlp`.
- `ffmpeg` from the `homebrew-ffmpeg/ffmpeg` tap so libass and the `subtitles` filter are available.
- Project Python `.venv` with `openai-whisper` and `deep-translator`.
- Signed-in YouTube session in Microsoft Edge for `--cookies-from-browser edge`.
- `assets/ms-logo-intro.mp4` and `assets/ms-logo-outro.mp4`; if only one bumper exists, use it for both intro and outro.

```bash
brew install yt-dlp
brew uninstall ffmpeg 2>/dev/null || true
brew tap homebrew-ffmpeg/ffmpeg
brew install homebrew-ffmpeg/ffmpeg/ffmpeg
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install openai-whisper deep-translator
```

## Step-by-step (each step is independently runnable)

### Step 1 — Register the run id

**Skill:** no skill; shell/MEMORY.md inline

**Example prompt:**
> "Register a new run for https://www.youtube.com/watch?v=VIDEO_ID in MEMORY.md and use that NNN for every sourceNNN.* file."

**Underlying command:**
```bash
touch "${MEMORY_FILE:-MEMORY.md}"
origin="https://www.youtube.com/watch?v=VIDEO_ID"
NNN=$(awk 'match($0,/^[0-9][0-9][0-9] - /){n=substr($0,1,3)+0; if(n>m)m=n} END{printf "%03d", m+1}' "${MEMORY_FILE:-MEMORY.md}")
printf '%s - %s\n' "$NNN" "$origin" >> "${MEMORY_FILE:-MEMORY.md}"
mkdir -p "work/${NNN}" outcome
```

Allocate `NNN` as the next zero-padded 3-digit id, starting at `001`. Append exactly one registry line in `NNN - <origin>` form, where `<origin>` is the YouTube URL or absolute local file path. Then create the per-run scratch folder `work/${NNN}/`.

**Output:** `MEMORY.md` entry, empty `work/NNN/` directory, and a reusable `NNN` for `work/NNN/sourceNNN.*` and `outcome/final_outputNNN.mp4`.

### Step 2 — Download or stage the source clip

**Skill:** `youtube-downloader`

**Example prompt:**
> "Download https://www.youtube.com/watch?v=VIDEO_ID with Edge cookies as adaptive HD mp4 to work/NNN/sourceNNN.mp4."

**Underlying command:**
```bash
yt-dlp --cookies-from-browser "${COOKIE_BROWSER:-edge}" \
  --extractor-args "youtube:player_client=web,mweb" \
  -f "bv*[height<=1080]+ba/b[height<=1080]" \
  --merge-output-format mp4 \
  -o "work/${NNN}/source${NNN}.mp4" "https://www.youtube.com/watch?v=VIDEO_ID" \
|| yt-dlp --cookies-from-browser "${COOKIE_BROWSER:-edge}" \
  --extractor-args "youtube:player_client=web,mweb" \
  -f "bv*[height<=720]+ba/b[height<=720]" \
  --merge-output-format mp4 \
  -o "work/${NNN}/source${NNN}.mp4" "https://www.youtube.com/watch?v=VIDEO_ID" \
|| yt-dlp --cookies-from-browser "${COOKIE_BROWSER:-edge}" \
  -f 18 -o "work/${NNN}/source${NNN}.mp4" "https://www.youtube.com/watch?v=VIDEO_ID"
```

For a local file source, copy it instead after Step 1 logs its absolute path:

```bash
cp "/absolute/path/to/local-input.mp4" "work/${NNN}/source${NNN}.mp4"
```

**Output:** `work/NNN/sourceNNN.mp4`.

### Step 3 — Transcribe English audio to SRT

**Skill:** `wjs-transcribing-audio`

**Example prompt:**
> "Transcribe work/NNN/sourceNNN.mp4 with Whisper small in English and write work/NNN/sourceNNN.en.raw.srt."

**Underlying command:**
```bash
.venv/bin/whisper "work/${NNN}/source${NNN}.mp4" \
  --model "${WHISPER_MODEL:-small}" \
  --language "${SOURCE_LANG:-en}" \
  --task transcribe \
  --output_format srt \
  --output_dir "work/${NNN}"
mv "work/${NNN}/source${NNN}.srt" "work/${NNN}/source${NNN}.en.raw.srt"
```

**Output:** `work/NNN/sourceNNN.en.raw.srt`.

### Step 4 — Review English SRT for Microsoft / Azure / GitHub product names

**Skill:** no skill; deterministic lexicon script

Whisper often lowercases product names (e.g. writes `microsoft azure` or `github copilot` or `co-pilot`). This step applies a hard-coded lexicon so Microsoft/Azure/GitHub properties are ALWAYS correctly cased and never left as generic tokens. It runs **before** translation so the Korean SRT inherits the fixed spellings.

Lexicon includes (non-exhaustive): `Microsoft`, `Microsoft Azure`, `Azure`, `Azure OpenAI`, `Azure DevOps`, `Azure Functions`, `Azure Kubernetes Service`, `Azure AI Foundry`, `GitHub`, `GitHub Copilot`, `GitHub Actions`, `GitHub Codespaces`, `Copilot`, `.NET`, `Visual Studio`, `VS Code`, `Power BI`, `Power Platform`, `Microsoft Fabric`, `Microsoft 365`, `SQL Server`, `Windows`, `PowerShell`, `OpenAI`, `ChatGPT`, `TypeScript`, `JavaScript`, `Kubernetes`, `Docker`, `Linux`, `macOS`.

**Example prompt:**
> "Correct Microsoft/Azure/GitHub product names in work/NNN/sourceNNN.en.raw.srt and write work/NNN/sourceNNN.en.srt."

**Underlying command:**
```bash
.venv/bin/python .github/skills/youtube-video-clip-editing/scripts/correct_terms.py \
  "work/${NNN}/source${NNN}.en.raw.srt" \
  "work/${NNN}/source${NNN}.en.srt"
```

**Output:** `work/NNN/sourceNNN.en.srt` (product-name-clean).

### Step 5 — Translate corrected English SRT to Korean (2-line-max)

**Skill:** `wjs-translating-subtitles`

Runs the machine translation only. QA and the 2-line cap happen in Step 6.

**Example prompt:**
> "Translate work/NNN/sourceNNN.en.srt to Korean."

**Underlying command:**
```bash
.venv/bin/python .github/skills/youtube-video-clip-editing/scripts/translate_srt.py \
  "work/${NNN}/source${NNN}.en.srt" \
  "work/${NNN}/source${NNN}.ko.raw.srt" \
  --source "${SOURCE_LANG:-en}" --target "${TARGET_LANG:-ko}"
```

**Output:** `work/NNN/sourceNNN.ko.raw.srt` (raw machine translation).

### Step 6 — QA the Korean subtitles, then cap at 2 lines

**Skill:** no skill; deterministic QA script

Machine translation makes two systematic mistakes on Microsoft content, and this step fixes both **before** the text is burned in.

**1. Product names translated as common nouns.** Google Translate renders `Fabric` as 직물, `Copilot` as 부조종사, `Azure Friday` as 푸른 금요일, `Sentinel` as 보초, `Playwright` as 극작가. The lexicon in `qa_ko_srt.py` restores these. Restoration is **context-gated on the English cue and case-sensitive** — a capitalized `Fabric` in the English SRT means the product, while a lowercase `fabric` means the textile and is left alone. This works because Step 4 already normalized product-name casing.

Substituting an English noun back in also breaks Korean particle agreement, so the script repairs it: 부조종사**를** → Copilot**을** (closed syllable), 푸른**은** → Azure**는** (open syllable).

**2. Inconsistent speech level.** Output mixes 합쇼체 (`~습니다`), 해요체 (`~해요`) and 한다체/반말 (`~한다`). Subtitles must be uniformly **높임말**; the script conjugates everything to 합쇼체 by Hangul jamo arithmetic rather than a word list, so unseen verbs are handled: 간다→갑니다, 저질렀다→저질렀습니다, 멋지다→멋집니다, 만든다→만듭니다. Already-polite endings (`입니다`, `습니다`, `~ㅂ시다`, `~ㄴ가요?`) are detected and left untouched.

Anything it cannot fix confidently is written to a report instead of being guessed at, so a human or agent reviews a short list rather than the whole file.

**Example prompt:**
> "QA work/NNN/sourceNNN.ko.raw.srt against the English SRT — fix mistranslated Microsoft product names, enforce 높임말, and report anything questionable."

**Underlying command:**
```bash
.venv/bin/python .github/skills/youtube-video-clip-editing/scripts/qa_ko_srt.py \
  "work/${NNN}/source${NNN}.en.srt" \
  "work/${NNN}/source${NNN}.ko.raw.srt" \
  "work/${NNN}/source${NNN}.ko.qa.srt" \
  --report "work/${NNN}/source${NNN}.ko.qa-report.txt"

.venv/bin/python .github/skills/youtube-video-clip-editing/scripts/wrap_srt.py \
  "work/${NNN}/source${NNN}.ko.qa.srt" \
  "work/${NNN}/source${NNN}.ko.srt"
```

Then **read the report** and hand-fix anything it flagged. It lists every automatic rewrite, any cue still in plain form, and any cue where the English named a product that never made it into the Korean.

Verify the QA rules themselves with `qa_ko_srt.py --self-test` (40 assertions).

**Output:** `work/NNN/sourceNNN.ko.srt` (product names correct, 높임말, every cue ≤ 2 lines) plus `work/NNN/sourceNNN.ko.qa-report.txt`.

### Step 7 — Burn Korean subtitles into the video

**Skill:** `wjs-burning-subtitles`

Burn at **FontSize=24** (default), with `WrapStyle=2` so libass never auto-wraps our carefully sized cues into a 3rd line.

**Example prompt:**
> "Burn work/NNN/sourceNNN.ko.srt into work/NNN/sourceNNN.mp4 with Apple SD Gothic Neo at FontSize 24 and keep English audio."

**Underlying command:**
```bash
ffmpeg -y -i "work/${NNN}/source${NNN}.mp4" \
  -vf "subtitles=work/${NNN}/source${NNN}.ko.srt:force_style='FontName=${SUB_FONT:-Apple SD Gothic Neo},FontSize=${SUB_FONT_SIZE:-24},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=0,MarginV=${SUB_MARGIN_V:-15},WrapStyle=2'" \
  -c:v libx264 -pix_fmt yuv420p -c:a copy \
  "work/${NNN}/source${NNN}.subtitled.mp4"
```

**Output:** `work/NNN/sourceNNN.subtitled.mp4` with Korean subtitles burned in (FontSize=24, max 2 lines) and original English audio preserved.

### Step 8 — Normalize and concatenate intro, main, and outro

**Skill:** `video-processing-editing`

**Example prompt:**
> "Normalize assets/ms-logo-intro.mp4, work/NNN/sourceNNN.subtitled.mp4, and assets/ms-logo-outro.mp4 to 1920×1080/30fps/libx264/aac 48k stereo, then concat to outcome/final_outputNNN.mp4."

**Underlying command:**
```bash
intro_clip="assets/ms-logo-intro.mp4"
outro_clip="${outro_clip:-assets/ms-logo-outro.mp4}"
mkdir -p "work/${NNN}" outcome

ffmpeg -y -i "$intro_clip" \
  -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30" \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -ar 48000 -ac 2 \
  "work/${NNN}/norm_${NNN}_intro.mp4"
ffmpeg -y -i "work/${NNN}/source${NNN}.subtitled.mp4" \
  -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30" \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -ar 48000 -ac 2 \
  "work/${NNN}/norm_${NNN}_main.mp4"
ffmpeg -y -i "$outro_clip" \
  -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30" \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -ar 48000 -ac 2 \
  "work/${NNN}/norm_${NNN}_outro.mp4"

printf "file 'norm_%s_intro.mp4'\nfile 'norm_%s_main.mp4'\nfile 'norm_%s_outro.mp4'\n" "$NNN" "$NNN" "$NNN" > "work/${NNN}/concat_${NNN}.txt"
(cd "work/${NNN}" && ffmpeg -y -f concat -safe 0 -i "concat_${NNN}.txt" -c copy "../../outcome/final_output${NNN}.mp4")
```

Use basename-only concat entries because the concat command runs from inside `work/NNN/`.

**Output:** `outcome/final_outputNNN.mp4`.

## One-shot automated run

**Natural-language prompt:**
> "Produce a localized clip from https://www.youtube.com/watch?v=VIDEO_ID using assets/ms-logo-intro.mp4 and assets/ms-logo-outro.mp4. Register it in MEMORY.md, create sourceNNN.* intermediates in work/NNN/, and save the deliverable as outcome/final_outputNNN.mp4."

**Script invocation:**
```bash
.github/skills/youtube-video-clip-editing/scripts/produce_localized_clip.sh \
  <source> <intro_clip> [outro_clip] [work_dir]
```

`<source>` is a YouTube URL or local video path. `[outro_clip]` defaults to `<intro_clip>` for the one-bumper fallback. `[work_dir]` defaults to `work/${NNN}/` and is created automatically; pass an explicit path only if you need to override the per-run subfolder. The output path is auto-derived from the allocated `NNN` as `outcome/final_output${NNN}.mp4`; do not pass an output argument.

Example:

```bash
.github/skills/youtube-video-clip-editing/scripts/produce_localized_clip.sh \
  "https://www.youtube.com/watch?v=VIDEO_ID" \
  assets/ms-logo-intro.mp4 \
  assets/ms-logo-outro.mp4
```

## Environment variables

- `AUTO_INSTALL_DEPS`: if set to `1`, allow automatic dependency installation via brew/apt.
- `COOKIE_BROWSER`: browser for `yt-dlp --cookies-from-browser`; default `edge`.
- `WHISPER_MODEL`: Whisper model for transcription; default `small`.
- `SOURCE_LANG`: source audio/subtitle language; default `en`.
- `TARGET_LANG`: translated subtitle language; default `ko`.
- `SUB_FONT`: subtitle font family; default `Apple SD Gothic Neo`.
- `SUB_FONT_SIZE`: subtitle font size for 1080p output; default **`24`**.
- `SUB_MARGIN_V`: vertical margin from the bottom of the frame in ASS units; default **`15`** (subtitles sit close to the bottom of the screen; raise to nudge them upward).
- `MEMORY_FILE`: run registry path; default `<repo_root>/MEMORY.md`.

## Notes / edge cases

- Non-English source: set `SOURCE_LANG` and route transcription through the appropriate `wjs-transcribing-audio` mode before Step 4.
- Cookie fallback ladder: Edge first, then another signed-in supported browser by setting `COOKIE_BROWSER`.
- HD download fallback ladder: adaptive 1080p, then adaptive 720p, then `-f 18` 360p muxed.
- Bumper with no audio track: the script auto-synthesizes silent AAC during normalization.
- Concurrent runs: `MEMORY.md` allocation is guarded by `flock` when available; the per-run `work/NNN/` subfolder also prevents intermediates from different runs colliding.
- Local file source: the script copies it to `work/NNN/sourceNNN.mp4` and logs the absolute path as origin in `MEMORY.md`.
- Trimmed source: the script has no trim option. Download the section first with `yt-dlp --download-sections "*HH:MM:SS-HH:MM:SS" --force-keyframes-at-cuts`, feed that file in as a local source, then rewrite the `MEMORY.md` line as `NNN - <youtube_url> [trim HH:MM:SS-HH:MM:SS]` so provenance survives deletion of the temp file.
- Deliverable over 100 MB: GitHub rejects single files above 100 MB and the free Git LFS tier is only 1 GB, so oversized outcomes are not retained. Drop `outcome/final_outputNNN.mp4` (`git rm --cached` first — it is LFS-tracked) plus the bulky `work/NNN/` intermediates (`sourceNNN.mp4`, `sourceNNN.subtitled.mp4`, `norm_NNN_main.mp4`), keep the `.srt` files, and annotate the run `NNN - <origin> [outcome removed: >100MB]`.
- Concurrent runs without `flock`: run-id allocation is racy. Give each concurrent run its own pre-seeded `MEMORY_FILE` (seeded so it deterministically allocates the id you want), then merge the registries afterwards.
- Large deliverables: `outcome/*.mp4` is tracked with Git LFS because GitHub rejects files over 100 MB and hour-long 1080p runs reach ~300 MB.
- Adding a new product name: append to `CORRECTIONS` in `scripts/correct_terms.py` (English casing, Step 4) **and** to `PRODUCTS` in `scripts/qa_ko_srt.py` (Korean mistranslations, Step 6). Longer phrases must come before their single-word components in both (e.g. `microsoft azure` before `microsoft`, `Azure Friday` before `Azure`).
- A Korean word that is also a legitimate common noun (직물, 보초, 전망) is only rewritten when the aligned English cue contains the product name **capitalized**, so ordinary prose is never clobbered. If a product still slips through, check that Step 4 capitalized it in the English SRT first.
- **Steps 4 and 6 are coupled — a term missing from Step 4 silently disables Step 6 for that term.** Real example: Whisper transcribed "It's firing up playwright." in lowercase; `correct_terms.py` had no `playwright` entry, so the English SRT kept it lowercase, so the case-sensitive gate in Step 6 correctly refused to rewrite 극작가 and the mistranslation shipped. Fixing it meant adding `playwright` to `CORRECTIONS`, not touching `PRODUCTS`. When a mistranslation survives QA, check the English SRT casing before suspecting the Korean lexicon.
- Do not add short or everyday words to `PRODUCTS`. `Go`/`Swift`/`Vue`/`Arc`/`Node` are deliberately excluded because their Korean forms (가다, 빠른, 뷰, 호, 마디) are ordinary vocabulary or fragments of longer words — "Go ahead and pick up the CLI" is not the Go language. Korean matches are additionally left-anchored on a Hangul boundary so 키워드 never becomes 키Word.
- Speech level: `qa_ko_srt.py` conjugates to 합쇼체 by jamo arithmetic, so new verbs need no configuration. Endings it must never touch (`~ㅂ시다` propositive, `~ㄴ가요?` interrogative, `~마다`, `~보다`) are listed in `NON_VERBAL_DA_TAILS` / `BOUNDARY_GUARDED` / `_is_propositive`.
- After changing either lexicon or a conjugation rule, run `qa_ko_srt.py --self-test` before shipping.
- Tuning the 2-line budget: adjust `LINE_UNITS` in `scripts/wrap_srt.py` (default `46` display units; CJK chars count as 2).
