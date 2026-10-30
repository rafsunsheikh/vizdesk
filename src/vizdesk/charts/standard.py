"""The standard charts: distributions, comparisons, relationships, composition, trends."""

from __future__ import annotations

import re
from collections import Counter
from statistics import NormalDist

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from vizdesk.charts.base import (  # noqa: F401
    ANY,
    CAT,
    NUM,
    TEXT,
    TIME,
    _STOPWORDS,
    _aggregate,
    _fmt,
    _groups,
    _kde,
    _labels,
    MISSING,
    _flag,
    _log_axes,
    _log_bins,
    _num,
    _opt,
    _order,
    _pivot_wide,
    _ohlc_columns,
    _rotate_dates,
    _rotate_if_crowded,
    _short,
    _squarify,
    _time_series,
    _top,
    _value_label,
    chart,
    need_columns,
)


# ---------------------------------------------------------------- distributions


@chart("histogram", x=(NUM, True), hue=(CAT, False), options="log=x", hint="Spread of one numeric column")
def _histogram(ax, df, p):
    values = _num(df, p.x).dropna()
    log = "x" in _log_axes(p) and (values >= 0).all()
    if log:
        bins, scale = _log_bins(values, p.bins)
        ax.set_xscale(scale)
    else:
        bins = np.histogram_bin_edges(values, bins=p.bins)
    for label, sub in _groups(df, p.hue, 5):
        ax.hist(_num(sub, p.x).dropna(), bins=bins, alpha=0.6 if p.hue else 0.9, label=label, edgecolor="white", linewidth=0.4)
    if p.hue:
        ax.legend(title=p.hue, fontsize="small")
    _labels(ax, p, p.x + (" (log scale)" if log else ""), "count", f"Distribution of {p.x}")


