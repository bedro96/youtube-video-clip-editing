# Copilot instructions — youtube-video-clip-editing

## What this repo is

This repo is **not application code**. It packages a single Copilot CLI *skill*
(`.github/skills/youtube-video-clip-editing/`) that **orchestrates other
skills** to turn a YouTube URL into a Korean-subtitled clip wrapped in a
Microsoft-logo intro/outro bumper.

The canonical spec lives in
`.github/skills/youtube-video-clip-editing/SKILL.md` — read it before editing
anything. The bash orchestrator
`.github/skills/youtube-video-clip-editing/scripts/produce_localized_clip.sh`
is the executable form of that spec; the two must stay in sync.

## Pipeline (7 stages)

```
YouTube URL (or local file path)
  → (1) register-run in /MEMORY.md   → allocates NNN, logs "NNN - <origin>"
  → (2) youtube-downloader           → work/NNN/sourceNNN.mp4
  → (3) wjs-transcribing-audio       → work/NNN/sourceNNN.en.raw.srt
  → (4) product-name review          → work/NNN/sourceNNN.en.srt
        (Microsoft / Azure / GitHub / Copilot / .NET / VS Code ...)
  → (5) wjs-translating-subtitles    → work/NNN/sourceNNN.ko.srt
        (post-processed to max 2 subtitle lines per cue)
  → (6) wjs-burning-subtitles        → work/NNN/sourceNNN.subtitled.mp4
        (FontSize 24, Apple SD Gothic Neo, WrapStyle=2)
  → (7) video-processing-editing     → outcome/final_outputNNN.mp4
        (FFmpeg concat: intro + subtitled + outro)
```

Key conventions this pipeline relies on — preserve them when editing:

- **Per-run scratch dir is `./work/NNN/`** — every intermediate for a given
  run lands under its own zero-padded 3-digit subfolder so that repeated runs
  do not pile files into a single `work/` root and are trivially cleanable
  (`rm -rf work/NNN`). Intermediate filenames still carry `NNN` for
  grep-ability: `sourceNNN.mp4`, `sourceNNN.en.raw.srt`, `sourceNNN.en.srt`,
  `sourceNNN.ko.raw.srt`, `sourceNNN.ko.srt`, `sourceNNN.subtitled.mp4`,
  `norm_NNN_{intro,main,outro}.mp4`, `concat_NNN.txt`. Every downstream
  stage substitutes the *same* `NNN` into the filename and folder — do not
  mix run ids across stages.
- **Step 1 (run registration) is mandatory and must run before Step 2.**
  Agents must:
  1. Read `/MEMORY.md` at the repo root (create it if missing).
  2. Compute `NNN = max(existing NNN) + 1`, starting at `001` when the file
     is empty.
  3. Append exactly one line: `NNN - <origin>` where `<origin>` is the
     YouTube URL or the absolute/relative local source path.
  4. Create `./work/NNN/` if it does not exist.
  5. Pass that same `NNN` into every subsequent stage's filenames.
- **Step 4 (product-name review) is mandatory.** Whisper commonly lowercases
  Microsoft/Azure/GitHub product names; Step 4 applies a deterministic
  lexicon (`scripts/correct_terms.py`) that ensures `Microsoft`, `Azure`,
  `GitHub`, `GitHub Copilot`, `Copilot`, `.NET`, `VS Code`, `Power BI`,
  `Microsoft 365`, etc. are always properly cased. **Never treat these as
  generic tokens.** Add new terms to `CORRECTIONS` in that script, longer
  phrases before shorter ones (e.g. `microsoft azure` before `microsoft`).
- **Step 5 hard-caps every cue to 2 subtitle lines.** `scripts/wrap_srt.py`
  measures display width in units (CJK = 2, other = 1), targets ≤ 46 units
  per line, and either wraps to 2 lines or splits the cue in time. This
  invariant is non-negotiable — do not weaken it or bump `LINE_UNITS` past
  ~50 without measuring on 1080p.
- **Default subtitle font size is 24, not 32.** This value is intentional
  and paired with the 2-line cap. Larger sizes will overflow 2 lines on
  medium-length Korean cues. Overrideable via `SUB_FONT_SIZE`, but the
  default in code and docs must stay `24`.
- **Default subtitle vertical margin is `MarginV=15`** so the caption
  block sits close to the bottom of the frame (YouTube-style burn-in
  placement). Overrideable via `SUB_MARGIN_V`; keep the code + docs
  default at `15` unless someone measurably justifies a different value.
- **Final deliverable is `outcome/final_outputNNN.mp4` at the repo root**,
  using the same `NNN` allocated in Step 1.
- **English audio is preserved** through Step 6; only the video track gets
  Korean subs burned in. Do not add an audio-replacement step.
- **Step 7 requires normalization first.** Intro, main, and outro must share
  codec/resolution/fps/audio-sample-rate before `ffmpeg -f concat -c copy`,
  or the output desyncs/corrupts. Current normalization target is
  `1920x1080 / 30 fps / libx264 yuv420p / aac 48 kHz stereo` — change all
  three inputs together, never just one.
