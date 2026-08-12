import json

with open("data/expanded_ground_truth.json", "r") as f:
    data = json.load(f)

cases = data.get("cases", [])
test_cases = [c for c in cases if c.get("split") == "test"]

print(f"Total Test Cases: {len(test_cases)}")

complexities = {}
lengths = []
target_counts = []

for c in test_cases:
    comp = c.get("complexity", "unknown")
    complexities[comp] = complexities.get(comp, 0) + 1
    
    desc = c.get("case_description", "")
    lengths.append(len(desc))
    
    gt = c.get("expected_diagnosis", {}).get("problem_list", [])
    target_counts.append(len(gt))

print("Complexity distribution:", complexities)
print(f"Query lengths (chars): Min={min(lengths)}, Max={max(lengths)}, Avg={sum(lengths)/len(lengths):.1f}")
print(f"Target codes per case: Min={min(target_counts)}, Max={max(target_counts)}, Avg={sum(target_counts)/len(target_counts):.1f}")