@chart("histogram_grid", columns=(NUM + "+", True), hint="One small histogram per numeric column, like pandas df.hist()")
def _histogram_grid(ax, df, p):
    cols = p.columns[:12]
    n = len(cols)
    ncols = min(n, 4)
    nrows = -(-n // ncols)
    ax.set_axis_off()
    ax.set_title(p.title or "Distribution of every numeric column", fontsize="medium")
    for i, col in enumerate(cols):
        r, c = divmod(i, ncols)
        inner = ax.inset_axes((c / ncols + 0.02, 1 - (r + 1) / nrows + 0.06, 1 / ncols - 0.05, 1 / nrows - 0.13))
        values = _num(df, col).dropna()
        log = len(values) > 2 and (values >= 0).all() and values.skew() > 2  # a long tail hides everything else
        bins, scale = _log_bins(values, 30) if log else (min(p.bins, 40), "linear")
        inner.hist(values, bins=bins, color="C0", edgecolor="white", linewidth=0.3)
        inner.set_xscale(scale)
        inner.set_title(_short(col, 20) + (" (log)" if log else ""), fontsize=7, pad=2)
        inner.tick_params(labelsize=5, length=2)


@chart("density_plot", x=(NUM, True), hue=(CAT, False), hint="Smooth curve of where values cluster")
def _density(ax, df, p):
    values = _num(df, p.x).dropna().to_numpy()
    grid = np.linspace(values.min(), values.max(), 300)
    for label, sub in _groups(df, p.hue, 6):
        dens = _kde(_num(sub, p.x).dropna().to_numpy(), grid)
        if dens is not None:
            ax.plot(grid, dens, label=label)
            ax.fill_between(grid, dens, alpha=0.15)
    if p.hue:
        ax.legend(title=p.hue, fontsize="small")
    _labels(ax, p, p.x, "density", f"Density of {p.x}")


@chart("ecdf_plot", x=(NUM, True), hue=(CAT, False), hint="Share of values at or below each point")
def _ecdf(ax, df, p):
    for label, sub in _groups(df, p.hue, 6):
        ax.ecdf(_num(sub, p.x).dropna(), label=label)
    if p.hue:
        ax.legend(title=p.hue, fontsize="small")
    _labels(ax, p, p.x, "share of rows ≤ value", f"ECDF of {p.x}")


@chart("qq_plot", x=(NUM, True), hint="Is the column normally distributed?")
def _qq(ax, df, p):
    values = np.sort(_num(df, p.x).dropna().to_numpy())
    n = len(values)
    nd = NormalDist()
    theory = np.array([nd.inv_cdf((i + 0.5) / n) for i in range(n)])
    ax.scatter(theory, values, s=8, alpha=0.6)
    slope, intercept = values.std(), values.mean()
    ax.plot(theory, intercept + slope * theory, color="red", linewidth=1, label="normal reference")
    ax.legend(fontsize="small")
    _labels(ax, p, "theoretical normal quantiles", p.x, f"Q-Q plot of {p.x}")


def _by_category(df, p, value_col):
    if not p.x:
        return [_num(df, value_col).dropna().to_numpy()], [value_col]
    order = df[p.x].value_counts().index[: p.top_n]
    data = [_num(df[df[p.x] == k], value_col).dropna().to_numpy() for k in order]
    keep = [(d, _short(k)) for d, k in zip(data, order) if len(d)]
    return [d for d, _ in keep], [k for _, k in keep]


@chart("box_whisker_plot", options="log=y", y=(NUM, True), x=(CAT, False), hint="Median, quartiles and outliers, optionally per group")
def _box(ax, df, p):
    data, labels = _by_category(df, p, p.y)
    ax.boxplot(data, positions=range(1, len(data) + 1), patch_artist=True,
               boxprops={"facecolor": "#9ecae1", "alpha": 0.8}, medianprops={"color": "black"})
    ax.set_xticks(range(1, len(labels) + 1), labels)
    _rotate_if_crowded(ax, labels)
    if "y" in _log_axes(p) and all((d >= 0).all() for d in data):
        ax.set_yscale("log" if all((d > 0).all() for d in data) else "symlog")
        ax.set_ylim(bottom=0 if ax.get_yscale() == "symlog" else None)
    _labels(ax, p, p.x or "", p.y, f"{p.y} by {p.x}" if p.x else f"Box plot of {p.y}")


@chart("violin_plot", y=(NUM, True), x=(CAT, False), hint="Distribution shape per group, shows bimodal data")
def _violin(ax, df, p):
    data, labels = _by_category(df, p, p.y)
    data = [d for d in data if len(d) > 1]
    parts = ax.violinplot(data, positions=range(1, len(data) + 1), showmedians=True)
    for body in parts["bodies"]:
        body.set_alpha(0.6)
    ax.set_xticks(range(1, len(data) + 1), labels[: len(data)])
    _rotate_if_crowded(ax, labels)
    _labels(ax, p, p.x or "", p.y, f"{p.y} by {p.x}" if p.x else f"Violin plot of {p.y}")


# ---------------------------------------------------------------- comparisons and rankings


@chart("bar_chart", x=(CAT, True), y=(NUM, False), hint="Count or total per category")
def _bar(ax, df, p):
    values = _order(_top(_aggregate(df, p.x, p), p.top_n), p)
    labels = [_short(i) for i in values.index]
    if len(values) > 8 and p.options.get("order") != "label":
        ax.barh(labels[::-1], values.to_numpy()[::-1], color="C0")
        _labels(ax, p, _value_label(p), p.x, f"{_value_label(p)} by {p.x}")
    else:
        ax.bar(labels, values.to_numpy(), color="C0")
        _rotate_if_crowded(ax, labels)
        _labels(ax, p, p.x, _value_label(p), f"{_value_label(p)} by {p.x}")


def _pivot(df, p) -> pd.DataFrame:
    return _pivot_wide(df, p, rows=p.top_n, cols=8)


@chart("multi_set_bar_chart", x=(CAT, True), hue=(CAT, True), y=(NUM, False), hint="Side-by-side bars for two categories")
def _grouped(ax, df, p):
    wide = _pivot(df, p)
    n = len(wide.columns)
    width = 0.8 / max(n, 1)
    pos = np.arange(len(wide.index))
    for i, col in enumerate(wide.columns):
        ax.bar(pos + i * width - 0.4 + width / 2, wide[col].to_numpy(), width, label=str(col))
    ax.set_xticks(pos, [_short(i) for i in wide.index])
    _rotate_if_crowded(ax, wide.index)
    ax.legend(title=p.hue, fontsize="small")
    _labels(ax, p, p.x, _value_label(p), f"{_value_label(p)} by {p.x} and {p.hue}")


def _stacked(ax, df, p, percent: bool):
    wide = _pivot(df, p)
    if percent:
        wide = wide.div(wide.sum(axis=1).replace(0, np.nan), axis=0) * 100
    bottom = np.zeros(len(wide.index))
    labels = [_short(i) for i in wide.index]
    for col in wide.columns:
        ax.bar(labels, wide[col].to_numpy(), bottom=bottom, label=str(col))
        bottom += wide[col].to_numpy()
    _rotate_if_crowded(ax, labels)
    ax.legend(title=p.hue, fontsize="small")
    _labels(ax, p, p.x, "% of bar" if percent else _value_label(p), f"{p.hue} within {p.x}")


@chart("stacked_bar_graph", x=(CAT, True), hue=(CAT, True), y=(NUM, False), hint="Totals per category split into parts")
def _stacked_bar(ax, df, p):
    _stacked(ax, df, p, percent=False)


@chart("stacked_bar_100", x=(CAT, True), hue=(CAT, True), y=(NUM, False), hint="Share of each part within each category")
def _stacked_100(ax, df, p):
    _stacked(ax, df, p, percent=True)


@chart("dot_plot", x=(CAT, True), y=(NUM, False), hint="Ranked dots, good for many categories")
def _dot(ax, df, p):
    values = _top(_aggregate(df, p.x, p), p.top_n).iloc[::-1]
    labels = [_short(i) for i in values.index]
    ax.scatter(values.to_numpy(), labels, s=40, zorder=3)
    ax.grid(axis="y", linestyle=":", alpha=0.6)
    _labels(ax, p, _value_label(p), p.x, f"{_value_label(p)} by {p.x}")


@chart("lollipop_chart", x=(CAT, True), y=(NUM, False), hint="Ranking with thin bars")
def _lollipop(ax, df, p):
    values = _top(_aggregate(df, p.x, p), p.top_n).iloc[::-1]
    labels = [_short(i) for i in values.index]
    ax.hlines(labels, 0, values.to_numpy(), color="C0", linewidth=1.5)
    ax.scatter(values.to_numpy(), labels, s=45, color="C0", zorder=3)
    _labels(ax, p, _value_label(p), p.x, f"Top {len(values)} {p.x} by {_value_label(p)}")


@chart("dumbbell_chart", check=need_columns(2, "two numeric columns on the same scale"), x=(CAT, True), columns=(NUM + "+", True), hint="Gap between two numeric columns per category")
def _dumbbell(ax, df, p):
    a, b = p.columns[:2]
    means = df.assign(_a=_num(df, a), _b=_num(df, b)).groupby(p.x, observed=True)[["_a", "_b"]].mean()
    means = means.loc[means.abs().sum(axis=1).sort_values(ascending=False).index[: p.top_n]].iloc[::-1]
    labels = [_short(i) for i in means.index]
    ax.hlines(labels, means["_a"], means["_b"], color="grey", linewidth=2)
    ax.scatter(means["_a"], labels, label=a, zorder=3, s=40)
    ax.scatter(means["_b"], labels, label=b, zorder=3, s=40)
    ax.legend(fontsize="small")
    _labels(ax, p, "mean value", p.x, f"{a} vs {b} by {p.x}")


@chart("error_bars", x=(CAT, True), y=(NUM, True), hint="Mean with ± standard deviation per category")
def _error_bars(ax, df, p):
    stats = df.assign(_v=_num(df, p.y)).groupby(p.x, observed=True)["_v"].agg(["mean", "std", "count"])
    stats = stats.sort_values("count", ascending=False).iloc[: p.top_n]
    labels = [_short(i) for i in stats.index]
    ax.bar(labels, stats["mean"], yerr=stats["std"].fillna(0), capsize=4, color="C0", alpha=0.8)
    _rotate_if_crowded(ax, labels)
    _labels(ax, p, p.x, f"mean of {p.y} (± 1 sd)", f"{p.y} by {p.x}")


@chart("radar_chart", polar=True, columns=(NUM + "+", True), x=(CAT, False), hint="Profile of several numeric columns per group (scaled 0-1)")
def _radar(ax, df, p):
    cols = p.columns[:10]
    data = df[cols].apply(pd.to_numeric, errors="coerce")
    scaled = (data - data.min()) / (data.max() - data.min()).replace(0, np.nan)
    angles = np.linspace(0, 2 * np.pi, len(cols), endpoint=False).tolist()
    angles += angles[:1]
    groups = [(str(k), scaled[df[p.x] == k]) for k in df[p.x].value_counts().index[:5]] if p.x else [("all rows", scaled)]
    for label, sub in groups:
        values = sub.mean().fillna(0).tolist()
        values += values[:1]
        ax.plot(angles, values, label=label)
        ax.fill(angles, values, alpha=0.12)
    ax.set_xticks(angles[:-1], cols, fontsize="small")
    ax.set_yticklabels([])
    if p.x:
        ax.legend(fontsize="x-small", loc="upper right", bbox_to_anchor=(1.3, 1.1))
    ax.set_title(p.title or "Mean profile (each axis scaled 0-1)", fontsize="medium")


@chart("span_chart", x=(CAT, True), y=(NUM, True), hint="Min-to-max range per category")
def _span(ax, df, p):
    stats = df.assign(_v=_num(df, p.y)).groupby(p.x, observed=True)["_v"].agg(["min", "max", "median"])
    stats = stats.sort_values("median").iloc[-p.top_n :]
    labels = [_short(i) for i in stats.index]
    ax.hlines(labels, stats["min"], stats["max"], linewidth=6, color="C0", alpha=0.6)
    ax.scatter(stats["median"], labels, color="black", s=15, zorder=3, label="median")
    ax.legend(fontsize="small")
    _labels(ax, p, p.y, p.x, f"Range of {p.y} by {p.x}")


# ---------------------------------------------------------------- relationships


@chart("scatterplot", x=(NUM, True), y=(NUM, True), hue=(CAT, False), hint="Does one number move with another?")
def _scatter(ax, df, p):
    data = df.assign(_x=_num(df, p.x), _y=_num(df, p.y)).dropna(subset=["_x", "_y"])
    if len(data) > 20000:
        data = data.sample(20000, random_state=0)
    alpha = 0.7 if len(data) < 1000 else 0.3
    for label, sub in _groups(data, p.hue, 8):
        ax.scatter(sub["_x"], sub["_y"], s=12, alpha=alpha, label=label)
    for axis, col, setter in (("x", "_x", ax.set_xscale), ("y", "_y", ax.set_yscale)):
        if axis in _log_axes(p) and (data[col] >= 0).all():
            setter("log" if (data[col] > 0).all() else "symlog")
    if _flag(p, "trend", True) and len(data) > 2 and data["_x"].std() > 0:
        slope, intercept = np.polyfit(data["_x"], data["_y"], 1)
        xs = np.linspace(data["_x"].min(), data["_x"].max(), 50)
        r = data["_x"].corr(data["_y"])
        ax.plot(xs, slope * xs + intercept, color="red", linewidth=1, label=f"best fit (r = {r:.2f})")
    ax.legend(fontsize="small", title=p.hue)
    _labels(ax, p, p.x, p.y, f"{p.y} vs {p.x}")


@chart("bubble_chart", x=(NUM, True), y=(NUM, True), size=(NUM, True), hue=(CAT, False), hint="Scatter with a third number as bubble area")
def _bubble(ax, df, p):
    data = df.assign(_x=_num(df, p.x), _y=_num(df, p.y), _s=_num(df, p.size)).dropna(subset=["_x", "_y", "_s"])
    if len(data) > 2000:
        data = data.sample(2000, random_state=0)
    s = data["_s"] - data["_s"].min()
    area = 20 + 600 * (s / s.max() if s.max() > 0 else s)  # area, not radius, is proportional
    for label, sub in _groups(data, p.hue, 8):
        ax.scatter(sub["_x"], sub["_y"], s=area.loc[sub.index], alpha=0.5, label=label, edgecolor="white")
    if p.hue:
        ax.legend(title=p.hue, fontsize="small", markerscale=0.4)
    _labels(ax, p, p.x, p.y, f"{p.y} vs {p.x} (size = {p.size})")


@chart("hexbin_plot", options="log=y (or x, xy)", x=(NUM, True), y=(NUM, True), hint="Scatter for big data, coloured by point density")
def _hexbin(ax, df, p):
    data = pd.DataFrame({"x": _num(df, p.x), "y": _num(df, p.y)}).dropna()
    log = _log_axes(p)
    dropped = 0
    for axis in "xy":
        if axis in log and (data[axis] <= 0).any():  # a log axis cannot show zeros
            dropped += int((data[axis] <= 0).sum())
            data = data[data[axis] > 0]
    hb = ax.hexbin(data["x"], data["y"], gridsize=35, cmap="viridis", mincnt=1, bins="log",
                   xscale="log" if "x" in log and (data["x"] > 0).all() else "linear",
                   yscale="log" if "y" in log and (data["y"] > 0).all() else "linear")
    ax.figure.colorbar(hb, ax=ax, label="rows (log colour scale)")
    _labels(ax, p, p.x, p.y, f"{p.y} vs {p.x}" + (f" ({dropped:,} rows with zero left out)" if dropped else ""))


@chart("correlation_heatmap", columns=(NUM + "+", True), hint="Correlation between every pair of numeric columns")
def _corr(ax, df, p):
    cols = p.columns[:15]
    corr = df[cols].apply(pd.to_numeric, errors="coerce").corr()
    im = ax.imshow(corr.to_numpy(), cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(cols)), cols, rotation=45, ha="right", fontsize="small")
    ax.set_yticks(range(len(cols)), cols, fontsize="small")
    if len(cols) <= 10:
        for i in range(len(cols)):
            for j in range(len(cols)):
                v = corr.iat[i, j]
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize="x-small",
                        color="white" if abs(v) > 0.6 else "black")
    ax.figure.colorbar(im, ax=ax, shrink=0.8)
    ax.set_title(p.title or "Correlation (Pearson)", fontsize="medium")


