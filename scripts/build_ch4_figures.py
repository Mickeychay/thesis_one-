"""Regenerate the Chapter 4 evidence figures with a Thai-capable font.

Every number is read from a result file at run time; nothing is hard-coded.
Any missing-glyph warning from matplotlib is promoted to an error, so a run
that completes is proof that all Thai labels rendered.

Sources
  fig 4.A  evaluation_results/derived/retrieval_metrics_20260807_per_case.csv
  fig 4.B  evaluation_results/derived/retrieval_significance_20260807.csv
  fig 4.C  evaluation_results/adversarial_stress_test_20260807.md
  fig 4.D  ablation_results/rq6_95cases_20260809/rq6_results.csv

Usage:  python scripts/build_ch4_figures.py
"""

import csv
import re
import statistics as st
import sys
import warnings
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "figures_ch4"

# Turn "Glyph N missing from font(s)" into a hard failure.
warnings.filterwarnings("error", message=r".*missing from font.*")

THAI_FONT_PREFERENCE = ("Sarabun", "Ayuthaya", "Thonburi", "Krungthep", "Tahoma")


def pick_thai_font() -> str:
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in THAI_FONT_PREFERENCE:
        if name in available:
            return name
    sys.exit(
        "No Thai-capable font found. Tried: "
        + ", ".join(THAI_FONT_PREFERENCE)
    )


