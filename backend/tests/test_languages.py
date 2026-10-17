"""Language profiles: the layers resolve, and they reproduce the rules the
pipeline had before they were centralised (scattered `if lang in (...)`)."""
import pytest

from yomeru.config import languages as L


def test_layers_general_script_language():
    es, ja, ko = L.profile("Spanish"), L.profile("Japanese"), L.profile("Korean")
    assert (es.script, es.hyphenation, es.ocr_codes) == ("latin", "es", ("es", "en"))
    assert es.stack_shouts and es.ocr_boxes and not es.reads_right_to_left    # from GENERAL/latin
    assert ja.ocr_engine == "manga_ocr" and ja.reads_right_to_left and not ja.ocr_boxes and ja.hyphenation is None
    assert ko.script == "hangul" and not ko.reads_right_to_left and not ko.ocr_boxes


def test_previous_rules_are_reproduced():
    # reading direction (was: source in japanese / chinese (traditional))
    assert [n for n in L.LANGUAGES if L.profile(n).reads_right_to_left] == ["Japanese", "Chinese (Traditional)"]
    # page OCR with boxes (was: not in japanese/korean/chinese*)
    assert {n for n in L.LANGUAGES if not L.profile(n).ocr_boxes} == {
        "Japanese", "Korean", "Chinese (Simplified)", "Chinese (Traditional)"}
    # unknown / auto → general (was: LANG_MAP default en_US, OCR codes en/es/pt)
    assert L.profile("Klingon").hyphenation == "en_US" and L.profile(None).ocr_codes == ("en", "es", "pt")


def test_text_rules_follow_the_written_script():
    assert L.text_rules("¡MAGNÍFICO!").stack_shouts
    assert L.text_rules("天才も恋には").vertical_native and not L.text_rules("天才も恋には").stack_shouts
    assert L.text_rules("안녕하세요").script == "hangul"


def test_a_typo_in_a_profile_fails_loudly():
    with pytest.raises(ValueError):
        L._build("X", "latin", {"stack_shout": True})