@chart("heatmap", x=(CAT, True), hue=(CAT, True), y=(NUM, False), hint="Grid of two categories, coloured by count or value")
def _heatmap(ax, df, p):
    wide = _pivot(df, p).T
    im = ax.imshow(wide.to_numpy(dtype=float), cmap="Blues", aspect="auto")
    ax.set_xticks(range(len(wide.columns)), [_short(c) for c in wide.columns], rotation=45, ha="right", fontsize="small")
    ax.set_yticks(range(len(wide.index)), [_short(i) for i in wide.index], fontsize="small")
    if wide.size <= 120:
        top = wide.to_numpy(dtype=float).max() or 1
        for i in range(wide.shape[0]):
            for j in range(wide.shape[1]):
                v = wide.iat[i, j]
                ax.text(j, i, _fmt(v), ha="center", va="center", fontsize="x-small", color="white" if v > top * 0.6 else "black")
    ax.figure.colorbar(im, ax=ax, shrink=0.8, label=_value_label(p))
    _labels(ax, p, p.x, p.hue, f"{_value_label(p)}: {p.hue} × {p.x}")


@chart("scatter_matrix", columns=(NUM + "+", True), hint="All pairwise scatterplots of 2-6 numeric columns")
def _scatter_matrix(ax, df, p):
    cols = p.columns[:6]
    data = df[cols].apply(pd.to_numeric, errors="coerce").dropna()
    if len(data) > 3000:
        data = data.sample(3000, random_state=0)
    n = len(cols)
    ax.set_axis_off()
    ax.set_title(p.title or "Scatter matrix", fontsize="medium")
    step = 1 / n
    for i, row in enumerate(cols):
        for j, col in enumerate(cols):
            inner = ax.inset_axes((j * step, 1 - (i + 1) * step, step * 0.92, step * 0.92))
            if i == j:
                inner.hist(data[col], bins=20, color="C0")
            else:
                inner.scatter(data[col], data[row], s=2, alpha=0.4)
            inner.tick_params(labelsize=5, length=2)
            if i < n - 1:
                inner.set_xticklabels([])
            else:
                inner.set_xlabel(col, fontsize=7)
            if j > 0:
                inner.set_yticklabels([])
            else:
                inner.set_ylabel(row, fontsize=7)


