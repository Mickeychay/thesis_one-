import json

with open("data/expanded_ground_truth.json", "r") as f:
    data = json.load(f)

taxonomy = set()
for case in data.get("cases", []):
    for prob in case.get("expected_diagnosis", {}).get("problem_list", []):
        if prob.get("code_type") == "SOCIAL":
            taxonomy.add((prob.get("code"), prob.get("category")))

for code, cat in sorted(taxonomy):
    print(f"{code} | {cat}")
