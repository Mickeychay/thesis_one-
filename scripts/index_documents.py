#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Document Indexing Script
------------------------
สร้าง Vector Database และ metadata.json จากเอกสาร
ค่าเริ่มต้นใช้เอกสาร production ใน data/chunked/ และป้องกัน label leakage
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import Config, get_config


LABEL_KEYS = {
    "expected_diagnosis",
    "expected_diagnosis_full",
    "problem_codes",
    "relevant_keywords",
}


def _safe_document_chunk(raw: Dict, doc_id: int, default_source: str) -> Dict:
    """Normalize a real document chunk and strip label/evaluation-only fields."""
    content = raw.get("content") or raw.get("text") or raw.get("case_description") or ""
    content = str(content).strip()
    if not content:
        return {}

    chunk = {
        "doc_id": doc_id,
        "content": content,
        "text": content,
        "chunk_id": raw.get("chunk_id") or raw.get("case_id") or f"chunk_{doc_id}",
        "source_document": raw.get("source_document", default_source),
        "source": raw.get("source", default_source),
        "title": raw.get("title", f"Document chunk {doc_id}"),
        "chunk_type": raw.get("chunk_type", "production_document"),
        "chunk_index": raw.get("chunk_index", doc_id),
        "char_count": raw.get("char_count", len(content)),
        "word_count": raw.get("word_count", len(content.split())),
        "thai_ratio": raw.get("thai_ratio"),
        "data_source": "production_docs",
    }
    return {k: v for k, v in chunk.items() if k not in LABEL_KEYS}


def load_production_documents(input_dir: str = "data/chunked") -> List[Dict]:
    """Load real document chunks without answer labels."""
    input_path = Path(input_dir)
    if not input_path.exists():
        print(f"❌ ไม่พบโฟลเดอร์เอกสาร production: {input_dir}")
        return []

    json_files = sorted(input_path.glob("*.json"))
    if not json_files:
        print(f"❌ ไม่พบไฟล์ .json ใน {input_dir}")
        return []

    chunks = []
    doc_counter = 0
    print(f"✅ Loading production chunks from: {input_dir}")
    for file_path in json_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"⚠️  Skip {file_path.name}: {e}")
            continue

        records = data if isinstance(data, list) else data.get("chunks", [])
        for raw in records:
            if not isinstance(raw, dict):
                continue
            normalized = _safe_document_chunk(raw, doc_counter, file_path.name)
            if normalized:
                chunks.append(normalized)
                doc_counter += 1

    print(f"✅ Loaded {len(chunks)} production chunks with label fields stripped")
    return chunks


