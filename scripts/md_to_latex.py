import os
import subprocess
from pathlib import Path

def convert_chapter(md_file, tex_file):
    cmd = [
        "pandoc",
        str(md_file),
        "-o", str(tex_file),
        "--from=markdown+tex_math_single_backslash",
        "--to=latex",
        "--top-level-division=chapter"
    ]
    try:
        subprocess.run(cmd, check=True)
        print(f"✅ Converted {md_file.name} -> {tex_file.name}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error converting {md_file.name}: {e}")

def main():
    md_dir = Path("md_report")
    tex_dir = Path("thesis_latex/chapters")
    tex_dir.mkdir(parents=True, exist_ok=True)

    mapping = {
        "thesis_full_ch1_intro.md": "ch1_intro.tex",
        "thesis_full_ch2_lit_review.md": "ch2_lit_review.tex",
        "thesis_full_ch3_methodology.md": "ch3_methodology.tex",
        "thesis_full_ch4_results.md": "ch4_results.tex",
        "thesis_full_ch5_conclusion.md": "ch5_conclusion.tex",
    }

    for md_name, tex_name in mapping.items():
        md_file = md_dir / md_name
        tex_file = tex_dir / tex_name
        if md_file.exists():
            convert_chapter(md_file, tex_file)
            
            # Post-processing: Pandoc sometimes adds \protect\hyperlink which can be annoying
            # Or it might not handle \tightlist. We can add minor fixes if needed.
            with open(tex_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Very basic cleanup
            content = content.replace('\\tightlist', '')
            
            with open(tex_file, 'w', encoding='utf-8') as f:
                f.write(content)

if __name__ == "__main__":
    main()