@chart("parallel_coordinates_plot", columns=(NUM + "+", True), hue=(CAT, False), hint="Each row as a line across several numeric axes (scaled 0-1)")
def _parallel(ax, df, p):
    cols = p.columns[:10]
    data = df[cols].apply(pd.to_numeric, errors="coerce")
    scaled = (data - data.min()) / (data.max() - data.min()).replace(0, np.nan)
    scaled = scaled.assign(_hue=df[p.hue].astype(str) if p.hue else "rows").dropna()
    if len(scaled) > 500:
        scaled = scaled.sample(500, random_state=0)
    xs = range(len(cols))
    colors = {h: f"C{i % 10}" for i, h in enumerate(scaled["_hue"].value_counts().index)}
    for _, r in scaled.iterrows():
        ax.plot(xs, r[cols].to_numpy(dtype=float), color=colors[r["_hue"]], alpha=0.25, linewidth=0.8)
    ax.set_xticks(list(xs), cols, rotation=30, ha="right")
    if p.hue:
        for h, c in list(colors.items())[:8]:
            ax.plot([], [], color=c, label=h)
        ax.legend(title=p.hue, fontsize="small")
    _labels(ax, p, None, "scaled value (0-1)", "Parallel coordinates")


# ---------------------------------------------------------------- composition


