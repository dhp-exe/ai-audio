"""Lightweight Vietnamese text normalizer for TTS input (decision D1).

Goals, in order of importance:
    1. Unicode NFC (copy-pasted Vietnamese often mixes composed/decomposed diacritics; TTS engines
       mispronounce the decomposed form).
    2. Numbers -> words: cardinals, decimals, thousands separators, percent, currency (đồng, đô la),
       chat units (50k, 2tr), times (21h30, 9:05), dates (12/3, 12/03/2025), ordinals (thứ 4 -> thứ tư),
       phone-like digit strings read digit by digit.
    3. Common chat contractions -> full words (ko -> không, đc -> được, ...). Conservative list.
    4. Punctuation: dashes -> commas, curly quotes -> straight, whitespace collapse, ensure a
       terminal punctuation mark so the engine closes the phrase.

Audio tags in square brackets (e.g. "[sighs]") are preserved verbatim.

CLI: python -m pipeline.text.vi_normalize "Anh nợ em 1.500.000đ từ 21h30 hôm 12/3, ko quên đâu"
"""

from __future__ import annotations

import re
import sys
import unicodedata

UNITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
SCALES = ["", "nghìn", "triệu", "tỷ"]


def _read_three(n: int, full: bool) -> list[str]:
    """Read 0..999. `full` means a higher group precedes, so a zero hundreds digit is spoken."""
    h, t, u = n // 100, (n // 10) % 10, n % 10
    parts: list[str] = []
    if h > 0 or full:
        parts += [UNITS[h], "trăm"]
    if t == 0:
        if u > 0:
            if h > 0 or full:
                parts.append("lẻ")
            parts.append(UNITS[u])
    elif t == 1:
        parts.append("mười")
        if u == 5:
            parts.append("lăm")
        elif u > 0:
            parts.append(UNITS[u])
    else:
        parts += [UNITS[t], "mươi"]
        if u == 1:
            parts.append("mốt")
        elif u == 4:
            parts.append("tư")
        elif u == 5:
            parts.append("lăm")
        elif u > 0:
            parts.append(UNITS[u])
    return parts


def number_to_vi(n: int) -> str:
    if n < 0:
        return "âm " + number_to_vi(-n)
    if n == 0:
        return "không"
    if n >= 1_000_000_000_000:
        head, rest = divmod(n, 1_000_000_000)
        out = number_to_vi(head) + " tỷ"
        if rest:
            out += " " + _read_groups(rest, full=True)
        return out
    return _read_groups(n, full=False)


def _read_groups(n: int, full: bool) -> str:
    groups: list[int] = []
    while n > 0:
        groups.append(n % 1000)
        n //= 1000
    parts: list[str] = []
    started = full
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if g == 0:
            continue
        parts += _read_three(g, full=started)
        if SCALES[i]:
            parts.append(SCALES[i])
        started = True
    return " ".join(parts)


def _digits_to_vi(s: str) -> str:
    return " ".join(UNITS[int(c)] for c in s if c.isdigit())


def _parse_int(s: str) -> int:
    return int(re.sub(r"[.,\s]", "", s))


# --- regexes ----------------------------------------------------------------------------

_NUM = r"\d{1,3}(?:\.\d{3})+|\d+"  # 1.500.000 or plain digits
_DEC = rf"(?:{_NUM})(?:,\d{{1,2}})?"  # optional decimal comma with 1-2 digits

_TAG_SPLIT = re.compile(r"(\[[^\[\]]+\])")

CONTRACTIONS: dict[str, str] = {
    "ko": "không", "k": "không", "hok": "không", "hong": "không", "hông": "không", "kh": "không",
    "đc": "được", "dc": "được", "vs": "với", "bn": "bao nhiêu", "ntn": "như thế nào",
    "trc": "trước", "ng": "người", "nc": "nước", "đt": "điện thoại", "ms": "mới",
    "mn": "mọi người", "bt": "bình thường", "cx": "cũng", "ok": "ô kê", "oke": "ô kê",
    "j": "gì", "z": "vậy", "v": "vậy", "r": "rồi", "ah": "à", "uh": "ừ", "hum": "hôm",
    "nhìu": "nhiều", "iu": "yêu", "thik": "thích", "bik": "biết", "wa": "quá", "wá": "quá",
}
_CONTRACTION_RE = re.compile(
    r"(?<![\w\d])(" + "|".join(sorted(map(re.escape, CONTRACTIONS), key=len, reverse=True)) + r")(?![\w\d])",
    re.IGNORECASE,
)


def _num_words(s: str) -> str:
    """Read a cardinal with optional decimal comma."""
    if "," in s:
        whole, frac = s.split(",", 1)
        return f"{number_to_vi(_parse_int(whole))} phẩy {_digits_to_vi(frac) if frac.startswith('0') else number_to_vi(int(frac))}"
    return number_to_vi(_parse_int(s))


