# บทที่ 4: ผลการทดลองและการวิเคราะห์ข้อมูล (Results and Analysis)

บทนี้นำเสนอผลการทดลองของระบบ H2L ตามสถานะปัจจุบันของโค้ดและ evaluation artifacts ที่มีอยู่จริง โดยยึดหลักว่า **รายงานเฉพาะผลที่เกิดจากการรันจริง** ไม่ใช้ mock data หรือค่าประมาณเพื่อความสวยงามของรายงาน ผลหลักของบทนี้อ้างอิงจากไฟล์ `evaluation_results/proper_eval_latest_summary.json`, `evaluation_results/sentence_polarity_latest.json`, `sensitivity_results/sensitivity_report.md` และ pair reruns ล่าสุดใน `evaluation_results/pairs/*/proper_eval_latest_summary.json`

---

## 4.1 กรอบการประเมินผลและข้อมูลที่ใช้ (Evaluation Setup and Data)

งานวิจัยนี้ใช้ชุดข้อมูล `expanded_ground_truth.json` จำนวน 197 เคส ซึ่งเก็บอยู่ในไฟล์เดียวและใช้ field `split` เพื่อแยก train 122 เคส และ test 75 เคส สำหรับการรายงานผล retrieval ในบทนี้ ผู้วิจัยใช้ proper evaluation ล่าสุดโดยตั้งค่า `problem_source=detected` และ `top_k=15` เพื่อให้ค่าที่ใช้ในหน้า analysis, evidence retrieval และ research report สอดคล้องกันทั้งหมด ส่วนการประเมิน sentence polarity ใช้ test split เดียวกัน โดยแยกเคสยืนยันปัญหา 57 เคส และเคสปฏิเสธ 18 เคส

**ตารางที่ 4.1 สรุปกรอบการประเมินผลหลัก**

| รายการ | ค่าที่ใช้ |
|:---|:---|
| ชุดข้อมูลทั้งหมด | 197 เคส |
| Train/Test split | 122 / 75 |
| ปัญหาที่ใช้ใน retrieval evaluation | `detected problems` |
| ค่า top-k หลักของวิทยานิพนธ์ | 15 |
| กลยุทธ์ที่เปรียบเทียบ | 8 กลยุทธ์ |
| ชุดประเมิน sentence polarity | 75 เคส (ยืนยันปัญหา 57 เคส, ปฏิเสธปัญหา 18 เคส) |
| สถิติที่ใช้เปรียบเทียบเชิงคู่ | Wilcoxon Signed-Rank Test |

กลยุทธ์ทั้ง 8 แบบที่นำมาประเมินประกอบด้วย 4 backbone เดิม และ 4 รุ่นที่ถูกครอบด้วย H2L ได้แก่ BM25, dense retrieval, HyDE, hybrid baseline, H2L-BM25, H2L-Dense, H2L-HyDE และ H2L-Hybrid

### 4.1.1 Protocol หลักที่ใช้สรุปผลในบทนี้

เพื่อให้การตีความผลมีจุดยึดเดียวกัน ผู้วิจัยกำหนด protocol หลักของบทนี้ดังนี้

- **ผลหลักของวิทยานิพนธ์:** ใช้ `problem_source=detected` และ `top_k=15`
- **upper-bound diagnostic:** ใช้ `reference problems (gold problems)` เพื่อดูศักยภาพของ retriever เมื่อไม่ถูกจำกัดด้วย detector
- **sensitivity analysis:** ใช้ `top-k = 5, 10, 20` เพื่อดูว่าผลของ H2L คงเส้นคงวาหรือไวต่อการเปลี่ยนขนาด evidence set มากน้อยเพียงใด

ดังนั้น เมื่อกล่าวถึง "ผลหลักของวิทยานิพนธ์" ในบทนี้ ผู้วิจัยหมายถึงผลแบบ end-to-end ภายใต้ `detected + top_k=15` เป็นหลัก ส่วนค่า `reference problems (gold problems)` และ top-k อื่นถูกใช้เพื่อช่วยอธิบายข้อจำกัดและตรวจสอบความเสถียรของผลเท่านั้น

### 4.1.2 ความเชื่อมโยงระหว่างกราฟรายงานกับคำถามวิจัย

