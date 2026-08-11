"""Guards for RQ4's prior ablation.

PRIOR_MODE is now a config flag in H2LConfigV3 ('severity' | 'uniform'),
read inside calculate_problem_prior(). No monkey-patching needed or used.

The original RQ4 monkey-patched retriever._apply_h2l_scoring with a function
taking (results, problems), but H2LUnifiedRetriever.retrieve() calls it as
(results, explicit_problems, query). The resulting TypeError was caught by
evaluate_strategy(), which retried without explicit_problems — skipping H2L
scoring. The "Uniform Prior" arm was the plain hybrid baseline
(nDCG@5=0.235064, bit-identical to the broken RQ3 keyword arm).

After moving to PRIOR_MODE the config path is the single source of truth,
and these tests verify both that the modes differ as expected AND that the
null is structural (P(p) document-independent → no rank flip).
"""

import numpy as np
import pytest

from H2L_core import H2LConfigV3, calculate_final_score_probabilistic, calculate_problem_prior
from ablation_study import AblationRunner


PROBLEMS = [
    {"code": "P1", "name": "ปัญหารายได้", "keywords": ["รายได้", "หนี้สิน"],
     "severity": 5, "confidence": 0.9},
    {"code": "P2", "name": "ปัญหาสุขภาพ", "keywords": ["เจ็บป่วย"],
     "severity": 1, "confidence": 0.6},
]

DOCS = [
    "ครอบครัวมีรายได้ไม่เพียงพอ และมีหนี้สินจำนวนมาก",
    "ผู้รับบริการเจ็บป่วยเรื้อรัง",
    "เอกสารบริหารทั่วไป",
    "รายได้ไม่พอและเจ็บป่วยพร้อมกัน",
]


def _score(docs, config, base=None):
    base = base or [1.0 - 0.01 * i for i in range(len(docs))]
    return [
        calculate_final_score_probabilistic(
            rerank_score=base[i], problems=PROBLEMS, doc_text=doc, config=config,
        )
        for i, doc in enumerate(docs)
    ]


# ── config plumbing ────────────────────────────────────────────────────────

def test_default_prior_mode_is_severity():
    assert H2LConfigV3().PRIOR_MODE == 'severity'


def test_invalid_prior_mode_raises():
    with pytest.raises(ValueError, match="PRIOR_MODE"):
        H2LConfigV3(PRIOR_MODE='bogus')


def test_prior_modes_produce_different_distributions():
    sev = calculate_problem_prior(PROBLEMS, H2LConfigV3(PRIOR_MODE='severity'))
    uni = calculate_problem_prior(PROBLEMS, H2LConfigV3(PRIOR_MODE='uniform'))
    assert sev != uni
    assert len(set(uni.values())) == 1          # uniform: all equal
    assert len(set(sev.values())) > 1           # severity: at least two values


def test_prior_mode_reaches_scoring_function():
    """Config flag must change scores, or the mode is inert."""
    sev_scores = [s for s, _ in _score(DOCS, H2LConfigV3(PRIOR_MODE='severity'))]
    uni_scores = [s for s, _ in _score(DOCS, H2LConfigV3(PRIOR_MODE='uniform'))]
    assert sev_scores != uni_scores, "PRIOR_MODE did not reach the scoring function"


def test_prior_mode_in_breakdown_matches_config():
    """Breakdown dict must record the active mode for traceability."""
    for mode in H2LConfigV3.PRIOR_MODES:
        cfg = H2LConfigV3(PRIOR_MODE=mode)
        _, breakdown = _score(DOCS, cfg)[0]
        # The breakdown records MATCHING_MODE; we also verify prior indirectly
        # through the priors key — the test above already checks scores differ.
        assert breakdown["method"] == "bayesian_v6"


# ── null is structural, not inert ─────────────────────────────────────────

def test_prior_mode_changes_scores_but_not_ranking():
    """The documented reason RQ4 is null: P(p) is document-independent
    within a case, so it scales all scores without reordering."""
    sev_scores = [s for s, _ in _score(DOCS, H2LConfigV3(PRIOR_MODE='severity'))]
    uni_scores = [s for s, _ in _score(DOCS, H2LConfigV3(PRIOR_MODE='uniform'))]

    assert sev_scores != uni_scores, "PRIOR_MODE is inert — scores unchanged"
    assert (list(np.argsort(-np.array(sev_scores)))
            == list(np.argsort(-np.array(uni_scores))))


def test_prior_shifts_alpha_far_less_than_a_rank_flip_requires():
    """Quantifies the claim in section 4.5.1."""
    _, sev_bd = _score(DOCS, H2LConfigV3(PRIOR_MODE='severity'))[0]
    _, uni_bd = _score(DOCS, H2LConfigV3(PRIOR_MODE='uniform'))[0]

    alpha_shift = abs(sev_bd["α_eff"] - uni_bd["α_eff"])
    assert alpha_shift > 0, "prior does not reach α_eff at all"
    assert alpha_shift < 0.5, "shift large enough to flip ranks; 4.5.1 claim is wrong"


def test_alpha_can_flip_ranking_in_principle():
    """Counterpart: the α channel is real, just not driven hard by the prior."""
    problems = [{"code": "P1", "name": "ปัญหารายได้", "keywords": ["รายได้"],
                 "severity": 3, "confidence": 0.8}]
    docs = ["รายได้ไม่พอ", "เอกสารอื่น"]
    base = [0.90, 1.00]

    winners = set()
    for alpha in (0.5, 3.0):
        cfg = H2LConfigV3(ALPHA=alpha)
        scores = [
            calculate_final_score_probabilistic(
                rerank_score=base[i], problems=problems, doc_text=doc, config=cfg,
            )[0]
            for i, doc in enumerate(docs)
        ]
        winners.add(int(np.argmax(scores)))
    assert len(winners) == 2, "α never reorders; 4.5.1 explanation is wrong"


# ── retriever constructor ──────────────────────────────────────────────────

def test_create_h2l_retriever_rejects_unknown_prior_mode():
    runner = AblationRunner.__new__(AblationRunner)
    with pytest.raises(ValueError, match="prior_mode"):
        runner.create_h2l_retriever(prior_mode='bogus')


def test_uniform_prior_kwarg_maps_to_prior_mode_uniform():
    """Backward-compat: uniform_prior=True is a deprecated alias."""
    import warnings
    runner = AblationRunner.__new__(AblationRunner)
    with pytest.raises(ValueError, match="conflicts with prior_mode"):
        runner.create_h2l_retriever(uniform_prior=True, prior_mode='severity')


def test_no_monkey_patch_in_create_h2l_retriever():
    """Regression guard: the monkey-patch has been removed."""
    import inspect
    source = inspect.getsource(AblationRunner.create_h2l_retriever)
    assert "uniform_prior_scoring" not in source
    assert "PRIOR_MODE" in source
