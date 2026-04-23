# retrievers.py - FIXED VERSION
# แก้ไข: Distance Metric Conversion สำหรับ LanceDB (Cosine Distance)
from __future__ import annotations
import os
import re
import json
import unicodedata
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from pythainlp import word_tokenize
from pythainlp.util import normalize as th_normalize 

import importlib.util

# --- Library Import Checks (Lazy Loading) ---
_HAS_BM25 = importlib.util.find_spec("rank_bm25") is not None
_HAS_FAISS = importlib.util.find_spec("faiss") is not None
_HAS_CHROMA = importlib.util.find_spec("chromadb") is not None
_HAS_LANCE = importlib.util.find_spec("lancedb") is not None
try:
    from rich.console import Console
    console = Console()
except ImportError:
    class _Dummy:
        def print(self, *a, **k): print(*a)
        def log(self, *a, **k): print(*a)
    console = _Dummy()

def _normalize_th(text: str) -> str:
    if not text or not isinstance(text, str): return ""
    try:
        text = unicodedata.normalize("NFC", text)
        text = th_normalize(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text
    except Exception:
        return str(text).strip()

def _tokenize_th(text: str) -> List[str]:
    normalized_text = _normalize_th(text)
    if not normalized_text: return []
    try:
        return word_tokenize(normalized_text, engine="newmm", keep_whitespace=False)
    except Exception:
        return str(text).split()

def _rrf_fusion(dense_hits: List[Tuple[int, float]], bm25_hits: List[Tuple[int, float]], k: int, rrf_k: int) -> List[Tuple[int, float]]:
    rank_scores: Dict[int, float] = {}
    for rank, (doc_id, _) in enumerate(dense_hits, start=1):
        if doc_id is not None:
            rank_scores[doc_id] = rank_scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)
    for rank, (doc_id, _) in enumerate(bm25_hits, start=1):
        if doc_id is not None:
            rank_scores[doc_id] = rank_scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)
    return sorted(rank_scores.items(), key=lambda x: x[1], reverse=True)[:k]

@dataclass
class Doc:
    id: int
    text: str
    meta: Dict[str, Any]

@dataclass
class RetrievalResult:
    doc: Doc
    score: float
    rerank_score: Optional[float] = None
    
    @property
    def final_score(self) -> float:
        return self.rerank_score if self.rerank_score is not None else self.score

