# บทที่ 1: บทนำ (Introduction)

## 1.1 ความเป็นมาและความสำคัญของปัญหา (Background and Significance)

งานสังคมสงเคราะห์ทางการแพทย์และงานคัดกรองปัญหาสังคมในโรงพยาบาลต้องอาศัยการอ่านบันทึกข้อความเสรีจำนวนมาก เช่น บันทึกการสัมภาษณ์ผู้รับบริการ การลงพื้นที่เยี่ยมบ้าน และสรุปปัญหาครอบครัวหรือสุขภาพจิต ข้อความเหล่านี้มักประกอบด้วยบริบทหลายชั้นในเคสเดียวกัน เช่น มีหลายบุคคลเกี่ยวข้อง มีการใช้ active/passive voice มี self-harm ที่กล่าวอย่างอ้อม มี clause ที่ขัดกัน และมีประโยคปฏิเสธ เช่น "ไม่ได้ทำร้ายตัวเอง" หรือ "บิดามารดาไม่รู้เรื่อง" ทำให้การใช้ระบบสืบค้นหรือระบบตรวจจับปัญหาที่อาศัยเพียง keyword matching หรือ semantic similarity อย่างเดียวมีความเสี่ยงต่อการตีความผิด

ปัญหาสำคัญที่พบในระบบปัจจุบันคือ **Negation Blindness** และ **Role Confusion** กล่าวคือ ระบบสามารถจับคำสำคัญรุนแรงได้ แต่ไม่สามารถแยกได้ดีพอว่าใครเป็นผู้กระทำ ใครเป็นผู้ถูกกระทำ และคำปฏิเสธนั้นครอบพฤติกรรมใดกันแน่ ผลที่ตามมาคือ false positive, การจับปัญหาผิดหมวด, และการค้นคืนเอกสารที่ดูเหมือนเกี่ยวข้องแต่ไม่สอดคล้องกับบริบทของเคสจริง ปัญหานี้ยิ่งมีนัยสำคัญเมื่อระบบถูกนำไปใช้เพื่อช่วยคัดกรองเคสเปราะบางในบริบทสังคมสงเคราะห์ ซึ่งต้องการทั้งความแม่นยำ ความปลอดภัย และความสามารถในการตรวจสอบย้อนกลับ

เพื่อตอบโจทย์ดังกล่าว วิทยานิพนธ์นี้เสนอ **H2L (A Two-Level Hierarchical Retrieval-Augmented Generation Approach with Polarity Gates for Screening and Differential Diagnosis of Social Problems)** ซึ่งออกแบบให้เป็นสถาปัตยกรรมเชิงระบบมากกว่าการเป็น retriever ตัวใหม่เพียงตัวเดียว โดยแกนหลักของ H2L ประกอบด้วย

- **L1 Context-Aware Keyword Detection:** ใช้การจับคำสำคัญร่วมกับกฎเชิงบริบท เช่น actor-target-action, passive/active pattern, self-harm pattern, clause boundary และ social action terms
- **L2 Semantic Validation:** ใช้แบบจำลองภาษาเพื่อตรวจสอบเฉพาะกรณีที่ L1 ยังไม่ชัดเจน เช่น conflict, implicit problem, หรือ candidate ที่กำกวม
- **Problem-Aware Retrieval and H2L Scoring:** ใช้ผล problem detection ไปช่วยขยาย query และปรับคะแนนเอกสารตาม prior, severity, semantic match, specificity และ polarity signal
- **Sentence Polarity Gate:** ใช้ candidate-specific gating เพื่อลด false positive จากข้อความปฏิเสธ โดยไม่ปะปนกับการให้คะแนน retrieval โดยตรง
- **Interactive Explainability Stack:** รายงานผลผ่าน Live Execution Path, Problem-Document Matrix, Semantic Evidence Map, Case H2L Summary, H2L Document Score Breakdown, Event Frames, token-level highlights รวมถึง `Performance Provenance`, `System Evaluation Status`, live evaluation progress และ artifact retention policy เพื่อให้ผู้ใช้แยกผลระดับเคสออกจากผล benchmark ตรวจว่าไฟล์ล่าสุดใดกำลังถูกใช้ และตรวจสอบย้อนกลับได้