def _shares(df, p, slices: int = 6) -> pd.Series:
    return _top(_aggregate(df, p.x, p).clip(lower=0), slices, other=True)


@chart("pie_chart", x=(CAT, True), y=(NUM, False), hint="Share of a whole, best with ≤ 6 slices")
def _pie(ax, df, p):
    values = _shares(df, p)
    ax.pie(values.to_numpy(), labels=[_short(i) for i in values.index], autopct="%1.0f%%", startangle=90, counterclock=False,
           wedgeprops={"edgecolor": "white"}, textprops={"fontsize": "small"})
    ax.set_title(p.title or f"Share of {_value_label(p)} by {p.x}", fontsize="medium")


@chart("donut_chart", x=(CAT, True), y=(NUM, False), hint="Pie with a hole; shows the total in the middle")
def _donut(ax, df, p):
    values = _shares(df, p)
    ax.pie(values.to_numpy(), labels=[_short(i) for i in values.index], autopct="%1.0f%%", startangle=90, counterclock=False,
           pctdistance=0.8, wedgeprops={"width": 0.4, "edgecolor": "white"}, textprops={"fontsize": "small"})
    ax.text(0, 0, f"{_fmt(values.sum())}\ntotal", ha="center", va="center", fontsize="small")
    ax.set_title(p.title or f"Share of {_value_label(p)} by {p.x}", fontsize="medium")


