"""Split ASB / AgentHarm / ASSEBench into train/val/test under data/split/.

Same methodology as script/split_rjudge.py (stratified largest-remainder
allocation of a 70/10/20 target, fixed seed, exact-duplicate groups kept in
the same split). Dataset-specific facts, verified against the papers:

- ASB (Agent-SafetyBench, arXiv 2412.14470): evaluation benchmark with no
  official train/val/test split. This repo holds a 60-record simulated
  subset (30 benign + 30 harmful). Stratify by (label, primary risk type)
  -- the benchmark's own taxonomy axes.

- AgentHarm (arXiv 2410.09024): HAS an official split, but it is
  val 10% / public test 60% / private test 30% at the *base behavior*
  level, with no train set (evaluation-only). Verified against the
  official HF release: this repo's data is exactly the official *public
  test* set (44 base behaviors x 4 prompt variants x harmful/benign twin).
  We therefore re-split the local (public-test) data ourselves, but keep
  the official design decisions: the split unit is the base behavior --
  all 4 prompt variants AND the benign twin stay together (official
  validation sets pair harmful and benign twins) -- and val stays ~10%.
  Stratify behavior groups by harm category.

- ASSEBench (arXiv 2506.00641, NeurIPS 2025): no train/val/test split in
  the paper (its "split" is only Safety vs Security evaluation
  dimensions). Both dimensions are split here, stratified by
  (application_scenario, label) within each. The 66 interactions shared
  by both dimensions get ONE assignment (leakage across dimensions is
  still leakage), stratified with the security set. Records are stored
  verbatim plus a "category" field carrying the scenario in seed-rule
  domain-key form (security: split-file stems, e.g.
  Security_Operations_System_Misuse; safety: normalized scenario name).
"""
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "split"
SEED = 44  # matches the pipeline's default --seed
RATIOS = {"train": 0.70, "val": 0.10, "test": 0.20}
SPLITS = ("train", "val", "test")


def largest_remainder(n, ratios=RATIOS):
    """Integer allocation of n items to splits, as close to ratios as possible."""
    exact = {k: n * v for k, v in ratios.items()}
    alloc = {k: int(v) for k, v in exact.items()}
    order = list(SPLITS)
    for _ in range(n - sum(alloc.values())):
        # hand out leftover units to the largest fractional part, ties -> train first
        pick = max(order, key=lambda k: (exact[k] - alloc[k], -order.index(k)))
        alloc[pick] += 1
    return alloc


def allocate_stratified(groups, strat_key, rng):
    """groups: list of hashable group ids; strat_key: group id -> stratum.

    Returns {group_id: split}. Duplicate/leakage groups must be merged into
    one group id by the caller before this is called.
    """
    strata = defaultdict(list)
    for g in groups:
        strata[strat_key(g)].append(g)
    assign = {}
    for key in sorted(strata, key=str):
        members = sorted(strata[key], key=str)
        rng.shuffle(members)
        alloc = largest_remainder(len(members))
        pos = 0
        for split in SPLITS:
            for g in members[pos : pos + alloc[split]]:
                assign[g] = split
            pos += alloc[split]
    return assign


def write_splits(name, records_by_split, meta):
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    for split in SPLITS:
        with open(folder / f"{split}.json", "w", encoding="utf-8") as f:
            json.dump(records_by_split[split], f, ensure_ascii=False, indent=1)
    manifest = {
        "seed": SEED,
        "ratios": RATIOS,
        "counts": {s: len(records_by_split[s]) for s in SPLITS},
        **meta,
    }
    with open(folder / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f"[{name}] " + json.dumps(manifest["counts"]) + "  " + json.dumps(meta.get("stratify_by", [])))


