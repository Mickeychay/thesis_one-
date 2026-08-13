#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
H2L Proper Evaluation — Rank-Aware Metrics with Problem-Code Relevance
=======================================================================
Replaces the broken keyword-coverage quality metric with:
  • nDCG@K — measures ranking quality with graded relevance
  • MAP    — measures average precision across all relevant docs
  • MRR    — measures how early the first relevant doc appears
  • P@K    — precision at cutoff K
  • R@K    — recall at cutoff K

Relevance is judged by matching retrieved doc content against expected
problem codes/keywords from the ground truth.

Usage:
    python evaluate_h2l_proper.py                     # Full evaluation
    python evaluate_h2l_proper.py --self-test          # Unit test mode
    python evaluate_h2l_proper.py --strategies h2l-hybrid basic  # Specific strategies
"""

import json
import math
import time
import logging
import argparse
import re
import sys
import os
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    # Pure-Python fallback for basic stats
    class _NpFallback:
        @staticmethod
        def mean(x): return sum(x) / len(x) if x else 0.0
        @staticmethod
        def std(x):
            if not x: return 0.0
            m = sum(x) / len(x)
            return (sum((v - m)**2 for v in x) / len(x)) ** 0.5
        @staticmethod
        def median(x):
            s = sorted(x)
            n = len(s)
            if n == 0: return 0.0
            if n % 2 == 1: return s[n // 2]
            return (s[n // 2 - 1] + s[n // 2]) / 2
        @staticmethod
        def min(x): return min(x) if x else 0.0
        @staticmethod
        def max(x): return max(x) if x else 0.0
        @staticmethod
        def array(x): return list(x)
        @staticmethod
        def sqrt(x): return x ** 0.5
    np = _NpFallback()

log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)
log_file = log_dir / f"evaluate_h2l_proper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(str(log_file), encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

LATEST_ARTIFACT_BASENAMES = {
    'summary': 'proper_eval_latest_summary.json',
    'raw': 'proper_eval_latest_raw.json',
    'cases': 'proper_eval_latest_cases.json',
}

CHECKPOINT_ARTIFACT_BASENAMES = {
    'summary': 'proper_eval_checkpoint_summary.json',
    'raw': 'proper_eval_checkpoint_raw.json',
    'cases': 'proper_eval_checkpoint_cases.json',
}

PROGRESS_ARTIFACT_BASENAME = 'proper_eval_progress.json'


def load_test_cases_from_ground_truth(ground_truth_path: str = "expanded_ground_truth.json") -> List[Dict]:
    """Load only test cases and fail fast if split annotations are missing."""
    with open(ground_truth_path, 'r', encoding='utf-8') as f:
        gt_data = json.load(f)

    all_cases = gt_data.get('cases', [])
    missing_split = [case.get('case_id', 'unknown') for case in all_cases if 'split' not in case]
    if missing_split:
        preview = ', '.join(missing_split[:10])
        raise ValueError(
            f"Ground truth contains {len(missing_split)} case(s) without 'split'. "
            f"Examples: {preview}"
        )

    metadata = gt_data.get('metadata', {})
    test_cases = [case for case in all_cases if case.get('split') == 'test']
    metadata_test_count = metadata.get('test_cases')
    if metadata_test_count is not None and int(metadata_test_count) != len(test_cases):
        logger.warning(
            "Ground truth metadata test_cases=%s does not match actual test split count=%s",
            metadata_test_count,
            len(test_cases),
        )

    return test_cases

# ============================================================================
# RELEVANCE JUDGMENT
# ============================================================================

def load_problem_taxonomy(path: str = "problem_codes.json") -> Dict:
    """Load problem code taxonomy with keywords"""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def build_relevance_keywords(
    expected_problems: List[Dict],
    taxonomy: Dict
) -> Dict[str, List[str]]:
    """
    Build keyword sets for relevance judgment from expected problems.

    For each expected problem code, collect:
    - The problem name
    - Keywords from taxonomy
    - Details from ground truth

    Returns:
        Dict mapping problem_code -> list of keywords for matching
    """
    relevance_map = {}

    for prob in expected_problems:
        code = prob.get('code', '')
        keywords = []

        # From ground truth problem entry
        name = prob.get('category', '')
        if name:
            # Extract meaningful parts from category string
            # e.g., "10 - ปัญหาการเงิน" -> "ปัญหาการเงิน"
            parts = name.split(' - ')
            for part in parts:
                clean = part.strip()
                if clean and not clean.isdigit():
                    keywords.append(clean)

        details = prob.get('details', '')
        if details:
            keywords.append(details)

        # From taxonomy
        if code in taxonomy:
            tax_entry = taxonomy[code]
            tax_name = tax_entry.get('name', '')
            if tax_name:
                keywords.append(tax_name)
            tax_keywords = tax_entry.get('keywords', [])
            keywords.extend(tax_keywords)
            tax_category = tax_entry.get('category', '')
            if tax_category:
                # e.g., "01: ปัญหาคู่สมรส" -> extract Thai part
                parts = tax_category.split(': ')
                for part in parts:
                    if not part.strip().isdigit():
                        keywords.append(part.strip())

        # Deduplicate and clean
        clean_keywords = []
        seen = set()
        for kw in keywords:
            kw_clean = kw.strip().lower()
            if kw_clean and kw_clean not in seen and len(kw_clean) > 1:
                clean_keywords.append(kw_clean)
                seen.add(kw_clean)

        if clean_keywords:
            relevance_map[code] = clean_keywords

    return relevance_map


def judge_relevance(
    doc_text: str,
    relevance_keywords: Dict[str, List[str]],
    expected_problems: List[Dict]
) -> int:
    """
    Judge document relevance based on problem-code keyword matching.

    Grading:
        2 = highly relevant — doc matches keywords from ≥2 expected problems
            OR matches ≥3 keywords from highest-severity problem
        1 = partially relevant — doc matches keywords from 1 expected problem
        0 = not relevant — no meaningful match

    Args:
        doc_text: Full text of the retrieved document
        relevance_keywords: Dict[problem_code -> keywords] from build_relevance_keywords
        expected_problems: Original expected problem list (for severity info)

    Returns:
        Relevance grade: 0, 1, or 2
    """
    if not doc_text or not relevance_keywords:
        return 0

    doc_lower = doc_text.lower()

    # Sort problems by severity (high first)
    severity_map = {p.get('code', ''): p.get('severity', 1) for p in expected_problems}

    problems_matched = 0
    max_severity_matched = 0
    max_keywords_matched = 0

    for code, keywords in relevance_keywords.items():
        severity = severity_map.get(code, 1)
        matched_count = sum(1 for kw in keywords if kw in doc_lower)

        if matched_count >= 2:  # Need at least 2 keyword matches per problem
            problems_matched += 1
            max_severity_matched = max(max_severity_matched, severity)
            max_keywords_matched = max(max_keywords_matched, matched_count)
        elif matched_count == 1 and severity >= 3:
            # Single keyword match for high-severity is still notable
            problems_matched += 0.5
            max_severity_matched = max(max_severity_matched, severity)

    # Grading logic
    if problems_matched >= 2:
        return 2  # Matches multiple problems
    elif max_keywords_matched >= 3 and max_severity_matched >= 3:
        return 2  # Strong match on high-severity problem
    elif problems_matched >= 1:
        return 1  # Matches at least one problem
    elif max_keywords_matched >= 1:
        return 1  # Weak match but still some relevance
    else:
        return 0  # No match


# ============================================================================
# RANK-AWARE METRICS
# ============================================================================

def precision_at_k(relevance_grades: List[int], k: int) -> float:
    """Precision@K: fraction of top-K docs that are relevant (grade > 0)"""
    top_k = relevance_grades[:k]
    if not top_k:
        return 0.0
    return sum(1 for g in top_k if g > 0) / len(top_k)


def recall_at_k(relevance_grades: List[int], k: int, total_relevant: int) -> float:
    """Recall@K: fraction of all relevant docs found in top-K"""
    if total_relevant == 0:
        return 0.0
    top_k = relevance_grades[:k]
    return sum(1 for g in top_k if g > 0) / total_relevant


def ndcg_at_k(relevance_grades: List[int], k: int) -> float:
    """
    Normalized Discounted Cumulative Gain @K

    DCG@K  = Σᵢ₌₁ᵏ (2^relᵢ - 1) / log₂(i + 1)
    IDCG@K = DCG for perfect ranking
    nDCG@K = DCG@K / IDCG@K
    """
    def dcg(grades, cutoff):
        result = 0.0
        for i, g in enumerate(grades[:cutoff]):
            result += (2**g - 1) / math.log2(i + 2)  # i+2 because 0-indexed
        return result

    actual_dcg = dcg(relevance_grades, k)

    # Ideal: sort grades descending
    ideal_grades = sorted(relevance_grades, reverse=True)
    ideal_dcg = dcg(ideal_grades, k)

    if ideal_dcg == 0:
        return 0.0
    return actual_dcg / ideal_dcg


def average_precision(relevance_grades: List[int]) -> float:
    """
    Average Precision (AP)

    AP = (Σᵢ P(i) × rel(i)) / |relevant|
    """
    total_relevant = sum(1 for g in relevance_grades if g > 0)
    if total_relevant == 0:
        return 0.0

    ap = 0.0
    relevant_so_far = 0

    for i, g in enumerate(relevance_grades):
        if g > 0:
            relevant_so_far += 1
            ap += relevant_so_far / (i + 1)

    return ap / total_relevant


def reciprocal_rank(relevance_grades: List[int]) -> float:
    """
    Reciprocal Rank (RR)

    RR = 1 / rank(first_relevant_doc)
    """
    for i, g in enumerate(relevance_grades):
        if g > 0:
            return 1.0 / (i + 1)
    return 0.0


def f1_at_k(relevance_grades: List[int], k: int, total_relevant: int) -> float:
    """F1@K: harmonic mean of P@K and R@K"""
    p = precision_at_k(relevance_grades, k)
    r = recall_at_k(relevance_grades, k, total_relevant)
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def compute_all_metrics(
    relevance_grades: List[int],
    k_values: List[int] = None
) -> Dict:
    """Compute all rank-aware metrics for a single query"""
    if k_values is None:
        k_values = [3, 5, 10]

    total_relevant = sum(1 for g in relevance_grades if g > 0)

    metrics = {
        'total_docs': len(relevance_grades),
        'total_relevant': total_relevant,
        'MAP': average_precision(relevance_grades),
        'MRR': reciprocal_rank(relevance_grades),
    }

    for k in k_values:
        metrics[f'P@{k}'] = precision_at_k(relevance_grades, k)
        metrics[f'R@{k}'] = recall_at_k(relevance_grades, k, total_relevant)
        metrics[f'F1@{k}'] = f1_at_k(relevance_grades, k, total_relevant)
        metrics[f'nDCG@{k}'] = ndcg_at_k(relevance_grades, k)

    return metrics


# ============================================================================
# STRATEGY RUNNER
# ============================================================================

# Strategy configurations mapping strategy name -> (class, needs_problems, kwargs)
STRATEGY_CONFIGS = {
    # =========================================================================
    # 2×N PAIRED FACTORIAL DESIGN — 4 Baselines × 2 (Standalone vs H2L)
    # =========================================================================

    # ── GROUP A: Baselines (Standalone, no H2L scoring) ──
    'bm25_only': {
        'use_unified_baseline': True,
        'baseline_key': 'bm25_only',
        'needs_problems': False,
        'group': 'baseline',
        'pair_id': 1,
        'description': 'BM25 Only (Lexical Matching)'
    },
    'naive_rag': {
        'use_unified_baseline': True,
        'baseline_key': 'naive_rag',
        'needs_problems': False,
        'group': 'baseline',
        'pair_id': 2,
        'description': 'Dense Retrieval Only (Naive RAG)'
    },
    'hyde': {
        'use_unified_baseline': True,
        'baseline_key': 'hyde',
        'needs_problems': False,
        'group': 'baseline',
        'pair_id': 3,
        'description': 'HyDE (Gao et al., 2022)'
    },
    'basic': {
        'module': 'h2l.retriever',
        'class': 'HybridRetriever',
        'needs_problems': False,
        'group': 'baseline',
        'pair_id': 4,
        'description': 'Hybrid (BM25+Dense+RRF+Reranker)'
    },

    # ── GROUP B: H2L-Enhanced (Baseline + H2L Scoring Augmentation) ──
    'h2l-bm25': {
        'use_h2l_unified': True,
        'base_strategy': 'bm25_only',
        'enable_adaptive': False,
        'enable_multihop': False,
        'needs_problems': True,
        'group': 'h2l',
        'pair_id': 1,
        'description': 'H2L + BM25'
    },
    'h2l-naive_rag': {
        'use_h2l_unified': True,
        'base_strategy': 'naive_rag',
        'enable_adaptive': False,
        'enable_multihop': False,
        'needs_problems': True,
        'group': 'h2l',
        'pair_id': 2,
        'description': 'H2L + Dense (Naive RAG)'
    },
    'h2l-hyde': {
        'use_h2l_unified': True,
        'base_strategy': 'hyde',
        'enable_adaptive': False,
        'enable_multihop': False,
        'needs_problems': True,
        'group': 'h2l',
        'pair_id': 3,
        'description': 'H2L + HyDE'
    },
    'h2l-hybrid': {
        'use_h2l_unified': True,
        'base_strategy': 'hybrid',
        'enable_adaptive': False,
        'enable_multihop': False,
        'needs_problems': True,
        'group': 'h2l',
        'pair_id': 4,
        'description': 'H2L + Hybrid (RRF+Reranker)'
    },
}


class EvaluationRunner:
    """
    Runs evaluation across strategies using ground truth cases.
    """

    def __init__(self, config=None, taxonomy_path="data/problem_codes.json"):
        self.taxonomy = load_problem_taxonomy(taxonomy_path)
        self._config = config
        self._shared = None
        self._retrievers = {}
        self._detector = None

    def _ensure_config(self):
        """Lazy-load config"""
        if self._config is None:
            from h2l.config import get_config
            self._config = get_config()
        return self._config

    def _ensure_shared_components(self):
        """Lazy-load shared components (embedding models, indexes)"""
        if self._shared is not None:
            return self._shared

        config = self._ensure_config()
        from h2l.retriever import HybridRetriever, DenseIndex, ThaiBM25, Reranker

        logger.info("📦 Loading shared components...")
        all_docs = HybridRetriever._load_all_docs(config)
        doc_map = {doc.id: doc for doc in all_docs}

        dense = DenseIndex(config.DB_TYPE, str(config.DB_PATH),
                          config.EMBEDDING_MODEL, config.DEVICE)
        bm25 = ThaiBM25(all_docs)
        reranker = Reranker(config.RERANK_MODEL, config.DEVICE) if config.USE_RERANK else None

        self._shared = {
            "all_docs": all_docs,
            "doc_map": doc_map,
            "dense_retriever": dense,
            "lexical_retriever": bm25,
            "reranker": reranker
        }
        logger.info(f"✅ Shared components ready. {len(all_docs)} docs loaded.")
        return self._shared

    def _ensure_detector(self):
        """Lazy-load H2L detector"""
        if self._detector is not None:
            return self._detector

        try:
            from h2l.detector import H2LDetectorV3
            config = self._ensure_config()
            self._detector = H2LDetectorV3(config=config)
            logger.info("✅ H2L Detector ready.")
        except Exception as e:
            logger.warning(f"⚠️ H2L Detector not available: {e}")
            self._detector = None

        return self._detector

    def _get_retriever(self, strategy_name: str):
        """Get or create retriever for a strategy"""
        if strategy_name in self._retrievers:
            return self._retrievers[strategy_name]

        config = self._ensure_config()
        shared = self._ensure_shared_components()
        strategy_cfg = STRATEGY_CONFIGS[strategy_name]

        if strategy_cfg.get('use_h2l_unified'):
            from h2l.core import H2LUnifiedRetriever
            retriever = H2LUnifiedRetriever(
                config=config,
                shared_components=shared,
                base_strategy=strategy_cfg['base_strategy'],
                enable_adaptive=strategy_cfg.get('enable_adaptive', False),
                enable_multihop=strategy_cfg.get('enable_multihop', False),
            )
        elif strategy_cfg.get('use_unified_baseline'):
            # Baseline from eval/baselines.py (BM25, Dense, HyDE)
            from baselines import BASELINE_REGISTRY
            baseline_key = strategy_cfg['baseline_key']
            baseline_info = BASELINE_REGISTRY[baseline_key]
            baseline_cls = baseline_info['class']
            retriever = baseline_cls(config, shared_components=shared)
        elif strategy_cfg.get('apply_h2l_filter'):
            # Baseline + H2L post-filter: wrap baseline retriever with H2L scoring
            import importlib
            mod = importlib.import_module(strategy_cfg['module'])
            cls = getattr(mod, strategy_cfg['class'])
            base_retriever = cls(config, shared_components=shared)
            retriever = H2LFilterWrapper(base_retriever, config, shared)
        else:
            import importlib
            mod = importlib.import_module(strategy_cfg['module'])
            cls = getattr(mod, strategy_cfg['class'])
            retriever = cls(config, shared_components=shared)

        self._retrievers[strategy_name] = retriever
        return retriever


    def detect_problems(self, case_text: str) -> List[Dict]:
        """Detect problems using H2L detector"""
        detector = self._ensure_detector()
        if detector is None:
            return []

        try:
            # H2LDetectorV3 exposes detect_problems() which returns List[Dict]
            if hasattr(detector, 'detect_problems'):
                problems = detector.detect_problems(case_text)
                return problems if isinstance(problems, list) else []
            else:
                # Fallback for older L1ContextAwareDetector
                detected, _meta = detector.detect(case_text)
                problems = []
                for d in detected:
                    if hasattr(d, '__dict__'):
                        prob = {
                            'code': getattr(d, 'code', ''),
                            'name': getattr(d, 'name', ''),
                            'severity': getattr(d, 'severity', 1),
                            'confidence': getattr(d, 'confidence', 0.5),
                            'keywords': getattr(d, 'matched_keywords', []),
                            'category': getattr(d, 'category', ''),
                        }
                    elif isinstance(d, dict):
                        prob = d
                    else:
                        continue
                    problems.append(prob)
                return problems
        except Exception as e:
            logger.warning(f"Detection failed: {e}")
            return []

    def expected_as_h2l_problems(self, expected_problems: List[Dict]) -> List[Dict]:
        """Convert ground-truth problems into the shape expected by H2L scoring."""
        problems = []
        for problem in expected_problems:
            code = problem.get('code', '')
            tax_entry = self.taxonomy.get(code, {}) if isinstance(self.taxonomy, dict) else {}
            keywords = []
            keywords.extend(tax_entry.get('keywords', []) if isinstance(tax_entry.get('keywords'), list) else [])
            if problem.get('details'):
                keywords.append(problem.get('details'))
            if problem.get('category'):
                keywords.append(problem.get('category'))
            problems.append({
                'code': code,
                'name': tax_entry.get('name') or problem.get('category') or code,
                'category': problem.get('category') or tax_entry.get('category', ''),
                'severity': problem.get('severity', 1),
                'confidence': 1.0,
                'keywords': list(dict.fromkeys([kw for kw in keywords if kw])),
                'details': problem.get('details', ''),
                'source': 'gold_problem',
            })
        return problems

    def evaluate_single_query(
        self,
        strategy_name: str,
        query_text: str,
        expected_problems: List[Dict],
        top_k: int = 15,
        problem_source: str = "detected",
    ) -> Dict:
        """
        Evaluate a single query on a single strategy.

        Returns:
            Dict with metrics and timing
        """
        retriever = self._get_retriever(strategy_name)
        strategy_cfg = STRATEGY_CONFIGS[strategy_name]

        # Build relevance keywords from expected problems
        relevance_keywords = build_relevance_keywords(expected_problems, self.taxonomy)

        # Detect problems if strategy needs them
        detected_problems = []
        if strategy_cfg['needs_problems']:
            if problem_source == "gold":
                detected_problems = self.expected_as_h2l_problems(expected_problems)
            else:
                detected_problems = self.detect_problems(query_text)

        # Retrieve
        start_time = time.time()
        try:
            if strategy_cfg['needs_problems'] and hasattr(retriever, 'retrieve'):
                # H2L retrievers accept explicit_problems
                results = retriever.retrieve(
                    query=query_text,
                    explicit_problems=detected_problems,
                    top_k_override=top_k
                )
            else:
                results = retriever.retrieve(query_text, top_k_override=top_k)
        except TypeError:
            # Some retrievers don't support top_k_override
            try:
                results = retriever.retrieve(query_text)
            except Exception as e:
                logger.error(f"Retrieval failed for {strategy_name}: {e}")
                return {'error': str(e)}

        elapsed = time.time() - start_time

        # Judge relevance for each retrieved doc
        relevance_grades = []
        doc_details = []

        for r in results:
            doc = r.doc if hasattr(r, 'doc') else r
            doc_text = getattr(doc, 'text', '')
            score = getattr(r, 'final_score', getattr(r, 'score', 0.0))

            grade = judge_relevance(doc_text, relevance_keywords, expected_problems)
            relevance_grades.append(grade)

            doc_details.append({
                'doc_id': getattr(doc, 'id', -1),
                'score': float(score),
                'relevance_grade': grade,
                'text_preview': doc_text[:100] + '...' if len(doc_text) > 100 else doc_text,
            })

        # Compute metrics
        metrics = compute_all_metrics(relevance_grades, k_values=[3, 5, 10])
        metrics['retrieval_time'] = elapsed
        metrics['num_detected_problems'] = len(detected_problems)
        metrics['detected_codes'] = [p.get('code', '') for p in detected_problems]
        metrics['problem_source'] = problem_source if strategy_cfg['needs_problems'] else 'not_used'

        return {
            'metrics': metrics,
            'doc_details': doc_details,
            'relevance_grades': relevance_grades,
        }

    def evaluate_all(
        self,
        ground_truth_path: str = "expanded_ground_truth.json",
        strategies: List[str] = None,
        max_cases: int = None,
        top_k: int = 15,
        problem_source: str = "detected",
        checkpoint_dir: Optional[str] = None,
        progress_dir: Optional[str] = None,
    ) -> Dict:
        """
        Run full evaluation across all strategies and ground truth cases.
        Uses Test set by default to prevent parameter/rule overfitting.

        Returns:
            Dict with per-strategy, per-query results and aggregates
        """
        # Load test split from unified ground truth
        cases = load_test_cases_from_ground_truth(ground_truth_path)
        if max_cases:
            cases = cases[:max_cases]

        if strategies is None:
            strategies = list(STRATEGY_CONFIGS.keys())

        logger.info(f"📊 Evaluating {len(strategies)} strategies on {len(cases)} Unseen TEST cases")
        logger.info(f"   Strategies: {strategies}")

        all_results = {}
        aggregate_metrics = {}
        total_cases = len(cases)
        total_strategies = len(strategies)
        evaluation_started_at = time.time()

        if progress_dir:
            _write_progress(progress_dir, {
                "status": "running",
                "phase": "evaluating",
                "problem_source": problem_source,
                "top_k": top_k,
                "ground_truth_path": ground_truth_path,
                "strategies": strategies,
                "completed_strategy_count": 0,
                "total_strategy_count": total_strategies,
                "completed_case_count": 0,
                "total_case_count": total_cases * total_strategies,
                "current_strategy": None,
                "current_strategy_index": 0,
                "current_case_id": None,
                "current_case_index": 0,
                "elapsed_seconds": 0.0,
                "latest_checkpoint": str(Path(checkpoint_dir) / CHECKPOINT_ARTIFACT_BASENAMES['summary']) if checkpoint_dir else None,
            })

        for strategy_index, strategy in enumerate(strategies, start=1):
            logger.info(f"\n{'='*60}")
            logger.info(f"🔄 Strategy: {strategy} ({STRATEGY_CONFIGS[strategy]['description']})")
            logger.info(f"{'='*60}")

            strategy_results = []
            metric_lists = defaultdict(list)

            for i, case in enumerate(cases):
                case_id = case.get('case_id', f'case_{i}')
                query = case.get('case_description', '')
                expected = case.get('expected_diagnosis', {}).get('problem_list', [])

                if not query:
                    continue

                logger.info(f"  [{i+1}/{len(cases)}] {case_id} ({case.get('complexity', '?')})")

                if progress_dir:
                    completed_case_count = ((strategy_index - 1) * total_cases) + i
                    _write_progress(progress_dir, {
                        "status": "running",
                        "phase": "evaluating",
                        "problem_source": problem_source,
                        "top_k": top_k,
                        "ground_truth_path": ground_truth_path,
                        "strategies": strategies,
                        "completed_strategy_count": strategy_index - 1,
                        "total_strategy_count": total_strategies,
                        "completed_case_count": completed_case_count,
                        "total_case_count": total_cases * total_strategies,
                        "current_strategy": strategy,
                        "current_strategy_index": strategy_index,
                        "current_case_id": case_id,
                        "current_case_index": i + 1,
                        "strategy_case_count": total_cases,
                        "elapsed_seconds": round(time.time() - evaluation_started_at, 2),
                        "latest_checkpoint": str(Path(checkpoint_dir) / CHECKPOINT_ARTIFACT_BASENAMES['summary']) if checkpoint_dir else None,
                    })

                result = self.evaluate_single_query(
                    strategy_name=strategy,
                    query_text=query,
                    expected_problems=expected,
                    top_k=top_k,
                    problem_source=problem_source,
                )

                if 'error' in result:
                    logger.warning(f"    ❌ Error: {result['error']}")
                    continue

                result['case_id'] = case_id
                result['complexity'] = case.get('complexity', 'unknown')
                result['category'] = case.get('category', 'unknown')
                result['expected_codes'] = [p.get('code', '') for p in expected]
                strategy_results.append(result)

                # Collect metrics for aggregation
                for metric_name, value in result['metrics'].items():
                    if isinstance(value, (int, float)):
                        metric_lists[metric_name].append(value)

                # Log key metrics
                m = result['metrics']
                logger.info(
                    f"    nDCG@5={m.get('nDCG@5', 0):.3f}  "
                    f"P@5={m.get('P@5', 0):.3f}  "
                    f"MAP={m.get('MAP', 0):.3f}  "
                    f"MRR={m.get('MRR', 0):.3f}  "
                    f"t={m.get('retrieval_time', 0):.2f}s"
                )

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
                        'values': values,  # Keep raw values for statistical tests
                    }

            all_results[strategy] = strategy_results
            aggregate_metrics[strategy] = agg

            if checkpoint_dir:
                checkpoint_results = build_results_payload(
                    cases=cases,
                    strategies=strategies,
                    top_k=top_k,
                    problem_source=problem_source,
                    per_strategy=all_results,
                    aggregates=aggregate_metrics,
                    status='partial',
                )
                save_checkpoint(checkpoint_results, checkpoint_dir)

            if progress_dir:
                _write_progress(progress_dir, {
                    "status": "running",
                    "phase": "strategy_complete",
                    "problem_source": problem_source,
                    "top_k": top_k,
                    "ground_truth_path": ground_truth_path,
                    "strategies": strategies,
                    "completed_strategy_count": strategy_index,
                    "total_strategy_count": total_strategies,
                    "completed_case_count": strategy_index * total_cases,
                    "total_case_count": total_cases * total_strategies,
                    "current_strategy": strategy,
                    "current_strategy_index": strategy_index,
                    "current_case_id": None,
                    "current_case_index": total_cases,
                    "strategy_case_count": total_cases,
                    "strategy_summary": {
                        "strategy": strategy,
                        "nDCG@5": agg.get("nDCG@5", {}).get("mean"),
                        "MAP": agg.get("MAP", {}).get("mean"),
                        "MRR": agg.get("MRR", {}).get("mean"),
                        "retrieval_time": agg.get("retrieval_time", {}).get("mean"),
                    },
                    "elapsed_seconds": round(time.time() - evaluation_started_at, 2),
                    "latest_checkpoint": str(Path(checkpoint_dir) / CHECKPOINT_ARTIFACT_BASENAMES['summary']) if checkpoint_dir else None,
                })

            # Print strategy summary
            logger.info(f"\n  📈 {strategy} Summary:")
            for metric in ['nDCG@5', 'P@5', 'MAP', 'MRR', 'F1@5', 'retrieval_time']:
                if metric in agg:
                    logger.info(
                        f"    {metric:>12}: {agg[metric]['mean']:.4f} "
                        f"± {agg[metric]['std']:.4f}"
                    )

        results = build_results_payload(
            cases=cases,
            strategies=strategies,
            top_k=top_k,
            problem_source=problem_source,
            per_strategy=all_results,
            aggregates=aggregate_metrics,
            status='complete',
        )
        if progress_dir:
            _write_progress(progress_dir, {
                "status": "running",
                "phase": "building_results",
                "problem_source": problem_source,
                "top_k": top_k,
                "ground_truth_path": ground_truth_path,
                "strategies": strategies,
                "completed_strategy_count": total_strategies,
                "total_strategy_count": total_strategies,
                "completed_case_count": total_cases * total_strategies,
                "total_case_count": total_cases * total_strategies,
                "current_strategy": None,
                "current_strategy_index": total_strategies,
                "current_case_id": None,
                "current_case_index": total_cases,
                "strategy_case_count": total_cases,
                "elapsed_seconds": round(time.time() - evaluation_started_at, 2),
                "latest_checkpoint": str(Path(checkpoint_dir) / CHECKPOINT_ARTIFACT_BASENAMES['summary']) if checkpoint_dir else None,
            })
        return results


# ============================================================================
# H2L FILTER WRAPPER (for baseline + h2l post-filter strategies)
# ============================================================================

class H2LFilterWrapper:
    """
    Wraps any baseline retriever with H2L problem-aware scoring as a post-filter.

    This enables a 2×N factorial design: any baseline can be evaluated
    both with and without H2L scoring, isolating the H2L contribution.
    """

    def __init__(self, base_retriever, config, shared_components):
        self.base_retriever = base_retriever
        self.config = config
        self.shared = shared_components

    def retrieve(self, query: str, explicit_problems=None, top_k_override=None):
        """Retrieve using base retriever, then apply H2L scoring"""
        # Step 1: Base retrieval
        try:
            results = self.base_retriever.retrieve(query, top_k_override=top_k_override)
        except TypeError:
            results = self.base_retriever.retrieve(query)

        if not results or not explicit_problems:
            return results

        # Step 2: Apply H2L scoring as post-filter
        from h2l.core import (
            calculate_problem_prior, calculate_final_score_probabilistic,
            H2LConfigV3, DEFAULT_CONFIG_V3
        )

        h2l_config = DEFAULT_CONFIG_V3
        priors = calculate_problem_prior(explicit_problems, h2l_config)

        # Compute semantic embeddings for problem-aware scoring
        try:
            from sentence_transformers import SentenceTransformer
            embedder = SentenceTransformer(self.config.DENSE_MODEL)

            problem_texts = [
                f"{p.get('name', '')} {' '.join(p.get('keywords', []))}"
                for p in explicit_problems
            ]
            problem_embeddings = {
                p.get('code', f'p_{i}'): emb
                for i, (p, emb) in enumerate(zip(
                    explicit_problems,
                    embedder.encode(problem_texts)
                ))
            }

            doc_texts = [getattr(r.doc, 'text', '') if hasattr(r, 'doc') else '' for r in results]
            doc_embs_list = embedder.encode(doc_texts) if doc_texts else []
            doc_embeddings = {}
            for r, emb in zip(results, doc_embs_list):
                doc_id = r.doc.id if hasattr(r, 'doc') and hasattr(r.doc, 'id') else id(r)
                doc_embeddings[doc_id] = emb

            use_semantic = True
        except Exception:
            problem_embeddings = None
            doc_embeddings = {}
            use_semantic = False

        for result in results:
            doc = result.doc if hasattr(result, 'doc') else result
            doc_text = getattr(doc, 'text', '')
            doc_id = getattr(doc, 'id', id(result))
            doc_emb = doc_embeddings.get(doc_id) if use_semantic else None

            final_score, breakdown = calculate_final_score_probabilistic(
                rerank_score=result.rerank_score,
                problems=explicit_problems,
                doc_text=doc_text,
                doc_embedding=doc_emb,
                problem_embeddings=problem_embeddings if use_semantic else None,
                config=h2l_config,
                alpha_override=1.0,
            )
            result.rerank_score = final_score

        results.sort(key=lambda x: x.final_score, reverse=True)
        return results


# ============================================================================
# ADVANCED STATISTICAL ANALYSIS
# ============================================================================

def bootstrap_bca_ci(values, n_bootstrap=1000, alpha=0.05, statistic=None):
    """
    Bias-Corrected and Accelerated (BCa) Bootstrap Confidence Interval.

    Superior to normal-approximation CIs for small samples.
    Reference: Efron & Tibshirani (1993)

    Args:
        values: 1D array of observations
        n_bootstrap: number of bootstrap resamples
        alpha: significance level (default 0.05 for 95% CI)
        statistic: function to compute (default: np.mean)
    Returns:
        dict with 'mean', 'ci_lower', 'ci_upper', 'se_bootstrap'
    """
    values = np.array(values)
    n = len(values)
    if n < 3:
        m = float(np.mean(values))
        return {'mean': m, 'ci_lower': m, 'ci_upper': m, 'se_bootstrap': 0.0}

    if statistic is None:
        statistic = np.mean

    theta_hat = float(statistic(values))

    # Bootstrap resamples
    rng = np.random.RandomState(42)
    boot_stats = np.array([
        statistic(values[rng.randint(0, n, n)])
        for _ in range(n_bootstrap)
    ])

    # Bias correction factor z0
    z0 = float(np.percentile(boot_stats, 50) - theta_hat)
    from scipy.stats import norm
    z0 = float(norm.ppf(np.mean(boot_stats < theta_hat)))

    # Acceleration factor a (jackknife)
    jackknife_stats = np.array([
        statistic(np.delete(values, i))
        for i in range(n)
    ])
    jack_mean = np.mean(jackknife_stats)
    num = np.sum((jack_mean - jackknife_stats) ** 3)
    den = 6.0 * (np.sum((jack_mean - jackknife_stats) ** 2) ** 1.5)
    a = float(num / den) if den != 0 else 0.0

    # BCa adjusted percentiles
    z_alpha = float(norm.ppf(alpha / 2))
    z_1alpha = float(norm.ppf(1 - alpha / 2))

    def bca_percentile(z_val):
        num = z0 + z_val
        adj = z0 + num / (1 - a * num)
        return max(0, min(100, float(norm.cdf(adj) * 100)))

    ci_lower = float(np.percentile(boot_stats, bca_percentile(z_alpha)))
    ci_upper = float(np.percentile(boot_stats, bca_percentile(z_1alpha)))
    se_bootstrap = float(np.std(boot_stats))

    return {
        'mean': theta_hat,
        'ci_lower': ci_lower,
        'ci_upper': ci_upper,
        'se_bootstrap': se_bootstrap,
    }


def bayesian_signed_rank(values_a, values_b, rope=0.01):
    """
    Bayesian Signed-Rank Test (Benavoli et al., 2017).

    Computes posterior probabilities that A > B, A ≈ B (within ROPE), or A < B.
    More informative than p-values alone.

    Args:
        values_a, values_b: paired observations
        rope: Region of Practical Equivalence (minimum meaningful difference)
    Returns:
        dict with 'p_a_wins', 'p_rope', 'p_b_wins'
    """
    diff = np.array(values_a) - np.array(values_b)
    n = len(diff)
    if n < 3:
        return {'p_a_wins': 0.5, 'p_rope': 0.0, 'p_b_wins': 0.5}

    # Bootstrap the mean difference to approximate the posterior
    rng = np.random.RandomState(42)
    n_boot = 5000
    boot_means = np.array([
        np.mean(diff[rng.randint(0, n, n)])
        for _ in range(n_boot)
    ])

    p_a_wins = float(np.mean(boot_means > rope))
    p_b_wins = float(np.mean(boot_means < -rope))
    p_rope = float(np.mean(np.abs(boot_means) <= rope))

    return {
        'p_a_wins': round(p_a_wins, 4),
        'p_rope': round(p_rope, 4),
        'p_b_wins': round(p_b_wins, 4),
    }


def kl_divergence_scores(scores_p, scores_q, n_bins=20):
    """
    KL-Divergence between two retrieval score distributions.

    Measures how much the H2L score distribution differs from baseline.
    Higher KL = more distinctive ranking behavior.

    Args:
        scores_p, scores_q: retrieval scores from two strategies
        n_bins: histogram bins
    Returns:
        dict with 'kl_pq', 'kl_qp', 'js_divergence'
    """
    scores_p = np.array(scores_p, dtype=float)
    scores_q = np.array(scores_q, dtype=float)

    if len(scores_p) == 0 or len(scores_q) == 0:
        return {'kl_pq': 0.0, 'kl_qp': 0.0, 'js_divergence': 0.0}

    # Create shared bins
    all_scores = np.concatenate([scores_p, scores_q])
    bins = np.linspace(np.min(all_scores) - 1e-6, np.max(all_scores) + 1e-6, n_bins + 1)

    # Histograms as probability distributions (add smoothing)
    eps = 1e-10
    p_hist = np.histogram(scores_p, bins=bins)[0].astype(float) + eps
    q_hist = np.histogram(scores_q, bins=bins)[0].astype(float) + eps
    p_hist /= p_hist.sum()
    q_hist /= q_hist.sum()

    kl_pq = float(np.sum(p_hist * np.log(p_hist / q_hist)))
    kl_qp = float(np.sum(q_hist * np.log(q_hist / p_hist)))

    # Jensen-Shannon divergence (symmetric)
    m = 0.5 * (p_hist + q_hist)
    js = 0.5 * np.sum(p_hist * np.log(p_hist / m)) + 0.5 * np.sum(q_hist * np.log(q_hist / m))

    return {
        'kl_pq': round(kl_pq, 6),
        'kl_qp': round(kl_qp, 6),
        'js_divergence': round(float(js), 6),
    }


def rank_correlation(ranking_a, ranking_b):
    """
    Kendall's τ rank correlation between two rankings.

    Measures how much one strategy reshuffles the document order.
    τ = 1 means identical rankings, τ = -1 means reversed.

    Args:
        ranking_a, ranking_b: lists of document IDs in ranked order
    Returns:
        dict with 'kendall_tau', 'p_value', 'concordant', 'discordant'
    """
    from scipy.stats import kendalltau

    # Build rank maps
    set_a = set(ranking_a)
    set_b = set(ranking_b)
    common = list(set_a & set_b)

    if len(common) < 3:
        return {'kendall_tau': 0.0, 'p_value': 1.0, 'concordant': 0, 'discordant': 0}

    rank_a = {doc: i for i, doc in enumerate(ranking_a) if doc in common}
    rank_b = {doc: i for i, doc in enumerate(ranking_b) if doc in common}

    ranks_1 = [rank_a[doc] for doc in common]
    ranks_2 = [rank_b[doc] for doc in common]

    tau, p_val = kendalltau(ranks_1, ranks_2)

    # Count concordant/discordant pairs
    n = len(common)
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            sign_a = ranks_1[i] - ranks_1[j]
            sign_b = ranks_2[i] - ranks_2[j]
            if sign_a * sign_b > 0:
                concordant += 1
            elif sign_a * sign_b < 0:
                discordant += 1

    return {
        'kendall_tau': round(float(tau), 4),
        'p_value': round(float(p_val), 6),
        'concordant': concordant,
        'discordant': discordant,
    }


# ============================================================================
# STATISTICAL COMPARISON
# ============================================================================

def run_statistical_tests(aggregates: Dict) -> Dict:
    """
    Run statistical significance tests between strategies.

    Tests:
    - Paired t-test (or Wilcoxon for non-normal)
    - Effect size (Cohen's d)
    - Confidence intervals
    """
    from scipy import stats

    results = {}
    strategies = list(aggregates.keys())
    key_metrics = ['nDCG@5', 'P@5', 'MAP', 'MRR']

    for metric in key_metrics:
        metric_results = {}

        # Get values for each strategy
        strategy_values = {}
        for s in strategies:
            if metric in aggregates[s]:
                strategy_values[s] = aggregates[s][metric]['values']

        if len(strategy_values) < 2:
            continue

        # Pairwise tests
        pairwise = {}
        strategy_list = list(strategy_values.keys())

        for i in range(len(strategy_list)):
            for j in range(i + 1, len(strategy_list)):
                s1, s2 = strategy_list[i], strategy_list[j]
                v1 = strategy_values[s1]
                v2 = strategy_values[s2]

                # Ensure same length (paired test)
                min_len = min(len(v1), len(v2))
                v1_paired = v1[:min_len]
                v2_paired = v2[:min_len]

                if min_len < 3:
                    continue

                # Normality check
                try:
                    _, p_norm1 = stats.shapiro(v1_paired)
                    _, p_norm2 = stats.shapiro(v2_paired)
                    is_normal = p_norm1 > 0.05 and p_norm2 > 0.05
                except:
                    is_normal = False

                if is_normal:
                    stat, p_value = stats.ttest_rel(v1_paired, v2_paired)
                    test_name = "paired_t_test"
                else:
                    stat, p_value = stats.wilcoxon(v1_paired, v2_paired)
                    test_name = "wilcoxon_signed_rank"

                # Cohen's d
                diff = np.array(v1_paired) - np.array(v2_paired)
                d = float(np.mean(diff) / (np.std(diff) + 1e-10))

                pairwise[f"{s1}_vs_{s2}"] = {
                    'test': test_name,
                    'statistic': float(stat),
                    'p_value': float(p_value),
                    'significant': p_value < 0.05,
                    'cohens_d': d,
                    'effect_interpretation': (
                        'large' if abs(d) >= 0.8 else
                        'medium' if abs(d) >= 0.5 else
                        'small' if abs(d) >= 0.2 else
                        'negligible'
                    ),
                    'mean_diff': float(np.mean(v1_paired) - np.mean(v2_paired)),
                }

        metric_results['pairwise'] = pairwise

        # Descriptive table
        desc_table = {}
        for s, vals in strategy_values.items():
            desc_table[s] = {
                'mean': float(np.mean(vals)),
                'std': float(np.std(vals)),
                'median': float(np.median(vals)),
                'ci_95': (
                    float(np.mean(vals) - 1.96 * np.std(vals) / np.sqrt(len(vals))),
                    float(np.mean(vals) + 1.96 * np.std(vals) / np.sqrt(len(vals)))
                ),
            }
        metric_results['descriptive'] = desc_table

        results[metric] = metric_results

    return results


def _paired_strategy_pairs(strategies: List[str]) -> List[Tuple[str, str, str]]:
    """Return baseline/H2L pairs that exist in this evaluation run."""
    by_pair = defaultdict(dict)
    for strategy in strategies:
        cfg = STRATEGY_CONFIGS.get(strategy, {})
        pair_id = cfg.get('pair_id')
        group = cfg.get('group')
        if pair_id is None or group not in {'baseline', 'h2l'}:
            continue
        by_pair[pair_id][group] = strategy

    pairs = []
    for pair_id, block in sorted(by_pair.items()):
        if block.get('baseline') and block.get('h2l'):
            pairs.append((f"pair_{pair_id}", block['baseline'], block['h2l']))
    return pairs


def _simple_paired_test(diff_values: List[float]) -> Dict:
    if len(diff_values) < 3:
        return {'test': 'not_enough_pairs', 'p_value': None, 'statistic': None}
    try:
        from scipy import stats
        stat, p_value = stats.wilcoxon(diff_values)
        return {
            'test': 'wilcoxon_signed_rank',
            'p_value': float(p_value),
            'statistic': float(stat),
            'significant': bool(p_value < 0.05),
        }
    except Exception:
        positives = sum(1 for value in diff_values if value > 0)
        negatives = sum(1 for value in diff_values if value < 0)
        return {
            'test': 'sign_count_fallback',
            'p_value': None,
            'statistic': positives - negatives,
            'significant': None,
        }


def build_experiment_diagnostics(results: Dict) -> Dict:
    """
    Build thesis-oriented paired diagnostics from real per-case results.

    This does not create new observations. It summarizes saved metric arrays and
    per-case metadata so the report can distinguish mean differences, paired
    uncertainty, and category-level behavior.
    """
    aggregates = results.get('aggregates', {})
    per_strategy = results.get('per_strategy', {})
    strategies = results.get('metadata', {}).get('strategies', list(aggregates.keys()))
    metrics = ['MAP', 'MRR', 'nDCG@5']
    pair_blocks = []

    for pair_id, base_name, h2l_name in _paired_strategy_pairs(strategies):
        base_cases = per_strategy.get(base_name, [])
        h2l_cases = per_strategy.get(h2l_name, [])
        case_count = min(len(base_cases), len(h2l_cases))
        metric_blocks = []
        category_buckets = defaultdict(lambda: defaultdict(list))
        complexity_buckets = defaultdict(lambda: defaultdict(list))

        for metric in metrics:
            base_values = aggregates.get(base_name, {}).get(metric, {}).get('values', [])
            h2l_values = aggregates.get(h2l_name, {}).get(metric, {}).get('values', [])
            paired = [
                (float(base_value), float(h2l_value))
                for base_value, h2l_value in zip(base_values, h2l_values)
                if isinstance(base_value, (int, float)) and isinstance(h2l_value, (int, float))
            ]
            diffs = [h2l_value - base_value for base_value, h2l_value in paired]
            ci = bootstrap_bca_ci(diffs, n_bootstrap=2000) if diffs else {
                'mean': None, 'ci_lower': None, 'ci_upper': None, 'se_bootstrap': None
            }
            bayes = bayesian_signed_rank(
                [h2l_value for _, h2l_value in paired],
                [base_value for base_value, _ in paired],
                rope=0.01,
            ) if diffs else {'p_a_wins': None, 'p_rope': None, 'p_b_wins': None}
            paired_test = _simple_paired_test(diffs)

            metric_blocks.append({
                'metric': metric,
                'n': len(diffs),
                'baseline_mean': float(np.mean([base for base, _ in paired])) if paired else None,
                'h2l_mean': float(np.mean([h2l for _, h2l in paired])) if paired else None,
                'delta_mean': float(np.mean(diffs)) if diffs else None,
                'h2l_case_wins': sum(1 for diff in diffs if diff > 1e-12),
                'baseline_case_wins': sum(1 for diff in diffs if diff < -1e-12),
                'ties': sum(1 for diff in diffs if abs(diff) <= 1e-12),
                'bootstrap_ci': ci,
                'bayesian_signed_rank': {
                    'p_h2l_wins': bayes.get('p_a_wins'),
                    'p_rope': bayes.get('p_rope'),
                    'p_baseline_wins': bayes.get('p_b_wins'),
                    'rope': 0.01,
                },
                'paired_test': paired_test,
            })

        for idx in range(case_count):
            base_case = base_cases[idx]
            h2l_case = h2l_cases[idx]
            category = h2l_case.get('category') or base_case.get('category') or 'unknown'
            complexity = h2l_case.get('complexity') or base_case.get('complexity') or 'unknown'
            for metric in metrics:
                base_value = base_case.get('metrics', {}).get(metric)
                h2l_value = h2l_case.get('metrics', {}).get(metric)
                if isinstance(base_value, (int, float)) and isinstance(h2l_value, (int, float)):
                    diff = float(h2l_value) - float(base_value)
                    category_buckets[category][metric].append(diff)
                    complexity_buckets[complexity][metric].append(diff)

        def summarize_buckets(buckets):
            rows = []
            for name, metric_map in sorted(buckets.items()):
                row = {'name': name}
                counts = []
                for metric in metrics:
                    diffs = metric_map.get(metric, [])
                    row[metric] = {
                        'n': len(diffs),
                        'delta_mean': float(np.mean(diffs)) if diffs else None,
                        'h2l_wins': sum(1 for diff in diffs if diff > 1e-12),
                        'baseline_wins': sum(1 for diff in diffs if diff < -1e-12),
                        'ties': sum(1 for diff in diffs if abs(diff) <= 1e-12),
                    }
                    counts.append(len(diffs))
                row['n_cases'] = max(counts) if counts else 0
                rows.append(row)
            return rows

        quality_metric_wins = sum(1 for block in metric_blocks if (block.get('delta_mean') or 0) > 1e-12)
        baseline_metric_wins = sum(1 for block in metric_blocks if (block.get('delta_mean') or 0) < -1e-12)
        pair_blocks.append({
            'pair_id': pair_id,
            'baseline': base_name,
            'h2l': h2l_name,
            'case_count': case_count,
            'quality_metric_wins': {
                'h2l': quality_metric_wins,
                'baseline': baseline_metric_wins,
                'tie': len(metric_blocks) - quality_metric_wins - baseline_metric_wins,
            },
            'metrics': metric_blocks,
            'by_category': summarize_buckets(category_buckets),
            'by_complexity': summarize_buckets(complexity_buckets),
        })

    return {
        'metadata': {
            'problem_source': results.get('metadata', {}).get('problem_source'),
            'num_cases': results.get('metadata', {}).get('num_cases'),
            'top_k': results.get('metadata', {}).get('top_k'),
        },
        'pairs': pair_blocks,
        'interpretation': (
            'ใช้ paired diagnostics เพื่อดู mean delta, CI, ROPE และผลแยก category; '
            'ถ้า CI คร่อม 0 หรือ p_rope สูง ควรสรุปว่าแนวโน้มยังไม่ชัด'
        ),
    }


# ============================================================================
# REPORTING
# ============================================================================

def print_comparison_table(aggregates: Dict, stats_results: Dict = None):
    """Print formatted comparison table"""
    strategies = list(aggregates.keys())
    metrics_to_show = ['nDCG@5', 'P@5', 'R@5', 'MAP', 'MRR', 'F1@5', 'retrieval_time']

    # Header
    print("\n" + "=" * 100)
    print("📊 Strategy Comparison Results")
    print("=" * 100)

    header = f"{'Strategy':<18}"
    for m in metrics_to_show:
        header += f" {m:>10}"
    print(header)
    print("-" * 100)

    # Values
    best_values = {}
    for m in metrics_to_show:
        values = []
        for s in strategies:
            if m in aggregates[s]:
                values.append(aggregates[s][m]['mean'])
        if values:
            if m == 'retrieval_time':
                best_values[m] = min(values)
            else:
                best_values[m] = max(values)

    for s in strategies:
        row = f"{s:<18}"
        for m in metrics_to_show:
            if m in aggregates[s]:
                val = aggregates[s][m]['mean']
                std = aggregates[s][m]['std']
                is_best = abs(val - best_values.get(m, -1)) < 0.0001
                marker = " *" if is_best else "  "
                row += f" {val:>7.4f}{marker}"
            else:
                row += f" {'N/A':>10}"
        print(row)

    print("-" * 100)
    print("  * = best in column")

    # Statistical significance summary
    if stats_results:
        print("\n📈 Statistical Significance (p < 0.05):")
        for metric, results in stats_results.items():
            significant_pairs = [
                (pair, data) for pair, data in results.get('pairwise', {}).items()
                if data['significant']
            ]
            if significant_pairs:
                print(f"\n  {metric}:")
                for pair, data in significant_pairs:
                    print(
                        f"    {pair}: p={data['p_value']:.4f}, "
                        f"d={data['cohens_d']:.3f} ({data['effect_interpretation']}), "
                        f"Δ={data['mean_diff']:+.4f}"
                    )


def build_results_payload(
    cases: List[Dict],
    strategies: List[str],
    top_k: int,
    problem_source: str,
    per_strategy: Dict,
    aggregates: Dict,
    status: str = 'complete',
) -> Dict:
    completed_strategies = list(aggregates.keys())
    pending_strategies = [strategy for strategy in strategies if strategy not in completed_strategies]
    return {
        'metadata': {
            'timestamp': datetime.now().isoformat(),
            'num_cases': len(cases),
            'strategies': strategies,
            'top_k': top_k,
            'problem_source': problem_source,
            'status': status,
            'completed_strategies': completed_strategies,
            'pending_strategies': pending_strategies,
            'completed_strategy_count': len(completed_strategies),
            'total_strategy_count': len(strategies),
        },
        'per_strategy': per_strategy,
        'aggregates': aggregates,
    }


def _serialize_results(results: Dict) -> Tuple[Dict, Dict, Dict]:
    """Prepare summary/raw/per-case payloads once so they can be written to multiple targets."""
    clean_results = {
        'metadata': results['metadata'],
        'aggregates': {},
    }
    if 'statistical_tests' in results:
        clean_results['statistical_tests'] = results['statistical_tests']
    if 'experiment_diagnostics' in results:
        clean_results['experiment_diagnostics'] = results['experiment_diagnostics']
    for strategy, agg in results['aggregates'].items():
        clean_agg = {}
        for metric, data in agg.items():
            clean_agg[metric] = {k: v for k, v in data.items() if k != 'values'}
        clean_results['aggregates'][strategy] = clean_agg

    # Save raw per-query metrics for statistical analysis
    raw_data = {}
    for strategy, agg in results['aggregates'].items():
        raw_data[strategy] = {}
        for metric, data in agg.items():
            if 'values' in data:
                raw_data[strategy][metric] = data['values']

    # Save per-case details for category-level error analysis.
    cases_data = {
        'metadata': results['metadata'],
        'per_strategy': results.get('per_strategy', {}),
    }

    return clean_results, raw_data, cases_data


def _write_json(path: Path, payload: Dict):
    path.parent.mkdir(exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)


def _write_progress(output_dir: str, payload: Dict) -> Path:
    progress_path = Path(output_dir) / PROGRESS_ARTIFACT_BASENAME
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "updated_at": datetime.now().isoformat(),
        **payload,
    }
    _write_json(progress_path, data)
    return progress_path


def _prune_timestamped_bundles(output_dir: str, keep_history: int = 2) -> Dict[str, int]:
    """
    Keep only the newest N timestamped proper-eval bundles.

    Stable aliases (`latest` / `checkpoint`) are never touched.
    """
    output_path = Path(output_dir)
    summaries = sorted(output_path.glob("proper_eval_summary_*.json"))
    if keep_history < 0:
        keep_history = 0
    removable = summaries[:-keep_history] if keep_history else summaries
    removed = 0
    missing_pairs = 0
    for summary_path in removable:
        stem = summary_path.name.replace("proper_eval_summary_", "").replace(".json", "")
        siblings = [
            summary_path,
            output_path / f"proper_eval_raw_{stem}.json",
            output_path / f"proper_eval_cases_{stem}.json",
        ]
        for path in siblings:
            try:
                if path.exists():
                    path.unlink()
                    removed += 1
                else:
                    missing_pairs += 1
            except Exception as exc:
                logger.warning("Failed to prune old artifact %s: %s", path, exc)
    return {
        "kept_history": keep_history,
        "removed_files": removed,
        "missing_pair_files": missing_pairs,
        "remaining_bundles": len(sorted(output_path.glob("proper_eval_summary_*.json"))),
    }


def save_checkpoint(results: Dict, output_dir: str = "evaluation_results") -> Tuple[Path, Path, Path]:
    """Overwrite a stable checkpoint bundle so long runs do not lose all progress if interrupted."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    clean_results, raw_data, cases_data = _serialize_results(results)

    summary_file = output_path / CHECKPOINT_ARTIFACT_BASENAMES['summary']
    raw_file = output_path / CHECKPOINT_ARTIFACT_BASENAMES['raw']
    cases_file = output_path / CHECKPOINT_ARTIFACT_BASENAMES['cases']

    _write_json(summary_file, clean_results)
    _write_json(raw_file, raw_data)
    _write_json(cases_file, cases_data)

    logger.info(
        "💾 Checkpoint updated: %s (%s/%s strategies)",
        summary_file.name,
        results.get('metadata', {}).get('completed_strategy_count', 0),
        results.get('metadata', {}).get('total_strategy_count', 0),
    )
    return summary_file, raw_file, cases_file


def save_results(
    results: Dict,
    output_dir: str = "evaluation_results",
    save_history: bool = True,
    history_limit: int = 2,
):
    """Save evaluation results, refresh stable aliases, and prune excess history."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    clean_results, raw_data, cases_data = _serialize_results(results)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    summary_file = raw_file = cases_file = None
    if save_history:
        summary_file = output_path / f"proper_eval_summary_{ts}.json"
        raw_file = output_path / f"proper_eval_raw_{ts}.json"
        cases_file = output_path / f"proper_eval_cases_{ts}.json"

        _write_json(summary_file, clean_results)
        _write_json(raw_file, raw_data)
        _write_json(cases_file, cases_data)

    latest_summary = output_path / LATEST_ARTIFACT_BASENAMES['summary']
    latest_raw = output_path / LATEST_ARTIFACT_BASENAMES['raw']
    latest_cases = output_path / LATEST_ARTIFACT_BASENAMES['cases']
    checkpoint_summary = output_path / CHECKPOINT_ARTIFACT_BASENAMES['summary']
    checkpoint_raw = output_path / CHECKPOINT_ARTIFACT_BASENAMES['raw']
    checkpoint_cases = output_path / CHECKPOINT_ARTIFACT_BASENAMES['cases']

    _write_json(latest_summary, clean_results)
    _write_json(latest_raw, raw_data)
    _write_json(latest_cases, cases_data)
    # Keep checkpoint bundle aligned with the final completed state after a successful run.
    _write_json(checkpoint_summary, clean_results)
    _write_json(checkpoint_raw, raw_data)
    _write_json(checkpoint_cases, cases_data)

    logger.info(f"✅ Results saved:")
    if save_history:
        logger.info(f"   Summary: {summary_file}")
        logger.info(f"   Raw data: {raw_file}")
        logger.info(f"   Per-case data: {cases_file}")
    logger.info(f"   Latest summary: {latest_summary}")
    logger.info(f"   Latest raw data: {latest_raw}")
    logger.info(f"   Latest per-case data: {latest_cases}")

    prune_report = _prune_timestamped_bundles(output_dir, history_limit) if save_history else {
        "kept_history": history_limit,
        "removed_files": 0,
        "missing_pair_files": 0,
        "remaining_bundles": len(sorted(output_path.glob("proper_eval_summary_*.json"))),
    }
    logger.info(
        "🧹 Artifact retention: kept newest %s bundle(s), remaining history=%s, removed files=%s",
        prune_report["kept_history"],
        prune_report["remaining_bundles"],
        prune_report["removed_files"],
    )

    return (
        summary_file or latest_summary,
        raw_file or latest_raw,
        cases_file or latest_cases,
    )


# ============================================================================
# SELF-TEST
# ============================================================================

def run_self_test():
    """Validate metrics and relevance judgment with known examples"""
    print("🧪 Running self-tests...\n")
    errors = 0

    # Test 1: nDCG@5 with known ranking
    grades = [2, 1, 0, 0, 1]  # Good ranking
    ndcg_val = ndcg_at_k(grades, 5)
    assert 0.8 < ndcg_val <= 1.0, f"nDCG@5 should be high for good ranking, got {ndcg_val}"
    print(f"  ✅ nDCG@5 (good ranking): {ndcg_val:.4f}")

    grades_bad = [0, 0, 1, 2, 1]  # Bad ranking (relevant docs at end)
    ndcg_bad = ndcg_at_k(grades_bad, 5)
    assert ndcg_bad < ndcg_val, f"Bad ranking should have lower nDCG"
    print(f"  ✅ nDCG@5 (bad ranking): {ndcg_bad:.4f} < {ndcg_val:.4f}")

    # Test 2: Precision@K
    grades = [1, 1, 0, 0, 0]
    p5 = precision_at_k(grades, 5)
    assert abs(p5 - 0.4) < 0.001, f"P@5 should be 0.4, got {p5}"
    print(f"  ✅ P@5: {p5:.4f}")

    # Test 3: MRR
    grades = [0, 0, 1, 0, 0]
    mrr_val = reciprocal_rank(grades)
    assert abs(mrr_val - 1/3) < 0.001, f"MRR should be 1/3, got {mrr_val}"
    print(f"  ✅ MRR: {mrr_val:.4f}")

    # Test 4: MAP
    grades = [1, 0, 1, 0, 0]
    map_val = average_precision(grades)
    expected_ap = (1/1 + 2/3) / 2  # P@1 for first rel + P@3 for second rel
    assert abs(map_val - expected_ap) < 0.001, f"MAP should be {expected_ap}, got {map_val}"
    print(f"  ✅ MAP: {map_val:.4f}")

    # Test 5: Relevance judgment
    taxonomy = {
        "1001": {"name": "ปัญหาการเงิน", "keywords": ["หนี้", "ค่าใช้จ่าย", "รายได้"], "severity": 2},
        "F32": {"name": "โรคซึมเศร้า", "keywords": ["ซึมเศร้า", "หมดหวัง", "เศร้า"], "severity": 4},
    }
    expected = [
        {"code": "1001", "category": "10 - ปัญหาการเงิน", "severity": 2},
        {"code": "F32", "category": "โรคซึมเศร้า", "severity": 4},
    ]
    rel_kw = build_relevance_keywords(expected, taxonomy)

    # Highly relevant doc
    doc_relevant = "ผู้ป่วยมีอาการซึมเศร้า หมดหวัง รายได้ไม่เพียงพอ มีหนี้สินจำนวนมาก ค่าใช้จ่ายสูง"
    grade = judge_relevance(doc_relevant, rel_kw, expected)
    assert grade == 2, f"Should be grade 2 (matches multiple problems), got {grade}"
    print(f"  ✅ Relevance (highly relevant): grade={grade}")

    # Partially relevant doc
    doc_partial = "แนวทางการช่วยเหลือผู้มีปัญหาการเงิน การจัดการหนี้สิน"
    grade = judge_relevance(doc_partial, rel_kw, expected)
    assert grade >= 1, f"Should be grade >= 1, got {grade}"
    print(f"  ✅ Relevance (partially relevant): grade={grade}")

    # Not relevant doc
    doc_irrelevant = "ระเบียบการจัดทำเอกสารราชการ ข้อบังคับกระทรวง"
    grade = judge_relevance(doc_irrelevant, rel_kw, expected)
    assert grade == 0, f"Should be grade 0, got {grade}"
    print(f"  ✅ Relevance (not relevant): grade={grade}")

    # Test 6: Different rankings produce different nDCG
    perfect = [2, 2, 1, 1, 0, 0, 0, 0, 0, 0]
    inverted = [0, 0, 0, 0, 0, 0, 1, 1, 2, 2]
    ndcg_perfect = ndcg_at_k(perfect, 5)
    ndcg_inverted = ndcg_at_k(inverted, 5)
    assert ndcg_perfect > ndcg_inverted, "Perfect ranking should have higher nDCG than inverted"
    print(f"  ✅ nDCG sensitivity: perfect={ndcg_perfect:.4f} > inverted={ndcg_inverted:.4f}")

    print(f"\n🎉 All {6} tests passed!")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='H2L Proper Evaluation')
    parser.add_argument('--self-test', action='store_true', help='Run self-tests')
    parser.add_argument('--strategies', nargs='+', default=None,
                       help='Strategies to evaluate (default: all)')
    parser.add_argument('--max-cases', type=int, default=None,
                       help='Max cases to evaluate (default: all)')
    parser.add_argument('--top-k', type=int, default=15,
                       help='Number of docs to retrieve per query')
    parser.add_argument('--top-k-list', nargs='+', type=int, default=None,
                       help='Run several doc-scaling experiments, e.g. --top-k-list 5 10 15 20')
    parser.add_argument('--ground-truth', default='expanded_ground_truth.json',
                       help='Path to ground truth file')
    parser.add_argument('--problem-source', choices=['detected', 'gold'], default='detected',
                       help='Problem source for H2L strategies: detected runtime problems or gold ground-truth problems')
    parser.add_argument('--output-dir', default='evaluation_results',
                       help='Directory to save results')
    parser.add_argument('--no-checkpoint', action='store_true',
                       help='Disable stable checkpoint files that are updated after each completed strategy')
    parser.add_argument('--no-history', action='store_true',
                       help='Do not create timestamped history artifacts; only refresh the stable latest bundle')
    parser.add_argument('--no-stats', action='store_true',
                       help='Skip statistical tests')
    parser.add_argument('--include-polarity', action='store_true',
                       help='Also run and append sentence polarity evaluation results')
    parser.add_argument('--history-limit', type=int, default=2,
                       help='Number of timestamped proper-eval bundles to keep after refreshing latest/checkpoint files')

    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        return

    runner = EvaluationRunner()

    top_k_values = args.top_k_list or [args.top_k]
    try:
        for top_k in top_k_values:
            results = runner.evaluate_all(
                ground_truth_path=args.ground_truth,
                strategies=args.strategies,
                max_cases=args.max_cases,
                top_k=top_k,
                problem_source=args.problem_source,
                checkpoint_dir=None if args.no_checkpoint else args.output_dir,
                progress_dir=args.output_dir,
            )

            _write_progress(args.output_dir, {
                "status": "running",
                "phase": "statistical_tests",
                "problem_source": args.problem_source,
                "top_k": top_k,
                "ground_truth_path": args.ground_truth,
                "strategies": args.strategies or list(STRATEGY_CONFIGS.keys()),
                "completed_strategy_count": len(args.strategies or list(STRATEGY_CONFIGS.keys())),
                "total_strategy_count": len(args.strategies or list(STRATEGY_CONFIGS.keys())),
                "completed_case_count": int((results.get("metadata", {}).get("num_cases") or 0)) * len(args.strategies or list(STRATEGY_CONFIGS.keys())),
            })
            stats_results = None
            if not args.no_stats and len(results['aggregates']) >= 2:
                try:
                    stats_results = run_statistical_tests(results['aggregates'])
                    results['statistical_tests'] = stats_results
                except ImportError:
                    logger.warning("scipy not available, skipping statistical tests")

            try:
                results['experiment_diagnostics'] = build_experiment_diagnostics(results)
            except Exception as e:
                logger.warning(f"Failed to build experiment diagnostics: {e}")

            print_comparison_table(results['aggregates'], stats_results)

            if args.include_polarity:
                print("\n" + "=" * 100)
                print("🔍 Running Sentence Polarity (G_neg) Evaluation")
                print("=" * 100)
                try:
                    from evaluate_sentence_polarity import evaluate_sentence_polarity, format_results_text
                    # Polarity evaluation uses the expanded ground truth tailored for polarity cases
                    pol_results = evaluate_sentence_polarity(
                        gt_path="expanded_ground_truth.json",
                        taxonomy_path="problem_codes.json"
                    )
                    print("\n" + format_results_text(pol_results))
                except Exception as e:
                    logger.error(f"Failed to run polarity evaluation: {e}")

            summary_path, raw_path, cases_path = save_results(
                results,
                args.output_dir,
                save_history=not args.no_history,
                history_limit=args.history_limit,
            )
            _write_progress(args.output_dir, {
                "status": "complete",
                "phase": "complete",
                "problem_source": args.problem_source,
                "top_k": top_k,
                "ground_truth_path": args.ground_truth,
                "strategies": args.strategies or list(STRATEGY_CONFIGS.keys()),
                "completed_strategy_count": len(args.strategies or list(STRATEGY_CONFIGS.keys())),
                "total_strategy_count": len(args.strategies or list(STRATEGY_CONFIGS.keys())),
                "completed_case_count": int((results.get("metadata", {}).get("num_cases") or 0)) * len(args.strategies or list(STRATEGY_CONFIGS.keys())),
                "latest_summary": str(summary_path),
                "latest_raw": str(raw_path),
                "latest_cases": str(cases_path),
                "history_limit": args.history_limit,
                "save_history": not args.no_history,
            })
    except Exception as exc:
        _write_progress(args.output_dir, {
            "status": "error",
            "phase": "failed",
            "problem_source": args.problem_source,
            "top_k": top_k_values[-1] if top_k_values else args.top_k,
            "ground_truth_path": args.ground_truth,
            "strategies": args.strategies or list(STRATEGY_CONFIGS.keys()),
            "error": str(exc),
        })
        raise


if __name__ == "__main__":
    main()
