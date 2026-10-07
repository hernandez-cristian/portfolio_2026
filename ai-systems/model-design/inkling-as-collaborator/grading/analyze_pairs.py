"""Unblind the pairwise pass and summarize it. Writes pair_results.json."""
import json
from collections import Counter, defaultdict
from common import HERE, ABBR, load_prompts, load_runs
from pair_common import make_map, load_pairs

prompts = load_prompts()
runs = load_runs()
pmap = make_map()                      # id -> run shown as A
pairs = load_pairs()
bmap = json.loads((HERE / ".blind_map.json").read_text())
grades = {}
for line in (HERE / "grades.jsonl").read_text().splitlines():
    if line.strip():
        g = json.loads(line); grades[g["id"]] = g

W, N = "WITH_SYSTEM", "NO_SYSTEM"
other = {W: N, N: W}

def words(run, pid):
    return len((runs[run][pid].get("model_response") or "").split())

rows = []
for pid, p in sorted(pairs.items()):
    a_run = pmap[pid]; b_run = other[a_run]
    v = p["v"]
    if v == "=":
        winner, strength = None, 0
    else:
        winner = a_run if v.startswith("A") else b_run
        strength = 2 if v.endswith(">>") else 1
    # first-pass totals (blind map: A in grades = bmap[pid])
    g = grades[pid]
    ga_run = bmap[pid]
    tot = {ga_run: sum(g["A"]["s"].values()), other[ga_run]: sum(g["B"]["s"].values())}
    fp = None if tot[W] == tot[N] else (W if tot[W] > tot[N] else N)
    pr = prompts[pid]
    rows.append(dict(id=pid, cat=pr["category"], prim=FULL if False else pr["primary_trait"],
                     v=v, pos=("A" if v.startswith("A") else "B" if v.startswith("B") else "="),
                     winner=winner, strength=strength, d=p.get("d", []), r=p["r"],
                     fp=fp, wW=words(W, pid), wN=words(N, pid)))

def tally(rs):
    c = Counter()
    for r in rs:
        if r["winner"] is None: c["tie"] += 1
        else: c[(r["winner"], r["strength"])] += 1
    w = c[(W, 1)] + c[(W, 2)]; n = c[(N, 1)] + c[(N, 2)]
    return dict(n=len(rs), with_wins=w, no_wins=n, ties=c["tie"],
                with_strong=c[(W, 2)], no_strong=c[(N, 2)],
                with_rate=round(w / len(rs), 3) if rs else 0,
                no_rate=round(n / len(rs), 3) if rs else 0,
                net=w - n)

out = {"overall": tally(rows)}

# position bias
pos = Counter(r["pos"] for r in rows)
out["position"] = dict(A=pos["A"], B=pos["B"], tie=pos["="],
                       a_shown_with=sum(1 for r in rows if pmap[r["id"]] == W))

# by category / primary trait
bycat = defaultdict(list); byprim = defaultdict(list)
for r in rows:
    bycat[r["cat"]].append(r); byprim[r["prim"]].append(r)
out["by_category"] = {k: tally(v) for k, v in sorted(bycat.items(), key=lambda kv: -len(kv[1]))}
out["by_primary"] = {k: tally(v) for k, v in sorted(byprim.items())}

# deciding traits by winner
dec = {W: Counter(), N: Counter()}
for r in rows:
    if r["winner"]:
        for t in r["d"]:
            dec[r["winner"]][t] += 1
out["deciding"] = {k: dict(v.most_common()) for k, v in dec.items()}

# agreement with first pass
both = [r for r in rows if r["winner"] and r["fp"]]
agree = sum(1 for r in both if r["winner"] == r["fp"])
fp_diff = [r for r in rows if r["fp"]]
out["agreement"] = dict(
    first_pass_differed=len(fp_diff),
    pairwise_tie_where_fp_differed=sum(1 for r in fp_diff if r["winner"] is None),
    both_decided=len(both), agree=agree,
    agree_rate=round(agree / len(both), 3) if both else None,
    pairwise_decided_where_fp_tied=sum(1 for r in rows if r["winner"] and not r["fp"]),
)

# length of winner vs loser
lw = [r for r in rows if r["winner"]]
longer_won = sum(1 for r in lw if (r["wW"] if r["winner"] == W else r["wN"]) > (r["wN"] if r["winner"] == W else r["wW"]))
out["length"] = dict(decided=len(lw), longer_won=longer_won,
                     shorter_won=len(lw) - longer_won)

# strong wins list
out["strong"] = [dict(id=r["id"], cat=r["cat"], winner=r["winner"], r=r["r"]) for r in rows if r["strength"] == 2]

(HERE / "pair_results.json").write_text(json.dumps(out, indent=1))
(HERE / "pair_rows.json").write_text(json.dumps(rows, indent=1))
print(json.dumps({k: out[k] for k in ["overall", "position", "agreement", "length", "deciding"]}, indent=1))
print("\nBY CATEGORY")
for k, v in out["by_category"].items():
    print(f"  {k:28s} n={v['n']:3d}  WITH {v['with_wins']:3d}  NO {v['no_wins']:3d}  tie {v['ties']:3d}  net {v['net']:+d}")
print("\nBY PRIMARY TRAIT")
for k, v in out["by_primary"].items():
    print(f"  {k:24s} n={v['n']:3d}  WITH {v['with_wins']:3d}  NO {v['no_wins']:3d}  tie {v['ties']:3d}  net {v['net']:+d}")
print("\nSTRONG")
for s in out["strong"]:
    print(" ", s["id"], s["cat"], s["winner"], "|", s["r"][:110])