def load_ground_truth_documents(
    ground_truth_file: str = "expanded_ground_truth.json",
    include_labels: bool = False
) -> List[Dict]:
    """Load ground-truth cases for explicit evaluation indexing only."""
    print(f"✅ กำลังโหลดข้อมูล Ground Truth จาก: {ground_truth_file}")
    gt_path = Path(ground_truth_file)
    
    if not gt_path.exists():
        print(f"❌ CRITICAL: ไม่พบไฟล์ Ground Truth ที่ '{ground_truth_file}'")
        print("   โปรดตรวจสอบว่าไฟล์ expanded_ground_truth.json อยู่ในตำแหน่งที่ถูกต้อง")
        return []

    try:
        with open(gt_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # ดึง list ของเคสออกมา
        test_cases = data.get("cases", [])
        if not test_cases:
            print(f"❌ CRITICAL: ไม่พบ Key 'cases' ใน {ground_truth_file}")
            return []

        valid_chunks = []
        doc_counter = 0
        
        print(f"🔄 กำลังแปลง Ground Truth {len(test_cases)} เคส เพื่อสร้าง Evaluation Index...")
        
        for case in test_cases:
            content = case.get("case_description")
            if not content or not content.strip():
                continue

            normalized_chunk = {
                "doc_id": doc_counter,
                "content": content,
                "text": content,
                "chunk_id": case.get("case_id", f"chunk_{doc_counter}"),
                "source_document": f"ground_truth_{case.get('case_id', 'N/A')}",
                "source": case.get("category", "Ground Truth"),
                "title": f"Case {case.get('case_id', 'N/A')}",
                "complexity": case.get("complexity", "unknown"),
                "data_source": "ground_truth_eval",
            }

            if include_labels:
                expected_diag = case.get("expected_diagnosis", {})
                problem_list = expected_diag.get("problem_list", [])
                ground_truth_codes = [p.get("code") for p in problem_list if p.get("code")]
                normalized_chunk.update({
                    "problem_codes": ground_truth_codes,
                    "relevant_keywords": case.get("relevant_keywords", {}),
                    "expected_diagnosis_full": expected_diag,
                    "data_source": "ground_truth_label_index",
                })
            
            valid_chunks.append(normalized_chunk)
            doc_counter += 1
        
        print(f"✅ แปลงข้อมูลสำเร็จ {len(valid_chunks)} เคส พร้อมสำหรับ Indexing")
        return valid_chunks

    except Exception as e:
        print(f"❌ CRITICAL: เกิดข้อผิดพลาดขณะโหลด {ground_truth_file}: {e}")
        return []


def load_parsed_documents(
    source: str = "production_docs",
    input_dir: str = "data/chunked",
    ground_truth_file: str = "expanded_ground_truth.json",
    include_labels: bool = False
) -> List[Dict]:
    """Backward-compatible loader with explicit data source selection."""
    if source == "production_docs":
        return load_production_documents(input_dir=input_dir)
    if source == "ground_truth":
        return load_ground_truth_documents(
            ground_truth_file=ground_truth_file,
            include_labels=include_labels
        )
    raise ValueError(f"Unsupported source: {source}")


def save_metadata(chunks: List[Dict], config):
    """Saves the standardized metadata file."""
    metadata_path = Path(config.METADATA_STORE)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    print(f"✅ Metadata file saved to: {metadata_path}")

def create_lancedb_index(chunks: List[Dict], config):
    """Create LanceDB index and metadata.json"""
    try:
        import lancedb
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("❌ LanceDB or sentence-transformers not installed. Please run: pip install lancedb pyarrow sentence-transformers")
        return None
    
    print("\n🔨 Creating LanceDB index...")
    print(f"📥 Loading embedding model: {config.EMBEDDING_MODEL} (Device: {config.DEVICE})")
    
    model = SentenceTransformer(config.EMBEDDING_MODEL, device=config.DEVICE)
    texts = [chunk.get('content', '') for chunk in chunks]
    
    print(f"🧮 Generating embeddings for {len(texts)} chunks...")
    embeddings = model.encode(
        texts, show_progress_bar=True, batch_size=16, 
        convert_to_numpy=True, normalize_embeddings=True
    )
    
    data_for_db = []
    for i, chunk in enumerate(chunks):
        data_for_db.append({
            "id": i,
            "text": chunk.get("content"),
            "vector": embeddings[i].tolist(),
            "metadata_json": json.dumps(chunk, ensure_ascii=False)
        })
    
    db_path = Path(config.DB_PATH).parent
    db_path.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(db_path))
    
    table_name = Path(config.DB_PATH).name
    if table_name in db.table_names():
        db.drop_table(table_name)
    
    table = db.create_table(table_name, data=data_for_db, mode="overwrite")
    print(f"✅ LanceDB index created successfully! Documents: {len(table)}")
    save_metadata(chunks, config)
    return table

