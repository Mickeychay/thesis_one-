#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
H2L V6 Ablation Study — Publication-Quality Evaluation
=======================================================

Systematic ablation of H2L V6 components using **real retrieval** through
the EvaluationRunner pipeline with ground truth cases.

Research Questions:
    RQ1: What is the impact of L2 LLM filtering on precision?
    RQ2: How sensitive is performance to the α parameter?
    RQ3: What is the advantage of soft (semantic) vs hard (keyword) matching?
    RQ4: How much does the Bayesian prior (severity-based) improve performance?
    RQ5: Does H2L filtering as post-processing improve baseline strategies?
    RQ6: Which V6 components contribute most to the final ranking?

Advanced Computational Analysis:
    - Bootstrap BCa 95% CIs (Efron & Tibshirani, 1993)
    - Bayesian Signed-Rank Test — P(H2L > Baseline) (Benavoli et al., 2017)
    - KL-Divergence & Jensen-Shannon Divergence of score distributions
    - Kendall's τ rank correlation (ranking reshuffle analysis)
    - Stratified effect heterogeneity with forest plots
    - Component interaction heatmaps (2-way effects)

Methodology:
    - Uses EvaluationRunner for all evaluations (no mock data)
    - Ground truth: split-annotated H2L social work cases
    - Metrics: nDCG@5, P@5, R@5, F1@5, MAP, MRR
    - Statistical tests: Paired t-test / Wilcoxon + Cohen's d + BCa Bootstrap

Usage:
    python ablation_study.py                       # Full study (all cases)
    python ablation_study.py --max-cases 10        # Quick run with 10 cases
    python ablation_study.py --rq 1 2 5 6          # Run specific RQs only
    python ablation_study.py --skip-baselines      # Skip baseline comparison
