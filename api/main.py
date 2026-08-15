import csv
import difflib
import hashlib
import json
import logging
import math
import os
import re
import threading
import time
import traceback
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set, Tuple
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from h2l.detector import H2LDetectorV3, classify_review_status_dict

logger = logging.getLogger(__name__)

DEFAULT_STRATEGY = "h2l-hybrid"
TAXONOMY_PATH = "data/problem_codes.json"
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
DOC_SCALING_OPTIONS = [5, 10, 15, 20]
DEFAULT_DOC_TOP_K = 15
EVALUATION_PROGRESS_FILES = {
    "proper_eval": Path("evaluation_results/proper_eval_progress.json"),
    "sentence_polarity": Path("evaluation_results/sentence_polarity_progress.json"),
}
STRATEGY_PAIRS = [
    {
        "family": "bm25",
        "label": "BM25",
        "baseline": "bm25_only",
        "enhanced": "h2l-bm25",
        "description": "ค้นจากคำตรงและคำใกล้เคียง เหมาะเป็นฐานเปรียบเทียบ lexical retrieval",
    },
    {
        "family": "dense",
        "label": "Dense / Naive RAG",
        "baseline": "naive_rag",
        "enhanced": "h2l-naive_rag",
        "description": "ค้นด้วย embedding อย่างเดียว เพื่อดูผลของ semantic retrieval แบบพื้นฐาน",
    },
    {
        "family": "hyde",
        "label": "HyDE",
        "baseline": "hyde",
        "enhanced": "h2l-hyde",
        "description": "ให้ LLM สร้าง hypothetical document ก่อนค้น ถ้า LLM ไม่พร้อมจะ degraded อย่างชัดเจน",
    },
    {
        "family": "hybrid",
        "label": "Hybrid",
        "baseline": "basic",
        "enhanced": "h2l-hybrid",
        "description": "รวม BM25 + embedding + rerank เป็นค่าเริ่มต้นสำหรับเคสจริง",
    },
]
BASELINE_LIMITATION_GUIDE = {
    "bm25": {
        "baseline": "BM25",
        "limitation": "ติดคำตรงและคำใกล้เคียง ถ้าเคสใช้ถ้อยคำคนละชุดกับ taxonomy อาจหาเอกสารสำคัญไม่เจอ",
        "h2l_response": "ใช้ problem prior + semantic problem-document signal เพื่อดันเอกสารที่ตรงความหมายของปัญหา แม้คำไม่ตรงกันทุกคำ",
        "primary_metrics": ["Recall@K", "nDCG@10", "MAP"],
        "evidence_slice": "lexical mismatch cases",
    },
    "dense": {
        "baseline": "Dense / Naive RAG",
        "limitation": "จับความหมายกว้างได้ดี แต่เสี่ยง overmatch กับประโยคปฏิเสธหรือบริบทคนละบทบาท",
        "h2l_response": "ใช้ sentence polarity, actor-target-action และ problem confidence gate เพื่อลด false positive",
        "primary_metrics": ["False positive rate", "Polarity F1", "Precision@K"],
        "evidence_slice": "negation / actor-target cases",
    },
    "hyde": {
        "baseline": "HyDE",
        "limitation": "ต้องให้ LLM สร้าง hypothetical document ก่อนค้น จึงเสี่ยง hallucination หรือ fallback ถ้า LLM ไม่พร้อม",
        "h2l_response": "ผูกการเพิ่มคะแนนกับ taxonomy/problem evidence ที่ระบบตรวจพบจริง และต้องรายงาน HyDE fallback/LLM readiness แยก",
        "primary_metrics": ["MAP", "Unsupported evidence rate", "Latency", "Fallback rate"],
        "evidence_slice": "LLM-generated query cases",
    },
    "hybrid": {
        "baseline": "Hybrid",
        "limitation": "รวม lexical+dense ได้ดี แต่ alpha/weight มักเป็นค่าคงที่ ไม่รู้ว่าปัญหาใดควรดันมากหรือน้อยในแต่ละเคส",
        "h2l_response": "ใช้ alpha_eff, severity entropy, KL penalty และ polarity gate เพื่อปรับน้ำหนักตาม problem distribution ของเคส",
        "primary_metrics": ["MAP", "MRR", "nDCG@10", "Ablation delta"],
        "evidence_slice": "multi-problem / severity-sensitive cases",
    },
}
METRIC_POLICY = {
    "primary": [
        {"metric": "MAP", "why": "วัดคุณภาพ ranking โดยรวม เหมาะเป็น headline เมื่อเทียบ retrieval systems"},
        {"metric": "MRR", "why": "ดูว่าเอกสารที่เกี่ยวข้องชิ้นแรกขึ้นมาเร็วแค่ไหน"},
        {"metric": "nDCG@10", "why": "ดูคุณภาพลำดับเอกสารที่ผู้วิจัยยังอ่านได้จริง โดยให้รางวัลกับอันดับบน"},
    ],
    "safety": [
        {"metric": "Polarity F1", "why": "วัดสมดุลของ sentence polarity โดยเฉพาะ negation/actor-target"},
        {"metric": "False positive rate", "why": "สำคัญกับเคสสังคม/คลินิก เพราะการแจ้งปัญหาเกินบริบททำให้ตีความผิด"},
    ],
    "coverage": [
        {"metric": "Recall@K", "why": "ดูว่าขยาย K แล้วครอบคลุมเอกสารรองรับมากขึ้นหรือไม่"},
        {"metric": "Detector exact/Jaccard", "why": "แยกปัญหาว่าแพ้เพราะ detector หรือเพราะ scoring"},
    ],
    "secondary": [
        {"metric": "P@5/F1@5", "why": "ใช้ดูความแน่นของ evidence ชุดแรก แต่อย่าใช้ตัดสิน H2L ทั้งระบบเพียงตัวเดียว"},
        {"metric": "Latency", "why": "เป็นต้นทุนของโมเดล ไม่ใช่ตัวชี้วัดคุณภาพหลัก"},
    ],
}
VALID_STRATEGIES = {
    strategy
    for pair in STRATEGY_PAIRS
    for strategy in (pair["baseline"], pair["enhanced"])
}
STRATEGY_REQUIRED_COMPONENTS = {
    "bm25_only": ["bm25"],
    "h2l-bm25": ["bm25"],
    "naive_rag": ["vector_index", "embedding_model"],
    "h2l-naive_rag": ["vector_index", "embedding_model"],
    "hyde": ["vector_index", "embedding_model"],
    "h2l-hyde": ["vector_index", "embedding_model"],
    "basic": ["bm25", "vector_index", "embedding_model"],
    "h2l-hybrid": ["bm25", "vector_index", "embedding_model"],
}
STRATEGY_ALIASES = {
    "detector-local": "h2l-hybrid",
    "h2l_basic": "h2l-hybrid",
    "h2l_adaptive": "h2l-hybrid",
    "h2l_dynamic": "h2l-hybrid",
    "h2l_multihop": "h2l-hybrid",
    "adaptive": "basic",
    "dynamic": "basic",
    "multihop": "basic",
}
NEGATION_MARKERS = [
    "ไม่ได้",
    "ไม่มี",
    "ไม่เคย",
    "ไม่ใช่",
    "ไม่พบ",
    "ปฏิเสธ",
    "ยังไม่",
    "ไม่แสดง",
    "ไม่ปรากฏ",
    "ไม่",
    "ไร้",
    "ปราศจาก",
]
POLARITY_SCOPE_BREAKERS = [
    ",", "，", ".", "。", ";", "；", "\n",
    " แต่", " ทว่า", " อย่างไรก็ตาม", " แล้ว", " จึง",
    " เลย", " เพราะ", " เนื่องจาก", " ทำให้", " ส่งผลให้",
    " ยอมรับ", " พบว่า", " ระบุว่า", " บอกว่า",
]
POLARITY_NEGATION_GATE = 0.4

_BASE_DIR = Path(__file__).resolve().parent.parent
SOCIAL_ACTOR_ROLES_PATH = _BASE_DIR / "data" / "social_actor_roles.json"
SOCIAL_ACTIONS_PATH = _BASE_DIR / "data" / "social_actions.json"


@lru_cache(maxsize=1)
def _social_actor_config() -> Dict[str, Dict[str, Any]]:
    fallback = {
        "[person]": {"roles": ["target"], "group": "client", "normalized": "ผู้รับบริการ/เด็ก"},
        "เด็ก": {"roles": ["target"], "group": "child", "normalized": "ผู้รับบริการ/เด็ก"},
        "นักเรียน": {"roles": ["target"], "group": "school", "normalized": "ผู้รับบริการ/เด็ก"},
        "พ่อ": {"roles": ["agent", "target", "context"], "group": "family", "normalized": "พ่อ"},
        "แม่": {"roles": ["agent", "target", "context"], "group": "family", "normalized": "แม่"},
        "บิดา": {"roles": ["agent", "target", "context"], "group": "family", "normalized": "บิดา"},
        "มารดา": {"roles": ["agent", "target", "context"], "group": "family", "normalized": "มารดา"},
        "ลูก": {"roles": ["agent", "target"], "group": "family", "normalized": "ลูก"},
        "สามี": {"roles": ["agent", "target"], "group": "partner", "normalized": "สามี"},
        "ภรรยา": {"roles": ["agent", "target"], "group": "partner", "normalized": "ภรรยา"},
        "เพื่อน": {"roles": ["agent", "target"], "group": "peer", "normalized": "เพื่อน"},
        "ครู": {"roles": ["agent", "context"], "group": "school", "normalized": "ครู"},
        "ผู้สูงอายุ": {"roles": ["target"], "group": "elder", "normalized": "ผู้สูงอายุ"},
        "ผู้พิการ": {"roles": ["target"], "group": "disability", "normalized": "ผู้พิการ"},
    }
    path = Path(__file__).parent / SOCIAL_ACTOR_ROLES_PATH
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return {str(key).lower(): value for key, value in data.items()}
    except Exception as exc:
        logger.warning("Could not load social actor ontology from %s: %s", path, exc)
        return fallback


@lru_cache(maxsize=1)
def _social_action_config() -> Dict[str, Dict[str, Any]]:
    fallback = {
        "ตัดเอง": {"domain": "self_harm", "pattern": "self", "normalized": "ตัดเอง"},
        "รอยกรีด": {"domain": "injury_evidence", "pattern": "evidence_mark", "normalized": "รอยกรีด"},
        "กรีด": {"domain": "self_harm", "pattern": "self_or_harm", "normalized": "กรีด"},
        "ทำร้ายตัวเอง": {"domain": "self_harm", "pattern": "self", "normalized": "ทำร้ายตัวเอง"},
        "รังแก": {"domain": "bullying", "pattern": "agent_action_target", "normalized": "รังแก"},
        "ด่าว่า": {"domain": "emotional_abuse", "pattern": "agent_action_target", "normalized": "ด่าว่า"},
        "ดุด่า": {"domain": "emotional_abuse", "pattern": "agent_action_target", "normalized": "ดุด่า"},
        "โพสต์รูปล้อเลียน": {"domain": "cyberbullying", "pattern": "agent_action_target", "normalized": "โพสต์รูปล้อเลียน"},
        "ทำร้าย": {"domain": "violence", "pattern": "agent_action_target", "normalized": "ทำร้าย"},
        "ตี": {"domain": "violence", "pattern": "agent_action_target", "normalized": "ตี"},
        "ทอดทิ้ง": {"domain": "neglect", "pattern": "agent_action_target", "normalized": "ทอดทิ้ง"},
        "ไม่ดูแล": {"domain": "neglect", "pattern": "agent_action_target", "normalized": "ไม่ดูแล"},
        "ไม่รู้เรื่อง": {"domain": "family_context", "pattern": "context_only", "normalized": "ไม่รู้เรื่อง"},
        "ช็อก": {"domain": "family_context", "pattern": "context_only", "normalized": "ช็อก"},
    }
    path = Path(__file__).parent / SOCIAL_ACTIONS_PATH
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return {str(key).lower(): value for key, value in data.items()}
    except Exception as exc:
        logger.warning("Could not load social action ontology from %s: %s", path, exc)
        return fallback


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_case_id() -> str:
    return f"CASE_{uuid4().hex}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime_manager.start()
    yield


app = FastAPI(title="H2L Clinical API", lifespan=lifespan)

cors_origins_env = os.getenv("CORS_ORIGINS")
if cors_origins_env:
    allowed_origins = [orig.strip() for orig in cors_origins_env.split(",") if orig.strip()]
else:
    allowed_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


class CaseRequest(BaseModel):
    case_description: str = Field(..., min_length=1)
    strategy: str = DEFAULT_STRATEGY
    enable_l2: bool = True
    llm_model: Optional[str] = None
    top_k: int = Field(DEFAULT_DOC_TOP_K, ge=1, le=50)
    user_adjusted_spans: List[Dict[str, Any]] = Field(default_factory=list)


class AuditRequest(BaseModel):
    case_id: Optional[str] = None
    analysis: Optional[Dict[str, Any]] = None


def _sanitize_pii(text: str) -> tuple[str, int]:
    # Mask explicit personal names without destroying event clauses such as
    # "เด็กหญิงถูกแม่ดุด่า". Social-role words and action phrases are evidence,
    # not PII names, so the redactor checks local context before replacing.
    title_terms = ["นางสาว", "เด็กชาย", "เด็กหญิง", "ด.ช.", "ด.ญ.", "นาย", "นาง"]
    title_pattern = "|".join(re.escape(term) for term in sorted(title_terms, key=len, reverse=True))
    name_pattern = re.compile(rf"(?<![ก-๙a-zA-Z])({title_pattern})\s+([ก-๙a-zA-Z]+)")
    actor_terms = set(_social_actor_config().keys())
    action_terms = set(_social_action_config().keys())
    redaction_blockers = actor_terms | action_terms | {"ถูก", "โดน"}

    pieces: List[str] = []
    last = 0
    n1 = 0
    for match in name_pattern.finditer(text):
        first_name_token = match.group(2).lower()
        if any(term and term in first_name_token for term in redaction_blockers):
            continue
        redact_end = match.end()
        following = re.match(r"\s+([ก-๙a-zA-Z]+)", text[redact_end:])
        if following:
            second_name_token = following.group(1).lower()
            if not any(term and term in second_name_token for term in redaction_blockers):
                redact_end += following.end()
        pieces.append(text[last:match.start()])
        pieces.append("[PERSON]")
        last = redact_end
        n1 += 1
    pieces.append(text[last:])
    text = "".join(pieces)
    # Mask Dates
    text, n2 = re.subn(r'([0-9]{1,2}\s*(มกราคม|กุมภาพันธ์|มีนาคม|เมษายน|พฤษภาคม|มิถุนายน|กรกฎาคม|สิงหาคม|กันยายน|ตุลาคม|พฤศจิกายน|ธันวาคม|ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\.)\s*[0-9]{2,4})', '[DATE]', text)
    # Mask Locations/Institutions
    text, n3 = re.subn(r'(รพ\.|โรงพยาบาล|รร\.|โรงเรียน|คลินิก)\s*[ก-๙a-zA-Z0-9]+', '[LOCATION]', text)
    return text, n1 + n2 + n3


def _remap_boundary_from_diff(
    opcodes: List[Tuple[str, int, int, int, int]],
    index: int,
    original_length: int,
    sanitized_length: int,
    *,
    prefer_end: bool,
) -> int:
    bounded = max(0, min(int(index), original_length))
    if bounded == original_length:
        return sanitized_length
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "insert":
            if bounded == i1:
                return j2 if prefer_end else j1
            continue
        if i1 <= bounded < i2:
            if tag == "equal":
                return j1 + (bounded - i1)
            return j2 if prefer_end else j1
    return sanitized_length


def _best_text_span_near_hint(text: str, needle: str, hint_start: int) -> Tuple[int, int]:
    text_lower = text.lower()
    needle_lower = needle.lower().strip()
    if not needle_lower:
        return (-1, -1)
    spans = _find_term_spans(text_lower, needle_lower)
    if not spans:
        return (-1, -1)
    return min(spans, key=lambda span: (abs(span[0] - hint_start), span[0]))


