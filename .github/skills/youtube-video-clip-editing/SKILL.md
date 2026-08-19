---
name: youtube-video-clip-editing
description: End-to-end 6-stage pipeline that registers a run in MEMORY.md, downloads a YouTube clip with Edge cookies, burns in Korean subtitles, and brackets the result with a Microsoft-logo intro/outro bumper. Orchestrates four sibling skills (youtube-downloader, wjs-transcribing-audio, wjs-translating-subtitles, wjs-burning-subtitles) plus MEMORY.md registration and FFmpeg normalization/concatenation into outcome/final_outputNNN.mp4. Use when the user asks to "download a YouTube clip and add Korean subtitles", "make a localized clip with our Microsoft intro/outro", or similar multi-step video-localization + branding requests.
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
      reason: Step 2 — fetches the source clip from YouTube into work/sourceNNN.mp4
    - skill: wjs-transcribing-audio
      reason: Step 3 — produces the source-language SRT at work/sourceNNN.en.srt
    - skill: wjs-translating-subtitles
      reason: Step 4 — translates the English SRT to Korean at work/sourceNNN.ko.srt
    - skill: wjs-burning-subtitles
      reason: Step 5 — burns the Korean SRT into work/sourceNNN.subtitled.mp4
    - skill: video-processing-editing
      reason: Step 6 — normalizes and concatenates intro, main, and outro into outcome/final_outputNNN.mp4
---

# YouTube Video Clip Editing (Register → Download → Korean Subs → Microsoft Bumper)

## Overview

This skill turns a YouTube URL or local video file into a branded, Korean-subtitled deliverable by allocating a run id, producing `sourceNNN.*` intermediates in `work/`, and writing the finished clip to `outcome/final_outputNNN.mp4`.

```
YouTube URL (or local file path)
  → (1) register-run in /MEMORY.md   → allocates NNN, logs "NNN - <origin>"
  → (2) youtube-downloader           → work/sourceNNN.mp4
  → (3) wjs-transcribing-audio       → work/sourceNNN.en.srt
  → (4) wjs-translating-subtitles    → work/sourceNNN.ko.srt
  → (5) wjs-burning-subtitles        → work/sourceNNN.subtitled.mp4
  → (6) video-processing-editing     → outcome/final_outputNNN.mp4
        (FFmpeg concat: intro + subtitled + outro)
```

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
mkdir -p work outcome
touch "${MEMORY_FILE:-MEMORY.md}"
origin="https://www.youtube.com/watch?v=VIDEO_ID"
NNN=$(awk 'match($0,/^[0-9][0-9][0-9] - /){n=substr($0,1,3)+0; if(n>m)m=n} END{printf "%03d", m+1}' "${MEMORY_FILE:-MEMORY.md}")
printf '%s - %s\n' "$NNN" "$origin" >> "${MEMORY_FILE:-MEMORY.md}"
```

Allocate `NNN` as the next zero-padded 3-digit id, starting at `001`. Append exactly one registry line in `NNN - <origin>` form, where `<origin>` is the YouTube URL or absolute local file path.

**Output:** `MEMORY.md` entry and a reusable `NNN` for `work/sourceNNN.*` and `outcome/final_outputNNN.mp4`.

### Step 2 — Download or stage the source clip

**Skill:** `youtube-downloader`

**Example prompt:**
> "Download https://www.youtube.com/watch?v=VIDEO_ID with Edge cookies as adaptive HD mp4 to work/sourceNNN.mp4."

**Underlying command:**
```bash
yt-dlp --cookies-from-browser "${COOKIE_BROWSER:-edge}" \
  --extractor-args "youtube:player_client=web,mweb" \
  -f "bv*[height<=1080]+ba/b[height<=1080]" \
  --merge-output-format mp4 \
  -o "work/source${NNN}.mp4" "https://www.youtube.com/watch?v=VIDEO_ID" \
|| yt-dlp --cookies-from-browser "${COOKIE_BROWSER:-edge}" \
  --extractor-args "youtube:player_client=web,mweb" \
  -f "bv*[height<=720]+ba/b[height<=720]" \
  --merge-output-format mp4 \
  -o "work/source${NNN}.mp4" "https://www.youtube.com/watch?v=VIDEO_ID" \
|| yt-dlp --cookies-from-browser "${COOKIE_BROWSER:-edge}" \
  -f 18 -o "work/source${NNN}.mp4" "https://www.youtube.com/watch?v=VIDEO_ID"
```

For a local file source, copy it instead after Step 1 logs its absolute path:

```bash
cp "/absolute/path/to/local-input.mp4" "work/source${NNN}.mp4"
```

**Output:** `work/sourceNNN.mp4`.

### Step 3 — Transcribe English audio to SRT

**Skill:** `wjs-transcribing-audio`

**Example prompt:**
> "Transcribe work/sourceNNN.mp4 with Whisper small in English and write work/sourceNNN.en.srt."

**Underlying command:**
```bash
.venv/bin/whisper "work/source${NNN}.mp4" \
  --model "${WHISPER_MODEL:-small}" \
  --language "${SOURCE_LANG:-en}" \
  --task transcribe \
  --output_format srt \
  --output_dir work
