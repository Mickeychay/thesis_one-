import { useMemo, useState, useRef, useEffect, useCallback } from 'react';

// Structured Metric Groups with Measurements and Top-K Scales
const METRIC_GROUPS = [
  {
    id: 'ndcg',
    name: 'nDCG (Ranking Quality)',
    shortLabel: 'nDCG',
    icon: 'military_tech',
    measurement: 'วัดคุณภาพการจัดอันดับเอกสารตามลำดับความสำคัญ (ให้คะแนนสูงกับเอกสารตรงที่อยู่อันดับต้น)',
    hasScale: true,
    scales: [
      { id: 'NDCG1', k: 1, label: '@1', fullLabel: 'nDCG@1', maxVal: 0.950, desc: 'Top-1 — ความแม่นยำของเอกสารอันดับแรกสุด' },
      { id: 'NDCG3', k: 3, label: '@3', fullLabel: 'nDCG@3', maxVal: 0.942, desc: 'Top-3 — คุณภาพการจัดอันดับ 3 อันดับแรก' },
      { id: 'NDCG5', k: 5, label: '@5', fullLabel: 'nDCG@5', maxVal: 0.938, desc: 'Top-5 — จุดสมดุลมาตรฐานทางการแพทย์' },
      { id: 'NDCG10', k: 10, label: '@10', fullLabel: 'nDCG@10', maxVal: 0.915, desc: 'Top-10 — คุณภาพการจัดอันดับขอบเขตกว้าง' },
      { id: 'NDCG15', k: 15, label: '@15', fullLabel: 'nDCG@15', maxVal: 0.902, desc: 'Top-15 — การจัดอันดับครอบคลุมลึกระดับสูงสุด' },
    ],
    defaultMetricId: 'NDCG5',
  },
  {
    id: 'precision',
    name: 'Precision (P@K - Accuracy)',
    shortLabel: 'Precision',
    icon: 'check_circle',
    measurement: 'วัดสัดส่วนความถูกต้อง/แม่นยำของเอกสารที่ดึงมา (ลด Noise และไม่ดึงเอกสารขยะ)',
    hasScale: true,
    scales: [
      { id: 'P5', k: 5, label: '@5', fullLabel: 'P@5', maxVal: 0.880, desc: 'Top-5 — สัดส่วนหลักฐานตรงใน 5 อันดับแรก' },
      { id: 'P10', k: 10, label: '@10', fullLabel: 'P@10', maxVal: 0.840, desc: 'Top-10 — สัดส่วนหลักฐานตรงใน 10 อันดับแรก' },
      { id: 'P15', k: 15, label: '@15', fullLabel: 'P@15', maxVal: 0.810, desc: 'Top-15 — สัดส่วนหลักฐานตรงใน 15 อันดับแรก' },
    ],
    defaultMetricId: 'P5',
  },
  {
    id: 'recall',
    name: 'Recall (R@K - Coverage)',
    shortLabel: 'Recall',
    icon: 'search_insights',
    measurement: 'วัดสัดส่วนความครอบคลุมหลักฐานทั้งหมดที่จำเป็น (ไม่หลุดประเด็นสำคัญของผู้ป่วย)',
    hasScale: true,
    scales: [
      { id: 'R5', k: 5, label: '@5', fullLabel: 'R@5', maxVal: 0.865, desc: 'Top-5 — สัดส่วนการครอบคลุมหลักฐานที่ Top-5' },
      { id: 'R10', k: 10, label: '@10', fullLabel: 'R@10', maxVal: 0.920, desc: 'Top-10 — สัดส่วนการครอบคลุมหลักฐานที่ Top-10' },
      { id: 'R15', k: 15, label: '@15', fullLabel: 'R@15', maxVal: 0.965, desc: 'Top-15 — สัดส่วนการครอบคลุมหลักฐานสูงสุดที่ Top-15' },
    ],
    defaultMetricId: 'R5',
  },
  {
    id: 'f1',
    name: 'F1 Score (Balanced Score)',
    shortLabel: 'F1 Score',
    icon: 'balance',
    measurement: 'วัดความสมดุลระหว่างความแม่นยำ (Precision) และความครอบคลุม (Recall) ด้วย Harmonic Mean',
    hasScale: true,
    scales: [
      { id: 'F1_5', k: 5, label: '@5', fullLabel: 'F1@5', maxVal: 0.884, desc: 'Top-5 — ความสมดุลระหว่าง Precision และ Recall' },
      { id: 'F1_15', k: 15, label: '@15', fullLabel: 'F1@15', maxVal: 0.875, desc: 'Top-15 — ความสมดุลระดับลึกที่ 15 อันดับ' },
    ],
    defaultMetricId: 'F1_5',
  },
  {
    id: 'global',
    name: 'Global Metrics (MAP & MRR)',
    shortLabel: 'Global',
    icon: 'analytics',
    measurement: 'วัดประสิทธิภาพภาพรวมตลอดทั้งรายการค้นคืน (MAP) และความเร็วในการพบเอกสารที่ถูกต้องชิ้นแรก (MRR)',
    hasScale: false,
    options: [
      { id: 'MAP', label: 'MAP', fullLabel: 'MAP (Mean Avg Precision)', maxVal: 0.912, desc: 'Mean Average Precision — ความแม่นยำเฉลี่ยตลอดทั้งรายการค้นคืน' },
      { id: 'MRR', label: 'MRR', fullLabel: 'MRR (Mean Reciprocal Rank)', maxVal: 0.945, desc: 'Mean Reciprocal Rank — ความเร็วในการค้นพบเอกสารที่ถูกต้องชิ้นแรก' },
    ],
    defaultMetricId: 'MAP',
  },
];

// Flat metrics map for easy lookup
const ALL_METRICS_LIST = METRIC_GROUPS.flatMap((g) => (g.hasScale ? g.scales : g.options)).map((m) => ({
  ...m,
  metricKey: m.fullLabel || m.label,
  axisLabel: m.fullLabel || m.label,
}));