เพื่อไม่ให้ส่วนแสดงผลเชิงโต้ตอบถูกมองว่าเป็นเพียงองค์ประกอบของหน้าเว็บ ผู้วิจัยกำหนดบทบาทของกราฟและส่วนรายงานแต่ละชนิดต่อคำถามวิจัยอย่างชัดเจน ดังตารางต่อไปนี้

**ตารางที่ 4.1B ความสัมพันธ์ระหว่างกราฟ รายการข้อมูล และคำถามวิจัย**

| กราฟ/ส่วนรายงาน | ระดับข้อมูล | บทบาทต่อคำถามวิจัย | แหล่งข้อมูลจริง |
|:---|:---|:---|:---|
| Evidence Scaling by Top-K | experiment-level | RQ1: H2L คงเส้นคงวาหรือไวต่อ top-k เพียงใดเมื่อเทียบกับ baseline | proper evaluation artifacts |
| Latest Pair Reruns | pair-family-level | RQ1: เมื่อแยก backbone ทีละคู่ H2L ช่วยหรือเสียเปรียบอย่างไร | `evaluation_results/pairs/*/proper_eval_latest_summary.json` |
| Comparison Bar Chart | pair-level | RQ1: H2L ช่วย backbone เดียวกันหรือไม่ | comparison pairs จาก proper evaluation |
| Scatter Plot (Quality vs Time) | strategy-level | RQ1: คุณภาพ retrieval ดีขึ้นแลกกับเวลาแค่ไหน | benchmark rows จาก proper evaluation |
| Performance Provenance | report-level | ใช้สนับสนุนการตีความ RQ1/RQ2 ว่าผลที่กำลังอ่านเป็น case-level หรือ benchmark-level | `/evaluation-summary` + runtime `/analyze` |
| Provenance badges + auto refresh | report-level | ใช้สนับสนุนการตีความ RQ1/RQ2 ว่า artifact ที่เห็นเป็นไฟล์ล่าสุดจริงหรือไม่ | `/evaluation-summary` polling + latest artifact aliases |
| Live Evaluation Progress + Artifact Retention | report-level | ใช้สนับสนุนการตีความ RQ1/RQ2 ว่า evaluator กำลังรันถึงไหน และ dashboard คุมไฟล์ผลลัพธ์อย่างไร | progress artifacts + latest/checkpoint policy |
| Problem-Document Matrix | case-level, structure-level | ใช้สนับสนุนการอธิบายผลของ RQ1/RQ2 ว่า problem ใดมี evidence ใดรองรับ | runtime `/analyze` |
| Semantic Evidence Map | case-level, node-level | ใช้สนับสนุนการอธิบายผลของ RQ1/RQ2 ในระดับ semantic relation และหลักฐาน | runtime vector projection |
| System Evaluation Status | benchmark-synthesis | RQ1/RQ2: อะไรพร้อมใช้สรุปผล และอะไรยังต้องระวัง | benchmark artifacts + diagnostics |

ตารางนี้ทำให้ผู้อ่านแยกได้ชัดว่า กราฟบางชนิดใช้ตอบคำถามวิจัยโดยตรงบนชุดทดสอบ ขณะที่บางชนิดทำหน้าที่เป็นหลักฐานสนับสนุนการตีความผลในระดับเคสเฉพาะหน้า จึงไม่ควรนำไปตีความข้ามระดับกัน

---

## 4.2 ผลการประเมิน Sentence Polarity (Sentence Polarity Evaluation)

การประเมิน sentence polarity มีเป้าหมายเพื่อตอบคำถามว่า เมื่อข้อความมีคำปฏิเสธหรือโครงสร้างที่อาจก่อ false positive ระบบสามารถกดทอน candidate ที่ไม่ควรถูกแจ้งเตือนได้หรือไม่ โดยการประเมินนี้วัดแยกจาก retrieval quality เพื่อไม่ให้ผลด้านความปลอดภัยถูกกลบด้วยค่า rank metrics

ผู้วิจัยได้รันยืนยันผลอีกครั้งบนโค้ดสถานะปัจจุบันเมื่อวันที่ 21 เมษายน 2026 และได้ค่าเท่ากับ artifact หลักล่าสุดทุกตัวชี้วัดสำคัญ จึงสะท้อนว่าผลของ sentence polarity ในรุ่นปัจจุบันมีความเสถียรในระดับที่ใช้อ้างอิงในวิทยานิพนธ์ได้

