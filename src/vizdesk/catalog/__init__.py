"""The chart catalog: every visualization technique vizdesk knows about.

charts.json is generated from the data scientists handbook by
scripts/build_catalog.py. extra_charts.json adds charts that the handbook
chapters use but the catalog file does not list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources

# Purpose groups, from the "By Analysis Purpose" table in the handbook.
PURPOSES: dict[str, list[str]] = {
    "distribution": ["histogram", "histogram_grid", "density_plot", "violin_plot", "box_whisker_plot", "ecdf_plot", "qq_plot"],
    "comparison": ["bar_chart", "multi_set_bar_chart", "dot_plot", "dumbbell_chart", "bullet_graph", "radar_chart", "error_bars"],
    "relationship": ["scatterplot", "bubble_chart", "hexbin_plot", "correlation_heatmap", "scatter_matrix", "heatmap", "parallel_coordinates_plot"],
    "composition": ["pie_chart", "donut_chart", "treemap", "stacked_bar_graph", "stacked_bar_100", "stacked_area_graph"],
    "trend": ["line_graph", "area_graph", "stacked_area_graph", "stream_graph", "candlestick_chart", "open_high_low_close_chart"],
    "ranking": ["bar_chart", "lollipop_chart", "dot_plot"],
    "data_quality": ["missing_values_map", "box_whisker_plot"],
    "geographic": ["choropleth_map", "bubble_map", "dot_map", "flow_map", "connection_map"],
    "flow": ["sankey_diagram", "parallel_sets", "flow_chart"],
    "hierarchy": ["tree_diagram", "sunburst_diagram", "treemap", "circle_packing"],
}


@dataclass(frozen=True)
class ChartInfo:
    key: str
    name: str
    category: str
    description: str = ""
    data_required: str = ""
    use_when: str = ""
    limitations: str = ""
    best_practice: str = ""
    variations: str = ""
    notes: str = ""
    aliases: tuple[str, ...] = ()
    similar: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    purposes: tuple[str, ...] = field(default=())

    @property
    def renderable(self) -> bool:
        from vizdesk.render import REGISTRY

        return self.key in REGISTRY

    def matches(self, text: str) -> bool:
        text = text.lower().strip()
        if not text:
            return True
        hay = " ".join(
            [self.name, self.category, self.description, self.use_when, " ".join(self.aliases), " ".join(self.purposes)]
        ).lower()
        return all(word in hay for word in text.split())

    def to_markdown(self) -> str:
        parts = [f"# {self.name}", f"*{self.category}*"]
        if self.aliases:
            parts.append(f"**Also known as:** {', '.join(self.aliases)}")
        parts.append(
            "**vizdesk can draw this:** " + ("yes" if self.renderable else "no (listed for reference)")
        )
        for label, value in [
            ("What it is", self.description),
            ("Data you need", self.data_required),
            ("Use it when", self.use_when),
            ("Watch out for", self.limitations),
            ("Best practice", self.best_practice),
            ("Variations", self.variations),
            ("Notes", self.notes),
        ]:
            if value:
                parts.append(f"**{label}:** {value}")
        if self.purposes:
            parts.append(f"**Good for goals:** {', '.join(self.purposes)}")
        if self.similar:
            parts.append(f"**Similar charts:** {', '.join(self.similar)}")
        if self.tools:
            parts.append(f"**Other tools:** {', '.join(self.tools)}")
        return "\n\n".join(parts)


def _load(name: str) -> list[dict]:
    return json.loads(resources.files(__package__).joinpath(name).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def all_charts() -> tuple[ChartInfo, ...]:
    charts = []
    for raw in _load("charts.json") + _load("extra_charts.json"):
        purposes = tuple(p for p, keys in PURPOSES.items() if raw["key"] in keys)
        charts.append(
            ChartInfo(
                key=raw["key"],
                name=raw["name"],
                category=raw["category"],
                description=raw.get("description", ""),
                data_required=raw.get("data_required", ""),
                use_when=raw.get("use_when", ""),
                limitations=raw.get("limitations", ""),
                best_practice=raw.get("best_practice", ""),
                variations=raw.get("variations", ""),
                notes=raw.get("notes", ""),
                aliases=tuple(raw.get("aliases", [])),
                similar=tuple(raw.get("similar", [])),
                tools=tuple(raw.get("tools", [])),
                purposes=purposes,
            )
        )
    return tuple(charts)


def get(key: str) -> ChartInfo:
    for chart in all_charts():
        if chart.key == key:
            return chart
    raise KeyError(f"unknown chart '{key}'")


def search(text: str = "", category: str | None = None, renderable_only: bool = False) -> list[ChartInfo]:
    return [
        c
        for c in all_charts()
        if c.matches(text)
        and (category is None or c.category == category)
        and (not renderable_only or c.renderable)
    ]


def categories() -> list[str]:
    seen: dict[str, None] = {}
    for c in all_charts():
        seen.setdefault(c.category, None)
    return list(seen)