@chart("treemap", x=(CAT, True), y=(NUM, False), hint="Nested rectangles sized by value; fits many categories")
def _treemap(ax, df, p):
    values = _top(_aggregate(df, p.x, p).clip(lower=0), max(p.top_n, 20)).loc[lambda s: s > 0]
    rects = _squarify(values.tolist(), 0, 0, 100, 100)
    cmap = plt.get_cmap("tab20")
    total = values.sum()
    for i, ((x, y, w, h), (label, v)) in enumerate(zip(rects, values.items())):
        ax.add_patch(plt.Rectangle((x, y), w, h, facecolor=cmap(i % 20), edgecolor="white", linewidth=1.5))
        if w > 8 and h > 5:
            ax.text(x + w / 2, y + h / 2, f"{label}\n{v / total:.0%}", ha="center", va="center", fontsize="x-small")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_axis_off()
    ax.set_title(p.title or f"{_value_label(p)} by {p.x}", fontsize="medium")


# ---------------------------------------------------------------- trends


@chart("line_graph", x=(TIME, True), y=(NUM, False), hue=(CAT, False), options="rolling=50; filter=Name=AAPL",
       hint="Trend over time; up to ~4 lines")
def _line(ax, df, p):
    series = _time_series(df, p, by_hue=True)
    if isinstance(series, pd.DataFrame):
        for col in series.columns:
            ax.plot(series.index, series[col], label=str(col), marker="o" if len(series) < 30 else None, markersize=3)
        ax.legend(title=p.hue, fontsize="small")
    else:
        ax.plot(series.index, series.to_numpy(), marker="o" if len(series) < 30 else None, markersize=3,
                label=p.y if p.options.get("rolling") else None)
    window = int(_opt(p, "rolling", 0))
    if window > 1:
        frame = series if isinstance(series, pd.DataFrame) else series.to_frame("value")
        for i, col in enumerate(frame.columns):
            ax.plot(frame.index, frame[col].rolling(window, min_periods=1).mean(), linestyle="--", linewidth=1.2,
                    color="black" if frame.shape[1] == 1 else f"C{i % 10}", label=f"{window}-point moving average"
                    + ("" if frame.shape[1] == 1 else f" ({col})"))
        ax.legend(fontsize="small", title=p.hue)
    if pd.api.types.is_datetime64_any_dtype(df[p.x]):
        _rotate_dates(ax)
    _labels(ax, p, p.x, _value_label(p), f"{_value_label(p)} over {p.x}")