def read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        sys.exit(f"missing required input: {path}")
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------------------
# fig 4.A  per-case paired difference, h2l-hybrid minus basic, nDCG@5
# --------------------------------------------------------------------------
def fig_4a() -> str:
    rows = read_csv(
        ROOT / "evaluation_results/derived/retrieval_metrics_20260807_per_case.csv"
    )
    bucket = defaultdict(list)
    for r in rows:
        if r.get("model") != "qwen2.5:7b":
            continue
        if r.get("strategy") not in ("h2l-hybrid", "basic"):
            continue
        v = r.get("nDCG@5")
        if v in (None, ""):
            continue
        bucket[(r["case_id"], r["strategy"])].append(float(v))

    diffs = []
    for cid in sorted({c for c, _ in bucket}):
        hi = bucket.get((cid, "h2l-hybrid"))
        lo = bucket.get((cid, "basic"))
        if hi and lo:
            diffs.append(st.mean(hi) - st.mean(lo))
    diffs.sort()

    pos = sum(1 for d in diffs if d > 1e-9)
    neg = sum(1 for d in diffs if d < -1e-9)
    zero = len(diffs) - pos - neg
    mean_d = st.mean(diffs)

    fig, ax = plt.subplots(figsize=(12, 5))
    colors = [
        "#e74c3c" if d < -1e-9 else "#bdc3c7" if abs(d) <= 1e-9 else "#2ecc71"
        for d in diffs
    ]
    ax.bar(range(len(diffs)), diffs, color=colors, width=1.0, edgecolor="none")
    ax.axhline(0, color="black", lw=0.8)
    ax.axhline(
        mean_d,
        color="#2980b9",
        lw=1.5,
        ls="--",
        label=f"ค่าเฉลี่ยผลต่าง = {mean_d:+.4f}",
    )
    ax.set_xlabel(f"กรณีศึกษา ({len(diffs)} เคส เรียงตามขนาดผลต่าง)", fontsize=11)
    ax.set_ylabel("nDCG@5 : h2l-hybrid ลบ basic", fontsize=11)
    ax.set_title(
        f"รูปที่ 4.A ผลต่าง nDCG@5 รายกรณีศึกษา (n={len(diffs)})\n"
        f"ดีขึ้น {pos} เคส · เท่าเดิม {zero} เคส · แย่ลง {neg} เคส · "
        f"ค่ามัธยฐาน = {st.median(diffs):+.4f}",
        fontsize=12,
    )
    ax.legend(fontsize=10)
    ax.set_xlim(-1, len(diffs))
    fig.tight_layout()
    fig.savefig(OUT / "fig_4a_paired_diff.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    return f"4.A n={len(diffs)} +{pos}/={zero}/-{neg} mean={mean_d:+.4f}"


# --------------------------------------------------------------------------
# fig 4.B  forest plot of the nDCG@5 pairwise comparisons
# --------------------------------------------------------------------------
def fig_4b() -> str:
    rows = [
        r
        for r in read_csv(
            ROOT / "evaluation_results/derived/retrieval_significance_20260807.csv"
        )
        if r["metric"] == "nDCG@5"
    ]
    rows.sort(key=lambda r: float(r["rank_biserial"]), reverse=True)

    fig, ax = plt.subplots(figsize=(10, 5))
    n_sig = 0
    for i, r in enumerate(rows):
        rb = float(r["rank_biserial"])
        hp = float(r["holm_p"])
        md = float(r["mean_difference"])
        nz = int(r["n_nonzero_differences"])
        sig = hp <= 0.05
        n_sig += sig
        ax.barh(
            i,
            rb,
            height=0.6,
            color="#2ecc71" if sig else "#e67e22",
            edgecolor="white",
        )
        star = "*" if sig else ""
        ax.text(
            rb + 0.02,
            i,
            f"ผลต่าง={md:+.4f}  Holm p={hp:.3f}{star}  เคสที่ต่าง={nz}",
            va="center",
            fontsize=8.5,
        )
    ax.axvline(0, color="black", lw=0.8)
    ax.axvline(0.5, color="#7f8c8d", lw=1, ls=":", alpha=0.6)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r["comparison"] for r in rows], fontsize=10)
    ax.set_xlabel("Rank-Biserial Correlation (ขนาดอิทธิพล)", fontsize=11)
    ax.set_title(
        f"รูปที่ 4.B การทดสอบนัยสำคัญแบบคู่ nDCG@5 เทียบกับ h2l-hybrid\n"
        f"ผ่านการปรับ Holm {n_sig} จาก {len(rows)} คู่",
        fontsize=11,
    )
    ax.legend(
        handles=[
            mpatches.Patch(color="#2ecc71", label="มีนัยสำคัญ (Holm p ≤ 0.05)"),
            mpatches.Patch(color="#e67e22", label="ไม่มีนัยสำคัญ"),
        ],
        fontsize=9,
    )
    ax.set_xlim(-0.1, 1.15)
    fig.tight_layout()
    fig.savefig(OUT / "fig_4b_forest_plot.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    return f"4.B pairs={len(rows)} significant={n_sig}"


# --------------------------------------------------------------------------
# fig 4.C  adversarial slice: target recall vs false-trigger suppression
# --------------------------------------------------------------------------
def fig_4c() -> str:
    src = ROOT / "evaluation_results/adversarial_stress_test_20260807.md"
    if not src.is_file():
        sys.exit(f"missing required input: {src}")
    text = src.read_text(encoding="utf-8")
    pat = re.compile(
        r"\| (ADV_\d+) \| [\w\-\.]+ \| [\w\-\.]+ \| \S+ \| (\S+) \| (\S+) \| (\S+) \|"
    )
    adv = [
        {
            "case": m.group(1),
            "recall": float(m.group(2)),
            "supp": float(m.group(3)),
            "joint": float(m.group(4)),
        }
        for m in pat.finditer(text)
    ]
    if not adv:
        sys.exit("parsed zero adversarial rows -- table format changed?")

    xs = [r["recall"] for r in adv]
    ys = [r["supp"] for r in adv]
    n_pass = sum(1 for r in adv if r["joint"] >= 1.0)

    fig, ax = plt.subplots(figsize=(9, 7))
    colors = [
        "#2ecc71"
        if r["joint"] >= 1.0
        else "#3498db"
        if r["recall"] >= 1.0
        else "#e74c3c"
        for r in adv
    ]
    ax.scatter(
        xs, ys, c=colors, s=130, alpha=0.85, edgecolors="white", lw=0.7, zorder=3
    )
    for r in adv:
        ax.annotate(
            r["case"].replace("ADV_", ""),
            (r["recall"], r["supp"]),
            textcoords="offset points",
            xytext=(4, 3),
            fontsize=7.5,
            color="#444",
        )
    ax.axhline(1.0, color="#27ae60", lw=0.8, ls=":", alpha=0.5)
    ax.axvline(1.0, color="#27ae60", lw=0.8, ls=":", alpha=0.5)
    ax.set_xlabel("Target Recall (ตรวจจับรหัสเป้าหมายได้ครบ)", fontsize=11)
    ax.set_ylabel("False-Trigger Suppression (ระงับรหัสลวงได้)", fontsize=11)
    ax.set_title(
        f"รูปที่ 4.C ชุดกรณีศึกษาท้าทาย: การตรวจจับเทียบกับการระงับรหัสลวง "
        f"(n={len(adv)})\n"
        f"เขียว = ผ่านทั้งสองเกณฑ์ ({n_pass}/{len(adv)}) · "
        f"น้ำเงิน = ตรวจจับผ่านแต่ระงับไม่ผ่าน · แดง = ตรวจจับไม่ผ่าน",
        fontsize=11,
    )
    ax.grid(True, alpha=0.3)
    ax.set_xlim(-0.1, 1.15)
    ax.set_ylim(-0.1, 1.15)
    ax.text(
        0.02,
        0.97,
        f"ผ่านทั้งสองเกณฑ์: {n_pass}/{len(adv)}\n"
        f"Recall เฉลี่ย: {st.mean(xs):.3f}\n"
        f"Suppression เฉลี่ย: {st.mean(ys):.3f}",
        transform=ax.transAxes,
        fontsize=9,
        va="top",
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.85),
    )
    fig.tight_layout()
    fig.savefig(OUT / "fig_4c_adversarial.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    return f"4.C parsed={len(adv)} joint_pass={n_pass}"


# --------------------------------------------------------------------------
# fig 4.D  score-vs-rank decoupling, from the 95-case RQ6 run
# --------------------------------------------------------------------------
def fig_4d() -> str:
    rows = read_csv(ROOT / "ablation_results/rq6_95cases_20260809/rq6_results.csv")
    agg = defaultdict(lambda: {"ndcg": [], "delta": []})
    for r in rows:
        v = r["variant"]
        agg[v]["ndcg"].append(float(r["nDCG@5"]))
        agg[v]["delta"].append(float(r["mean_abs_score_delta"]))

    order = ["Full V6"] + sorted(v for v in agg if v != "Full V6")
    ndcg = [st.mean(agg[v]["ndcg"]) for v in order]
    delta = [st.mean(agg[v]["delta"]) for v in order]

    labels = [v.replace("w/o ", "ไม่มี\n").replace(" ", "\n") for v in order]

    fig, ax1 = plt.subplots(figsize=(12, 5.5))
    x = np.arange(len(order))
    w = 0.38
    ax1.bar(x - w / 2, ndcg, w, color="#2980b9", alpha=0.85, label="nDCG@5 (แกนซ้าย)")
    ax1.set_ylabel("nDCG@5", color="#2980b9", fontsize=11)
    ax1.tick_params(axis="y", labelcolor="#2980b9")
    ax1.set_ylim(0, max(ndcg) * 1.6)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=8)

    ax2 = ax1.twinx()
    ax2.bar(
        x + w / 2,
        delta,
        w,
        color="#e74c3c",
        alpha=0.75,
        label="ค่าเฉลี่ยการเปลี่ยนแปลงคะแนน (แกนขวา)",
    )
    ax2.set_ylabel("mean_abs_score_delta", color="#e74c3c", fontsize=11)
    ax2.tick_params(axis="y", labelcolor="#e74c3c")
    ax2.set_ylim(0, max(delta) * 1.4)

    ax1.set_title(
        f"รูปที่ 4.D การแยกกันของคะแนนและอันดับ: การถอดองค์ประกอบ H2L V6 "
        f"(n={len(agg[order[0]]['ndcg'])} เคส)\n"
        f"คะแนนภายในเปลี่ยน {min(delta):.4f}–{max(delta):.4f} "
        f"แต่ nDCG@5 อยู่ในช่วง {min(ndcg):.4f}–{max(ndcg):.4f} เท่านั้น",
        fontsize=11,
    )
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="upper right", fontsize=9)
    ax1.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "fig_4d_decoupling.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    return (
        f"4.D variants={len(order)} "
        f"ndcg={min(ndcg):.4f}-{max(ndcg):.4f} "
        f"delta={min(delta):.4f}-{max(delta):.4f}"
    )


def main() -> None:
    font = pick_thai_font()
    plt.rcParams["font.family"] = font
    plt.rcParams["axes.unicode_minus"] = False
    print(f"Thai font: {font}")

    OUT.mkdir(parents=True, exist_ok=True)
    for fn in (fig_4a, fig_4b, fig_4c, fig_4d):
        print("  " + fn())

    print(f"\nWrote to {OUT}")
    for f in sorted(OUT.glob("*.png")):
        print(f"  {f.name}  {f.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