def _normalize_user_adjusted_spans(
    raw_spans: Any,
    original_text: str,
    sanitized_text: str,
) -> List[Dict[str, Any]]:
    if not raw_spans:
        return []

    matcher = difflib.SequenceMatcher(a=original_text, b=sanitized_text, autojunk=False)
    opcodes = matcher.get_opcodes()
    normalized: List[Dict[str, Any]] = []

    for raw in raw_spans:
        if isinstance(raw, BaseModel):
            raw = raw.model_dump()
        if not isinstance(raw, dict):
            continue

        start = int(raw.get("start", -1) or -1)
        end = int(raw.get("end", -1) or -1)
        if start < 0 or end <= start or end > len(original_text):
            continue

        original_span_text = str(raw.get("text", "") or original_text[start:end])
        keyword = str(raw.get("keyword", "") or original_span_text).lower().strip()
        remapped_start = _remap_boundary_from_diff(
            opcodes,
            start,
            len(original_text),
            len(sanitized_text),
            prefer_end=False,
        )
        remapped_end = _remap_boundary_from_diff(
            opcodes,
            end,
            len(original_text),
            len(sanitized_text),
            prefer_end=True,
        )

        if remapped_end <= remapped_start and original_span_text.strip():
            fallback_start, fallback_end = _best_text_span_near_hint(
                sanitized_text,
                original_span_text,
                remapped_start,
            )
            if fallback_end > fallback_start:
                remapped_start, remapped_end = fallback_start, fallback_end

        if remapped_start < 0 or remapped_end <= remapped_start or remapped_end > len(sanitized_text):
            continue

        normalized.append({
            "keyword": keyword or sanitized_text[remapped_start:remapped_end].lower().strip(),
            "start": remapped_start,
            "end": remapped_end,
            "scope": str(raw.get("scope", "") or "match"),
            "text": sanitized_text[remapped_start:remapped_end],
            "position_source": "user_adjusted",
            "user_adjusted": True,
            "original_start": start,
            "original_end": end,
            "original_text": original_span_text,
        })

    normalized.sort(key=lambda item: (int(item["start"]), int(item["end"])))
    deduped: List[Dict[str, Any]] = []
    seen: Set[Tuple[int, int, str]] = set()
    for span in normalized:
        key = (int(span["start"]), int(span["end"]), str(span.get("keyword", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(span)
    return deduped

class FinalizeRequest(BaseModel):
    case_id: str
    reviewer_note: str = ""
    selected_findings: Optional[List[str]] = None
    finding_review_states: Dict[str, Literal["accepted", "review", "excluded"]] = Field(default_factory=dict)
    expert_override_added: List[str] = Field(default_factory=list)
    expert_override_rejected: List[str] = Field(default_factory=list)
    zero_finding_acknowledged: bool = False
    final_status: str = "Ready for Human Review"


@lru_cache(maxsize=2)
def get_detector(enable_l2: bool = True) -> H2LDetectorV3:
    """Cache the lightweight detector so requests do not reload taxonomy files."""
    return H2LDetectorV3(
        taxonomy_path=TAXONOMY_PATH,
        enable_l2=enable_l2,
    )


def _taxonomy_loaded(enable_l2: bool = True) -> bool:
    try:
        return bool(get_detector(enable_l2).get_taxonomy())
    except Exception as exc:
        logger.warning("Detector health check failed: %s", exc)
        return False


CASE_CACHE: Dict[str, Dict[str, Any]] = {}
FINALIZED_CASES: Dict[str, Dict[str, Any]] = {}


def _strategy_available(strategy: str, components: Optional[Dict[str, bool]] = None) -> bool:
    if components is None:
        return True
    return all(components.get(name) for name in STRATEGY_REQUIRED_COMPONENTS.get(strategy, []))


def _strategy_options(components: Optional[Dict[str, bool]] = None) -> List[Dict[str, Any]]:
    options = []
    for pair in STRATEGY_PAIRS:
        options.append({
            "id": pair["baseline"],
            "family": pair["family"],
            "label": f"{pair['label']} Baseline",
            "group": "Baseline RAG",
            "paired_with": pair["enhanced"],
            "runtime": "live-runtime",
            "description": pair["description"],
            "available": _strategy_available(pair["baseline"], components),
        })
        options.append({
            "id": pair["enhanced"],
            "family": pair["family"],
            "label": f"{pair['label']} + H2L",
            "group": "H2L-Enhanced RAG",
            "paired_with": pair["baseline"],
            "runtime": "live-runtime",
            "description": f"H2L scoring/gating เพิ่มบน {pair['label']}",
            "available": _strategy_available(pair["enhanced"], components),
        })
    return options


def _default_strategy_for_components(components: Optional[Dict[str, bool]] = None) -> str:
    if _strategy_available(DEFAULT_STRATEGY, components):
        return DEFAULT_STRATEGY
    if _strategy_available("h2l-bm25", components):
        return "h2l-bm25"
    if _strategy_available("bm25_only", components):
        return "bm25_only"
    return DEFAULT_STRATEGY


def _normalize_strategy(strategy: str | None) -> str:
    normalized = (strategy or DEFAULT_STRATEGY).strip()
    normalized = STRATEGY_ALIASES.get(normalized, normalized)
    if normalized not in VALID_STRATEGIES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported strategy '{strategy}'. Use one of: {', '.join(sorted(VALID_STRATEGIES))}",
        )
    return normalized


class RuntimeManager:
    """Background loader for shared detector, embeddings, indexes, and retrievers."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self.status = "loading"
        self.stage = "not-started"
        self.started_at: Optional[float] = None
        self.ready_at: Optional[float] = None
        self.errors: List[Dict[str, str]] = []
        self.components: Dict[str, bool] = {
            "config": False,
            "taxonomy": False,
            "detector_l1": False,
            "detector_l2_client": False,
            "llm": False,
            "documents": False,
            "embedding_model": False,
            "vector_index": False,
            "bm25": False,
            "reranker": False,
            "h2l_scoring": False,
        }
        self.models: Dict[str, Any] = {}
        self.config = None
        self.detector: Optional[H2LDetectorV3] = None
        self.shared: Optional[Dict[str, Any]] = None
        self.retrievers: Dict[str, Any] = {}
        self.l2_ready = False
        self.available_l2_models: Set[str] = set()

    def start(self) -> None:
        with self._lock:
            if self.status in {"ready", "degraded", "error"} and self.ready_at:
                return
            if self._thread and self._thread.is_alive():
                return
            self.started_at = time.time()
            self.status = "loading"
            self.stage = "queued"
            self._thread = threading.Thread(target=self._warmup, name="h2l-runtime-warmup", daemon=True)
            self._thread.start()

    def _set_stage(self, stage: str) -> None:
        with self._lock:
            self.stage = stage
        logger.info("[Runtime] %s", stage)

    def _add_error(self, component: str, exc: Exception | str) -> None:
        message = str(exc)
        logger.warning("[Runtime] %s degraded: %s", component, message)
        with self._lock:
            self.errors.append({
                "component": component,
                "message": message,
                "trace": traceback.format_exc() if isinstance(exc, Exception) else "",
            })

    def _warmup(self) -> None:
        try:
            self._set_stage("Loading configuration")
            from h2l.config import get_config

            config = get_config()
            with self._lock:
                self.config = config
                self.components["config"] = True
                self.models.update({
                    "embedding_model": getattr(config, "EMBEDDING_MODEL", None),
                    "rerank_model": getattr(config, "RERANK_MODEL", None),
                    "llm_model": getattr(config, "LOCAL_LLM_MODEL", None),
                    "vector_backend": getattr(config, "DB_TYPE", None),
                    "vector_path": getattr(config, "DB_PATH", None),
                    "metadata_store": getattr(config, "METADATA_STORE", None),
                    "safe_start": getattr(config, "SAFE_START", False),
                    "dense_runtime": getattr(config, "ENABLE_DENSE_RUNTIME", True),
                    "use_rerank": getattr(config, "USE_RERANK", False),
                })

            self._set_stage("Loading H2L detector and taxonomy")
            detector = H2LDetectorV3(
                config=config,
                taxonomy_path=TAXONOMY_PATH,
                enable_l2=True,
            )
            taxonomy_loaded = bool(detector.get_taxonomy())
            with self._lock:
                self.detector = detector
                self.components["taxonomy"] = taxonomy_loaded
                self.components["detector_l1"] = taxonomy_loaded
                self.components["detector_l2_client"] = bool(detector.l2_detector and detector.l2_detector.is_ready)

            self._set_stage("Checking L2/LLM endpoint")
            self.l2_ready = self._check_llm_ready(config)
            with self._lock:
                self.components["llm"] = self.l2_ready
            if not self.l2_ready:
                self._add_error("llm", "Ollama/OpenAI-compatible L2 endpoint is not reachable; L2 validation will run in degraded mode.")

            self._set_stage("Loading retrieval documents, embedding index, BM25, and reranker")
            self._load_shared_components(config)

            with self._lock:
                retrieval_ready = bool(self.shared and self.components["documents"] and (self.components["bm25"] or self.components["vector_index"]))
                self.components["h2l_scoring"] = retrieval_ready
                self.ready_at = time.time()
                self.status = "ready" if retrieval_ready and self.l2_ready and not self.errors else "degraded"
                self.stage = "ready" if self.status == "ready" else "degraded"
        except Exception as exc:
            logger.exception("Runtime warmup failed")
            self._add_error("runtime", exc)
            with self._lock:
                self.ready_at = time.time()
                self.status = "error"
                self.stage = "error"

    def _check_llm_ready(self, config) -> bool:
        if not getattr(config, "USE_LOCAL_LLM", True):
            self.available_l2_models = {str(getattr(config, "OPENROUTER_MODEL", ""))}
            return bool(getattr(config, "OPENROUTER_API_KEY", ""))

        base_url = getattr(config, "LOCAL_LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/")
        models_url = f"{base_url}/models"
        try:
            with urllib.request.urlopen(models_url, timeout=1.5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.available_l2_models = {
                    str(item.get("id") or "")
                    for item in payload.get("data", [])
                    if item.get("id")
                }
                default_model = str(getattr(config, "LOCAL_LLM_MODEL", ""))
                return 200 <= response.status < 500 and default_model in self.available_l2_models
        except Exception:
            self.available_l2_models = set()
            return False

    def _load_shared_components(self, config) -> None:
        from h2l.retriever import DenseIndex, HybridRetriever, Reranker, ThaiBM25

        all_docs = HybridRetriever._load_all_docs(config)
        doc_map = {doc.id: doc for doc in all_docs}
        with self._lock:
            self.components["documents"] = bool(all_docs)

        lexical_retriever = None
        dense_retriever = None
        reranker = None

        try:
            lexical_retriever = ThaiBM25(all_docs)
            with self._lock:
                self.components["bm25"] = True
        except Exception as exc:
            self._add_error("bm25", exc)

        if getattr(config, "ENABLE_DENSE_RUNTIME", True):
            try:
                dense_retriever = DenseIndex(config.DB_TYPE, str(config.DB_PATH), config.EMBEDDING_MODEL, config.DEVICE)
                with self._lock:
                    self.components["embedding_model"] = bool(getattr(dense_retriever, "embedder", None))
                    self.components["vector_index"] = bool(getattr(dense_retriever, "index", None))
            except Exception as exc:
                self._add_error("embedding/vector_index", exc)
        else:
            self._add_error(
                "embedding/vector_index",
                "Dense runtime disabled by H2L_SAFE_START/ENABLE_DENSE_RUNTIME; BM25 runtime remains available.",
            )

        if getattr(config, "USE_RERANK", False):
            try:
                reranker = Reranker(config.RERANK_MODEL, config.DEVICE)
                with self._lock:
                    self.components["reranker"] = True
            except Exception as exc:
                self._add_error("reranker", exc)

        if not lexical_retriever and not dense_retriever:
            raise RuntimeError("No retrieval backend loaded. BM25 and dense retrieval are both unavailable.")

        with self._lock:
            self.shared = {
                "all_docs": all_docs,
                "doc_map": doc_map,
                "dense_retriever": dense_retriever,
                "lexical_retriever": lexical_retriever,
                "reranker": reranker,
            }

    def _strategy_dependencies_ready(self, strategy: str) -> tuple[bool, List[str]]:
        required = STRATEGY_REQUIRED_COMPONENTS.get(strategy, [])
        missing = [name for name in required if not self.components.get(name)]
        return not missing, missing

    def get_retriever(self, strategy: str):
        strategy = _normalize_strategy(strategy)
        with self._lock:
            if self.status == "loading":
                raise RuntimeError("Runtime is still loading retrieval components.")
            if self.status == "error":
                raise RuntimeError("Runtime failed to load retrieval components.")
            ready, missing = self._strategy_dependencies_ready(strategy)
            if not ready:
                raise RuntimeError(f"Selected strategy '{strategy}' is unavailable because components are missing: {', '.join(missing)}")
            if strategy in self.retrievers:
                return self.retrievers[strategy]
            config = self.config
            shared = self.shared

        if strategy == "bm25_only":
            try:
                from eval.baselines import BM25OnlyBaseline
            except ImportError:
                from unified_baselines import BM25OnlyBaseline
            retriever = BM25OnlyBaseline(config, shared)
        elif strategy == "naive_rag":
            try:
                from eval.baselines import NaiveRAGBaseline
            except ImportError:
                from unified_baselines import NaiveRAGBaseline
            retriever = NaiveRAGBaseline(config, shared)
        elif strategy == "hyde":
            try:
                from eval.baselines import HyDEBaseline
            except ImportError:
                from unified_baselines import HyDEBaseline
            retriever = HyDEBaseline(config, shared)
        elif strategy.startswith("h2l-"):
            from h2l.core import H2LUnifiedRetriever
            retriever = H2LUnifiedRetriever(config=config, shared_components=shared, strategy_mode=strategy)
        else:
            from h2l.retriever import HybridRetriever
            retriever = HybridRetriever(config, shared_components=shared)

        with self._lock:
            self.retrievers[strategy] = retriever
        return retriever

    def embedder(self):
        with self._lock:
            dense = (self.shared or {}).get("dense_retriever") if self.shared else None
            return getattr(dense, "embedder", None)

    def payload(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            components = dict(self.components)
            return {
                "status": self.status,
                "stage": self.stage,
                "components": components,
                "models": dict(self.models),
                "strategy_pairs": STRATEGY_PAIRS,
                "strategy_options": _strategy_options(components),
                "default_strategy": _default_strategy_for_components(components),
                "l2_model_options": self.l2_model_options(),
                "l2_ready": self.l2_ready,
                "errors": list(self.errors),
                "started_at": self.started_at,
                "ready_at": self.ready_at,
                "uptime_seconds": (now - self.started_at) if self.started_at else 0,
                "load_seconds": (self.ready_at - self.started_at) if self.ready_at and self.started_at else None,
            }

    def l2_model_options(self) -> List[Dict[str, Any]]:
        config = self.config
        if config is None:
            return []
        default_model = str(
            getattr(config, "LOCAL_LLM_MODEL", "")
            if getattr(config, "USE_LOCAL_LLM", True)
            else getattr(config, "OPENROUTER_MODEL", "")
        )
        configured = list(getattr(config, "L2_MODEL_OPTIONS", ()) or [default_model])
        catalog = {
            "qwen2.5:7b": {
                "label": "Qwen 2.5 7B",
                "detail": "Current local baseline",
                "parameters": "7.6B",
                "size_gb": 4.36,
            },
            "scb10x/llama3.1-typhoon2-8b-instruct:latest": {
                "label": "Typhoon 2 8B Instruct",
                "detail": "Thai-focused local comparator",
                "parameters": "8.0B",
                "size_gb": 4.58,
            },
            "scb10x/typhoon2.1-gemma3-4b:latest": {
                "label": "Typhoon 2.1 Gemma 3 4B",
                "detail": "Smaller Thai-focused efficiency comparator",
                "parameters": "3.9B",
                "size_gb": 2.44,
            },
        }
        return [
            {
                "id": model,
                **catalog.get(model, {"label": model, "detail": "Configured L2 model"}),
                "available": (model in self.available_l2_models) if getattr(config, "USE_LOCAL_LLM", True) else model == default_model,
                "default": model == default_model,
            }
            for model in configured
        ]

    def resolve_l2_model(self, requested_model: Optional[str]) -> str:
        config = self.config
        if config is None:
            raise HTTPException(status_code=503, detail="Runtime configuration is not ready.")
        default_model = str(
            getattr(config, "LOCAL_LLM_MODEL", "")
            if getattr(config, "USE_LOCAL_LLM", True)
            else getattr(config, "OPENROUTER_MODEL", "")
        )
        selected = str(requested_model or default_model).strip()
        allowed = {str(model) for model in getattr(config, "L2_MODEL_OPTIONS", ()) or [default_model]}
        if selected not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported L2 model '{selected}'. Allowed models: {', '.join(sorted(allowed))}",
            )
        if getattr(config, "USE_LOCAL_LLM", True) and selected not in self.available_l2_models:
            raise HTTPException(
                status_code=503,
                detail=f"L2 model '{selected}' is allowed but is not installed in the local Ollama runtime.",
            )
        return selected


runtime_manager = RuntimeManager()


def _determine_severity(problems: List[Dict]) -> str:
    if not problems:
        return "NOT_ASSESSED"
    if any(p.get("code") == "X60-X84" for p in problems):
        return "CRITICAL"
    max_severity = max((p.get("severity", 1) for p in problems), default=1)
    return {
        1: "MILD",
        2: "MILD",
        3: "MODERATE",
        4: "SEVERE",
        5: "CRITICAL",
    }.get(max_severity, "MILD")


def _recommend_tools(problems: List[Dict]) -> List[Dict]:
    tools = []
    problem_codes = [p.get("code", "") for p in problems]

    if "X60-X84" in problem_codes:
        tools.append({
            "name": "การส่งต่อจิตแพทย์ฉุกเฉิน (8Q)",
            "priority": "วิกฤต",
            "priority_score": 5,
            "reason": "ประเมินความเสี่ยงฆ่าตัวตาย (X60-X84)",
        })

    if "F32-F33" in problem_codes or any(code.startswith("F") for code in problem_codes):
        tools.append({
            "name": "การให้คำปรึกษาเชิงจิตวิทยา (PHQ-9)",
            "priority": "สูง",
            "priority_score": 4,
            "reason": "ช่วยเหลือด้านสุขภาพจิต",
        })

    if any(code in problem_codes for code in ["0206", "Z63", "0102", "T74"]):
        tools.append({
            "name": "การประเมินความพร้อมครอบครัว (F.R.A.)",
            "priority": "สูง",
            "priority_score": 4,
            "reason": "ประเมินความปลอดภัยครอบครัว",
        })

    if any(code.startswith("11") for code in problem_codes):
        tools.append({
            "name": "การประสานโรงเรียน/กศน.",
            "priority": "กลาง",
            "priority_score": 3,
            "reason": "ช่วยเหลือด้านการศึกษา",
        })

    tools.extend([
        {
            "name": "S.D.M.A. (ประเมินวินิจฉัยทางสังคม)",
            "priority": "กลาง",
            "priority_score": 3,
            "reason": "เครื่องมือประเมินเบื้องต้น",
        },
        {
            "name": "การติดตามเยี่ยมบ้าน",
            "priority": "ต่ำ",
            "priority_score": 1,
            "reason": "ติดตามความก้าวหน้า",
        },
    ])

    seen = set()
    unique_tools = []
    for tool in tools:
        if tool["name"] not in seen:
            seen.add(tool["name"])
            unique_tools.append(tool)

    return sorted(unique_tools, key=lambda item: item["priority_score"], reverse=True)


def _calculate_metrics(problems: List[Dict], filtered_out: List[Dict], retrieved_docs: Optional[List[Dict]] = None) -> Dict:
    """Per-case operational metrics.

    Research IR metrics such as MAP/MRR/nDCG need ground truth and live in
    evaluation artifacts. A single submitted case should only expose observed
    runtime quantities, so the UI never implies per-case benchmark scores.
    """
    retrieved_docs = retrieved_docs or []
    if problems:
        avg_confidence = sum(p.get("confidence", 0.0) for p in problems) / len(problems)
    else:
        avg_confidence = 0.0

    candidate_total = len(problems) + len(filtered_out)
    accepted_ratio = len(problems) / candidate_total if candidate_total else None
    filtered_ratio = len(filtered_out) / candidate_total if candidate_total else 0.0
    severities = [int(p.get("severity", 1) or 1) for p in problems]
    retrieval_scores = [
        doc.get("h2l_final_score") if doc.get("h2l_final_score") is not None else doc.get("score")
        for doc in retrieved_docs
        if isinstance(doc, dict)
    ]
    retrieval_scores = [
        float(score)
        for score in retrieval_scores
        if isinstance(score, (int, float)) and math.isfinite(float(score))
    ]

    return {
        "type": "case_operational_metrics",
        "source": "runtime analysis response",
        "note": "ค่านี้เป็นตัวชี้วัดการทำงานของเคสปัจจุบัน ไม่ใช่ MAP/MRR/nDCG ของงานวิจัย ซึ่งต้องอ่านจาก evaluation artifacts",
        "avg_confidence": avg_confidence,
        "avg_detection_confidence": avg_confidence,
        "problems_found": len(problems),
        "candidate_count": candidate_total,
        "accepted_count": len(problems),
        "filtered_count": len(filtered_out),
        "accepted_ratio": accepted_ratio,
        "filtered_ratio": filtered_ratio,
        "max_severity": max(severities) if severities else 0,
        "high_severity_count": sum(1 for severity in severities if severity >= 4),
        "moderate_severity_count": sum(1 for severity in severities if severity == 3),
        "retrieved_docs_count": len(retrieved_docs),
        "avg_retrieval_score": sum(retrieval_scores) / len(retrieval_scores) if retrieval_scores else None,
        "max_retrieval_score": max(retrieval_scores) if retrieval_scores else None,
        "ground_truth_metrics_available": False,
        "ground_truth_metrics_note": "ไม่มี ground truth ต่อเคสที่ผู้ใช้กรอก จึงไม่คำนวณ precision/recall/MAP/MRR/nDCG แบบต่อเคส",
    }


def _score_components(problems: List[Dict], filtered_out: List[Dict], retrieved_docs: List[Dict] | None = None) -> List[Dict]:
    retrieved_docs = retrieved_docs or []
    avg_confidence = sum(p.get("confidence", 0.0) for p in problems) / len(problems) if problems else 0.0
    total_keywords = sum(len(p.get("matched_keywords", [])) for p in problems)
    keyword_coverage = min(1.0, total_keywords / max(len(problems) * 2, 1)) if problems else 0.0
    specificity = min(1.0, sum(p.get("severity", 1) for p in problems) / max(len(problems) * 5, 1)) if problems else 0.0
    polarity_gate = 1.0 - (len(filtered_out) / max(len(problems) + len(filtered_out), 1))

    retrieval_score = None
    if retrieved_docs:
        scores = []
        for doc in retrieved_docs:
            if not isinstance(doc, dict):
                continue
            value = doc.get("h2l_final_score") if doc.get("h2l_final_score") is not None else doc.get("score")
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                scores.append(float(value))
        if scores:
            retrieval_score = max(0.0, min(1.0, sum(scores) / len(scores)))

    return [
        {
            "id": "detection_confidence",
            "label": "Detection Confidence",
            "value": avg_confidence,
            "delta": avg_confidence,
            "direction": "positive",
            "available": bool(problems),
            "source": "H2LDetectorV3 confidence values",
        },
        {
            "id": "keyword_coverage",
            "label": "Keyword Coverage",
            "value": keyword_coverage,
            "delta": keyword_coverage,
            "direction": "positive",
            "available": bool(problems),
            "source": "Matched keyword count normalized by detected problems",
        },
        {
            "id": "specificity",
            "label": "Specificity",
            "value": specificity,
            "delta": specificity,
            "direction": "positive",
            "available": bool(problems),
            "source": "Detected severity distribution",
        },
        {
            "id": "polarity_gate",
            "label": "Polarity Gate",
            "value": polarity_gate if problems or filtered_out else None,
            "delta": -len(filtered_out),
            "direction": "negative" if filtered_out else "positive",
            "available": bool(problems or filtered_out),
            "source": "Filtered context and negation-sensitive candidates",
        },
        {
            "id": "retrieval_evidence",
            "label": "Retrieval Evidence",
            "value": retrieval_score,
            "delta": len(retrieved_docs),
            "direction": "positive",
            "available": retrieval_score is not None,
            "source": "Runtime retrieved document scores, bounded to 0-1 for display only",
        },
    ]


def _keyword_analysis(problems: List[Dict], filtered_out: List[Dict]) -> Dict:
    rows = []
    for problem in problems:
        keywords = problem.get("matched_keywords", [])
        rows.append({
            "code": problem.get("code"),
            "name": problem.get("name"),
            "keywords": keywords,
            "keyword_count": len(keywords),
            "context_valid": problem.get("context_valid", True),
            "detection_level": problem.get("detection_level", "L1"),
            "reasoning": problem.get("reasoning", ""),
            "confidence": problem.get("confidence", 0.0),
        })

    total_keywords = sum(row["keyword_count"] for row in rows)
    return {
        "total_keywords": total_keywords,
        "unique_keywords": sorted({kw for row in rows for kw in row["keywords"]}),
        "rows": rows,
        "filtered_out": filtered_out,
    }


def _sentence_profile(text: str) -> Dict:
    text_lower = text.lower()
    markers = [marker for marker in NEGATION_MARKERS if marker in text_lower]
    actor_config = _social_actor_config()
    action_config = _social_action_config()
    actor_terms = sorted(actor_config.keys(), key=len, reverse=True)
    action_terms = sorted(action_config.keys(), key=len, reverse=True)
    reference_terms = {
        "เขา": {"roles": [], "group": "reference", "normalized": "เขา", "is_reference": True},
        "เธอ": {"roles": [], "group": "reference", "normalized": "เธอ", "is_reference": True},
        "รายนี้": {"roles": [], "group": "reference", "normalized": "รายนี้", "is_reference": True},
        "รายดังกล่าว": {"roles": [], "group": "reference", "normalized": "รายดังกล่าว", "is_reference": True},
        "รายเดิม": {"roles": [], "group": "reference", "normalized": "รายเดิม", "is_reference": True},
        "คนนี้": {"roles": [], "group": "reference", "normalized": "คนนี้", "is_reference": True},
        "คนดังกล่าว": {"roles": [], "group": "reference", "normalized": "คนดังกล่าว", "is_reference": True},
        "คนเดิม": {"roles": [], "group": "reference", "normalized": "คนเดิม", "is_reference": True},
    }
    guarded_boundary_markers = {"และ", "โดย", "ว่า", "ส่วน"}
    boundary_follow_cues = tuple(sorted({
        *actor_terms,
        *action_terms,
        *reference_terms.keys(),
        "ไม่", "ไม่ได้", "ไม่เคย", "เคย", "ผู้ป่วย", "ผู้รับบริการ", "เด็ก", "[person]",
    }, key=len, reverse=True))

    def find_mentions(terms: List[str]) -> List[Dict]:
        mentions = []
        for term in terms:
            start = text_lower.find(term)
            while start >= 0:
                mentions.append({"text": term, "start": start, "end": start + len(term)})
                start = text_lower.find(term, start + len(term))
        mentions = sorted(mentions, key=lambda item: (item["start"], -(item["end"] - item["start"])))
        non_overlapping = []
        for mention in mentions:
            overlaps = any(mention["start"] < existing["end"] and existing["start"] < mention["end"] for existing in non_overlapping)
            if not overlaps:
                non_overlapping.append(mention)
        return non_overlapping

    def enrich_actor_mentions(mentions: List[Dict]) -> List[Dict]:
        enriched = []
        for mention in mentions:
            meta = actor_config.get(mention["text"], {}) or reference_terms.get(mention["text"], {})
            enriched.append({
                **mention,
                "normalized": meta.get("normalized", mention["text"]),
                "roles": meta.get("roles", []),
                "group": meta.get("group", "unknown"),
                "is_reference": bool(meta.get("is_reference", False)),
            })
        return enriched

    def enrich_action_mentions(mentions: List[Dict]) -> List[Dict]:
        enriched = []
        for mention in mentions:
            meta = action_config.get(mention["text"], {})
            enriched.append({
                **mention,
                "normalized": meta.get("normalized", mention["text"]),
                "domain": meta.get("domain", "general"),
                "pattern": meta.get("pattern", "agent_action_target"),
            })
        return enriched

    def has_role(mention: Dict[str, Any], role: str) -> bool:
        return role in mention.get("roles", [])

    def normalize_actor(mention: Dict[str, Any]) -> str:
        return mention.get("normalized") or mention.get("text", "")

    def unique(values: List[str]) -> List[str]:
        return [value for value in dict.fromkeys(values) if value]

    def scan_boundaries(
        position: int,
        markers: List[str],
        *,
        marker_end_left: bool = True,
    ) -> Tuple[int, int]:
        left_boundaries = [0]
        right_boundaries = [len(text_lower)]

        def marker_is_boundary(found: int, marker: str) -> bool:
            if marker not in guarded_boundary_markers:
                return True
            marker_end = found + len(marker)
            prev_window = text_lower[max(0, found - 18):found]
            next_window = text_lower[marker_end:min(len(text_lower), marker_end + 18)]
            if marker == "ว่า":
                return any(cue in prev_window for cue in ("บอก", "ระบุ", "แจ้ง", "เล่า", "ยืนยัน"))
            return any(cue in next_window for cue in boundary_follow_cues)

        for marker in markers:
            search_at = 0
            while True:
                found = text_lower.find(marker, search_at)
                if found < 0:
                    break
                marker_end = found + len(marker)
                if not marker_is_boundary(found, marker):
                    search_at = marker_end
                    continue
                left_value = marker_end if marker_end_left else found
                if marker_end <= position:
                    left_boundaries.append(left_value)
                elif found >= position:
                    right_boundaries.append(found)
                search_at = marker_end
        return max(left_boundaries), min(right_boundaries)

    def sentence_bounds(position: int) -> Tuple[int, int]:
        left = 0
        right = len(text_lower)
        sentence_markers = [".", "。", "!", "?", "\n", ";", "；"]
        for marker in sentence_markers:
            search_at = 0
            while True:
                found = text_lower.find(marker, search_at)
                if found < 0:
                    break
                marker_end = found + len(marker)
                if marker_end <= position:
                    left = max(left, marker_end)
                elif found >= position:
                    right = min(right, found)
                    break
                search_at = marker_end
        return left, right

    def reference_clause_bounds(position: int) -> Tuple[int, int]:
        boundary_markers = [
            ",", "，", ".", "。", ";", "；", "\n", "(", ")",
            " แต่", " แล้ว", " จึง", " จน", " เพราะ", " เนื่องจาก",
            " อย่างไรก็ตาม", " ขณะเดียวกัน", " ส่วน", " อีกทั้ง", " โดย", " และ", " ว่า", "ว่า",
            "แต่", "แล้ว", "จึง", "จน", "เพราะ", "เนื่องจาก",
            "อย่างไรก็ตาม", "ขณะเดียวกัน", "ส่วน", "อีกทั้ง", "โดย", "และ",
        ]
        return scan_boundaries(position, boundary_markers)

    def resolve_actor_references(mentions: List[Dict]) -> List[Dict]:
        pronoun_refs = {"เขา", "เธอ"}
        deferred_refs = {"รายนี้", "รายดังกล่าว", "รายเดิม", "คนนี้", "คนดังกล่าว", "คนเดิม"}
        reporting_cues = ("บอก", "ระบุ", "แจ้ง", "เล่า", "ยืนยัน", "ว่า")

        def choose_antecedent(reference: Dict, explicit_mentions: List[Dict]) -> Optional[Dict]:
            candidates = [item for item in explicit_mentions if item["end"] <= reference["start"]]
            if not candidates:
                return None

            sentence_start, _sentence_end = sentence_bounds(reference["start"])
            clause_start, _clause_end = reference_clause_bounds(reference["start"])
            same_sentence = [item for item in candidates if sentence_start <= item["start"] < reference["start"]]
            same_clause = [item for item in candidates if clause_start <= item["start"] < reference["start"]]
            prev_sentence = [
                item for item in candidates
                if item["end"] <= sentence_start and sentence_start - item["end"] <= 180
            ]
            reporting_context = any(cue in text_lower[sentence_start:reference["start"]] for cue in reporting_cues)
            sentence_subject = same_sentence[0] if same_sentence else None

            best = None
            best_score = None
            for candidate in candidates:
                distance = max(0, reference["start"] - candidate["end"])
                score = max(0, 220 - distance)
                if candidate in same_clause:
                    score += 160
                elif candidate in same_sentence:
                    score += 95
                elif candidate in prev_sentence:
                    score += 70

                if "agent" in candidate.get("roles", []) or "context" in candidate.get("roles", []):
                    score += 20

                if reference["text"] in deferred_refs and candidate in prev_sentence:
                    score += 35

                if reporting_context and sentence_subject is not None:
                    if candidate is sentence_subject:
                        score += 55
                    elif len(same_sentence) > 1 and candidate is same_sentence[-1]:
                        score -= 35

                if reference["text"] in pronoun_refs and candidate in same_sentence and candidate is same_sentence[-1]:
                    score += 10

                if best_score is None or score > best_score:
                    best = candidate
                    best_score = score
            return best

        resolved: List[Dict] = []
        explicit_mentions: List[Dict] = []
        for mention in sorted(mentions, key=lambda item: (item["start"], -(item["end"] - item["start"]))):
            if not mention.get("is_reference"):
                resolved.append(mention)
                explicit_mentions.append(mention)
                continue

            antecedent = choose_antecedent(mention, explicit_mentions)

            if antecedent:
                resolved_mention = {
                    **mention,
                    "normalized": antecedent.get("normalized", antecedent.get("text", mention["text"])),
                    "roles": antecedent.get("roles", []),
                    "group": antecedent.get("group", "unknown"),
                    "is_reference": True,
                    "resolved_from": mention["text"],
                    "antecedent": antecedent.get("normalized", antecedent.get("text", "")),
                    "antecedent_start": antecedent.get("start"),
                    "antecedent_end": antecedent.get("end"),
                }
                resolved.append(resolved_mention)
                continue

            resolved.append(mention)
        return resolved

    def assign_actor_instance_ids(mentions: List[Dict]) -> List[Dict]:
        counters: Dict[str, int] = {}
        entity_by_span: Dict[Tuple[int, int], str] = {}
        enriched: List[Dict] = []
        for index, mention in enumerate(sorted(mentions, key=lambda item: (item["start"], -(item["end"] - item["start"]))), start=1):
            antecedent_start = mention.get("antecedent_start", -1)
            antecedent_end = mention.get("antecedent_end", -1)
            antecedent_span = (
                int(-1 if antecedent_start is None else antecedent_start),
                int(-1 if antecedent_end is None else antecedent_end),
            )
            entity_instance_id = ""
            if mention.get("is_reference") and antecedent_span in entity_by_span:
                entity_instance_id = entity_by_span[antecedent_span]
            else:
                base = str(mention.get("normalized") or mention.get("text") or "entity")
                counters[base] = counters.get(base, 0) + 1
                entity_instance_id = f"{base}#{counters[base]}"
            entity_by_span[(int(mention["start"]), int(mention["end"]))] = entity_instance_id
            enriched.append({
                **mention,
                "mention_id": f"m{index}",
                "entity_instance_id": entity_instance_id,
                "mention_text": text[max(0, int(mention["start"])):min(len(text), int(mention["end"]))],
            })
        return enriched

    def assign_action_ids(mentions: List[Dict]) -> List[Dict]:
        enriched: List[Dict] = []
        for index, mention in enumerate(sorted(mentions, key=lambda item: (item["start"], -(item["end"] - item["start"]))), start=1):
            enriched.append({
                **mention,
                "action_id": f"a{index}",
                "mention_text": text[max(0, int(mention["start"])):min(len(text), int(mention["end"]))],
            })
        return enriched

    def mention_gap_text(left: Dict[str, Any], right: Dict[str, Any]) -> str:
        start = int(left.get("end", 0) or 0)
        end = int(right.get("start", start) or start)
        return text_lower[start:end]

    def contiguous_actor_cluster(mentions: List[Dict[str, Any]], *, reverse: bool) -> List[Dict[str, Any]]:
        if not mentions:
            return []
        ordered = sorted(mentions, key=lambda item: int(item["start"]), reverse=reverse)
        cluster = [ordered[0]]
        allowed_connectors = ("และ", "กับ", "และก็", "รวมทั้ง")
        for mention in ordered[1:]:
            gap = mention_gap_text(mention, cluster[-1]) if reverse else mention_gap_text(cluster[-1], mention)
            if len(gap) > 10:
                break
            if gap.strip() and not any(connector in gap for connector in allowed_connectors):
                break
            cluster.append(mention)
        return sorted(cluster, key=lambda item: int(item["start"]))

    def passive_clause_end(start: int) -> int:
        boundary_candidates = [len(text_lower)]
        punctuation = [",", "，", ".", "。", ";", "；", "\n", "(", ")"]
        boundary_phrases = [
            " ไม่อยาก",
            " ไม่รู้",
            " แต่",
            " แล้ว",
            " จึง",
            " จน",
            " บิดา",
            " มารดา",
            " พ่อ",
            " แม่",
            " เพิ่ง",
            " ช็อก",
            " เข้ารักษา",
            "ไม่อยาก",
            "ไม่รู้",
            "แต่",
            "แล้ว",
            "จึง",
            "จน",
            "เพิ่ง",
            "ช็อก",
            "เข้ารักษา",
        ]
        for marker in punctuation + boundary_phrases:
            found = text_lower.find(marker, start)
            if found >= 0:
                boundary_candidates.append(found)
        return min(boundary_candidates)

    def clause_bounds(position: int) -> Tuple[int, int]:
        boundary_markers = [
            ",", "，", ".", "。", ";", "；", "\n", "(", ")",
            " แต่", " แล้ว", " จึง", " จน", " เพราะ", " เนื่องจาก", " ว่า", "ว่า",
            " ถูก", " โดน", " ไม่อยาก", " ไม่รู้", " เพิ่ง", " ช็อก",
            "แต่", "แล้ว", "จึง", "จน", "เพราะ", "เนื่องจาก", "ว่า",
            "ถูก", "โดน", "ไม่อยาก", "ไม่รู้", "เพิ่ง", "ช็อก",
            "อย่างไรก็ตาม", "ขณะเดียวกัน", "ส่วน", "อีกทั้ง", "โดย", "และ",
        ]
        return scan_boundaries(position, boundary_markers)

    def inferred_case_subject() -> str:
        subject_signals = ["[person]", "เด็ก", "เด็กหญิง", "เด็กชาย", "14 ปี", "ม.2", "ตัดเอง", "รอยกรีด"]
        if any(signal in text_lower for signal in subject_signals):
            return "ผู้รับบริการ/เด็ก"
        return ""

    def evidence_span(start: int, end: int) -> str:
        return text[max(0, start):min(len(text), end)].strip()

    actor_mentions = enrich_actor_mentions(find_mentions(actor_terms + sorted(reference_terms.keys(), key=len, reverse=True)))
    actor_mentions = resolve_actor_references(actor_mentions)
    actor_mentions = assign_actor_instance_ids(actor_mentions)
    action_mentions = assign_action_ids(enrich_action_mentions(find_mentions(action_terms)))
    passive_markers = find_mentions(["ถูก", "โดน"])
    actors = unique(mention["text"] for mention in actor_mentions)
    events: List[Dict[str, Any]] = []
    passive_spans: List[Tuple[int, int]] = []
    voice = "active"

    def append_event(
        event_type: str,
        agents: List[str],
        targets: List[str],
        actions: List[str],
        span_start: int,
        span_end: int,
        confidence: float,
        pattern: str,
        note: str = "",
        context_actors: Optional[List[str]] = None,
        agent_mentions: Optional[List[Dict[str, Any]]] = None,
        target_mentions: Optional[List[Dict[str, Any]]] = None,
        action_mentions_meta: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        clean_agents = unique(agents)
        clean_targets = unique(targets)
        clean_actions = unique(actions)
        if not (clean_agents or clean_targets or clean_actions or context_actors):
            return
        support_spans: List[Dict[str, Any]] = []

        def add_support(kind: str, entries: List[Dict[str, Any]], *, id_key: str, label_key: str) -> None:
            for entry in entries:
                support_spans.append({
                    "kind": kind,
                    "id": entry.get(id_key),
                    "label": entry.get(label_key) or entry.get("normalized") or entry.get("text"),
                    "start": int(entry.get("start", 0) or 0),
                    "end": int(entry.get("end", 0) or 0),
                })

        add_support("agent", agent_mentions or [], id_key="mention_id", label_key="mention_text")
        add_support("target", target_mentions or [], id_key="mention_id", label_key="mention_text")
        add_support("action", action_mentions_meta or [], id_key="action_id", label_key="mention_text")

        events.append({
            "event_id": f"evt{len(events) + 1}",
            "event_type": event_type,
            "agents": clean_agents,
            "targets": clean_targets,
            "actions": clean_actions,
            "agent": ", ".join(clean_agents) or "ไม่ชัดเจน",
            "target": ", ".join(clean_targets) or "ไม่ชัดเจน",
            "action": ", ".join(clean_actions) or "ไม่ชัดเจน",
            "pattern": pattern,
            "confidence": round(max(0.0, min(1.0, confidence)), 3),
            "needs_review": confidence < 0.65,
            "evidence_span": evidence_span(span_start, span_end),
            "span_start": span_start,
            "span_end": span_end,
            "clause_id": f"clause:{span_start}-{span_end}",
            "agent_mentions": [
                {
                    "mention_id": mention.get("mention_id"),
                    "entity_instance_id": mention.get("entity_instance_id"),
                    "label": mention.get("normalized") or mention.get("text"),
                    "start": mention.get("start"),
                    "end": mention.get("end"),
                }
                for mention in (agent_mentions or [])
            ],
            "target_mentions": [
                {
                    "mention_id": mention.get("mention_id"),
                    "entity_instance_id": mention.get("entity_instance_id"),
                    "label": mention.get("normalized") or mention.get("text"),
                    "start": mention.get("start"),
                    "end": mention.get("end"),
                }
                for mention in (target_mentions or [])
            ],
            "action_mentions": [
                {
                    "action_id": mention.get("action_id"),
                    "label": mention.get("normalized") or mention.get("text"),
                    "start": mention.get("start"),
                    "end": mention.get("end"),
                    "domain": mention.get("domain"),
                }
                for mention in (action_mentions_meta or [])
            ],
            "support_spans": support_spans,
            "context_actors": unique(context_actors or []),
            "note": note,
        })

    if passive_markers:
        voice = "passive"
        for passive in passive_markers:
            clause_end = passive_clause_end(passive["end"])
            passive_spans.append((passive["start"], clause_end))
            before_passive = [
                mention
                for mention in actor_mentions
                if mention["end"] <= passive["start"] and has_role(mention, "target")
            ]
            in_clause_actors = [
                mention
                for mention in actor_mentions
                if passive["end"] <= mention["start"] < clause_end
            ]
            in_clause_actions = [
                mention
                for mention in action_mentions
                if passive["end"] <= mention["start"] < clause_end and mention["pattern"] != "context_only"
            ]
            selected_passive_targets = contiguous_actor_cluster(before_passive, reverse=True)
            selected_passive_agents = contiguous_actor_cluster(
                [mention for mention in in_clause_actors if has_role(mention, "agent")],
                reverse=False,
            )
            passive_targets = [normalize_actor(mention) for mention in selected_passive_targets]
            passive_agents = [normalize_actor(mention) for mention in selected_passive_agents]
            passive_actions = [mention["normalized"] for mention in in_clause_actions]
            inferred_subject = inferred_case_subject()
            if not passive_targets and inferred_subject:
                passive_targets.append(inferred_subject)
            if passive_agents or passive_actions:
                domains = unique(mention["domain"] for mention in in_clause_actions)
                append_event(
                    event_type=domains[0] if domains else "passive_event",
                    agents=passive_agents,
                    targets=passive_targets,
                    actions=passive_actions,
                    span_start=passive["start"],
                    span_end=clause_end,
                    confidence=0.88 if passive_agents and passive_targets and passive_actions else 0.62,
                    pattern="passive",
                    note="passive marker จำกัดขอบเขตด้วย clause boundary",
                    agent_mentions=selected_passive_agents,
                    target_mentions=selected_passive_targets,
                    action_mentions_meta=in_clause_actions,
                )

    for action in action_mentions:
        if action["pattern"] not in {"self", "self_or_harm"}:
            continue
        if action["pattern"] == "self_or_harm" and not any(marker in text_lower for marker in ["ตัวเอง", "ตนเอง", "เอง"]):
            continue
        start, end = clause_bounds(action["start"])
        targets = [normalize_actor(mention) for mention in actor_mentions if start <= mention["start"] <= action["start"] and has_role(mention, "target")]
        inferred_subject = inferred_case_subject()
        if not targets and inferred_subject:
            targets = [inferred_subject]
        append_event(
            event_type="self_harm",
            agents=["ตนเอง"],
            targets=targets or ["ตนเอง"],
            actions=[action["normalized"]],
            span_start=start,
            span_end=end,
            confidence=0.9 if targets or inferred_subject else 0.68,
            pattern="self",
            note="self-harm pattern จาก action ที่อ้างถึงตนเอง",
            target_mentions=[mention for mention in actor_mentions if start <= mention["start"] <= action["start"] and has_role(mention, "target")],
            action_mentions_meta=[action],
        )

    for action in action_mentions:
        if action["pattern"] in {"self", "context_only", "evidence_mark"}:
            continue
        if any(start <= action["start"] < end for start, end in passive_spans):
            continue
        start, end = clause_bounds(action["start"])
        before_action = [
            mention
            for mention in actor_mentions
            if start <= mention["end"] <= action["start"] and has_role(mention, "agent")
        ]
        after_action = [
            mention
            for mention in actor_mentions
            if action["end"] <= mention["start"] < end and has_role(mention, "target")
        ]
        selected_before_action = contiguous_actor_cluster(before_action, reverse=True)
        selected_after_action = contiguous_actor_cluster(after_action, reverse=False)
        if selected_before_action and selected_after_action:
            append_event(
                event_type=action["domain"],
                agents=[normalize_actor(mention) for mention in selected_before_action],
                targets=[normalize_actor(mention) for mention in selected_after_action],
                actions=[action["normalized"]],
                span_start=start,
                span_end=end,
                confidence=0.86,
                pattern="active",
                note="active pattern: ผู้กระทำ action ผู้ถูกกระทำ",
                agent_mentions=selected_before_action,
                target_mentions=selected_after_action,
                action_mentions_meta=[action],
            )

    for action in action_mentions:
        if action["pattern"] != "context_only":
            continue
        start, end = clause_bounds(action["start"])
        context_mentions = [
            mention
            for mention in actor_mentions
            if start <= mention["start"] < end and ("context" in mention.get("roles", []) or mention.get("group") == "family")
        ]
        if context_mentions:
            append_event(
                event_type=action["domain"],
                agents=[],
                targets=[],
                actions=[action["normalized"]],
                span_start=min([action["start"], *[mention["start"] for mention in context_mentions]]),
                span_end=end,
                confidence=0.8,
                pattern="context_only",
                note="context-only mention ไม่ถือเป็นผู้กระทำหรือผู้ถูกกระทำ",
                context_actors=[normalize_actor(mention) for mention in context_mentions],
                action_mentions_meta=[action],
            )

    role_events = [event for event in events if event["pattern"] != "context_only"]
    agents = unique(agent for event in role_events for agent in event["agents"])
    targets = unique(target for event in role_events for target in event["targets"])
    actions = unique(action for event in role_events for action in event["actions"])
    if any(agent != "ตนเอง" for agent in agents):
        agents = [agent for agent in agents if agent != "ตนเอง"]

    if agents and targets and actions:
        relation_summary = f"{', '.join(agents)} -> {', '.join(actions[:2])} -> {', '.join(targets)}"
    elif agents and actions:
        relation_summary = f"{', '.join(agents)} -> {', '.join(actions[:2])}"
    elif targets:
        relation_summary = f"target: {', '.join(targets)}"
    else:
        relation_summary = "ไม่พบบทบาทผู้กระทำ/ผู้ถูกกระทำชัดเจน"

    length = len(text)
    if length < 80:
        length_category = "short"
    elif length < 220:
        length_category = "medium"
    else:
        length_category = "long"

    return {
        "length": length,
        "length_category": length_category,
        "negation_markers": markers,
        "has_negation": bool(markers),
        "actors": actors,
        "actor_roles": {
            "agents": agents,
            "targets": targets,
            "actions": actions,
            "voice": voice,
            "relation_summary": relation_summary,
            "mentions": actor_mentions,
        },
        "events": events,
        "sentence_count": max(1, text.count(".") + text.count("।") + text.count("\n") + text.count("。") + 1),
    }


def _find_term_spans(text_lower: str, term: str) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    if not term:
        return spans
    start = text_lower.find(term)
    while start >= 0:
        spans.append((start, start + len(term)))
        start = text_lower.find(term, start + len(term))
    return spans


_GLOBAL_GUARDED_BOUNDARY_MARKERS = {"และ", "โดย", "ว่า", "ส่วน"}
_GLOBAL_BOUNDARY_FOLLOW_CUES = (
    "ไม่", "ไม่ได้", "ไม่เคย", "ถูก", "โดน", "เด็ก", "บุตร", "ลูก",
    "ผู้ป่วย", "ผู้รับบริการ", "พ่อ", "แม่", "บิดา", "มารดา",
    "สามี", "ภรรยา", "แฟน", "เพื่อน", "ญาติ", "ครู",
    "ตี", "ดุด่า", "ทำร้าย", "ทุบตี", "รังแก", "ทอดทิ้ง",
)


def _scan_text_boundaries(
    text_lower: str,
    position: int,
    markers: List[str],
) -> Tuple[int, int]:
    left_boundaries = [0]
    right_boundaries = [len(text_lower)]

    def marker_is_boundary(found: int, marker: str) -> bool:
        if marker not in _GLOBAL_GUARDED_BOUNDARY_MARKERS:
            return True
        marker_end = found + len(marker)
        prev_window = text_lower[max(0, found - 18):found]
        next_window = text_lower[marker_end:min(len(text_lower), marker_end + 18)]
        if marker == "ว่า":
            return any(cue in prev_window for cue in ("บอก", "ระบุ", "แจ้ง", "เล่า", "ยืนยัน"))
        return any(cue in next_window for cue in _GLOBAL_BOUNDARY_FOLLOW_CUES)

    for marker in markers:
        search_at = 0
        while True:
            found = text_lower.find(marker, search_at)
            if found < 0:
                break
            marker_end = found + len(marker)
            if not marker_is_boundary(found, marker):
                search_at = marker_end
                continue
            if marker_end <= position:
                left_boundaries.append(marker_end)
            elif found >= position:
                right_boundaries.append(found)
            search_at = marker_end
    return max(left_boundaries), min(right_boundaries)


def _clause_bounds_for_text(text_lower: str, position: int) -> Tuple[int, int]:
    boundary_markers = [
        ",", "，", ".", "。", ";", "；", "\n", "(", ")",
        " แต่", " แล้ว", " จึง", " จน", " เพราะ", " เนื่องจาก",
        " อย่างไรก็ตาม", " ขณะเดียวกัน", " ส่วน", " อีกทั้ง", " โดย",
        "แต่", "แล้ว", "จึง", "จน", "เพราะ", "เนื่องจาก",
        "อย่างไรก็ตาม", "ขณะเดียวกัน", "ส่วน", "อีกทั้ง", "โดย", "และ",
    ]
    return _scan_text_boundaries(text_lower, position, boundary_markers)


def _candidate_terms(item: Dict[str, Any]) -> List[str]:
    raw_terms = item.get("matched_keywords", []) or []
    if not raw_terms and item.get("name"):
        raw_terms = [item.get("name")]
    return [term.lower().strip() for term in raw_terms if isinstance(term, str) and term.strip()]


def _normalize_span_records(raw_spans: Any, text_lower: str, *, keyword_fallback: str = "") -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for raw in raw_spans or []:
        if not isinstance(raw, dict):
            continue
        start = int(raw.get("start", -1) or -1)
        end = int(raw.get("end", -1) or -1)
        if start < 0 or end <= start or end > len(text_lower):
            continue
        keyword = str(raw.get("keyword", "") or keyword_fallback or text_lower[start:end]).lower().strip()
        scope = str(raw.get("scope", "") or "")
        text = str(raw.get("text", "") or text_lower[start:end])
        normalized.append({
            "keyword": keyword,
            "start": start,
            "end": end,
            "scope": scope,
            "text": text,
            "position_source": str(raw.get("position_source", "") or ("user_adjusted" if raw.get("user_adjusted") else "provided")),
            "user_adjusted": bool(raw.get("user_adjusted", False) or raw.get("position_source") == "user_adjusted"),
        })
    normalized.sort(
        key=lambda item: (
            0 if bool(item.get("user_adjusted")) or str(item.get("position_source", "")) == "user_adjusted" else 1,
            0 if str(item.get("scope", "")) == "anchor" else 1,
            int(item["start"]),
            -(int(item["end"]) - int(item["start"])),
        )
    )
    return normalized


def _derive_evidence_spans_from_match_spans(match_spans: List[Dict[str, Any]], case_text: str) -> List[Dict[str, Any]]:
    text_lower = case_text.lower()
    spans: List[Dict[str, Any]] = []
    for match in match_spans:
        if bool(match.get("user_adjusted")) or str(match.get("position_source", "")) == "user_adjusted":
            spans.append({
                "keyword": str(match.get("keyword", "") or ""),
                "start": int(match["start"]),
                "end": int(match["end"]),
                "scope": "anchor",
                "text": case_text[int(match["start"]):int(match["end"])].strip(),
                "position_source": "user_adjusted",
                "user_adjusted": True,
            })
        clause_start, clause_end = _clause_bounds_for_text(text_lower, int(match["start"]))
        spans.append({
            "keyword": str(match.get("keyword", "") or ""),
            "start": clause_start,
            "end": clause_end,
            "scope": "clause",
            "text": case_text[clause_start:clause_end].strip(),
            "position_source": str(match.get("position_source", "") or "derived"),
            "user_adjusted": bool(match.get("user_adjusted", False)),
        })
    deduped: List[Dict[str, Any]] = []
    seen: Set[Tuple[int, int, str]] = set()
    for span in spans:
        key = (int(span["start"]), int(span["end"]), str(span.get("scope", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(span)
    return deduped


def _manual_span_matches_candidate(
    item: Dict[str, Any],
    manual_span: Dict[str, Any],
    case_text: str,
    existing_match_spans: List[Dict[str, Any]],
) -> bool:
    manual_range = (int(manual_span["start"]), int(manual_span["end"]))
    for existing in existing_match_spans:
        if _spans_overlap(manual_range, (int(existing["start"]), int(existing["end"]))):
            return True

    manual_keyword = str(manual_span.get("keyword", "") or "").lower().strip()
    manual_text = str(manual_span.get("text", "") or "").lower().strip()
    candidate_terms = _candidate_terms(item)
    return any(
        candidate_term
        and (
            (manual_keyword and (manual_keyword in candidate_term or candidate_term in manual_keyword))
            or (manual_text and (manual_text in candidate_term or candidate_term in manual_text))
        )
        for candidate_term in candidate_terms
    )


def _apply_user_adjusted_spans_to_candidates(
    items: List[Dict[str, Any]],
    case_text: str,
    user_adjusted_spans: List[Dict[str, Any]],
) -> int:
    if not items or not user_adjusted_spans:
        return 0

    applied_count = 0
    for item in items:
        base_match_spans = _candidate_match_spans(item, case_text)
        relevant_manual_spans = [
            dict(span)
            for span in user_adjusted_spans
            if _manual_span_matches_candidate(item, span, case_text, base_match_spans)
        ]
        if not relevant_manual_spans:
            continue
        applied_count += 1
        item["matched_spans"] = relevant_manual_spans
        item["evidence_spans"] = _derive_evidence_spans_from_match_spans(relevant_manual_spans, case_text)
        item["position_source"] = "user_adjusted"
        item["user_adjusted_spans_applied"] = True
    return applied_count


def _candidate_match_spans(item: Dict[str, Any], case_text: str) -> List[Dict[str, Any]]:
    text_lower = case_text.lower()
    provided = _normalize_span_records(item.get("matched_spans", []), text_lower)
    if provided:
        return provided

    spans: List[Dict[str, Any]] = []
    for term in _candidate_terms(item):
        for start, end in _find_term_spans(text_lower, term):
            spans.append({
                "keyword": term,
                "start": start,
                "end": end,
                "scope": "match",
                "text": case_text[start:end],
                "position_source": "derived",
                "user_adjusted": False,
            })
    spans.sort(key=lambda item: (int(item["start"]), -(int(item["end"]) - int(item["start"]))))
    return spans


def _candidate_evidence_spans(item: Dict[str, Any], case_text: str) -> List[Dict[str, Any]]:
    provided = _normalize_span_records(item.get("evidence_spans", []), case_text.lower())
    if provided:
        return provided

    match_spans = _candidate_match_spans(item, case_text)
    return _derive_evidence_spans_from_match_spans(match_spans, case_text)


def _candidate_term_spans(item: Dict[str, Any], case_text: str) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    for span in _candidate_match_spans(item, case_text):
        spans.append((int(span["start"]), int(span["end"])))
    return spans


def _spans_overlap(left: Tuple[int, int], right: Tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def _span_distance(left: Tuple[int, int], right: Tuple[int, int]) -> int:
    if _spans_overlap(left, right):
        return 0
    if left[1] <= right[0]:
        return right[0] - left[1]
    return left[0] - right[1]


def _event_support_spans(event: Dict[str, Any]) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    for support in event.get("support_spans", []) or []:
        if not isinstance(support, dict):
            continue
        start = int(support.get("start", -1) or -1)
        end = int(support.get("end", -1) or -1)
        if start < 0 or end <= start:
            continue
        spans.append((start, end))
    if not spans and event.get("span_start") is not None and event.get("span_end") is not None:
        spans.append((int(event.get("span_start", 0) or 0), int(event.get("span_end", 0) or 0)))
    return spans


def _positive_hardship_patterns(item: Dict[str, Any]) -> List[str]:
    code = str(item.get("code") or "")
    category = str(item.get("category") or "")
    patterns = []
    if code.startswith("10") or "การเงิน" in category:
        patterns.extend([
            "ไม่มีเงิน", "เงินไม่พอ", "รายได้ไม่พอ", "รายได้ไม่เพียงพอ",
            "จ่ายไม่ไหว", "หนี้", "หนี้สิน", "หนี้นอกระบบ", "กู้ยืม",
            "ค้างชำระ", "ค่าเช่า", "ยังไม่ได้นำส่ง", "ไม่ได้นำส่ง", "ดอก",
            "ค่าเทอม", "ค่าเทอมไม่พอ", "หาเงินค่าเทอมไม่พอ", "เงินค่าเทอม",
            "ไม่มีเงินจ่ายค่าเทอม", "หาเงินไม่พอ", "เงินไม่พอใช้", "ขาดแคลนเงิน",
        ])
    if code.startswith("11") or "การศึกษา" in category:
        patterns.extend([
            "ค่าเทอมไม่พอ", "ขาดค่าเทอม", "หาเงินค่าเทอมไม่พอ", "เงินค่าเทอม", "ไม่มีเงินจ่ายค่าเทอม",
        ])
    if code.startswith("12") or "อาชีพ" in category:
        patterns.extend([
            "ไม่มีงาน", "ว่างงาน", "ตกงาน", "ทำงานไม่ได้", "ไม่มีอาชีพ",
            "งานไม่มั่นคง", "รายได้ไม่แน่นอน",
        ])
    if code.startswith("08") or code.startswith("Z59") or "ที่อยู่อาศัย" in category:
        patterns.extend(["ไม่มีที่อยู่", "ไม่มีที่อยู่อาศัย", "ไม่มีบ้าน", "ไร้ที่พึ่ง", "เร่ร่อน"])
    if code.startswith("14") or code.startswith("17") or code.startswith(("I", "G", "E")) or "สุขภาพ" in category or "อุปสรรค" in category:
        patterns.extend([
            "ไม่ยอมกินยา", "ไม่ยอมรักษา", "ไม่ให้ความร่วมมือ", "ไม่ให้ความร่วมมือรักษา",
            "ไม่กินยา", "ไม่ร่วมมือรักษา", "ไม่มาตามนัด", "ขาดนัด", "ขาดนัดหมาย",
            "ช่วยเหลือตัวเองไม่ได้", "พูดไม่ได้", "ควบคุมไม่ได้", "ปลดหนี้ไม่ได้",
            "กินยาไม่สม่ำเสมอ", "ไม่มีเวลาพักผ่อน", "ไม่ได้พักผ่อน", "เข้ากับเพื่อนบ้านไม่ได้",
        ])
    return patterns


def _candidate_allows_actor_relation(item: Dict[str, Any]) -> bool:
    """Only interpersonal/violence candidates should inherit actor-target-action events."""
    code = str(item.get("code") or "")
    category = str(item.get("category") or "")
    name = str(item.get("name") or "")
    terms = " ".join(_candidate_terms(item))
    relation_text = " ".join([code, category, name, terms])
    relation_markers = [
        "ความรุนแรง", "ทารุณ", "ทำร้าย", "ดุด่า", "ตี", "ทุบตี",
        "ล่วงละเมิด", "ขัดแย้ง", "ทะเลาะ", "ความสัมพันธ์",
        "บิดา", "มารดา", "บุตร", "คู่สมรส", "ครอบครัว",
    ]
    if code in {"0101", "0102", "0201", "0206", "0401", "0502", "0901"}:
        return True
    if code.startswith(("01", "02", "04", "05", "09")) and any(marker in relation_text for marker in relation_markers):
        return True
    return any(marker in terms for marker in relation_markers[:7])


def _candidate_event_action_matches(item: Dict[str, Any], event: Dict[str, Any]) -> bool:
    terms = _candidate_terms(item)
    actions = [
        str(action).lower().strip()
        for action in (event.get("actions") or [event.get("action")])
        if str(action or "").strip() and str(action or "").strip() != "ไม่ชัดเจน"
    ]
    return any(action in term or term in action for action in actions for term in terms)


def _candidate_relation(item: Dict[str, Any], case_text: str, sentence_profile: Dict[str, Any]) -> Dict[str, str]:
    match_spans = _candidate_match_spans(item, case_text)
    evidence_spans = _candidate_evidence_spans(item, case_text)
    events = sentence_profile.get("events", []) or []
    if not match_spans or not events or not _candidate_allows_actor_relation(item):
        return {
            "actor": "ไม่ชัดเจน",
            "target": "ไม่ชัดเจน",
            "action": "ไม่ชัดเจน",
            "relation": "ไม่พบบทบาทผู้กระทำ/ผู้ถูกกระทำชัดเจน",
            "event_id": "",
            "event_span": "",
        }

    best_event = None
    best_score = None
    for event in events:
        event_start = int(event.get("span_start", 0) or 0)
        event_end = int(event.get("span_end", 0) or 0)
        event_span = (event_start, event_end)
        support_spans = _event_support_spans(event)
        if not _candidate_event_action_matches(item, event):
            continue

        local_score = None
        for span in evidence_spans + match_spans:
            candidate_span = (int(span["start"]), int(span["end"]))
            distance = _span_distance(candidate_span, event_span)
            score = max(0, 220 - distance)
            if bool(span.get("user_adjusted")) or str(span.get("position_source", "")) == "user_adjusted":
                score += 260
            if str(span.get("scope", "")) == "anchor":
                score += 180
            if event_start <= candidate_span[0] and candidate_span[1] <= event_end:
                score += 240
            elif _spans_overlap(candidate_span, event_span):
                score += 180

            support_distance = min(_span_distance(candidate_span, support_span) for support_span in support_spans) if support_spans else None
            if support_distance == 0:
                score += 320
            elif support_distance is not None:
                score += max(0, 120 - support_distance)

            if span in evidence_spans:
                score += 30

            if local_score is None or score > local_score:
                local_score = score

        if local_score is None:
            continue
        if best_score is None or local_score > best_score:
            best_event = event
            best_score = local_score

    if not best_event or (best_score is not None and best_score < 200):
        return {
            "actor": "ไม่ชัดเจน",
            "target": "ไม่ชัดเจน",
            "action": "ไม่ชัดเจน",
            "relation": "ไม่พบบทบาทผู้กระทำ/ผู้ถูกกระทำชัดเจน",
            "event_id": "",
            "event_span": "",
        }

    actor = best_event.get("agent") or "ไม่ชัดเจน"
    target = best_event.get("target") or "ไม่ชัดเจน"
    action = best_event.get("action") or "ไม่ชัดเจน"
    if actor != "ไม่ชัดเจน" and target != "ไม่ชัดเจน" and action != "ไม่ชัดเจน":
        relation = f"{actor} -> {action} -> {target}"
    elif actor != "ไม่ชัดเจน" and action != "ไม่ชัดเจน":
        relation = f"{actor} -> {action}"
    else:
        relation = "ไม่พบบทบาทผู้กระทำ/ผู้ถูกกระทำชัดเจน"
    return {
        "actor": actor,
        "target": target,
        "action": action,
        "relation": relation,
        "event_id": str(best_event.get("event_id") or ""),
        "event_span": f"{best_event.get('span_start', 0)}-{best_event.get('span_end', 0)}",
    }


def _candidate_polarity_signal(
    item: Dict[str, Any],
    case_text: str,
    sentence_profile: Dict[str, Any],
) -> Dict[str, Any]:
    text_lower = case_text.lower()
    negation_markers = sentence_profile.get("negation_markers", []) or []
    match_spans = _candidate_match_spans(item, case_text)
    negated_terms: List[str] = []

    if not text_lower or not negation_markers or not match_spans:
        return {
            "gate": 1.0,
            "negated": False,
            "negated_terms": [],
            "reason": "ไม่พบ negation ที่ครอบ candidate นี้",
        }

    marker_spans: List[Tuple[int, int, str]] = []
    for marker in negation_markers:
        for start, end in _find_term_spans(text_lower, marker.lower()):
            marker_spans.append((start, end, marker))

    hardship_patterns = _positive_hardship_patterns(item)
    for span in match_spans:
        term = str(span.get("keyword", "") or "").lower().strip()
        term_start = int(span["start"])
        clause_start, clause_end = _clause_bounds_for_text(text_lower, term_start)
        clause_text = text_lower[clause_start:clause_end]
        for marker_start, marker_end, _marker in marker_spans:
            if marker_start < clause_start or marker_end > clause_end:
                continue
            if term_start < marker_end:
                continue
            if term_start - marker_end > 28:
                continue
            between = text_lower[marker_end:term_start]
            if any(breaker in between for breaker in POLARITY_SCOPE_BREAKERS):
                continue
            if hardship_patterns and any(pattern in clause_text for pattern in hardship_patterns):
                continue
            negated_terms.append(term or case_text[term_start:int(span["end"])])
            break

    negated_terms = list(dict.fromkeys(negated_terms))
    if negated_terms:
        return {
            "gate": POLARITY_NEGATION_GATE,
            "negated": True,
            "negated_terms": negated_terms,
            "reason": f"พบ negation scope ครอบคำ: {', '.join(negated_terms[:3])}",
        }

    return {
        "gate": 1.0,
        "negated": False,
        "negated_terms": [],
        "reason": "มี negation ในประโยค แต่ไม่ได้ครอบ candidate นี้โดยตรง",
    }


def _apply_polarity_gate(
    case_text: str,
    problems: List[Dict[str, Any]],
    filtered_out: List[Dict[str, Any]],
    sentence_profile: Dict[str, Any],
    *,
    enabled: bool,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    updated_problems: List[Dict[str, Any]] = []
    updated_filtered: List[Dict[str, Any]] = []

    def annotate(item: Dict[str, Any]) -> Dict[str, Any]:
        before = float(item.get("confidence", 0.0) or 0.0)
        signal = _candidate_polarity_signal(item, case_text, sentence_profile)
        relation = _candidate_relation(item, case_text, sentence_profile)
        after = round(before * signal["gate"], 4)
        return {
            **item,
            "confidence_before_polarity": before,
            "confidence_after_polarity": after,
            "polarity_gate": signal["gate"],
            "polarity_negated": signal["negated"],
            "polarity_negated_terms": signal["negated_terms"],
            "polarity_reason": signal["reason"],
            "polarity_actor": relation["actor"],
            "polarity_target": relation["target"],
            "polarity_action": relation["action"],
            "polarity_relation": relation["relation"],
            "polarity_event_id": relation["event_id"],
            "polarity_event_span": relation["event_span"],
        }

    for item in problems:
        annotated = annotate(item)
        if enabled and annotated["polarity_negated"]:
            moved = {
                **annotated,
                "confidence": annotated["confidence_after_polarity"],
                "validation_notes": annotated["polarity_reason"],
            }
            updated_filtered.append(moved)
            continue
        updated_problems.append({
            **annotated,
            "confidence": annotated["confidence_after_polarity"] if enabled else annotated["confidence_before_polarity"],
        })

    for item in filtered_out:
        annotated = annotate(item)
        updated_filtered.append({
            **annotated,
            "confidence": annotated["confidence_after_polarity"] if enabled and annotated["polarity_negated"] else annotated["confidence_before_polarity"],
        })

    return updated_problems, updated_filtered


ABUSE_EVIDENCE_ASPECTS = (
    {
        "id": "physical_violence",
        "label": "ความรุนแรงทางร่างกาย",
        "indicators": (
            "ทำร้ายร่างกาย", "ทำโทษเกินเหตุ", "ทุบตี", "ตบตี",
            "ตีเด็ก", "ตีลูก", "เตะ", "ตบ", "ตี",
        ),
    },
    {
        "id": "psychological_violence",
        "label": "ความรุนแรงทางจิตใจ",
        "indicators": (
            "ทำร้ายจิตใจ", "ขู่เข็ญ", "ข่มขู่", "ด่าว่า", "ดุด่า",
            "กดดัน", "เหยียด",
        ),
    },
)


def _event_exact_quote(event: Dict[str, Any], case_text: str) -> str:
    start_value = event.get("span_start", -1)
    end_value = event.get("span_end", -1)
    start = int(start_value) if start_value is not None else -1
    end = int(end_value) if end_value is not None else -1
    if 0 <= start < end <= len(case_text):
        return case_text[start:end].strip()
    quote = str(event.get("evidence_span") or "").strip()
    return quote if quote and quote in case_text else ""


def _grounded_explanation(
    item: Dict[str, Any],
    case_text: str,
    sentence_profile: Dict[str, Any],
) -> Dict[str, Any]:
    relation = {
        "actor": str(item.get("polarity_actor") or "ไม่ชัดเจน"),
        "target": str(item.get("polarity_target") or "ไม่ชัดเจน"),
        "action": str(item.get("polarity_action") or "ไม่ชัดเจน"),
    }
    evidence_spans = _candidate_evidence_spans(item, case_text)
    quote = ""
    for span in evidence_spans:
        start_value = span.get("start", -1)
        end_value = span.get("end", -1)
        start = int(start_value) if start_value is not None else -1
        end = int(end_value) if end_value is not None else -1
        if 0 <= start < end <= len(case_text):
            quote = case_text[start:end].strip()
            if quote:
                break

    indicator_scope = quote.lower() if quote else case_text.lower()
    indicators = [
        str(keyword)
        for keyword in item.get("matched_keywords", []) or []
        if str(keyword).strip() and str(keyword).lower() in indicator_scope
    ]
    indicators = list(dict.fromkeys(indicators))
    name = str(item.get("name") or item.get("code") or "ประเด็นที่เกี่ยวข้อง")
    if relation["actor"] != "ไม่ชัดเจน" and relation["action"] != "ไม่ชัดเจน":
        target_suffix = f"ต่อ{relation['target']}" if relation["target"] != "ไม่ชัดเจน" else ""
        lead = f"{relation['actor']}มีการ{relation['action']}{target_suffix}"
    else:
        lead = f"พบข้อบ่งชี้ที่สอดคล้องกับ {name}"
    context_text = f" จากบริบทว่า \"{quote}\"" if quote else ""
    indicator_text = f" โดยมีข้อบ่งชี้คือ {', '.join(indicators)}" if indicators else ""
    return {
        "summary": f"{lead}{context_text}{indicator_text}",
        **relation,
        "evidence_quote": quote,
        "indicators": indicators,
        "source": "deterministic_evidence",
        "grounded": bool(quote and quote in case_text),
    }


def _abuse_evidence_aspects(
    item: Dict[str, Any],
    case_text: str,
    sentence_profile: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if str(item.get("code") or "") not in {"0102", "0206", "T74", "T74.1"}:
        return []

    text_lower = case_text.lower()
    events = sentence_profile.get("events", []) or []
    aspects: List[Dict[str, Any]] = []
    for definition in ABUSE_EVIDENCE_ASPECTS:
        indicators = [term for term in definition["indicators"] if term in text_lower]
        if not indicators:
            continue

        matching_events = [
            event
            for event in events
            if any(
                term in str(event.get("action") or "").lower()
                or str(event.get("action") or "").lower() in term
                for term in indicators
            )
        ]
        event = matching_events[0] if matching_events else None
        quote = _event_exact_quote(event, case_text) if event else ""
        if not quote:
            for span in _candidate_evidence_spans(item, case_text):
                start_value = span.get("start", -1)
                end_value = span.get("end", -1)
                start = int(start_value) if start_value is not None else -1
                end = int(end_value) if end_value is not None else -1
                if not (0 <= start < end <= len(case_text)):
                    continue
                candidate_quote = case_text[start:end].strip()
                if any(term in candidate_quote.lower() for term in indicators):
                    quote = candidate_quote
                    break
        if not quote or quote not in case_text:
            continue

        actor = str((event or {}).get("agent") or item.get("polarity_actor") or "ไม่ชัดเจน")
        target = str((event or {}).get("target") or item.get("polarity_target") or "ไม่ชัดเจน")
        action = str((event or {}).get("action") or item.get("polarity_action") or "ไม่ชัดเจน")
        if actor != "ไม่ชัดเจน" and target != "ไม่ชัดเจน":
            lead = f"{actor}เป็นผู้กระทำ{definition['label']}ต่อ{target}"
        else:
            lead = f"พบข้อบ่งชี้ของ{definition['label']}"
        aspects.append({
            "id": definition["id"],
            "label": definition["label"],
            "summary": f"{lead} จากบริบทว่า \"{quote}\" โดยมีข้อบ่งชี้คือ {', '.join(indicators)}",
            "actor": actor,
            "target": target,
            "action": action,
            "evidence_quote": quote,
            "indicators": indicators,
            "source": "deterministic_evidence",
            "grounded": True,
        })
    return aspects


def _attach_grounded_explanations(
    case_text: str,
    problems: List[Dict[str, Any]],
    filtered_out: List[Dict[str, Any]],
    sentence_profile: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    def annotate(item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            **item,
            "grounded_explanation": _grounded_explanation(item, case_text, sentence_profile),
            "evidence_aspects": _abuse_evidence_aspects(item, case_text, sentence_profile),
        }

    return [annotate(item) for item in problems], [annotate(item) for item in filtered_out]


def _apply_review_status(
    problems: List[Dict[str, Any]],
    filtered_out: List[Dict[str, Any]],
    *,
    baseline_mode: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    annotated_problems = [classify_review_status_dict(item, filtered=False, baseline=baseline_mode) for item in problems]
    annotated_filtered = [classify_review_status_dict(item, filtered=True, baseline=baseline_mode) for item in filtered_out]
    return annotated_problems, annotated_filtered


def _review_status_summary(
    problems: List[Dict[str, Any]],
    filtered_out: List[Dict[str, Any]],
    *,
    baseline_mode: bool = False,
) -> Dict[str, Any]:
    summary = {
        "confirmed": 0,
        "needs_review": 0,
        "verify_documents": 0,
        "filtered": 0,
        "baseline_candidate": 0,
        "baseline_filtered": 0,
        "total": len(problems) + len(filtered_out),
        "accepted_total": len(problems),
        "filtered_total": len(filtered_out),
    }
    for item in problems + filtered_out:
        status = str(item.get("review_status") or "")
        if status in summary:
            summary[status] += 1
    if baseline_mode:
        interpretation = (
            f"baseline preview มี candidate {summary['baseline_candidate']} รายการ "
            f"และ filtered preview {summary['baseline_filtered']} รายการ"
        )
    else:
        interpretation = (
            f"confirmed {summary['confirmed']} | needs review {summary['needs_review']} | "
            f"verify documents {summary['verify_documents']} | filtered {summary['filtered']}"
        )
    return {
        **summary,
        "baseline_mode": baseline_mode,
        "interpretation": interpretation,
    }


def _stable_unit_interval(value: str, salt: int) -> float:
    total = sum((idx + 1 + salt) * ord(char) for idx, char in enumerate(value))
    return (total % 1000) / 1000


def _vector_space(case_text: str, problems: List[Dict], retrieved_docs: List[Dict], runtime: RuntimeManager) -> Dict:
    embedder = runtime.embedder()
    if embedder is None:
        return {
            "projection": "embedding-unavailable",
            "embedding_status": "unavailable",
            "note": "ยังสร้าง 3D vector space จาก embedding จริงไม่ได้ เพราะ embedding model หรือ vector index ยังไม่พร้อม",
            "nodes": [],
            "edges": [],
        }

    source_nodes: List[Dict[str, Any]] = [{
        "id": "query",
        "label": "q: ข้อความเคสที่กำลังวิเคราะห์",
        "type": "query",
        "raw_text": case_text,
        "score": 1.0,
        "severity": 1,
    }]

    for index, problem in enumerate(problems[:8], start=1):
        keywords = " ".join(problem.get("matched_keywords", [])[:6])
        code = str(problem.get("code", f"P{index}"))
        source_nodes.append({
            "id": code,
            "label": f"P_{index}: {code} {problem.get('name', '')}",
            "type": "problem",
            "raw_text": f"{code} {problem.get('name', '')} {keywords}",
            "score": float(problem.get("confidence", 0.0)),
            "severity": float(problem.get("severity", 1)),
            "code": code,
            "explanation": f"รหัส {code} ถูกวางเทียบกับข้อความเคสจากชื่อปัญหาและ keyword ที่ detector พบ",
        })

    for index, doc in enumerate(retrieved_docs[:6], start=1):
        doc_id = str(doc.get("id") or f"D{index}")
        source_nodes.append({
            "id": f"D_{index}",
            "label": f"D_{index}: {doc.get('title') or doc.get('source') or doc_id}",
            "type": "document",
            "raw_text": doc.get("snippet") or doc.get("content") or "",
            "score": float(doc.get("h2l_final_score") or doc.get("final_score") or doc.get("score") or 0.0),
            "severity": 1,
            "doc_id": doc_id,
            "rank": doc.get("rank", index),
            "source": doc.get("source"),
            "explanation": doc.get("reason", "เอกสารนี้ถูกดึงมาเพราะ score retrieval สูงสำหรับข้อความเคสปัจจุบัน"),
        })

    if len(source_nodes) <= 1:
        return {
            "projection": "embedding-ready-no-nodes",
            "embedding_status": "ready",
            "note": "embedding พร้อม แต่ยังไม่มี problem/document node ให้แสดง",
            "nodes": source_nodes,
            "edges": [],
        }

    try:
        import numpy as np

        texts = [
            f"query: {node['raw_text']}" if node["type"] == "query" else node["raw_text"]
            for node in source_nodes
        ]
        embeddings = embedder.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        embeddings = np.asarray(embeddings, dtype="float32")
        relative = embeddings - embeddings[0]
        if relative.shape[0] > 1:
            _, _, vh = np.linalg.svd(relative, full_matrices=False)
            dims = min(3, vh.shape[0])
            coords = relative @ vh[:dims].T
        else:
            coords = np.zeros((len(source_nodes), 3), dtype="float32")
        if coords.shape[1] < 3:
            coords = np.pad(coords, ((0, 0), (0, 3 - coords.shape[1])), mode="constant")

        max_abs = max(float(np.max(np.abs(coords))), 1e-6)
        normalized = 0.5 + (coords / (max_abs * 2.4))
        normalized[0] = np.array([0.5, 0.5, 0.5])

        query_vec = embeddings[0]
        for idx, node in enumerate(source_nodes):
            sim = float(np.dot(query_vec, embeddings[idx]))
            dist = float(1.0 - sim)
            node.update({
                "x": max(0.08, min(0.92, float(normalized[idx][0]))),
                "y": max(0.08, min(0.92, float(normalized[idx][1]))),
                "z": max(0.08, min(0.92, float(normalized[idx][2]))),
                "semantic_similarity_to_query": sim,
                "semantic_distance_to_query": dist,
                "distance_label": f"d(q,{node['id']})={dist:.3f}",
            })

        edges: List[Dict[str, Any]] = []
        for node in source_nodes:
            if node["id"] == "query":
                continue
            edges.append({
                "source": "query",
                "target": node["id"],
                "weight": max(0.0, min(1.0, node.get("semantic_similarity_to_query", 0.0))),
                "distance": node.get("semantic_distance_to_query"),
                "edge_type": "query-problem" if node["type"] == "problem" else "query-document",
            })

        problem_nodes = [node for node in source_nodes if node["type"] == "problem"]
        doc_nodes = [node for node in source_nodes if node["type"] == "document"]
        by_id = {node["id"]: idx for idx, node in enumerate(source_nodes)}
        for problem in problem_nodes[:4]:
            for doc in doc_nodes[:4]:
                sim = float(np.dot(embeddings[by_id[problem["id"]]], embeddings[by_id[doc["id"]]]))
                if sim >= 0.15:
                    edges.append({
                        "source": problem["id"],
                        "target": doc["id"],
                        "weight": max(0.0, min(1.0, sim)),
                        "distance": 1.0 - sim,
                        "edge_type": "problem-document",
                    })

        return {
            "projection": "real-embedding-svd-3d",
            "embedding_status": "ready",
            "note": "3D projection นี้สร้างจาก embedding ของข้อความเคส รหัสปัญหา และเอกสารที่ retrieval ดึงมาจริง แล้วลดมิติด้วย SVD เพื่ออธิบายระยะ semantic",
            "nodes": source_nodes,
            "edges": edges,
            "legend": [
                {"edge_type": "query-problem", "label": "ข้อความเคส ↔ รหัสปัญหา"},
                {"edge_type": "query-document", "label": "ข้อความเคส ↔ เอกสารหลักฐาน"},
                {"edge_type": "problem-document", "label": "รหัสปัญหา ↔ เอกสารหลักฐาน"},
            ],
        }
    except Exception as exc:
        logger.warning("Vector projection failed: %s", exc)
        return {
            "projection": "embedding-projection-error",
            "embedding_status": "error",
            "note": f"embedding พร้อมแต่สร้าง projection ไม่สำเร็จ: {exc}",
            "nodes": [],
            "edges": [],
        }


def _detection_flow(
    metadata: Dict,
    problems: List[Dict],
    filtered_out: List[Dict],
    phase_timings: Optional[Dict[str, float]] = None,
) -> Dict:
    l1_count = metadata.get("l1_count", 0)
    l2_count = metadata.get("l2_count", 0)
    l2_status = "complete" if l2_count else "not-run"
    timings = phase_timings or {}
    ambiguity = _ambiguity_summary(metadata)
    return {
        "steps": [
            {"name": "Case Input", "count": 1, "status": "complete", "duration_ms": timings.get("case_input", 0.0)},
            {"name": "L1 Keyword + Context", "count": l1_count + len(filtered_out), "status": "complete", "duration_ms": timings.get("l1", 0.0)},
            {"name": "L2 Semantic Validation", "count": l2_count, "status": l2_status, "duration_ms": timings.get("l2", 0.0)},
            {"name": "Final Problems", "count": len(problems), "status": "complete", "duration_ms": timings.get("finalize", 0.0)},
        ],
        "phase_timings_ms": timings,
        "conflicts": metadata.get("conflicts", {}),
        "ambiguity_summary": ambiguity,
        "filtered_count": len(filtered_out),
    }


def _ambiguity_summary(metadata: Dict[str, Any]) -> Dict[str, Any]:
    conflicts = metadata.get("conflicts", {}) or {}
    needs_validation = metadata.get("needs_l2_validation", []) or []
    l1_filtered_out = metadata.get("l1_filtered_out", []) or []

    conflict_codes = sorted(
        {
            *[str(code) for code in conflicts.keys()],
            *[str(code) for values in conflicts.values() for code in (values or [])],
        }
    )
    review_codes = sorted({*map(str, needs_validation), *conflict_codes})
    conflict_links = int(sum(len(values or []) for values in conflicts.values()))
    review_count = len(review_codes)
    l1_filtered_count = len(l1_filtered_out)

    if review_count >= 4 or conflict_links >= 4:
        level = "high"
    elif review_count >= 2 or conflict_links >= 2:
        level = "medium"
    else:
        level = "low"

    if review_count == 0 and l1_filtered_count == 0:
        interpretation = "ไม่พบรหัสที่ชนกันหรือ candidate ที่ต้องทบทวนเพิ่ม"
    elif conflict_codes:
        interpretation = (
            f"พบ {len(conflict_codes)} รหัสที่ชนหรือทับกัน "
            f"และมี {len(set(map(str, needs_validation)))} candidate ที่ต้องทบทวนบริบทเพิ่ม"
        )
    else:
        interpretation = (
            f"มี {review_count} candidate ที่ต้องทบทวนบริบทเพิ่ม"
            + (f" และมี {l1_filtered_count} candidate ถูกกรองตั้งแต่ L1" if l1_filtered_count else "")
        )

    return {
        "label": "Review Load",
        "count": review_count,
        "level": level,
        "review_codes": review_codes,
        "review_count": review_count,
        "conflict_codes": conflict_codes,
        "conflict_code_count": len(conflict_codes),
        "conflict_links": conflict_links,
        "needs_validation_count": len(set(map(str, needs_validation))),
        "l1_filtered_count": l1_filtered_count,
        "interpretation": interpretation,
    }


def _doc_text(result: Any) -> str:
    doc = getattr(result, "doc", None)
    if doc is not None:
        return getattr(doc, "text", "") or ""
    if isinstance(result, dict):
        return result.get("text") or result.get("content") or result.get("snippet") or ""
    return ""


def _doc_meta(result: Any) -> Dict[str, Any]:
    doc = getattr(result, "doc", None)
    if doc is not None:
        return getattr(doc, "meta", {}) or {}
    if isinstance(result, dict):
        return result.get("meta") or result.get("metadata") or {}
    return {}


def _doc_id(result: Any, fallback: int) -> Any:
    doc = getattr(result, "doc", None)
    if doc is not None:
        return getattr(doc, "id", fallback)
    if isinstance(result, dict):
        return result.get("id", fallback)
    return fallback


def _result_score(result: Any, *names: str) -> Optional[float]:
    for name in names:
        value = getattr(result, name, None)
        if value is None and isinstance(result, dict):
            value = result.get(name)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _matched_problem_evidence(text: str, problems: List[Dict]) -> List[Dict[str, Any]]:
    text_lower = text.lower()
    evidence = []
    for problem in problems:
        keywords = [kw for kw in problem.get("matched_keywords", []) if kw and kw.lower() in text_lower]
        name_words = [
            word
            for word in str(problem.get("name", "")).split()
            if len(word) > 2 and word.lower() in text_lower
        ]
        if keywords or name_words:
            evidence.append({
                "code": problem.get("code"),
                "name": problem.get("name"),
                "matched_keywords": keywords[:8],
                "matched_name_terms": name_words[:6],
                "reason": f"พบคำ/บริบทที่สัมพันธ์กับรหัส {problem.get('code')} ในเอกสาร",
            })
    return evidence


def _serialize_retrieved_docs(results: List[Any], problems: List[Dict]) -> List[Dict[str, Any]]:
    docs = []
    for rank, result in enumerate(results or [], start=1):
        text = _doc_text(result)
        meta = _doc_meta(result)
        doc_id = _doc_id(result, rank)
        source = (
            meta.get("source")
            or meta.get("file_name")
            or meta.get("filename")
            or meta.get("document")
            or meta.get("path")
            or f"doc-{doc_id}"
        )
        title = meta.get("title") or meta.get("heading") or str(source)
        base_score = _result_score(result, "h2l_base_score", "score")
        rerank_score = _result_score(result, "rerank_score")
        final_score = _result_score(result, "h2l_final_score", "final_score", "rerank_score", "score")
        breakdown = getattr(result, "h2l_breakdown", None)
        if isinstance(result, dict):
            breakdown = result.get("h2l_breakdown", breakdown)
        chunk_index = meta.get("chunk_index") if meta.get("chunk_index") is not None else meta.get("chunk_idx", meta.get("index"))
        if chunk_index is None and isinstance(doc_id, str) and doc_id.startswith("chunk_"):
            chunk_index = doc_id.replace("chunk_", "")
        page_number = meta.get("page") or meta.get("page_number") or meta.get("page_no")
        source_doc = meta.get("source_document") or meta.get("file_name") or meta.get("filename") or source
        if source_doc:
            source_doc = str(source_doc).strip()

        location_parts = []
        if source:
            location_parts.append(str(source))
        if chunk_index is not None:
            location_parts.append(f"ช่วงที่ {chunk_index}")
        if page_number is not None:
            location_parts.append(f"หน้า {page_number}")
        location_label = " · ".join(location_parts)

        matched = _matched_problem_evidence(text, problems)

        docs.append({
            "rank": rank,
            "id": doc_id,
            "title": title,
            "source": source,
            "source_document": source_doc,
            "chunk_index": chunk_index,
            "page_number": page_number,
            "location_label": location_label,
            "snippet": text[:520],
            "content": text[:1500],
            "score": final_score,
            "base_score": base_score,
            "rerank_score": rerank_score,
            "h2l_final_score": final_score,
            "h2l_breakdown": breakdown or {},
            "h2l_semantic_used": bool(getattr(result, "h2l_semantic_used", False)),
            "matched_problem_evidence": matched,
            "reason": (
                f"อันดับ {rank}: score retrieval สูง"
                + (f" และพบ evidence สำหรับ {', '.join(item['code'] for item in matched[:3] if item.get('code'))}" if matched else "")
            ),
            "metadata": {
                key: value
                for key, value in meta.items()
                if key not in {"content", "text"} and isinstance(value, (str, int, float, bool, type(None)))
            },
        })
    return docs


def _candidate_trace(problems: List[Dict], filtered_out: List[Dict], metadata: Dict[str, Any]) -> Dict[str, Any]:
    candidates = []

    def add_candidate(item: Dict[str, Any], decision: str, reason: str) -> None:
        detection_level = item.get("detection_level", "L1")
        confidence = float(item.get("confidence", 0.0) or 0.0)
        candidates.append({
            "code": item.get("code"),
            "name": item.get("name"),
            "keyword": ", ".join(item.get("matched_keywords", [])[:4]) or "implicit/context",
            "matched_keywords": item.get("matched_keywords", []),
            "confidence": confidence,
            "context_rule": item.get("reasoning") or item.get("validation_notes") or "ไม่มี context rule ระบุ",
            "context_valid": item.get("context_valid", True),
            "needs_l2": "NeedsValidation" in detection_level,
            "detection_level": detection_level,
            "final_decision": decision,
            "filter_reason": reason if decision != "accepted" else "",
            "severity": item.get("severity", 1),
        })

    for problem in problems:
        add_candidate(problem, "accepted", "")
    for item in filtered_out:
        reason = item.get("validation_notes") or item.get("reasoning") or "filtered by low confidence/context threshold"
        add_candidate(item, "filtered", reason)

    reason_counts: Dict[str, int] = {}
    for candidate in candidates:
        reason = candidate.get("filter_reason") or "accepted"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    return {
        "candidate_count": len(candidates),
        "l1_candidates": metadata.get("l1_count", 0) + len(filtered_out),
        "l2_candidates": metadata.get("l2_count", 0),
        "final_accepted": len(problems),
        "filtered_out": len(filtered_out),
        "candidates": candidates,
        "filter_reasons": [
            {"reason": reason, "count": count}
            for reason, count in sorted(reason_counts.items(), key=lambda item: item[1], reverse=True)
        ],
    }


def _polarity_effect(problems: List[Dict], filtered_out: List[Dict], sentence_profile: Dict[str, Any]) -> Dict[str, Any]:
    rows = []
    negated = bool(sentence_profile.get("has_negation"))
    relation_summary = sentence_profile.get("actor_roles", {}).get("relation_summary") or "ไม่พบบทบาทชัดเจน"

    for item in problems + filtered_out:
        before = float(item.get("confidence_before_polarity", item.get("confidence", 0.0)) or 0.0)
        is_filtered = item in filtered_out
        gate = float(item.get("polarity_gate", 1.0) or 1.0)
        after = float(item.get("confidence_after_polarity", before * gate) or 0.0)
        negated_terms = item.get("polarity_negated_terms", []) or []
        polarity_reason = item.get("polarity_reason") or ""
        relation = item.get("polarity_relation") or "ไม่พบบทบาทผู้กระทำ/ผู้ถูกกระทำชัดเจน"
        rows.append({
            "code": item.get("code"),
            "name": item.get("name"),
            "before_confidence": before,
            "after_polarity_gate": after,
            "gate": gate,
            "decision": "filtered" if is_filtered else "kept",
            "actor": item.get("polarity_actor") or "ไม่ชัดเจน",
            "target": item.get("polarity_target") or "ไม่ชัดเจน",
            "action": item.get("polarity_action") or "ไม่ชัดเจน",
            "event_id": item.get("polarity_event_id") or "",
            "event_span": item.get("polarity_event_span") or "",
            "trigger_terms": negated_terms,
            "explanation": (
                f"polarity gate อ่านความสัมพันธ์ '{relation}'"
                + (f" และลดน้ำหนักเพราะ negation ครอบคำ {', '.join(negated_terms[:3])}" if gate < 1 and negated_terms else "")
                + (f" ({polarity_reason})" if polarity_reason else "")
                + (" และคงน้ำหนักเพราะไม่พบ negation ที่หักล้าง candidate" if gate >= 1 else "")
            ),
        })

    return {
        "has_negation": negated,
        "negation_markers": sentence_profile.get("negation_markers", []),
        "relation_summary": relation_summary,
        "rows": rows,
        "interpretation": (
            "มี sentence polarity แล้ว candidate ที่ถูก negation ครอบตรง ๆ จะถูกลดน้ำหนักหรือย้ายออกจาก final problems"
            if negated
            else "ไม่พบคำปฏิเสธที่ชัด ระบบจึงคงน้ำหนัก candidate และใช้ actor/target/action เพื่ออธิบายบริบท"
        ),
    }


def _retrieval_trace(
    strategy: str,
    retrieved_docs: List[Dict[str, Any]],
    errors: List[str],
    retriever: Any = None,
    docs_requested: Optional[int] = None,
) -> Dict[str, Any]:
    return {
        "strategy": strategy,
        "retriever_class": type(retriever).__name__ if retriever is not None else None,
        "docs_requested": docs_requested if docs_requested is not None else (runtime_manager.config.TOP_K if runtime_manager.config else None),
        "docs_returned": len(retrieved_docs),
        "errors": errors,
        "score_fields": ["base_score", "rerank_score", "h2l_final_score"],
        "explanation": "เอกสารถูกจัดอันดับจาก retrieval score และ H2L problem-aware score เมื่อใช้ strategy ฝั่ง enhanced",
    }


def _h2l_scoring_trace(retrieved_docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    trace = []
    for doc in retrieved_docs:
        breakdown = doc.get("h2l_breakdown") or {}
        if breakdown:
            trace.append({
                "rank": doc.get("rank"),
                "doc_id": doc.get("id"),
                "base_score": doc.get("base_score"),
                "final_score": doc.get("h2l_final_score"),
                "semantic_used": doc.get("h2l_semantic_used"),
                "breakdown": breakdown,
                "interpretation": "H2L ปรับคะแนนเอกสารจาก prior/severity/keyword-semantic match และ sentence polarity",
            })
    trace.sort(
        key=lambda item: float(
            item.get("final_score")
            or (item.get("breakdown") or {}).get("S_final")
            or 0.0
        ),
        reverse=True,
    )
    return trace


def _latest_json(pattern: str) -> tuple[Path | None, Dict]:
    preferred_alias = _preferred_artifact_alias(pattern)
    if preferred_alias and preferred_alias.exists():
        try:
            return preferred_alias, json.loads(preferred_alias.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read %s: %s", preferred_alias, exc)
            return preferred_alias, {}
    files = sorted(Path(".").glob(pattern))
    if not files:
        return None, {}
    latest = files[-1]
    try:
        return latest, json.loads(latest.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read %s: %s", latest, exc)
        return latest, {}


def _read_json_path(path: Path | None) -> Dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return {}


def _artifact_inventory_summary() -> Dict[str, Any]:
    proper_history = sorted(Path("evaluation_results").glob("proper_eval_summary_*.json"))
    polarity_history = sorted(Path("evaluation_results").glob("sentence_polarity_eval_*.json"))
    pair_dirs = sorted([path for path in (Path("evaluation_results") / "pairs").glob("*") if path.is_dir()])
    return {
        "proper_eval_history_count": len(proper_history),
        "polarity_history_count": len(polarity_history),
        "pair_family_dirs": [path.name for path in pair_dirs],
        "history_retention_policy": {
            "proper_eval": "keep latest + checkpoint + newest timestamped bundles",
            "sentence_polarity": "keep latest + newest timestamped bundles",
            "pair_runs": "keep latest bundle inside each family directory",
        },
        "interpretation": (
            "artifact history ถูกย่อให้เหลือไฟล์ที่ใช้ review ย้อนหลังได้จริง ขณะที่ latest/checkpoint ยังเป็นแหล่งหลักที่ UI อ่านแบบ realtime"
        ),
    }


def _normalize_progress_payload(progress: Optional[Dict[str, Any]], source_path: Path) -> Dict[str, Any]:
    if not progress:
        return {"source": str(source_path), "status": "idle", "phase": "not_started"}
    payload = {"source": str(source_path), **progress}
    raw_status = payload.get("status", "idle")
    if raw_status == "running":
        completed = int(payload.get("completed_case_count") or 0)
        total = int(payload.get("total_case_count") or 0)
        if total > 0 and completed >= total:
            payload["status"] = "complete"
            payload["phase"] = "completed"
        else:
            updated_dt = _parse_iso_datetime(payload.get("updated_at"))
            if updated_dt and (datetime.now(timezone.utc) - updated_dt).total_seconds() > 300:
                payload["status"] = "stale"
                payload["phase"] = "timed_out"
    return payload


def _evaluation_progress_summary() -> Dict[str, Any]:
    proper_raw = _read_json_path(EVALUATION_PROGRESS_FILES["proper_eval"])
    polarity_raw = _read_json_path(EVALUATION_PROGRESS_FILES["sentence_polarity"])
    proper = _normalize_progress_payload(proper_raw, EVALUATION_PROGRESS_FILES["proper_eval"])
    polarity = _normalize_progress_payload(polarity_raw, EVALUATION_PROGRESS_FILES["sentence_polarity"])
    proper_status = proper.get("status", "idle")
    polarity_status = polarity.get("status", "idle")
    if "running" in {proper_status, polarity_status}:
        overall_status = "running"
    elif "error" in {proper_status, polarity_status}:
        overall_status = "error"
    elif "complete" in {proper_status, polarity_status}:
        overall_status = "complete"
    else:
        overall_status = "idle"
    return {
        "status": overall_status,
        "proper_eval": proper,
        "sentence_polarity": polarity,
        "interpretation": (
            "progress นี้อ่านจากไฟล์จริงที่ evaluator เขียนระหว่างรัน พร้อมระบบตรวจสอบความสดใหม่เพื่อป้องกันการค้างสถานะ"
        ),
    }


def _preferred_artifact_alias(pattern: str) -> Optional[Path]:
    alias_map = {
        "evaluation_results/proper_eval_summary_*.json": Path("evaluation_results/proper_eval_latest_summary.json"),
        "evaluation_results/proper_eval_raw_*.json": Path("evaluation_results/proper_eval_latest_raw.json"),
        "evaluation_results/proper_eval_cases_*.json": Path("evaluation_results/proper_eval_latest_cases.json"),
        "evaluation_results/sentence_polarity_eval_*.json": Path("evaluation_results/sentence_polarity_latest.json"),
    }
    return alias_map.get(pattern)


def _proper_summary_candidate_paths() -> List[Path]:
    paths: List[Path] = list(sorted(Path(".").glob("evaluation_results/proper_eval_summary_*.json")))
    alias = _preferred_artifact_alias("evaluation_results/proper_eval_summary_*.json")
    if alias and alias.exists():
        paths.append(alias)
    return paths


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _ground_truth_split_summary() -> Dict[str, Any]:
    gt_path = _BASE_DIR / "data/expanded_ground_truth.json"
    if not gt_path.exists():
        return {
            "status": "missing",
            "source": None,
            "split_mode": "unified_json_split_field",
            "total_cases": 0,
            "train_count": 0,
            "test_count": 0,
            "split_ratio": None,
            "test_affirmative_cases": 0,
            "test_negated_cases": 0,
            "missing_split_count": 0,
            "missing_split_examples": [],
            "dataset_updated_at": None,
            "generated_at": None,
            "metadata_version": None,
            "source_note": "ไม่พบ expanded_ground_truth.json",
        }

    try:
        payload = json.loads(gt_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read %s: %s", gt_path, exc)
        return {
            "status": "degraded",
            "source": str(gt_path),
            "split_mode": "unified_json_split_field",
            "total_cases": 0,
            "train_count": 0,
            "test_count": 0,
            "split_ratio": None,
            "test_affirmative_cases": 0,
            "test_negated_cases": 0,
            "missing_split_count": 0,
            "missing_split_examples": [],
            "dataset_updated_at": None,
            "generated_at": None,
            "metadata_version": None,
            "source_note": f"อ่าน expanded_ground_truth.json ไม่สำเร็จ: {exc}",
        }

    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    cases = payload.get("cases", []) if isinstance(payload, dict) else []
    train_cases = [case for case in cases if case.get("split") == "train"]
    test_cases = [case for case in cases if case.get("split") == "test"]
    missing_split = [case.get("case_id", "unknown") for case in cases if "split" not in case]
    negated_cases = [
        case for case in test_cases
        if bool(case.get("is_negated", case.get("has_negation", False)))
    ]
    dataset_updated_at = (
        metadata.get("last_updated")
        or metadata.get("generated_at")
        or datetime.fromtimestamp(gt_path.stat().st_mtime, tz=timezone.utc).isoformat()
    )
    total_cases = len(cases)
    return {
        "status": "ready" if not missing_split else "degraded",
        "source": str(gt_path),
        "split_mode": "unified_json_split_field",
        "total_cases": total_cases,
        "train_count": len(train_cases),
        "test_count": len(test_cases),
        "split_ratio": metadata.get("split_ratio") or (
            f"{len(train_cases)}/{len(test_cases)}" if total_cases else None
        ),
        "test_affirmative_cases": len(test_cases) - len(negated_cases),
        "test_negated_cases": len(negated_cases),
        "missing_split_count": len(missing_split),
        "missing_split_examples": missing_split[:10],
        "dataset_updated_at": dataset_updated_at,
        "generated_at": metadata.get("generated_at"),
        "metadata_version": metadata.get("version"),
        "source_note": "เก็บ ground truth ไว้ในไฟล์เดียวและแยก train/test ด้วย field split",
    }


def _paired_proper_raw(proper_path: Optional[Path]) -> tuple[Path | None, Dict]:
    if proper_path:
        raw_name = proper_path.name
        if "proper_eval_summary_" in raw_name:
            raw_name = raw_name.replace("proper_eval_summary_", "proper_eval_raw_")
        elif "proper_eval_latest_summary" in raw_name:
            raw_name = raw_name.replace("proper_eval_latest_summary", "proper_eval_latest_raw")
        elif "proper_eval_checkpoint_summary" in raw_name:
            raw_name = raw_name.replace("proper_eval_checkpoint_summary", "proper_eval_checkpoint_raw")
        raw_path = proper_path.with_name(raw_name)
        if raw_path.exists():
            try:
                return raw_path, json.loads(raw_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed to read %s: %s", raw_path, exc)
                return raw_path, {}
    return _latest_json("evaluation_results/proper_eval_raw_*.json")


def _paired_proper_cases(proper_path: Optional[Path]) -> tuple[Path | None, Dict]:
    if proper_path:
        cases_name = proper_path.name
        if "proper_eval_summary_" in cases_name:
            cases_name = cases_name.replace("proper_eval_summary_", "proper_eval_cases_")
        elif "proper_eval_latest_summary" in cases_name:
            cases_name = cases_name.replace("proper_eval_latest_summary", "proper_eval_latest_cases")
        elif "proper_eval_checkpoint_summary" in cases_name:
            cases_name = cases_name.replace("proper_eval_checkpoint_summary", "proper_eval_checkpoint_cases")
        cases_path = proper_path.with_name(cases_name)
        if cases_path.exists():
            try:
                return cases_path, json.loads(cases_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed to read %s: %s", cases_path, exc)
                return cases_path, {}
    return _latest_json("evaluation_results/proper_eval_cases_*.json")


def _safe_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, bool)) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            return str(value)
    return value if isinstance(value, (str, int, float, bool)) else str(value)


def _normalize_doc_top_k(value: Any) -> int:
    """Normalize requested top_k to valid integer range [1, 50]."""
    try:
        requested = int(value)
    except (TypeError, ValueError):
        requested = DEFAULT_DOC_TOP_K
    return max(1, min(50, requested))


def _file_sha256(file_path: Any) -> Optional[str]:
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _artifact_input_status(
    metadata: Dict[str, Any],
    current_taxonomy_sha256: Optional[str],
    current_ground_truth_sha256: Optional[str],
) -> Dict[str, Any]:
    artifact_taxonomy_sha256 = metadata.get("taxonomy_sha256")
    artifact_ground_truth_sha256 = metadata.get("ground_truth_sha256")
    taxonomy_hash_present = bool(artifact_taxonomy_sha256)
    ground_truth_hash_present = bool(artifact_ground_truth_sha256)
    taxonomy_hash_match = bool(
        taxonomy_hash_present
        and current_taxonomy_sha256
        and artifact_taxonomy_sha256 == current_taxonomy_sha256
    )
    ground_truth_hash_match = bool(
        ground_truth_hash_present
        and current_ground_truth_sha256
        and artifact_ground_truth_sha256 == current_ground_truth_sha256
    )
    return {
        "artifact_taxonomy_sha256": artifact_taxonomy_sha256,
        "artifact_ground_truth_sha256": artifact_ground_truth_sha256,
        "taxonomy_hash_present": taxonomy_hash_present,
        "ground_truth_hash_present": ground_truth_hash_present,
        "taxonomy_hash_match": taxonomy_hash_match,
        "ground_truth_hash_match": ground_truth_hash_match,
        "current": bool(taxonomy_hash_match and ground_truth_hash_match),
    }


def _statistical_artifact_status(
    artifact: Dict[str, Any],
    current_taxonomy_sha256: Optional[str],
    current_ground_truth_sha256: Optional[str],
) -> Dict[str, Any]:
    input_status = _artifact_input_status(
        artifact,
        current_taxonomy_sha256,
        current_ground_truth_sha256,
    )
    source_path_value = artifact.get("source")
    source_path = Path(source_path_value) if source_path_value else None
    reported_source_sha256 = artifact.get("source_sha256")
    actual_source_sha256 = _file_sha256(source_path) if source_path else None
    source_hash_match = bool(
        reported_source_sha256
        and actual_source_sha256
        and reported_source_sha256 == actual_source_sha256
    )
    alternative = str(artifact.get("alternative") or "").lower()
    test_name = str(artifact.get("statistical_test") or "").lower()
    two_sided = alternative == "two-sided" and "wilcoxon" in test_name
    return {
        **input_status,
        "source": source_path_value,
        "reported_source_sha256": reported_source_sha256,
        "actual_source_sha256": actual_source_sha256,
        "source_hash_match": source_hash_match,
        "alternative": alternative or None,
        "two_sided": two_sided,
        "current": bool(input_status["current"] and source_hash_match and two_sided),
    }


def _doc_scaling_guidance(selected_top_k: Optional[int] = None) -> Dict[str, Any]:
    raw_k = _normalize_doc_top_k(selected_top_k or DEFAULT_DOC_TOP_K)
    nearest_option = min(DOC_SCALING_OPTIONS, key=lambda option: abs(option - raw_k))
    return {
        "selected_top_k": raw_k,
        "nearest_scaling_option": nearest_option,
        "options": DOC_SCALING_OPTIONS,
        "recommended_top_k": DEFAULT_DOC_TOP_K,
        "recommended_for_reporting": "top_k=15",
        "interpretation": (
            "top 5 ใช้อ่านความแม่นของหลักฐานชุดแรก, top 15 เหมาะเป็นค่า headline เพราะสมดุล precision/coverage, "
            "top 10 ใช้เป็น sensitivity analysis ระดับกลาง และ top 20 ใช้เฉพาะเมื่อต้องการตรวจ recall เพิ่ม"
        ),
        "metric_policy": {
            "top5": "รายงาน precision/nDCG ของหลักฐานสำคัญที่ผู้วิจัยอ่านก่อน",
            "top10": "ใช้ดูความเสถียรเมื่อย่อ evidence pool ลงจาก headline protocol",
            "top15": "รายงานผลหลักของ retrieval เพราะยังอ่านได้จริงและให้พื้นที่ H2L จัดอันดับเอกสารรองรับมากขึ้น",
            "top20": "ใช้เป็น robustness/recall check ไม่ควรเป็น headline ถ้าผู้ใช้ต้องอ่านผลด้วยตา",
        },
    }


def _latest_statistical_summary() -> Dict[str, Any]:
    path, data = _latest_json("evaluation_results/statistical_analysis_*.json")
    metrics = []
    for key, block in data.items():
        if not isinstance(block, dict) or "descriptive_stats" not in block:
            continue
        stats = block.get("descriptive_stats", {})
        means = stats.get("Mean", {}) if isinstance(stats, dict) else {}
        stds = stats.get("Std", {}) if isinstance(stats, dict) else {}
        counts = stats.get("N", {}) if isinstance(stats, dict) else {}
        rows = []
        for strategy, mean_value in means.items():
            rows.append({
                "strategy": strategy,
                "mean": _safe_number(mean_value),
                "std": _safe_number(stds.get(strategy)),
                "n": counts.get(strategy),
            })
        rows = [row for row in rows if row["mean"] is not None]
        lower_is_better = key.lower() in {"time", "latency", "retrieval_time"}
        best = None
        if rows:
            best = sorted(rows, key=lambda item: item["mean"], reverse=not lower_is_better)[0]
        metrics.append({
            "id": key,
            "metric_name": block.get("metric_name", key),
            "source_function": block.get("source_function") or data.get("source_function"),
            "direction": "lower_is_better" if lower_is_better else "higher_is_better",
            "anova": {
                "f_statistic": _safe_number(block.get("anova", {}).get("f_statistic")),
                "p_value": _safe_number(block.get("anova", {}).get("p_value")),
                "significant": (_safe_number(block.get("anova", {}).get("p_value")) or 1.0) < 0.05,
            },
            "best": best,
            "rows": rows,
            "interpretation": (
                "ค่านี้อ่านเรื่องเวลา ยิ่งต่ำยิ่งเร็ว"
                if lower_is_better
                else "ค่านี้อ่านเรื่องคุณภาพ/ความครอบคลุม ยิ่งสูงยิ่งดี"
            ),
        })
    return {
        "source": str(path) if path else None,
        "source_function": data.get("source_function"),
        "generated_at": data.get("generated_at"),
        "source_artifact": data.get("source"),
        "source_sha256": data.get("source_sha256"),
        "taxonomy_sha256": data.get("taxonomy_sha256"),
        "ground_truth_sha256": data.get("ground_truth_sha256"),
        "statistical_test": data.get("statistical_test"),
        "alternative": data.get("alternative"),
        "multiplicity_correction": data.get("multiplicity_correction"),
        "provenance_status": data.get("provenance_status"),
        "metrics": metrics,
        "note": data.get("note") or "ผลสถิติระดับระบบจาก matrix artifact ที่ตรวจสอบ provenance แล้ว",
    }


def _csv_group_summary(path: Path, group_key: str, metrics: List[str]) -> Dict[str, Any]:
    if not path.exists():
        return {"source": None, "rows": [], "best": None}
    groups: Dict[str, Dict[str, Any]] = {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                group = row.get(group_key)
                if group is None:
                    continue
                bucket = groups.setdefault(group, {"count": 0, "sums": {metric: 0.0 for metric in metrics}})
                bucket["count"] += 1
                for metric in metrics:
                    value = _safe_number(row.get(metric))
                    if value is not None:
                        bucket["sums"][metric] += value
    except Exception as exc:
        logger.warning("Failed to read sensitivity CSV %s: %s", path, exc)
        return {"source": str(path), "rows": [], "best": None, "error": str(exc)}

    rows = []
    for group, bucket in groups.items():
        count = max(bucket["count"], 1)
        item = {group_key: group, "count": bucket["count"]}
        for metric in metrics:
            item[metric] = bucket["sums"][metric] / count
        rows.append(item)
    rows.sort(key=lambda item: str(item.get(group_key)))
    best = sorted(rows, key=lambda item: item.get("map", item.get("ndcg_at_k", 0)), reverse=True)[0] if rows else None
    return {"source": str(path), "rows": rows, "best": best}


def _compact_proper_run(path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
    aggregates = data.get("aggregates", {}) if isinstance(data, dict) else {}

    def metric(strategy: str, key: str) -> Optional[float]:
        block = aggregates.get(strategy, {}).get(key, {}) if isinstance(aggregates.get(strategy), dict) else {}
        return _safe_number(block.get("mean")) if isinstance(block, dict) else None

    strategies = metadata.get("strategies", [])
    rows = []
    for strategy in strategies:
        row_data = {
            "strategy": strategy,
            "group": "H2L-enhanced" if strategy.startswith("h2l-") else "Baseline",
            "MAP": metric(strategy, "MAP"),
            "MRR": metric(strategy, "MRR"),
            "retrieval_time": metric(strategy, "retrieval_time"),
        }
        for k in [1, 3, 5, 10, 15]:
            row_data[f"nDCG@{k}"] = metric(strategy, f"nDCG@{k}")
            row_data[f"P@{k}"] = metric(strategy, f"P@{k}")
            row_data[f"R@{k}"] = metric(strategy, f"R@{k}")
            row_data[f"F1@{k}"] = metric(strategy, f"F1@{k}")
        rows.append(row_data)

    delta = {}
    if "basic" in aggregates and "h2l-hybrid" in aggregates:
        keys_to_delta = ["MAP", "MRR", "retrieval_time"] + [
            f"{m}@{k}" for m in ["nDCG", "P", "R", "F1"] for k in [1, 3, 5, 10, 15]
        ]
        for key in keys_to_delta:
            base = metric("basic", key)
            h2l = metric("h2l-hybrid", key)
            delta[key] = h2l - base if base is not None and h2l is not None else None

    raw_path, _ = _paired_proper_raw(path)
    cases_path, _ = _paired_proper_cases(path)
    return {
        "source": str(path),
        "raw_source": str(raw_path) if raw_path else None,
        "cases_source": str(cases_path) if cases_path else None,
        "timestamp": metadata.get("timestamp"),
        "problem_source": metadata.get("problem_source", "legacy"),
        "num_cases": metadata.get("num_cases"),
        "top_k": metadata.get("top_k"),
        "strategies": strategies,
        "rows": rows,
        "delta_h2l_minus_basic": delta,
        "experiment_diagnostics": data.get("experiment_diagnostics", {}) if isinstance(data, dict) else {},
    }


def _detector_gap_from_cases(summary_path: Path, strategy: str = "h2l-hybrid") -> Dict[str, Any]:
    cases_path, cases_data = _paired_proper_cases(summary_path)
    per_strategy = cases_data.get("per_strategy", {}) if isinstance(cases_data, dict) else {}
    rows = per_strategy.get(strategy) or []
    total = 0
    exact = 0
    total_jaccard = 0.0
    missing_counts: Dict[str, int] = {}
    extra_counts: Dict[str, int] = {}
    examples: List[Dict[str, Any]] = []

    for row in rows:
        expected = {str(code) for code in row.get("expected_codes", []) if code}
        metrics = row.get("metrics", {}) if isinstance(row, dict) else {}
        detected = {str(code) for code in metrics.get("detected_codes", []) if code}
        if not expected and not detected:
            continue

        total += 1
        missing = sorted(expected - detected)
        extra = sorted(detected - expected)
        union = expected | detected
        overlap = expected & detected
        total_jaccard += len(overlap) / len(union) if union else 1.0
        if not missing and not extra:
            exact += 1

        for code in missing:
            missing_counts[code] = missing_counts.get(code, 0) + 1
        for code in extra:
            extra_counts[code] = extra_counts.get(code, 0) + 1

        if (missing or extra) and len(examples) < 6:
            examples.append({
                "case_id": row.get("case_id"),
                "category": row.get("category"),
                "complexity": row.get("complexity"),
                "expected": sorted(expected),
                "detected": sorted(detected),
                "missing": missing,
                "extra": extra,
            })

    top_missing = sorted(missing_counts.items(), key=lambda item: item[1], reverse=True)[:8]
    top_extra = sorted(extra_counts.items(), key=lambda item: item[1], reverse=True)[:8]
    return {
        "source": str(cases_path) if cases_path else None,
        "strategy": strategy,
        "cases": total,
        "exact_match_rate": exact / total if total else None,
        "avg_jaccard": total_jaccard / total if total else None,
        "top_missing_codes": [{"code": code, "count": count} for code, count in top_missing],
        "top_extra_codes": [{"code": code, "count": count} for code, count in top_extra],
        "examples": examples,
        "interpretation": (
            "ถ้า gold run ดีขึ้นแต่ detected run ไม่ดีขึ้น จุดอ่อนมักอยู่ที่ detector ส่ง problem ไม่ครบหรือเกิน; "
            "ดู missing/extra codes เพื่อปรับ ontology หรือ clause logic ก่อนสรุปว่า H2L scoring แพ้"
        ),
    }


def _latest_proper_runs_by_problem_source() -> Dict[str, Dict[str, Any]]:
    runs: Dict[str, Dict[str, Any]] = {}
    for path in _proper_summary_candidate_paths():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            continue
        metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
        problem_source = metadata.get("problem_source", "legacy")
        runs[str(problem_source)] = _compact_proper_run(path, data)
    return runs


def _proper_summary_candidates() -> List[Tuple[Path, Dict[str, Any]]]:
    candidates = []
    for path in _proper_summary_candidate_paths():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            continue
        candidates.append((path, data))
    return candidates


def _preferred_proper_summary() -> tuple[Path | None, Dict]:
    candidates = _proper_summary_candidates()
    if not candidates:
        return None, {}

    def metadata_of(item: Tuple[Path, Dict[str, Any]]) -> Dict[str, Any]:
        data = item[1]
        return data.get("metadata", {}) if isinstance(data, dict) else {}

    preferred_order = [
        ("detected", DEFAULT_DOC_TOP_K),
        ("gold", DEFAULT_DOC_TOP_K),
        ("detected", None),
        ("gold", None),
    ]
    for problem_source, top_k in preferred_order:
        matches = []
        for item in candidates:
            metadata = metadata_of(item)
            if str(metadata.get("problem_source", "legacy")) != problem_source:
                continue
            if top_k is not None:
                try:
                    item_top_k = int(metadata.get("top_k") or -1)
                except (TypeError, ValueError):
                    item_top_k = -1
                if item_top_k != top_k:
                    continue
            matches.append(item)
        if matches:
            return matches[-1]
    return candidates[-1]


def _proper_doc_scaling_runs() -> Dict[str, Any]:
    newest_by_key: Dict[Tuple[str, int], Dict[str, Any]] = {}
    all_runs: List[Dict[str, Any]] = []

    for path in _proper_summary_candidate_paths():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            continue
        metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
        problem_source = str(metadata.get("problem_source", "legacy"))
        if problem_source not in {"detected", "gold"}:
            continue
        top_k_raw = metadata.get("top_k")
        try:
            top_k = int(top_k_raw)
        except (TypeError, ValueError):
            continue
        strategies = set(metadata.get("strategies") or [])
        if not {"basic", "h2l-hybrid"}.issubset(strategies):
            continue

        run = _compact_proper_run(path, data)
        run["artifact_time"] = path.name.replace("proper_eval_summary_", "").replace(".json", "")
        run["reporting_role"] = (
            "headline" if top_k == DEFAULT_DOC_TOP_K else
            "precision_first_read" if top_k == 5 else
            "sensitivity" if top_k == 15 else
            "recall_robustness" if top_k == 20 else
            "supporting"
        )
        if problem_source == "detected":
            run["detector_gap"] = _detector_gap_from_cases(path)

        all_runs.append(run)
        newest_by_key[(problem_source, top_k)] = run

    newest_runs = sorted(
        newest_by_key.values(),
        key=lambda item: (str(item.get("problem_source")), int(item.get("top_k") or 0)),
    )
    by_problem_source: Dict[str, List[Dict[str, Any]]] = {}
    for run in newest_runs:
        by_problem_source.setdefault(str(run.get("problem_source")), []).append(run)

    available_top_k = sorted({int(run["top_k"]) for run in newest_runs if run.get("top_k") is not None})
    missing_top_k = [top_k for top_k in DOC_SCALING_OPTIONS if top_k not in available_top_k]
    missing_by_problem_source = {}
    for problem_source in ["detected", "gold"]:
        source_top_k = {
            int(run["top_k"])
            for run in by_problem_source.get(problem_source, [])
            if run.get("top_k") is not None
        }
        missing_by_problem_source[problem_source] = [top_k for top_k in DOC_SCALING_OPTIONS if top_k not in source_top_k]
    return {
        **_doc_scaling_guidance(DEFAULT_DOC_TOP_K),
        "available_top_k": available_top_k,
        "missing_top_k": missing_top_k,
        "missing_by_problem_source": missing_by_problem_source,
        "runs": newest_runs,
        "by_problem_source": by_problem_source,
        "source_count": len(newest_runs),
        "note": "ตารางนี้อ่านจาก proper_eval_summary/proper_eval_cases artifacts จริงเท่านั้น; top_k ที่ยังไม่มี artifact จะถูกแจ้งเป็น missing ไม่เติมค่าจำลอง",
    }


def _sensitivity_summary() -> Dict[str, Any]:
    metric_names = ["precision_at_k", "recall_at_k", "f1_at_k", "ndcg_at_k", "map", "mrr"]
    alpha = _csv_group_summary(Path("ablation_results/rq2_α_parameter_sensitivity.csv"), "alpha", metric_names)
    l2 = _csv_group_summary(Path("ablation_results/rq1_l2_filtering_impact.csv"), "variant", metric_names)
    matching = _csv_group_summary(Path("ablation_results/rq3_soft_vs_hard_matching.csv"), "variant", metric_names)
    prior = _csv_group_summary(Path("ablation_results/rq4_prior_calculation_impact.csv"), "variant", metric_names)
    return {
        "alpha": {
            **alpha,
            "title": "Alpha Sensitivity",
            "source_function": "ablation_study.py::AlphaSensitivityExperiment",
            "meaning": "alpha คือระดับน้ำหนักที่ให้ problem-aware H2L scoring เทียบกับ retrieval score เดิม",
            "interpretation": "ดูว่าเมื่อเพิ่มน้ำหนัก H2L แล้ว MAP/nDCG เปลี่ยนอย่างไร เพื่อเลือกค่าที่ไม่ overfit; อ่านร่วมกับจำนวนเคสใน artifact",
        },
        "l2_filtering": {
            **l2,
            "title": "L2 Filtering Impact",
            "source_function": "ablation_study.py::L2FilteringImpactExperiment",
            "meaning": "เทียบ Full L1+L2 กับ L1 only เพื่อดูว่า semantic validation ช่วยกรอง candidate หรือไม่",
        },
        "matching_method": {
            **matching,
            "title": "Semantic Soft vs Keyword Hard Matching",
            "source_function": "ablation_study.py::SoftVsHardMatchingExperiment",
            "meaning": "เทียบการจับคู่แบบ embedding/semantic กับ keyword exact match",
        },
        "prior": {
            **prior,
            "title": "Severity Prior Impact",
            "source_function": "ablation_study.py::PriorCalculationImpactExperiment",
            "meaning": "เทียบ prior ตามความรุนแรงกับ uniform prior เพื่อดูผลต่อ ranking",
        },
    }


def _pair_case_diagnostics(raw: Dict[str, Any], base_name: str, h2l_name: str) -> Dict[str, Any]:
    metrics = ["MAP", "MRR", "nDCG@5"]
    metric_rows = []
    for metric in metrics:
        base_values = raw.get(base_name, {}).get(metric, []) if isinstance(raw.get(base_name), dict) else []
        h2l_values = raw.get(h2l_name, {}).get(metric, []) if isinstance(raw.get(h2l_name), dict) else []
        paired_values = []
        for base_value, h2l_value in zip(base_values, h2l_values):
            base_num = _safe_number(base_value)
            h2l_num = _safe_number(h2l_value)
            if base_num is None or h2l_num is None:
                continue
            paired_values.append((base_num, h2l_num))

        h2l_wins = sum(1 for base_num, h2l_num in paired_values if h2l_num > base_num + 1e-12)
        baseline_wins = sum(1 for base_num, h2l_num in paired_values if base_num > h2l_num + 1e-12)
        ties = len(paired_values) - h2l_wins - baseline_wins
        delta_mean = (
            sum(h2l_num - base_num for base_num, h2l_num in paired_values) / len(paired_values)
            if paired_values else None
        )
        metric_rows.append({
            "metric": metric,
            "n": len(paired_values),
            "h2l_wins": h2l_wins,
            "baseline_wins": baseline_wins,
            "ties": ties,
            "delta_mean": delta_mean,
        })

    h2l_metric_wins = sum(1 for row in metric_rows if (row.get("delta_mean") or 0) > 1e-12)
    baseline_metric_wins = sum(1 for row in metric_rows if (row.get("delta_mean") or 0) < -1e-12)
    ties_by_mean = len(metric_rows) - h2l_metric_wins - baseline_metric_wins
    total_h2l_case_wins = sum(row["h2l_wins"] for row in metric_rows)
    total_baseline_case_wins = sum(row["baseline_wins"] for row in metric_rows)
    total_ties = sum(row["ties"] for row in metric_rows)

    if h2l_metric_wins > baseline_metric_wins:
        takeaway = "H2L เด่นในคุณภาพ ranking ของคู่นี้ แต่ควรอ่านร่วมกับจำนวนเคสที่เสมอและเวลาเพิ่มขึ้น"
    elif baseline_metric_wins > h2l_metric_wins:
        takeaway = "Baseline ยังเด่นกว่าในคุณภาพ ranking ของคู่นี้ ควรทำ error analysis ว่า H2L ดันเอกสารผิดหรือ detector ส่ง problem ไม่ตรง"
    else:
        takeaway = "ผลคุณภาพใกล้เคียงกัน ควรใช้ paired significance หรือ bootstrap CI ก่อนสรุปว่าฝ่ายใดชนะ"

    return {
        "metrics": metric_rows,
        "quality_metric_wins": {
            "h2l": h2l_metric_wins,
            "baseline": baseline_metric_wins,
            "tie": ties_by_mean,
        },
        "case_votes": {
            "h2l": total_h2l_case_wins,
            "baseline": total_baseline_case_wins,
            "tie": total_ties,
        },
        "takeaway": takeaway,
    }


def _mean_metric(metrics: Dict[str, Any], key: str) -> float | None:
    value = metrics.get(key, {}) if isinstance(metrics, dict) else {}
    if isinstance(value, dict):
        return _safe_number(value.get("mean"))
    return None


def _comparison_pairs_from_results(results: Dict[str, Any], raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    aggregates = results.get("aggregates", {}) if isinstance(results, dict) else {}
    pairs = []
    for pair in STRATEGY_PAIRS:
        base_name = pair["baseline"]
        h2l_name = pair["enhanced"]
        base = aggregates.get(base_name, {})
        h2l = aggregates.get(h2l_name, {})
        base_quality = _mean_metric(base, "MAP")
        h2l_quality = _mean_metric(h2l, "MAP")
        base_time = _mean_metric(base, "retrieval_time")
        h2l_time = _mean_metric(h2l, "retrieval_time")
        quality_delta = h2l_quality - base_quality if base_quality is not None and h2l_quality is not None else None
        time_delta = h2l_time - base_time if base_time is not None and h2l_time is not None else None
        pair_dict = {
            "family": pair["family"],
            "label": pair["label"],
            "base_strategy": base_name,
            "h2l_strategy": h2l_name,
            "base_quality": base_quality,
            "h2l_quality": h2l_quality,
            "quality_delta": quality_delta,
            "base_time": base_time,
            "h2l_time": h2l_time,
            "time_delta": time_delta,
            "base_mrr": _mean_metric(base, "MRR"),
            "h2l_mrr": _mean_metric(h2l, "MRR"),
        }
        for k in [1, 3, 5, 10, 15]:
            pair_dict[f"base_ndcg_at_{k}"] = _mean_metric(base, f"nDCG@{k}")
            pair_dict[f"h2l_ndcg_at_{k}"] = _mean_metric(h2l, f"nDCG@{k}")
            pair_dict[f"base_p_at_{k}"] = _mean_metric(base, f"P@{k}")
            pair_dict[f"h2l_p_at_{k}"] = _mean_metric(h2l, f"P@{k}")
            pair_dict[f"base_r_at_{k}"] = _mean_metric(base, f"R@{k}")
            pair_dict[f"h2l_r_at_{k}"] = _mean_metric(h2l, f"R@{k}")
            pair_dict[f"base_f1_at_{k}"] = _mean_metric(base, f"F1@{k}")
            pair_dict[f"h2l_f1_at_{k}"] = _mean_metric(h2l, f"F1@{k}")

        pair_dict.update({
            "base_queries": base.get("MAP", {}).get("n") if isinstance(base.get("MAP"), dict) else None,
            "h2l_queries": h2l.get("MAP", {}).get("n") if isinstance(h2l.get("MAP"), dict) else None,
            "case_diagnostics": _pair_case_diagnostics(raw, base_name, h2l_name),
            "limitation_coverage": BASELINE_LIMITATION_GUIDE.get(pair["family"], {}),
            "interpretation": _strategy_delta_interpretation(base_name, quality_delta, time_delta),
        })
        pairs.append(pair_dict)
    return pairs


def _pairwise_test_block(results: Dict[str, Any], metric: str, base_name: str, h2l_name: str) -> Dict[str, Any]:
    tests = results.get("statistical_tests", {}) if isinstance(results, dict) else {}
    pairwise = tests.get(metric, {}).get("pairwise", {}) if isinstance(tests.get(metric), dict) else {}
    direct_key = f"{base_name}_vs_{h2l_name}"
    reverse_key = f"{h2l_name}_vs_{base_name}"
    block = pairwise.get(direct_key) or pairwise.get(reverse_key) or {}
    significant = block.get("significant")
    if isinstance(significant, str):
        significant = significant.strip().lower() == "true"
    return {
        "metric": metric,
        "test": block.get("test"),
        "statistic": _safe_number(block.get("statistic")),
        "p_value": _safe_number(block.get("p_value")),
        "significant": bool(significant) if significant is not None else False,
        "effect_size": _safe_number(block.get("cohens_d")),
        "effect_interpretation": block.get("effect_interpretation"),
        "mean_diff": _safe_number(block.get("mean_diff")),
    }


def _isolated_pair_runs_reference(problem_source: str = "detected", top_k: int = DEFAULT_DOC_TOP_K) -> Dict[str, Any]:
    root = Path("evaluation_results") / "pairs"
    runs: List[Dict[str, Any]] = []
    rows_by_strategy: Dict[str, Dict[str, Any]] = {}
    comparison_pairs: List[Dict[str, Any]] = []
    latest_timestamp: Optional[datetime] = None

    for pair in STRATEGY_PAIRS:
        folder = root / f"{pair['family']}_{problem_source}_top{top_k}"
        summary_path = folder / "proper_eval_latest_summary.json"
        raw_path = folder / "proper_eval_latest_raw.json"
        cases_path = folder / "proper_eval_latest_cases.json"
        if not summary_path.exists():
            runs.append({
                "family": pair["family"],
                "label": pair["label"],
                "baseline": pair["baseline"],
                "enhanced": pair["enhanced"],
                "status": "missing",
                "source": None,
                "raw_source": None,
                "cases_source": None,
                "timestamp": None,
                "problem_source": problem_source,
                "top_k": top_k,
                "rows": [],
                "comparison_pair": None,
                "paired_test": {},
            })
            continue
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read pair artifact %s: %s", summary_path, exc)
            runs.append({
                "family": pair["family"],
                "label": pair["label"],
                "baseline": pair["baseline"],
                "enhanced": pair["enhanced"],
                "status": "error",
                "source": str(summary_path),
                "raw_source": str(raw_path) if raw_path.exists() else None,
                "cases_source": str(cases_path) if cases_path.exists() else None,
                "timestamp": None,
                "problem_source": problem_source,
                "top_k": top_k,
                "rows": [],
                "comparison_pair": None,
                "paired_test": {},
                "error": str(exc),
            })
            continue

        raw: Dict[str, Any] = {}
        if raw_path.exists():
            try:
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed to read pair raw artifact %s: %s", raw_path, exc)
                raw = {}

        compact = _compact_proper_run(summary_path, data)
        comparison_pair = next(
            (
                item for item in _comparison_pairs_from_results(data, raw)
                if item.get("family") == pair["family"]
            ),
            None,
        )
        paired_test = _pairwise_test_block(data, "nDCG@5", pair["baseline"], pair["enhanced"])
        map_test = _pairwise_test_block(data, "MAP", pair["baseline"], pair["enhanced"])
        timestamp_text = compact.get("timestamp")
        timestamp_dt = _parse_iso_datetime(timestamp_text)
        if timestamp_dt and (latest_timestamp is None or timestamp_dt > latest_timestamp):
            latest_timestamp = timestamp_dt

        for row in compact.get("rows", []):
            rows_by_strategy[row["strategy"]] = row
        if comparison_pair and (
            comparison_pair.get("base_quality") is not None or comparison_pair.get("h2l_quality") is not None
        ):
            comparison_pairs.append(comparison_pair)

        runs.append({
            "family": pair["family"],
            "label": pair["label"],
            "baseline": pair["baseline"],
            "enhanced": pair["enhanced"],
            "status": "ready",
            "source": str(summary_path),
            "raw_source": str(raw_path) if raw_path.exists() else None,
            "cases_source": str(cases_path) if cases_path.exists() else None,
            "timestamp": timestamp_text,
            "problem_source": compact.get("problem_source", problem_source),
            "top_k": compact.get("top_k", top_k),
            "rows": compact.get("rows", []),
            "comparison_pair": comparison_pair,
            "paired_test": paired_test,
            "map_test": map_test,
            "num_cases": compact.get("num_cases"),
            "experiment_diagnostics": compact.get("experiment_diagnostics", {}),
        })

    ready_runs = [run for run in runs if run.get("status") == "ready"]
    return {
        "source_root": str(root),
        "status": "ready" if len(ready_runs) == len(STRATEGY_PAIRS) else "partial" if ready_runs else "missing",
        "problem_source": problem_source,
        "top_k": top_k,
        "expected_count": len(STRATEGY_PAIRS),
        "ready_count": len(ready_runs),
        "latest_timestamp": latest_timestamp.isoformat() if latest_timestamp else None,
        "runs": runs,
        "rows": list(rows_by_strategy.values()),
        "comparison_pairs": comparison_pairs,
        "interpretation": (
            "pair artifacts ชุดย่อยครบทุก family และอ่านจากไฟล์ latest ใน evaluation_results/pairs โดยตรง"
            if len(ready_runs) == len(STRATEGY_PAIRS)
            else "pair artifacts พร้อมบาง family; UI ควรระบุชัดว่าผลที่เห็นมาจากคู่ใดบ้าง"
            if ready_runs else
            "ยังไม่มี pair artifacts ที่พร้อมใช้"
        ),
    }


def _latest_full_strategy_reference() -> Dict[str, Any]:
    selected_path: Optional[Path] = None
    selected_data: Dict[str, Any] = {}
    for path, data in _proper_summary_candidates():
        metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
        strategies = set(metadata.get("strategies") or [])
        if VALID_STRATEGIES.issubset(strategies):
            selected_path = path
            selected_data = data

    if not selected_path:
        return {
            "source": None,
            "status": "missing",
            "comparison_pairs": [],
            "interpretation": "ยังไม่มี artifact ที่รันครบ baseline 4 ตัวและ H2L คู่กันทั้ง 4 family",
        }

    raw_path, raw = _paired_proper_raw(selected_path)
    metadata = selected_data.get("metadata", {}) if isinstance(selected_data, dict) else {}
    compact = _compact_proper_run(selected_path, selected_data)
    problem_source = metadata.get("problem_source", "legacy")
    top_k = metadata.get("top_k")
    try:
        top_k_number = int(top_k or -1)
    except (TypeError, ValueError):
        top_k_number = -1
    status = "ready" if problem_source in {"detected", "gold"} and top_k_number == DEFAULT_DOC_TOP_K else "preliminary"
    role = (
        "final_candidate" if status == "ready" and problem_source == "detected"
        else "upper_bound" if status == "ready" and problem_source == "gold"
        else "reference_only"
    )
    return {
        "source": str(selected_path),
        "raw_source": str(raw_path) if raw_path else None,
        "status": status,
        "role": role,
        "problem_source": problem_source,
        "top_k": top_k,
        "num_cases": metadata.get("num_cases"),
        "strategies": metadata.get("strategies", []),
        "rows": compact.get("rows", []),
        "comparison_pairs": _comparison_pairs_from_results(selected_data, raw),
        "interpretation": (
            "artifact นี้ใช้เทียบครบ 4 baseline family ได้ แต่ยังเป็น reference เท่านั้นถ้า problem_source เป็น legacy หรือ top_k ไม่ตรงค่า headline"
            if status == "preliminary"
            else "artifact นี้พร้อมใช้เป็นผลเทียบ baseline family ตาม protocol ปัจจุบัน"
        ),
    }


def _thesis_protocol_summary(
    proper_metadata: Dict[str, Any],
    doc_scaling: Dict[str, Any],
    polarity: Dict[str, Any],
    full_reference: Dict[str, Any],
    isolated_pair_runs: Dict[str, Any],
) -> Dict[str, Any]:
    doc_by_source = doc_scaling.get("by_problem_source", {}) if isinstance(doc_scaling, dict) else {}
    detected_top = {int(run.get("top_k")) for run in doc_by_source.get("detected", []) if run.get("top_k") is not None}
    gold_top = {int(run.get("top_k")) for run in doc_by_source.get("gold", []) if run.get("top_k") is not None}
    detected_ready = set(DOC_SCALING_OPTIONS).issubset(detected_top)
    gold_ready = set(DOC_SCALING_OPTIONS).issubset(gold_top)
    full_pairs_ready = full_reference.get("status") == "ready"
    full_pairs_prelim = bool(full_reference.get("source"))
    isolated_pairs_ready = isolated_pair_runs.get("status") == "ready"
    isolated_ready_families = {
        run.get("family")
        for run in isolated_pair_runs.get("runs", [])
        if run.get("status") == "ready"
    }
    polarity_ready = bool(polarity.get("overall", {}).get("total_cases"))
    current_problem_source = proper_metadata.get("problem_source", "legacy")

    readiness_items = [
        {
            "id": "real_runtime_case",
            "label": "เคสปัจจุบันใช้ runtime จริง",
            "status": "ready",
            "meaning": "ผล /analyze มาจาก detector + retriever จริง และไม่มี sample/mock fallback",
        },
        {
            "id": "detected_doc_scaling",
            "label": "Detected top-k scaling",
            "status": "ready" if detected_ready else "partial",
            "meaning": f"มี detected artifacts top {sorted(detected_top) or 'N/A'}; ใช้เป็นผลหลักของระบบจริง",
        },
        {
            "id": "gold_upper_bound",
            "label": "Gold upper-bound",
            "status": "ready" if gold_ready else "partial",
            "meaning": f"มี gold artifacts top {sorted(gold_top) or 'N/A'}; ใช้เป็นเพดานบน ไม่ปนกับผลหลัก",
        },
        {
            "id": "four_baseline_matrix",
            "label": "4-baseline paired matrix",
            "status": "ready" if full_pairs_ready else "partial" if full_pairs_prelim else "missing",
            "meaning": full_reference.get("interpretation"),
        },
        {
            "id": "isolated_pair_reruns",
            "label": "Isolated pair reruns",
            "status": "ready" if isolated_pairs_ready else "partial" if isolated_ready_families else "missing",
            "meaning": isolated_pair_runs.get("interpretation"),
        },
        {
            "id": "sentence_polarity_eval",
            "label": "Sentence polarity evaluation",
            "status": "ready" if polarity_ready else "missing",
            "meaning": f"มี {polarity.get('overall', {}).get('total_cases') or 0} polarity cases สำหรับวัด negation/false positive",
        },
    ]
    blockers = [item for item in readiness_items if item["status"] in {"missing"}]
    warnings = [item for item in readiness_items if item["status"] == "partial"]

    capacity_checks = [
        {
            "strategy": "BM25",
            "status": "ready" if "bm25" in isolated_ready_families or full_pairs_prelim else "needs_run",
            "meaning": "รัน lexical retrieval แบบไม่ใช้ H2L; เหมาะวัด vocabulary mismatch",
        },
        {
            "strategy": "Dense / Naive RAG",
            "status": "ready" if "dense" in isolated_ready_families or full_pairs_prelim else "needs_run",
            "meaning": "รัน embedding retrieval แบบไม่ใช้ H2L; เหมาะวัด semantic overmatch",
        },
        {
            "strategy": "HyDE",
            "status": "ready" if "hyde" in isolated_ready_families else "needs_verification" if full_pairs_prelim else "needs_run",
            "meaning": "ต้องยืนยัน Ollama/LLM พร้อมและรายงาน fallback rate ก่อนอ้างว่า HyDE ใช้ศักยภาพเต็ม; pair rerun ล่าสุดช่วยยืนยันส่วนนี้ได้ตรงกว่า",
        },
        {
            "strategy": "Hybrid",
            "status": "ready" if "hybrid" in isolated_ready_families or doc_scaling.get("source_count") else "needs_run",
            "meaning": "มี basic vs h2l-hybrid ใน doc scaling; ใช้เป็นคู่หลักของระบบจริง",
        },
        {
            "strategy": "H2L Formula",
            "status": "ready",
            "meaning": "ใช้ alpha_eff, severity entropy, KL penalty และ sentence polarity ใน H2L scoring trace; ablation ใช้พิสูจน์ contribution",
        },
    ]

    return {
        "status": "ready" if not blockers and not warnings and full_pairs_ready else "partial" if not blockers else "needs_work",
        "headline_rule": "ใช้ detected + top_k=15 เป็นผลหลัก, top 5/10/20 เป็น sensitivity, gold เป็น upper-bound",
        "current_artifact_role": (
            "main_detected_result" if current_problem_source == "detected"
            else "upper_bound_result" if current_problem_source == "gold"
            else "legacy_reference"
        ),
        "readiness_items": readiness_items,
        "blockers": blockers,
        "warnings": warnings,
        "capacity_checks": capacity_checks,
        "metric_policy": METRIC_POLICY,
        "baseline_limitations": [
            {"family": family, **guide}
            for family, guide in BASELINE_LIMITATION_GUIDE.items()
        ],
        "final_experiment_commands": {
            "primary_detected_top15": (
                "python eval/evaluate_h2l_proper.py --ground-truth data/expanded_ground_truth.json "
                "--strategies bm25_only naive_rag hyde basic h2l-bm25 h2l-naive_rag h2l-hyde "
                "h2l-hybrid --problem-source detected --top-k 15 --include-polarity"
            ),
            "sensitivity_detected": (
                "python eval/evaluate_h2l_proper.py --ground-truth data/expanded_ground_truth.json "
                "--strategies bm25_only naive_rag hyde basic h2l-bm25 h2l-naive_rag h2l-hyde "
                "h2l-hybrid --problem-source detected --top-k-list 5 10 15 20"
            ),
            "gold_upper_bound": (
                "python eval/evaluate_h2l_proper.py --ground-truth data/expanded_ground_truth.json "
                "--strategies bm25_only naive_rag hyde basic h2l-bm25 h2l-naive_rag h2l-hyde "
                "h2l-hybrid --problem-source gold --top-k-list 5 10 15 20"
            ),
        },
        "interpretation": (
            "ระบบมี artifact จริงสำหรับอ่านผลแล้ว และ isolated pair reruns ช่วยยืนยัน behavior ราย family เพิ่มขึ้น แต่ควรรัน 4-baseline matrix ภายใต้ detected top15/current protocol ก่อนใช้เป็นผลสุดท้าย"
            if not full_pairs_ready else
            "ระบบพร้อมอ่านผลตาม protocol หลัก: detected top15 + sensitivity + gold upper-bound"
        ),
    }


def _evaluation_summary() -> Dict:
    proper_path, proper = _preferred_proper_summary()
    proper_raw_path, proper_raw = _paired_proper_raw(proper_path)
    proper_cases_path, _proper_cases = _paired_proper_cases(proper_path)
    polarity_path, polarity = _latest_json("evaluation_results/sentence_polarity_eval_*.json")
    ground_truth = _ground_truth_split_summary()

    aggregates = proper.get("aggregates", {})
    proper_metadata = proper.get("metadata", {}) if isinstance(proper, dict) else {}
    experiment_diagnostics = proper.get("experiment_diagnostics", {}) if isinstance(proper, dict) else {}
    proper_runs_by_problem_source = _latest_proper_runs_by_problem_source()
    doc_scaling = _proper_doc_scaling_runs()
    preferred = "h2l-hybrid" if "h2l-hybrid" in aggregates else next(iter(aggregates), None)
    preferred_metrics = aggregates.get(preferred, {}) if preferred else {}

    benchmark_rows = []
    for name, metrics in aggregates.items():
        benchmark_rows.append({
            "strategy": name,
            "group": "H2L-enhanced" if name.startswith("h2l-") else "Baseline",
            "map": _mean_metric(metrics, "MAP"),
            "mrr": _mean_metric(metrics, "MRR"),
            "p_at_5": _mean_metric(metrics, "P@5"),
            "r_at_5": _mean_metric(metrics, "R@5"),
            "ndcg_at_5": _mean_metric(metrics, "nDCG@5"),
            "retrieval_time": _mean_metric(metrics, "retrieval_time"),
            "avg_docs_retrieved": _mean_metric(metrics, "total_docs"),
            "cases": metrics.get("MAP", {}).get("n") if isinstance(metrics.get("MAP"), dict) else None,
        })

    comparison_pairs = _comparison_pairs_from_results(proper, proper_raw)
    full_strategy_reference = _latest_full_strategy_reference()
    isolated_pair_runs = _isolated_pair_runs_reference("detected", DEFAULT_DOC_TOP_K)
    statistical = _latest_statistical_summary()
    sensitivity = _sensitivity_summary()
    evaluation_progress = _evaluation_progress_summary()
    artifact_inventory = _artifact_inventory_summary()
    ablation_path = Path("ablation_results/ABLATION_STUDY_REPORT.md")
    ablation_excerpt = ""
    if ablation_path.exists():
        try:
            ablation_excerpt = "\n".join(ablation_path.read_text(encoding="utf-8").splitlines()[0:24])
        except Exception:
            ablation_excerpt = ""
    thesis_protocol = _thesis_protocol_summary(
        proper_metadata,
        doc_scaling,
        polarity,
        full_strategy_reference,
        isolated_pair_runs,
    )
    gt_updated_dt = _parse_iso_datetime(ground_truth.get("dataset_updated_at"))
    proper_dt = _parse_iso_datetime(proper_metadata.get("timestamp"))
    polarity_dt = _parse_iso_datetime(polarity.get("metadata", {}).get("timestamp"))
    benchmark_current_ts = bool(proper_dt and (not gt_updated_dt or proper_dt >= gt_updated_dt))
    polarity_current_ts = bool(polarity_dt and (not gt_updated_dt or polarity_dt >= gt_updated_dt))

    current_tax_hash = _file_sha256("data/problem_codes.json")
    current_gt_hash = _file_sha256("data/expanded_ground_truth.json")
    benchmark_inputs = _artifact_input_status(proper_metadata, current_tax_hash, current_gt_hash)
    polarity_inputs = _artifact_input_status(
        polarity.get("metadata", {}),
        current_tax_hash,
        current_gt_hash,
    )
    statistics_inputs = _statistical_artifact_status(
        {
            "source": statistical.get("source_artifact"),
            "source_sha256": statistical.get("source_sha256"),
            "taxonomy_sha256": statistical.get("taxonomy_sha256"),
            "ground_truth_sha256": statistical.get("ground_truth_sha256"),
            "statistical_test": statistical.get("statistical_test"),
            "alternative": statistical.get("alternative"),
        },
        current_tax_hash,
        current_gt_hash,
    )

    is_benchmark_current = bool(benchmark_current_ts and benchmark_inputs["current"])
    is_polarity_current = bool(polarity_current_ts and polarity_inputs["current"])
    is_statistics_current = bool(statistical.get("source") and statistics_inputs["current"])
    all_artifacts_current = bool(
        is_benchmark_current and is_polarity_current and is_statistics_current
    )
    needs_review = not all_artifacts_current

    freshness = {
        "dataset_updated_at": ground_truth.get("dataset_updated_at"),
        "proper_eval_timestamp": proper_metadata.get("timestamp"),
        "polarity_eval_timestamp": polarity.get("metadata", {}).get("timestamp"),
        "current_taxonomy_sha256": current_tax_hash,
        "current_ground_truth_sha256": current_gt_hash,
        "artifact_taxonomy_sha256": benchmark_inputs["artifact_taxonomy_sha256"],
        "artifact_ground_truth_sha256": benchmark_inputs["artifact_ground_truth_sha256"],
        "taxonomy_hash_match": benchmark_inputs["taxonomy_hash_match"],
        "ground_truth_hash_match": benchmark_inputs["ground_truth_hash_match"],
        "benchmark_hashes_present": bool(
            benchmark_inputs["taxonomy_hash_present"]
            and benchmark_inputs["ground_truth_hash_present"]
        ),
        "benchmark": benchmark_inputs,
        "polarity": polarity_inputs,
        "statistics": statistics_inputs,
        "benchmark_current": is_benchmark_current,
        "polarity_current": is_polarity_current,
        "statistics_current": is_statistics_current,
        "all_artifacts_current": all_artifacts_current,
        "needs_review": needs_review,
        "interpretation": (
            "evaluation, polarity และ statistical artifacts สอดคล้องกับ input และ source artifact รุ่นปัจจุบัน"
            if all_artifacts_current else
            "artifact อย่างน้อยหนึ่งรายการขาด provenance, ใช้ hash คนละรุ่น, หรือไม่ได้ใช้ two-sided Wilcoxon ตาม protocol"
        ),
    }
    review_actions = {
        "refresh_endpoint": "/evaluation-summary",
        "refresh_label": "Reload Performance Snapshot",
        "needs_benchmark_rerun": not is_benchmark_current,
        "needs_polarity_rerun": not is_polarity_current,
        "needs_statistics_rerun": not is_statistics_current,
        "benchmark_command": thesis_protocol.get("final_experiment_commands", {}).get("primary_detected_top15"),
        "polarity_command": "python eval/evaluate_sentence_polarity.py --ground-truth data/expanded_ground_truth.json --taxonomy data/problem_codes.json",
        "statistics_command": "python scripts/build_statistical_analysis.py",
        "note": (
            "กด reload เพื่ออ่าน artifact ล่าสุดจาก disk; hash ที่หายหรือไม่ตรงจะถูกจัดเป็น stale และไม่ผ่าน thesis readiness"
        ),
    }

    return {
        "proper_eval": {
            "source": str(proper_path) if proper_path else None,
            "raw_source": str(proper_raw_path) if proper_raw_path else None,
            "cases_source": str(proper_cases_path) if proper_cases_path else None,
            "source_function": "evaluate_h2l_proper.py::EvaluationRunner.evaluate_all",
            "timestamp": proper_metadata.get("timestamp"),
            "num_cases": proper_metadata.get("num_cases"),
            "problem_source": proper_metadata.get("problem_source", "legacy"),
            "top_k": proper_metadata.get("top_k"),
            "strategies": proper_metadata.get("strategies", []),
            "strategy": preferred,
            "ground_truth_source": ground_truth.get("source"),
            "dataset_updated_at": ground_truth.get("dataset_updated_at"),
            "benchmark_current": is_benchmark_current,
            "map": _mean_metric(preferred_metrics, "MAP"),
            "mrr": _mean_metric(preferred_metrics, "MRR"),
            "p_at_5": _mean_metric(preferred_metrics, "P@5"),
            "r_at_5": _mean_metric(preferred_metrics, "R@5"),
            "ndcg_at_5": _mean_metric(preferred_metrics, "nDCG@5"),
            "metric_guidance": {
                "MAP": "ภาพรวมความแม่นของ ranking ตลอดรายการ ยิ่งสูงยิ่งดี",
                "MRR": "ตำแหน่งของหลักฐานที่เกี่ยวข้องชิ้นแรก ถ้าสูงแปลว่าเจอเร็ว",
                "nDCG@5": "คุณภาพการจัดลำดับ 5 อันดับแรก โดยให้รางวัลกับเอกสารสำคัญที่อยู่บน",
                "P@5": "ใน 5 อันดับแรก มีหลักฐานที่เกี่ยวข้องกี่ส่วน",
                "R@5": "ใน 5 อันดับแรก ครอบคลุมหลักฐานที่ควรเจอได้มากแค่ไหน",
            },
        },
        "polarity_eval": {
            "source": str(polarity_path) if polarity_path else None,
            "source_function": "evaluate_sentence_polarity.py::evaluate_sentence_polarity",
            "timestamp": polarity.get("metadata", {}).get("timestamp"),
            "total_cases": polarity.get("overall", {}).get("total_cases"),
            "ground_truth_source": ground_truth.get("source"),
            "dataset_updated_at": ground_truth.get("dataset_updated_at"),
            "benchmark_current": is_polarity_current,
            "accuracy": polarity.get("overall", {}).get("accuracy"),
            "negation_detection_rate": polarity.get("overall", {}).get("negation_detection_rate"),
            "false_positive_rate": polarity.get("overall", {}).get("false_positive_rate"),
            "f1_score": polarity.get("overall", {}).get("f1_score"),
            "metric_guidance": {
                "accuracy": "สัดส่วนประโยคที่ polarity gate ตัดสินถูกโดยรวม",
                "f1_score": "สมดุลระหว่างการจับประโยคเสี่ยงให้เจอและไม่แจ้งเกิน",
                "negation_detection_rate": "ความสามารถในการรู้ว่าประโยคนั้นปฏิเสธเหตุการณ์ เช่น ไม่ได้ทำร้าย",
            },
        },
        "benchmark": {
            "source": str(proper_path) if proper_path else None,
            "raw_source": str(proper_raw_path) if proper_raw_path else None,
            "source_function": "evaluate_h2l_proper.py::EvaluationRunner.evaluate_all",
            "rows": benchmark_rows,
            "comparison_pairs": comparison_pairs,
            "full_strategy_reference": full_strategy_reference,
            "isolated_pair_runs": isolated_pair_runs,
            "experiment_diagnostics": experiment_diagnostics,
            "problem_source_runs": proper_runs_by_problem_source,
            "doc_scaling": doc_scaling,
            "diagnostic_note": "case_diagnostics, experiment_diagnostics, problem_source_runs และ doc_scaling อ่านจาก proper_eval artifacts ที่จับคู่กับ summary artifact เพื่อดู H2L/Baseline โดยไม่สร้างข้อมูลใหม่",
        },
        "research_report": {
            "dataset_source": ground_truth.get("source"),
            "train_source": ground_truth.get("source"),
            "test_source": ground_truth.get("source"),
            "train_count": ground_truth.get("train_count"),
            "test_count": ground_truth.get("test_count"),
            "split_ratio": ground_truth.get("split_ratio") or "70/30",
            "dataset_updated_at": ground_truth.get("dataset_updated_at"),
            "test_affirmative_cases": ground_truth.get("test_affirmative_cases"),
            "test_negated_cases": ground_truth.get("test_negated_cases"),
            "ground_truth_status": ground_truth.get("status"),
            "ground_truth_note": ground_truth.get("source_note"),
            "polarity_cases": polarity.get("overall", {}).get("total_cases"),
            "polarity_f1": polarity.get("overall", {}).get("f1_score"),
            "ablation_source": str(ablation_path) if ablation_path.exists() else None,
            "ablation_highlights": ablation_excerpt,
            "statistical": statistical,
            "sensitivity": sensitivity,
            "experiment_diagnostics": experiment_diagnostics,
            "full_strategy_reference": full_strategy_reference,
            "isolated_pair_runs": isolated_pair_runs,
            "problem_source_runs": proper_runs_by_problem_source,
            "doc_scaling": doc_scaling,
            "provenance": {
                "dataset": ground_truth,
                "case_level": {
                    "label": "Current case runtime review",
                    "source": "/analyze",
                    "scope": "single analyzed case",
                    "interpretation": "ใช้ดูตรรกะของระบบในเคสปัจจุบัน ไม่ใช่คะแนน benchmark",
                },
                "benchmark": {
                    "label": "Benchmark performance review",
                    "source": str(proper_path) if proper_path else None,
                    "scope": "test split from expanded_ground_truth.json",
                    "problem_source": proper_metadata.get("problem_source"),
                    "top_k": proper_metadata.get("top_k"),
                    "interpretation": "ใช้สรุปผล retrieval และเปรียบเทียบ baseline vs H2L บน test split",
                },
                "freshness": freshness,
                "review_actions": review_actions,
            },
            "interpretation": "Research Report แยก case-level runtime review ออกจาก benchmark performance review อย่างชัดเจน โดย benchmark อ้างอิง test split จาก expanded_ground_truth.json และ case-level อ้างอิงผล runtime ใน /analyze",
        },
        "data_sources": {
            "dataset": ground_truth,
            "freshness": freshness,
            "review_actions": review_actions,
            "evaluation_progress": evaluation_progress,
            "artifact_inventory": artifact_inventory,
        },
        "thesis_protocol": thesis_protocol,
        "strategy_pairs": STRATEGY_PAIRS,
        "strategy_options": _strategy_options(),
        "evaluation_progress": evaluation_progress,
        "artifact_inventory": artifact_inventory,
    }


def _latest_path(pattern: str) -> Optional[Path]:
    preferred_alias = _preferred_artifact_alias(pattern)
    if preferred_alias and preferred_alias.exists():
        return preferred_alias
    files = sorted(Path(".").glob(pattern))
    return files[-1] if files else None


def _csv_row_count(path: Optional[Path]) -> int:
    if not path or not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            return max(0, sum(1 for _ in csv.DictReader(handle)))
    except Exception:
        return 0


def _artifact_check(
    check_id: str,
    label: str,
    path: Optional[Path],
    source_function: str,
    required: bool = True,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    exists = bool(path and path.exists())
    return {
        "id": check_id,
        "label": label,
        "status": "ready" if exists else ("missing" if required else "optional-missing"),
        "required": required,
        "source": str(path) if path else None,
        "source_function": source_function,
        "details": details or {},
    }


def _thesis_status_payload() -> Dict[str, Any]:
    runtime_manager.start()
    runtime = runtime_manager.payload()
    summary = _evaluation_summary()
    evaluation_progress = summary.get("evaluation_progress", {})
    artifact_inventory = summary.get("artifact_inventory", {})
    checks: List[Dict[str, Any]] = []

    proper_path = _latest_path("evaluation_results/proper_eval_summary_*.json")
    proper = summary.get("proper_eval", {})
    freshness = summary.get("data_sources", {}).get("freshness", {})
    actual_strategies = set(proper.get("strategies") or [])
    aggregate_rows = summary.get("benchmark", {}).get("rows", [])
    missing_strategies = sorted(VALID_STRATEGIES - actual_strategies)
    proper_status = (
        "ready"
        if proper_path and not missing_strategies and len(aggregate_rows) >= len(VALID_STRATEGIES) and freshness.get("benchmark_current", True)
        else "degraded"
    )
    checks.append({
        "id": "proper_eval_pairs",
        "label": "Proper RAG evaluation pairs",
        "status": proper_status,
        "required": True,
        "source": str(proper_path) if proper_path else None,
        "source_function": "evaluate_h2l_proper.py::EvaluationRunner.evaluate_all",
        "details": {
            "cases": proper.get("num_cases"),
            "expected_strategies": sorted(VALID_STRATEGIES),
            "artifact_strategies": sorted(actual_strategies),
            "missing_strategies": missing_strategies,
            "comparison_pairs": len(summary.get("benchmark", {}).get("comparison_pairs", [])),
            "benchmark_current": freshness.get("benchmark_current"),
            "dataset_updated_at": freshness.get("dataset_updated_at"),
            "proper_eval_timestamp": freshness.get("proper_eval_timestamp"),
        },
    })

    polarity_path = _latest_path("evaluation_results/sentence_polarity_eval_*.json")
    polarity = summary.get("polarity_eval", {})
    polarity_status = "ready" if polarity_path and freshness.get("polarity_current", True) else "degraded"
    checks.append({
        **_artifact_check(
            "sentence_polarity_eval",
            "Sentence polarity evaluation",
            polarity_path,
            "evaluate_sentence_polarity.py::evaluate_sentence_polarity",
            True,
            {
                "cases": polarity.get("total_cases"),
                "accuracy": polarity.get("accuracy"),
                "f1_score": polarity.get("f1_score"),
                "negation_detection_rate": polarity.get("negation_detection_rate"),
                "polarity_current": freshness.get("polarity_current"),
                "dataset_updated_at": freshness.get("dataset_updated_at"),
                "polarity_eval_timestamp": freshness.get("polarity_eval_timestamp"),
            },
        ),
        "status": polarity_status,
    })

    statistical_path = _latest_path("evaluation_results/statistical_analysis_*.json")
    statistical = summary.get("research_report", {}).get("statistical", {})
    statistics_freshness = freshness.get("statistics", {})
    statistical_check = _artifact_check(
        "statistical_analysis",
        "Statistical analysis artifact",
        statistical_path,
        statistical.get("source_function") or "scripts/build_statistical_analysis.py::build_artifact",
        True,
        {
            "metrics": [metric.get("id") for metric in statistical.get("metrics", [])],
            "note": statistical.get("note"),
            "statistics_current": freshness.get("statistics_current"),
            "source_hash_match": statistics_freshness.get("source_hash_match"),
            "taxonomy_hash_match": statistics_freshness.get("taxonomy_hash_match"),
            "ground_truth_hash_match": statistics_freshness.get("ground_truth_hash_match"),
            "alternative": statistics_freshness.get("alternative"),
            "two_sided": statistics_freshness.get("two_sided"),
        },
    )
    statistical_check["status"] = (
        "ready" if statistical_path and freshness.get("statistics_current") else "degraded"
    )
    checks.append(statistical_check)

    sensitivity_specs = [
        ("alpha_sensitivity", "Alpha sensitivity", Path("ablation_results/rq2_α_parameter_sensitivity.csv"), "ablation_study.py::AlphaSensitivityExperiment"),
        ("l2_filtering", "L2 filtering impact", Path("ablation_results/rq1_l2_filtering_impact.csv"), "ablation_study.py::L2FilteringImpactExperiment"),
        ("matching_method", "Soft vs hard matching", Path("ablation_results/rq3_soft_vs_hard_matching.csv"), "ablation_study.py::SoftVsHardMatchingExperiment"),
        ("severity_prior", "Severity prior impact", Path("ablation_results/rq4_prior_calculation_impact.csv"), "ablation_study.py::PriorCalculationImpactExperiment"),
    ]
    for check_id, label, path, source_function in sensitivity_specs:
        checks.append(_artifact_check(
            check_id,
            label,
            path,
            source_function,
            True,
            {"rows": _csv_row_count(path)},
        ))

    ground_truth = summary.get("data_sources", {}).get("dataset", {})
    research = summary.get("research_report", {})
    checks.append({
        "id": "ground_truth_split",
        "label": "Unified ground truth split",
        "status": ground_truth.get("status", "missing"),
        "required": True,
        "source": ground_truth.get("source"),
        "source_function": "expanded_ground_truth.json::split field",
        "details": {
            "train_count": research.get("train_count"),
            "test_count": research.get("test_count"),
            "split_ratio": research.get("split_ratio"),
            "test_affirmative_cases": research.get("test_affirmative_cases"),
            "test_negated_cases": research.get("test_negated_cases"),
            "missing_split_count": ground_truth.get("missing_split_count"),
        },
    })

    frontend_index = FRONTEND_DIST / "index.html"
    checks.append(_artifact_check(
        "one_server_frontend",
        "Single-server frontend build",
        frontend_index,
        "frontend npm run build -> FastAPI StaticFiles/FileResponse",
        True,
        {
            "url": "http://127.0.0.1:8000/",
            "vite_required": False,
            "dist": str(FRONTEND_DIST),
        },
    ))

    taxonomy_path = Path(TAXONOMY_PATH)
    checks.append(_artifact_check(
        "taxonomy",
        "Problem-code taxonomy",
        taxonomy_path,
        "H2LDetectorV3 taxonomy loader",
        True,
        {"path": TAXONOMY_PATH},
    ))

    models = runtime.get("models", {})
    metadata_value = models.get("metadata_store")
    vector_value = models.get("vector_path")
    metadata_path = Path(str(metadata_value)) if metadata_value else None
    vector_path = Path(str(vector_value)) if vector_value else None
    checks.append(_artifact_check(
        "retrieval_index",
        "Retrieval metadata/vector index",
        metadata_path if metadata_path and metadata_path.exists() else None,
        "retriever.py::DenseIndex / HybridRetriever",
        True,
        {
            "metadata_store": str(metadata_path) if metadata_path else None,
            "vector_path": str(vector_path) if vector_path else None,
            "vector_path_exists": vector_path.exists() if vector_path else False,
            "embedding_model": models.get("embedding_model"),
            "rerank_model": models.get("rerank_model"),
        },
    ))

    components = runtime.get("components", {})
    component_required = ["config", "taxonomy", "detector_l1", "documents", "bm25", "embedding_model", "vector_index", "reranker", "h2l_scoring"]
    missing_components = [name for name in component_required if not components.get(name)]
    checks.append({
        "id": "runtime_components",
        "label": "Runtime detector/retrieval components",
        "status": "ready" if runtime.get("status") == "ready" and not missing_components else runtime.get("status"),
        "required": True,
        "source": "/runtime/status",
        "source_function": "RuntimeManager._warmup",
        "details": {
            "components": components,
            "missing_required_components": missing_components,
            "l2_ready": runtime.get("l2_ready"),
            "load_seconds": runtime.get("load_seconds"),
        },
    })

    checks.append({
        "id": "no_mock_contract",
        "label": "No-mock thesis contract",
        "status": "ready",
        "required": True,
        "source": "/analyze response contract",
        "source_function": "analyze_case / _calculate_metrics",
        "details": {
            "case_results": "detector + runtime retrieval",
            "case_metrics": "case_operational_metrics only",
            "research_metrics": "evaluation_summary artifacts only",
            "mock_fallback": False,
        },
    })

    checks.append({
        "id": "evaluation_progress",
        "label": "Live evaluation progress feed",
        "status": "ready" if evaluation_progress.get("status") in {"idle", "running", "complete"} else "degraded",
        "required": False,
        "source": "/evaluation-progress",
        "source_function": "evaluate_h2l_proper.py / evaluate_sentence_polarity.py progress artifacts",
        "details": evaluation_progress,
    })
    checks.append({
        "id": "artifact_retention",
        "label": "Artifact retention inventory",
        "status": "ready",
        "required": False,
        "source": "evaluation_results/",
        "source_function": "latest/checkpoint aliases + evaluator retention policy",
        "details": artifact_inventory,
    })

    blockers = [
        check
        for check in checks
        if check.get("required") and check.get("status") not in {"ready"}
    ]
    runtime_errors = runtime.get("errors", [])
    if runtime.get("status") == "error":
        overall = "error"
    elif blockers or runtime.get("status") == "degraded":
        overall = "degraded"
    else:
        overall = "ready"

    feature_groups = [
        {
            "id": "runtime_case_analysis",
            "label": "Live case analysis",
            "status": "ready" if runtime.get("status") in {"ready", "degraded"} and components.get("detector_l1") else "degraded",
            "meaning": "วิเคราะห์เคสจริงด้วย detector และ runtime retrieval ไม่ใช้ sample fallback",
        },
        {
            "id": "rag_comparison",
            "label": "Baseline vs H2L RAG comparison",
            "status": proper_status,
            "meaning": "เทียบ bm25_only/naive_rag/hyde/basic กับ h2l-* ตาม proper evaluation artifact",
        },
        {
            "id": "polarity_gate",
            "label": "Sentence polarity gate",
            "status": "ready" if polarity_path else "missing",
            "meaning": "อ่าน actor/target/action และ negation เพื่ออธิบาย candidate ก่อน/หลัง gate",
        },
        {
            "id": "vector_explainability",
            "label": "3D vector explainability",
            "status": "ready" if components.get("embedding_model") and components.get("vector_index") else "degraded",
            "meaning": "ใช้ embedding ของ query/problem/document จริงเพื่อสร้าง 3D projection",
        },
        {
            "id": "research_statistics",
            "label": "Research statistics and sensitivity",
            "status": "ready" if not any(check["id"] in {"statistical_analysis", "alpha_sensitivity", "l2_filtering", "matching_method", "severity_prior"} and check["status"] != "ready" for check in checks) else "degraded",
            "meaning": "ดึงค่า statistical/evaluation/sensitivity จาก artifact วิจัยจริง",
        },
        {
            "id": "human_review_workflow",
            "label": "Human audit and sign-off",
            "status": "ready",
            "meaning": "สร้าง audit packet และ sign-off summary สำหรับ human review",
        },
    ]

    return _json_safe({
        "status": overall,
        "thesis_ready": overall == "ready",
        "checked_at": _utc_now_iso(),
        "runtime_status": runtime,
        "features": feature_groups,
        "checks": checks,
        "blockers": blockers,
        "warnings": runtime_errors,
        "commands": {
            "build_frontend": "cd frontend && npm run build",
            "run_full_app": "python api.py",
            "open_url": "http://127.0.0.1:8000/",
            "smoke_test": "cd frontend && npm run smoke:cdp",
        },
        "interpretation": (
            "พร้อมใช้งานตาม thesis local demo: ผลเคสมาจาก runtime จริง และผลวิจัยมาจาก artifacts จริง"
            if overall == "ready"
            else "ยังใช้งานได้บางส่วน แต่ควรดู blockers/warnings ก่อนใช้เป็น thesis demo"
        ),
    })


def _strategy_delta_interpretation(strategy: str, quality_delta: float | None, time_delta: float | None) -> str:
    if quality_delta is None:
        return f"{strategy}: ไม่มี artifact ครบพอสำหรับเปรียบเทียบ H2L delta"
    quality_text = "เพิ่มคุณภาพ" if quality_delta > 0 else "ลดคุณภาพ" if quality_delta < 0 else "คุณภาพเท่าเดิม"
    time_text = ""
    if time_delta is not None:
        time_text = " โดยใช้เวลามากขึ้น" if time_delta > 0 else " โดยใช้เวลาลดลง" if time_delta < 0 else " โดยเวลาเท่าเดิม"
    return f"{strategy}: H2L {quality_text} {quality_delta:+.4f}{time_text}"


def _strategy_profile(requested_strategy: str) -> Dict:
    summary = _evaluation_summary()
    benchmark_rows = summary.get("benchmark", {}).get("rows", [])
    row = next((item for item in benchmark_rows if item.get("strategy") == requested_strategy), None)
    option = next((item for item in _strategy_options() if item["id"] == requested_strategy), _strategy_options()[0])
    pair = next((item for item in STRATEGY_PAIRS if requested_strategy in (item["baseline"], item["enhanced"])), None)
    return {
        **option,
        "selected": requested_strategy,
        "local_execution": False,
        "pair": pair,
        "benchmark": row,
        "execution_note": (
            "รันผ่าน runtime retrieval จริง และใช้ H2L problem-aware scoring"
            if requested_strategy.startswith("h2l-")
            else "รันผ่าน baseline retrieval จริงของ family เดียวกันเพื่อเทียบกับ H2L"
        ),
    }


def _health_payload() -> Dict:
    runtime = runtime_manager.payload()
    detector_ready = bool(runtime.get("components", {}).get("detector_l1")) or _taxonomy_loaded(enable_l2=False)
    return {
        "status": "ok" if detector_ready and runtime["status"] in {"ready", "degraded", "loading"} else "degraded",
        "message": "H2L API is running",
        "mode": "runtime-rag-h2l",
        "detector_ready": detector_ready,
        "l2_enabled": True,
        "l2_ready": runtime.get("l2_ready", False),
        "taxonomy_loaded": detector_ready,
        "taxonomy_path": TAXONOMY_PATH,
        "runtime_status_url": "/runtime/status",
        "thesis_status_url": "/thesis/status",
        "runtime_status": runtime["status"],
        "runtime_stage": runtime["stage"],
        "strategy_pairs": STRATEGY_PAIRS,
        "strategy_options": _strategy_options(),
    }


@app.get("/health")
def health():
    return _health_payload()


@app.get("/evaluation-summary")
def evaluation_summary():
    return _evaluation_summary()


@app.get("/evaluation-progress")
def evaluation_progress():
    return _evaluation_progress_summary()


@app.get("/runtime/status")
def runtime_status():
    runtime_manager.start()
    return runtime_manager.payload()


@app.get("/thesis/status")
def thesis_status():
    return _thesis_status_payload()


@app.post("/analyze")
def analyze_case(req: CaseRequest):
    raw_case_description = str(req.case_description or "")
    case_description = raw_case_description.strip()
    if not case_description:
        raise HTTPException(status_code=422, detail="case_description is required")

    request_started_perf = time.perf_counter()
    case_description, pii_redacted_count = _sanitize_pii(case_description)
    user_adjusted_spans = _normalize_user_adjusted_spans(
        req.user_adjusted_spans,
        raw_case_description,
        case_description,
    )

    start_time = time.time()
    requested_strategy = _normalize_strategy(req.strategy)
    requested_top_k = _normalize_doc_top_k(req.top_k)
    runtime_manager.start()
    runtime = runtime_manager.payload()

    if runtime["status"] == "loading":
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Runtime is still loading embedding/index/model components.",
                "runtime_status": runtime,
            },
        )
    if runtime["status"] == "error":
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Runtime failed to load retrieval components.",
                "runtime_status": runtime,
            },
        )

    effective_strategy = requested_strategy
    ready, missing = runtime_manager._strategy_dependencies_ready(effective_strategy)
    if not ready:
        fallback_strategy = _normalize_strategy(runtime.get("default_strategy"))
        fallback_ready, _ = runtime_manager._strategy_dependencies_ready(fallback_strategy)
        if fallback_ready:
            effective_strategy = fallback_strategy
        else:
            raise HTTPException(
                status_code=503,
                detail={
                    "message": f"Selected strategy '{requested_strategy}' is unavailable because components are missing: {', '.join(missing)}",
                    "runtime_status": runtime,
                },
            )

    # Determine if this is an H2L-Enhanced strategy
    is_h2l_strategy = effective_strategy.startswith("h2l-")
    
    # Research Integrity: Force L2 OFF for baseline strategies
    # Even if the user sends enable_l2=True, if they picked a baseline strategy, we must disable it
    if is_h2l_strategy:
        enable_l2_requested = bool(req.enable_l2)
    else:
        enable_l2_requested = False
        
    # Keep H2L detection semantics even when the semantic L2 endpoint is
    # degraded. The detector will still apply deterministic context filtering
    # and will report semantic L2 readiness separately.
    enable_l2_effective = enable_l2_requested
    requested_l2_model = str(req.llm_model or "").strip() or None
    effective_l2_model = (
        runtime_manager.resolve_l2_model(requested_l2_model)
        if enable_l2_effective
        else None
    )
    
    if runtime_manager.detector:
        detector = runtime_manager.detector
    else:
        detector = get_detector(enable_l2=True)

    try:
        detection = detector.detect_with_metadata(
            case_description,
            use_l2=enable_l2_effective,
            l2_model=effective_l2_model,
        )
    except Exception as exc:
        logger.exception("Detector analysis failed")
        if enable_l2_effective:
            detection = detector.detect_with_metadata(case_description, use_l2=False)
            enable_l2_effective = False
        else:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    problems = detection.get("problems", [])
    filtered_out = detection.get("filtered_out", [])
    metadata = detection.get("metadata", {})
    user_adjusted_problem_count = _apply_user_adjusted_spans_to_candidates(
        problems,
        case_description,
        user_adjusted_spans,
    )
    user_adjusted_filtered_count = _apply_user_adjusted_spans_to_candidates(
        filtered_out,
        case_description,
        user_adjusted_spans,
    )
    detection_timings = metadata.get("timings_ms", {}) if isinstance(metadata, dict) else {}
    case_input_ms = round((time.perf_counter() - request_started_perf) * 1000, 2)

    finalize_started_perf = time.perf_counter()
    sentence_profile = _sentence_profile(case_description)
    problems, filtered_out = _apply_polarity_gate(
        case_description,
        problems,
        filtered_out,
        sentence_profile,
        enabled=is_h2l_strategy,
    )
    problems, filtered_out = _attach_grounded_explanations(
        case_description,
        problems,
        filtered_out,
        sentence_profile,
    )
    problems, filtered_out = _apply_review_status(
        problems,
        filtered_out,
        baseline_mode=not is_h2l_strategy,
    )
    review_summary = _review_status_summary(
        problems,
        filtered_out,
        baseline_mode=not is_h2l_strategy,
    )
    candidate_trace = _candidate_trace(problems, filtered_out, metadata)
    finalize_ms = round((time.perf_counter() - finalize_started_perf) * 1000, 2)

    retrieval_errors: List[str] = []
    retriever = None
    retrieval_results: List[Any] = []
    retrieval_started_perf = time.perf_counter()

    try:
        retriever = runtime_manager.get_retriever(effective_strategy)
        try:
            retrieval_results = retriever.retrieve(
                query=case_description,
                explicit_problems=problems,
                top_k_override=requested_top_k,
            )
        except TypeError:
            retrieval_results = retriever.retrieve(
                query=case_description,
                top_k_override=requested_top_k,
            )
    except Exception as exc:
        logger.exception("Retrieval failed")
        retrieval_errors.append(str(exc))

    retrieved_docs = _serialize_retrieved_docs(retrieval_results[:requested_top_k], problems)
    retrieval_ms = round((time.perf_counter() - retrieval_started_perf) * 1000, 2)
    metrics = _calculate_metrics(problems, filtered_out, retrieved_docs)

    execution_time = time.time() - start_time
    case_id = _new_case_id()
    runtime_status_after = runtime_manager.payload()
    phase_timings_ms = {
        "case_input": case_input_ms,
        "l1": float(detection_timings.get("l1", 0.0) or 0.0),
        "l2": float(detection_timings.get("l2", 0.0) or 0.0),
        "finalize": finalize_ms,
        "retrieval": retrieval_ms,
        "total": round((time.perf_counter() - request_started_perf) * 1000, 2),
    }

    strategy_degraded = effective_strategy != requested_strategy
    degradation_reason = None
    if strategy_degraded:
        degradation_reason = f"Requested strategy '{requested_strategy}' fell back to '{effective_strategy}' because dense embedding or reranker runtime components are unavailable."
    elif retrieval_errors:
        degradation_reason = f"Retrieval encountered errors: {'; '.join(retrieval_errors)}"

    overall_status = "degraded" if (retrieval_errors or strategy_degraded) else "ok"

    result = {
        "status": overall_status,
        "mode": "runtime-rag-h2l",
        "requested_strategy": requested_strategy,
        "effective_strategy": effective_strategy,
        "strategy_fallback": strategy_degraded,
        "degradation_reason": degradation_reason,
        "requested_l2_model": requested_l2_model,
        "effective_l2_model": metadata.get("l2_model"),
        "model_provenance": {
            "requested_l2_model": requested_l2_model,
            "selected_l2_model": effective_l2_model,
            "effective_l2_model": metadata.get("l2_model"),
            "l2_attempted": bool(metadata.get("l2_attempted", False)),
            "embedding_model": runtime_status_after.get("models", {}).get("embedding_model"),
            "rerank_model": runtime_status_after.get("models", {}).get("rerank_model"),
            "h2l_formula": "bayesian_v6_unchanged",
        },
        "requested_top_k": req.top_k,
        "top_k": requested_top_k,
        "doc_scaling": _doc_scaling_guidance(requested_top_k),
        "strategy_profile": _strategy_profile(effective_strategy),
        "strategy_note": (
            "This request used live runtime retrieval. If runtime is degraded, unavailable strategies fall back to the runtime default and the response does not claim unavailable components ran successfully."
        ),
        "case_id": case_id,
        "case_description": case_description,
        "problems": problems,
        "filtered_out": filtered_out,
        "tools": _recommend_tools(problems),
        "severity_level": _determine_severity(problems),
        "metrics": metrics,
        "score_components": _score_components(problems, filtered_out, retrieved_docs),
        "keyword_analysis": _keyword_analysis(problems, filtered_out),
        "review_summary": review_summary,
        "sentence_profile": sentence_profile,
        "polarity_effect": _polarity_effect(problems, filtered_out, sentence_profile),
        "vector_space": _vector_space(case_description, problems, retrieved_docs, runtime_manager),
        "detection_flow": _detection_flow(metadata, problems, filtered_out, phase_timings_ms),
        "phase_timings_ms": phase_timings_ms,
        "evaluation_summary": _evaluation_summary(),
        "execution_time": execution_time,
        "detection_info": {
            "l1_candidates": candidate_trace["l1_candidates"],
            "l2_applied": bool(metadata.get("l2_attempted", False)),
            "l2_requested": enable_l2_requested,
            "requested_l2_model": requested_l2_model,
            "effective_l2_model": metadata.get("l2_model"),
            "l2_ready": runtime_status_after.get("l2_ready", False),
            "l2_client_ready": bool(metadata.get("l2_ready", False)),
            "l2_semantic_ready": runtime_status_after.get("l2_ready", False),
            "l2_degraded": bool(metadata.get("l2_degraded", False)),
            "final_count": len(problems),
            "filtered_count": len(filtered_out),
            "l1_count": metadata.get("l1_count", 0),
            "l2_count": metadata.get("l2_count", 0),
            "conflicts": metadata.get("conflicts", {}),
            "needs_l2_validation": metadata.get("needs_l2_validation", []),
            "ambiguity_summary": _ambiguity_summary(metadata),
            "context_analysis": metadata.get("context_analysis", {}),
            "review_summary": review_summary,
        },
        "candidate_count": candidate_trace["candidate_count"],
        "candidates": candidate_trace["candidates"],
        "filter_reasons": candidate_trace["filter_reasons"],
        "candidate_trace": candidate_trace,
        "retrieved_docs_count": len(retrieved_docs),
        "retrieved_docs": retrieved_docs,
        "retrieval_trace": _retrieval_trace(effective_strategy, retrieved_docs, retrieval_errors, retriever, requested_top_k),
        "h2l_scoring_trace": _h2l_scoring_trace(retrieved_docs),
        "runtime_status": runtime_status_after,
        "pii_redacted_count": pii_redacted_count,
        "user_adjusted_spans": user_adjusted_spans,
        "user_adjusted_span_count": len(user_adjusted_spans),
        "user_adjusted_spans_applied_to": {
            "problems": user_adjusted_problem_count,
            "filtered_out": user_adjusted_filtered_count,
        },
    }
    result = _json_safe(result)
    CASE_CACHE[case_id] = result
    return result


@app.post("/audit/prepare")
def prepare_audit(req: AuditRequest):
    analysis = req.analysis or (CASE_CACHE.get(req.case_id or "") if req.case_id else None)
    if not analysis:
        raise HTTPException(status_code=404, detail="Run analysis first or provide a valid case_id.")

    packet = {
        "audit_id": f"AUDIT_{int(time.time())}",
        "case_id": analysis.get("case_id"),
        "prepared_at": _utc_now_iso(),
        "objective": "รวบรวมข้อมูลสำหรับ secondary human audit โดยไม่สรุปแทนผู้ทบทวน",
        "case_summary": analysis.get("case_description", "")[:600],
        "severity_level": analysis.get("severity_level"),
        "accepted_problems": analysis.get("problems", []),
        "rejected_candidates": analysis.get("filtered_out", []),
        "candidate_trace": analysis.get("candidate_trace", {}),
        "evidence_docs": analysis.get("retrieved_docs", []),
        "polarity_notes": analysis.get("polarity_effect", {}),
        "runtime_status": analysis.get("runtime_status", {}),
        "export_markdown": _audit_markdown(analysis),
    }
    return packet


@app.post("/case/finalize")
def finalize_case(req: FinalizeRequest):
    analysis = CASE_CACHE.get(req.case_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="case_id not found. Run analysis before finalizing.")

    def unique_codes(values: List[Any]) -> List[str]:
        normalized: List[str] = []
        seen: Set[str] = set()
        for value in values:
            code = str(value or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            normalized.append(code)
        return normalized

    problems = analysis.get("problems", [])
    analysis_codes = unique_codes([problem.get("code") for problem in problems])
    if not analysis_codes and not req.zero_finding_acknowledged:
        raise HTTPException(
            status_code=422,
            detail="Acknowledge the zero-finding result before finalizing this case.",
        )

    requested_review_states = dict(req.finding_review_states)
    unknown_review_codes = sorted(set(requested_review_states) - set(analysis_codes))
    if unknown_review_codes:
        raise HTTPException(
            status_code=422,
            detail=f"finding_review_states contains codes not present in this analysis: {', '.join(unknown_review_codes)}",
        )
    review_states = {
        code: requested_review_states[code]
        for code in analysis_codes
        if code in requested_review_states
    }

    selected = unique_codes(
        list(req.selected_findings)
        if req.selected_findings is not None
        else analysis_codes
    )
    rejected = unique_codes(req.expert_override_rejected)
    rejected_set = set(rejected)
    selected = [code for code in selected if code not in rejected_set]
    for code in analysis_codes:
        state = review_states.get(code)
        if state == "excluded":
            selected = [selected_code for selected_code in selected if selected_code != code]
            if code not in rejected:
                rejected.append(code)
        elif state in {"accepted", "review"}:
            if code not in selected:
                selected.append(code)
            rejected = [rejected_code for rejected_code in rejected if rejected_code != code]

    summary = {
        "case_id": req.case_id,
        "finalized_at": _utc_now_iso(),
        "status": req.final_status,
        "reviewer_note": req.reviewer_note,
        "selected_findings": selected,
        "finding_review_states": review_states,
        "expert_override_added": req.expert_override_added,
        "expert_override_rejected": rejected,
        "zero_finding_acknowledged": req.zero_finding_acknowledged,
        "checklist": [
            {"item": "Reviewed accepted problem codes", "done": bool(selected) or (not analysis_codes and req.zero_finding_acknowledged)},
            {"item": "Reviewed rejected/filter reasons", "done": True},
            {"item": "Reviewed evidence retrieval ranks", "done": bool(analysis.get("retrieved_docs"))},
            {"item": "Reviewed polarity actor/target/action notes", "done": True},
            {"item": "Ready for human review", "done": req.final_status == "Ready for Human Review"},
        ],
        "export_json": {
            "case_id": req.case_id,
            "status": req.final_status,
            "selected_findings": selected,
            "finding_review_states": review_states,
            "expert_override_rejected": rejected,
            "zero_finding_acknowledged": req.zero_finding_acknowledged,
            "severity_level": analysis.get("severity_level"),
            "runtime_status": analysis.get("runtime_status", {}).get("status"),
        },
        "export_markdown": _signoff_markdown(
            analysis,
            req,
            selected,
            review_states,
            rejected,
        ),
    }
    FINALIZED_CASES[req.case_id] = summary
    return summary


def _audit_markdown(analysis: Dict[str, Any]) -> str:
    problems = analysis.get("problems", [])
    filtered = analysis.get("filtered_out", [])
    docs = analysis.get("retrieved_docs", [])
    lines = [
        f"# Secondary Audit Packet: {analysis.get('case_id')}",
        "",
        f"Severity: {analysis.get('severity_level')}",
        f"Strategy: {analysis.get('requested_strategy')}",
        "",
        "## Case Summary",
        analysis.get("case_description", ""),
        "",
        "## Accepted Problems",
    ]
    lines.extend([f"- {p.get('code')}: {p.get('name')} ({p.get('confidence', 0):.2f})" for p in problems] or ["- None"])
    lines.append("")
    lines.append("## Rejected Candidates")
    lines.extend([f"- {p.get('code')}: {p.get('reasoning', 'filtered')}" for p in filtered] or ["- None"])
    lines.append("")
    lines.append("## Evidence Documents")
    lines.extend([f"- Rank {d.get('rank')}: {d.get('title')} score={d.get('h2l_final_score')}" for d in docs[:8]] or ["- None"])
    lines.append("")
    lines.append("## Polarity Notes")
    lines.append(analysis.get("polarity_effect", {}).get("interpretation", "N/A"))
    return "\n".join(lines)


def _signoff_markdown(
    analysis: Dict[str, Any],
    req: FinalizeRequest,
    findings: List[str],
    review_states: Dict[str, str],
    rejected_findings: List[str],
) -> str:
    review_state_lines = [
        f"- {code}: {state}"
        for code, state in review_states.items()
    ] or ["- None provided"]
    return "\n".join([
        f"# Case Sign-Off: {req.case_id}",
        "",
        f"Status: {req.final_status}",
        f"Reviewer note: {req.reviewer_note or 'N/A'}",
        f"Selected findings: {', '.join(findings) if findings else 'None'}",
        f"Excluded findings: {', '.join(rejected_findings) if rejected_findings else 'None'}",
        f"Zero-finding acknowledged: {'Yes' if req.zero_finding_acknowledged else 'No'}",
        f"Severity: {analysis.get('severity_level')}",
        "",
        "## Finding Review States",
        *review_state_lines,
        "",
        "This summary is prepared for human review and is not a final clinical diagnosis.",
    ])


def _serve_frontend_file(path: str = "index.html"):
    requested = FRONTEND_DIST / path
    if requested.exists() and requested.is_file():
        return FileResponse(requested)

    index_file = FRONTEND_DIST / "index.html"
    if index_file.exists():
        return FileResponse(index_file)

    raise HTTPException(
        status_code=503,
        detail="Frontend build is missing. Run `cd frontend && npm run build`, then restart python api.py.",
    )


@app.get("/")
def serve_frontend_root():
    return _serve_frontend_file()


@app.head("/")
def serve_frontend_root_head():
    return _serve_frontend_file()


@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    return _serve_frontend_file(full_path)


@app.head("/{full_path:path}")
def serve_frontend_head(full_path: str):
    return _serve_frontend_file(full_path)


if __name__ == "__main__":
    import uvicorn
    from h2l.config import get_config

    config = get_config()
    uvicorn.run(app, host=getattr(config, "HOST", "0.0.0.0"), port=getattr(config, "PORT", 8000))
