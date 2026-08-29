"""Charts and markdown tables for the backtest results."""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.metrics import daily_pnl

INK = "#1a1a1a"
ACCENT = "#c2410c"
MUTED = "#94a3b8"


def _style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(MUTED)
    ax.tick_params(colors=INK, labelsize=8)
    ax.grid(axis="y", color=MUTED, alpha=0.25, linewidth=0.6)
    ax.set_axisbelow(True)


def equity_chart(curves: dict[str, pd.Series], initial: float, path: Path,
                 title: str) -> None:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), height_ratios=[2, 1],
                                   sharex=True)
    for i, (label, eq) in enumerate(curves.items()):
        colour = ACCENT if i == 0 else None
        lw = 1.8 if i == 0 else 1.1
        ax1.plot(pd.to_datetime(eq.index), eq.to_numpy(), label=label,
                 color=colour, linewidth=lw, alpha=1.0 if i == 0 else 0.75)
    ax1.axhline(initial, color=MUTED, linewidth=0.9, linestyle="--")
    ax1.set_ylabel("Account equity ($)")
    ax1.set_title(title, color=INK, fontsize=12, loc="left", pad=12)
    ax1.legend(frameon=False, fontsize=8, loc="upper left")
    _style(ax1)

    head = next(iter(curves.values()))
    dd = head - head.cummax()
    ax2.fill_between(pd.to_datetime(dd.index), dd.to_numpy(), 0,
                     color=ACCENT, alpha=0.30, linewidth=0)
    ax2.set_ylabel("Drawdown ($)")
    _style(ax2)
    fig.tight_layout()
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def yearly_chart(table: pd.DataFrame, path: Path, title: str) -> None:
    fig, ax = plt.subplots(figsize=(11, 4))
    colours = [ACCENT if v < 0 else "#0f766e" for v in table["net_pnl"]]
    ax.bar(table["year"], table["net_pnl"], color=colours, width=0.7)
    ax.axhline(0, color=INK, linewidth=0.8)
    ax.set_ylabel("Net P&L ($)")
    ax.set_title(title, color=INK, fontsize=12, loc="left", pad=12)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def sweep_chart(rows: pd.DataFrame, path: Path, title: str) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for kind, group in rows.groupby("variant"):
        ax.plot(range(len(group)), group["total_return_pct"], marker="o",
                label=kind, linewidth=1.4)
        for x, (_, r) in enumerate(group.iterrows()):
            ax.annotate(f"{r['param']:g}", (x, r["total_return_pct"]),
                        textcoords="offset points", xytext=(0, 7),
                        ha="center", fontsize=7, color=MUTED)
    ax.axhline(0, color=INK, linewidth=0.8)
    ax.set_ylabel("Total return (%)")
    ax.set_xlabel("parameter step (label = parameter value)")
    ax.set_title(title, color=INK, fontsize=12, loc="left", pad=12)
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def md_table(frame: pd.DataFrame, floatfmt: str = "{:,.2f}") -> str:
    if frame.empty:
        return "_(no rows)_\n"
    cols = list(frame.columns)
    head = "| " + " | ".join(str(c) for c in cols) + " |"
    rule = "|" + "|".join("---" for _ in cols) + "|"
    lines = [head, rule]
    for _, row in frame.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            if isinstance(v, float):
                cells.append("—" if pd.isna(v) else floatfmt.format(v))
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