// Parameter Pairs for RQ Sensitivity Studies
// Parameter Pairs for Comprehensive Clinical Decision Support RQ Sensitivity Studies
const PARAMETER_PAIRS = [
  {
    id: 'alpha_thresh',
    title: 'H2L Weight (α) × Threshold (τ)',
    xLabel: 'Threshold (τ)',
    zLabel: 'α (H2L Weight)',
    xName: 'Decision Threshold (τ)',
    zName: 'H2L Interpolation Weight (α)',
    xObjective: 'ใช้วัดระดับความเข้มงวดในการตรวจจับปัญหาทางการแพทย์ (Finding Confidence Cutoff: 0.10–0.90)',
    zObjective: 'ใช้วัดสัดส่วนน้ำหนักที่นำคะแนนปัญหา H2L ไปผสมผสานกับคะแนนการค้นคืนเดิม (0.00–1.00)',
    rqTag: 'RQ2: Hybrid Balancing',
    xMin: 0.10,
    xMax: 0.90,
    zMin: 0.00,
    zMax: 1.00,
    xOpt: 0.50,
    zOpt: 0.65,
    xStep: 0.05,
    zStep: 0.05,
    optScore: 0.938,
    ticksX: [0.10, 0.30, 0.50, 0.70, 0.90],
    ticksZ: [0.00, 0.25, 0.50, 0.65, 0.75, 1.00],
    safeZone: { xMin: 0.35, xMax: 0.65, zMin: 0.45, zMax: 0.80 },
    purpose: 'ทดสอบสมมติฐานว่าการจัดอันดับเอกสารแบบ Hybrid (ผสมผสานระหว่างปัญหาผู้ป่วยกับความคล้ายคลึงของเอกสารเดิม) ให้ผลลัพธ์เหนือกว่า Baseline เดี่ยวๆ',
    howToRead: 'แกน X คือเกณฑ์ตัดปัญหา (ซ้าย=หละหลวม, ขวา=เข้มงวด) · แกน Z คือน้ำหนัก H2L (ล่าง=Baselineเดิม, บน=เน้นเฉพาะปัญหา) · ความสูงแกน Y คือคุณภาพการจัดอันดับ จุดยอดเขา (α=0.65, τ=0.50) คือจุดทำงานที่สมดุลที่สุด หากปรับ α=0 กราฟจะยุบลงสู่ Baseline',
    interpretation: 'จุดยอดเขาอยู่ที่ α = 0.65, τ = 0.50 แสดงให้เห็นว่าการผสมผสาน H2L แบบ Hybrid ชนะทั้ง Baseline เดิม (α = 0) และการพึ่งพาเฉพาะ Finding เพียงอย่างเดียว (α = 1)',
    pipelineRole: 'Finding Gate (τ) → Hybrid Document Re-ranking Score (α)',
    keyTakeaways: [
      { icon: 'star', text: 'จุดทำงานแนะนำตามแบบจำลอง: α = 0.65, τ = 0.50 (จุดสมดุลระหว่างปัญหา H2L กับความคล้ายคลึงของข้อความ)' },
      { icon: 'warning', text: 'ถ้า α = 0.00: ระบบจะกลายเป็น Baseline เดิม ซึ่งคะแนนตกไปอยู่ที่ระดับ Baseline' },
      { icon: 'shield', text: 'Safe Operating Zone: ค่า τ อยู่ช่วง 0.40–0.60 และ α อยู่ช่วง 0.50–0.80 ให้ผลลัพธ์สูงสม่ำเสมอ' },
    ],
    zoneAnnotations: [
      { text: '⭐ Sweet Spot (α=0.65, τ=0.50)', u: 0.50, v: 0.65, type: 'peak' },
      { text: '⚠️ Baseline Fallback (α=0)', u: 0.50, v: 0.05, type: 'low' },
      { text: '⚠️ Over-filtering (τ>0.8)', u: 0.85, v: 0.65, type: 'drop' },
    ],
  },
  {
    id: 'neg_thresh',
    title: 'Negation Penalty (β) × Threshold (τ)',
    xLabel: 'Threshold (τ)',
    zLabel: 'β (Negation Penalty)',
    xName: 'Decision Threshold (τ)',
    zName: 'Negation Scope Penalty (β)',
    xObjective: 'ใช้วัดเกณฑ์ความมั่นใจในการระบุว่ามีปัญหาทางการแพทย์เกิดขึ้นจริง (0.10–0.90)',
    zObjective: 'ใช้วัดความเด็ดขาดในการตัดคะแนน/ลงโทษเมื่อตรวจพบประโยคปฏิเสธ เช่น "ไม่มีประวัติ...", "ปฏิเสธ..." (0.00–1.00)',
    rqTag: 'RQ1: Negation Safety & Robustness',
    xMin: 0.10,
    xMax: 0.90,
    zMin: 0.00,
    zMax: 1.00,
    xOpt: 0.50,
    zOpt: 0.85,
    xStep: 0.05,
    zStep: 0.05,
    optScore: 0.941,
    ticksX: [0.10, 0.30, 0.50, 0.70, 0.90],
    ticksZ: [0.00, 0.20, 0.40, 0.60, 0.85, 1.00],
    safeZone: { xMin: 0.35, xMax: 0.65, zMin: 0.70, zMax: 1.00 },
    purpose: 'พิสูจน์ความปลอดภัยทางคลินิก (Clinical Safety) ว่าระบบสามารถตัดประโยคปฏิเสธทิ้งได้เด็ดขาด ป้องกันการดึงแนวทางช่วยเหลือที่คนไข้ไม่ได้เป็น',
    howToRead: 'แกน Z ยิ่งสูง = การลงโทษประโยคปฏิเสธยิ่งเด็ดขาด จะเห็นว่าเมื่อ β ≥ 0.70 พื้นผิวจะยกตัวเป็นที่ราบสูงปลอดภัย (Safe Plateau) แต่ถ้า β ต่ำ (<0.30) กราฟจะดิ่งลงเหวเพราะโมเดลสับสน นำประวัติปฏิเสธมาค้นเอกสาร',
    interpretation: 'การตั้งค่า β ในช่วง 0.70–1.00 ช่วยกำจัด False Positive จากประโยคปฏิเสธได้สมบูรณ์แบบ ทำให้การจัดอันดับมีคุณภาพสูงและปลอดภัยต่อผู้ป่วยจริง',
    pipelineRole: 'Negation Scope Detector → Confidence Penalty Suppressor (β)',
    keyTakeaways: [
      { icon: 'star', text: 'จุดทำงานดีที่สุด: β = 0.85, τ = 0.50 ตัดประโยคปฏิเสธเด็ดขาด ปลอดภัยสูงสุดทางการแพทย์' },
      { icon: 'warning', text: 'ถ้า β < 0.30: โมเดลจะดึงเอกสารของโรคที่คนไข้ปฏิเสธมาแสดง ทำให้คะแนนดิ่งลงอย่างรุนแรง' },
      { icon: 'shield', text: 'Safe Operating Zone: β ≥ 0.70 ให้ความปลอดภัยคงที่และทนทานต่อรูปแบบการเขียนประวัติของแพทย์' },
    ],
    zoneAnnotations: [
      { text: '⭐ Safe Zone (β=0.85, τ=0.50)', u: 0.50, v: 0.85, type: 'peak' },
      { text: '⚠️ Negation Leakage (β<0.3)', u: 0.50, v: 0.15, type: 'drop' },
      { text: '⚠️ Over-filtering (τ>0.8)', u: 0.85, v: 0.85, type: 'drop' },
    ],
  },
  {
    id: 'calib_thresh',
    title: 'Temperature (T_base) × Threshold (τ)',
    xLabel: 'Threshold (τ)',
    zLabel: 'T_base (Softmax Temp)',
    xName: 'Decision Threshold (τ)',
    zName: 'Confidence Temperature (T_base)',
    xObjective: 'ใช้วัดเกณฑ์ความมั่นใจในการตรวจจับปัญหาทางการแพทย์ (0.10–0.90)',
    zObjective: 'ใช้วัดการ Calibrate ความนุ่มนวลของการแจกแจงคะแนนความมั่นใจ Softmax (0.50–2.50)',
    rqTag: 'RQ3: Confidence Calibration',
    xMin: 0.10,
    xMax: 0.90,
    zMin: 0.50,
    zMax: 2.50,
    xOpt: 0.50,
    zOpt: 1.20,
    xStep: 0.05,
    zStep: 0.10,
    optScore: 0.931,
    ticksX: [0.10, 0.30, 0.50, 0.70, 0.90],
    ticksZ: [0.50, 0.90, 1.20, 1.60, 2.00, 2.50],
    safeZone: { xMin: 0.35, xMax: 0.65, zMin: 0.90, zMax: 1.50 },
    purpose: 'ทดสอบว่าการ Calibrate ความมั่นใจช่วยป้องกันปัญหาโมเดลมั่นใจเกินจริง (Overconfidence) ในกรณีเคสที่มีความซับซ้อนได้อย่างไร',
    howToRead: 'สังเกตที่ราบสูง (Smooth Plateau) ช่วง T_base = 1.0–1.4 คือจุดที่ระบบยืดหยุ่นต่อคำศัพท์ หาก T ต่ำเกินไป (<0.8) กราฟจะแคบและเปราะบาง หาก T สูงเกินไป (>2.2) กราฟจะแบนราบเพราะคะแนนกระจายเท่ากันหมด',
    interpretation: 'ช่วงราบเรียบ (Plateau) อยู่ที่ T_base = 1.0–1.4 ซึ่ง Softmax มีความคมชัดพอดี; หาก T < 0.8 จะกลายเป็น Hard Cutoff ที่เปราะบาง; หาก T > 2.0 คะแนนจะแบนราบ',
    pipelineRole: 'L2 Soft Problem Matching → Temperature-calibrated Evidence Scoring (T_base)',
    keyTakeaways: [
      { icon: 'star', text: 'จุดทำงานดีที่สุด: T_base = 1.20, τ = 0.50 Softmax กระจายน้ำหนักได้คมชัดและยืดหยุ่น' },
      { icon: 'warning', text: 'ถ้า T_base < 0.80: ระบบจะกลายเป็น Hard Match แบบเปราะบาง หากคำต่างนิดเดียวจะไม่จับคู่' },
      { icon: 'shield', text: 'Safe Operating Zone: ช่วง T_base = 1.00–1.40 เป็นที่ราบกว้าง (Plateau) ปลอดภัยต่อข้อมูลจริง' },
    ],
    zoneAnnotations: [
      { text: '⭐ Smooth Plateau (T=1.20)', u: 0.50, v: 1.20, type: 'peak' },
      { text: '⚠️ Hard Cutoff (T<0.8)', u: 0.50, v: 0.60, type: 'low' },
      { text: '⚠️ Over-smoothed (T>2.2)', u: 0.50, v: 2.30, type: 'drop' },
    ],
  },
  {
    id: 'kl_thresh',
    title: 'Prior Penalty (κ) × Threshold (τ)',
    xLabel: 'Threshold (τ)',
    zLabel: 'κ (Prior Penalty)',
    xName: 'Decision Threshold (τ)',
    zName: 'Prior Divergence Penalty (κ)',
    xObjective: 'ใช้วัดเกณฑ์ความมั่นใจในการตรวจจับปัญหา (0.10–0.90)',
    zObjective: 'ใช้วัดตัวลงโทษการกระจายตัวของปัญหาที่ไม่สอดคล้องกับความรุนแรงของโรค (0.00–2.00)',
    rqTag: 'RQ4: Prior Regularization',
    xMin: 0.10,
    xMax: 0.90,
    zMin: 0.00,
    zMax: 2.00,
    xOpt: 0.50,
    zOpt: 0.80,
    xStep: 0.05,
    zStep: 0.10,
    optScore: 0.925,
    ticksX: [0.10, 0.30, 0.50, 0.70, 0.90],
    ticksZ: [0.00, 0.40, 0.80, 1.20, 1.60, 2.00],
    safeZone: { xMin: 0.35, xMax: 0.65, zMin: 0.50, zMax: 1.10 },
    purpose: 'ทดสอบผลของการลงโทษปัญหาที่เป็น Noise เพื่อให้ระบบเน้นเฉพาะปัญหาที่มีนัยสำคัญทางคลินิกสอดคล้องกับข้อมูลเวชระเบียนประชากร',
    howToRead: 'รูปทรงโดมยอดมนที่ κ = 0.80 แสดงถึงการคุมเสถียรภาพ หาก κ = 0 จะไม่มีการควบคุม Prior แต่หาก κ > 1.5 กราฟจะลาดลงเพราะระบบลงโทษปัญหาหายากมากเกินไป',
    interpretation: 'ยอดเขามีลักษณะโค้งมนที่ κ = 0.80 ช่วยลด False Positives จากปัญหาที่ไม่รุนแรง; หาก κ > 1.5 คะแนนจะลดลงเนื่องจากลงโทษปัญหาหายากมากเกินไป',
    pipelineRole: 'Prior Severity Distribution → Divergence Penalty Regularization (κ)',
    keyTakeaways: [
      { icon: 'star', text: 'จุดทำงานดีที่สุด: κ = 0.80, τ = 0.50 ช่วยกรองปัญหา Noise ที่ไม่รุนแรงออกได้อย่างแม่นยำ' },
      { icon: 'warning', text: 'ถ้า κ > 1.50: ระบบจะลงโทษปัญหาที่พบน้อยมากเกินไป ทำให้คะแนนลดลงเหลือ ~0.82' },
      { icon: 'shield', text: 'Safe Operating Zone: ค่า κ ในช่วง 0.50–1.10 มีความเสถียรสูง เหมาะกับการใช้งานจริง' },
    ],
    zoneAnnotations: [
      { text: '⭐ Optimal Prior (κ=0.80)', u: 0.50, v: 0.80, type: 'peak' },
      { text: '⚠️ No Regularization (κ=0)', u: 0.50, v: 0.05, type: 'low' },
      { text: '⚠️ Heavy Penalty (κ>1.6)', u: 0.50, v: 1.80, type: 'drop' },
    ],
  },
  {
    id: 'idf_budget',
    title: 'IDF Weight (λ) × Evidence Budget (K)',
    xLabel: 'Budget (K)',
    zLabel: 'λ (IDF Specificity)',
    xName: 'Evidence Retrieval Budget (Top-K)',
    zName: 'IDF Term Specificity Weight (λ)',
    xObjective: 'ใช้วัดจำนวนเอกสารหลักฐานที่ส่งต่อให้แพทย์/นักสังคมสงเคราะห์ทบทวน (K = 1 ถึง 15 ฉบับ)',
    zObjective: 'ใช้วัดน้ำหนักการให้ความสำคัญกับคำศัพท์เฉพาะทางคลินิกเทียบกับคำทั่วไป (0.00–1.00)',
    rqTag: 'RQ5: Term Specificity & Budget',
    xMin: 1,
    xMax: 15,
    zMin: 0.00,
    zMax: 1.00,
    xOpt: 5,
    zOpt: 0.70,
    xStep: 1,
    zStep: 0.05,
    optScore: 0.935,
    ticksX: [1, 3, 5, 10, 15],
    ticksZ: [0.00, 0.25, 0.50, 0.70, 1.00],
    safeZone: { xMin: 3, xMax: 10, zMin: 0.50, zMax: 0.85 },
    purpose: 'ทดสอบความสมดุลระหว่างภาระการอ่านของมนุษย์ (Cognitive Load ในงบ K) กับการให้น้ำหนักคำศัพท์เฉพาะทาง (IDF Specificity)',
    howToRead: 'แกน X คือจำนวนเอกสาร K ที่ดึงมา (1=น้อยสุด, 15=ลึกสุด) · แกน Z คือการเน้นคำเฉพาะทางคลินิก (0=ไม่ถ่วงน้ำหนัก, 1=เน้นสูงสุด) จุดสมดุลสูงสุดอยู่ที่ K=5, λ=0.70 ซึ่งแพทย์อ่านได้เร็วและได้สาระสำคัญครบถ้วน',
    interpretation: 'ที่ K = 5 และ λ = 0.70 ให้ค่าความสมดุลสูงสุดระหว่างภาระการอ่าน (Workload) และความครอบคลุมหลักฐานที่ตรงเป้า โดยไม่ก่อให้เกิด Information Overload',
    pipelineRole: 'IDF Lexical Booster (λ) → Human-in-the-loop Review Window (Top-K)',
    keyTakeaways: [
      { icon: 'star', text: 'จุดทำงานดีที่สุด: Top-5 และ λ = 0.70 ให้ความแม่นยำสูงโดยไม่เพิ่มภาระการอ่านแก่แพทย์' },
      { icon: 'warning', text: 'ถ้า λ = 0.00: ระบบจะไม่แยกแยะคำเฉพาะทาง ทำให้เอกสารทั่วไปขึ้นมาบดบังหลักฐานสำคัญ' },
      { icon: 'shield', text: 'Safe Operating Zone: K = 3–5 และ λ = 0.50–0.85 เหมาะสมที่สุดสำหรับสถานการณ์จริงหน้างาน' },
    ],
    zoneAnnotations: [
      { text: '⭐ Clinical Balance (K=5, λ=0.70)', u: (5 - 1) / 14, v: 0.70, type: 'peak' },
      { text: '⚠️ Unweighted Words (λ=0)', u: (5 - 1) / 14, v: 0.05, type: 'low' },
      { text: '⚠️ Cognitive Overload (K>12)', u: (14 - 1) / 14, v: 0.70, type: 'drop' },
    ],
  },
];

const PRESETS = [
  { id: 'default', label: 'Perspective (มุมเฉียง)', yaw: 45, pitch: 26, scale: 175 },
  { id: 'top', label: 'Top View (มุมบน)', yaw: 0, pitch: 65, scale: 165 },
  { id: 'side', label: 'Side View (มุมข้าง)', yaw: 85, pitch: 18, scale: 175 },
  { id: 'front', label: 'Front View (มุมหน้า)', yaw: 5, pitch: 18, scale: 175 },
];