"""

import json
import time
import copy
import hashlib
import logging
import argparse
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for server

try:
    import seaborn as sns
    HAS_SEABORN = True
except ImportError:
    HAS_SEABORN = False

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def file_sha256(path: Path) -> str:
    """Return a stable digest for experiment provenance."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def repository_path(path: Path) -> str:
    """Prefer a repository-relative path in saved metadata."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(resolved)


def case_provenance_fields(case: Dict, split: str) -> Dict:
    """Normalize slice metadata needed for held-out stress-test reporting."""
    augmentation = case.get("augmentation")
    augmentation = augmentation if isinstance(augmentation, dict) else {}
    default_slice = "standard_test" if split == "test" else split
    return {
        "evaluation_slice": case.get("evaluation_slice") or default_slice,
        "augmentation_type": (
            augmentation.get("type")
            or case.get("augmentation_type")
            or "original"
        ),
        "false_trigger_code": augmentation.get("false_trigger_code"),
    }


# ============================================================================
# ABLATION RUNNER — Central coordinator for all experiments
# ============================================================================

class AblationRunner:
    """
    Orchestrates ablation experiments using the real EvaluationRunner pipeline.

    Loads models & indexes once, then runs each experiment by dynamically
    registering strategy configurations with different H2L parameters.
    """

    def __init__(self, ground_truth_path: str = "expanded_ground_truth.json",
                 max_cases: int = None, top_k: int = 15,
                 split: str = "all",
                 detected_problems_cache_path: str = None,
                 detected_problems_model: str = "qwen2.5:7b",
                 detected_problems_repeat: int = 1):
        self.ground_truth_path = ground_truth_path
        self.max_cases = max_cases
        self.top_k = top_k
        self.split = split
        self.detected_problems_cache_path = detected_problems_cache_path
        self.detected_problems_model = detected_problems_model
        self.detected_problems_repeat = detected_problems_repeat
        self._runner = None
        self._gt_data = None
        self._detected_problems_cache = None
        self._detected_problems_cache_payload = None

    def _ensure_runner(self):
        """Lazy-initialize EvaluationRunner (loads models once)"""
        if self._runner is not None:
            return self._runner

        from evaluate_h2l_proper import EvaluationRunner
        logger.info("📦 Initializing EvaluationRunner (loading models)...")
        self._runner = EvaluationRunner()
        logger.info("✅ EvaluationRunner ready")
        return self._runner

    def _load_cases(self) -> List[Dict]:
        """Load ground truth cases"""
        if self._gt_data is None:
            with open(self.ground_truth_path, 'r', encoding='utf-8') as f:
                self._gt_data = json.load(f)
        cases = self._gt_data.get('cases', [])
        if self.split != "all":
            cases = [case for case in cases if case.get("split") == self.split]
        if self.max_cases:
            cases = cases[:self.max_cases]
        return cases

    def _load_detected_problems_cache(self) -> Dict[str, List[Dict]]:
        if self._detected_problems_cache is not None:
            return self._detected_problems_cache
        if not self.detected_problems_cache_path:
            self._detected_problems_cache = {}
            return self._detected_problems_cache

        with open(self.detected_problems_cache_path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
        self._detected_problems_cache_payload = payload
        model_rows = payload.get('per_case', {}).get(self.detected_problems_model, [])
        cache = {}
        duplicate_case_ids = []
        for row in model_rows:
            if int(row.get('repeat', 1)) != self.detected_problems_repeat:
                continue
            case_id = row.get('case_id')
            if case_id:
                if case_id in cache:
                    duplicate_case_ids.append(case_id)
                cache[case_id] = row.get('detected_problems', [])
        if duplicate_case_ids:
            raise ValueError(
                "Duplicate case IDs in detected-problems cache for "
                f"model={self.detected_problems_model!r}, "
                f"repeat={self.detected_problems_repeat}: "
                f"{sorted(set(duplicate_case_ids))[:10]}"
            )
        if not cache:
            raise ValueError(
                f"No cached detections for model={self.detected_problems_model!r}, "
                f"repeat={self.detected_problems_repeat} in {self.detected_problems_cache_path}"
            )
        self._detected_problems_cache = cache
        logger.info(
            "Loaded cached detections for %s cases from %s (model=%s, repeat=%s)",
            len(cache),
            self.detected_problems_cache_path,
            self.detected_problems_model,
            self.detected_problems_repeat,
        )
        return cache

    def validate_detected_problems_cache(self) -> Dict:
        """Fail fast when a cached L2 matrix does not match the selected cases."""
        cache = self._load_detected_problems_cache()
        selected_cases = self._load_cases()
        selected_case_ids = [str(case.get('case_id', '')) for case in selected_cases]
        if len(selected_case_ids) != len(set(selected_case_ids)):
            raise ValueError("Selected ground-truth split contains duplicate case IDs")

        if not self.detected_problems_cache_path:
            return {
                'enabled': False,
                'selected_cases': len(selected_cases),
            }

        expected_ids = set(selected_case_ids)
        cached_ids = set(cache)
        missing_ids = sorted(expected_ids - cached_ids)
        extra_ids = sorted(cached_ids - expected_ids)
        # A quick --max-cases smoke run intentionally selects a prefix of the
        # final split, so its signed full-split cache is a valid superset. Full
        # runs still require an exact case-set match.
        exact_case_set_required = self.max_cases is None
        if missing_ids or (exact_case_set_required and extra_ids):
            raise ValueError(
                "Detected-problems cache does not match the selected split: "
                f"selected={len(expected_ids)}, cached={len(cached_ids)}, "
                f"missing={missing_ids[:10]}, extra={extra_ids[:10]}"
            )

        payload = self._detected_problems_cache_payload or {}
        metadata = payload.get('metadata', {})
        metadata_models = metadata.get('models', [])
        if metadata_models and self.detected_problems_model not in metadata_models:
            raise ValueError(
                f"Cache model {self.detected_problems_model!r} is absent from metadata models"
            )
        metadata_repeats = int(metadata.get('repeats', 0) or 0)
        if metadata_repeats and not 1 <= self.detected_problems_repeat <= metadata_repeats:
            raise ValueError(
                f"Cache repeat {self.detected_problems_repeat} is outside 1..{metadata_repeats}"
            )
        if self.split == 'test' and exact_case_set_required:
            metadata_test_cases = int(metadata.get('test_cases', -1) or -1)
            if metadata_test_cases != len(selected_cases):
                raise ValueError(
                    "Cache metadata test_cases does not match the selected test split: "
                    f"metadata={metadata_test_cases}, selected={len(selected_cases)}"
                )

        case_by_id = {str(case.get('case_id')): case for case in selected_cases}
        selected_rows = [
            row
            for row in payload.get('per_case', {}).get(self.detected_problems_model, [])
            if int(row.get('repeat', 1)) == self.detected_problems_repeat
        ]
        for row in selected_rows:
            case_id = str(row.get('case_id', ''))
            if case_id not in case_by_id:
                continue
            cached_expected = [str(code) for code in row.get('expected_codes', [])]
            ground_truth_expected = [
                str(problem.get('code'))
                for problem in case_by_id[case_id].get('expected_diagnosis', {}).get('problem_list', [])
                if problem.get('code')
            ]
            if cached_expected and cached_expected != ground_truth_expected:
                raise ValueError(
                    f"Expected codes changed since cache creation for case {case_id}: "
                    f"cache={cached_expected}, ground_truth={ground_truth_expected}"
                )

        cache_path = Path(self.detected_problems_cache_path)
        return {
            'enabled': True,
            'path': repository_path(cache_path),
            'sha256': file_sha256(cache_path),
            'created_at': metadata.get('created_at'),
            'metadata_test_cases': metadata.get('test_cases'),
            'metadata_repeats': metadata.get('repeats'),
            'metadata_top_k': metadata.get('top_k'),
            'metadata_strategies': metadata.get('retrieval_strategies', []),
            'selected_model': self.detected_problems_model,
            'selected_repeat': self.detected_problems_repeat,
            'selected_cases': len(selected_cases),
            'cached_cases': len(cache),
            'case_set_validation': (
                'exact' if exact_case_set_required else 'selected_subset_of_cache'
            ),
        }

    def detected_problems_for_case(self, case: Dict, runner,
                                   use_l2: bool = True) -> List[Dict]:
        cache = self._load_detected_problems_cache()
        case_id = case.get('case_id')
        if cache:
            if not use_l2:
                # The cache stores L2-validated problem lists from a completed
                # matrix run. Serving it under an L1-only condition would make
                # the two ablation arms identical and silently produce a
                # null result. Refuse instead of reporting a false negative.
                raise ValueError(
                    "Cannot run an L1-only (use_l2=False) condition while the "
                    "detected-problems cache is enabled: the cache contains "
                    "L2-validated problems, so both arms would be identical. "
                    "Re-run without --detected-problems-cache."
                )
            if case_id not in cache:
                raise KeyError(f"Case {case_id!r} is missing from the detected-problems cache")
            return copy.deepcopy(cache[case_id])
        return runner.detect_problems(case.get('case_description', ''), use_l2=use_l2)

    def evaluate_strategy(self, strategy_name: str, cases: List[Dict] = None,
                          custom_retriever=None, use_l2: bool = True) -> Dict:
        """
        Evaluate a single strategy on ground truth cases.

        Args:
            use_l2: Passed through to detection. False yields raw L1 detections
                without L2 semantic validation — the real L2 ablation switch.

        Returns dict with per-case results and aggregate metrics.
        """
        runner = self._ensure_runner()
        if cases is None:
            cases = self._load_cases()

        from evaluate_h2l_proper import (
            STRATEGY_CONFIGS, build_relevance_keywords, judge_relevance,
            compute_all_metrics
        )

        strategy_results = []
        metric_lists = defaultdict(list)

        for i, case in enumerate(cases):
            case_id = case.get('case_id', f'case_{i}')
            query = case.get('case_description', '')
            expected = case.get('expected_diagnosis', {}).get('problem_list', [])
            if not query:
                continue

            # Build relevance keywords
            relevance_keywords = build_relevance_keywords(expected, runner.taxonomy)

            # Detect problems
            detected_problems = runner.detect_problems(query, use_l2=use_l2) if (
                strategy_name in STRATEGY_CONFIGS and
                STRATEGY_CONFIGS[strategy_name].get('needs_problems', False)
            ) or custom_retriever else []

            # Retrieve
            start_time = time.time()
            try:
                retriever = custom_retriever or runner._get_retriever(strategy_name)
                if detected_problems and hasattr(retriever, 'retrieve'):
                    results = retriever.retrieve(
                        query=query,
                        explicit_problems=detected_problems,
                        top_k_override=self.top_k
                    )
                else:
                    results = retriever.retrieve(query, top_k_override=self.top_k)
            except TypeError:
                try:
                    results = retriever.retrieve(query)
                except Exception as e:
                    logger.warning(f"    ❌ {case_id}: {e}")
                    continue
            elapsed = time.time() - start_time

            # Judge relevance
            relevance_grades = []
            for r in results:
                doc = r.doc if hasattr(r, 'doc') else r
                doc_text = getattr(doc, 'text', '')
                grade = judge_relevance(doc_text, relevance_keywords, expected)
                relevance_grades.append(grade)

            # Compute metrics
            metrics = compute_all_metrics(relevance_grades, k_values=[3, 5, 10])
            metrics['retrieval_time'] = elapsed

            strategy_results.append({
                'case_id': case_id,
                'complexity': case.get('complexity', 'unknown'),
                'category': case.get('category', 'unknown'),
                'metrics': metrics,
                'relevance_grades': relevance_grades,
                # Number of problems fed into scoring. Recorded so an L2
                # ablation can be shown to actually change the detected
                # problem list, rather than assumed to.
                'n_problems': len(detected_problems),
                'detected_codes': [
                    str(p.get('code', '')) for p in detected_problems
                ],
            })

            for metric_name, value in metrics.items():
                if isinstance(value, (int, float)):
                    metric_lists[metric_name].append(value)

        # Aggregate
        agg = {}
        for metric_name, values in metric_lists.items():
            if values:
                agg[metric_name] = {
                    'mean': float(np.mean(values)),
                    'std': float(np.std(values)),
                    'median': float(np.median(values)),
                    'min': float(np.min(values)),
                    'max': float(np.max(values)),
                    'n': len(values),
                    'values': values,
                }

        return {
            'per_case': strategy_results,
            'aggregates': agg,
            'n_cases': len(strategy_results),
        }

    def create_h2l_retriever(self, alpha: float = None,
                             h2l_config=None,
                             force_keyword: bool = False,
                             uniform_prior: bool = False,
                             **kwargs):
        """
        Create a custom H2LUnifiedRetriever with specific parameter overrides.

        This is the core mechanism for ablation — toggle individual components.
        """
        from H2L_core import H2LUnifiedRetriever, H2LConfigV3

        runner = self._ensure_runner()
        config = runner._ensure_config()
        shared = runner._ensure_shared_components()

        h2l_cfg = h2l_config or H2LConfigV3()
        if alpha is not None:
            h2l_cfg.ALPHA = alpha

        retriever = H2LUnifiedRetriever(
            config=config,
            shared_components=shared,
            base_strategy=kwargs.get('base_strategy', 'hybrid'),
            enable_adaptive=kwargs.get('enable_adaptive', False),
            enable_multihop=kwargs.get('enable_multihop', False),
            h2l_config=h2l_cfg,
        )

        # Force keyword-only matching by replacing the embedder
        if force_keyword:
            retriever._force_keyword_matching = True
            # Monkey-patch _apply_h2l_scoring to skip semantic
            original_scoring = retriever._apply_h2l_scoring

            def keyword_only_scoring(results, problems):
                from H2L_core import calculate_problem_prior, calculate_final_score_probabilistic
                priors = calculate_problem_prior(problems, retriever.h2l_config)
                for result in results:
                    final_score, breakdown = calculate_final_score_probabilistic(
                        rerank_score=result.rerank_score,
                        problems=problems,
                        doc_text=result.doc.text,
                        doc_embedding=None,  # Force keyword-only
                        problem_embeddings=None,
                        config=retriever.h2l_config,
                        alpha_override=retriever.alpha,
                    )
                    result.rerank_score = final_score
                return results

            retriever._apply_h2l_scoring = keyword_only_scoring

        # Uniform prior override
        if uniform_prior:
            import H2L_core as h2l_mod
            _original_prior = h2l_mod.calculate_problem_prior

            def uniform_prior_fn(problems, config=None):
                """Uniform prior: P(p) = 1/k for all problems"""
                if not problems:
                    return {}
                k = len(problems)
                return {p.get('code', 'unknown'): 1.0 / k for p in problems}

            # Monkey-patch for this retriever's scoring
            original_scoring_2 = retriever._apply_h2l_scoring

            def uniform_prior_scoring(results, problems):
                h2l_mod.calculate_problem_prior = uniform_prior_fn
                try:
                    return original_scoring_2(results, problems)
                finally:
                    h2l_mod.calculate_problem_prior = _original_prior

            retriever._apply_h2l_scoring = uniform_prior_scoring

        return retriever


# ============================================================================
# EXPERIMENT CLASSES
# ============================================================================

class AblationExperiment:
    """Base class for ablation experiments"""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    def run(self, ablation_runner: AblationRunner) -> pd.DataFrame:
        raise NotImplementedError

    def visualize(self, results: pd.DataFrame, output_dir: Path):
        raise NotImplementedError


class RQ1_L2Filtering(AblationExperiment):
    """
    RQ1: What is the impact of L2 LLM filtering on precision?

    Compare two DETECTION conditions (identical H2L scoring in both arms):
    - 'L1+L2 detection':      detect_problems(use_l2=True)  — L1 candidates
                              validated/filtered by the L2 LLM.
    - 'L1-only detection':    detect_problems(use_l2=False) — raw L1 candidates,
                              no L2 validation.

    Hypothesis: L2 filtering improves precision by removing false positives.

    IMPORTANT — why this is not implemented with L1_WEIGHT_BETA:
        H2LConfigV3.L1_WEIGHT_BETA documents 'S_detect = β×S_L1 + (1-β)×S_L2',
        but that formula has no implementation anywhere in H2L_core.py: β is
        never read by any scoring function, and S_L1/S_L2 are never computed as
        separate quantities. A previous version of this experiment varied β
        (0.3 vs 1.0) and therefore ran the SAME pipeline twice, producing
        byte-identical metrics across all 95 cases — a false null result, not
        evidence about L2. sensitivity_analysis.py and
        scripts/build_chapter4_evidence.py already record β as
        'not exercised'; do not reintroduce it here as an L2 switch.

        The real switch is use_l2 in H2LDetector.detect_problems(), which
        changes the detected problem list itself.
    """

    def __init__(self):
        super().__init__(
            name="RQ1: L2 Filtering Impact",
            description="Evaluate precision improvement from L2 LLM validation"
        )

    def run(self, ablation_runner: AblationRunner) -> pd.DataFrame:
        logger.info(f"\n{'='*70}")
        logger.info(f"Running {self.name}")
        logger.info(f"{'='*70}\n")

        if ablation_runner.detected_problems_cache_path:
            raise ValueError(
                "RQ1 ablates L2 at detection time and cannot run against a "
                "detected-problems cache (the cache holds one fixed "
                "L2-validated problem list, so both arms would be identical). "
                "Re-run RQ1 without --detected-problems-cache."
            )

        # Identical scoring config in both arms — only detection differs.
        conditions = {
            'L1+L2 detection': True,
            'L1-only detection': False,
        }

        all_rows = []
        results_by_variant = {}

        for variant_name, use_l2 in conditions.items():
            logger.info(f"\n  🔧 Condition: {variant_name} (use_l2={use_l2})")
            retriever = ablation_runner.create_h2l_retriever()
            result = ablation_runner.evaluate_strategy(
                'h2l-hybrid', custom_retriever=retriever, use_l2=use_l2
            )
            results_by_variant[variant_name] = result

            for case_result in result['per_case']:
                m = case_result['metrics']
                all_rows.append({
                    'variant': variant_name,
                    'use_l2': use_l2,
                    'case_id': case_result['case_id'],
                    'complexity': case_result['complexity'],
                    'n_problems': case_result.get('n_problems', 0),
                    'P@5': m.get('P@5', 0),
                    'R@5': m.get('R@5', 0),
                    'F1@5': m.get('F1@5', 0),
                    'nDCG@5': m.get('nDCG@5', 0),
                    'MAP': m.get('MAP', 0),
                    'MRR': m.get('MRR', 0),
                })

            agg = result['aggregates']
            logger.info(f"    P@5:    {agg.get('P@5', {}).get('mean', 0):.4f} "
                        f"± {agg.get('P@5', {}).get('std', 0):.4f}")
            logger.info(f"    nDCG@5: {agg.get('nDCG@5', {}).get('mean', 0):.4f} "
                        f"± {agg.get('nDCG@5', {}).get('std', 0):.4f}")

        df = pd.DataFrame(all_rows)

        # Manipulation check: if the two arms detected identical problem counts
        # on every case, the L2 switch did not take effect. Report loudly
        # instead of letting a null result look like a finding.
        self._manipulation_check(df)

        self._raw_results = results_by_variant
        return df

    @staticmethod
    def _manipulation_check(df: pd.DataFrame) -> None:
        if df.empty or 'n_problems' not in df.columns:
            return
        pivot = df.pivot_table(index='case_id', columns='variant',
                               values='n_problems', aggfunc='first')
        if pivot.shape[1] < 2:
            return
        differing = int((pivot.nunique(axis=1) > 1).sum())
        total = int(pivot.shape[0])
        logger.info(f"\n  🔎 Manipulation check: detected-problem counts differ "
                    f"in {differing}/{total} cases")
        if differing == 0:
            logger.error(
                "  ❌ RQ1 manipulation check FAILED: the L1-only and L1+L2 arms "
                "produced the same number of detected problems on every case. "
                "The L2 switch did not take effect — do not report these "
                "numbers as evidence about L2."
            )

    def visualize(self, results: pd.DataFrame, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))

        metrics = ['P@5', 'R@5', 'F1@5', 'nDCG@5', 'MAP', 'MRR']
        avg = results.groupby('variant')[metrics].mean()

        # Plot 1: All metrics comparison
        colors = ['#2ECC71', '#E74C3C', '#3498DB', '#F39C12', '#9B59B6', '#1ABC9C']
        avg.plot(kind='bar', ax=axes[0], color=colors)
        axes[0].set_title('RQ1: L2 Filtering Impact — All Metrics', fontsize=13, fontweight='bold')
        axes[0].set_ylabel('Score')
        axes[0].set_ylim([0, 1])
        axes[0].legend(loc='lower right', fontsize=9)
        axes[0].grid(axis='y', alpha=0.3)
        axes[0].tick_params(axis='x', rotation=0)

        # Plot 2: Per-complexity breakdown (F1@5)
        complexity_avg = results.groupby(['variant', 'complexity'])['F1@5'].mean().unstack()
        if not complexity_avg.empty:
            complexity_avg.plot(kind='bar', ax=axes[1], color=['#3498DB', '#E74C3C', '#F39C12'])
            axes[1].set_title('F1@5 by Case Complexity', fontsize=13, fontweight='bold')
            axes[1].set_ylabel('F1@5')
            axes[1].set_ylim([0, 1])
            axes[1].legend(title='Complexity', fontsize=9)
            axes[1].grid(axis='y', alpha=0.3)
            axes[1].tick_params(axis='x', rotation=0)

        plt.tight_layout()
        plt.savefig(output_dir / 'rq1_l2_filtering_impact.png', dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"✅ RQ1 visualization saved")


class RQ2_AlphaSensitivity(AblationExperiment):
    """
    RQ2: How sensitive is performance to the α parameter?

    Test α ∈ {0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0}

    Hypothesis: Optimal α exists where problem-awareness helps without over-fitting.
    α=0 means no problem influence (baseline reranker score only).
    """

    def __init__(self):
        super().__init__(
            name="RQ2: α Parameter Sensitivity",
            description="Evaluate performance vs α (problem influence weight)"
        )

    def run(self, ablation_runner: AblationRunner) -> pd.DataFrame:
        logger.info(f"\n{'='*70}")
        logger.info(f"Running {self.name}")
        logger.info(f"{'='*70}\n")

        alpha_values = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0]
        all_rows = []

        for alpha in alpha_values:
            logger.info(f"\n  🔧 Testing α = {alpha}")

            if alpha == 0.0:
                # α=0 reduces to baseline (no problem boost)
                result = ablation_runner.evaluate_strategy('basic')
            else:
                retriever = ablation_runner.create_h2l_retriever(alpha=alpha)
                result = ablation_runner.evaluate_strategy('h2l-hybrid',
                                                           custom_retriever=retriever)

            for case_result in result['per_case']:
                m = case_result['metrics']
                all_rows.append({
                    'alpha': alpha,
                    'case_id': case_result['case_id'],
                    'complexity': case_result['complexity'],
                    'P@5': m.get('P@5', 0),
                    'R@5': m.get('R@5', 0),
                    'F1@5': m.get('F1@5', 0),
                    'nDCG@5': m.get('nDCG@5', 0),
                    'MAP': m.get('MAP', 0),
                    'MRR': m.get('MRR', 0),
                })

            agg = result['aggregates']
            logger.info(f"    F1@5: {agg.get('F1@5', {}).get('mean', 0):.4f}, "
                        f"nDCG@5: {agg.get('nDCG@5', {}).get('mean', 0):.4f}")

        df = pd.DataFrame(all_rows)
        return df

    def visualize(self, results: pd.DataFrame, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))

        # Plot 1: Performance curves over α
        metrics_to_plot = ['P@5', 'R@5', 'F1@5', 'nDCG@5']
        colors = ['#3498DB', '#E74C3C', '#2ECC71', '#F39C12']
        labels = ['Precision@5', 'Recall@5', 'F1@5', 'nDCG@5']

        avg_by_alpha = results.groupby('alpha')[metrics_to_plot].agg(['mean', 'std'])

        for metric, color, label in zip(metrics_to_plot, colors, labels):
            means = avg_by_alpha[(metric, 'mean')]
            stds = avg_by_alpha[(metric, 'std')]
            axes[0].plot(means.index, means.values, marker='o', linewidth=2,
                         color=color, label=label, markersize=7)
            axes[0].fill_between(means.index,
                                 means.values - stds.values,
                                 means.values + stds.values,
                                 alpha=0.15, color=color)

        # Mark optimal α
        f1_means = avg_by_alpha[('F1@5', 'mean')]
        optimal_alpha = f1_means.idxmax()
        axes[0].axvline(optimal_alpha, color='red', linestyle='--', alpha=0.5)
        axes[0].annotate(f'Optimal α={optimal_alpha}',
                         xy=(optimal_alpha, f1_means.max()),
                         xytext=(optimal_alpha + 0.2, f1_means.max() - 0.05),
                         fontsize=10, color='red', fontweight='bold',
                         arrowprops=dict(arrowstyle='->', color='red'))

        axes[0].set_title('RQ2: Performance vs α (Problem Influence Weight)',
                          fontsize=13, fontweight='bold')
        axes[0].set_xlabel('α', fontsize=12)
        axes[0].set_ylabel('Score', fontsize=12)
        axes[0].legend(loc='best', fontsize=9)
        axes[0].grid(True, alpha=0.3)
        axes[0].set_ylim([0, 1])

        # Plot 2: α effect by complexity
        complexity_f1 = results.groupby(['alpha', 'complexity'])['F1@5'].mean().unstack()
        if not complexity_f1.empty:
            for col in complexity_f1.columns:
                axes[1].plot(complexity_f1.index, complexity_f1[col], marker='s',
                             linewidth=2, label=col, markersize=6)
            axes[1].set_title('F1@5 vs α by Case Complexity', fontsize=13, fontweight='bold')
            axes[1].set_xlabel('α', fontsize=12)
            axes[1].set_ylabel('F1@5', fontsize=12)
            axes[1].legend(title='Complexity', fontsize=9)
            axes[1].grid(True, alpha=0.3)
            axes[1].set_ylim([0, 1])

        plt.tight_layout()
        plt.savefig(output_dir / 'rq2_alpha_sensitivity.png', dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"✅ RQ2 visualization saved")


class RQ3_MatchingMethod(AblationExperiment):
    """
    RQ3: What is the advantage of semantic vs keyword matching?

    Compare:
    - Semantic: P(d|p) via cosine similarity of embeddings
    - Keyword:  P(d|p) via keyword proportion matching

    Hypothesis: Semantic matching is more robust to paraphrasing.
    """

    def __init__(self):
        super().__init__(
            name="RQ3: Soft vs Hard Matching",
            description="Compare semantic similarity vs keyword matching for P(d|p)"
        )

    def run(self, ablation_runner: AblationRunner) -> pd.DataFrame:
        logger.info(f"\n{'='*70}")
        logger.info(f"Running {self.name}")
        logger.info(f"{'='*70}\n")

        all_rows = []

        # Variant 1: Semantic (default)
        logger.info("  🔧 Semantic matching (default)")
        retriever_semantic = ablation_runner.create_h2l_retriever(force_keyword=False)
        result_semantic = ablation_runner.evaluate_strategy('h2l-hybrid',
                                                            custom_retriever=retriever_semantic)

        for case_result in result_semantic['per_case']:
            m = case_result['metrics']
            all_rows.append({
                'variant': 'Semantic (Soft)',
                'case_id': case_result['case_id'],
                'complexity': case_result['complexity'],
                'P@5': m.get('P@5', 0), 'R@5': m.get('R@5', 0),
                'F1@5': m.get('F1@5', 0), 'nDCG@5': m.get('nDCG@5', 0),
                'MAP': m.get('MAP', 0), 'MRR': m.get('MRR', 0),
            })

        # Variant 2: Keyword-only
        logger.info("  🔧 Keyword matching (forced)")
        retriever_keyword = ablation_runner.create_h2l_retriever(force_keyword=True)
        result_keyword = ablation_runner.evaluate_strategy('h2l-hybrid',
                                                           custom_retriever=retriever_keyword)

        for case_result in result_keyword['per_case']:
            m = case_result['metrics']
            all_rows.append({
                'variant': 'Keyword (Hard)',
                'case_id': case_result['case_id'],
                'complexity': case_result['complexity'],
                'P@5': m.get('P@5', 0), 'R@5': m.get('R@5', 0),
                'F1@5': m.get('F1@5', 0), 'nDCG@5': m.get('nDCG@5', 0),
                'MAP': m.get('MAP', 0), 'MRR': m.get('MRR', 0),
            })

        agg_s = result_semantic['aggregates']
        agg_k = result_keyword['aggregates']
        logger.info(f"  Semantic F1@5: {agg_s.get('F1@5', {}).get('mean', 0):.4f}")
        logger.info(f"  Keyword  F1@5: {agg_k.get('F1@5', {}).get('mean', 0):.4f}")

        self._raw_results = {
            'Semantic (Soft)': result_semantic,
            'Keyword (Hard)': result_keyword,
        }
        return pd.DataFrame(all_rows)

    def visualize(self, results: pd.DataFrame, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))

        metrics = ['P@5', 'R@5', 'F1@5', 'nDCG@5', 'MAP', 'MRR']
        avg = results.groupby('variant')[metrics].mean()

        # Plot 1: Side-by-side bar chart
        x = np.arange(len(metrics))
        width = 0.35
        semantic_vals = avg.loc['Semantic (Soft)'].values
        keyword_vals = avg.loc['Keyword (Hard)'].values

        axes[0].bar(x - width/2, semantic_vals, width, label='Semantic (Soft)',
                    color='#2ECC71', edgecolor='white')
        axes[0].bar(x + width/2, keyword_vals, width, label='Keyword (Hard)',
                    color='#E74C3C', edgecolor='white')

        axes[0].set_title('RQ3: Semantic vs Keyword Matching', fontsize=13, fontweight='bold')
        axes[0].set_ylabel('Score')
        axes[0].set_xticks(x)
        axes[0].set_xticklabels(metrics)
        axes[0].legend(fontsize=10)
        axes[0].set_ylim([0, 1])
        axes[0].grid(axis='y', alpha=0.3)

        # Plot 2: Per-case paired difference
        semantic_cases = results[results['variant'] == 'Semantic (Soft)'].set_index('case_id')
        keyword_cases = results[results['variant'] == 'Keyword (Hard)'].set_index('case_id')
        common_ids = semantic_cases.index.intersection(keyword_cases.index)
        if len(common_ids) > 0:
            diff_f1 = semantic_cases.loc[common_ids, 'F1@5'] - keyword_cases.loc[common_ids, 'F1@5']
            diff_sorted = diff_f1.sort_values()
            colors_diff = ['#2ECC71' if d >= 0 else '#E74C3C' for d in diff_sorted.values]
            axes[1].barh(range(len(diff_sorted)), diff_sorted.values, color=colors_diff, height=0.7)
            axes[1].set_title('Per-Case F1@5 Difference (Semantic − Keyword)',
                              fontsize=13, fontweight='bold')
            axes[1].set_xlabel('Δ F1@5')
            axes[1].axvline(0, color='black', linewidth=0.5)
            axes[1].set_yticks(range(len(diff_sorted)))
            axes[1].set_yticklabels(diff_sorted.index, fontsize=6)
            axes[1].grid(axis='x', alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_dir / 'rq3_matching_method.png', dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"✅ RQ3 visualization saved")


class RQ4_PriorCalculation(AblationExperiment):
    """
    RQ4: How much does the severity-based prior improve performance?

    Compare:
    - Severity prior: P(p) = sev_i / Σ sev_j
    - Uniform prior:  P(p) = 1 / k

    Hypothesis: Severity-based prior improves ranking for critical cases.
    """

    def __init__(self):
        super().__init__(
            name="RQ4: Prior Calculation Impact",
            description="Evaluate severity-based vs uniform problem priors"
        )

    def run(self, ablation_runner: AblationRunner) -> pd.DataFrame:
        logger.info(f"\n{'='*70}")
        logger.info(f"Running {self.name}")
        logger.info(f"{'='*70}\n")

        all_rows = []
        cases = ablation_runner._load_cases()

        # Variant 1: Severity prior (default)
        logger.info("  🔧 Severity-based prior (default)")
        retriever_sev = ablation_runner.create_h2l_retriever(uniform_prior=False)
        result_sev = ablation_runner.evaluate_strategy('h2l-hybrid',
                                                       custom_retriever=retriever_sev)

        # Evaluation-only oracle metadata:
        # max_severity comes from expected_diagnosis labels for stratified reporting,
        # not from the retrieval/inference path. Do not use this as headline
        # end-to-end system evidence without this qualifier.
        severity_map = {}
        for case in cases:
            cid = case.get('case_id', '')
            probs = case.get('expected_diagnosis', {}).get('problem_list', [])
            max_sev = max((p.get('severity', 1) for p in probs), default=1) if probs else 1
            severity_map[cid] = max_sev

        for case_result in result_sev['per_case']:
            m = case_result['metrics']
            cid = case_result['case_id']
            all_rows.append({
                'variant': 'Severity Prior (oracle-stratified eval only)',
                'evidence_scope': 'evaluation-only; max_severity derived from expected_diagnosis labels',
                'case_id': cid,
                'complexity': case_result['complexity'],
                'max_severity': severity_map.get(cid, 1),
                'P@5': m.get('P@5', 0), 'R@5': m.get('R@5', 0),
                'F1@5': m.get('F1@5', 0), 'nDCG@5': m.get('nDCG@5', 0),
                'MAP': m.get('MAP', 0), 'MRR': m.get('MRR', 0),
            })

        # Variant 2: Uniform prior
        logger.info("  🔧 Uniform prior")
        retriever_uni = ablation_runner.create_h2l_retriever(uniform_prior=True)
        result_uni = ablation_runner.evaluate_strategy('h2l-hybrid',
                                                       custom_retriever=retriever_uni)

        for case_result in result_uni['per_case']:
            m = case_result['metrics']
            cid = case_result['case_id']
            all_rows.append({
                'variant': 'Uniform Prior (oracle-stratified eval only)',
                'evidence_scope': 'evaluation-only; max_severity derived from expected_diagnosis labels',
                'case_id': cid,
                'complexity': case_result['complexity'],
                'max_severity': severity_map.get(cid, 1),
                'P@5': m.get('P@5', 0), 'R@5': m.get('R@5', 0),
                'F1@5': m.get('F1@5', 0), 'nDCG@5': m.get('nDCG@5', 0),
                'MAP': m.get('MAP', 0), 'MRR': m.get('MRR', 0),
            })

        self._raw_results = {
            'Severity Prior': result_sev,
            'Uniform Prior': result_uni,
        }
        return pd.DataFrame(all_rows)

    def visualize(self, results: pd.DataFrame, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))

        metrics = ['P@5', 'R@5', 'F1@5', 'nDCG@5', 'MAP', 'MRR']
        avg = results.groupby('variant')[metrics].mean()

        # Plot 1: Overall comparison
        avg.plot(kind='bar', ax=axes[0], color=['#3498DB', '#E74C3C', '#2ECC71',
                                                 '#F39C12', '#9B59B6', '#1ABC9C'])
        axes[0].set_title('RQ4: Prior Calculation Impact (Overall)',
                          fontsize=13, fontweight='bold')
        axes[0].set_ylabel('Score')
        axes[0].set_ylim([0, 1])
        axes[0].legend(loc='lower right', fontsize=9)
        axes[0].grid(axis='y', alpha=0.3)
        axes[0].tick_params(axis='x', rotation=0)

        # Plot 2: By severity level
        results['severity_level'] = pd.cut(
            results['max_severity'],
            bins=[0, 2, 3, 5],
            labels=['Low (1-2)', 'Medium (3)', 'High (4-5)']
        )
        sev_grouped = results.groupby(['variant', 'severity_level'])['nDCG@5'].mean().unstack()
        if not sev_grouped.empty:
            sev_grouped.plot(kind='bar', ax=axes[1], color=['#3498DB', '#F39C12', '#E74C3C'])
            axes[1].set_title('nDCG@5 by Severity Level', fontsize=13, fontweight='bold')
            axes[1].set_ylabel('nDCG@5')
            axes[1].set_ylim([0, 1])
            axes[1].legend(title='Severity', fontsize=9)
            axes[1].grid(axis='y', alpha=0.3)
            axes[1].tick_params(axis='x', rotation=0)

        plt.tight_layout()
        plt.savefig(output_dir / 'rq4_prior_calculation.png', dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"✅ RQ4 visualization saved")


class RQ5_FilterToggle(AblationExperiment):
    """
    RQ5: Does H2L filtering as post-processing improve baseline strategies?

    Applies H2L scoring as a re-ranking filter on top of each baseline.
    This creates a 2×N factorial design:
      - Factor A: Base retrieval strategy (basic, dynamic, adaptive, multihop)
      - Factor B: H2L filter (OFF / ON)

    Hypothesis: H2L post-filtering consistently improves all baselines.
    """

    def __init__(self):
        super().__init__(
            name="RQ5: H2L Filter as Post-Processing",
            description="2×N factorial: Does H2L filter improve every baseline?"
        )

    def run(self, ablation_runner: AblationRunner) -> pd.DataFrame:
        logger.info(f"\n{'='*70}")
        logger.info(f"Running {self.name}")
        logger.info(f"{'='*70}\n")

        base_strategies = ['basic', 'dynamic', 'adaptive', 'multihop']
        all_rows = []

        for base in base_strategies:
            # Without H2L filter
            logger.info(f"\n  🔧 {base} (no filter)")
            result_off = ablation_runner.evaluate_strategy(base)
            for cr in result_off['per_case']:
                m = cr['metrics']
                all_rows.append({
                    'base_strategy': base, 'h2l_filter': 'OFF',
                    'case_id': cr['case_id'], 'complexity': cr['complexity'],
                    'P@5': m.get('P@5', 0), 'R@5': m.get('R@5', 0),
                    'F1@5': m.get('F1@5', 0), 'nDCG@5': m.get('nDCG@5', 0),
                    'MAP': m.get('MAP', 0), 'MRR': m.get('MRR', 0),
                })

            # With H2L filter
            h2l_key = f"{base}+h2l"
            logger.info(f"  🔧 {h2l_key} (with filter)")
            try:
                result_on = ablation_runner.evaluate_strategy(h2l_key)
                for cr in result_on['per_case']:
                    m = cr['metrics']
                    all_rows.append({
                        'base_strategy': base, 'h2l_filter': 'ON',
                        'case_id': cr['case_id'], 'complexity': cr['complexity'],
                        'P@5': m.get('P@5', 0), 'R@5': m.get('R@5', 0),
                        'F1@5': m.get('F1@5', 0), 'nDCG@5': m.get('nDCG@5', 0),
                        'MAP': m.get('MAP', 0), 'MRR': m.get('MRR', 0),
                    })
            except Exception as e:
                logger.error(f"    ❌ {h2l_key} failed: {e}")

            # Log comparison
            agg_off = result_off['aggregates']
            logger.info(f"    {base}        nDCG@5: {agg_off.get('nDCG@5', {}).get('mean', 0):.4f}")
            try:
                agg_on = result_on['aggregates']
                logger.info(f"    {h2l_key} nDCG@5: {agg_on.get('nDCG@5', {}).get('mean', 0):.4f}")
            except:
                pass

        return pd.DataFrame(all_rows)

    def visualize(self, results: pd.DataFrame, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        fig, axes = plt.subplots(1, 2, figsize=(16, 6))

        metrics = ['P@5', 'F1@5', 'nDCG@5', 'MAP']
        strategies = results['base_strategy'].unique()

        # Plot 1: Grouped bar chart (OFF vs ON per strategy)
        x = np.arange(len(strategies))
        width = 0.35

        for i, metric in enumerate(metrics):
            if i >= 2:
                break
            off_vals = [results[(results['base_strategy'] == s) & (results['h2l_filter'] == 'OFF')][metric].mean()
                        for s in strategies]
            on_vals = [results[(results['base_strategy'] == s) & (results['h2l_filter'] == 'ON')][metric].mean()
                       for s in strategies]

        # Use nDCG@5 for the main comparison
        off_ndcg = [results[(results['base_strategy'] == s) & (results['h2l_filter'] == 'OFF')]['nDCG@5'].mean()
                    for s in strategies]
        on_ndcg = [results[(results['base_strategy'] == s) & (results['h2l_filter'] == 'ON')]['nDCG@5'].mean()
                   for s in strategies]

        axes[0].bar(x - width/2, off_ndcg, width, label='Without H2L Filter',
                    color='#95A5A6', edgecolor='white')
        axes[0].bar(x + width/2, on_ndcg, width, label='With H2L Filter',
                    color='#27AE60', edgecolor='white')
        axes[0].set_title('RQ5: H2L Filter Effect on Baselines (nDCG@5)',
                          fontsize=13, fontweight='bold')
        axes[0].set_ylabel('nDCG@5')
        axes[0].set_xticks(x)
        axes[0].set_xticklabels(strategies)
        axes[0].legend(fontsize=10)
        axes[0].set_ylim([0, 1])
        axes[0].grid(axis='y', alpha=0.3)

        # Plot 2: Improvement delta
        deltas = [on - off for on, off in zip(on_ndcg, off_ndcg)]
        colors = ['#27AE60' if d >= 0 else '#E74C3C' for d in deltas]
        bars = axes[1].bar(strategies, deltas, color=colors, edgecolor='white')
        axes[1].set_title('Δ nDCG@5 (With Filter − Without)', fontsize=13, fontweight='bold')
        axes[1].set_ylabel('Δ nDCG@5')
        axes[1].axhline(0, color='black', linewidth=0.5)
        axes[1].grid(axis='y', alpha=0.3)
        for bar, val in zip(bars, deltas):
            axes[1].text(bar.get_x() + bar.get_width()/2, val + 0.005,
                         f'{val:+.3f}', ha='center', fontsize=10, fontweight='bold')

        plt.tight_layout()
        plt.savefig(output_dir / 'rq5_filter_toggle.png', dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"✅ RQ5 visualization saved")


class RQ6_V6ComponentAblation(AblationExperiment):
    """
    RQ6: Which V6 scoring components materially contribute to ranking quality?

    Compares the full V6 configuration against one-component-disabled variants.
    This supports claims about adaptive alpha, Bayesian prior integration, IDF
    specificity, margin activation, KL regularization, negation gating, and
    weighted-sum feature composition.
    """

    def __init__(self):
        super().__init__(
            name="RQ6: V6 Component Ablation",
            description="Disable one V6 component at a time and compare rank-aware metrics",
        )

    def _variant_configs(self):
        from H2L_core import H2LConfigV3

        def cfg(**overrides):
            # V6 Fix: Ensure fresh instance and correct flag names
            from H2L_core import H2LConfigV3
            instance = H2LConfigV3()
            for key, value in overrides.items():
                setattr(instance, key, value)
            return instance

        return {
            "Full V6": cfg(),
            "w/o Adaptive Alpha": cfg(ADAPTIVE_ALPHA_ENABLE=False),
            "w/o Bayesian Prior": cfg(BAYESIAN_PRIOR_ENABLE=False),
            "w/o IDF Specificity": cfg(IDF_ENABLE=False),
            "w/o Margin Activation": cfg(MARGIN_ENABLE=False),
            "w/o KL Penalty": cfg(KL_KAPPA=0.0),
            "w/o Negation Gate": cfg(NEG_ENABLE=False),
            "Product Feature Mode": cfg(FEATURE_MODE="product"),
        }

    @staticmethod
    def _score_key(result) -> float:
        """Use the mutated H2L score even for baseline wrappers with fixed final_score."""
        for attr in ("h2l_final_score", "rerank_score", "score", "final_score"):
            value = getattr(result, attr, None)
            if isinstance(value, (int, float, np.number)):
                return float(value)
        return 0.0

    def run(self, ablation_runner: AblationRunner) -> pd.DataFrame:
        logger.info(f"\n{'='*70}")
        logger.info(f"Running {self.name}")
        logger.info(f"{'='*70}\n")

        from evaluate_h2l_proper import (
            build_relevance_keywords,
            judge_relevance,
            compute_all_metrics,
        )
        from H2L_core import expand_query_with_problems

        all_rows = []
        self._raw_results = defaultdict(lambda: {"per_case": [], "aggregates": {}})
        cases = ablation_runner._load_cases()
        runner = ablation_runner._ensure_runner()
        candidate_pool_k = max(ablation_runner.top_k * 3, 30)
        variant_configs = self._variant_configs()

        # RQ6 is a component-level re-ranking ablation. We intentionally keep
        # the candidate pool fixed per case, then re-score that same pool with
        # each one-component-disabled configuration. This removes candidate-set
        # noise and is much faster than retrieving separately for every variant.
        case_bundles = []
        base_retriever = ablation_runner.create_h2l_retriever(h2l_config=variant_configs["Full V6"])
        logger.info("  📌 Building fixed candidate pools once per case (pool_k=%s)", candidate_pool_k)
        for i, case in enumerate(cases):
            query = case.get("case_description", "")
            if not query:
                continue

            expected = case.get("expected_diagnosis", {}).get("problem_list", [])
            relevance_keywords = build_relevance_keywords(expected, runner.taxonomy)
            detected_problems = ablation_runner.detected_problems_for_case(case, runner)
            expanded_query = (
                expand_query_with_problems(query, detected_problems, base_retriever.h2l_config)
                if detected_problems else query
            )

            try:
                base_results = base_retriever.base_retriever.retrieve(expanded_query, candidate_pool_k)
            except TypeError:
                base_results = base_retriever.base_retriever.retrieve(expanded_query)

            case_bundles.append({
                "case": case,
                "query": query,
                "expected": expected,
                "relevance_keywords": relevance_keywords,
                "detected_problems": detected_problems,
                "base_results": base_results,
            })

            if (i + 1) % 10 == 0:
                logger.info("    Candidate pools ready: %s/%s", i + 1, len(cases))

        metric_names = [
            "P@5", "R@5", "F1@5", "DCG@5", "IDCG@5", "nDCG@5",
            "P@10", "R@10", "F1@10", "DCG@10", "IDCG@10", "nDCG@10",
            "MAP", "MRR",
        ]

        for variant_name, h2l_cfg in variant_configs.items():
            logger.info(f"\n  🔧 Configuration: {variant_name}")
            retriever = ablation_runner.create_h2l_retriever(h2l_config=h2l_cfg)
            metric_lists = defaultdict(list)
            per_case = []

            for bundle in case_bundles:
                case = bundle["case"]
                query = bundle["query"]
                problems = bundle["detected_problems"]
                # copy.copy keeps document references but prevents score mutation
                # from leaking across variants.
                variant_results = [copy.deepcopy(r) for r in bundle["base_results"]]
                base_order = [getattr(getattr(r, "doc", None), "id", id(r)) for r in variant_results[:5]]
                base_order_at10 = [getattr(getattr(r, "doc", None), "id", id(r)) for r in variant_results[:10]]
                base_scores = [
                    float(getattr(r, "rerank_score", getattr(r, "score", 0.0)) or 0.0)
                    for r in variant_results
                ]

                # V6 Fix: Inject config directly to ensure isolation in shared runner
                retriever.h2l_config = h2l_cfg
                
                if problems:
                    variant_results = retriever._apply_h2l_scoring(variant_results, problems, query)
                variant_results.sort(key=self._score_key, reverse=True)
                ranked = variant_results[:ablation_runner.top_k]
                reranked_order = [getattr(getattr(r, "doc", None), "id", id(r)) for r in ranked[:5]]
                reranked_order_at10 = [getattr(getattr(r, "doc", None), "id", id(r)) for r in ranked[:10]]

                relevance_grades = []
                for r in ranked:
                    doc = r.doc if hasattr(r, "doc") else r
                    doc_text = getattr(doc, "text", "")
                    grade = judge_relevance(doc_text, bundle["relevance_keywords"], bundle["expected"])
                    relevance_grades.append(grade)

                m = compute_all_metrics(relevance_grades, k_values=[3, 5, 10])
                scored_values = [self._score_key(r) for r in variant_results]
                mean_score_delta = float(np.mean([
                    abs(after - before)
                    for before, after in zip(base_scores, scored_values)
                ])) if base_scores else 0.0

                # Q1 Enhancement: Capture raw H2L scores for between-variant comparison
                h2l_top5_scores = [round(self._score_key(r), 8) for r in ranked[:5]]
                h2l_mean_top5 = float(np.mean(h2l_top5_scores)) if h2l_top5_scores else 0.0

                case_result = {
                    "case_id": case.get("case_id", "unknown"),
                    "complexity": case.get("complexity", "unknown"),
                    "category": case.get("category", "unknown"),
                    **case_provenance_fields(case, ablation_runner.split),
                    "metrics": m,
                    "relevance_grades": relevance_grades,
                    "rank_changed_at5": base_order != reranked_order,
                    "rank_changed_at10": base_order_at10 != reranked_order_at10,
                    "mean_abs_score_delta": mean_score_delta,
                    "n_detected_problems": len(problems),
                    "h2l_mean_top5": h2l_mean_top5,
                }
                per_case.append(case_result)

                for metric_name, value in m.items():
                    if isinstance(value, (int, float)):
                        metric_lists[metric_name].append(value)

                all_rows.append({
                    "variant": variant_name,
                    "case_id": case_result["case_id"],
                    "complexity": case_result["complexity"],
                    "category": case_result.get("category", "unknown"),
                    "evaluation_slice": case_result["evaluation_slice"],
                    "augmentation_type": case_result["augmentation_type"],
                    "false_trigger_code": case_result["false_trigger_code"],
                    "P@5": m.get("P@5", 0),
                    "R@5": m.get("R@5", 0),
                    "F1@5": m.get("F1@5", 0),
                    "DCG@5": m.get("DCG@5", 0),
                    "IDCG@5": m.get("IDCG@5", 0),
                    "nDCG@5": m.get("nDCG@5", 0),
                    "P@10": m.get("P@10", 0),
                    "R@10": m.get("R@10", 0),
                    "F1@10": m.get("F1@10", 0),
                    "DCG@10": m.get("DCG@10", 0),
                    "IDCG@10": m.get("IDCG@10", 0),
                    "nDCG@10": m.get("nDCG@10", 0),
                    "MAP": m.get("MAP", 0),
                    "MRR": m.get("MRR", 0),
                    "rank_changed_at5": case_result["rank_changed_at5"],
                    "rank_changed_at10": case_result["rank_changed_at10"],
                    "mean_abs_score_delta": case_result["mean_abs_score_delta"],
                    "n_detected_problems": case_result["n_detected_problems"],
                    "h2l_mean_top5": case_result.get("h2l_mean_top5", 0.0),
                })

            agg = {}
            for metric_name, values in metric_lists.items():
                if values:
                    agg[metric_name] = {
                        "mean": float(np.mean(values)),
                        "std": float(np.std(values)),
                        "median": float(np.median(values)),
                        "min": float(np.min(values)),
                        "max": float(np.max(values)),
                        "n": len(values),
                        "values": values,
                    }
            self._raw_results[variant_name] = {
                "per_case": per_case,
                "aggregates": agg,
                "n_cases": len(per_case),
            }
            logger.info(
                "    MAP: %.4f, MRR: %.4f, nDCG@5: %.4f, nDCG@10: %.4f, rank_changed@5: %.1f%%, score_delta: %.4f",
                agg.get("MAP", {}).get("mean", 0),
                agg.get("MRR", {}).get("mean", 0),
                agg.get("nDCG@5", {}).get("mean", 0),
                agg.get("nDCG@10", {}).get("mean", 0),
                100.0 * np.mean([r["rank_changed_at5"] for r in per_case]) if per_case else 0.0,
                np.mean([r["mean_abs_score_delta"] for r in per_case]) if per_case else 0.0,
            )

        return pd.DataFrame(all_rows)

    def visualize(self, results: pd.DataFrame, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        metrics = ["MAP", "MRR", "nDCG@5", "nDCG@10"]
        avg = results.groupby("variant")[metrics].mean().sort_values("MAP", ascending=False)

        fig, ax = plt.subplots(figsize=(13, 6))
        avg.plot(kind="bar", ax=ax, color=["#2ECC71", "#3498DB", "#F39C12", "#8E44AD"])
        ax.set_title("RQ6: V6 Component Ablation", fontsize=13, fontweight="bold")
        ax.set_ylabel("Mean score")
        ax.set_ylim([0, max(0.05, min(1.0, float(avg.max().max()) + 0.08))])
        ax.grid(axis="y", alpha=0.3)
        ax.tick_params(axis="x", rotation=30)
        plt.tight_layout()
        plt.savefig(output_dir / "rq6_v6_component_ablation.png", dpi=300, bbox_inches="tight")
        plt.close()
        logger.info("✅ RQ6 visualization saved")


# ============================================================================
# ADVANCED COMPUTATIONAL ANALYSIS
# ============================================================================

class AdvancedComputationalAnalysis:
    """
    Publication-quality advanced analyses that go beyond basic means & p-values.

    Analyses:
        1. Bootstrap BCa CIs per strategy per metric
        2. Bayesian posterior P(H2L > Baseline)
        3. KL-Divergence / JS-Divergence of score distributions
        4. Kendall's τ rank correlation analysis
        5. Stratified effect heterogeneity — forest plots
        6. Component interaction heatmaps
    """

    def __init__(self):
        self.name = "Advanced Computational Analysis"

    def run(self, all_results: Dict[str, pd.DataFrame],
            output_dir: Path) -> Dict:
        """
        Run all advanced analyses on the collected experiment data.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        analysis_output = {}

        logger.info(f"\n{'='*70}")
        logger.info(f"🧮 {self.name}")
        logger.info(f"{'='*70}\n")

        # 1. Bootstrap BCa Confidence Intervals
        analysis_output['bootstrap'] = self._bootstrap_ci_analysis(
            all_results, output_dir)

        # 2. Bayesian Signed-Rank
        analysis_output['bayesian'] = self._bayesian_analysis(
            all_results, output_dir)

        # 3. Effect heterogeneity + forest plots
        analysis_output['forest'] = self._forest_plot_analysis(
            all_results, output_dir)

        # 4. Component interaction
        analysis_output['interaction'] = self._interaction_analysis(
            all_results, output_dir)

        return analysis_output

    def _bootstrap_ci_analysis(self, all_results, output_dir) -> Dict:
        """Bootstrap BCa CIs for each strategy/metric"""
        from evaluate_h2l_proper import bootstrap_bca_ci
        logger.info("  📊 Bootstrap BCa Confidence Intervals (1000 resamples)")

        boot_results = {}
        metrics_to_analyze = ['nDCG@5', 'P@5', 'MAP', 'MRR']

        # Use baseline results if available
        df = all_results.get('baselines')
        if df is None or df.empty:
            logger.info("    ⚠️ No baseline results for bootstrap analysis")
            return boot_results

        for method in df['method'].unique():
            method_data = df[df['method'] == method]
            boot_results[method] = {}
            for metric in metrics_to_analyze:
                if metric in method_data.columns:
                    vals = method_data[metric].values
                    ci = bootstrap_bca_ci(vals, n_bootstrap=1000)
                    boot_results[method][metric] = ci
                    logger.info(f"    {method:18s} {metric}: "
                                f"{ci['mean']:.4f} [{ci['ci_lower']:.4f}, {ci['ci_upper']:.4f}]")

        # Visualize: CI comparison plot
        self._plot_bootstrap_cis(boot_results, output_dir)
        return boot_results

    def _plot_bootstrap_cis(self, boot_results, output_dir):
        """Forest-style plot for bootstrap CIs"""
        fig, axes = plt.subplots(1, 2, figsize=(16, 6))
        metrics_for_plot = ['nDCG@5', 'MAP']

        for ax_idx, metric in enumerate(metrics_for_plot):
            methods = []
            means = []
            ci_lows = []
            ci_highs = []

            for method, data in boot_results.items():
                if metric in data:
                    methods.append(method)
                    means.append(data[metric]['mean'])
                    ci_lows.append(data[metric]['ci_lower'])
                    ci_highs.append(data[metric]['ci_upper'])

            if not methods:
                continue

            y_pos = range(len(methods))
            colors = ['#27AE60' if 'h2l' in m else '#95A5A6' for m in methods]
            err_low = [m - l for m, l in zip(means, ci_lows)]
            err_high = [h - m for m, h in zip(means, ci_highs)]

            axes[ax_idx].barh(y_pos, means, xerr=[err_low, err_high],
                              color=colors, capsize=4, height=0.6, edgecolor='white')
            axes[ax_idx].set_yticks(y_pos)
            axes[ax_idx].set_yticklabels(methods)
            axes[ax_idx].set_title(f'Bootstrap BCa 95% CI — {metric}',
                                   fontsize=13, fontweight='bold')
            axes[ax_idx].set_xlabel(metric)
            axes[ax_idx].grid(axis='x', alpha=0.3)
            axes[ax_idx].set_xlim([0, 1])

        plt.tight_layout()
        plt.savefig(output_dir / 'advanced_bootstrap_ci.png', dpi=300, bbox_inches='tight')
        plt.close()
        logger.info("    ✅ Bootstrap CI plot saved")

    def _bayesian_analysis(self, all_results, output_dir) -> Dict:
        """Bayesian signed-rank: P(H2L > Baseline) for each pair"""
        from evaluate_h2l_proper import bayesian_signed_rank
        logger.info("  📊 Bayesian Signed-Rank Analysis")

        bayes_results = {}
        df = all_results.get('baselines')
        if df is None or df.empty:
            return bayes_results

        baselines = [m for m in df['method'].unique() if 'h2l' not in m]
        h2l_strategies = [m for m in df['method'].unique() if 'h2l' in m]
        metric = 'nDCG@5'

        for bl in baselines:
            for h2l in h2l_strategies:
                bl_data = df[df['method'] == bl].set_index('case_id')[metric]
                h2l_data = df[df['method'] == h2l].set_index('case_id')[metric]
                common = bl_data.index.intersection(h2l_data.index)
                if len(common) < 3:
                    continue

                result = bayesian_signed_rank(
                    h2l_data.loc[common].values,
                    bl_data.loc[common].values,
                    rope=0.01
                )
                pair_key = f"{h2l} vs {bl}"
                bayes_results[pair_key] = result
                logger.info(f"    {pair_key}: P(H2L wins)={result['p_a_wins']:.3f}, "
                            f"P(ROPE)={result['p_rope']:.3f}, "
                            f"P(BL wins)={result['p_b_wins']:.3f}")

        # Visualize: Bayesian probabilities plot
        self._plot_bayesian(bayes_results, output_dir)
        return bayes_results

    def _plot_bayesian(self, bayes_results, output_dir):
        """Stacked bar chart of Bayesian posterior probabilities"""
        if not bayes_results:
            return

        fig, ax = plt.subplots(figsize=(12, max(4, len(bayes_results) * 0.5)))
        labels = list(bayes_results.keys())
        p_wins = [r['p_a_wins'] for r in bayes_results.values()]
        p_rope = [r['p_rope'] for r in bayes_results.values()]
        p_loses = [r['p_b_wins'] for r in bayes_results.values()]

        y_pos = range(len(labels))
        ax.barh(y_pos, p_wins, color='#27AE60', label='P(H2L wins)', height=0.6)
        ax.barh(y_pos, p_rope, left=p_wins, color='#F39C12', label='P(ROPE)', height=0.6)
        ax.barh(y_pos, p_loses, left=[w + r for w, r in zip(p_wins, p_rope)],
                color='#E74C3C', label='P(Baseline wins)', height=0.6)

        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=8)
        ax.set_xlabel('Posterior Probability')
        ax.set_title('Bayesian Signed-Rank: P(H2L > Baseline) on nDCG@5',
                      fontsize=13, fontweight='bold')
        ax.legend(loc='lower right', fontsize=9)
        ax.set_xlim([0, 1])
        ax.grid(axis='x', alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_dir / 'advanced_bayesian.png', dpi=300, bbox_inches='tight')
        plt.close()
        logger.info("    ✅ Bayesian analysis plot saved")

    def _forest_plot_analysis(self, all_results, output_dir) -> Dict:
        """Stratified effect heterogeneity: Cohen's d by complexity"""
        logger.info("  📊 Stratified Effect Heterogeneity (Forest Plots)")

        df = all_results.get('baselines')
        if df is None or df.empty:
            return {}

        # Compare best baseline vs best H2L, stratified by complexity
        baselines = [m for m in df['method'].unique() if 'h2l' not in m]
        h2l_strats = [m for m in df['method'].unique() if 'h2l' in m]
        if not baselines or not h2l_strats:
            return {}

        # Pick best baseline and best H2L by mean nDCG@5
        best_bl = max(baselines, key=lambda m: df[df['method'] == m]['nDCG@5'].mean())
        best_h2l = max(h2l_strats, key=lambda m: df[df['method'] == m]['nDCG@5'].mean())

        forest_data = {}
        complexities = df['complexity'].unique()

        for comp in complexities:
            bl_vals = df[(df['method'] == best_bl) & (df['complexity'] == comp)]['nDCG@5'].values
            h2l_vals = df[(df['method'] == best_h2l) & (df['complexity'] == comp)]['nDCG@5'].values
            if len(bl_vals) < 2 or len(h2l_vals) < 2:
                continue

            diff = h2l_vals[:min(len(bl_vals), len(h2l_vals))] - bl_vals[:min(len(bl_vals), len(h2l_vals))]
            d = float(np.mean(diff) / (np.std(diff) + 1e-10))
            se = float(np.std(diff) / np.sqrt(len(diff)))
            forest_data[comp] = {
                'cohens_d': round(d, 3),
                'se': round(se, 4),
                'n': len(diff),
                'ci_lower': round(d - 1.96 * se, 3),
                'ci_upper': round(d + 1.96 * se, 3),
            }
            logger.info(f"    {comp}: d={d:.3f} [{d - 1.96*se:.3f}, {d + 1.96*se:.3f}] (n={len(diff)})")

        # Forest plot
        self._plot_forest(forest_data, best_bl, best_h2l, output_dir)
        return forest_data

    def _plot_forest(self, forest_data, best_bl, best_h2l, output_dir):
        """Forest plot of effect sizes by complexity"""
        if not forest_data:
            return

        fig, ax = plt.subplots(figsize=(10, max(3, len(forest_data) * 0.8 + 2)))
        labels = list(forest_data.keys())
        d_vals = [forest_data[k]['cohens_d'] for k in labels]
        ci_lows = [forest_data[k]['ci_lower'] for k in labels]
        ci_highs = [forest_data[k]['ci_upper'] for k in labels]
        ns = [forest_data[k]['n'] for k in labels]

        y_pos = range(len(labels))
        err_low = [d - l for d, l in zip(d_vals, ci_lows)]
        err_high = [h - d for d, h in zip(d_vals, ci_highs)]

        ax.errorbar(d_vals, y_pos, xerr=[err_low, err_high],
                    fmt='D', color='#2C3E50', markersize=8, capsize=5,
                    linewidth=2, capthick=1.5)

        # Effect size regions
        ax.axvspan(-0.2, 0.2, alpha=0.08, color='gray', label='Negligible')
        ax.axvspan(0.2, 0.5, alpha=0.08, color='#F39C12', label='Small')
        ax.axvspan(0.5, 0.8, alpha=0.08, color='#E67E22', label='Medium')
        ax.axvspan(0.8, 3.0, alpha=0.08, color='#E74C3C', label='Large')
        ax.axvline(0, color='black', linewidth=0.5, linestyle='--')

        ax.set_yticks(y_pos)
        ax.set_yticklabels([f"{l} (n={n})" for l, n in zip(labels, ns)])
        ax.set_xlabel("Cohen's d (positive = H2L better)", fontsize=11)
        ax.set_title(f'Forest Plot: Effect Size by Complexity\n({best_h2l} vs {best_bl})',
                     fontsize=13, fontweight='bold')
        ax.legend(loc='lower right', fontsize=8)
        ax.grid(axis='x', alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_dir / 'advanced_forest_plot.png', dpi=300, bbox_inches='tight')
        plt.close()
        logger.info("    ✅ Forest plot saved")

    def _interaction_analysis(self, all_results, output_dir) -> Dict:
        """
        Component interaction heatmap: Do components have synergy?

        Tests interactions between:
        - L2 filtering × matching method
        - α level × prior type
        """
        logger.info("  📊 Component Interaction Analysis")

        interactions = {}

        rq1 = all_results.get('RQ1')
        rq3 = all_results.get('RQ3')
        if rq1 is not None and rq3 is not None and not rq1.empty and not rq3.empty:
            # L2 filtering × matching method interaction
            l2_variants = rq1['variant'].unique() if 'variant' in rq1.columns else []
            match_variants = rq3['variant'].unique() if 'variant' in rq3.columns else []

            interaction_matrix = {}
            for l2v in l2_variants:
                l2_vals = rq1[rq1['variant'] == l2v]['nDCG@5'].mean()
                for mv in match_variants:
                    m_vals = rq3[rq3['variant'] == mv]['nDCG@5'].mean()
                    # Estimated interaction: additive baseline vs observed
                    interaction_matrix[(l2v, mv)] = {
                        'l2_effect': round(float(l2_vals), 4),
                        'match_effect': round(float(m_vals), 4),
                        'combined_estimate': round(float((l2_vals + m_vals) / 2), 4),
                    }
            interactions['l2_x_matching'] = interaction_matrix

        # Interaction heatmap
        self._plot_interaction_heatmap(all_results, output_dir)
        return interactions

    def _plot_interaction_heatmap(self, all_results, output_dir):
        """Heatmap of component interactions"""
        rq1 = all_results.get('RQ1')
        rq3 = all_results.get('RQ3')
        if rq1 is None or rq3 is None or rq1.empty or rq3.empty:
            return

        l2_variants = rq1['variant'].unique() if 'variant' in rq1.columns else []
        match_variants = rq3['variant'].unique() if 'variant' in rq3.columns else []

        if len(l2_variants) < 2 or len(match_variants) < 2:
            return

        # Build heatmap data
        data = []
        for l2v in l2_variants:
            row = []
            for mv in match_variants:
                l2_vals = rq1[rq1['variant'] == l2v].set_index('case_id')['nDCG@5']
                m_vals = rq3[rq3['variant'] == mv].set_index('case_id')['nDCG@5']
                common = l2_vals.index.intersection(m_vals.index)
                if len(common) > 0:
                    row.append(float((l2_vals.loc[common].mean() + m_vals.loc[common].mean()) / 2))
                else:
                    row.append(0.0)
            data.append(row)

        fig, ax = plt.subplots(figsize=(8, 5))
        data_arr = np.array(data)

        if HAS_SEABORN:
            sns.heatmap(data_arr, annot=True, fmt='.3f', cmap='RdYlGn',
                        xticklabels=list(match_variants),
                        yticklabels=list(l2_variants),
                        ax=ax, vmin=0, vmax=1)
        else:
            im = ax.imshow(data_arr, cmap='RdYlGn', vmin=0, vmax=1, aspect='auto')
            ax.set_xticks(range(len(match_variants)))
            ax.set_xticklabels(list(match_variants))
            ax.set_yticks(range(len(l2_variants)))
            ax.set_yticklabels(list(l2_variants))
            for i in range(data_arr.shape[0]):
                for j in range(data_arr.shape[1]):
                    ax.text(j, i, f'{data_arr[i,j]:.3f}', ha='center', va='center', fontsize=12)
            plt.colorbar(im, ax=ax)

        ax.set_title('Component Interaction: L2 Filtering × Matching Method\n(nDCG@5)',
                     fontsize=13, fontweight='bold')
        ax.set_xlabel('Matching Method')
        ax.set_ylabel('L2 Configuration')

        plt.tight_layout()
        plt.savefig(output_dir / 'advanced_interaction_heatmap.png', dpi=300, bbox_inches='tight')
        plt.close()
        logger.info("    ✅ Interaction heatmap saved")


