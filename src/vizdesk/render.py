"""Draw FigureSpecs to PNG (or SVG / PDF) with matplotlib.

The chart functions live in vizdesk.charts; this module lays panels out on
the figure grid, applies the theme and saves the image and its recipe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from vizdesk.charts import REGISTRY, Renderer  # noqa: F401  (re-exported)
from vizdesk.charts.base import AGG_HELP, apply_filter  # noqa: F401
from vizdesk.cleaning import apply_steps
from vizdesk.data import coerce_types, load_table, profile
from vizdesk.spec import FigureSpec, PanelSpec

# "colorblind" is the default: its palette (Tableau colorblind 10) stays distinct for red-green colour blindness.
THEMES = {
    "colorblind": "tableau-colorblind10",
    "default": "default",
    "whitegrid": "seaborn-v0_8-whitegrid",
    "ggplot": "ggplot",
    "dark": "dark_background",
    "minimal": "fast",
}


# ---------------------------------------------------------------- figure assembly


@dataclass
class RenderResult:
    path: Path
    spec_path: Path
    warnings: list[str] = field(default_factory=list)
    alt_text: str = ""
    alt_path: Path | None = None
    script_path: Path | None = None


def validate_panel(df: pd.DataFrame, panel: PanelSpec) -> list[str]:
    """Return plain-language problems with a panel, or [] when it can be drawn."""
    if panel.chart not in REGISTRY:
        return [f"'{panel.chart}' is in the catalog but vizdesk cannot draw it yet."]
    r = REGISTRY[panel.chart]
    problems = []
    for role in r.required():
        value = getattr(panel, role)
        if not value:
            problems.append(f"{panel.chart} needs a '{role}' column ({r.roles[role][0]}).")
    for role in ("x", "y", "hue", "size"):
        col = getattr(panel, role)
        if col and col not in df.columns:
            problems.append(f"column '{col}' (used as {role}) is not in the data.")
    missing = [c for c in panel.columns if c not in df.columns]
    if missing:
        problems.append(f"columns not in the data: {', '.join(missing)}.")
    if not problems and r.check:
        problems += r.check(df, panel)
    return problems


def prepare_data(spec: FigureSpec) -> pd.DataFrame:
    df = load_table(spec.source, spec.sheet)
    df = apply_steps(df, spec.cleaning)
    return coerce_types(df, profile(df))


def render_figure(df: pd.DataFrame, spec: FigureSpec) -> RenderResult:
    spec.fit_grid()
    out = Path(spec.output).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    style = THEMES.get(spec.theme, THEMES["colorblind"])
    with plt.style.context(style):
        fig = plt.figure(figsize=(spec.width, spec.height), dpi=spec.dpi, layout="constrained")
        engine = fig.get_layout_engine()
        if spec.padding:
            engine.set(w_pad=spec.pad / 2, h_pad=spec.pad / 2, wspace=0.05, hspace=0.05)
        else:
            engine.set(w_pad=0, h_pad=0, wspace=0, hspace=0)
        grid = fig.add_gridspec(spec.rows, spec.cols)
        for i, panel in enumerate(spec.panels[: spec.rows * spec.cols]):
            renderer = REGISTRY.get(panel.chart)
            ax = fig.add_subplot(grid[i // spec.cols, i % spec.cols], projection="polar" if renderer and renderer.polar else None)
            problems = validate_panel(df, panel)
            if not problems:
                try:
                    data = apply_filter(df, panel)
                    if data.empty:
                        raise ValueError(f"no rows left after filter '{panel.options.get('filter')}'")
                    renderer.func(ax, data, panel)
                except Exception as exc:  # one bad panel should not lose the whole figure
                    problems = [f"{type(exc).__name__}: {exc}"]
            if problems:
                warnings.append(f"panel {i + 1} ({panel.label()}): " + " ".join(problems))
                ax.clear()
                ax.set_axis_off()
                ax.text(0.5, 0.5, "Could not draw\n" + panel.label() + "\n\n" + "\n".join(problems),
                        ha="center", va="center", wrap=True, fontsize="small", color="firebrick", transform=ax.transAxes)
        if spec.title:
            fig.suptitle(spec.title)
        alt_text = describe_figure(df, spec)
        meta_key = {".pdf": "Subject", ".svg": "Description"}.get(out.suffix.lower(), "Description")
        fig.savefig(out, dpi=spec.dpi, bbox_inches="tight", pad_inches=spec.pad if spec.padding else 0.02,
                    metadata={meta_key: alt_text})
        plt.close(fig)
    alt_path = out.with_suffix(".alt.txt")
    alt_path.write_text(alt_text + "\n", encoding="utf-8")
    script_path = script_path_for(out)
    script_path.write_text(to_script(spec), encoding="utf-8")
    return RenderResult(out, spec.save(), warnings, alt_text, alt_path, script_path)


def render_spec(spec: FigureSpec) -> RenderResult:
    return render_figure(prepare_data(spec), spec)


from vizdesk.alt import describe_figure  # noqa: E402  (these import THEMES/REGISTRY from this module)
from vizdesk.export import script_path_for, to_script  # noqa: E402
