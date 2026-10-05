"""Language id without extra packages. Script first, then Latin function words."""

from __future__ import annotations

import re

_SCRIPTS = (
    ("ar", re.compile(r"[\u0600-\u06FF]")),
    ("he", re.compile(r"[\u0590-\u05FF]")),
    ("fa", re.compile(r"[\u0600-\u06FF]")),  # disambiguated below
    ("ru", re.compile(r"[\u0400-\u04FF]")),
    ("uk", re.compile(r"[\u0400-\u04FF]")),
    ("el", re.compile(r"[\u0370-\u03FF]")),
    ("hy", re.compile(r"[\u0530-\u058F]")),
    ("ka", re.compile(r"[\u10A0-\u10FF]")),
    ("am", re.compile(r"[\u1200-\u137F]")),
    ("hi", re.compile(r"[\u0900-\u097F]")),
    ("bn", re.compile(r"[\u0980-\u09FF]")),
    ("ta", re.compile(r"[\u0B80-\u0BFF]")),
    ("th", re.compile(r"[\u0E00-\u0E7F]")),
    ("lo", re.compile(r"[\u0E80-\u0EFF]")),
    ("km", re.compile(r"[\u1780-\u17FF]")),
    ("my", re.compile(r"[\u1000-\u109F]")),
    ("ko", re.compile(r"[\uAC00-\uD7AF]")),
    ("ja", re.compile(r"[\u3040-\u30FF]")),
    ("zh", re.compile(r"[\u4E00-\u9FFF]")),
)

_CYR_UK = re.compile(r"[іїєґІЇЄҐ]")
_CYR_RU = re.compile(r"[ыэёъЫЭЁЪ]")
_AR_FA = re.compile(r"[پچژگ]")

_LATIN = {
    "de": ("und", "der", "die", "das", "nicht", "ein", "ist", "im", "den", "von", "zu", "mit", "auf", "für", "auch", "hat", "dem", "eine", "wurde", "nach", "sich", "bei", "als"),
    "fr": ("les", "des", "une", "est", "dans", "que", "pour", "qui", "pas", "sur", "par", "plus", "dans"),
    "es": ("los", "las", "una", "por", "que", "del", "con", "para", "está", "como", "más"),
    "pt": ("uma", "para", "não", "os", "as", "com", "por", "uma", "mais", "como"),
    "it": ("che", "non", "una", "per", "con", "sono", "dell", "come", "più"),
    "nl": ("het", "een", "van", "niet", "voor", "dat", "op", "aan", "ook"),
    "sv": ("och", "det", "att", "som", "för", "på", "är", "av"),
    "da": ("og", "det", "at", "ikke", "på", "er", "af", "til"),
    "nb": ("og", "det", "ikke", "på", "er", "til", "som"),
    "pl": ("nie", "się", "jest", "jak", "ale", "czy", "tylko"),
    "cs": ("že", "pro", "jako", "jsou", "nebo", "také"),
    "ro": ("sunt", "pentru", "unei", "este", "că"),
    "hu": ("hogy", "nem", "egy", "vagy", "meg"),
    "tr": ("bir", "ve", "için", "bu", "ile", "daha", "değil"),
    "id": ("yang", "dan", "tidak", "dengan", "untuk", "dari", "pada"),
    "ms": ("yang", "dan", "tidak", "dengan", "untuk", "dari"),
    "vi": ("không", "của", "trong", "một", "được", "các"),
    "en": ("the", "and", "of", "to", "in", "that", "for", "is", "on", "as"),
}

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def _script_guess(text: str) -> str | None:
    counts: dict[str, int] = {}
    for lang, rx in _SCRIPTS:
        n = len(rx.findall(text))
        if n:
            counts[lang] = counts.get(lang, 0) + n
    if not counts:
        return None
    # CJK: hiragana/katakana wins over han
    if counts.get("ja", 0) >= 4:
        return "ja"
    if counts.get("ko", 0) >= 4:
        return "ko"
    if counts.get("zh", 0) >= 8:
        return "zh"
    if counts.get("ru", 0) or counts.get("uk", 0):
        if _CYR_UK.search(text) and not _CYR_RU.search(text):
            return "uk"
        return "ru"
    if counts.get("ar", 0) or counts.get("fa", 0):
        if _AR_FA.search(text):
            return "fa"
        return "ar"
    return max(counts, key=counts.get)


def _latin_guess(text: str) -> str | None:
    words = [w.lower() for w in _WORD.findall(text)]
    if len(words) < 6:
        return None
    bag = set(words)
    scored = []
    for lang, stops in _LATIN.items():
        hit = sum(1 for s in stops if s in bag)
        if hit:
            scored.append((hit, lang))
    if not scored:
        return None
    scored.sort(reverse=True)
    if scored[0][0] < 2:
        return None
    return scored[0][1]


def detect(text: str, hint: str | None = None) -> str | None:
    hint = (hint or "").strip().lower()
    if hint and re.fullmatch(r"[a-z]{2}(-[a-z]+)?", hint):
        # keep as prior if the text is too short to override
        prior = hint[:2]
    else:
        prior = None
    if not text or not text.strip():
        return prior
    sample = text[:4000]
    script = _script_guess(sample)
    if script:
        return script
    latin = _latin_guess(sample)
    if latin:
        return latin
    letters = [c for c in sample if c.isalpha()]
    if letters and sum(1 for c in letters if c.isascii()) / len(letters) > 0.95:
        return prior or "en"
    return prior
