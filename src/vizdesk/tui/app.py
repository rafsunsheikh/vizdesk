"""The vizdesk terminal UI.

Tabs follow the workflow left to right:
  Data -> Clean -> Suggest -> Compose -> Gallery, plus a Catalog to browse.

The app keeps one working FigureSpec. Suggestions and catalog picks add
panels to it, Compose edits it, Draw renders it, and Gallery reloads any saved
recipe back into Compose so it can be changed and redrawn.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Markdown,
    OptionList,
    Select,
    SelectionList,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)

from vizdesk import catalog
from vizdesk.pipeline import Scan, paginate, scan, scan_all
from vizdesk.render import REGISTRY, THEMES, render_figure, validate_panel
from vizdesk.spec import AGGREGATIONS, FigureSpec, PanelSpec, find_specs, format_options, load_spec, parse_options
from vizdesk.suggest import GOALS, find_target

ROLE_FIELDS = ("x", "y", "hue", "size")


def open_file(path: str | Path) -> None:
    """Open a file with the system viewer (Preview, Photos, xdg-open ...)."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _none(value) -> str | None:
    return None if value in (Select.BLANK, Select.NULL, "", None) else value


class VizDeskApp(App):
    TITLE = "vizdesk"
    SUB_TITLE = "data → clean → suggest → compose → PNG"
    CSS = """
    Screen { layout: vertical; }
    .bar { height: auto; padding: 0 1; }
    .bar > * { margin-right: 1; }
    .bar Input { width: 1fr; }
    .hint { color: $text-muted; padding: 0 1; }
    .title { text-style: bold; padding: 1 1 0 1; }
    DataTable { height: 1fr; }
    #profile { height: 2fr; }
    #data-preview { height: 1fr; }
    #clean-list, #suggest-list { height: 1fr; }
    #clean-why, #suggest-why { height: auto; max-height: 12; border: round $primary; padding: 0 1; }
    #compose-body { height: 1fr; }
    #panel-col { width: 32; }
    #panels { height: 1fr; }
    #panel-buttons { height: 3; }
    #panel-buttons Button { min-width: 4; width: 1fr; margin: 0; }
    #editor { width: 1fr; padding: 0 1; }
    #layout-col { width: 34; padding: 0 1; }
    .field { height: auto; margin-bottom: 0; }
    .field Label { width: 9; padding: 1 0 0 0; }
    .field Input, .field Select { width: 1fr; }
    #columns-list { height: 8; }
    #role-hint { color: $text-muted; height: auto; padding: 0 0 1 0; }
    #status { height: auto; max-height: 6; color: $warning; padding: 0 1; }
    #gallery-body, #catalog-body { height: 1fr; }
    #gallery-table { width: 1fr; }
    #gallery-detail { width: 1fr; padding: 0 1; }
    #catalog-list { width: 40; }
    #catalog-detail { width: 1fr; padding: 0 1; }
    #goal { width: 2fr; }
    #target { width: 1fr; }
    #preview-image { height: 1fr; content-align: center middle; }
    #preview-alt { height: auto; max-height: 10; border: round $primary; padding: 0 1; }
    """
    BINDINGS = [
        Binding("f1", "tab('data')", "Data"),
        Binding("f2", "tab('clean')", "Clean"),
        Binding("f3", "tab('suggest')", "Suggest"),
        Binding("f4", "tab('compose')", "Compose"),
        Binding("f5", "tab('gallery')", "Gallery"),
        Binding("f6", "tab('catalog')", "Catalog"),
        Binding("f7", "tab('preview')", "Preview"),
        Binding("ctrl+d", "draw", "Draw PNG"),
        Binding("ctrl+o", "open_image", "Open PNG"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, path: str | None = None, out_dir: str = "vizdesk-output") -> None:
        super().__init__()
        import matplotlib

        matplotlib.use("Agg")  # figures are drawn in worker threads and only saved to files
        self.initial_path = path
        self.out_dir = Path(out_dir).expanduser()
        self.scans: list[Scan] = []
        self.current: Scan | None = None
        self.figure: FigureSpec | None = None
        self.panel_index = 0
        self.suggestions: list[PanelSpec] = []
        self._catalog_keys: list[str] = []
        self._gallery_paths: list[Path] = []

    # ------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="data"):
            with TabPane("Data", id="data"):
                with Horizontal(classes="bar"):
                    yield Input(placeholder="Path to a CSV / Excel file or a folder (e.g. ~/Downloads/sales.xlsx)", id="path")
                    yield Button("Load", id="load", variant="primary")
                with Horizontal(classes="bar"):
                    yield Label("Table:", classes="hint")
                    yield Select([], id="table", prompt="load a file first", allow_blank=True)
                yield Static("", id="data-summary", classes="hint")
                yield DataTable(id="profile", cursor_type="row", zebra_stripes=True)
                yield DataTable(id="data-preview", zebra_stripes=True)
            with TabPane("Clean", id="clean"):
                yield Static("Tick the steps to apply. 'safe' steps only fix how values are stored and are ticked for you. "
                             "Steps re-run from the raw file, so unticking undoes them.", classes="hint")
                yield SelectionList(id="clean-list")
                yield Markdown("", id="clean-why")
                with Horizontal(classes="bar"):
                    yield Button("Apply ticked steps", id="clean-apply", variant="primary")
                    yield Button("Tick safe only", id="clean-safe")
                    yield Button("Untick all", id="clean-none")
            with TabPane("Suggest", id="suggest"):
                with Horizontal(classes="bar"):
                    yield Label("Goal:", classes="hint")
                    yield Select([(f"{g.label}: {g.question}", g.key) for g in GOALS], id="goal", value="explore", allow_blank=False)
                    yield Label("Target:", classes="hint")
                    yield Select([], id="target", prompt="auto (guess from names)")
                    yield Button("Auto scan", id="suggest-run", variant="primary")
                yield SelectionList(id="suggest-list")
                yield Markdown("", id="suggest-why")
                with Horizontal(classes="bar"):
                    yield Button("Add ticked to figure", id="suggest-add", variant="primary")
                    yield Button("Auto draw all ticked", id="suggest-draw", variant="success")
                    yield Button("Tick all", id="suggest-all")
            with TabPane("Compose", id="compose"):
                with Horizontal(id="compose-body"):
                    with Vertical(id="panel-col"):
                        yield Static("Panels (in grid order)", classes="title")
                        yield OptionList(id="panels")
                        with Horizontal(id="panel-buttons"):
                            yield Button("+", id="panel-add", tooltip="add an empty panel")
                            yield Button("⧉", id="panel-copy", tooltip="duplicate panel")
                            yield Button("↑", id="panel-up")
                            yield Button("↓", id="panel-down")
                            yield Button("✕", id="panel-del", variant="error")
                    with VerticalScroll(id="editor"):
                        yield Static("Panel settings", classes="title")
                        yield self._field("Chart", Select(self._chart_options(), id="f-chart", allow_blank=False, value="histogram"))
                        yield Static("", id="role-hint")
                        for role in ROLE_FIELDS:
                            yield self._field(role, Select([], id=f"f-{role}", prompt="(none)"))
                        yield Static("columns (multi-column charts: radar, heatmaps, scatter matrix, dumbbell, OHLC, gantt)", classes="hint")
                        yield SelectionList(id="columns-list")
                        yield self._field("agg", Select([(a, a) for a in AGGREGATIONS], id="f-agg", allow_blank=False, value="auto"))
                        yield self._field("title", Input(id="f-title", placeholder="automatic"))
                        yield self._field("top N", Input(id="f-top_n", type="integer", value="15"))
                        yield self._field("bins", Input(id="f-bins", type="integer", value="30"))
                        yield self._field("options", Input(id="f-options", placeholder="key=value; key=value (e.g. filter=Name=AAPL)"))
                        with Horizontal(classes="field"):
                            yield Label("log y")
                            yield Switch(id="f-log_y")
                    with VerticalScroll(id="layout-col"):
                        yield Static("Figure layout", classes="title")
                        yield self._field("rows", Input(id="l-rows", type="integer", value="2"))
                        yield self._field("cols", Input(id="l-cols", type="integer", value="2"))
                        yield self._field("width in", Input(id="l-width", type="number", value="12"))
                        yield self._field("height in", Input(id="l-height", type="number", value="9"))
                        yield self._field("dpi", Input(id="l-dpi", type="integer", value="150"))
                        with Horizontal(classes="field"):
                            yield Label("padding")
                            yield Switch(id="l-padding", value=True)
                        yield self._field("pad in", Input(id="l-pad", type="number", value="0.3"))
                        yield self._field("theme", Select([(t, t) for t in THEMES], id="l-theme", allow_blank=False, value="colorblind"))
                        yield self._field("title", Input(id="l-title", placeholder="figure title"))
                        yield self._field("save as", Input(id="l-output"))
                        yield Static("", id="pixels", classes="hint")
                        yield Button("Draw PNG  (ctrl+d)", id="draw", variant="success")
                        yield Button("Open PNG  (ctrl+o)", id="open")
                        yield Button("New figure", id="new-figure")
                yield Static("", id="status")
            with TabPane("Gallery", id="gallery"):
                with Horizontal(classes="bar"):
                    yield Input(id="gallery-dir", placeholder="output folder")
                    yield Button("Refresh", id="gallery-refresh")
                with Horizontal(id="gallery-body"):
                    yield DataTable(id="gallery-table", cursor_type="row", zebra_stripes=True)
                    with Vertical(id="gallery-detail"):
                        yield Markdown("Pick a figure.", id="gallery-info")
                        with Horizontal(classes="bar"):
                            yield Button("Edit & redraw", id="gallery-edit", variant="primary")
                            yield Button("Open PNG", id="gallery-open")
            with TabPane("Catalog", id="catalog"):
                with Horizontal(classes="bar"):
                    yield Input(placeholder="search, e.g. 'part whole' or 'outliers'", id="catalog-search")
                    yield Select([(c, c) for c in catalog.categories()], id="catalog-category", prompt="all categories")
                    yield Label("drawable only", classes="hint")
                    yield Switch(id="catalog-drawable")
                with Horizontal(id="catalog-body"):
                    yield OptionList(id="catalog-list")
                    with VerticalScroll(id="catalog-detail"):
                        yield Markdown("", id="catalog-info")
                        yield Button("Use this chart in a new panel", id="catalog-use", variant="primary")
            with TabPane("Preview", id="preview"):
                with Horizontal(classes="bar"):
                    yield Static("Nothing drawn yet.", id="preview-name", classes="hint")
                    yield Button("Open full size", id="preview-open")
                yield Static("", id="preview-image")
                yield Markdown("", id="preview-alt")
        yield Footer()

    def _quiet(self):
        """Change widgets from code without their Changed events feeding back into the figure."""
        return self.prevent(Select.Changed, Input.Changed, Switch.Changed, SelectionList.SelectedChanged,
                            OptionList.OptionHighlighted)

    @staticmethod
    def _field(label: str, widget) -> Horizontal:
        return Horizontal(Label(label), widget, classes="field")

    @staticmethod
    def _chart_options() -> list[tuple[str, str]]:
        names = {c.key: c.name for c in catalog.all_charts()}
        return sorted(((f"{names.get(k, k)}  ({k})", k) for k in REGISTRY), key=lambda t: t[0].lower())

    def on_mount(self) -> None:
        self.query_one("#gallery-dir", Input).value = str(self.out_dir)
        self.query_one("#l-output", Input).value = str(self.out_dir / "figure-01.png")
        for table_id, cols in {
            "profile": ("column", "kind", "missing %", "unique", "range / top values", "notes"),
            "gallery-table": ("figure", "panels", "grid", "size px", "source"),
        }.items():
            self.query_one(f"#{table_id}", DataTable).add_columns(*cols)
        self._refresh_catalog()
        self._refresh_gallery()
        if self.initial_path:
            self.query_one("#path", Input).value = self.initial_path
            self.load_path(self.initial_path)

    def action_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

    def status(self, text: str, error: bool = False) -> None:
        self.query_one("#status", Static).update(text)
        self.notify(text, severity="error" if error else "information", timeout=6)

    # ------------------------------------------------------------ Data tab

    @on(Button.Pressed, "#load")
    @on(Input.Submitted, "#path")
    def _load_clicked(self) -> None:
        path = self.query_one("#path", Input).value.strip()
        if path:
            self.load_path(path)

    @work(thread=True, exclusive=True, group="load")
    def load_path(self, path: str) -> None:
        self.call_from_thread(self.notify, f"Scanning {path} ...")
        try:
            scans = scan_all(path, apply_safe=True)
        except Exception as exc:  # shown to the user, not raised
            self.call_from_thread(self.notify, f"Could not load: {exc}", severity="error")
            return
        if not scans:
            self.call_from_thread(self.notify, "No CSV or Excel files found there.", severity="warning")
            return
        self.call_from_thread(self._scans_loaded, scans)

    def _scans_loaded(self, scans: list[Scan]) -> None:
        self.scans = scans
        table = self.query_one("#table", Select)
        with self._quiet():
            table.set_options([(s.name, i) for i, s in enumerate(scans)])
            table.value = 0
        self.select_table(0)
        self.notify(f"Loaded {len(scans)} table(s). Safe cleaning applied; see the Clean tab.")

    @on(Select.Changed, "#table")
    def _table_changed(self, event: Select.Changed) -> None:
        if _none(event.value) is not None and self.scans[int(event.value)] is not self.current:
            self.select_table(int(event.value))

    def select_table(self, index: int) -> None:
        self.current = self.scans[index]
        self.new_figure()
        self._refresh_data()
        self._refresh_clean()
        self.run_suggestions()

    def _refresh_data(self) -> None:
        s = self.current
        if s is None:
            return
        p = s.profile
        self.query_one("#data-summary", Static).update(
            f"{s.source}  {('sheet ' + s.sheet) if s.sheet else ''}  |  {p.rows} rows × {len(p.columns)} columns  |  "
            f"{p.duplicate_rows} duplicate rows  |  {len(s.applied)} cleaning step(s) applied"
        )
        prof = self.query_one("#profile", DataTable)
        prof.clear()
        for c in p.columns:
            notes = []
            if c.outlier_pct:
                notes.append(f"{c.outlier_pct:g}% outliers")
            if c.skew is not None and abs(c.skew) > 1:
                notes.append(f"skew {c.skew:.1f}")
            if c.case_variants:
                notes.append(f"{c.case_variants} case variants")
            prof.add_row(c.name, c.kind, f"{c.missing_pct:g}", str(c.unique), c.summary[:45], ", ".join(notes))
        prev = self.query_one("#data-preview", DataTable)
        prev.clear(columns=True)
        head = s.data.head(50)
        prev.add_columns(*[str(c) for c in head.columns])
        for row in head.itertuples(index=False):
            prev.add_row(*["" if pd.isna(v) else str(v)[:40] for v in row])
        self._refresh_column_choices()

    # ------------------------------------------------------------ Clean tab

    def _refresh_clean(self) -> None:
        s = self.current
        lst = self.query_one("#clean-list", SelectionList)
        lst.clear_options()
        if s is None:
            return
        applied = {a.id for a in s.applied}
        lst.add_options([(f"{'SAFE' if st.safe else 'ask '}  {st.title}", i, st.id in applied) for i, st in enumerate(s.cleaning)])
        self.query_one("#clean-why", Markdown).update(
            "No cleaning needed: no type, gap, duplicate or scale problems found." if not s.cleaning else "Highlight a step to see why it is suggested."
        )

    @on(SelectionList.SelectionHighlighted, "#clean-list")
    def _clean_highlight(self, event: SelectionList.SelectionHighlighted) -> None:
        if self.current:
            step = self.current.cleaning[event.selection.value]
            self.query_one("#clean-why", Markdown).update(f"**{step.title}**\n\n{step.reason}")

    @on(Button.Pressed, "#clean-safe")
    def _clean_safe(self) -> None:
        lst = self.query_one("#clean-list", SelectionList)
        lst.deselect_all()
        for i, st in enumerate(self.current.cleaning if self.current else []):
            if st.safe:
                lst.select(i)

    @on(Button.Pressed, "#clean-none")
    def _clean_none(self) -> None:
        self.query_one("#clean-list", SelectionList).deselect_all()

    @on(Button.Pressed, "#clean-apply")
    def _clean_apply(self) -> None:
        if not self.current:
            return
        ticked = sorted(self.query_one("#clean-list", SelectionList).selected)
        self.current.apply([self.current.cleaning[i] for i in ticked])
        if self.figure:
            self.figure.cleaning = list(self.current.applied)
        self._refresh_data()
        self.run_suggestions()
        self.notify(f"Applied {len(ticked)} cleaning step(s). Profile and suggestions updated.")

    # ------------------------------------------------------------ Suggest tab

    @on(Button.Pressed, "#suggest-run")
    @on(Select.Changed, "#goal, #target")
    def run_suggestions(self) -> None:
        if not self.current:
            return
        goal = self.query_one("#goal", Select).value
        target = _none(self.query_one("#target", Select).value)
        self.suggestions = self.current.suggestions(goal, limit=16, target=target)
        found = find_target(self.current.profile, self.current.data, target)
        self.query_one("#target", Select).prompt = f"auto: {found.column}" if found and not target else "auto (none found)"
        lst = self.query_one("#suggest-list", SelectionList)
        lst.clear_options()
        lst.add_options([(f"{p.options.get('score', ''):>3}  {p.chart:<26} {p.label().split('(', 1)[1].rstrip(')')}", i, i < 4)
                         for i, p in enumerate(self.suggestions)])
        self.query_one("#suggest-why", Markdown).update(
            f"{len(self.suggestions)} suggestion(s); the top 4 are ticked. Highlight one to see why."
            if self.suggestions else "Nothing fits this goal with these columns. Try **Explore everything**."
        )

    @on(SelectionList.SelectionHighlighted, "#suggest-list")
    def _suggest_highlight(self, event: SelectionList.SelectionHighlighted) -> None:
        p = self.suggestions[event.selection.value]
        info = catalog.get(p.chart) if p.chart in {c.key for c in catalog.all_charts()} else None
        text = f"**{info.name if info else p.chart}** ({p.label()})\n\n**Why:** {p.reason}"
        if info and info.use_when:
            text += f"\n\n**Use it when:** {info.use_when}"
        self.query_one("#suggest-why", Markdown).update(text)

    def _ticked_suggestions(self) -> list[PanelSpec]:
        ticked = sorted(self.query_one("#suggest-list", SelectionList).selected)
        return [PanelSpec.from_dict(dict(self.suggestions[i].__dict__)) for i in ticked]

    @on(Button.Pressed, "#suggest-all")
    def _suggest_all(self) -> None:
        self.query_one("#suggest-list", SelectionList).select_all()

    @on(Button.Pressed, "#suggest-add")
    def _suggest_add(self) -> None:
        panels = self._ticked_suggestions()
        if not panels or not self.figure:
            return
        self.figure.panels = [p for p in self.figure.panels if p.x or p.y or p.columns or p.chart == "missing_values_map"]
        self.figure.panels += panels
        self._grow_grid()
        self.panel_index = len(self.figure.panels) - len(panels)
        self._load_figure_into_form()
        self.action_tab("compose")
        self.notify(f"Added {len(panels)} panel(s). Adjust them here, then press ctrl+d to draw.")

    @on(Button.Pressed, "#suggest-draw")
    def _suggest_draw(self) -> None:
        panels = self._ticked_suggestions()
        if not panels or not self.current or not self.figure:
            return
        self._read_layout()
        template = self.figure
        per = template.rows * template.cols
        stem = Path(template.output).with_suffix("")
        specs = []
        for page, chunk in enumerate(paginate(panels, per), start=1):
            spec = FigureSpec.from_dict(template.to_dict())
            spec.panels = chunk
            spec.output = f"{stem}-auto-{page:02d}{Path(template.output).suffix or '.png'}"
            specs.append(spec)
        self.draw_specs(specs)

    # ------------------------------------------------------------ Compose tab

    def new_figure(self) -> None:
        if not self.current:
            return
        n = len(list(self.out_dir.glob(f"{self.current.name}-*.png"))) + 1
        layout = self.figure
        self.figure = FigureSpec(
            source=str(self.current.source), sheet=self.current.sheet, cleaning=list(self.current.applied),
            panels=[PanelSpec("histogram")], output=str(self.out_dir / f"{self._slug(self.current.name)}-{n:02d}.png"),
            rows=2, cols=2, width=12, height=9,
        )
        if layout:  # keep the user's layout choices across new figures
            for k in ("rows", "cols", "width", "height", "dpi", "padding", "pad", "theme"):
                setattr(self.figure, k, getattr(layout, k))
        self.panel_index = 0
        self._load_figure_into_form()

    @staticmethod
    def _slug(text: str) -> str:
        import re

        return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower() or "figure"

    @on(Button.Pressed, "#new-figure")
    def _new_figure_clicked(self) -> None:
        self.new_figure()
        self.notify("Started a new figure. The previous one is still in the Gallery if you drew it.")

    def _grow_grid(self) -> None:
        f = self.figure
        if f and f.rows * f.cols < len(f.panels):
            f.fit_grid()

    def _refresh_column_choices(self) -> None:
        if not self.current:
            return
        options = [(f"{c.name}  [{c.kind}]", c.name) for c in self.current.profile.columns]
        targets = [(f"{c.name}  [{c.kind}]", c.name) for c in self.current.profile.columns
                   if (c.is_category and c.unique <= 10) or c.is_measure]
        with self._quiet():
            self.query_one("#target", Select).set_options(targets)
            for role in ROLE_FIELDS:
                self.query_one(f"#f-{role}", Select).set_options(options)
        self._load_panel_into_editor()

    def _refresh_panel_list(self) -> None:
        f = self.figure
        with self._quiet():
            self._fill_panel_list(f)

    def _fill_panel_list(self, f: FigureSpec | None) -> None:
        lst = self.query_one("#panels", OptionList)
        lst.clear_options()
        if not f:
            return
        df = self.current.data if self.current else None
        for i, p in enumerate(f.panels):
            ok = "" if df is None or not validate_panel(df, p) else " ⚠"
            lst.add_option(f"{i + 1}. {p.label()}{ok}")
        if f.panels:
            self.panel_index = min(self.panel_index, len(f.panels) - 1)
            lst.highlighted = self.panel_index

    def _load_figure_into_form(self) -> None:
        f = self.figure
        if not f:
            return
        with self._quiet():
            for key in ("rows", "cols", "width", "height", "dpi", "pad"):
                self.query_one(f"#l-{key}", Input).value = f"{getattr(f, key):g}"
            self.query_one("#l-padding", Switch).value = f.padding
            self.query_one("#l-theme", Select).value = f.theme if f.theme in THEMES else "colorblind"
            self.query_one("#l-title", Input).value = f.title
            self.query_one("#l-output", Input).value = f.output
        self._update_pixels()
        self._refresh_panel_list()
        self._load_panel_into_editor()

    def _panel(self) -> PanelSpec | None:
        f = self.figure
        if not f or not f.panels:
            return None
        return f.panels[min(self.panel_index, len(f.panels) - 1)]

    def _load_panel_into_editor(self) -> None:
        p = self._panel()
        if p is None:
            return
        with self._quiet():
            if p.chart in REGISTRY:
                self.query_one("#f-chart", Select).value = p.chart
            columns = {c.name for c in self.current.profile.columns} if self.current else set()
            for role in ROLE_FIELDS:
                sel = self.query_one(f"#f-{role}", Select)
                value = getattr(p, role)
                if value in columns:
                    sel.value = value
                else:
                    sel.clear()
            self.query_one("#f-agg", Select).value = p.agg if p.agg in AGGREGATIONS else "auto"
            self.query_one("#f-title", Input).value = p.title
            self.query_one("#f-top_n", Input).value = str(p.top_n)
            self.query_one("#f-bins", Input).value = str(p.bins)
            options = self.query_one("#f-options", Input)
            options.value = format_options(p.options)
            hint = REGISTRY[p.chart].options if p.chart in REGISTRY else ""
            options.placeholder = f"e.g. {hint}" if hint else "filter=column=value (keeps matching rows)"
            self.query_one("#f-log_y", Switch).value = p.log_y
            cols = self.query_one("#columns-list", SelectionList)
            cols.clear_options()
            if self.current:
                numeric_first = sorted(self.current.profile.columns, key=lambda c: (c.kind != "numeric", c.name))
                cols.add_options([(f"{c.name} [{c.kind}]", c.name, c.name in p.columns) for c in numeric_first])
        self._update_role_hint()

    def _update_role_hint(self) -> None:
        p = self._panel()
        if p is None or p.chart not in REGISTRY:
            return
        r = REGISTRY[p.chart]
        roles = ", ".join(f"{role}={kind}{'' if req else ' (optional)'}" for role, (kind, req) in r.roles.items()) or "no columns needed"
        problems = validate_panel(self.current.data, p) if self.current else []
        text = f"{r.hint}\nUses: {roles}" + (f"\nOptions: {r.options}" if r.options else "")
        if problems:
            text += "\n⚠ " + " ".join(problems)
        self.query_one("#role-hint", Static).update(text)

    @on(OptionList.OptionHighlighted, "#panels")
    def _panel_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_index == self.panel_index:
            return
        self.panel_index = event.option_index
        self._load_panel_into_editor()

    def _panel_changed(self) -> None:
        """Something in the editor changed: refresh the list label and hint."""
        with self._quiet():
            lst = self.query_one("#panels", OptionList)
            p = self._panel()
            if p is not None:
                df = self.current.data if self.current else None
                warn = "" if df is None or not validate_panel(df, p) else " ⚠"
                lst.replace_option_prompt_at_index(self.panel_index, f"{self.panel_index + 1}. {p.label()}{warn}")
        self._update_role_hint()

    @on(Select.Changed, "#f-chart, #f-x, #f-y, #f-hue, #f-size, #f-agg")
    def _editor_select(self, event: Select.Changed) -> None:
        p = self._panel()
        if p is None:
            return
        field = event.select.id.removeprefix("f-")
        setattr(p, field, _none(event.value) if field in ROLE_FIELDS else event.value)
        self._panel_changed()

    @on(Input.Changed, "#f-title, #f-top_n, #f-bins, #f-options")
    def _editor_input(self, event: Input.Changed) -> None:
        p = self._panel()
        if p is None:
            return
        field = event.input.id.removeprefix("f-")
        if field == "title":
            p.title = event.value
        elif field == "options":
            p.options = {**{k: v for k, v in p.options.items() if k == "score"}, **parse_options(event.value)}
        elif event.value.strip().lstrip("-").isdigit():
            setattr(p, field, max(int(event.value), 1))
        self._panel_changed()

    @on(Switch.Changed, "#f-log_y")
    def _editor_switch(self, event: Switch.Changed) -> None:
        p = self._panel()
        if p is not None:
            p.log_y = event.value

    @on(SelectionList.SelectedChanged, "#columns-list")
    def _editor_columns(self, event: SelectionList.SelectedChanged) -> None:
        p = self._panel()
        if p is None:
            return
        chosen = set(event.selection_list.selected)
        p.columns = [c for c in p.columns if c in chosen] + [c for c in event.selection_list.selected if c not in p.columns]
        self._panel_changed()

    @on(Button.Pressed, "#panel-add")
    def _panel_add(self) -> None:
        if not self.figure:
            return
        self.figure.panels.append(PanelSpec("histogram"))
        self._grow_grid()
        self.panel_index = len(self.figure.panels) - 1
        self._load_figure_into_form()

    @on(Button.Pressed, "#panel-copy")
    def _panel_copy(self) -> None:
        p = self._panel()
        if p is None:
            return
        self.figure.panels.insert(self.panel_index + 1, PanelSpec.from_dict(dict(p.__dict__, columns=list(p.columns), options=dict(p.options))))
        self._grow_grid()
        self.panel_index += 1
        self._load_figure_into_form()

    @on(Button.Pressed, "#panel-del")
    def _panel_del(self) -> None:
        if self.figure and self.figure.panels:
            self.figure.panels.pop(self.panel_index)
            self.panel_index = max(self.panel_index - 1, 0)
            self._load_figure_into_form()

    @on(Button.Pressed, "#panel-up, #panel-down")
    def _panel_move(self, event: Button.Pressed) -> None:
        f, i = self.figure, self.panel_index
        j = i - 1 if event.button.id == "panel-up" else i + 1
        if f and 0 <= j < len(f.panels):
            f.panels[i], f.panels[j] = f.panels[j], f.panels[i]
            self.panel_index = j
            self._refresh_panel_list()

    @on(Input.Changed, "#l-width, #l-height, #l-dpi")
    def _update_pixels(self) -> None:
        try:
            w, h = float(self.query_one("#l-width", Input).value), float(self.query_one("#l-height", Input).value)
            dpi = int(self.query_one("#l-dpi", Input).value)
            self.query_one("#pixels", Static).update(f"≈ {int(w * dpi)} × {int(h * dpi)} pixels")
        except ValueError:
            pass

    def _read_layout(self) -> bool:
        f = self.figure
        if not f:
            return False
        try:
            f.rows = max(int(self.query_one("#l-rows", Input).value), 1)
            f.cols = max(int(self.query_one("#l-cols", Input).value), 1)
            f.width = max(float(self.query_one("#l-width", Input).value), 1.0)
            f.height = max(float(self.query_one("#l-height", Input).value), 1.0)
            f.dpi = min(max(int(self.query_one("#l-dpi", Input).value), 50), 600)
            f.pad = max(float(self.query_one("#l-pad", Input).value), 0.0)
        except ValueError:
            self.status("Layout values must be numbers.", error=True)
            return False
        f.padding = self.query_one("#l-padding", Switch).value
        f.theme = self.query_one("#l-theme", Select).value
        f.title = self.query_one("#l-title", Input).value
        f.output = self.query_one("#l-output", Input).value.strip() or str(self.out_dir / "figure.png")
        if f.rows * f.cols < len(f.panels):
            self.notify(f"{len(f.panels)} panels do not fit {f.rows}×{f.cols}; the grid will grow to fit.", severity="warning")
        return True

    @on(Button.Pressed, "#draw")
    def action_draw(self) -> None:
        if not self.figure or not self.current:
            self.status("Load a file first (F1).", error=True)
            return
        if not self.figure.panels:
            self.status("Add at least one panel.", error=True)
            return
        if self._read_layout():
            self.draw_specs([self.figure])

    @work(thread=True, exclusive=True, group="draw")
    def draw_specs(self, specs: list[FigureSpec]) -> None:
        data = self.current.data
        messages = []
        for spec in specs:
            try:
                r = render_figure(data, spec)
            except Exception as exc:
                self.call_from_thread(self.status, f"Drawing failed: {exc}", True)
                return
            messages.append(f"Saved {r.path}" + (f"  ({len(r.warnings)} panel warning(s): " + " | ".join(r.warnings) + ")" if r.warnings else ""))
        self.call_from_thread(self._drawn, messages, specs[-1])

    def _drawn(self, messages: list[str], last: FigureSpec) -> None:
        self.query_one("#status", Static).update("\n".join(messages))
        self.notify(messages[-1] if len(messages) == 1 else f"Saved {len(messages)} figures.", timeout=6)
        self._last_output = last.output
        self.set_preview(Path(last.output))
        self.query_one("#l-output", Input).value = self.figure.output if self.figure else last.output
        self._refresh_gallery()
        self._refresh_panel_list()

    @on(Button.Pressed, "#open")
    def action_open_image(self) -> None:
        path = Path(getattr(self, "_last_output", "") or (self.figure.output if self.figure else ""))
        if path.is_file():
            open_file(path)
        else:
            self.status("Nothing drawn yet. Press ctrl+d first.", error=True)

    # ------------------------------------------------------------ Gallery tab

    @on(Button.Pressed, "#gallery-refresh")
    @on(Input.Submitted, "#gallery-dir")
    def _refresh_gallery(self) -> None:
        folder = Path(self.query_one("#gallery-dir", Input).value or self.out_dir).expanduser()
        table = self.query_one("#gallery-table", DataTable)
        table.clear()
        self._gallery_paths = []
        for spec_path in find_specs(folder) if folder.is_dir() else []:
            try:
                spec = load_spec(spec_path)
            except Exception:
                continue
            w, h = spec.pixel_size
            table.add_row(Path(spec.output).name, str(len(spec.panels)), f"{spec.rows}×{spec.cols}", f"{w}×{h}",
                          Path(spec.source).name + (f" / {spec.sheet}" if spec.sheet else ""))
            self._gallery_paths.append(spec_path)

    def _gallery_selected(self) -> Path | None:
        table = self.query_one("#gallery-table", DataTable)
        if not self._gallery_paths or table.cursor_row is None or table.cursor_row >= len(self._gallery_paths):
            return None
        return self._gallery_paths[table.cursor_row]

    @on(DataTable.RowHighlighted, "#gallery-table")
    def _gallery_highlight(self) -> None:
        path = self._gallery_selected()
        if not path:
            return
        spec = load_spec(path)
        lines = [f"### {Path(spec.output).name}", f"Source: `{spec.source}`" + (f" sheet `{spec.sheet}`" if spec.sheet else ""),
                 f"Grid {spec.rows}×{spec.cols}, {spec.width:g}×{spec.height:g} in at {spec.dpi} dpi, "
                 f"padding {'on' if spec.padding else 'off'}, theme {spec.theme}",
                 f"Cleaning: {', '.join(s.title for s in spec.cleaning) or 'none'}", "", "**Panels:**"]
        lines += [f"{i}. {p.label()}" for i, p in enumerate(spec.panels, 1)]
        self.query_one("#gallery-info", Markdown).update("\n".join(lines))
        self.set_preview(Path(spec.output))

    @on(Button.Pressed, "#gallery-open")
    def _gallery_open(self) -> None:
        path = self._gallery_selected()
        if path:
            image = Path(load_spec(path).output)
            if image.is_file():
                open_file(image)
            else:
                self.status(f"The image {image} is missing; use Edit & redraw to recreate it.", error=True)

    @on(Button.Pressed, "#gallery-edit")
    @on(DataTable.RowSelected, "#gallery-table")
    def _gallery_edit(self) -> None:
        path = self._gallery_selected()
        if path:
            self.edit_spec(path)

    @work(thread=True, exclusive=True, group="load")
    def edit_spec(self, path: Path) -> None:
        try:
            spec = load_spec(path)
            s = scan(spec.source, spec.sheet)
            s.cleaning = s.cleaning + [c for c in spec.cleaning if c.id not in {x.id for x in s.cleaning}]
            s.apply(spec.cleaning)
        except Exception as exc:
            self.call_from_thread(self.status, f"Could not reopen the source data: {exc}", True)
            return
        self.call_from_thread(self._spec_loaded, s, spec)

    def _spec_loaded(self, s: Scan, spec: FigureSpec) -> None:
        if s.source not in {x.source for x in self.scans} or s.sheet not in {x.sheet for x in self.scans if x.source == s.source}:
            self.scans.append(s)
        else:
            idx = next(i for i, x in enumerate(self.scans) if x.source == s.source and x.sheet == s.sheet)
            self.scans[idx] = s
        self.current = s
        table = self.query_one("#table", Select)
        with self._quiet():
            table.set_options([(x.name, i) for i, x in enumerate(self.scans)])
            table.value = self.scans.index(s)
        self.figure = spec
        self.panel_index = 0
        self._refresh_data()
        self._refresh_clean()
        self._load_figure_into_form()
        self.action_tab("compose")
        self.notify("Loaded the figure recipe. Change anything, then ctrl+d redraws it to the same file "
                    "(edit 'save as' to keep both).")

    # ------------------------------------------------------------ Catalog tab

    @on(Input.Changed, "#catalog-search")
    @on(Select.Changed, "#catalog-category")
    @on(Switch.Changed, "#catalog-drawable")
    def _refresh_catalog(self) -> None:
        text = self.query_one("#catalog-search", Input).value
        category = _none(self.query_one("#catalog-category", Select).value)
        drawable = self.query_one("#catalog-drawable", Switch).value
        charts = catalog.search(text, category, drawable)
        lst = self.query_one("#catalog-list", OptionList)
        lst.clear_options()
        lst.add_options([f"{'●' if c.renderable else '○'} {c.name}" for c in charts])
        self._catalog_keys = [c.key for c in charts]
        self.query_one("#catalog-info", Markdown).update(
            f"{len(charts)} techniques. ● = vizdesk can draw it, ○ = listed for reference." if charts else "No match."
        )

    @on(OptionList.OptionHighlighted, "#catalog-list")
    def _catalog_highlight(self, event: OptionList.OptionHighlighted) -> None:
        key = self._catalog_keys[event.option_index]
        self.query_one("#catalog-info", Markdown).update(catalog.get(key).to_markdown())
        self.query_one("#catalog-use", Button).disabled = key not in REGISTRY

    @on(Button.Pressed, "#catalog-use")
    def _catalog_use(self) -> None:
        idx = self.query_one("#catalog-list", OptionList).highlighted
        if idx is None or not self.figure:
            self.status("Load a file first (F1), then pick a chart.", error=True)
            return
        self.figure.panels.append(PanelSpec(self._catalog_keys[idx]))
        self._grow_grid()
        self.panel_index = len(self.figure.panels) - 1
        self._load_figure_into_form()
        self.action_tab("compose")
        self.notify("Added. Now choose its columns.")


    # ------------------------------------------------------------ Preview tab

    def set_preview(self, image: Path) -> None:
        """Remember which image to preview; draw it now if the Preview tab is showing."""
        self._preview_path = image
        name = self.query_one("#preview-name", Static)
        alt = image.with_suffix(".alt.txt")
        script = image.with_suffix(".py")
        name.update(f"{image}" + (f"   script: {script.name}" if script.is_file() else ""))
        self.query_one("#preview-alt", Markdown).update(
            "**Alt text** (also saved as " + f"`{alt.name}` and inside the PNG)\n\n" + alt.read_text(encoding="utf-8")
            if alt.is_file() else "")
        if self.query_one(TabbedContent).active == "preview":
            self._paint_preview()

    @on(TabbedContent.TabActivated)
    def _tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id == "preview":
            self.call_after_refresh(self._paint_preview)

    def on_resize(self) -> None:
        if self.query_one(TabbedContent).active == "preview":
            self.call_after_refresh(self._paint_preview)

    def _paint_preview(self) -> None:
        from vizdesk.preview import rich_blocks

        image = getattr(self, "_preview_path", None)
        target = self.query_one("#preview-image", Static)
        if not image or not Path(image).is_file():
            target.update("Draw a figure (ctrl+d) or pick one in the Gallery to preview it here.")
            return
        size = target.size
        target.update(rich_blocks(image, max(size.width, 20), max(size.height, 8)))

    @on(Button.Pressed, "#preview-open")
    def _preview_open(self) -> None:
        image = getattr(self, "_preview_path", None)
        if image and Path(image).is_file():
            open_file(image)


def run(path: str | None = None, out_dir: str = "vizdesk-output") -> None:
    VizDeskApp(path, out_dir).run()
