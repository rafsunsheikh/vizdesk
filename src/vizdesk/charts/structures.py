"""Charts of structure: networks and links, flows between stages,
hierarchies, and maps.

Column conventions, shared by every chart here:
  links       x = source, hue = target, size = weight (optional; else rows count)
  stages      columns = category columns in order (Region -> Category -> Segment), y = value (optional)
  hierarchy   columns = level columns from top to bottom, y = value (optional)
  maps        x = longitude, y = latitude, or columns = [lon1, lat1, lon2, lat2] for routes;
              options geojson=<path> draws real boundaries, key=<feature property> matches regions
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection, PatchCollection
from matplotlib.patches import Circle, FancyBboxPatch, PathPatch, Polygon, Rectangle, Wedge
from matplotlib.path import Path as MPath

from vizdesk.charts.base import (
    ANY,
    CAT,
    NUM,
    _agg_name,
    _aggregate,
    _fmt,
    _labels,
    _num,
    _opt,
    _short,
    _value_label,
    chart,
    need_columns,
)

# ---------------------------------------------------------------- shared helpers


def _edges(df: pd.DataFrame, p, max_nodes: int = 30) -> tuple[list[str], pd.Series]:
    """(nodes, weights indexed by (source, target)), keeping the most connected nodes."""
    data = df.dropna(subset=[p.x, p.hue]).assign(_s=lambda d: d[p.x].astype(str), _t=lambda d: d[p.hue].astype(str))
    if p.size:
        weights = data.assign(_w=_num(data, p.size)).groupby(["_s", "_t"])["_w"].sum()
    else:
        weights = data.groupby(["_s", "_t"]).size()
    weights = weights[weights > 0]
    strength: dict[str, float] = defaultdict(float)
    for (s, t), w in weights.items():
        strength[s] += w
        strength[t] += w
    nodes = sorted(strength, key=lambda n: -strength[n])[:max_nodes]
    keep = set(nodes)
    weights = weights[[s in keep and t in keep for s, t in weights.index]]
    return nodes, weights


def _check_edges(df, p):
    nodes, weights = _edges(df, p)
    return [] if len(weights) else [f"no links found between '{p.x}' and '{p.hue}'."]


def _spring_layout(n: int, pairs: np.ndarray, weights: np.ndarray, iterations: int = 250) -> np.ndarray:
    """Fruchterman-Reingold force layout: linked nodes pull together, all nodes push apart."""
    rng = np.random.default_rng(0)
    pos = rng.random((n, 2))
    k = 1 / math.sqrt(max(n, 1))
    temp = 0.1
    w = weights / weights.max() if len(weights) else weights
    for _ in range(iterations):
        delta = pos[:, None, :] - pos[None, :, :]
        dist = np.linalg.norm(delta, axis=2) + 1e-9
        disp = (delta / dist[..., None] * (k * k / dist)[..., None]).sum(axis=1)
        if len(pairs):
            d = pos[pairs[:, 0]] - pos[pairs[:, 1]]
            length = np.linalg.norm(d, axis=1)[:, None] + 1e-9
            pull = d / length * (length**2 / k) * (0.5 + w[:, None])
            np.add.at(disp, pairs[:, 0], -pull)
            np.add.at(disp, pairs[:, 1], pull)
        disp -= (pos - pos.mean(axis=0)) * 0.6 * k  # gravity keeps separate groups from drifting apart
        length = np.linalg.norm(disp, axis=1)[:, None] + 1e-9
        pos += disp / length * np.minimum(length, temp)
        temp *= 0.985
    return pos


def _levels(df: pd.DataFrame, p, per_level: tuple[int, ...] = (8, 6, 5)) -> pd.Series:
    """Values per path through the level columns, small branches folded into 'Other'."""
    cols = p.columns[:3]
    data = df.copy()
    for depth, col in enumerate(cols):
        data[col] = data[col].astype(str).where(data[col].notna(), "missing")
        limit = per_level[min(depth, len(per_level) - 1)]
        parents = cols[:depth]
        sizes = _aggregate(data, parents + [col], p) if parents else _aggregate(data, col, p)
        if parents:
            ranked = sizes.groupby(level=list(range(depth)), group_keys=False).nlargest(limit)
            keep = {k if isinstance(k, tuple) else (k,) for k in ranked.index}
            path = data[parents + [col]].apply(tuple, axis=1)
        else:
            keep = {(k,) for k in sizes.nlargest(limit).index}
            path = data[[col]].apply(tuple, axis=1)
        data[col] = data[col].where(path.isin(keep), "Other")
    series = _aggregate(data, cols, p) if len(cols) > 1 else _aggregate(data, cols[0], p)
    if len(cols) == 1:
        series.index = pd.MultiIndex.from_tuples([(i,) for i in series.index])
    return series.clip(lower=0)


def _tree(series: pd.Series) -> dict:
    """Nested dict {name: {"value": v, "children": {...}}} from a MultiIndex series."""
    root: dict = {"value": float(series.sum()), "children": {}}
    for path, value in series.items():
        node = root
        for name in path:
            node = node["children"].setdefault(str(name), {"value": 0.0, "children": {}})
            node["value"] += float(value)
    return root


def _geojson_shapes(path: str) -> list[tuple[dict, list[np.ndarray]]]:
    """[(properties, [ring arrays])] for every Polygon / MultiPolygon feature."""
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    features = data["features"] if data.get("type") == "FeatureCollection" else [data]
    shapes = []
    for f in features:
        geom = f.get("geometry") or {}
        polys = [geom["coordinates"]] if geom.get("type") == "Polygon" else geom.get("coordinates", []) if geom.get("type") == "MultiPolygon" else []
        rings = [np.asarray(poly[0], dtype=float) for poly in polys if poly]
        props = dict(f.get("properties") or {})
        if "id" in f:
            props.setdefault("id", f["id"])
        shapes.append((props, rings))
    return shapes


def _basemap(ax, p) -> None:
    if p.options.get("geojson"):
        for _, rings in _geojson_shapes(p.options["geojson"]):
            for ring in rings:
                ax.add_patch(Polygon(ring, closed=True, facecolor="#f2f2f2", edgecolor="#bbbbbb", linewidth=0.5, zorder=0))


def _geo_axes(ax, p, title: str) -> None:
    ax.set_aspect("equal", adjustable="datalim")
    ax.autoscale_view()
    _labels(ax, p, "longitude", "latitude", title + ("" if p.options.get("geojson") else " (no basemap; add geojson=<file>)"))


# ---------------------------------------------------------------- networks


@chart("network_diagram", check=_check_edges, x=(CAT, True), hue=(CAT, True), size=(NUM, False),
       hint="Nodes and links from source (x) to target (hue) columns")
def _network(ax, df, p):
    nodes, weights = _edges(df, p)
    index = {n: i for i, n in enumerate(nodes)}
    pairs = np.array([(index[s], index[t]) for s, t in weights.index])
    w = weights.to_numpy(dtype=float)
    pos = _spring_layout(len(nodes), pairs, w)
    segments = [(pos[a], pos[b]) for a, b in pairs]
    ax.add_collection(LineCollection(segments, linewidths=0.5 + 4 * w / w.max(), colors="grey", alpha=0.5, zorder=1))
    degree = np.zeros(len(nodes))
    np.add.at(degree, pairs[:, 0], w)
    np.add.at(degree, pairs[:, 1], w)
    sources = set(df[p.x].astype(str))
    ax.scatter(pos[:, 0], pos[:, 1], s=40 + 600 * degree / degree.max(), zorder=2,
               c=["C0" if n in sources else "C1" for n in nodes], edgecolor="white")
    for n, (x, y) in zip(nodes, pos):
        ax.text(x, y, _short(n, 14), fontsize="x-small", ha="center", va="center", zorder=3)
    ax.set_axis_off()
    ax.set_title(p.title or f"Network: {p.x} → {p.hue} (top {len(nodes)} nodes)", fontsize="medium")


@chart("arc_diagram", check=_check_edges, x=(CAT, True), hue=(CAT, True), size=(NUM, False),
       hint="Nodes on a line, links as arcs; good for co-occurrence")
def _arc(ax, df, p):
    nodes, weights = _edges(df, p, max_nodes=25)
    index = {n: i for i, n in enumerate(nodes)}
    w = weights.to_numpy(dtype=float)
    top = 0.0
    for ((s, t), weight) in zip(weights.index, w):
        a, b = sorted((index[s], index[t]))
        if a == b:
            continue
        theta = np.linspace(0, np.pi, 40)
        radius = (b - a) / 2
        ax.plot(a + radius + radius * np.cos(theta), radius * np.sin(theta), color="C0", alpha=0.45,
                linewidth=0.5 + 4 * weight / w.max())
        top = max(top, radius)
    ax.scatter(range(len(nodes)), np.zeros(len(nodes)), s=30, color="C1", zorder=3)
    ax.set_xticks(range(len(nodes)), [_short(n, 14) for n in nodes], rotation=60, ha="right", fontsize="x-small")
    ax.set_yticks([])
    ax.set_ylim(-0.3, top * 1.05 + 0.5)
    ax.spines[["left", "top", "right"]].set_visible(False)
    ax.set_title(p.title or f"Arc diagram: {p.x} ↔ {p.hue}", fontsize="medium")


@chart("chord_diagram", check=_check_edges, x=(CAT, True), hue=(CAT, True), size=(NUM, False),
       hint="Links between groups around a circle, ribbon width = strength")
def _chord(ax, df, p):
    nodes, weights = _edges(df, p, max_nodes=12)
    n = len(nodes)
    index = {name: i for i, name in enumerate(nodes)}
    m = np.zeros((n, n))
    for (s, t), w in weights.items():
        m[index[s], index[t]] += w
    sym = m + m.T - np.diag(np.diag(m))
    totals = sym.sum(axis=1)
    gap = 0.03 * 2 * np.pi
    scale = (2 * np.pi - gap * n) / totals.sum()
    start, spans = 0.0, {}
    for i in range(n):
        spans[i] = (start, start + totals[i] * scale)
        ax.add_patch(Wedge((0, 0), 1.0, np.degrees(spans[i][0]), np.degrees(spans[i][1]), width=0.07, color=f"C{i % 10}"))
        mid = (spans[i][0] + spans[i][1]) / 2
        ax.text(1.12 * np.cos(mid), 1.12 * np.sin(mid), _short(nodes[i], 12), ha="center", va="center", fontsize="x-small",
                rotation=np.degrees(mid) - 90 if 0 < mid < np.pi else np.degrees(mid) + 90)
        start = spans[i][1] + gap
    cursor = {i: spans[i][0] for i in range(n)}
    segment = {}
    for i in range(n):
        for j in range(n):
            if sym[i, j]:
                segment[(i, j)] = (cursor[i], cursor[i] + sym[i, j] * scale)
                cursor[i] += sym[i, j] * scale

    def arc(a0, a1, r=0.93):
        t = np.linspace(a0, a1, 12)
        return list(zip(r * np.cos(t), r * np.sin(t)))

    for i in range(n):
        for j in range(i, n):
            if not sym[i, j]:
                continue
            (a0, a1), (b0, b1) = segment[(i, j)], segment[(j, i)]
            if i == j:  # a group linked to itself: a loop back onto its own arc
                b0, b1 = a1, a0
            side_a, side_b = arc(a0, a1), arc(b0, b1)
            verts = side_a + [(0, 0), side_b[0]] + side_b[1:] + [(0, 0), side_a[0]]
            codes = [MPath.MOVETO] + [MPath.LINETO] * 11 + [MPath.CURVE3] * 2 + [MPath.LINETO] * 11 + [MPath.CURVE3] * 2
            ax.add_patch(PathPatch(MPath(verts, codes), facecolor=f"C{i % 10}", alpha=0.45, edgecolor="none"))
    ax.set_xlim(-1.3, 1.3)
    ax.set_ylim(-1.3, 1.3)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(p.title or f"Chord diagram: {p.x} ↔ {p.hue}", fontsize="medium")


@chart("flow_chart", check=_check_edges, x=(CAT, True), hue=(CAT, True), size=(NUM, False),
       hint="Process steps (x → hue) laid out left to right; diamonds branch")
def _flow_chart(ax, df, p):
    nodes, weights = _edges(df, p, max_nodes=24)
    out_edges: dict[str, list[str]] = defaultdict(list)
    indeg: dict[str, int] = defaultdict(int)
    for s, t in weights.index:
        if s != t:
            out_edges[s].append(t)
            indeg[t] += 1
    depth = {n: 0 for n in nodes if indeg[n] == 0} or {nodes[0]: 0}
    frontier = list(depth)
    while frontier:  # breadth-first layering; each node keeps the first (shortest) depth it gets, so cycles stop
        nxt = []
        for s in frontier:
            for t in out_edges[s]:
                if t not in depth:
                    depth[t] = depth[s] + 1
                    nxt.append(t)
        frontier = nxt
    for n in nodes:
        depth.setdefault(n, 0)
    layers: dict[int, list[str]] = defaultdict(list)
    for n in nodes:
        layers[depth[n]].append(n)
    pos = {n: (d * 3.0, -(i - (len(layer) - 1) / 2) * 1.4) for d, layer in layers.items() for i, n in enumerate(layer)}
    for (s, t), w in weights.items():
        if s != t:
            ax.annotate("", xy=pos[t], xytext=pos[s], arrowprops={"arrowstyle": "-|>", "color": "grey", "shrinkA": 28,
                                                                  "shrinkB": 28, "connectionstyle": "arc3,rad=0.08"})
            if p.size:
                mx, my = (pos[s][0] + pos[t][0]) / 2, (pos[s][1] + pos[t][1]) / 2
                ax.text(mx, my + 0.15, _fmt(w), fontsize="xx-small", color="grey", ha="center")
    for n, (x, y) in pos.items():
        if len(out_edges[n]) > 1:
            ax.add_patch(Polygon([(x - 1, y), (x, y + 0.55), (x + 1, y), (x, y - 0.55)], facecolor="#fde9b8", edgecolor="#b8860b"))
        else:
            style = "round,pad=0.1,rounding_size=0.4" if indeg[n] == 0 or not out_edges[n] else "square,pad=0.1"
            ax.add_patch(FancyBboxPatch((x - 0.9, y - 0.35), 1.8, 0.7, boxstyle=style,
                                        facecolor="#d6e9f8" if indeg[n] else "#c8f0c8", edgecolor="#4a7ca8"))
        ax.text(x, y, _short(n, 16), ha="center", va="center", fontsize="x-small")
    xs, ys = zip(*pos.values())
    ax.set_xlim(min(xs) - 1.3, max(xs) + 1.3)
    ax.set_ylim(min(ys) - 1, max(ys) + 1)
    ax.set_axis_off()
    ax.set_title(p.title or f"Flow: {p.x} → {p.hue}", fontsize="medium")


# ---------------------------------------------------------------- flows between stages


def _alluvial(ax, df, p, color_by_first: bool) -> None:
    stages = p.columns[:4]
    data = df.copy()
    for c in stages:
        data[c] = data[c].astype(str).where(data[c].notna(), "missing")
        top = data[c].value_counts().index[:7]
        data[c] = data[c].where(data[c].isin(top), "Other")
    weight = _num(data, p.y) if p.y else pd.Series(1.0, index=data.index)
    data = data.assign(_w=weight.fillna(0).clip(lower=0))
    total = data["_w"].sum()
    gap = 0.02
    node_pos: list[dict[str, tuple[float, float]]] = []
    for c in stages:
        sizes = data.groupby(c)["_w"].sum().sort_values(ascending=False) / total
        room = 1 - gap * (len(sizes) - 1)
        y, pos = 1.0, {}
        for name, share in sizes.items():
            h = share * room
            pos[name] = (y - h, y)
            y -= h + gap
        node_pos.append(pos)
    first_colors = {name: f"C{i % 10}" for i, name in enumerate(node_pos[0])}
    width = 0.08
    for k in range(len(stages) - 1):
        a, b = stages[k], stages[k + 1]
        keys = [stages[0], a, b] if color_by_first else [a, b]
        flows = data.groupby(keys)["_w"].sum() / total
        out_cursor = {n: top for n, (_, top) in node_pos[k].items()}
        in_cursor = {n: top for n, (_, top) in node_pos[k + 1].items()}
        order = sorted(flows.items(), key=lambda kv: (list(node_pos[k]).index(kv[0][-2]), list(node_pos[k + 1]).index(kv[0][-1])))
        for key, share in order:
            src, dst = key[-2], key[-1]
            h = share * (1 - gap * (len(node_pos[k]) - 1))
            y0, y1 = out_cursor[src], in_cursor[dst]
            out_cursor[src] -= h
            in_cursor[dst] -= h
            x0, x1 = k + width / 2, k + 1 - width / 2
            xm = (x0 + x1) / 2
            verts = [(x0, y0), (xm, y0), (xm, y1), (x1, y1), (x1, y1 - h), (xm, y1 - h), (xm, y0 - h), (x0, y0 - h), (x0, y0)]
            codes = [MPath.MOVETO, MPath.CURVE4, MPath.CURVE4, MPath.CURVE4, MPath.LINETO, MPath.CURVE4, MPath.CURVE4, MPath.CURVE4, MPath.CLOSEPOLY]
            color = first_colors.get(key[0], "grey") if color_by_first else f"C{list(node_pos[k]).index(src) % 10}"
            ax.add_patch(PathPatch(MPath(verts, codes), facecolor=color, alpha=0.45, edgecolor="none"))
    for k, pos in enumerate(node_pos):
        for name, (lo, hi) in pos.items():
            ax.add_patch(Rectangle((k - width / 2, lo), width, hi - lo, facecolor="#444444", edgecolor="white"))
            if hi - lo > 0.025:
                ax.text(k + (width / 2 + 0.02) * (1 if k < len(stages) - 1 else -1), (lo + hi) / 2, _short(name, 16),
                        va="center", ha="left" if k < len(stages) - 1 else "right", fontsize="x-small")
    ax.set_xticks(range(len(stages)), stages, fontsize="small")
    ax.set_xlim(-0.3, len(stages) - 0.7)
    ax.set_ylim(-0.02, 1.02)
    ax.set_yticks([])
    ax.spines[["left", "top", "right"]].set_visible(False)


@chart("sankey_diagram", check=need_columns(2, "two or more category columns, as stages"), columns=(CAT + "+", True),
       y=(NUM, False), hint="How rows (or y totals) flow from one stage column to the next")
def _sankey(ax, df, p):
    _alluvial(ax, df, p, color_by_first=False)
    _labels(ax, p, None, None, "Flow of " + (f"{p.y}" if p.y else "rows") + ": " + " → ".join(p.columns[:4]))


@chart("parallel_sets", check=need_columns(2, "two or more category columns"), columns=(CAT + "+", True),
       y=(NUM, False), hint="Category combinations across several columns, coloured by the first")
def _parallel_sets(ax, df, p):
    _alluvial(ax, df, p, color_by_first=True)
    _labels(ax, p, None, None, f"Parallel sets, coloured by {p.columns[0]}")


# ---------------------------------------------------------------- hierarchies


@chart("sunburst_diagram", check=need_columns(1, "one to three level columns"), columns=(CAT + "+", True),
       y=(NUM, False), hint="Rings of a hierarchy, inner ring = top level")
def _sunburst(ax, df, p):
    root = _tree(_levels(df, p))
    total = root["value"] or 1

    def draw(node, start, depth, color):
        angle = start
        for i, (name, child) in enumerate(sorted(node["children"].items(), key=lambda kv: -kv[1]["value"])):
            span = 360 * child["value"] / total
            c = f"C{i % 10}" if depth == 0 else color
            ax.add_patch(Wedge((0, 0), 0.3 + 0.3 * (depth + 1), angle, angle + span, width=0.29, facecolor=c,
                               edgecolor="white", alpha=1 - 0.22 * depth))
            if span > 8:
                mid = math.radians(angle + span / 2)
                r = 0.3 + 0.3 * depth + 0.15
                ax.text(r * math.cos(mid), r * math.sin(mid), _short(name, 10), ha="center", va="center", fontsize="xx-small")
            draw(child, angle, depth + 1, c)
            angle += span

    draw(root, 90, 0, None)
    reach = 0.3 + 0.3 * len(p.columns[:3])
    ax.text(0, 0, f"{_fmt(total)}\n{_value_label(p)}", ha="center", va="center", fontsize="x-small")
    ax.set_xlim(-reach, reach)
    ax.set_ylim(-reach, reach)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(p.title or "Sunburst: " + " → ".join(p.columns[:3]), fontsize="medium")


def _pack(radii: list[float]) -> tuple[np.ndarray, float]:
    """Greedy circle packing: each circle goes to the closest-to-centre free spot touching another."""
    order = np.argsort(radii)[::-1]
    pos = np.zeros((len(radii), 2))
    placed: list[int] = []
    for idx in order:
        r = radii[idx]
        if not placed:
            pos[idx] = (0, 0)
        else:
            best, best_d = None, np.inf
            for j in placed:
                for a in np.linspace(0, 2 * np.pi, 36, endpoint=False):
                    c = pos[j] + (radii[j] + r + 1e-6) * np.array([math.cos(a), math.sin(a)])
                    if all(np.linalg.norm(c - pos[k]) >= radii[k] + r - 1e-9 for k in placed):
                        d = np.linalg.norm(c)
                        if d < best_d:
                            best, best_d = c, d
            pos[idx] = best
        placed.append(idx)
    centre = pos.mean(axis=0)
    pos -= centre
    outer = max(np.linalg.norm(pos[i]) + radii[i] for i in range(len(radii)))
    return pos, outer


@chart("circle_packing", check=need_columns(1, "one or two level columns"), columns=(CAT + "+", True),
       y=(NUM, False), hint="Nested circles sized by value; shows the hierarchy clearly")
def _circle_packing(ax, df, p):
    p_two = type(p).from_dict({**p.__dict__, "columns": p.columns[:2]})
    root = _tree(_levels(df, p_two, per_level=(10, 8)))
    groups = sorted(root["children"].items(), key=lambda kv: -kv[1]["value"])
    inner = []
    for name, node in groups:
        kids = sorted(node["children"].items(), key=lambda kv: -kv[1]["value"]) or [(name, node)]
        radii = [math.sqrt(k[1]["value"]) or 1e-3 for k in kids]
        pos, outer = _pack(radii)
        inner.append((name, kids, radii, pos, outer * 1.08))
    centres, _ = _pack([g[4] for g in inner])
    for i, ((name, kids, radii, pos, outer), c) in enumerate(zip(inner, centres)):
        ax.add_patch(Circle(c, outer, facecolor=f"C{i % 10}", alpha=0.15, edgecolor=f"C{i % 10}"))
        for (kid, _), r, kp in zip(kids, radii, pos):
            ax.add_patch(Circle(c + kp, r, facecolor=f"C{i % 10}", alpha=0.55, edgecolor="white"))
            if r > outer * 0.25 and len(p.columns) > 1:
                ax.text(*(c + kp), _short(kid, 10), ha="center", va="center", fontsize="xx-small")
        ax.text(c[0], c[1] + outer * 0.9, _short(name, 14), ha="center", va="top", fontsize="x-small", weight="bold")
    ax.autoscale_view()
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_axis_off()
    ax.set_title(p.title or "Circle packing: " + " → ".join(p.columns[:2]), fontsize="medium")


def _layout_tree(root: dict, label: str) -> tuple[list, list]:
    """Tidy left-to-right layout: leaves stacked evenly, each parent centred on its children."""
    nodes, links = [], []
    counter = [0]

    def walk(name, node, depth):
        kids = sorted(node["children"].items(), key=lambda kv: -kv[1]["value"])
        if not kids:
            y = counter[0]
            counter[0] += 1
        else:
            ys = [walk(k, child, depth + 1) for k, child in kids]
            y = sum(ys) / len(ys)
            for (k, child), cy in zip(kids, ys):
                links.append(((depth, y), (depth + 1, cy)))
        nodes.append((depth, y, name, node["value"]))
        return y

    walk(label, root, 0)
    return nodes, links


@chart("tree_diagram", check=need_columns(1, "one to three level columns"), columns=(CAT + "+", True),
       y=(NUM, False), hint="Parent → child branches of a hierarchy")
def _tree_diagram(ax, df, p):
    nodes, links = _layout_tree(_tree(_levels(df, p, per_level=(6, 4, 3))), p.title or "all rows")
    for (x0, y0), (x1, y1) in links:
        xm = (x0 + x1) / 2
        ax.plot([x0, xm, xm, x1], [y0, y0, y1, y1], color="grey", linewidth=0.8)
    for x, y, name, value in nodes:
        ax.scatter(x, y, s=25, color="C0", zorder=3)
        ax.text(x + 0.05, y, f"{_short(name, 16)} ({_fmt(value)})", va="center", fontsize="xx-small")
    ax.set_xticks(range(len(p.columns[:3]) + 1), ["all"] + p.columns[:3], fontsize="x-small")
    ax.set_yticks([])
    ax.invert_yaxis()
    ax.spines[["left", "top", "right"]].set_visible(False)
    ax.set_xlim(-0.2, len(p.columns[:3]) + 0.9)
    ax.set_title(p.title or f"Tree of {' → '.join(p.columns[:3])} ({_value_label(p)})", fontsize="medium")


@chart("brainstorm", check=need_columns(1, "one or two level columns"), columns=(CAT + "+", True),
       y=(NUM, False), hint="Mind map: the topic in the middle, groups and items branching out")
def _brainstorm(ax, df, p):
    p_two = type(p).from_dict({**p.__dict__, "columns": p.columns[:2]})
    root = _tree(_levels(df, p_two, per_level=(8, 4)))
    ax.text(0, 0, _short(p.title or p.columns[0], 18), ha="center", va="center", fontsize="small", weight="bold",
            bbox={"boxstyle": "round,pad=0.6", "fc": "#fff3b0", "ec": "#b8860b"})
    branches = sorted(root["children"].items(), key=lambda kv: -kv[1]["value"])
    for i, (name, node) in enumerate(branches):
        a = 2 * np.pi * i / len(branches)
        bx, by = 1.0 * math.cos(a), 1.0 * math.sin(a)
        ax.plot([0, bx], [0, by], color=f"C{i % 10}", linewidth=2.5, alpha=0.7)
        ax.text(bx, by, _short(name, 14), ha="center", va="center", fontsize="x-small",
                bbox={"boxstyle": "round", "fc": "white", "ec": f"C{i % 10}"})
        kids = sorted(node["children"].items(), key=lambda kv: -kv[1]["value"])
        for j, (kid, _) in enumerate(kids):
            ka = a + (j - (len(kids) - 1) / 2) * (0.9 / max(len(branches), 3))
            kx, ky = 1.85 * math.cos(ka), 1.85 * math.sin(ka)
            ax.plot([bx, kx], [by, ky], color=f"C{i % 10}", linewidth=1, alpha=0.6)
            ax.text(kx, ky, _short(kid, 12), ha="center", va="center", fontsize="xx-small")
    ax.set_xlim(-2.4, 2.4)
    ax.set_ylim(-2.2, 2.2)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(f"Mind map of {' → '.join(p.columns[:2])}", fontsize="medium")


# ---------------------------------------------------------------- maps


def _check_choropleth(df, p):
    if p.options.get("geojson"):
        if not p.x:
            return ["with a geojson file, set x to the column holding region names or codes."]
        if not Path(str(p.options["geojson"])).expanduser().is_file():
            return [f"geojson file not found: {p.options['geojson']}"]
        return []
    return [] if len(p.columns) >= 2 else ["needs geojson=<file> with x = region column, or columns = [longitude, latitude]."]


@chart("choropleth_map", check=_check_choropleth, x=(ANY, False), y=(NUM, False), columns=(NUM + "+", False),
       options="geojson=regions.geojson; key=name; grid=40",
       hint="Regions shaded by value (with a GeoJSON file), or a shaded lon/lat grid")
def _choropleth(ax, df, p):
    if p.options.get("geojson"):
        values = _aggregate(df, p.x, p)
        values.index = values.index.astype(str).str.strip().str.lower()
        key = p.options.get("key")
        shapes = _geojson_shapes(p.options["geojson"])
        patches, colors, matched = [], [], 0
        for props, rings in shapes:
            names = [props.get(key)] if key else [props.get(k) for k in ("name", "NAME", "id", "iso_a3", "ISO_A3", "code", "STATE_NAME")]
            value = next((values[str(n).strip().lower()] for n in names if n is not None and str(n).strip().lower() in values.index), np.nan)
            matched += not np.isnan(value)
            for ring in rings:
                patches.append(Polygon(ring, closed=True))
                colors.append(value)
        cmap = plt.get_cmap("viridis").with_extremes(bad="#eeeeee")
        coll = PatchCollection(patches, cmap=cmap, edgecolor="white", linewidth=0.4)
        coll.set_array(np.ma.masked_invalid(np.array(colors, dtype=float)))
        ax.add_collection(coll)
        ax.figure.colorbar(coll, ax=ax, shrink=0.7, label=_value_label(p))
        _geo_axes(ax, p, f"{_value_label(p)} by {p.x} ({matched} of {len(shapes)} regions matched)")
        return
    lon, lat = p.columns[:2]
    data = df.assign(_x=_num(df, lon), _y=_num(df, lat)).dropna(subset=["_x", "_y"])
    cells = int(_opt(p, "grid", 40))
    xb = np.linspace(data["_x"].min(), data["_x"].max(), cells + 1)
    yb = np.linspace(data["_y"].min(), data["_y"].max(), cells + 1)
    data["_cx"] = np.clip(np.digitize(data["_x"], xb) - 1, 0, cells - 1)
    data["_cy"] = np.clip(np.digitize(data["_y"], yb) - 1, 0, cells - 1)
    grid = np.full((cells, cells), np.nan)
    agg = _aggregate(data, ["_cy", "_cx"], p)
    for (cy, cx), v in agg.items():
        grid[int(cy), int(cx)] = v
    mesh = ax.pcolormesh(xb, yb, np.ma.masked_invalid(grid), cmap="viridis", shading="flat")
    _basemap(ax, p)
    ax.figure.colorbar(mesh, ax=ax, shrink=0.7, label=_value_label(p) + (" per cell" if _agg_name(p) in ("count", "sum") else ""))
    _geo_axes(ax, p, f"{_value_label(p)} on a {cells}×{cells} grid")


def _routes(df, p) -> pd.DataFrame:
    a, b, c, d = p.columns[:4]
    data = df.assign(_x0=_num(df, a), _y0=_num(df, b), _x1=_num(df, c), _y1=_num(df, d),
                     _w=_num(df, p.size) if p.size else 1.0).dropna(subset=["_x0", "_y0", "_x1", "_y1"])
    return data.groupby(["_x0", "_y0", "_x1", "_y1"], as_index=False)["_w"].sum().nlargest(400, "_w")


def _curve(x0, y0, x1, y1, bend=0.2, n=30):
    t = np.linspace(0, 1, n)
    mx, my = (x0 + x1) / 2 - bend * (y1 - y0), (y0 + y1) / 2 + bend * (x1 - x0)
    return (1 - t) ** 2 * x0 + 2 * (1 - t) * t * mx + t**2 * x1, (1 - t) ** 2 * y0 + 2 * (1 - t) * t * my + t**2 * y1


@chart("connection_map", check=need_columns(4, "[lon_from, lat_from, lon_to, lat_to]"), columns=(NUM + "+", True),
       size=(NUM, False), options="geojson=world.geojson", hint="Lines between pairs of locations")
def _connection_map(ax, df, p):
    routes = _routes(df, p)
    _basemap(ax, p)
    for r in routes.itertuples():
        xs, ys = _curve(r._1, r._2, r._3, r._4)
        ax.plot(xs, ys, color="C0", alpha=0.35, linewidth=0.8)
    ax.scatter(pd.concat([routes["_x0"], routes["_x1"]]), pd.concat([routes["_y0"], routes["_y1"]]), s=8, color="C1", zorder=3)
    _geo_axes(ax, p, f"Connections ({len(routes)} routes)")


@chart("flow_map", check=need_columns(4, "[lon_from, lat_from, lon_to, lat_to]"), columns=(NUM + "+", True),
       size=(NUM, False), options="geojson=world.geojson", hint="Movement between locations; line width = volume")
def _flow_map(ax, df, p):
    routes = _routes(df, p)
    _basemap(ax, p)
    top = routes["_w"].max() or 1
    for r in routes.itertuples():
        xs, ys = _curve(r._1, r._2, r._3, r._4, bend=0.15)
        width = 0.5 + 6 * r._5 / top
        ax.plot(xs, ys, color="C3", alpha=0.5, linewidth=width, solid_capstyle="round")
        ax.annotate("", xy=(xs[-1], ys[-1]), xytext=(xs[-4], ys[-4]),
                    arrowprops={"arrowstyle": "-|>", "color": "C3", "alpha": 0.7, "mutation_scale": 6 + width * 2})
    _geo_axes(ax, p, f"Flows ({'width = ' + p.size if p.size else 'width = trips'})")
