#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
H2L Orchestrator (Optimized Version)
=====================================
✅ Global Model Caching: โหลดโมเดล Retrieval ครั้งเดียว
✅ Shared H2L Detector: รองรับการรับ Detector ที่สร้างไว้แล้ว
✅ Robust Path Finding: หาไฟล์ JSON เจอเสมอ
"""

import json
import logging
import time
import os
from typing import Dict, List, Optional, TYPE_CHECKING
from pathlib import Path

if TYPE_CHECKING:
    from H2LDetector import H2LDetector

# Setup logging first
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Import Retrievers ---
from retrieval_engine import HybridRetriever

# --- Import H2L Components ---
try:
    from h2l.detector import H2LDetector
    from h2l.core import H2LUnifiedRetriever
    _HAS_H2L = True
except Exception as e:
    logger.error(f"Failed to import H2L components: {e}")
    _HAS_H2L = False

# เก็บโมเดลค้นหา (Embeddings, BM25 Index) ไว้ที่นี่
_GLOBAL_SHARED_COMPONENTS = None

class RAGFirstOrchestrator:
    
    def __init__(
        self,
        config,
        shared_components=None,
        retriever_strategy: str = "h2l-hybrid",
        problem_codes_path: str = "problem_codes.json",
        assessment_tools_path: str = "assessment_tools.json",
        h2l_detector: Optional["H2LDetector"] = None,
        enable_l2: bool = True
    ):
        # 1. กำหนดค่าพื้นฐานก่อน
        self.config = config
        self.retriever_strategy = retriever_strategy.lower()
        self.enable_l2 = enable_l2
        
        # 2. Log strategy ที่เลือก
        logger.info(f"🔧 Initializing with strategy: {self.retriever_strategy}")
        
        # 3. สร้าง H2L Detector
        if h2l_detector:
            self.h2l_detector = h2l_detector
        else:
            real_path = self._resolve_path(problem_codes_path)
            try:
                self.h2l_detector = H2LDetector(config=config, taxonomy_path=real_path)
            except:
                self.h2l_detector = H2LDetector(taxonomy_path=real_path)

        # 4. โหลด Shared Components
        self._ensure_global_components(config)
        
        # 5. สร้าง Retriever
        self.retriever = self._init_retriever(
            self.retriever_strategy, 
            config, 
            _GLOBAL_SHARED_COMPONENTS
        )
        
        # 6. Log retriever ที่ใช้
        logger.info(f"✅ Using retriever: {type(self.retriever).__name__}")
        
        # 7. โหลด Tools
        real_tools_path = self._resolve_path(assessment_tools_path)
        self.assessment_tools = self._load_json(real_tools_path)
        
    def _ensure_global_components(self, config):
        """โหลด Shared Components (Model/Index) ครั้งเดียว"""
        global _GLOBAL_SHARED_COMPONENTS
        
        if _GLOBAL_SHARED_COMPONENTS is None:
            logger.info("⚡ Loading AI Models & Index (First Time Only)...")
            try:
                # สร้าง Temporary Hybrid Retriever เพื่อโหลดทุกอย่าง
                temp = HybridRetriever(config)
                _GLOBAL_SHARED_COMPONENTS = {
                    'all_docs': temp.all_docs,
                    'doc_map': temp.doc_map,
                    'dense_retriever': temp.dense_retriever,
                    'lexical_retriever': temp.lexical_retriever,
                    'reranker': temp.reranker
                }
                logger.info("✅ Global Components Cached!")
            except Exception as e:
                logger.error(f"❌ Failed to cache components: {e}")
                raise  # Propagate error so caller can fall back to detector-only mode

    def _resolve_path(self, filename: str) -> str:
        """ฟังก์ชันช่วยหาไฟล์: หาใน Root ก่อน แล้วค่อยหาใน Data"""
        clean = os.path.basename(filename)
        # 1. หาในโฟลเดอร์ปัจจุบัน
        if os.path.exists(clean): return clean
        # 2. ลองหาใน data/
        data_path = os.path.join("data", clean)
        if os.path.exists(data_path): return data_path
        # 3. คืนค่าเดิม
        return filename

    def _load_json(self, path: str) -> Dict:
        try:
            with open(path, 'r', encoding='utf-8') as f: return json.load(f)
        except: return {}

    def _init_retriever(self, strategy: str, config, shared):
        """เลือก Retriever ตาม Strategy"""
        if strategy.startswith("h2l-") and _HAS_H2L:
            # H2L strategies: use H2LUnifiedRetriever with strategy_mode auto-mapping
            return H2LUnifiedRetriever(
                config=config,
                shared_components=shared,
                strategy_mode=strategy  # Auto-maps via _STRATEGY_MODE_MAP
            )
        # Baselines (no H2L scoring)
        elif strategy == "bm25_only":
            from unified_baselines import BM25OnlyBaseline
            return BM25OnlyBaseline(config, shared)
        elif strategy == "naive_rag":
            from unified_baselines import NaiveRAGBaseline
            return NaiveRAGBaseline(config, shared)
        elif strategy == "hyde":
            from unified_baselines import HyDEBaseline
            return HyDEBaseline(config, shared)
        else:
            return HybridRetriever(config, shared)

    def _compute_retrieval_evidence(self, problems: List[Dict], retrieved_docs) -> List[float]:
        """
        Compute per-problem retrieval evidence scores.
        
        For each problem, measures what fraction of retrieved docs
        contain keywords related to that problem, weighted by document rank.
        
        Returns:
            List of retrieval evidence scores (0.0–1.0), one per problem
        """
        if not problems or not retrieved_docs:
            return [0.0] * len(problems)
        
        # Extract document texts
        doc_texts = []
        for d in retrieved_docs:
            text = ""
            if hasattr(d, 'doc') and d.doc:
                text = d.doc.text.lower() if d.doc.text else ""
            elif isinstance(d, dict):
                text = str(d.get('text', '')).lower()
            doc_texts.append(text)
        
        if not doc_texts or not any(doc_texts):
            return [0.0] * len(problems)
        
        n_docs = len(doc_texts)
        evidence_scores = []
        
        for problem in problems:
            # Collect search terms from problem keywords and name
            search_terms = []
            keywords = problem.get('matched_keywords', [])
            search_terms.extend([kw.lower() for kw in keywords if kw and len(kw) > 1])
            
            name = problem.get('name', '')
            if name:
                # Use words with >2 chars to avoid noise
                name_words = [w.lower() for w in name.split() if len(w) > 2]
                search_terms.extend(name_words)
            
            if not search_terms:
                evidence_scores.append(0.0)
                continue
            
            # Rank-weighted support: top docs matter more
            weighted_support = 0.0
            total_weight = 0.0
            
            for rank, doc_text in enumerate(doc_texts):
                if not doc_text:
                    continue
                # Rank discount: 1/(rank+1) — top docs matter more
                rank_weight = 1.0 / (rank + 1)
                total_weight += rank_weight
                
                # Count how many search terms appear in this doc
                matches = sum(1 for term in search_terms if term in doc_text)
                if matches > 0:
                    term_coverage = min(1.0, matches / len(search_terms))
                    weighted_support += rank_weight * term_coverage
            
            # Normalize to [0, 1]
            evidence = weighted_support / total_weight if total_weight > 0 else 0.0
            evidence_scores.append(min(1.0, evidence))
        
        return evidence_scores

    def analyze_case(self, case_text: str, case_id: str = None) -> Dict:
        """
        ฟังก์ชันหลัก: รับเคส -> วิเคราะห์ปัญหา -> ค้นหาเอกสาร -> สรุปผล
        """
        start_time = time.time()

        # Step 1: Detect Problems (ใช้ L2 ตาม enable_l2 flag จาก user)
        is_h2l = "h2l" in self.retriever_strategy
        detection_result = self.h2l_detector.detect_with_metadata(case_text, use_l2=self.enable_l2)
        detected_problems = detection_result["problems"]
        detection_metadata = detection_result.get("metadata", {})

        # Extract detection info
        l1_count = detection_metadata.get("l1_count", 0)
        l2_count = detection_metadata.get("l2_count", 0)
        filtered_out = detection_result.get("filtered_out", [])
        # L2 applied = มีการ detect implicit (l2_count) หรือ กรอง L1 ออก (filtered_out)
        l2_was_actually_applied = (self.enable_l2 and (l2_count > 0 or len(filtered_out) > 0))

        # Step 2: Retrieve Documents (ใช้ H2L Context ถ้ามี)
        try:
            retrieved_docs = self.retriever.retrieve(
                query=case_text,
                explicit_problems=detected_problems, # ส่งปัญหาไปช่วยค้นหา
                top_k_override=self.config.TOP_K
            )
        except TypeError as e:
            # Fallback สำหรับ Retriever ทั่วไป
            logger.warning(f"TypeError in retrieve(): {e}")
            retrieved_docs = self.retriever.retrieve(query=case_text)

        # Step 3: Recommend Tools & Severity (With Demographic Gating)
        context = detection_metadata.get("context_analysis", {})
        demographic_group = context.get("demographic_group", "general").lower()
        
        recommended_tools = self._recommend_tools(detected_problems, demographic_group=demographic_group)
        severity_level = self._determine_severity(detected_problems)

        # Step 4: Metrics
        execution_time = time.time() - start_time
        
        # Detection-only confidence (same for all strategies)
        detection_confidence = 0.0
        if detected_problems:
            detection_confidence = sum(p['confidence'] for p in detected_problems) / len(detected_problems)

        # Step 4a: Retrieval-Augmented Confidence  
        # Combines detection confidence (80%) with retrieval evidence (20%)
        # so strategies that retrieve more relevant docs → higher confidence
        LAMBDA = 0.2  # Retrieval evidence weight
        retrieval_evidence_scores = self._compute_retrieval_evidence(detected_problems, retrieved_docs)
        
        if retrieval_evidence_scores and detected_problems:
            avg_retrieval_evidence = sum(retrieval_evidence_scores) / len(retrieval_evidence_scores)
        else:
            avg_retrieval_evidence = 0.0
        
        # Combined confidence: detection dominates, retrieval evidence adjusts
        avg_confidence = detection_confidence * (1 - LAMBDA) + avg_retrieval_evidence * LAMBDA if detected_problems else 0.0

        # Step 4b: Retrieval quality metrics (strategy-dependent)
        avg_retrieval_score = 0.0
        top3_avg_score = 0.0
        if retrieved_docs:
            scores = []
            for d in retrieved_docs:
                if hasattr(d, 'final_score'):
                    scores.append(d.final_score)
                elif isinstance(d, dict):
                    scores.append(d.get('final_score', d.get('score', 0.0)))
            if scores:
                avg_retrieval_score = sum(scores) / len(scores)
                top3_avg_score = sum(sorted(scores, reverse=True)[:3]) / min(3, len(scores))

        # Extract strategy metadata from retriever if available
        strategy_metadata = {}
        if hasattr(self.retriever, 'base_strategy'):
            strategy_metadata = {
                "base_strategy": self.retriever.base_strategy,
                "features": {
                    "adaptive": getattr(self.retriever, 'enable_adaptive', False),
                    "multihop": getattr(self.retriever, 'enable_multihop', False)
                },
                "scoring_params": {
                    "alpha": getattr(self.retriever, 'alpha', 1.0)
                }
            }

        return {
            "case_id": case_id,
            "problems": detected_problems,
            "filtered_out": detection_result.get("filtered_out", []),
            "tools": recommended_tools,
            "severity_level": severity_level,
            "retrieved_docs_count": len(retrieved_docs),
            "retrieved_docs": retrieved_docs,
            "metrics": {
                "avg_confidence": avg_confidence,
                "detection_confidence": detection_confidence,
                "retrieval_evidence": avg_retrieval_evidence,
                "problems_found": len(detected_problems),
                "execution_time": execution_time,
                "avg_retrieval_score": avg_retrieval_score,
                "top3_avg_score": top3_avg_score
            },
            "execution_time": execution_time,
            "retrieval_strategy": self.retriever_strategy,
            "retriever_class": type(self.retriever).__name__,
            "strategy_metadata": strategy_metadata,
            "detection_info": {
                "l1_candidates": l1_count + l2_count,
                "l2_applied": l2_was_actually_applied,
                "final_count": len(detected_problems),
                "filtered_count": len(detection_result.get("filtered_out", [])),
                "l1_count": l1_count,
                "l2_count": l2_count
            }
        }

    def _determine_severity(self, problems: List[Dict]) -> str:
        """ประเมินระดับความรุนแรง"""
        if not problems: return "UNKNOWN"
        
        codes = [p.get('code', '') for p in problems]
        # เช็คความเสี่ยงสูงพิเศษ
        if any(c == "X60-X84" or c.startswith("X") for c in codes): return "CRITICAL"
        
        max_sev = max((p.get('severity', 1) for p in problems), default=1)
        return {5: "CRITICAL", 4: "SEVERE", 3: "MODERATE"}.get(max_sev, "MILD")

    def _recommend_tools(self, problems: List[Dict], demographic_group: str = "general") -> List[Dict]:
        """
        แนะนำเครื่องมือตามปัญหา (Neuro-Symbolic Demographic Gating)

        Uses assessment_tools.json to match tools based on:
        - Problem codes (exact match)
        - Keywords in problem names/descriptions
        - $G_{demo}$: Demographics validation from LLM Extractor
        - Severity-based prioritization
        """
        if not problems:
            return [{
                "name": "S.D.M.A.",
                "priority": "Mandatory",
                "reason": "Standard Protocol"
            }]

        # Always include S.D.M.A. as baseline
        recommended = [{
            "name": "S.D.M.A.",
            "priority": "Mandatory",
            "reason": "Standard Protocol"
        }]

        # Extract problem codes and keywords
        problem_codes = {p.get('code', '') for p in problems}
        problem_keywords = set()
        for p in problems:
            # Add problem name words
            if 'name' in p:
                problem_keywords.update(p['name'].lower().split())
            # Add problem description words
            if 'description' in p:
                problem_keywords.update(p['description'].lower().split())

        # Track tool matches with scores
        tool_matches = {}  # {tool_name: {'score': int, 'reasons': [str]}}

        # Iterate through all tools in assessment_tools.json
        for tool_key, tool_data in self.assessment_tools.items():
            tool_name = tool_data.get('name', tool_key)
            use_for = tool_data.get('use_for', [])

            score = 0
            reasons = []

            # Check code matches
            for code in problem_codes:
                for use_case in use_for:
                    use_case_upper = str(use_case).upper()
                    code_upper = code.upper()

                    # Exact match
                    if code_upper == use_case_upper:
                        score += 10
                        if f"รหัส {code}" not in reasons:
                            reasons.append(f"รหัส {code}")
                    # Prefix match (e.g., F32 matches F32-F33)
                    elif code_upper in use_case_upper or use_case_upper in code_upper:
                        score += 8
                        if f"รหัส {code}" not in reasons:
                            reasons.append(f"รหัส {code}")

            # Check keyword matches
            for keyword in problem_keywords:
                for use_case in use_for:
                    if keyword in str(use_case).lower():
                        score += 3
                        if f"คำสำคัญ: {keyword}" not in reasons:
                            reasons.append(f"คำสำคัญ: {keyword}")
                        break  # Count each keyword once per tool

            # ==============================================================
            # Neuro-Symbolic Gating: $G_{demo}$
            # ==============================================================
            target_demos = tool_data.get("target_demographics", ["general"])
            g_demo = 1.0  # Base logic
            
            # If the tool specifies constraints
            if "general" not in target_demos:
                # If LLM detected a demographic constraint but tool doesn't match
                if demographic_group != "general" and demographic_group not in [d.lower() for d in target_demos]:
                    g_demo = 0.0
                    logger.info(f"🚫 [G_demo = 0.0] Blocked {tool_name} (Requires: {target_demos}, Patient: {demographic_group})")

            final_score = score * g_demo

            # If tool has matches and survived demographic gate
            if final_score > 0:
                tool_matches[tool_name] = {
                    'score': final_score,
                    'reasons': reasons[:3],  # Limit to top 3 reasons
                    'tool_key': tool_key,
                    'description': tool_data.get('description', '')
                }

        # Determine priority based on tool type and score
        def get_priority(tool_key: str, score: float) -> str:
            # Critical tools (suicide, violence)
            if tool_key in ['8Q', 'WAST', 'CMST']:
                return 'Critical'
            # High priority (mental health, substance abuse)
            elif tool_key in ['9Q', 'PHQ-9', 'AUDIT', 'DAST-10', 'F.R.A.']:
                return 'High'
            # Medium priority based on score
            elif score >= 10.0:
                return 'High'
            elif score >= 5.0:
                return 'Medium'
            else:
                return 'Low'

        # Sort by score and add to recommendations
        sorted_tools = sorted(
            tool_matches.items(),
            key=lambda x: x[1]['score'],
            reverse=True
        )

        # Limit to top 10 tools (excluding S.D.M.A.)
        for tool_name, match_data in sorted_tools[:10]:
            tool_key = match_data['tool_key']
            priority = get_priority(tool_key, match_data['score'])
            reason = ', '.join(match_data['reasons']) if match_data['reasons'] else 'ตรงตามเกณฑ์'

            recommended.append({
                'name': tool_name,
                'priority': priority,
                'reason': reason,
                'description': match_data['description']
            })

        return recommended

# Backward compatibility alias
EnhancedOrchestrator = RAGFirstOrchestrator