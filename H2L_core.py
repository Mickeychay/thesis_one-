#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
H2L Core V6 : Generalizable Bayesian Problem-Aware Retrieval Framework
======================================================================

📐 Theoretical Foundation: Query Likelihood Model Extension

Standard Query Likelihood:
    P(d|q) ∝ P(q|d) × P(d)

H2L V5 Extension (Problem-Conditioned, Log-Linear, Enhanced):
    S_final = S_rerank · exp(α_eff · Σ_i  w_i · φ(d, p_i))

where:
    φ(d, p_i) = C(p_i|q) · Ω(d|p_i) · P_smoothed(p_i) · IDF(p_i) · G_neg(p_i)
    w_i        = 1 + γ · CoOccur(p_i, P\\{p_i})       (cross-problem bonus)
    α_eff      = α₀ · (1 + δ · H_severity) · (1 - κ · KL_penalty)

V5 Components (NEW):
    C(p|q)    = P(p|q)^(1/T_i) where T_i = f(severity)   (calibrated confidence)
    Ω(d|p)    = σ((sim(d,p) - m) / τ_Ω)                  (margin-aware activation)
    IDF(p_i)  = log(1 + N / (1 + DF(p_i)))                (document specificity)
    KL_penalty = KL(P_prior || Uniform)                    (concentration regularization)
    G_neg(p_i) = 1 - λ_neg · neg_score(p_i, q)            (negation-aware gating)

V4 Components (retained):
    P_fused(d|p)      = g·P_sem + (1-g)·P_kw   (gated fusion)
    P_smoothed(p)     = (sev + μ·P_bg) / (Σsev + μ)  (Dirichlet smoothing)
    H_severity        = -Σ P(p_i)·log P(p_i)   (Shannon entropy)

📊 Key Improvements (V4 → V5):
    1. Severity-weighted confidence calibration — Platt scaling variant (Platt, 1999)
    2. IDF-inspired document specificity — rare problems = stronger signal (Robertson, 1976)
    3. Margin-aware saturating activation — better discrimination (Schroff et al., 2015)
    4. KL-divergence concentration penalty — prevents score explosion (Kullback & Leibler, 1951)
    5. Negation-aware gating — dampens boost for negated problems

References:
    - Ponte & Croft (1998): Query Likelihood Model
    - Robertson & Zaragoza (2009): Probabilistic Relevance Framework
    - Zhai & Lafferty (2001): Dirichlet Smoothing for Language Models
    - Shannon (1948): Information Theory
    - Platt (1999): Probabilistic Outputs for SVM (confidence calibration)
    - Robertson & Sparck Jones (1976): IDF weighting
    - Schroff et al. (2015): FaceNet — Triplet Loss & Margin Learning
    - Kullback & Leibler (1951): Information and Sufficiency
