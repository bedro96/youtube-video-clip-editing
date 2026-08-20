#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <source> <intro_clip> [outro_clip] [work_dir]"
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 2 ]]; then
  usage >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

AUTO_INSTALL_DEPS="${AUTO_INSTALL_DEPS:-0}"
COOKIE_BROWSER="${COOKIE_BROWSER:-edge}"
COOKIES_FILE="${COOKIES_FILE:-}"
WHISPER_MODEL="${WHISPER_MODEL:-small}"
SOURCE_LANG="${SOURCE_LANG:-en}"
TARGET_LANG="${TARGET_LANG:-ko}"
SUB_FONT="${SUB_FONT:-Apple SD Gothic Neo}"
SUB_FONT_SIZE="${SUB_FONT_SIZE:-24}"
SUB_MARGIN_V="${SUB_MARGIN_V:-15}"
MEMORY_FILE="${MEMORY_FILE:-${repo_root}/MEMORY.md}"

SOURCE_INPUT="$1"
INTRO_CLIP="$2"
OUTRO_CLIP="${3:-$INTRO_CLIP}"
# WORK_DIR default is deferred until NNN is allocated so that each run
# lands in its own ./work/NNN/ subfolder. Callers can still override the
# 4th positional arg with an explicit path.
WORK_DIR_ARG="${4:-}"

need_python=0
need_ffmpeg=0
need_ytdlp=0
command -v python3 >/dev/null 2>&1 || need_python=1
if [[ ! -x /opt/homebrew/bin/ffmpeg ]] && ! command -v ffmpeg >/dev/null 2>&1; then need_ffmpeg=1; fi
command -v yt-dlp >/dev/null 2>&1 || need_ytdlp=1

install_safe_deps() {
  packages=()
  case "$(uname -s)" in
    Darwin)
      if ! command -v brew >/dev/null 2>&1; then
        echo "Homebrew is required to auto-install dependencies." >&2
        echo "Install it from https://brew.sh, then run:" >&2
        echo "  brew install python yt-dlp ffmpeg" >&2
        return 1
      fi
      if (( need_python )); then packages+=(python); fi
      if (( need_ffmpeg )); then packages+=(ffmpeg); fi
      if (( need_ytdlp )); then packages+=(yt-dlp); fi
      brew install "${packages[@]}" || return 1
      ;;
    Linux)
      if ! command -v apt-get >/dev/null 2>&1; then
        echo "Unsupported package manager; install python3, ffmpeg, and yt-dlp manually." >&2
        return 1
      fi
      if (( need_python )); then packages+=(python3); fi
      if (( need_ffmpeg )); then packages+=(ffmpeg); fi
      if (( need_ytdlp )); then packages+=(yt-dlp); fi
      if (( EUID == 0 )); then
        apt-get update && apt-get install -y "${packages[@]}" || return 1
      elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
        sudo -n apt-get update && sudo -n apt-get install -y "${packages[@]}" || return 1
      else
        echo "Run the following interactively, then retry:" >&2
        echo "  sudo apt-get update" >&2
        echo "  sudo apt-get install -y ${packages[*]}" >&2
        return 1
      fi
      ;;
    *)
      echo "Unsupported OS; install python3, ffmpeg, and yt-dlp manually, then retry." >&2
      return 1
      ;;
  esac
}

if (( need_python || need_ffmpeg || need_ytdlp )); then
  if [[ "${AUTO_INSTALL_DEPS}" == "1" ]]; then
    install_safe_deps || exit 127
  else
    echo "Missing required system dependencies (python3, ffmpeg, and/or yt-dlp)." >&2
    case "$(uname -s)" in
      Darwin) echo "Install with: brew install python yt-dlp ffmpeg" >&2 ;;
      Linux) echo "Install with: sudo apt-get install -y python3 ffmpeg yt-dlp" >&2 ;;
    esac
    echo "Or rerun with AUTO_INSTALL_DEPS=1 to install automatically." >&2
    exit 127
  fi
fi