@chart("area_graph", x=(TIME, True), y=(NUM, False), hint="Trend over time with the area filled")
def _area(ax, df, p):
    series = _time_series(df, p, by_hue=False)
    ax.fill_between(series.index, series.to_numpy(dtype=float), alpha=0.4)
    ax.plot(series.index, series.to_numpy(dtype=float))
    _labels(ax, p, p.x, _value_label(p), f"{_value_label(p)} over {p.x}")


@chart("stacked_area_graph", x=(TIME, True), hue=(CAT, True), y=(NUM, False), hint="How parts add up to a total over time")
def _stacked_area(ax, df, p):
    wide = _time_series(df, p, by_hue=True).clip(lower=0)
    ax.stackplot(wide.index, wide.T.to_numpy(dtype=float), labels=[_short(c) for c in wide.columns], alpha=0.85)
    ax.legend(title=p.hue, fontsize="small", loc="upper left")
    _labels(ax, p, p.x, _value_label(p), f"{_value_label(p)} by {p.hue} over {p.x}")


@chart("stream_graph", x=(TIME, True), hue=(CAT, True), y=(NUM, False), hint="Stacked area around a centre line; broad trends only")
def _stream(ax, df, p):
    wide = _time_series(df, p, by_hue=True).clip(lower=0)
    ax.stackplot(wide.index, wide.T.to_numpy(dtype=float), labels=[_short(c) for c in wide.columns], baseline="wiggle", alpha=0.85)
    ax.set_yticks([])
    ax.legend(title=p.hue, fontsize="small", loc="upper left")
    _labels(ax, p, p.x, None, f"{p.hue} over {p.x}")


def _check_ohlc(df, p):
    if len(_ohlc_columns(df, p)) < 4:
        return ["needs open, high, low and close columns (name them in 'columns' or use those column names)."]
    return []


