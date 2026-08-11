# HANDOFF — สถานะงานบท 4 (RQ2/RQ3/RQ4 + DOCX pipeline)

เขียนเมื่อจบเซสชัน 2026-08-10 ทุกตัวเลขในเอกสารนี้อ่านจากไฟล์จริงในเซสชันนั้น

---

## 1. สถานะ Git

Commit ที่ลงแล้ว (บน `main`):

| Hash | เรื่อง |
|:---|:---|
| `21ae5977a` | fix(RQ3/RQ4): เลิก monkey-patch เปลี่ยนเป็น `MATCHING_MODE` ผ่าน config |
| `0058390ae` | fix(ch4-docx): ฝังรูปเป็น picture จริง + เลิกทำเนื้อหาหายตอน inject |

**ยังไม่ commit** (`git diff --stat`):

```
 ablation_study.py                  | 168 ++++++++++++++++++++++++-------
 md_report/thesis_full_ch4_final.md |  18 ++--
 scripts/build_ch4_figures.py       | 104 ++++++++++++++++++++-
```

**Untracked:**

- `65130641_Riskie_Thesis_Glen_fixed.BACKUP_20260810_035816.docx` — ฐานก่อน inject ครั้งแรก
- `65130641_Riskie_Thesis_Glen_fixed.BACKUP_beforefigures_20260810_092454.docx`
- `ablation_results/rq3_real_95cases_final_console.log`
- `ablation_results/rq4_real_95cases_final_console.log`
- `output/figures_ch4/fig_4e_rq3_matching.png`

> ⚠️ **ยังไม่ได้รัน `pytest` หลังแก้ RQ2** ผลล่าสุดที่ยืนยันคือ **220 passed** ซึ่งเป็นสถานะ *ก่อน* rewrite RQ2 ให้รัน test suite เป็นขั้นแรกของเซสชันถัดไป

## 2. งานที่เสร็จแล้วในเซสชันนี้

### 2.1 RQ3 — soft vs hard matching (commit `21ae5977a`)

ต้นตอ: `create_h2l_retriever()` monkey-patch `_apply_h2l_scoring` ด้วย signature
`(results, problems)` แต่ `retrieve()` เรียกด้วย `(results, explicit_problems, query)`
→ TypeError ทุกเคส → `evaluate_strategy()` จับแล้วลองใหม่แบบไม่ส่ง `explicit_problems`
→ H2L scoring ไม่ทำงาน

หลักฐาน: แขน RQ3 `Keyword (Hard)` เดิม และแขน RQ4 `Uniform Prior` เดิม
ให้ **0.235064 เท่ากันทุกเคสแบบ bit-for-bit** = hybrid baseline เปล่า

แก้: `H2LConfigV3.MATCHING_MODE` ∈ {`soft`, `keyword_soft`, `hard`} อ่านที่จุดคำนวณ
φ_semantic = P(d|p) จริง โหมดผิด raise ไม่ fallback เงียบ

ผลใหม่ (`ablation_results/rq3_real_95cases_final/`, n=95):

| แขน | nDCG@5 | nDCG@10 |
|:---|---:|---:|
| Semantic (Soft) | 0.2485 | 0.2734 |
| Keyword (Graded) | 0.2451 | 0.2722 |
| Keyword (Hard) | 0.2485 | 0.2756 |

- อันดับเปลี่ยน 56/95 เคส (สวิตช์ทำงานจริง)
- ไม่มีคู่ใดผ่าน Holm ที่ใกล้สุด keyword_soft↔hard ที่ nDCG@10 (raw p=0.018, Holm 0.054)
  และ **เครื่องหมายเป็นลบ** — hard ดีกว่าเล็กน้อย ขัดสมมติฐาน
- 66/95 เคสมี nDCG@5=0 ทุกแขน → จัดอันดับใหม่ยกอะไรไม่ได้

### 2.2 RQ4 — severity vs uniform prior (commit `21ae5977a`)

รันใหม่ด้วย arity ที่แก้แล้ว: **0/95 เคสต่างกัน ทุก metric**
(`ablation_results/rq4_real_95cases_final/`)

