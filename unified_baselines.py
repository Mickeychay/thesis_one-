#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified Baselines — V5 Consolidated
=====================================
All baseline retrievers for H2L V5 paired comparison:
1. BM25 Only — Lexical search only
2. Naive RAG — Dense retrieval only (no BM25, no reranking)
3. Query Expansion — Pseudo-relevance feedback (no problem detection)
4. HyDE — Hypothetical Document Embedding (Gao et al., 2022)

Consolidated from: baseline_retrievers.py + external_baselines.py
Old V3-V4 strategies (Dynamic, MultiHop, Adaptive) removed — no longer used.

Usage:
    python unified_baselines.py                          # Run all baselines
    python unified_baselines.py --baselines naive bm25   # Specific baselines
"""

import json
import time
import logging
import argparse
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ============================================================================
# BASELINE IMPLEMENTATIONS
# ============================================================================

class NaiveRAGBaseline:
    """
    Baseline 1: Pure dense retrieval (no BM25, no reranking)
    
    This represents the simplest RAG setup:
    - Embed query
    - Retrieve top-K by cosine similarity
    - No reranking, no fusion, no problem awareness
    """
    
    def __init__(self, config, shared_components):
        self.config = config
        self.dense = shared_components['dense_retriever']
        self.doc_map = shared_components.get('doc_map', {})
    
    def retrieve(self, query: str, top_k_override: int = 15, **kwargs):
        """Retrieve using only dense embeddings"""
        try:
            results = self.dense.search(query, top_k=top_k_override)
            # Wrap results to match expected interface
            wrapped = []
            for doc_id, score in results:
                doc = self.doc_map.get(doc_id)
                if doc:
                    wrapped.append(type('Result', (), {
                        'doc': doc,
                        'score': score,
                        'rerank_score': score,
                        'final_score': score
                    })())
            return wrapped
        except Exception as e:
            logger.error(f"Naive RAG retrieval failed: {e}")
            return []


class BM25OnlyBaseline:
    """
    Baseline 2: Pure BM25 lexical retrieval
    
    Shows the performance of keyword-based retrieval alone.
    """
    
    def __init__(self, config, shared_components):
        self.config = config
        self.bm25 = shared_components['lexical_retriever']
        self.all_docs = shared_components['all_docs']
    
    def retrieve(self, query: str, top_k_override: int = 15, **kwargs):
        """Retrieve using only BM25"""
        try:
            # ThaiBM25.search returns List[Tuple[int, float]]
            top_k_results = self.bm25.search(query, top_k=top_k_override)
            
            results = []
            for doc_id, score in top_k_results:
                if doc_id in getattr(self, 'doc_map', {}):
                    doc = self.doc_map[doc_id]
                else:
                    # Fallback if doc_map isn't explicitly set but all_docs is accessible by index
                    doc = next((d for d in self.all_docs if d.id == doc_id), None)
                    
                if doc:
                    results.append(type('Result', (), {
                        'doc': doc,
                        'score': float(score),
                        'rerank_score': float(score),
                        'final_score': float(score)
                    })())
            return results
        except Exception as e:
            logger.error(f"BM25 retrieval failed: {e}")
            return []


class QueryExpansionBaseline:
    """
    Baseline 3: Standard Query Expansion (no problem detection)
    
    Uses pseudo-relevance feedback:
    1. Initial retrieval
    2. Extract top terms from top-3 results
    3. Expand query
    4. Re-retrieve with expanded query
    """
    
    def __init__(self, config, shared_components):
        self.config = config
        self.shared = shared_components
        # Use the base hybrid retriever for retrieval
        try:
            from retrieval_engine import HybridRetriever
            self.retriever = HybridRetriever(config, shared_components=shared_components)
        except Exception as e:
            logger.error(f"Failed to init query expansion baseline: {e}")
            self.retriever = None
    
    def retrieve(self, query: str, top_k_override: int = 15, **kwargs):
        """Retrieve with pseudo-relevance feedback query expansion"""
        if not self.retriever:
            return []
        
        try:
            # Step 1: Initial retrieval
            initial_results = self.retriever.retrieve(query, top_k_override=5)
            
            if not initial_results:
                return self.retriever.retrieve(query, top_k_override=top_k_override)
            
            # Step 2: Extract expansion terms from top-3 docs
            expansion_terms = set()
            for result in initial_results[:3]:
                doc = result.doc if hasattr(result, 'doc') else result
                doc_text = getattr(doc, 'text', '')
                # Simple term extraction: find words that appear in doc but not query
                doc_words = set(doc_text.split())
                query_words = set(query.split())
                new_words = doc_words - query_words
                # Take a few longer words (more likely meaningful)
                meaningful = [w for w in new_words if len(w) > 3][:5]
                expansion_terms.update(meaningful)
            
            # Step 3: Expand query
            expanded_query = query + " " + " ".join(list(expansion_terms)[:5])
            
            # Step 4: Re-retrieve with expanded query
            return self.retriever.retrieve(expanded_query, top_k_override=top_k_override)
            
        except Exception as e:
            logger.error(f"Query expansion retrieval failed: {e}")
            return self.retriever.retrieve(query, top_k_override=top_k_override)


class HyDEBaseline:
    """
    Baseline 4: Hypothetical Document Embedding (HyDE)
    
    Based on Gao et al., 2022:
    1. LLM generates a hypothetical relevant document
    2. Embed the hypothetical document 
    3. Retrieve using the hypothetical document embedding
    """
    
    def __init__(self, config, shared_components):
        self.config = config
        self.dense = shared_components['dense_retriever']
        self.doc_map = shared_components.get('doc_map', {})
        self.llm_client = None
        self.last_generation_fallback = False
        
        # Try to init LLM client
        try:
            from openai import OpenAI
            use_local_llm = getattr(config, 'USE_LOCAL_LLM', True)
            base_url = (
                getattr(config, 'LOCAL_LLM_BASE_URL', 'http://localhost:11434/v1')
                if use_local_llm
                else 'https://openrouter.ai/api/v1'
            )
            api_key = (
                'ollama'
                if use_local_llm
                else getattr(config, 'OPENROUTER_API_KEY', '')
            )
            self.llm_client = OpenAI(
                base_url=base_url,
                api_key=api_key,
            )
            self.llm_model = (
                getattr(config, 'LOCAL_LLM_MODEL', 'qwen2.5:7b')
                if use_local_llm
                else getattr(config, 'OPENROUTER_MODEL', 'openai/gpt-4o-mini')
            )
        except Exception as e:
            logger.warning(f"HyDE: LLM not available, falling back to dense: {e}")
    
    def _generate_hypothetical_doc(self, query: str) -> str:
        """Generate a hypothetical relevant document using LLM"""
        if not self.llm_client:
            self.last_generation_fallback = True
            logger.warning("HyDE generation unavailable; using original query as fallback")
            return query
        
        try:
            self.last_generation_fallback = False
            response = self.llm_client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "คุณเป็นนักสังคมสงเคราะห์ผู้เชี่ยวชาญ เมื่อได้รับคำถามหรือกรณีศึกษา "
                            "ให้เขียนย่อหน้าสั้นๆ ที่อธิบายแนวทางการให้ความช่วยเหลือที่เกี่ยวข้อง "
                            "เขียนเป็นภาษาไทย ความยาวไม่เกิน 100 คำ"
                        )
                    },
                    {"role": "user", "content": query}
                ],
                max_tokens=200,
                temperature=0.3,
                seed=42,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.warning(f"HyDE generation failed: {e}")
            self.last_generation_fallback = True
            return query
    
    def retrieve(self, query: str, top_k_override: int = 15, **kwargs):
        """Retrieve using hypothetical document embedding"""
        try:
            # Step 1: Generate hypothetical document
            hypo_doc = self._generate_hypothetical_doc(query)
            
            # Step 2: Retrieve using hypothetical doc as query
            results = self.dense.search(hypo_doc, top_k=top_k_override)
            
            wrapped = []
            for doc_id, score in results:
                doc = self.doc_map.get(doc_id)
                if doc:
                    wrapped.append(type('Result', (), {
                        'doc': doc,
                        'score': score,
                        'rerank_score': score,
                        'final_score': score,
                        'hyde_generation_fallback': self.last_generation_fallback
                    })())
            return wrapped
        except Exception as e:
            logger.error(f"HyDE retrieval failed: {e}")
            return []


# ============================================================================
# BASELINE REGISTRY
# ============================================================================

BASELINE_REGISTRY = {
    'naive_rag': {
        'class': NaiveRAGBaseline,
        'description': 'Dense retrieval only (no BM25, no reranking)',
        'needs_llm': False,
    },
    'bm25_only': {
        'class': BM25OnlyBaseline,
        'description': 'BM25 lexical search only',
        'needs_llm': False,
    },
    'query_expansion': {
        'class': QueryExpansionBaseline,
        'description': 'Pseudo-relevance feedback query expansion',
        'needs_llm': False,
    },
    'hyde': {
        'class': HyDEBaseline,
        'description': 'Hypothetical Document Embedding (Gao et al., 2022)',
        'needs_llm': True,
    },
}


def run_external_baselines(
    baselines: List[str] = None,
    ground_truth_path: str = "expanded_ground_truth.json",
    max_cases: int = None,
    top_k: int = 15
):
    """
    Run external baselines through evaluate_h2l_proper.py pipeline
    """
    from evaluate_h2l_proper import (
        EvaluationRunner,
        load_problem_taxonomy,
        build_relevance_keywords,
        judge_relevance,
        compute_all_metrics,
        save_results,
        print_comparison_table,
        run_statistical_tests,
    )
    
    if baselines is None:
        baselines = list(BASELINE_REGISTRY.keys())
    
    # Load config & shared components
    from config import get_config
    from retrieval_engine import HybridRetriever, DenseIndex, ThaiBM25, Reranker
    
    config = get_config()
    logger.info("📦 Loading shared components...")
    all_docs = HybridRetriever._load_all_docs(config)
    doc_map = {doc.id: doc for doc in all_docs}
    
    dense = DenseIndex(config.DB_TYPE, str(config.DB_PATH), config.EMBEDDING_MODEL, config.DEVICE)
    bm25 = ThaiBM25(all_docs)
    reranker = Reranker(config.RERANK_MODEL, config.DEVICE) if config.USE_RERANK else None
    
    shared = {
        "all_docs": all_docs, "doc_map": doc_map,
        "dense_retriever": dense, "lexical_retriever": bm25,
        "reranker": reranker
    }
    
    taxonomy = load_problem_taxonomy()
    
    # Load ground truth
    with open(ground_truth_path, 'r', encoding='utf-8') as f:
        gt_data = json.load(f)
    cases = gt_data.get('cases', [])
    if max_cases:
        cases = cases[:max_cases]
    
    logger.info(f"📊 Running {len(baselines)} external baselines on {len(cases)} cases")
    
    from collections import defaultdict
    all_results = {}
    aggregates = {}
    
    for baseline_name in baselines:
        if baseline_name not in BASELINE_REGISTRY:
            logger.warning(f"Unknown baseline: {baseline_name}, skipping")
            continue
        
        info = BASELINE_REGISTRY[baseline_name]
        logger.info(f"\n{'='*60}")
        logger.info(f"🔄 Baseline: {baseline_name} ({info['description']})")
        logger.info(f"{'='*60}")
        
        try:
            retriever = info['class'](config, shared)
        except Exception as e:
            logger.error(f"Failed to init {baseline_name}: {e}")
            continue
        
        strategy_results = []
        metric_lists = defaultdict(list)
        
        for i, case in enumerate(cases):
            case_id = case.get('case_id', f'case_{i}')
            query = case.get('case_description', '')
            expected = case.get('expected_diagnosis', {}).get('problem_list', [])
            
            if not query:
                continue
            
            relevance_keywords = build_relevance_keywords(expected, taxonomy)
            
            start_time = time.time()
            try:
                results = retriever.retrieve(query, top_k_override=top_k)
            except Exception as e:
                logger.error(f"  [{i+1}] {case_id}: {e}")
                continue
            elapsed = time.time() - start_time
            
            # Judge relevance
            relevance_grades = []
            for r in results:
                doc = r.doc if hasattr(r, 'doc') else r
                doc_text = getattr(doc, 'text', '')
                grade = judge_relevance(doc_text, relevance_keywords, expected)
                relevance_grades.append(grade)
            
            metrics = compute_all_metrics(relevance_grades)
            metrics['retrieval_time'] = elapsed
            
            for metric_name, value in metrics.items():
                if isinstance(value, (int, float)):
                    metric_lists[metric_name].append(value)
            
            strategy_results.append({
                'case_id': case_id,
                'metrics': metrics,
                'relevance_grades': relevance_grades,
            })
            
            if (i + 1) % 10 == 0:
                logger.info(f"  [{i+1}/{len(cases)}] Processed...")
        
        # Aggregate
        agg = {}
        for metric_name, values in metric_lists.items():
            if values:
                mean_val = sum(values) / len(values)
                std_val = (sum((v - mean_val)**2 for v in values) / len(values)) ** 0.5
                agg[metric_name] = {
                    'mean': mean_val,
                    'std': std_val,
                    'n': len(values),
                    'values': values,
                }
        
        all_results[baseline_name] = strategy_results
        aggregates[baseline_name] = agg
        
        logger.info(f"\n  📈 {baseline_name} Summary:")
        for metric in ['nDCG@5', 'P@5', 'MAP', 'MRR']:
            if metric in agg:
                logger.info(f"    {metric}: {agg[metric]['mean']:.4f} ± {agg[metric]['std']:.4f}")
    
    # Print comparison table
    print_comparison_table(aggregates)
    
    # Save results
    output = {
        'metadata': {
            'timestamp': datetime.now().isoformat(),
            'baselines': baselines,
            'num_cases': len(cases),
            'top_k': top_k,
        },
        'aggregates': aggregates,
    }
    
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("evaluation_results")
    output_dir.mkdir(exist_ok=True)
    
    # Clean for JSON serialization
    clean_agg = {}
    for name, agg in aggregates.items():
        clean_agg[name] = {m: {k: v for k, v in d.items() if k != 'values'} for m, d in agg.items()}
    
    with open(output_dir / f"external_baselines_{ts}.json", 'w', encoding='utf-8') as f:
        json.dump({'metadata': output['metadata'], 'aggregates': clean_agg}, f, indent=2)
    
    logger.info(f"\n✅ Results saved to evaluation_results/external_baselines_{ts}.json")


def main():
    parser = argparse.ArgumentParser(description='External Baseline Comparison')
    parser.add_argument('--baselines', nargs='+', default=None,
                       choices=list(BASELINE_REGISTRY.keys()),
                       help='Baselines to run (default: all)')
    parser.add_argument('--ground-truth', default='expanded_ground_truth.json')
    parser.add_argument('--max-cases', type=int, default=None)
    parser.add_argument('--top-k', type=int, default=15)
    
    args = parser.parse_args()
    
    run_external_baselines(
        baselines=args.baselines,
        ground_truth_path=args.ground_truth,
        max_cases=args.max_cases,
        top_k=args.top_k,
    )


if __name__ == "__main__":
    main()