class DenseIndex:
    def __init__(self, db_type: str, db_path: str, model_name: str, device: str):
        self.backend = db_type.lower()
        self.db_path = Path(db_path)
        self.model_name = model_name
        self.device = device
        self.embedder = None
        self.index = None
        self._load_embedder()
        self._load_index()

    def _load_embedder(self):
        try:
            from sentence_transformers import SentenceTransformer

            self.embedder = SentenceTransformer(self.model_name, device=self.device, trust_remote_code=True)
        except Exception as e:
            raise RuntimeError(f"Failed to load embedding model: {e}")

    def _load_index(self):
        try:
            if self.backend == "faiss":
                if not _HAS_FAISS: raise ImportError("faiss-cpu not installed.")
                if not self.db_path.exists(): raise FileNotFoundError(f"FAISS index file not found at {self.db_path}")
                import faiss
                self.index = faiss.read_index(str(self.db_path))
            elif self.backend == "lancedb":
                if not _HAS_LANCE: raise ImportError("lancedb not installed.")
                import lancedb
                db_uri = str(self.db_path.parent)
                db = lancedb.connect(db_uri)
                self.index = db.open_table(self.db_path.name)
            elif self.backend in ["chroma", "chromadb"]:
                if not _HAS_CHROMA: raise ImportError("chromadb not installed.")
                import chromadb
                db_uri = str(self.db_path.parent)
                client = chromadb.PersistentClient(path=db_uri)
                self.index = client.get_collection(name=self.db_path.name)
            else:
                raise ValueError(f"Unsupported DB type: {self.backend}")
        except Exception as e:
            raise RuntimeError(f"Failed to load index '{self.db_path}': {e}")

    def search(self, query: str, top_k: int) -> List[Tuple[int, float]]:
        import numpy as np
        query_vector = self.embedder.encode(f"query: {query}", normalize_embeddings=True, convert_to_numpy=True)
        
        if self.backend == "faiss":
            distances_sq, ids = self.index.search(np.array([query_vector], dtype="float32"), top_k)
            valid_indices = ids[0] != -1
            valid_ids = ids[0][valid_indices]
            valid_distances_sq = distances_sq[0][valid_indices]
            # FAISS L2: similarity = 1 - dist/2
            similarities = [1 - (dist / 2) for dist in valid_distances_sq]
            return list(zip(valid_ids.tolist(), similarities))

        elif self.backend == "lancedb":
            search_results = self.index.search(query_vector).limit(top_k).to_df()
            results = []
            for _, row in search_results.iterrows():
                doc_id = int(row['id'])
                distance = row['_distance']
                # ✅ FIXED: LanceDB default = Cosine Distance
                # Cosine Distance ∈ [0, 2], Similarity = 1 - Distance
                similarity = 1.0 - distance
                # Clamp to valid range [0, 1]
                similarity = max(0.0, min(1.0, similarity))
                results.append((doc_id, similarity))
            return results
            
        elif self.backend in ["chroma", "chromadb"]:
            res = self.index.query(query_embeddings=[query_vector.tolist()], n_results=top_k)
            results = []
            if res.get('ids') and res['ids'][0]:
                for id_str, dist in zip(res['ids'][0], res['distances'][0]):
                    try:
                        doc_id = int(id_str)
                        # ChromaDB default = Cosine Distance
                        similarity = 1.0 - dist
                        similarity = max(0.0, min(1.0, similarity))
                        results.append((doc_id, similarity))
                    except (ValueError, AttributeError): continue
            return results
        return []

class ThaiBM25:
    def __init__(self, all_docs: List[Doc]):
        if not _HAS_BM25: raise ImportError("rank-bm25 not installed.")
        console.print(f"  - 🔍 [ThaiBM25] Starting tokenization for {len(all_docs)} docs...", style="yellow")
        self.docs = all_docs
        
        corpus_with_content = [doc for doc in self.docs if doc.text and doc.text.strip()]
        if not corpus_with_content:
             raise ValueError("All documents have empty content. Cannot build BM25 index.")
             
        from rank_bm25 import BM25Okapi
        
        tokenized_corpus = [_tokenize_th(doc.text) for doc in corpus_with_content]
        
        self.index = BM25Okapi(tokenized_corpus)
        self.doc_map_indices = {i: doc.id for i, doc in enumerate(corpus_with_content)}
        console.print("  - ✅ [ThaiBM25] BM25 index created successfully.", style="green")

    def search(self, query: str, top_k: int) -> List[Tuple[int, float]]:
        tokenized_query = _tokenize_th(query)
        if not tokenized_query: return []
        doc_scores = self.index.get_scores(tokenized_query)
        top_n_indices = sorted(range(len(doc_scores)), key=lambda i: doc_scores[i], reverse=True)[:top_k]
        return [(self.doc_map_indices[i], doc_scores[i]) for i in top_n_indices if i in self.doc_map_indices]

class Reranker:
    def __init__(self, model_name: str, device: str):
        try:
            from sentence_transformers import CrossEncoder

            self.model = CrossEncoder(model_name, device=device, trust_remote_code=True)
        except Exception as e:
            raise RuntimeError(f"Failed to load reranker model: {e}")

    def rerank(self, query: str, candidates: List[Doc], top_k: int) -> List[Tuple[Doc, float]]:
        if not candidates: return []
        pairs = [(query, doc.text) for doc in candidates]
        try:
            scores = self.model.predict(pairs, convert_to_numpy=True)
            return sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)[:top_k]
        except Exception as e:
            console.log(f"❌ Reranking failed: {e}")
            for doc in candidates[:top_k]:
                doc.meta = dict(doc.meta or {})
                doc.meta["rerank_fallback"] = "model_predict_failed"
                doc.meta["rerank_fallback_error"] = str(e)
            return [(doc, 0.0) for doc in candidates[:top_k]]