ในงานรุ่นปัจจุบัน ผู้วิจัยยังเพิ่มกลไก `sentence_polarity_progress.json` และ `proper_eval_progress.json` เพื่อให้หน้า report อ่านสถานะการรัน evaluator จากไฟล์จริงระหว่างประมวลผล และใช้ `*_latest*` กับ `*_checkpoint*` เป็น stable aliases สำหรับการแสดงผลหลัก ขณะที่ไฟล์ timestamped history ถูกเก็บไว้ในจำนวนจำกัดเพื่อไม่ให้ artifact กองสะสมจนรบกวนการ review

นอกเหนือจากตัวเลขเชิง benchmark รุ่นนี้ยังเพิ่ม refinement สำคัญในชั้น runtime ได้แก่ candidate-specific polarity แบบ clause-local, sentence-bound evidence, entity/coreference binding, code-specific context rules, implicit taxonomy-anchor guard, review statuses และการยุบรหัสซ้ำเชิงประเด็น เพื่อแก้ปัญหา false positive จากเคสภาษาจริงที่มีหลายบุคคล หลาย clause และคำปฏิเสธที่ไม่ครอบ candidate เดียวกัน

**ตารางที่ 4.2 ผลการประเมิน sentence polarity ล่าสุด**

| ตัวชี้วัด | ค่า |
|:---|---:|
| Accuracy | 0.8667 |
| Negation Detection Rate (NDR) | 0.7222 |
| False Positive Rate (FPR) | 0.0877 |
| Precision | 0.7222 |
| F1 | 0.7222 |
| จำนวนเคสยืนยันปัญหา | 57 |
| จำนวนเคสปฏิเสธปัญหา | 18 |

เมื่อตีความเป็นจำนวนเคสจริง ระบบตัดสินถูกต้อง 65 จาก 75 เคส ตรวจพบเคสปฏิเสธได้ 13 จาก 18 เคส และลดน้ำหนักเคสยืนยันปัญหาผิดพลาด 5 จาก 57 เคส ผลลัพธ์นี้แสดงให้เห็นว่า sentence polarity gate ในรุ่นปัจจุบันสามารถช่วยลด false positive ได้จริง แต่ยังไม่สมบูรณ์จนถึงระดับที่ไม่พลาดเลย

### 4.2.1 ความหมายของผลลัพธ์

ข้อค้นพบสำคัญมี 3 ประเด็น

1. **ระบบไม่ได้เพียงตรวจคำว่า "ไม่" แบบผิวเผิน**
   ในรุ่นปัจจุบัน polarity gate ถูกใช้แบบ candidate-specific กล่าวคือระบบพิจารณาว่าคำปฏิเสธครอบ problem candidate ใดจริง ไม่ใช่ลดคะแนนทุกปัญหาพร้อมกันทั้งเคส

2. **ข้อมูล actor-target-action ช่วยลดความสับสนเชิงบริบท**
   การแยกผู้กระทำ ผู้ถูกกระทำ และ action ทำให้ระบบไม่ดึงบุคคลที่อยู่คนละ clause มาเป็น agent โดยอัตโนมัติ และช่วยให้ polarity reasoning อ่านได้ตรงกับเคสจริงมากขึ้น

3. **ยังมี trade-off ระหว่างการกัน false positive กับการไม่ลดน้ำหนักเคสจริงเกินไป**
   ค่า FPR ที่ 0.0877 แสดงว่ายังมีเคสยืนยันปัญหาบางส่วนที่ถูกลดน้ำหนักผิด ซึ่งเป็นข้อจำกัดที่ควรอภิปรายอย่างตรงไปตรงมาในวิทยานิพนธ์

### 4.2.2 ข้อสังเกตสำหรับการอภิปรายผล

ผลชุดนี้สนับสนุนแนวคิดว่า sentence polarity ควรถูกนำเสนอเป็น **มิติด้าน safety** แยกจาก retrieval quality เนื่องจากระบบอาจปลอดภัยขึ้นแม้ค่า retrieval บาง backbone จะไม่ได้เพิ่มขึ้นทันทีในอันดับต้น ๆ การสรุปผลแบบแยกมิติทำให้ผู้อ่านเข้าใจได้ชัดว่า H2L ช่วยอะไรแน่ และไม่เหมารวมว่าค่า nDCG ที่เพิ่มขึ้นหรือลดลงเล็กน้อยเท่ากับความปลอดภัยของระบบ