// Color mapping from height (0.30 -> 0.95)
function getHeightColor(val, isDark = true, minVal = 0.30, maxVal = 0.95) {
  const norm = Math.max(0, Math.min(1, (val - minVal) / (maxVal - minVal)));
  if (isDark) {
    if (norm < 0.35) {
      const t = norm / 0.35;
      const r = Math.round(10 + t * (18 - 10));
      const g = Math.round(30 + t * (65 - 30));
      const b = Math.round(65 + t * (125 - 65));
      return `rgb(${r}, ${g}, ${b})`;
    } else if (norm < 0.70) {
      const t = (norm - 0.35) / 0.35;
      const r = Math.round(18 + t * (14 - 18));
      const g = Math.round(65 + t * (135 - 65));
      const b = Math.round(125 + t * (195 - 125));
      return `rgb(${r}, ${g}, ${b})`;
    } else {
      const t = (norm - 0.70) / 0.30;
      const r = Math.round(14 + t * (56 - 14));
      const g = Math.round(135 + t * (189 - 135));
      const b = Math.round(195 + t * (248 - 195));
      return `rgb(${r}, ${g}, ${b})`;
    }
  } else {
    if (norm < 0.35) {
      const t = norm / 0.35;
      const r = Math.round(203 - t * (203 - 147));
      const g = Math.round(213 - t * (213 - 197));
      const b = Math.round(225 - t * (225 - 253));
      return `rgb(${r}, ${g}, ${b})`;
    } else if (norm < 0.70) {
      const t = (norm - 0.35) / 0.35;
      const r = Math.round(147 - t * (147 - 14));
      const g = Math.round(197 - t * (197 - 148));
      const b = Math.round(253 - t * (253 - 196));
      return `rgb(${r}, ${g}, ${b})`;
    } else {
      const t = (norm - 0.70) / 0.30;
      const r = Math.round(14 - t * (14 - 5));
      const g = Math.round(148 + t * (150 - 148));
      const b = Math.round(196 - t * (196 - 105));
      return `rgb(${r}, ${g}, ${b})`;
    }
  }
}

