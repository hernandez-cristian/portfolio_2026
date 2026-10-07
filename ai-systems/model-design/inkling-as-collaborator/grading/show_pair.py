#!/usr/bin/env python3
"""Print prompts N..M with both answers under the pairwise A/B shuffle. No earlier grades are shown."""
import sys
from common import FULL, load_prompts, load_runs
from pair_common import make_map
first, last = int(sys.argv[1]), int(sys.argv[2])
P, R, M = load_prompts(), load_runs(), make_map()
for n in range(first, last + 1):
    i = "C%03d" % n; p = P[i]; a = M[i]; b = "WITH_SYSTEM" if a == "NO_SYSTEM" else "NO_SYSTEM"
    traits = [FULL[p["primary_trait"]]] + [FULL[s] for s in p["secondary_traits"]]
    print("=" * 90)
    print("%s | %s | traits: %s" % (i, p["category"], ", ".join(traits)))
    print("PROBE: " + p["probe"])
    print("PROMPT:\n" + p["prompt"])
    for label, run in (("A", a), ("B", b)):
        resp = R[run][i]["model_response"]
        print("\n--- %s (%d words) ---\n%s" % (label, len(resp.split()), resp))
print("=" * 90)
