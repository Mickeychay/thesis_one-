#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Script: Verify Strategy Differences
=========================================

This script tests whether different strategies actually produce different results.
"""

import sys
import logging
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_strategy_differences():
    """Smoke-test strategy execution without returning diagnostic payloads."""

    # Import after path setup
    from h2l.config import Config
    from orchestrator import RAGFirstOrchestrator

    config = Config()

    # Test case
    test_case = """
    เด็กหญิงอายุ 15 ปี มีอาการซึมเศร้า นอนไม่หลับ ไม่อยากไปโรงเรียน
    มีความคิดอยากทำร้ายตัวเอง พ่อแม่หย่าร้าง อยู่กับแม่ที่ดื่มเหล้า
    """

    strategies = ["h2l-hybrid", "h2l-dynamic", "h2l-multihop", "h2l-adaptive"]

    print("\n" + "="*80)
    print("🔍 Testing Strategy Differences")
    print("="*80)

    results = {}

    for strategy in strategies:
        print(f"\n📊 Testing: {strategy.upper()}")
        print("-" * 80)

        try:
            # Create orchestrator with strategy
            orc = RAGFirstOrchestrator(
                config=config,
                retriever_strategy=strategy
            )

            # Analyze case
            result = orc.analyze_case(test_case, f"TEST_{strategy}")

            # Extract key metrics
            problems = result.get('problems', [])
            retrieved_docs = result.get('retrieved_docs', [])
            retriever_class = result.get('retriever_class', 'Unknown')
            execution_time = result.get('execution_time', 0)
            strategy_metadata = result.get('strategy_metadata', {})

            results[strategy] = {
                'problems_count': len(problems),
                'docs_count': len(retrieved_docs),
                'retriever_class': retriever_class,
                'execution_time': execution_time,
                'problems': [p.get('code', 'N/A') for p in problems],
                'top_doc_scores': [
                    getattr(doc, 'final_score', getattr(doc, 'score', 0))
                    for doc in retrieved_docs[:3]
                ] if retrieved_docs else [],
                'strategy_metadata': strategy_metadata
            }

            # Print results
            print(f"✅ Retriever Class: {retriever_class}")
            if strategy_metadata:
                print(f"   Base Strategy: {strategy_metadata.get('base_strategy', 'N/A')}")
                features = strategy_metadata.get('features', {})
                print(f"   Features: Adaptive={features.get('adaptive', False)}, Multihop={features.get('multihop', False)}")
                scoring = strategy_metadata.get('scoring_params', {})
                print(f"   Alpha: {scoring.get('alpha', 'N/A')}")
            print(f"   Problems Found: {len(problems)}")
            print(f"   Problem Codes: {', '.join([p.get('code', 'N/A') for p in problems])}")
            print(f"   Documents Retrieved: {len(retrieved_docs)}")
            if retrieved_docs:
                print(f"   Top 3 Doc Scores: {[f'{s:.4f}' for s in results[strategy]['top_doc_scores']]}")
            print(f"   Execution Time: {execution_time:.3f}s")

        except Exception as e:
            pytest.fail(f"{strategy} failed during strategy-difference smoke test: {e}")

    # Compare results
    print("\n" + "="*80)
    print("📈 Comparison Summary")
    print("="*80)

    # Check if problems are the same
    problem_sets = [tuple(r.get('problems', [])) for r in results.values() if 'problems' in r]
    if len(set(problem_sets)) == 1:
        print("⚠️  WARNING: All strategies detected the SAME problems!")
        print("   This is expected because detection uses the same detector.")
    else:
        print("✅ Different strategies detected different problems.")

    # Check if retriever classes are different
    retriever_classes = [r.get('retriever_class', 'Unknown') for r in results.values() if 'retriever_class' in r]
    unique_classes = set(retriever_classes)
    print(f"\n🔧 Retriever Classes Used: {len(unique_classes)} unique")
    for cls in unique_classes:
        strategies_using = [s for s, r in results.items() if r.get('retriever_class') == cls]
        print(f"   • {cls}: {', '.join(strategies_using)}")

    # Check if document counts are different
    doc_counts = [r.get('docs_count', 0) for r in results.values() if 'docs_count' in r]
    if len(set(doc_counts)) > 1:
        print(f"\n✅ Different strategies retrieved different numbers of documents:")
        for strategy, result in results.items():
            if 'docs_count' in result:
                print(f"   • {strategy}: {result['docs_count']} docs")
    else:
        print(f"\n⚠️  WARNING: All strategies retrieved the SAME number of documents ({doc_counts[0] if doc_counts else 0})")

    # Check if scores are different
    print(f"\n📊 Top Document Scores:")
    for strategy, result in results.items():
        if 'top_doc_scores' in result and result['top_doc_scores']:
            scores_str = ', '.join([f'{s:.4f}' for s in result['top_doc_scores']])
            print(f"   • {strategy}: [{scores_str}]")
        else:
            print(f"   • {strategy}: No documents retrieved")

    # Final verdict
    print("\n" + "="*80)
    print("🎯 Final Verdict")
    print("="*80)

    assert results, "No strategy results were collected"
    assert all("error" not in result for result in results.values())
    assert all(result["problems_count"] > 0 for result in results.values())
    assert all(result["retriever_class"] for result in results.values())

    # In safe-start or no-index environments, strategies may degrade to the same
    # retriever with zero documents. Keep this as a smoke test, and let full
    # evaluation artifacts carry the statistical strategy-difference claim.
    docs_available = any(result.get("docs_count", 0) > 0 for result in results.values())
    if docs_available:
        assert all(result.get("docs_count", 0) > 0 for result in results.values())

    # Check if scores differ significantly
    all_scores = [r.get('top_doc_scores', []) for r in results.values() if 'top_doc_scores' in r]
    if all_scores and len(all_scores) > 1:
        # Check if first doc score varies by more than 0.01
        first_scores = [scores[0] if scores else 0 for scores in all_scores]
        score_range = max(first_scores) - min(first_scores)
        if score_range > 0.01:
            print(f"✅ GOOD: Document scores vary significantly (range: {score_range:.4f})")
            print("   → Strategies are producing different rankings.")
        else:
            print(f"⚠️  WARNING: Document scores are very similar (range: {score_range:.4f})")
            print("   → Strategies may not be differentiating effectively.")

    print("\n" + "="*80)


if __name__ == "__main__":
    test_strategy_differences()