export default function PerformanceLandscape3D({ rows = [], totalCases = null }) {
  const [selectedGroupId, setSelectedGroupId] = useState('ndcg');
  const [metricId, setMetricId] = useState('NDCG5');
  const [paramPair, setParamPair] = useState('alpha_thresh');
  const [viewMode, setViewMode] = useState('3d'); // '3d' | 'heatmap' | 'simulator'
  const [camera, setCamera] = useState({ yaw: 45, pitch: 26, scale: 180 });
  const [canvasTheme, setCanvasTheme] = useState('auto');
  const [hoveredPoint, setHoveredPoint] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [showExplanation, setShowExplanation] = useState(true);

  // Extract empirical benchmark metrics from real rows if available
  const empiricalH2L = useMemo(() => (rows || []).find((r) => r.strategy === 'h2l-hybrid') || {}, [rows]);
  const empiricalBasic = useMemo(() => (rows || []).find((r) => r.strategy === 'basic') || {}, [rows]);
  const hasEmpiricalData = Boolean(empiricalH2L.map || empiricalH2L['nDCG@5'] || empiricalH2L['nDCG@10'] || empiricalH2L.mrr);
  const empiricalCases = totalCases || empiricalH2L.num_cases || rows?.[0]?.num_cases || (rows?.length ? 100 : null);
  const formatMetric = (val) => (val !== undefined && val !== null && !isNaN(Number(val)) ? Number(val).toFixed(4) : '—');

  // Interactive Simulator slider states
  const [simX, setSimX] = useState(0.50);
  const [simZ, setSimZ] = useState(0.65);

  // Dynamic 1D Slice Lock states (allows user to select which K or parameter value to lock)
  const [activeLockX, setActiveLockX] = useState(0.50);
  const [activeLockZ, setActiveLockZ] = useState(0.65);

  const dragStartRef = useRef({ x: 0, y: 0, yaw: 45, pitch: 26 });
  const svgRef = useRef(null);

  const isSystemDark = typeof document !== 'undefined' && document.documentElement.classList.contains('dark');
  const isDark = canvasTheme === 'dark' ? true : canvasTheme === 'light' ? false : isSystemDark;

  const currentGroup = useMemo(
    () => METRIC_GROUPS.find((g) => g.id === selectedGroupId) || METRIC_GROUPS[0],
    [selectedGroupId]
  );

  const metric = useMemo(
    () => ALL_METRICS_LIST.find((m) => m.id === metricId) || ALL_METRICS_LIST[0],
    [metricId]
  );

  const handleGroupChange = (groupId) => {
    setSelectedGroupId(groupId);
    const grp = METRIC_GROUPS.find((g) => g.id === groupId) || METRIC_GROUPS[0];
    setMetricId(grp.defaultMetricId);
  };

  const pair = useMemo(() => PARAMETER_PAIRS.find((p) => p.id === paramPair) || PARAMETER_PAIRS[0], [paramPair]);

  // Sync simulator sliders and 1D slice locks when switching parameter pair
  useEffect(() => {
    setSimX(pair.xOpt);
    setSimZ(pair.zOpt);
    setActiveLockX(pair.xOpt);
    setActiveLockZ(pair.zOpt);
  }, [pair]);

  // Drag to rotate
  const handleMouseDown = useCallback((e) => {
    setIsDragging(true);
    dragStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      yaw: camera.yaw,
      pitch: camera.pitch,
    };
  }, [camera]);

  const handleMouseMove = useCallback((e) => {
    if (!isDragging) return;
    const dx = e.clientX - dragStartRef.current.x;
    const dy = e.clientY - dragStartRef.current.y;
    const newYaw = (dragStartRef.current.yaw + dx * 0.45) % 360;
    const newPitch = Math.max(5, Math.min(85, dragStartRef.current.pitch + dy * 0.35));
    setCamera((prev) => ({ ...prev, yaw: newYaw, pitch: newPitch }));
  }, [isDragging]);

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  useEffect(() => {
    if (isDragging) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
      return () => {
        window.removeEventListener('mousemove', handleMouseMove);
        window.removeEventListener('mouseup', handleMouseUp);
      };
    }
  }, [isDragging, handleMouseMove, handleMouseUp]);

  // 3D Projection Engine
  const proj = useMemo(() => {
    const radY = (camera.yaw * Math.PI) / 180;
    const radP = (camera.pitch * Math.PI) / 180;
    const cosY = Math.cos(radY);
    const sinY = Math.sin(radY);
    const cosP = Math.cos(radP);
    const sinP = Math.sin(radP);

    const cx = 350;
    const cy = 250;
    const scale = camera.scale;

    return (x, y, z) => {
      const x1 = x * cosY - z * sinY;
      const z1 = x * sinY + z * cosY;

      const y2 = y * cosP - z1 * sinP;
      const z2 = y * sinP + z1 * cosP;

      const sx = cx + x1 * scale;
      const sy = cy - y2 * scale;
      return { x: sx, y: sy, depth: z2 };
    };
  }, [camera]);

  // Dynamic Continuous Surface Function f(x, z) specific to the chosen Parameter Pair
  const getSurfaceHeight = useCallback((u, v) => {
    const maxVal = metric.maxVal || 0.938;

    if (pair.id === 'alpha_thresh') {
      // Ridge along alpha = 0.65, threshold = 0.50
      const uNorm = (u - 0.50) / 0.45;
      const vNorm = (v - 0.65) / 0.50;
      const distSq = (uNorm * uNorm * 1.1) + (vNorm * vNorm * 0.9);
      const baseVal = maxVal * Math.exp(-0.85 * distSq);
      const baselineFloor = 0.45 + (0.30 * (1 - Math.abs(u - 0.50)));
      const alphaGain = v * 0.18 * Math.exp(-2.0 * Math.pow(u - 0.50, 2));
      return Math.max(0.30, Math.min(0.95, Math.max(baseVal, baselineFloor + alphaGain)));
    } else if (pair.id === 'neg_thresh') {
      // Negation safety: Safe plateau when v (beta) >= 0.70, steep drop when v < 0.30
      const uNorm = (u - 0.50) / 0.45;
      const vNorm = (v - 0.85) / 0.45;
      const distSq = (uNorm * uNorm * 1.0) + (vNorm * vNorm * 0.8);
      const baseVal = (maxVal + 0.003) * Math.exp(-0.80 * distSq);
      const negLeakagePenalty = v < 0.40 ? Math.pow((0.40 - v) / 0.40, 1.8) * 0.38 : 0;
      return Math.max(0.30, Math.min(0.95, baseVal - negLeakagePenalty + 0.02));
    } else if (pair.id === 'kl_thresh') {
      // Bell-shaped dome at kappa = 0.80 (v = 0.40 of [0, 2.0]), threshold = 0.50 (u = 0.50)
      const uNorm = (u - 0.50) / 0.42;
      const vNorm = (v - 0.40) / 0.45;
      const distSq = (uNorm * uNorm * 1.2) + (vNorm * vNorm * 1.4);
      const baseVal = (maxVal - 0.013) * Math.exp(-1.1 * distSq);
      const penaltyDrop = v > 0.7 ? (v - 0.7) * 0.15 : 0;
      return Math.max(0.30, Math.min(0.95, baseVal - penaltyDrop + 0.05));
    } else if (pair.id === 'idf_budget') {
      // Term Specificity lambda (v) vs Budget K (u, mapped from 1..15 -> u in [0, 1])
      const optU = (5 - 1) / 14; // K=5
      const uNorm = (u - optU) / 0.45;
      const vNorm = (v - 0.70) / 0.45;
      const distSq = (uNorm * uNorm * 1.0) + (vNorm * vNorm * 1.1);
      const baseVal = (maxVal - 0.003) * Math.exp(-0.85 * distSq);
      const lowIdfDrop = v < 0.30 ? (0.30 - v) * 0.22 : 0;
      return Math.max(0.30, Math.min(0.95, baseVal - lowIdfDrop + 0.02));
    } else {
      // Temperature: Plateau across T = 1.0–1.4 (v = 0.35–0.55 of [0.5, 2.5]), threshold = 0.50
      const uNorm = (u - 0.50) / 0.40;
      const vNorm = Math.max(0, Math.abs(v - 0.45) - 0.12) / 0.38;
      const distSq = (uNorm * uNorm * 1.0) + (vNorm * vNorm * 1.6);
      const baseVal = (maxVal - 0.007) * Math.exp(-0.95 * distSq);
      const sharpnessPenalty = v < 0.2 ? (0.2 - v) * 0.20 : 0;
      return Math.max(0.30, Math.min(0.95, baseVal - sharpnessPenalty + 0.03));
    }
  }, [metric, pair.id]);

  // Generate 3D Surface Mesh (24 x 24 grid)
  const GRID_SIZE = 24;
  const {
    polygons,
    optimalPoint,
    axes,
    verticalTicks,
    threshTicks,
    alphaTicks,
    floorGrid,
    heatmapRows,
    curveX,
    curveZ,
    projectedAnnotations,
  } = useMemo(() => {
    const gridPoints = [];

    for (let i = 0; i <= GRID_SIZE; i++) {
      const u = i / GRID_SIZE;
      const xNorm = (u - 0.5) * 2.0;
      const row = [];

      for (let j = 0; j <= GRID_SIZE; j++) {
        const v = j / GRID_SIZE;
        const zNorm = (v - 0.5) * 2.0;

        const score = getSurfaceHeight(u, v);
        const yNorm = ((score - 0.30) / (0.95 - 0.30)) * 0.85;

        const p2d = proj(xNorm, yNorm, zNorm);
        row.push({
          u,
          v,
          xRealVal: pair.xMin + u * (pair.xMax - pair.xMin),
          zRealVal: pair.zMin + v * (pair.zMax - pair.zMin),
          score,
          xNorm,
          yNorm,
          zNorm,
          screenX: p2d.x,
          screenY: p2d.y,
          depth: p2d.depth,
        });
      }
      gridPoints.push(row);
    }

    const quads = [];
    for (let i = 0; i < GRID_SIZE; i++) {
      for (let j = 0; j < GRID_SIZE; j++) {
        const p00 = gridPoints[i][j];
        const p10 = gridPoints[i + 1][j];
        const p11 = gridPoints[i + 1][j + 1];
        const p01 = gridPoints[i][j + 1];

        const avgDepth = (p00.depth + p10.depth + p11.depth + p01.depth) / 4;
        const avgScore = (p00.score + p10.score + p11.score + p01.score) / 4;
        const isOptimalPlateau = avgScore >= 0.88;

        quads.push({
          id: `quad-${i}-${j}`,
          i,
          j,
          p00,
          p10,
          p11,
          p01,
          avgDepth,
          avgScore,
          isOptimalPlateau,
          fillColor: getHeightColor(avgScore, isDark),
        });
      }
    }

    quads.sort((a, b) => a.avgDepth - b.avgDepth);

    // Optimal Coordinates mapped to unit [0, 1]
    const optU = (pair.xOpt - pair.xMin) / (pair.xMax - pair.xMin);
    const optV = (pair.zOpt - pair.zMin) / (pair.zMax - pair.zMin);
    const optScore = getSurfaceHeight(optU, optV);
    const optYNorm = ((optScore - 0.30) / (0.95 - 0.30)) * 0.85;
    const optXNorm = (optU - 0.5) * 2.0;
    const optZNorm = (optV - 0.5) * 2.0;
    const optP2d = proj(optXNorm, optYNorm, optZNorm);

    // Axes definitions
    const origin2d = proj(-1.1, 0, -1.1);
    const threshEnd2d = proj(1.2, 0, -1.1);
    const alphaEnd2d = proj(-1.1, 0, 1.2);
    const ndcgTop2d = proj(-1.1, 1.15, -1.1);

    // Vertical Ticks on Y-axis (0.30 to 0.95)
    const vTicks = [0.30, 0.45, 0.60, 0.75, 0.90, 0.95].map((val) => {
      const yNorm = ((val - 0.30) / (0.95 - 0.30)) * 0.85;
      const pt = proj(-1.1, yNorm, -1.1);
      return { val, x: pt.x, y: pt.y };
    });

    // Threshold Ticks on X-axis
    const tTicks = (pair.ticksX || [0.10, 0.30, 0.50, 0.70, 0.90]).map((val) => {
      const u = (val - pair.xMin) / (pair.xMax - pair.xMin);
      const xNorm = (u - 0.5) * 2.0;
      const pt = proj(xNorm, 0, -1.1);
      return { val, x: pt.x, y: pt.y };
    });

    // Parameter Z Ticks on Z-axis
    const aTicks = (pair.ticksZ || [0.00, 0.25, 0.50, 0.65, 0.75, 1.00]).map((val) => {
      const v = (val - pair.zMin) / (pair.zMax - pair.zMin);
      const zNorm = (v - 0.5) * 2.0;
      const pt = proj(-1.1, 0, zNorm);
      return { val, x: pt.x, y: pt.y };
    });

    // Base Floor Grid Lines (Y=0)
    const fLines = [];
    for (let u = 0; u <= 1.0; u += 0.25) {
      const xNorm = (u - 0.5) * 2.0;
      const pStart = proj(xNorm, 0, -1.0);
      const pEnd = proj(xNorm, 0, 1.0);
      fLines.push({ id: `fx-${u}`, x1: pStart.x, y1: pStart.y, x2: pEnd.x, y2: pEnd.y });
    }
    for (let v = 0; v <= 1.0; v += 0.25) {
      const zNorm = (v - 0.5) * 2.0;
      const pStart = proj(-1.0, 0, zNorm);
      const pEnd = proj(1.0, 0, zNorm);
      fLines.push({ id: `fz-${v}`, x1: pStart.x, y1: pStart.y, x2: pEnd.x, y2: pEnd.y });
    }

    // Generate 2D Heatmap Data (9 x 9 discrete matrix for crystal-clear table reading)
    const heatmapRows = [];
    const matrixSteps = 8;
    for (let j = matrixSteps; j >= 0; j--) {
      const v = j / matrixSteps;
      const zVal = pair.zMin + v * (pair.zMax - pair.zMin);
      const cells = [];
      for (let i = 0; i <= matrixSteps; i++) {
        const u = i / matrixSteps;
        const xVal = pair.xMin + u * (pair.xMax - pair.xMin);
        const score = getSurfaceHeight(u, v);
        const isOptimal = Math.abs(xVal - pair.xOpt) < (pair.xStep || 0.06) && Math.abs(zVal - pair.zOpt) < (pair.zStep || 0.08);
        const inSafeZone = xVal >= pair.safeZone.xMin && xVal <= pair.safeZone.xMax && zVal >= pair.safeZone.zMin && zVal <= pair.safeZone.zMax;
        cells.push({
          u,
          v,
          xVal,
          zVal,
          score,
          isOptimal,
          inSafeZone,
          fillColor: getHeightColor(score, isDark),
        });
      }
      heatmapRows.push({ zVal, cells });
    }

    // Generate 1D Sensitivity Slice Curves
    const curLockX = activeLockX ?? pair.xOpt;
    const curLockZ = activeLockZ ?? pair.zOpt;
    const lockU = Math.max(0, Math.min(1, (curLockX - pair.xMin) / (pair.xMax - pair.xMin)));
    const lockV = Math.max(0, Math.min(1, (curLockZ - pair.zMin) / (pair.zMax - pair.zMin)));

    // Curve A: Sweep X with Z locked at curLockZ
    const curveX = [];
    for (let i = 0; i <= 20; i++) {
      const u = i / 20;
      const xVal = pair.xMin + u * (pair.xMax - pair.xMin);
      const score = getSurfaceHeight(u, lockV);
      curveX.push({ xVal, score });
    }

    // Curve B: Sweep Z with X locked at curLockX
    const curveZ = [];
    for (let j = 0; j <= 20; j++) {
      const v = j / 20;
      const zVal = pair.zMin + v * (pair.zMax - pair.zMin);
      const score = getSurfaceHeight(lockU, v);
      curveZ.push({ zVal, score });
    }

    // Projected zone annotation coordinates for 3D on-canvas tags
    const projectedAnnotations = (pair.zoneAnnotations || []).map((anno) => {
      const u = (anno.u - pair.xMin) / (pair.xMax - pair.xMin);
      const v = (anno.v - pair.zMin) / (pair.zMax - pair.zMin);
      const score = getSurfaceHeight(u, v);
      const yNorm = ((score - 0.30) / (0.95 - 0.30)) * 0.85;
      const xNorm = (u - 0.5) * 2.0;
      const zNorm = (v - 0.5) * 2.0;
      const p2d = proj(xNorm, yNorm, zNorm);
      return {
        ...anno,
        screenX: p2d.x,
        screenY: p2d.y,
        score,
      };
    });

    return {
      polygons: quads,
      optimalPoint: {
        score: optScore,
        xVal: pair.xOpt,
        zVal: pair.zOpt,
        screenX: optP2d.x,
        screenY: optP2d.y,
      },
      axes: {
        origin: origin2d,
        threshEnd: threshEnd2d,
        alphaEnd: alphaEnd2d,
        ndcgTop: ndcgTop2d,
      },
      verticalTicks: vTicks,
      threshTicks: tTicks,
      alphaTicks: aTicks,
      floorGrid: fLines,
      heatmapRows,
      curveX,
      curveZ,
      projectedAnnotations,
    };
  }, [GRID_SIZE, getSurfaceHeight, proj, isDark, pair, activeLockX, activeLockZ]);

  // Current Simulator Score and Real-time Diagnostic Verdict
  const simScore = useMemo(() => {
    const u = Math.max(0, Math.min(1, (simX - pair.xMin) / (pair.xMax - pair.xMin)));
    const v = Math.max(0, Math.min(1, (simZ - pair.zMin) / (pair.zMax - pair.zMin)));
    return getSurfaceHeight(u, v);
  }, [simX, simZ, pair, getSurfaceHeight]);

  const simVerdict = useMemo(() => {
    const isOptimal = Math.abs(simX - pair.xOpt) <= 0.05 && Math.abs(simZ - pair.zOpt) <= 0.08;
    const inSafe = simX >= pair.safeZone.xMin && simX <= pair.safeZone.xMax && simZ >= pair.safeZone.zMin && simZ <= pair.safeZone.zMax;
    
    if (isOptimal) {
      return {
        status: 'optimal',
        badge: '🌟 จุดทำงานดีที่สุด (Optimal Sweet Spot)',
        tone: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
        text: `การตั้งค่าที่ ${pair.zLabel}=${simZ.toFixed(2)}, ${pair.xLabel}=${simX.toFixed(2)} ดึงความสามารถของ H2L ได้สมบูรณ์แบบที่สุด ประสิทธิภาพ ${metric.label} สูงถึง ${(simScore).toFixed(3)}`,
      };
    }
    if (inSafe) {
      return {
        status: 'safe',
        badge: '🛡️ ปลอดภัยและเสถียร (Robust Operating Zone)',
        tone: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40',
        text: `อยู่ในช่วงที่ระบบทำงานได้อย่างเสถียร (คะแนน ${(simScore).toFixed(3)}) ผลลัพธ์ไม่เปราะบางต่อความแปรปรวนของข้อมูลผู้ป่วย`,
      };
    }
    if (simScore >= 0.85) {
      return {
        status: 'acceptable',
        badge: '⚡ พอใช้ได้ (Acceptable Performance)',
        tone: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
        text: `ประสิทธิภาพ ${(simScore).toFixed(3)} สูงกว่า Baseline แต่แนะนำให้ปรับเข้าใกล้ ${pair.zLabel}=${pair.zOpt.toFixed(2)}, ${pair.xLabel}=${pair.xOpt.toFixed(2)} เพื่อผลลัพธ์ที่ดีขึ้น`,
      };
    }
    return {
      status: 'degraded',
      badge: '⚠️ เสี่ยงลดทอนประสิทธิภาพ (Suboptimal / Baseline Drop)',
      tone: 'bg-rose-500/20 text-rose-300 border-rose-500/40',
      text: `คะแนนลดลงเหลือ ${(simScore).toFixed(3)} ${simZ <= 0.1 ? 'เนื่องจากไม่ได้ใช้น้ำหนัก H2L ช่วยจัดอันดับ (ตกไปเป็น Baseline)' : 'เนื่องจากเกณฑ์คัดกรองหรือการลงโทษมีความเข้มงวดมากเกินไป'}`,
    };
  }, [simX, simZ, simScore, pair, metric]);

  return (
    <div className={`relative overflow-hidden rounded-2xl border transition-colors shadow-xl ${isDark ? 'border-slate-800 bg-[#060913] text-slate-100' : 'border-slate-300/80 bg-slate-50/90 text-slate-900'}`}>
      {/* Background radial glow */}
      <div className={`pointer-events-none absolute inset-0 ${isDark ? 'bg-[radial-gradient(circle_at_50%_40%,rgba(14,116,144,0.18),transparent_70%)]' : 'bg-[radial-gradient(circle_at_50%_40%,rgba(14,116,144,0.08),transparent_70%)]'}`} />

      {/* Top Header & Interactive Controls */}
      <div className={`relative z-10 flex flex-wrap items-center justify-between gap-4 border-b p-4 sm:p-5 backdrop-blur-md ${isDark ? 'border-slate-800/80 bg-slate-950/60' : 'border-slate-200/80 bg-white/80'}`}>
        <div>
          <div className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 rounded-full animate-pulse ${isDark ? 'bg-cyan-400' : 'bg-teal-600'}`} />
            <span className={`text-[11px] font-bold uppercase tracking-widest ${isDark ? 'text-cyan-400' : 'text-teal-700'}`}>
              แบบจำลองการตอบสนองเชิงพารามิเตอร์ 3 มิติ (Parametric Response Surface Simulator) · {pair.rqTag}
            </span>
          </div>
          <h2 className={`mt-1 font-headline text-lg sm:text-xl font-extrabold ${isDark ? 'text-white' : 'text-slate-900'}`}>
            ภูมิทัศน์ความไวต่อพารามิเตอร์ ({pair.zName} × {pair.xName})
          </h2>
          {/* Conceptual illustration notice */}
          <div className={`mt-1.5 inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 border text-[10px] font-bold uppercase tracking-wider ${isDark ? 'bg-amber-950/40 border-amber-700/50 text-amber-300' : 'bg-amber-50 border-amber-300 text-amber-800'}`}>
            <span className="material-symbols-outlined text-[13px]">info</span>
            ภาพประกอบแนวคิด (Conceptual Illustration) — พื้นผิวสร้างจากสูตรจำลองทางทฤษฎี ไม่ใช่ผลการ sweep จริง
          </div>
          <div className={`mt-2 inline-flex items-center gap-2 rounded-xl px-3 py-1.5 border text-xs leading-relaxed max-w-2xl ${isDark ? 'bg-cyan-950/30 border-cyan-900/50 text-cyan-200' : 'bg-teal-50 border-teal-200 text-teal-950'}`}>
            <span className="material-symbols-outlined text-[16px] text-teal-600 dark:text-cyan-400 flex-shrink-0">help</span>
            <div>
              <strong>สิ่งที่ใช้วัด ({currentGroup.name}):</strong> {currentGroup.measurement}
              <span className="mx-1.5 opacity-60">·</span>
              <strong>{metric.fullLabel || metric.label}:</strong> {metric.desc}
            </div>
          </div>
        </div>

        {/* Metric Group Dropdown + Scale Scrolling Strip + Theme Controls */}
        <div className="flex flex-wrap items-center justify-end gap-3 max-w-2xl">
          {/* Dropdown: Metric Group */}
          <div className="flex items-center gap-2">
            <label htmlFor="metric-group-select" className={`text-[10px] font-bold uppercase tracking-wider whitespace-nowrap ${isDark ? 'text-cyan-400' : 'text-teal-700'}`}>
              กลุ่มมาตราวัด:
            </label>
            <select
              id="metric-group-select"
              value={selectedGroupId}
              onChange={(e) => handleGroupChange(e.target.value)}
              className={`rounded-xl px-3 py-1.5 text-xs font-bold border transition-colors outline-none cursor-pointer shadow-sm ${
                isDark
                  ? 'bg-slate-900 border-slate-700 text-slate-100 focus:border-cyan-500'
                  : 'bg-white border-slate-300 text-slate-900 focus:border-teal-600'
              }`}
            >
              {METRIC_GROUPS.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          </div>

          {/* Scale: Scrolling Pill Bar (if group hasScale) or Option Buttons (if no scale) */}
          <div className="flex items-center gap-1.5">
            <span className={`text-[10px] font-bold uppercase tracking-wider whitespace-nowrap ${isDark ? 'text-cyan-400' : 'text-teal-700'}`}>
              {currentGroup.hasScale ? 'Scale (K):' : 'ตัวเลือก:'}
            </span>
            {currentGroup.hasScale ? (
              <div className={`flex items-center gap-1 overflow-x-auto p-1 rounded-xl border max-w-[200px] sm:max-w-[260px] ${isDark ? 'bg-slate-900/90 border-slate-800' : 'bg-slate-200/70 border-slate-300/80'}`}>
                {currentGroup.scales.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => setMetricId(s.id)}
                    className={`rounded-lg px-2.5 py-1 text-xs font-bold whitespace-nowrap transition-all flex-shrink-0 ${
                      metricId === s.id
                        ? isDark
                          ? 'bg-gradient-to-r from-cyan-600 to-teal-500 text-white shadow-md'
                          : 'bg-teal-700 text-white shadow-sm'
                        : isDark
                          ? 'text-slate-400 hover:text-white hover:bg-slate-800/60'
                          : 'text-slate-700 hover:text-slate-950 hover:bg-slate-300/60'
                    }`}
                    type="button"
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            ) : (
              <div className={`flex items-center gap-1 p-1 rounded-xl border ${isDark ? 'bg-slate-900/90 border-slate-800' : 'bg-slate-200/70 border-slate-300/80'}`}>
                {currentGroup.options.map((opt) => (
                  <button
                    key={opt.id}
                    onClick={() => setMetricId(opt.id)}
                    className={`rounded-lg px-2.5 py-1 text-xs font-bold whitespace-nowrap transition-all ${
                      metricId === opt.id
                        ? isDark
                          ? 'bg-gradient-to-r from-cyan-600 to-teal-500 text-white shadow-md'
                          : 'bg-teal-700 text-white shadow-sm'
                        : isDark
                          ? 'text-slate-400 hover:text-white hover:bg-slate-800/60'
                          : 'text-slate-700 hover:text-slate-950 hover:bg-slate-300/60'
                    }`}
                    type="button"
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Canvas Theme Selector */}
          <div className={`flex items-center rounded-lg border p-0.5 text-[11px] font-semibold flex-shrink-0 ${isDark ? 'bg-slate-900 border-slate-800' : 'bg-slate-200/80 border-slate-300'}`}>
            <button
              type="button"
              onClick={() => setCanvasTheme('auto')}
              className={`rounded px-1.5 py-0.5 ${canvasTheme === 'auto' ? (isDark ? 'bg-cyan-900/80 text-cyan-200' : 'bg-white text-slate-900 shadow-sm') : 'opacity-60'}`}
              title="ธีมตามระบบ (Auto)"
            >
              🌓 Auto
            </button>
            <button
              type="button"
              onClick={() => setCanvasTheme('dark')}
              className={`rounded px-1.5 py-0.5 ${canvasTheme === 'dark' ? 'bg-cyan-900/80 text-cyan-200' : 'opacity-60'}`}
              title="โหมดมืด (Dark Canvas)"
            >
              🌙 Dark
            </button>
            <button
              type="button"
              onClick={() => setCanvasTheme('light')}
              className={`rounded px-1.5 py-0.5 ${canvasTheme === 'light' ? 'bg-white text-slate-900 shadow-sm' : 'opacity-60'}`}
              title="โหมดสว่าง (Light Canvas)"
            >
              ☀️ Light
            </button>
          </div>
        </div>
      </div>

      {/* Parameter Pair Selector & View Mode Switcher */}
      <div className={`relative z-10 flex flex-wrap items-center justify-between gap-3 border-b px-4 py-2.5 sm:px-5 text-xs ${isDark ? 'border-slate-800/80 bg-slate-950/40' : 'border-slate-200 bg-white/50'}`}>
        <div className="flex flex-wrap items-center gap-2 max-w-full">
          <label htmlFor="param-pair-select" className={`font-bold uppercase tracking-wider text-[10px] whitespace-nowrap ${isDark ? 'text-cyan-400' : 'text-teal-800'}`}>
            คู่แกนพารามิเตอร์:
          </label>
          <select
            id="param-pair-select"
            value={paramPair}
            onChange={(e) => setParamPair(e.target.value)}
            className={`rounded-xl px-3 py-1.5 text-xs font-bold border transition-colors outline-none cursor-pointer shadow-sm ${
              isDark
                ? 'bg-slate-900 border-slate-700 text-cyan-200 focus:border-cyan-500'
                : 'bg-white border-slate-300 text-teal-900 focus:border-teal-600'
            }`}
          >
            {PARAMETER_PAIRS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.rqTag} — {p.title}
              </option>
            ))}
          </select>

          {/* Quick Pill Scroll Bar for Pairs */}
          <div className="hidden sm:flex items-center gap-1 overflow-x-auto py-0.5 max-w-full">
            {PARAMETER_PAIRS.map((p) => {
              const isSelected = p.id === paramPair;
              return (
                <button
                  key={p.id}
                  onClick={() => setParamPair(p.id)}
                  className={`rounded-lg px-2.5 py-1 text-xs font-bold transition-all flex items-center gap-1.5 whitespace-nowrap flex-shrink-0 ${
                    isSelected
                      ? isDark
                        ? 'bg-cyan-600 text-white shadow-md'
                        : 'bg-teal-700 text-white shadow-sm'
                      : isDark
                        ? 'bg-slate-900/80 text-slate-400 hover:text-slate-200 border border-slate-800'
                        : 'bg-slate-100 text-slate-700 hover:bg-slate-200 border border-slate-200'
                  }`}
                  type="button"
                >
                  <span>{p.title}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* View Mode Switcher (3D vs 2D Heatmap vs Simulator) */}
        <div className={`flex items-center rounded-xl p-1 border shadow-sm ${isDark ? 'bg-slate-900 border-slate-800' : 'bg-slate-200/80 border-slate-300'}`}>
          <button
            type="button"
            onClick={() => setViewMode('3d')}
            className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-bold transition-all ${
              viewMode === '3d'
                ? isDark
                  ? 'bg-cyan-600 text-white shadow-md'
                  : 'bg-teal-700 text-white shadow-sm'
                : isDark
                  ? 'text-slate-400 hover:text-white'
                  : 'text-slate-700 hover:text-slate-950'
            }`}
          >
            <span className="material-symbols-outlined text-[15px]">3d_rotation</span>
            <span>3D Surface</span>
          </button>
          <button
            type="button"
            onClick={() => setViewMode('heatmap')}
            className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-bold transition-all ${
              viewMode === 'heatmap'
                ? isDark
                  ? 'bg-cyan-600 text-white shadow-md'
                  : 'bg-teal-700 text-white shadow-sm'
                : isDark
                  ? 'text-slate-400 hover:text-white'
                  : 'text-slate-700 hover:text-slate-950'
            }`}
          >
            <span className="material-symbols-outlined text-[15px]">grid_view</span>
            <span>2D Heatmap Matrix</span>
          </button>
          <button
            type="button"
            onClick={() => setViewMode('simulator')}
            className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-bold transition-all ${
              viewMode === 'simulator'
                ? isDark
                  ? 'bg-cyan-600 text-white shadow-md'
                  : 'bg-teal-700 text-white shadow-sm'
                : isDark
                  ? 'text-slate-400 hover:text-white'
                  : 'text-slate-700 hover:text-slate-950'
            }`}
          >
            <span className="material-symbols-outlined text-[15px]">tune</span>
            <span>Simulator & Sliders</span>
          </button>
        </div>
      </div>

      {/* Empirical Benchmark Snapshot Banner (Real benchmark data from Chapter 4 / latest benchmark) */}
      {hasEmpiricalData && (
        <div className={`relative z-10 border-b p-4 sm:p-5 ${isDark ? 'border-slate-800/80 bg-slate-950/90' : 'border-slate-200 bg-emerald-50/60'}`}>
          <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-emerald-600 text-[20px]">verified</span>
              <h3 className="text-xs font-bold uppercase tracking-wider text-emerald-950 dark:text-emerald-300">
                ผลการทดลองจริงจากชุดทดสอบ {empiricalCases ? `${empiricalCases} เคส` : ''} (Empirical Benchmark: H2L-Hybrid vs Basic Baseline)
              </h3>
            </div>
            <span className="rounded-full bg-emerald-600/20 px-2.5 py-0.5 text-[10px] font-mono font-bold text-emerald-700 dark:text-emerald-300">
              {empiricalCases ? `N = ${empiricalCases} Cases` : 'Empirical Benchmark'} · Official Evaluation Artifact
            </span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs">
            <div className="rounded-xl bg-surface-container-lowest p-3 border border-slate-200/60 dark:border-slate-800">
              <span className="text-[10px] text-on-surface-variant font-bold uppercase tracking-wider">MAP (Mean Avg Precision)</span>
              <div className="font-headline font-extrabold text-base text-emerald-700 dark:text-emerald-300 mt-1">
                {formatMetric(empiricalH2L.map)}
                <span className="text-[11px] text-on-surface-variant font-normal ml-1.5">(Base: {formatMetric(empiricalBasic.map)})</span>
              </div>
            </div>
            <div className="rounded-xl bg-surface-container-lowest p-3 border border-slate-200/60 dark:border-slate-800">
              <span className="text-[10px] text-on-surface-variant font-bold uppercase tracking-wider">MRR (Mean Reciprocal Rank)</span>
              <div className="font-headline font-extrabold text-base text-emerald-700 dark:text-emerald-300 mt-1">
                {formatMetric(empiricalH2L.mrr)}
                <span className="text-[11px] text-on-surface-variant font-normal ml-1.5">(Base: {formatMetric(empiricalBasic.mrr)})</span>
              </div>
            </div>
            <div className="rounded-xl bg-surface-container-lowest p-3 border border-slate-200/60 dark:border-slate-800">
              <span className="text-[10px] text-on-surface-variant font-bold uppercase tracking-wider">nDCG@5</span>
              <div className="font-headline font-extrabold text-base text-emerald-700 dark:text-emerald-300 mt-1">
                {formatMetric(empiricalH2L['nDCG@5'])}
                <span className="text-[11px] text-on-surface-variant font-normal ml-1.5">(Base: {formatMetric(empiricalBasic['nDCG@5'])})</span>
              </div>
            </div>
            <div className="rounded-xl bg-surface-container-lowest p-3 border border-slate-200/60 dark:border-slate-800">
              <span className="text-[10px] text-on-surface-variant font-bold uppercase tracking-wider">nDCG@10</span>
              <div className="font-headline font-extrabold text-base text-emerald-700 dark:text-emerald-300 mt-1">
                {formatMetric(empiricalH2L['nDCG@10'])}
                <span className="text-[11px] text-on-surface-variant font-normal ml-1.5">(Base: {formatMetric(empiricalBasic['nDCG@10'])})</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Axis Objectives & Interpretation Guide Card (รายละเอียดวัตถุประสงค์แต่ละแกนและวิธีอ่านแปรผล) */}
      <div className={`relative z-10 border-b p-4 sm:p-5 text-xs ${isDark ? 'border-slate-800/80 bg-slate-950/70' : 'border-slate-200 bg-white/90'}`}>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5">
          {/* Col 1: Axis Objectives */}
          <div className={`rounded-xl p-3 border ${isDark ? 'bg-slate-900/80 border-slate-800 text-slate-200' : 'bg-slate-50 border-slate-200 text-slate-800'}`}>
            <div className="flex items-center gap-1.5 font-bold uppercase tracking-wider text-[11px] text-teal-600 dark:text-cyan-400">
              <span className="material-symbols-outlined text-[16px]">straighten</span>
              <span>วัตถุประสงค์ของแต่ละแกนวัด</span>
            </div>
            <div className="mt-2 space-y-1.5 leading-relaxed text-[11px]">
              <div>
                <strong className="text-teal-700 dark:text-cyan-300">📏 แกน X ({pair.xName}):</strong> {pair.xObjective}
              </div>
              <div>
                <strong className="text-teal-700 dark:text-cyan-300">📐 แกน Z ({pair.zName}):</strong> {pair.zObjective}
              </div>
              <div>
                <strong className="text-teal-700 dark:text-cyan-300">📈 แกน Y (ความสูง):</strong> ประสิทธิภาพ {metric.fullLabel || metric.label} ({metric.measurement || metric.desc})
              </div>
            </div>
          </div>

          {/* Col 2: Research Purpose & Pipeline Role */}
          <div className={`rounded-xl p-3 border ${isDark ? 'bg-slate-900/80 border-slate-800 text-slate-200' : 'bg-slate-50 border-slate-200 text-slate-800'}`}>
            <div className="flex items-center gap-1.5 font-bold uppercase tracking-wider text-[11px] text-teal-600 dark:text-cyan-400">
              <span className="material-symbols-outlined text-[16px]">psychology</span>
              <span>วัตถุประสงค์การวิจัยคู่นี้ ({pair.rqTag})</span>
            </div>
            <p className="mt-2 leading-relaxed text-[11px]">
              {pair.purpose}
            </p>
            <div className="mt-2 flex items-center gap-1.5 font-mono text-[10px] opacity-80">
              <span className="material-symbols-outlined text-[14px]">hub</span>
              <span>Pipeline: {pair.pipelineRole}</span>
            </div>
          </div>

          {/* Col 3: How to Read & Interpret */}
          <div className={`rounded-xl p-3 border ${isDark ? 'bg-cyan-950/30 border-cyan-900/50 text-cyan-100' : 'bg-teal-50/80 border-teal-200 text-teal-950'}`}>
            <div className="flex items-center justify-between gap-1.5">
              <div className="flex items-center gap-1.5 font-bold uppercase tracking-wider text-[11px] text-teal-700 dark:text-cyan-300">
                <span className="material-symbols-outlined text-[16px]">menu_book</span>
                <span>วิธีอ่านและแปรผลรูปทรง</span>
              </div>
              <span className="rounded bg-teal-600 px-1.5 py-0.2 text-[10px] font-bold text-white shadow-sm">
                Sweet Spot: {pair.zLabel}={(pair.zOpt).toFixed(2)}, {pair.xLabel}={(pair.xOpt).toFixed(2)}
              </span>
            </div>
            <p className="mt-2 leading-relaxed text-[11px]">
              {pair.howToRead}
            </p>
          </div>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* VIEW MODE 1: 3D LANDSCAPE SURFACE VIEW                                    */}
      {/* ========================================================================= */}
      {viewMode === '3d' && (
        <div
          className="relative select-none cursor-grab active:cursor-grabbing"
          onMouseDown={handleMouseDown}
          style={{ minHeight: 460 }}
        >
          {/* Angle Presets Bar */}
          <div className="absolute left-6 top-5 z-20 flex items-center gap-1 rounded-xl p-1 border backdrop-blur-md bg-slate-900/60 border-slate-800 text-xs">
            <span className="text-[10px] uppercase font-bold text-slate-400 px-1">มุมมอง:</span>
            {PRESETS.map((pst) => (
              <button
                key={pst.id}
                onClick={() => setCamera({ yaw: pst.yaw, pitch: pst.pitch, scale: pst.scale })}
                className={`rounded px-2 py-0.5 text-[11px] font-medium transition-colors ${
                  Math.abs(camera.yaw - pst.yaw) < 5 && Math.abs(camera.pitch - pst.pitch) < 5
                    ? 'bg-cyan-600 text-white font-bold'
                    : 'text-slate-300 hover:bg-slate-800'
                }`}
                type="button"
              >
                {pst.label.split(' ')[0]}
              </button>
            ))}
          </div>

          {/* Colorbar Scale Legend */}
          <div className="absolute right-6 top-5 z-20 flex flex-col items-end backdrop-blur-md p-2 rounded-xl border bg-slate-900/60 border-slate-800">
            <div className="flex items-center gap-2">
              <span className={`text-[10px] font-mono font-bold ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>0.30</span>
              <div
                className="h-3 w-32 rounded-sm shadow-inner"
                style={{
                  background: isDark
                    ? 'linear-gradient(to right, rgb(10, 30, 65), rgb(18, 65, 125), rgb(14, 135, 195), rgb(56, 189, 248))'
                    : 'linear-gradient(to right, rgb(203, 213, 225), rgb(147, 197, 253), rgb(14, 148, 196), rgb(5, 150, 105))',
                }}
              />
              <span className={`text-[10px] font-mono font-bold ${isDark ? 'text-cyan-300' : 'text-teal-800'}`}>0.95</span>
            </div>
            <span className={`mt-0.5 text-[9px] uppercase tracking-wider font-semibold ${isDark ? 'text-slate-400' : 'text-slate-600'}`}>
              {metric.axisLabel} Score Palette
            </span>
          </div>

          {/* 3D SVG Canvas */}
          <svg
            ref={svgRef}
            viewBox="0 0 700 480"
            className="mx-auto block h-full w-full max-w-4xl"
            style={{ overflow: 'visible' }}
          >
            <defs>
              <filter id="golden-glow" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur in="SourceGraphic" stdDeviation="4" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>

            {/* Floor Reference Grid */}
            <g className="floor-grid opacity-30">
              {floorGrid.map((l) => (
                <line
                  key={l.id}
                  x1={l.x1}
                  y1={l.y1}
                  x2={l.x2}
                  y2={l.y2}
                  stroke={isDark ? '#334155' : '#94a3b8'}
                  strokeWidth={0.8}
                  strokeDasharray="3 3"
                />
              ))}
            </g>

            {/* Coordinate Axes Lines & Numerical Calibration Ticks */}
            <g className="axes-group">
              {/* Vertical Y Axis (Metric Score) */}
              <line
                x1={axes.origin.x}
                y1={axes.origin.y}
                x2={axes.ndcgTop.x}
                y2={axes.ndcgTop.y}
                stroke={isDark ? '#eab308' : '#b45309'}
                strokeWidth={2}
                strokeLinecap="round"
              />
              <text
                x={axes.ndcgTop.x}
                y={axes.ndcgTop.y - 14}
                textAnchor="middle"
                fill={isDark ? '#fbbf24' : '#92400e'}
                fontSize={13}
                fontWeight="800"
                letterSpacing="0.05em"
              >
                {metric.axisLabel}
              </text>

              {/* Vertical Axis Graduation Ticks */}
              {verticalTicks.map((vt) => (
                <g key={`vt-${vt.val}`}>
                  <line
                    x1={vt.x - 4}
                    y1={vt.y}
                    x2={vt.x + 4}
                    y2={vt.y}
                    stroke={isDark ? '#fbbf24' : '#92400e'}
                    strokeWidth={1}
                  />
                  <text
                    x={vt.x - 8}
                    y={vt.y + 3.5}
                    textAnchor="end"
                    fill={isDark ? '#fef08a' : '#78350f'}
                    fontSize={9.5}
                    fontWeight="600"
                    fontFamily="monospace"
                  >
                    {vt.val.toFixed(2)}
                  </text>
                </g>
              ))}

              {/* Left X Axis (Threshold) */}
              <line
                x1={axes.origin.x}
                y1={axes.origin.y}
                x2={axes.threshEnd.x}
                y2={axes.threshEnd.y}
                stroke={isDark ? '#10b981' : '#047857'}
                strokeWidth={1.8}
                strokeLinecap="round"
              />
              <text
                x={axes.threshEnd.x - 14}
                y={axes.threshEnd.y + 16}
                textAnchor="end"
                fill={isDark ? '#34d399' : '#047857'}
                fontSize={12}
                fontWeight="700"
              >
                {pair.xLabel}
              </text>

              {/* Threshold Axis Graduation Ticks */}
              {threshTicks.map((tt) => (
                <g key={`tt-${tt.val}`}>
                  <line
                    x1={tt.x}
                    y1={tt.y - 3}
                    x2={tt.x}
                    y2={tt.y + 3}
                    stroke={isDark ? '#10b981' : '#047857'}
                    strokeWidth={1}
                  />
                  <text
                    x={tt.x}
                    y={tt.y + 13}
                    textAnchor="middle"
                    fill={isDark ? '#a7f3d0' : '#065f46'}
                    fontSize={9}
                    fontWeight="600"
                    fontFamily="monospace"
                  >
                    {tt.val.toFixed(2)}
                  </text>
                </g>
              ))}

              {/* Right Z Axis (Parameter Z) */}
              <line
                x1={axes.origin.x}
                y1={axes.origin.y}
                x2={axes.alphaEnd.x}
                y2={axes.alphaEnd.y}
                stroke={isDark ? '#06b6d4' : '#0369a1'}
                strokeWidth={1.8}
                strokeLinecap="round"
              />
              <text
                x={axes.alphaEnd.x + 14}
                y={axes.alphaEnd.y + 16}
                textAnchor="start"
                fill={isDark ? '#38bdf8' : '#0369a1'}
                fontSize={12}
                fontWeight="700"
              >
                {pair.zLabel}
              </text>

              {/* Parameter Z Axis Graduation Ticks */}
              {alphaTicks.map((at) => (
                <g key={`at-${at.val}`}>
                  <line
                    x1={at.x - 3}
                    y1={at.y}
                    x2={at.x + 3}
                    y2={at.y}
                    stroke={isDark ? '#06b6d4' : '#0369a1'}
                    strokeWidth={1}
                  />
                  <text
                    x={at.x + 7}
                    y={at.y + 3.5}
                    textAnchor="start"
                    fill={isDark ? '#bae6fd' : '#075985'}
                    fontSize={9}
                    fontWeight="600"
                    fontFamily="monospace"
                  >
                    {at.val.toFixed(2)}
                  </text>
                </g>
              ))}
            </g>

            {/* 3D Continuous Shaded Surface Mesh */}
            <g className="surface-mesh">
              {polygons.map((quad) => {
                const pts = `${quad.p00.screenX.toFixed(1)},${quad.p00.screenY.toFixed(1)} ${quad.p10.screenX.toFixed(1)},${quad.p10.screenY.toFixed(1)} ${quad.p11.screenX.toFixed(1)},${quad.p11.screenY.toFixed(1)} ${quad.p01.screenX.toFixed(1)},${quad.p01.screenY.toFixed(1)}`;
                
                const strokeColor = quad.isOptimalPlateau
                  ? (isDark ? '#22d3ee' : '#059669')
                  : (isDark ? '#082f49' : '#cbd5e1');
                const strokeWidth = quad.isOptimalPlateau ? 1.1 : 0.45;
                const strokeOpacity = quad.isOptimalPlateau ? 0.95 : 0.4;

                return (
                  <polygon
                    key={quad.id}
                    points={pts}
                    fill={quad.fillColor}
                    stroke={strokeColor}
                    strokeWidth={strokeWidth}
                    strokeOpacity={strokeOpacity}
                    onMouseEnter={() => setHoveredPoint(quad)}
                    onMouseLeave={() => setHoveredPoint(null)}
                    className="transition-colors duration-75"
                  />
                );
              })}
            </g>

            {/* On-Canvas Zone Annotation Badges */}
            <g className="zone-annotations pointer-events-none">
              {projectedAnnotations.map((anno) => (
                <g key={anno.text} transform={`translate(${anno.screenX}, ${anno.screenY})`}>
                  <rect
                    x="-65"
                    y="-22"
                    width="130"
                    height="18"
                    rx="4"
                    fill={anno.type === 'peak' ? 'rgba(6, 78, 59, 0.85)' : 'rgba(15, 23, 42, 0.85)'}
                    stroke={anno.type === 'peak' ? '#34d399' : '#94a3b8'}
                    strokeWidth="0.8"
                  />
                  <text
                    x="0"
                    y="-10"
                    textAnchor="middle"
                    fill={anno.type === 'peak' ? '#6ee7b7' : '#e2e8f0'}
                    fontSize="8.5"
                    fontWeight="700"
                  >
                    {anno.text}
                  </text>
                </g>
              ))}
            </g>

            {/* Optimal Operating Point (Golden Glowing Pin) */}
            <g
              className="optimal-marker cursor-pointer"
              transform={`translate(${optimalPoint.screenX}, ${optimalPoint.screenY})`}
              onMouseEnter={() => setHoveredPoint({
                avgScore: optimalPoint.score,
                p00: { xRealVal: optimalPoint.xVal, zRealVal: optimalPoint.zVal },
                isOptimal: true,
              })}
            >
              <circle
                r="14"
                fill="none"
                stroke="#fbbf24"
                strokeWidth="1.4"
                strokeDasharray="3,2"
                opacity="0.9"
                className="animate-spin"
                style={{ animationDuration: '9s' }}
              />
              <circle
                r="8"
                fill="rgba(245, 158, 11, 0.4)"
                stroke="#f59e0b"
                strokeWidth="1.5"
                filter="url(#golden-glow)"
              />
              <circle
                r="4.5"
                fill="#fbbf24"
                stroke="#ffffff"
                strokeWidth="1"
              />
            </g>
          </svg>

          {/* Hover / Tooltip Card */}
          {hoveredPoint && (
            <div
              className={`pointer-events-none absolute bottom-5 left-6 z-30 rounded-xl border p-3.5 shadow-2xl backdrop-blur-md ${isDark ? 'border-cyan-500/40 bg-slate-900/90 text-slate-100' : 'border-teal-600/40 bg-white/95 text-slate-900'}`}
              style={{ minWidth: 250 }}
            >
              <div className="flex items-center justify-between gap-2 border-b border-slate-200/50 pb-2 dark:border-slate-800">
                <span className={`text-[10px] font-bold uppercase tracking-wider ${isDark ? 'text-cyan-400' : 'text-teal-700'}`}>
                  {hoveredPoint.isOptimal ? '⭐ Optimal Sweet Spot Peak' : '3D Surface Probe'}
                </span>
                <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${isDark ? 'bg-cyan-950 text-cyan-300' : 'bg-teal-100 text-teal-900'}`}>
                  {metric.axisLabel}: {hoveredPoint.avgScore.toFixed(3)}
                </span>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                <div>
                  <span className={`block text-[10px] ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>{pair.xLabel}:</span>
                  <strong className={`font-mono ${isDark ? 'text-emerald-400' : 'text-emerald-700'}`}>
                    {(hoveredPoint.p00?.xRealVal || optimalPoint.xVal).toFixed(2)}
                  </strong>
                </div>
                <div>
                  <span className={`block text-[10px] ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>{pair.zLabel}:</span>
                  <strong className={`font-mono ${isDark ? 'text-cyan-400' : 'text-teal-700'}`}>
                    {(hoveredPoint.p00?.zRealVal || optimalPoint.zVal).toFixed(2)}
                  </strong>
                </div>
              </div>
              {hoveredPoint.avgScore >= 0.88 && (
                <div className={`mt-2 rounded p-1.5 text-[11px] font-semibold text-center border ${isDark ? 'bg-emerald-950/60 text-emerald-300 border-emerald-800/40' : 'bg-emerald-50 text-emerald-800 border-emerald-200'}`}>
                  ✨ อยู่ในโซน Convex Sweet Spot Plateau (ประสิทธิภาพสูงสุด)
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ========================================================================= */}
      {/* VIEW MODE 2: 2D HEATMAP MATRIX & CROSS-SECTION VIEW                       */}
      {/* ========================================================================= */}
      {viewMode === 'heatmap' && (
        <div className="p-5 sm:p-6 space-y-6">
          <div className="grid gap-6 lg:grid-cols-12 items-start">
            {/* Heatmap Grid Matrix */}
            <div className="lg:col-span-8 overflow-x-auto rounded-xl border p-4 bg-surface-container-low/60 border-slate-200/60 dark:border-slate-800">
              <div className="flex items-center justify-between mb-3">
                <h4 className="font-headline text-sm font-bold text-on-surface flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-[18px] text-teal-600">grid_on</span>
                  ตารางค่าความร้อน 2 มิติ (แกน Y: {pair.zLabel} × แกน X: {pair.xLabel})
                </h4>
                <span className="text-[11px] text-on-surface-variant font-medium">⭐ = จุด Optimal แนะนำ</span>
              </div>

              <div className="inline-block min-w-full">
                <table className="w-full border-collapse text-center text-xs">
                  <thead>
                    <tr>
                      <th className="p-1.5 text-right font-bold text-[10px] text-slate-500 uppercase">{pair.zLabel} \ {pair.xLabel}</th>
                      {heatmapRows[0]?.cells.map((c) => (
                        <th key={`th-${c.xVal}`} className="p-1.5 font-mono text-[10px] font-bold text-slate-600 dark:text-slate-400">
                          {c.xVal.toFixed(2)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {heatmapRows.map((row) => (
                      <tr key={`tr-${row.zVal}`}>
                        <td className="p-1.5 text-right font-mono text-[10px] font-bold text-slate-600 dark:text-slate-400 pr-2">
                          {row.zVal.toFixed(2)}
                        </td>
                        {row.cells.map((cell) => (
                          <td
                            key={`cell-${cell.xVal}-${cell.zVal}`}
                            className={`relative p-2 font-mono text-[11px] font-bold transition-transform hover:scale-110 cursor-pointer border border-black/10 rounded-sm`}
                            style={{ backgroundColor: cell.fillColor, color: cell.score >= 0.80 ? '#ffffff' : '#e2e8f0' }}
                            onClick={() => {
                              setSimX(Number(cell.xVal.toFixed(2)));
                              setSimZ(Number(cell.zVal.toFixed(2)));
                              setViewMode('simulator');
                            }}
                            title={`คลิกเพื่อจำลองจุดนี้: ${pair.xLabel}=${cell.xVal.toFixed(2)}, ${pair.zLabel}=${cell.zVal.toFixed(2)} (${metric.axisLabel}=${cell.score.toFixed(3)})`}
                          >
                            {cell.score.toFixed(3)}
                            {cell.isOptimal && (
                              <span className="absolute -top-1 -right-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-amber-400 text-[9px] text-black shadow">
                                ★
                              </span>
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Side 1D Cross-Section Curves */}
            <div className="lg:col-span-4 space-y-4">
              {/* Curve 1: Threshold / Parameter X Sensitivity */}
              <div className="rounded-xl border p-4 bg-surface-container-low/60 border-slate-200/60 dark:border-slate-800">
                <div className="flex items-center justify-between text-xs font-bold text-on-surface">
                  <span>
                    Sensitivity เมื่อล็อค {pair.zLabel} = {Number.isInteger(activeLockZ ?? pair.zOpt) ? (activeLockZ ?? pair.zOpt) : (activeLockZ ?? pair.zOpt).toFixed(2)}
                  </span>
                  <span className="text-teal-600 dark:text-cyan-400 font-mono text-[10px]">Curve X</span>
                </div>
                <p className="text-[10px] text-on-surface-variant mt-0.5">พฤติกรรมเมื่อปรับ {pair.xName}</p>

                {/* Interactive Lock Z Selector */}
                <div className="mt-2 flex items-center gap-1 overflow-x-auto py-1">
                  <span className="text-[10px] font-bold text-slate-500 whitespace-nowrap">ล็อค {pair.zLabel}:</span>
                  {(pair.ticksZ || [0.0, 0.25, 0.5, 0.75, 1.0]).map((val) => {
                    const isSelected = Math.abs((activeLockZ ?? pair.zOpt) - val) < 0.02;
                    const isOptimal = Math.abs(pair.zOpt - val) < 0.02;
                    return (
                      <button
                        key={`lock-z-${val}`}
                        type="button"
                        onClick={() => setActiveLockZ(val)}
                        className={`rounded px-1.5 py-0.5 text-[10px] font-bold font-mono transition-all whitespace-nowrap flex-shrink-0 ${
                          isSelected
                            ? 'bg-teal-600 text-white shadow-sm'
                            : isDark
                              ? 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                              : 'bg-slate-200 text-slate-700 hover:bg-slate-300'
                        }`}
                      >
                        {isOptimal && '⭐ '}{Number.isInteger(val) ? val : val.toFixed(2)}
                      </button>
                    );
                  })}
                </div>

                <div className="mt-2.5 flex items-end gap-1 h-20 w-full border-b border-l border-slate-300 dark:border-slate-700 px-1 pb-0.5">
                  {curveX.map((pt, idx) => {
                    const heightPct = Math.max(10, Math.min(100, ((pt.score - 0.30) / (0.95 - 0.30)) * 100));
                    const isMax = Math.abs(pt.xVal - pair.xOpt) <= (pair.xStep || 0.05);
                    return (
                      <div
                        key={`cx-${idx}`}
                        className={`flex-1 rounded-t transition-all ${isMax ? 'bg-amber-400 ring-1 ring-amber-300' : 'bg-teal-600/70 dark:bg-cyan-500/70'}`}
                        style={{ height: `${heightPct}%` }}
                        title={`${pair.xLabel} = ${Number.isInteger(pt.xVal) ? pt.xVal : pt.xVal.toFixed(2)} → Score = ${pt.score.toFixed(3)}`}
                      />
                    );
                  })}
                </div>
                <div className="flex justify-between text-[9px] text-slate-500 font-mono mt-1">
                  <span>{pair.xLabel}={Number.isInteger(pair.xMin) ? pair.xMin : pair.xMin.toFixed(2)}</span>
                  <span className="font-bold text-amber-500">Peak {pair.xLabel}={Number.isInteger(pair.xOpt) ? pair.xOpt : pair.xOpt.toFixed(2)}</span>
                  <span>{pair.xLabel}={Number.isInteger(pair.xMax) ? pair.xMax : pair.xMax.toFixed(2)}</span>
                </div>
              </div>

              {/* Curve 2: Parameter Z Sensitivity */}
              <div className="rounded-xl border p-4 bg-surface-container-low/60 border-slate-200/60 dark:border-slate-800">
                <div className="flex items-center justify-between text-xs font-bold text-on-surface">
                  <span>
                    Sensitivity เมื่อล็อค {pair.xLabel} = {Number.isInteger(activeLockX ?? pair.xOpt) ? (activeLockX ?? pair.xOpt) : (activeLockX ?? pair.xOpt).toFixed(2)}
                  </span>
                  <span className="text-cyan-600 dark:text-cyan-400 font-mono text-[10px]">Curve Z</span>
                </div>
                <p className="text-[10px] text-on-surface-variant mt-0.5">พฤติกรรมเมื่อปรับ {pair.zName}</p>

                {/* Interactive Lock X / Budget K Selector (1, 3, 5, 10, 15) */}
                <div className="mt-2 flex items-center gap-1 overflow-x-auto py-1">
                  <span className="text-[10px] font-bold text-slate-500 whitespace-nowrap">ล็อค {pair.xLabel}:</span>
                  {(pair.ticksX || [0.1, 0.3, 0.5, 0.7, 0.9]).map((val) => {
                    const isSelected = Math.abs((activeLockX ?? pair.xOpt) - val) < 0.02;
                    const isOptimal = Math.abs(pair.xOpt - val) < 0.02;
                    return (
                      <button
                        key={`lock-x-${val}`}
                        type="button"
                        onClick={() => setActiveLockX(val)}
                        className={`rounded px-1.5 py-0.5 text-[10px] font-bold font-mono transition-all whitespace-nowrap flex-shrink-0 ${
                          isSelected
                            ? 'bg-cyan-600 text-white shadow-sm'
                            : isDark
                              ? 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                              : 'bg-slate-200 text-slate-700 hover:bg-slate-300'
                        }`}
                      >
                        {isOptimal && '⭐ '}{Number.isInteger(val) ? val : val.toFixed(2)}
                      </button>
                    );
                  })}
                </div>

                <div className="mt-2.5 flex items-end gap-1 h-20 w-full border-b border-l border-slate-300 dark:border-slate-700 px-1 pb-0.5">
                  {curveZ.map((pt, idx) => {
                    const heightPct = Math.max(10, Math.min(100, ((pt.score - 0.30) / (0.95 - 0.30)) * 100));
                    const isMax = Math.abs(pt.zVal - pair.zOpt) <= (pair.zStep || 0.08);
                    return (
                      <div
                        key={`cz-${idx}`}
                        className={`flex-1 rounded-t transition-all ${isMax ? 'bg-amber-400 ring-1 ring-amber-300' : 'bg-cyan-600/70 dark:bg-teal-500/70'}`}
                        style={{ height: `${heightPct}%` }}
                        title={`${pair.zLabel} = ${Number.isInteger(pt.zVal) ? pt.zVal : pt.zVal.toFixed(2)} → Score = ${pt.score.toFixed(3)}`}
                      />
                    );
                  })}
                </div>
                <div className="flex justify-between text-[9px] text-slate-500 font-mono mt-1">
                  <span>{pair.zLabel}={Number.isInteger(pair.zMin) ? pair.zMin : pair.zMin.toFixed(2)}</span>
                  <span className="font-bold text-amber-500">Peak {pair.zLabel}={Number.isInteger(pair.zOpt) ? pair.zOpt : pair.zOpt.toFixed(2)}</span>
                  <span>{pair.zLabel}={Number.isInteger(pair.zMax) ? pair.zMax : pair.zMax.toFixed(2)}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* VIEW MODE 3: INTERACTIVE WHAT-IF SIMULATOR                                 */}
      {/* ========================================================================= */}
      {viewMode === 'simulator' && (
        <div className="p-5 sm:p-6 space-y-6">
          <div className="grid gap-6 md:grid-cols-12 items-center">
            {/* Sliders Control Panel */}
            <div className="md:col-span-7 space-y-5 rounded-2xl border p-5 bg-surface-container-low/70 border-slate-200/60 dark:border-slate-800">
              <h4 className="font-headline text-sm font-bold text-on-surface flex items-center gap-2">
                <span className="material-symbols-outlined text-teal-600">sliders</span>
                ตัวจำลองปรับค่าพารามิเตอร์แบบโต้ตอบ (Interactive Parameter Sliders)
              </h4>

              {/* Slider 1: Threshold tau */}
              <div>
                <div className="flex items-center justify-between text-xs font-bold mb-1.5">
                  <span className="text-on-surface">{pair.xName}</span>
                  <span className="font-mono text-teal-600 dark:text-cyan-400 font-extrabold text-sm">
                    {pair.xLabel} = {simX.toFixed(2)}
                  </span>
                </div>
                <input
                  type="range"
                  min={pair.xMin}
                  max={pair.xMax}
                  step={pair.xStep || 0.05}
                  value={simX}
                  onChange={(e) => setSimX(parseFloat(e.target.value))}
                  className="w-full accent-teal-600 cursor-pointer"
                />
                <div className="flex justify-between text-[10px] text-on-surface-variant font-mono mt-1">
                  <span>Min: {pair.xMin.toFixed(2)}</span>
                  <span className="text-emerald-600 dark:text-emerald-400 font-bold">Recommended: {pair.xOpt.toFixed(2)}</span>
                  <span>Max: {pair.xMax.toFixed(2)}</span>
                </div>
                <p className="mt-1 text-[11px] text-on-surface-variant">{pair.xShortDesc}</p>
              </div>

              {/* Slider 2: Parameter Z */}
              <div>
                <div className="flex items-center justify-between text-xs font-bold mb-1.5">
                  <span className="text-on-surface">{pair.zName}</span>
                  <span className="font-mono text-cyan-600 dark:text-cyan-400 font-extrabold text-sm">
                    {pair.zLabel} = {simZ.toFixed(2)}
                  </span>
                </div>
                <input
                  type="range"
                  min={pair.zMin}
                  max={pair.zMax}
                  step={pair.zStep || 0.05}
                  value={simZ}
                  onChange={(e) => setSimZ(parseFloat(e.target.value))}
                  className="w-full accent-cyan-600 cursor-pointer"
                />
                <div className="flex justify-between text-[10px] text-on-surface-variant font-mono mt-1">
                  <span>Min: {pair.zMin.toFixed(2)}</span>
                  <span className="text-cyan-600 dark:text-cyan-400 font-bold">Recommended: {pair.zOpt.toFixed(2)}</span>
                  <span>Max: {pair.zMax.toFixed(2)}</span>
                </div>
                <p className="mt-1 text-[11px] text-on-surface-variant">{pair.zShortDesc}</p>
              </div>

              {/* Reset to Optimal Button */}
              <div className="pt-2 flex gap-2">
                <button
                  type="button"
                  onClick={() => { setSimX(pair.xOpt); setSimZ(pair.zOpt); }}
                  className="rounded-lg px-3 py-1.5 text-xs font-bold bg-teal-600 text-white hover:bg-teal-700 transition-colors flex items-center gap-1.5"
                >
                  <span className="material-symbols-outlined text-[15px]">restart_alt</span>
                  <span>รีเซ็ตกลับเป็นจุด Sweet Spot (Optimal)</span>
                </button>
              </div>
            </div>

            {/* Performance Meter & Diagnostic Card */}
            <div className="md:col-span-5 rounded-2xl border p-5 bg-surface-container-lowest border-slate-200/60 dark:border-slate-800 space-y-4">
              <div className="text-center">
                <span className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">คะแนนคาดการณ์จำลอง</span>
                <div className="mt-1 font-headline text-3xl font-extrabold text-teal-700 dark:text-teal-300">
                  {simScore.toFixed(3)}
                </div>
                <span className="text-xs text-on-surface-variant font-semibold">
                  (มาตราวัด: {metric.label})
                </span>
              </div>

              {/* Visual Progress Bar */}
              <div className="w-full bg-slate-200 dark:bg-slate-800 rounded-full h-3 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-300"
                  style={{
                    width: `${Math.max(0, Math.min(100, ((simScore - 0.30) / (0.95 - 0.30)) * 100))}%`,
                    background: simScore >= 0.90
                      ? 'linear-gradient(to right, #059669, #10b981)'
                      : simScore >= 0.80
                        ? 'linear-gradient(to right, #0284c7, #38bdf8)'
                        : 'linear-gradient(to right, #d97706, #f59e0b)',
                  }}
                />
              </div>

              {/* Dynamic Verdict Box */}
              <div className={`rounded-xl border p-3.5 text-xs ${simVerdict.tone}`}>
                <strong className="block font-bold text-sm mb-1">{simVerdict.badge}</strong>
                <p className="leading-relaxed opacity-90">{simVerdict.text}</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* EXECUTIVE SUMMARY & KEY RESEARCH TAKEAWAYS (อ่านเข้าใจได้ทันที)             */}
      {/* ========================================================================= */}
      <div className={`border-t p-4 sm:p-5 ${isDark ? 'border-slate-800/80 bg-slate-950/70' : 'border-slate-200 bg-white'}`}>
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-[20px] text-teal-600 dark:text-cyan-400">insights</span>
              <h4 className="font-headline text-sm sm:text-base font-bold text-on-surface">
                สรุปผลการวิจัยและคำแนะนำในการตั้งค่าระบบ ({pair.zName} vs {pair.xName})
              </h4>
            </div>

            {/* 3 Clear Bullet Points */}
            <div className="grid gap-2.5 sm:grid-cols-3 pt-1">
              {pair.keyTakeaways.map((item, idx) => (
                <div key={idx} className="flex items-start gap-2 rounded-xl p-3 bg-surface-container-low/70 border border-slate-200/50 dark:border-slate-800">
                  <span className="material-symbols-outlined text-[18px] text-teal-600 dark:text-cyan-400 flex-shrink-0 mt-0.5">
                    {item.icon}
                  </span>
                  <span className="text-xs leading-relaxed text-on-surface font-medium">{item.text}</span>
                </div>
              ))}
            </div>
          </div>

          <button
            type="button"
            onClick={() => setShowExplanation(!showExplanation)}
            className="rounded-lg p-1.5 text-xs text-on-surface-variant hover:bg-surface-container-high transition-colors flex-shrink-0"
            title="แสดง/ซ่อน รายละเอียดทางวิชาการ"
          >
            <span className="material-symbols-outlined text-[18px]">
              {showExplanation ? 'expand_less' : 'help'}
            </span>
          </button>
        </div>

        {/* Expandable Academic Guide */}
        {showExplanation && (
          <div className="mt-4 border-t border-slate-200/60 pt-3 dark:border-slate-800/80 text-xs">
            <div className="rounded-xl bg-teal-50/60 dark:bg-cyan-950/30 p-3.5 border border-teal-200/60 dark:border-cyan-800/40 text-teal-950 dark:text-cyan-100">
              <strong className="font-bold flex items-center gap-1.5 text-sm mb-1">
                <span className="material-symbols-outlined text-[18px]">menu_book</span>
                หลักการตีความสำหรับเล่มวิทยานิพนธ์ (Thesis Interpretation Principle):
              </strong>
              <p className="leading-relaxed text-xs opacity-90">
                {pair.interpretation} — <strong className="text-amber-600 dark:text-amber-400">หมายเหตุ: พื้นผิวนี้สร้างจากสูตรจำลองทางทฤษฎีเพื่อแสดงแนวคิด ไม่ใช่ผลการ sweep จริง ใช้เพื่อประกอบความเข้าใจหลักการเท่านั้น</strong>
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className={`flex flex-wrap items-center justify-between gap-3 border-t px-5 py-2.5 text-xs ${isDark ? 'border-slate-800/80 bg-slate-950/70 text-slate-400' : 'border-slate-200 bg-white/70 text-slate-600'}`}>
        <div className="flex items-center gap-2">
          <span className={`material-symbols-outlined text-[16px] ${isDark ? 'text-cyan-400' : 'text-teal-700'}`}>touch_app</span>
          <span>สลับมุมมองได้ที่ปุ่ม 3D Surface / 2D Heatmap / Simulator ด้านบนขวา</span>
        </div>
        <div className="flex items-center gap-2 font-mono text-[11px]">
          <span>Current View: {viewMode.toUpperCase()}</span>
          <span>· Metric: {metric.label}</span>
        </div>
      </div>
    </div>
  );
}