# ============================================================================
# BASELINE COMPARISON
# ============================================================================

class BaselineComparison:
    """
    Compare H2L V6 variants against baseline retrieval strategies.

    Uses real evaluation (no mock data) through EvaluationRunner.
    Now includes baseline+h2l-filter variants for complete factorial comparison.
    """

    def __init__(self):
        self.name = "Baseline Comparison"

    def run(self, ablation_runner: AblationRunner) -> pd.DataFrame:
        logger.info(f"\n{'='*70}")
        logger.info(f"Running {self.name}")
        logger.info(f"{'='*70}\n")

        strategies = [
            'basic', 'dynamic', 'adaptive', 'multihop',
            'basic+h2l', 'dynamic+h2l', 'adaptive+h2l', 'multihop+h2l',
            'h2l-hybrid', 'h2l-dynamic', 'h2l-adaptive', 'h2l-multihop',
        ]

        all_rows = []

        for strategy in strategies:
            logger.info(f"\n  🔧 Evaluating: {strategy}")
            try:
                result = ablation_runner.evaluate_strategy(strategy)
            except Exception as e:
                logger.error(f"    ❌ Failed: {e}")
                continue

            for case_result in result['per_case']:
                m = case_result['metrics']
                all_rows.append({
                    'method': strategy,
                    'case_id': case_result['case_id'],
                    'complexity': case_result['complexity'],
                    'P@5': m.get('P@5', 0), 'R@5': m.get('R@5', 0),
                    'F1@5': m.get('F1@5', 0), 'nDCG@5': m.get('nDCG@5', 0),
                    'MAP': m.get('MAP', 0), 'MRR': m.get('MRR', 0),
                    'retrieval_time': m.get('retrieval_time', 0),
                })

            agg = result['aggregates']
            logger.info(f"    nDCG@5: {agg.get('nDCG@5', {}).get('mean', 0):.4f} "
                        f"± {agg.get('nDCG@5', {}).get('std', 0):.4f}")

        return pd.DataFrame(all_rows)

    def visualize(self, results: pd.DataFrame, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)

        metrics = ['P@5', 'R@5', 'F1@5', 'nDCG@5', 'MAP', 'MRR']
        avg = results.groupby('method')[metrics].mean()

        # Order: baselines → +h2l filter → H2L unified
        method_order = [m for m in [
            'basic', 'dynamic', 'adaptive', 'multihop',
            'basic+h2l', 'dynamic+h2l', 'adaptive+h2l', 'multihop+h2l',
            'h2l-hybrid', 'h2l-dynamic', 'h2l-adaptive', 'h2l-multihop',
        ] if m in avg.index]
        avg = avg.reindex(method_order)

        fig, axes = plt.subplots(1, 2, figsize=(18, 7))

        # Plot 1: All metrics grouped bar chart
        avg[['P@5', 'F1@5', 'nDCG@5', 'MAP']].plot(kind='bar', ax=axes[0],
            color=['#3498DB', '#2ECC71', '#F39C12', '#9B59B6'])
        axes[0].set_title('All Strategies: Key Metrics', fontsize=13, fontweight='bold')
        axes[0].set_ylabel('Score')
        axes[0].set_ylim([0, 1])
        axes[0].legend(loc='lower right', fontsize=9)
        axes[0].grid(axis='y', alpha=0.3)
        axes[0].tick_params(axis='x', rotation=45)

        # Plot 2: Horizontal bar chart — nDCG@5 sorted with 3 color groups
        ndcg_sorted = avg['nDCG@5'].sort_values()
        color_map = []
        for m in ndcg_sorted.index:
            if 'h2l-' in m:
                color_map.append('#27AE60')  # H2L unified = green
            elif '+h2l' in m:
                color_map.append('#3498DB')  # +h2l filter = blue
            else:
                color_map.append('#95A5A6')  # baseline = gray

        bars = axes[1].barh(range(len(ndcg_sorted)), ndcg_sorted.values,
                            color=color_map, height=0.6)
        axes[1].set_title('nDCG@5 (sorted) — 3 strategy groups', fontsize=13, fontweight='bold')
        axes[1].set_xlabel('nDCG@5')
        axes[1].set_yticks(range(len(ndcg_sorted)))
        axes[1].set_yticklabels(ndcg_sorted.index)
        axes[1].set_xlim([0, 1])
        axes[1].grid(axis='x', alpha=0.3)

        # Legend
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='#95A5A6', label='Baseline'),
            Patch(facecolor='#3498DB', label='Baseline + H2L Filter'),
            Patch(facecolor='#27AE60', label='H2L Unified'),
        ]
        axes[1].legend(handles=legend_elements, loc='lower right', fontsize=9)

        # Value labels
        for bar, val in zip(bars, ndcg_sorted.values):
            axes[1].text(val + 0.01, bar.get_y() + bar.get_height()/2,
                         f'{val:.3f}', va='center', fontsize=9, fontweight='bold')

        plt.tight_layout()
        plt.savefig(output_dir / 'baseline_comparison.png', dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"✅ Baseline comparison visualization saved")


