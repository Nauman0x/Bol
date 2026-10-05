"""Urdu text normalisation for TTS training and inference.

Use the same function at training time (prepare_dataset.py) and at inference
time (synth.py), otherwise the model sees text it was never trained on.

    from normalize_ur import normalize, has_latin
    normalize("میرے پاس 25 روپے ہیں.")  ->  "میرے پاس پچیس روپے ہیں۔"
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

# Urdu cardinals 0-99 are irregular, so they are listed rather than composed.
ONES = (
    "صفر ایک دو تین چار پانچ چھ سات آٹھ نو "
    "دس گیارہ بارہ تیرہ چودہ پندرہ سولہ سترہ اٹھارہ انیس "
    "بیس اکیس بائیس تئیس چوبیس پچیس چھبیس ستائیس اٹھائیس انتیس "
    "تیس اکتیس بتیس تینتیس چونتیس پینتیس چھتیس سینتیس اڑتیس انتالیس "
    "چالیس اکتالیس بیالیس تینتالیس چوالیس پینتالیس چھیالیس سینتالیس اڑتالیس انچاس "
    "پچاس اکیاون باون ترپن چون پچپن چھپن ستاون اٹھاون انسٹھ "
    "ساٹھ اکسٹھ باسٹھ تریسٹھ چونسٹھ پینسٹھ چھیاسٹھ سڑسٹھ اڑسٹھ انہتر "
    "ستر اکہتر بہتر تہتر چوہتر پچھتر چھہتر ستتر اٹھہتر اناسی "
    "اسی اکیاسی بیاسی تراسی چوراسی پچاسی چھیاسی ستاسی اٹھاسی نواسی "
    "نوے اکانوے بانوے ترانوے چورانوے پچانوے چھیانوے ستانوے اٹھانوے ننانوے"
).split()

SCALES = [
    (10**9, "ارب"),
    (10**7, "کروڑ"),
    (10**5, "لاکھ"),
    (10**3, "ہزار"),
    (10**2, "سو"),
]
MAX_SPOKEN_INT = 10**11  # above this (or with leading zeros) digits are read one by one

# Arabic code points that look the same as the Urdu ones but are different characters.
CHAR_MAP = str.maketrans(
    {
        "ي": "ی",  # ي -> ی
        "ى": "ی",  # ى -> ی
        "ك": "ک",  # ك -> ک
        "ه": "ہ",  # ه -> ہ
        "ة": "ہ",  # ة -> ہ
        "٪": "%",  # ٪
        "٬": ",",  # ٬ thousands separator
        "٫": ".",  # ٫ decimal separator
        "₨": "Rs ",  # ₨
    }
)
DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
PUNCT_MAP = str.maketrans({".": "۔", ",": "،", "?": "؟", ";": "؛", ":": "،"})

PUNCT = "۔،؟!؛"
_PRESENTATION_FORMS = re.compile(r"[ﭐ-﷿ﹰ-ﻼ]+")
_INVISIBLE = re.compile(r"[ـ​-‏‪-‮⁠-⁤﻿]")
_NUMBER = re.compile(r"\d+(?:,\d+)*(?:\.\d+)?")
_RUPEES = re.compile(r"\bRs\.?\s*(\d+(?:,\d+)*(?:\.\d+)?)", re.IGNORECASE)
_DISALLOWED = re.compile(r"[^؀-ۿA-Za-z!\s]")
_PUNCT_RUN = re.compile(rf"\s*([{PUNCT}])[\s{PUNCT}]*")
_TOKEN_SPLIT = re.compile(rf"(\s+|[{PUNCT}])")
_LATIN = re.compile(r"[A-Za-z]")


def int_to_words(n: int) -> str:
    parts = []
    for value, name in SCALES:
        q, n = divmod(n, value)
        if q:
            parts.append(f"{int_to_words(q)} {name}")
    if n or not parts:
        parts.append(ONES[n])
    return " ".join(parts)


def _spell_digits(digits: str) -> str:
    return " ".join(ONES[int(d)] for d in digits)


def number_to_words(token: str) -> str:
    """'1,500' -> 'ایک ہزار پانچ سو', '3.14' -> 'تین اعشاریہ ایک چار'."""
    whole, _, frac = token.replace(",", "").partition(".")
    if (len(whole) > 1 and whole[0] == "0") or int(whole) >= MAX_SPOKEN_INT:
        words = _spell_digits(whole)
    else:
        words = int_to_words(int(whole))
    if frac:
        words += " اعشاریہ " + _spell_digits(frac)
    return words


def load_lexicon(path: str | Path) -> dict[str, str]:
    """TSV of word<TAB>replacement, e.g. an undiacritised word and its diacritised
    spelling, to fix words the phonemizer mispronounces. Lines starting with # are skipped."""
    lexicon = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        word, _, replacement = line.partition("\t")
        if replacement:
            lexicon[word.strip()] = replacement.strip()
    return lexicon


def normalize(text: str, lexicon: dict[str, str] | None = None) -> str:
    text = _PRESENTATION_FORMS.sub(lambda m: unicodedata.normalize("NFKC", m.group()), text)
    text = unicodedata.normalize("NFC", text)
    text = _INVISIBLE.sub("", text)
    text = text.translate(CHAR_MAP).translate(DIGIT_MAP)

    text = _RUPEES.sub(r"\1 روپے", text)
    text = text.replace("%", " فیصد ").replace("&", " اور ")
    text = _NUMBER.sub(lambda m: f" {number_to_words(m.group())} ", text)

    text = text.translate(PUNCT_MAP)
    text = _DISALLOWED.sub(" ", text)

    if lexicon:
        text = "".join(lexicon.get(tok, tok) for tok in _TOKEN_SPLIT.split(text))

    text = _PUNCT_RUN.sub(r"\1 ", text)
    return re.sub(r"\s+", " ", text).strip()


def has_latin(text: str) -> bool:
    return bool(_LATIN.search(text))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    lines = sys.argv[1:] or sys.stdin.read().splitlines()
    for line in lines:
        print(normalize(line))