เป็น null เชิงโครงสร้าง ไม่ใช่สวิตช์ตาย — พิสูจน์แล้วว่า patch ทำงาน (คะแนนเปลี่ยน)
แต่ P(p) ไม่ขึ้นกับเอกสารภายในเคสเดียว จึงปรับขนาดคะแนนแต่ไม่ปรับลำดับ
ช่องทางเดียวคือ α_eff ซึ่ง prior ขยับได้ ≤0.27 (เฉลี่ย 0.060) ขณะที่ต้องใช้ ~0.5
เพื่อพลิกอันดับ ค้นหา adversarial 4,000 ชุด พบ 0 การพลิก

### 2.3 DOCX pipeline (commit `0058390ae`)

สามบั๊กที่ทำให้เนื้อหาหายเงียบ ๆ:

1. `build_ch4_docx.py` ไม่มี branch สำหรับรูป → `![alt](path)` เขียนเป็นข้อความ
   เพิ่ม `add_figure()` + raise ถ้าไฟล์ไม่มี
2. `build_ch4_docx.py` ถือว่าบรรทัดที่มี `|` คือแถวตาราง → กลืนย่อหน้าที่มี
   `$P(d|p)$` หรือ `$|matched|/|all|$` หายไป 8 ย่อหน้า แก้ให้ต้องขึ้นต้นด้วย `|`
3. `inject_ch4_into_main_thesis.py` สร้าง `Document()` เปล่าแล้วคัดแค่ `run.text`
   → รูปหลุดทั้งหมด (รูปอยู่ใน XML ของ run) + ทิ้ง section properties และตาราง
   นอกบท 4 (ตารางสรุปหลักฐานบท 5 หลุดทุกครั้ง)
   เขียนใหม่ให้แก้ body ในที่เดิม + `_remap_images()` remap `r:embed`

ผลตรวจไฟล์จริง: 1064 ย่อหน้า, 15 ตาราง, **4 รูปฝังจริง**, markdown refs เหลือ 0,
zip + XML 16 parts well-formed, `r:embed` ทั้ง 4 resolve ไม่มี dangling

เพิ่ม test 15 ตัว (`tests/test_ch4_docx_figures.py`) — mutation-checked ทั้งสองจุด:
ย้อน pipe guard → fail 4 ตัว, ปิด `_remap_images` → fail 2 ตัว

### 2.4 เลขตาราง + footnote baseline (ยังไม่ commit)

**เรียงเลขตารางใหม่** จาก `4.1 4.2 4.3 4.4 4.5 4.6 4.7 [4.11] 4.10 4.8 4.8ข 4.9`
เป็น `4.1 … 4.11` ตามลำดับการอ่าน (12 caption, ตรวจ inline refs 14 จุดครบ)

mapping ที่ใช้: `4.11→4.8`, `4.10→4.9`, `4.8ข→4.10ข`, `4.8→4.10`, `4.9→4.11`

**footnote ตารางที่ 4.6** อธิบายว่าทำไม Full V6 = 0.2442 แต่ตารางอื่น = 0.2485
ทั้งที่เป็นการตั้งค่าเดียวกัน:

- RQ6 = re-ranking ablation ดึง pool 45 (=3×top_k) แล้ว rescore → ตัด 15
- ตารางอื่น = เส้นทาง retrieval ปกติ ดึง 15 → rescore
- ต่างกันเคสเดียว `CHILD_004_PAR_01` (0.7654 vs 0.3575) → ลากค่าเฉลี่ย 0.0043
- อีก 94 เคสเท่ากันทุกตัวเลข → เทียบ**ภายใน**ตารางที่ 4.6 ยังใช้ได้

### 2.5 รูปที่ 4.E (สร้างแล้ว ยังไม่อ้างอิง)

`scripts/build_ch4_figures.py` เพิ่ม `fig_4e()` → `output/figures_ch4/fig_4e_rq3_matching.png`

output ยืนยัน: `4.E arms=3 changed=56/95 metric_moved=4 zero_ceiling=36 other=16`

---

## 3. งานที่เหลือ เรียงตามลำดับที่ควรทำ

