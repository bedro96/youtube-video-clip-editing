#!/usr/bin/env python3
"""Correct Microsoft / Azure / GitHub product-name spellings in an SRT file.

Applies a deterministic, case-insensitive-match / correctly-cased-replace
lexicon so that names like "Microsoft", "Azure", "GitHub", "Copilot",
"VS Code", ".NET", etc. are never left as generic-looking lowercase tokens
in the transcribed English subtitles. Runs before translation so the
translated Korean SRT inherits the corrections.

Longer phrases (e.g. "GitHub Copilot", "Microsoft Azure") are applied before
their single-word components so bigram corrections win.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Order matters: longer / more specific phrases first.
CORRECTIONS: list[tuple[str, str]] = [
    ("microsoft azure", "Microsoft Azure"),
    ("azure openai", "Azure OpenAI"),
    ("azure devops", "Azure DevOps"),
    ("azure functions", "Azure Functions"),
    ("azure kubernetes service", "Azure Kubernetes Service"),
    ("azure ai foundry", "Azure AI Foundry"),
    ("azure ai search", "Azure AI Search"),
    ("azure ai", "Azure AI"),
    ("github copilot", "GitHub Copilot"),
    ("github actions", "GitHub Actions"),
    ("github enterprise", "GitHub Enterprise"),
    ("github codespaces", "GitHub Codespaces"),
    ("visual studio code", "Visual Studio Code"),
    ("visual studio", "Visual Studio"),
    ("vs code", "VS Code"),
    ("vscode", "VS Code"),
    ("power bi", "Power BI"),
    ("power platform", "Power Platform"),
    ("power automate", "Power Automate"),
    ("power apps", "Power Apps"),
    ("microsoft fabric", "Microsoft Fabric"),
    ("microsoft 365", "Microsoft 365"),
    ("office 365", "Microsoft 365"),
    ("sql server", "SQL Server"),
    ("windows server", "Windows Server"),
    ("windows", "Windows"),
    ("microsoft", "Microsoft"),
    ("azure", "Azure"),
    ("github", "GitHub"),
    ("co-pilot", "Copilot"),
    ("co pilot", "Copilot"),
    ("copilot", "Copilot"),
    (".net", ".NET"),
    ("dotnet", ".NET"),
    ("powershell", "PowerShell"),
    ("typescript", "TypeScript"),
    ("javascript", "JavaScript"),
    ("openai", "OpenAI"),
    ("chatgpt", "ChatGPT"),
    ("kubernetes", "Kubernetes"),
    ("docker", "Docker"),
    ("linux", "Linux"),
    ("macos", "macOS"),
    ("ios", "iOS"),
    ("android", "Android"),
]


def _escape_and_boundaries(term: str) -> re.Pattern[str]:
    escaped = re.escape(term)
    # Use lookarounds instead of \b so terms starting/ending with '.'
    # (like ".net") still match at word edges.
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)


COMPILED: list[tuple[re.Pattern[str], str]] = [
    (_escape_and_boundaries(src), dst) for src, dst in CORRECTIONS
]


def _looks_like_srt_metadata(line: str) -> bool:
    if not line.strip():
        return True
    if line.strip().isdigit():
        return True
    if "-->" in line:
        return True
    return False


def correct_text(text: str) -> str:
    corrected = text
    for pattern, replacement in COMPILED:
        corrected = pattern.sub(replacement, corrected)
    return corrected


def correct_srt(input_srt: Path, output_srt: Path) -> int:
    lines = input_srt.read_text(encoding="utf-8-sig").splitlines()
    changed_lines = 0
    corrected_lines: list[str] = []
    for line in lines:
        if _looks_like_srt_metadata(line):
            corrected_lines.append(line)
            continue
        new_line = correct_text(line)
        if new_line != line:
            changed_lines += 1
        corrected_lines.append(new_line)

    output_srt.parent.mkdir(parents=True, exist_ok=True)
    output_srt.write_text("\n".join(corrected_lines) + "\n", encoding="utf-8")
    return changed_lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Fix Microsoft/Azure/GitHub product names in an SRT.")
    parser.add_argument("input_srt", type=Path)
    parser.add_argument("output_srt", type=Path)
    args = parser.parse_args()

    changed = correct_srt(args.input_srt, args.output_srt)
    print(f"corrected {changed} line(s) in {args.output_srt}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