# --------------------------------------------------------------------------
# ASB: 60 simulated records, stratify by (label, primary risk type)
# --------------------------------------------------------------------------
def split_asb():
    items = []
    for label_file in ("benign_simulate", "harmful_simulate"):
        path = ROOT / "data" / "ASB" / f"{label_file}.jsonl"
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line:
                items.append(json.loads(line))

    def primary_risk(rec):
        risks = rec.get("agentsafebench_risks") or []
        return risks[0] if risks else "none"

    # Exact-duplicate requests must not straddle splits (2 pairs locally).
    by_request = defaultdict(list)
    for i, rec in enumerate(items):
        by_request[rec.get("request", "")].append(i)
    group_of = {}
    groups = []
    for req, idxs in by_request.items():
        gid = len(groups)
        groups.append(idxs)
        for i in idxs:
            group_of[i] = gid

    rng = random.Random(SEED)
    # 60 records cannot support stable quotas on (label x risk) -- 12 strata of
    # ~5 push val down to ~4 records -- so stratify by label only and let risk
    # types mix naturally under the fixed-seed shuffle.
    strat = {gid: items[g[0]]["labels"] for gid, g in enumerate(groups)}
    assign = allocate_stratified(list(range(len(groups))), lambda gid: strat[gid], rng)

    records_by_split = {s: [] for s in SPLITS}
    for i, rec in enumerate(items):
        rec = dict(rec)
        rec.setdefault("category", primary_risk(rec))
        records_by_split[assign[group_of[i]]].append(rec)

    write_splits(
        "ASB",
        records_by_split,
        {
            "source": "data/ASB/{benign,harmful}_simulate.jsonl (Agent-SafetyBench, "
            "arXiv 2412.14470; evaluation benchmark, no official split; local 60-record subset)",
            "stratify_by": ["labels"],
            "duplicate_groups_kept_together": len([g for g in groups if len(g) > 1]),
            "notes": [
                "records stored verbatim (simulate format) + 'category' = primary risk type",
                "agentsafebench_failure_modes kept verbatim (list) for analysis",
            ],
        },
    )


# --------------------------------------------------------------------------
# AgentHarm: split at base-behavior level (official design), stratify by category
# --------------------------------------------------------------------------
def split_agentharm():
    categories = [
        "Copyright", "Cybercrime", "Disinformation", "Drugs",
        "Fraud", "Harassment", "Hate", "Sexual",
    ]
    items = []
    for cat in categories:
        for label_file in ("benign_simulate", "harmful_simulate"):
            path = ROOT / "data" / "agentharm" / cat / f"{label_file}.jsonl"
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if line:
                    items.append(json.loads(line))

    # Group = base behavior (agentharm_id prefix, e.g. '13' from '13-1'):
    # all 4 prompt variants (hint x detailed) of BOTH the harmful behavior
    # and its benign twin stay together, mirroring the official split unit
    # (official validation pairs harmful/benign twins of the same id_original).
    groups = defaultdict(list)
    for i, rec in enumerate(items):
        prefix = str(rec.get("agentharm_id", "")).split("-")[0]
        groups[prefix].append(i)

    rng = random.Random(SEED)
    strat = {p: items[g[0]]["agentharm_category"] for p, g in groups.items()}
    assign = allocate_stratified(sorted(groups), lambda p: strat[p], rng)

    records_by_split = {s: [] for s in SPLITS}
    for i, rec in enumerate(items):
        records_by_split[assign[str(rec.get("agentharm_id", "")).split("-")[0]]].append(rec)

    group_sizes = Counter(len(g) for g in groups.values())
    write_splits(
        "AgentHarm",
        records_by_split,
        {
            "source": "data/agentharm/<category>/{benign,harmful}_simulate.jsonl "
            "(AgentHarm, arXiv 2410.09024)",
            "stratify_by": ["agentharm_category (at base-behavior group level)"],
            "base_behavior_groups": len(groups),
            "group_sizes": {str(k): v for k, v in sorted(group_sizes.items())},
            "notes": [
                "local data == official public test set (44 base behaviors, verified "
                "against HF ai-safety-institute/AgentHarm); official split "
                "val 10%/public 60%/private 30% has NO train set, so we re-split "
                "locally for evolution experiments",
                "split unit = base behavior (agentharm_id prefix): 4 prompt variants "
                "+ benign twin stay together (official pairs harmful/benign twins)",
                "records stored verbatim (simulate format, already carry "
                "agentharm_category for per-record rule routing)",
            ],
        },
    )