mv "work/source${NNN}.srt" "work/source${NNN}.en.srt"
```

**Output:** `work/sourceNNN.en.srt`.

### Step 4 — Translate English SRT to Korean

**Skill:** `wjs-translating-subtitles`

**Example prompt:**
> "Translate work/sourceNNN.en.srt to Korean and write work/sourceNNN.ko.srt."

**Underlying command:**
```bash
.venv/bin/python .github/skills/wjs-translating-subtitles/scripts/translate_srt.py \
  "work/source${NNN}.en.srt" \
  "work/source${NNN}.ko.srt" \
  --source-lang "${SOURCE_LANG:-en}" \
  --target-lang "${TARGET_LANG:-ko}"
```

**Output:** `work/sourceNNN.ko.srt`.

### Step 5 — Burn Korean subtitles into the video

**Skill:** `wjs-burning-subtitles`

**Example prompt:**
> "Burn work/sourceNNN.ko.srt into work/sourceNNN.mp4 with Apple SD Gothic Neo at FontSize 32 and keep English audio."

**Underlying command:**
```bash
ffmpeg -y -i "work/source${NNN}.mp4" \
  -vf "subtitles=work/source${NNN}.ko.srt:force_style='FontName=${SUB_FONT:-Apple SD Gothic Neo},FontSize=${SUB_FONT_SIZE:-32}'" \
  -c:v libx264 -pix_fmt yuv420p -c:a copy \
  "work/source${NNN}.subtitled.mp4"
```

**Output:** `work/sourceNNN.subtitled.mp4` with Korean subtitles burned in and original English audio preserved.

### Step 6 — Normalize and concatenate intro, main, and outro

**Skill:** `video-processing-editing`

**Example prompt:**
> "Normalize assets/ms-logo-intro.mp4, work/sourceNNN.subtitled.mp4, and assets/ms-logo-outro.mp4 to 1920×1080/30fps/libx264/aac 48k stereo, then concat to outcome/final_outputNNN.mp4."

**Underlying command:**
```bash
intro_clip="assets/ms-logo-intro.mp4"
outro_clip="${outro_clip:-assets/ms-logo-outro.mp4}"
mkdir -p work outcome

ffmpeg -y -i "$intro_clip" \
  -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30" \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -ar 48000 -ac 2 \
  "work/norm_${NNN}_intro.mp4"
ffmpeg -y -i "work/source${NNN}.subtitled.mp4" \
  -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30" \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -ar 48000 -ac 2 \
  "work/norm_${NNN}_main.mp4"
ffmpeg -y -i "$outro_clip" \
  -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30" \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -ar 48000 -ac 2 \
  "work/norm_${NNN}_outro.mp4"

printf "file 'norm_%s_intro.mp4'\nfile 'norm_%s_main.mp4'\nfile 'norm_%s_outro.mp4'\n" "$NNN" "$NNN" "$NNN" > "work/concat_${NNN}.txt"
cd work && ffmpeg -y -f concat -safe 0 -i "concat_${NNN}.txt" -c copy "../outcome/final_output${NNN}.mp4"
```

Use basename-only concat entries because the concat command runs from inside `work/`.

**Output:** `outcome/final_outputNNN.mp4`.

## One-shot automated run

**Natural-language prompt:**
> "Produce a localized clip from https://www.youtube.com/watch?v=VIDEO_ID using assets/ms-logo-intro.mp4 and assets/ms-logo-outro.mp4. Register it in MEMORY.md, create sourceNNN.* intermediates, and save the deliverable as outcome/final_outputNNN.mp4."

**Script invocation:**
```bash
.github/skills/youtube-video-clip-editing/scripts/produce_localized_clip.sh \
  <source> <intro_clip> [outro_clip] [work_dir]
```

`<source>` is a YouTube URL or local video path. `[outro_clip]` defaults to `<intro_clip>` for the one-bumper fallback. The output path is auto-derived from the allocated `NNN` as `outcome/final_output${NNN}.mp4`; do not pass an output argument.

Example:

```bash
.github/skills/youtube-video-clip-editing/scripts/produce_localized_clip.sh \
  "https://www.youtube.com/watch?v=VIDEO_ID" \
  assets/ms-logo-intro.mp4 \
  assets/ms-logo-outro.mp4
```

## Environment variables

- `AUTO_INSTALL_DEPS`: if set by the script, allow automatic dependency installation.
- `COOKIE_BROWSER`: browser for `yt-dlp --cookies-from-browser`; default `edge`.
- `WHISPER_MODEL`: Whisper model for transcription; default `small`.
- `SOURCE_LANG`: source audio/subtitle language; default `en`.
- `TARGET_LANG`: translated subtitle language; default `ko`.
- `SUB_FONT`: subtitle font family; default `Apple SD Gothic Neo`.
- `SUB_FONT_SIZE`: subtitle font size for 1080p output; default `32`.
- `MEMORY_FILE`: run registry path; default `<repo_root>/MEMORY.md`.

## Notes / edge cases

- Non-English source: set `SOURCE_LANG` and route transcription through the appropriate `wjs-transcribing-audio` mode before translation.
- Cookie fallback ladder: Edge first, then another signed-in supported browser by setting `COOKIE_BROWSER`.
- HD download fallback ladder: adaptive 1080p, then adaptive 720p, then `-f 18` 360p muxed.
- Bumper with no audio track: the script auto-synthesizes silent AAC during normalization.
- Concurrent runs: `MEMORY.md` allocation is guarded by `flock` when available.
- Local file source: the script copies it to `work/sourceNNN.mp4` and logs the absolute path as origin in `MEMORY.md`.
