import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MD_DIR = ROOT / "md_report"

chapters_dir = MD_DIR / "chapters"
diagrams_dir = MD_DIR / "diagrams"
presentation_dir = MD_DIR / "presentation"

chapters_dir.mkdir(exist_ok=True)
diagrams_dir.mkdir(exist_ok=True)
presentation_dir.mkdir(exist_ok=True)

# Copy chapters
shutil.copy(MD_DIR / "thesis_abstract.md", chapters_dir / "00_abstract.md")
shutil.copy(MD_DIR / "thesis_full_ch1_intro.md", chapters_dir / "ch1_intro.md")
shutil.copy(MD_DIR / "thesis_full_ch2_lit_review.md", chapters_dir / "ch2_lit_review.md")
shutil.copy(MD_DIR / "thesis_full_ch3_methodology.md", chapters_dir / "ch3_methodology.md")
shutil.copy(MD_DIR / "thesis_ch4_verified_20260807.md", chapters_dir / "ch4_results.md")
shutil.copy(MD_DIR / "thesis_full_ch5_conclusion.md", chapters_dir / "ch5_conclusion.md")

# Copy diagrams
for diag in MD_DIR.glob("diagram_*.md"):
    shutil.copy(diag, diagrams_dir / diag.name)

# Copy presentation
if (MD_DIR / "slides_h2l_presentation.md").is_file():
    shutil.copy(MD_DIR / "slides_h2l_presentation.md", presentation_dir / "slides_h2l_presentation.md")

print("Successfully organized md_report into subfolders!")