---

## 4.3 ผลการประเมิน Retrieval Performance (Retrieval Results)

### 4.3.1 ผลรวมทุกกลยุทธ์

**ตารางที่ 4.3 ผลรวมของ retrieval metrics จาก proper evaluation**

| กลยุทธ์ | nDCG@5 | nDCG@10 | MAP | MRR | เวลาเฉลี่ยต่อเคส (วินาที) |
|:---|---:|---:|---:|---:|---:|
| H2L-BM25 | **0.3201** | **0.3310** | **0.3045** | 0.3388 | 0.0291 |
| BM25 Only | 0.3058 | 0.3177 | 0.2975 | **0.3430** | **0.0012** |
| Hybrid baseline (`basic`) | 0.2871 | 0.3004 | 0.2774 | 0.3221 | 1.6167 |
| H2L-Hybrid | 0.2862 | 0.3076 | 0.2863 | 0.3354 | 25.6152 |
| Naive RAG | 0.2626 | 0.2869 | 0.2625 | 0.3270 | 0.0978 |
| H2L-Naive RAG | 0.2595 | 0.2925 | 0.2674 | 0.3284 | 2.9008 |
| HyDE | 0.1994 | 0.2148 | 0.1991 | 0.2256 | 4.4847 |
| H2L-HyDE | 0.1939 | 0.2318 | 0.1895 | 0.2241 | 55.3731 |

ผลรวมชี้ให้เห็นว่า **H2L-BM25** ได้อันดับสูงสุดในชุดทดสอบหลักทั้ง nDCG@5, nDCG@10 และ MAP รวมถึง P@5 และ F1@5 ขณะที่ **BM25 Only** ยังมีความเร็วสูงที่สุดและทำ MRR ได้สูงกว่า H2L-BM25 เล็กน้อย ส่วน **H2L-Hybrid** ไม่ได้เป็นอันดับหนึ่งด้าน rank metric แต่ยกระดับ MAP และ MRR เหนือ hybrid baseline ได้ พร้อมมีองค์ประกอบของระบบครบที่สุดสำหรับใช้เป็นโมเดลหลักของงานวิจัย

### 4.3.2 การเปรียบเทียบแบบคู่ Baseline vs H2L

เพื่อประเมินผลของ H2L อย่างเป็นธรรม ผู้วิจัยเปรียบเทียบ baseline แต่ละตัวกับรุ่น H2L ที่ใช้ backbone เดียวกัน

**ตารางที่ 4.4 ผลเปรียบเทียบเชิงคู่ของ backbone เดียวกันจาก unified proper evaluation ล่าสุด**

เพื่อให้บทนี้สอดคล้องกับผลหลักของวิทยานิพนธ์ ผู้วิจัยยึดค่าเปรียบเทียบจาก proper evaluation รอบล่าสุดที่รันทั้ง 8 กลยุทธ์ภายใต้ protocol เดียวกัน แล้วคำนวณส่วนต่างของ H2L เทียบกับ backbone เดิมโดยตรง

| คู่เปรียบเทียบ | ΔMAP | ΔMRR | ΔnDCG@5 | ΔP@5 | ข้อสรุปเบื้องต้น |
|:---|---:|---:|---:|---:|:---|
| BM25 Only vs H2L-BM25 | +0.0070 | -0.0042 | +0.0143 | +0.0080 | H2L ช่วย BM25 ชัดที่สุดในภาพรวมรอบล่าสุด |
| Naive RAG vs H2L-Naive RAG | +0.0048 | +0.0014 | -0.0030 | -0.0080 | ภาพรวมเป็น mixed effect โดย MAP/MRR ดีขึ้นเล็กน้อย |
| HyDE vs H2L-HyDE | -0.0096 | -0.0015 | -0.0055 | -0.0187 | H2L ไม่ช่วย HyDE ใน unified evaluation รอบล่าสุด |
| Hybrid baseline vs H2L-Hybrid | +0.0089 | +0.0134 | -0.0009 | -0.0053 | top-5 ใกล้เคียงเดิม แต่ MAP/MRR ดีขึ้นชัดกว่า backbone เดิม |

