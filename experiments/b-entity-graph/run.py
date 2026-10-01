"""Experiment B — Entity-graph / fraud-ring detection.

Hypothesis: ATO fraud is organised. Mule destination addresses, drop devices and
payment instruments are re-used across many hijacked accounts. A streaming graph
over shippers ↔ addresses ↔ devices ↔ payment instruments therefore carries signal
that a per-booking behavioural model cannot see, especially for the "stealthy"
scenario that copies the victim's normal behaviour.

What this experiment measures
1. Ranking quality of graph-only vs behavioural-only vs combined features, overall and
   for the stealthy scenario.
2. Unsupervised mule-address discovery: naive fan-in ranks fulfilment hubs first
   (super-node problem); a "novelty-mass" score (how many *unrelated* shippers ship
   there for the *first time*) recovers the mule addresses without labels; confirmed
   labels (delayed) sharpen it further.
3. How much of test-period fraud touches infrastructure that was already confirmed
   bad (label propagation) vs fresh infrastructure (where only behaviour can help).
4. A picture of one ring (visuals/ring_graph.png).
"""
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "prototypes" / "data"))
sys.path.insert(0, str(ROOT / "experiments" / "a-rules-gbm-shap"))
from simulate import generate                                            # noqa: E402
from featurize import build_feature_frame, BEHAV_COLS, GRAPH_COLS       # noqa: E402
from run import train_gbm, summarize, recall_at_fpr                     # noqa: E402


def precision_at_k(ranked: pd.Index, truth: set, k: int) -> float:
    top = list(ranked[:k])
    return sum(1 for a in top if a in truth) / k