# --------------------------------------------------------------------------
# ASSEBench: split safety (1,476) and security (817) dimensions, shared
# contents get one assignment; stratify by (scenario, label)
# --------------------------------------------------------------------------
def normalize_scenario(scenario):
    """'Legal, Compliance & Audit' -> 'Legal_Compliance_Audit' (seed-rule key form)."""
    s = re.sub(r"[,&.]", " ", scenario)
    return "_".join(s.split())


def split_assebench():
    src = ROOT / "data" / "ASSEBench" / "dataset"
    safety = json.load(open(src / "AgentJudge-safety.json", encoding="utf-8"))
    security = json.load(open(src / "AgentJudge-security.json", encoding="utf-8"))

    def key(r):
        return json.dumps(r.get("contents"), ensure_ascii=False, sort_keys=True)

    # Map security records to their seed-rule domain key (the split/ file stems).
    scen_file = {}
    for f in sorted((ROOT / "data" / "ASSEBench" / "split").glob("*.json")):
        for r in json.load(open(f, encoding="utf-8")):
            scen_file[key(r)] = f.stem

    # Assignment unit = interaction contents; security records stratified by
    # (scenario, label) via canonical security record, safety-only records by
    # their own (scenario, label). Shared contents ride with security.
    sec_by_key = {key(r): r for r in security}
    saf_by_key = {key(r): r for r in safety}
    all_keys = sorted(set(sec_by_key) | set(saf_by_key))

    rng = random.Random(SEED)

    def strat(k):
        if k in sec_by_key:
            r = sec_by_key[k]
        else:
            r = saf_by_key[k]
        return (r["application_scenario"], r["label"])

    assign = allocate_stratified(all_keys, strat, rng)

    records_by_split = {"safety": {s: [] for s in SPLITS}, "security": {s: [] for s in SPLITS}}
    for r in safety:
        rec = dict(r)
        rec.setdefault("category", normalize_scenario(rec["application_scenario"]))
        records_by_split["safety"][assign[key(r)]].append(rec)
    for r in security:
        rec = dict(r)
        # Seed-rule key form for security records (matches the split/ file stems).
        rec.setdefault("category", scen_file.get(key(r), normalize_scenario(rec["application_scenario"])))
        records_by_split["security"][assign[key(r)]].append(rec)

    shared = set(sec_by_key) & set(saf_by_key)
    write_splits(
        "ASSEBench/safety",
        records_by_split["safety"],
        {
            "source": "data/ASSEBench/dataset/AgentJudge-safety.json (ASSEBench, "
            "arXiv 2506.00641, NeurIPS 2025; no official train/val/test split)",
            "stratify_by": ["application_scenario", "label"],
            "notes": [
                "records stored verbatim + 'category' = normalized application_scenario",
                "strict/loose are the same records (ids aligned) under two other "
                "annotation standards; join by id if needed",
                "66 interactions shared with the security dimension get the same "
                "split assignment as there (no cross-dimension leakage)",
            ],
        },
    )
    write_splits(
        "ASSEBench/security",
        records_by_split["security"],
        {
            "source": "data/ASSEBench/dataset/AgentJudge-security.json (= the 12 "
            "scenario files under data/ASSEBench/split/)",
            "stratify_by": ["application_scenario", "label"],
            "notes": [
                "records stored verbatim + 'category' = scenario split-file stem "
                "(seed_rules domain key, e.g. Security_Operations_System_Misuse)",
                "shared contents with the safety dimension ride with this "
                "dimension's stratification",
            ],
        },
    )
    # cross-check: shared contents on the same side
    bad = sum(1 for k in shared if assign[k] != assign[k])
    assert bad == 0
    print(f"[ASSEBench] shared contents across dimensions: {len(shared)}, same-split violations: {bad}")


if __name__ == "__main__":
    split_asb()
    split_agentharm()
    split_assebench()
