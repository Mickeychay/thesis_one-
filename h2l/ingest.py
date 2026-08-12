#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Data Pipeline: Document Processing Utilities
=============================================
Consolidated from: parser.py, merge_chunks.py, add_source_metadata.py, auto_tag_documents.py

Pipeline: parse → merge → add_source_metadata → auto_tag

Usage:
    # Parse documents
    python ingest.py parse

    # Merge chunks
    python ingest.py merge

    # Add source metadata
    python ingest.py add-source

    # Auto-tag documents
    python ingest.py auto-tag <input_file>
"""

from __future__ import annotations
import re
import json
import hashlib
import unicodedata
import logging
import shutil
import uuid
import sys
import argparse
from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass, asdict
from collections import Counter

logger = logging.getLogger(__name__)


# =============================================================================
# Section 1: Document Parsing & Chunking (from parser.py)
# =============================================================================

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        return iterable
    tqdm.write = print

try:
    from pythainlp import word_tokenize
    from pythainlp.util import normalize as th_normalize
except ImportError:
    word_tokenize = None
    th_normalize = None

try:
    from h2l.config import get_config
    _config = get_config()
except ImportError:
    _config = None


@dataclass
class Chunk:
    chunk_id: str
    source_document: str
    title: str
    content: str
    chunk_type: str
    chunk_index: int
    char_count: int
    word_count: int
    thai_ratio: float

    def to_dict(self) -> Dict:
        return asdict(self)

    @property
    def is_valid(self) -> bool:
        if _config and hasattr(_config, 'parsing'):
            return (
                self.char_count >= _config.parsing.min_chunk_length and
                self.char_count <= _config.parsing.max_chunk_length and
                self.thai_ratio >= _config.parsing.min_thai_ratio
            )
        return self.char_count >= 50 and self.thai_ratio >= 0.1


class TextProcessor:
    @staticmethod
    def normalize(text: str) -> str:
        text = unicodedata.normalize("NFC", text)
        if th_normalize:
            try:
                text = th_normalize(text)
            except Exception:
                pass
        return re.sub(r'\s+', ' ', text).strip()

    @staticmethod
    def clean(text: str) -> str:
        text = re.sub(r"มาตรฐานการปฏิบัติงานการบริการผู้ป่วยคลินิกสังคมสงเคราะห์.*\n", "", text, flags=re.IGNORECASE)
        text = re.sub(r"แนวทางการวิเคราะห์และออกแบบการดูแลทางสังคมฯ\s*\d*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"PageNumber:\s*\d+", "", text, flags=re.IGNORECASE)
        text = re.sub(r'\n\s*\n', '\n\n', text)
        return text.strip()

    @staticmethod
    def calculate_thai_ratio(text: str) -> float:
        if not text: return 0.0
        thai_chars = sum(1 for c in text if '\u0E00' <= c <= '\u0E7F')
        return thai_chars / len(text) if len(text) > 0 else 0.0

    @staticmethod
    def count_words(text: str) -> int:
        if word_tokenize:
            try:
                return len(word_tokenize(text, engine="newmm", keep_whitespace=False))
            except Exception:
                pass
        return len(text.split())

    @staticmethod
    def generate_chunk_id(source: str, content: str, index: int) -> str:
        content_hash = hashlib.md5(f"{source}:{content[:100]}:{index}".encode('utf-8')).hexdigest()[:12]
        return f"chunk_{content_hash}"


class RecursiveChunker:
    def __init__(self, source: str):
        self.source = source
        self.processor = TextProcessor()

    def chunk(self, text: str) -> List[Chunk]:
        text = self.processor.clean(text)
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]

        all_sub_chunks = []
        for para in paragraphs:
            sub_chunks = self._split_text_recursively(para)
            all_sub_chunks.extend(sub_chunks)

        final_chunks = []
        for i, content in enumerate(all_sub_chunks):
            chunk = self._create_chunk(content, i)
            if chunk.is_valid:
                final_chunks.append(chunk)
        return final_chunks

    def _split_text_recursively(self, text: str) -> List[str]:
        max_len = _config.parsing.max_chunk_length if _config and hasattr(_config, 'parsing') else 2000
        overlap = _config.parsing.overlap if _config and hasattr(_config, 'parsing') else 200

        if len(text) <= max_len:
            return [text]

        split_pos = text.rfind(' ', 0, max_len)
        if split_pos == -1:
            split_pos = max_len

        chunk1 = text[:split_pos]
        rest_start = max(0, split_pos - overlap)
        chunk2_rest = text[rest_start:]
        return [chunk1] + self._split_text_recursively(chunk2_rest)

    def _create_chunk(self, content: str, index: int) -> Chunk:
        title = content.split('\n')[0][:100]
        return Chunk(
            chunk_id=self.processor.generate_chunk_id(self.source, content, index),
            source_document=self.source,
            title=title,
            content=self.processor.normalize(content),
            chunk_type="recursive_section",
            chunk_index=index,
            char_count=len(content),
            word_count=self.processor.count_words(content),
            thai_ratio=self.processor.calculate_thai_ratio(content)
        )


def run_parse():
    """Parse processed text files into chunks"""
    processed_dir = Path("data/processed")
    chunked_dir = Path("data/chunked")
    chunked_dir.mkdir(parents=True, exist_ok=True)

    text_files = list(processed_dir.glob("*_typhoon.txt"))
    if not text_files:
        logger.error(f"ไม่พบไฟล์ text ใน '{processed_dir}'. กรุณา run `load.py` ก่อน")
        return

    total_chunks_processed = 0
    logger.info(f"พบ {len(text_files)} ไฟล์ที่ต้องทำการ Parse...")
    for text_file in tqdm(text_files, desc="Parsing Documents"):
        content = text_file.read_text(encoding="utf-8")
        parser = RecursiveChunker(source=text_file.name)
        valid_chunks = parser.chunk(content)

        tqdm.write(f"  -> Parsed {text_file.name}: Found {len(valid_chunks)} valid chunks.")

        if valid_chunks:
            output_path = chunked_dir / f"{text_file.stem}_chunks.json"
            chunks_to_save = [c.to_dict() for c in valid_chunks]
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(chunks_to_save, f, ensure_ascii=False, indent=2)
            tqdm.write(f"  -> Saved {len(chunks_to_save)} chunks to '{output_path}'")
            total_chunks_processed += len(chunks_to_save)

    if total_chunks_processed > 0:
        logger.info(f"✅ Successfully parsed all files. Total chunks: {total_chunks_processed}")
    else:
        logger.warning("No valid chunks were generated.")


# =============================================================================
# Section 2: Chunk Merging (from merge_chunks.py)
# =============================================================================

def run_merge(in_dir: str = "data/chunked", out_path: str = "data/chunks.json"):
    """Merge chunked JSON files into a single chunks.json"""
    in_dir_path = Path(in_dir)
    out_path_path = Path(out_path)

    if not in_dir_path.exists():
        print(f"❌ ไม่พบโฟลเดอร์ {in_dir_path.resolve()}")
        sys.exit(1)

    all_items = []
    for fp in sorted(in_dir_path.glob("*.json")):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"⚠️ ข้ามไฟล์ {fp.name}: {e}", file=sys.stderr)
            continue

        if isinstance(data, list):
            all_items.extend(data)
        elif isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, dict):
                    v = {**v, "chunk_id": v.get("chunk_id", k)}
                all_items.append(v)

    clean = []
    for i, d in enumerate(all_items):
        if not isinstance(d, dict):
            continue
        d = dict(d)
        d.setdefault("chunk_id", d.get("id", f"chunk_{i:06d}_{uuid.uuid4().hex[:6]}"))
        txt = d.get("text") or d.get("content") or d.get("content_snippet", "")
        d["text"] = txt
        d.setdefault("content_snippet", txt[:400])
        clean.append(d)

    out_path_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path_path, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)

    print(f"✅ รวมได้ {len(clean):,} chunks → {out_path_path}")


# =============================================================================
# Section 3: Source Metadata (from add_source_metadata.py)
# =============================================================================

def clean_filename(filename: str) -> str:
    """ทำความสะอาดชื่อไฟล์โดยลบ suffix ที่เกิดจาก processing"""
    if not filename or not filename.strip():
        return "เอกสารทั่วไป"

    clean_name = filename.strip()
    processing_patterns = [
        r'_compressed_typhoon_chunks\.json$',
        r'_compressed_typhoon\.txt$',
        r'_compressed\.pdf$',
        r'_chunks\.json$',
        r'\.json$', r'\.txt$', r'\.pdf$'
    ]
    for pattern in processing_patterns:
        clean_name = re.sub(pattern, '', clean_name)

    clean_name = clean_name.strip()
    if not clean_name:
        clean_name = Path(filename.strip()).stem or "เอกสารทั่วไป"
    return clean_name


def get_source_from_filename(filename: str) -> str:
    """แปลงชื่อไฟล์เป็น source name"""
    source = clean_filename(filename)
    if not source or source == "เอกสารทั่วไป":
        if filename and filename.strip():
            source = Path(filename.strip()).stem
    return source if source and source.strip() else "เอกสารทั่วไป"


def run_add_source(input_file: str = "data/chunks.json",
                   output_file: str = "data/chunks_with_source.json",
                   backup: bool = True):
    """Add source metadata to chunks"""
    print("=" * 70)
    print("🔄 Adding Source Metadata to chunks.json")
    print("=" * 70)

    input_path = Path(input_file)
    if not input_path.exists():
        print(f"❌ Error: {input_file} not found!")
        return

    if backup:
        backup_file = input_path.parent / f"{input_path.stem}_backup{input_path.suffix}"
        try:
            shutil.copy2(input_path, backup_file)
        except Exception as e:
            print(f"⚠️ Warning: Could not create backup: {e}")

    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            chunks = json.load(f)
    except Exception as e:
        print(f"❌ Error loading file: {e}")
        return

    if not chunks:
        print("❌ Error: No chunks found!")
        return

    print(f"   Found {len(chunks)} chunks")
    source_counts = Counter()

    for i, chunk in enumerate(chunks):
        filename = chunk.get("source_document", "").strip()
        source = get_source_from_filename(filename) if filename else "เอกสารทั่วไป"
        chunk["source"] = source
        source_counts[source] += 1

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Updated {len(chunks)} chunks with source metadata")
    print(f"📈 Unique Sources: {len(source_counts)}")
    for source, count in sorted(source_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"   {source:<50} {count:>6} chunks")


# =============================================================================
# Section 4: Auto-Tagging (from auto_tag_documents.py)
# =============================================================================

class DocumentTagger:
    """Auto-tag documents with problem codes based on keyword matching"""

    def __init__(self, problem_codes_path: str = "data/problem_codes.json"):
        self.problem_codes = self._load_problem_codes(problem_codes_path)
        print(f"✅ Loaded {len(self.problem_codes)} problem codes")
        self._build_keyword_index()

    def _load_problem_codes(self, filepath: str) -> Dict:
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Problem codes not found: {filepath}")
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _build_keyword_index(self):
        self.keyword_index = {}
        for code, info in self.problem_codes.items():
            for keyword in info.get('keywords', []):
                keyword_lower = keyword.lower()
                if keyword_lower not in self.keyword_index:
                    self.keyword_index[keyword_lower] = []
                self.keyword_index[keyword_lower].append(code)

    def tag_document(self, text: str, title: str = "", threshold: int = 2) -> List[str]:
        if not text:
            return []
        full_text = f"{title} {text}".lower()
        problem_matches = Counter()
        for code, info in self.problem_codes.items():
            for keyword in info.get('keywords', []):
                if keyword.lower() in full_text:
                    problem_matches[code] += 1
        return [code for code, count in problem_matches.items() if count >= threshold]

    def tag_metadata_file(self, input_path: str, output_path: str = None, threshold: int = 2) -> str:
        input_file = Path(input_path)
        if not input_file.exists():
            raise FileNotFoundError(f"Metadata file not found: {input_path}")

        print(f"📂 Loading metadata from {input_file}...")
        try:
            with open(input_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                metadata = data.get("cases") or data.get("chunks") or [data]
            elif isinstance(data, list):
                metadata = data
            else:
                metadata = []
        except Exception as e:
            print(f"Error loading {input_file}: {e}")
            return

        tagged_count = 0
        total_tags = 0
        for i, doc in enumerate(metadata):
            content = doc.get('case_description') or doc.get('content') or doc.get('case_text', '')
            title = doc.get('title') or doc.get('case_id', '')
            problem_codes = self.tag_document(content, title=title, threshold=threshold)
            doc['problem_codes'] = problem_codes
            if problem_codes:
                tagged_count += 1
                total_tags += len(problem_codes)

        print(f"✅ Tagged: {tagged_count}/{len(metadata)} ({tagged_count/len(metadata)*100:.1f}%)")

        if output_path is None:
            output_path = str(input_file.parent / f"{input_file.stem}_tagged{input_file.suffix}")

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        print(f"✅ Saved to {output_path}")
        return output_path


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Data Pipeline: parse → merge → add-source → auto-tag')
    sub = parser.add_subparsers(dest='command')

    sub.add_parser('parse', help='Parse processed text files into chunks')
    sub.add_parser('merge', help='Merge chunked JSON files into chunks.json')
    sub.add_parser('add-source', help='Add source metadata to chunks')

    tag_parser = sub.add_parser('auto-tag', help='Auto-tag documents with problem codes')
    tag_parser.add_argument('input_file', help='Input metadata JSON')
    tag_parser.add_argument('--output', '-o', help='Output file')
    tag_parser.add_argument('--threshold', '-t', type=int, default=2)

    args = parser.parse_args()

    if args.command == 'parse':
        run_parse()
    elif args.command == 'merge':
        run_merge()
    elif args.command == 'add-source':
        run_add_source()
    elif args.command == 'auto-tag':
        tagger = DocumentTagger()
        tagger.tag_metadata_file(args.input_file, args.output, args.threshold)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
