import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MD_DIR = ROOT / "md_report"

files_to_combine = [
    ("บทคัดย่อ (Abstract)", MD_DIR / "thesis_abstract.md"),
    ("บทที่ 1: บทนำ (Introduction)", MD_DIR / "thesis_full_ch1_intro.md"),
    ("บทที่ 2: การทบทวนวรรณกรรม (Literature Review)", MD_DIR / "thesis_full_ch2_lit_review.md"),
    ("บทที่ 3: วิธีดำเนินการวิจัย (Methodology)", MD_DIR / "thesis_full_ch3_methodology.md"),
    ("บทที่ 4: ผลการศึกษาวิจัย (Results)", MD_DIR / "thesis_ch4_verified_20260807.md"),
    ("บทที่ 5: สรุป อภิปรายผล และข้อเสนอแนะ (Conclusion)", MD_DIR / "thesis_full_ch5_conclusion.md"),
]

output_path = MD_DIR / "THESIS_FULL_MASTER.md"

combined_text = []
combined_text.append("# 📄 เล่มวิทยานิพนธ์ฉบับสมบูรณ์ (H2L Thesis Master Document)\n")
combined_text.append("> **หมายเหตุ**: เอกสารนี้รวบรวมเนื้อหาบทคัดย่อและบทที่ 1-5 ทั้งหมดที่อัปเดตตัวเลขผลการทดลอง 100 เคสล่าสุดเรียบร้อยแล้ว\n\n---\n\n")

for title, file_path in files_to_combine:
    if file_path.is_file():
        content = file_path.read_text(encoding="utf-8")
        combined_text.append(f"\n\n<!-- ==================== {title} ==================== -->\n\n")
        combined_text.append(content)
        combined_text.append("\n\n---\n\n")
    else:
        print(f"Warning: Missing file {file_path}")

output_path.write_text("".join(combined_text), encoding="utf-8")
print(f"Successfully generated {output_path} ({len(''.join(combined_text))} characters)")