class HybridRetriever:
    def __init__(self, config, shared_components: 'SharedComponents' = None):
        console.print(f"\n🚀 [{self.__class__.__name__}] Initializing...", style="bold blue")
        
        self.config = config
        
        if shared_components:
            console.log("  - Using pre-loaded shared components.")
            self.all_docs = shared_components['all_docs']
            self.doc_map = shared_components['doc_map']
            self.dense_retriever = shared_components['dense_retriever']
            self.lexical_retriever = shared_components['lexical_retriever']
            self.reranker = shared_components.get('reranker')
        else:
            console.log("  - No shared components provided. Loading components individually.")
            self.all_docs = self._load_all_docs(config)
            if not self.all_docs:
                raise ValueError("FATAL: _load_all_docs returned an empty list. Check data source and config.")
            self.doc_map = {doc.id: doc for doc in self.all_docs}
            
            self.dense_retriever = (
                DenseIndex(config.DB_TYPE, config.DB_PATH, config.EMBEDDING_MODEL, config.DEVICE)
                if getattr(config, "ENABLE_DENSE_RUNTIME", True)
                else None
            )
            self.lexical_retriever = ThaiBM25(self.all_docs)
            self.reranker = Reranker(config.RERANK_MODEL, config.DEVICE) if getattr(config, "USE_RERANK", False) else None
                
        console.print(f"✅ [{self.__class__.__name__}] Pipeline ready!", style="bold green")

    @staticmethod
    def _load_all_docs(config) -> List[Doc]:
        metadata_path = config.METADATA_STORE
        metadata_file = Path(metadata_path)
        
        if not metadata_file.exists():
            raise FileNotFoundError(
                f"FATAL: Metadata file not found at '{metadata_path}'. "
                f"Please run the indexing script first: python index_documents.py"
            )

        console.log(f"  [Loader] Loading metadata from '{metadata_path}'...")
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata_list = json.load(f)
            
            docs = []
            for i, meta_chunk in enumerate(metadata_list):
                content = meta_chunk.get("content", "")
                if not content or not content.strip():
                    continue
                docs.append(Doc(id=i, text=content, meta=meta_chunk))
            return docs
        except Exception as e:
            raise RuntimeError(f"Failed to load or parse metadata file '{metadata_path}': {e}")

    def retrieve(self, query: str, top_k_override: int = None, bm25_k_override: int = None, fusion_k_override: int = None, **kwargs) -> List[RetrievalResult]:
        if not query or not query.strip(): return []
        
        bm25_k = bm25_k_override if bm25_k_override is not None else self.config.BM25_K
        fusion_k = fusion_k_override if fusion_k_override is not None else self.config.FUSION_K
        top_k = top_k_override if top_k_override is not None else self.config.TOP_K

        dense_hits = self.dense_retriever.search(query, top_k=bm25_k) if self.dense_retriever else []
        bm25_hits = self.lexical_retriever.search(query, top_k=bm25_k) if self.lexical_retriever else []
        
        if dense_hits and bm25_hits:
            fused_hits = _rrf_fusion(dense_hits, bm25_hits, k=fusion_k, rrf_k=self.config.RRF_K)
        elif bm25_hits:
            fused_hits = bm25_hits[:fusion_k]
        else:
            fused_hits = dense_hits[:fusion_k]
        fused_hits_map = dict(fused_hits)
        
        candidate_docs = [self.doc_map[doc_id] for doc_id, _ in fused_hits if doc_id in self.doc_map]
        
        if not candidate_docs: return []
        
        if self.reranker:
            reranked_results = self.reranker.rerank(query, candidate_docs, top_k=top_k)
            final_results = [
                RetrievalResult(doc=doc, score=fused_hits_map.get(doc.id, 0.0), rerank_score=score)
                for doc, score in reranked_results
            ]
        else:
            final_results = [
                RetrievalResult(doc=self.doc_map[doc_id], score=score)
                for doc_id, score in fused_hits[:top_k] if doc_id in self.doc_map
            ]
        
        return final_results

def get_retriever(config):
    return HybridRetriever(config)
