#!/usr/bin/env python3
"""Validate grades (JSON lines on stdin) and merge them into grades.jsonl.

Line format: {"id":"C001","A":{"s":{"gi":5,"bb":4},"w":{"bb":"generic"},"t":["specifics"],"f":"finding"},"B":{...}}
- s: a 1-5 score for the primary trait and every secondary trait (abbreviations), nothing else
- w: for each score below 5, the issue tag that cost the points
- t: behavior tags; f: one-sentence finding
"""

import json
import sys
from common import ABBR, FULL, GRADES, ISSUES, TAGS, load_grades, load_prompts

P = load_prompts()
existing = load_grades()
new = {}
errors = []
for raw in sys.stdin.read().splitlines():
    if not raw.strip():
        continue
    try:
        g = json.loads(raw)
    except json.JSONDecodeError as e:
        errors.append("bad JSON: %s :: %s" % (e, raw[:80]))
        continue
    i = g.get("id")
    if i not in P:
        errors.append("unknown id %r" % i)
        continue
    p = P[i]
    want = {FULL[p["primary_trait"]]} | {FULL[s] for s in p["secondary_traits"]}
    for side in ("A", "B"):
        x = g.get(side)
        if not isinstance(x, dict):
            errors.append("%s: missing side %s" % (i, side))
            continue
        s, w, t, f = x.get("s", {}), x.get("w", {}), x.get("t", []), x.get("f", "")
        if set(s) != want:
            errors.append("%s%s: scored %s, need %s" % (i, side, sorted(s), sorted(want)))
        for k, v in s.items():
            if v not in (1, 2, 3, 4, 5):
                errors.append("%s%s: bad score %r for %s" % (i, side, v, k))
            if v < 5 and w.get(k) not in ISSUES:
                errors.append("%s%s: %s=%s needs an issue cause in w (got %r)" % (i, side, k, v, w.get(k)))
        for k in w:
            if k not in s or s[k] == 5:
                errors.append("%s%s: cause given for %s but it isn't below 5" % (i, side, k))
        for tag in t:
            if tag not in TAGS:
                errors.append("%s%s: unknown tag %r" % (i, side, tag))
        for k, cause in w.items():
            if cause not in t:
                t.append(cause)
        if not f.strip():
            errors.append("%s%s: empty finding" % (i, side))
    new[i] = g

if errors:
    print("NOT SAVED. Fix these:\n  " + "\n  ".join(errors))
    sys.exit(1)
existing.update(new)
order = sorted(existing)
GRADES.write_text("".join(json.dumps(existing[k], ensure_ascii=False) + "\n" for k in order))
print("saved %d; total graded %d/500; next ungraded: %s" % (
    len(new), len(existing), next(("C%03d" % n for n in range(1, 501) if "C%03d" % n not in existing), "none")))
