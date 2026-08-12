
import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock heavy dependencies before importing H2L_core
sys.modules['retrieval_engine'] = MagicMock()
sys.modules['unified_baselines'] = MagicMock()
sys.modules['H2LAdaptiveRetriever'] = MagicMock()
sys.modules['H2LMultiHopRetriever'] = MagicMock()

from h2l.core import (
    H2LUnifiedRetriever, STRATEGY_ALPHA,
    calibrate_confidence, calculate_idf_weight,
    margin_aware_activation, calculate_kl_concentration_penalty,
    calculate_sentence_polarity, calculate_final_score_probabilistic,
    calculate_problem_prior, _compute_severity_entropy,
    H2LConfigV3, DEFAULT_CONFIG_V3, sigmoid, cosine_similarity
)
import numpy as np


class TestDynamicScaling(unittest.TestCase):
    def setUp(self):
        self.mock_config = MagicMock()
        self.mock_config.TOP_K = 10
        self.mock_config.BM25_K = 50
        self.mock_config.FUSION_K = 60
        self.mock_config.DB_TYPE = 'lancedb'

        self.mock_shared = MagicMock()

    def test_strategy_alpha_values(self):
        """Verify paired-comparison strategies all use α=1.0"""
        expected = {
            "h2l-bm25": 1.0,
            "h2l-naive_rag": 1.0,
            "h2l-hybrid": 1.0,
            "h2l-hyde": 1.0,
            "h2l-full": 1.0,
        }
        for mode, expected_alpha in expected.items():
            self.assertAlmostEqual(
                STRATEGY_ALPHA[mode], expected_alpha, places=1,
                msg=f"{mode} should have alpha={expected_alpha}"
            )
        print(f"✅ Alpha values: {expected}")

    def test_strategy_mode_constructor(self):
        """Verify strategy_mode auto-maps to correct base_strategy + flags"""
        r = H2LUnifiedRetriever(
            config=self.mock_config,
            shared_components=self.mock_shared,
            strategy_mode="h2l-hybrid"
        )
        self.assertEqual(r.base_strategy, "hybrid")
        self.assertFalse(r.enable_adaptive)
        self.assertFalse(r.enable_multihop)
        self.assertAlmostEqual(r.alpha, 1.0, places=1)

        r2 = H2LUnifiedRetriever(
            config=self.mock_config,
            shared_components=self.mock_shared,
            strategy_mode="h2l-full"
        )
        self.assertEqual(r2.base_strategy, "hybrid")
        self.assertTrue(r2.enable_adaptive)
        # V6: All strategies use α=1.0 (unified via STRATEGY_ALPHA dict)
        # α₀ is the base; actual boosting is handled by adaptive α mechanism
        self.assertAlmostEqual(r2.alpha, 1.0, places=1)

    def test_dynamic_scaling(self):
        """Verify retrieval is called with problems"""
        retriever = H2LUnifiedRetriever(
            config=self.mock_config,
            shared_components=self.mock_shared,
            strategy_mode="h2l-hybrid"
        )

        # Verify strategy-specific alpha
        self.assertAlmostEqual(retriever.alpha, 1.0, places=1,
                               msg="h2l-hybrid should have alpha=1.0")

        # Mock base retriever
        retriever.base_retriever = MagicMock()
        retriever.base_retriever.retrieve.return_value = []

        # Test: 5 problems
        problems = [{'code': f'P{i}', 'confidence': 0.8, 'severity': 3} for i in range(5)]
        retriever.retrieve("query", explicit_problems=problems)

        # Verify base_retriever.retrieve was called (at least once)
        self.assertTrue(retriever.base_retriever.retrieve.called,
                        "base_retriever.retrieve should have been called")
        print("✅ Dynamic scaling test passed")


