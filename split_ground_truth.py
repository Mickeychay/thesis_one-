import json
import random
from pathlib import Path

def main():
    random.seed(42)  # For reproducibility

    gt_path = Path("expanded_ground_truth.json")
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

    # We want ~70/30 split for NORMAL cases.
    # Total cases ~179.
    # Polarity Pairs: 9 pairs (18 cases). We will force ALL of these into the Test set to serve as the stress-test benchmark for G_neg.
    for key, pairs in polarity_pairs.items():
        for case in pairs:
            case["split"] = "test"

    # Normal cases: 161. 70/30 means ~48 test, ~113 train.
    # Let's stratify by Category roughly.
    cat_bins = {}
    for case in normal_cases:
        cat = case.get("category", "unknown")
        if cat not in cat_bins:
            cat_bins[cat] = []
        cat_bins[cat].append(case)

    for cat, cases in cat_bins.items():
        random.shuffle(cases)
        # 30% to test
        num_test = max(1, int(len(cases) * 0.3)) if len(cases) >= 4 else (1 if random.random() > 0.5 else 0)
        
        test_slice = cases[:num_test]
        train_slice = cases[num_test:]
        
        for case in test_slice:
            case["split"] = "test"
        for case in train_slice:
            case["split"] = "train"

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
    data["metadata"]["split_ratio"] = "70/30"
    data["metadata"]["train_cases"] = train_count
    data["metadata"]["test_cases"] = test_count
    data["metadata"]["test_affirmative_cases"] = base_aff_test
    data["metadata"]["test_negated_cases"] = negated_test
    
    with open(gt_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
