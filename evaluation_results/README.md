# Evaluation Artifacts

โฟลเดอร์นี้เก็บผลการประเมินหลายรอบของระบบ H2L ทั้ง benchmark, pair reruns,
progress artifacts และผล runtime บางกรณี เพื่อให้ trace ย้อนหลังได้โดยไม่ต้องพึ่ง
ค่า mock หรือค่าที่คัดลอกมาใส่ใหม่

## Canonical Files

- `proper_eval_latest_summary.json`
  สรุปผล proper evaluation ล่าสุดที่ใช้เป็น headline ของงานวิจัย
- `proper_eval_latest_raw.json`
  ผลรายเคสของ proper evaluation ล่าสุดในระดับ strategy aggregates และ raw metrics
- `proper_eval_latest_cases.json`
  รายละเอียดระดับเคสของ proper evaluation ล่าสุด
- `proper_eval_checkpoint_summary.json`
- `proper_eval_checkpoint_raw.json`
- `proper_eval_checkpoint_cases.json`
  checkpoint alias สำหรับระหว่างที่ evaluator ยังรันไม่เสร็จ
- `sentence_polarity_latest.json`
  canonical polarity artifact ล่าสุด
- `sentence_polarity_progress.json`
- `proper_eval_progress.json`
  สถานะการรัน evaluator จากไฟล์จริงที่ dashboard อ่านได้โดยตรง
- `pairs/`
  pair reruns แยกตาม retrieval family เพื่อใช้เปรียบเทียบ baseline กับ H2L
- `general_case_latest.json`
  snapshot ของ runtime case analysis ล่าสุดที่ใช้เป็นตัวอย่างเคสจริงนอก benchmark
- `ground_truth_audit.json` / `ground_truth_audit.md`
  รายงานตรวจ split integrity, family leakage, near-duplicate cross-split cases และสถานะ generated/stress-test cases
- `q1_readiness_report.md`
  รายงาน conservative claim readiness ที่อ่านค่าจาก artifact จริงและเตือนเมื่อผลยังไม่ significant หรือมี risk flags

## Timestamped History

ไฟล์ที่ลงท้ายด้วย timestamp เช่น `proper_eval_summary_YYYYMMDD_HHMMSS.json`
หรือ `sentence_polarity_eval_YYYYMMDD_HHMMSS.json` ทำหน้าที่เป็นประวัติการรันจริง
ซึ่งช่วยให้ย้อนกลับไปดูผลแต่ละรอบได้โดยไม่ทำให้ alias ล่าสุดเปลี่ยนความหมาย

## Thesis Usage

หากต้องอ้างอิงตัวเลขในเล่มหรือใน dashboard ให้ยึดไฟล์กลุ่ม `*_latest*` เป็นหลัก
และใช้ไฟล์ timestamped เพื่อตรวจ provenance หรือ replay ผลของรอบประเมินก่อนหน้า

ก่อนใช้ผลเป็น claim ระดับบทความ ให้รัน:

```bash
python scripts/ground_truth_audit.py
python scripts/q1_readiness_report.py
```

ถ้า `q1_readiness_report.md` ระบุว่าเป็น `trend_only` หรือพบ split leakage ให้เขียนข้อสรุปแบบจำกัดขอบเขต
และใช้ blind expert evaluation / external holdout เพิ่มก่อน claim ว่า H2L เหนือกว่า baseline โดยทั่วไป