จากตารางจะเห็นว่า H2L ไม่ได้เพิ่มค่า top-5 ให้ทุก backbone แบบอัตโนมัติ แต่ช่วยแตกต่างกันไปตามธรรมชาติของ backbone นั้น ๆ

- **BM25:** H2L ช่วยเสริมได้เล็กน้อยโดยไม่ทำลายอันดับเดิมมากนัก และยังคงเร็วที่สุดในกลุ่ม H2L
- **Dense retrieval:** H2L ทำให้ MAP/MRR ดีขึ้นเล็กน้อย แต่ nDCG@5 และ P@5 ลดลงเล็กน้อย จึงเป็นภาพแบบ near-neutral มากกว่าชนะชัด
- **HyDE:** ใน unified evaluation รอบล่าสุด H2L-HyDE ให้ผลด้อยกว่า HyDE เดิมทั้ง nDCG@5, MAP, MRR และ P@5 พร้อมมีต้นทุนเวลาเพิ่มสูงมาก
- **Hybrid:** H2L-Hybrid ยังคง competitive และมี MAP/MRR สูงกว่า hybrid baseline อย่างชัดเจน แม้ nDCG@5 จะลดลงเล็กน้อยและเวลาเพิ่มขึ้นมาก

### 4.3.3 การตีความผลเชิงวิทยานิพนธ์

ผล retrieval ปัจจุบันนำไปสู่ข้อสรุปสำคัญ 4 ข้อ

1. **H2L ไม่ใช่โมดูลเพิ่มคะแนนแบบเส้นตรง**
   H2L ปรับอันดับเอกสารตาม problem distribution, severity, polarity และ semantic cues ของเคสจริง ดังนั้นจึงมีโอกาสช่วยหรือ trade off ต่างกันในแต่ละ backbone

2. **การชนะใน nDCG@5 ไม่ได้เท่ากับเป็นโมเดลหลักของวิทยานิพนธ์เสมอไป**
   แม้ H2L-BM25 จะได้คะแนน retrieval สูงสุด แต่ `h2l-hybrid` ยังเหมาะเป็นโมเดลหลักของวิทยานิพนธ์ เพราะรวม detector + hybrid retrieval + polarity + explanation stack ครบที่สุด

3. **ขนาด test set ปัจจุบันยังเล็กและควรสรุปผลเชิง retrieval อย่างระมัดระวัง**
   แม้ H2L-BM25 จะเด่นชัดที่สุดในภาพรวม unified evaluation แต่ความแตกต่างของแต่ละคู่ยังมีขนาดไม่มากในหลาย metric และบางคู่มี trade-off ข้าม metric ดังนั้นการอภิปรายผลควรใช้คำว่า H2L "ช่วยแตกต่างกันตาม backbone" มากกว่าจะเหมารวมว่าเหนือกว่าทุกคู่แบบเด็ดขาด

4. **การรายงาน retrieval ควรคู่กับ safety metrics เสมอ**
   หากพิจารณาเฉพาะ nDCG อย่างเดียว อาจมองไม่เห็นคุณค่าของ polarity gate และ contextual filtering ที่ช่วยลด false positive ได้จริง

---

## 4.4 การวิเคราะห์ความอ่อนไหวของพารามิเตอร์ (Sensitivity Analysis)

ผล sensitivity analysis ล่าสุดช่วยตอบว่าพารามิเตอร์ใดเป็นตัวคุมระบบจริง และพารามิเตอร์ใดมีความเสถียรสูงในงานรุ่นปัจจุบัน

**ตารางที่ 4.5 สรุปความอ่อนไหวของพารามิเตอร์**

| พารามิเตอร์ | ค่าเริ่มต้น | Max abs Δ | การตีความ |
|:---|---:|---:|:---|
| α0 | 1.0 | **219.68%** | ตัวคุมระบบหลัก ต้องตั้งค่าอย่างระมัดระวัง |
| T_base | 0.5 | **17.51%** | มีผลรองลงมา โดยเฉพาะต่อ calibration |
| T_range | 1.5 | 2.25% | ค่อนข้างเสถียร |
| μ | 2.0 | 0.24% | เสถียรสูง |
| κ | 0.15 | 0.17% | เสถียรสูง |
| λ_neg | 0.6 | 0.00% | เสถียรในชุดทดสอบปัจจุบัน |
| m | 0.3 | 0.00% | เสถียรในชุดทดสอบปัจจุบัน |
| β | 0.3 | 0.00% | เสถียรในชุดทดสอบปัจจุบัน |