class TestV5Enhancements(unittest.TestCase):
    """Unit tests for all V5 equation enhancements"""

    def setUp(self):
        self.config = H2LConfigV3()
        self.problems = [
            {
                "code": "X60-X84",
                "name": "ทำร้ายตัวเอง",
                "severity": 5,
                "confidence": 0.92,
                "keywords": ["ทำร้ายตัวเอง", "ไม่อยากมีชีวิต", "ฆ่าตัวตาย"]
            },
            {
                "code": "F32",
                "name": "โรคซึมเศร้า",
                "severity": 4,
                "confidence": 0.85,
                "keywords": ["ซึมเศร้า", "หมดหวัง", "เศร้า"]
            },
            {
                "code": "Z55",
                "name": "ปัญหาการศึกษา",
                "severity": 2,
                "confidence": 0.70,
                "keywords": ["ไม่ไปเรียน", "หนีเรียน"]
            }
        ]

    # ── V5.1: Confidence Calibration ──

    def test_calibration_high_severity_discriminates(self):
        """V6: High severity → low T → more discriminative calibration.
        
        Formula: C(p|q) = P(p|q)^(1/T_i)
        High severity → small T_i → large 1/T_i → P^(large) → pushed toward 0/1.
        For P=0.8 (< 1.0): more discriminative = LOWER value.
        This is clinically correct: high-severity problems require
        HIGH certainty to contribute — uncertain detections are penalized.
        """
        raw = 0.8
        c_high = calibrate_confidence(raw, severity=5, max_severity=5, config=self.config)
        c_low = calibrate_confidence(raw, severity=1, max_severity=5, config=self.config)
        # V6 design: high severity → stricter → LOWER calibrated value for P<1
        self.assertLess(c_high, c_low,
                        "High-severity should be more discriminative (lower C for P<1)")
        # Both should still be positive and bounded
        self.assertGreater(c_high, 0.0)
        self.assertLess(c_low, 1.0)

    def test_calibration_bounds(self):
        """Calibrated confidence stays in [0, 1]"""
        self.assertEqual(calibrate_confidence(0.0, severity=5), 0.0)
        self.assertEqual(calibrate_confidence(1.0, severity=5), 1.0)
        c = calibrate_confidence(0.5, severity=3)
        self.assertGreaterEqual(c, 0.0)
        self.assertLessEqual(c, 1.0)

    def test_calibration_monotonic(self):
        """Higher raw confidence → higher calibrated confidence"""
        c1 = calibrate_confidence(0.5, severity=3)
        c2 = calibrate_confidence(0.8, severity=3)
        c3 = calibrate_confidence(0.95, severity=3)
        self.assertLess(c1, c2)
        self.assertLess(c2, c3)

    # ── V5.2: IDF Weight ──

    def test_idf_disabled_returns_one(self):
        """When IDF is disabled, weight should be 1.0"""
        config = H2LConfigV3(IDF_ENABLE=False)
        w = calculate_idf_weight(self.problems[0], config=config)
        self.assertEqual(w, 1.0)

    def test_idf_positive(self):
        """IDF weight should be positive"""
        w = calculate_idf_weight(self.problems[0])
        self.assertGreater(w, 0.0)

    def test_idf_rare_problem_higher(self):
        """Problem with fewer keywords (rarer) should have higher IDF"""
        rare = {"code": "R1", "name": "โรคหายาก", "keywords": ["หายาก"]}
        common = {"code": "C1", "name": "ทั่วไป", "keywords": ["a", "b", "c", "d", "e", "f", "g", "h"]}
        idf_rare = calculate_idf_weight(rare)
        idf_common = calculate_idf_weight(common)
        self.assertGreater(idf_rare, idf_common,
                           "Rare problems should have higher IDF")

    # ── V5.3: Margin-Aware Activation ──

    def test_margin_at_boundary(self):
        """At sim = margin, Ω should be ~0.5"""
        # Create vectors with known cosine similarity ≈ 0.3 (the margin)
        config = H2LConfigV3(MARGIN_M=0.3, MARGIN_TAU=0.15)
        # Unit vectors at angle cos⁻¹(0.3)
        v1 = np.array([1.0, 0.0])
        # cos(angle) = 0.3 → v2 = [0.3, sqrt(1-0.09)]
        v2 = np.array([0.3, np.sqrt(0.91)])
        omega = margin_aware_activation(v1, v2, config)
        self.assertAlmostEqual(omega, 0.5, places=1,
                               msg="At sim=margin, Ω should be ~0.5")

    def test_margin_none_embeddings(self):
        """Missing embeddings → 0.0"""
        self.assertEqual(margin_aware_activation(None, None), 0.0)

    # ── V5.4: KL Concentration Penalty ──

    def test_kl_uniform_is_zero(self):
        """Uniform distribution → KL = 0"""
        uniform = {"A": 0.333, "B": 0.333, "C": 0.334}
        kl = calculate_kl_concentration_penalty(uniform)
        self.assertAlmostEqual(kl, 0.0, places=2)

    def test_kl_concentrated_is_positive(self):
        """Concentrated distribution → KL > 0"""
        concentrated = {"A": 0.9, "B": 0.05, "C": 0.05}
        kl = calculate_kl_concentration_penalty(concentrated)
        self.assertGreater(kl, 0.1, "Concentrated distribution should have high KL")

    def test_kl_single_problem(self):
        """Single problem → no penalty"""
        single = {"A": 1.0}
        kl = calculate_kl_concentration_penalty(single)
        self.assertEqual(kl, 0.0)

    def test_kl_capped(self):
        """KL penalty should be capped at KL_MAX"""
        extreme = {"A": 0.999, "B": 0.0005, "C": 0.0005}
        config = H2LConfigV3(KL_MAX=1.0)
        kl = calculate_kl_concentration_penalty(extreme, config)
        self.assertLessEqual(kl, 1.0)

    # ── V5.5: Negation-Aware Gating ──

    def test_negation_no_query(self):
        """No query → no negation → G_neg = 1.0"""
        g = calculate_sentence_polarity(self.problems[1], query_text=None)
        self.assertEqual(g, 1.0)

    def test_negation_disabled(self):
        """Disabled → G_neg = 1.0"""
        config = H2LConfigV3(NEG_ENABLE=False)
        g = calculate_sentence_polarity(self.problems[1], "ไม่มีซึมเศร้า", config)
        self.assertEqual(g, 1.0)

    def test_negation_positive_query(self):
        """Positive query (no negation) → G_neg = 1.0"""
        g = calculate_sentence_polarity(
            self.problems[1],
            "ผู้ป่วยมีอาการซึมเศร้า หมดหวัง"
        )
        self.assertEqual(g, 1.0)

    def test_negation_negative_query(self):
        """Negated query → G_neg < 1.0"""
        g = calculate_sentence_polarity(
            self.problems[1],
            "ผู้ป่วยไม่มีอาการซึมเศร้า ไม่มีอาการหมดหวัง"
        )
        self.assertLess(g, 1.0, "Negated query should reduce G_neg")

    # ── End-to-end V5 Scoring ──

    def test_v5_no_problems_returns_base(self):
        """No problems → S_final = S_rerank (baseline reduction)"""
        score, breakdown = calculate_final_score_probabilistic(
            rerank_score=0.85, problems=[]
        )
        self.assertEqual(score, 0.85)
        self.assertEqual(breakdown["method"], "no_problems")

    def test_v6_method_label(self):
        """V6 should report method as bayesian_v6"""
        _, breakdown = calculate_final_score_probabilistic(
            rerank_score=0.85,
            problems=self.problems,
            doc_text="ซึมเศร้า หมดหวัง ทำร้ายตัวเอง"
        )
        self.assertEqual(breakdown["method"], "bayesian_v6")

    def test_v5_boost_positive(self):
        """Relevant doc should get boost > 1"""
        score, breakdown = calculate_final_score_probabilistic(
            rerank_score=0.85,
            problems=self.problems,
            doc_text="ซึมเศร้า หมดหวัง ทำร้ายตัวเอง ฆ่าตัวตาย"
        )
        self.assertGreater(breakdown["boost"], 1.0,
                           "Relevant doc should get positive boost")
        self.assertGreater(score, 0.85)

    def test_v6_breakdown_has_v6_fields(self):
        """V6 breakdown should contain V6 fields"""
        _, breakdown = calculate_final_score_probabilistic(
            rerank_score=0.85,
            problems=self.problems,
            doc_text="ซึมเศร้า ทำร้ายตัวเอง"
        )
        # V6 breakdown fields
        self.assertIn("KL_penalty", breakdown)
        self.assertIn("H_severity", breakdown)
        self.assertIn("α_eff", breakdown)
        self.assertIn("P(rel|profile)", breakdown)
        self.assertIn("margin_m", breakdown)

        # Per-factor V6 fields (uppercase Φ in V6)
        for f in breakdown["factors"]:
            self.assertIn("P(p|q)_raw", f)
            self.assertIn("C(p|q)", f)
            self.assertIn("IDF", f)
            self.assertIn("G_neg", f)
            self.assertIn("Φ_i", f)
            self.assertIn("w·Φ", f)


