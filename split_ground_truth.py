import json
import random
import argparse
import re
from pathlib import Path
from difflib import SequenceMatcher

VARIANT_SUFFIX_RE = re.compile(r"(_PAR_\d+|_ESC_\d+|_SIM_\d+)$")
POLARITY_SUFFIX_RE = re.compile(r"_(POS|NEG)(?:_V\d+)?$")


def case_family(case_id: str) -> str:
    case_id = VARIANT_SUFFIX_RE.sub("", case_id)
    case_id = POLARITY_SUFFIX_RE.sub("", case_id)
    return case_id


def resolve_near_duplicate_cross_split(cases, threshold=0.9):
    """Move near-duplicate generated cases into the same split as their pair."""
    changed = 0
    by_family = {}
    for case in cases:
        by_family.setdefault(case_family(case.get("case_id", "")), []).append(case)

    def move_family(family, split):
        nonlocal changed
        for member in by_family.get(family, []):
            if member.get("split") != split:
                member["split"] = split
                changed += 1

    normalized = [
        (
            case,
            " ".join(case.get("case_description", "").split()),
        )
        for case in cases
        if case.get("case_description")
    ]

    for i, (case_a, text_a) in enumerate(normalized):
        for case_b, text_b in normalized[i + 1:]:
            if case_a.get("split") == case_b.get("split"):
                continue
            if case_family(case_a.get("case_id", "")) == case_family(case_b.get("case_id", "")):
                continue
            ratio = SequenceMatcher(None, text_a, text_b).ratio()
            if ratio < threshold:
                continue

            # Prefer moving generated near-duplicates out of the test split so
            # the headline test set stays conservative. Original cases keep
            # their assigned split unless both sides are generated.
            id_a = case_a.get("case_id", "")
            id_b = case_b.get("case_id", "")
            family_a = case_family(id_a)
            family_b = case_family(id_b)
            a_generated = any(token in id_a for token in ("_PAR_", "_ESC_", "_SIM_")) or id_a.startswith(("ADV_", "NEG_"))
            b_generated = any(token in id_b for token in ("_PAR_", "_ESC_", "_SIM_")) or id_b.startswith(("ADV_", "NEG_"))

            if case_a.get("split") == "test" and a_generated:
                move_family(family_a, case_b.get("split", "train"))
            elif case_b.get("split") == "test" and b_generated:
                move_family(family_b, case_a.get("split", "train"))

    return changed


def main():
    parser = argparse.ArgumentParser(description="Apply leakage-safe family-level train/test split")
    parser.add_argument("--ground-truth", default="expanded_ground_truth.json")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--test-ratio", type=float, default=0.3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    random.seed(args.seed)  # For reproducibility

    gt_path = Path(args.ground_truth)
    with open(gt_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Clean existing cases and build structure
    normal_cases = []
    polarity_pairs = {}

    for case in data["cases"]:
        c_id = case["case_id"]
        
        # Inject natural polarity labels to normal cases
        if not c_id.startswith("NEG_"):
            case["is_negated"] = False
            case["polarity_type"] = "base_affirmative"
            normal_cases.append(case)
        else:
            # Group polarity cases by their prefix (e.g., "NEG_SH")
            base_id = c_id[:-4] # e.g. NEG_SH from NEG_SH_POS
            if base_id not in polarity_pairs:
                polarity_pairs[base_id] = []
            polarity_pairs[base_id].append(case)

    # Force polarity pairs into the test set as a stress-test benchmark for G_neg.
    for key, pairs in polarity_pairs.items():
        for case in pairs:
            case["split"] = "test"

    # Family-level split for normal/generated variants. This prevents original
    # cases and their paraphrase/simplified/escalated variants from landing in
    # different splits, which would inflate performance via leakage.
    cat_bins = {}
    for case in normal_cases:
        cat = case.get("category", "unknown")
        if cat not in cat_bins:
            cat_bins[cat] = {}
        cat_bins[cat].setdefault(case_family(case["case_id"]), []).append(case)

    for cat, family_map in cat_bins.items():
        families = list(family_map.values())
        random.shuffle(families)
        num_test = max(1, int(len(families) * args.test_ratio)) if len(families) >= 4 else (
            1 if random.random() > 0.5 else 0
        )

        for idx, family_cases in enumerate(families):
            split = "test" if idx < num_test else "train"
            for case in family_cases:
                case["split"] = split

    duplicate_moves = resolve_near_duplicate_cross_split(normal_cases)

    # Verify counts
    train_count = sum(1 for c in data["cases"] if c.get("split") == "train")
    test_count = sum(1 for c in data["cases"] if c.get("split") == "test")
    base_aff_test = sum(1 for c in data["cases"] if c.get("split") == "test" and c.get("polarity_type") == "base_affirmative")

    print(f"✅ Split applied successfully.")
    print(f"Total Cases: {len(data['cases'])}")
    print(f"Train Set: {train_count} cases")
    print(f"Test Set: {test_count} cases")
    print(f"  - Base Affirmative Test Cases (Real FPR evaluation pool): {base_aff_test} cases")
    print(f"  - Contrastive Polarity Test Cases: {sum(1 for c in data['cases'] if c.get('split') == 'test' and c.get('polarity_type') != 'base_affirmative')}")

    negated_test = sum(1 for c in data["cases"] if c.get("split") == "test" and c.get("is_negated", c.get("has_negation", False)))

    # Write back
    data["metadata"]["split_ratio"] = f"{1 - args.test_ratio:.0%}/{args.test_ratio:.0%}"
    data["metadata"]["split_method"] = "family_level_stratified_by_category"
    data["metadata"]["split_seed"] = args.seed
    data["metadata"]["near_duplicate_resolution_threshold"] = 0.9
    data["metadata"]["near_duplicate_split_moves"] = duplicate_moves
    data["metadata"]["train_cases"] = train_count
    data["metadata"]["test_cases"] = test_count
    data["metadata"]["test_affirmative_cases"] = base_aff_test
    data["metadata"]["test_negated_cases"] = negated_test

    if args.dry_run:
        print("🔎 Dry run only; ground truth file was not modified.")
    else:
        with open(gt_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