# ============================================================================
# STATISTICAL ANALYSIS
# ============================================================================

def run_pairwise_stats(df: pd.DataFrame, group_col: str,
                       metric_col: str, case_col: str = 'case_id',
                       reference_group: str = None,
                       adjust_method: str = None,
                       test_method: str = 'auto') -> Dict:
    """
    Run paired statistical tests between groups.

    Returns dict with test results per pair.
    """
    try:
        from scipy import stats as scipy_stats
    except ImportError:
        logger.warning("scipy not available — skipping statistical tests")
        return {}

    groups = df[group_col].unique()
    results = {}

    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            g1, g2 = groups[i], groups[j]
            if reference_group is not None and reference_group not in (g1, g2):
                continue
            if reference_group is not None and g2 == reference_group:
                g1, g2 = g2, g1
            df1 = df[df[group_col] == g1].set_index(case_col)[metric_col]
            df2 = df[df[group_col] == g2].set_index(case_col)[metric_col]

            if not df1.index.is_unique or not df2.index.is_unique:
                raise ValueError(
                    f"Paired statistics require one row per {case_col} and {group_col}"
                )

            common = df1.index.intersection(df2.index)
            if len(common) < 3:
                continue

            v1 = df1.loc[common].values
            v2 = df2.loc[common].values
            diff = v1 - v2

            if np.allclose(diff, 0.0, equal_nan=True):
                stat, p_val = 0.0, 1.0
                test_name = "No difference"
            else:
                if test_method == 'wilcoxon':
                    stat, p_val = scipy_stats.wilcoxon(
                        diff,
                        zero_method='wilcox',
                        alternative='two-sided',
                        method='auto',
                    )
                    test_name = "Wilcoxon"
                else:
                    # A paired t-test assumes normality of the paired differences.
                    try:
                        _, p_norm = scipy_stats.shapiro(diff)
                        is_normal = p_norm > 0.05
                    except Exception:
                        is_normal = False

                if test_method != 'wilcoxon' and is_normal:
                    stat, p_val = scipy_stats.ttest_rel(v1, v2)
                    test_name = "paired t-test"
                elif test_method != 'wilcoxon':
                    try:
                        stat, p_val = scipy_stats.wilcoxon(
                            diff,
                            zero_method='wilcox',
                            alternative='two-sided',
                            method='auto',
                        )
                        test_name = "Wilcoxon"
                    except Exception:
                        stat, p_val = 0.0, 1.0
                        test_name = "N/A"

            if not np.isfinite(p_val):
                p_val = 1.0

            # Cohen's d
            d = float(np.mean(diff) / (np.std(diff) + 1e-10))

            results[f"{g1} vs {g2}"] = {
                'test': test_name,
                'metric': metric_col,
                'reference': g1,
                'comparison': g2,
                'n_pairs': int(len(common)),
                'n_nonzero_differences': int(np.count_nonzero(np.abs(diff) > 1e-15)),
                'statistic': float(stat),
                'p_value': float(p_val),
                'significant': p_val < 0.05,
                'cohens_d': d,
                'effect': ('large' if abs(d) >= 0.8 else
                           'medium' if abs(d) >= 0.5 else
                           'small' if abs(d) >= 0.2 else 'negligible'),
                'mean_diff': float(np.mean(diff)),
                'median_diff': float(np.median(diff)),
                'ci_95': (
                    float(np.mean(diff) - 1.96*np.std(diff)/np.sqrt(len(diff))),
                    float(np.mean(diff) + 1.96*np.std(diff)/np.sqrt(len(diff))),
                ),
            }

    if adjust_method == 'holm' and results:
        ordered = sorted(results.items(), key=lambda item: item[1]['p_value'])
        adjusted = {}
        running_max = 0.0
        count = len(ordered)
        for rank, (pair, result) in enumerate(ordered):
            raw_p = float(result['p_value'])
            corrected = min(1.0, (count - rank) * raw_p)
            running_max = max(running_max, corrected)
            adjusted[pair] = min(1.0, running_max)
        for pair, result in results.items():
            result['raw_p_value'] = result['p_value']
            result['p_value'] = adjusted[pair]
            result['p_adjustment'] = 'Holm-Bonferroni'
            result['significant'] = adjusted[pair] < 0.05

    return results


