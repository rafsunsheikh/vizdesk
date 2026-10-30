"""Write a Python script that recreates a figure.

The script is split into notebook cells ("# %%"), so it runs as a file or
pastes into Jupyter / VS Code. Loading and every cleaning step are written as
plain pandas, so they can be read and changed. The drawing cell calls the
same vizdesk chart functions the PNG was made with, so the result matches.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from vizdesk import __version__
from vizdesk.cleaning import CleaningStep
from vizdesk.data import CSV_SUFFIXES
from vizdesk.render import REGISTRY, THEMES
from vizdesk.spec import FigureSpec, PanelSpec

_NUMBER_JUNK = r"[,\s$€£¥%]"


def _load_code(spec: FigureSpec) -> list[str]:
    path = Path(spec.source)
    if path.suffix.lower() in CSV_SUFFIXES:
        return [f'df = pd.read_csv(r"{path}", sep=None, engine="python")']
    sheet = repr(spec.sheet) if spec.sheet else "0"
    return [f'df = pd.read_excel(r"{path}", sheet_name={sheet})']


def _step_code(step: CleaningStep) -> list[str]:
    a, cols = step.action, step.columns
    q = [repr(c) for c in cols]
    lines = [f"# {step.title}"]
    if a == "drop_columns":
        lines.append(f"df = df.drop(columns=[{', '.join(q)}])")
    elif a == "drop_duplicates":
        lines.append("df = df.drop_duplicates().reset_index(drop=True)")
    for name, c in zip(cols, q):
        if a == "strip_whitespace":
            lines.append(f"df[{c}] = df[{c}].map(lambda v: v.strip() if isinstance(v, str) else v)")
        elif a == "lowercase":
            lines.append(f"df[{c}] = df[{c}].map(lambda v: v.strip().lower() if isinstance(v, str) else v)")
        elif a == "to_numeric":
            lines.append(f"df[{c}] = pd.to_numeric(df[{c}].astype('string').str.replace(r'{_NUMBER_JUNK}', '', regex=True), errors='coerce')")
        elif a == "to_datetime":
            lines.append(f"df[{c}] = pd.to_datetime(df[{c}].astype('string').str.strip(), errors='coerce', format='mixed')")
        elif a == "fill_missing":
            method = step.params.get("method", "median")
            if method == "constant":
                lines.append(f"df[{c}] = df[{c}].fillna({step.params.get('value', 'Unknown')!r})")
            else:
                lines.append(f"df[{c}] = pd.to_numeric(df[{c}], errors='coerce')")
                lines.append(f"df[{c}] = df[{c}].fillna(df[{c}].{method}())")
        elif a == "clip_outliers":
            lines.append(f"q1, q3 = df[{c}].quantile([0.25, 0.75])")
            lines.append(f"df[{c}] = df[{c}].clip(q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1))")
        elif a == "log_transform":
            lines.append(f"df[{name + '_log'!r}] = np.log(df[{c}].where(df[{c}] > 0))")
        elif a == "group_rare":
            share = step.params.get("min_share", 0.01)
            lines.append(f"rare = df[{c}].value_counts(normalize=True).loc[lambda s: s < {share}].index")
            lines.append(f"df[{c}] = df[{c}].where(~df[{c}].isin(rare), 'Other')")
        elif a == "standardize":
            lines.append(f"df[{name + '_z'!r}] = (df[{c}] - df[{c}].mean()) / df[{c}].std()")
        elif a == "min_max_scale":
            lines.append(f"df[{name + '_scaled'!r}] = (df[{c}] - df[{c}].min()) / (df[{c}].max() - df[{c}].min())")
        elif a not in ("drop_columns", "drop_duplicates"):
            lines.append(f"df = apply_step(df, CleaningStep.from_dict({step.to_dict()!r}))")
            break
    return lines


def _panel_code(p: PanelSpec) -> str:
    fields = {k: v for k, v in p.__dict__.items() if k != "reason"}
    defaults = PanelSpec(p.chart).__dict__
    options = {k: v for k, v in fields.pop("options").items() if k != "score"}
    args = [repr(p.chart)] + [f"{k}={v!r}" for k, v in fields.items() if k != "chart" and v != defaults[k]]
    if options:
        args.append(f"options={options!r}")
    return f"    PanelSpec({', '.join(args)}),"


def to_script(spec: FigureSpec) -> str:
    style = THEMES.get(spec.theme, THEMES["colorblind"])
    polar = [i for i, p in enumerate(spec.panels) if p.chart in REGISTRY and REGISTRY[p.chart].polar]
    cleaning = [line for step in spec.cleaning for line in _step_code(step)]
    needs_numpy = any(s.action in ("log_transform",) for s in spec.cleaning)
    needs_apply = any("apply_step(" in line for line in cleaning)
    out = Path(spec.output).name
    lines = [
        f'"""Recreates {out}. Written by vizdesk {__version__} on {date.today():%Y-%m-%d}.',
        "",
        "Run it with `python " + Path(spec.output).with_suffix(".py").name + "`, or paste the cells into a notebook.",
        "Change the cleaning, the panels or the layout below, then run it again.",
        '"""',
        "",
        "# %% Load the data",
        "import pandas as pd",
        *(["import numpy as np"] if needs_numpy else []),
        "",
        *_load_code(spec),
        "",
        "# %% Clean (the steps you chose in vizdesk, as plain pandas)",
        *(["from vizdesk.cleaning import CleaningStep, apply_step", ""] if needs_apply else []),
        *(cleaning or ["# no cleaning steps"]),
        "",
        "# %% Choose the charts",
        "from vizdesk.spec import PanelSpec",
        "",
        "panels = [",
        *[_panel_code(p) for p in spec.panels],
        "]",
        "",
        "# %% Draw",
        "import matplotlib.pyplot as plt",
        "from vizdesk.charts import REGISTRY",
        "from vizdesk.charts.base import apply_filter",
        "from vizdesk.data import coerce_types, profile",
        "",
        "df = coerce_types(df, profile(df))  # the same text-to-number/date fixes vizdesk makes before drawing",
        f"ROWS, COLS = {spec.rows}, {spec.cols}",
        f"POLAR = {set(polar)!r}  # panels drawn on round (polar) axes" if polar else "POLAR = set()",
        "",
        f"with plt.style.context({style!r}):",
        f"    fig = plt.figure(figsize=({spec.width:g}, {spec.height:g}), dpi={spec.dpi}, layout='constrained')",
        f"    fig.get_layout_engine().set(w_pad={spec.pad / 2 if spec.padding else 0:g}, h_pad={spec.pad / 2 if spec.padding else 0:g}, "
        f"wspace={0.05 if spec.padding else 0}, hspace={0.05 if spec.padding else 0})",
        "    grid = fig.add_gridspec(ROWS, COLS)",
        "    for i, panel in enumerate(panels[: ROWS * COLS]):",
        "        ax = fig.add_subplot(grid[i // COLS, i % COLS], projection='polar' if i in POLAR else None)",
        "        REGISTRY[panel.chart].func(ax, apply_filter(df, panel), panel)",
        *([f"    fig.suptitle({spec.title!r})"] if spec.title else []),
        f"    fig.savefig({out!r}, dpi={spec.dpi}, bbox_inches='tight', pad_inches={spec.pad if spec.padding else 0.02:g})",
        "plt.show()",
        "",
    ]
    return "\n".join(lines)


def script_path_for(image_path: str | Path) -> Path:
    return Path(image_path).with_suffix(".py")
