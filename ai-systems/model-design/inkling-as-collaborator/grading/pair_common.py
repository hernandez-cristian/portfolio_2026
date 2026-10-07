"""Pairwise preference pass: new A/B shuffle, independent of the first blind pass."""
import json, random
from common import HERE, load_prompts, load_runs

PAIR_MAP = HERE / ".pair_map.json"
PAIRS = HERE / "pairs.jsonl"
VERDICTS = ["A>>", "A>", "=", "B>", "B>>"]

def make_map():
    if PAIR_MAP.exists():
        return json.loads(PAIR_MAP.read_text())
    rng = random.Random(20261007)
    m = {"C%03d" % n: rng.choice(["NO_SYSTEM", "WITH_SYSTEM"]) for n in range(1, 501)}
    PAIR_MAP.write_text(json.dumps(m))
    return m

def load_pairs():
    out = {}
    if PAIRS.exists():
        for line in PAIRS.read_text().splitlines():
            if line.strip():
                g = json.loads(line); out[g["id"]] = g
    return out
