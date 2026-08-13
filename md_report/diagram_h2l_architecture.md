# แผนภาพ Mermaid: ภาพรวมสถาปัตยกรรมระบบ H2L

**ภาพที่ 3.2 ภาพรวมสถาปัตยกรรมระบบ H2L (Two-Level Hierarchical RAG with Polarity Gates)**

```mermaid
flowchart TB
    IN["1) ข้อความกรณีศึกษาแบบไร้โครงสร้าง<br/>Unstructured Case Text"] --> DET
    subgraph KB["ฐานความรู้และดัชนี — Knowledge Base & Index"]
        TAX["Problem Taxonomy<br/>34 กลุ่ม · 202 รหัส"]
        DOCS["คลังเอกสารสิทธิสวัสดิการ<br/>Recursive Chunk 100–2000 · overlap 300"]
        IDX["LanceDB Vector Store<br/>multilingual-e5-base (768d)"]
        DOCS -->|"Clean + Thai Normalization"| IDX
    end
    subgraph DET["2) การตรวจจับปัญหา — Two-Layer Detection"]
        L1["Layer 1: L1 Detection<br/>Keyword + Context Rules Matching<br/>conf = clamp(raw × conf_mult, 0.05, 0.95)"]
        L1 --> CLR["พบปัญหาชัดเจน (Clear Path)<br/>conf_mult ≥ 0.8 · level=L1"]
        L1 --> NV["กำกวม/ขัดแย้ง (Needs Validation)"]
        L1 --> FLT["Filtered<br/>context_valid=False และ conf < 0.3"]
        NV --> L2["Layer 2: L2 LLM Validation<br/>LLM Semantic Check<br/>Safety Net: Sev ≥ 4 AND context_valid AND conf ≥ 0.5<br/>Implicit Mining (default conf = 0.75)"]
        CLR --> PS["Final Detected Problem Set<br/>(keep confidence ≥ 0.25)"]
        L2 --> PS
    end
    PS --> QE["Query Expansion<br/>q' = q ⊕ ชื่อปัญหาที่ตรวจพบ"]
    subgraph RET["3) การค้นคืนเอกสารสองสาย — Dual-Path Hybrid Retrieval"]
        DENSE["Dense Retrieval<br/>multilingual-e5-base (K=25)"]
        BM25["ThaiBM25 Retrieval<br/>Lexical Search (K=25)"]
        RRF["Reciprocal Rank Fusion (RRF)<br/>k=60 → FUSION_K=30 candidates"]
        RERANK["Cross-Encoder Reranker<br/>bge-reranker-v2-m3<br/>30 candidates → top-15"]
        DENSE --> RRF
        BM25 --> RRF
        RRF --> RERANK
    end
    subgraph SCORE["4) การจัดอันดับ — H2L Scoring + Polarity Gates"]
        GATES["Sentence Polarity Gates<br/>G_neg (window 30 ตัวอักษรก่อน keyword)<br/>× G_len × G_sub (เฉพาะ severity ≥ 3)"]
        H2L["H2L Scoring Integration<br/>Φ = Detect(35%) + Semantic(30%) + Smoothed Prior(15%)<br/>+ IDF Specificity(10%) + Polarity(10%)<br/>× P(rel|profile) แยกเป็นตัวคูณ"]
        GATES --> H2L
    end
    QE --> DENSE
    QE --> BM25
    TAX -.-> L1
    IDX --> DENSE
    PS --> H2L
    RERANK --> H2L
    H2L --> OUT["5) สรุปผลลัพธ์ — Final Output<br/>Detected Problems + Ranked Welfare Documents<br/>พร้อมอธิบายเส้นทางการตัดสินใจ (Explainability)"]

    classDef io fill:#e8f0fe,stroke:#1a73e8,color:#174ea6;
    classDef keep fill:#e6f4ea,stroke:#34a853,color:#0b6b2f;
    classDef drop fill:#fce8e6,stroke:#ea4335,color:#a50e0e;
    classDef wait fill:#fef7e0,stroke:#f9ab00,color:#7a5900;
    class IN,OUT io;
    class CLR,PS keep;
    class FLT drop;
    class NV,L2 wait;
```

**คำบรรยายภาพ:** ระบบ H2L รับข้อความกรณีศึกษาแบบไร้โครงสร้าง แล้วทำการตรวจจับปัญหาแบบสองชั้น (L1 เชิงกฎ/คะแนนความเชื่อมั่น และ L2 ด้วย LLM พร้อมกลไก Safety Net และการตรวจปัญหาแฝง) เพื่อให้ได้ชุดรหัสปัญหาสุดท้าย ปัญหาที่พบจะถูกนำไปทำ Query Expansion ก่อนส่งเข้าสู่การค้นคืนเอกสารแบบ Dual-Path (Dense + ThaiBM25 → RRF) ซึ่งส่ง 30 อันดับแรกไปให้ Reranker คัดกรองเหลือ Top-15 ข้อมูลทั้งสองส่วนบรรจบกันที่ชั้น H2L Scoring ซึ่งผสานคุณลักษณะของปัญหากับคะแนนเอกสาร และควบคุมผลบวกลวงด้วย Contextual Polarity Gates ก่อนสรุปเป็นผลลัพธ์สุดท้าย ค่าพารามิเตอร์ทั้งหมดอ้างอิงจาก implementation จริง
