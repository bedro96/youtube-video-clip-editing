#!/usr/bin/env python3
"""Translate SRT subtitle cue text while preserving indices and timings."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from deep_translator import GoogleTranslator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Translate SRT subtitle text lines with deep-translator."
    )
    parser.add_argument("input_srt", type=Path, help="Source SRT file")
    parser.add_argument("output_srt", type=Path, help="Translated SRT destination")
    parser.add_argument("--source", default="en", help="Source language code (default: en)")
    parser.add_argument("--target", default="ko", help="Target language code (default: ko)")
    return parser.parse_args()


def translate_cue_text(
    translator: GoogleTranslator, cue_index: str, text_lines: list[str]
) -> list[str]:
    text = "\n".join(text_lines).strip()
    if not text:
        return text_lines

    try:
        translated = translator.translate(text)
    except Exception as exc:  # deep-translator surfaces provider/network errors broadly.
        print(f"[warn] cue {cue_index} translate failed: {exc}", file=sys.stderr)
        return text_lines

    if not translated:
        print(f"[warn] cue {cue_index} translated to empty text; keeping source", file=sys.stderr)
        return text_lines
    return str(translated).splitlines() or [str(translated)]


def translate_srt(input_srt: Path, output_srt: Path, source: str, target: str) -> int:
    content = input_srt.read_text(encoding="utf-8-sig")
    stripped = content.strip()
    if not stripped:
        output_srt.write_text("", encoding="utf-8")
        return 0

    translator = GoogleTranslator(source=source, target=target)
    blocks = re.split(r"\n\s*\n", stripped)
    translated_blocks: list[str] = []

    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3:
            translated_blocks.append(block)
            continue

        cue_index, timing = lines[0], lines[1]
        translated_lines = translate_cue_text(translator, cue_index, lines[2:])
        translated_blocks.append("\n".join([cue_index, timing] + translated_lines))

    output_srt.parent.mkdir(parents=True, exist_ok=True)
    output_srt.write_text("\n\n".join(translated_blocks) + "\n", encoding="utf-8")
    return len(translated_blocks)


def main() -> int:
    args = parse_args()
    cue_count = translate_srt(args.input_srt, args.output_srt, args.source, args.target)
    print(f"wrote {args.output_srt} ({cue_count} cues)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
