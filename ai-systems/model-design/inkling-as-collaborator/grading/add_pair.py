#!/usr/bin/env python3
"""Validate pairwise judgments (JSON lines on stdin) and merge into pairs.jsonl.
Line: {"id":"C001","v":"A>","d":["gi","bb"],"r":"one-sentence reason"}
v: A>> (A clearly better), A> (A somewhat better), = (no meaningful difference), B>, B>>
d: the trait codes that decided it (empty only for =)."""
import json, sys
from common import ABBR, load_prompts
from pair_common import PAIRS, VERDICTS, load_pairs
P = load_prompts(); existing = load_pairs(); new = {}; errors = []
for raw in sys.stdin.read().splitlines():
    if not raw.strip(): continue
    try: g = json.loads(raw)
    except json.JSONDecodeError as e: errors.append("bad JSON %s :: %s" % (e, raw[:80])); continue
    i = g.get("id")
    if i not in P: errors.append("unknown id %r" % i); continue
    if g.get("v") not in VERDICTS: errors.append("%s: bad verdict %r" % (i, g.get("v")))
    d = g.get("d", [])
    if any(k not in ABBR for k in d): errors.append("%s: unknown trait in %r" % (i, d))
    if g.get("v") != "=" and not d: errors.append("%s: non-tie needs deciding traits" % i)
    if not g.get("r", "").strip(): errors.append("%s: empty reason" % i)
    new[i] = g
if errors:
    print("NOT SAVED:\n  " + "\n  ".join(errors)); sys.exit(1)
existing.update(new)
PAIRS.write_text("".join(json.dumps(existing[k], ensure_ascii=False) + "\n" for k in sorted(existing)))
nxt = next(("C%03d" % n for n in range(1, 501) if "C%03d" % n not in existing), "none")
print("saved %d; total %d/500; next: %s" % (len(new), len(existing), nxt))
