#!/usr/bin/env python3
"""QA pass over a machine-translated Korean SRT.

Machine translation makes two systematic mistakes on Microsoft/Azure/GitHub
content:

1. **Product names get translated as common nouns.** Google Translate renders
   "Fabric" as 직물, "Copilot" as 부조종사, "Azure Friday" as 푸른 금요일,
   "Sentinel" as 보초. These are always wrong -- they are product names.
2. **Inconsistent speech level.** Output mixes 합쇼체 (~습니다), 해요체 (~해요)
   and 한다체/반말 (~한다). Subtitles should be uniformly 높임말, and the
   convention for narration is 합쇼체.

This script fixes both deterministically, then reports anything it could not
fix with confidence so a human or agent can eyeball a short list instead of
the whole file.

Product restoration is **context-gated**: a Korean word is only rewritten when
the aligned English cue actually contains the corresponding product name. That
is what keeps a genuine 직물 ("fabric" the textile) from being clobbered in a
cue that never mentioned the product.

Usage:
    qa_ko_srt.py <en.srt> <ko_in.srt> <ko_out.srt> [--report <path>]
    qa_ko_srt.py --self-test
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Product name restoration
# ---------------------------------------------------------------------------
# Key   = canonical English product name, and also the replacement text.
# Value = Korean renderings that must be rewritten back to the key.
# The key must appear in the aligned English cue for the rewrite to fire.
# Longer keys are checked first so "Azure Friday" wins over "Azure".

PRODUCTS: "dict[str, list[str]]" = {
    "Azure Friday": ["푸른 금요일", "블루 프라이데이", "하늘색 금요일"],
    "Azure OpenAI": ["푸른 오픈AI", "하늘색 오픈에이아이"],
    "Microsoft Fabric": ["마이크로소프트 직물", "마이크로소프트 패브릭"],
    "GitHub Copilot": ["깃허브 부조종사", "깃허브 코파일럿", "GitHub 부조종사"],
    "Pull Request": ["끌어오기 요청", "당기기 요청", "풀 리퀘스트", "풀 요청"],
    "Copilot Studio": ["부조종사 스튜디오", "코파일럿 스튜디오"],
    "Copilot Skills": ["코파일럿 기술", "부조종사 기술", "Copilot 기술"],
    "Copilot Skill": ["코파일럿 기술", "부조종사 기술", "Copilot 기술"],
    "WorkIQ": ["워크IQ", "워크 IQ", "작업 IQ", "업무 IQ"],
    "Power BI": ["파워 BI", "전력 BI", "파워비아이"],
    "Key Vault": ["키 금고", "열쇠 금고", "키 보관소"],
    "Front Door": ["정문", "현관문", "앞문"],
    "Service Bus": ["서비스 버스"],
    "Logic Apps": ["논리 앱", "로직 앱"],
    "Cosmos DB": ["코스모스 DB", "우주 DB"],
    "Visual Studio": ["비주얼 스튜디오", "시각 스튜디오"],
    "VS Code": ["VS 코드", "브이에스 코드"],
    "Data Factory": ["데이터 공장"],
    "Lakehouse": ["호수 집", "호수집", "레이크하우스"],
    "SharePoint": ["셰어포인트", "공유 지점", "쉐어포인트"],
    "OneDrive": ["원드라이브", "원 드라이브"],
    "Dataverse": ["데이터버스", "데이터 버스"],
    "Microsoft": ["마이크로소프트"],
    "GitHub": ["깃허브", "깃 허브"],
    "Copilot": ["부조종사", "코파일럿", "부기장"],
    "Fabric": ["직물", "천", "원단", "패브릭"],
    "Azure": ["푸른", "하늘색", "하늘빛", "청색", "애저"],
    "Sentinel": ["보초", "파수꾼", "감시자", "센티넬"],
    "Foundry": ["주조 공장", "주조공장", "파운드리", "제철소"],
    "Defender": ["수비수", "방어자", "디펜더", "수비자"],
    "Synapse": ["시냅스"],
    "Bicep": ["이두근", "이두박근"],
    "Blob": ["얼룩", "방울"],
    "Spark": ["불꽃", "스파크", "불똥"],
    "Outlook": ["전망", "아웃룩", "관점"],
    "Teams": ["팀즈", "팀스"],
    "Word": ["워드"],
    "Excel": ["엑셀", "탁월"],
    "Access": ["액세스"],
    "Purview": ["퍼뷰", "퍼브뷰"],
    "Entra": ["엔트라"],
    "Intune": ["인튠"],
    "Viva": ["비바"],
    "Loop": ["고리", "루프"],
    "Planner": ["기획자", "플래너"],
    "Dynamics": ["역학", "다이나믹스"],
    "Arc": ["호", "아크"],
    "Bastion": ["요새", "성채"],
    "Edge": ["가장자리", "모서리", "엣지"],
    "Windows": ["창문", "윈도우즈"],
    ".NET": ["그물", "닷넷"],
    "Sway": ["흔들림"],
    "Stream": ["개울", "시내"],
    "Forms": ["양식"],
    "Hub": ["중심지"],
    "Runbook": ["실행 책"],
    "Container Apps": ["컨테이너 앱"],
    "Playwright": ["극작가", "각본가", "플레이라이트"],
    # "agent" in this domain is a software agent. Google Translate reaches for
    # the human senses -- 상담원 (call-centre rep), 대리인 (legal proxy),
    # 요원 (operative) -- none of which is ever right here. Gated on a
    # capitalized "Agent", which Step 4 now produces for "Coding Agent" /
    # "Custom Agent" / "Agent Mode".
    "Agent": ["상담원", "대리인", "요원"],
    "Terraform": ["테라폼"],
    "Kusto": ["쿠스토"],
    "Grafana": ["그라파나"],
    "Prometheus": ["프로메테우스"],
    "Redis": ["레디스"],
    "Kafka": ["카프카"],
    "Snowflake": ["눈송이"],
    "Databricks": ["데이터브릭스"],
    "Postman": ["우체부", "집배원"],
    "Angular": ["앵귤러"],
    "React": ["리액트"],
    "Rust": ["러스트"],
    "Ruby": ["루비"],
}
# The English gate is case-sensitive by default, because Step 4 normalizes
# product casing and a lowercase word usually means the ordinary sense
# (fabric the textile, outlook the viewpoint). A few terms are exempt: their
# *Korean* mistranslation is impossible in developer content whatever the
# English casing. 상담원 is a call-centre representative and 대리인 a legal
# proxy -- neither is ever what "agent" means here, and Whisper writes the
# word lowercase most of the time, which would otherwise disable the fix.
CASE_INSENSITIVE_GATE = {"Agent"}

# Deliberately NOT in the lexicon: Go, Swift, Vue, Arc, Node.# Their Korean forms (가다, 빠른, 뷰, 호, 마디) are everyday words or short
# fragments of longer ones, so even a case-sensitive English gate produces
# false positives -- "Go ahead and pick up the CLI" is not the Go language.

# ---------------------------------------------------------------------------
# Speech level normalization: 반말 / 한다체 / 해요체  ->  합쇼체 (높임말)
# ---------------------------------------------------------------------------
# Applied only at sentence end (end of line, or before . ! ? ...), so we never
# touch these syllables mid-word. Longer patterns must precede shorter ones
# that are their suffixes (e.g. 있어요 before 어요, 이에요 before 에요).

HONORIFIC_RULES: "list[tuple[str, str]]" = [
    # --- 해요체 -> 합쇼체 ---
    ("이거예요", "이것입니다"),
    ("거예요", "것입니다"),
    ("거에요", "것입니다"),
    ("이에요", "입니다"),
    ("이예요", "입니다"),
    ("예요", "입니다"),
    ("에요", "입니다"),
    ("있어요", "있습니다"),
    ("없어요", "없습니다"),
    ("했어요", "했습니다"),
    ("됐어요", "됐습니다"),
    ("왔어요", "왔습니다"),
    ("갔어요", "갔습니다"),
    ("봤어요", "봤습니다"),
    ("몰라요", "모릅니다"),
    ("알아요", "압니다"),
    ("좋아요", "좋습니다"),
    ("많아요", "많습니다"),
    ("같아요", "같습니다"),
    ("고마워요", "고맙습니다"),
    ("반가워요", "반갑습니다"),
    # ~죠 / ~지요 is 해요체. 거죠 = 것이죠.
    ("이거죠", "이것입니다"),
    ("거죠", "것입니다"),
    ("겠죠", "겠습니다"),
    ("맞죠", "맞습니다"),
    ("하죠", "합니다"),
    ("되죠", "됩니다"),
    ("있죠", "있습니다"),
    ("없죠", "없습니다"),
    ("이죠", "입니다"),
    # --- plain propositive ~자 -> 합쇼체 propositive ~ㅂ시다 ---
    # Spelled out as whole verbs rather than conjugated from a generic "자"
    # suffix: 자 is an extremely productive noun ending (숫자, 사용자, 글자,
    # 참가자, 후보자), and a suffix rule would turn 참가자 into 참갑시다.
    # The bare stems 보자 / 하자 / 가자 are boundary-guarded below instead.
    ("물어보자", "물어봅시다"),
    ("살펴보자", "살펴봅시다"),
    ("알아보자", "알아봅시다"),
    ("해보자", "해봅시다"),
    ("시작하자", "시작합시다"),
    ("확인하자", "확인합시다"),
    ("들어가자", "들어갑시다"),
    ("만들자", "만듭시다"),
    # ~네요 is 해요체. Curated rather than conjugated from a generic "네요"
    # suffix, because a noun can end in 네 -- "우리 동네요" would otherwise be
    # mangled into "동합니다".
    ("보이네요", "보입니다"),
    ("좋네요", "좋습니다"),
    ("있네요", "있습니다"),
    ("없네요", "없습니다"),
    ("되네요", "됩니다"),
    ("하네요", "합니다"),
    ("나네요", "납니다"),
    ("돼요", "됩니다"),
    ("해요", "합니다"),
    ("줘요", "줍니다"),
    ("와요", "옵니다"),
    ("봐요", "봅니다"),
]

# Rules whose pattern can also appear as the tail of an already-polite ending
# must only fire as a standalone word. "가요" is the verb 가다, but "~ㄴ가요?"
# / "~는가요?" is a polite interrogative -- rewriting it produced "필요한갑니다?".
BOUNDARY_GUARDED = {"가요", "보자", "하자", "가자"}
HONORIFIC_RULES.append(("가요", "갑니다"))
# Bare propositive stems. Guarded to a standalone word so 후보자 does not
# become 후봅시다 and 참가자 does not become 참갑시다. "하자" is also the noun
# for "defect", which this guard does not disambiguate -- but a sentence that
# is only the word 하자 is vanishingly rare in these demos.
HONORIFIC_RULES.append(("보자", "봅시다"))
HONORIFIC_RULES.append(("하자", "합시다"))
HONORIFIC_RULES.append(("가자", "갑시다"))

# --- 한다체 / 반말 -> 합쇼체, by Hangul jamo arithmetic ---
#
# A curated word list can never cover every verb, so we conjugate properly.
# A Hangul syllable is  0xAC00 + (cho*21 + jung)*28 + jong,  and the plain
# sentence ender 다 attaches to a stem whose final syllable tells us which
# 합쇼체 form to build:
#
#   stem has no 받침      하다   -> 하 + ㅂ + 니다   = 합니다
#   stem ends in ㄴ       간다   -> 가 + ㅂ + 니다   = 갑니다   (ㄴ다 present)
#   stem ends in ㄹ       만들다 -> 만드 + ㅂ + 니다 = 만듭니다 (ㄹ elision)
#   stem ends in 는       먹는다 -> 먹 + 습니다      = 먹습니다
#   any other 받침        있다   -> 있 + 습니다      = 있습니다
#                        저질렀다 -> 저질렀 + 습니다 = 저질렀습니다

HANGUL_BASE = 0xAC00
HANGUL_LAST = 0xD7A3
JONG_COUNT = 28
JONG_NONE, JONG_N, JONG_L, JONG_B = 0, 4, 8, 17

# Tokens that merely end in the syllable 다 without being a plain-form verb:
# 마다 = "every", 보다 = "than". Rewriting these would corrupt the sentence.
NON_VERBAL_DA_TAILS = ("마다", "보다")


def _decompose(ch: str) -> "tuple[int, int, int] | None":
    code = ord(ch)
    if not (HANGUL_BASE <= code <= HANGUL_LAST):
        return None
    offset = code - HANGUL_BASE
    return offset // 588, (offset % 588) // JONG_COUNT, offset % JONG_COUNT


def _compose(cho: int, jung: int, jong: int) -> str:
    return chr(HANGUL_BASE + (cho * 21 + jung) * JONG_COUNT + jong)


def _is_propositive(text: str) -> bool:
    """True for the 합쇼체 propositive ~ㅂ시다 / ~읍시다 (봅시다, 합시다).

    Distinguished from the honorific ~시다 (하시다 -> 하십니다, which we *do*
    want to convert) by the ㅂ 받침 on the syllable before 시.
    """
    if not text.endswith("시다") or len(text) < 3:
        return False
    parts = _decompose(text[-3])
    return parts is not None and parts[2] == JONG_B


def _conjugate_plain(stem_and_da: str) -> "str | None":
    """Turn a plain-form clause ending in 다 into 합쇼체. None if not applicable."""
    if not stem_and_da.endswith("다") or len(stem_and_da) < 2:
        return None
    if stem_and_da.endswith("니다"):
        return None  # already 합쇼체 (입니다 / 습니다 / 겠습니다)
    if _is_propositive(stem_and_da):
        return None  # already 합쇼체 (봅시다 / 합시다 / 먹읍시다)
    if stem_and_da.endswith(NON_VERBAL_DA_TAILS):
        return None

    stem = stem_and_da[:-1]
    if stem.endswith("는") and len(stem) >= 2:
        return stem[:-1] + "습니다"

    parts = _decompose(stem[-1])
    if parts is None:
        return None
    cho, jung, jong = parts

    if jong == JONG_NONE:
        return stem[:-1] + _compose(cho, jung, JONG_B) + "니다"
    if jong in (JONG_N, JONG_L):
        return stem[:-1] + _compose(cho, jung, JONG_B) + "니다"
    return stem + "습니다"


# Matches a plain-form clause at sentence end: trailing Hangul run ending in 다.
PLAIN_CLAUSE_RE = re.compile(r"([가-힣]+다)(?=[.!?…]|\s*$)")

# Endings that are already acceptable 높임말; used to suppress false reports.
POLITE_TAIL = re.compile(
    r"(니다|니까|세요|십시오|시죠|죠|군요|네요|는데요|나요|가요|까요|어요|아요|해요|요)"
    r"[.!?\"'\)\]…]*$"
)

# A sentence still in plain form ends in 다 without the 니다 honorific marker.
PLAIN_TAIL = re.compile(r"(?<!니)다[.!?\"'\)\]…]*$")

SENTENCE_END = r"(?=[.!?…]|\s*$)"

# Interjection-style endings are complete utterances on their own and often
# appear mid-sentence before a comma ("고마워요, Copilot."), where
# SENTENCE_END would never fire. Only these are allowed to match a comma;
# widening SENTENCE_END globally would rewrite connective clauses, where
# 합쇼체 mid-sentence reads wrong.
CLAUSE_END_OK = {"고마워요", "반가워요"}
CLAUSE_END = r"(?=[.!?…,]|\s*$)"

# First-person pronouns carry register too: 높임말 narration uses the humble
# 저/제, not the plain 나/내. Left-anchored on a Hangul boundary so 하나는,
# 안내가 and 내용 are never touched.
#
# Bare possessive "내" is deliberately excluded: "회사 내 규정" means "within
# the company", not "my rules", and the two are not separable by pattern.
# "내 브라우저" is left as-is -- mildly informal but idiomatic in subtitles.
PRONOUN_RULES: "list[tuple[str, str]]" = [
    ("나는", "저는"),
    ("내가", "제가"),
    ("나를", "저를"),
    ("나도", "저도"),
    ("나의", "저의"),
    ("나와", "저와"),
]


def _apply_honorific(text: str) -> str:
    """Rewrite plain/informal sentence endings into 합쇼체."""
    for plain, polite in PRONOUN_RULES:
        text = re.sub(r"(?<![가-힣])" + plain, polite, text)

    for plain, polite in HONORIFIC_RULES:
        prefix = r"(?:(?<=^)|(?<=\s))" if plain in BOUNDARY_GUARDED else ""
        ending = CLAUSE_END if plain in CLAUSE_END_OK else SENTENCE_END
        text = re.sub(prefix + re.escape(plain) + ending, polite, text)

    def conjugate(m: "re.Match[str]") -> str:
        return _conjugate_plain(m.group(1)) or m.group(1)

    return PLAIN_CLAUSE_RE.sub(conjugate, text)


def _mentions_product(canonical: str, text: str) -> bool:
    """Word-boundary-aware English gate for the product lexicon.

    Plain substring matching let "Access" fire on "Accessibility" and would
    let "Arc" fire on "Architecture". \\b is unusable here because ".NET"
    starts with a non-word character, so we assert instead that the
    neighbouring characters are not alphanumeric.
    """
    flags = re.IGNORECASE if canonical in CASE_INSENSITIVE_GATE else 0
    # A trailing plural "s" still refers to the same product: "a team of
    # agents" must gate "Agent" just as "the agent" does. Without this,
    # 요원 survived in run 009 purely because the English said "agents".
    pattern = r"(?<![A-Za-z0-9])" + re.escape(canonical) + r"s?(?![A-Za-z0-9])"
    return re.search(pattern, text, flags) is not None


def _restore_products(ko: str, en: str) -> "tuple[str, list[str]]":
    """Rewrite mistranslated product names, gated on the English cue.

    The gate is **case-sensitive**: Step 4 (correct_terms.py) already
    normalized product-name casing in the English SRT, so a capitalized
    "Fabric" means the product while lowercase "fabric" means the textile.
    """
    notes: "list[str]" = []
    for canonical, wrong_forms in PRODUCTS.items():
        if not _mentions_product(canonical, en):
            continue
        for wrong in wrong_forms:
            # Left-anchored on a Hangul boundary so we never rewrite a
            # fragment of a longer word: 키워드 must not yield 키Word, and
            # 인터뷰 must not be touched. A trailing boundary is deliberately
            # NOT required, because Korean particles attach directly to the
            # noun (직물은, 직물을).
            pattern = r"(?<![가-힣])" + re.escape(wrong)
            if re.search(pattern, ko):
                ko = re.sub(pattern, canonical, ko)
                notes.append(f"{wrong} -> {canonical}")
    return ko, notes


# ---------------------------------------------------------------------------
# Korean particle agreement after a Latin-script word
# ---------------------------------------------------------------------------
# Substituting a Korean noun with an English one breaks particle agreement:
# "부조종사를" correctly becomes "Copilot을", not "Copilot를". Korean picks the
# particle by whether the preceding syllable ends in a consonant (받침).
#
# We approximate the Korean transliteration of an English word:
#   - final l / m / n  -> always closed   (Excel -> 엑셀, Sentinel -> 센티넬)
#   - final k / c / t  -> closed only after a vowel (Fabric -> 패브릭,
#     Copilot -> 코파일럿) but open after a consonant, because a consonant
#     cluster picks up an epenthetic vowel (Microsoft -> 마이크로소프트,
#     Spark -> 스파크, Arc -> 아크)
#   - everything else  -> open (Azure -> 애저, GitHub -> 깃허브, Word -> 워드)

PARTICLE_PAIRS = [
    ("을", "를"),
    ("은", "는"),
    ("이", "가"),
    ("과", "와"),
    ("으로", "로"),
    ("이라는", "라는"),
    ("이란", "란"),
]

_VOWELS = set("aeiouAEIOU")
_ALWAYS_CLOSED = set("lmnLMN")
_VOWEL_DEPENDENT = set("kctKCT")

_LATIN_PARTICLE_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9.+#]*)(" + "|".join(
        sorted({p for pair in PARTICLE_PAIRS for p in pair}, key=len, reverse=True)
    ) + r")"
)


def _ends_closed(word: str) -> bool:
    """True if the Korean reading of an English word ends in a 받침."""
    core = word.rstrip(".")
    if not core:
        return False
    last = core[-1]
    if last in _ALWAYS_CLOSED:
        return True
    if last in _VOWEL_DEPENDENT:
        return len(core) >= 2 and core[-2] in _VOWELS
    return False


def _fix_particles(text: str) -> str:
    """Make Korean particles agree with a preceding Latin-script word."""

    def repl(m: "re.Match[str]") -> str:
        word, particle = m.group(1), m.group(2)
        closed = _ends_closed(word)
        for after_consonant, after_vowel in PARTICLE_PAIRS:
            if particle in (after_consonant, after_vowel):
                return word + (after_consonant if closed else after_vowel)
        return m.group(0)

    return _LATIN_PARTICLE_RE.sub(repl, text)


# ---------------------------------------------------------------------------
# SRT parsing
# ---------------------------------------------------------------------------

class Cue:
    __slots__ = ("index", "timing", "lines")

    def __init__(self, index: str, timing: str, lines: "list[str]"):
        self.index = index
        self.timing = timing
        self.lines = lines

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def parse_srt(path: Path) -> "list[Cue]":
    raw = path.read_text(encoding="utf-8-sig")
    cues: "list[Cue]" = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip() != ""]
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        cues.append(Cue(lines[0].strip(), lines[1].strip(), lines[2:]))
    return cues


def write_srt(path: Path, cues: "list[Cue]") -> None:
    out = []
    for i, cue in enumerate(cues, start=1):
        out.append(f"{i}\n{cue.timing}\n{cue.text}\n")
    path.write_text("\n".join(out), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main QA pass
# ---------------------------------------------------------------------------

def qa(en_path: Path, ko_path: Path, out_path: Path, report_path: "Path | None") -> int:
    ko_cues = parse_srt(ko_path)
    en_cues = parse_srt(en_path) if en_path.exists() else []
    en_by_index = {c.index: c.text for c in en_cues}
    # Fall back to positional alignment when indices do not line up.
    en_by_pos = [c.text for c in en_cues]

    product_fixes = 0
    honorific_fixes = 0
    flagged: "list[str]" = []

    for pos, cue in enumerate(ko_cues):
        en_text = en_by_index.get(cue.index)
        if en_text is None:
            en_text = en_by_pos[pos] if pos < len(en_by_pos) else ""

        new_lines = []
        for line in cue.lines:
            original = line

            line, notes = _restore_products(line, en_text)
            if notes:
                line = _fix_particles(line)
                product_fixes += len(notes)
                flagged.append(
                    f"[cue {cue.index}] product: {', '.join(notes)}\n"
                    f"    en: {en_text.strip()}\n"
                    f"    ko: {original.strip()}\n"
                    f"    ->: {line.strip()}"
                )

            before_honorific = line
            line = _apply_honorific(line)
            if line != before_honorific:
                honorific_fixes += 1

            new_lines.append(line)

        cue.lines = new_lines

        # Report residual plain-form endings we did not dare auto-fix.
        for line in cue.lines:
            stripped = line.strip()
            bare = stripped.rstrip(".!?\"')]…")
            if bare.endswith(NON_VERBAL_DA_TAILS) or _is_propositive(bare):
                continue
            if PLAIN_TAIL.search(stripped) and not POLITE_TAIL.search(stripped):
                flagged.append(
                    f"[cue {cue.index}] speech level: still plain form (반말/한다체)\n"
                    f"    ko: {stripped}"
                )

        # Report product names present in English but absent from Korean.
        for canonical in PRODUCTS:
            if _mentions_product(canonical, en_text) and canonical.lower() not in cue.text.lower():
                flagged.append(
                    f"[cue {cue.index}] missing product name '{canonical}'\n"
                    f"    en: {en_text.strip()}\n"
                    f"    ko: {cue.text.strip()}"
                )
                break

    write_srt(out_path, ko_cues)

    summary = (
        f"[qa] cues={len(ko_cues)} product_fixes={product_fixes} "
        f"honorific_fixes={honorific_fixes} flagged={len(flagged)}"
    )
    print(summary)

    if report_path is not None:
        body = summary + "\n\n" + ("\n\n".join(flagged) if flagged else "No issues flagged.")
        report_path.write_text(body + "\n", encoding="utf-8")
        print(f"[qa] report written to {report_path}")

    return 0


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def self_test() -> int:
    cases = [
        # (english cue, korean cue, expected korean)
        ("This particular GQL is specifically Fabric.",
         "이 특정 GQL은 특히 직물입니다.",
         "이 특정 GQL은 특히 Fabric입니다."),
        ("Hey folks, I'm Scott. It's Azure Friday.",
         "안녕 친구들, 저는 스캇이에요. 푸른 금요일입니다.",
         "안녕 친구들, 저는 스캇입니다. Azure Friday입니다."),
        # Particle must agree: Copilot ends closed -> 을, not 를.
        ("So I can open my Copilot here.",
         "그래서 여기에서 내 부조종사를 열 수 있습니다.",
         "그래서 여기에서 내 Copilot을 열 수 있습니다."),
        # Particle must agree the other way: Azure ends open -> 는.
        ("Azure is a cloud platform.",
         "푸른은 클라우드 플랫폼이다.",
         "Azure는 클라우드 플랫폼입니다."),
        # Context gate: English says lowercase "fabric", so the textile
        # meaning must survive untouched.
        ("The fabric of the chair is soft.",
         "의자의 직물은 부드럽다.",
         "의자의 직물은 부드럽습니다."),
        # Speech level only.
        ("This works well.", "이것은 잘 작동한다.", "이것은 잘 작동합니다."),
        ("It is a database.", "그것은 데이터베이스이다.", "그것은 데이터베이스입니다."),
        ("Here we go.", "그럼 우리는 간다.", "그럼 우리는 갑니다."),
        # Also exercises the pronoun rule: 나는 -> 저는.
        ("I made a big mistake.", "나는 결국 큰 실수를 저질렀다.", "저는 결국 큰 실수를 저질렀습니다."),
        ("That is pretty cool.", "이것은 꽤 멋지다.", "이것은 꽤 멋집니다."),
        ("This is how we navigate.", "탐색할 수 있는 방법은 이렇다.", "탐색할 수 있는 방법은 이렇습니다."),
        ("You can build one.", "당신은 하나를 만든다.", "당신은 하나를 만듭니다."),
        # 마다 / 보다 are not plain-form verbs and must be left alone.
        ("Whenever you use an agent", "에이전트를 사용할 때마다", "에이전트를 사용할 때마다"),
        ("more than the Fabric tenant", "패브릭 임차인보다.", "Fabric 임차인보다."),
        # Already-polite endings must never be re-conjugated (입니다 -> 입닙니다).
        ("It is already polite.", "이미 존댓말입니다.", "이미 존댓말입니다."),
        ("We can do it.", "할 수 있습니다.", "할 수 있습니다."),
        ("I will do that.", "그렇게 하겠습니다.", "그렇게 하겠습니다."),
        # "~ㄴ가요?" is a polite interrogative, not the verb 가다.
        ("What kind of information do you need?",
         "어떤 종류의 정보가 필요한가요?", "어떤 종류의 정보가 필요한가요?"),
        ("Shall we go?", "그럼 가요.", "그럼 갑니다."),
        # ~ㅂ시다 is already 합쇼체 (propositive) -- must not become 봅십니다.
        ("Let's try it.", "시도해 봅시다.", "시도해 봅시다."),
        ("Let's do it.", "합시다.", "합시다."),
        # ...but the honorific ~시다 should still be conjugated.
        ("The teacher does it.", "선생님이 하시다.", "선생님이 하십니다."),
        # Playwright is a test tool, not a dramatist.
        ("We are burning down Playwright.", "극작가를 불태우고 있습니다.",
         "Playwright를 불태우고 있습니다."),
        # A bad form must not be matched inside a longer Hangul word.
        ("Give me the Word document.", "키워드를 알려주세요.", "키워드를 알려주세요."),
        ("Fabric is great.", "패브릭이 좋습니다.", "Fabric이 좋습니다."),
        # Interjection before a comma: SENTENCE_END would not fire here.
        (
            "Thanks, Copilot.",
            "고마워요, 코파일럿.",
            "고맙습니다, Copilot.",
        ),
        # A connective clause must NOT be rewritten before its comma.
        (
            "We work on it, and then we ship.",
            "우리는 작업해요, 그리고 배포합니다.",
            "우리는 작업해요, 그리고 배포합니다.",
        ),
        # "pull request" is capitalized by Step 4, so the gate fires.
        (
            "Copilot creates a Pull Request.",
            "Copilot이 끌어오기 요청을 생성합니다.",
            "Copilot이 Pull Request를 생성합니다.",
        ),
        # "Access" must not fire inside "Accessibility" (word-boundary gate).
        (
            "Accessibility is important, though,",
            "액세스 기능도 중요하지만",
            "액세스 기능도 중요하지만",
        ),
        # --- plain propositive ~자 -> ~ㅂ시다 (run 010: 물어보자) ---
        ("Let's ask Copilot.", "Copilot에게 물어보자.", "Copilot에게 물어봅시다."),
        ("Let's look at the code.", "코드를 살펴보자.", "코드를 살펴봅시다."),
        ("Let's start.", "이제 시작하자.", "이제 시작합시다."),
        ("Let's go.", "그럼 가자.", "그럼 갑시다."),
        # ...but a noun that merely ends in 자 must survive untouched.
        ("Here is the candidate.", "이 사람이 후보자.", "이 사람이 후보자."),
        ("That is the participant.", "그것이 참가자.", "그것이 참가자."),
        ("Count the characters.", "이것은 숫자.", "이것은 숫자."),
        # --- ~죠 is 해요체 (run 009: 거죠) ---
        ("That is the point.", "그게 핵심인 거죠.", "그게 핵심인 것입니다."),
        ("It will work.", "잘 되겠죠.", "잘 되겠습니다."),
        ("That is right.", "그게 맞죠.", "그게 맞습니다."),
        # --- product senses found in the fleet batch ---
        # "agent" here is software, never a call-centre rep or legal proxy.
        (
            "Select a different Coding Agent.",
            "다른 상담원을 선택하세요.",
            "다른 Agent를 선택하세요.",
        ),
        (
            "The Coding Agent runs it.",
            "대리인이 실행합니다.",
            "Agent가 실행합니다.",
        ),
        # ...a lowercase "agent" now ALSO fires, because 대리인/상담원 is never
        # the right reading in developer content. This is a deliberate
        # exemption from the case gate, not an oversight.
        (
            "the agent picks up the task",
            "대리인이 작업을 가져갑니다.",
            "Agent가 작업을 가져갑니다.",
        ),
        # WorkIQ must not be transliterated.
        ("Introducing WorkIQ.", "워크IQ를 소개합니다.", "WorkIQ를 소개합니다."),
        # Copilot Skills is a product; bare 기술 elsewhere must survive.
        (
            "This is about Copilot Skills.",
            "이것은 Copilot 기술에 대한 것입니다.",
            "이것은 Copilot Skills에 대한 것입니다.",
        ),
        (
            "He has strong engineering skills.",
            "그는 뛰어난 엔지니어링 기술을 가지고 있습니다.",
            "그는 뛰어난 엔지니어링 기술을 가지고 있습니다.",
        ),
        # A plural in English still names the product (run 009: "agents").
        (
            "A team of agents spotted the gap.",
            "한 팀의 요원이 공백을 발견했습니다.",
            "한 팀의 Agent가 공백을 발견했습니다.",
        ),
        # ~네요 / 같아요 are 해요체 and must become 합쇼체.        ("I see another one.", "또 다른 것도 보이네요.", "또 다른 것도 보입니다."),
        ("It seems they forgot.", "잊어버린 것 같아요.", "잊어버린 것 같습니다."),
        # A noun ending in 네 must survive the 네요 rules untouched.
        ("It's our neighborhood.", "우리 동네요.", "우리 동네요."),
        # First-person pronouns take the humble form in 높임말 narration.
        ("So I want to pay attention.", "그래서 나는 관심을 기울입니다.", "그래서 저는 관심을 기울입니다."),
        ("when Copilot detected what I write", "Copilot이 내가 쓰는 내용을 감지합니다.", "Copilot이 제가 쓰는 내용을 감지합니다."),
        # 하나는 / 안내가 / 내용 must not be mangled by the pronoun rules.
        ("One of them is important.", "하나는 중요합니다.", "하나는 중요합니다."),
        ("The guidance is helpful.", "안내가 유용합니다.", "안내가 유용합니다."),
    ]

    failures = 0
    for en, ko, expected in cases:
        got, notes = _restore_products(ko, en)
        if notes:
            got = _fix_particles(got)
        got = _apply_honorific(got)
        ok = got == expected
        status = "ok  " if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"{status} en={en!r}\n     ko={ko!r}\n     got={got!r}\n     exp={expected!r}")

    # 받침 detection drives particle choice; check it directly too.
    closed_expected = {
        "Fabric": True, "Copilot": True, "Excel": True, "Sentinel": True,
        "Azure": False, "GitHub": False, "Microsoft": False, "Word": False,
        "Spark": False, "Arc": False, "Teams": False, "Foundry": False,
    }
    for word, expect in closed_expected.items():
        got = _ends_closed(word)
        if got != expect:
            failures += 1
            print(f"FAIL _ends_closed({word!r}) = {got}, expected {expect}")

    total = len(cases) + len(closed_expected)
    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("en_srt", nargs="?", help="Corrected English SRT (alignment reference)")
    ap.add_argument("ko_srt", nargs="?", help="Machine-translated Korean SRT")
    ap.add_argument("out_srt", nargs="?", help="QA'd Korean SRT to write")
    ap.add_argument("--report", help="Optional path for the human-readable QA report")
    ap.add_argument("--self-test", action="store_true", help="Run built-in checks and exit")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if not (args.en_srt and args.ko_srt and args.out_srt):
        ap.error("en_srt, ko_srt and out_srt are required unless --self-test is given")

    return qa(
        Path(args.en_srt),
        Path(args.ko_srt),
        Path(args.out_srt),
        Path(args.report) if args.report else None,
    )


if __name__ == "__main__":
    sys.exit(main())
