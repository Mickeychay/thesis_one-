import pytest
from h2l.core import calculate_sentence_polarity, DEFAULT_CONFIG_V3, H2LConfigV3


def test_thai_negation_compound_unpunctuated():
    """
    Test that negation is correctly detected even in unpunctuated compound sentences,
    and earlier tone exceptions do not swallow subsequent negations.
    """
    prob_depression = {'name': 'โรคซึมเศร้า', 'keywords': ['ซึมเศร้า'], 'severity': 3}
    
    # Case 1: 'ผู้ป่วยไม่ได้พักผ่อนไม่ได้ซึมเศร้า'
    # 'ไม่ได้พักผ่อน' is a tone exception, but 'ไม่ได้ซึมเศร้า' IS negated.
    text1 = 'ผู้ป่วยไม่ได้พักผ่อนไม่ได้ซึมเศร้า'
    res1 = calculate_sentence_polarity(prob_depression, text1, DEFAULT_CONFIG_V3)
    assert res1['gate_neg'] <= 0.4, f"Expected gate_neg <= 0.4 for negated depression, got {res1['gate_neg']}"

    # Case 2: 'ผู้ป่วยไม่ได้ซึมเศร้าไม่ได้พักผ่อน'
    text2 = 'ผู้ป่วยไม่ได้ซึมเศร้าไม่ได้พักผ่อน'
    res2 = calculate_sentence_polarity(prob_depression, text2, DEFAULT_CONFIG_V3)
    assert res2['gate_neg'] <= 0.4, f"Expected gate_neg <= 0.4 for negated depression, got {res2['gate_neg']}"

    # Case 3: Positive symptom without negation
    text3 = 'ผู้ป่วยมีอาการซึมเศร้าและนอนไม่หลับ'
    res3 = calculate_sentence_polarity(prob_depression, text3, DEFAULT_CONFIG_V3)
    assert res3['gate_neg'] >= 0.9, f"Expected gate_neg >= 0.9 for positive depression, got {res3['gate_neg']}"


def test_tone_exceptions_bypass_penalty():
    """
    Test that actual tone exception phrases (e.g. ไม่มีเงิน, ไม่ได้พักผ่อน)
    do not get penalized as problem negation.
    """
    prob_poverty = {'name': 'ปัญหาความยากจน', 'keywords': ['เงิน', 'รายได้'], 'severity': 3}
    text = 'ครอบครัวไม่มีเงินและไม่มีรายได้'
    res = calculate_sentence_polarity(prob_poverty, text, DEFAULT_CONFIG_V3)
    # 'ไม่มีเงิน' and 'ไม่มีรายได้' are tone exceptions for poverty (indicating problem exists, not denied)
    assert res['gate_neg'] >= 0.9, f"Expected gate_neg >= 0.9 for tone exception, got {res['gate_neg']}"


def test_adversarial_denials():
    """
    Test explicit denials on sensitive codes.
    """
    prob_suicide = {'name': 'พยายามฆ่าตัวตาย', 'keywords': ['ฆ่าตัวตาย'], 'severity': 4}
    text = 'ผู้รับบริการยืนยันว่าไม่ได้คิดฆ่าตัวตาย'
    res = calculate_sentence_polarity(prob_suicide, text, DEFAULT_CONFIG_V3)
    assert res['gate_neg'] <= 0.4, f"Expected gate_neg <= 0.4 for explicit denial, got {res['gate_neg']}"