### 3.1 รัน pytest ก่อนอย่างอื่น (สำคัญ)

```bash
python3 -m pytest tests/ -q
```

คาดว่า 220 passed ถ้าไม่ผ่าน สาเหตุน่าจะมาจาก rewrite RQ2 ใน `ablation_study.py`
(ยังไม่มีใครรัน test หลังแก้)

### 3.2 RQ2 — เขียนโค้ดเสร็จแล้ว **แต่ยังไม่รัน**

สิ่งที่แก้ไปแล้วใน `ablation_study.py` (class `RQ2_AlphaSensitivity`):

- เดิม α=0 เรียก `evaluate_strategy('basic')` ซึ่งเป็น**ระบบอื่น** (ไม่มีชั้น H2L,
  ไม่มี query expansion, ไม่มี scoring) จุดซ้ายสุดของกราฟจึงเทียบกับจุดอื่นไม่ได้
- และ α=0 **ไม่ได้ปิด H2L** ด้วย — ยืนยันแล้วว่า `α_eff` ถูก clamp ที่พื้น 0.01
  ทำให้ `S_final = S_rerank · exp(0.01 · Σ)` ยังกวนอันดับ
  (ทดสอบ: ALPHA=0 → α_eff=0.0100, S_final=0.906540 ≠ S_rerank=1.0)
- ใหม่: sweep α ∈ {0, 0.01, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0} บนไปป์ไลน์ H2L เดียวกันทุกจุด
  และเก็บ `basic` เป็น **reference arm แยก** (`alpha=NaN`, `arm='basic reference (no H2L layer)'`)
- เพิ่ม `_clamp_check()` (α=0 ต้องเท่า α=0.01 เป๊ะ ถ้าต่างแปลว่า clamp ย้ายแล้ว
  คำอธิบายในบทจะเก่า) และ `_sweep_check()` (α ต้องขยับอันดับที่ใดที่หนึ่ง)
  พร้อม `retrieve_fallbacks` guard แบบเดียวกับ RQ3
- `visualize()` แยก sweep ออกจาก reference อย่างชัดเจน (เดิม `groupby('alpha')`
  จะทิ้งแถว NaN เงียบ ๆ) วาด reference เป็นเส้นแนวนอน, เลิก `set_ylim([0,1])`
  ที่บีบเส้น 0.24–0.25 ให้แบน, และประกาศ "Optimal α" เฉพาะเมื่อ spread > 1e-4

CSV เก่าทั้งสองไฟล์ **ใช้ไม่ได้** ต้องรันใหม่:

- `ablation_results/rq2_α_parameter_sensitivity.csv` — Apr 23, มีแค่ 5 เคส, 5 ค่า α
- `ablation_results/rq6_test_95cases_20260807/rq2_results.csv` — Aug 9, 95 เคส 7 ค่า α
  แต่ `run_metadata.json` มี `status: running` (รันไม่จบ) และ `h2l_core_sha256` เป็นของเก่า

คำสั่งรัน (9 arms ≈ 2 นาที/arm ≈ 18–20 นาที ควรรัน background):

```bash
OUT=ablation_results/rq2_real_95cases_final
rm -rf "$OUT"
python3 ablation_study.py --rq 2 --split test --skip-baselines --top-k 15 \
  --detected-problems-cache evaluation_results/model_comparison/l2_full_matrix_95cases_3models_3repeats_8strategies.json \
  --detected-problems-model qwen2.5:7b --detected-problems-repeat 1 \
  --output-dir "$OUT" > "${OUT}_console.log" 2>&1
```

หลังรันเสร็จ **ต้องตรวจ log สองบรรทัดนี้ก่อนเชื่อตัวเลข**:

```bash
grep -E "Clamp check|Manipulation check|❌|fell back" ablation_results/rq2_real_95cases_final_console.log
```

ถ้าเห็น `❌ RQ2 manipulation check FAILED` แปลว่า ALPHA ไม่ถึงฟังก์ชันคะแนน — อย่ารายงานผล

### 3.3 ใส่อ้างอิงรูปที่ 4.E ใน 4.5.4