ผลนี้ทำให้การอภิปรายในวิทยานิพนธ์ควรเน้นว่า **α0 เป็น system driver ที่แท้จริง** ส่วน **T_base** เป็นค่าที่ควรจับตาในขั้น calibration ขณะที่พารามิเตอร์อีกหลายตัวทำหน้าที่เหมือน stabilizer มากกว่า optimizer กล่าวคือมีผลช่วยให้สมการสมบูรณ์และตีความได้ แต่ไม่ได้ทำให้คะแนนเหวี่ยงอย่างรุนแรง

---

## 4.5 ผลด้าน Explainability และการตรวจสอบย้อนกลับ (Explainability and Reporting)

งานรุ่นปัจจุบันไม่ได้พึ่งการอธิบายผลด้วยมุมมอง 3D เพียงอย่างเดียวอีกต่อไป แต่ขยายสู่ชุดเครื่องมือเชิงโต้ตอบที่ช่วยให้ตีความผลของคำถามวิจัยทั้งสองข้อได้ง่ายกว่าเดิม กล่าวคือช่วยอธิบายว่าทำไม H2L จึงเปลี่ยนอันดับเอกสารจาก baseline และช่วยตรวจสอบว่ากลไก polarity ลดหรือคง candidate ใดไว้ด้วยเหตุผลอะไร เครื่องมือสำคัญประกอบด้วย

1. **Analyzed Case Text**
   แสดงคำหรือวลีที่ตรวจจับได้จริงในระดับ occurrence พร้อม matched keywords, polarity rows, support spans และการเชื่อมโยงกับ problem candidates ทำให้คำที่ซ้ำกันหลายตำแหน่ง เช่น `มารดา` ใน clause เรื่องหนี้สินและ `มารดา` ใน clause เรื่องตีเด็ก ถูกแยกเป็นคนละ token และชี้ไปยัง event frame คนละตัว

2. **Event Frames**
   แสดง actor, action, target และ evidence span ในรูปแบบที่ผู้ใช้คลิกดูรายละเอียดได้ โดยแต่ละ event ถูกผูกกับ `span_start/span_end`, `mention_id`, `action_id` และ support mentions ทำให้ตรวจสอบย้อนหลังได้ว่าบทบาทใดมาจากคำ occurrence ใดในข้อความจริง

3. **Live Execution Path**
   แยก phase ของระบบ เช่น case preparation, L1 detection, L2 validation, polarity effect และ retrieval พร้อมระบุเวลาของแต่ละ phase

4. **Case H2L Summary และ H2L Document Score Breakdown**
   แยกตัวแปรระดับเคสออกจากตัวแปรระดับเอกสาร ทำให้ผู้อ่านเห็นว่า final document score เกิดจาก prior, severity, semantic evidence และ polarity อย่างไร โดยไม่สับสนว่าคะแนนเป็นของเคสหรือของเอกสาร

5. **Problem-Document Matrix**
   ใช้เป็นมุมมองเชิงโครงสร้างเพื่อสรุปอย่างรวดเร็วว่า problem code ใดมี evidence document ใดรองรับ และการรองรับนั้นกระจุกหรือกระจายเพียงใด

6. **Semantic Evidence Map**
   ใช้เป็นมุมมองเชิงลึกสำหรับดู semantic distance, linked nodes และรายละเอียดหลักฐานระดับ node ซึ่งละเอียดกว่ามุมมองแบบ Problem-Document Matrix

7. **Performance Provenance, Case-Level Runtime Review และ Benchmark Performance Review**
   ช่วยแยกอย่างชัดเจนว่าผลใดมาจาก runtime ของเคสปัจจุบัน และผลใดมาจาก benchmark artifacts บน test split เพื่อกันการตีความข้ามระดับ

8. **Review Status Summary**
   แสดงสถานะ `confirmed`, `needs_review`, `verify_documents`, `filtered`, รวมถึงโหมด `baseline_candidate` และ `baseline_filtered` เพื่อช่วยสื่อสารว่ารหัสใดพร้อมใช้งาน รหัสใดยังต้องตรวจทะเบียน/สิทธิ/เอกสาร และรหัสใดเป็นเพียง preview จาก baseline detector

