# แผนภาพ Mermaid: ภาพรวมสถาปัตยกรรมระบบ H2L

**ภาพที่ 3.2 ภาพรวมสถาปัตยกรรมระบบ H2L (Two-Level Hierarchical RAG with Polarity Gates)**

```mermaid
flowchart TB
    IN["ข้อความกรณีศึกษาแบบไร้โครงสร้าง<br/>Unstructured Case Text"] --> PREP["Text Preparation<br/>Clean + Normalize"]

    subgraph KB["ฐานความรู้และดัชนี — Knowledge Base &amp; Index"]
        TAX["Problem Taxonomy<br/>problem_codes.json<br/>34 กลุ่ม · 202 รหัส<br/>keywords + severity"]
        DOCS["คลังเอกสารอ้างอิง<br/>Recursive Chunking<br/>100–2000 ตัวอักษร · overlap 300"]
        IDX["LanceDB Vector Store<br/>multilingual-e5-base · 768 มิติ"]
        DOCS --> IDX
    end

    subgraph DET["1) การตรวจจับปัญหา — Two-Layer Detection"]
        L1["L1 Detection<br/>Keyword + Context Rules<br/>raw = 0.50 + match + cov + spec + phrase + rep<br/>final = clamp(raw × conf_mult, 0.05, 0.95)"]
        L1 --> CLR["พบปัญหาชัดเจน — Clear Path<br/>context_valid · conf_mult ≥ 0.8 · level=L1"]
        L1 --> NV["L1-NeedsValidation<br/>กำกวม / conflict"]
        L1 --> FLT["Filtered<br/>context_valid=False · conf &lt; 0.30"]
        NV --> L2["L2 LLM Semantic Validation<br/>valid+ctx → × 1.2 (cap 0.95)<br/>valid+bad ctx → ≤ 0.40<br/>Safety Net sev ≥ 4 · Implicit conf=0.75"]
        CLR --> PS["Final Problem Set<br/>keep confidence ≥ 0.25"]
        L2 --> PS
    end

    subgraph RET["2) การค้นคืนเอกสาร — Hybrid Retrieval (ขนาน)"]
        DENSE["Dense Retrieval<br/>e5 embeddings"]
        BM25["ThaiBM25<br/>lexical · K=25"]
        RRF["Reciprocal Rank Fusion<br/>k=60"]
        RERANK["Reranker<br/>bge-reranker-v2-m3 · top-k=15"]
        DENSE --> RRF
        BM25 --> RRF
        RRF --> RERANK
    end

    subgraph SCORE["3) การให้คะแนน — H2L Scoring + Polarity Gates"]
        GATES["Contextual Polarity Gates<br/>G_neg (window 30 · λ=0.6)<br/>G_len · G_sub (0.85)"]
        H2L["H2L Scoring<br/>detect .35 · semantic .30<br/>prior .15 · specificity .10 · negation .10"]
        GATES --> H2L
    end

    PREP --> L1
    PREP --> DENSE
    PREP --> BM25
    TAX -.-> L1
    IDX --> DENSE
    PS --> H2L
    RERANK --> H2L
    H2L --> OUT["ผลลัพธ์สุดท้าย — Output<br/>Detected Problems + Ranked Documents<br/>S_final = S_rerank × exp(α_eff × meanΦ) × P(rel | profile)"]

    classDef io fill:#e8f0fe,stroke:#1a73e8,color:#174ea6;
    classDef keep fill:#e6f4ea,stroke:#34a853,color:#0b6b2f;
    classDef drop fill:#fce8e6,stroke:#ea4335,color:#a50e0e;
    classDef wait fill:#fef7e0,stroke:#f9ab00,color:#7a5900;
    class IN,OUT io;
    class CLR,PS keep;
    class FLT drop;
    class NV,L2 wait;
```

**คำบรรยายภาพ:** ระบบ H2L รับข้อความกรณีศึกษาแบบไร้โครงสร้าง แล้วแยกการประมวลผลออกเป็นสองเส้นทางขนานจากขั้นเตรียมข้อความเดียวกัน เส้นทางแรกคือการตรวจจับปัญหาแบบสองชั้น (L1 เชิงกฎ/คะแนนความเชื่อมั่น และ L2 ด้วย LLM พร้อมกลไก Safety Net และการตรวจปัญหาแฝง) เพื่อให้ได้ชุดรหัสปัญหาสุดท้าย เส้นทางที่สองคือการค้นคืนเอกสารแบบไฮบริด (Dense + ThaiBM25 → RRF → Reranker) ทั้งสองเส้นทางบรรจบกันที่ชั้น H2L Scoring ซึ่งผสานคุณลักษณะของปัญหากับคะแนนเอกสาร และควบคุมผลบวกลวงด้วย Contextual Polarity Gates ก่อนสรุปเป็นผลลัพธ์สุดท้าย ค่าพารามิเตอร์ทั้งหมดอ้างอิงจาก implementation จริง