# ============================================================================
# REPORT GENERATOR
# ============================================================================

def generate_report(all_results: Dict[str, pd.DataFrame],
                    all_stats: Dict[str, Dict],
                    output_dir: Path):
    """Generate comprehensive Markdown ablation report"""

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    lines = [
        "# H2L V6 Ablation Study — Full Report",
        f"\n**Generated**: {timestamp}",
        f"**Evaluation**: Real retrieval via EvaluationRunner with ground truth cases",
        "",
        "---",
        "",
        "## Overview",
        "",
        "This study systematically evaluates H2L V6 components using **real retrieval** ",
        "(not simulated/mock data). Each experiment toggles one component while holding ",
        "others constant, measuring impact on rank-aware metrics.",
        "",
    ]

    # ── RQ Results ──
    rq_names = {
        'RQ1': ('L2 Filtering Impact', 'variant'),
        'RQ2': ('α Parameter Sensitivity', 'alpha'),
        'RQ3': ('Matching Methods', 'variant'),
        'RQ4': ('Prior Calculation', 'variant'),
        'RQ5': ('H2L Filter Toggle', 'base_strategy'),
        'RQ6': ('V6 Component Ablation', 'variant'),
    }

    for rq_key, (title, group_col) in rq_names.items():
        if rq_key not in all_results:
            continue
        df = all_results[rq_key]
        stats = all_stats.get(rq_key, {})

        lines.append(f"## {rq_key}: {title}")
        lines.append("")

        # Metrics table
        metrics_cols = [
            'P@5', 'R@5', 'F1@5', 'DCG@5', 'IDCG@5', 'nDCG@5',
            'P@10', 'R@10', 'F1@10', 'DCG@10', 'IDCG@10', 'nDCG@10',
            'MAP', 'MRR',
        ]
        available_metrics = [m for m in metrics_cols if m in df.columns]
        avg = df.groupby(group_col)[available_metrics].agg(['mean', 'std'])

        lines.append("| Configuration | " + " | ".join(available_metrics) + " |")
        lines.append("|" + "|".join(["---"] * (len(available_metrics) + 1)) + "|")

        for row_name in avg.index:
            vals = []
            for m in available_metrics:
                mean = avg.loc[row_name, (m, 'mean')]
                std = avg.loc[row_name, (m, 'std')]
                vals.append(f"{mean:.4f} ± {std:.4f}")
            lines.append(f"| {row_name} | " + " | ".join(vals) + " |")
        lines.append("")

        if rq_key == 'RQ6' and {'rank_changed_at5', 'rank_changed_at10', 'mean_abs_score_delta', 'n_detected_problems'}.issubset(df.columns):
            diag = df.groupby(group_col).agg(
                rank_changed_at5=('rank_changed_at5', 'mean'),
                rank_changed_at10=('rank_changed_at10', 'mean'),
                mean_abs_score_delta=('mean_abs_score_delta', 'mean'),
                mean_detected_problems=('n_detected_problems', 'mean'),
            ).sort_values('mean_abs_score_delta', ascending=False)

            lines.append("**Score/Ranking Diagnostics:**")
            lines.append("")
            lines.append("| Configuration | rank_changed@5 | rank_changed@10 | mean_abs_score_delta | mean_detected_problems |")
            lines.append("|---|---:|---:|---:|---:|")
            for row_name in diag.index:
                lines.append(
                    f"| {row_name} | "
                    f"{diag.loc[row_name, 'rank_changed_at5']:.1%} | "
                    f"{diag.loc[row_name, 'rank_changed_at10']:.1%} | "
                    f"{diag.loc[row_name, 'mean_abs_score_delta']:.4f} | "
                    f"{diag.loc[row_name, 'mean_detected_problems']:.2f} |"
                )
            lines.append("")
            full_rows = df[df[group_col] == 'Full V6'].set_index('case_id')
            rank_metrics_changed = False
            for variant in df[group_col].unique():
                if variant == 'Full V6':
                    continue
                variant_rows = df[df[group_col] == variant].set_index('case_id')
                common = full_rows.index.intersection(variant_rows.index)
                for metric in ('nDCG@5', 'nDCG@10', 'MAP', 'MRR'):
                    if metric in df.columns and not np.allclose(
                        full_rows.loc[common, metric],
                        variant_rows.loc[common, metric],
                    ):
                        rank_metrics_changed = True
                        break
                if rank_metrics_changed:
                    break
            if rank_metrics_changed:
                interpretation = (
                    "Interpretation: at least one one-component-disabled variant changes "
                    "a rank-aware relevance metric in this run. Statistical tests below "
                    "determine whether those paired changes survive multiplicity correction."
                )
            else:
                interpretation = (
                    "Interpretation: rank-aware relevance metrics are unchanged across "
                    "one-component-disabled variants in this run, although score and ordering "
                    "diagnostics may still change."
                )
            lines.append(interpretation)
            lines.append(
                "Treat score-only changes as component sensitivity evidence, not causal "
                "component-level effectiveness evidence."
            )
            lines.append("")

        # Statistical tests
        if stats:
            lines.append("**Statistical Tests:**")
            lines.append("")
            for pair, test_result in stats.items():
                sig = "✅ significant" if test_result['significant'] else "❌ not significant"
                if 'raw_p_value' in test_result:
                    p_text = (
                        f"raw p={test_result['raw_p_value']:.4f}, "
                        f"Holm p={test_result['p_value']:.4f}"
                    )
                else:
                    p_text = f"p={test_result['p_value']:.4f}"
                lines.append(
                    f"- **{test_result.get('metric', 'metric')} — {pair}**: {test_result['test']}, "
                    f"{p_text} ({sig}), "
                    f"Cohen's d={test_result['cohens_d']:.3f} ({test_result['effect']}), "
                    f"95% CI: {test_result['ci_95']}"
                )
            lines.append("")

        image_map = {
            'RQ1': 'rq1_l2_filtering_impact.png',
            'RQ2': 'rq2_alpha_sensitivity.png',
            'RQ3': 'rq3_matching_method.png',
            'RQ4': 'rq4_prior_calculation.png',
            'RQ5': 'rq5_filter_toggle.png',
            'RQ6': 'rq6_v6_component_ablation.png',
        }
        image_name = image_map.get(rq_key)
        if image_name and (output_dir / image_name).exists():
            lines.append(f"![{rq_key}]({image_name})")
        lines.append("")
        lines.append("---")
        lines.append("")

    # ── Baseline comparison ──
    if 'baselines' in all_results:
        df = all_results['baselines']
        lines.append("## Baseline Comparison")
        lines.append("")

        metrics_cols = ['P@5', 'F1@5', 'nDCG@5', 'MAP', 'MRR']
        available = [m for m in metrics_cols if m in df.columns]
        avg = df.groupby('method')[available].mean()

        method_order = [m for m in ['basic', 'dynamic', 'adaptive', 'multihop',
                                     'h2l-hybrid', 'h2l-dynamic', 'h2l-adaptive',
                                     'h2l-multihop'] if m in avg.index]
        avg = avg.reindex(method_order)

        lines.append("| Method | " + " | ".join(available) + " |")
        lines.append("|" + "|".join(["---"] * (len(available) + 1)) + "|")
        for method in avg.index:
            vals = [f"{avg.loc[method, m]:.4f}" for m in available]
            prefix = "**" if 'h2l' in method else ""
            suffix = "**" if 'h2l' in method else ""
            lines.append(f"| {prefix}{method}{suffix} | " + " | ".join(vals) + " |")
        lines.append("")
        lines.append("---")
        lines.append("")

    # ── Advanced Analysis Summary ──
    adv = all_results.get('_advanced_analysis')
    if adv and isinstance(adv, dict):
        lines.append("## Advanced Computational Analysis")
        lines.append("")

        boot = adv.get('bootstrap', {})
        if boot:
            lines.append("### Bootstrap BCa 95% Confidence Intervals")
            lines.append("")
            lines.append("| Strategy | nDCG@5 | MAP |")
            lines.append("|---|---|---|")
            for method, metrics_data in boot.items():
                ndcg = metrics_data.get('nDCG@5', {})
                map_d = metrics_data.get('MAP', {})
                lines.append(
                    f"| {method} | "
                    f"{ndcg.get('mean', 0):.4f} [{ndcg.get('ci_lower', 0):.4f}, {ndcg.get('ci_upper', 0):.4f}] | "
                    f"{map_d.get('mean', 0):.4f} [{map_d.get('ci_lower', 0):.4f}, {map_d.get('ci_upper', 0):.4f}] |"
                )
            lines.append("")

        bayes = adv.get('bayesian', {})
        if bayes:
            lines.append("### Bayesian Signed-Rank Analysis")
            lines.append("")
            lines.append("| Comparison | P(H2L wins) | P(ROPE) | P(Baseline wins) |")
            lines.append("|---|---|---|---|")
            for pair, res in bayes.items():
                lines.append(
                    f"| {pair} | {res['p_a_wins']:.3f} | {res['p_rope']:.3f} | {res['p_b_wins']:.3f} |"
                )
            lines.append("")

        forest = adv.get('forest', {})
        if forest:
            lines.append("### Stratified Effect Size (Forest)")
            lines.append("")
            lines.append("| Complexity | Cohen's d | 95% CI | n |")
            lines.append("|---|---|---|---|")
            for comp, data in forest.items():
                lines.append(
                    f"| {comp} | {data['cohens_d']:.3f} | [{data['ci_lower']:.3f}, {data['ci_upper']:.3f}] | {data['n']} |"
                )
            lines.append("")

        lines.append("---")
        lines.append("")

    # ── Files generated ──
    lines.append("## Generated Files")
    lines.append("")
    generated_files = sorted(
        p.name for p in output_dir.iterdir()
        if p.is_file() and p.name != "ABLATION_STUDY_REPORT.md"
    )
    if generated_files:
        for name in generated_files:
            lines.append(f"- `{name}`")
    else:
        lines.append("- No data or visualization files were generated.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*Generated by H2L V6 Ablation Study (real evaluation pipeline)*")

    report_path = output_dir / 'ABLATION_STUDY_REPORT.md'
    report_path.write_text('\n'.join(lines), encoding='utf-8')
    logger.info(f"✅ Report saved: {report_path}")


