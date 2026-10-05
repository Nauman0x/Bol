import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from normalize_ur import ONES, has_latin, int_to_words, normalize  # noqa: E402


def test_ones_table_complete():
    assert len(ONES) == 100
    assert len(set(ONES)) == 100
    assert ONES[0] == "صفر" and ONES[25] == "پچیس" and ONES[99] == "ننانوے"


def test_int_to_words():
    assert int_to_words(0) == "صفر"
    assert int_to_words(100) == "ایک سو"
    assert int_to_words(1500) == "ایک ہزار پانچ سو"
    assert int_to_words(100000) == "ایک لاکھ"
    assert int_to_words(12345678) == "ایک کروڑ تئیس لاکھ پینتالیس ہزار چھ سو اٹھہتر"


def test_numbers_in_text():
    assert normalize("میرے پاس 25 روپے ہیں۔") == "میرے پاس پچیس روپے ہیں۔"
    assert normalize("1,500") == "ایک ہزار پانچ سو"
    assert normalize("۱۲۳") == "ایک سو تئیس"
    assert normalize("3.14") == "تین اعشاریہ ایک چار"
    assert normalize("0300") == "صفر تین صفر صفر"


def test_symbols():
    assert normalize("50%") == "پچاس فیصد"
    assert normalize("Rs. 500") == "پانچ سو روپے"


def test_arabic_letters_mapped_to_urdu():
    # ك ت ا ب / ع ل ي  ->  ک ت ا ب / ع ل ی
    assert normalize("كتاب علي") == "کتاب علی"
    assert normalize("هے") == "ہے"


def test_tatweel_and_zero_width_removed():
    assert normalize("کـتاب‌") == "کتاب"


def test_punctuation():
    assert normalize("کیا حال ہے?") == "کیا حال ہے؟"
    assert normalize("ہاں , ٹھیک ہے .") == "ہاں، ٹھیک ہے۔"
    assert normalize("«واہ» (کیا بات ہے)!!") == "واہ کیا بات ہے!"


def test_diacritics_kept():
    assert normalize("اِس") == "اِس"


def test_latin_detected():
    assert has_latin(normalize("یہ WhatsApp ہے"))
    assert not has_latin(normalize("یہ کتاب ہے"))


def test_lexicon():
    assert normalize("اس کتاب", lexicon={"اس": "اِس"}) == "اِس کتاب"
