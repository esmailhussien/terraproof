"""Scope retrieval to requested work, not quoted copy or excluded operations.

This is deliberately a small lexical clause pass, not a general language parser.
The original prompt remains intact in the public query metadata.
"""

from __future__ import annotations

import re

from .text import normalize_arabic

_QUOTES = re.compile(r'"[^"\n]*"|“[^”\n]*”|«[^»\n]*»|(?<!\w)\'[^\'\n]+\'(?!\w)')
_EDITORIAL = re.compile(
    r"\b(?:rename|reword|proofread|translate|typo|button label|page heading|"
    r"(?:write|draft|rewrite|compose|edit)\s+(?:(?:a|an|the|short|brief|plain|text)\s+)*"
    r"(?:email|letter|message|document|memo|summary|paragraph|sentence|copy|announcement))\b"
    r"|(?:ترجم|صحح النص|راجع (?:دقه )?النص|صحح الاملاء|غير اسم|غير نص|تسميه الزر|عنوان الصفحه|"
    r"(?:اكتب|صغ|حرر|عد[لّ])\s+(?:لي\s+)?(?:رساله|بريد|مستند|ملخص|نص الزر|عنوان|فقره|جمله))", re.I)
# Punctuation and contrast delimit scope. A plain 'and' is intentionally not a
# boundary: 'do not download and process' excludes both operations.
_BOUNDARY = re.compile(r"[;؛.!?؟\n]+|,(?=\s)|\b(?:but|instead|then|however)\b|\b(?:لكن|بل|ثم|وبعدين)\b", re.I)
_NEGATIVE = re.compile(
    r"\b(?:do not|don't|never|without|no need to|not asking (?:you )?to|"
    r"not (?:to|using)|no|not|لا اريد|لا نريد|لا تقم ب|لا|بدون|دون|مش عايز|مش محتاج|ليس)\s+", re.I)
_OPERATION = re.compile(
    r"^(?:(?:any|a|an|the)\s+)?(?:use\b|using\b|run\b|execut\w*|comput\w*|calculat\w*|process\w*|download\w*|"
    r"search\w*|acquir\w*|fetch\w*|analy[sz]\w*|classif\w*|mask\w*|decod\w*|"
    r"calibrat\w*|convert\w*|reproject\w*|sampl\w*|plot\w*|draw\w*|build\w*|map\w*|"
    r"gis\b|python\b|geospatial\b|spatial\b|sar\b|stac\b|ndvi\b|"
    r"تستخدم|استخدم|تنفذ|تشغل|تشغيل|احسب|تحسب|حساب|حوسبه|معالج\w*|تحميل|تنزيل|تنزل|ابحث|بحث|تحليل|تصنيف|"
    r"قناع|ازاله|فك|تحويل|ترسم|ارسم|تبني|ابني|خريط\w*|خرائط|بايثون|نظم المعلومات الجغرافيه)", re.I)
_IMPLEMENTATION_ONLY = re.compile(r"^(?:python|بايثون)\b\s*", re.I)


def intent_text(task: str) -> str:
    """Keep affirmative clauses, including quoted identifiers used as operands.

    Editorial requests consume their own clause only. Thus a later affirmative
    domain operation survives a copy edit or a negative task in the same prompt.
    Negated descriptions ('raw DN, not reflectance') are not negative commands.
    """
    text = normalize_arabic(task)
    kept = []
    # A punctuation mark inside quoted copy is not a scope boundary. Keep quote
    # spans atomic rather than deleting quoted technical operands globally.
    quotes = list(_QUOTES.finditer(text))
    start = 0
    clauses = []
    for boundary in _BOUNDARY.finditer(text):
        if any(quote.start() <= boundary.start() < quote.end() for quote in quotes):
            continue
        clauses.append(text[start:boundary.start()])
        start = boundary.end()
    clauses.append(text[start:])
    for clause in clauses:
        # Quoted text cannot turn an editorial request into domain work. Outside
        # editorial clauses, quotes can be real operands (e.g. a band name).
        unquoted = _QUOTES.sub(" ", clause)
        if _EDITORIAL.search(unquoted):
            continue
        for match in _NEGATIVE.finditer(unquoted):
            tail = unquoted[match.end():].lstrip()
            directive = match.group().strip().lower() in {"do not", "don't", "never"}
            if directive or _OPERATION.match(tail):
                # A runtime constraint is not a ban on the remaining task.
                runtime = _IMPLEMENTATION_ONLY.match(tail)
                if runtime:
                    clause = unquoted[:match.start()] + tail[runtime.end():]
                else:
                    clause = unquoted[:match.start()]
                break
        kept.append(clause.strip(" ,:،"))
    return " ".join(part for part in kept if part).strip()