def normalize_numbers(text: str) -> str:
    # ordinals: thứ 1 -> thứ nhất, thứ 4 -> thứ tư, thứ 2 -> thứ hai
    def _ordinal(m: re.Match) -> str:
        n = int(m.group(1))
        return "thứ " + {1: "nhất", 4: "tư"}.get(n, number_to_vi(n))

    text = re.sub(r"\bthứ\s+(\d{1,2})\b", _ordinal, text, flags=re.IGNORECASE)

    # dates dd/mm or dd/mm/yyyy
    def _date(m: re.Match) -> str:
        d, mo, y = m.group(1), m.group(2), m.group(3)
        out = f"ngày {number_to_vi(int(d))} tháng {number_to_vi(int(mo))}"
        if y:
            out += f" năm {number_to_vi(int(y))}"
        return out

    text = re.sub(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{4}))?(?![\d/])", _date, text)

    # times 21h30, 9h, 9:05
    def _time(m: re.Match) -> str:
        h, mi = m.group(1), m.group(2)
        out = f"{number_to_vi(int(h))} giờ"
        if mi:
            out += f" {number_to_vi(int(mi))}" if int(mi) else ""
        return out

    text = re.sub(r"\b(\d{1,2})[h:](\d{2})?\b(?!\d)", _time, text)

    # percent
    text = re.sub(rf"({_DEC})\s*%", lambda m: f"{_num_words(m.group(1))} phần trăm", text)

    # currency: 1.500.000đ / 200k / 2tr / 3 tỷ / $5 / 5 USD
    text = re.sub(rf"({_DEC})\s*(?:đ|₫|vnđ|vnd|đồng)\b", lambda m: f"{_num_words(m.group(1))} đồng", text, flags=re.IGNORECASE)
    text = re.sub(rf"\$\s*({_DEC})", lambda m: f"{_num_words(m.group(1))} đô la", text)
    text = re.sub(rf"({_DEC})\s*(?:usd|đô la|đô)\b", lambda m: f"{_num_words(m.group(1))} đô la", text, flags=re.IGNORECASE)
    text = re.sub(rf"({_DEC})\s*k\b", lambda m: f"{_num_words(m.group(1))} nghìn", text)
    text = re.sub(rf"({_DEC})\s*(?:tr|triệu)\b", lambda m: f"{_num_words(m.group(1))} triệu", text, flags=re.IGNORECASE)
    text = re.sub(rf"({_DEC})\s*(?:tỷ|tỉ)\b", lambda m: f"{_num_words(m.group(1))} tỷ", text, flags=re.IGNORECASE)

    # phone-like strings (leading 0, 9-11 digits) -> digit by digit
    text = re.sub(r"\b0\d{8,10}\b", lambda m: _digits_to_vi(m.group(0)), text)

    # remaining cardinals (with thousands separators / decimal comma)
    text = re.sub(rf"(?<![\w])({_DEC})(?![\w])", lambda m: _num_words(m.group(1)), text)
    return text


def normalize_contractions(text: str) -> str:
    def _sub(m: re.Match) -> str:
        src = m.group(1)
        rep = CONTRACTIONS[src.lower()]
        return rep[0].upper() + rep[1:] if src[0].isupper() else rep

    return _CONTRACTION_RE.sub(_sub, text)


def normalize_punctuation(text: str) -> str:
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    text = re.sub(r"\s*[—–]\s*", ", ", text)
    text = re.sub(r"(?<!\.)\.{2}(?!\.)", "...", text)  # ".." -> "..."
    text = re.sub(r"\.{4,}", "...", text)
    text = re.sub(r"[*_#>]+", "", text)  # markdown residue
    text = re.sub(r"\s+([,.!?;:…])", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text and text[-1] not in ".!?…\"'":
        text += "."
    return text


def normalize_vi(text: str, *, numbers: bool = True, contractions: bool = True, punctuation: bool = True) -> str:
    """Full pipeline. Bracketed audio tags are left untouched."""
    text = unicodedata.normalize("NFC", text)
    out: list[str] = []
    for chunk in _TAG_SPLIT.split(text):
        if not chunk:
            continue
        if _TAG_SPLIT.fullmatch(chunk):
            out.append(chunk)
            continue
        if numbers:
            chunk = normalize_numbers(chunk)
        if contractions:
            chunk = normalize_contractions(chunk)
        out.append(chunk)
    text = "".join(out)
    if punctuation:
        text = normalize_punctuation(text)
    return text


if __name__ == "__main__":
    print(normalize_vi(" ".join(sys.argv[1:]) or sys.stdin.read()))
