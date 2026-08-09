"""Guards for RQ4's prior ablation.

RQ4 monkey-patched retriever._apply_h2l_scoring with a function taking
(results, problems), but H2LUnifiedRetriever.retrieve() calls it as
(results, explicit_problems, query). The resulting TypeError was caught by
evaluate_strategy(), which retried retrieve(query) without explicit_problems —
skipping H2L scoring entirely. The "Uniform Prior" arm was therefore the plain
hybrid baseline (nDCG@5 = 0.235064, bit-identical to the equally-broken RQ3
keyword arm) rather than a uniform-prior H2L run.

After the arity fix the arm runs real H2L scoring and matches the severity arm
on all 95 cases. These tests pin why that null is structural rather than inert:
P(p) is document-independent within a case, so it scales scores without
reordering them.
"""

import numpy as np

import H2L_core as h2l
from H2L_core import H2LConfigV3, calculate_final_score_probabilistic


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


def uniform_prior(problems, config=None):
    if not problems:
        return {}
    k = len(problems)
    return {p.get("code", "unknown"): 1.0 / k for p in problems}


def _score(docs, config, base=None):
    base = base or [1.0 - 0.01 * i for i in range(len(docs))]
    out = []
    for i, doc in enumerate(docs):
        score, breakdown = calculate_final_score_probabilistic(
            rerank_score=base[i], problems=PROBLEMS, doc_text=doc, config=config,
        )
        out.append((score, breakdown))
    return out


def test_severity_and_uniform_priors_are_actually_different():
    """Manipulation check: the two prior functions must not agree."""
    config = H2LConfigV3()
    severity = h2l.calculate_problem_prior(PROBLEMS, config)
    uniform = uniform_prior(PROBLEMS)
    assert severity != uniform
    assert len(set(uniform.values())) == 1
    assert len(set(severity.values())) > 1


def test_uniform_prior_changes_scores_but_not_ranking():
    """The documented reason RQ4 is null: P(p) is document-independent."""
    config = H2LConfigV3()
    severity_scores = [s for s, _ in _score(DOCS, config)]

    original = h2l.calculate_problem_prior
    h2l.calculate_problem_prior = uniform_prior
    try:
        uniform_scores = [s for s, _ in _score(DOCS, config)]
    finally:
        h2l.calculate_problem_prior = original

    assert severity_scores != uniform_scores, "patch is inert — scores unchanged"
    assert (list(np.argsort(-np.array(severity_scores)))
            == list(np.argsort(-np.array(uniform_scores))))


def test_prior_shifts_alpha_far_less_than_a_rank_flip_requires():
    """Quantifies the claim written into section 4.5.1."""
    config = H2LConfigV3()
    _, severity_breakdown = _score(DOCS, config)[0]

    original = h2l.calculate_problem_prior
    h2l.calculate_problem_prior = uniform_prior
    try:
        _, uniform_breakdown = _score(DOCS, config)[0]
    finally:
        h2l.calculate_problem_prior = original

    alpha_shift = abs(severity_breakdown["α_eff"] - uniform_breakdown["α_eff"])
    assert alpha_shift > 0, "prior does not reach α_eff at all"
    assert alpha_shift < 0.5, "shift is large enough to flip ranks; claim is wrong"


def test_alpha_can_flip_ranking_in_principle():
    """Counterpart: the α channel is real, just not driven hard by the prior."""
    problems = [{"code": "P1", "name": "ปัญหารายได้", "keywords": ["รายได้"],
                 "severity": 3, "confidence": 0.8}]
    docs = ["รายได้ไม่พอ", "เอกสารอื่น"]
    base = [0.90, 1.00]

    winners = set()
    for alpha in (0.5, 3.0):
        config = H2LConfigV3(ALPHA=alpha)
        scores = [
            calculate_final_score_probabilistic(
                rerank_score=base[i], problems=problems, doc_text=doc, config=config,
            )[0]
            for i, doc in enumerate(docs)
        ]
        winners.add(int(np.argmax(scores)))

    assert len(winners) == 2, "α never reorders; the 4.5.1 explanation is wrong"
