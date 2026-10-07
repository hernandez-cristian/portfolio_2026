#!/usr/bin/env python3
"""Print prompts with both runs' answers, blinded as A and B. Usage: show.py FIRST LAST (numbers)."""

import sys
from common import ABBR, FULL, load_map, load_prompts, load_runs

first, last = int(sys.argv[1]), int(sys.argv[2])
P, R, M = load_prompts(), load_runs(), load_map()
for n in range(first, last + 1):
    i = "C%03d" % n
    p = P[i]
    a = M[i]
    b = "WITH_SYSTEM" if a == "NO_SYSTEM" else "NO_SYSTEM"
    traits = [FULL[p["primary_trait"]]] + [FULL[s] for s in p["secondary_traits"]]
    print("=" * 100)
    print("%s | %s | score: %s" % (i, p["category"], ", ".join(traits)))
    print("PROBE: " + p["probe"])
    print("PROMPT:\n" + p["prompt"])
    for label, run in (("A", a), ("B", b)):
        resp = R[run][i]["model_response"]
        print("\n----- %s (%d words) -----\n%s" % (label, len(resp.split()), resp))
print("=" * 100)
