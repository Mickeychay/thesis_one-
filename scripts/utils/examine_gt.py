import json
with open('data/expanded_ground_truth.json', 'r') as f:
    data = json.load(f)
print(data['metadata'])
