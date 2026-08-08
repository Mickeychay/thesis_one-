#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ground Truth Audit for H2L thesis experiments.

Checks the split for common Q1-review risks:
  - generated/paraphrase cases mixed with original cases
  - case-family leakage across train/test
  - duplicate or near-duplicate case descriptions across splits
  - missing split annotations

This script is read-only by default.
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Tuple


VARIANT_SUFFIX_RE = re.compile(r"(_PAR_\d+|_ESC_\d+|_SIM_\d+)$")
POLARITY_SUFFIX_RE = re.compile(r"_(POS|NEG)(?:_V\d+)?$")


def case_family(case_id: str) -> str:
    """Collapse augmented IDs to their source family."""
    case_id = VARIANT_SUFFIX_RE.sub("", case_id)
    case_id = POLARITY_SUFFIX_RE.sub("", case_id)
    return case_id


def augmentation_type(case: Dict) -> str:
    case_id = case.get("case_id", "")
    if case_id.startswith("NEG_"):
        return "polarity"
    if "_PAR_" in case_id:
        return "paraphrase"
    if "_ESC_" in case_id:
        return "complexity_escalation"
    if "_SIM_" in case_id:
        return "complexity_reduction"
    if case_id.startswith("ADV_"):
        return "adversarial"
    return case.get("augmentation_type", "original")


def find_cross_split_families(cases: List[Dict]) -> List[Dict]:
    grouped = defaultdict(list)
    for case in cases:
        grouped[case_family(case.get("case_id", ""))].append(case)

    leaks = []
    for family, members in grouped.items():
        splits = {member.get("split", "missing") for member in members}
        if "train" in splits and "test" in splits:
            leaks.append(
                {
                    "family": family,
                    "splits": sorted(splits),
                    "case_ids": [member.get("case_id") for member in members],
                }
            )
    return leaks


def find_exact_duplicates(cases: List[Dict]) -> List[Dict]:
    """Find identical normalized descriptions, including within one split."""
    grouped = defaultdict(list)
    for case in cases:
        text = " ".join(case.get("case_description", "").split())
        if text:
            grouped[text].append(
                {
                    "case_id": case.get("case_id", ""),
                    "split": case.get("split", "missing"),
                }
            )
    return [
        {"case_ids": members, "normalized_text": text}
        for text, members in grouped.items()
        if len(members) > 1
    ]


def find_near_duplicates(cases: List[Dict], threshold: float) -> List[Dict]:
    duplicates = []
    normalized = [
        (
            case.get("case_id", ""),
            case.get("split", "missing"),
            " ".join(case.get("case_description", "").split()),
        )
        for case in cases
    ]

    for i, (case_a, split_a, text_a) in enumerate(normalized):
        if not text_a:
            continue
        for case_b, split_b, text_b in normalized[i + 1:]:
            if split_a == split_b or not text_b:
                continue
            ratio = SequenceMatcher(None, text_a, text_b).ratio()
            if ratio >= threshold:
                duplicates.append(
                    {
                        "case_a": case_a,
                        "split_a": split_a,
                        "case_b": case_b,
                        "split_b": split_b,
                        "similarity": round(ratio, 4),
                    }
                )
    return duplicates


