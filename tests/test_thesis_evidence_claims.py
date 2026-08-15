import hashlib
import json
from pathlib import Path

from scripts.build_chapter4_evidence import EVIDENCE_SCOPE


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_CHAPTER5_FILES = (
    ROOT / "md_report/THESIS_FULL_MASTER.md",
    ROOT / "md_report/chapters/ch5_conclusion.md",
    ROOT / "md_report/thesis_full_ch5_conclusion.md",
)
HISTORICAL_CHAPTER4_FILES = (
    ROOT / "md_report/chapters/ch4_results.md",
    ROOT / "md_report/thesis_full_ch4_results.md",
    ROOT / "md_report/thesis_ch4_verified_20260807.md",
)


def test_active_chapter5_claims_match_two_sided_single_run_evidence():
    stale_claims = (
        "Holm p = 0.034",
        "Holm p = 0.019",
        "p >= 0.541",
        "p ≥ 0.541",
        "บนการรันประมวลผลซ้ำ 3 รอบ",
        "98.2%",
        "Production-Ready",
    )

    for path in ACTIVE_CHAPTER5_FILES:
        text = path.read_text(encoding="utf-8")
        assert not any(claim in text for claim in stale_claims), path
        assert "Holm p = 0.0676" in text
        assert "Holm p = 0.0379" in text
        assert "มีเพียง 1 รอบต่อกรณี" in text
        assert "taxonomy runtime ปัจจุบัน" in text


def test_master_uses_current_polarity_strata_and_runtime_adversarial_metrics():
    text = (ROOT / "md_report/THESIS_FULL_MASTER.md").read_text(encoding="utf-8")

    assert "| unknown | 56 | 0 | 0.0000 | 0.0357 |" in text
    assert "| H2L-hybrid | 0.0500 | 0.0500 | 0.0574 | 0.0574 |" in text
    assert "การเปรียบเทียบรูปแบบ window หลายค่าที่เคยจัดทำ" in text


def test_current_ground_truth_audit_matches_225_case_dataset():
    audit_path = ROOT / "evaluation_results/ground_truth_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    assert audit["total_cases"] == 225
    assert audit["split_counts"] == {"train": 125, "test": 100}
    assert audit["augmentation_counts"]["original"] == 105
    assert audit["cross_split_families"] == []
    assert audit["exact_duplicates"] == []
    assert audit["near_duplicates"] == []

    digest = hashlib.sha256(audit_path.read_bytes()).hexdigest()[:12]
    master = (ROOT / "md_report/THESIS_FULL_MASTER.md").read_text(encoding="utf-8")
    assert f"| Ground-truth audit | evaluation_results/ground_truth_audit.json | {digest} |" in master


def test_legacy_chapter4_outputs_are_marked_historical():
    assert EVIDENCE_SCOPE == "archived_historical_95_case"
    for path in HISTORICAL_CHAPTER4_FILES:
        text = path.read_text(encoding="utf-8")
        assert "หลักฐานรองเชิงประวัติ" in text, path
        assert "ไม่ใช่บทที่ 4 หลัก" in text, path
