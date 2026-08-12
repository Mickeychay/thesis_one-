"""Guards for RQ3's soft-vs-hard matching ablation.

RQ3 previously implemented "keyword-only" by monkey-patching
retriever._apply_h2l_scoring with a function taking (results, problems).
H2LUnifiedRetriever.retrieve() calls it as (results, explicit_problems, query),
so the patch raised TypeError on every case; evaluate_strategy() caught that
TypeError and retried retrieve(query) without explicit_problems, skipping H2L
scoring entirely. The "Keyword (Hard)" arm was therefore the plain hybrid
baseline, which is why it matched `basic` on 95/95 cases.

These tests pin the corrected behaviour: matching granularity is a config flag
(H2LConfigV3.MATCHING_MODE) read inside calculate_final_score_probabilistic(),
and the failure modes that previously went unnoticed now raise or log an error.
"""

import inspect
import logging

import numpy as np
import pandas as pd
import pytest

from eval.ablation_study import AblationRunner, RQ3_MatchingMethod
from h2l.core import H2LConfigV3, calculate_final_score_probabilistic


PROBLEMS = [
    {"code": "1001", "name": "ปัญหารายได้", "keywords": ["รายได้", "หนี้สิน"],
     "severity": 4, "confidence": 0.9},
    {"code": "2002", "name": "ปัญหาสุขภาพ", "keywords": ["เจ็บป่วย"],
     "severity": 3, "confidence": 0.7},
]

DOCS = [
    "ครอบครัวมีรายได้ไม่เพียงพอ และมีหนี้สินจำนวนมาก",
    "ผู้รับบริการเจ็บป่วยเรื้อรังต่อเนื่อง",
    "เอกสารบริหารทั่วไปที่ไม่เกี่ยวข้องกับกรณีศึกษา",
]


def _unit_embeddings(seed=0, dim=16):
    rng = np.random.default_rng(seed)
    docs = {}
    for doc in DOCS:
        vec = rng.normal(size=dim)
        docs[doc] = vec / np.linalg.norm(vec)
    problems = {}
    for problem in PROBLEMS:
        vec = rng.normal(size=dim)
        problems[problem["code"]] = vec / np.linalg.norm(vec)
    return docs, problems


def _score_all(mode):
    doc_emb, prob_emb = _unit_embeddings()
    config = H2LConfigV3(MATCHING_MODE=mode)
    scores = []
    for i, doc in enumerate(DOCS):
        score, breakdown = calculate_final_score_probabilistic(
            rerank_score=1.0 - 0.01 * i,
            problems=PROBLEMS,
            doc_text=doc,
            doc_embedding=doc_emb[doc],
            problem_embeddings=prob_emb,
            config=config,
        )
        scores.append((score, breakdown))
    return scores


# ── config plumbing ────────────────────────────────────────────────────────

def test_default_matching_mode_is_soft():
    """Existing results must stay reproducible: the default cannot change."""
    assert H2LConfigV3().MATCHING_MODE == "soft"


def test_invalid_matching_mode_raises():
    """A silently-ignored typo would make an arm identical to the default."""
    with pytest.raises(ValueError, match="MATCHING_MODE"):
        H2LConfigV3(MATCHING_MODE="semantic")


def test_matching_mode_reaches_the_scoring_function():
    """Without this wiring all three RQ3 arms are the same pipeline run."""
    for mode in H2LConfigV3.MATCHING_MODES:
        _, breakdown = _score_all(mode)[0]
        assert breakdown["matching_mode"] == mode


def test_each_mode_produces_a_distinct_score_vector():
    by_mode = {mode: [round(s, 8) for s, _ in _score_all(mode)]
               for mode in H2LConfigV3.MATCHING_MODES}
    assert by_mode["soft"] != by_mode["keyword_soft"]
    assert by_mode["keyword_soft"] != by_mode["hard"]
    assert by_mode["soft"] != by_mode["hard"]


