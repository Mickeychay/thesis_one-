# ชุด Prompt สำหรับสร้างภาพการทำงานของ H2L ใน GPT (ภาพ / DALL·E)

> วิธีใช้: คัดลอกแต่ละ prompt ไปวางใน ChatGPT (โหมดสร้างภาพ) ทีละภาพ
> เคล็ดลับ: โมเดลภาพมักสะกดข้อความยาวๆ ผิด — แนะนำใช้ป้ายข้อความ **ภาษาอังกฤษสั้นๆ** ตามด้านล่าง
> ถ้าต้องการไดอะแกรมที่ตัวอักษรเป๊ะ 100% ให้ใช้ Mermaid (มีอยู่แล้วใน diagram_h2l_architecture.md) แทนภาพ AI

---

## ภาพที่ 1 — สถาปัตยกรรมรวมทั้งระบบ (System Architecture)

```
A clean, modern technical architecture diagram, horizontal flow, flat design,
soft blue and teal palette, white background, rounded rectangle nodes, clear arrows.

Title at top: "H2L — Two-Level Hierarchical RAG with Polarity Gates"

Left: a box "Case Text (unstructured)".
It splits into TWO parallel branches:

Branch A (top), labeled "Problem Detection":
  "L1 Detection (keyword + context rules)" -> "L2 Validation (LLM + Safety Net)" -> "Final Problem Set".

Branch B (bottom), labeled "Hybrid Retrieval":
  two parallel boxes "Dense Retrieval (e5, 768-dim)" and "BM25 (lexical)" ->
  merge into "RRF Fusion (k=60)" -> "Cross-Encoder Rerank".

Both branches converge into a central highlighted box:
  "H2L Scoring + Polarity Gates".

It points to a final box on the right: "Ranked Documents + Detected Problems".

Minimalist, professional, presentation slide style, no clutter, legible English labels only.
```

---

## ภาพที่ 2 — Two-Stage Hybrid Retrieval (ขยายเฉพาะการค้นคืน)

```
A horizontal pipeline diagram, flat modern style, blue/teal accents, white background.

Step 1 (left): a box "Query" splits into two parallel boxes:
  "Dense Retrieval — 25 candidates" (semantic, vector icon)
  "BM25 Retrieval — 25 candidates" (lexical, magnifier icon)

Step 2 (middle): both arrows merge into "RRF Fusion (k=60) -> 30 docs",
  with a small funnel icon to show narrowing down.

Step 3 (right): "Cross-Encoder Reranker (bge-reranker-v2-m3)" ->
  final box "Top 15 Documents".

Use a funnel/filter visual metaphor: wide on the left, narrow on the right
(25+25 -> 30 -> 15). Clean infographic, English labels, presentation quality.
```

---

## ภาพที่ 3 — H2L Scoring (สมการ + 5 คุณลักษณะ)

```
A clean infographic explaining a scoring formula, flat design, soft blue palette,
white background, presentation style.

Center-top: the formula in a highlighted box:
  "S_final = S_rerank x exp(alpha x weighted features) x P(rel | profile)"

Below it, FIVE feature cards arranged in a row, each a rounded rectangle with a
small icon and a percentage badge:
  1. "Detection Confidence — 35%"
  2. "Semantic Relevance — 30%"
  3. "Problem Prior — 15%"
  4. "Specificity / IDF — 10%"
  5. "Negation Gate — 10%"

A small donut chart on the side showing weights summing to 100%, with the first two
slices (35% + 30%) highlighted as the largest. Modern, legible English labels.
```

---

## ภาพที่ 4 — Contextual Polarity Gates (3 ประตู)

```
A clean infographic of three quality-control "gates" multiplying together,
flat modern style, white background, blue/green/orange accent colors.

Three gate cards in a row, each shaped like a control gate/valve:
  Gate 1 "Negation Gate (G_neg)" — icon of a crossed-out word, note "window 30 chars, lambda 0.6"
  Gate 2 "Length Gate (G_len)" — icon of a short vs long text bar, note "log scale"
  Gate 3 "Subject Gate (G_sub)" — icon of two people with one highlighted, note "other-subject 0.85"

The three gates connect with multiplication symbols (x) into a final box:
  "G_polarity = G_neg x G_len x G_sub".

Below, a small example row: text "patient narrates ..." -> green check "1.00",
text "negation present" -> orange "0.40". Professional, legible English labels.
```

---

## ภาพที่ 5 (ทางเลือก) — เปรียบเทียบ Funnel ปริมาณเอกสาร

```
A simple funnel infographic showing document count shrinking through stages,
flat design, blue gradient, white background, large readable numbers:

Top (widest): "50 candidates (25 Dense + 25 BM25)"
Next: "30 after RRF Fusion"
Next: "15 after Cross-Encoder Rerank"
Bottom (narrowest, highlighted): "Final Ranked Documents".

Vertical funnel shape, clean, minimal, presentation slide style, English labels only.
```

---

## หมายเหตุการใช้งาน

- ถ้า GPT สะกดคำผิดบนภาพ: สั่งเพิ่ม "keep all text labels short and in English, double-check spelling"
- อยากได้โทนสีตรงกับสไลด์: เพิ่ม "primary color #1a73e8 (blue), accent teal" ในทุก prompt
- ต้องการภาพแนวนอนสำหรับสไลด์ 16:9: เพิ่ม "wide 16:9 aspect ratio" ท้าย prompt
- ถ้าต้องการความถูกต้องของข้อความ/ตัวเลขแบบเป๊ะ (สำหรับเล่มวิทยานิพนธ์) แนะนำใช้ Mermaid diagram ที่มีอยู่แล้วใน `diagram_h2l_architecture.md` แล้ว export เป็น PNG/SVG จะคมและถูกต้องกว่าภาพ AI