แนวคิดสำคัญของงานนี้คือ H2L ไม่ได้พยายามแทนที่ retrieval backbone เดิมทั้งหมด แต่ทำหน้าที่เป็น **problem-aware scoring and safety layer** ที่สามารถครอบบน baseline หลายแบบได้ เช่น BM25, dense retrieval, HyDE และ hybrid retrieval การออกแบบเช่นนี้ทำให้งานวิจัยสามารถตอบคำถามหลักได้ทั้งด้าน retrieval quality และ safety from negation errors พร้อมทั้งมีชั้น explainability รองรับการตีความผลลัพธ์ในระดับเคสและเอกสารหลักฐาน

---

## 1.2 คำถามการวิจัย (Research Questions)

1. H2L ในฐานะ problem-aware scoring layer ให้ผลด้านคุณภาพการจัดอันดับเอกสารแตกต่างจาก baseline อย่างไร เมื่อครอบบน retrieval backbone หลายแบบและวัดด้วย nDCG@K, MAP และ MRR?

2. Sentence polarity gate ภายในสถาปัตยกรรม H2L ช่วยลด false positive จากประโยคที่ต้องอาศัยการตีความเชิงบริบท เช่น negation, actor-target-action และ clause boundary ได้ในระดับใด เมื่อวัดด้วย Accuracy, Negation Detection Rate (NDR), False Positive Rate (FPR) และ F1?

---

## 1.3 วัตถุประสงค์ของการวิจัย (Research Objectives)

1. พัฒนาระบบ H2L สำหรับตรวจจับปัญหาสังคมจากข้อความภาษาไทย โดยใช้ L1 context-aware detection และ L2 semantic validation ทำงานร่วมกัน
2. ออกแบบ sentence polarity gate แบบ candidate-specific เพื่อจัดการกับคำปฏิเสธและลด false positive ที่เกิดจากการจับคำสำคัญอย่างผิวเผิน
3. ประเมินผล H2L บน retrieval backbone หลายแบบ ได้แก่ BM25, dense retrieval, HyDE และ hybrid retrieval ภายใต้กรอบ paired comparison ที่ใช้ข้อมูลจริง
4. สร้างชั้นการอธิบายผลที่ตรวจสอบย้อนกลับได้ ทั้งในระดับ analyzed case text แบบ occurrence-aware, event frames, live execution path, Case H2L Summary, H2L Document Score Breakdown, Problem-Document Matrix, Semantic Evidence Map และการแยก case-level ออกจาก benchmark-level report
5. สังเคราะห์ข้อค้นพบเชิงวิชาการและเชิงระบบที่สามารถนำไปใช้สรุปผลในระดับวิทยานิพนธ์ได้อย่างตรงกับการทำงานจริงของระบบ

---

## 1.4 ขอบเขตของการวิจัย (Scope and Boundaries)

1. **ขอบเขตข้อมูล:** ใช้ taxonomy ของปัญหาสังคมจำนวน 34 กลุ่ม 202 รหัสย่อย และใช้ชุดข้อมูล `expanded_ground_truth.json` จำนวน 197 เคส โดยเก็บในไฟล์เดียวและแยก train 129 เคส กับ test 68 เคสด้วย family-level leakage-safe split
2. **ขอบเขตการประเมิน retrieval:** ผลหลักในวิทยานิพนธ์อ้างอิงจาก proper evaluation แบบ `problem_source=detected` และ `top_k=15` เพื่อให้ทุกส่วนของระบบใช้ค่าเดียวกันในการรายงานผล แม้ว่าหน้าเว็บจะรองรับการสำรวจค่า top-k ได้หลายระดับ
3. **ขอบเขต sentence polarity:** ประเมินบน test set 68 เคส ซึ่งมีเคสยืนยันปัญหา 50 เคส และเคสปฏิเสธ 18 เคส โดยวัดผลแยกจาก retrieval metrics
4. **ขอบเขตเทคโนโลยี:** L1 ใช้ keyword and context rules, L2 ใช้ Qwen2.5 7B ผ่าน Ollama, retrieval ใช้ BM25, embedding model, HyDE และ hybrid retrieval พร้อม reranking
5. **ขอบเขตภาษา:** งานวิจัยนี้มุ่งเน้นภาษาไทย และรองรับลักษณะภาษาที่เกี่ยวข้องกับปัญหาสังคม เช่น passive pattern, active pattern, self-harm expression, bullying/social action terms และประโยคปฏิเสธ
6. **ขอบเขต explainability:** มุ่งเน้นการอธิบายผลผ่าน traces, evidence maps และ score breakdowns ไม่ได้อ้างว่าแก้ปัญหา explainability ของ LLM ได้ทั้งหมดในทุกบริบท