รูปสร้างแล้วแต่ **ยังไม่มีบรรทัดอ้างอิงใน markdown** ตอนนี้ 4.5.4 ไม่มีรูปเลย
ขณะที่ 4.5.1 มีรูปที่ 4.D จุดที่ควรแทรกคือหลังย่อหน้าที่พูดถึงเพดานการค้นคืน
(66/95 เคสมี nDCG@5=0) ก่อนย่อหน้า "ข้อสรุป"

รูปแบบที่ใช้ในบทนี้คือสองบรรทัด — ย่อหน้าบรรยายก่อน แล้ว markdown image:

```markdown
**รูปที่ 4.E** แสดง...

![รูปที่ 4.E ...](../output/figures_ch4/fig_4e_rq3_matching.png)
```

ตัวเลขที่ใช้อ้างในคำบรรยายได้ (จาก output ของ builder): อันดับเปลี่ยน 56/95,
ยกตัวชี้วัดได้ 4 เคส, ติดเพดาน nDCG@5=0 ทุกแขน 36 เคส, อันดับเปลี่ยนแต่ค่าเท่าเดิม
(ไม่เป็นศูนย์) 16 เคส, อันดับไม่เปลี่ยน 39 เคส

### 3.4 เขียนหัวข้อ RQ2 ในบท 4

ตอนนี้ 4.5.2 ชื่อ "ผลการวิเคราะห์ความไวของพารามิเตอร์" แต่เนื้อหาเป็น
**OAT sensitivity 6 พารามิเตอร์** ($\lambda_{neg}, \mu, \kappa, T_{range}, \alpha_0, T_{base}$)
ซึ่งเป็นการวิเคราะห์อีกชุด **ไม่ใช่ RQ2** — α sweep ของ RQ2 ยังไม่มีที่ในบท 4 เลย

ต้องตัดสินใจ: เพิ่มหัวข้อใหม่สำหรับ RQ2 หรือรวมเข้า 4.5.2 แล้วแยกสองส่วนให้ชัด
ถ้าเพิ่มหัวข้อใหม่ ต้องเลื่อนเลข 4.5.x และเลขตารางที่ตามมาทั้งหมดอีกรอบ

ประเด็นที่ต้องเขียนให้ตรง: α=0 **ไม่ใช่** "ปิด problem influence" เพราะ clamp ที่ 0.01
และ `basic` เป็น reference แยก ไม่ใช่จุด α=0 ของเส้นเดียวกัน

### 3.5 uniform_prior ยังเป็น monkey-patch

`ablation_study.py:525-550` — RQ4 ยังใช้ monkey-patch (แก้ arity แล้ว + มี test ล็อก
signature ไว้ที่ `tests/test_rq4_uniform_prior.py`) แต่ยังเปราะกว่าวิธี config
แนวทางเดียวกับ `MATCHING_MODE`: เพิ่ม `H2LConfigV3.PRIOR_MODE ∈ {'severity', 'uniform'}`
อ่านที่ `calculate_problem_prior()` แล้วลบ patch ออก

หมายเหตุ: ต้องรัน RQ4 ใหม่หลังแก้ เพื่อยืนยันว่าได้ 0/95 เท่าเดิม

### 3.6 ไฟล์ค้างใน git

`.gitignore` ยังไม่มี pattern สำหรับ `BACKUP` และ `console.log`
(ตรวจแล้ว: `git ls-files | grep BACKUP` เจอ 1 ไฟล์ที่ถูก track ไว้แล้วจากอดีต)

ข้อเสนอ: เพิ่มสองบรรทัดนี้ใน `.gitignore` แล้วลบ backup ที่ track อยู่ออกจาก index

```
*.BACKUP_*.docx
ablation_results/*_console.log
```

### 3.7 rebuild + commit

หลังแก้ markdown เสร็จทุกข้อ:

```bash
python3 scripts/build_ch4_figures.py          # regenerate 4.A-4.E
python3 scripts/build_ch4_docx.py             # markdown -> ch4_thesis.docx
cp 65130641_Riskie_Thesis_Glen_fixed.docx \
   "65130641_Riskie_Thesis_Glen_fixed.BACKUP_$(date +%Y%m%d_%H%M%S).docx"
python3 inject_ch4_into_main_thesis.py
python3 -m pytest tests/ -q
```

ตรวจไฟล์ผลลัพธ์ว่าไม่มีอะไรหาย (ควรได้ ≥15 ตาราง, 5 รูป, markdown refs = 0):

```bash
python3 -c "
from docx import Document
d = Document('65130641_Riskie_Thesis_Glen_fixed.docx')
txt = '\n'.join(p.text for p in d.paragraphs)
media = [x for x in d.part.package.parts if 'media' in str(x.partname)]
import re
print('paras', len(d.paragraphs), 'tables', len(d.tables),
      'images', len(media), 'leftover_md_refs', len(re.findall(r'!\[', txt)))
"
```

---

## 4. กับดักที่เจอมาแล้ว อย่าเหยียบซ้ำ

1. **monkey-patch bound method** — signature ต้องตรงกับที่ `retrieve()` เรียกจริง
   `(results, explicit_problems, query)` ถ้าผิด `evaluate_strategy()` จะกลืน TypeError
   แล้วลองใหม่แบบไม่ส่ง problems ทำให้แขนกลายเป็น baseline เงียบ ๆ
   วิธีจับ: ถ้าสองแขนให้ค่า **เท่ากันเป๊ะทุกเคสแบบ bit-for-bit** ให้สงสัยทันที

2. **`'|' in line` ใน markdown parser** — กลืนย่อหน้าที่มี inline math
   ต้องใช้ `line.strip().startswith('|')`

3. **`run.text` ไม่พารูปมา** — รูปอยู่ใน XML ของ run ต้อง deepcopy element
   แล้ว remap `r:embed` ไม่งั้น Word บอกไฟล์เสีย

4. **`main_doc.paragraphs` ข้ามตาราง** — ถ้าจะคัดทั้งช่วง ต้อง iterate `body` แล้วดู
   ทั้ง `w:p` และ `w:tbl`

5. **`groupby()` ทิ้ง NaN เงียบ ๆ** — ถ้าใช้คอลัมน์ที่มี NaN เป็น key แถวนั้นจะหายจากกราฟ

6. **ตัวเลขเดียวกันจากสอง code path** — ก่อนเทียบข้ามตาราง ตรวจว่า `candidate_pool_k`
   และเส้นทาง retrieval ตรงกัน (บทเรียนจาก 0.2442 vs 0.2485)

7. **`run_metadata.json` มี `status: running`** — แปลว่ารันไม่จบ อย่าใช้ตัวเลขจาก run นั้น
   และตรวจ `h2l_core_sha256` ว่าตรงกับ core ปัจจุบัน

---

## 5. ไฟล์อ้างอิงเร็ว

| ไฟล์ | บทบาท |
|:---|:---|
| `md_report/thesis_full_ch4_final.md` | ต้นฉบับบท 4 (แหล่งความจริงเดียว) |
| `ablation_study.py` | RQ1-RQ6 ทุก experiment class |
| `H2L_core.py` | `H2LConfigV3`, `calculate_final_score_probabilistic()` |
| `scripts/build_ch4_figures.py` | รูป 4.A-4.E |
| `scripts/build_ch4_docx.py` | markdown → `ch4_thesis.docx` |
| `inject_ch4_into_main_thesis.py` | `ch4_thesis.docx` → เล่มหลัก (in-place) |
| `tests/test_rq3_matching_mode.py` | guard RQ3 |
| `tests/test_rq4_uniform_prior.py` | guard RQ4 + signature lock |
| `tests/test_ch4_docx_figures.py` | guard รูป/ตาราง/image-rel |
| `ablation_results/rq3_real_95cases_final/` | ผล RQ3 ที่ใช้ในบท |
| `ablation_results/rq4_real_95cases_final/` | ผล RQ4 ที่ใช้ในบท |
| `ablation_results/rq6_95cases_20260809/` | ผล RQ6 (ตารางที่ 4.6) |
