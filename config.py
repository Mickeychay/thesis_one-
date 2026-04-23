#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration Module
--------------------
จัดการ configuration สำหรับ RAG Bot
"""

import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()

def _as_bool(s: str, default=False):
    """Convert string to boolean"""
    if s is None:
        return default
    return str(s).lower() in {"1", "true", "yes", "y", "on"}

def _default_device() -> str:
    """Pick a safe default device for local Mac and Linux/cloud runtimes."""
    explicit_device = os.getenv("DEVICE")
    if explicit_device:
        return explicit_device

    try:
        import torch

        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass

    return "cpu"

def _looks_like_cloud_runtime() -> bool:
    """Detect common hosted runtimes where loading large ML models can kill the process."""
    cloud_markers = [
        "DYNO",
        "FLY_APP_NAME",
        "K_SERVICE",
        "RAILWAY_ENVIRONMENT",
        "RENDER",
        "SPACE_ID",
        "VERCEL",
    ]
    return any(os.getenv(marker) for marker in cloud_markers)

class Config:
    """Main configuration class"""
    
    # =========================================================================
    # API Keys
    # =========================================================================
    OCR_TYPHOON_API_KEY = os.getenv("OCR_TYPHOON_API_KEY")
    LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
    PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME")

    # =========================================================================
    # Vector Database Configuration
    # =========================================================================
    DB_TYPE = os.getenv("VECTOR_BACKEND", "lancedb")
    DB_PATH_BASE = Path(f"data/vector_db_{DB_TYPE}")
    DB_PATH = str(DB_PATH_BASE / ("faiss.index" if DB_TYPE == "faiss" else "social_work_docs"))
    METADATA_STORE = str(DB_PATH_BASE / "metadata.json")

    # =========================================================================
    # Embedding & Reranking Models
    # =========================================================================
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-base")
    RERANK_MODEL = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
    DEVICE = _default_device()
    SAFE_START = _as_bool(os.getenv("H2L_SAFE_START"), default=_looks_like_cloud_runtime())
    ENABLE_DENSE_RUNTIME = _as_bool(os.getenv("ENABLE_DENSE_RUNTIME"), default=not SAFE_START)

    # =========================================================================
    # LLM Configuration
    # =========================================================================
    USE_LOCAL_LLM = _as_bool(os.getenv("USE_LOCAL_LLM", "true"), default=True)
    LOCAL_LLM_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
    LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:7b")
    OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))

    # =========================================================================
    # Retrieval Strategy Configuration
    # =========================================================================
    RETRIEVAL_STRATEGY = os.getenv("RETRIEVAL_STRATEGY", "orchestrator")
    USE_RERANK = _as_bool(os.getenv("USE_RERANK"), default=not SAFE_START)
    TOP_K = int(os.getenv("TOP_K", "10"))
    BM25_K = int(os.getenv("BM25_K", "25"))
    FUSION_K = int(os.getenv("FUSION_K", "30"))
    RRF_K = int(os.getenv("RRF_K", "60"))
    MAX_HOPS = int(os.getenv("MAX_HOPS", "2"))
    
    # =========================================================================
    # Chunking Configuration
    # =========================================================================
    class ChunkingConfig:
        MIN_CHUNK_LENGTH = int(os.getenv("MIN_CHUNK_LENGTH", "100"))
        MAX_CHUNK_LENGTH = int(os.getenv("MAX_CHUNK_LENGTH", "2000"))
        MIN_THAI_RATIO = float(os.getenv("MIN_THAI_RATIO", "0.6"))
        OVERLAP = int(os.getenv("OVERLAP", "300"))
        STRATEGY = os.getenv("CHUNKING_STRATEGY", "hybrid")
        SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.7"))
        MIN_SENTENCES_PER_CHUNK = int(os.getenv("MIN_SENTENCES_PER_CHUNK", "3"))
        MAX_SENTENCES_PER_CHUNK = int(os.getenv("MAX_SENTENCES_PER_CHUNK", "20"))
        
    # =========================================================================
    # H2L-Detect Configuration
    # =========================================================================
    # Auto-resolve: prefer root-level problem_codes.json, fallback to data/
    _DEFAULT_PROBLEM_DB = "problem_codes.json" if os.path.exists("problem_codes.json") else "data/problem_codes.json"
    PROBLEM_DB_PATH = os.getenv("PROBLEM_DB_PATH", _DEFAULT_PROBLEM_DB)
    ENABLE_L2_DETECTION = _as_bool(os.getenv("ENABLE_L2_DETECTION", "true"), default=True)
    L2_SIMILARITY_THRESHOLD = float(os.getenv("L2_SIMILARITY_THRESHOLD", "0.7"))
    L2_TOP_K = int(os.getenv("L2_TOP_K", "5"))
    
    # =========================================================================
    # Adaptive (HCA-RAG) Configuration
    # =========================================================================
    ADAPTIVE_K = int(os.getenv("ADAPTIVE_K", "10"))
    ADAPTIVE_T_CRITICAL = float(os.getenv("ADAPTIVE_T_CRITICAL", "1.96"))
    INNER_K = int(os.getenv("INNER_K", "3"))
    OUTER_K = int(os.getenv("OUTER_K", "5"))

    # =========================================================================
    # Dynamic Retrieval Configuration
    # =========================================================================
    class DynamicRetrievalConfig:
        SIMPLE_K = int(os.getenv("SIMPLE_K", "5"))
        SPECIFIC_K = int(os.getenv("SPECIFIC_K", "7"))
        NORMAL_K = int(os.getenv("NORMAL_K", "10"))
        COMPLEX_K = int(os.getenv("COMPLEX_K", "15"))

    class RAGConfig:
        MAX_CONTEXT_DOCS = 5
        MIN_SIMILARITY_SCORE = 0.3
        PROBLEM_DETECTION_THRESHOLD = 0.5

    @property
    def parsing(self):
        class ParsingConfig:
            min_chunk_length = self.ChunkingConfig.MIN_CHUNK_LENGTH
            max_chunk_length = self.ChunkingConfig.MAX_CHUNK_LENGTH
            min_thai_ratio = self.ChunkingConfig.MIN_THAI_RATIO
            overlap = self.ChunkingConfig.OVERLAP
        return ParsingConfig()
        
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))
    DEBUG = _as_bool(os.getenv("DEBUG", "false"), default=False)
    ENABLE_LOG_BODY = _as_bool(os.getenv("ENABLE_LOG_BODY", "true"), default=True)
    GROUND_TRUTH_PATH = os.getenv("GROUND_TRUTH_PATH", "expanded_ground_truth.json")
    USE_GROUND_TRUTH_IN_PRODUCTION = _as_bool(os.getenv("USE_GROUND_TRUTH_IN_PRODUCTION", "false"), default=False)
    SEED = int(os.getenv("SEED", "42"))

    # =========================================================================
    # Research Integrity Guardrails
    # =========================================================================
    # Disabled by default so demo/synthetic/oracle paths cannot be mistaken for
    # empirical system outputs in thesis experiments.
    ALLOW_DEMO_DATA = _as_bool(os.getenv("ALLOW_DEMO_DATA", "false"), default=False)
    ALLOW_SYNTHETIC_STATS = _as_bool(os.getenv("ALLOW_SYNTHETIC_STATS", "false"), default=False)
    ALLOW_GROUND_TRUTH_INDEX = _as_bool(os.getenv("ALLOW_GROUND_TRUTH_INDEX", "false"), default=False)

    @classmethod
    def validate_app_config(cls):
        missing = []
        if not cls.LINE_CHANNEL_ACCESS_TOKEN: missing.append("LINE_CHANNEL_ACCESS_TOKEN")
        if not cls.LINE_CHANNEL_SECRET: missing.append("LINE_CHANNEL_SECRET")
        
        if cls.USE_LOCAL_LLM:
            if not cls.LOCAL_LLM_BASE_URL: missing.append("LOCAL_LLM_BASE_URL")
            if not cls.LOCAL_LLM_MODEL: missing.append("LOCAL_LLM_MODEL")
            print(f"🖥️  Config Mode: LOCAL LLM ({cls.LOCAL_LLM_MODEL})")
        else:
            if not cls.OPENROUTER_API_KEY: missing.append("OPENROUTER_API_KEY")
            if not cls.OPENROUTER_MODEL: missing.append("OPENROUTER_MODEL")
            print(f"☁️  Config Mode: OPENROUTER ({cls.OPENROUTER_MODEL})")
        
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
        cls._print_config_summary()
        return True

    @classmethod
    def _print_config_summary(cls):
        print("\n" + "="*70 + "\n⚙️  CONFIGURATION SUMMARY\n" + "="*70)
        llm_info = cls.get_llm_info()
        print(f"LLM Mode:           {llm_info['mode'].upper()}")
        print(f"LLM Model:          {llm_info['model']}")
        print(f"LLM Endpoint:       {llm_info['endpoint']}")
        if llm_info['mode'] == 'local':
            print(f"Device:             {llm_info['device']}")
        print(f"\nRetrieval Strategy: {cls.RETRIEVAL_STRATEGY.upper()}")
        print(f"Vector Backend:     {cls.DB_TYPE.upper()}")
        print(f"H2L Detection:      {cls.ENABLE_L2_DETECTION}")
        print("="*70 + "\n")

    @classmethod
    def get_llm_info(cls):
        if cls.USE_LOCAL_LLM:
            return {"mode": "local", "model": cls.LOCAL_LLM_MODEL, "endpoint": cls.LOCAL_LLM_BASE_URL, "device": cls.DEVICE}
        else:
            return {"mode": "cloud", "model": cls.OPENROUTER_MODEL, "endpoint": "https://openrouter.ai/api/v1"}
            
_config_instance = None

def get_config():
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance
