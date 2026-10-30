"""Specialist charts: extra comparison forms, calendars and timelines,
financial range charts, text, and annotated "illustration" charts."""

from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from vizdesk.charts.base import (
    ANY,
    CAT,
    NUM,
    TEXT,
    TIME,
    _STOPWORDS,
    _aggregate,
    _fmt,
    _labels,
    _num,
    _opt,
    _pivot_wide,
    _rotate_dates,
    _short,
    _time_series,
    _top,
    _value_label,
    chart,
)


def _nice_unit(maximum: float, max_marks: int) -> float:
    """1, 2, 5, 10, 20, 50 ... so that `maximum` needs at most `max_marks` marks."""
    if maximum <= max_marks:
        return 1
    raw = maximum / max_marks
    base = 10 ** math.floor(math.log10(raw))
    return next(m * base for m in (1, 2, 5, 10) if m * base >= raw)


def _price_series(df: pd.DataFrame, p) -> pd.Series:
    data = df.assign(_t=pd.to_datetime(df[p.x], errors="coerce", format="mixed"), _v=_num(df, p.y)).dropna(subset=["_t", "_v"])
    return data.groupby("_t")["_v"].last().sort_index()


# ---------------------------------------------------------------- distributions and comparisons


@chart("stem_leaf_plot", x=(NUM, True), hint="Distribution that keeps every value readable (small data)")
def _stem_leaf(ax, df, p):
    values = _num(df, p.x).dropna()
    if len(values) > 300:
        values = values.sample(300, random_state=0)
    span = max(abs(values.max()), abs(values.min())) or 1
    unit = 10 ** (math.floor(math.log10(span)) - 1)  # two significant digits: stem = first, leaf = second
    scaled = np.floor(values / unit).astype(int)
    stems: dict[int, list[int]] = {}
    for v in sorted(scaled):
        stems.setdefault(int(v // 10), []).append(int(abs(v) % 10))
    lines = [f"{s:>5} | {''.join(str(l) for l in leaves)[:60]}" for s, leaves in sorted(stems.items())]
    ax.set_axis_off()
    ax.text(0.02, 0.98, "\n".join(lines[:40]), family="monospace", va="top", fontsize="small", transform=ax.transAxes)
    ax.text(0.98, 0.02, f"key: 4 | 2 = {42 * unit:g}" + (" (300-row sample)" if len(_num(df, p.x).dropna()) > 300 else ""),
            ha="right", fontsize="x-small", transform=ax.transAxes)
    ax.set_title(p.title or f"Stem & leaf of {p.x}", fontsize="medium")


@chart("bullet_graph", x=(CAT, True), y=(NUM, True), size=(NUM, False), options="target=100",
       hint="Actual vs target per category, on poor / ok / good bands")
def _bullet(ax, df, p):
    actual = _top(_aggregate(df, p.x, p), min(p.top_n, 8))
    if p.size:
        target = df.assign(_t=_num(df, p.size)).groupby(p.x, observed=True)["_t"].mean().reindex(actual.index)
    else:
        target = pd.Series(_opt(p, "target", float(actual.mean())), index=actual.index)
    top = float(max(actual.max(), target.max())) * 1.15
    labels = [_short(i) for i in actual.index][::-1]
    for i, (a, t) in enumerate(zip(actual.to_numpy()[::-1], target.to_numpy()[::-1])):
        for share, shade in ((1.0, "#e6e6e6"), (0.75, "#cccccc"), (0.5, "#b3b3b3")):
            ax.barh(i, top * share, height=0.8, color=shade, zorder=1)
        ax.barh(i, a, height=0.3, color="C0", zorder=2)
        ax.plot([t, t], [i - 0.3, i + 0.3], color="black", linewidth=2.5, zorder=3)
    ax.set_yticks(range(len(labels)), labels)
    _labels(ax, p, _value_label(p), None, f"{_value_label(p)} vs target ({p.size or 'average'})")


@chart("marimekko_chart", x=(CAT, True), hue=(CAT, True), y=(NUM, False),
       hint="Bar widths = size of each group, segments = share inside it")
def _marimekko(ax, df, p):
    wide = _pivot_wide(df, p, rows=10, cols=8)
    totals = wide.sum(axis=1)
    widths = totals / totals.sum()
    left = 0.0
    for name, row in wide.iterrows():
        bottom = 0.0
        shares = row / row.sum() if row.sum() else row
        for j, (seg, share) in enumerate(shares.items()):
            ax.add_patch(Rectangle((left, bottom), widths[name], share, facecolor=f"C{j % 10}", edgecolor="white",
                                   label=str(seg) if left == 0 else None))
            if widths[name] > 0.06 and share > 0.08:
                ax.text(left + widths[name] / 2, bottom + share / 2, f"{share:.0%}", ha="center", va="center", fontsize="x-small")
            bottom += share
        ax.text(left + widths[name] / 2, -0.03, _short(name, 12), ha="center", va="top", fontsize="x-small", rotation=30)
        left += widths[name]
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.legend(title=p.hue, fontsize="x-small", loc="upper left", bbox_to_anchor=(1, 1))
    _labels(ax, p, None, f"share of {p.hue}", f"{p.hue} within {p.x} (width = {_value_label(p)})")


@chart("pictogram_chart", x=(CAT, True), y=(NUM, False), hint="Icons stand for amounts; for general audiences")
def _pictogram(ax, df, p):
    values = _top(_aggregate(df, p.x, p), min(p.top_n, 8)).clip(lower=0)
    per_row = 10
    unit = _nice_unit(float(values.max()), 50)
    y = 0.0
    for row, (name, v) in enumerate(values.items()):
        full, part = divmod(v / unit, 1)
        icons = int(full) + (1 if part >= 0.25 else 0)
        for k in range(icons):
            size = 120 if k < full else 120 * max(part, 0.3)
            ax.scatter(k % per_row, y - (k // per_row) * 0.8, s=size, color=f"C{row % 10}", marker="o")
        ax.text(-1, y, _short(name, 16), ha="right", va="center", fontsize="small")
        y -= max(math.ceil(icons / per_row), 1) * 0.8 + 0.7
    ax.set_xlim(-6, per_row)
    ax.set_axis_off()
    ax.set_title(p.title or f"{_value_label(p)} by {p.x} (● = {_fmt(unit)})", fontsize="medium")


@chart("radial_bar_chart", polar=True, x=(CAT, True), y=(NUM, False), hint="Bars bent into rings; decorative, not precise")
def _radial_bar(ax, df, p):
    values = _top(_aggregate(df, p.x, p), min(p.top_n, 10)).clip(lower=0).iloc[::-1]
    full = 1.5 * np.pi
    ax.barh(range(len(values)), values / (values.max() or 1) * full, left=0, height=0.7,
            color=[f"C{i % 10}" for i in range(len(values))])
    ax.set_yticks(range(len(values)), [f"{_short(i, 14)}  {_fmt(v)}" for i, v in values.items()], fontsize="x-small")
    ax.set_xticks([])
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_title(p.title or f"{_value_label(p)} by {p.x}", fontsize="medium")


@chart("radial_column_chart", polar=True, x=(CAT, True), y=(NUM, False), hint="Columns around a circle")
def _radial_column(ax, df, p):
    values = _top(_aggregate(df, p.x, p), min(p.top_n, 16)).clip(lower=0)
    theta = np.linspace(0, 2 * np.pi, len(values), endpoint=False)
    ax.bar(theta, values.to_numpy(), width=2 * np.pi / len(values) * 0.85, color=[f"C{i % 10}" for i in range(len(values))])
    ax.set_xticks(theta, [_short(i, 12) for i in values.index], fontsize="x-small")
    ax.set_title(p.title or f"{_value_label(p)} by {p.x}", fontsize="medium")


@chart("tally_chart", x=(CAT, True), hint="Tally marks in groups of five per category")
def _tally(ax, df, p):
    counts = _top(df[p.x].value_counts(), min(p.top_n, 10))
    unit = _nice_unit(float(counts.max()), 40)
    for row, (name, n) in enumerate(counts.items()):
        marks = int(round(n / unit))
        y = -row
        for g in range(0, marks, 5):
            x0 = (g // 5) * 1.4
            for k in range(min(5, marks - g)):
                if k < 4:
                    ax.plot([x0 + k * 0.25] * 2, [y - 0.3, y + 0.3], color="black", linewidth=1.2)
                else:
                    ax.plot([x0 - 0.1, x0 + 0.85], [y - 0.25, y + 0.25], color="firebrick", linewidth=1.2)
        ax.text(-0.4, y, _short(name, 16), ha="right", va="center", fontsize="small")
        ax.text((marks // 5 + 1) * 1.4, y, f"{n:,}", va="center", fontsize="x-small", color="grey")
    ax.set_xlim(-5, 12)
    ax.set_axis_off()
    ax.set_title(p.title or f"Tally of {p.x}" + (f" (1 mark = {_fmt(unit)})" if unit > 1 else ""), fontsize="medium")


# ---------------------------------------------------------------- time


def _daily(df, p) -> pd.Series:
    data = df.assign(_t=pd.to_datetime(df[p.x], errors="coerce", format="mixed")).dropna(subset=["_t"])
    data["_d"] = data["_t"].dt.normalize()
    return _aggregate(data, "_d", p).sort_index()


@chart("calendar", x=(TIME, True), y=(NUM, False), hint="Day-by-day heatmap of the most recent year")
def _calendar(ax, df, p):
    daily = _daily(df, p)
    end = daily.index.max()
    start = max(daily.index.min(), end - pd.Timedelta(days=364))
    days = pd.date_range(start - pd.Timedelta(days=start.weekday()), end, freq="D")
    values = daily.reindex(days)
    week = ((days - days[0]).days // 7).to_numpy()
    grid = np.full((7, week.max() + 1), np.nan)
    grid[days.day_of_week.to_numpy(), week] = values.to_numpy(dtype=float)
    im = ax.imshow(np.ma.masked_invalid(grid), aspect="auto", cmap="YlGn", interpolation="nearest")
    ax.set_yticks(range(7), ["Mon", "", "Wed", "", "Fri", "", "Sun"], fontsize="x-small")
    firsts = [(w, d) for w, d in zip(week, days) if d.day == 1]
    ax.set_xticks([w for w, _ in firsts], [d.strftime("%b") for _, d in firsts], fontsize="x-small")
    ax.figure.colorbar(im, ax=ax, shrink=0.7, label=_value_label(p))
    ax.set_title(p.title or f"{_value_label(p)} per day, {start:%Y-%m-%d} to {end:%Y-%m-%d}", fontsize="medium")


@chart("spiral_plot", polar=True, x=(TIME, True), y=(NUM, False), hint="One turn per year: shows yearly cycles in long series")
def _spiral(ax, df, p):
    daily = _daily(df, p)
    if len(daily) > 3000:
        daily = daily.resample("W").sum() if _value_label(p) == "count" or "sum" in _value_label(p) else daily.resample("W").mean()
    t = daily.index
    theta = 2 * np.pi * (t.day_of_year.to_numpy() / 365.25)
    radius = 1 + (t - t[0]).days.to_numpy() / 365.25
    sc = ax.scatter(theta, radius, c=daily.to_numpy(dtype=float), cmap="viridis", s=12)
    ax.plot(theta, radius, color="grey", linewidth=0.3, alpha=0.6)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_xticks(np.linspace(0, 2 * np.pi, 12, endpoint=False), ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                                                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], fontsize="x-small")
    ax.set_yticks([])
    ax.figure.colorbar(sc, ax=ax, shrink=0.6, label=_value_label(p))
    ax.set_title(p.title or f"{_value_label(p)} by time of year (one turn = one year)", fontsize="medium")


@chart("timeline", x=(TIME, True), hue=(ANY, False), hint="Events in date order with labels")
def _timeline(ax, df, p):
    data = df.assign(_t=pd.to_datetime(df[p.x], errors="coerce", format="mixed")).dropna(subset=["_t"]).sort_values("_t")
    if len(data) > 20:
        data = data.iloc[np.linspace(0, len(data) - 1, 20).astype(int)]
    levels = np.tile([1, -1, 0.6, -0.6, 0.3, -0.3], len(data))[: len(data)]
    ax.vlines(data["_t"], 0, levels, color="grey", linewidth=0.8)
    ax.plot(data["_t"], np.zeros(len(data)), "o", color="C0")
    ax.axhline(0, color="black", linewidth=1)
    for t, lvl, label in zip(data["_t"], levels, data[p.hue] if p.hue else data["_t"].dt.strftime("%Y-%m-%d")):
        ax.annotate(_short(label, 24), (t, lvl), xytext=(3, 3 if lvl > 0 else -3), textcoords="offset points",
                    va="bottom" if lvl > 0 else "top", fontsize="x-small")
    ax.set_yticks([])
    ax.spines[["left", "top", "right"]].set_visible(False)
    _rotate_dates(ax)
    _labels(ax, p, p.x, None, "Timeline" + (" (20 evenly spaced events)" if len(df) > 20 else ""))


@chart("timetable", x=(TIME, True), hue=(ANY, True), columns=(ANY + "+", False), hint="A schedule table sorted by time")
def _timetable(ax, df, p):
    data = df.assign(_t=pd.to_datetime(df[p.x], errors="coerce", format="mixed")).dropna(subset=["_t"]).sort_values("_t").head(25)
    cols = [p.hue] + [c for c in p.columns if c not in (p.hue, p.x)][:3]
    times = data["_t"].dt.strftime("%Y-%m-%d %H:%M" if (data["_t"].dt.hour + data["_t"].dt.minute).any() else "%Y-%m-%d")
    cells = [[t] + [_short(v, 28) for v in row] for t, row in zip(times, data[cols].astype(str).to_numpy())]
    ax.set_axis_off()
    table = ax.table(cellText=cells, colLabels=[p.x] + cols, loc="upper center", cellLoc="left")
    table.auto_set_font_size(False)
    table.set_fontsize(7)
    table.scale(1, 1.15)
    ax.set_title(p.title or f"Timetable ({len(data)} of {len(df)} rows)", fontsize="medium")


# ---------------------------------------------------------------- financial


def _kagi_points(prices: np.ndarray, reversal: float) -> list[float]:
    line = [prices[0]]
    direction = 0
    for price in prices[1:]:
        last = line[-1]
        if direction == 0:
            if abs(price - last) >= reversal:
                direction = 1 if price > last else -1
                line.append(price)
        elif (direction > 0 and price > last) or (direction < 0 and price < last):
            line[-1] = price
        elif abs(price - last) >= reversal:
            line.append(price)
            direction = -direction
    return line


@chart("kagi_chart", x=(TIME, True), y=(NUM, True), options="reversal=4% (or a price); filter=Name=AAPL",
       hint="Price turns only after a set reversal; ignores time")
def _kagi(ax, df, p):
    prices = _price_series(df, p).to_numpy(dtype=float)
    raw = str(p.options.get("reversal", "4%")).strip()
    reversal = float(raw.rstrip("%")) / 100 * float(np.median(prices)) if raw.endswith("%") else float(raw)
    line = _kagi_points(prices, reversal)
    shoulder, waist, thick = -np.inf, np.inf, line[1] > line[0] if len(line) > 1 else True
    for i in range(1, len(line)):
        a, b = line[i - 1], line[i]
        if b > a and b > shoulder:
            thick = True
        elif b < a and b < waist:
            thick = False
        ax.plot([i, i], [a, b], color="C0" if thick else "C1", linewidth=2.6 if thick else 1)
        if i + 1 < len(line):
            ax.plot([i, i + 1], [b, b], color="grey", linewidth=0.8)
        shoulder, waist = (b, waist) if b > a else (shoulder, b)
    ax.set_xticks([])
    _labels(ax, p, f"reversals (≥ {_fmt(reversal)})", p.y, f"Kagi chart of {p.y} (thick blue = demand, thin orange = supply)")


@chart("point_figure_chart", x=(TIME, True), y=(NUM, True), options="box=1.0; reversal=3; filter=Name=AAPL",
       hint="X columns for rises, O columns for falls")
def _point_figure(ax, df, p):
    prices = _price_series(df, p).to_numpy(dtype=float)
    box = _opt(p, "box", float(np.ptp(prices)) / 40 or 1.0)
    rev = int(_opt(p, "reversal", 3))
    columns: list[tuple[str, int, int]] = []  # (X/O, low box, high box)
    level = int(prices[0] // box)
    kind, lo, hi = None, level, level
    for price in prices[1:]:
        b = int(price // box)
        if kind in (None, "X") and b > hi:
            kind, hi = "X", b
        elif kind in (None, "O") and b < lo:
            kind, lo = "O", b
        elif kind == "X" and b <= hi - rev:
            columns.append(("X", lo, hi))
            kind, hi, lo = "O", hi - 1, b
        elif kind == "O" and b >= lo + rev:
            columns.append(("O", lo, hi))
            kind, lo, hi = "X", lo + 1, b
    if kind:
        columns.append((kind, lo, hi))
    columns = columns[-60:]
    for i, (k, a, b) in enumerate(columns):
        levels = np.arange(a, b + 1) * box
        ax.scatter([i] * len(levels), levels, marker="x" if k == "X" else "o", s=18,
                   color="C0" if k == "X" else "C1", facecolors="none" if k == "O" else None)
    ax.set_xticks([])
    _labels(ax, p, f"columns (box {_fmt(box)}, {rev}-box reversal)", p.y, f"Point & figure of {p.y}")


# ---------------------------------------------------------------- text and annotation


def _word_counts(df, col) -> Counter[str]:
    counts: Counter[str] = Counter()
    for text in df[col].dropna().astype(str):
        counts.update(w for w in re.findall(r"[a-zA-Z']{3,}", text.lower()) if w not in _STOPWORDS)
    return counts


@chart("word_cloud", x=(TEXT, True), hint="Common words sized by frequency; for a feel, not for measuring")
def _word_cloud(ax, df, p):
    words = _word_counts(df, p.x).most_common(max(p.top_n, 60))
    if not words:
        raise ValueError(f"no words found in '{p.x}'")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    fig = ax.figure
    renderer = fig.canvas.get_renderer()
    box = ax.get_window_extent(renderer)
    scale = min(box.width, box.height) / 300
    top = words[0][1]
    placed = []
    for i, (word, n) in enumerate(words):
        size = (8 + 34 * (n / top) ** 0.6) * scale * 72 / fig.dpi * 1.6
        text = ax.text(0.5, 0.5, word, fontsize=size, ha="center", va="center", color=f"C{i % 10}",
                       rotation=90 if i % 7 == 3 else 0)
        for step in range(400):
            angle = step * 0.35
            r = 0.006 * angle
            text.set_position((0.5 + r * math.cos(angle) * box.height / max(box.width, 1) * 1.6, 0.5 + r * math.sin(angle)))
            bb = text.get_window_extent(renderer)
            inside = box.x0 <= bb.x0 and bb.x1 <= box.x1 and box.y0 <= bb.y0 and bb.y1 <= box.y1
            if inside and not any(bb.overlaps(o) for o in placed):
                placed.append(bb)
                break
        else:
            text.remove()
    ax.set_title(p.title or f"Word cloud of {p.x}", fontsize="medium")


def _check_ordered_x(df, p):
    x = df[p.x]
    if pd.api.types.is_datetime64_any_dtype(x) or pd.api.types.is_numeric_dtype(x):
        return []
    return [f"x must be a date or numeric column; '{p.x}' is {x.dtype}."]


@chart("illustration_diagram", check=_check_ordered_x, x=(ANY, True), y=(NUM, True),
       hint="The series with call-outs on its high, low, biggest change and latest value")
def _illustration(ax, df, p):
    if pd.api.types.is_datetime64_any_dtype(df[p.x]):
        series = _time_series(df, p, by_hue=False)
    else:
        series = df.assign(_x=_num(df, p.x), _y=_num(df, p.y)).dropna(subset=["_x", "_y"]).groupby("_x")["_y"].mean()
    series = series.dropna()
    ax.plot(series.index, series.to_numpy(), color="C0")
    ax.fill_between(series.index, series.to_numpy(dtype=float), series.min(), alpha=0.1)
    jumps = series.diff().abs()
    notes = {
        "highest": series.idxmax(),
        "lowest": series.idxmin(),
        "biggest change": jumps.idxmax() if jumps.notna().any() else series.index[-1],
        "latest": series.index[-1],
    }
    offsets = {"highest": (10, 20), "lowest": (10, -25), "biggest change": (-60, 25), "latest": (-40, -30)}
    for i, (what, at) in enumerate(notes.items(), 1):
        ax.annotate(f"{i}", (at, series[at]), xytext=offsets[what], textcoords="offset points", fontsize="small",
                    bbox={"boxstyle": "circle", "fc": "#fff3b0"}, arrowprops={"arrowstyle": "->", "color": "grey"})
    legend = "\n".join(f"{i}  {what}: {_fmt(series[at])}"
                       + (f" ({at:%Y-%m-%d})" if isinstance(at, pd.Timestamp) else f" at {p.x} = {_fmt(at)}")
                       for i, (what, at) in enumerate(notes.items(), 1))
    ax.text(0.01, 0.99, legend, transform=ax.transAxes, va="top", fontsize="x-small",
            bbox={"boxstyle": "round", "fc": "white", "alpha": 0.85})
    if isinstance(series.index, pd.DatetimeIndex):
        _rotate_dates(ax)
    _labels(ax, p, p.x, p.y, f"{p.y}: what stands out")