"""

import math
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

# Default Thai negation markers for negation-aware gating
# Moved to config for generalizability — override via H2LConfigV3.NEGATION_MARKERS
_DEFAULT_NEGATION_MARKERS = [
    'ไม่ได้', 'ไม่มี', 'ไม่เคย', 'ไม่ใช่', 'ไม่พบ',
    'ปฏิเสธ', 'ยังไม่', 'ไม่แสดง', 'ไม่ปรากฏ', 'ไม่',
    'ไร้', 'ปราศจาก', 'ไม่น่า', 'ไม่ค่อย'
]


@dataclass
class H2LConfigV3:
    """Configuration for H2L V5 Enhanced Probabilistic Framework"""

    # Detection (L1 + L2)
    L1_WEIGHT_BETA: float = 0.3  # β in S_detect = β×S_L1 + (1-β)×S_L2

    # Probabilistic Retrieval
    ALPHA: float = 1.0           # Base problem influence weight (α₀)
    TEMPERATURE: float = 0.1     # Softmax temperature for P(d|p)

    # Smoothing (for numerical stability)
    EPSILON: float = 1e-6
    MIN_PRIOR: float = 0.01      # Minimum problem prior

    # V4: Dirichlet-smoothed prior (Enhancement 2)
    DIRICHLET_MU: float = 2.0    # μ — smoothing strength (higher = more uniform)

    # V4: Gated fusion for P(d|p) (Enhancement 1)
    GATE_WEIGHT: float = 5.0     # w_g — controls gate steepness
    GATE_BIAS: float = -1.5      # b_g — gate threshold (negative = prefer semantic)

    # V4: Cross-problem co-occurrence (Enhancement 3)
    CO_OCCURRENCE_GAMMA: float = 0.3  # γ — co-occurrence bonus strength

    # V4: Entropy-conditioned α (Enhancement 4)
    ENTROPY_SCALE_DELTA: float = 0.5  # δ — entropy amplification factor

    # ── V5 Enhancements ──

    # V5.1: Severity-Weighted Confidence Calibration (Platt, 1999)
    CALIBRATION_T_BASE: float = 0.5    # T_base — base temperature for calibration
    CALIBRATION_T_RANGE: float = 1.5   # T_range — range of temperature adjustment
    # T_i = T_BASE + (1 - sev/sev_max) * T_RANGE
    # High severity → lower T → sharper confidence
    # Low severity  → higher T → softer confidence

    # V5.2: IDF-inspired Document Specificity (Robertson & Sparck Jones, 1976)
    IDF_ENABLE: bool = True            # Enable/disable IDF factor
    IDF_CORPUS_SIZE: int = 500         # N — estimated corpus size (updated at runtime)
    IDF_SMOOTH: float = 1.0            # Additive smoothing for DF
    IDF_MAX: float = 3.0               # Maximum IDF value (for clamping & normalization)

    # V5.3: Margin-Aware Saturating Activation (Schroff et al., 2015)
    MARGIN_M: float = 0.3              # m — decision boundary margin
    MARGIN_TAU: float = 0.15           # τ_Ω — temperature for margin activation
    MARGIN_ENABLE: bool = True         # Enable/disable margin-aware Ω(d|p)

    # V5.4: KL-Divergence Concentration Penalty (Kullback & Leibler, 1951)
    KL_KAPPA: float = 0.15             # κ — penalty strength
    KL_MAX: float = 2.0                # Maximum KL penalty value (capped)

    # V5.5: Negation-Aware Gating
    NEG_LAMBDA: float = 0.6            # λ_neg — negation dampening strength
    NEG_ENABLE: bool = True            # Enable/disable negation gating
    NEGATION_MARKERS: list = None      # Language-specific negation markers (default: Thai)

    # ── V6 Enhancements (Generalizable Framework) ──

    # V6.1: Context-Dependent Adaptive α
    # α(C) = α_base · σ(γ · num_problems + δ · avg_confidence)
    ADAPTIVE_ALPHA_ENABLE: bool = True
    ADAPTIVE_ALPHA_GAMMA: float = 0.3   # γ — weight for number of problems
    ADAPTIVE_ALPHA_DELTA: float = 0.5   # δ — weight for average confidence

    # V6.2: Bayesian Prior Integration
    # P(rel | profile) = Σ P(pᵢ) · P(rel | pᵢ)
    BAYESIAN_PRIOR_ENABLE: bool = True
    BAYESIAN_PRIOR_BASE: float = 0.5    # Base prior when no profile data

    # V6.3: Tone Analysis Exception Lexicon (Emotional/Contextual bypass for G_neg)
    TONE_EXCEPTIONS: list = None        # Initialized in __post_init__

    # V6.3: Multi-Granularity Feature Mode
    # 'product' = V5 style (multiply all features)
    # 'weighted_sum' = V6 style (weighted sum of normalized features)
    FEATURE_MODE: str = 'weighted_sum'
    FEATURE_WEIGHTS: dict = None  # Defaults set in __post_init__

    def __post_init__(self):
        if self.FEATURE_WEIGHTS is None:
            self.FEATURE_WEIGHTS = {
                'detect': 0.35,      # C(p|q) — detection confidence
                'semantic': 0.30,    # Ω(d|p) — doc-problem similarity
                'prior': 0.15,       # P(p) — problem prior
                'specificity': 0.10, # IDF(p) — document specificity
                'negation': 0.10,    # G_neg(p) — negation gating
            }
        # Validate weights normalization (V6 fix: prevent silent errors)
        total_w = sum(self.FEATURE_WEIGHTS.values())
        if abs(total_w - 1.0) > 0.01:
            logger.warning(f"FEATURE_WEIGHTS sum={total_w:.4f}, normalizing to 1.0")
            self.FEATURE_WEIGHTS = {k: v / total_w for k, v in self.FEATURE_WEIGHTS.items()}
        # Default negation markers (Thai) — override for other languages
        if self.NEGATION_MARKERS is None:
            self.NEGATION_MARKERS = list(_DEFAULT_NEGATION_MARKERS)
        # Default tone exception lexicons (Sarcasm/Fear/Emotion/Contextual)
        if self.TONE_EXCEPTIONS is None:
            self.TONE_EXCEPTIONS = [
                "ไม่กล้า", "ไม่อยาก", "ไม่มีเงิน", "ไม่มีความสุข",
                "ไม่ได้ตั้งใจ", "ไม่สบายใจ", "ไม่พร้อม", "ไม่เป็นไร",
                "ไม่รู้", "ไม่มีค่า", "ไม่อยากอยู่", "ไม่มีที่ไป",
                "ไม่มีใคร", "ไม่รู้สึก", "ไม่คิด", 
                "ไม่ได้ออกไปไหน", "ไม่มีเพื่อน", "ไม่บอก", "ไม่พูดกัน", "ไม่ได้ทำอะไรผิด",
                "ไม่มีรายได้", "ไม่มีที่อยู่", "ไม่รังเกียจ", "ไม่ได้พักผ่อน",
                "ไม่พอ", "ไม่เข้าใจ", "เข้ากับเพื่อนบ้านไม่ได้",
                "ไม่มีที่", "ไม่รังเกียจสังคม", "ทรุดโทรม"
            ]

    # Query Expansion (retained)
    QUERY_EXPANSION_MAX_PROBLEMS: int = 3
    QUERY_EXPANSION_MAX_KEYWORDS: int = 3

    # Backward compatibility with V2
    PROBLEM_RELEVANCE_WEIGHT: float = 0.2


DEFAULT_CONFIG_V3 = H2LConfigV3()


# =============================================================================
# MATHEMATICAL FUNCTIONS
# =============================================================================

def sigmoid(x: float) -> float:
    """Numerically stable sigmoid function (uses math.exp for scalar speed)"""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    else:
        exp_x = math.exp(x)
        return exp_x / (1.0 + exp_x)


def cosine_similarity(
    vec1: np.ndarray,
    vec2: np.ndarray,
    pre_normalized: bool = False
) -> float:
    """Cosine similarity between two vectors.
    When pre_normalized=True (e.g. from sentence-transformers with
    normalize_embeddings=True), skips norm computation → ~2x faster.
    """
    if vec1 is None or vec2 is None:
        return 0.0
    
    if pre_normalized:
        return float(np.dot(vec1, vec2))
    
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)
    
    if norm1 < 1e-8 or norm2 < 1e-8:
        return 0.0
    
    return float(np.dot(vec1, vec2) / (norm1 * norm2))


# =============================================================================
# PROBLEM PRIOR: Dirichlet-Smoothed (V4)
# P_smoothed(p_i) = (sev_i + μ·P_bg) / (Σ_j sev_j + μ)
# =============================================================================

def calculate_problem_prior(
    problems: List[Dict],
    config: H2LConfigV3 = None
) -> Dict[str, float]:
    """
    Calculate prior probability distribution over problems.
    
    V4 Formula (Dirichlet Smoothing — Zhai & Lafferty 2001):
        P_smoothed(p_i) = (sev_i + μ · P_bg(p_i)) / (Σ_j sev_j + μ)
    
    where:
        μ = DIRICHLET_MU (smoothing strength)
        P_bg(p_i) = 1/|P|  (uniform background)
    
    Benefits:
        - Numerically stable with 1–2 problems (won't allocate 100% to one)
        - Theoretically grounded in language model smoothing
        - μ=0 recovers original V3 MLE behavior
    
    Args:
        problems: List of detected problems with 'code' and 'severity'
        config: Configuration object
    
    Returns:
        Dict mapping problem code to prior probability
    """
    if config is None:
        config = DEFAULT_CONFIG_V3
    
    if not problems:
        return {}
    
    n = len(problems)
    mu = config.DIRICHLET_MU
    p_bg = 1.0 / n  # Uniform background prior
    
    total_severity = sum(p.get('severity', 1) for p in problems)
    
    if total_severity == 0:
        # Uniform prior if no severity info
        return {p.get('code', 'unknown'): p_bg for p in problems}
    
    priors = {}
    for p in problems:
        code = p.get('code', 'unknown')
        severity = p.get('severity', 1)
        # Dirichlet smoothing: (sev_i + μ·P_bg) / (Σsev + μ)
        prior = (severity + mu * p_bg) / (total_severity + mu)
        # Apply minimum prior floor
        priors[code] = max(config.MIN_PRIOR, prior)
    
    # Renormalize to ensure sum = 1
    total = sum(priors.values())
    if total > 0:
        priors = {k: v / total for k, v in priors.items()}
    
    return priors


# =============================================================================
# DETECTION PROBABILITY: P(p|q)
# =============================================================================

def calculate_detection_probability(
    problem: Dict
) -> float:
    """
    Get detection probability P(p|q) from problem detection result
    
    Formula:
        P(p|q) = confidence from L1+L2 detection
    
    The confidence score from H2LDetector already represents:
        S_detect = β × S_L1 + (1-β) × S_L2
    
    We interpret this as P(p|q) - probability that problem p
    exists given query q.
    
    Args:
        problem: Detected problem with 'confidence' field
    
    Returns:
        Detection probability [0, 1]
    """
    confidence = problem.get('confidence', 0.5)
    # Ensure valid probability range
    return max(0.0, min(1.0, confidence))


# =============================================================================
# DOCUMENT-PROBLEM PROBABILITY: P(d|p)
# =============================================================================

def calculate_doc_problem_probability_semantic(
    doc_embedding: np.ndarray,
    problem_embedding: np.ndarray,
    temperature: float = 0.1
) -> float:
    """
    Calculate P(d|p) using semantic similarity (soft matching)
    
    Formula:
        P(d|p) = σ(sim(d, p) / τ)
    
    where:
        sim(d, p) = cosine similarity between doc and problem embeddings
        τ = temperature (controls sharpness)
        σ = sigmoid function
    
    Interpretation:
        - Soft matching: value in [0, 1] based on semantic similarity
        - Temperature controls how "soft" the matching is
        - Low τ → sharp (close to binary)
        - High τ → smooth (more gradual)
    
    Advantage over binary matching:
        - Captures semantic similarity, not just keyword overlap
        - Differentiable (useful for learning α)
        - More robust to paraphrasing
    
    Args:
        doc_embedding: Document embedding vector
        problem_embedding: Problem description embedding vector
        temperature: Softmax temperature
    
    Returns:
        Probability P(d|p) in [0, 1]
    """
    if doc_embedding is None or problem_embedding is None:
        return 0.0
    
    similarity = cosine_similarity(doc_embedding, problem_embedding)
    
    # Apply temperature scaling and sigmoid
    # σ(sim/τ) maps similarity to probability
    scaled_sim = similarity / max(temperature, 1e-6)
    
    return sigmoid(scaled_sim)


def calculate_doc_problem_probability_keyword(
    doc_text: str,
    problem: Dict,
    soft: bool = True
) -> float:
    """
    Calculate P(d|p) using keyword matching (fallback when no embeddings)
    
    Formula (soft):
        P(d|p) = |matched_keywords| / |all_keywords|
    
    Formula (hard):
        P(d|p) = 1 if any keyword matches else 0
    
    Args:
        doc_text: Document text
        problem: Problem dict with 'keywords' and 'name'
        soft: If True, use proportion; if False, use binary
    
    Returns:
        Probability P(d|p) in [0, 1]
    """
    doc_lower = doc_text.lower()
    
    # Collect all keywords
    keywords = problem.get('keywords', [])
    matched_keywords = problem.get('matched_keywords', [])
    name = problem.get('name', '')
    
    all_keywords = list(set(keywords + matched_keywords))
    if name:
        all_keywords.append(name)
    
    if not all_keywords:
        return 0.0
    
    # Count matches
    matches = sum(1 for kw in all_keywords if kw.lower() in doc_lower)
    
    if soft:
        # Soft: proportion of matching keywords
        return matches / len(all_keywords)
    else:
        # Hard: binary match
        return 1.0 if matches > 0 else 0.0


def calculate_doc_problem_probability_fused(
    doc_text: str,
    problem: Dict,
    doc_embedding: np.ndarray = None,
    problem_embedding: np.ndarray = None,
    config: H2LConfigV3 = None
) -> Tuple[float, str]:
    """
    V4 Gated Fusion: Adaptive blending of semantic & keyword P(d|p)
    
    Formula:
        P_fused(d|p) = g · P_sem(d|p) + (1 - g) · P_kw(d|p)
        g = σ(w_g · sim(d, p) + b_g)
    
    The gate g adapts based on semantic similarity quality:
        - High cosine similarity → g ≈ 1 → trust semantic
        - Low cosine similarity → g ≈ 0 → fall back to keyword
    
    Args:
        doc_text: Document text
        problem: Problem dict
        doc_embedding: Document embedding (optional)
        problem_embedding: Problem embedding (optional)
        config: Configuration
    
    Returns:
        Tuple of (fused_probability, method_description)
    """
    if config is None:
        config = DEFAULT_CONFIG_V3
    
    # Always compute keyword probability
    p_kw = calculate_doc_problem_probability_keyword(doc_text, problem, soft=True)
    
    # If we have embeddings, compute semantic + gate
    if doc_embedding is not None and problem_embedding is not None:
        raw_sim = cosine_similarity(doc_embedding, problem_embedding)
        p_sem = calculate_doc_problem_probability_semantic(
            doc_embedding, problem_embedding, config.TEMPERATURE
        )
        
        # Gated fusion: g = σ(w_g · sim + b_g)
        gate = sigmoid(config.GATE_WEIGHT * raw_sim + config.GATE_BIAS)
        p_fused = gate * p_sem + (1.0 - gate) * p_kw
        
        return p_fused, f"gated(g={gate:.3f},sem={p_sem:.3f},kw={p_kw:.3f})"
    else:
        # No embeddings — keyword only
        return p_kw, f"keyword({p_kw:.3f})"


# =============================================================================
# CROSS-PROBLEM CO-OCCURRENCE WEIGHTS (V4 Enhancement 3)
# =============================================================================

def calculate_co_occurrence_weights(
    problems: List[Dict],
    problem_embeddings: Dict[str, np.ndarray] = None,
    config: H2LConfigV3 = None
) -> Dict[str, float]:
    """
    Calculate cross-problem co-occurrence bonus weights.
    
    Formula:
        w_i = 1 + γ · (1/(|P|-1)) · Σ_{j≠i} sim(p_i, p_j)
    
    Vectorized: uses matrix multiply for all pairwise similarities at once.
    
    Args:
        problems: List of detected problems
        problem_embeddings: Dict code → embedding (assumed pre-normalized)
        config: Configuration
    
    Returns:
        Dict mapping problem code to weight w_i (≥ 1.0)
    """
    if config is None:
        config = DEFAULT_CONFIG_V3
    
    n = len(problems)
    gamma = config.CO_OCCURRENCE_GAMMA
    
    # Default: uniform weights
    codes = [p.get('code', 'unknown') for p in problems]
    weights = {c: 1.0 for c in codes}
    
    # Need ≥2 problems and embeddings to compute co-occurrence
    if n < 2 or not problem_embeddings or gamma == 0:
        return weights
    
    # Collect codes that have embeddings
    valid_codes = [c for c in codes if c in problem_embeddings]
    if len(valid_codes) < 2:
        return weights
    
    # Vectorized: stack embeddings → matrix multiply for all pairwise sims
    emb_matrix = np.stack([problem_embeddings[c] for c in valid_codes])
    # Embeddings are pre-normalized → dot product = cosine similarity
    sim_matrix = emb_matrix @ emb_matrix.T
    np.clip(sim_matrix, 0.0, None, out=sim_matrix)  # Only positive similarities
    
    for i, code_i in enumerate(valid_codes):
        # Sum of similarities excluding self (diagonal)
        co_sim_sum = float(sim_matrix[i].sum()) - float(sim_matrix[i, i])
        avg_co_sim = co_sim_sum / (len(valid_codes) - 1)
        weights[code_i] = 1.0 + gamma * avg_co_sim
    
    return weights


# =============================================================================
# V5 ENHANCEMENT 1: Severity-Weighted Confidence Calibration
# C(p|q) = P(p|q)^(1/T_i)  where T_i = T_base + (1 - sev/sev_max) * T_range
# Reference: Platt (1999) — Probabilistic Outputs for SVM
# =============================================================================

def calibrate_confidence(
    p_detection: float,
    severity: int,
    max_severity: int = 5,
    config: H2LConfigV3 = None
) -> float:
    """
    Severity-Weighted Confidence Calibration.
    
    Formula:
        C(p|q) = P(p|q)^(1/T_i)
        T_i = T_base + (1 - sev_i / sev_max) · T_range
    
    Interpretation:
        - High severity → low T_i → P(p|q)^(1/low) → amplified confidence
        - Low severity  → high T_i → P(p|q)^(1/high) → dampened confidence
    
    This ensures clinically urgent problems (e.g., suicide risk)
    dominate scoring even with moderate detection confidence.
    
    Grounding: Platt scaling (Platt, 1999) adapted with severity-awareness.
    
    Args:
        p_detection: Raw detection probability P(p|q) ∈ [0, 1]
        severity: Problem severity score (1–5)
        max_severity: Maximum possible severity
        config: Configuration with calibration parameters
    
    Returns:
        Calibrated confidence C(p|q) ∈ [0, 1]
    """
    if config is None:
        config = DEFAULT_CONFIG_V3
    
    if p_detection <= 0:
        return 0.0
    if p_detection >= 1:
        return 1.0
    
    # Temperature: high severity → low T → sharper discrimination
    sev_ratio = severity / max(max_severity, 1)
    t_i = config.CALIBRATION_T_BASE + (1.0 - sev_ratio) * config.CALIBRATION_T_RANGE
    t_i = max(t_i, 0.1)  # Floor to prevent division issues
    
    # C(p|q) = P(p|q)^(1/T_i)  — matches docstring formula
    # High sev → T_i small → 1/T_i large → P^large → sharper (polarized toward 0 or 1)
    # Low sev  → T_i large → 1/T_i small → P^small → softer (closer to uniform)
    # This is Platt-inspired: higher severity = more discriminative confidence
    calibrated = p_detection ** (1.0 / t_i)
    return max(0.0, min(1.0, calibrated))


# =============================================================================
# V5 ENHANCEMENT 2: IDF-Inspired Document Specificity
# IDF(p_i) = log(1 + N / (1 + DF(p_i)))
# Reference: Robertson & Sparck Jones (1976)
# =============================================================================

def calculate_idf_weight(
    problem: Dict,
    all_docs_texts: List[str] = None,
    config: H2LConfigV3 = None
) -> float:
    """
    IDF-inspired document specificity weight for a problem.
    
    Formula:
        IDF(p_i) = log(1 + N / (1 + DF(p_i)))
    
    where:
        N = total documents in corpus
        DF(p_i) = number of documents containing problem keywords
    
    Interpretation:
        - Common problems (high DF) → low IDF → weaker discriminative signal
        - Rare problems (low DF) → high IDF → stronger discriminative signal
    
    Grounding: Classic IDF (Robertson & Sparck Jones, 1976) adapted
    from term-level to problem-level specificity.
    
    Args:
        problem: Problem dict with 'keywords' and 'name'
        all_docs_texts: Optional list of all document texts for DF computation
        config: Configuration
    
    Returns:
        IDF weight (≥ 0, typically 0.5–3.0)
    """
    if config is None:
        config = DEFAULT_CONFIG_V3
    
    if not config.IDF_ENABLE:
        return 1.0  # Neutral — effectively disables IDF
    
    # Collect problem keywords
    keywords = problem.get('keywords', [])
    name = problem.get('name', '')
    all_kw = list(set(kw.lower() for kw in keywords if kw))
    if name:
        all_kw.append(name.lower())
    
    if not all_kw:
        return 1.0
    
    N = config.IDF_CORPUS_SIZE
    
    if all_docs_texts:
        # Exact DF computation when corpus is available
        df = 0
        for doc_text in all_docs_texts:
            doc_lower = doc_text.lower()
            if any(kw in doc_lower for kw in all_kw):
                df += 1
        N = max(len(all_docs_texts), N)
    else:
        # Heuristic DF estimation when no corpus available (V6 fix)
        # Uses keyword count + average keyword length as specificity proxy:
        # - More keywords → broader coverage → higher DF
        # - Longer keywords → more specific → lower DF
        n_keywords = len(all_kw)
        avg_kw_len = sum(len(kw) for kw in all_kw) / max(n_keywords, 1)
        specificity_factor = min(avg_kw_len / 10.0, 1.0)  # Normalize by typical max
        df = max(1, int(n_keywords * 8 * (1.0 - 0.5 * specificity_factor)))
    
    # IDF formula with smoothing
    idf = math.log(1.0 + N / (config.IDF_SMOOTH + df))
    
    # Normalize to config-driven range [0.5, IDF_MAX]
    idf = max(0.5, min(config.IDF_MAX, idf))
    
    return idf


# =============================================================================
# V5 ENHANCEMENT 3: Margin-Aware Saturating Activation
# Ω(d|p) = σ((sim(d,p) - m) / τ_Ω)
# Reference: Schroff et al. (2015) — FaceNet Triplet Loss
# =============================================================================

def margin_aware_activation(
    doc_embedding: np.ndarray,
    problem_embedding: np.ndarray,
    config: H2LConfigV3 = None
) -> float:
    """
    Margin-Aware Saturating Activation for P(d|p).
    
    Formula:
        Ω(d|p) = σ((sim(d, p) - m) / τ_Ω)
    
    where:
        m = margin (decision boundary)
        τ_Ω = temperature (controls steepness)
    
    Interpretation:
        - Documents must exceed the margin m in similarity to get high Ω
        - At sim = m: Ω = σ(0) = 0.5 (decision boundary)
        - sim > m: Ω → 1.0 (relevant)
        - sim < m: Ω → 0.0 (irrelevant)
    
    Advantage over plain sigmoid σ(sim/τ):
        - Defines a clear relevance boundary
        - Better discrimination in the "useful" similarity range
        - Reduces noise from weakly similar documents
    
    Grounding: Inspired by contrastive margin learning (Schroff et al., 2015).
    
    Args:
        doc_embedding: Document embedding vector
        problem_embedding: Problem embedding vector
        config: Configuration with MARGIN_M and MARGIN_TAU
    
    Returns:
        Ω(d|p) ∈ [0, 1]
    """
    if config is None:
        config = DEFAULT_CONFIG_V3
    
    if doc_embedding is None or problem_embedding is None:
        return 0.0
    
    sim = cosine_similarity(doc_embedding, problem_embedding, pre_normalized=True)
    
    # Margin-shifted, temperature-scaled sigmoid
    scaled = (sim - config.MARGIN_M) / max(config.MARGIN_TAU, 1e-6)
    return sigmoid(scaled)


# =============================================================================
# V5 ENHANCEMENT 4: KL-Divergence Concentration Penalty
# KL(P || U) = Σ P(p_i) · log(P(p_i) / (1/k))
# Reference: Kullback & Leibler (1951)
# =============================================================================

def calculate_kl_concentration_penalty(
    priors: Dict[str, float],
    config: H2LConfigV3 = None
) -> float:
    """
    KL divergence from uniform distribution as a concentration penalty.
    
    Formula:
        KL(P || U) = Σ_i P(p_i) · log(P(p_i) / (1/k))
                   = Σ_i P(p_i) · log(k · P(p_i))
    
    Interpretation:
        - KL = 0 when P is uniform (all problems equally severe)
        - KL > 0 when P is concentrated (one problem dominates)
        - Higher KL → stronger dampening of α_eff
    
    Usage in α_eff:
        α_eff = α₀ · (1 + δ · H) · (1 - κ · min(KL, KL_max))
    
    Grounding: KL divergence (Kullback & Leibler, 1951) as a
    regularization signal against over-concentration.
    
    Args:
        priors: Problem prior distribution {code: probability}
        config: Configuration with KL_KAPPA and KL_MAX
    
    Returns:
        KL penalty value (≥ 0, capped at KL_MAX)
    """
    if config is None:
        config = DEFAULT_CONFIG_V3
    
    k = len(priors)
    if k <= 1:
        return 0.0  # Single problem → no penalty
    
    uniform = 1.0 / k
    kl = 0.0
    epsilon = 1e-10
    
    for p in priors.values():
        if p > epsilon:
            kl += p * math.log(p / uniform)
    
    return float(min(max(0.0, kl), config.KL_MAX))


# =============================================================================
# V5 ENHANCEMENT 5: Sentence Polarity Gating
# G_neg(p_i) = 1 - λ_neg · neg_score(p_i, q)
# =============================================================================

class PolarityGateResult(dict):
    """Dict result that remains numerically compatible with legacy G_neg callers."""

    def _legacy_value(self) -> float:
        return float(self.get("gate_neg", self.get("gate_total", 1.0)))

    def __float__(self):
        return self._legacy_value()

    def __lt__(self, other):
        return self._legacy_value() < float(other)

    def __le__(self, other):
        return self._legacy_value() <= float(other)

    def __gt__(self, other):
        return self._legacy_value() > float(other)

    def __ge__(self, other):
        return self._legacy_value() >= float(other)

    def __eq__(self, other):
        if isinstance(other, (int, float)):
            return self._legacy_value() == float(other)
        return dict.__eq__(self, other)


def calculate_sentence_polarity(
    problem: Dict,
    query_text: str = None,
    config: H2LConfigV3 = None
) -> Dict[str, float]:
    """
    Sentence Polarity Analysis (V6.1):
    Analyzes sentence structure across 3 dimensions:
    1. Negation (G_neg): Checks if the problem is negated (e.g. "ไม่").
    2. Length/Complexity (G_len): Penalizes extremely short queries.
    3. Subject/Actor (G_sub): Evaluates if the query refers to the patient or others.
    
    Formula:
        G_polarity = G_neg × G_len × G_sub
    
    Returns:
        Dict containing individual gates and the total score.
    """
    if config is None:
        config = DEFAULT_CONFIG_V3
    
    default_result = PolarityGateResult({"gate_total": 1.0, "gate_neg": 1.0, "gate_len": 1.0, "gate_sub": 1.0})
    if not config.NEG_ENABLE or not query_text:
        return default_result
    
    query_lower = query_text.lower()
    
    # ==========================
    # Dimension 1: Negation Gate
    # ==========================
    gate_neg = 1.0
    keywords = problem.get('keywords', [])
    name = problem.get('name', '')
    search_terms = [kw.lower() for kw in keywords if kw] + ([name.lower()] if name else [])
    
    if search_terms:
        neg_score = 0.0
        matched_terms = 0
        for term in search_terms:
            if term not in query_lower:
                continue
            matched_terms += 1
            idx = query_lower.find(term)
            window_start = max(0, idx - 30)
            window = query_lower[window_start:idx]
            for neg in config.NEGATION_MARKERS:
                if neg in window:
                    # Tone Analysis Module (V6.3): Emotion / Sarcasm / Contextual Bypassing
                    # Exceptions often occur within the keyword itself (e.g., "ไม่มีเงิน")
                    # or in the preceding text window ("ไม่กล้า").
                    has_tone_exception = any(tone in window or tone in term for tone in config.TONE_EXCEPTIONS)
                    if has_tone_exception:
                        # Bypass negation penalty due to emotional context
                        break
                        
                    neg_score += 1.0
                    break
        if matched_terms > 0:
            neg_ratio = neg_score / matched_terms
            gate_neg = 1.0 - config.NEG_LAMBDA * neg_ratio
            gate_neg = float(max(0.1, min(1.0, gate_neg)))
            
    # ==========================
    # Dimension 2: Length / Complexity
    # ==========================
    import math
    char_len = len(query_text.strip())
    # Logarithmic smoothing: G_len = min(1.0, log10(len_chars / 10 + 1) + 0.5)
    gate_len = min(1.0, math.log10((char_len / 10.0) + 1.0) + 0.5)
    gate_len = float(gate_len)
    
    # ==========================
    # Dimension 3: Subject / Actor 
    # ==========================
    gate_sub = 1.0
    severity = problem.get('severity', 1)
    if severity >= 3:
        other_subjects = ["พ่อ", "แม่", "เพื่อน", "พี่", "น้อง", "เขา", "แฟน", "สามี", "ภรรยา", "ลูก"]
        self_subjects = ["ฉัน", "ผม", "หนู", "ตัวเอง", "ผู้ป่วย", "เด็ก", "ผู้มารับบริการ"]
        
        has_other = any(subj in query_lower for subj in other_subjects)
        has_self = any(subj in query_lower for subj in self_subjects)
        
        if has_other and not has_self:
            gate_sub = 0.85

    # ==========================
    # Final Polarity Score
    # ==========================
    gate_total = gate_neg * gate_len * gate_sub
    
    return PolarityGateResult({
        "gate_total": round(gate_total, 4),
        "gate_neg": round(gate_neg, 4),
        "gate_len": round(gate_len, 4),
        "gate_sub": round(gate_sub, 4)
    })

# Backward-compat alias for callers expecting V5
def calculate_negation_gate(problem: Dict, query_text: str = None, config: H2LConfigV3 = None) -> float:
    return calculate_sentence_polarity(problem, query_text, config)["gate_total"]

# =============================================================================
# V6 ENHANCEMENT 1: Context-Dependent Adaptive α
# α(C) = α_base · σ(γ · num_problems + δ · avg_confidence)
# =============================================================================

def calculate_adaptive_alpha(
    problems: List[Dict],
    config: H2LConfigV3 = None,
    alpha_base: float = None
) -> float:
    """
    V6 Context-Dependent Adaptive Alpha.
    
    Formula:
        α(C) = α_base · 2 · σ(γ · |P| + δ · avg_conf - z_center)
    
    where:
        |P| = number of detected problems
        avg_conf = average detection confidence
        z_center = γ·2 + δ·0.7 (typical case center point)
        σ = sigmoid function
        Factor of 2 so that α(C) ≈ α_base when z = z_center
    
    Interpretation:
        - More problems + higher confidence → α increases → trust H2L boost more
        - Few problems + low confidence → α decreases → rely on reranker
    
    Generalizability:
        Only requires count + confidence — works in any domain.
    
    Args:
        problems: List of detected problems
        config: Configuration with ADAPTIVE_ALPHA_GAMMA, DELTA
        alpha_base: Base alpha (overrides config.ALPHA if provided)
    
    Returns:
        Adaptive alpha value α(C) > 0
    """
    if config is None:
        config = DEFAULT_CONFIG_V3
    
    if not config.ADAPTIVE_ALPHA_ENABLE or not problems:
        return alpha_base if alpha_base is not None else config.ALPHA
    
    a_base = alpha_base if alpha_base is not None else config.ALPHA
    
    num_problems = len(problems)
    avg_confidence = sum(p.get('confidence', 0.5) for p in problems) / max(num_problems, 1)
    
    # σ(γ · |P| + δ · avg_conf - center)
    # Center at typical case (2 problems, 0.7 confidence) so α can go both up AND down
    # z_typical = 0.3*2 + 0.5*0.7 = 0.95 → center here so σ(0) = 0.5 at typical case
    z_center = 0.3 * 2.0 + 0.5 * 0.7  # = 0.95 for default γ=0.3, δ=0.5
    z = config.ADAPTIVE_ALPHA_GAMMA * num_problems + config.ADAPTIVE_ALPHA_DELTA * avg_confidence - z_center
    s = sigmoid(z)
    
    # Scale: α(C) = α_base · 2 · σ(z) so that at midpoint σ=0.5 → α=α_base
    # Now z=0 at typical case → σ(0)=0.5 → α=α_base (can go up OR down)
    alpha_adaptive = a_base * 2.0 * s
    
    return max(0.01, alpha_adaptive)


# =============================================================================
# V6 ENHANCEMENT 2: Bayesian Prior Integration
# P(rel | profile) = Σ P(pᵢ) · P(rel | pᵢ)
# =============================================================================

def calculate_bayesian_prior(
    problems: List[Dict],
    priors: Dict[str, float],
    config: H2LConfigV3 = None
) -> float:
    """
    V6 Bayesian Prior: estimates document relevance from problem profile.
    
    Formula:
        P(rel | profile) = Σᵢ P(pᵢ) · P(rel | pᵢ)
    
    where:
        P(pᵢ) = Dirichlet-smoothed problem prior (from V4)
        P(rel | pᵢ) = estimated relevance given problem pᵢ
                     = detection confidence as proxy
    
    Interpretation:
        - High-confidence, high-prior problems → high relevance prior
        - Acts as a multiplicative prior on the final score
        - Bounds: [BAYESIAN_PRIOR_BASE, 1.0] to prevent zeroing out
    
    Generalizability:
        Uses confidence + prior probability — available in any detection system.
        Researchers can override P(rel | pᵢ) with domain-specific estimates.
    
    Args:
        problems: List of detected problems
        priors: Dirichlet-smoothed prior distribution {code: probability}
        config: Configuration
    
    Returns:
        P(rel | profile) ∈ [base, 1.0]
    """
    if config is None:
        config = DEFAULT_CONFIG_V3
    
    if not config.BAYESIAN_PRIOR_ENABLE or not problems:
        return 1.0  # Neutral prior
    
    # P(rel | profile) = Σ P(pᵢ) · P(rel | pᵢ)
    # Use detection confidence as proxy for P(rel | pᵢ)
    relevance_prior = 0.0
    for problem in problems:
        code = problem.get('code', 'unknown')
        p_prior = priors.get(code, config.MIN_PRIOR)
        p_rel_given_p = problem.get('confidence', 0.5)
        relevance_prior += p_prior * p_rel_given_p
    
    # Normalize: scale to [base, 1.0]
    # relevance_prior ∈ [0, 1] since priors sum to ~1 and conf ≤ 1  (V6 fix: removed arbitrary *2.0)
    prior = config.BAYESIAN_PRIOR_BASE + (1.0 - config.BAYESIAN_PRIOR_BASE) * min(relevance_prior, 1.0)
    
    return max(config.BAYESIAN_PRIOR_BASE, min(1.0, prior))


# =============================================================================
# V6 ENHANCEMENT 3: Multi-Granularity Feature Aggregation
# Φᵢ = Σₖ wₖ · φₖ(d, pᵢ, q) — weighted sum of normalized features
# =============================================================================

def aggregate_features_v6(
    features: Dict[str, float],
    config: H2LConfigV3 = None
) -> float:
    """
    V6 Multi-Granularity Feature Aggregation.
    
    Instead of V5's product (φ = C · Ω · P · IDF · G_neg),
    V6 uses a weighted sum: Φ = Σ wₖ · φₖ
    
    This is more robust because:
        - One weak feature doesn't zero out the entire score
        - Weights are tunable per feature
        - Researchers can add domain-specific features by extending FEATURE_WEIGHTS
    
    Args:
        features: Dict of {feature_name: value} — each value in [0, 1]
        config: Configuration with FEATURE_WEIGHTS
    
    Returns:
        Aggregated feature value Φ ∈ [0, 1]
    """
    if config is None:
        config = DEFAULT_CONFIG_V3
    
    if config.FEATURE_MODE == 'product':
        # V5-style: multiply all features
        result = 1.0
        for v in features.values():
            result *= v
        return result
    
    # V6-style: weighted sum
    weights = config.FEATURE_WEIGHTS
    total_weight = 0.0
    weighted_sum = 0.0
    
    # Feature-to-Flag Mapping for V6 Ablation
    feature_flags = {
        'detect': True, # Always enabled
        'semantic': True, # Controlled via temperature
        'prior': getattr(config, 'BAYESIAN_PRIOR_ENABLE', True),
        'specificity': getattr(config, 'IDF_ENABLE', True),
        'negation': getattr(config, 'NEG_ENABLE', True),
    }
    
    for name, value in features.items():
        if not feature_flags.get(name, True):
            continue # Skip disabled features in weighted sum
            
        w = weights.get(name, 0.1)
        weighted_sum += w * value
        total_weight += w
    
    
    # Normalize by total weight (V6 Fix: Use fixed denominator 1.0 for ablation sensitivity)
    # If we re-normalize by current total_weight, the ratio stays identical 
    # and we can't see the impact of missing components.
    return weighted_sum # Weights are already normalized to sum to 1.0 in __post_init__



# =============================================================================
# FINAL SCORE: V6 Generalizable Bayesian Problem-Aware Scoring
# S_final = S_rerank · exp(α(C) · Σ wᵢ · Φᵢ(d, pᵢ, q)) · P(rel | profile)
# =============================================================================

def _compute_severity_entropy(
    priors: Dict[str, float],
    epsilon: float = 1e-10
) -> float:
    """
    Shannon entropy of the severity distribution.
    
    H = -Σ P(p_i) · log₂ P(p_i)
    
    - Low H → one dominant problem (concentrated)
    - High H → many equally severe problems (uniform)
    """
    _LOG2 = math.log(2.0)
    h = 0.0
    for p in priors.values():
        if p > epsilon:
            h -= p * (math.log(p) / _LOG2)
    return float(h)


def calculate_final_score_probabilistic(
    rerank_score: float,
    problems: List[Dict],
    doc_text: str = None,
    doc_embedding: np.ndarray = None,
    problem_embeddings: Dict[str, np.ndarray] = None,
    config: H2LConfigV3 = None,
    alpha_override: float = None,
    query_text: str = None,
    precomputed: Dict = None
) -> Tuple[float, Dict]:
    """
    V6 Generalizable Bayesian Problem-Aware Scoring
    
    Formula:
        S_final = S_rerank · exp(α(C) · Σ_i w_i · Φ_i(d, p_i, q)) · P(rel | profile)
    
    V6 Enhancements:
        α(C)           = α_base · 2σ(γ·|P| + δ·avg_conf)  — context-dependent (V6.1)
        P(rel|profile) = Σ P(pᵢ)·P(rel|pᵢ)                — Bayesian prior (V6.2)
        Φ_i            = Σ wₖ·φₖ                           — multi-granularity (V6.3)
    
    Feature vector φₖ:
        φ_detect     = C(p|q)    — calibrated detection confidence
        φ_semantic   = Ω(d|p)    — margin-aware doc-problem similarity
        φ_prior      = P(p)      — Dirichlet-smoothed problem prior
        φ_specificity = IDF(p)   — document specificity weight
        φ_negation   = G_neg(p)  — negation-aware gating
    
    Retained from V4/V5:
        Entropy H, KL penalty, co-occurrence weights, gated fusion
    
    Args:
        rerank_score: Base reranker score S_rerank
        problems: List of detected problems
        doc_text: Document text (for keyword matching fallback)
        doc_embedding: Document embedding (for semantic matching)
        problem_embeddings: Dict of problem code -> embedding
        config: Configuration
        alpha_override: Override alpha value (for ablation experiments)
        query_text: Original query text (for negation gating; V5)
        precomputed: Optional dict with pre-computed per-problem invariants
                     (priors, alpha_eff, co_weights, calibrations, idfs, neg_gates)
                     to avoid redundant computation when called in a loop.
    
    Returns:
        Tuple of (final_score, breakdown_dict)
    """
    if config is None:
        config = DEFAULT_CONFIG_V3

    # Base alpha (α₀)
    alpha_base = alpha_override if alpha_override is not None else config.ALPHA

    if not problems:
        return rerank_score, {"method": "no_problems", "factors": []}
    
    # ── Use precomputed values if available, else compute ──
    if precomputed:
        priors = precomputed['priors']
        h_severity = precomputed['h_severity']
        kl_penalty = precomputed['kl_penalty']
        alpha_eff = precomputed['alpha_eff']
        co_weights = precomputed['co_weights']
        max_severity = precomputed['max_severity']
        calibrations = precomputed.get('calibrations')
        idfs = precomputed.get('idfs')
        neg_gates = precomputed.get('neg_gates')
        bayesian_prior = precomputed.get('bayesian_prior', 1.0)
    else:
        # ── Step 1: Dirichlet-smoothed priors ──
        priors = calculate_problem_prior(problems, config)
        
        # ── Step 2: V6 Adaptive α with entropy+KL regularization ──
        h_severity = _compute_severity_entropy(priors)
        kl_penalty = calculate_kl_concentration_penalty(priors, config)
        
        # V6.1: Context-dependent adaptive α
        alpha_adaptive = calculate_adaptive_alpha(problems, config, alpha_base)
        
        # Apply entropy+KL as regularization (retained from V4/V5)
        entropy_factor = (1.0 + config.ENTROPY_SCALE_DELTA * h_severity)
        kl_factor = (1.0 - config.KL_KAPPA * kl_penalty)
        alpha_eff = alpha_adaptive * entropy_factor * kl_factor
        alpha_eff = max(0.01, alpha_eff)
        
        # ── Step 3: Cross-problem co-occurrence weights ──
        co_weights = calculate_co_occurrence_weights(
            problems, problem_embeddings, config
        )
        
        # ── Step 4: Maximum severity for calibration ──
        max_severity = max((p.get('severity', 1) for p in problems), default=5)
        
        # ── V6.2: Bayesian Prior ──
        bayesian_prior = calculate_bayesian_prior(problems, priors, config)
        
        calibrations = None
        idfs = None
        neg_gates = None
    
    # ── Step 5: Per-problem Φ_i with V6 multi-granularity features ──
    weighted_sum = 0.0
    factors = []
    
    for problem in problems:
        code = problem.get('code', 'unknown')
        severity = problem.get('severity', 1)
        
        # Calibrated confidence C(p|q) — use precomputed if available
        if calibrations and code in calibrations:
            raw_detection, c_detection = calibrations[code]
        else:
            raw_detection = calculate_detection_probability(problem)
            c_detection = calibrate_confidence(
                raw_detection, severity, max_severity, config
            )
        
        # P_fused(d|p_i) = gated fusion of semantic + keyword (V4)
        prob_emb = problem_embeddings.get(code) if problem_embeddings else None
        if doc_text is not None:
            p_doc_problem, match_method = calculate_doc_problem_probability_fused(
                doc_text=doc_text,
                problem=problem,
                doc_embedding=doc_embedding,
                problem_embedding=prob_emb,
                config=config
            )
        elif doc_embedding is not None and prob_emb is not None:
            p_doc_problem = calculate_doc_problem_probability_semantic(
                doc_embedding, prob_emb, config.TEMPERATURE
            )
            match_method = "semantic"
        else:
            p_doc_problem = 0.0
            match_method = "none"
        
        # Margin-aware activation Ω(d|p) (blended with P_fused)
        if config.MARGIN_ENABLE and doc_embedding is not None and prob_emb is not None:
            omega = margin_aware_activation(doc_embedding, prob_emb, config)
            p_doc_final = max(p_doc_problem, omega)
            match_method += f"+margin(Ω={omega:.3f})"
        else:
            p_doc_final = p_doc_problem
        
        # P_smoothed(p_i) = Dirichlet-smoothed prior
        p_prior = priors.get(code, config.MIN_PRIOR)
        
        # IDF document specificity
        idf_w = idfs[code] if (idfs and code in idfs) else calculate_idf_weight(problem, config=config)
        
        # Sentence polarity gating (V6.1)
        if neg_gates and code in neg_gates:
            neg_val = neg_gates[code]
            if isinstance(neg_val, dict):
                polarity_dict = neg_val
                g_neg = polarity_dict.get("gate_total", 1.0)
            else:
                g_neg = float(neg_val)
                polarity_dict = {"gate_total": g_neg, "gate_neg": g_neg, "gate_len": 1.0, "gate_sub": 1.0}
        else:
            polarity_res = calculate_sentence_polarity(problem, query_text, config)
            if isinstance(polarity_res, dict):
                polarity_dict = polarity_res
                g_neg = polarity_dict.get("gate_total", 1.0)
            else:
                g_neg = float(polarity_res)
                polarity_dict = {"gate_total": g_neg, "gate_neg": g_neg, "gate_len": 1.0, "gate_sub": 1.0}
        
        # w_i = co-occurrence weight
        w_i = co_weights.get(code, 1.0)

        # V6.3: Multi-Granularity Feature Aggregation
        # Φ_i = weighted_sum(φ_detect, φ_semantic, φ_prior, φ_specificity, φ_negation)
        feature_dict = {
            'detect': c_detection,
            'semantic': p_doc_final,
            'prior': p_prior,
            'specificity': max(0.0, min((idf_w - 0.5) / (config.IDF_MAX - 0.5), 1.0)),  # Normalize IDF [0.5, IDF_MAX] → [0, 1]
            'negation': g_neg,
        }
        phi = aggregate_features_v6(feature_dict, config)
        
        # Weighted contribution: w_i · Φ_i
        weighted_phi = w_i * phi
        weighted_sum += weighted_phi
        
        factors.append({
            "code": code,
            "P(p|q)_raw": round(raw_detection, 4),
            "C(p|q)": round(c_detection, 4),
            "P(d|p)": round(p_doc_final, 4),
            "P(p)": round(p_prior, 4),
            "IDF": round(idf_w, 4),
            "G_neg": round(g_neg, 4),
            "gate_len": polarity_dict.get("gate_len", 1.0),
            "gate_sub": polarity_dict.get("gate_sub", 1.0),
            "w_i": round(w_i, 4),
            "Φ_i": round(phi, 6),
            "w·Φ": round(weighted_phi, 6),
            "match_method": match_method
        })
    
    # ── Step 6: V6 Log-linear final score with Bayesian prior ──
    # S_final = S_rerank · exp(α(C) · mean(w_i · Φ_i)) · P(rel | profile)
    n_problems = max(len(problems), 1)
    normalized_sum = weighted_sum / n_problems
    exponent = alpha_eff * normalized_sum
    # Clamp exponent for numerical stability
    exponent = max(-3.0, min(3.0, exponent))
    boost = math.exp(exponent)
    
    # V6.2: Apply Bayesian prior
    final_score = rerank_score * boost * bayesian_prior

    # Cache adaptive alpha (V6 fix B3: avoid redundant recomputation)
    _alpha_adaptive = calculate_adaptive_alpha(problems, config, alpha_base) if not precomputed else alpha_eff
    breakdown = {
        "method": "bayesian_v6",
        "S_rerank": round(rerank_score, 4),
        "α₀": round(alpha_base, 4),
        "α_adaptive": round(_alpha_adaptive, 4),
        "H_severity": round(h_severity, 4),
        "KL_penalty": round(kl_penalty, 4),
        "α_eff": round(alpha_eff, 4),
        "Σ(w·Φ)": round(weighted_sum, 6),
        "n_problems": n_problems,
        "mean(w·Φ)": round(normalized_sum, 6),
        "exponent": round(exponent, 6),
        "boost": round(boost, 4),
        "P(rel|profile)": round(bayesian_prior, 4),
        "S_final": round(final_score, 4),
        "feature_mode": config.FEATURE_MODE,
        "temperature": config.TEMPERATURE,
        "μ_dirichlet": config.DIRICHLET_MU,
        "γ_co_occur": config.CO_OCCURRENCE_GAMMA,
        "margin_m": config.MARGIN_M,
        "factors": factors
    }
    
    return final_score, breakdown


# =============================================================================
# SIMPLIFIED INTERFACE (for backward compatibility)
# =============================================================================

def calculate_final_retrieval_score_v3(
    rerank_score: float,
    problems: List[Dict],
    doc_text: str,
    config: H2LConfigV3 = None
) -> float:
    """
    Simplified interface using keyword matching
    (Use when embeddings not available)
    
    Args:
        rerank_score: Base reranker score
        problems: Detected problems
        doc_text: Document text
        config: Configuration
    
    Returns:
        Final score
    """
    score, _ = calculate_final_score_probabilistic(
        rerank_score=rerank_score,
        problems=problems,
        doc_text=doc_text,
        doc_embedding=None,
        problem_embeddings=None,
        config=config
    )
    return score


# =============================================================================
# COMPARISON: V2 vs V6
# =============================================================================

def compare_v2_v3(
    rerank_score: float,
    problems: List[Dict],
    doc_text: str
) -> Dict:
    """
    Compare V2 (weighted average) vs V6 (enhanced log-linear probabilistic)
    
    For thesis: shows the evolution of formulation
    """
    # V2: Weighted Average
    total_severity = sum(p.get('severity', 1) for p in problems)
    if total_severity > 0:
        doc_lower = doc_text.lower()
        matched_severity = 0
        for p in problems:
            keywords = p.get('keywords', []) + p.get('matched_keywords', [])
            name = p.get('name', '')
            if any(kw.lower() in doc_lower for kw in keywords if kw) or (name and name.lower() in doc_lower):
                matched_severity += p.get('severity', 1)
        
        s_problem_v2 = matched_severity / total_severity
        lambda_v2 = 0.2
        s_final_v2 = rerank_score * (1 + lambda_v2 * s_problem_v2)
    else:
        s_problem_v2 = 0
        s_final_v2 = rerank_score
    
    # V6: Enhanced Log-linear Probabilistic
    s_final_v6, breakdown = calculate_final_score_probabilistic(
        rerank_score=rerank_score,
        problems=problems,
        doc_text=doc_text
    )
    
    return {
        "V2_Simplified": {
            "formula": "S_final = S_rerank × (1 + λ × S_problem)",
            "S_problem": round(s_problem_v2, 4),
            "lambda": 0.2,
            "S_final": round(s_final_v2, 4),
            "theoretical_basis": "None (ad-hoc weighted average)"
        },
        "V6_Enhanced": {
            "formula": "S_final = S_rerank · exp(α_eff · Σ w_i · φ_i)",
            "boost": breakdown["boost"],
            "α_eff": breakdown["α_eff"],
            "H_severity": breakdown["H_severity"],
            "KL_penalty": breakdown["KL_penalty"],
            "S_final": round(s_final_v6, 4),
            "theoretical_basis": "Query Likelihood + Dirichlet + IDF + Platt Calibration + KL Regularization + Gated Contextual Features",
            "factors": breakdown["factors"]
        },
        "difference": round(s_final_v6 - s_final_v2, 4)
    }


# =============================================================================
# QUERY EXPANSION (unchanged from V2)
# =============================================================================

def expand_query_with_problems(
    query: str,
    problems: List[Dict],
    config: H2LConfigV3 = None
) -> str:
    """
    Query Expansion: q' = q ⊕ expand(P_detected)
    
    Sort by prior probability (high severity first)
    """
    if config is None:
        config = DEFAULT_CONFIG_V3
    
    if not problems:
        return query
    
    priors = calculate_problem_prior(problems, config)
    
    # Sort by prior (severity-weighted)
    sorted_problems = sorted(
        problems,
        key=lambda p: priors.get(p.get('code', ''), 0),
        reverse=True
    )
    
    expansion_terms = []
    seen = set()
    
    for problem in sorted_problems[:config.QUERY_EXPANSION_MAX_PROBLEMS]:
        name = problem.get('name', '')
        if name and name.lower() not in seen:
            expansion_terms.append(name)
            seen.add(name.lower())
        
        for kw in problem.get('keywords', [])[:config.QUERY_EXPANSION_MAX_KEYWORDS]:
            if kw and kw.lower() not in seen:
                expansion_terms.append(kw)
                seen.add(kw.lower())
    
    if expansion_terms:
        return query + ' ' + ' '.join(expansion_terms)
    return query


# =============================================================================
# TESTING
# =============================================================================

def test_probabilistic_formulation():
    """Test and demonstrate V6 enhanced log-linear probabilistic scoring"""
    
    print("\n" + "="*70)
    print("🧪 H2L V6: Enhanced Log-Linear Probabilistic Problem-Aware Retrieval")
    print("="*70)
    
    # Test case
    problems = [
        {
            "code": "X60-X84",
            "name": "ทำร้ายตัวเอง",
            "severity": 5,
            "confidence": 0.92,
            "keywords": ["ทำร้ายตัวเอง", "ไม่อยากมีชีวิต", "ฆ่าตัวตาย","พยายามฆ่าตัวตาย","คิดสั้น","พยายามทำร้ายตัวเอง"]
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
    
    query_text = """
    ผู้ป่วยมีอาการซึมเศร้า หมดหวัง พูดเรื่องไม่อยากมีชีวิตอยู่บ่อยครั้ง
    เคยพยายามทำร้ายตัวเอง มีประวัติการรักษาโรคซึมเศร้า
    """
    
    doc_text = """
    ผู้ป่วยมีอาการซึมเศร้า หมดหวัง พูดเรื่องไม่อยากมีชีวิตอยู่บ่อยครั้ง
    เคยพยายามทำร้ายตัวเอง มีประวัติการรักษาโรคซึมเศร้า
    """
    
    rerank_score = 0.85
    
    print("\n📊 Test Case:")
    print(f"   S_rerank = {rerank_score}")
    print(f"   Problems: {len(problems)}")
    for p in problems:
        print(f"     - {p['code']}: {p['name']} (sev={p['severity']}, conf={p['confidence']})")
    
    # Calculate priors (Dirichlet-smoothed)
    print("\n📐 Step 1: Dirichlet-Smoothed Priors P(p)")
    priors = calculate_problem_prior(problems)
    for code, prior in priors.items():
        print(f"   P({code}) = {prior:.4f}")
    
    # Shannon entropy & KL penalty
    h = _compute_severity_entropy(priors)
    kl = calculate_kl_concentration_penalty(priors)
    print(f"\n   H_severity  = {h:.4f} bits")
    print(f"   KL_penalty  = {kl:.4f}")
    
    # Calculate final score with V6
    print("\n📐 Step 2: V6 Enhanced Log-Linear Score")
    final_score, breakdown = calculate_final_score_probabilistic(
        rerank_score=rerank_score,
        problems=problems,
        doc_text=doc_text,
        query_text=query_text
    )
    
    print(f"\n   Formula: S_final = S_rerank · exp(α_eff · Σ w_i · φ_i)")
    print(f"   α₀ = {breakdown['α₀']}, H = {breakdown['H_severity']:.4f}, KL = {breakdown['KL_penalty']:.4f}")
    print(f"   α_eff = {breakdown['α_eff']:.4f}")
    print(f"\n   Per-problem contributions (V6 Enhanced):")
    for f in breakdown['factors']:
        print(f"     {f['code']}:")
        print(f"       P(p|q)_raw = {f['P(p|q)_raw']}")
        print(f"       C(p|q)     = {f['C(p|q)']} (calibrated)")
        print(f"       P(d|p)     = {f['P(d|p)']} ({f['match_method']})")
        print(f"       P(p)       = {f['P(p)']}")
        print(f"       IDF        = {f['IDF']}")
        print(f"       G_neg      = {f['G_neg']}")
        print(f"       w_i        = {f['w_i']}")
        print(f"       Φ_i        = {f['Φ_i']}")
        print(f"       w·φ        = {f['w·φ']}")
    
    print(f"\n   Σ(w·φ)   = {breakdown['Σ(w·φ)']}")
    print(f"   exponent = α_eff × Σ(w·φ) = {breakdown['exponent']}")
    print(f"   boost    = exp(exponent) = {breakdown['boost']:.4f}")
    print(f"   S_final  = {rerank_score} × {breakdown['boost']:.4f} = {final_score:.4f}")
    
    # Compare V2 vs V6
    print("\n" + "="*70)
    print("📊 V2 vs V6 Comparison")
    print("="*70)
    
    comparison = compare_v2_v3(rerank_score, problems, doc_text)
    
    print("\n V2 (Weighted Average):")
    print(f"   Formula: {comparison['V2_Simplified']['formula']}")
    print(f"   S_problem = {comparison['V2_Simplified']['S_problem']}")
    print(f"   S_final = {comparison['V2_Simplified']['S_final']}")
    print(f"   Theory: {comparison['V2_Simplified']['theoretical_basis']}")
    
    print("\n V6 (Enhanced Log-Linear Probabilistic):")
    print(f"   Formula: {comparison['V6_Enhanced']['formula']}")
    print(f"   boost = {comparison['V6_Enhanced']['boost']}")
    print(f"   α_eff = {comparison['V6_Enhanced']['α_eff']}")
    print(f"   H_severity = {comparison['V6_Enhanced']['H_severity']}")
    print(f"   KL_penalty = {comparison['V6_Enhanced']['KL_penalty']}")
    print(f"   S_final = {comparison['V6_Enhanced']['S_final']}")
    print(f"   Theory: {comparison['V6_Enhanced']['theoretical_basis']}")
    
    print(f"\n   Difference: {comparison['difference']:+.4f}")
    
    print("\n" + "="*70)
    print("✅ V6 Test completed!")
    print("="*70)


# =============================================================================
# BACKWARD COMPATIBILITY WITH V2
# =============================================================================
# ให้ H2L retrievers ที่ยัง import V2 APIs ทำงานได้

# Alias: H2LConfig → H2LConfigV3
H2LConfig = H2LConfigV3

# Alias: calculate_final_retrieval_score() → calculate_final_retrieval_score_v3()
def calculate_final_retrieval_score(
    rerank_score: float,
    problem_relevance: float,
    config = None
) -> float:
    """
    Backward compatibility wrapper for V2 API

    V2 API:
        calculate_final_retrieval_score(rerank_score, problem_relevance, config)

    Maps to V3:
        S_final = rerank_score × (1 + problem_relevance)

    Note: This is a simplified version. For full probabilistic scoring,
    use calculate_final_score_probabilistic() directly.
    """
    # Simple multiplicative boost (V2 style)
    return rerank_score * (1.0 + problem_relevance)


# Alias for old function name
def calculate_problem_relevance_with_severity(
    doc_text: str,
    detected_problems: List[Dict]
) -> float:
    """
    Backward compatibility wrapper 

    V2 API:
        calculate_problem_relevance_with_severity(doc_text, detected_problems)
        Returns: S_problem (severity-weighted keyword match ratio)

    Maps to V3:
        Use keyword-based P(d|p) calculation
    """
    if not detected_problems:
        return 0.0

    total_severity = sum(p.get('severity', 1) for p in detected_problems)
    if total_severity == 0:
        return 0.0

    matched_severity = 0
    for problem in detected_problems:
        # Use V3's keyword matching
        p_match = calculate_doc_problem_probability_keyword(doc_text, problem, soft=True)
        matched_severity += p_match * problem.get('severity', 1)

    return matched_severity / total_severity


# =============================================================================
# H2L UNIFIED RETRIEVER - Composition Pattern
# =============================================================================

# Strategy-specific alpha values (exported for tests and external use)
# All use α=1.0 for fair paired comparison (same base retriever ± H2L)
STRATEGY_ALPHA = {
    "h2l-bm25":      1.0,
    "h2l-naive_rag":  1.0,
    "h2l-hybrid":     1.0,
    "h2l-hyde":       1.0,
    "h2l-full":       1.0,
}

# Mapping from strategy_mode to constructor parameters
_STRATEGY_MODE_MAP = {
    "h2l-bm25":      {"base_strategy": "bm25_only",  "enable_adaptive": False, "enable_multihop": False},
    "h2l-naive_rag": {"base_strategy": "naive_rag",   "enable_adaptive": False, "enable_multihop": False},
    "h2l-hybrid":    {"base_strategy": "hybrid",      "enable_adaptive": False, "enable_multihop": False},
    "h2l-hyde":      {"base_strategy": "hyde",        "enable_adaptive": False, "enable_multihop": False},
    "h2l-full":      {"base_strategy": "hybrid",      "enable_adaptive": True,  "enable_multihop": True},
}


class H2LUnifiedRetriever:
    """
    H2L Unified Retrieval Framework
    ================================

    Unified framework that wraps baseline retrievers with H2L problem-aware scoring.
    Uses Composition Pattern instead of Inheritance for better modularity.

    Features (can be toggled for Ablation Study):
    - Core H2L Scoring: Problem-aware probabilistic scoring
    - Adaptive Boundaries: Dynamic threshold adjustment
    - Multi-hop Retrieval: Iterative query expansion with LLM

    Usage:
        # Basic H2L (Core only)
        retriever = H2LUnifiedRetriever(
            base_strategy="hybrid",
            config=config,
            enable_adaptive=False,
            enable_multihop=False
        )

        # Full Framework (All features)
        retriever = H2LUnifiedRetriever(
            base_strategy="hybrid",
            config=config,
            enable_adaptive=True,
            enable_multihop=True
        )

    Ablation Study:
    - Experiment 1: Core only (enable_adaptive=False, enable_multihop=False)
    - Experiment 2: Core + Adaptive (enable_adaptive=True, enable_multihop=False)
    - Experiment 3: Core + Multi-hop (enable_adaptive=False, enable_multihop=True)
    - Experiment 4: Full Framework (enable_adaptive=True, enable_multihop=True)
    """

    def __init__(
        self,
        config,
        shared_components=None,
        base_strategy: str = "hybrid",
        enable_adaptive: bool = False,
        enable_multihop: bool = False,
        h2l_config: H2LConfigV3 = None,
        strategy_mode: Optional[str] = None
    ):
        """
        Initialize H2L Unified Retriever

        Args:
            config: Main configuration object
            shared_components: Shared embeddings/index
            base_strategy: Baseline retriever ("hybrid", "dynamic", "multihop", "adaptive")
            enable_adaptive: Enable adaptive boundary adjustment
            enable_multihop: Enable multi-hop retrieval with LLM
            h2l_config: H2L-specific configuration
            strategy_mode: Convenience param (e.g. "h2l-dynamic") — auto-maps to base_strategy + flags
        """
        # If strategy_mode is provided, auto-map to base_strategy + flags
        if strategy_mode and strategy_mode in _STRATEGY_MODE_MAP:
            mapped = _STRATEGY_MODE_MAP[strategy_mode]
            base_strategy = mapped["base_strategy"]
            enable_adaptive = mapped["enable_adaptive"]
            enable_multihop = mapped["enable_multihop"]
            self.strategy_mode = strategy_mode
        else:
            self.strategy_mode = None

        self.config = config
        self.base_strategy = base_strategy.lower()
        self.enable_adaptive = enable_adaptive
        self.enable_multihop = enable_multihop
        self.h2l_config = h2l_config or DEFAULT_CONFIG_V3

        # Strategy-specific alpha values for differentiation
        self.alpha = self._get_strategy_alpha()

        # Initialize base retriever using composition
        self.base_retriever = self._init_base_retriever(config, shared_components)

        # Initialize multi-hop components if enabled
        if self.enable_multihop:
            self._init_multihop_components()

    def _get_strategy_alpha(self) -> float:
        """
        Get strategy-specific alpha value for problem-aware scoring.

        V6 fix B2: Uses STRATEGY_ALPHA dict for consistency with
        paired comparison design (all strategies use α=1.0 by default).
        Override via STRATEGY_ALPHA dict for experiments.

        Returns:
            Alpha value for this strategy
        """
        # Use the centralized STRATEGY_ALPHA dict for consistency
        if self.strategy_mode and self.strategy_mode in STRATEGY_ALPHA:
            return STRATEGY_ALPHA[self.strategy_mode]
        return 1.0  # Default for paired comparisons

    def _init_base_retriever(self, config, shared_components):
        """Initialize baseline retriever based on strategy"""
        from retrieval_engine import HybridRetriever

        if self.base_strategy == "bm25_only":
            from unified_baselines import BM25OnlyBaseline
            return BM25OnlyBaseline(config, shared_components)
        elif self.base_strategy == "naive_rag":
            from unified_baselines import NaiveRAGBaseline
            return NaiveRAGBaseline(config, shared_components)
        elif self.base_strategy == "hyde":
            from unified_baselines import HyDEBaseline
            return HyDEBaseline(config, shared_components)
        else:  # default to hybrid
            return HybridRetriever(config, shared_components)

    def _init_multihop_components(self):
        """Initialize LLM components for multi-hop retrieval"""
        try:
            from openai import OpenAI

            base_url = "http://localhost:11434/v1"
            api_key = "ollama"

            if self.config:
                if getattr(self.config, 'USE_LOCAL_LLM', True):
                    base_url = getattr(self.config, 'LOCAL_LLM_BASE_URL', base_url)
                    self.llm_model = getattr(self.config, 'LOCAL_LLM_MODEL', 'llama3.2:3b')
                else:
                    base_url = "https://openrouter.ai/api/v1"
                    self.llm_model = getattr(self.config, 'OPENROUTER_MODEL', 'openai/gpt-4o-mini')
                    api_key = getattr(self.config, 'OPENROUTER_API_KEY', '')

            self.llm_client = OpenAI(base_url=base_url, api_key=api_key)

        except Exception as e:
            self.llm_client = None
            self.enable_multihop = False

    def retrieve(
        self,
        query: str,
        explicit_problems: List[Dict] = None,
        top_k_override: int = None
    ) -> List:
        """
        Main retrieval method with H2L problem-aware scoring

        Args:
            query: User query
            explicit_problems: Detected problems from H2LDetector
            top_k_override: Override default top_k

        Returns:
            List of RetrievalResult with H2L scores
        """
        # Step 1: Expand query with problems (if available)
        expanded_query = query
        if explicit_problems:
            expanded_query = expand_query_with_problems(
                query,
                explicit_problems,
                self.h2l_config
            )

        # Step 2: Base retrieval
        if self.enable_multihop and self.llm_client and explicit_problems:
            # Multi-hop retrieval with LLM query reformulation
            results = self._retrieve_multihop(expanded_query, explicit_problems, top_k_override)
        else:
            # Single-hop retrieval
            results = self.base_retriever.retrieve(expanded_query, top_k_override)

        # Step 3: Apply H2L problem-aware scoring
        if explicit_problems:
            results = self._apply_h2l_scoring(results, explicit_problems, query)

        # Step 4: Apply adaptive boundaries (if enabled)
        if self.enable_adaptive and explicit_problems:
            results = self._apply_adaptive_boundaries(results, explicit_problems)

        # Step 5: Sort by final score
        results.sort(key=lambda x: x.final_score, reverse=True)

        return results

    def _retrieve_multihop(
        self,
        query: str,
        problems: List[Dict],
        top_k_override: int = None
    ) -> List:
        """
        Multi-hop retrieval with LLM query reformulation

        Addresses:
        - Error Propagation: LLM validates retrieval quality before next hop
        - Keyword Drift: LLM generates semantically coherent queries
        """
        max_hops = 3
        all_results = []
        current_query = query

        for hop in range(1, max_hops + 1):
            logger.info(f"[Multi-hop] Hop {hop}/{max_hops}")

            # Retrieve with current query
            hop_results = self.base_retriever.retrieve(current_query, top_k_override)
            all_results.extend(hop_results)

            if hop < max_hops:
                # Generate next hop query using LLM
                next_query = self._generate_next_hop_query_llm(
                    query, hop_results[:5], hop, problems
                )

                if next_query:
                    current_query = next_query
                else:
                    # LLM suggests stopping
                    logger.info(f"[Multi-hop] Stopping at hop {hop} (sufficient information)")
                    break

        # Remove duplicates
        seen_ids = set()
        unique_results = []
        for r in all_results:
            doc_id = r.doc.id if hasattr(r.doc, 'id') else id(r.doc)
            if doc_id not in seen_ids:
                seen_ids.add(doc_id)
                unique_results.append(r)

        return unique_results

    def _fallback_keyword_expansion(
        self,
        original_query: str,
        problems: List[Dict],
        hop_number: int
    ) -> Optional[str]:
        """
        Fallback query expansion when LLM is unavailable.
        Hop 2: เพิ่มชื่อปัญหา, Hop 3: เพิ่ม keywords
        """
        if not problems:
            return None

        if hop_number == 1:
            # Hop 2 query: เพิ่มชื่อปัญหาหลัก
            names = [p.get('name', '') for p in problems[:3] if p.get('name')]
            if names:
                expanded = original_query + ' ' + ' '.join(names)
                logger.info(f"[Multi-hop] Fallback hop 2: added problem names → '{expanded[:80]}...'")
                return expanded
        elif hop_number == 2:
            # Hop 3 query: เพิ่ม keywords จากปัญหา
            keywords = []
            for p in problems[:3]:
                keywords.extend(p.get('keywords', [])[:2])
            if keywords:
                expanded = original_query + ' ' + ' '.join(keywords[:5])
                logger.info(f"[Multi-hop] Fallback hop 3: added keywords → '{expanded[:80]}...'")
                return expanded

        return None

    def _generate_next_hop_query_llm(
        self,
        original_query: str,
        retrieved_docs: List,
        hop_number: int,
        problems: List[Dict]
    ) -> Optional[str]:
        """Generate next hop query using LLM, with keyword fallback"""
        # Fallback: keyword expansion from problems when LLM is unavailable
        if not self.llm_client or not retrieved_docs:
            return self._fallback_keyword_expansion(original_query, problems, hop_number)

        try:
            # Build context from retrieved documents
            context_snippets = []
            for i, result in enumerate(retrieved_docs[:3], 1):
                snippet = result.doc.text[:200] + "..." if len(result.doc.text) > 200 else result.doc.text
                context_snippets.append(f"[Doc {i}] {snippet}")

            context_text = "\n".join(context_snippets)

            # Build problem context
            problem_context = ""
            if problems:
                problem_names = [p.get('name', '') for p in problems[:3]]
                problem_context = f"\n\nDetected Problems: {', '.join(problem_names)}"

            # English instructions, Thai output (qwen2.5 is EN/CN bilingual - Thai prompts cause Chinese output)
            prompt = f"""You are a social work information retrieval assistant.
You MUST respond in Thai language. Never use Chinese.

Original query: "{original_query}"{problem_context}

Documents found in hop {hop_number}:
{context_text}

Task: Analyze whether the retrieved documents fully answer the query. If not, write a new search query (short, 5-10 words, in Thai) to find missing information.

If the documents already fully answer the query, respond with "STOP".

New search query:"""

            response = self.llm_client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {"role": "system", "content": "You are a social work information retrieval expert. Always respond in Thai language. Never use Chinese."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=100
            )

            new_query = response.choices[0].message.content.strip()

            if "STOP" in new_query.upper() or len(new_query) < 3:
                return None

            logger.info(f"[Multi-hop] LLM reformulated query: '{new_query}'")
            return new_query

        except Exception as e:
            logger.warning(f"⚠️ LLM query reformulation failed: {e}")
            return None

    def _get_embedder(self):
        """Get the embedding model from the base retriever (if available)"""
        try:
            return self.base_retriever.dense_retriever.embedder
        except AttributeError:
            return None

    def _compute_problem_embeddings(
        self,
        problems: List[Dict],
        embedder
    ) -> Dict[str, np.ndarray]:
        """
        Compute semantic embeddings for detected problems.
        Uses problem name + keywords as the text representation.

        Caches results to avoid recomputation within the same query.
        """
        if embedder is None:
            return {}

        problem_embeddings = {}
        texts_to_encode = []
        codes = []

        for p in problems:
            code = p.get('code', 'unknown')
            # Build rich text representation: name + keywords
            parts = []
            if p.get('name'):
                parts.append(p['name'])
            for kw in p.get('keywords', [])[:5]:
                if kw:
                    parts.append(kw)
            text = ' '.join(parts) if parts else code
            texts_to_encode.append(text)
            codes.append(code)

        if texts_to_encode:
            try:
                embeddings = embedder.encode(
                    texts_to_encode,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False
                )
                for code, emb in zip(codes, embeddings):
                    problem_embeddings[code] = emb
            except Exception as e:
                logger.warning(f"Failed to compute problem embeddings: {e}")

        return problem_embeddings

    def _compute_doc_embeddings(
        self,
        results: List,
        embedder
    ) -> Dict[int, np.ndarray]:
        """
        Batch-compute document embeddings for scoring.
        Uses the first 512 chars of each document for efficiency.
        """
        if embedder is None:
            return {}

        doc_embeddings = {}
        texts = []
        doc_ids = []

        for r in results:
            doc_id = r.doc.id if hasattr(r.doc, 'id') else id(r.doc)
            # Use truncated text for efficiency
            text = r.doc.text[:512] if r.doc.text else ""
            texts.append(text)
            doc_ids.append(doc_id)

        if texts:
            try:
                embeddings = embedder.encode(
                    texts,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False
                )
                for doc_id, emb in zip(doc_ids, embeddings):
                    doc_embeddings[doc_id] = emb
            except Exception as e:
                logger.warning(f"Failed to compute doc embeddings: {e}")

        return doc_embeddings

    def _apply_h2l_scoring(
        self,
        results: List,
        problems: List[Dict],
        query_text: str = None
    ) -> List:
        """
        Apply H2L problem-aware scoring with semantic embeddings.

        Optimized: pre-computes all per-problem invariants once,
        then passes them to calculate_final_score_probabilistic()
        via precomputed dict — avoids N×P redundant computations.
        """
        config = self.h2l_config

        # V6 Stateless Fix: Always use config directly, avoid stale self.alpha/self.enable_adaptive
        config_alpha = getattr(config, 'ALPHA', 1.0)
        config_adaptive_enabled = getattr(config, 'ADAPTIVE_ALPHA_ENABLE', True)

        if config_adaptive_enabled and problems:
            # Note: We now defer detailed adaptive calculation to calculate_adaptive_alpha()
            # but we need a base to work from.
            adaptive_alpha = config_alpha 
        else:
            adaptive_alpha = config_alpha

        # Compute semantic embeddings for problem-aware scoring
        embedder = self._get_embedder()
        problem_embeddings = self._compute_problem_embeddings(problems, embedder)
        doc_embeddings = self._compute_doc_embeddings(results, embedder)

        use_semantic = bool(problem_embeddings and doc_embeddings)
        if use_semantic:
            logger.info(f"[H2L-Scoring] Using SEMANTIC matching (α={adaptive_alpha:.2f})")
        else:
            logger.info(f"[H2L-Scoring] Using KEYWORD fallback (α={adaptive_alpha:.2f})")

        # ── Pre-compute all per-problem invariants (once, not per result) ──
        priors = calculate_problem_prior(problems, config)
        h_severity = _compute_severity_entropy(priors)
        kl_penalty = calculate_kl_concentration_penalty(priors, config)
        
        alpha_base = adaptive_alpha
        # V6 fix B1: Use calculate_adaptive_alpha() for consistency with non-precomputed path
        alpha_v6 = calculate_adaptive_alpha(problems, config, alpha_base)
        alpha_eff = alpha_v6 * (1.0 + config.ENTROPY_SCALE_DELTA * h_severity)
        alpha_eff *= (1.0 - config.KL_KAPPA * kl_penalty)
        alpha_eff = max(0.01, alpha_eff)
        
        co_weights = calculate_co_occurrence_weights(
            problems, problem_embeddings if use_semantic else None, config
        )
        max_severity = max((p.get('severity', 1) for p in problems), default=5)
        
        # Pre-compute per-problem: calibration, IDF, negation gates
        calibrations = {}
        idfs = {}
        neg_gates = {}
        for problem in problems:
            code = problem.get('code', 'unknown')
            severity = problem.get('severity', 1)
            raw_det = calculate_detection_probability(problem)
            calibrations[code] = (raw_det, calibrate_confidence(raw_det, severity, max_severity, config))
            idfs[code] = calculate_idf_weight(problem, config=config)
            neg_gates[code] = calculate_sentence_polarity(problem, query_text, config)
        
        # V6 fix: include bayesian_prior in precomputed to avoid it defaulting to 1.0
        bayesian_prior = calculate_bayesian_prior(problems, priors, config)
        
        precomputed = {
            'priors': priors,
            'h_severity': h_severity,
            'kl_penalty': kl_penalty,
            'alpha_eff': alpha_eff,
            'co_weights': co_weights,
            'max_severity': max_severity,
            'calibrations': calibrations,
            'idfs': idfs,
            'neg_gates': neg_gates,
            'bayesian_prior': bayesian_prior,
        }

        for result in results:
            doc_id = result.doc.id if hasattr(result.doc, 'id') else id(result.doc)
            doc_emb = doc_embeddings.get(doc_id) if use_semantic else None

            # Safely get base score
            base_score = getattr(result, 'rerank_score', None)
            if base_score is None:
                base_score = getattr(result, 'score', None)
            if base_score is None:
                base_score = getattr(result, 'final_score', 0.0)

            final_score, breakdown = calculate_final_score_probabilistic(
                rerank_score=base_score,
                problems=problems,
                doc_text=result.doc.text,
                doc_embedding=doc_emb,
                problem_embeddings=problem_embeddings if use_semantic else None,
                config=config,
                alpha_override=adaptive_alpha,
                query_text=query_text,
                precomputed=precomputed
            )

            # Expose the real H2L scoring trace to API/UI layers. This keeps
            # retrieval behavior unchanged while allowing explainability panels
            # to show which factors changed the document score.
            try:
                result.h2l_base_score = base_score
                result.h2l_final_score = final_score
                result.h2l_breakdown = breakdown
                result.h2l_semantic_used = use_semantic
            except Exception:
                pass

            # Update the score
            if hasattr(result, 'rerank_score'):
                result.rerank_score = final_score
            elif hasattr(result, 'score'):
                result.score = final_score

        return results

    def _apply_adaptive_boundaries(
        self,
        results: List,
        problems: List[Dict]
    ) -> List:
        """
        Apply adaptive boundary adjustment based on problem severity

        High severity problems → Lower threshold (retrieve more)
        Low severity problems → Higher threshold (retrieve less)
        """
        if not problems:
            return results

        # Calculate average severity
        avg_severity = sum(p.get('severity', 1) for p in problems) / len(problems)

        # Adaptive threshold (inverse relationship with severity)
        # High severity (5) → low threshold (0.3)
        # Low severity (1) → high threshold (0.7)
        base_threshold = 0.5
        severity_factor = (5 - avg_severity) / 5  # Normalize to [0, 1]
        adaptive_threshold = base_threshold + (severity_factor * 0.2)

        logger.info(f"[Adaptive] Avg Severity: {avg_severity:.2f} → Threshold: {adaptive_threshold:.2f}")

        # Filter results based on adaptive threshold
        filtered_results = [
            r for r in results
            if r.final_score >= adaptive_threshold
        ]

        # Ensure minimum results
        if len(filtered_results) < 5 and len(results) >= 5:
            filtered_results = results[:5]

        return filtered_results


if __name__ == "__main__":
    test_probabilistic_formulation()