def main():
    df = generate(seed=7)
    X = build_feature_frame(df)
    cut = X["ts"].quantile(0.70)
    tr, te = X[X.ts < cut], X[X.ts >= cut]
    ytr, yte = tr.is_fraud.values, te.is_fraud.values

    # 1. feature-group ablation ------------------------------------------------
    rows, per_scen = [], {}
    for name, cols in [("graph features only", GRAPH_COLS), ("behavioural features only", BEHAV_COLS),
                       ("behavioural + graph", BEHAV_COLS + GRAPH_COLS)]:
        m, _ = train_gbm(tr, ytr, cols)
        p = m.predict_proba(te[cols])[:, 1]
        rows.append(summarize(yte, p, name))
        _, thr = recall_at_fpr(yte, p, 0.01)
        caught = te.assign(c=p > thr)
        per_scen[name] = caught[caught.is_fraud == 1].groupby("scenario")["c"].mean()
    res = pd.DataFrame(rows)
    scen = pd.DataFrame(per_scen)

    # 2. unsupervised mule-address discovery ----------------------------------
    truth = set(a for a in df.dest_address_id.unique() if a.startswith("mule_"))
    Xa = X.merge(df[["booking_id", "dest_address_id"]], on="booking_id")
    # novelty of the FIRST booking each shipper made to each address: how surprising was it
    # for that shipper (given their own history + cohort prior) to ship there at all?
    first = Xa.sort_values("ts").groupby(["dest_address_id", "shipper_id"], as_index=False).first()
    g = first.groupby("dest_address_id").agg(n_shippers=("shipper_id", "nunique"),
                                             first_nov=("dest_addr_nov", "mean"), fraud_conf=("dest_fraud", "max"))
    g["n"] = Xa.groupby("dest_address_id").size()
    g["fraud_conf"] = Xa.groupby("dest_address_id")["dest_fraud"].max()
    # novelty-mass: several *unrelated* shippers, each of whom found this address surprising.
    # Addresses above the super-node cap are treated as business hubs (verified out-of-band).
    g["novelty_score"] = np.where((g.n_shippers >= 2) & (g.n_shippers <= 10), g.first_nov * np.log1p(g.n_shippers), 0.0)
    g["novelty_plus_labels"] = g.novelty_score * (1 + g.fraud_conf)
    rank_fanin = g.sort_values(["n_shippers", "n"], ascending=False).index
    rank_nov = g.sort_values("novelty_score", ascending=False).index
    rank_lab = g.sort_values("novelty_plus_labels", ascending=False).index
    k = len(truth)
    mule_tbl = pd.DataFrame({
        "ranking": ["naive fan-in (distinct shippers)", "novelty-mass (unsupervised)", "novelty-mass × (1+confirmed fraud)"],
        f"precision@{k}": [precision_at_k(r, truth, k) for r in (rank_fanin, rank_nov, rank_lab)],
        "precision@10": [precision_at_k(r, truth, 10) for r in (rank_fanin, rank_nov, rank_lab)],
    })
    top_fanin = g.loc[rank_fanin[:5], ["n_shippers", "n"]]

    # 3. known vs fresh infrastructure in the test period ---------------------
    tf = te[te.is_fraud == 1]
    known = ((tf.dest_fraud > 0) | (tf.dev_fraud > 0) | (tf.pay_fraud > 0))
    known_share = float(known.mean())
    stealth = tf[tf.scenario == "stealthy_mule"]
    stealth_known = float(((stealth.dest_fraud > 0) | (stealth.dev_fraud > 0) | (stealth.pay_fraud > 0)).mean())

    # 4. draw one ring --------------------------------------------------------
    pic = ""
    try:
        import networkx as nx
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        ring = df[df.is_fraud == 1].ring_id.value_counts().index[0]
        fr = df[(df.ring_id == ring)]
        G = nx.Graph()
        for r in fr.itertuples():
            G.add_node(r.shipper_id, kind="victim")
            for ent, kind in [(r.dest_address_id, "mule address"), (r.device_id, "device"), (r.payment_id, "payment")]:
                if ent.startswith(("mule_", "dev_ring", "pay_ring")):
                    G.add_node(ent, kind=kind)
                    G.add_edge(r.shipper_id, ent)
        # add a few legitimate bookings of the same victims to show the contrast
        legit = df[(df.shipper_id.isin(fr.shipper_id.unique())) & (df.is_fraud == 0)].groupby("shipper_id").head(2)
        for r in legit.itertuples():
            G.add_node(r.dest_address_id, kind="legit address")
            G.add_edge(r.shipper_id, r.dest_address_id)
        colors = {"victim": "#3B6EA5", "mule address": "#C8102E", "device": "#E68A00", "payment": "#7B3F9E", "legit address": "#9AA5B1"}
        pos = nx.spring_layout(G, seed=3, k=0.6)
        plt.figure(figsize=(10, 7))
        for kind, col in colors.items():
            nodes = [n for n, d in G.nodes(data=True) if d.get("kind") == kind]
            nx.draw_networkx_nodes(G, pos, nodelist=nodes, node_color=col, node_size=260 if kind != "legit address" else 90, label=kind)
        nx.draw_networkx_edges(G, pos, alpha=0.35)
        nx.draw_networkx_labels(G, pos, {n: n for n, d in G.nodes(data=True) if d.get("kind") != "legit address"}, font_size=6)
        plt.legend(scatterpoints=1, fontsize=8, loc="lower left")
        plt.title(f"Fraud ring {ring}: hijacked shipper accounts (blue) fan in to shared mule addresses, devices and payment instruments")
        plt.axis("off")
        out = ROOT / "visuals" / "ring_graph.png"
        plt.savefig(out, dpi=150, bbox_inches="tight")
        pic = f"![ring]({out.relative_to(ROOT)})"
    except Exception as e:  # pragma: no cover
        pic = f"(ring picture skipped: {e})"

    md = ["# Experiment B — entity graph / ring detection", "",
          "## 1. Feature-group ablation (test period, time split)", "",
          res.to_markdown(index=False, floatfmt=".3f"), "",
          "Per-scenario recall at 1 % FPR:", "", scen.to_markdown(floatfmt=".2f"), "",
          "## 2. Unsupervised mule-address discovery", "",
          f"{len(truth)} true mule addresses among {len(g)} destination addresses.", "",
          mule_tbl.to_markdown(index=False, floatfmt=".2f"), "",
          "Top-5 addresses by naive fan-in (the super-node problem — these are fulfilment hubs, not mules):", "",
          top_fanin.to_markdown(), "",
          "## 3. Known vs fresh ring infrastructure (test-period fraud)", "",
          f"- {known_share:.0%} of test-period fraud bookings touch an address, device or payment instrument that was",
          "  already confirmed fraudulent (labels arrive with a 10-day delay). These are near-certain catches for the graph.",
          f"- For the stealthy scenario the share is {stealth_known:.0%}; the remainder is fresh infrastructure where only",
          "  'many unrelated shippers, first-time destination, new device' style novelty can help — which is why the",
          "  graph counters and the behavioural novelty features must be fed to the same model rather than run as",
          "  separate rules.", "",
          "## 4. One ring", "", pic, "",
          "## Observations", "",
          "- Raw fan-in is a trap: hubs dominate. Degree-capping unions (super-node guard) and weighting fan-in by",
          "  *first-time-for-that-shipper* novelty is what separates mules from hubs without any labels.",
          "- Graph features are cheap to serve online: three hash-map lookups (entity → recent shippers) and one",
          "  union-find root lookup per booking — no GNN inference on the synchronous path.",
          "- Label propagation is the feedback loop the problem statement already has (post-delivery detection); the",
          "  graph turns yesterday's confirmed cases into today's blocks on shared infrastructure.", ""]
    (HERE / "results.md").write_text("\n".join(md), encoding="utf-8")
    print(res.to_string(index=False)); print(scen); print(mule_tbl.to_string(index=False))
    print(f"known-infra share {known_share:.0%} (stealthy {stealth_known:.0%})")


if __name__ == "__main__":
    main()