def test_keyword_modes_ignore_embeddings_for_p_doc_problem():
    """A keyword arm that still reads embeddings is not a keyword arm."""
    doc_emb, prob_emb = _unit_embeddings()
    for mode in ("keyword_soft", "hard"):
        config = H2LConfigV3(MATCHING_MODE=mode)
        with_emb, _ = calculate_final_score_probabilistic(
            rerank_score=1.0, problems=PROBLEMS, doc_text=DOCS[0],
            doc_embedding=doc_emb[DOCS[0]], problem_embeddings=prob_emb,
            config=config,
        )
        without_emb, _ = calculate_final_score_probabilistic(
            rerank_score=1.0, problems=PROBLEMS, doc_text=DOCS[0],
            doc_embedding=None, problem_embeddings=None, config=config,
        )
        assert with_emb == pytest.approx(without_emb)


def test_soft_mode_does_read_embeddings():
    """Counterpart to the test above — proves the contrast is real."""
    config = H2LConfigV3(MATCHING_MODE="soft")
    doc_emb, prob_emb = _unit_embeddings()
    with_emb, _ = calculate_final_score_probabilistic(
        rerank_score=1.0, problems=PROBLEMS, doc_text=DOCS[0],
        doc_embedding=doc_emb[DOCS[0]], problem_embeddings=prob_emb,
        config=config,
    )
    without_emb, _ = calculate_final_score_probabilistic(
        rerank_score=1.0, problems=PROBLEMS, doc_text=DOCS[0],
        doc_embedding=None, problem_embeddings=None, config=config,
    )
    assert with_emb != pytest.approx(without_emb)


def test_hard_mode_binarises_p_doc_problem():
    graded = {f["code"]: f["P(d|p)"] for f in _score_all("keyword_soft")[0][1]["factors"]}
    hard = {f["code"]: f["P(d|p)"] for f in _score_all("hard")[0][1]["factors"]}
    assert set(hard.values()) <= {0.0, 1.0}
    # DOCS[0] matches 2 of problem 1001's keywords but not all of them, so the
    # graded arm must sit strictly between the binary endpoints.
    assert 0.0 < graded["1001"] < 1.0
    assert hard["1001"] == 1.0


def test_non_matching_components_stay_active_in_keyword_modes():
    """Only P(d|p) may change; disabling the whole scoring layer is the old bug."""
    for mode in H2LConfigV3.MATCHING_MODES:
        _, breakdown = _score_all(mode)[0]
        assert breakdown["method"] == "bayesian_v6"
        assert breakdown["P(rel|profile)"] != 1.0, mode
        factor = breakdown["factors"][0]
        assert factor["IDF"] > 0, mode
        assert factor["P(p)"] > 0, mode
        assert factor["w_i"] > 0, mode


# ── retriever construction ─────────────────────────────────────────────────

def test_create_h2l_retriever_rejects_unknown_matching_mode():
    """Assigning after construction skips __post_init__, so validate there too."""
    runner = AblationRunner.__new__(AblationRunner)
    with pytest.raises(ValueError, match="matching_mode"):
        runner.create_h2l_retriever(matching_mode="nope")


def test_force_keyword_conflicting_with_matching_mode_raises():
    runner = AblationRunner.__new__(AblationRunner)
    with pytest.raises(ValueError, match="conflicts with matching_mode"):
        runner.create_h2l_retriever(force_keyword=True, matching_mode="soft")


def test_rq3_no_longer_monkey_patches_apply_h2l_scoring():
    """Regression guard for the arity bug that caused the false null result."""
    source = inspect.getsource(AblationRunner.create_h2l_retriever)
    assert "keyword_only_scoring" not in source
    assert "MATCHING_MODE" in source

    run_body = inspect.getsource(RQ3_MatchingMethod.run)
    assert "matching_mode" in run_body
    assert "force_keyword" not in run_body


