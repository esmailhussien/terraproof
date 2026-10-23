"""Deterministic tokenization, lightweight English stemming, and Arabic expansion."""

from __future__ import annotations

import re
import unicodedata

from .lexicon import ARABIC_NOISE, ARABIC_TERMS

STOPWORDS = frozenset("""
a an and are as at be been being by can could did do does for from had has have
how i if in into is it its me my of on or our should than that the their them then
there these they this those to use using was we were what when where which who
will with would you your please want need help tell about get make compute
calculate create build design implement show give work data file input output
before after also not without all any each just same example python code
fix error debug bug issue problem fail failure broken exception
""".split())
_ARABIC = re.compile(r"[\u0621-\u063a\u0641-\u064a\u066e-\u06d3]")
_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u0640]")
_FORMS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه"})
_WORDS = re.compile(r"[^\W_]+(?:_[^\W_]+)*", re.UNICODE)


def normalize_arabic(text: str) -> str:
    """Normalize matching forms only; never change the caller's original text."""
    return _DIACRITICS.sub("", unicodedata.normalize("NFKC", text)).translate(_FORMS)


def normalize(text: str) -> str:
    return " ".join(_WORDS.findall(normalize_arabic(text).lower()))


def stem(word: str) -> str:
    """Small conservative suffix stripper, identical for documents and queries."""
    if not word.isascii() or not word.isalpha():
        return word
    if len(word) > 5 and word.endswith("ies"):
        return word[:-3] + "y"
    for suffix in ("ing", "ed"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            base = word[:-len(suffix)]
            if len(base) > 2 and base[-1] == base[-2] and base[-1] not in "lsz":
                base = base[:-1]
            # Keep common silent-e forms compatible (e.g. resampled/resample).
            return base[:-1] if base.endswith("e") else base
    if len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    if len(word) > 4 and word.endswith("e"):
        word = word[:-1]
    return word


_NOISE = frozenset(normalize_arabic(word) for word in ARABIC_NOISE)


def tokenize(text: str) -> list[str]:
    words = normalize(text).split()
    return [stem(word) for word in words if word not in STOPWORDS and word not in _NOISE and len(word) > 1]


def _arabic_variants(word: str) -> set[str]:
    """Allow stacked attached articles, conjunctions and prepositions, not substrings."""
    forms = {word}
    for form in tuple(forms):
        if form[0] in "وف" and len(form) > 3:
            forms.add(form[1:])
    for form in tuple(forms):
        for prefix in ("وال", "فال", "بال", "لل", "ال"):
            if form.startswith(prefix) and len(form) > len(prefix) + 2:
                forms.add(form[len(prefix):])
    for form in tuple(forms):
        if form[0] in "بل" and len(form) > 3:
            forms.add(form[1:])
    # Possessive pronouns attach to nouns after their article/preposition prefixes.
    # Keep whole-word variants and let the curated lexicon validate each candidate;
    # do not strip arbitrary Arabic plurals or match interior substrings.
    for form in tuple(forms):
        for suffix in ("هما", "هم", "هن", "ها", "نا", "كم", "كن", "ه", "ك", "ي"):
            if form.endswith(suffix) and len(form) > len(suffix) + 2:
                base = form[:-len(suffix)]
                forms.add(base)
                # ة becomes ت before an attached pronoun: مساحتها -> مساحة.
                if base.endswith("ت"):
                    forms.add(base[:-1] + "ه")
    return forms


def _plural_bases(forms: set[str]) -> set[str]:
    """Sound plural and dual bases, used only when a word has no direct lexicon form."""
    bases = set()
    for form in forms:
        for suffix in ("ات", "ين", "ون", "ان"):
            if form.endswith(suffix) and len(form) > len(suffix) + 2:
                bases.add(form[:-len(suffix)])
                if suffix == "ات":
                    bases.add(form[:-2] + "ه")
    return bases


def expand_query(task: str) -> tuple[dict, list[str], list[str]]:
    """Return API query metadata, retrieval tokens, and translation explanations."""
    normalized = normalize(task)
    words = normalized.split()
    variants = [_arabic_variants(word) if _ARABIC.search(word) else {word} for word in words]
    # A word that is itself a lexicon entry keeps its own expansion only.
    single_keys = {normalize(phrase) for phrase in ARABIC_TERMS if " " not in normalize(phrase)}
    variants = [forms | _plural_bases(forms) if _ARABIC.search(word) and not forms & single_keys else forms
                for word, forms in zip(words, variants)]
    expanded: list[str] = []
    reasons = []
    # Longest phrases first, then lexical order: overlapping terms are deduplicated.
    for phrase, english in sorted(ARABIC_TERMS.items(), key=lambda item: (-len(normalize(item[0]).split()), item[0])):
        parts = normalize(phrase).split()
        if any(all(part in variants[start + j] for j, part in enumerate(parts))
               for start in range(len(words) - len(parts) + 1)):
            reasons.append(f"Arabic lexicon: {phrase} -> {english}")
            for word in normalize(english).split():
                if word not in expanded:
                    expanded.append(word)
    tokens = sorted(set(tokenize(normalized + " " + " ".join(expanded))))
    query = {
        "text": task,
        "normalized": normalized,
        "language": "ar" if _ARABIC.search(normalized) else "en",
        "expanded_terms": expanded,
    }
    return query, tokens, reasons
