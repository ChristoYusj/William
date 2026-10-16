"""Score the human check: precision per checker, agreement with the AI check, agreement between humans.

    python eval/human_check/score.py eval/human_check/human_check_*.json

Inputs are the JSON files downloaded from human_check.html. "unsure" is reported separately and excluded from
agreement. Cohen's kappa is computed on correct vs wrong.
"""
import json
import sys
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).parent
items = {str(i["hid"]): i for i in json.loads((HERE / "items.json").read_text(encoding="utf-8"))}
ai = {a["id"]: a["verdict"] for a in json.loads((HERE.parent / "ai_check_kept_values.json").read_text(encoding="utf-8"))["items"]}
ai_v = {hid: ai[i["ai_id"]] for hid, i in items.items()}


def kappa(a, b):
    keys = [k for k in a if k in b and a[k] in ("correct", "wrong") and b[k] in ("correct", "wrong")]
    if not keys:
        return None, 0
    po = sum(a[k] == b[k] for k in keys) / len(keys)
    pa = sum(a[k] == "correct" for k in keys) / len(keys)
    pb = sum(b[k] == "correct" for k in keys) / len(keys)
    pe = pa * pb + (1 - pa) * (1 - pb)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0, len(keys), po


humans = {}
for f in sys.argv[1:]:
    d = json.loads(Path(f).read_text(encoding="utf-8"))
    humans[d["checker"]] = d["verdicts"]

print("| checker | judged | correct | wrong | unsure | precision (unsure = wrong) |\n|---|---|---|---|---|---|")
for name, v in list(humans.items()) + [("AI (same 50)", ai_v)]:
    c = sum(x == "correct" for x in v.values()); w = sum(x == "wrong" for x in v.values()); u = sum(x == "unsure" for x in v.values())
    print(f"| {name} | {len(v)} | {c} | {w} | {u} | {c / max(1, len(v)):.2f} |")
print()
for name, v in humans.items():
    k = kappa(v, ai_v)
    if k[0] is not None:
        print(f"{name} vs AI: raw agreement {k[2]:.2f}, Cohen's kappa {k[0]:.2f} on {k[1]} items")
for (n1, v1), (n2, v2) in combinations(humans.items(), 2):
    k = kappa(v1, v2)
    if k[0] is not None:
        print(f"{n1} vs {n2}: raw agreement {k[2]:.2f}, Cohen's kappa {k[0]:.2f} on {k[1]} items")
