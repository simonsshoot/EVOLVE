"""Split the R-Judge benchmark into train/val/test under data/split/Rjudge/.

R-Judge ships as a test-only benchmark (569 official records; 571 in this repo's
copy) with no official split. EVOLVE needs one because rule/tool evolution
consumes misjudgments from the training stream while val/test must stay held
out. Design (see manifest.json for the realized counts):

- Stratify by (domain, label, attack_type) -- the three design axes of the
  benchmark -- via largest-remainder allocation of a 70/10/20 target.
- Exact-duplicate interaction records are kept in the same split (no leakage).
- Deterministic: fixed seed, stable item ordering.
- Records are stored verbatim plus a "category" field carrying the source
  domain, so mixed-domain split files still resolve domain-specific rules
  (data_wrapper already reads data["category"] into rjudge_category).
"""
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "R-Judge"
OUT = ROOT / "data" / "split" / "Rjudge"
DOMAINS = ["Application", "Program", "IoT", "Finance", "Web"]
LABELS = ["benign", "harmful"]
SEED = 44  # matches the pipeline's default --seed
RATIOS = {"train": 0.70, "val": 0.10, "test": 0.20}


def load_items():
    items = []
    for domain in DOMAINS:
        for label in LABELS:
            with open(SRC / domain / f"{label}.json", "r", encoding="utf-8") as f:
                for rec in json.load(f):
                    items.append({
                        "record": rec,
                        "domain": domain,
                        "label": label,  # file-level ground truth (label 0=benign, 1=harmful)
                        "attack": rec.get("attack_type", ""),
                    })
    return items


def dedup_key(item):
    return json.dumps(item["record"].get("contents"), ensure_ascii=False, sort_keys=True)


def largest_remainder(n, ratios=RATIOS):
    """Integer allocation of n items to splits, as close to ratios as possible."""
    exact = {k: n * v for k, v in ratios.items()}
    alloc = {k: int(v) for k, v in exact.items()}
    order = ["train", "val", "test"]
    for _ in range(n - sum(alloc.values())):
        # hand out leftover units to the largest fractional part, ties -> train first
        pick = max(order, key=lambda k: (exact[k] - alloc[k], -order.index(k)))
        alloc[pick] += 1
    return alloc


def main():
    items = load_items()
    print(f"loaded {len(items)} records from {SRC}")

    # Exact-duplicate groups must not straddle splits.
    groups = defaultdict(list)
    for i, it in enumerate(items):
        groups[dedup_key(it)].append(i)
    dup_groups = [g for g in groups.values() if len(g) > 1]

    # Stratified allocation: (domain, label, attack) -> per-split counts.
    strata = defaultdict(list)
    for i, it in enumerate(items):
        strata[(it["domain"], it["label"], it["attack"])].append(i)

    rng = random.Random(SEED)
    assign = {}
    for key in sorted(strata):
        idxs = sorted(strata[key])
        rng.shuffle(idxs)
        alloc = largest_remainder(len(idxs))
        pos = 0
        for split in ("train", "val", "test"):
            for j in range(pos, pos + alloc[split]):
                assign[idxs[j]] = split
            pos += alloc[split]

    # Pull any duplicate group that straddles splits back into the earliest split.
    rank = {"train": 0, "val": 1, "test": 2}
    for g in dup_groups:
        earliest = min((assign[i] for i in g), key=lambda s: rank[s])
        for i in g:
            assign[i] = earliest

    # Write verbatim records + source domain as "category".
    OUT.mkdir(parents=True, exist_ok=True)
    splits = {s: [] for s in RATIOS}
    for i, it in enumerate(items):
        rec = dict(it["record"])
        rec.setdefault("category", it["domain"])
        splits[assign[i]].append(rec)
    for split, recs in splits.items():
        with open(OUT / f"{split}.json", "w", encoding="utf-8") as f:
            json.dump(recs, f, ensure_ascii=False, indent=1)

    # Manifest: realized distribution + provenance.
    def dist(recs):
        c = Counter((r["category"], "benign" if str(r.get("label")) == "0" else "harmful",
                     r.get("attack_type", "")) for r in recs)
        return {f"{k[0]}/{k[1]}/{k[2]}": v for k, v in sorted(c.items())}

    manifest = {
        "source": "data/R-Judge (arXiv 2401.10019, EMNLP Findings 2024; test-only benchmark, no official split)",
        "seed": SEED,
        "ratios": RATIOS,
        "stratify_by": ["domain", "label", "attack_type"],
        "total": len(items),
        "counts": {s: len(r) for s, r in splits.items()},
        "distribution": {s: dist(r) for s, r in splits.items()},
        "duplicate_groups_kept_together": len(dup_groups),
        "notes": [
            "label field in records: 0=benign/safe, 1=harmful/unsafe (R-Judge convention)",
            "records stored verbatim; 'category' added = source domain (Application/Program/IoT/Finance/Web)",
            "shared user-instruction templates across records are the benchmark's design "
            "(same instruction, different agent behavior/label) and are NOT grouped",
        ],
    }
    with open(OUT / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    print(json.dumps(manifest["counts"]))
    for s in ("train", "val", "test"):
        lab = Counter("benign" if str(r.get("label")) == "0" else "harmful" for r in splits[s])
        dom = Counter(r["category"] for r in splits[s])
        print(f"{s:>5}: {len(splits[s]):>3}  " +
              " ".join(f"{d}={dom[d]}" for d in DOMAINS) +
              f"  benign={lab['benign']} harmful={lab['harmful']}")


if __name__ == "__main__":
    main()