- **Sibling-skill script paths are relative**, resolved from the orchestrator
  as `$(dirname "$0")/../../<skill-name>/scripts/...`. Moving the script
  breaks Steps 2 and 6.
- **`set -euo pipefail`** in the orchestrator is intentional: any stage
  failure must abort so partial/garbage files never propagate downstream.
  Do not weaken this.
- **One-bumper fallback:** if the user supplies only one branding clip, it
  is passed for *both* intro and outro positions. Keep this behavior.

## `/MEMORY.md` format

One line per run, in allocation order, using exactly this shape:

```
NNN - <origin>
```

- `NNN` is zero-padded 3 digits (`001`, `002`, ..., `999`).
- `<origin>` is the YouTube URL for downloaded clips, or the local file path
  for clips sourced from disk.
- No other columns, no headers, no blank lines between entries.

Example:

```
001 - https://www.youtube.com/watch?v=abc123
002 - /Users/me/Videos/keynote.mp4
003 - https://www.youtube.com/watch?v=xyz789
```

To pick the next id, read the file, parse the leading integer of each line,
take the max, add 1, and re-zero-pad to width 3. If `/MEMORY.md` does not
exist or is empty, the next id is `001`.

## Running / testing

There is no build, unit-test, or lint tooling in this repo. Validation is
end-to-end:

```bash
.github/skills/youtube-video-clip-editing/scripts/produce_localized_clip.sh \
  "<youtube_url>" <intro.mp4> [outro.mp4] [work_dir]
```

The orchestrator handles Step 1 registration automatically: it reads or
creates `/MEMORY.md`, allocates the next `NNN`, creates `./work/NNN/`, and
writes `outcome/final_outputNNN.mp4`.

Supported environment overrides are `AUTO_INSTALL_DEPS`, `COOKIE_BROWSER`
(default `edge`), `WHISPER_MODEL` (default `small`), `SOURCE_LANG`/
`TARGET_LANG` (defaults `en`/`ko`), `SUB_FONT`, `SUB_FONT_SIZE` (default
**`24`**), `SUB_MARGIN_V` (default **`15`**), and `MEMORY_FILE`.

To test a single stage in isolation, first pick an `NNN` manually — either
reuse an existing id from `/MEMORY.md` (to re-run a stage against an
already-staged intermediate) or allocate a fresh one and append the
registration line yourself — then stage `work/NNN/sourceNNN.mp4` (or the
relevant intermediate) and invoke that stage's underlying command from
`SKILL.md`. Do not add a test harness unless the user asks — this repo
intentionally defers execution to the delegated skills.

## YouTube Edge sign-in prerequisite

**Sign into YouTube in Microsoft Edge before running the pipeline.** The `yt-dlp` step uses your Edge browser cookies (`--cookies-from-browser edge`) to fetch adaptive HD formats and to bypass DRM-flagged responses on other clients. If you're not signed in, downloads may return 403 or fall back to low-resolution (360p) muxed formats. If you use a different browser, sign in there and swap `edge` for `brave`, `chrome`, `chromium`, `firefox`, `opera`, `safari`, `vivaldi`, or `whale` in the command below.

Standard command:

```bash
yt-dlp --cookies-from-browser edge \
  --extractor-args "youtube:player_client=web,mweb" \
  -f "bv*[height<=1080]+ba/b[height<=1080]" \
  --merge-output-format mp4 \
  -o "work/NNN/sourceNNN.mp4" "<youtube_url>"
```

`-f 18` (360p muxed mp4) is a fallback only when adaptive HD formats are unavailable.

## Known gotchas on macOS

**1. Homebrew `ffmpeg` from `homebrew/core` ships without libass.** That means the `subtitles` filter used by Step 6 is missing (`No such filter: 'subtitles'`). Fix:
```bash
brew uninstall ffmpeg
brew tap homebrew-ffmpeg/ffmpeg
brew install homebrew-ffmpeg/ffmpeg/ffmpeg
```
Confirm with `ffmpeg -filters | grep -i subtitle`.

**2. Homebrew Python is PEP-668 externally-managed.** `pip install --user openai-whisper deep-translator` fails with an "externally-managed-environment" error. Fix: use a project-local venv.
```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install openai-whisper deep-translator
```
Then invoke skill scripts as `.venv/bin/python …` (or `.venv/bin/whisper …`). Do NOT pass `--break-system-packages` to pip.

## When editing

- Update `SKILL.md`, `produce_localized_clip.sh`, `README.md`, and this file
  **together**. When any of them changes, revisit the others in the same
  edit pass.
- The step-by-step section in `SKILL.md` is the source of truth for what
  the script does.
- The skill's frontmatter `description:` field is what the CLI matches on
  for auto-invocation. If you change trigger phrases, update it there.
- If you add a new stage, also update the `pairs-with:` list, the pipeline
  ASCII diagram in both `SKILL.md` and this file, and the mermaid flowchart
  in `README.md`.
- If you change `SUB_FONT_SIZE`, `LINE_UNITS`, or the term-correction
  lexicon, restate the defaults in both `SKILL.md` and this file, and note
  the change in `README.md` if user-visible.
