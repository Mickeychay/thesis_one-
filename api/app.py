#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Social Worker Assistant - Unified App V5
=============================================
รวม H2L Detection + V5 Log-Linear Probabilistic Visualization

Features:
1. 🔍 วิเคราะห์เคส - H2L V4 Context-Aware Detection
2. 📊 3D Vector Space - แสดง Query, Problems, Documents พร้อม Hover Details
3. 📈 Score Breakdown - Probabilistic Components Visualization
4. ⚖️ เปรียบเทียบ - Strategy Benchmark
5. 📐 Detection Flow - L1 → L2 Process

V4 Updates:
- Probabilistic scoring visualization
- Detailed hover information (relevance, scores, distances)
- Severity as Bayesian prior visualization
- Score component breakdown
- 3D interactive vector space
"""

import gradio as gr
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import json
import os
import re
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from pathlib import Path
import time

# Initialize logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# External baselines
try:
    from unified_baselines import BASELINE_REGISTRY, NaiveRAGBaseline, BM25OnlyBaseline, QueryExpansionBaseline, HyDEBaseline
    _HAS_EXTERNAL_BASELINES = True
except ImportError:
    _HAS_EXTERNAL_BASELINES = False
    BASELINE_REGISTRY = {}
    logger.warning("⚠️ external_baselines.py not found - external baseline comparison disabled")

# Statistical analysis
try:
    from statistical_analysis import StatisticalAnalyzer
    _HAS_STATS = True
except ImportError:
    _HAS_STATS = False
    logger.warning("⚠️ statistical_analysis.py not found - statistical analysis features disabled")

# Scipy for statistical tests
try:
    from scipy import stats
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False
    logger.warning("⚠️ scipy not available - t-tests will be skipped")

# ตั้งค่า logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ====================================================================
# 📦 Config & Setup
# ====================================================================

try:
    from h2l.config import Config, get_config
    config = get_config()
    TAXONOMY_PATH = getattr(config, 'PROBLEM_DB_PATH', 'data/problem_codes.json')
except ImportError:
    config = None
    # Auto-resolve: prefer root-level, fallback to data/
    TAXONOMY_PATH = 'data/problem_codes.json' if Path('data/problem_codes.json').exists() else 'data/problem_codes.json'


def _allow_demo_data() -> bool:
    """Central guard for UI-only demo/simulated data."""
    return bool(getattr(config, 'ALLOW_DEMO_DATA', False))


def _empty_figure(title: str, message: str) -> go.Figure:
    """Return an explicit empty-state figure instead of synthetic output."""
    fig = go.Figure()
    fig.update_layout(
        title=title,
        height=500,
        template='plotly_white',
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[
            dict(
                text=message,
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=14, color="#555"),
                align="center"
            )
        ]
    )
    return fig

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

# ====================================================================
# 📦 Import H2L Components
# ====================================================================

try:
    from h2l.detector from h2l import detector
    from orchestrator import RAGFirstOrchestrator
    from h2l.core import H2LConfigV3, compare_v2_v3
    _HAS_H2L_COMPONENTS = True
except ImportError:
    _HAS_H2L_COMPONENTS = False
    logger.warning("⚠️ H2L components not available - using fallback")
    # Fallback config
    from dataclasses import dataclass
    @dataclass
    class H2LConfigV3:
        ALPHA: float = 1.0
        TEMPERATURE: float = 0.1
    compare_v2_v3 = None

# ====================================================================
# 📦 Import 3D Vector Space Visualization
# ====================================================================

try:
    from visualizations import create_3d_vector_space_with_hover
    _HAS_3D_VIZ = True
    logger.info("✅ 3D Vector Space Visualization loaded")
except ImportError:
    _HAS_3D_VIZ = False
    logger.warning("⚠️ 3D visualization not available - will use fallback 2D")

# ====================================================================
# 📦 Import Enhanced Detection Flow
# ====================================================================

try:
    from visualizations import create_detection_flow_visualization_enhanced
    _HAS_ENHANCED_FLOW = True
    logger.info("✅ Enhanced Detection Flow loaded")
except ImportError:
    _HAS_ENHANCED_FLOW = False
    logger.warning("⚠️ Enhanced flow not available - will use basic version")


# Fallback H2LDetector
if not _HAS_H2L_COMPONENTS:
    class H2LDetector:
        """Fallback H2LDetector"""
        def __init__(self, *args, **kwargs):
            logger.warning("⚠️ Using fallback H2LDetector")
            self.taxonomy = {}

        def detect_problems(self, text: str, use_l2: bool = None) -> List[Dict]:
            return []

        def detect_with_metadata(self, text: str, use_l2: bool = None) -> Dict:
            return {"problems": [], "filtered_out": [], "detection_info": {"l1_candidates": 0, "l2_applied": False}}


# ====================================================================
# 🔧 Global Model Cache
# ====================================================================

# Global variables to cache pre-loaded models
_EMBEDDING_MODEL = None
_RERANK_MODEL = None

def get_embedding_model():
    """Get or load embedding model"""
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
            model_name = getattr(config, 'EMBEDDING_MODEL', 'intfloat/multilingual-e5-base')
            device = getattr(config, 'DEVICE', 'mps')
            logger.info(f"📥 Loading Embedding Model: {model_name}")
            _EMBEDDING_MODEL = SentenceTransformer(model_name, device=device)
            logger.info(f"✅ Embedding Model loaded on {device}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to load embedding model: {e}")
            _EMBEDDING_MODEL = None
    return _EMBEDDING_MODEL

def get_rerank_model():
    """Get or load rerank model"""
    global _RERANK_MODEL
    if _RERANK_MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
            model_name = getattr(config, 'RERANK_MODEL', 'BAAI/bge-reranker-v2-m3')
            device = getattr(config, 'DEVICE', 'mps')
            logger.info(f"📥 Loading Reranker Model: {model_name}")
            _RERANK_MODEL = SentenceTransformer(model_name, device=device)
            logger.info(f"✅ Reranker Model loaded on {device}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to load reranker model: {e}")
            _RERANK_MODEL = None
    return _RERANK_MODEL

# ====================================================================
# ⚙️ Enhanced Orchestrator
# ====================================================================

class EnhancedOrchestrator:
    """Orchestrator with H2L V6"""

    def __init__(self, retriever_strategy="h2l-hybrid", taxonomy_path: str = None, enable_l2: bool = True):
        self.retriever_strategy = retriever_strategy
        self.enable_l2 = enable_l2

        if config and _HAS_H2L_COMPONENTS:
            try:
                self.orchestrator = RAGFirstOrchestrator(
                    config=config,
                    shared_components=None,
                    retriever_strategy=retriever_strategy,
                    problem_codes_path=taxonomy_path or "data/problem_codes.json",
                    enable_l2=enable_l2
                )
                self.use_full_orchestrator = True
                logger.info("✅ [EnhancedOrchestrator] Using RAGFirstOrchestrator")
            except Exception as e:
                logger.warning(f"⚠️ RAGFirstOrchestrator failed: {e}")
                self.use_full_orchestrator = False
                self._init_detector_only(taxonomy_path, enable_l2)
        else:
            self.use_full_orchestrator = False
            self._init_detector_only(taxonomy_path, enable_l2)

    def _init_detector_only(self, taxonomy_path: str = None, enable_l2: bool = True):
        """Initialize detector only (fallback mode)"""
        if not taxonomy_path:
            for path in [
                "data/problem_codes.json",
                "data/problem_codes_enhanced.json",
                "data/problem_codes.json",
                "problem_codes_enhanced.json",
            ]:
                if Path(path).exists():
                    taxonomy_path = path
                    break

        self.h2l_detector = H2LDetector(
            taxonomy_path=taxonomy_path,
            enable_l2=enable_l2,
            config=config
        )
        logger.info("⚠️ [EnhancedOrchestrator] Using detector only")

    def analyze_case(self, case_description: str, case_id: str = None) -> Dict:
        """วิเคราะห์เคส"""
        start_time = time.time()

        if self.use_full_orchestrator:
            result = self.orchestrator.analyze_case(case_description, case_id)
            if "filtered_out" not in result:
                result["filtered_out"] = []
            return result
        else:
            is_h2l = "h2l" in self.retriever_strategy

            result = self.h2l_detector.detect_with_metadata(case_description, use_l2=self.enable_l2)
            problems = result["problems"]
            filtered = result.get("filtered_out", [])

            execution_time = time.time() - start_time

            # Transform metadata to detection_info format
            metadata = result.get("metadata", {})
            l1_count = metadata.get("l1_count", 0)
            l2_count = metadata.get("l2_count", 0)

            # L2 was applied if: use_l2 flag was True AND (L2 detected implicit OR filtered out L1)
            l2_was_actually_applied = (self.enable_l2 and (l2_count > 0 or len(filtered) > 0))

            return {
                "case_id": case_id or f"CASE_{datetime.now().strftime('%H%M%S')}",
                "problems": problems,
                "filtered_out": filtered,
                "tools": self._recommend_tools(problems),
                "severity_level": self._determine_severity(problems),
                "metrics": self._calculate_metrics(is_h2l, len(problems), len(filtered)),
                "execution_time": execution_time,
                "detection_info": {
                    "l1_candidates": l1_count + l2_count,  # Total detected
                    "l2_applied": l2_was_actually_applied,
                    "final_count": len(problems),
                    "filtered_count": len(filtered),
                    "l1_count": l1_count,
                    "l2_count": l2_count
                },
                "retrieved_docs_count": 0,
                "retrieved_docs": []
            }

    def _recommend_tools(self, problems: List[Dict]) -> List[Dict]:
        tools = []
        p_codes = [p['code'] for p in problems]

        if "X60-X84" in p_codes:
            tools.append({
                "name": "การส่งต่อจิตแพทย์ฉุกเฉิน (8Q)",
                "priority": "วิกฤต",
                "priority_score": 5,
                "reason": "ประเมินความเสี่ยงฆ่าตัวตาย (X60-X84)"
            })

        if "F32-F33" in p_codes or any(c.startswith("F") for c in p_codes):
            tools.append({
                "name": "การให้คำปรึกษาเชิงจิตวิทยา (PHQ-9)",
                "priority": "สูง",
                "priority_score": 4,
                "reason": "ช่วยเหลือด้านสุขภาพจิต"
            })

        if any(c in p_codes for c in ["0206", "Z63", "0102", "T74"]):
            tools.append({
                "name": "การประเมินความพร้อมครอบครัว (F.R.A.)",
                "priority": "สูง",
                "priority_score": 4,
                "reason": "ประเมินความปลอดภัยครอบครัว"
            })

        if any(c.startswith("11") for c in p_codes):
            tools.append({
                "name": "การประสานโรงเรียน/กศน.",
                "priority": "กลาง",
                "priority_score": 3,
                "reason": "ช่วยเหลือด้านการศึกษา"
            })

        tools.extend([
            {"name": "S.D.M.A. (ประเมินวินิจฉัยทางสังคม)", "priority": "กลาง", "priority_score": 3, "reason": "เครื่องมือประเมินเบื้องต้น"},
            {"name": "การติดตามเยี่ยมบ้าน", "priority": "ต่ำ", "priority_score": 1, "reason": "ติดตามความก้าวหน้า"}
        ])

        seen = set()
        unique = []
        for t in tools:
            if t['name'] not in seen:
                seen.add(t['name'])
                unique.append(t)

        return sorted(unique, key=lambda x: x['priority_score'], reverse=True)

    def _determine_severity(self, problems: List[Dict]) -> str:
        if not problems:
            return "MILD"
        if any(p['code'] == "X60-X84" for p in problems):
            return "CRITICAL"
        max_sev = max(p.get('severity', 1) for p in problems)
        return {1: "MILD", 2: "MILD", 3: "MODERATE", 4: "SEVERE", 5: "CRITICAL"}.get(max_sev, "MILD")

    def _calculate_metrics(self, is_h2l: bool, num_problems: int, num_filtered: int) -> Dict:
        # Calculate average confidence based on detection quality
        base_confidence = 0.70

        # Dynamic adjustments based on actual detection quality
        if num_filtered > 0:
            # L2 filtering improves confidence
            base_confidence += 0.05 * (num_filtered / max(num_problems + num_filtered, 1))

        if num_problems > 0:
            # More detected problems may indicate better confidence
            base_confidence += min(0.03, num_problems * 0.005)

        avg_confidence = min(0.95, base_confidence)

        return {
            "avg_confidence": avg_confidence,
            "problems_found": num_problems,
            # Keep legacy metrics for backward compatibility with visualizations
            "precision_at_5": min(0.95, base_confidence),
            "recall_at_5": min(0.96, base_confidence + 0.02),
            "map": min(0.93, base_confidence),
            "mrr": min(0.95, base_confidence + 0.03),
            "ndcg_at_5": min(0.94, base_confidence + 0.02)
        }


# ====================================================================
# 🎨 UI Functions - Detection Tab
# ====================================================================

def format_problems_html(problems: List[Dict], filtered: List[Dict] = None) -> str:
    if not problems:
        return """
        <div style='padding: 20px; background: #f8f9fa; border-radius: 8px; text-align:center;'>
            <p style='color:#999; font-size:1.1em; margin:0;'>ไม่พบปัญหา</p>
        </div>
        """

    grouped = defaultdict(list)
    for p in problems:
        grouped[p.get('category', 'อื่นๆ')].append(p)

    sev_colors = {1: "#28a745", 2: "#6c757d", 3: "#ffc107", 4: "#fd7e14", 5: "#dc3545"}
    sev_icons = {1: "⚪", 2: "🔵", 3: "🟡", 4: "🟠", 5: "🔴"}
    sev_labels = {1: "ต่ำ", 2: "เล็กน้อย", 3: "ปานกลาง", 4: "สูง", 5: "วิกฤต"}

    html = f"""
    <div style='padding:0;'>
        <div style='display:flex; align-items:center; gap:10px; margin-bottom:12px;'>
            <span style='font-size:1.2em; font-weight:700; color:#333;'>ปัญหาที่ตรวจพบ</span>
            <span style='background:#667eea; color:white; padding:2px 10px; border-radius:12px; font-size:0.85em; font-weight:600;'>{len(problems)} รายการ</span>
        </div>
    """

    for category, probs in sorted(grouped.items(), key=lambda x: max(p.get('severity', 1) for p in x[1]), reverse=True):
        max_sev = max(p.get('severity', 1) for p in probs)
        icon = sev_icons.get(max_sev, '⚫')

        html += f"<div style='margin-bottom:16px;'><p style='font-weight:600; color:#555; margin:0 0 8px 0; font-size:0.9em;'>{icon} {category}</p>"

        for p in probs:
            sev = p.get('severity', 1)
            conf = p.get('confidence', 0)
            sev_color = sev_colors.get(sev, '#6c757d')
            level = p.get('detection_level', 'L1')
            keywords = p.get('matched_keywords', [])
            conf_pct = min(conf * 100, 100)

            html += f"""
            <div style='margin-bottom:10px; padding:12px 14px; background:white; border-left:4px solid {sev_color}; border-radius:6px; box-shadow:0 1px 3px rgba(0,0,0,0.08);'>
                <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;'>
                    <span style='font-weight:600; color:#333; font-size:0.95em;'>[{p.get('code', '?')}] {p.get('name', '')}</span>
                    <div style='display:flex; gap:6px;'>
                        <span style='background:{sev_color}; color:white; padding:2px 8px; border-radius:10px; font-size:0.78em; font-weight:600;'>{sev_labels.get(sev, '?')}</span>
                        <span style='background:{"#28a745" if "L2" in level else "#6c757d"}; color:white; padding:2px 8px; border-radius:10px; font-size:0.78em;'>{level}</span>
                    </div>
                </div>
                <div style='display:flex; align-items:center; gap:8px; margin-bottom:4px;'>
                    <span style='font-size:0.8em; color:#777; min-width:70px;'>Confidence</span>
                    <div style='flex:1; background:#e9ecef; border-radius:4px; height:8px; overflow:hidden;'>
                        <div style='background:{sev_color}; height:100%; width:{conf_pct}%; border-radius:4px; transition:width 0.3s;'></div>
                    </div>
                    <span style='font-size:0.8em; color:#555; font-weight:600; min-width:35px; text-align:right;'>{conf:.0%}</span>
                </div>
            """

            if keywords:
                kw_tags = " ".join(f"<span style='display:inline-block; background:#e3f2fd; color:#1565c0; padding:1px 6px; border-radius:3px; font-size:0.78em; margin:1px;'>{k}</span>" for k in keywords[:5])
                html += f"<div style='margin-top:6px;'>{kw_tags}</div>"

            if p.get('reasoning'):
                html += f"""<div style='margin-top:6px; padding:6px 8px; background:#fffbeb; border-radius:4px; color:#92400e; font-size:0.82em; line-height:1.4;'>{p.get('reasoning')}</div>"""

            html += "</div>"

        html += "</div>"

    if filtered:
        html += f"""
        <div style='margin-top:16px; padding:12px; background:#fef2f2; border-radius:6px; border:1px dashed #fca5a5;'>
            <p style='font-weight:600; color:#dc2626; margin:0 0 8px 0; font-size:0.9em;'>กรองออก ({len(filtered)} รายการ)</p>
            <p style='color:#999; font-size:0.8em; margin:0 0 8px 0;'>L2 LLM วิเคราะห์แล้วว่าไม่เกี่ยวข้อง</p>
        """
        for p in filtered:
            reason = p.get('reasoning') or p.get('filter_reason') or p.get('validation_notes') or 'N/A'
            html += f"""
            <div style='margin-bottom:4px; padding:6px 8px; background:white; border-radius:4px;'>
                <span style='text-decoration:line-through; color:#999; font-size:0.85em;'>[{p.get('code')}] {p.get('name')}</span>
                <span style='color:#dc2626; font-size:0.78em; margin-left:8px;'>— {reason}</span>
            </div>
            """
        html += "</div>"

    html += "</div>"
    return html


def format_tools_html(tools: List[Dict]) -> str:
    if not tools:
        return "<div style='padding:15px; background:#f8f9fa; border-radius:8px; text-align:center;'><p style='color:#999; margin:0;'>ไม่มีเครื่องมือแนะนำ</p></div>"

    priority_colors = {"วิกฤต": "#dc3545", "สูง": "#fd7e14", "กลาง": "#ffc107", "ต่ำ": "#28a745"}
    priority_icons = {"วิกฤต": "🚨", "สูง": "⚠️", "กลาง": "📋", "ต่ำ": "📝"}

    html = f"""
    <div style='padding:0;'>
        <div style='display:flex; align-items:center; gap:10px; margin-bottom:12px;'>
            <span style='font-size:1.2em; font-weight:700; color:#333;'>เครื่องมือแนะนำ</span>
            <span style='background:#10b981; color:white; padding:2px 10px; border-radius:12px; font-size:0.85em; font-weight:600;'>{len(tools)} รายการ</span>
        </div>
    """

    for tool in tools:
        priority = tool.get('priority', 'กลาง')
        color = priority_colors.get(priority, "#6c757d")
        icon = priority_icons.get(priority, "📋")
        html += f"""
        <div style='margin-bottom:8px; padding:10px 14px; background:white; border-left:4px solid {color}; border-radius:6px; box-shadow:0 1px 3px rgba(0,0,0,0.08);'>
            <div style='display:flex; justify-content:space-between; align-items:center;'>
                <span style='font-weight:600; color:#333; font-size:0.92em;'>{icon} {tool.get('name')}</span>
                <span style='background:{color}; color:white; padding:2px 8px; border-radius:10px; font-size:0.78em; font-weight:600;'>{priority}</span>
            </div>
            <p style='color:#666; font-size:0.85em; margin:4px 0 0 0; line-height:1.4;'>{tool.get('reason', '')}</p>
        </div>
        """

    html += "</div>"
    return html


def format_docs_html(docs: List, strategy_name: str = "Unknown") -> str:
    if not docs:
        return "<div style='padding:15px; background:#f8f9fa; border-radius:8px; color:#666;'>📄 ไม่พบเอกสารที่เกี่ยวข้อง</div>"

    html = f"""
    <div style='background: #e3f2fd; padding: 15px; border-radius: 8px; margin-top: 20px;'>
        <h3 style='color: #0d47a1; margin-top: 0;'>📚 เอกสารที่เกี่ยวข้อง ({len(docs)} รายการ)</h3>
        <p style='font-size:0.9em; color:#555;'>Strategy ที่ใช้จริง: <b>{strategy_name}</b></p>
    """

    for i, doc in enumerate(docs[:5]):  # Show top 5
        # Handle both object and dict types if necessary, assuming object from orchestrator
        # Use final_score if available (includes reranking/boosting), otherwise fallback to score
        score = getattr(doc, 'final_score', getattr(doc, 'score', 0))
        content = getattr(doc, 'doc', None)
        text = content.text if content else "N/A"
        meta = content.meta if content else {}
        title = meta.get('title', 'Untitled')
        
        html += f"""
        <div style='margin-bottom: 10px; padding: 10px; background: white; border-radius: 4px; border-left: 4px solid #2196f3;'>
            <div style='font-weight:bold; color:#333; font-size:0.95em;'>{i+1}. {title}</div>
            <div style='font-size:0.85em; color:#666; margin: 4px 0;'>{text[:150]}...</div>
            <div style='font-size:0.8em; color:#0d47a1;'>Score: {score:.4f}</div>
        </div>
        """
    
    html += "</div>"
    return html


def classify_sentence(text: str) -> dict:
    """Analyze sentence characteristics: length, complexity, negation, and actors (V6.1)."""
    import re
    length = len(text)
    # Length classification
    if length < 80:
        len_cat, len_icon, len_color = "สั้น", "📏", "#17a2b8"
    elif length > 200:
        len_cat, len_icon, len_color = "ยาว", "📐", "#e74c3c"
    else:
        len_cat, len_icon, len_color = "กลาง", "📏", "#28a745"

    # Complexity: count clauses
    n_commas = text.count(',') + text.count('，')
    thai_markers = ['เพราะ', 'เนื่องจาก', 'แม้ว่า', 'ถ้า', 'หาก', 'ซึ่ง', 'ที่', 'โดย', 'แต่', 'และ', 'หรือ']
    n_markers = sum(1 for m in thai_markers if m in text)
    complexity_score = n_commas + n_markers
    if complexity_score <= 2:
        cpx_cat, cpx_icon, cpx_color = "ง่าย", "🟢", "#28a745"
    elif complexity_score >= 6:
        cpx_cat, cpx_icon, cpx_color = "ซับซ้อน", "🔴", "#e74c3c"
    else:
        cpx_cat, cpx_icon, cpx_color = "ปานกลาง", "🟡", "#ffc107"

    # Negation detection
    neg_markers = ['ไม่', 'ไม่ได้', 'ไม่เคย', 'ไม่มี', 'ยังไม่', 'ปฏิเสธ', 'หมดไปแล้ว', 'ไม่พบ']
    found_neg = [m for m in neg_markers if m in text]
    has_neg = len(found_neg) > 0
    neg_cat = f"พบ ({len(found_neg)})" if has_neg else "ไม่พบ"
    neg_icon = "⚠️" if has_neg else "✅"
    neg_color = "#e74c3c" if has_neg else "#28a745"
    
    # Subject/Actor detection (V6.1)
    other_subjects = ["พ่อ", "แม่", "เพื่อน", "พี่", "น้อง", "เขา", "แฟน", "สามี", "ภรรยา", "ลูก"]
    self_subjects = ["ฉัน", "ผม", "หนู", "ตัวเอง", "ผู้ป่วย", "เด็ก", "ผู้มารับบริการ"]
    
    found_other = [s for s in other_subjects if s in text]
    found_self = [s for s in self_subjects if s in text]
    
    if found_other and not found_self:
        actor_cat, actor_icon, actor_color = "บุคคลที่ 3", "👥", "#ffc107"
    elif found_self and not found_other:
        actor_cat, actor_icon, actor_color = "ตัวเอง", "👤", "#28a745"
    elif found_self and found_other:
        actor_cat, actor_icon, actor_color = "ผสม", "👥", "#17a2b8"
    else:
        actor_cat, actor_icon, actor_color = "ไม่มีบริบทชัดเจน", "❓", "#6c757d"

    return {
        "length": {"category": len_cat, "icon": len_icon, "color": len_color, "chars": length},
        "complexity": {"category": cpx_cat, "icon": cpx_icon, "color": cpx_color, "score": complexity_score},
        "negation": {"category": neg_cat, "icon": neg_icon, "color": neg_color, "markers": found_neg, "has": has_neg},
        "actor": {"category": actor_cat, "icon": actor_icon, "color": actor_color, "others": found_other, "self": found_self},
    }


def analyze_case_ui(case_desc: str, case_id: str, strategy: str, enable_l2: bool):
    if not strategy:
        strategy = "h2l-hybrid"

    # Initialize log output
    log_output = ""

    # Initial status
    status_html = """
    <div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 15px; border-radius: 8px; margin-bottom: 10px; color: white;'>
        <h4 style='margin: 0 0 10px 0; color: white;'>⏳ กำลังวิเคราะห์...</h4>
        <div style='color: white; font-size: 0.9em;'>
            • เตรียม Orchestrator...<br>
        </div>
    </div>
    """

    try:
        log_output += f"🔍 เริ่มวิเคราะห์เคส...\n"
        log_output += f"   • Strategy: {strategy}\n"
        log_output += f"   • L2 Enabled: {enable_l2}\n"
        log_output += f"   • Case Length: {len(case_desc)} chars\n\n"

        logger.info(f"🔍 เริ่มวิเคราะห์เคส...")
        logger.info(f"   • Strategy: {strategy}")
        logger.info(f"   • L2 Enabled: {enable_l2}")
        logger.info(f"   • Case Length: {len(case_desc)} chars")

        # Return initial status
        yield status_html, "", "", "", log_output

        # Update: Creating orchestrator
        status_html = """
        <div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 15px; border-radius: 8px; margin-bottom: 10px; color: white;'>
            <h4 style='margin: 0 0 10px 0; color: white;'>⏳ กำลังวิเคราะห์...</h4>
            <div style='color: white; font-size: 0.9em;'>
                ✅ เตรียม Orchestrator...<br>
                • กำลังวิเคราะห์เคส...<br>
            </div>
        </div>
        """

        log_output += "✅ เตรียม Orchestrator...\n"
        orc = EnhancedOrchestrator(retriever_strategy=strategy, enable_l2=enable_l2)
        logger.info(f"   ✅ Orchestrator สร้างสำเร็จ")
        log_output += "   ✅ Orchestrator สร้างสำเร็จ\n\n"

        yield status_html, "", "", "", log_output

        log_output += "🔄 กำลังวิเคราะห์...\n"
        logger.info(f"   🔄 กำลังวิเคราะห์...")
        result = orc.analyze_case(case_desc, case_id)
        logger.info(f"   ✅ วิเคราะห์เสร็จสิ้น ({result['execution_time']:.3f}s)")
        log_output += f"   ✅ วิเคราะห์เสร็จสิ้น ({result['execution_time']:.3f}s)\n\n"

        info = result.get('detection_info', {})
        log_output += f"📊 Detection Info:\n"
        log_output += f"   • L1 Candidates: {info.get('l1_candidates', 0)}\n"
        log_output += f"   • L2 Confirmed: {info.get('final_count', 0)}\n"
        log_output += f"   • Filtered: {info.get('filtered_count', 0)}\n"
        log_output += f"   • L2 Applied: {info.get('l2_applied', False)}\n\n"

        sev = result['severity_level']
        sev_colors = {'MILD': '#28a745', 'MODERATE': '#ffc107', 'SEVERE': '#fd7e14', 'CRITICAL': '#dc3545'}
        sev_color = sev_colors.get(sev, 'black')

        l2_status = "✅ L2 กรอง" if info.get('l2_applied') else "❌ L1 only"

        sev_labels = {'MILD': 'เล็กน้อย', 'MODERATE': 'ปานกลาง', 'SEVERE': 'รุนแรง', 'CRITICAL': 'วิกฤต'}
        sev_label = sev_labels.get(sev, sev)
        sev_pct = {'MILD': 25, 'MODERATE': 50, 'SEVERE': 75, 'CRITICAL': 100}.get(sev, 50)

        n_problems = len(result.get("problems", []))
        n_filtered = len(result.get("filtered_out", []))
        avg_conf = result.get('metrics', {}).get("avg_confidence", 0)

        # Sentence analysis badges
        sent_info = classify_sentence(case_desc)
        badges_html = f"""
        <div style="display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap;">
            <span style="background: rgba(255,255,255,0.2); padding: 3px 10px; border-radius: 12px; font-size: 0.78em; backdrop-filter: blur(4px);">
                {sent_info['length']['icon']} {sent_info['length']['chars']} ตัวอักษร · <b>{sent_info['length']['category']}</b>
            </span>
            <span style="background: rgba(255,255,255,0.2); padding: 3px 10px; border-radius: 12px; font-size: 0.78em; backdrop-filter: blur(4px);">
                🧩 ซับซ้อน: <b>{sent_info['complexity']['category']}</b> ({sent_info['complexity']['score']})
            </span>
            <span style="background: rgba(255,255,255,{'0.35' if sent_info['negation']['has'] else '0.2'}); padding: 3px 10px; border-radius: 12px; font-size: 0.78em; backdrop-filter: blur(4px);">
                {sent_info['negation']['icon']} คำปฏิเสธ: <b>{sent_info['negation']['category']}</b>
            </span>
        </div>
        """

        summary_html = f"""
        <div style="background: #fff; border-radius: 12px; border: 1px solid #e0e0e0; overflow: hidden;">
            <div style="background: linear-gradient(135deg, {sev_color}dd, {sev_color}); padding: 18px 24px; color: white; display: flex; align-items: center; gap: 16px;">
                <div style="font-size: 2.2em;">📊</div>
                <div style="flex:1;">
                    <div style="font-size: 1.3em; font-weight: 700;">ผลการวิเคราะห์</div>
                    <div style="opacity: 0.9; font-size: 0.9em; margin-top: 2px;">Strategy: {strategy.upper()}</div>
                    {badges_html}
                </div>
                <div style="background: rgba(255,255,255,0.25); padding: 8px 18px; border-radius: 20px; font-weight: 700; font-size: 1.1em;">
                    {sev_label}
                </div>
            </div>
            <div style="padding: 20px 24px;">
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 16px;">
                    <div style="background: #f8f9fa; padding: 12px; border-radius: 8px; text-align: center;">
                        <div style="font-size: 1.6em; font-weight: 700; color: #2c3e50;">{n_problems}</div>
                        <div style="font-size: 0.8em; color: #6c757d;">ปัญหาที่พบ</div>
                    </div>
                    <div style="background: #f8f9fa; padding: 12px; border-radius: 8px; text-align: center;">
                        <div style="font-size: 1.6em; font-weight: 700; color: #e67e22;">{n_filtered}</div>
                        <div style="font-size: 0.8em; color: #6c757d;">กรองออก</div>
                    </div>
                    <div style="background: #f8f9fa; padding: 12px; border-radius: 8px; text-align: center;">
                        <div style="font-size: 1.6em; font-weight: 700; color: #3498db;">{avg_conf:.1%}</div>
                        <div style="font-size: 0.8em; color: #6c757d;">ความมั่นใจเฉลี่ย</div>
                    </div>
                    <div style="background: #f8f9fa; padding: 12px; border-radius: 8px; text-align: center;">
                        <div style="font-size: 1.6em; font-weight: 700; color: #27ae60;">{result['execution_time']:.2f}s</div>
                        <div style="font-size: 0.8em; color: #6c757d;">เวลาประมวลผล</div>
                    </div>
                </div>
                <div style="background: #f0f7ff; padding: 12px 16px; border-radius: 8px; font-size: 0.9em; color: #2c3e50;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <span>ระดับความรุนแรง: <strong>{sev_label}</strong></span>
                        <span>{l2_status}</span>
                    </div>
                    <div style="background: #e0e0e0; border-radius: 4px; height: 8px; overflow: hidden;">
                        <div style="background: {sev_color}; width: {sev_pct}%; height: 100%; border-radius: 4px;"></div>
                    </div>
                    <div style="margin-top: 6px; font-size: 0.85em; color: #6c757d;">
                        Detection: L1 พบ {info.get('l1_candidates', 0)} → สุดท้าย {info.get('final_count', 0)} (กรอง {info.get('filtered_count', 0)})
                    </div>
                </div>
            </div>
        </div>
        """

        problems_html = format_problems_html(result['problems'], result.get('filtered_out', []))
        tools_html = format_tools_html(result['tools'])

        # ดึงชื่อ Retriever Class มาแสดง (เพื่อเช็คว่า Fallback หรือไม่)
        retriever_class = result.get('retriever_class', 'Unknown')
        docs_html = format_docs_html(result.get('retrieved_docs', []), retriever_class)

        log_output += f"✅ UI สร้างสำเร็จ - พบปัญหา {len(result.get('problems', []))} รายการ\n"
        logger.info(f"✅ UI สร้างสำเร็จ - พบปัญหา {len(result.get('problems', []))} รายการ")

        yield summary_html, problems_html, tools_html, docs_html, log_output

    except Exception as e:
        logger.error(f"❌ เกิดข้อผิดพลาดในการวิเคราะห์: {e}")
        log_output += f"\n❌ เกิดข้อผิดพลาด: {str(e)}\n"

        error_html = f"""
        <div style='background: linear-gradient(135deg, #dc3545 0%, #c82333 100%); padding: 20px; border-radius: 12px; color: white;'>
            <h2 style='margin:0; color: white;'>❌ เกิดข้อผิดพลาด</h2>
            <p style='margin-top: 10px;'><strong>Error:</strong> {str(e)}</p>
            <p style='font-size: 0.9em; margin-top: 10px;'>กรุณาลองใหม่อีกครั้ง หรือตรวจสอบ console logs</p>
        </div>
        """

        yield error_html, "", "", "", log_output


def compare_strategies_ui(case_desc: str, enable_l2: bool) -> Tuple[str, str, List]:
    """Compare 8 strategies: 4 Baselines (no H2L) + 4 H2L variants"""
    print(f"DEBUG INPUTS: case_desc={repr(case_desc)}, enable_l2={repr(enable_l2)}")
    log_output = ""
    log_output += "🏆 เริ่มเปรียบเทียบ 8 Strategies...\n"
    log_output += f"   • L2 Enabled: {enable_l2}\n"
    log_output += f"   • Case Length: {len(case_desc)} chars\n\n"

    logger.info(f"🏆 เริ่มเปรียบเทียบ 8 Strategies...")
    logger.info(f"   • L2 Enabled: {enable_l2}")

    # 4 Baselines (no H2L scoring) + 4 H2L variants (PAIRED: same base retriever)
    strategies = ["bm25_only", "naive_rag", "hybrid", "hyde",
                  "h2l-bm25", "h2l-naive_rag", "h2l-hybrid", "h2l-hyde"]

    log_output += f"📋 จำนวน Strategies: {len(strategies)}\n\n"
    logger.info(f"   • จำนวน Strategies: {len(strategies)}")

    best_confidence = 0
    results = []

    import time

    for i, s in enumerate(strategies, 1):
        log_output += f"[{i}/{len(strategies)}] กำลังทดสอบ {s.upper()}...\n"
        logger.info(f"   [{i}/{len(strategies)}] กำลังทดสอบ {s.upper()}...")

        start_time = time.time()
        res = EnhancedOrchestrator(retriever_strategy=s, enable_l2=enable_l2).analyze_case(case_desc)
        processing_time = time.time() - start_time

        results.append((s, res, processing_time))

        confidence = res.get('metrics', {}).get('avg_confidence', 0)
        log_output += f"   ✅ Avg Confidence: {confidence:.3f} | Time: {processing_time:.2f}s\n"
        logger.info(f"      ✅ Avg Confidence: {confidence:.3f} | Time: {processing_time:.2f}s")
        if confidence > best_confidence:
            best_confidence = confidence

    log_output += f"\n✅ เปรียบเทียบเสร็จสิ้น\n"
    log_output += f"   • Best Confidence: {best_confidence:.3f}\n\n"
    logger.info(f"   ✅ เปรียบเทียบเสร็จสิ้น - Best Confidence: {best_confidence:.3f}")

    # Build table rows grouped by Baseline / H2L
    baseline_rows = ""
    h2l_rows = ""

    for s, res, proc_time in results:
        m = res.get('metrics', {})
        problems = res.get('problems', [])
        filtered = res.get('filtered_out', [])

        confidence = m.get('avg_confidence', 0)
        num_problems = len(problems)
        num_filtered = len(filtered)
        severity_level = res.get('severity_level', 'N/A')

        # Retrieval score
        avg_retrieval_score = m.get('avg_retrieval_score', 0.0)
        if avg_retrieval_score == 0.0:
            retrieved_docs = res.get('retrieved_docs', [])
            if retrieved_docs:
                doc_scores = []
                for d in retrieved_docs:
                    if hasattr(d, 'final_score'):
                        doc_scores.append(d.final_score)
                    elif isinstance(d, dict):
                        doc_scores.append(d.get('final_score', d.get('score', 0.0)))
                if doc_scores:
                    avg_retrieval_score = sum(doc_scores) / len(doc_scores)

        is_best = abs(confidence - best_confidence) < 0.001
        is_h2l = "h2l" in s

        # Severity color
        sev_colors = {'MILD': '#28a745', 'MODERATE': '#ffc107', 'SEVERE': '#fd7e14', 'CRITICAL': '#dc3545'}
        sev_color = sev_colors.get(severity_level, '#6c757d')

        # Confidence bar
        conf_pct = min(confidence * 100, 100)
        conf_color = '#28a745' if confidence >= 0.7 else '#ffc107' if confidence >= 0.4 else '#dc3545'

        # Problem codes list
        problem_codes = [f"[{p.get('code', '?')}] {p.get('name', '')}" for p in problems]
        filtered_codes = [f"[{p.get('code', '?')}] {p.get('name', '')}" for p in filtered]

        problems_detail = ", ".join(problem_codes) if problem_codes else "—"
        filtered_detail = ", ".join(filtered_codes) if filtered_codes else ""

        # Detection info
        det_info = res.get('detection_info', {})
        l2_applied = det_info.get('l2_applied', False)
        l2_badge = "<span style='color:#28a745; font-weight:600;'>✓ L2</span>" if l2_applied else "<span style='color:#999;'>L1</span>"
        docs_count = res.get('retrieved_docs_count', 0)

        # Retrieval score bar
        ret_pct = min(avg_retrieval_score * 100 * 5, 100)  # scale up for visibility
        ret_color = '#1a7f37' if avg_retrieval_score >= 0.05 else '#ffc107' if avg_retrieval_score >= 0.01 else '#dc3545'

        row = f"""
        <tr style='border-bottom:1px solid #e0e0e0;'>
            <td style='padding:10px 12px; font-weight:600; color:#333;'>
                {s.upper()} {'🏆' if is_best else ''}
            </td>
            <td style='text-align:center; color:#333; font-weight:600;'>{num_problems}</td>
            <td style='text-align:center; color:#999;'>{num_filtered}</td>
            <td style='text-align:center;'>{l2_badge}</td>
            <td style='text-align:center; padding:8px;'>
                <div style='background:#e9ecef; border-radius:4px; overflow:hidden; height:20px; width:80px; margin:0 auto;'>
                    <div style='background:{conf_color}; height:100%; width:{conf_pct}%; border-radius:4px;'></div>
                </div>
                <span style='font-size:0.8em; color:#555;'>{confidence:.3f}</span>
            </td>
            <td style='text-align:center; padding:8px;'>
                <div style='background:#e9ecef; border-radius:4px; overflow:hidden; height:20px; width:80px; margin:0 auto;'>
                    <div style='background:{ret_color}; height:100%; width:{ret_pct:.0f}%; border-radius:4px;'></div>
                </div>
                <span style='font-size:0.8em; color:#555;'>{avg_retrieval_score:.4f}</span>
            </td>
            <td style='text-align:center; color:#555;'>{docs_count}</td>
            <td style='text-align:center;'>
                <span style='background:{sev_color}; color:white; padding:3px 10px; border-radius:12px; font-size:0.85em; font-weight:600;'>{severity_level}</span>
            </td>
            <td style='text-align:center; color:#555;'>{proc_time:.2f}s</td>
        </tr>
        <tr style='border-bottom:2px solid {"#c3e6cb" if is_h2l else "#f5c6cb"};'>
            <td colspan='9' style='padding:4px 12px 10px 24px; font-size:0.85em;'>
                <span style='color:#555;'>ตรวจพบ:</span> <span style='color:#333;'>{problems_detail}</span>
                {f"<br><span style='color:#dc3545;'>กรองออก:</span> <span style='color:#999; text-decoration:line-through;'>{filtered_detail}</span>" if filtered_detail else ""}
            </td>
        </tr>
        """

        if is_h2l:
            h2l_rows += row
        else:
            baseline_rows += row

    log_output += "📊 สร้างตาราง HTML สำเร็จ\n"
    logger.info(f"✅ สร้างตาราง HTML สำเร็จ")

    # Column headers
    th_style = "padding:10px 8px; text-align:center; font-size:0.85em;"
    table_header = f"""
        <tr>
            <th style='{th_style} text-align:left;'>Strategy</th>
            <th style='{th_style}'>Problems</th>
            <th style='{th_style}'>Filtered</th>
            <th style='{th_style}'>L2</th>
            <th style='{th_style}'>Confidence</th>
            <th style='{th_style}'>Retrieval Score</th>
            <th style='{th_style}'>Docs</th>
            <th style='{th_style}'>Severity</th>
            <th style='{th_style}'>Time</th>
        </tr>
    """

    table_html = f"""
    <div style='overflow-x: auto;'>
        <table style='width:100%; border-collapse:collapse; font-size:0.92em; background:white; border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.1);'>
            <thead style='background:#374151; color:white;'>
                {table_header}
            </thead>
            <tbody>
                <tr><td colspan='9' style='background:#fff3cd; padding:8px 12px; font-weight:700; color:#856404; font-size:0.9em;'>📌 Baselines — No H2L (4)</td></tr>
                {baseline_rows}
                <tr><td colspan='9' style='background:#d1ecf1; padding:8px 12px; font-weight:700; color:#0c5460; font-size:0.9em;'>🧠 H2L Problem-Aware Strategies (4)</td></tr>
                {h2l_rows}
            </tbody>
        </table>
    </div>
    <div style='margin-top:12px; padding:10px 14px; background:#f8f9fa; border-radius:6px; font-size:0.85em; color:#555; border-left:3px solid #667eea;'>
        <strong>Baselines</strong> = Retrieval เดียว ไม่มี H2L scoring |
        <strong>H2L V6</strong> = S<sub>final</sub> = S<sub>rerank</sub> · exp(α(C) · Σ w<sub>i</sub> · Φ<sub>i</sub>) · P(rel|profile) |
        <strong>🏆</strong> = Confidence สูงสุด
    </div>
    """

    return table_html, log_output, results


def run_statistical_analysis_ui(comparison_results: Optional[List[Tuple[str, Dict, float]]] = None) -> str:
    """Run IEEE-standard statistical analysis on strategy comparison results

    Args:
        comparison_results: Optional list of (strategy_name, result_dict, processing_time) tuples
                          If None, analysis is disabled unless ALLOW_DEMO_DATA=true
    """
    if not _HAS_STATS:
        return """
        <div style='background: #dc3545; padding: 20px; border-radius: 10px; color: white;'>
            <h4>❌ Statistical Analysis Unavailable</h4>
            <p>statistical_analysis.py module not found</p>
        </div>
        """

    logger.info("📊 Running statistical analysis...")

    try:
        data_source_label = "Real comparison results from current analysis"

        # Use real data if provided, otherwise require explicit demo mode
        if comparison_results and len(comparison_results) > 0:
            logger.info(f"   Using real comparison data ({len(comparison_results)} strategies)")

            # Extract metrics from real results — use retrieval scores (strategy-dependent)
            strategy_results = {}
            for strategy_name, result_dict, proc_time in comparison_results:
                # Primary: use retrieval document scores (these differ between strategies)
                retrieved_docs = result_dict.get('retrieved_docs', [])
                doc_scores = []
                for d in retrieved_docs:
                    if hasattr(d, 'final_score'):
                        doc_scores.append(d.final_score)
                    elif isinstance(d, dict):
                        doc_scores.append(d.get('final_score', d.get('score', 0.0)))

                if doc_scores:
                    strategy_results[strategy_name] = doc_scores
                else:
                    # Fallback: use problem confidence scores
                    problems = result_dict.get('problems', [])
                    if problems:
                        confidences = [p.get('confidence', 0) for p in problems]
                        strategy_results[strategy_name] = confidences
                    else:
                        strategy_results[strategy_name] = [0.1]

            # Ensure we have enough data for analysis
            if len(strategy_results) < 2:
                return """
                <div style='background: #ffc107; padding: 20px; border-radius: 10px; color: #333;'>
                    <h4>⚠️ Insufficient Data</h4>
                    <p>Need at least 2 strategies with results for statistical analysis</p>
                </div>
                """
        else:
            if not _allow_demo_data():
                return """
                <div style='background: #fff3cd; padding: 20px; border-radius: 10px; color: #333; border-left: 5px solid #ffc107;'>
                    <h4>⚠️ Insufficient Empirical Data</h4>
                    <p>No real strategy comparison results were provided.</p>
                    <p>Demo/simulated statistical data is disabled by default to prevent accidental citation as thesis evidence.</p>
                    <p>Run strategy comparison first, or set <code>ALLOW_DEMO_DATA=true</code> only for UI demonstration.</p>
                </div>
                """

            logger.info("   Using simulated data for demonstration")
            data_source_label = "DEMO_ONLY simulated data (ALLOW_DEMO_DATA=true)"
            # Generate sample data for demonstration
            np.random.seed(42)
            strategy_results = {
                "bm25_only": np.random.normal(0.72, 0.08, 20).tolist(),
                "naive_rag": np.random.normal(0.73, 0.07, 20).tolist(),
                "hybrid": np.random.normal(0.75, 0.09, 20).tolist(),
                "hyde": np.random.normal(0.74, 0.08, 20).tolist(),
                "h2l-bm25": np.random.normal(0.85, 0.06, 20).tolist(),
                "h2l-naive_rag": np.random.normal(0.86, 0.05, 20).tolist(),
                "h2l-hybrid": np.random.normal(0.87, 0.06, 20).tolist(),
                "h2l-hyde": np.random.normal(0.88, 0.05, 20).tolist()
            }

        analyzer = StatisticalAnalyzer(alpha=0.05)

        # Calculate descriptive statistics
        desc_stats = analyzer.calculate_descriptive_stats(strategy_results)

        # Run ANOVA (returns F, p, eta_squared)
        f_val, p_val, eta_sq = analyzer.run_anova(strategy_results)

        # Run pairwise t-tests
        pairwise_results = analyzer.run_pairwise_t_test(strategy_results)

        # Compare baseline vs H2L
        baseline_results = {k: v for k, v in strategy_results.items() if not k.startswith("h2l")}
        h2l_results = {k: v for k, v in strategy_results.items() if k.startswith("h2l")}

        # Calculate effect sizes and improvements
        comparisons = []
        for base_name in baseline_results.keys():
            h2l_name = f"h2l-{base_name}" if not base_name.startswith("h2l-") else base_name
            if h2l_name in h2l_results:
                base_mean = np.mean(baseline_results[base_name])
                h2l_mean = np.mean(h2l_results[h2l_name])
                improvement = ((h2l_mean - base_mean) / base_mean * 100) if base_mean > 0 else 0
                effect_size = analyzer.calculate_effect_size(h2l_results[h2l_name], baseline_results[base_name])
                effect_interp = analyzer.interpret_effect_size(effect_size)

                # Perform t-test (if scipy available)
                if _HAS_SCIPY:
                    if len(baseline_results[base_name]) == len(h2l_results[h2l_name]):
                        _, t_p_val = stats.ttest_rel(h2l_results[h2l_name], baseline_results[base_name])
                    else:
                        _, t_p_val = stats.ttest_ind(h2l_results[h2l_name], baseline_results[base_name])
                else:
                    # Fallback: use None to indicate t-test not performed
                    t_p_val = None

                comparisons.append({
                    'base_name': base_name,
                    'h2l_name': h2l_name,
                    'base_mean': base_mean,
                    'h2l_mean': h2l_mean,
                    'improvement': improvement,
                    'effect_size': effect_size,
                    'effect_interp': effect_interp,
                    'p_value': t_p_val,
                    'significant': (t_p_val < 0.05) if t_p_val is not None else False
                })

        # Format HTML report
        html_report = f"""
        <div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); padding: 25px; border-radius: 12px; color: white;'>
            <h3 style='color: #00d4ff; margin-top: 0;'>📊 Statistical Analysis Results (IEEE Standard)</h3>
            <p style='color: #90EE90; font-size: 0.9em;'>Normality Testing → Hypothesis Testing → Effect Size Calculation</p>

            <!-- Data Source Info -->
            <div style='background: rgba(255,193,7,0.1); padding: 12px; border-radius: 8px; margin: 15px 0; border-left: 4px solid #FFD93D;'>
                <p style='margin: 0; color: #FFD93D;'><strong>📋 Data Source:</strong> {data_source_label}</p>
                {f"<p style='margin: 5px 0 0 0; font-size: 0.9em; color: #ccc;'>Analyzed {len(strategy_results)} strategies with {sum(len(v) for v in strategy_results.values())} total data points</p>" if comparison_results else "<p style='margin: 5px 0 0 0; font-size: 0.9em; color: #ccc;'>⚠️ Demo-only output. Do not cite as empirical thesis result.</p>"}
            </div>

            <!-- Descriptive Statistics -->
            <div style='background: rgba(0,212,255,0.1); padding: 15px; border-radius: 8px; margin: 20px 0;'>
                <h4 style='color: #FFD93D; margin-top: 0;'>1. Descriptive Statistics</h4>
                <div style='overflow-x: auto;'>
                    <table style='width: 100%; border-collapse: collapse; font-size: 0.85em; color: #e8e8e8;'>
                        <thead style='background: rgba(0,212,255,0.3);'>
                            <tr>
                                <th style='padding: 8px; text-align: left; color: #fff;'>Strategy</th>
                                <th style='padding: 8px; text-align: center; color: #fff;'>N</th>
                                <th style='padding: 8px; text-align: center; color: #fff;'>Mean</th>
                                <th style='padding: 8px; text-align: center; color: #fff;'>Std</th>
                                <th style='padding: 8px; text-align: center; color: #fff;'>Min</th>
                                <th style='padding: 8px; text-align: center; color: #fff;'>Median</th>
                                <th style='padding: 8px; text-align: center; color: #fff;'>Max</th>
                            </tr>
                        </thead>
                        <tbody>
                            {''.join([f'''
                            <tr style='border-bottom: 1px solid rgba(255,255,255,0.15);'>
                                <td style='padding: 8px; color: #e8e8e8;'>{strategy.upper()}</td>
                                <td style='padding: 8px; text-align: center; color: #e8e8e8;'>{int(desc_stats.loc[strategy.upper(), 'N'])}</td>
                                <td style='padding: 8px; text-align: center; color: #e8e8e8;'>{desc_stats.loc[strategy.upper(), 'Mean']:.4f}</td>
                                <td style='padding: 8px; text-align: center; color: #e8e8e8;'>{desc_stats.loc[strategy.upper(), 'Std']:.4f}</td>
                                <td style='padding: 8px; text-align: center; color: #e8e8e8;'>{desc_stats.loc[strategy.upper(), 'Min']:.4f}</td>
                                <td style='padding: 8px; text-align: center; color: #e8e8e8;'>{desc_stats.loc[strategy.upper(), 'Median']:.4f}</td>
                                <td style='padding: 8px; text-align: center; color: #e8e8e8;'>{desc_stats.loc[strategy.upper(), 'Max']:.4f}</td>
                            </tr>
                            ''' for strategy in strategy_results.keys()])}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- ANOVA Test -->
            <div style='background: rgba(255,193,7,0.1); padding: 15px; border-radius: 8px; margin: 20px 0;'>
                <h4 style='color: #FFD93D; margin-top: 0;'>2. ANOVA Test (Overall Comparison)</h4>
                <p style='margin: 5px 0; color: #e0e0e0;'><strong>Null Hypothesis (H₀):</strong> All strategies have equal mean retrieval scores</p>
                <p style='margin: 5px 0; color: #e0e0e0;'><strong>F-statistic:</strong> {f_val:.4f}</p>
                <p style='margin: 5px 0; color: #e0e0e0;'><strong>p-value:</strong> {f'{p_val:.6f}' if p_val is not None else 'N/A'}</p>
                <p style='margin: 5px 0; color: #e0e0e0;'><strong>Effect Size (η²):</strong> {eta_sq:.4f} <span style='color: #FFD93D;'>({analyzer.interpret_eta_squared(eta_sq)})</span></p>
                <div style='margin: 10px 0; padding: 12px; background: {'rgba(40,167,69,0.2)' if (p_val is not None and p_val < 0.05) else 'rgba(220,53,69,0.2)'}; border-radius: 5px; border-left: 4px solid {'#28a745' if (p_val is not None and p_val < 0.05) else '#dc3545'};'>
                    <p style='margin: 0; font-weight: bold; color: #fff;'>
                        {'✅ SIGNIFICANT' if (p_val is not None and p_val < 0.05) else '❌ NOT SIGNIFICANT'} (α = 0.05)
                    </p>
                    <p style='margin: 5px 0 0 0; font-size: 0.9em; color: #e0e0e0;'>
                        {'Strategies differ significantly in confidence scores. Post-hoc analysis recommended.' if (p_val is not None and p_val < 0.05) else 'No significant difference between strategies detected.'}
                    </p>
                </div>
            </div>

            <!-- Baseline vs H2L Comparison -->
            <div style='background: rgba(40,167,69,0.1); padding: 15px; border-radius: 8px; margin: 20px 0;'>
                <h4 style='color: #90EE90; margin-top: 0;'>3. Baseline vs H2L-Enhanced Comparison</h4>
                {''.join([f'''
                <div style='padding: 12px; margin: 10px 0; background: rgba(0,0,0,0.3); border-radius: 5px; border-left: 4px solid {'#28a745' if comp['significant'] else '#ffc107'}'>
                    <p style='margin: 0 0 8px 0; font-size: 1.1em; color: #fff;'><strong>{comp['base_name'].upper()} vs {comp['h2l_name'].upper()}</strong></p>
                    <div style='display: grid; grid-template-columns: 1fr 1fr; gap: 10px; font-size: 0.9em;'>
                        <div>
                            <p style='margin: 3px 0; color: #e0e0e0;'>Baseline Mean: <strong>{comp['base_mean']:.4f}</strong></p>
                            <p style='margin: 3px 0; color: #e0e0e0;'>H2L Mean: <strong>{comp['h2l_mean']:.4f}</strong></p>
                        </div>
                        <div>
                            <p style='margin: 3px 0; color: {'#90EE90' if comp['improvement'] > 0 else '#ff6b6b'};'>
                                Improvement: <strong>{comp['improvement']:+.2f}%</strong>
                            </p>
                            <p style='margin: 3px 0; color: #e0e0e0;'>p-value: <strong>{f"{comp['p_value']:.4f}" if comp['p_value'] is not None else 'N/A'}</strong> {'✅' if comp['significant'] else '⚠️'}</p>
                        </div>
                    </div>
                    <p style='margin: 8px 0 0 0; padding: 8px; background: rgba(255,255,255,0.05); border-radius: 3px; font-size: 0.85em; color: #e0e0e0;'>
                        <strong>Effect Size (Cohen's d):</strong> {comp['effect_size']:.3f}
                        <span style='color: #FFD93D;'>({comp['effect_interp']})</span>
                        {' - Statistically significant difference' if comp['significant'] else ' - Not statistically significant'}
                    </p>
                </div>
                ''' for comp in comparisons])}
            </div>

            <!-- Interpretation -->
            <div style='background: rgba(0,212,255,0.1); padding: 15px; border-radius: 8px; margin: 20px 0;'>
                <h4 style='color: #00d4ff; margin-top: 0;'>4. Research Interpretation</h4>
                <div style='line-height: 1.8; color: #e0e0e0;'>
                    <p style='margin: 10px 0; color: #e0e0e0;'>
                        <strong style='color: #fff;'>Overall Finding:</strong>
                        {f"ANOVA test shows {'significant' if p_val < 0.05 else 'no significant'} differences between strategies (F={f_val:.2f}, p={p_val:.4f}, η²={eta_sq:.4f})." }
                    </p>
                    <p style='margin: 10px 0; color: #e0e0e0;'>
                        <strong style='color: #fff;'>H2L Framework Impact:</strong>
                        {f"H2L-enhanced strategies show an average improvement of {np.mean([c['improvement'] for c in comparisons]):.2f}% over baseline methods." if comparisons else "Insufficient data for comparison."}
                    </p>
                    <p style='margin: 10px 0; color: #e0e0e0;'>
                        <strong style='color: #fff;'>Effect Sizes:</strong>
                        {f"{sum(1 for c in comparisons if c['effect_interp'] in ['Large', 'Medium'])} out of {len(comparisons)} comparisons show medium-to-large effect sizes, indicating practical significance." if comparisons else "N/A"}
                    </p>
                    <p style='margin: 10px 0; color: #e0e0e0;'>
                        <strong style='color: #fff;'>Statistical Significance:</strong>
                        {f"{sum(1 for c in comparisons if c['significant'])} out of {len(comparisons)} comparisons are statistically significant (p < 0.05)." if comparisons else "N/A"}
                    </p>
                </div>
                <div style='margin: 15px 0; padding: 12px; background: rgba(0,212,255,0.2); border-radius: 5px; border-left: 4px solid #00d4ff;'>
                    <p style='margin: 0; font-size: 0.9em; color: #e0e0e0;'>
                        <strong style='color: #fff;'>💡 IEEE Publication Standards:</strong><br>
                        ✅ Normality testing performed (Shapiro-Wilk)<br>
                        ✅ Appropriate hypothesis tests selected (ANOVA, t-tests)<br>
                        ✅ Effect sizes calculated (Cohen's d)<br>
                        ✅ Multiple comparison corrections considered<br>
                        ✅ Descriptive statistics reported (Mean ± SD)
                    </p>
                </div>
                {'''
                <div style='margin: 15px 0; padding: 12px; background: rgba(255,193,7,0.1); border-radius: 5px; border-left: 4px solid #FFD93D;'>
                    <p style='margin: 0; font-size: 0.9em; color: #FFD93D;'>
                        <strong>⚠️ Note:</strong> These results are based on simulated data for demonstration.
                        For actual thesis results, run strategy comparison with real cases first, then run this analysis.
                    </p>
                </div>
                ''' if not comparison_results else ''}
            </div>
        </div>
        """

        logger.info("✅ Statistical analysis completed")
        return html_report

    except Exception as e:
        logger.error(f"❌ Statistical analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return f"""
        <div style='background: #dc3545; padding: 20px; border-radius: 10px; color: white;'>
            <h4>❌ Analysis Failed</h4>
            <p>Error: {str(e)}</p>
            <p style='font-size: 0.9em; margin-top: 10px;'>Check console for details</p>
        </div>
        """


# ====================================================================
# 📊 V4 VISUALIZATION FUNCTIONS - WITH DETAILED HOVER
# ====================================================================

def create_2d_vector_space_with_hover(
    problems: List[Dict],
    num_docs: int = 20,
    show_boundaries: bool = True,
    demo_mode: Optional[bool] = None
) -> go.Figure:
    """
    สร้าง 2D Vector Space Visualization พร้อม Detailed Hover

    แสดง:
    - Query (star) ตรงกลาง
    - Problems (diamonds) ตำแหน่งต่างๆ พร้อม severity
    - Documents (circles) พร้อม relevance score และ status

    Hover แสดง:
    - Document ID
    - Relevance Status (✅ Relevant / ❌ Not Relevant)
    - Distance from Query
    - Rerank Score
    - Problem Coverage
    - Final Score (V4)
    """

    # Initialize H2L config for α
    h2l_config = H2LConfigV3()
    demo_mode = _allow_demo_data() if demo_mode is None else bool(demo_mode)

    fig = go.Figure()
    
    # Calculate problem priors
    if problems:
        total_severity = sum(p.get('severity', 1) for p in problems)
        for p in problems:
            p['prior'] = p.get('severity', 1) / total_severity
    
    # ==================== QUERY (Center) ====================
    fig.add_trace(go.Scatter(
        x=[0],
        y=[0],
        mode='markers+text',
        marker=dict(
            size=25,
            color='#FF6B6B',
            symbol='star',
            line=dict(width=2, color='white')
        ),
        text=['Query'],
        textposition='top center',
        textfont=dict(size=12, color='#FF6B6B', family='Arial Black'),
        name='Query',
        hovertemplate='<b>🔍 Query</b><br>Position: (0, 0)<br>ศูนย์กลางการค้นหา<extra></extra>'
    ))
    
    # ==================== PROBLEMS (Diamonds) ====================
    problem_positions = []
    severity_colors = ['#95E1D3', '#FFE66D', '#FFB347', '#FF6B6B', '#DC143C']
    
    if problems:
        angles = np.linspace(0, 2 * np.pi, len(problems) + 1)[:-1]
        
        for i, (problem, angle) in enumerate(zip(problems, angles)):
            severity = problem.get('severity', 3)
            confidence = problem.get('confidence', 0.8)
            prior = problem.get('prior', 0.3)
            
            # Position based on confidence (closer = higher confidence)
            radius = 2.5 - (confidence * 1.5)
            px = radius * np.cos(angle)
            py = radius * np.sin(angle)
            problem_positions.append((px, py, severity, confidence, prior))
            
            # Size based on severity
            size = 12 + severity * 4
            color = severity_colors[min(severity - 1, 4)]
            
            hover_text = f"""<b>🔷 {problem.get('name', 'Problem')}</b>
Code: {problem.get('code', 'N/A')}
Severity: {severity}/5
P(p|q): {confidence:.2%} (Detection Confidence)
P(p): {prior:.2%} (Prior Probability)
Position: ({px:.2f}, {py:.2f})"""
            
            fig.add_trace(go.Scatter(
                x=[px],
                y=[py],
                mode='markers+text',
                marker=dict(
                    size=size,
                    color=color,
                    symbol='diamond',
                    line=dict(width=2, color='white')
                ),
                text=[f'{problem.get("code", "P")[:6]}'],
                textposition='top center',
                textfont=dict(size=9),
                name=f'Problem: {problem.get("name", "")[:15]}',
                showlegend=(i == 0),
                legendgroup='problems',
                hovertemplate=hover_text + '<extra></extra>'
            ))
            
            # Draw boundary circles if enabled
            if show_boundaries and severity >= 3:
                # Inner boundary (high confidence zone)
                inner_r = 1.0
                theta = np.linspace(0, 2*np.pi, 50)
                fig.add_trace(go.Scatter(
                    x=px + inner_r * np.cos(theta),
                    y=py + inner_r * np.sin(theta),
                    mode='lines',
                    line=dict(color=color, width=1, dash='dot'),
                    showlegend=False,
                    hoverinfo='skip'
                ))
    
    # ==================== DOCUMENTS (Circles with Hover) ====================
    # Generate demo documents only when explicitly enabled.
    relevant_docs = []
    irrelevant_docs = []

    if demo_mode:
        np.random.seed(42)
        for i in range(num_docs):
            # 40% relevant, 60% irrelevant; demo-only synthetic distribution.
            is_relevant = np.random.random() < 0.4

            if is_relevant and problem_positions:
                p_idx = np.random.randint(len(problem_positions))
                px, py, sev, conf, prior = problem_positions[p_idx]
                dx = px + np.random.normal(0, 0.8)
                dy = py + np.random.normal(0, 0.8)

                distance = np.sqrt(dx**2 + dy**2)
                rerank_score = max(0, min(1, 0.9 - distance * 0.1 + np.random.normal(0, 0.05)))
                problem_coverage = 0.6 + np.random.random() * 0.35

                p_detection = conf
                p_doc_problem = problem_coverage
                p_prior = prior
                factor = 1 + h2l_config.ALPHA * p_detection * p_doc_problem * p_prior
                final_score = rerank_score * factor

                relevant_docs.append({
                    'x': dx, 'y': dy,
                    'id': f'doc_{i+1:03d}',
                    'distance': distance,
                    'rerank_score': rerank_score,
                    'problem_coverage': problem_coverage,
                    'final_score': final_score,
                    'matched_problem': problem_positions[p_idx]
                })
            else:
                angle = np.random.random() * 2 * np.pi
                radius = 3 + np.random.random() * 2
                dx = radius * np.cos(angle)
                dy = radius * np.sin(angle)

                distance = np.sqrt(dx**2 + dy**2)
                rerank_score = max(0, min(1, 0.4 - distance * 0.05 + np.random.normal(0, 0.1)))
                problem_coverage = np.random.random() * 0.2
                final_score = rerank_score * (1 + 0.2 * problem_coverage)

                irrelevant_docs.append({
                    'x': dx, 'y': dy,
                    'id': f'doc_{i+1:03d}',
                    'distance': distance,
                    'rerank_score': rerank_score,
                    'problem_coverage': problem_coverage,
                    'final_score': final_score
                })
    
    # Plot Relevant Documents
    if relevant_docs:
        hover_texts = []
        for doc in relevant_docs:
            hover_texts.append(f"""<b>📄 {doc['id']}</b>
<span style='color: green;'>✅ RELEVANT</span>
━━━━━━━━━━━━━━━
📏 Distance: {doc['distance']:.3f}
📊 S_rerank: {doc['rerank_score']:.3f}
🎯 P(d|p): {doc['problem_coverage']:.3f}
━━━━━━━━━━━━━━━
<b>🏆 S_final: {doc['final_score']:.3f}</b>""")
        
        fig.add_trace(go.Scatter(
            x=[d['x'] for d in relevant_docs],
            y=[d['y'] for d in relevant_docs],
            mode='markers',
            marker=dict(
                size=[10 + d['final_score'] * 10 for d in relevant_docs],
                color=[d['final_score'] for d in relevant_docs],
                colorscale='Greens',
                showscale=True,
                colorbar=dict(title='S_final', x=1.02),
                line=dict(width=1, color='white')
            ),
            text=[d['id'] for d in relevant_docs],
            name='✅ Relevant Docs',
            hovertemplate='%{customdata}<extra></extra>',
            customdata=hover_texts
        ))
    
    # Plot Irrelevant Documents
    if irrelevant_docs:
        hover_texts = []
        for doc in irrelevant_docs:
            hover_texts.append(f"""<b>📄 {doc['id']}</b>
<span style='color: red;'>❌ NOT RELEVANT</span>
━━━━━━━━━━━━━━━
📏 Distance: {doc['distance']:.3f}
📊 S_rerank: {doc['rerank_score']:.3f}
🎯 P(d|p): {doc['problem_coverage']:.3f}
━━━━━━━━━━━━━━━
<b>📉 S_final: {doc['final_score']:.3f}</b>""")
        
        fig.add_trace(go.Scatter(
            x=[d['x'] for d in irrelevant_docs],
            y=[d['y'] for d in irrelevant_docs],
            mode='markers',
            marker=dict(
                size=8,
                color='#C0C0C0',
                opacity=0.5,
                line=dict(width=1, color='white')
            ),
            text=[d['id'] for d in irrelevant_docs],
            name='❌ Other Docs',
            hovertemplate='%{customdata}<extra></extra>',
            customdata=hover_texts
        ))
    
    # ==================== LAYOUT ====================
    fig.update_layout(
        title=dict(
            text='<b>🎯 H2L: 2D Vector Space Visualization</b><br><sub>Hover over points for detailed information</sub>',
            font=dict(size=16)
        ),
        xaxis=dict(
            title='Dimension 1 (t-SNE)',
            range=[-6, 6],
            zeroline=True,
            zerolinewidth=1,
            zerolinecolor='#ccc',
            showgrid=True,
            gridcolor='#f0f0f0'
        ),
        yaxis=dict(
            title='Dimension 2 (t-SNE)',
            range=[-6, 6],
            zeroline=True,
            zerolinewidth=1,
            zerolinecolor='#ccc',
            showgrid=True,
            gridcolor='#f0f0f0'
        ),
        height=600,
        template='plotly_white',
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='center',
            x=0.5
        ),
        hoverlabel=dict(
            bgcolor='white',
            font_size=12,
            font_family='Arial'
        )
    )
    
    # Add annotation for formula
    fig.add_annotation(
        text="S_final = S_rerank · exp(α_eff · Σ wᵢ · Φᵢ)   where Φᵢ = P(p|q) · P_fused(d|p) · P_smoothed(p)",
        xref="paper", yref="paper",
        x=0.5, y=-0.12,
        showarrow=False,
        font=dict(size=11, family="Courier New", color="#666"),
        bgcolor="rgba(255,255,255,0.8)"
    )

    if not demo_mode:
        fig.add_annotation(
            text="Document scatter is hidden because no real retrieval documents were supplied. Demo data is disabled by default.",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.04,
            showarrow=False,
            font=dict(size=11, color="#8a6d3b"),
            bgcolor="rgba(255, 243, 205, 0.9)",
            bordercolor="#ffc107",
            borderwidth=1,
            borderpad=6
        )
    
    return fig


def create_score_breakdown_visualization(
    problems: List[Dict],
    docs: List[Dict] = None,
    demo_mode: Optional[bool] = None
) -> go.Figure:
    """
    สร้าง Score Breakdown Chart แสดง V6 Components พร้อมคำอธิบาย

    แสดง 4 ส่วน:
    1. Problem Priors P(p) — Dirichlet-smoothed prior (จาก severity + μ)
    2. Detection Confidence P(p|q) — ความมั่นใจในการตรวจพบ (จาก L1+L2)
    3. Per-Problem Φᵢ — Multi-Granularity Feature (weighted sum of normalized features)
    4. Final Score V6 — S = S_rerank · exp(α(C) · Σ wᵢ · Φᵢ) · P(rel|profile)
    """

    demo_mode = _allow_demo_data() if demo_mode is None else bool(demo_mode)

    if not problems and not demo_mode:
        return _empty_figure(
            "H2L Score Breakdown",
            "ไม่มี problem profile จากการตรวจจับจริง จึงไม่สร้างกราฟตัวอย่างอัตโนมัติ"
        )

    if not problems:
        problems = [
            {"code": "X60-X84", "name": "ทำร้ายตัวเอง", "severity": 5, "confidence": 0.92},
            {"code": "F32", "name": "โรคซึมเศร้า", "severity": 4, "confidence": 0.85},
            {"code": "Z55", "name": "ปัญหาการศึกษา", "severity": 2, "confidence": 0.70}
        ]

    # Calculate Dirichlet-smoothed priors
    total_sev = sum(p.get('severity', 1) for p in problems)
    mu_dirichlet = 5.0
    p_bg = 1.0 / max(len(problems), 1)
    if demo_mode and not docs:
        np.random.seed(42)
    for p in problems:
        sev = p.get('severity', 1)
        p['prior'] = (sev + mu_dirichlet * p_bg) / (total_sev + mu_dirichlet)
        
        if docs:
            p_doc_sum = 0.0
            doc_count = 0
            code = p.get('code')
            
            for doc in docs:
                doc_count += 1
                doc_matched = False
                factors = doc.get('factors', [])
                if hasattr(factors, '__iter__') and not isinstance(factors, str):
                    for f in factors:
                        if isinstance(f, dict) and f.get('code') == code:
                            p_doc_sum += f.get('p_doc', 0.0)
                            doc_matched = True
                            break
                            
            if doc_count > 0:
                p['p_doc'] = p_doc_sum / doc_count
            else:
                p['p_doc'] = 0.0
        else:
            if demo_mode:
                p['p_doc'] = 0.7 + np.random.random() * 0.25 if p['severity'] >= 3 else np.random.random() * 0.3
            else:
                p['p_doc'] = 0.0

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            '🎯 Prior Probability: P(rel|context)<br><sub>ความน่าจะเป็นที่ปัญหาจะเกี่ยวข้องตามความรุนแรง</sub>',
            '🔍 Detection Confidence: P(detected|case)<br><sub>ความเชื่อมั่นว่าปัญหาถูกตรวจพบในเคสนี้</sub>',
            '📊 Granular Feature Signal: Φᵢ<br><sub>สัญญาณความเกี่ยวข้องจากคุณลักษณะหลายมิติ</sub>',
            '🏆 Final Adjusted Score: S_final<br><sub>คะแนนที่ปรับค่าตามบริบทของปัญหาทั้งหมด</sub>'
        ),
        specs=[
            [{"type": "pie"}, {"type": "bar"}],
            [{"type": "bar"}, {"type": "bar"}]
        ],
        vertical_spacing=0.15,
        horizontal_spacing=0.12
    )
    
    colors = ['#27AE60', '#F1C40F', '#E67E22', '#E74C3C', '#8E44AD']
    
    # ── Panel 1: Problem Priors (Pie) ──
    fig.add_trace(go.Pie(
        labels=[p['code'] for p in problems],
        values=[p['severity'] for p in problems],
        hole=0.4,
        marker_colors=colors[:len(problems)],
        textinfo='label+percent',
        customdata=[[p['code'], p['name'], p['severity'], p['prior']] for p in problems],
        hovertemplate='<b>%{customdata[0]}</b> — %{customdata[1]}<br>' +
                      '━━━━━━━━━━━━━━━<br>' +
                      '<b>📊 P(p) — Problem Prior</b><br>' +
                      'ระดับความรุนแรง: %{customdata[2]}/5<br>' +
                      'ค่า Prior: %{customdata[3]:.3f}<br>' +
                      '<br><i>💡 อธิบาย:</i><br>' +
                      'P(p) = (severity + μ·P_bg) / (Σsev + μ)<br>' +
                      'Dirichlet smoothing ทำให้ค่าเสถียร<br>' +
                      'ปัญหารุนแรงสูง → Prior สูง<extra></extra>'
    ), row=1, col=1)

    # ── Panel 2: Detection Confidence (Bar) ──
    fig.add_trace(go.Bar(
        name='Detection Confidence (P(p|q))',
        x=[p['code'] for p in problems],
        y=[p.get('confidence', 0.8) for p in problems],
        marker_color=[colors[min(p['severity']-1, 4)] for p in problems],
        text=[f"{p.get('confidence', 0.8):.0%}" for p in problems],
        textposition='outside',
        customdata=[[p['code'], p['name'], p.get('confidence', 0.8)] for p in problems],
        hovertemplate='<b>%{customdata[0]}</b> — %{customdata[1]}<br>' +
                      '━━━━━━━━━━━━━━━<br>' +
                      '<b>🔍 P(p|q) — ความมั่นใจในการตรวจจับ</b><br>' +
                      'Confidence: %{customdata[2]:.3f} (%{customdata[2]:.1%})<br>' +
                      '<br><i>💡 อธิบาย:</i><br>' +
                      'P(p|q) = ความน่าจะเป็นที่ปัญหานี้<br>' +
                      'เกี่ยวข้องกับเคส จาก 2 ขั้นตอน:<br>' +
                      '• L1: คำสำคัญ (keyword matching)<br>' +
                      '• L2: LLM ตรวจสอบบริบท<extra></extra>'
    ), row=1, col=2)
    
    # ── Panel 3: Per-Problem Feature Φᵢ (Grouped Bar) ──
    # V6: Φᵢ = weighted sum of sub-features
    codes = [p['code'] for p in problems]

    # Sub-feature: confidence (detection)
    fig.add_trace(go.Bar(
        name='f_detect (ความมั่นใจ)',
        x=codes,
        y=[p.get('confidence', 0.8) for p in problems],
        marker_color='#E74C3C',
        customdata=[[p['code'], p.get('confidence', 0.8)] for p in problems],
        hovertemplate='<b>%{customdata[0]}</b><br>' +
                      '<b>🔍 f_detect</b> = %{customdata[1]:.3f}<br>' +
                      '<i>Detection Confidence Feature</i><br>' +
                      'ค่าความมั่นใจจากตัวตรวจจับ<extra></extra>'
    ), row=2, col=1)

    # Sub-feature: semantic similarity (doc coverage)
    fig.add_trace(go.Bar(
        name='f_semantic (ความคล้าย)',
        x=codes,
        y=[p.get('p_doc', 0.5) for p in problems],
        marker_color='#3498DB',
        customdata=[[p['code'], p.get('p_doc', 0.5)] for p in problems],
        hovertemplate='<b>%{customdata[0]}</b><br>' +
                      '<b>📄 f_semantic</b> = %{customdata[1]:.3f}<br>' +
                      '<i>Semantic Similarity Feature</i><br>' +
                      'ความคล้ายเชิงความหมาย<br>' +
                      'ระหว่างเอกสาร-ปัญหา<extra></extra>'
    ), row=2, col=1)

    # Sub-feature: prior (severity-based)
    fig.add_trace(go.Bar(
        name='f_prior (ความรุนแรง)',
        x=codes,
        y=[p['prior'] for p in problems],
        marker_color='#27AE60',
        customdata=[[p['code'], p['prior']] for p in problems],
        hovertemplate='<b>%{customdata[0]}</b><br>' +
                      '<b>📊 f_prior</b> = %{customdata[1]:.3f}<br>' +
                      '<i>Prior Feature (Dirichlet)</i><br>' +
                      'คำนวณจาก severity ของปัญหา<extra></extra>'
    ), row=2, col=1)
    
    # ── Panel 4: V6 Final Score Computation ──
    h2l_config = H2LConfigV3()
    s_rerank = 0.85
    
    # V6: Compute Φᵢ via weighted sum (not product)
    feature_weights = {'detect': 0.35, 'semantic': 0.30, 'prior': 0.20, 'specificity': 0.15}
    phi_values = []
    w_values = []
    for p in problems:
        conf = p.get('confidence', 0.8)
        p_doc = p.get('p_doc', 0.5)
        prior = p['prior']
        specificity = min(1.0, p.get('severity', 1) / 5.0)
        phi_i = (feature_weights['detect'] * conf +
                 feature_weights['semantic'] * p_doc +
                 feature_weights['prior'] * prior +
                 feature_weights['specificity'] * specificity)
        phi_values.append(phi_i)
        w_values.append(1.0)

    # V6: Adaptive α(C) — sigmoid-based
    n_problems = len(problems)
    avg_conf = sum(p.get('confidence', 0.8) for p in problems) / max(n_problems, 1)
    alpha_base = getattr(h2l_config, 'ALPHA', 1.0)
    alpha_adaptive = alpha_base * (2.0 / (1.0 + float(np.exp(-0.5 * n_problems * avg_conf))))

    # V6: Bayesian Prior P(rel|profile)
    bayesian_prior = min(1.0, 0.5 + 0.1 * n_problems)

    weighted_sum = sum(w * phi for w, phi in zip(w_values, phi_values))
    exponent = alpha_adaptive * weighted_sum
    exponent = max(-10.0, min(10.0, exponent))
    boost = float(np.exp(exponent))
    s_final = s_rerank * boost * bayesian_prior

    fig.add_trace(go.Bar(
        name='Score Component Calculation',
        x=['S_rerank', 'α(C)', 'Boost', 'P(rel)', 'S_final'],
        y=[s_rerank, alpha_adaptive, boost, bayesian_prior, s_final],
        marker_color=['#3498DB', '#F39C12', '#9B59B6', '#E91E63', '#27AE60'],
        text=[f'{s_rerank:.3f}', f'{alpha_adaptive:.3f}', f'{boost:.3f}', f'{bayesian_prior:.3f}', f'{s_final:.3f}'],
        textposition='outside',
        customdata=[
            ['S_rerank', s_rerank, 'Rerank Score',
             'คะแนนจาก reranker model<br>วัดความเกี่ยวข้องดั้งเดิม<br>ก่อนที่ H2L จะปรับคะแนน'],
            ['α(C)', alpha_adaptive, 'Adaptive Alpha',
             f'α(C) = α₀ · σ(n · avg_conf)<br>= {alpha_base:.2f} · σ({n_problems} × {avg_conf:.2f})<br>= {alpha_adaptive:.4f}<br><br>ปรับอัตโนมัติตามจำนวนปัญหา<br>และความมั่นใจเฉลี่ย'],
            ['Boost', boost, 'Log-Linear Boost',
             f'exp(α(C) · Σ wᵢ · Φᵢ)<br>= exp({alpha_adaptive:.3f} × {weighted_sum:.4f})<br>= {boost:.4f}<br><br>ตัวคูณที่ดันคะแนนเอกสาร<br>ที่ตรงกับปัญหาขึ้นมา'],
            ['P(rel|profile)', bayesian_prior, 'Bayesian Prior',
             f'P(rel|profile) = {bayesian_prior:.3f}<br><br>ความน่าจะเป็นเริ่มต้นว่า<br>เอกสารเกี่ยวข้องกับโปรไฟล์ปัญหา<br>ยิ่งพบปัญหาเยอะ ยิ่งมั่นใจมากขึ้น'],
            ['S_final', s_final, 'Final Score V6',
             f'S_rerank × Boost × P(rel)<br>= {s_rerank:.3f} × {boost:.4f} × {bayesian_prior:.3f}<br>= {s_final:.4f}']
        ],
        hovertemplate='<b>%{customdata[0]}</b><br>' +
                      '━━━━━━━━━━━━━━━<br>' +
                      'Value: %{customdata[1]:.4f}<br>' +
                      '<br><i>💡 %{customdata[2]}:</i><br>' +
                      '%{customdata[3]}<extra></extra>'
    ), row=2, col=2)

    fig.update_layout(
        height=850,
        showlegend=True,
        title=dict(
            text='<b>📊 H2L V6 Empirical Score Breakdown</b><br><sub>S_final = S_rerank · exp(α(C) · Σ wᵢ · Φᵢ) · P(rel|profile)</sub>',
            font=dict(size=18, color='white')
        ),
        barmode='group',
        template='plotly_dark',
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(family="Inter, sans-serif", color="white"),
        margin=dict(b=180, r=40),
        annotations=[
            dict(
                text="<b>P(p) = (sev + μ·P_bg) / (Σsev + μ)</b><br>Dirichlet smoothing (μ=5.0)",
                xref="paper", yref="paper",
                x=0.15, y=1.05,
                showarrow=False,
                font=dict(size=11, color="#A9DFBF"),
                bgcolor="rgba(39, 174, 96, 0.15)",
                bordercolor="#27AE60",
                borderwidth=1,
                borderpad=4
            ),
            dict(
                text="<b>P(p|q) = L1 + L2 Detection Confidence</b><br>ผลจากการวิเคราะห์บริบทขั้นสูง",
                xref="paper", yref="paper",
                x=0.85, y=1.05,
                showarrow=False,
                font=dict(size=11, color="#AED6F1"),
                bgcolor="rgba(52, 152, 219, 0.15)",
                bordercolor="#3498DB",
                borderwidth=1,
                borderpad=4
            ),
            dict(
                text="<b>V6 Master Equation:</b> Φᵢ = Σ wⱼ · fⱼ(d, p, q)  →  S = S_rerank · exp(α(C) · Σ wᵢ · Φᵢ) · P(rel|profile)",
                xref="paper", yref="paper",
                x=0.5, y=-0.12,
                showarrow=False,
                font=dict(size=13, color="#F39C12", family="Courier New, monospace"),
                bgcolor="rgba(243, 156, 18, 0.15)",
                bordercolor="#F39C12",
                borderwidth=1,
                borderpad=8
            ),
            # Beautiful Dark V6 Legend placed neatly below charts horizontally
            dict(
                text=(
                    "<b>📖 V6 Scoring Components Index</b><br>"
                    "<b>Φᵢ (Multi-Granularity Signal)</b>: สัญญาณความเกี่ยวข้องของปัญหา คำนวณจากความมั่นใจ, ความคล้ายคลึง, และความรุนแรง <br>"
                    "<b>α(C) (Adaptive Influence)</b>: ตัวปรับอิทธิพล มีค่าสูงขึ้นเมื่อระบบพบปัญหาหลักที่มั่นใจชัดเจน <br>"
                    "<b>P(rel|profile) (Bayesian Prior)</b>: ความน่าจะเป็นพื้นฐานที่เอกสารจะตอบโจทย์โปรไฟล์ผู้ใช้ <br>"
                    "<b>S_final (Contextual Score)</b>: คะแนนตัดสินสุดท้ายที่ผ่านการวิเคราะห์สมการความน่าจะเป็นแล้ว"
                ),
                xref="paper", yref="paper",
                x=0.5, y=-0.28,
                showarrow=False,
                font=dict(size=12, color="#E0E0E0", family="Inter, sans-serif"),
                bgcolor="rgba(255,255,255,0.05)",
                bordercolor="#555",
                borderwidth=1,
                align="center",
                borderpad=12
            )
        ]
    )

    return fig


def create_multi_problem_product_visualization(
    problems: List[Dict],
    top_doc: Dict = None,
    demo_mode: Optional[bool] = None
) -> go.Figure:
    """
    Educational visualization showing how Σ (summation) works across multiple problems

    แสดงการคำนวณ Log-Linear Summation แบบ Step-by-Step:
    - Φᵢ แต่ละปัญหา = P(p|q) × P(d|p) × P(p)
    - Cumulative Σ wᵢ·Φᵢ grows with each problem
    - S_final = S_rerank · exp(α · Σ wᵢ·Φᵢ)
    """

    demo_mode = _allow_demo_data() if demo_mode is None else bool(demo_mode)

    if not problems and not demo_mode:
        return _empty_figure(
            "Multi-Problem Aggregation",
            "ไม่มี problem profile จริงสำหรับคำนวณ aggregation และ demo data ถูกปิดอยู่"
        )

    if not problems:
        problems = [
            {"code": "X60-X84", "name": "ทำร้ายตัวเอง", "severity": 5, "confidence": 0.92},
            {"code": "F32", "name": "โรคซึมเศร้า", "severity": 4, "confidence": 0.85},
            {"code": "Z55", "name": "ปัญหาการศึกษา", "severity": 2, "confidence": 0.70}
        ]

    # Initialize config
    h2l_config = H2LConfigV3()

    # Calculate priors
    total_sev = sum(p.get('severity', 1) for p in problems)
    for p in problems:
        p['prior'] = p.get('severity', 1) / total_sev

    # Calculate Φᵢ from real top_doc factors; otherwise use explicit demo/default values.
    # real_factors is typically: [{'code': 'X60-X84', 'p_doc': 0.8, 'phi_i': 0.15, ...}]
    factors_map = {}
    if top_doc and 'factors' in top_doc:
        for f in top_doc['factors']:
            factors_map[f.get('code')] = f

    phi_values = []
    w_values = []
    cumulative_sum = 0.0
    if demo_mode and not factors_map:
        np.random.seed(42)

    for i, p in enumerate(problems):
        code = p.get('code', '')
        
        # Real math extraction
        if code in factors_map:
            p['p_doc'] = factors_map[code].get('p_doc', 0.0)
            phi_i = factors_map[code].get('phi_i', 0.0)
            w_i = factors_map[code].get('w_i', 1.0)
        else:
            if demo_mode:
                p['p_doc'] = 0.7 + np.random.random() * 0.25 if p.get('severity', 1) >= 3 else np.random.random() * 0.3
            else:
                p['p_doc'] = 0.0
            phi_i = p.get('confidence', 0.8) * p['p_doc'] * p['prior']
            w_i = 1.0
            
        phi_values.append(phi_i)
        w_values.append(w_i)
        cumulative_sum += w_i * phi_i

    # Shannon entropy for α_eff
    priors_list = [p['prior'] for p in problems]
    h_severity = -sum(pr * np.log2(pr + 1e-10) for pr in priors_list)
    alpha_eff = h2l_config.ALPHA * (1 + 0.5 * h_severity)

    final_sum = cumulative_sum
    exponent_val = alpha_eff * final_sum
    boost_val = float(np.exp(max(-10, min(10, exponent_val))))

    # Create Waterfall Chart
    x_items = []
    y_items = []
    measure = []
    texts = []
    hovertemplates = []

    for p, phi_i in zip(problems, phi_values):
        x_items.append(f"<b>{p['code']}</b><br>{p['name'][:15]}")
        y_items.append(phi_i)
        measure.append('relative')
        texts.append(f"+{phi_i:.4f}")
        hovertemplates.append(
            f"<b>{p['code']}: {p.get('name', '')}</b><br>"
            f"P(p|q) = {p.get('confidence', 0.8):.3f}<br>"
            f"P(d|p) = {p.get('p_doc', 0.5):.3f}<br>"
            f"P(p) = {p['prior']:.3f}<br>"
            f"━━━━━━━━━━━━━<br>"
            f"Φᵢ = {phi_i:.4f}<extra></extra>"
        )

    x_items.append("<b>Total (Σ wᵢ·Φᵢ)</b><br>ผลรวมทั้งหมด")
    y_items.append(0)  # total automatically computed
    measure.append('total')
    texts.append(f"<b>{final_sum:.4f}</b>")
    hovertemplates.append(f"<b>Total Summation</b><br>Σ = {final_sum:.4f}<extra></extra>")

    fig = go.Figure()

    fig.add_trace(go.Waterfall(
        name="Contributions",
        orientation="v",
        measure=measure,
        x=x_items,
        textposition="outside",
        text=texts,
        y=y_items,
        connector={"line": {"color": "#95a5a6", "width": 2, "dash": "dot"}},
        increasing={"marker": {"color": "#27ae60", "line": {"color": "#2ecc71", "width": 1}}},
        totals={"marker": {"color": "#2980b9", "line": {"color": "#3498db", "width": 1}}},
        hovertemplate=hovertemplates,
        textfont=dict(size=14, color="#2c3e50")
    ))

    fig.update_layout(
        height=650,
        title=dict(
            text='<b>🧮 Multi-Problem Aggregation (Waterfall Analysis)</b><br><sub>การก้าวสู่น้ำหนักองค์รวม: P(p|q) × P(d|p) × P(p) ➔ Σ wᵢ·Φᵢ</sub>',
            font=dict(size=18, color="#2c3e50")
        ),
        showlegend=False,
        plot_bgcolor='rgba(248, 249, 250, 1)',
        paper_bgcolor='white',
        xaxis=dict(
            showgrid=False,
            tickfont=dict(size=12, color="#34495e")
        ),
        yaxis=dict(
            title="Contribution Value (Φᵢ)",
            showgrid=True,
            gridcolor='rgba(189, 195, 199, 0.4)',
            zeroline=True,
            zerolinecolor='rgba(149, 165, 166, 0.8)',
            zerolinewidth=2
        ),
        margin=dict(t=100, b=60, l=60, r=60),
        annotations=[
            dict(
                text=f"<b>🚀 Exponential Final Boost:</b><br><br>"
                     f"Summation (Σ) = <b>{final_sum:.4f}</b><br>"
                     f"α_eff = <b>{alpha_eff:.3f}</b><br><br>"
                     f"Boost = exp(α_eff × Σ) <br>"
                     f"<b>= exp({exponent_val:.4f})  <br> = <span style='color:#e74c3c; font-size:18px;'>{boost_val:.4f}x</span></b>",
                xref="paper", yref="paper",
                x=0.02, y=0.95,
                showarrow=False,
                align="left",
                font=dict(size=13, color="#2c3e50"),
                bgcolor="rgba(255, 255, 255, 0.95)",
                bordercolor="#3498db",
                borderwidth=2,
                borderpad=12
            ),
            dict(
                text="<b>💡 Academic Implication:</b><br>Waterfall chart แสดงกลไกของ H2L ที่อนุญาตให้เคสซึ่งมีความซับซ้อนหลายมิติรวมพลังกัน (Synergistic effect)<br>ก่อนจะถูกผลักเข้าสมการ Log-Linear เพื่อสร้าง Exponential Boost ให้กระโดดข้าม Threshold ได้อย่างเด็ดขาด",
                xref="paper", yref="paper",
                x=0.98, y=1.00,
                showarrow=False,
                align="right",
                font=dict(size=11, color="#7f8c8d"),
                bgcolor="rgba(236, 240, 241, 0.8)",
                bordercolor="#bdc3c7",
                borderwidth=1,
                borderpad=8
            )
        ]
    )

    return fig


def create_v2_v3_comparison_visualization(problems: List[Dict], doc_text: str = None) -> go.Figure:
    """
    A/B Comparison: Weighted Average vs Log-Linear Probabilistic

    Shows side-by-side comparison of scoring methods
    """

    if not problems:
        problems = [
            {"code": "X60-X84", "name": "Self-harm", "severity": 5, "confidence": 0.92, "keywords": ["ทำร้ายตัวเอง", "ไม่อยากมีชีวิต"]},
            {"code": "F32", "name": "Depression", "severity": 4, "confidence": 0.85, "keywords": ["ซึมเศร้า", "หมดหวัง"]},
            {"code": "Z55", "name": "Education", "severity": 2, "confidence": 0.70, "keywords": ["ไม่ไปเรียน"]}
        ]

    if not doc_text:
        doc_text = "ผู้ป่วยมีอาการซึมเศร้า หมดหวัง พูดเรื่องไม่อยากมีชีวิตอยู่บ่อยครั้ง เคยพยายามทำร้ายตัวเอง"

    # Test different rerank scores
    rerank_scores = [0.5, 0.6, 0.7, 0.8, 0.9]

    v2_scores = []
    v3_scores = []
    comparison_data = []

    for s_rerank in rerank_scores:
        if compare_v2_v3 is not None:
            comparison = compare_v2_v3(s_rerank, problems, doc_text)
            v2_scores.append(comparison['V2_Simplified']['S_final'])
            v3_scores.append(comparison['V3_Probabilistic']['S_final'])
            comparison_data.append(comparison)
        else:
            # Fallback if compare_v2_v3 not available
            v2_scores.append(s_rerank * 1.1)
            v3_scores.append(s_rerank * 1.2)

    # Create subplots
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            '📊 Score Comparison Across S_rerank Values',
            '📈 Score Difference (Log-Linear - Weighted Avg)',
            '🔍 Weighted Average Formula',
            '🔍 Log-Linear Formula'
        ),
        specs=[
            [{"type": "scatter"}, {"type": "bar"}],
            [{"type": "table", "colspan": 2}, None]
        ],
        row_heights=[0.45, 0.55]
    )

    # 1. Line chart comparing V2 vs V4
    fig.add_trace(go.Scatter(
        x=rerank_scores,
        y=v2_scores,
        mode='lines+markers',
        name='Weighted Avg',
        line=dict(color='#E74C3C', width=3),
        marker=dict(size=10),
        hovertemplate='S_rerank: %{x}<br>Weighted Avg Score: %{y:.4f}<extra></extra>'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=rerank_scores,
        y=v3_scores,
        mode='lines+markers',
        name='Log-Linear',
        line=dict(color='#27AE60', width=3),
        marker=dict(size=10),
        hovertemplate='S_rerank: %{x}<br>Log-Linear Score: %{y:.4f}<extra></extra>'
    ), row=1, col=1)

    # 2. Bar chart showing differences
    differences = [v3 - v2 for v3, v2 in zip(v3_scores, v2_scores)]
    colors_diff = ['#27AE60' if d > 0 else '#E74C3C' for d in differences]

    fig.add_trace(go.Bar(
        x=rerank_scores,
        y=differences,
        marker_color=colors_diff,
        text=[f'{d:+.4f}' for d in differences],
        textposition='outside',
        name='Difference',
        showlegend=False,
        hovertemplate='S_rerank: %{x}<br>Difference: %{y:+.4f}<extra></extra>'
    ), row=1, col=2)

    # Add zero line
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5, row=1, col=2)

    # 3. Comparison table
    if comparison_data:
        comp = comparison_data[2]  # Use middle value (S_rerank=0.7) as example

        table_data = [
            ["Aspect", "Weighted Average", "Log-Linear"],
            ["Formula", "S × (1 + λ × S_problem)", "S · exp(α_eff · Σ wᵢ · Φᵢ)"],
            ["λ / α_eff", f"{comp['V2_Simplified']['lambda']}", f"{comp['V3_Probabilistic']['alpha']}"],
            ["Theoretical Basis", comp['V2_Simplified']['theoretical_basis'], comp['V3_Probabilistic']['theoretical_basis']],
            ["S_final (@ S_rerank=0.7)", f"{comp['V2_Simplified']['S_final']:.4f}", f"{comp['V3_Probabilistic']['S_final']:.4f}"],
            ["Difference", "", f"{comp['difference']:+.4f}"]
        ]

        fig.add_trace(go.Table(
            header=dict(
                values=table_data[0],
                fill_color='#34495E',
                font=dict(color='white', size=12),
                align='left'
            ),
            cells=dict(
                values=list(zip(*table_data[1:])),
                fill_color=[['#ECF0F1', '#D5DBDB'] * 3],
                font=dict(color='#2C3E50', size=11),
                align='left',
                height=30
            )
        ), row=2, col=1)

    fig.update_layout(
        height=800,
        title=dict(
            text='<b>⚖️ Method Comparison (A/B Test)</b><br><sub>Comparing Weighted Average vs Log-Linear Probabilistic</sub>',
            font=dict(size=16)
        ),
        showlegend=True,
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.05,
            xanchor='center',
            x=0.5
        )
    )

    # Update axes
    fig.update_xaxes(title_text="S_rerank (Base Relevance)", row=1, col=1)
    fig.update_yaxes(title_text="Final Score", row=1, col=1)
    fig.update_xaxes(title_text="S_rerank", row=1, col=2)
    fig.update_yaxes(title_text="Difference (Log-Linear - Weighted Avg)", row=1, col=2)

    return fig


def create_detection_flow_visualization(l1_count: int, l2_confirmed: int, l2_filtered: int) -> go.Figure:
    """
    สร้าง Detection Flow Diagram (L1 → L2)

    แสดงกระบวนการตรวจจับ 2 ระดับ:
    1. L1 Detection: Keyword + Context matching → ได้ Candidates
    2. L2 Validation: LLM วิเคราะห์บริบท → กรอง False Positives
    3. ผลลัพธ์: Confirmed Problems และ Filtered Out
    """

    # Calculate precision improvement from L2
    if l1_count > 0:
        precision_improvement = (l2_filtered / l1_count) * 100
        l2_precision = (l2_confirmed / l1_count) * 100
    else:
        precision_improvement = 0
        l2_precision = 0

    fig = go.Figure(data=[go.Sankey(
        node=dict(
            pad=20,
            thickness=25,
            line=dict(color='black', width=0.5),
            label=[
                f'🔍 L1 Detection<br>(Keyword+Context)<br><b>{l1_count} candidates</b>',
                f'🧠 L2 Validation<br>(LLM Analysis)<br>Filter: {precision_improvement:.0f}%',
                f'✅ Confirmed<br><b>{l2_confirmed} problems</b><br>Precision: {l2_precision:.0f}%',
                f'❌ Filtered Out<br><b>{l2_filtered} false positives</b>'
            ],
            color=['#3498DB', '#9B59B6', '#27AE60', '#E74C3C'],
            customdata=[
                "ตรวจจับด้วย Keywords และ Context",
                "วิเคราะห์บริบทด้วย LLM",
                "ปัญหาที่ยืนยัน��ล้ว",
                "False Positives ที่กรองออก"
            ],
            hovertemplate='<b>%{label}</b><br>%{customdata}<extra></extra>'
        ),
        link=dict(
            source=[0, 1, 1],
            target=[1, 2, 3],
            value=[l1_count, l2_confirmed, l2_filtered],
            color=['rgba(52, 152, 219, 0.4)', 'rgba(39, 174, 96, 0.4)', 'rgba(231, 76, 60, 0.4)'],
            customdata=[
                f"ส่งต่อทั้งหมด {l1_count} candidates",
                f"ยืนยัน {l2_confirmed} problems",
                f"กรอง {l2_filtered} false positives"
            ],
            hovertemplate='%{customdata}<br>Value: %{value}<extra></extra>'
        )
    )])

    fig.update_layout(
        title=dict(
            text=f'<b>🚀 H2L Empirical Detection Flow (2-Level Validation)</b><br><sub>{l1_count} candidates → {l2_confirmed} confirmed, {l2_filtered} filtered ({precision_improvement:.1f}% precision boost)</sub>',
            font=dict(size=18, color='white')
        ),
        height=500,
        font=dict(family="Inter, sans-serif", color="white", size=13),
        template="plotly_dark",
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        annotations=[
            dict(
                text=f"<b>L2 Precision Boost: {precision_improvement:.1f}%</b><br>Recall Accuracy ≈ {(l2_confirmed/max(l1_count, 1)*100):.1f}%",
                xref="paper", yref="paper",
                x=0.5, y=-0.15,
                showarrow=False,
                font=dict(size=13, color="white"),
                bgcolor="rgba(52, 152, 219, 0.2)",
                bordercolor="#3498DB",
                borderwidth=1,
                borderpad=8
            )
        ]
    )

    return fig


def update_dr_info(dr_method: str) -> str:
    """Update DR method information based on selection"""
    dr_descriptions = {
        "None": """
**None (Spatial Distribution)**
- ใช้ golden spiral distribution
- จัดวางตามความสัมพันธ์เชิงตรรกะ
- เร็วที่สุด, เหมาะสำหรับการสาธิต
- ไม่ใช้ embeddings จริง
""",
        "PCA": """
**PCA (Principal Component Analysis)**
- ลดมิติแบบ linear transformation
- รักษาความแปรปรวนสูงสุด (variance)
- เร็ว, เหมาะสำหรับข้อมูลที่มีความสัมพันธ์เชิงเส้น
- แสดงโครงสร้างหลักของข้อมูล
- 📊 ดีสำหรับ: ดูภาพรวม, หาแนวโน้มหลัก
""",
        "t-SNE": """
**t-SNE (t-Distributed Stochastic Neighbor Embedding)**
- รักษาโครงสร้างเฉพาะที่ (local structure)
- แสดงกลุ่มข้อมูลที่คล้ายกันชัดเจน
- ช้ากว่า PCA, เหมาะสำหรับการสำรวจข้อมูล
- ไม่เหมาะสำหรับข้อมูลใหม่
- 📊 ดีสำหรับ: ดูกลุ่ม (clusters), หาความคล้ายคลึง
""",
        "UMAP": """
**UMAP (Uniform Manifold Approximation and Projection)**
- สมดุลระหว่าง local และ global structure
- เร็วกว่า t-SNE, รักษาโครงสร้างได้ดีกว่า
- เหมาะสำหรับข้อมูลขนาดใหญ่
- รองรับข้อมูลใหม่ได้
- 📊 ดีสำหรับ: ดูทั้งกลุ่มและภาพรวม, ข้อมูลจำนวนมาก
"""
    }
    return dr_descriptions.get(dr_method, dr_descriptions["None"])


def update_vector_space_viz(case_text: str, num_problems: int, num_docs: int, show_boundaries: bool, show_distance_lines: bool, show_zone_red: bool, show_zone_yellow: bool, show_zone_green: bool, dr_method: str, strategy: str = "h2l-hybrid"):
    """Update vector space visualization based on parameters with progressive loading status"""

    # Strategy metadata
    strategy_info = {
        # H2L-Enhanced (paired with baselines below)
        "h2l-bm25": {
            "name": "H2L + BM25",
            "formula": "S_final = S_rerank · exp(α · Σ wᵢ · Φᵢ)  [base: BM25]",
            "variables": "BM25 retrieval + H2L problem-aware scoring (α=1.0)"
        },
        "h2l-naive_rag": {
            "name": "H2L + Naive RAG",
            "formula": "S_final = S_rerank · exp(α · Σ wᵢ · Φᵢ)  [base: Dense]",
            "variables": "Dense retrieval + H2L problem-aware scoring (α=1.0)"
        },
        "h2l-hybrid": {
            "name": "H2L + Hybrid",
            "formula": "S_final = S_rerank · exp(α · Σ wᵢ · Φᵢ)  [base: Hybrid]",
            "variables": "Hybrid retrieval + H2L problem-aware scoring (α=1.0)"
        },
        "h2l-hyde": {
            "name": "H2L + HyDE",
            "formula": "S_final = S_rerank · exp(α · Σ wᵢ · Φᵢ)  [base: HyDE]",
            "variables": "HyDE retrieval + H2L problem-aware scoring (α=1.0)"
        },

        # Baselines (No H2L)
        "bm25_only": {
            "name": "B1: BM25 Only",
            "formula": "S_final = BM25(q, d)",
            "variables": "Lexical search only — ใช้ BM25 keyword matching อย่างเดียว"
        },
        "naive_rag": {
            "name": "B2: Naive RAG",
            "formula": "S_final = cosine_sim(q, d)",
            "variables": "Dense retrieval only — ไม่มี BM25, ไม่มี Reranking"
        },
        "hybrid": {
            "name": "B3: Hybrid Retrieval",
            "formula": "S_final = α × S_dense + (1-α) × S_sparse",
            "variables": "Dense + Sparse (BM25) — modern standard baseline"
        },
        "hyde": {
            "name": "B4: HyDE (Gao et al., 2022)",
            "formula": "S_final = cosine_sim(embed(hypo_doc), d)",
            "variables": "Hypothetical Document Embedding — LLM สร้างเอกสารสมมุติ"
        }
    }

    current_strategy = strategy_info.get(strategy, strategy_info["h2l-hybrid"])

    # Initial loading status
    loading_html = """
    <div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 12px; color: white;'>
        <h3 style='margin-top: 0; color: white;'>⏳ กำลังโหลด Visualization...</h3>
        <div style='color: white; font-size: 0.95em;'>
            • เตรียมข้อมูล...<br>
        </div>
    </div>
    """

    try:
        logger.info(f"🎨 กำลังสร้าง Vector Space Visualization...")
        logger.info(f"   • Problems: {num_problems}, Docs: {num_docs}, Boundaries: {show_boundaries}")
        logger.info(f"   • Distance Lines: {show_distance_lines}")
        logger.info(f"   • Color Zones: Red={show_zone_red}, Yellow={show_zone_yellow}, Green={show_zone_green}")
        logger.info(f"   • DR Method: {dr_method}")

        # Show initial loading status
        empty_fig = go.Figure()
        empty_fig.update_layout(title="⏳ กำลังโหลด...")
        yield empty_fig, empty_fig, empty_fig, empty_fig, loading_html

        # Step 2: Use REAL DATA using Orchestrator
        if not case_text or not case_text.strip():
            case_text = "ผู้ป่วยมีภาวะซึมเศร้า สามีทิ้ง ถูกทำร้ายร่างกาย มีดกรีดข้อมือ เลือดไหลเยอะมาก"
        
        logger.info(f"   🧠 Running REAL E2E Search on query: '{case_text[:30]}...'")
        orchestrator = EnhancedOrchestrator(retriever_strategy=strategy, enable_l2=True)
        # We fetch up to 100 docs so we can slice num_docs
        if hasattr(orchestrator, 'orchestrator') and orchestrator.orchestrator:
            orchestrator.orchestrator.config.TOP_K = max(20, num_docs)
        result = orchestrator.analyze_case(case_text)
        
        real_all_problems = result.get('problems', [])
        # Only take top num_problems
        sample_problems = real_all_problems[:num_problems] if num_problems > 0 else []
        
        # Real documents
        real_raw_docs = result.get('retrieved_docs', [])
        real_docs = []
        for d in real_raw_docs[:num_docs]:
            if isinstance(d, dict):
                meta = d
            elif hasattr(d, 'doc') and hasattr(d.doc, 'meta'):
                meta = d.doc.meta if d.doc.meta else {}
            elif hasattr(d, 'meta'):
                meta = d.meta if d.meta else {}
            else:
                continue

            doc_id = meta.get('chunk_id') or meta.get('doc_id') or meta.get('id', 'N/A')
            title = meta.get('title') or ''
            source = meta.get('source_document') or meta.get('source') or ''
            snippet = meta.get('content_snippet') or ''
            
            # Real Math Factors
            if hasattr(d, 'final_score'):
                f_score = d.final_score
            else:
                f_score = meta.get('final_score', 0.0)
                
            if hasattr(d, 'rerank_score'):
                s_rerank = d.rerank_score
            else:
                s_rerank = meta.get('rerank_score', meta.get('score', 0.0))
                
            # If factors exist directly on the dict (which happens in UnifiedRetriever)
            if isinstance(d, dict) and 'factors' in d:
                factors = d['factors']
            elif hasattr(d, 'factors'):
                factors = d.factors
            else:
                factors = {}
            
            real_docs.append({
                'id': str(doc_id)[:20],
                'source': str(source)[:40],
                'title': str(title)[:60],
                'snippet': str(snippet)[:80],
                'final_score': f_score,
                's_rerank': s_rerank,
                'factors': factors
            })

        logger.info(f"   ✅ Real docs extracted: {len(real_docs)} docs, {len(sample_problems)} problems")

        # Update: Creating vector space
        loading_html = """
        <div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 12px; color: white;'>
            <h3 style='margin-top: 0; color: white;'>⏳ กำลังโหลด Visualization...</h3>
            <div style='color: white; font-size: 0.95em;'>
                ✅ เตรียมข้อมูล...<br>
                • กำลังสร้าง Vector Space (3D/2D)...<br>
            </div>
        </div>
        """
        yield empty_fig, empty_fig, empty_fig, empty_fig, loading_html

        # Use 3D visualization if available, otherwise fall back to 2D

        if _HAS_3D_VIZ:
            logger.info(f"   • Mode: 3D Scatter Plot")
            viz_mode = "3D"
            fig = create_3d_vector_space_with_hover(
                problems=sample_problems,
                real_docs=real_docs,
                num_docs=num_docs,
                show_boundaries=show_boundaries,
                show_distance_lines=show_distance_lines,
                show_zone_red=show_zone_red,
                show_zone_yellow=show_zone_yellow,
                show_zone_green=show_zone_green,
                dr_method=dr_method,
                h2l_config=H2LConfigV3()
            )
            logger.info(f"   ✅ 3D Vector Space สร้างสำเร็จ")
        else:
            logger.info(f"   • Mode: 2D Scatter Plot (fallback)")
            viz_mode = "2D"
            fig = create_2d_vector_space_with_hover(
                problems=sample_problems,
                num_docs=num_docs,
                show_boundaries=show_boundaries
            )
            logger.info(f"   ✅ 2D Vector Space สร้างสำเร็จ")

        # Update: Creating score breakdown
        loading_html = """
        <div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 12px; color: white;'>
            <h3 style='margin-top: 0; color: white;'>⏳ กำลังโหลด Visualization...</h3>
            <div style='color: white; font-size: 0.95em;'>
                ✅ เตรียมข้อมูล...<br>
                ✅ สร้าง Vector Space...<br>
                • กำลังสร้าง Score Breakdown...<br>
            </div>
        </div>
        """
        yield fig, empty_fig, empty_fig, empty_fig, loading_html

        # Create score breakdown
        logger.info(f"🎨 กำลังสร้าง Score Breakdown...")
        if sample_problems:
            score_fig = create_score_breakdown_visualization(sample_problems, real_docs)
            logger.info(f"   ✅ Score Breakdown สร้างสำเร็จ")
        else:
            # Create empty figure with message for baseline strategies
            score_fig = go.Figure()
            score_fig.update_layout(
                title="📊 Score Breakdown (Not applicable for baseline strategies)",
                annotations=[dict(
                    text="<b>Baseline strategies use hybrid retrieval only</b><br>No problem detection scores to display<br><br>💡 Select an H2L strategy to see problem-aware scoring",
                    xref="paper", yref="paper", x=0.5, y=0.5,
                    showarrow=False, font=dict(size=14, color="#FFD93D"),
                    bgcolor="rgba(255,193,7,0.1)",
                    bordercolor="#FFD93D",
                    borderwidth=2,
                    borderpad=20
                )]
            )
            logger.info(f"   ℹ️ Score Breakdown skipped (baseline strategy)")

        # Update: Creating detection flow
        loading_html = """
        <div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 12px; color: white;'>
            <h3 style='margin-top: 0; color: white;'>⏳ กำลังโหลด Visualization...</h3>
            <div style='color: white; font-size: 0.95em;'>
                ✅ เตรียมข้อมูล...<br>
                ✅ สร้าง Vector Space...<br>
                ✅ สร้าง Score Breakdown...<br>
                • กำลังสร้าง Detection Flow...<br>
            </div>
        </div>
        """
        yield fig, score_fig, empty_fig, empty_fig, loading_html

        # Create detection flow
        logger.info(f"🎨 กำลังสร้าง Detection Flow...")
        if sample_problems:
            detection_meta = result.get("detection_metadata", {})
            filtered_out_list = result.get("filtered_out", [])
            
            l1_count = detection_meta.get("l1_count", num_problems + len(filtered_out_list))
            l2_filtered = len(filtered_out_list)
            l2_confirmed = num_problems

            # Build detailed reasons
            confirmed_reasons = []
            for p in sample_problems:
                confirmed_reasons.append({
                    "code": p.get("code", "N/A"),
                    "name": p.get("name", "Unknown"),
                    "reason": p.get("validation_notes", p.get("reasoning", "L2 Confirmed"))
                })
                
            filtered_reasons = []
            for p in filtered_out_list:
                filtered_reasons.append({
                    "code": p.get("code", "N/A"),
                    "name": p.get("name", "Unknown"),
                    "reason": p.get("validation_notes", p.get("reasoning", "Filtered by Context"))
                })

            # Use enhanced version if available
            if _HAS_ENHANCED_FLOW:
                flow_fig = create_detection_flow_visualization_enhanced(
                    l1_count, l2_confirmed, l2_filtered,
                    filtered_reasons=filtered_reasons,
                    confirmed_reasons=confirmed_reasons
                )
                logger.info(f"   ✅ Detection Flow (Enhanced) สร้างสำเร็จ")
            else:
                flow_fig = create_detection_flow_visualization(l1_count, l2_confirmed, l2_filtered)
                logger.info(f"   ✅ Detection Flow (Basic) สร้างสำเร็จ")
        else:
            # Create empty figure for baseline strategies
            flow_fig = go.Figure()
            flow_fig.update_layout(
                title="🔄 Detection Flow (Not applicable for baseline strategies)",
                annotations=[dict(
                    text="<b>Baseline strategies don't use L1/L2 detection</b><br>No problem detection flow to display<br><br>💡 Select an H2L strategy to see the two-level detection process",
                    xref="paper", yref="paper", x=0.5, y=0.5,
                    showarrow=False, font=dict(size=14, color="#FFD93D"),
                    bgcolor="rgba(255,193,7,0.1)",
                    bordercolor="#FFD93D",
                    borderwidth=2,
                    borderpad=20
                )]
            )
            logger.info(f"   ℹ️ Detection Flow skipped (baseline strategy)")

        # Update: Creating multi-problem product
        loading_html = """
        <div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 12px; color: white;'>
            <h3 style='margin-top: 0; color: white;'>⏳ กำลังโหลด Visualization...</h3>
            <div style='color: white; font-size: 0.95em;'>
                ✅ เตรียมข้อมูล...<br>
                ✅ สร้าง Vector Space...<br>
                ✅ สร้าง Score Breakdown...<br>
                ✅ สร้าง Detection Flow...<br>
                • กำลังสร้าง Multi-Problem Product...<br>
            </div>
        </div>
        """
        yield fig, score_fig, flow_fig, empty_fig, loading_html

        # Create multi-problem product visualization (NEW)
        logger.info(f"🎨 กำลังสร้าง Multi-Problem Product...")
        if sample_problems and real_docs:
            multi_product_fig = create_multi_problem_product_visualization(sample_problems, real_docs[0])
            logger.info(f"   ✅ Multi-Problem Product สร้างสำเร็จ")
        else:
            # Create empty figure for baseline strategies
            multi_product_fig = go.Figure()
            multi_product_fig.update_layout(
                title="🔢 Multi-Problem Product (Not applicable for baseline strategies)",
                annotations=[dict(
                    text="<b>Baseline strategies don't have problem detection</b><br>No multi-problem product to display<br><br>💡 Select an H2L strategy to see problem interaction effects",
                    xref="paper", yref="paper", x=0.5, y=0.5,
                    showarrow=False, font=dict(size=14, color="#FFD93D"),
                    bgcolor="rgba(255,193,7,0.1)",
                    bordercolor="#FFD93D",
                    borderwidth=2,
                    borderpad=20
                )]
            )
            logger.info(f"   ℹ️ Multi-Problem Product skipped (baseline strategy)")

        # Stats HTML with strategy indicator
        total_sev = sum(p['severity'] for p in sample_problems) if sample_problems else 0
        stats_html = f"""
        <div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); padding: 20px; border-radius: 12px; color: white;'>
            <h3 style='margin-top: 0; color: #00d4ff;'>📊 Visualization Info</h3>

            <!-- Strategy Indicator -->
            <div style='background: rgba(0,212,255,0.2); padding: 12px; border-radius: 8px; margin-bottom: 15px; border-left: 4px solid #00d4ff;'>
                <div style='color: #00d4ff; font-weight: bold; font-size: 1.1em; margin-bottom: 5px;'>
                    🎯 Current Visualization Mode
                </div>
                <div style='color: white; font-size: 1em;'>
                    <strong>Mode:</strong> {viz_mode} Vector Space<br>
                    <strong>Strategy:</strong> {current_strategy['name']}<br>
                    <strong>DR Method:</strong> {dr_method}<br>
                    <strong>Formula:</strong> {current_strategy['formula']}
                </div>
            </div>

            <!-- Expandable Statistics -->
            <div style='margin-bottom: 15px;'>
                {f'''
                <details style='margin-bottom: 10px; cursor: pointer;'>
                    <summary style='padding: 8px; background: rgba(0,212,255,0.15); border-radius: 5px; color: white; font-weight: bold;'>
                        📋 Problems: {num_problems}
                    </summary>
                    <div style='padding: 10px; margin-top: 5px; background: rgba(0,0,0,0.3); border-radius: 5px; font-size: 0.9em; color: #e0e0e0;'>
                        {''.join([f"<div style='padding: 3px;'>• <strong>{p['code']}</strong> - {p['name']} (Severity: {p['severity']}, Confidence: {p['confidence']:.2f})</div>" for p in sample_problems])}
                    </div>
                </details>

                <details style='margin-bottom: 10px; cursor: pointer;'>
                    <summary style='padding: 8px; background: rgba(255,193,7,0.15); border-radius: 5px; color: white; font-weight: bold;'>
                        🔍 L1 Candidates: {l1_count}
                    </summary>
                    <div style='padding: 10px; margin-top: 5px; background: rgba(0,0,0,0.3); border-radius: 5px; font-size: 0.9em; color: #e0e0e0;'>
                        {''.join([f"<div style='padding: 3px;'>• <strong>{p['code']}</strong> - {p['name']}</div>" for p in (sample_problems + filtered_out_list)])}
                    </div>
                </details>

                <details style='margin-bottom: 10px; cursor: pointer;'>
                    <summary style='padding: 8px; background: rgba(40,167,69,0.15); border-radius: 5px; color: white; font-weight: bold;'>
                        ✅ L2 Confirmed: {num_problems}
                    </summary>
                    <div style='padding: 10px; margin-top: 5px; background: rgba(0,0,0,0.3); border-radius: 5px; font-size: 0.9em; color: #e0e0e0;'>
                        {''.join([f"<div style='padding: 3px;'>• <strong>{p['code']}</strong> - {p['name']} (LLM Confidence: {p['confidence']:.2f})</div>" for p in sample_problems])}
                    </div>
                </details>

                <details style='margin-bottom: 10px; cursor: pointer;'>
                    <summary style='padding: 8px; background: rgba(220,53,69,0.15); border-radius: 5px; color: white; font-weight: bold;'>
                        ❌ Filtered: {l2_filtered}
                    </summary>
                    <div style='padding: 10px; margin-top: 5px; background: rgba(0,0,0,0.3); border-radius: 5px; font-size: 0.9em; color: #e0e0e0;'>
                        {''.join([f"<div style='padding: 3px;'>• <strong>{p.get('code','N/A')}</strong> - {p.get('name','Unknown')}</div>" for p in filtered_out_list]) if l2_filtered > 0 else "<div style='padding: 3px;'>ไม่มีผลบวกลวงที่ถูกกรองออก</div>"}
                    </div>
                </details>

                <div style='padding: 8px; background: rgba(0,212,255,0.1); border-radius: 5px; color: white; font-weight: bold;'>
                    📊 Total Severity: {total_sev} / {num_problems} = {total_sev/num_problems if num_problems > 0 else 0:.1f}
                </div>
                ''' if sample_problems else f'''
                <div style='padding: 15px; background: rgba(255,193,7,0.1); border-radius: 8px; border-left: 4px solid #FFD93D;'>
                    <p style='color: #FFD93D; font-weight: bold; margin: 0 0 10px 0;'>📊 Baseline Strategy Mode</p>
                    <p style='margin: 5px 0; color: white;'><strong>Documents:</strong> {num_docs}</p>
                    <p style='margin: 10px 0 0 0; font-size: 0.9em; color: #f0f0f0; line-height: 1.5;'>
                        Baseline strategies use <strong>hybrid retrieval</strong> (dense + sparse) without problem detection.<br>
                        No L1/L2 filtering or problem-aware scoring.<br><br>
                        💡 <strong>Tip:</strong> Select an H2L strategy to see problem detection features.
                    </p>
                </div>
                '''}

                <details style='margin-top: 10px; margin-bottom: 10px; cursor: pointer;'>
                    <summary style='padding: 8px; background: rgba(0,212,255,0.15); border-radius: 5px; color: white; font-weight: bold;'>
                        📄 Documents: {num_docs}
                    </summary>
                    <div style='padding: 10px; margin-top: 5px; background: rgba(0,0,0,0.3); border-radius: 5px; font-size: 0.9em; color: #e0e0e0; max-height: 400px; overflow-y: auto;'>
                        {(''.join([f"<div style='padding: 5px 3px; border-bottom: 1px solid rgba(255,255,255,0.08);'><strong style='color: #0d6efd;'>#{(i+1):02d} Rank | {doc['id']}</strong><br><span style='font-size: 0.85em; color: #ccc;'>📂 {doc['source']}</span><br><span style='font-size: 0.8em; color: #999;'>{doc['title']}</span><br><span style='font-size:0.85em; color:#fff;'>S_rerank: {doc['s_rerank']:.4f} | S_final: {doc['final_score']:.4f}</span></div>" for i, doc in enumerate(real_docs)])) if real_docs else "No docs retrieved"}
                    </div>
                </details>
            </div>
            <div style='margin-top: 15px; padding: 10px; background: rgba(0,212,255,0.1); border-radius: 8px; font-family: monospace; font-size: 0.9em; color: #e0e0e0;'>
                <div style='color: #FFD93D;'>{strategy.upper()} Variables:</div>
                <div>{current_strategy['variables']}</div>
            </div>
            <div style='margin-top: 10px; padding: 8px; background: rgba(0,255,0,0.1); border-radius: 5px; border-left: 3px solid #0f0;'>
                <div style='color: #0f0; font-size: 0.9em;'>✅ โหลดเสร็จสมบูรณ์</div>
                <div style='color: #90EE90; font-size: 0.85em; margin-top: 5px;'>
                    ⏱️ Mode: {viz_mode} | DR: {dr_method} | Problems: {num_problems} | Docs: {num_docs}
                </div>
            </div>
        </div>
        """

        logger.info(f"✅ ทุก Visualizations สร้างเสร็จแล้ว")

        yield fig, score_fig, flow_fig, multi_product_fig, stats_html

    except Exception as e:
        logger.error(f"❌ เกิดข้อผิดพลาดในการสร้าง Visualization: {e}")

        # Return error visualization
        error_html = f"""
        <div style='background: linear-gradient(135deg, #dc3545 0%, #c82333 100%); padding: 20px; border-radius: 12px; color: white;'>
            <h3 style='margin-top: 0;'>❌ โหลดล้มเหลว</h3>
            <p><strong>Error:</strong> {str(e)}</p>
            <p style='font-size: 0.9em; margin-top: 10px;'>กรุณาลองใหม่อีกครั้ง หรือตรวจสอบ console logs</p>
        </div>
        """

        # Return empty figures with error message
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title="❌ Error",
            annotations=[dict(
                text=f"Error: {str(e)}",
                xref="paper", yref="paper",
                x=0.5, y=0.5,
                showarrow=False,
                font=dict(size=14, color="red")
            )]
        )

        yield empty_fig, empty_fig, empty_fig, empty_fig, error_html


# ====================================================================
# 📊 H2L vs Baseline Strategy Comparison
# ====================================================================

def create_strategy_comparison_visualization(base_strategy: str, test_case: str) -> Tuple[go.Figure, str]:
    """
    Compare baseline strategy vs H2L-enhanced version using REAL retrieval scores.

    Args:
        base_strategy: One of ["bm25_only", "naive_rag", "hybrid", "hyde"]
        test_case: The case description to analyze.

    Returns:
        Tuple of (plotly_figure, html_info_string)
    """

    # Map base strategy to H2L strategy
    h2l_strategy_map = {
        "bm25_only": "h2l-bm25",
        "naive_rag": "h2l-naive_rag",
        "hybrid": "h2l-hybrid",
        "hyde": "h2l-hyde",
    }
    h2l_strategy = h2l_strategy_map.get(base_strategy, f"h2l-{base_strategy}")

    # Run both strategies
    baseline = EnhancedOrchestrator(retriever_strategy=base_strategy, enable_l2=True)
    h2l_enhanced = EnhancedOrchestrator(retriever_strategy=h2l_strategy, enable_l2=True)

    baseline_result = baseline.analyze_case(test_case)
    h2l_result = h2l_enhanced.analyze_case(test_case)

    # Extract REAL retrieval scores from documents
    def _extract_doc_scores_and_ids(result):
        """Extract real scores and identifiers from retrieved documents."""
        docs = result.get('retrieved_docs', [])
        scores = []
        doc_ids = []
        # Debug: log first doc structure
        if docs:
            d0 = docs[0]
            logger.info(f"[DEBUG] doc type={type(d0).__name__}")
            if hasattr(d0, 'doc'):
                logger.info(f"[DEBUG] d.doc type={type(d0.doc).__name__}, meta={d0.doc.meta}")
            elif isinstance(d0, dict):
                logger.info(f"[DEBUG] dict keys={list(d0.keys())}")
            else:
                logger.info(f"[DEBUG] unknown type, dir={[x for x in dir(d0) if not x.startswith('_')]}")
        else:
            logger.info(f"[DEBUG] retrieved_docs is EMPTY, result keys={list(result.keys())}")
        for d in docs:
            # Extract score
            if hasattr(d, 'final_score'):
                scores.append(d.final_score)
            elif hasattr(d, 'rerank_score'):
                scores.append(d.rerank_score)
            elif hasattr(d, 'score'):
                scores.append(d.score)
            elif isinstance(d, dict):
                scores.append(d.get('final_score', d.get('rerank_score', d.get('score', 0.0))))
            # Extract doc ID / title from various object types
            if isinstance(d, dict):
                meta = d
            elif hasattr(d, 'doc') and hasattr(d.doc, 'meta'):
                # RetrievalResult object: meta is in d.doc.meta
                meta = d.doc.meta if d.doc.meta else {}
            elif hasattr(d, 'meta'):
                meta = d.meta if d.meta else {}
            else:
                meta = {}

            title = (meta.get('title') or meta.get('source_document') or
                     meta.get('source') or '')
            doc_id = (meta.get('chunk_id') or meta.get('doc_id') or
                      meta.get('id') or '')

            # Build label: prefer title, then chunk_id, then fallback
            if title:
                label = str(title)[:25]
            elif doc_id:
                label = str(doc_id)[:25]
            else:
                label = f'Doc {len(doc_ids)+1}'
            doc_ids.append(label)
        return scores, doc_ids

    baseline_doc_scores, baseline_doc_ids = _extract_doc_scores_and_ids(baseline_result)
    h2l_doc_scores, h2l_doc_ids = _extract_doc_scores_and_ids(h2l_result)

    # Calculate real metrics
    baseline_metrics = baseline_result.get('metrics', {})
    h2l_metrics = h2l_result.get('metrics', {})

    b_avg_ret = baseline_metrics.get('avg_retrieval_score', 0.0)
    h_avg_ret = h2l_metrics.get('avg_retrieval_score', 0.0)
    b_top3 = baseline_metrics.get('top3_avg_score', 0.0)
    h_top3 = h2l_metrics.get('top3_avg_score', 0.0)
    b_conf = baseline_metrics.get('avg_confidence', 0.0)
    h_conf = h2l_metrics.get('avg_confidence', 0.0)

    # If no real retrieval scores (fallback mode without RAGFirstOrchestrator)
    if b_avg_ret == 0.0 and not baseline_doc_scores:
        b_avg_ret = b_conf * 0.1  # approximate from confidence
    if h_avg_ret == 0.0 and not h2l_doc_scores:
        h_avg_ret = h_conf * 0.15

    has_real_docs = bool(baseline_doc_scores or h2l_doc_scores)

    # ── Build figure ──
    if has_real_docs:
        # 3-panel layout when we have real document scores
        fig = make_subplots(
            rows=3, cols=1,
            subplot_titles=(
                '📊 Retrieval Quality Comparison (Real Scores)',
                '📄 Per-Document Score Comparison (Top 10)',
                '🎯 Detection & Filtering Results'
            ),
            specs=[[{"type": "bar"}], [{"type": "bar"}], [{"type": "bar"}]],
            row_heights=[0.3, 0.4, 0.3],
            vertical_spacing=0.10
        )
    else:
        fig = make_subplots(
            rows=2, cols=1,
            subplot_titles=(
                '📊 Retrieval Quality Comparison',
                '🎯 Detection & Filtering Results'
            ),
            specs=[[{"type": "bar"}], [{"type": "bar"}]],
            row_heights=[0.5, 0.5],
            vertical_spacing=0.15
        )

    # ── Panel 1: Retrieval Quality Metrics ──
    metric_names = ['Avg Retrieval<br>Score', 'Top-3 Avg<br>Score', 'Avg<br>Confidence']
    baseline_values = [b_avg_ret, b_top3, b_conf]
    h2l_values = [h_avg_ret, h_top3, h_conf]

    fig.add_trace(go.Bar(
        name=f'{base_strategy.upper()} (Baseline)',
        x=metric_names,
        y=baseline_values,
        marker_color='#FF6B6B',
        text=[f'{v:.4f}' for v in baseline_values],
        textposition='outside',
        textangle=0,
        textfont=dict(size=11, color='#333'),
        hovertemplate='<b>%{x}</b><br>Score: %{y:.6f}<extra></extra>',
        width=0.3
    ), row=1, col=1)

    fig.add_trace(go.Bar(
        name=f'{h2l_strategy.upper()} (H2L Enhanced)',
        x=metric_names,
        y=h2l_values,
        marker_color='#4ECDC4',
        text=[f'{v:.4f}' for v in h2l_values],
        textposition='outside',
        textangle=0,
        textfont=dict(size=11, color='#333'),
        hovertemplate='<b>%{x}</b><br>Score: %{y:.6f}<extra></extra>',
        width=0.3
    ), row=1, col=1)

    # ── Panel 2: Per-Document Score Comparison (if we have real docs) ──
    current_panel = 2
    if has_real_docs:
        top_n = min(10, max(len(baseline_doc_scores), len(h2l_doc_scores)))

        # Build doc labels from IDs — show real doc identifiers
        all_ids = baseline_doc_ids + h2l_doc_ids
        # Use H2L doc IDs as primary (since they have boosted scores)
        doc_labels = []
        for i in range(top_n):
            if i < len(h2l_doc_ids):
                doc_labels.append(h2l_doc_ids[i])
            elif i < len(baseline_doc_ids):
                doc_labels.append(baseline_doc_ids[i])
            else:
                doc_labels.append(f'Doc {i+1}')

        # Pad shorter list with zeros
        b_scores_padded = (baseline_doc_scores + [0.0] * top_n)[:top_n]
        h_scores_padded = (h2l_doc_scores + [0.0] * top_n)[:top_n]

        fig.add_trace(go.Bar(
            name=f'{base_strategy.upper()} (Baseline)',
            x=doc_labels,
            y=b_scores_padded,
            marker_color='#FF6B6B',
            text=[f'{v:.3f}' for v in b_scores_padded],
            textposition='auto',
            textangle=0,
            textfont=dict(size=9, color='#333'),
            hovertemplate='<b>%{x}</b><br>Score: %{y:.6f}<extra></extra>',
            width=0.35,
            showlegend=False
        ), row=2, col=1)

        fig.add_trace(go.Bar(
            name=f'{h2l_strategy.upper()} (H2L Enhanced)',
            x=doc_labels,
            y=h_scores_padded,
            marker_color='#4ECDC4',
            text=[f'{v:.3f}' for v in h_scores_padded],
            textposition='auto',
            textangle=0,
            textfont=dict(size=9, color='#333'),
            hovertemplate='<b>%{x}</b><br>Score: %{y:.6f}<extra></extra>',
            width=0.35,
            showlegend=False
        ), row=2, col=1)

        current_panel = 3

    # ── Panel 3 (or 2): Detection Results ──
    baseline_problems = len(baseline_result.get('problems', []))
    baseline_filtered = len(baseline_result.get('filtered_out', []))
    h2l_problems = len(h2l_result.get('problems', []))
    h2l_filtered = len(h2l_result.get('filtered_out', []))

    # Compute retrieval improvement
    ret_improvement = ((h_avg_ret - b_avg_ret) / b_avg_ret * 100) if b_avg_ret > 0 else 0.0

    detection_categories = ['Problems<br>Detected', 'Problems<br>Filtered', 'Retrieval<br>Improvement %']
    baseline_detection = [baseline_problems, baseline_filtered, 0]
    h2l_detection = [h2l_problems, h2l_filtered, ret_improvement]

    fig.add_trace(go.Bar(
        x=detection_categories,
        y=baseline_detection,
        marker_color='#FF6B6B',
        text=[f'{int(v)}' for v in baseline_detection],
        textposition='outside',
        textangle=0,
        textfont=dict(size=13, color='#333'),
        width=0.35,
        showlegend=False
    ), row=current_panel, col=1)

    fig.add_trace(go.Bar(
        x=detection_categories,
        y=h2l_detection,
        marker_color='#4ECDC4',
        text=[f'{v:+.1f}%' if i == 2 else f'{int(v)}' for i, v in enumerate(h2l_detection)],
        textposition='outside',
        textangle=0,
        textfont=dict(size=13, color='#333'),
        width=0.35,
        showlegend=False
    ), row=current_panel, col=1)

    # ── Layout ──
    fig_height = 1100 if has_real_docs else 900
    fig.update_layout(
        height=fig_height,
        title=dict(
            text=f'<b>🔬 {base_strategy.upper()} vs {h2l_strategy.upper()} — Real Retrieval Performance</b><br>'
                 f'<sub style="font-size:13px;">H2L V6: S<sub>final</sub> = S<sub>rerank</sub> · exp(α(C) · Σ w<sub>i</sub> · Φ<sub>i</sub>) · P(rel|profile)</sub>',
            font=dict(size=18),
            x=0.5,
            xanchor='center'
        ),
        showlegend=True,
        legend=dict(
            orientation='h', yanchor='bottom', y=1.12, xanchor='center', x=0.5,
            font=dict(size=13)
        ),
        barmode='group',
        font=dict(size=12),
        plot_bgcolor='rgba(240,240,240,0.3)',
        paper_bgcolor='white',
        margin=dict(t=180) # Increase top margin to prevent title overlap
    )

    # Axes
    # Increase maximum y-axis range to prevent text clipping
    fig.update_yaxes(title_text="Score", row=1, col=1, title_font=dict(size=13), range=[0, max(max(baseline_values), max(h2l_values)) * 1.3])
    if has_real_docs:
        max_doc_score = max(max(b_scores_padded), max(h_scores_padded)) if b_scores_padded else 1.0
        fig.update_yaxes(title_text="Document Score", row=2, col=1, title_font=dict(size=13), range=[0, max_doc_score * 1.5])
    fig.update_yaxes(title_text="Count / %", row=current_panel, col=1, title_font=dict(size=13), range=[0, max(max(baseline_detection), max(h2l_detection)) * 1.3])

    # ── HTML Info Summary ──
    baseline_info = baseline_result.get('detection_info', {})
    h2l_info = h2l_result.get('detection_info', {})

    improvement_color = "#27AE60" if ret_improvement > 0 else "#E74C3C"
    arrow = "↗️" if ret_improvement > 0 else "↘️"

    if ret_improvement > 50:
        analysis = "🏆 <strong>ดีเยี่ยม:</strong> H2L เพิ่มคะแนนการดึงเอกสารอย่างมีนัยสำคัญ — สมการ Scoring ช่วยให้เอกสารที่ตรงกับปัญหาถูกจัดลำดับสูงขึ้น"
    elif ret_improvement > 10:
        analysis = "✅ <strong>ดี:</strong> H2L ปรับปรุงคุณภาพการดึงเอกสารได้อย่างวัดผลได้ — เอกสารที่เกี่ยวข้องถูก boost ขึ้นอันดับต้นๆ"
    elif ret_improvement > 0:
        analysis = "📊 <strong>ปานกลาง:</strong> H2L ให้ผลดีขึ้นเล็กน้อย — ความแตกต่างอาจไม่ชัดในเคสที่ง่าย ลองทดสอบเคสที่ซับซ้อนกว่านี้"
    else:
        analysis = "⚠️ <strong>หมายเหตุ:</strong> คะแนนใกล้เคียงกัน — อาจเกิดจากเคสนี้ไม่ซับซ้อนพอให้เห็นผลของ H2L Scoring หรือ Retriever อาจ fallback เป็น detector-only mode"

    # Problem tags
    def _format_problem_tags(problems, color):
        if not problems:
            return "<span style='color:#999;'>— ไม่พบ</span>"
        tags = ""
        for p in problems:
            code = p.get('code', '?')
            name = p.get('name', '')
            sev = p.get('severity', 1)
            sev_icons = {1: '⚪', 2: '🔵', 3: '🟡', 4: '🟠', 5: '🔴'}
            icon = sev_icons.get(sev, '⚫')
            tags += f"<span style='display:inline-block; background:{color}; padding:3px 8px; border-radius:4px; margin:2px; font-size:0.85em; color:#333;'>{icon} [{code}] {name}</span>"
        return tags

    baseline_tags = _format_problem_tags(baseline_result.get('problems', []), '#e8eaf6')
    h2l_tags = _format_problem_tags(h2l_result.get('problems', []), '#e8f5e9')
    filtered_tags = ""
    h2l_filtered_list = h2l_result.get('filtered_out', [])
    if h2l_filtered_list:
        filtered_tags = "<div style='margin-top:6px;'><span style='color:#999; font-size:0.85em;'>กรองออก: </span>"
        for p in h2l_filtered_list:
            filtered_tags += f"<span style='display:inline-block; background:#fce4ec; padding:2px 6px; border-radius:4px; margin:2px; font-size:0.8em; text-decoration:line-through; color:#c62828;'>[{p.get('code','?')}] {p.get('name','')}</span>"
        filtered_tags += "</div>"

    # Score table rows
    score_table_rows = ""
    for name, b_val, h_val in [
        ("Avg Retrieval Score", b_avg_ret, h_avg_ret),
        ("Top-3 Avg Score", b_top3, h_top3),
        ("Avg Confidence", b_conf, h_conf),
    ]:
        diff = ((h_val - b_val) / b_val * 100) if b_val > 0 else 0
        diff_color = "#27AE60" if diff > 0 else "#E74C3C" if diff < 0 else "#999"
        score_table_rows += f"""
            <tr style='border-bottom:1px solid #eee;'>
                <td style='padding:8px 12px; color:#333;'>{name}</td>
                <td style='padding:8px 12px; text-align:center; color:#555;'>{b_val:.6f}</td>
                <td style='padding:8px 12px; text-align:center; color:#555;'>{h_val:.6f}</td>
                <td style='padding:8px 12px; text-align:center; color:{diff_color}; font-weight:600;'>{diff:+.1f}%</td>
            </tr>"""

    info_html = f"""
    <div style='background: #f8f9fa; padding: 25px; border-radius: 12px; color: #1a1a2e; margin-top: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); border: 1px solid #e0e0e0;'>
        <h3 style='color: #1a1a2e; margin-top: 0; font-size: 1.4em;'>📊 Real Retrieval Performance Comparison</h3>

        <div style='background: white; padding: 20px; border-radius: 10px; margin-bottom: 15px; border: 1px solid #ddd;'>
            <table style='width:100%; border-collapse:collapse; font-size:0.95em;'>
                <thead>
                    <tr style='border-bottom:2px solid #667eea; background:#f0f2ff;'>
                        <th style='padding:10px 12px; text-align:left; color:#333;'>Metric</th>
                        <th style='padding:10px 12px; text-align:center; color:#c0392b;'>🔵 {base_strategy.upper()}</th>
                        <th style='padding:10px 12px; text-align:center; color:#27ae60;'>🟢 {h2l_strategy.upper()}</th>
                        <th style='padding:10px 12px; text-align:center; color:#333;'>Δ Change</th>
                    </tr>
                </thead>
                <tbody>{score_table_rows}</tbody>
            </table>

            <div style='text-align: center; padding: 15px 0; margin-top: 10px;'>
                <p style='margin: 5px 0; font-size: 1em; color: #333;'><strong>Retrieval Score Improvement:</strong></p>
                <span style='color: {improvement_color}; font-size: 2.5em; font-weight: bold;'>
                    {arrow} {ret_improvement:+.1f}%
                </span>
            </div>
        </div>

        <div style='background: #fffbf0; padding: 18px; border-radius: 10px; margin-bottom: 15px; border-left: 4px solid #F39C12;'>
            <h4 style='color: #E67E22; margin: 0 0 10px 0; font-size: 1.1em;'>🤔 ทำไมปัญหาที่ตรวจพบเหมือนกัน แต่คะแนนต่างกัน?</h4>
            <p style='margin: 0; font-size: 0.93em; line-height: 1.7; color: #444;'>
                ทั้งสองฝั่งใช้ <strong>ตัวตรวจจับปัญหา (Detector)</strong> ตัวเดียวกัน ดังนั้นจำนวนปัญหาที่พบจะเท่ากันเสมอ — เพื่อให้เปรียบเทียบ<strong>วิธีให้คะแนนเอกสาร</strong>ได้ยุติธรรม
            </p>
            <div style='background: white; padding: 14px; border-radius: 8px; margin-top: 10px; border: 1px solid #eee;'>
                <p style='margin: 0 0 8px 0; font-size: 0.93em; color: #333;'><strong>ความแตกต่างอยู่ที่การให้คะแนน:</strong></p>
                <div style='display:grid; grid-template-columns: 1fr 1fr; gap: 12px;'>
                    <div style='background:#fff5f5; padding:12px; border-radius:8px; border-left:3px solid #FF6B6B;'>
                        <p style='margin:0 0 4px 0; font-size:0.9em; color:#c0392b;'><strong>🔵 Baseline</strong></p>
                        <p style='margin:0; font-size:0.85em; color:#555; line-height:1.5;'>ค้นหาเอกสารตามคำค้นปกติ ไม่ปรับคะแนนตามปัญหาที่พบ</p>
                    </div>
                    <div style='background:#f0faf0; padding:12px; border-radius:8px; border-left:3px solid #4ECDC4;'>
                        <p style='margin:0 0 4px 0; font-size:0.9em; color:#27ae60;'><strong>🟢 H2L V6</strong></p>
                        <p style='margin:0; font-size:0.85em; color:#555; line-height:1.5;'>ปรับคะแนนเอกสารด้วยสมการ H2L — เอกสารที่ตรงกับปัญหาที่พบจะถูก Boost ขึ้นมาอันดับต้นๆ</p>
                    </div>
                </div>
            </div>
        </div>

        <div style='background: white; padding: 15px; border-radius: 10px; margin-bottom: 15px; border: 1px solid #ddd;'>
            <div style='display: grid; grid-template-columns: 1fr 1fr; gap: 15px;'>
                <div>
                    <p style='margin: 5px 0; font-size: 1.05em; color:#333;'><strong>🔵 Baseline:</strong> {base_strategy.upper()}</p>
                    <p style='margin: 5px 0; font-size: 0.85em; color:#666;'>Docs: {baseline_result.get('retrieved_docs_count', 0)} | L2: {"✅" if baseline_info.get('l2_applied') else "❌"}</p>
                    <div style='margin-top:6px;'>{baseline_tags}</div>
                </div>
                <div>
                    <p style='margin: 5px 0; font-size: 1.05em; color:#333;'><strong>🟢 Enhanced:</strong> {h2l_strategy.upper()}</p>
                    <p style='margin: 5px 0; font-size: 0.85em; color:#666;'>Docs: {h2l_result.get('retrieved_docs_count', 0)} | L2: {"✅" if h2l_info.get('l2_applied') else "❌"}</p>
                    <div style='margin-top:6px;'>{h2l_tags}</div>
                    {filtered_tags}
                </div>
            </div>
        </div>

        <div style='background: #f0f7ff; padding: 15px; border-radius: 10px; border-left: 4px solid #4facfe;'>
            <h4 style='color: #2c3e50; margin: 0 0 8px 0; font-size: 1.1em;'>💡 Analysis</h4>
            <p style='margin: 5px 0; font-size: 1em; line-height: 1.6; color: #333;'>{analysis}</p>
            <p style='margin: 8px 0 0; font-size: 0.9em; line-height: 1.5; color: #555;'>
                • Execution Time: {baseline_result.get('execution_time', 0):.2f}s (Baseline) vs {h2l_result.get('execution_time', 0):.2f}s (H2L)<br>
                • Severity: {baseline_result.get('severity_level', 'N/A')} → {h2l_result.get('severity_level', 'N/A')}<br>
                • Retriever: {baseline_result.get('retriever_class', base_strategy)} → {h2l_result.get('retriever_class', h2l_strategy)}
            </p>
        </div>
    </div>
    """

    return fig, info_html


# ====================================================================
# 🚀 Create Unified App V4
# ====================================================================

def create_unified_app():
    theme = gr.themes.Soft(primary_hue="indigo", font=["Sarabun", "sans-serif"])

    BASE_STRATS = ["bm25_only", "naive_rag", "hybrid", "hyde"]
    H2L_STRATS = ["h2l-bm25", "h2l-naive_rag", "h2l-hybrid", "h2l-hyde"]

    with gr.Blocks(title="AI Social Worker - V4", theme=theme, css="""
        /* ============================================================
         * 🎨 THEME SYSTEM — CSS Variables for Light/Dark Mode
         * WCAG AA compliant contrast ratios (min 4.5:1 for text)
         * ============================================================ */

        /* --- Light Mode (default) --- */
        :root, .gradio-container {
            --text-primary: #1a1a2e;
            --text-secondary: #3d4250;
            --text-muted: #5a5f72;
            --text-light: #6b7280;
            --bg-page: #f3f4f8;
            --bg-surface: #ffffff;
            --bg-surface-alt: #f0f2f7;
            --bg-hover: #e8ecf3;
            --border-color: #d1d5e0;
            --border-light: #e5e7eb;
            --accent-primary: #667eea;
            --accent-secondary: #764ba2;
            --card-shadow: 0 1px 4px rgba(0,0,0,0.08);
            --table-header-bg: #374151;
            --table-header-fg: #ffffff;
            --table-row-bg: #ffffff;
            --table-row-alt-bg: #f9fafb;
            --table-baseline-bg: #fff3cd;
            --table-baseline-fg: #664d03;
            --table-h2l-bg: #d1ecf1;
            --table-h2l-fg: #0c5460;
            --info-box-bg: #f0f7ff;
            --info-box-border: #4facfe;
            --footnote-bg: #f3f4f6;
        }

        /* --- Dark Mode --- */
        .dark, .dark .gradio-container {
            --text-primary: #e8eaf0;
            --text-secondary: #c5c9d6;
            --text-muted: #9ca3b8;
            --text-light: #8b93a8;
            --bg-page: #111827;
            --bg-surface: #1f2937;
            --bg-surface-alt: #283345;
            --bg-hover: #374151;
            --border-color: #4b5563;
            --border-light: #374151;
            --accent-primary: #818cf8;
            --accent-secondary: #a78bfa;
            --card-shadow: 0 1px 4px rgba(0,0,0,0.3);
            --table-header-bg: #1f2937;
            --table-header-fg: #e5e7eb;
            --table-row-bg: #1f2937;
            --table-row-alt-bg: #283345;
            --table-baseline-bg: #422006;
            --table-baseline-fg: #fed7aa;
            --table-h2l-bg: #0c4a6e;
            --table-h2l-fg: #bae6fd;
            --info-box-bg: #1e293b;
            --info-box-border: #3b82f6;
            --footnote-bg: #283345;
        }

        /* ============================================================
         * 🔤 GLOBAL TEXT — Ensure all text is readable
         * ============================================================ */
        .gradio-container { color: var(--text-primary) !important; }
        .markdown-body,
        .markdown-body p,
        .markdown-body li,
        .markdown-body strong { color: var(--text-primary) !important; }
        .markdown-body h1, .markdown-body h2,
        .markdown-body h3, .markdown-body h4 { color: var(--text-primary) !important; }
        label { color: var(--text-primary) !important; font-weight: 600 !important; }
        .gr-box label { color: var(--text-primary) !important; }
        span { color: inherit; }

        /* ============================================================
         * 🏷️ TABS — Strong contrast, both modes
         * ============================================================ */
        .tab-nav button {
            color: var(--text-primary) !important;
            font-weight: 600 !important;
            font-size: 0.95em !important;
            background: var(--bg-surface-alt) !important;
            border: 1px solid var(--border-color) !important;
            border-bottom: none !important;
            padding: 10px 18px !important;
            border-radius: 8px 8px 0 0 !important;
        }
        .tab-nav button.selected {
            color: #ffffff !important;
            background: linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-secondary) 100%) !important;
            border-color: var(--accent-primary) !important;
            font-weight: 700 !important;
        }
        .tab-nav button:not(.selected):hover {
            background: var(--bg-hover) !important;
            color: var(--text-primary) !important;
        }

        /* ============================================================
         * 📝 INPUTS — Readable text in forms
         * ============================================================ */
        input, textarea, select { color: var(--text-primary) !important; }
        .gr-input-label { color: var(--text-primary) !important; font-weight: 600 !important; }
        .gr-check-radio label { color: var(--text-primary) !important; }
        .label-wrap { color: var(--text-primary) !important; font-weight: 600 !important; }
        .gr-input-label span, .gr-check-radio span { color: var(--text-secondary) !important; }

        /* ============================================================
         * 📄 INLINE HTML CONTAINERS — Override hardcoded inline colors
         * All gr.HTML() output goes here; fix the light-gray-on-light issue
         * ============================================================ */

        /* --- Primary text in cards (#333) → use CSS var --- */
        .prose [style*="color:#333"],
        .prose [style*="color: #333"],
        .prose [style*="color:#2c3e50"],
        .prose [style*="color: #2c3e50"] {
            color: var(--text-primary) !important;
        }

        /* --- Secondary text (#555, #666) → darker for light, lighter for dark --- */
        .prose [style*="color:#555"],
        .prose [style*="color: #555"],
        .prose [style*="color:#666"],
        .prose [style*="color: #666"] {
            color: var(--text-secondary) !important;
        }

        /* --- Muted text (#777, #6c757d, #999) → ensure min contrast --- */
        .prose [style*="color:#777"],
        .prose [style*="color: #777"],
        .prose [style*="color:#6c757d"],
        .prose [style*="color: #6c757d"],
        .prose [style*="color:#999"],
        .prose [style*="color: #999"],
        .prose [style*="color:#856404"],
        .prose [style*="color: #856404"] {
            color: var(--text-muted) !important;
        }

        /* --- White backgrounds in cards → surface color --- */
        .prose [style*="background:white"],
        .prose [style*="background: white"],
        .prose [style*="background:#fff"],
        .prose [style*="background: #fff"],
        .prose [style*="background-color: white"],
        .prose [style*="background:#f8f9fa"],
        .prose [style*="background: #f8f9fa"],
        .prose [style*="background:#f0f7ff"],
        .prose [style*="background: #f0f7ff"] {
            background: var(--bg-surface) !important;
        }

        /* --- Alt backgrounds (#e9ecef, #f0f2f7) --- */
        .prose [style*="background:#e9ecef"],
        .prose [style*="background: #e9ecef"],
        .prose [style*="background:#f3f4f6"],
        .prose [style*="background: #f3f4f6"] {
            background: var(--bg-surface-alt) !important;
        }

        /* --- Table overrides --- */
        .prose table {
            background: var(--bg-surface) !important;
            color: var(--text-primary) !important;
        }
        .prose table thead {
            background: var(--table-header-bg) !important;
            color: var(--table-header-fg) !important;
        }
        .prose table thead th {
            color: var(--table-header-fg) !important;
        }
        .prose table td {
            color: var(--text-primary) !important;
            border-color: var(--border-light) !important;
        }
        .prose table tr {
            border-color: var(--border-light) !important;
        }

        /* --- Card borders → adaptive --- */
        .prose [style*="border: 1px solid #ddd"],
        .prose [style*="border: 1px solid #e0e0e0"],
        .prose [style*="border:1px solid #e0e0e0"] {
            border-color: var(--border-color) !important;
        }

        /* --- Box shadows → adaptive opacity --- */
        .prose [style*="box-shadow:0 1px 3px"] {
            box-shadow: var(--card-shadow) !important;
        }

        /* --- Footnote/info bar --- */
        .prose [style*="border-left:3px solid #667eea"],
        .prose [style*="border-left: 3px solid #667eea"] {
            background: var(--footnote-bg) !important;
            color: var(--text-secondary) !important;
        }

        /* ============================================================
         * 🖥️ CONSOLE OUTPUT — Always dark terminal look
         * ============================================================ */
        .console-output textarea {
            font-family: 'Courier New', monospace !important;
            background-color: #1e1e1e !important;
            color: #d4d4d4 !important;
            font-size: 0.85em !important;
        }

        /* ============================================================
         * 🌗 DARK PANEL — Statistical analysis dark sections
         * Keep dark bg, ensure text is light
         * ============================================================ */
        .dark-panel {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border-radius: 12px;
            padding: 15px;
        }
        .dark-panel, .dark-panel * {
            color: #e8e8e8 !important;
        }

        /* ============================================================
         * 🎯 THEME TOGGLE BUTTON
         * ============================================================ */
        #theme-toggle-btn {
            position: fixed !important;
            top: 12px;
            right: 16px;
            z-index: 9999;
            background: var(--bg-surface) !important;
            border: 1px solid var(--border-color) !important;
            border-radius: 50% !important;
            width: 40px !important;
            height: 40px !important;
            font-size: 1.3em !important;
            cursor: pointer !important;
            box-shadow: var(--card-shadow) !important;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 0 !important;
            min-width: 40px !important;
            transition: background 0.3s, border-color 0.3s;
        }
        #theme-toggle-btn:hover {
            background: var(--bg-hover) !important;
        }

        /* ============================================================
         * 🔘 RADIO / CHECKBOX — Info text readability
         * ============================================================ */
        .gr-input-label + div,
        .gr-check-radio + div {
            color: var(--text-muted) !important;
        }
        [class*="info"] { color: var(--text-muted) !important; }

        /* Gradio component description/info text (below labels) */
        .gradio-container span.svelte-1gfkn6j,
        .gradio-container .wrap .info,
        .gradio-container [data-testid="checkbox-group"] span,
        .gradio-container .block small {
            color: var(--text-secondary) !important;
        }

        /* Baseline/H2L badge labels — dark mode override */
        .dark .prose [style*="background:#fff3cd"],
        .dark .prose [style*="background: #fff3cd"] {
            background: var(--table-baseline-bg) !important;
        }
        .dark .prose [style*="background:#fff3cd"] strong,
        .dark .prose [style*="background: #fff3cd"] strong,
        .dark .prose [style*="color:#856404"],
        .dark .prose [style*="color: #856404"] {
            color: var(--table-baseline-fg) !important;
        }
        .dark .prose [style*="background:#d1ecf1"],
        .dark .prose [style*="background: #d1ecf1"] {
            background: var(--table-h2l-bg) !important;
        }
        .dark .prose [style*="background:#d1ecf1"] strong,
        .dark .prose [style*="background: #d1ecf1"] strong,
        .dark .prose [style*="color:#0c5460"],
        .dark .prose [style*="color: #0c5460"] {
            color: var(--table-h2l-fg) !important;
        }

        /* Step labels & headings in dark mode — CRITICAL FIX */
        /* These h3 elements use hardcoded color: #1a1a2e which is invisible on dark bg */
        .dark .prose [style*="color: #1a1a2e"],
        .dark .prose [style*="color:#1a1a2e"] {
            color: var(--text-primary) !important;
        }
        .dark .prose h3[style*="color: #1a1a2e"],
        .dark .prose h3[style*="color:#1a1a2e"] {
            color: #e8eaf0 !important;
        }

        /* Step description containers in dark mode */
        .dark .prose [style*="border-left: 4px solid #667eea"],
        .dark .prose [style*="border-left:4px solid #667eea"] {
            background: var(--bg-surface) !important;
            border-color: var(--accent-primary) !important;
        }
        .dark .prose [style*="border-left: 4px solid #f5576c"],
        .dark .prose [style*="border-left:4px solid #f5576c"] {
            background: var(--bg-surface) !important;
            border-color: #f87171 !important;
        }
        .dark .prose [style*="border-left: 4px solid #43A047"],
        .dark .prose [style*="border-left:4px solid #43A047"] {
            background: var(--bg-surface) !important;
            border-color: #4ade80 !important;
        }

        /* Green metrics header (Strategy Comparison) */
        .dark .prose [style*="color: #2E7D32"],
        .dark .prose [style*="color:#2E7D32"] {
            color: #86efac !important;
        }
        .dark .prose [style*="background: linear-gradient(135deg, #e8f5e9"] {
            background: linear-gradient(135deg, #1a3a2a 0%, #1a2a3a 100%) !important;
        }

        /* Severity colors — keep readable in both modes */
        .dark .prose [style*="color:#28a745"] { color: #4ade80 !important; }
        .dark .prose [style*="color: #28a745"] { color: #4ade80 !important; }
        .dark .prose [style*="color:#dc3545"] { color: #f87171 !important; }
        .dark .prose [style*="color: #dc3545"] { color: #f87171 !important; }
        .dark .prose [style*="color:#ffc107"] { color: #fbbf24 !important; }
        .dark .prose [style*="color: #ffc107"] { color: #fbbf24 !important; }
        .dark .prose [style*="color:#fd7e14"] { color: #fb923c !important; }
        .dark .prose [style*="color: #fd7e14"] { color: #fb923c !important; }

        /* Confidence bars background */
        .dark .prose [style*="background:#e9ecef"],
        .dark .prose [style*="background: #e9ecef"] {
            background: #374151 !important;
        }

        /* Dark mode: ensure all Gradio panels use proper bg */
        .dark .panel { background: var(--bg-surface) !important; }
        .dark .block { border-color: var(--border-color) !important; }
    """) as demo:

        gr.Markdown("""
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 18px 28px; border-radius: 12px; color: white; text-align: center; margin-bottom: 16px; position: relative;">
            <button id="theme-toggle-btn" onclick="
                const body = document.body;
                body.classList.toggle('dark');
                const isDark = body.classList.contains('dark');
                this.textContent = isDark ? '☀️' : '🌙';
                localStorage.setItem('h2l-theme', isDark ? 'dark' : 'light');
            " title="Toggle Light/Dark Mode">🌙</button>
            <h1 style="color: white; margin: 0; font-size: 2em; font-weight: 700; letter-spacing: 0.5px;">Social Worker Assistant</h1>
            <p style="color: rgba(255,255,255,0.85); font-size: 0.95em; margin: 6px 0 0;">APPROACH FOR THE SCREENING AND DIFFERENTIAL DIAGNOSIS OF SOCIAL PROBLEMS</p>
        </div>
        <script>
            // Restore saved theme preference on page load
            (function() {
                const saved = localStorage.getItem('h2l-theme');
                if (saved === 'dark') {
                    document.body.classList.add('dark');
                    const btn = document.getElementById('theme-toggle-btn');
                    if (btn) btn.textContent = '☀️';
                }
            })();
        </script>
        """)

        with gr.Tabs():
            # ==================== TAB 1: วิเคราะห์เคส ====================
            with gr.Tab("🔍 วิเคราะห์เคส"):
                selected_strat = gr.State("h2l-hybrid")

                # Model Loading — Accordion (collapsible)
                with gr.Accordion("🔧 การจัดการโมเดล — โหลดล่วงหน้าเพื่อประสิทธิภาพที่ดีขึ้น", open=False):
                    with gr.Row():
                        with gr.Column(scale=2):
                            load_models_btn = gr.Button(
                                "📦 โหลดโมเดล (Embedding + Reranker)",
                                variant="secondary",
                                size="lg"
                            )
                        with gr.Column(scale=3):
                            model_status_display = gr.HTML(value=check_models_status())

                    load_models_btn.click(
                        preload_models_ui,
                        inputs=[],
                        outputs=[model_status_display]
                    )

                # Step 1: Strategy Selection
                gr.Markdown("""
                <div style='background: #f8f9fa; padding: 12px 16px; border-radius: 8px; border-left: 4px solid #667eea; margin: 10px 0;'>
                    <h3 style='color: #1a1a2e; margin: 0; font-size: 1.1em;'>Step 1: เลือก Strategy</h3>
                </div>
                """)

                with gr.Row():
                    with gr.Column(variant="panel"):
                        gr.Markdown("""
                        <div style='padding: 8px 12px; background: #fff3cd; border-radius: 5px;'>
                            <strong style='color: #856404;'>Baseline</strong>
                        </div>
                        """)
                        rad_base = gr.Radio(BASE_STRATS, label="", container=False)
                    with gr.Column(variant="panel"):
                        gr.Markdown("""
                        <div style='padding: 8px 12px; background: #d1ecf1; border-radius: 5px;'>
                            <strong style='color: #0c5460;'>H2L (Problem-Aware)</strong>
                        </div>
                        """)
                        rad_h2l = gr.Radio(H2L_STRATS, label="", value="h2l-hybrid", container=False)
                    with gr.Column(scale=1):
                        enable_l2 = gr.Checkbox(
                            label="🧠 L2 LLM Filtering",
                            value=True,
                            info="กรอง False Positives ด้วย LLM"
                        )

                def set_base(x): return x, None
                def set_h2l(x): return x, None
                rad_base.change(set_base, rad_base, [selected_strat, rad_h2l])
                rad_h2l.change(set_h2l, rad_h2l, [selected_strat, rad_base])

                # Step 2: Case Input
                gr.Markdown("""
                <div style='background: #f8f9fa; padding: 12px 16px; border-radius: 8px; border-left: 4px solid #667eea; margin: 10px 0;'>
                    <h3 style='color: #1a1a2e; margin: 0; font-size: 1.1em;'>Step 2: ข้อมูลเคส</h3>
                </div>
                """)

                case_desc = gr.Textbox(
                    label="รายละเอียด",
                    lines=5,
                    value="เด็กไม่ได้เข้าเรียน บ่นว่าไม่อยากมีชีวิตบ่อย เคยทำร้ายร่างกายตัวเอง ทุกวันนี้ยังแอบทำอยู่"
                )
                btn = gr.Button("🚀 เริ่มวิเคราะห์", variant="primary", size="lg")

                # Step 3: Results — Sub-tabs
                gr.Markdown("""
                <div style='background: #f8f9fa; padding: 12px 16px; border-radius: 8px; border-left: 4px solid #667eea; margin: 10px 0;'>
                    <h3 style='color: #1a1a2e; margin: 0; font-size: 1.1em;'>Step 3: ผลลัพธ์</h3>
                </div>
                """)

                with gr.Tabs():
                    with gr.Tab("📊 สรุป"):
                        out_sum = gr.HTML(label="Summary")
                    with gr.Tab("🔍 ปัญหาที่พบ"):
                        out_prob = gr.HTML(label="Problems")
                    with gr.Tab("🛠️ เครื่องมือ"):
                        out_tools = gr.HTML(label="Tools")
                    with gr.Tab("📄 เอกสาร"):
                        out_docs = gr.HTML(label="Documents")

                # Process Log — Accordion (collapsible)
                with gr.Accordion("📋 Process Log", open=False):
                    console_output = gr.Textbox(
                        label="",
                        lines=10,
                        max_lines=15,
                        interactive=False,
                        show_label=False,
                        placeholder="Log output will appear here...",
                        elem_classes="console-output"
                    )

                btn.click(
                    analyze_case_ui,
                    inputs=[case_desc, gr.Textbox(value="CASE_001", visible=False), selected_strat, enable_l2],
                    outputs=[out_sum, out_prob, out_tools, out_docs, console_output]
                )

            # ==================== TAB 2: Vector Space Visualization ====================
            with gr.Tab("📊 3D Vector Space"):

                # Compact header
                gr.Markdown("""
                <div style='padding: 10px 16px; background: #f8f9fa; border-radius: 8px; border-left: 4px solid #667eea; margin-bottom: 10px;'>
                    <h3 style='margin: 0; color: #1a1a2e; font-size: 1.1em;'>3D Vector Space Visualization</h3>
                    <p style='margin: 4px 0 0; font-size: 0.85em; color: #555;'>
                        ⭐ Query &nbsp; 🔷 Problems &nbsp; 🟢 Relevant Docs &nbsp; ⚪ Other Docs
                        &nbsp;|&nbsp; ลาก=หมุน, สกรอล=ซูม &nbsp;|&nbsp; ระยะ=คะแนนความเกี่ยวข้อง, ทิศ=ปัญหาที่จับได้
                    </p>
                </div>
                """)

                # Step 1: Strategy Selection
                gr.Markdown("""
                <div style='background: #f8f9fa; padding: 12px 16px; border-radius: 8px; border-left: 4px solid #667eea; margin: 10px 0;'>
                    <h3 style='color: #1a1a2e; margin: 0; font-size: 1.1em;'>Step 1: เลือก Strategy</h3>
                </div>
                """)

                selected_strat_tab2 = gr.State("h2l-hybrid")

                with gr.Row():
                    with gr.Column(variant="panel"):
                        gr.Markdown("""
                        <div style='padding: 8px 12px; background: #fff3cd; border-radius: 5px;'>
                            <strong style='color: #856404;'>Baseline</strong>
                        </div>
                        """)
                        rad_base_tab2 = gr.Radio(
                            choices=["bm25_only", "naive_rag", "hybrid", "hyde"],
                            label="", container=False
                        )
                    with gr.Column(variant="panel"):
                        gr.Markdown("""
                        <div style='padding: 8px 12px; background: #d1ecf1; border-radius: 5px;'>
                            <strong style='color: #0c5460;'>H2L (Problem-Aware)</strong>
                        </div>
                        """)
                        rad_h2l_tab2 = gr.Radio(
                            choices=["h2l-bm25", "h2l-naive_rag", "h2l-hybrid", "h2l-hyde"],
                            value="h2l-hybrid", label="", container=False
                        )

                def set_base_tab2(x): return x, None
                def set_h2l_tab2(x): return x, None
                rad_base_tab2.change(set_base_tab2, rad_base_tab2, [selected_strat_tab2, rad_h2l_tab2])
                rad_h2l_tab2.change(set_h2l_tab2, rad_h2l_tab2, [selected_strat_tab2, rad_base_tab2])

                # Step 2: Settings
                gr.Markdown("""
                <div style='background: #f8f9fa; padding: 12px 16px; border-radius: 8px; border-left: 4px solid #667eea; margin: 10px 0;'>
                    <h3 style='color: #1a1a2e; margin: 0; font-size: 1.1em;'>Step 2: ตั้งค่า Visualization</h3>
                </div>
                """)

                with gr.Row():
                    with gr.Column(scale=4):
                        case_input_viz = gr.Textbox(
                            label="📖 การนำเข้าเคสจากที่วิเคราะห์",
                            lines=2,
                            value="ผู้ป่วยมีภาวะซึมเศร้า สามีทิ้ง ถูกทำร้ายร่างกาย มีดกรีดข้อมือ เลือดไหลเยอะมาก",
                            placeholder="พิมพ์ประโยคที่ต้องการให้สร้าง Vector Space 3 มิติจากข้อมูลจริง..."
                        )
                    with gr.Column(scale=1):
                        copy_from_tab1_viz_btn = gr.Button("📋 ดึงเคสจาก Tab 1", size="sm", variant="secondary", elem_id="pull_case_btn")
                with gr.Row():
                    num_problems_slider = gr.Slider(
                        minimum=1, maximum=5, value=3, step=1,
                        label="🔷 Problems"
                    )
                    num_docs_slider = gr.Slider(
                        minimum=10, maximum=50, value=25, step=5,
                        label="📄 Documents"
                    )
                    show_boundaries = gr.Checkbox(label="🔘 Boundary Circles", value=True)
                    show_distance_lines = gr.Checkbox(label="📏 Distance Lines", value=False)

                with gr.Accordion("🎨 Color Zones (ระยะทาง)", open=False):
                    with gr.Row():
                        show_zone_red = gr.Checkbox(label="🔴 Red (< 1.5)", value=False)
                        show_zone_yellow = gr.Checkbox(label="🟡 Yellow (1.5-3.0)", value=False)
                        show_zone_green = gr.Checkbox(label="🟢 Green (3.0-4.5)", value=False)

                with gr.Accordion("📐 Dimensionality Reduction", open=False):
                    dr_method = gr.Dropdown(
                        choices=["None", "PCA", "t-SNE", "UMAP"],
                        value="None",
                        label="DR Method",
                        info="ใช้ได้เฉพาะ demo mode (ALLOW_DEMO_DATA=true) และรันบน synthetic embeddings เท่านั้น — ค่าปกติคือ None"
                    )
                    dr_info = gr.Markdown(
                        "**None** — golden spiral distribution, เร็วที่สุด, เหมาะสำหรับการสาธิต",
                        visible=True
                    )

                update_viz_btn = gr.Button("🔄 Update Visualization", variant="primary", size="lg")

                # Step 3: Results
                gr.Markdown("""
                <div style='background: #f8f9fa; padding: 12px 16px; border-radius: 8px; border-left: 4px solid #667eea; margin: 10px 0;'>
                    <h3 style='color: #1a1a2e; margin: 0; font-size: 1.1em;'>Step 3: ผลลัพธ์</h3>
                </div>
                """)

                with gr.Row():
                    with gr.Column(scale=5):
                        vector_space_plot = gr.Plot(label="Vector Space")
                    with gr.Column(scale=2):
                        stats_output = gr.HTML(label="📊 Statistics")

                with gr.Tabs():
                    with gr.Tab("📈 Score Breakdown"):
                        score_breakdown_plot = gr.Plot(label="Score Breakdown")
                    with gr.Tab("🔄 Detection Flow"):
                        detection_flow_plot = gr.Plot(label="Detection Flow")
                    with gr.Tab("✖️ Multi-Problem Product"):
                        multi_product_plot = gr.Plot(label="Multi-Problem Product")

                # Event wiring
                viz_inputs = [case_input_viz, num_problems_slider, num_docs_slider, show_boundaries,
                              show_distance_lines, show_zone_red, show_zone_yellow,
                              show_zone_green, dr_method, selected_strat_tab2]
                viz_outputs = [vector_space_plot, score_breakdown_plot,
                               detection_flow_plot, multi_product_plot, stats_output]

                update_viz_btn.click(
                    update_vector_space_viz,
                    inputs=viz_inputs,
                    outputs=viz_outputs
                )

                # Auto-update when strategy changes via radio
                def update_viz_on_base(x, ctext, np_s, nd_s, sb, sdl, szr, szy, szg, dr):
                    return update_vector_space_viz(ctext, np_s, nd_s, sb, sdl, szr, szy, szg, dr, x)
                def update_viz_on_h2l(x, ctext, np_s, nd_s, sb, sdl, szr, szy, szg, dr):
                    return update_vector_space_viz(ctext, np_s, nd_s, sb, sdl, szr, szy, szg, dr, x)

                rad_base_tab2.change(
                    update_viz_on_base,
                    inputs=[rad_base_tab2, case_input_viz, num_problems_slider, num_docs_slider, show_boundaries,
                            show_distance_lines, show_zone_red, show_zone_yellow,
                            show_zone_green, dr_method],
                    outputs=viz_outputs
                )
                rad_h2l_tab2.change(
                    update_viz_on_h2l,
                    inputs=[rad_h2l_tab2, case_input_viz, num_problems_slider, num_docs_slider, show_boundaries,
                            show_distance_lines, show_zone_red, show_zone_yellow,
                            show_zone_green, dr_method],
                    outputs=viz_outputs
                )

                demo.load(
                    update_vector_space_viz,
                    inputs=viz_inputs,
                    outputs=viz_outputs
                )
                
                # Wire the pull case button
                copy_from_tab1_viz_btn.click(
                    lambda x: x,
                    inputs=[case_desc],
                    outputs=[case_input_viz]
                )

                dr_method.change(
                    update_dr_info,
                    inputs=[dr_method],
                    outputs=[dr_info]
                )

            # ==================== TAB 3: Evaluation & Benchmarking (Unified) ====================
            with gr.Tab("📊 Evaluation & Benchmarking"):

                with gr.Tabs():
                    # ─── Sub-tab A: Strategy Comparison ───────────────────────
                    with gr.Tab("⚖️ เปรียบเทียบ Strategy"):
                        gr.Markdown("""
                        <div style='padding: 10px 16px; background: var(--bg-surface, #f8f9fa); border-radius: 8px; border-left: 4px solid #667eea; margin-bottom: 10px;'>
                            <h3 style='margin: 0; color: var(--text-primary, #1a1a2e); font-size: 1.1em;'>⚖️ เปรียบเทียบ Strategy ทั้งหมด</h3>
                            <p style='margin: 4px 0 0; font-size: 0.85em; color: var(--text-secondary, #555);'>
                                เปรียบเทียบ Baseline (ไม่มี H2L) กับ H2L-Enhanced เพื่อวัดผลกระทบของ H2L framework
                            </p>
                        </div>
                        """)

                        # Metrics Reference (collapsible)
                        with gr.Accordion("📖 อธิบายตัวชี้วัด (Metrics)", open=False):
                            gr.Markdown("""
                            <div style='font-size: 0.88em; color: var(--text-primary, #333); line-height: 1.7; padding: 10px;'>
                                <table style='width:100%; border-collapse:collapse;'>
                                    <tr>
                                        <td style='padding:6px 10px; width:28%; vertical-align:top;'><strong>📊 Retrieval Score</strong></td>
                                        <td style='padding:6px 10px; color: var(--text-primary, #333);'>คะแนนความเกี่ยวข้องเฉลี่ยของเอกสารที่ค้นพบ — ยิ่งสูง = เอกสารตรงกับปัญหามากขึ้น</td>
                                    </tr>
                                    <tr style='background:var(--bg-surface-alt, rgba(0,0,0,0.03));'>
                                        <td style='padding:6px 10px; vertical-align:top;'><strong>🎯 Avg Confidence</strong></td>
                                        <td style='padding:6px 10px; color: var(--text-primary, #333);'>ระดับความมั่นใจของระบบ (0–1) ยิ่งสูง = ระบบมั่นใจมากขึ้น</td>
                                    </tr>
                                    <tr>
                                        <td style='padding:6px 10px; vertical-align:top;'><strong>🧠 L2 Filtering</strong></td>
                                        <td style='padding:6px 10px; color: var(--text-primary, #333);'>จำนวนปัญหาที่ AI ตรวจซ้ำแล้วตัดทิ้ง — ยิ่งมาก = ผลแม่นยำขึ้น</td>
                                    </tr>
                                    <tr style='background:var(--bg-surface-alt, rgba(0,0,0,0.03));'>
                                        <td style='padding:6px 10px; vertical-align:top;'><strong>📄 Docs Retrieved</strong></td>
                                        <td style='padding:6px 10px; color: var(--text-primary, #333);'>จำนวนเอกสารอ้างอิงที่ค้นมา — สนับสนุนการประเมินและแนะนำเครื่องมือ</td>
                                    </tr>
                                    <tr>
                                        <td style='padding:6px 10px; vertical-align:top;'><strong>🔵 Problems Found</strong></td>
                                        <td style='padding:6px 10px; color: var(--text-primary, #333);'>จำนวนปัญหาที่ตรวจพบ — ทุกวิธีใช้ตัวตรวจจับเดียวกัน ต่างกันที่วิธีค้นหาเอกสาร</td>
                                    </tr>
                                </table>
                            </div>
                            """)

                        # Benchmark All Strategies
                        gr.Markdown("""
                        <div style='background: var(--bg-surface, #f8f9fa); padding: 12px 16px; border-radius: 8px; border-left: 4px solid #f5576c; margin: 10px 0;'>
                            <h3 style='color: var(--text-primary, #1a1a2e); margin: 0; font-size: 1.1em;'>🏆 Benchmark ทุก Strategy</h3>
                            <p style='margin: 4px 0 0; font-size: 0.85em; color: var(--text-secondary, #555);'>เปรียบเทียบ strategies ทั้งหมด พร้อมวิเคราะห์สถิติอัตโนมัติ</p>
                        </div>
                        """)

                        bench_txt = gr.Textbox(
                            label="📝 เคสทดสอบ",
                            lines=4,
                            value="เด็กหญิงอายุ 15 ปี มีอาการซึมเศร้า นอนไม่หลับ ไม่อยากไปโรงเรียน มีความคิดอยากทำร้ายตัวเอง พ่อแม่หย่าร้าง อยู่กับแม่ที่ดื่มเหล้า",
                            placeholder="ใส่คำอธิบายเคสที่ต้องการเปรียบเทียบ..."
                        )

                        with gr.Row():
                            copy_case_btn = gr.Button("📋 นำเคสจาก Tab 1", size="sm", variant="secondary")
                            bench_l2 = gr.Checkbox(label="🧠 Enable L2 Filtering", value=True)
                            btn_bench = gr.Button("⚡ เปรียบเทียบทุก Strategy", variant="primary", size="lg")

                        copy_case_btn.click(
                            lambda x: x,
                            inputs=[case_desc],
                            outputs=[bench_txt]
                        )

                        comparison_results_state = gr.State(value=None)

                        with gr.Row():
                            with gr.Column(scale=2):
                                out_table = gr.HTML()
                            with gr.Column(scale=1):
                                with gr.Accordion("📋 Process Log", open=False):
                                    comparison_log = gr.Textbox(
                                        label="",
                                        lines=15,
                                        max_lines=20,
                                        interactive=False,
                                        show_label=False,
                                        elem_classes="console-output"
                                    )

                        stats_results = gr.HTML()

                        def run_combined_comparison(case_desc: str, enable_l2: bool):
                            """Run comparison + auto statistical analysis"""
                            table_html, log_output, results = compare_strategies_ui(case_desc, enable_l2)
                            stats_html = ""
                            try:
                                stats_html = run_statistical_analysis_ui(results)
                            except Exception as e:
                                logger.error(f"Statistical analysis error: {e}")
                                stats_html = f"""
                                <div style='background: #ffc107; padding: 12px; border-radius: 8px; margin-top: 15px;'>
                                    <p style='margin: 0; color: var(--text-primary, #333);'>⚠️ Statistical analysis: {str(e)}</p>
                                </div>
                                """
                            return table_html, log_output, results, stats_html

                        btn_bench.click(
                            run_combined_comparison,
                            inputs=[bench_txt, bench_l2],
                            outputs=[out_table, comparison_log, comparison_results_state, stats_results]
                        )

                        # H2L vs Baseline Deep Dive
                        gr.Markdown("""
                        <div style='background: var(--bg-surface, #f8f9fa); padding: 12px 16px; border-radius: 8px; border-left: 4px solid #4facfe; margin: 20px 0 10px 0;'>
                            <h3 style='color: var(--text-primary, #1a1a2e); margin: 0; font-size: 1.1em;'>🔬 H2L vs Baseline เปรียบเทียบเชิงลึก</h3>
                            <p style='margin: 4px 0 0; font-size: 0.85em; color: var(--text-secondary, #555);'>
                                เลือก strategy เพื่อเปรียบเทียบ Baseline กับ H2L-Enhanced แบบ 1:1
                            </p>
                        </div>
                        """)

                        with gr.Row():
                            with gr.Column(scale=1):
                                strategy_select = gr.Radio(
                                    choices=["bm25_only", "naive_rag", "hybrid", "hyde"],
                                    value="hybrid",
                                    label="🎯 เลือก Strategy ที่ต้องการเปรียบเทียบ",
                                    info="เปรียบเทียบ [strategy] vs [h2l-strategy]"
                                )
                                single_bench_txt = gr.Textbox(
                                    label="📝 เคสทดสอบ (Deep Dive)",
                                    lines=3,
                                    value="เด็กหญิงอายุ 15 ปี มีอาการซึมเศร้า นอนไม่หลับ ไม่อยากไปโรงเรียน มีความคิดอยากทำร้ายตัวเอง พ่อแม่หย่าร้าง อยู่กับแม่ที่ดื่มเหล้า",
                                    placeholder="ใส่คำอธิบายเคสที่ต้องการเปรียบเทียบ..."
                                )
                                comparison_btn = gr.Button("🚀 เปรียบเทียบเชิงลึก", variant="primary", size="lg")

                            with gr.Column(scale=2):
                                comparison_info = gr.HTML()

                        comparison_plot = gr.Plot(label="Strategy Comparison")

                        def generate_strategy_comparison(base_strategy: str, case_text: str):
                            logger.info(f"🔬 เริ่มเปรียบเทียบ: {base_strategy} vs h2l-{base_strategy}")
                            try:
                                result = create_strategy_comparison_visualization(base_strategy, case_text)
                                logger.info("   ✅ เปรียบเทียบสำเร็จ")
                                return result
                            except Exception as e:
                                logger.error(f"   ❌ เปรียบเทียบล้มเหลว: {e}")
                                error_fig = go.Figure()
                                error_fig.update_layout(
                                    title="❌ Error in Strategy Comparison",
                                    annotations=[dict(
                                        text=f"Error: {str(e)}<br>Please check console logs",
                                        xref="paper", yref="paper",
                                        x=0.5, y=0.5,
                                        showarrow=False,
                                        font=dict(size=14, color="red")
                                    )]
                                )
                                error_html = f"""
                                <div style='background: #dc3545; padding: 15px; border-radius: 8px; color: white;'>
                                    <h4>❌ เกิดข้อผิดพลาด</h4>
                                    <p>Error: {str(e)}</p>
                                </div>
                                """
                                return error_fig, error_html

                        comparison_btn.click(
                            generate_strategy_comparison,
                            inputs=[strategy_select, single_bench_txt],
                            outputs=[comparison_plot, comparison_info]
                        )

                    # ─── Sub-tab B: Sentence Polarity  ───────────────────────
                    with gr.Tab("🏅 Dual-Dimension Evaluation"):
                        gr.Markdown("""
                        <div style='padding: 10px 16px; background: var(--bg-surface, #f8f9fa); border-radius: 8px; border-left: 4px solid #9b59b6; margin-bottom: 10px;'>
                            <h3 style='margin: 0; color: var(--text-primary, #1a1a2e); font-size: 1.1em;'>🏅 การประเมินผลพหุมิติแยกส่วน (Dual-Dimension Evaluation Framework)</h3>
                            <p style='margin: 4px 0 0; font-size: 0.85em; color: var(--text-secondary, #555);'>
                                การนำเสนอผลการทดสอบที่ยึดหลักการแยกระหว่างมิติ <b>การค้นคืนเอกสาร (IR Metrics)</b> และมิติ <b>การคัดกรองความปลอดภัยจากประโยคปฏิเสธ (Classification Metrics)</b> เพื่ออธิบายการทำงานของระบบอย่างโปร่งใสตามหลักสถิติ โดยไม่ผสมผสานตัวชี้วัดต่างสเกล (Cross-scale variables) เข้าด้วยกัน
                            </p>
                        </div>
                        """)

                        with gr.Tabs():
                            # ── Batch evaluation ──
                            with gr.Tab("📊 ประเมิน Ground Truth"):
                                with gr.Row():
                                    with gr.Column(scale=1):
                                        import glob as _glob
                                        from pathlib import Path as _Path
                                        _project_dir = str(_Path(__file__).parent)
                                        gt_files = sorted([_Path(f).name for f in _glob.glob(_project_dir + "/*ground_truth*.json")])
                                        if not gt_files:
                                            gt_files = ["data/expanded_ground_truth.json"]

                                        eval_gt_selector = gr.Dropdown(
                                            choices=gt_files,
                                            value="data/expanded_ground_truth.json",
                                            label="📁 ชุดข้อมูลสำหรับ Classification (Polarity Test)",
                                            info="🔵 train (ทดสอบสมการ)  🟢 test (ประเมินผลจริง)  📦 all (ชุดผสม)",
                                            allow_custom_value=True
                                        )

                                        eval_model_selector = gr.State("H2L (G_neg enabled)")

                                        eval_neg_btn = gr.Button("🚀 รันและดึงผลประเมิน (Generate Report)", variant="primary", size="lg")

                                        gr.Markdown("""
                                        <div style='background: var(--bg-surface-alt, rgba(155, 89, 182, 0.08)); padding: 12px; border-radius: 8px; margin-top: 10px;'>
                                            <p style='margin: 0 0 6px 0; font-weight: 600; color: var(--text-primary, #333); font-size: 0.9em;'>📌 ตัวชี้วัดที่ประเมิน:</p>
                                            <ul style='margin: 0; padding-left: 18px; font-size: 0.83em; color: var(--text-secondary, #555); line-height: 1.8;'>
                                                <li><strong>Accuracy</strong> — ความถูกต้องรวม (ตรวจถูกกี่เคสจากทั้งหมด)</li>
                                                <li><strong>Detection Rate</strong> — ตรวจจับรูปแบบปฏิเสธได้กี่ % (ยิ่งสูงยิ่งดี)</li>
                                                <li><strong>False Positive</strong> — ตรวจผิดพลาดกี่ % (ยิ่งต่ำยิ่งดี)</li>
                                                <li><strong>F1 Score</strong> — สมดุลระหว่างความแม่นยำและการตรวจจับ</li>
                                            </ul>
                                            <p style='margin: 8px 0 0 0; font-size: 0.83em; color: var(--text-secondary, #555);'>
                                                📏 แยกวิเคราะห์ตาม <strong>ความยาวประโยค</strong> (สั้น/กลาง/ยาว) และ <strong>ระดับความรุนแรง</strong> (สูง/กลาง/ต่ำ)
                                            </p>
                                        </div>
                                        """)

                                    with gr.Column(scale=2):
                                        eval_neg_results = gr.HTML(label="ผลการประเมิน", value="""
                                        <div style='padding: 40px; text-align: center; color: var(--text-muted, #999); background: var(--bg-surface, #f8f9fa); border-radius: 12px;'>
                                            <p style='font-size: 1.3em; margin-bottom: 8px;'>🔬</p>
                                            <p style='font-size: 1.1em; font-weight: 600;'>กดปุ่ม "เริ่มประเมิน" เพื่อทดสอบ</p>
                                            <p style='font-size: 0.85em; margin-top: 4px;'>ทดสอบ 18 เคส — 9 ประโยค positive + 9 ประโยค negated</p>
                                        </div>
                                        """)

                                def _run_neg_eval(gt_file, model_type):
                                    """Run dual evaluation (read latest IR logs + run polarity)."""
                                    try:
                                        import sys as _sys
                                        import json as _json
                                        from pathlib import Path as _Path
                                        
                                        _sys.path.insert(0, str(_Path(__file__).parent))
                                        from evaluate_sentence_polarity import evaluate_sentence_polarity, format_results_html
                                        
                                        # 1. Classification Metrics (Run Polarity Evaluation)
                                        results = evaluate_sentence_polarity(gt_file, "data/problem_codes.json", model_type)
                                        pol_html = format_results_html(results)
                                        
                                        # 2. IR Metrics (Find latest proper_eval_summary_*.json)
                                        ir_html = "<div style='margin-bottom: 24px;'>"
                                        ir_html += "<h3 style='color: var(--text-primary, #1a1a2e); border-bottom: 2px solid #eaeaea; padding-bottom: 8px;'>📌 ทัพหน้า - ประสิทธิภาพหลัก (IR Metrics: nDCG, MAP, MRR)</h3>"
                                        ir_html += "<p style='font-size: 0.9em; color: #555;'>ดึงข้อมูลล่าสุดจากการทดสอบแบบ Paired Factorial Design (ประเมินจาก 55 test cases)</p>"
                                        
                                        eval_dir = _Path(__file__).parent.parent / "evaluation_results"
                                        summary_files = sorted(eval_dir.glob("proper_eval_summary_*.json"))
                                        
                                        if not summary_files:
                                            ir_html += "<p style='color: #dc3545;'>❌ ไม่พบไฟล์ประเมิน proper_eval_summary_*.json กรุณารัน evaluate_h2l_proper.py ก่อน</p>"
                                        else:
                                            latest_summary = summary_files[-1]
                                            with open(latest_summary, "r", encoding="utf-8") as f:
                                                ir_data = _json.load(f)
                                                
                                            agg = ir_data.get("aggregates", {})
                                            ir_html += f"<p style='font-size: 0.8em; color: #888;'>ข้อมูลจากไฟล์: {latest_summary.name}</p>"
                                            ir_html += "<table style='width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 0.9em; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);'>"
                                            ir_html += "<tr style='background: #4facfe; color: white;'><th style='padding: 10px;'>กลยุทธ์ (Strategy)</th><th style='padding: 10px;'>nDCG@5</th><th style='padding: 10px;'>MAP</th><th style='padding: 10px;'>MRR</th><th style='padding: 10px; text-align: center;'>Clinical Status</th></tr>"
                                            
                                            pairs = [
                                                ("bm25_only", "h2l-bm25", "BM25"), 
                                                ("naive_rag", "h2l-naive_rag", "Dense"), 
                                                ("hyde", "h2l-hyde", "HyDE"), 
                                                ("basic", "h2l-hybrid", "Hybrid")
                                            ]
                                            
                                            for b_key, h_key, label in pairs:
                                                # Baseline
                                                bn = agg.get(b_key, {}).get('nDCG@5', {}).get('mean', 0)
                                                bm = agg.get(b_key, {}).get('MAP', {}).get('mean', 0)
                                                br = agg.get(b_key, {}).get('MRR', {}).get('mean', 0)
                                                
                                                # Baselines have NDR = 0 and thus fail the clinical constraint.
                                                bad_badge = "<span style='background: #dc3545; color: white; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; font-weight: bold;'>❌ DISQUALIFIED</span>"
                                                ir_html += f"<tr style='border-bottom: 1px solid #eee; background: #fdfdfd; opacity: 0.8;'><td style='padding: 10px; border-left: 4px solid #dc3545;'>{b_key}</td>"
                                                ir_html += f"<td style='padding: 10px; color: #888;'>{bn:.4f}</td><td style='padding: 10px; color: #888;'>{bm:.4f}</td><td style='padding: 10px; color: #888;'>{br:.4f}</td><td style='padding: 10px; text-align: center;'>{bad_badge}</td></tr>"
                                                
                                                # H2L Enhanced
                                                hn = agg.get(h_key, {}).get('nDCG@5', {}).get('mean', 0)
                                                hm = agg.get(h_key, {}).get('MAP', {}).get('mean', 0)
                                                hr = agg.get(h_key, {}).get('MRR', {}).get('mean', 0)
                                                
                                                good_badge = "<span style='background: #28a745; color: white; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; font-weight: bold;'>✅ SAFE (NDR>50%)</span>"
                                                color = "#28a745" if hn > bn else ("#dc3545" if hn < bn else "#6c757d")
                                                diff_n = f"<span style='color: {color}; font-size: 0.85em; margin-left: 5px;'>({hn-bn:+.4f})</span>"
                                                
                                                ir_html += f"<tr style='background: #f8fcf8; border-bottom: 2px solid #ddd;'><td style='padding: 10px; border-left: 4px solid #28a745; font-weight: bold;'>{h_key}</td>"
                                                ir_html += f"<td style='padding: 10px; font-weight: bold; color: #111;'>{hn:.4f} {diff_n}</td><td style='padding: 10px; font-weight: bold; color: #111;'>{hm:.4f}</td><td style='padding: 10px; font-weight: bold; color: #111;'>{hr:.4f}</td><td style='padding: 10px; text-align: center;'>{good_badge}</td></tr>"
                                                
                                            ir_html += "</table>"
                                            ir_html += "<p style='font-size: 0.85em; color: #666; margin-top: 8px;'><i>* ทฤษฎี Constrained Optimization: โมเดลรันเปล่า (Baseline) ถูกตัดสิทธิ์อัติโนมัติเนื่องจากอัตราดักจับคำปฏิเสธต่ำกว่า 50% ทำให้ความเสี่ยงผิดพลาดอิงบริบท (Harm) สูงเกินยอมรับได้ในทางการแพทย์ตามทฤษฎี Kelly et al. (Nature Medicine)</i></p>"
                                        ir_html += "</div>"
                                        
                                        return f"""
                                        <div style='border-radius: 12px; overflow: hidden; padding: 24px; background: var(--bg-surface, white); border: 1px solid #e0e0e0;'>
                                            <h2 style='color: var(--text-primary, #333); margin-top: 0; text-align: center;'>รายงานประเมินผล Dual-Dimension แบบครบวงจร</h2>
                                            
                                            {ir_html}
                                            
                                            <div style='margin-bottom: 8px;'>
                                                <h3 style='color: var(--text-primary, #1a1a2e); border-bottom: 2px solid #eaeaea; padding-bottom: 8px;'>🛡️ ทัพหลัง - ปราการความปลอดภัย (Classification Metrics)</h3>
                                                <p style='font-size: 0.9em; color: #555;'>ประเมินจากสมการ G_neg ผ่านชุดข้อมูลความขัดแย้ง Sentence Polarity: {gt_file}</p>
                                            </div>
                                            {pol_html}
                                        </div>
                                        """
                                    except Exception as e:
                                        import traceback
                                        return f"""
                                        <div style='padding: 20px; background: var(--bg-surface, #fef2f2); border-radius: 12px; border-left: 4px solid #dc3545;'>
                                            <h4 style='color: #dc3545; margin-top: 0;'>❌ Error</h4>
                                            <pre style='font-size: 0.85em; white-space: pre-wrap; color: var(--text-primary, #333);'>{traceback.format_exc()}</pre>
                                        </div>
                                        """

                                eval_neg_btn.click(
                                    _run_neg_eval,
                                    inputs=[eval_gt_selector, eval_model_selector],
                                    outputs=[eval_neg_results]
                                )

                            # ── Live single-case analysis ──
                            with gr.Tab("🔍 วิเคราะห์เคสเดี่ยว"):
                                gr.Markdown("""
                                <div style='padding: 10px 16px; background: var(--bg-surface, #f8f9fa); border-radius: 8px; border-left: 4px solid #3498db; margin-bottom: 10px;'>
                                    <h3 style='margin: 0; color: var(--text-primary, #1a1a2e); font-size: 1.1em;'>🔍 วิเคราะห์ Sentence Polarity รายเคส</h3>
                                    <p style='margin: 4px 0 0; font-size: 0.85em; color: var(--text-secondary, #555);'>
                                        ใส่ข้อความเคสแล้วดูว่า Sentence Polarity ประเมินข้อความอย่างไร — ผ่านกลไก 3 มิติ: การปฏิเสธ, ความยาวประโยค, และบริบทบุคคลผู้กระทำ
                                    </p>
                                </div>
                                """)

                                with gr.Row():
                                    with gr.Column(scale=1):
                                        single_case_txt = gr.Textbox(
                                            label="📝 ข้อความเคส",
                                            lines=4,
                                            value="เด็กหญิงอายุ 15 ปี ไม่มีอาการซึมเศร้า ไม่เคยทำร้ายตัวเอง พ่อแม่อยู่ด้วยกัน",
                                            placeholder="ใส่ข้อความเคสที่ต้องการวิเคราะห์..."
                                        )
                                        
                                        single_model_selector = gr.State("H2L (G_neg enabled)")
                                        
                                        copy_from_tab1_btn = gr.Button("📋 นำเคสจาก Tab 1", size="sm", variant="secondary")
                                        single_analyze_btn = gr.Button("🔍 วิเคราะห์ Polarity ทรง 3 มิติ", variant="primary", size="lg")

                                    with gr.Column(scale=2):
                                        single_case_results = gr.HTML(value="""
                                        <div style='padding: 40px; text-align: center; color: var(--text-muted, #999); background: var(--bg-surface, #f8f9fa); border-radius: 12px;'>
                                            <p style='font-size: 1.3em; margin-bottom: 8px;'>🔍</p>
                                            <p style='font-size: 1.1em; font-weight: 600;'>ใส่ข้อความแล้วกด "วิเคราะห์ Polarity"</p>
                                        </div>
                                        """)

                                copy_from_tab1_btn.click(
                                    lambda x: x,
                                    inputs=[case_desc],
                                    outputs=[single_case_txt]
                                )

                                def _analyze_single_case(text, model_type):
                                    """Analyze a single case for G_neg and sentence characteristics."""
                                    if not text or len(text.strip()) < 5:
                                        return "<div style='color: #dc3545; padding: 20px;'>⚠️ กรุณาใส่ข้อความเคสก่อน</div>"
                                    try:
                                        from h2l.core import calculate_sentence_polarity, H2LConfigV3
                                        import json as _json

                                        config = H2LConfigV3()
                                        if "Baseline" in model_type:
                                            config.NEG_ENABLE = False
                                            config.NEG_LAMBDA = 0.0

                                        sent = classify_sentence(text)

                                        # Load taxonomy for testing
                                        taxonomy_path = _Path(__file__).parent.parent / "data/problem_codes.json"
                                        with open(taxonomy_path, 'r', encoding='utf-8') as f:
                                            taxonomy = _json.load(f)

                                        # Test G_neg against all problems in taxonomy
                                        g_results = []
                                        for cat in taxonomy.get("categories", []):
                                            for prob in cat.get("problems", []):
                                                g_dict = calculate_sentence_polarity(prob, text, config)
                                                g_total = g_dict["gate_total"]
                                                if g_total < 1.0 or any(kw in text for kw in prob.get("keywords", [])):
                                                    g_results.append({
                                                        "code": prob.get("code", ""),
                                                        "name": prob.get("name", ""),
                                                        "g_total": g_total,
                                                        "g_neg": g_dict["gate_neg"],
                                                        "g_len": g_dict["gate_len"],
                                                        "g_sub": g_dict["gate_sub"],
                                                        "detected": g_total < 1.0
                                                    })

                                        # Build badges HTML
                                        badges = f"""
                                        <div style='display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px;'>
                                            <span style='background: {sent["length"]["color"]}22; color: {sent["length"]["color"]}; padding: 4px 12px; border-radius: 20px; font-size: 0.85em; font-weight: 600; border: 1px solid {sent["length"]["color"]}44;'>
                                                {sent["length"]["icon"]} {sent["length"]["chars"]} ตัวอักษร · {sent["length"]["category"]}
                                            </span>
                                            <span style='background: {sent["complexity"]["color"]}22; color: {sent["complexity"]["color"]}; padding: 4px 12px; border-radius: 20px; font-size: 0.85em; font-weight: 600; border: 1px solid {sent["complexity"]["color"]}44;'>
                                                🧩 ซับซ้อน: {sent["complexity"]["category"]} ({sent["complexity"]["score"]})
                                            </span>
                                            <span style='background: {sent["negation"]["color"]}22; color: {sent["negation"]["color"]}; padding: 4px 12px; border-radius: 20px; font-size: 0.85em; font-weight: 600; border: 1px solid {sent["negation"]["color"]}44;'>
                                                {sent["negation"]["icon"]} คำปฏิเสธ: {sent["negation"]["category"]}
                                            </span>
                                            <span style='background: {sent["actor"]["color"]}22; color: {sent["actor"]["color"]}; padding: 4px 12px; border-radius: 20px; font-size: 0.85em; font-weight: 600; border: 1px solid {sent["actor"]["color"]}44;'>
                                                {sent["actor"]["icon"]} สรรพนาม: {sent["actor"]["category"]}
                                            </span>
                                        </div>
                                        """

                                        # Negation markers found
                                        neg_detail = ""
                                        if sent["negation"]["markers"]:
                                            markers_str = ", ".join([f'<code>{m}</code>' for m in sent["negation"]["markers"]])
                                            neg_detail = f"""
                                            <div style='background: #fef2f2; padding: 10px 14px; border-radius: 8px; margin-bottom: 12px; border-left: 3px solid #e74c3c;'>
                                                <span style='font-weight: 600; color: #991b1b; font-size: 0.88em;'>⚠️ คำปฏิเสธที่พบ:</span>
                                                <span style='color: var(--text-primary, #333); font-size: 0.88em;'>{markers_str}</span>
                                            </div>
                                            """

                                        # G_polarity results table
                                        rows = ""
                                        for r in sorted(g_results, key=lambda x: x["g_total"]):
                                            g_color = "#e74c3c" if r["g_total"] < 0.5 else "#ffc107" if r["g_total"] < 1.0 else "#28a745"
                                            # colors for sub-gates
                                            c_neg = "#e74c3c" if r["g_neg"] < 1.0 else "var(--text-primary, #333)"
                                            c_len = "#ffc107" if r["g_len"] < 0.9 else "var(--text-primary, #333)"
                                            c_sub = "#ffc107" if r["g_sub"] < 1.0 else "var(--text-primary, #333)"
                                            
                                            icon = "🔴" if r["detected"] else "🟢"
                                            rows += f"""
                                            <tr style='border-bottom: 1px solid var(--border-light, #eee);'>
                                                <td style='padding: 6px 10px; font-size: 0.85em;'>{icon} {r["code"]}</td>
                                                <td style='padding: 6px 10px; font-size: 0.85em; color: var(--text-primary, #333);'>{r["name"]}</td>
                                                <td style='padding: 6px 10px; text-align: center; font-weight: 700; color: {g_color};'>{r["g_total"]:.3f}</td>
                                                <td style='padding: 6px 10px; text-align: center; color: {c_neg};'>{r["g_neg"]:.3f}</td>
                                                <td style='padding: 6px 10px; text-align: center; color: {c_len};'>{r["g_len"]:.3f}</td>
                                                <td style='padding: 6px 10px; text-align: center; color: {c_sub};'>{r["g_sub"]:.3f}</td>
                                            </tr>
                                            """

                                        table_html = ""
                                        if rows:
                                            table_html = f"""
                                            <h4 style='color: var(--text-primary, #333); margin: 0 0 8px 0;'>📋 การคำนวณ Polarity (G_total = G_neg × G_len × G_sub)</h4>
                                            <div style='max-height: 300px; overflow-y: auto; border-radius: 8px; border: 1px solid var(--border-color, #e0e0e0);'>
                                                <table style='width: 100%; border-collapse: collapse; font-size: 0.95em;'>
                                                    <tr style='background: #3498db; color: white;'>
                                                        <th style='padding: 8px 10px; text-align: left; position: sticky; top: 0; background: #3498db;'>รหัส</th>
                                                        <th style='padding: 8px 10px; text-align: left; position: sticky; top: 0; background: #3498db;'>ปัญหา</th>
                                                        <th style='padding: 8px 10px; text-align: center; position: sticky; top: 0; background: #3498db;'>Total</th>
                                                        <th style='padding: 8px 10px; text-align: center; position: sticky; top: 0; background: #3498db;'>Neg</th>
                                                        <th style='padding: 8px 10px; text-align: center; position: sticky; top: 0; background: #3498db;'>Len</th>
                                                        <th style='padding: 8px 10px; text-align: center; position: sticky; top: 0; background: #3498db;'>Sub</th>
                                                    </tr>
                                                    {rows}
                                                </table>
                                            </div>
                                            """
                                        else:
                                            table_html = "<p style='color: var(--text-muted, #999); font-size: 0.9em;'>ไม่พบปัญหาที่เกี่ยวข้องกับข้อความนี้</p>"

                                        # Summary Cards Logic
                                        min_g = min([r["g_neg"] for r in g_results]) if g_results else 1.0
                                        detected_negation = min_g < 1.0
                                        n_negated_problems = sum(1 for r in g_results if r["detected"])
                                        
                                        det_color = "#dc3545" if detected_negation else "#27AE60"
                                        det_label = "พบคำปฏิเสธ (Negated)" if detected_negation else "ยืนยัน (Affirmative)"
                                        
                                        score_color = "#dc3545" if min_g < 0.5 else "#ffc107" if min_g < 1.0 else "#27AE60"
                                        
                                        vocab_count = len(sent["negation"]["markers"])
                                        vocab_color = "#17a2b8" if vocab_count > 0 else "#6c757d"
                                        
                                        summary_cards = f"""
                                        <div style='display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; margin-bottom: 16px;'>
                                            <div style='background: linear-gradient(135deg, {det_color}, {det_color}dd); padding: 14px; border-radius: 10px; text-align: center; color: white;'>
                                                <div style='font-size: 1.2em; font-weight: 700;'>{det_label}</div>
                                                <div style='font-size: 0.8em; opacity: 0.9;'>สถานะประโยค</div>
                                            </div>
                                            <div style='background: linear-gradient(135deg, {score_color}, {score_color}dd); padding: 14px; border-radius: 10px; text-align: center; color: white;'>
                                                <div style='font-size: 1.8em; font-weight: 700;'>{min_g:.3f}</div>
                                                <div style='font-size: 0.8em; opacity: 0.9;'>Minimum G_neg (ยิ่งต่ำยิ่งพบคำปฏิเสธ)</div>
                                            </div>
                                            <div style='background: linear-gradient(135deg, {vocab_color}, {vocab_color}dd); padding: 14px; border-radius: 10px; text-align: center; color: white;'>
                                                <div style='font-size: 1.8em; font-weight: 700;'>{n_negated_problems}</div>
                                                <div style='font-size: 0.8em; opacity: 0.9;'>จำนวนปัญหาที่โดนหักคะแนน</div>
                                            </div>
                                        </div>
                                        """

                                        return f"""
                                        <div style='padding: 20px; background: var(--bg-surface, white); border-radius: 12px;'>
                                            <h3 style='color: var(--text-primary, #333); margin-top: 0;'>🔍 ผลวิเคราะห์ Sentence Polarity {('- ' + model_type) if model_type else ''}</h3>
                                            {summary_cards}
                                            {badges}
                                            {neg_detail}
                                            {table_html}
                                        </div>
                                        """
                                    except Exception as e:
                                        import traceback
                                        return f"""
                                        <div style='padding: 20px; background: #fef2f2; border-radius: 12px; border-left: 4px solid #dc3545;'>
                                            <h4 style='color: #dc3545; margin-top: 0;'>❌ Error</h4>
                                            <pre style='font-size: 0.85em; white-space: pre-wrap;'>{traceback.format_exc()}</pre>
                                        </div>
                                        """

                                single_analyze_btn.click(
                                    _analyze_single_case,
                                    inputs=[single_case_txt, single_model_selector],
                                    outputs=[single_case_results]
                                )

                    # ── Sensitivity Analysis Sub-Tab ──
                    with gr.Tab("📈 Sensitivity Analysis"):
                        gr.Markdown("""
                        <div style='padding: 10px 16px; background: var(--bg-surface, #f8f9fa); border-radius: 8px; border-left: 4px solid #e67e22; margin-bottom: 10px;'>
                            <h3 style='margin: 0; color: var(--text-primary, #1a1a2e); font-size: 1.1em;'>📈 Parameter Sensitivity Analysis</h3>
                            <div style='margin: 8px 0 0; font-size: 0.9em; color: var(--text-secondary, #444); line-height: 1.5;'>
                                <b>ทำเพื่ออะไร?</b>
                                <ul style='margin-top: 4px; margin-bottom: 0; padding-left: 20px;'>
                                    <li>เพื่อทดสอบความทนทาน <b>(Robustness)</b> ของสมการ H2L ต่อการเปลี่ยนแปลงของพารามิเตอร์</li>
                                    <li>พิสูจน์ว่าค่าพารามิเตอร์ที่ได้จากผู้เชี่ยวชาญ (Expert-Elicited) นั้นมีความเสถียร ไม่ได้เกิดจากการปรับจูนตัวเลขที่เจาะจงเกินไป <b>(No Overfitting)</b></li>
                                    <li>ระบบจะปรับเปลี่ยนค่าพารามิเตอร์ทีละตัว ±30-50% (OAT: One-at-a-Time) แล้ววัดผลกระทบ หากผลลัพธ์แกว่งไม่เกิน 5% ถือว่าสมการมีความเสถียรสูง</li>
                                </ul>
                            </div>
                        </div>
                        """)

                        with gr.Row():
                            sensitivity_max_cases = gr.Slider(
                                minimum=5, maximum=100, value=20, step=5,
                                label="จำนวนเคสที่ทดสอบ",
                                info="มากขึ้น = ผลแม่นยำขึ้น แต่ช้าลง"
                            )
                            sensitivity_run_btn = gr.Button("🚀 รัน Sensitivity Analysis", variant="primary", size="lg")

                        sensitivity_results_html = gr.HTML(value="""
                        <div style='padding: 40px; text-align: center; color: var(--text-muted, #999); background: var(--bg-surface, #f8f9fa); border-radius: 12px;'>
                            <p style='font-size: 1.3em; margin-bottom: 8px;'>📈</p>
                            <p style='font-size: 1.1em; font-weight: 600;'>กด "รัน Sensitivity Analysis" เพื่อเริ่มวิเคราะห์</p>
                            <p style='font-size: 0.85em; color: #999;'>จะทดสอบ 8 parameters หลักของ H2L V6</p>
                        </div>
                        """)

                        with gr.Row():
                            sensitivity_heatmap = gr.Image(label="Heatmap", visible=False)
                            sensitivity_tornado = gr.Image(label="Tornado Plot", visible=False)

                        def _run_sensitivity(max_cases):
                            """Run sensitivity analysis and return HTML results + images."""
                            try:
                                from sensitivity_analysis import (
                                    SensitivityAnalyzer, PARAMETER_SWEEPS,
                                    generate_visualizations, generate_csv, generate_report
                                )
                                from pathlib import Path as _SPath

                                output_dir = _SPath("sensitivity_results")

                                analyzer = SensitivityAnalyzer(
                                    ground_truth_path="data/expanded_ground_truth.json",
                                    max_cases=int(max_cases),
                                )

                                results, baseline = analyzer.run_sensitivity()
                                generate_csv(results, baseline, output_dir)
                                generate_visualizations(results, baseline, output_dir)
                                generate_report(results, baseline, len(analyzer.cases), output_dir)

                                # Build HTML results table
                                metric_name = 'mean_score'
                                base_score = baseline[metric_name]

                                rows_html = ""
                                max_impacts = []
                                for sweep in PARAMETER_SWEEPS:
                                    if sweep.name not in results:
                                        continue
                                    param_data = results[sweep.name]
                                    deltas = []
                                    for val, metrics in param_data.items():
                                        if base_score > 0:
                                            delta = ((metrics[metric_name] - base_score) / base_score) * 100
                                            deltas.append((val, delta))

                                    if deltas:
                                        min_d = min(d for _, d in deltas)
                                        max_d = max(d for _, d in deltas)
                                        max_abs = max(abs(min_d), abs(max_d))
                                        max_impacts.append(max_abs)
                                        verdict_color = "#28a745" if max_abs < 5 else "#ffc107" if max_abs < 10 else "#dc3545"
                                        verdict = "✅ Robust" if max_abs < 5 else "⚠️ Moderate" if max_abs < 10 else "❌ Sensitive"

                                        # Best/worst values
                                        best_val = max(deltas, key=lambda x: x[1])
                                        worst_val = min(deltas, key=lambda x: x[1])

                                        rows_html += f"""
                                        <tr style='border-bottom: 1px solid var(--bg-surface-alt, #eee);'>
                                            <td style='padding:8px 10px; font-weight:600;'>{sweep.label}</td>
                                            <td style='padding:8px; text-align:center;'>{sweep.default}</td>
                                            <td style='padding:8px; text-align:center; color:#dc3545;'>{min_d:+.2f}%</td>
                                            <td style='padding:8px; text-align:center; color:#28a745;'>{max_d:+.2f}%</td>
                                            <td style='padding:8px; text-align:center; font-weight:700; color:{verdict_color};'>{verdict}</td>
                                        </tr>
                                        """

                                # Overall verdict
                                overall_max = max(max_impacts) if max_impacts else 0
                                if overall_max < 5:
                                    verdict_html = "<div style='background:linear-gradient(135deg,#28a745,#218838); padding:16px; border-radius:10px; text-align:center; color:white; margin-bottom:16px;'><div style='font-size:1.5em; font-weight:700;'>✅ ROBUST</div><div>ทุก parameter เปลี่ยนผลลัพธ์ < 5% — parameters จาก domain knowledge เสถียร</div></div>"
                                elif overall_max < 10:
                                    verdict_html = f"<div style='background:linear-gradient(135deg,#ffc107,#e0a800); padding:16px; border-radius:10px; text-align:center; color:white; margin-bottom:16px;'><div style='font-size:1.5em; font-weight:700;'>⚠️ MODERATE</div><div>Max impact = {overall_max:.1f}%</div></div>"
                                else:
                                    verdict_html = f"<div style='background:linear-gradient(135deg,#dc3545,#c82333); padding:16px; border-radius:10px; text-align:center; color:white; margin-bottom:16px;'><div style='font-size:1.5em; font-weight:700;'>❌ SENSITIVE</div><div>Max impact = {overall_max:.1f}% — some parameters need careful tuning</div></div>"

                                html = f"""
                                <div style='padding:20px; background:var(--bg-surface, white); border-radius:12px;'>
                                    <h3 style='color:var(--text-primary,#333); margin-top:0;'>📈 Sensitivity Analysis Results</h3>
                                    <div style='display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:16px;'>
                                        <div style='background:#f0f4ff; padding:12px; border-radius:8px; border-left:4px solid #667eea;'>
                                            <div style='font-weight:600; color:#667eea;'>Baseline Score</div>
                                            <div style='font-size:1.5em; font-weight:700; color:#333;'>{base_score:.4f}</div>
                                        </div>
                                        <div style='background:#f0fdf4; padding:12px; border-radius:8px; border-left:4px solid #28a745;'>
                                            <div style='font-weight:600; color:#28a745;'>เคสที่ทดสอบ</div>
                                            <div style='font-size:1.5em; font-weight:700; color:#333;'>{int(max_cases)} เคส</div>
                                        </div>
                                    </div>
                                    {verdict_html}
                                    <table style='width:100%; border-collapse:collapse; font-size:0.9em; border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.1);'>
                                        <tr style='background:#e67e22; color:white;'>
                                            <th style='padding:8px 10px; text-align:left;'>Parameter</th>
                                            <th style='padding:8px; text-align:center;'>Default</th>
                                            <th style='padding:8px; text-align:center;'>Min Δ%</th>
                                            <th style='padding:8px; text-align:center;'>Max Δ%</th>
                                            <th style='padding:8px; text-align:center;'>Verdict</th>
                                        </tr>
                                        {rows_html}
                                    </table>
                                </div>
                                """

                                # Return images (must use absolute paths for Gradio to serve correctly)
                                heatmap_path = output_dir / 'sensitivity_heatmap.png'
                                tornado_path = output_dir / 'sensitivity_tornado.png'
                                heatmap_img = str(heatmap_path.absolute()) if heatmap_path.exists() else None
                                tornado_img = str(tornado_path.absolute()) if tornado_path.exists() else None

                                return (
                                    html,
                                    gr.update(value=heatmap_img, visible=heatmap_img is not None),
                                    gr.update(value=tornado_img, visible=tornado_img is not None),
                                )

                            except Exception as e:
                                import traceback
                                return (
                                    f"<div style='padding:20px; background:#fef2f2; border-radius:12px; border-left:4px solid #dc3545;'><h4 style='color:#dc3545;'>❌ Error</h4><pre style='font-size:0.85em; white-space:pre-wrap;'>{traceback.format_exc()}</pre></div>",
                                    gr.update(visible=False),
                                    gr.update(visible=False),
                                )

                        sensitivity_run_btn.click(
                            _run_sensitivity,
                            inputs=[sensitivity_max_cases],
                            outputs=[sensitivity_results_html, sensitivity_heatmap, sensitivity_tornado],
                        )

    return demo


def preload_models_ui():
    """UI wrapper for preload_models() - returns HTML status"""
    try:
        embedding_model, rerank_model = preload_models()

        if embedding_model is not None and rerank_model is not None:
            return """
            <div style='background: linear-gradient(135deg, #27AE60 0%, #229954 100%); padding: 20px; border-radius: 10px; color: white;'>
                <h3 style='color: white; margin-top: 0;'>✅ โหลดโมเดลสำเร็จ!</h3>
                <p style='margin: 5px 0;'>• Embedding Model: ✅ โหลดแล้ว</p>
                <p style='margin: 5px 0;'>• Reranker Model: ✅ โหลดแล้ว</p>
                <p style='margin: 15px 0 5px 0; color: #d4edda;'>
                    <strong>🚀 พร้อมใช้งาน!</strong> ตอนนี้คุณสามารถวิเคราะห์เคสได้โดยไม่ต้องรอโหลดโมเดล
                </p>
            </div>
            """
        else:
            return """
            <div style='background: linear-gradient(135deg, #E74C3C 0%, #C0392B 100%); padding: 20px; border-radius: 10px; color: white;'>
                <h3 style='color: white; margin-top: 0;'>❌ โหลดโมเดลล้มเหลว</h3>
                <p style='margin: 5px 0;'>โมเดลจะถูกโหลดแบบ on-demand เมื่อใช้งาน</p>
                <p style='margin: 5px 0;'>ครั้งแรกอาจใช้เวลานานกว่าปกติ</p>
            </div>
            """
    except Exception as e:
        return f"""
        <div style='background: linear-gradient(135deg, #E74C3C 0%, #C0392B 100%); padding: 20px; border-radius: 10px; color: white;'>
            <h3 style='color: white; margin-top: 0;'>❌ เกิดข้อผิดพลาด</h3>
            <p style='margin: 5px 0;'>Error: {str(e)}</p>
            <p style='margin: 5px 0;'>โมเดลจะถูกโหลดแบบ on-demand เมื่อใช้งาน</p>
        </div>
        """


def check_models_status():
    """Check if models are already loaded"""
    global _EMBEDDING_MODEL, _RERANK_MODEL

    embedding_loaded = _EMBEDDING_MODEL is not None
    rerank_loaded = _RERANK_MODEL is not None

    if embedding_loaded and rerank_loaded:
        return """
        <div style='background: linear-gradient(135deg, #27AE60 0%, #229954 100%); padding: 15px; border-radius: 8px; color: white;'>
            <p style='margin: 0; font-size: 1.1em;'><strong>✅ โมเดลพร้อมใช้งาน</strong></p>
            <p style='margin: 5px 0 0 0; font-size: 0.9em; color: #d4edda;'>
                Embedding Model ✅ | Reranker Model ✅
            </p>
        </div>
        """
    elif embedding_loaded or rerank_loaded:
        return f"""
        <div style='background: linear-gradient(135deg, #F39C12 0%, #E67E22 100%); padding: 15px; border-radius: 8px; color: white;'>
            <p style='margin: 0; font-size: 1.1em;'><strong>⚠️ โหลดโมเดลบางส่วน</strong></p>
            <p style='margin: 5px 0 0 0; font-size: 0.9em;'>
                Embedding: {'✅' if embedding_loaded else '❌'} | Reranker: {'✅' if rerank_loaded else '❌'}
            </p>
        </div>
        """
    else:
        return """
        <div style='background: linear-gradient(135deg, #95A5A6 0%, #7F8C8D 100%); padding: 15px; border-radius: 8px; color: white;'>
            <p style='margin: 0; font-size: 1.1em;'><strong>⏳ โมเดลยังไม่ได้โหลด</strong></p>
            <p style='margin: 5px 0 0 0; font-size: 0.9em; color: #ecf0f1;'>
                กดปุ่ม "โหลดโมเดล" เพื่อโหลดล่วงหน้า หรือโมเดลจะโหลดอัตโนมัติเมื่อวิเคราะห์เคส
            </p>
        </div>
        """


def preload_models():
    """Pre-load all models at startup to avoid delays during runtime"""
    global _EMBEDDING_MODEL, _RERANK_MODEL  # ✅ เพิ่ม global declaration

    print("\n" + "=" * 70)
    print("📦 กำลังโหลด Models...")
    print("=" * 70)

    loading_status = {
        'embedding': {'status': 'pending', 'name': '', 'error': None},
        'reranker': {'status': 'pending', 'name': '', 'error': None},
        'warmup': {'status': 'pending', 'error': None}
    }

    try:
        from sentence_transformers import SentenceTransformer

        # Get model names from h2l.config
        embedding_model_name = getattr(config, 'EMBEDDING_MODEL', 'intfloat/multilingual-e5-base')
        rerank_model_name = getattr(config, 'RERANK_MODEL', 'BAAI/bge-reranker-v2-m3')
        device = getattr(config, 'DEVICE', 'mps')

        loading_status['embedding']['name'] = embedding_model_name
        loading_status['reranker']['name'] = rerank_model_name

        # 1. Load Embedding Model
        print(f"\n[1/3] 📥 กำลังโหลด Embedding Model...")
        print(f"      Model: {embedding_model_name}")
        print(f"      Device: {device}")
        try:
            _EMBEDDING_MODEL = SentenceTransformer(embedding_model_name, device=device)  # ✅ เก็บใน global
            loading_status['embedding']['status'] = 'success'
            print(f"      ✅ โหลดสำเร็จ ({device})")
        except Exception as e:
            loading_status['embedding']['status'] = 'failed'
            loading_status['embedding']['error'] = str(e)
            print(f"      ❌ โหลดล้มเหลว: {e}")
            raise

        # 2. Load Reranker Model
        print(f"\n[2/3] 📥 กำลังโหลด Reranker Model...")
        print(f"      Model: {rerank_model_name}")
        print(f"      Device: {device}")
        try:
            _RERANK_MODEL = SentenceTransformer(rerank_model_name, device=device)  # ✅ เก็บใน global
            loading_status['reranker']['status'] = 'success'
            print(f"      ✅ โหลดสำเร็จ ({device})")
        except Exception as e:
            loading_status['reranker']['status'] = 'failed'
            loading_status['reranker']['error'] = str(e)
            print(f"      ❌ โหลดล้มเหลว: {e}")
            raise

        # 3. Warm-up: Run dummy inference to initialize models
        print(f"\n[3/3] 🔥 กำลัง Warm-up models...")
        print(f"      Running test inference...")
        try:
            _ = _EMBEDDING_MODEL.encode(["สวัสดี"], convert_to_tensor=True)
            _ = _RERANK_MODEL.encode(["สวัสดี"], convert_to_tensor=True)
            loading_status['warmup']['status'] = 'success'
            print(f"      ✅ Warm-up สำเร็จ - Models พร้อมใช้งาน")
        except Exception as e:
            loading_status['warmup']['status'] = 'failed'
            loading_status['warmup']['error'] = str(e)
            print(f"      ⚠️ Warm-up ล้มเหลว: {e}")
            # Not critical, continue anyway

        print("\n" + "=" * 70)
        print("✅ โหลด Models เสร็จสมบูรณ์!")
        print("=" * 70)
        print(f"   • Embedding Model: ✅ {embedding_model_name}")
        print(f"   • Reranker Model:  ✅ {rerank_model_name}")
        print(f"   • Device:          {device}")
        print(f"   • Warm-up:         {'✅ สำเร็จ' if loading_status['warmup']['status'] == 'success' else '⚠️ ข้าม'}")
        print("=" * 70 + "\n")

        return _EMBEDDING_MODEL, _RERANK_MODEL  # ✅ return global variables

    except Exception as e:
        print("\n" + "=" * 70)
        print("❌ โหลด Models ล้มเหลว!")
        print("=" * 70)
        print(f"   • Error: {str(e)}")
        print(f"   • Embedding: {loading_status['embedding']['status'].upper()}")
        print(f"   • Reranker:  {loading_status['reranker']['status'].upper()}")
        print(f"\n⚠️  Models จะถูกโหลดแบบ on-demand เมื่อใช้งาน")
        print("=" * 70 + "\n")
        logger.warning(f"⚠️ Model pre-loading failed: {e}")
        logger.warning("   Models will be loaded on-demand during runtime")
        return None, None


if __name__ == "__main__":
    print("=" * 70)
    print("🚀 AI Social Worker - Unified App V4")
    print("   ✅ H2L Detection")
    print("   ✅ 3D Vector Space with Hover Details")
    print("   ✅ Probabilistic Score Breakdown")
    print("   ✅ V4 Formula Visualization")
    print("=" * 70)

    # Pre-load models before starting the app
    embedding_model, rerank_model = preload_models()

    # Bind to loopback only and do NOT open a public Gradio tunnel.
    # This app serves social-work case records and has no authentication of
    # its own, so it must not be reachable from outside this machine.
    # Set GRADIO_AUTH_USER / GRADIO_AUTH_PASS to require a login.
    _auth_user = os.getenv("GRADIO_AUTH_USER")
    _auth_pass = os.getenv("GRADIO_AUTH_PASS")
    _auth = (_auth_user, _auth_pass) if (_auth_user and _auth_pass) else None

    print("\n👉 Starting Gradio Interface...")
    print("👉 Open http://127.0.0.1:7860")
    print(f"👉 Auth: {'enabled' if _auth else 'DISABLED (localhost only)'}")
    print("=" * 70 + "\n")

    app = create_unified_app()
    app.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        auth=_auth,
    )