---

## 1.5 ประโยชน์ที่คาดว่าจะได้รับ (Expected Contributions)

1. **เชิงวิชาการ:** เสนอกรอบคิดที่แยกการประเมิน retrieval quality ออกจาก sentence polarity safety อย่างชัดเจน ทำให้การอภิปรายผลไม่สับสนระหว่าง "ค้นได้ดี" กับ "ปลอดภัยพอสำหรับการใช้งาน"
2. **เชิงระบบ:** พัฒนา H2L ให้เป็นชั้น problem-aware scoring ที่สามารถนำไปครอบบน baseline หลายแบบได้ โดยไม่ต้องออกแบบ retriever ใหม่ทั้งหมด
3. **เชิงปฏิบัติ:** ช่วยให้นักสังคมสงเคราะห์หรือผู้วิจัยตรวจสอบว่าเคสหนึ่ง ๆ ถูกจับปัญหาอะไร เพราะอะไร และอ้างอิงเอกสารชิ้นใดเป็นหลักฐาน
4. **เชิงอธิบายผล:** ยกระดับการรายงานผลจากการแสดงตัวเลขรวม ไปสู่การแสดง live execution path, event frames, Problem-Document Matrix, Semantic Evidence Map, Case H2L Summary, H2L Document Score Breakdown, evaluator progress และ provenance/retention ของ artifact ที่ผู้อ่านเข้าใจได้ง่ายขึ้น
5. **เชิงวิทยานิพนธ์:** ทำให้การสรุปผลของระบบสอดคล้องกับผลประเมินจริง ไม่อาศัย mock data หรือ simulated statistics ในบทอภิปรายผล

---

## 1.6 นิยามศัพท์เฉพาะ (Definition of Key Terms)

| คำศัพท์ | นิยาม |
|:---|:---|
| **H2L** | สถาปัตยกรรมสองระดับสำหรับตรวจจับปัญหาและค้นคืนเอกสาร โดยใช้ L1, L2, H2L scoring และ sentence polarity gate ร่วมกัน |
| **Sentence Polarity Gate** | กลไกที่ลดหรือตัดน้ำหนัก problem candidate เมื่อมีหลักฐานว่าคำปฏิเสธครอบพฤติกรรมหรือปัญหานั้นโดยตรง |
| **Problem-Aware Retrieval** | การค้นคืนเอกสารที่ไม่ใช้ query text อย่างเดียว แต่ใช้ problem codes และบริบทของเคสจริงช่วยปรับอันดับเอกสาร |
| **Actor-Target-Action** | โครงสร้างเชิงเหตุการณ์ที่ช่วยระบุว่าใครเป็นผู้กระทำ ใครเป็นผู้ถูกกระทำ และเกิดพฤติกรรมใดขึ้น |
| **Semantic Evidence Map** | มุมมองเชิงโต้ตอบที่เชื่อม query, problems และ supporting documents เพื่อช่วยอธิบาย semantic distance, node relation และเหตุผลเชิงลึกของการดึงเอกสาร |
| **Problem-Document Matrix** | มุมมองเชิงโครงสร้างที่แสดงว่า problem code ใดมี supporting document ใดหนุนอยู่บ้าง และหนุนแรงมากน้อยเพียงใด |
| **Live Execution Path** | ภาพรวมลำดับการประมวลผลของระบบจาก case text ไปสู่ detected problems, polarity effect และ evidence retrieval |
| **Performance Provenance** | ส่วนของรายงานที่อธิบายว่าผลที่กำลังอ่านมาจาก runtime ของเคสปัจจุบันหรือจาก benchmark artifacts บน test split |
| **System Evaluation Status** | ส่วนสรุปว่าหลักฐาน benchmark ใดพร้อมใช้สรุปผลแล้ว และหัวข้อใดยังต้อง review เพิ่มก่อนอ้างอิงในวิทยานิพนธ์ |
| **nDCG@K / MAP / MRR** | มาตรวัดคุณภาพการจัดอันดับเอกสารที่ใช้ประเมิน retrieval performance |
| **NDR / FPR / F1** | มาตรวัดด้าน sentence polarity และความปลอดภัยของการคัดกรองบริบท |
