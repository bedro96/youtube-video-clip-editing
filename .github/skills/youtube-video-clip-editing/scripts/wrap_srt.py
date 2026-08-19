#!/usr/bin/env python3
"""Hard-cap SRT cues to at most 2 subtitle lines.

Uses a "display units" budget where CJK / full-width characters count as 2
and everything else as 1. This roughly approximates rendered width for
proportional fonts like Apple SD Gothic Neo at FontSize=24 on a 1920x1080
canvas.

Rules per cue text:
- Strip existing newlines and normalize whitespace.
- If total display width <= LINE_UNITS -> single line.
- Else if total <= 2 * LINE_UNITS -> split into exactly 2 balanced lines,
  preferring the last whitespace boundary at or before the midpoint.
- Else -> split the cue in time (proportional to display width), and recurse
  on each half. Timings are split at whitespace boundaries so words are not
  cut mid-token.

Guarantees: every emitted cue has 1 or 2 subtitle lines. No cue ever has 3
or more lines.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

LINE_UNITS = 46  # max display units per subtitle line (see module docstring)

TIMESTAMP_RE = re.compile(
    r"(\d\d):(\d\d):(\d\d),(\d\d\d)\s*-->\s*(\d\d):(\d\d):(\d\d),(\d\d\d)"
)


def _char_width(ch: str) -> int:
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


def display_width(text: str) -> int:
    return sum(_char_width(c) for c in text)


@dataclass
class Cue:
    start_ms: int
    end_ms: int
    text: str  # cleaned, single-line, whitespace-normalized

    @property
    def duration_ms(self) -> int:
        return max(1, self.end_ms - self.start_ms)


def _ts_to_ms(h: str, m: str, s: str, ms: str) -> int:
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms)


def _ms_to_ts(ms: int) -> str:
    ms = max(0, ms)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(content: str) -> list[Cue]:
    cues: list[Cue] = []
    blocks = re.split(r"\n\s*\n", content.strip())
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip() != ""]
        if len(lines) < 2:
            continue
        # Find the timing line (block might start with cue index or not).
        timing_idx = None
        for i, ln in enumerate(lines[:2]):
            if TIMESTAMP_RE.search(ln):
                timing_idx = i
                break
        if timing_idx is None:
            continue
        m = TIMESTAMP_RE.search(lines[timing_idx])
        if not m:
            continue
        start_ms = _ts_to_ms(*m.group(1, 2, 3, 4))
        end_ms = _ts_to_ms(*m.group(5, 6, 7, 8))
        text_lines = lines[timing_idx + 1 :]
        text = " ".join(" ".join(text_lines).split())
        if not text:
            continue
        cues.append(Cue(start_ms=start_ms, end_ms=end_ms, text=text))
    return cues


def _split_two_lines(text: str) -> tuple[str, str]:
    total = display_width(text)
    target = total // 2
    running = 0
    last_space = -1
    best_pos = -1
    best_delta = 10**9
    for i, ch in enumerate(text):
        running += _char_width(ch)
        if ch.isspace():
            last_space = i
            delta = abs(running - target)
            if delta < best_delta:
                best_delta = delta
                best_pos = i
    if best_pos != -1:
        return text[:best_pos].rstrip(), text[best_pos + 1 :].lstrip()
    # No whitespace at all (common for Korean). Hard-split by units.
    running = 0
    for i, ch in enumerate(text):
        running += _char_width(ch)
        if running >= target:
            return text[: i + 1], text[i + 1 :]
    return text, ""


def _split_text_at_midpoint(text: str) -> tuple[str, str]:
    """Split text at a whitespace boundary near the midpoint (unit-wise).

    Falls back to a hard character split if there is no whitespace. Used by
    the cue-splitter to keep words intact across time-split cues.
    """
    total = display_width(text)
    if total == 0:
        return text, ""
    target = total // 2
    running = 0
    best_pos = -1
    best_delta = 10**9
    for i, ch in enumerate(text):
        running += _char_width(ch)
        if ch.isspace():
            delta = abs(running - target)
            if delta < best_delta:
                best_delta = delta
                best_pos = i
    if best_pos != -1:
        left = text[:best_pos].rstrip()
        right = text[best_pos + 1 :].lstrip()
        return left, right
    # No whitespace -> hard split at unit target.
    running = 0
    for i, ch in enumerate(text):
        running += _char_width(ch)
        if running >= target:
            return text[: i + 1], text[i + 1 :]
    return text, ""


def wrap_cue(cue: Cue) -> list[Cue]:
    text = cue.text
    width = display_width(text)
    if width <= LINE_UNITS:
        return [Cue(cue.start_ms, cue.end_ms, text)]
    if width <= 2 * LINE_UNITS:
        top, bottom = _split_two_lines(text)
        if bottom:
            return [Cue(cue.start_ms, cue.end_ms, f"{top}\n{bottom}")]
        return [Cue(cue.start_ms, cue.end_ms, top)]

    # Overflow: split the cue in time so each half re-enters wrap_cue.
    left, right = _split_text_at_midpoint(text)
    if not right:
        # Genuine unsplittable single glyph - keep as one line rather than loop.
        return [Cue(cue.start_ms, cue.end_ms, text)]
    left_units = display_width(left)
    total_units = left_units + display_width(right)
    split_ratio = left_units / total_units if total_units else 0.5
    split_ms = cue.start_ms + int(round(cue.duration_ms * split_ratio))
    split_ms = max(cue.start_ms + 1, min(cue.end_ms - 1, split_ms))
    left_cue = Cue(cue.start_ms, split_ms, left)
    right_cue = Cue(split_ms, cue.end_ms, right)
    return wrap_cue(left_cue) + wrap_cue(right_cue)


def wrap_srt(input_srt: Path, output_srt: Path) -> int:
    content = input_srt.read_text(encoding="utf-8-sig")
    cues = parse_srt(content)
    wrapped: list[Cue] = []
    for cue in cues:
        wrapped.extend(wrap_cue(cue))

    out_lines: list[str] = []
    for i, cue in enumerate(wrapped, start=1):
        out_lines.append(str(i))
        out_lines.append(f"{_ms_to_ts(cue.start_ms)} --> {_ms_to_ts(cue.end_ms)}")
        out_lines.append(cue.text)
        out_lines.append("")

    output_srt.parent.mkdir(parents=True, exist_ok=True)
    output_srt.write_text("\n".join(out_lines).rstrip() + "\n", encoding="utf-8")
    return len(wrapped)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hard-cap SRT cues to at most 2 subtitle lines."
    )
    parser.add_argument("input_srt", type=Path)
    parser.add_argument("output_srt", type=Path)
    args = parser.parse_args()
    count = wrap_srt(args.input_srt, args.output_srt)
    print(f"wrote {args.output_srt} ({count} cues, max 2 lines each)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