def create_faiss_index(chunks: List[Dict], config):
    """Create FAISS index and metadata.json"""
    try:
        import faiss
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("❌ FAISS or sentence-transformers not installed. Please run: pip install faiss-cpu sentence-transformers")
        return None
    
    print("\n🔨 Creating FAISS index...")
    model = SentenceTransformer(config.EMBEDDING_MODEL, device=config.DEVICE)
    texts = [chunk.get('content', '') for chunk in chunks]
    
    print(f"🧮 Generating embeddings for {len(texts)} chunks...")
    embeddings = model.encode(
        texts, show_progress_bar=True, batch_size=32, 
        convert_to_numpy=True, normalize_embeddings=True
    )
    
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatL2(dimension)
    index.add(embeddings.astype('float32'))
    
    db_path = Path(config.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    faiss.write_index(index, str(db_path))
    print(f"✅ FAISS index saved to: {db_path}")
    save_metadata(chunks, config)
    return index

def create_chromadb_index(chunks: List[Dict], config):
    """Create ChromaDB index"""
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("❌ ChromaDB or sentence-transformers not installed. Please run: pip install chromadb sentence-transformers")
        return None

    print("\n🔨 Creating ChromaDB index...")
    model = SentenceTransformer(config.EMBEDDING_MODEL, device=config.DEVICE)
    texts = [chunk.get('content', '') for chunk in chunks]

    print(f"🧮 Generating embeddings for {len(texts)} chunks...")
    embeddings = model.encode(
        texts, show_progress_bar=True, batch_size=16,
        convert_to_numpy=True, normalize_embeddings=True
    ).tolist()

    db_path = Path(config.DB_PATH).parent
    client = chromadb.PersistentClient(path=str(db_path))

    collection_name = Path(config.DB_PATH).name
    try:
        client.delete_collection(name=collection_name)
    except Exception:
        pass
    
    collection = client.create_collection(name=collection_name)

    ids = [str(chunk['doc_id']) for chunk in chunks]
    
    print(f"➕ Adding {len(chunks)} documents to the collection...")
    batch_size = 500
    for i in tqdm(range(0, len(chunks), batch_size), desc="Adding batches"):
        collection.add(
            ids=ids[i:i + batch_size],
            embeddings=embeddings[i:i + batch_size],
            documents=texts[i:i + batch_size]
        )

    print(f"✅ ChromaDB index created successfully! Documents: {collection.count()}")
    save_metadata(chunks, config)
    return collection


def _force_eval_output_paths(config):
    """Route ground-truth indexes to an eval-specific path."""
    db_path = Path(config.DB_PATH)
    path_text = str(db_path).lower()
    if any(token in path_text for token in ["eval", "demo", "ground_truth", "gt"]):
        return config

    config.DB_PATH = str(db_path.parent / f"{db_path.name}_eval_ground_truth")
    metadata_path = Path(config.METADATA_STORE)
    config.METADATA_STORE = str(metadata_path.parent / "metadata_eval_ground_truth.json")
    print("⚠️  Ground-truth source selected; routing output to evaluation-specific paths:")
    print(f"   - DB Path: {config.DB_PATH}")
    print(f"   - Metadata: {config.METADATA_STORE}")
    return config


def main(argv=None):
    """Main indexing function"""
    parser = argparse.ArgumentParser(description="Build vector index with data-source guardrails")
    parser.add_argument(
        "--source",
        choices=["production_docs", "ground_truth"],
        default="production_docs",
        help="Data source to index. Default indexes real document chunks only."
    )
    parser.add_argument(
        "--input-dir",
        default="data/chunked",
        help="Directory of production chunk JSON files"
    )
    parser.add_argument(
        "--ground-truth-file",
        default="expanded_ground_truth.json",
        help="Ground-truth JSON file for explicit evaluation indexing"
    )
    parser.add_argument(
        "--allow-ground-truth-index",
        action="store_true",
        default=getattr(Config, "ALLOW_GROUND_TRUTH_INDEX", False),
        help="Allow indexing ground-truth cases for evaluation-only corpus"
    )
    parser.add_argument(
        "--allow-label-index",
        action="store_true",
        help="Also store answer labels in metadata; evaluation-only and never production"
    )
    args = parser.parse_args(argv)

    print("="*70)
    print("🚀 Document Indexing Process")
    print("="*70)
    
    config = get_config()

    if args.source == "ground_truth":
        if not args.allow_ground_truth_index and not args.allow_label_index:
            print("\n❌ Refusing to index ground-truth cases by default.")
            print("💡 Use --allow-ground-truth-index for evaluation-only indexing.")
            print("💡 Use --allow-label-index only when metadata labels are explicitly needed for evaluation.")
            return 2
        config = _force_eval_output_paths(config)
        if args.allow_label_index:
            print("⚠️  LABEL INDEX ENABLED: problem codes and expected diagnosis will be stored in metadata.")
            print("⚠️  Use this corpus for evaluation/debugging only, never for production retrieval.")
    
    print(f"\n📊 Configuration:")
    print(f"   - Vector Backend: {config.DB_TYPE}")
    print(f"   - Embedding Model: {config.EMBEDDING_MODEL}")
    print(f"   - Device: {config.DEVICE}")
    print(f"   - DB Path: {config.DB_PATH}")
    print(f"   - Metadata Path: {config.METADATA_STORE}")
    print(f"   - Source: {args.source}")
    
    chunks = load_parsed_documents(
        source=args.source,
        input_dir=args.input_dir,
        ground_truth_file=args.ground_truth_file,
        include_labels=args.allow_label_index
    )
    
    if not chunks:
        print("\n❌ No valid documents found to index. Exiting.")
        return
    
    try:
        backend = config.DB_TYPE.lower()
        if backend in ["lancedb","lance"]:
            create_lancedb_index(chunks, config)
        elif backend == "faiss":
            create_faiss_index(chunks, config)
        elif backend in ["chroma", "chromadb"]:
            create_chromadb_index(chunks, config)
        else:
            print(f"❌ Unsupported backend: {config.DB_TYPE}")
            return
        
        print("\n" + "="*70)
        print("✅ Indexing completed successfully!")
        print("="*70)
        
    except Exception as e:
        print(f"\n❌ Indexing failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
