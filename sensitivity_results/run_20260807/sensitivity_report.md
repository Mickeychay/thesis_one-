# H2L V6 Score-Function Parameter Sensitivity Report

**Generated**: 2026-08-08 00:10

**Analysis scope**: `score_function_oat`
**Retrieval executed**: `false`

**Baseline Score**: 1.479691
**Baseline Boost**: 3.2882
**Train cases selected**: 125
**Cases scored**: 115
**Empty problem lists skipped by design**: 10

### ขอบเขตและชุดข้อมูล (Analysis Scope and Dataset)
เลือกเคสชุดฝึก **125** เคสจาก unified ground truth; คำนวณได้จริง **115** เคส และข้าม **10** เคสที่ expected problem list ว่างตามนิยามของชุดข้อมูล
การวิเคราะห์นี้ปรับพารามิเตอร์ครั้งละหนึ่งค่า โดยคงค่าอื่นไว้ที่ค่าปริยาย และเรียกเฉพาะ `calculate_final_score_probabilistic`
ไม่มีการรัน retrieval, L1/L2 detection, reranker หรือ embedding model ในการวิเคราะห์นี้ ดังนั้นผลลัพธ์จึงอธิบายความไวของฟังก์ชันคะแนนภายใต้สมมติฐานนี้ ไม่ใช่ประสิทธิภาพหรือความเสถียรของโมเดล retrieval ทั้งระบบ

### เกณฑ์การตีความ (Interpretation Guide)
- **Low sensitivity:** ค่าเฉลี่ยของฟังก์ชันคะแนนเปลี่ยนแปลงน้อยกว่า 5% จากค่าปริยายภายในช่วงที่ทดสอบ
- **Moderate sensitivity:** ค่าเฉลี่ยของฟังก์ชันคะแนนเปลี่ยนแปลงตั้งแต่ 5% แต่ไม่ถึง 10%
- **High sensitivity:** ค่าเฉลี่ยของฟังก์ชันคะแนนเปลี่ยนแปลงตั้งแต่ 10% ขึ้นไป
- **Not exercised:** พารามิเตอร์อยู่ในสาขาการคำนวณที่ไม่ถูกเรียกใช้ภายใต้สมมติฐานนี้ จึงไม่สามารถสรุปความไวจาก delta เท่ากับศูนย์

## Parameter Impact Summary

| Parameter | Default | Min delta | Max delta | Max absolute delta | Interpretation |
|-----------|---------|-----------|-----------|--------------------|----------------|
| T_base (Calibration) | 0.5 | -17.91% | +11.68% | 17.91% | High sensitivity |
| T_range (Calibration) | 1.5 | -2.26% | +1.32% | 2.26% | Low sensitivity |
| λ_neg (Polarity Gate) | 0.6 | -0.13% | +0.12% | 0.13% | Low sensitivity |
| κ (KL Penalty) | 0.15 | -0.16% | +0.16% | 0.16% | Low sensitivity |
| m (Margin) | 0.3 | +0.00% | +0.00% | 0.00% | Not exercised in this score-function setup |
| μ (Dirichlet) | 2.0 | -0.22% | +0.16% | 0.22% | Low sensitivity |
| α₀ (Base Weight) | 1.0 | -59.40% | +227.26% | 227.26% | High sensitivity |
| β (L1/L2 Balance) | 0.3 | +0.00% | +0.00% | 0.00% | Not exercised in this score-function setup |

## สรุปความไวของฟังก์ชันคะแนน (Overall Score-Function Sensitivity)

> ฟังก์ชันคะแนนมีความไวสูงต่อบางพารามิเตอร์ (ค่าเปลี่ยนแปลงสูงสุด 227.3%) ภายใต้ช่วงค่าที่ทดสอบ

### ข้อจำกัดในการตีความ

`MARGIN_M` ไม่ถูกกระตุ้นเนื่องจากไม่ได้ส่ง document/problem embeddings เข้าสู่ฟังก์ชันคะแนน และ `L1_WEIGHT_BETA` ไม่ถูกกระตุ้นเนื่องจากใช้ detected problem list กับ confidence คงที่ ค่า delta เท่ากับศูนย์ของสองพารามิเตอร์นี้จึงไม่ใช่หลักฐานว่ามีความไวต่ำ