def audit_ground_truth(path: str, duplicate_threshold: float = 0.9) -> Dict:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    cases = data.get("cases", [])
    missing_split = [case.get("case_id", "unknown") for case in cases if "split" not in case]
    split_counts = Counter(case.get("split", "missing") for case in cases)
    augmentation_counts = Counter(augmentation_type(case) for case in cases)
    split_by_aug = defaultdict(Counter)
    for case in cases:
        split_by_aug[augmentation_type(case)][case.get("split", "missing")] += 1

    cross_split_families = find_cross_split_families(cases)
    exact_duplicates = find_exact_duplicates(cases)
    near_duplicates = find_near_duplicates(cases, duplicate_threshold)

    risk_flags = []
    if missing_split:
        risk_flags.append("missing_split_annotations")
    if cross_split_families:
        risk_flags.append("case_family_cross_split_leakage")
    if exact_duplicates:
        risk_flags.append("exact_duplicate_case_descriptions")
    if near_duplicates:
        risk_flags.append("near_duplicate_cross_split_cases")
    if augmentation_counts.get("paraphrase", 0) or augmentation_counts.get("polarity", 0):
        risk_flags.append("generated_cases_present_report_separately")

    return {
        "path": path,
        "total_cases": len(cases),
        "split_counts": dict(split_counts),
        "augmentation_counts": dict(augmentation_counts),
        "split_by_augmentation": {k: dict(v) for k, v in split_by_aug.items()},
        "missing_split": missing_split,
        "cross_split_families": cross_split_families,
        "exact_duplicates": exact_duplicates,
        "near_duplicates": near_duplicates,
        "duplicate_threshold": duplicate_threshold,
        "risk_flags": risk_flags,
        "recommendation": (
            "Use group/family-level splits and report generated/adversarial/polarity cases "
            "as separate stress-test slices before making Q1-level generalization claims."
        ),
    }


def write_markdown(report: Dict, output_path: str) -> None:
    lines = [
        "# Ground Truth Audit",
        "",
        f"- Source: `{report['path']}`",
        f"- Total cases: {report['total_cases']}",
        f"- Split counts: `{report['split_counts']}`",
        f"- Augmentation counts: `{report['augmentation_counts']}`",
        f"- Risk flags: `{report['risk_flags'] or ['none']}`",
        "",
        "## Cross-Split Families",
        "",
    ]

    leaks = report["cross_split_families"]
    if leaks:
        lines.extend(["| Family | Splits | Case IDs |", "|---|---|---|"])
        for leak in leaks[:50]:
            lines.append(
                f"| {leak['family']} | {', '.join(leak['splits'])} | "
                f"{', '.join(leak['case_ids'])} |"
            )
        if len(leaks) > 50:
            lines.append(f"| ... | ... | {len(leaks) - 50} more families omitted |")
    else:
        lines.append("No train/test family overlap detected.")

    lines.extend(["", "## Exact Duplicate Descriptions", ""])
    exact_duplicates = report["exact_duplicates"]
    if exact_duplicates:
        lines.extend(["| Case IDs and Splits | Normalized Text |", "|---|---|"])
        for duplicate in exact_duplicates[:50]:
            labels = ", ".join(
                f"{item['case_id']} ({item['split']})"
                for item in duplicate["case_ids"]
            )
            lines.append(f"| {labels} | {duplicate['normalized_text']} |")
    else:
        lines.append("No identical normalized case descriptions detected.")

    lines.extend(["", "## Near Duplicates Across Splits", ""])
    duplicates = report["near_duplicates"]
    if duplicates:
        lines.extend(["| Case A | Split A | Case B | Split B | Similarity |", "|---|---|---|---|---|"])
        for dup in duplicates[:50]:
            lines.append(
                f"| {dup['case_a']} | {dup['split_a']} | {dup['case_b']} | "
                f"{dup['split_b']} | {dup['similarity']:.4f} |"
            )
        if len(duplicates) > 50:
            lines.append(f"| ... | ... | ... | ... | {len(duplicates) - 50} more pairs omitted |")
    else:
        lines.append("No near-duplicate train/test pairs above threshold.")

    lines.extend(["", "## Recommendation", "", report["recommendation"], ""])
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit ground truth split integrity")
    parser.add_argument("--ground-truth", default="expanded_ground_truth.json")
    parser.add_argument("--output-json", default="evaluation_results/ground_truth_audit.json")
    parser.add_argument("--output-md", default="evaluation_results/ground_truth_audit.md")
    parser.add_argument("--duplicate-threshold", type=float, default=0.9)
    args = parser.parse_args()

    report = audit_ground_truth(args.ground_truth, args.duplicate_threshold)
    Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report, args.output_md)

    print(f"Audit JSON: {args.output_json}")
    print(f"Audit Markdown: {args.output_md}")
    if report["risk_flags"]:
        print("Risk flags:", ", ".join(report["risk_flags"]))


if __name__ == "__main__":
    main()