def write_rq6_structured_artifacts(
    frame: pd.DataFrame,
    stats: Dict,
    output_dir: Path,
) -> None:
    """Persist machine-readable RQ6 statistics and held-out slice summaries."""
    stat_rows = []
    for result in stats.values():
        ci_low, ci_high = result.get('ci_95', (None, None))
        stat_rows.append({
            'metric': result.get('metric'),
            'reference': result.get('reference'),
            'comparison': result.get('comparison'),
            'test': result.get('test'),
            'n_pairs': result.get('n_pairs'),
            'n_nonzero_differences': result.get('n_nonzero_differences'),
            'reference_minus_comparison_mean': result.get('mean_diff'),
            'median_difference': result.get('median_diff'),
            'statistic': result.get('statistic'),
            'raw_p': result.get('raw_p_value', result.get('p_value')),
            'holm_p': result.get('p_value') if result.get('p_adjustment') else None,
            'significant_0_05': result.get('significant'),
            'cohens_d_paired': result.get('cohens_d'),
            'effect': result.get('effect'),
            'ci_95_low': ci_low,
            'ci_95_high': ci_high,
            'multiplicity_correction': result.get('p_adjustment'),
        })
    pd.DataFrame(stat_rows).to_csv(
        output_dir / 'rq6_significance.csv',
        index=False,
        encoding='utf-8',
    )

    metric_columns = [
        metric
        for metric in (
            'P@5', 'R@5', 'F1@5', 'DCG@5', 'IDCG@5', 'nDCG@5',
            'P@10', 'R@10', 'F1@10', 'DCG@10', 'IDCG@10', 'nDCG@10',
            'MAP', 'MRR',
        )
        if metric in frame.columns
    ]
    slices = [('all_test', frame)]
    if 'evaluation_slice' in frame.columns:
        slices.extend(
            (str(slice_name), slice_frame)
            for slice_name, slice_frame in frame.groupby('evaluation_slice', sort=False)
        )

    slice_rows = []
    for slice_name, slice_frame in slices:
        for variant, variant_frame in slice_frame.groupby('variant', sort=False):
            row = {
                'evaluation_slice': slice_name,
                'variant': variant,
                'n_cases': int(variant_frame['case_id'].nunique()),
            }
            for metric in metric_columns:
                row[f'{metric}_mean'] = float(variant_frame[metric].mean())
                row[f'{metric}_std'] = float(variant_frame[metric].std(ddof=1))
            slice_rows.append(row)
    pd.DataFrame(slice_rows).to_csv(
        output_dir / 'rq6_slice_summary.csv',
        index=False,
        encoding='utf-8',
    )


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def run_full_ablation_study(output_dir: str = "ablation_results",
                            max_cases: int = None,
                            rq_filter: List[int] = None,
                            skip_baselines: bool = False,
                            split: str = "all",
                            ground_truth_path: str = "expanded_ground_truth.json",
                            top_k: int = 15,
                            detected_problems_cache_path: str = None,
                            detected_problems_model: str = "qwen2.5:7b",
                            detected_problems_repeat: int = 1):
    """
    Run all ablation experiments with real retrieval evaluation.

    Args:
        output_dir: Directory for results
        max_cases: Limit ground truth cases (for quick testing)
        rq_filter: Only run specific RQs (e.g. [1, 2])
        skip_baselines: Skip baseline comparison
        split: Ground-truth split to evaluate (all, train, or test)
        ground_truth_path: Split-annotated ground-truth JSON
        top_k: Number of ranked documents retained for metric computation
        detected_problems_cache_path: Optional L2 matrix with cached detector outputs
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    logger.info("\n" + "="*70)
    logger.info("H2L V6 ABLATION STUDY — Real Evaluation Pipeline")
    logger.info("="*70)
    logger.info(f"Output: {output_path.absolute()}")
    logger.info(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Ground-truth split: {split}")
    if max_cases:
        logger.info(f"Max cases: {max_cases}")
    logger.info("="*70 + "\n")

    # Initialize
    ablation = AblationRunner(
        ground_truth_path=ground_truth_path,
        max_cases=max_cases,
        top_k=top_k,
        split=split,
        detected_problems_cache_path=detected_problems_cache_path,
        detected_problems_model=detected_problems_model,
        detected_problems_repeat=detected_problems_repeat,
    )

    cache_provenance = ablation.validate_detected_problems_cache()
    ground_truth_file = Path(ablation.ground_truth_path)
    ground_truth_payload = json.loads(ground_truth_file.read_text(encoding='utf-8'))
    ground_truth_metadata = ground_truth_payload.get('metadata', {})
    run_metadata = {
        'status': 'running',
        'generated_at': datetime.now().isoformat(),
        'ground_truth_path': repository_path(ground_truth_file),
        'ground_truth_sha256': file_sha256(ground_truth_file),
        'ground_truth_total_cases': ground_truth_metadata.get('total_cases'),
        'ground_truth_train_cases': ground_truth_metadata.get('train_cases'),
        'ground_truth_test_cases': ground_truth_metadata.get('test_cases'),
        'ground_truth_adversarial_cases': ground_truth_metadata.get('adversarial_test_cases'),
        'h2l_core_sha256': file_sha256(Path('H2L_core.py')),
        'split': split,
        'available_cases_after_filter': len(ablation._load_cases()),
        'max_cases': max_cases,
        'top_k': top_k,
        'candidate_pool_k': max(top_k * 3, 30),
        'rq_filter': rq_filter,
        'skip_baselines': skip_baselines,
        'detected_problems_cache': cache_provenance,
    }

    def save_run_metadata() -> None:
        with (output_path / 'run_metadata.json').open('w', encoding='utf-8') as handle:
            json.dump(run_metadata, handle, ensure_ascii=False, indent=2)

    save_run_metadata()

    # Define experiments
    experiments = {
        1: RQ1_L2Filtering(),
        2: RQ2_AlphaSensitivity(),
        3: RQ3_MatchingMethod(),
        4: RQ4_PriorCalculation(),
        5: RQ5_FilterToggle(),
        6: RQ6_V6ComponentAblation(),
    }

    if rq_filter:
        experiments = {k: v for k, v in experiments.items() if k in rq_filter}

    all_results = {}
    all_stats = {}
    failed_experiments = {}

    # ── Run RQ experiments ──
    for rq_num, exp in experiments.items():
        rq_key = f"RQ{rq_num}"
        logger.info(f"\n🔬 Starting {exp.name}")

        start = time.time()
        try:
            df = exp.run(ablation)
        except Exception as e:
            logger.error(f"❌ {rq_key} failed: {e}")
            import traceback
            traceback.print_exc()
            failed_experiments[rq_key] = str(e)
            continue
        elapsed = time.time() - start

        # Save raw data
        csv_path = output_path / f'{rq_key.lower()}_results.csv'
        df.to_csv(csv_path, index=False, encoding='utf-8')
        logger.info(f"  💾 Data saved: {csv_path} ({len(df)} rows, {elapsed:.1f}s)")

        # Visualize
        try:
            exp.visualize(df, output_path)
        except Exception as e:
            logger.warning(f"  ⚠️ Visualization failed: {e}")

        # Statistical tests
        group_col = 'alpha' if rq_num == 2 else 'h2l_filter' if rq_num == 5 else 'variant'
        try:
            if rq_num == 6:
                stats = {}
                for metric_col in ('nDCG@5', 'nDCG@10'):
                    metric_stats = run_pairwise_stats(
                        df,
                        group_col,
                        metric_col,
                        reference_group='Full V6',
                        adjust_method='holm',
                        test_method='wilcoxon',
                    )
                    stats.update({f"{metric_col}: {pair}": result for pair, result in metric_stats.items()})
            else:
                stats = run_pairwise_stats(df, group_col, 'nDCG@5')
            all_stats[rq_key] = stats
        except Exception as e:
            logger.warning(f"  ⚠️ Stats failed: {e}")
            all_stats[rq_key] = {}
            if rq_num == 6:
                failed_experiments[f'{rq_key}_statistics'] = str(e)

        all_results[rq_key] = df
        if rq_num == 6 and all_stats.get(rq_key):
            write_rq6_structured_artifacts(
                df,
                all_stats[rq_key],
                output_path,
            )

    # ── Baseline comparison ──
    if not skip_baselines:
        logger.info("\n🔬 Starting Baseline Comparison")
        baseline = BaselineComparison()
        start = time.time()
        try:
            df_baselines = baseline.run(ablation)
            csv_path = output_path / 'baseline_results.csv'
            df_baselines.to_csv(csv_path, index=False, encoding='utf-8')
            logger.info(f"  💾 Data saved: {csv_path} ({len(df_baselines)} rows)")

            baseline.visualize(df_baselines, output_path)
            all_results['baselines'] = df_baselines

            # Stats: compare best baseline vs best H2L
            try:
                stats_bl = run_pairwise_stats(df_baselines, 'method', 'nDCG@5')
                all_stats['baselines'] = stats_bl
            except Exception as e:
                logger.warning(f"  ⚠️ Baseline stats failed: {e}")
        except Exception as e:
            logger.error(f"❌ Baseline comparison failed: {e}")
            import traceback
            traceback.print_exc()

    # ── Advanced computational analysis ──
    if not skip_baselines and 'baselines' in all_results:
        logger.info("\n🧮 Running Advanced Computational Analysis")
        advanced = AdvancedComputationalAnalysis()
        try:
            analysis_output = advanced.run(all_results, output_path)
            all_results['_advanced_analysis'] = analysis_output
        except Exception as e:
            logger.error(f"❌ Advanced analysis failed: {e}")
            import traceback
            traceback.print_exc()

    # ── Generate report ──
    generate_report(all_results, all_stats, output_path)

    run_metadata['completed_at'] = datetime.now().isoformat()
    run_metadata['failed_experiments'] = failed_experiments
    run_metadata['status'] = 'complete' if not failed_experiments else 'failed'
    run_metadata['generated_files'] = sorted(
        path.name for path in output_path.iterdir() if path.is_file()
    )
    save_run_metadata()

    if failed_experiments:
        raise RuntimeError(
            "Ablation study did not complete all requested outputs: "
            + "; ".join(f"{key}={value}" for key, value in failed_experiments.items())
        )

    logger.info("\n" + "="*70)
    logger.info("✅ Ablation study completed!")
    logger.info("="*70)
    logger.info(f"\nResults in: {output_path.absolute()}")
    logger.info("Files:")
    for f in sorted(output_path.glob('*')):
        logger.info(f"  • {f.name}")

    return all_results


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='H2L V6 Ablation Study')
    parser.add_argument('--max-cases', type=int, default=None,
                        help='Limit number of ground truth cases (for quick testing)')
    parser.add_argument('--rq', type=int, nargs='+', default=None,
                        help='Run specific RQs only (e.g. --rq 1 2)')
    parser.add_argument('--skip-baselines', action='store_true',
                        help='Skip baseline comparison')
    parser.add_argument('--output-dir', type=str, default='ablation_results',
                        help='Output directory')
    parser.add_argument('--split', choices=['all', 'train', 'test'], default='all',
                        help='Ground-truth split to evaluate (default: all)')
    parser.add_argument('--ground-truth', default='expanded_ground_truth.json',
                        help='Split-annotated ground-truth JSON')
    parser.add_argument('--top-k', type=int, default=15,
                        help='Number of ranked documents retained (default: 15)')
    parser.add_argument('--detected-problems-cache', default=None,
                        help='L2 matrix JSON containing per-case detected_problems')
    parser.add_argument('--detected-problems-model', default='qwen2.5:7b',
                        help='Model key to select from the detected-problems cache')
    parser.add_argument('--detected-problems-repeat', type=int, default=1,
                        help='Repeat number to select from the detected-problems cache')

    args = parser.parse_args()

    run_full_ablation_study(
        output_dir=args.output_dir,
        max_cases=args.max_cases,
        rq_filter=args.rq,
        skip_baselines=args.skip_baselines,
        split=args.split,
        ground_truth_path=args.ground_truth,
        top_k=args.top_k,
        detected_problems_cache_path=args.detected_problems_cache,
        detected_problems_model=args.detected_problems_model,
        detected_problems_repeat=args.detected_problems_repeat,
    )