command -v python3 >/dev/null 2>&1 || { echo "Required command still unavailable after installation: python3" >&2; exit 127; }
if [[ -x /opt/homebrew/bin/ffmpeg ]]; then
  FFMPEG="/opt/homebrew/bin/ffmpeg"
else
  FFMPEG="$(command -v ffmpeg)"
fi
if [[ -x /opt/homebrew/bin/ffprobe ]]; then
  FFPROBE="/opt/homebrew/bin/ffprobe"
elif command -v ffprobe >/dev/null 2>&1; then
  FFPROBE="$(command -v ffprobe)"
else
  echo "Missing ffprobe. Install ffmpeg, then retry." >&2
  exit 127
fi
YTDLP="$(command -v yt-dlp)"

if ! "${FFMPEG}" -hide_banner -filters 2>/dev/null | grep '^ ... subtitles ' >/dev/null; then
  echo "This ffmpeg build is missing the subtitles filter/libass support." >&2
  echo "On macOS, install with:" >&2
  echo "  brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg" >&2
  exit 127
fi

PYTHON_BIN="${repo_root}/.venv/bin/python"
WHISPER_BIN="${repo_root}/.venv/bin/whisper"
if [[ ! -x "${WHISPER_BIN}" || ! -x "${PYTHON_BIN}" ]]; then
  echo "Missing skill virtualenv tools (.venv/bin/whisper and/or .venv/bin/python)." >&2
  echo "Recover with:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install openai-whisper deep-translator" >&2
  exit 127
fi

if [[ ! -r "${INTRO_CLIP}" ]]; then
  echo "Intro clip is missing or not readable: ${INTRO_CLIP}" >&2
  exit 1
fi
if [[ ! -r "${OUTRO_CLIP}" ]]; then
  echo "Outro clip is missing or not readable: ${OUTRO_CLIP}" >&2
  exit 1
fi