9. **Evidence Scaling by Top-K, Comparison Bar Chart, Scatter Plot, Live Evaluation Progress และ System Evaluation Status**
   ใช้ตอบคำถามเชิงงานทดลองว่า H2L มีผลต่อ retrieval quality, latency, ความคงเส้นคงวาตาม top-k, สถานะการรัน evaluator และความพร้อมของ benchmark artifacts อย่างไร โดยอ้างอิงจาก stable latest/checkpoint aliases และ progress artifacts จริง

นอกจากนี้ dashboard รุ่นล่าสุดยังสะท้อน refinement เชิงตรรกะของ detector โดยตรง เช่น การจับ evidence แบบ sentence-bound, การใช้ coreference สำหรับตัวอ้างอิงในประโยคถัดไป, การยุบรหัสซ้ำเชิงประเด็น เช่น `0801` กับ `Z59.0`, การแยกเคสที่ควรเป็น `verify_documents` แทนการสรุปเป็นปัญหายืนยัน และการรองรับ `user-adjusted span anchor` ที่ผู้ใช้เลือกเองเพื่อบังคับให้ polarity และ event binding อ้างอิง occurrence เดียวกับที่ผู้ใช้ตรวจแล้วว่าถูกต้อง การเพิ่มความละเอียดระดับนี้มีผลมากต่อคุณภาพของ runtime case review แม้จะไม่ถูกสรุปเป็นตัวเลข retrieval metric โดยตรง

ผลเชิง explainability จึงไม่ควรถูกมองเป็นเพียงส่วนแสดงผลของหน้าเว็บ แต่เป็นองค์ประกอบสำคัญที่ช่วยรองรับการตีความผลของ RQ1 และ RQ2 เพราะทำให้ระบบสามารถถูก audit ได้ทั้งในระดับเคสและระดับเอกสารหลักฐาน ซึ่งมีความสำคัญต่อการนำเสนอในวิทยานิพนธ์และต่อการตรวจสอบโดยผู้เชี่ยวชาญ

---

## 4.6 สรุปผลสำหรับการนำไปใช้ในบทอภิปรายและบทสรุป

จากผลการทดลองทั้งหมด ผู้วิจัยสามารถสรุปประเด็นสำคัญสำหรับบทถัดไปได้ดังนี้

1. **Sentence polarity gate ช่วยลด false positive ได้จริง**
   Accuracy 0.8667 และ NDR 0.7222 สะท้อนว่าระบบมีความสามารถด้าน safety ที่ใช้งานได้จริง แม้ยังมีพื้นที่สำหรับปรับปรุงเพิ่มเติม

2. **H2L ช่วย retrieval บาง backbone มากกว่าบาง backbone**
   H2L-BM25 ให้แนวโน้มดีขึ้นชัดที่สุดในเชิง retrieval score ขณะที่ H2L-Hybrid ให้ภาพแบบสมดุลพร้อมยก MAP/MRR เหนือ hybrid baseline ส่วน H2L-Naive RAG ให้ผลแบบผสม และ H2L-HyDE ลดลงทั้งคุณภาพและเวลา จึงควรอธิบาย trade-off อย่างตรงไปตรงมา

3. **โมเดลหลักของวิทยานิพนธ์ควรเป็น H2L-Hybrid**
   เพราะเป็นตัวแทนของระบบเต็มที่รวม detector, hybrid retrieval, sentence polarity และ explanation stack เข้าด้วยกัน แม้จะไม่ใช่อันดับหนึ่งด้าน nDCG@5

4. **โมเดลทางเลือกที่โดดเด่นด้าน retrieval efficiency คือ H2L-BM25**
   หากจุดเน้นคือความเร็ว ความเรียบง่าย และ retrieval score สูงสุดใน test split ปัจจุบัน H2L-BM25 เป็นตัวเลือกที่น่าสนใจมาก

5. **บทสรุปในวิทยานิพนธ์ควรแยกคำว่า "ดีขึ้น" ออกเป็นสองมิติ**
   ได้แก่ "ดีขึ้นด้าน safety/polarity" และ "ดีขึ้นด้าน retrieval ranking" เพื่อไม่ให้การตีความคลาดเคลื่อน