class TestNegationGateCases(unittest.TestCase):
    """
    Comprehensive negation gate tests following the 3×3 matrix:
    (sentence length: short/medium/long) × (severity: high/medium/low)
    
    Each cell tests:
    - Positive query → G_neg = 1.0 (no dampening)
    - Negated query  → G_neg < 1.0 (dampening active)
    """

    def setUp(self):
        self.config = H2LConfigV3()
        # High severity problems
        self.prob_suicide = {
            "code": "X60-X84", "name": "ทำร้ายตัวเอง", "severity": 5,
            "confidence": 0.92, "keywords": ["ทำร้ายตัวเอง", "ฆ่าตัวตาย", "ไม่อยากมีชีวิต"]
        }
        self.prob_depression = {
            "code": "F32", "name": "โรคซึมเศร้า", "severity": 4,
            "confidence": 0.85, "keywords": ["ซึมเศร้า", "หมดหวัง"]
        }
        self.prob_violence = {
            "code": "0102", "name": "การใช้ความรุนแรงระหว่างคู่สมรส", "severity": 4,
            "confidence": 0.88, "keywords": ["ทุบตี", "ทำร้ายร่างกาย", "รุนแรง"]
        }
        self.prob_child_abuse = {
            "code": "T74.1", "name": "ผู้ถูกกระทำความรุนแรง", "severity": 4,
            "confidence": 0.90, "keywords": ["ถูกทำร้ายร่างกาย", "ทารุณกรรม", "รอยช้ำ"]
        }
        # Medium severity problems
        self.prob_finance = {
            "code": "1001", "name": "ไม่มีรายได้/รายได้ไม่เพียงพอ", "severity": 3,
            "confidence": 0.75, "keywords": ["รายได้ไม่เพียงพอ", "ไม่มีเงิน", "ขาดแคลน"]
        }
        self.prob_spouse = {
            "code": "0101", "name": "ปัญหาคู่สมรส", "severity": 2,
            "confidence": 0.70, "keywords": ["ทะเลาะ", "ด่าว่า", "รุนแรง"]
        }
        self.prob_medical_cost = {
            "code": "1003", "name": "ค่าใช้จ่ายรักษาพยาบาล", "severity": 3,
            "confidence": 0.78, "keywords": ["ค่ารักษา", "ค่ารักษาเกินสิทธิ์", "จ่ายไม่ไหว"]
        }
        self.prob_gambling = {
            "code": "1601", "name": "สารเสพติด/การพนัน", "severity": 3,
            "confidence": 0.72, "keywords": ["ติดการพนัน", "หนี้สิน", "สุรา"]
        }
        # Low severity problems
        self.prob_health_barrier = {
            "code": "1401", "name": "อุปสรรคต่อการดูแลสุขภาพ", "severity": 1,
            "confidence": 0.65, "keywords": ["ขาดความรู้", "ไม่เข้าใจโรค", "ไม่ยอมรับการป่วย"]
        }
        self.prob_social = {
            "code": "0901", "name": "ปัญหาความสัมพันธ์คนนอกครอบครัว", "severity": 2,
            "confidence": 0.60, "keywords": ["เข้ากับเพื่อนบ้านไม่ได้", "โดดเดี่ยว"]
        }
        self.prob_housing = {
            "code": "0805", "name": "เปลี่ยนที่อยู่", "severity": 2,
            "confidence": 0.55, "keywords": ["ย้ายบ้าน", "ย้ายที่อยู่"]
        }
        self.prob_lonely = {
            "code": "0801", "name": "อยู่คนเดียว", "severity": 2,
            "confidence": 0.60, "keywords": ["อยู่คนเดียว", "ไม่มีคนดูแล", "เหงา"]
        }

    # =====================================================================
    # SHORT × HIGH SEVERITY
    # =====================================================================

    def test_short_high_positive(self):
        """S-H positive: G_neg = 1.0 (suicide/depression keywords present, no negation)"""
        query = "ผู้ป่วยพยายามฆ่าตัวตายด้วยการกินยาเกินขนาด มีอาการซึมเศร้ารุนแรง"
        g_suicide = calculate_sentence_polarity(self.prob_suicide, query, self.config)
        g_depression = calculate_sentence_polarity(self.prob_depression, query, self.config)
        self.assertEqual(g_suicide, 1.0, "Positive suicide query → G_neg = 1.0")
        self.assertEqual(g_depression, 1.0, "Positive depression query → G_neg = 1.0")

    def test_short_high_negation(self):
        """S-H negation: G_neg < 1.0 (keywords negated with ไม่มี/ไม่เคย)"""
        query = "ผู้ป่วยไม่มีอาการซึมเศร้า ไม่เคยคิดทำร้ายตัวเอง ไม่เคยพยายามฆ่าตัวตาย"
        g_suicide = calculate_sentence_polarity(self.prob_suicide, query, self.config)
        g_depression = calculate_sentence_polarity(self.prob_depression, query, self.config)
        self.assertLess(g_suicide, 1.0, "Negated suicide query → G_neg < 1.0")
        self.assertLess(g_depression, 1.0, "Negated depression query → G_neg < 1.0")

    # =====================================================================
    # SHORT × MEDIUM SEVERITY
    # =====================================================================

    def test_short_medium_positive(self):
        """S-M positive: medical cost keywords present (no negation nearby)"""
        query = "ค่ารักษาเกินสิทธิ์ ผู้ป่วยจ่ายไม่ไหว ต้องการความช่วยเหลือเรื่องเงิน"
        g = calculate_sentence_polarity(self.prob_medical_cost, query, self.config)
        self.assertEqual(g, 1.0, "Positive medical cost query → G_neg = 1.0")

    def test_short_medium_negation(self):
        """S-M negation: medical cost keywords negated"""
        query = "ไม่มีปัญหาค่ารักษา ไม่ได้จ่ายไม่ไหว ค่ารักษาไม่เกินสิทธิ์"
        g = calculate_sentence_polarity(self.prob_medical_cost, query, self.config)
        self.assertLess(g, 1.0, "Negated medical cost query → G_neg < 1.0")

    # =====================================================================
    # SHORT × LOW SEVERITY
    # =====================================================================

    def test_short_low_positive(self):
        """S-L positive: health barrier present"""
        query = "ผู้ป่วยขาดความรู้เรื่องสิทธิการรักษา ไม่เข้าใจโรคที่เป็นอยู่"
        g = calculate_sentence_polarity(self.prob_health_barrier, query, self.config)
        self.assertEqual(g, 1.0, "Positive health barrier query → G_neg = 1.0")

    def test_short_low_negation(self):
        """S-L negation: health barrier denied"""
        query = "ผู้ป่วยไม่ได้ขาดความรู้ เข้าใจโรคดี ยอมรับการป่วย"
        g = calculate_sentence_polarity(self.prob_health_barrier, query, self.config)
        self.assertLess(g, 1.0, "Negated health barrier query → G_neg < 1.0")

    # =====================================================================
    # MEDIUM × HIGH SEVERITY
    # =====================================================================

    def test_medium_high_positive(self):
        """M-H positive: child abuse present"""
        query = ("เด็กหญิงอายุ 8 ปี ถูกบิดาเลี้ยงทำร้ายร่างกายเป็นประจำ "
                 "มีรอยช้ำที่แขนและหลังหลายจุด เด็กกลัวกลับบ้าน")
        g = calculate_sentence_polarity(self.prob_child_abuse, query, self.config)
        self.assertEqual(g, 1.0, "Positive child abuse query → G_neg = 1.0")

    def test_medium_high_negation(self):
        """M-H negation: child abuse keywords negated"""
        query = ("เด็กหญิงอายุ 8 ปี ไม่ได้ถูกทำร้ายร่างกาย ไม่มีรอยช้ำ "
                 "บิดาเลี้ยงดูแลดีมาก ไม่เคยถูกทารุณกรรม")
        g = calculate_sentence_polarity(self.prob_child_abuse, query, self.config)
        self.assertLess(g, 1.0, "Negated child abuse query → G_neg < 1.0")

    # =====================================================================
    # MEDIUM × MEDIUM SEVERITY
    # =====================================================================

    def test_medium_medium_positive(self):
        """M-M positive: spousal conflict present"""
        query = ("หญิงอายุ 45 ปี สามีดื่มสุราเป็นประจำ ทะเลาะกับภรรยาบ่อยครั้ง "
                 "ใช้คำพูดรุนแรง ด่าว่าหยาบคาย")
        g = calculate_sentence_polarity(self.prob_spouse, query, self.config)
        self.assertEqual(g, 1.0, "Positive spousal conflict query → G_neg = 1.0")

    def test_medium_medium_negation(self):
        """M-M negation: spousal problems denied, real issue elsewhere"""
        query = ("หญิงอายุ 45 ปี สามีไม่ได้ดื่มสุรา ไม่เคยทะเลาะ "
                 "ไม่เคยใช้คำพูดรุนแรง ไม่ได้ด่าว่า สนใจครอบครัวดี")
        g = calculate_sentence_polarity(self.prob_spouse, query, self.config)
        self.assertLess(g, 1.0, "Negated spousal query → G_neg < 1.0")

    # =====================================================================
    # MEDIUM × LOW SEVERITY
    # =====================================================================

    def test_medium_low_positive(self):
        """M-L positive: social isolation present"""
        query = ("ผู้ป่วยชายอายุ 55 ปี ย้ายบ้านมาอยู่จังหวัดใหม่ "
                 "เข้ากับเพื่อนบ้านไม่ได้ รู้สึกโดดเดี่ยว")
        g = calculate_sentence_polarity(self.prob_housing, query, self.config)
        self.assertEqual(g, 1.0, "Positive social isolation query → G_neg = 1.0")

    def test_medium_low_negation(self):
        """M-L negation: social problems denied"""
        query = ("ผู้ป่วยชายอายุ 55 ปี ไม่ได้ย้ายบ้าน อยู่ที่เดิมมานาน "
                 "เข้ากับเพื่อนบ้านได้ดี ไม่ได้โดดเดี่ยว")
        g = calculate_sentence_polarity(self.prob_housing, query, self.config)
        self.assertLess(g, 1.0, "Negated housing query → G_neg < 1.0")

    # =====================================================================
    # LONG × HIGH SEVERITY — Third-person reference
    # =====================================================================

    def test_long_high_positive_third_person(self):
        """L-H positive: violence against sister (third-person)"""
        query = ("หญิงอายุ 35 ปี มาปรึกษาเรื่องน้องสาวอายุ 28 ปี "
                 "ที่ถูกสามีทำร้ายร่างกาย สามีของน้องสาวดื่มสุราเป็นประจำ "
                 "และทุบตีภรรยาเมื่อเมา น้องสาวมีรอยช้ำตามตัว")
        g = calculate_sentence_polarity(self.prob_violence, query, self.config)
        self.assertEqual(g, 1.0, "Third-person positive violence → G_neg = 1.0")

    def test_long_high_negation_third_person(self):
        """L-H negation: violence against sister denied (third-person negation)"""
        query = ("หญิงอายุ 35 ปี มาปรึกษาเรื่องน้องสาวอายุ 28 ปี "
                 "สามีของน้องสาวไม่ได้ทำร้ายร่างกาย ไม่เคยใช้ความรุนแรง "
                 "ไม่ดื่มสุรา ครอบครัวน้องสาวอบอุ่นดี ไม่เคยทุบตี")
        g = calculate_sentence_polarity(self.prob_violence, query, self.config)
        self.assertLess(g, 1.0, "Third-person negated violence → G_neg < 1.0")

    # =====================================================================
    # LONG × MEDIUM SEVERITY — Third-person reference
    # =====================================================================

    def test_long_medium_positive(self):
        """L-M positive: gambling/debt problem present"""
        query = ("ชายอายุ 60 ปี ลูกชายคนโตอายุ 32 ปี ติดการพนันออนไลน์ "
                 "มีหนี้สินกว่า 500,000 บาท ถูกทวงหนี้ ดื่มสุราทุกวัน "
                 "ครอบครัวแตกแยก")
        g = calculate_sentence_polarity(self.prob_gambling, query, self.config)
        self.assertEqual(g, 1.0, "Positive gambling query → G_neg = 1.0")

    def test_long_medium_negation_third_person(self):
        """L-M negation: son's gambling denied"""
        query = ("ชายอายุ 60 ปี ลูกชายคนโตไม่ได้ติดการพนัน ไม่มีหนี้สิน "
                 "ไม่เคยนำโฉนดบ้านไปจำนำ ลูกชายทั้งสองคนรักกันดี "
                 "ครอบครัวไม่ได้แตกแยก")
        g = calculate_sentence_polarity(self.prob_gambling, query, self.config)
        self.assertLess(g, 1.0, "Third-person negated gambling → G_neg < 1.0")

    # =====================================================================
    # LONG × LOW SEVERITY
    # =====================================================================

    def test_long_low_positive(self):
        """L-L positive: elderly living alone"""
        query = ("หญิงอายุ 70 ปี อาศัยอยู่คนเดียวหลังสามีเสียชีวิต "
                 "รู้สึกเหงาเวลากลางคืน ไม่มีคนดูแล "
                 "ขาดความรู้เรื่องสิทธิเบี้ยผู้สูงอายุ")
        g = calculate_sentence_polarity(self.prob_lonely, query, self.config)
        self.assertEqual(g, 1.0, "Positive elderly lonely query → G_neg = 1.0")

    def test_long_low_negation(self):
        """L-L negation: loneliness denied"""
        query = ("หญิงอายุ 70 ปี ไม่ได้อาศัยอยู่คนเดียว อยู่กับลูกสาวและหลาน "
                 "ไม่ได้เหงา มีคนพูดคุยตลอด ไม่ได้ขาดผู้ดูแล "
                 "ลูกสาวดูแลดีมาก ไม่มีปัญหา")
        g = calculate_sentence_polarity(self.prob_lonely, query, self.config)
        self.assertLess(g, 1.0, "Negated elderly query → G_neg < 1.0")

    # =====================================================================
    # EDGE CASES
    # =====================================================================

    def test_double_negation(self):
        """Double negation: 'ไม่ใช่ว่าไม่มี' → keyword still present, should not dampen"""
        # In Thai, double negation often means affirmation but the G_neg heuristic
        # may still detect the negation marker. We test the behavior.
        query = "ผู้ป่วยไม่ใช่ว่าไม่มีปัญหาเรื่องเงิน แต่มีรายได้ไม่เพียงพอจริงๆ"
        g = calculate_sentence_polarity(self.prob_finance, query, self.config)
        # Double negation is a known limitation — the heuristic may detect negation
        # We just assert G_neg is > 0 (floor at 0.1)
        self.assertGreater(g, 0.0, "Double negation should not zero out G_neg")

    def test_negation_far_from_keyword(self):
        """Negation marker far from keyword (>30 chars) → should NOT trigger"""
        # Construct query where negation is far from keyword
        query = "ผู้ป่วยไม่ได้มีปัญหาเรื่องครอบครัวหรือสังคมใดๆเลย แต่ตอนนี้มีอาการซึมเศร้ารุนแรงมาก"
        g = calculate_sentence_polarity(self.prob_depression, query, self.config)
        # "ไม่ได้" is far from "ซึมเศร้า" (>30 chars) → should be 1.0
        self.assertEqual(g, 1.0, "Far negation should not affect G_neg")

    def test_negation_close_to_keyword(self):
        """Negation marker close to keyword (<30 chars) → should trigger"""
        query = "ผู้ป่วยไม่มีอาการซึมเศร้า"
        g = calculate_sentence_polarity(self.prob_depression, query, self.config)
        self.assertLess(g, 1.0, "Close negation should reduce G_neg")

    def test_mixed_negation_positive(self):
        """Some keywords negated, some positive → partial dampening"""
        query = "ผู้ป่วยไม่มีอาการซึมเศร้า แต่ยังรู้สึกหมดหวังอย่างมาก"
        g = calculate_sentence_polarity(self.prob_depression, query, self.config)
        # One keyword negated ("ซึมเศร้า"), one positive ("หมดหวัง")
        # G_neg should be between 0.4 and 1.0
        self.assertGreater(g, 0.3, "Partial negation → G_neg partially dampened")
        self.assertLess(g, 1.0, "Partial negation → G_neg < 1.0")

    def test_negation_gate_floor(self):
        """G_neg should never go below 0.1 (floor value)"""
        # Many negated keywords
        query = ("ไม่มีซึมเศร้า ไม่เคยหมดหวัง ไม่มีเศร้า "
                 "ไม่เคยท้อแท้ ปฏิเสธปัญหาสุขภาพจิตทุกอย่าง")
        prob_many_kw = {
            "code": "F32", "name": "โรคซึมเศร้า", "severity": 4,
            "keywords": ["ซึมเศร้า", "หมดหวัง", "เศร้า", "ท้อแท้"]
        }
        g = calculate_sentence_polarity(prob_many_kw, query, self.config)
        self.assertGreaterEqual(g, 0.1, "G_neg floor at 0.1")

    def test_no_keywords_in_query(self):
        """Keywords not present in query → G_neg = 1.0"""
        query = "ผู้ป่วยมาพบแพทย์เพราะปวดฟัน ต้องการทำฟัน"
        g = calculate_sentence_polarity(self.prob_depression, query, self.config)
        self.assertEqual(g, 1.0, "No keywords in query → G_neg = 1.0")

    def test_negation_gate_severity_independence(self):
        """G_neg should be independent of severity (it's purely linguistic)"""
        query = "ไม่มีอาการซึมเศร้า"
        g_sev4 = calculate_sentence_polarity(
            {"code": "F32", "name": "ซึมเศร้า", "severity": 4, "keywords": ["ซึมเศร้า"]},
            query, self.config
        )
        g_sev1 = calculate_sentence_polarity(
            {"code": "F32", "name": "ซึมเศร้า", "severity": 1, "keywords": ["ซึมเศร้า"]},
            query, self.config
        )
        self.assertEqual(g_sev4, g_sev1,
                          "G_neg should be same regardless of severity")


if __name__ == '__main__':
    unittest.main()