def test_no_monkey_patches_remain_in_create_h2l_retriever():
    """Regression guard: both matching and prior are now config-driven.

    Previously uniform_prior_scoring was a monkey-patch on
    _apply_h2l_scoring. It had the wrong arity (2 params vs the real 3),
    which caused a TypeError inside retrieve() that evaluate_strategy()
    swallowed — silently making the arm a plain baseline. Moving both
    MATCHING_MODE and PRIOR_MODE to config removes the failure mode
    entirely and this test makes sure neither patch comes back.
    """
    source = inspect.getsource(AblationRunner.create_h2l_retriever)
    assert "uniform_prior_scoring" not in source, \
        "uniform_prior monkey-patch must not return"
    assert "keyword_only_scoring" not in source, \
        "keyword_only monkey-patch must not return"
    assert "MATCHING_MODE" in source
    assert "PRIOR_MODE" in source


# ── manipulation check ─────────────────────────────────────────────────────

def _df(rankings, n_problems=None):
    rows = []
    for variant, per_case in rankings.items():
        for case_id, docs in per_case.items():
            rows.append({
                "variant": variant,
                "case_id": case_id,
                "doc_ids": docs,
                "n_problems": (n_problems or {}).get(variant, 2),
            })
    return pd.DataFrame(rows)


def test_manipulation_check_errors_when_all_arms_rank_identically(caplog):
    """This is the exact shape of the false null result RQ3 produced before."""
    df = _df({
        "Semantic (Soft)": {"C1": "d1|d2", "C2": "d3|d4"},
        "Keyword (Graded)": {"C1": "d1|d2", "C2": "d3|d4"},
        "Keyword (Hard)": {"C1": "d1|d2", "C2": "d3|d4"},
    })

    with caplog.at_level(logging.ERROR):
        RQ3_MatchingMethod._manipulation_check(df)

    assert "manipulation check FAILED" in caplog.text


def test_manipulation_check_passes_when_rankings_differ(caplog):
    df = _df({
        "Semantic (Soft)": {"C1": "d1|d2", "C2": "d3|d4"},
        "Keyword (Graded)": {"C1": "d2|d1", "C2": "d3|d4"},
        "Keyword (Hard)": {"C1": "d2|d1", "C2": "d4|d3"},
    })

    with caplog.at_level(logging.ERROR):
        RQ3_MatchingMethod._manipulation_check(df)

    assert "manipulation check FAILED" not in caplog.text


def test_manipulation_check_flags_differing_detection_as_a_confound(caplog):
    """Detection must be constant across arms; only P(d|p) may vary."""
    df = _df(
        {
            "Semantic (Soft)": {"C1": "d1|d2"},
            "Keyword (Hard)": {"C1": "d2|d1"},
        },
        n_problems={"Semantic (Soft)": 3, "Keyword (Hard)": 1},
    )

    with caplog.at_level(logging.ERROR):
        RQ3_MatchingMethod._manipulation_check(df)

    assert "confound" in caplog.text


def test_co_occurrence_is_gated_on_embeddings_not_on_matching_mode():
    """Regression guard for a confound.

    _apply_h2l_scoring() used to pass `problem_embeddings if use_semantic`, so
    making use_semantic mode-dependent would flatten the co-occurrence weight
    w_i to 1.0 in the keyword arms. RQ3 must vary P(d|p) only.
    """
    source = inspect.getsource(
        __import__("h2l.core", fromlist=["core"]).H2LUnifiedRetriever._apply_h2l_scoring
    )
    co_call = source.split("calculate_co_occurrence_weights(")[1].split(")")[0]
    assert "embeddings_available" in co_call
    assert "use_semantic" not in co_call


def test_rq3_arms_cover_soft_graded_and_hard():
    assert RQ3_MatchingMethod.ARMS == {
        "Semantic (Soft)": "soft",
        "Keyword (Graded)": "keyword_soft",
        "Keyword (Hard)": "hard",
    }