def _ohlc(ax, df, p, candles: bool):
    o, h, l, c = _ohlc_columns(df, p)
    data = df.assign(_t=pd.to_datetime(df[p.x], errors="coerce"), _o=_num(df, o), _h=_num(df, h), _l=_num(df, l), _c=_num(df, c))
    data = data.dropna(subset=["_t", "_o", "_h", "_l", "_c"]).sort_values("_t").tail(int(_opt(p, "last", 120)))
    xs = np.arange(len(data))
    up = (data["_c"] >= data["_o"]).to_numpy()
    colors = np.where(up, "C0", "C1")
    ax.vlines(xs, data["_l"], data["_h"], color=colors, linewidth=1)
    if candles:
        bottom = np.minimum(data["_o"], data["_c"])
        ax.bar(xs, (data["_c"] - data["_o"]).abs().clip(lower=1e-9), bottom=bottom, color=colors, width=0.6)
    else:
        ax.hlines(data["_o"], xs - 0.3, xs, color=colors)
        ax.hlines(data["_c"], xs, xs + 0.3, color=colors)
    step = max(len(xs) // 8, 1)
    ax.set_xticks(xs[::step], data["_t"].dt.strftime("%Y-%m-%d").iloc[::step], rotation=45, ha="right")
    _labels(ax, p, None, "price", ("Candlestick" if candles else "OHLC") + " (blue = up, orange = down)")


@chart("candlestick_chart", check=_check_ohlc, options="filter=Name=AAPL; last=120", x=(TIME, True), columns=(NUM + "+", False), hint="Open/high/low/close per period; needs those 4 columns")
def _candlestick(ax, df, p):
    _ohlc(ax, df, p, candles=True)


@chart("open_high_low_close_chart", check=_check_ohlc, options="filter=Name=AAPL; last=120", x=(TIME, True), columns=(NUM + "+", False), hint="Open/high/low/close ticks per period")
def _ohlc_chart(ax, df, p):
    _ohlc(ax, df, p, candles=False)


@chart("gantt_chart", check=need_columns(2, "a start and an end date column"), x=(CAT, True), columns=(TIME + "+", True), hue=(CAT, False), hint="Tasks as bars from start date to end date")
def _gantt(ax, df, p):
    start, end = p.columns[:2]
    data = df.assign(_s=pd.to_datetime(df[start], errors="coerce"), _e=pd.to_datetime(df[end], errors="coerce"))
    data = data.dropna(subset=["_s", "_e"]).sort_values("_s").head(40).iloc[::-1]
    colors = {h: f"C{i % 10}" for i, h in enumerate(data[p.hue].astype(str).unique())} if p.hue else {}
    ax.barh(data[p.x].astype(str), (data["_e"] - data["_s"]).dt.total_seconds() / 86400, left=data["_s"],
            color=[colors.get(str(h), "C0") for h in data[p.hue]] if p.hue else "C0")
    _rotate_dates(ax)
    _labels(ax, p, "date", p.x, "Schedule")


# ---------------------------------------------------------------- geo, text, data quality


def _geo_points(ax, df, p, sizes):
    """Scatter lon/lat; colour by a category (legend) or by a number (colour bar)."""
    if p.hue and pd.api.types.is_numeric_dtype(df[p.hue]) and df[p.hue].nunique() > 8:
        order = _num(df, p.hue).sort_values(na_position="first").index  # draw high values last, on top
        sc = ax.scatter(_num(df, p.x).loc[order], _num(df, p.y).loc[order], c=_num(df, p.hue).loc[order],
                        s=sizes.loc[order] if hasattr(sizes, "loc") else sizes, cmap="viridis", alpha=0.6, edgecolor="none")
        ax.figure.colorbar(sc, ax=ax, shrink=0.8, label=p.hue)
    else:
        for label, sub in _groups(df, p.hue, 8):
            ax.scatter(_num(sub, p.x), _num(sub, p.y), s=sizes.loc[sub.index] if hasattr(sizes, "loc") else sizes,
                       alpha=0.6, label=label, edgecolor="none")
        if p.hue:
            ax.legend(title=p.hue, fontsize="small", markerscale=2)
    ax.set_aspect("equal", adjustable="datalim")


@chart("dot_map", x=(NUM, True), y=(NUM, True), hue=(ANY, False), hint="Longitude (x) / latitude (y) points, coloured by a column; no basemap")
def _dot_map(ax, df, p):
    _geo_points(ax, df, p, 4 if len(df) > 5000 else 10)
    _labels(ax, p, p.x, p.y, "Locations" + (f" coloured by {p.hue}" if p.hue else ""))


@chart("bubble_map", x=(NUM, True), y=(NUM, True), size=(NUM, True), hue=(ANY, False),
       hint="Longitude / latitude bubbles sized by one column and coloured by another; no basemap")
def _bubble_map(ax, df, p):
    df = df.assign(_s=_num(df, p.size)).dropna(subset=["_s"])
    s = df["_s"].clip(lower=0)
    _geo_points(ax, df, p, 2 + 300 * s / (s.max() or 1))
    _labels(ax, p, p.x, p.y, f"size = {p.size}" + (f", colour = {p.hue}" if p.hue else ""))


@chart("word_frequency_bar", x=(TEXT, True), hint="Most common words in a text column")
def _words(ax, df, p):
    counts: Counter[str] = Counter()
    for text in df[p.x].dropna().astype(str):
        counts.update(w for w in re.findall(r"[a-zA-Z']{3,}", text.lower()) if w not in _STOPWORDS)
    top = counts.most_common(p.top_n)[::-1]
    ax.barh([w for w, _ in top], [n for _, n in top], color="C0")
    _labels(ax, p, "count", None, f"Top words in {p.x}")


@chart("missing_values_map", hint="Where the gaps are in the table")
def _missing(ax, df, p):
    data = df if len(df) <= 1000 else df.sample(1000, random_state=0).sort_index()
    ax.imshow(data.isna().to_numpy(), aspect="auto", cmap="Greys", interpolation="nearest", vmin=0, vmax=1)
    pct = df.isna().mean() * 100
    ax.set_xticks(range(len(df.columns)), [f"{c} ({pct[c]:.0f}%)" for c in df.columns], rotation=60, ha="right", fontsize="x-small")
    ax.set_ylabel("rows" + (" (sample of 1000)" if len(df) > 1000 else ""))
    ax.set_title(p.title or "Missing values (black = missing)", fontsize="medium")