if [[ "${SOURCE_INPUT}" =~ ^https?:// ]]; then
  ORIGIN="${SOURCE_INPUT}"
else
  if [[ ! -r "${SOURCE_INPUT}" ]]; then
    echo "Source is neither an HTTP(S) URL nor a readable local file: ${SOURCE_INPUT}" >&2
    exit 1
  fi
  ORIGIN="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "${SOURCE_INPUT}")"
fi

mkdir -p "${repo_root}/outcome"

max_memory_number() {
  awk 'match($0,/^[0-9]+/){n=substr($0,RSTART,RLENGTH)+0;if(n>max)max=n}END{print max+0}' "$1"
}

register_run() {
  touch "${MEMORY_FILE}"
  if command -v flock >/dev/null 2>&1; then
    (
      exec 9>>"${MEMORY_FILE}"
      flock -x 9
      max_num="$(max_memory_number "${MEMORY_FILE}")"
      next_num=$((max_num + 1))
      nnn="$(printf '%03d' "${next_num}")"
      printf '%s - %s\n' "${nnn}" "${ORIGIN}" >&9
      printf '%s\n' "${nnn}"
    )
  else
    echo "[warn] flock not found; install with 'brew install flock' for concurrent-safe MEMORY.md registration." >&2
    echo "[warn] Proceeding under a single-run assumption." >&2
    max_num="$(max_memory_number "${MEMORY_FILE}")"
    next_num=$((max_num + 1))
    nnn="$(printf '%03d' "${next_num}")"
    printf '%s - %s\n' "${nnn}" "${ORIGIN}" >>"${MEMORY_FILE}"
    printf '%s\n' "${nnn}"
  fi
}

NNN="$(register_run)"
if [[ -z "${WORK_DIR_ARG}" ]]; then
  WORK_DIR="${repo_root}/work/${NNN}"
else
  WORK_DIR="${WORK_DIR_ARG}"
fi
mkdir -p "${WORK_DIR}"
SOURCE_MP4="${WORK_DIR}/source${NNN}.mp4"

echo "[1/8] Registered run ${NNN} in ${MEMORY_FILE}"
echo "[info] Work directory: ${WORK_DIR}"

if [[ "${SOURCE_INPUT}" =~ ^https?:// ]]; then
  echo "[2/8] Acquiring source from YouTube..."
  download_ok=0
  if [[ -n "${COOKIES_FILE}" ]]; then
    cookie_args=(--cookies "${COOKIES_FILE}")
  else
    cookie_args=(--cookies-from-browser "${COOKIE_BROWSER}")
  fi
  for selector in "bv*[height<=1080]+ba/b[height<=1080]" "bv*[height<=720]+ba/b[height<=720]" "18"; do
    echo "[info] Trying yt-dlp selector: ${selector}"
    if "${YTDLP}" -f "${selector}" --merge-output-format mp4 "${cookie_args[@]}" --remote-components ejs:github --extractor-args "youtube:player_client=web,mweb" -o "${SOURCE_MP4}" "${SOURCE_INPUT}"; then
      echo "[info] yt-dlp selector succeeded: ${selector}"
      download_ok=1
      break
    fi
  done
  if [[ "${download_ok}" != "1" ]]; then
    echo "Failed to download source after all yt-dlp fallback selectors." >&2
    exit 1
  fi
else
  echo "[2/8] Copying local source..."
  cp -f "${ORIGIN}" "${SOURCE_MP4}"
fi

echo "[3/8] Transcribing ${SOURCE_LANG} audio to SRT..."
"${WHISPER_BIN}" "${SOURCE_MP4}" --model "${WHISPER_MODEL}" --language "${SOURCE_LANG}" --task transcribe --output_format srt --output_dir "${WORK_DIR}"
if [[ ! -f "${WORK_DIR}/source${NNN}.srt" ]]; then
  echo "Expected Whisper output not found: ${WORK_DIR}/source${NNN}.srt" >&2
  exit 1
fi
mv "${WORK_DIR}/source${NNN}.srt" "${WORK_DIR}/source${NNN}.en.raw.srt"

echo "[4/8] Reviewing en.srt for Microsoft/Azure/GitHub product names..."
"${PYTHON_BIN}" "${SCRIPT_DIR}/correct_terms.py" \
  "${WORK_DIR}/source${NNN}.en.raw.srt" \
  "${WORK_DIR}/source${NNN}.en.srt"

echo "[5/8] Translating SRT to ${TARGET_LANG}..."
"${PYTHON_BIN}" "${SCRIPT_DIR}/translate_srt.py" "${WORK_DIR}/source${NNN}.en.srt" "${WORK_DIR}/source${NNN}.${TARGET_LANG}.raw.srt" --source "${SOURCE_LANG}" --target "${TARGET_LANG}"

echo "[6/8] QA on ${TARGET_LANG}.srt (product names, 높임말 speech level)..."
"${PYTHON_BIN}" "${SCRIPT_DIR}/qa_ko_srt.py" \
  "${WORK_DIR}/source${NNN}.${SOURCE_LANG}.srt" \
  "${WORK_DIR}/source${NNN}.${TARGET_LANG}.raw.srt" \
  "${WORK_DIR}/source${NNN}.${TARGET_LANG}.qa.srt" \
  --report "${WORK_DIR}/source${NNN}.${TARGET_LANG}.qa-report.txt"

echo "[info] Enforcing max 2 subtitle lines per cue..."
"${PYTHON_BIN}" "${SCRIPT_DIR}/wrap_srt.py" \
  "${WORK_DIR}/source${NNN}.${TARGET_LANG}.qa.srt" \
  "${WORK_DIR}/source${NNN}.${TARGET_LANG}.srt"

echo "[7/8] Burning ${TARGET_LANG} subtitles into the video (FontSize=${SUB_FONT_SIZE}, MarginV=${SUB_MARGIN_V}, max 2 lines)..."
"${FFMPEG}" -y -i "${SOURCE_MP4}" \
  -vf "subtitles=${WORK_DIR}/source${NNN}.${TARGET_LANG}.srt:force_style='FontName=${SUB_FONT},FontSize=${SUB_FONT_SIZE},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=0,MarginV=${SUB_MARGIN_V},WrapStyle=2'" \
  -c:v libx264 -pix_fmt yuv420p -c:a copy \
  "${WORK_DIR}/source${NNN}.subtitled.mp4"

has_audio_stream() {
  [[ -n "$("${FFPROBE}" -v error -select_streams a -show_entries stream=codec_type -of csv=p=0 "$1")" ]]
}

intro_needs_silence=0
outro_needs_silence=0
if ! has_audio_stream "${INTRO_CLIP}"; then
  intro_needs_silence=1
  echo "[info] Intro has no audio stream; synthesizing silent AAC during normalization."
fi
if ! has_audio_stream "${OUTRO_CLIP}"; then
  outro_needs_silence=1
  echo "[info] Outro has no audio stream; synthesizing silent AAC during normalization."
fi

echo "[8/8] Normalizing and concatenating..."
for pair in "intro:${INTRO_CLIP}" "main:${WORK_DIR}/source${NNN}.subtitled.mp4" "outro:${OUTRO_CLIP}"; do
  role="${pair%%:*}"
  src="${pair#*:}"
  synth_silence=0
  if [[ "${role}" == "intro" && "${intro_needs_silence}" == "1" ]]; then synth_silence=1; fi
  if [[ "${role}" == "outro" && "${outro_needs_silence}" == "1" ]]; then synth_silence=1; fi

  if [[ "${synth_silence}" == "1" ]]; then
    "${FFMPEG}" -y -i "${src}" -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000 -shortest \
      -vf "scale=1920:1080,fps=30" -c:v libx264 -pix_fmt yuv420p -c:a aac -ar 48000 -ac 2 \
      "${WORK_DIR}/norm_${NNN}_${role}.mp4"
  else
    "${FFMPEG}" -y -i "${src}" -vf "scale=1920:1080,fps=30" -c:v libx264 -pix_fmt yuv420p \
      -c:a aac -ar 48000 -ac 2 "${WORK_DIR}/norm_${NNN}_${role}.mp4"
  fi
done

CONCAT_LIST="${WORK_DIR}/concat_${NNN}.txt"
{
  echo "file 'norm_${NNN}_intro.mp4'"
  echo "file 'norm_${NNN}_main.mp4'"
  echo "file 'norm_${NNN}_outro.mp4'"
} >"${CONCAT_LIST}"

FINAL_OUTPUT="${repo_root}/outcome/final_output${NNN}.mp4"
(cd "${WORK_DIR}" && "${FFMPEG}" -y -f concat -safe 0 -i "concat_${NNN}.txt" -c copy "${FINAL_OUTPUT}")

probe_csv="$("${FFPROBE}" -v error -select_streams v:0 -show_entries stream=width,height -show_entries format=duration -of csv=p=0 "${FINAL_OUTPUT}")"
width="$(printf '%s\n' "${probe_csv}" | awk -F',' 'NF>=2 {print $1; exit}')"
height="$(printf '%s\n' "${probe_csv}" | awk -F',' 'NF>=2 {print $2; exit}')"
duration="$(printf '%s\n' "${probe_csv}" | awk -F',' 'NF==1 {print $1; exit}')"
if [[ -z "${duration}" ]]; then
  duration="$("${FFPROBE}" -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "${FINAL_OUTPUT}")"
fi
if [[ -n "${width}" && -n "${height}" ]]; then
  if (( width < 1280 || height < 720 )); then
    echo "[warn] Final output is below 1280x720 (${width}x${height}); the source may have been sub-HD." >&2
  fi
else
  echo "[warn] Could not determine final output resolution." >&2
fi
size="$(wc -c <"${FINAL_OUTPUT}" | tr -d ' ')"

echo "Done."
echo "NNN: ${NNN}"
echo "Source origin: ${ORIGIN}"
echo "Resolution: ${width:-unknown}x${height:-unknown}"
echo "Duration: ${duration:-unknown}"
echo "Size bytes: ${size}"
echo "Deliverable: ${FINAL_OUTPUT}"
