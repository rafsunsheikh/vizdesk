"""Command line entry point. With no command, opens the TUI."""

from __future__ import annotations

import argparse
import sys

from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from vizdesk import __version__, catalog
from vizdesk.render import AGG_HELP, THEMES
from vizdesk.spec import AGGREGATIONS, FigureSpec, PanelSpec, load_spec
from vizdesk.suggest import GOAL_KEYS, GOALS

console = Console()


def _add_layout_args(p: argparse.ArgumentParser, defaults: bool = True) -> None:
    d = (lambda v: v) if defaults else (lambda v: None)
    g = p.add_argument_group("figure layout")
    g.add_argument("--rows", type=int, default=d(2), help="panels per column of the grid")
    g.add_argument("--cols", type=int, default=d(2), help="panels per row of the grid")
    g.add_argument("--width", type=float, default=d(12.0), help="figure width in inches")
    g.add_argument("--height", type=float, default=d(9.0), help="figure height in inches")
    g.add_argument("--dpi", type=int, default=d(150), help="dots per inch (pixels = inches x dpi)")
    g.add_argument("--padding", dest="padding", action="store_true", default=d(True), help="space between panels (default)")
    g.add_argument("--no-padding", dest="padding", action="store_false", help="pack panels edge to edge")
    g.add_argument("--pad", type=float, default=d(0.3), help="padding size in inches")
    g.add_argument("--theme", choices=list(THEMES), default=d("colorblind"), help="colours (default colorblind: safe for red-green colour blindness)")
    g.add_argument("--title", default=d(""), help="title over the whole figure")
    p.add_argument("--show", action="store_true", help="preview each figure in the terminal after drawing it")


def _parse_panel(text: str) -> PanelSpec:
    """'chart=bar_chart,x=region,y=revenue,columns=a+b' -> PanelSpec."""
    fields = _parse_fields(text)
    if "chart" not in fields:
        raise SystemExit("every --panel needs chart=<key>. See `vizdesk catalog --drawable`.")
    return PanelSpec.from_dict(fields)


def _parse_fields(text: str) -> dict:
    """Only the fields written in `text`; 'hue=' (empty) clears a field.
    Keys that are not panel fields (reversal=2%, filter=Name=AAPL, geojson=...) become options."""
    fields: dict = {}
    known = set(PanelSpec.__dataclass_fields__)
    for part in text.split(","):
        if "=" not in part:
            raise SystemExit(f"bad --panel part '{part}'. Use key=value pairs, e.g. chart=bar_chart,x=region")
        k, v = (s.strip() for s in part.split("=", 1))
        if k == "columns":
            fields[k] = [c for c in v.split("+") if c]
        elif k in ("top_n", "bins"):
            fields[k] = int(v)
        elif k == "log_y":
            fields[k] = v.lower() in ("1", "true", "yes")
        elif k not in known:
            fields.setdefault("options", {})[k] = v
        else:
            fields[k] = v or None
    return fields


# ---------------------------------------------------------------- commands


def cmd_catalog(a: argparse.Namespace) -> None:
    if a.show:
        try:
            console.print(Markdown(catalog.get(a.show).to_markdown()))
        except KeyError:
            raise SystemExit(f"unknown chart '{a.show}'. Run `vizdesk catalog` to list keys.")
        return
    charts = catalog.search(" ".join(a.search), a.category, a.drawable)
    t = Table(title=f"{len(charts)} visualization techniques", show_lines=False)
    for col in ("key", "name", "category", "draw", "use it when"):
        t.add_column(col, overflow="fold")
    for c in charts:
        t.add_row(c.key, c.name, c.category, "yes" if c.renderable else "-", c.use_when[:110])
    console.print(t)
    console.print("Details: [bold]vizdesk catalog --show <key>[/]")


def cmd_goals(_: argparse.Namespace) -> None:
    t = Table(title="Goals")
    t.add_column("key")
    t.add_column("goal")
    t.add_column("question it answers")
    for g in GOALS:
        t.add_row(g.key, g.label, g.question)
    console.print(t)


def cmd_scan(a: argparse.Namespace) -> None:
    from vizdesk.pipeline import scan_all

    for s in scan_all(a.path):
        console.rule(f"[bold]{s.name}[/] ({s.profile.rows} rows, {len(s.profile.columns)} columns)")
        t = Table(title="Columns")
        for col in ("column", "kind", "missing %", "unique", "range / top values"):
            t.add_column(col)
        for c in s.profile.columns:
            flag = " (text→number)" if c.numeric_like else " (text→date)" if c.datetime_like else ""
            t.add_row(c.name, c.kind + flag, f"{c.missing_pct:g}", str(c.unique), c.summary)
        console.print(t)
        t = Table(title="Cleaning and normalization suggestions")
        for col in ("#", "auto", "suggestion", "why"):
            t.add_column(col, overflow="fold")
        for i, step in enumerate(s.cleaning, 1):
            t.add_row(str(i), "safe" if step.safe else "ask", step.title, step.reason)
        console.print(t)
        s.apply([c for c in s.cleaning if c.safe])
        from vizdesk.suggest import find_target

        found = find_target(s.profile, s.data, a.target)
        console.print(f"Target: [bold]{found.column}[/] ({found.kind}{', positive = ' + found.positive if found.positive else ''})"
                      if found else "Target: none found (use --target <column> to choose one)")
        t = Table(title=f"Chart suggestions for goal '{a.goal}' (after safe cleaning)")
        for col in ("#", "score", "chart", "columns", "why"):
            t.add_column(col, overflow="fold")
        for i, p in enumerate(s.suggestions(a.goal, a.count, a.target), 1):
            t.add_row(str(i), str(p.options.get("score", "")), p.chart, p.label().split("(", 1)[1].rstrip(")"), p.reason)
        console.print(t)


def _layout_from(a: argparse.Namespace, fmt: str = "png"):
    from vizdesk.pipeline import Layout

    return Layout(a.rows, a.cols, a.width, a.height, a.dpi, a.padding, a.pad, a.theme, fmt)


def cmd_auto(a: argparse.Namespace) -> None:
    from vizdesk.pipeline import auto_run

    results = auto_run(a.path, a.goal, a.out, _layout_from(a, a.format), a.count, apply_safe=not a.no_clean, target=a.target)
    for r in results:
        _report(r, a.show)
    if not results:
        console.print("[yellow]No figures: no suggestions matched this goal. Try --goal explore.[/]")


def cmd_draw(a: argparse.Namespace) -> None:
    from vizdesk.pipeline import scan
    from vizdesk.render import render_figure

    s = scan(a.path, a.sheet, apply_safe=not a.no_clean)
    panels = [_parse_panel(p) for p in a.panel]
    spec = FigureSpec(source=str(s.source), sheet=s.sheet, cleaning=s.applied, panels=panels, rows=a.rows, cols=a.cols,
                      width=a.width, height=a.height, dpi=a.dpi, padding=a.padding, pad=a.pad, theme=a.theme,
                      title=a.title, output=a.out)
    _report(render_figure(s.data, spec), a.show)


def cmd_redraw(a: argparse.Namespace) -> None:
    from vizdesk.render import render_spec

    spec = load_spec(a.spec)
    for key in ("rows", "cols", "width", "height", "dpi", "padding", "pad", "theme", "title"):
        value = getattr(a, key)
        if value is not None:
            setattr(spec, key, value)
    for n in sorted(a.remove_panel or [], reverse=True):
        spec.panels.pop(n - 1)
    for edit in a.set or []:
        num, _, assignment = edit.partition(":")
        panel = spec.panels[int(num) - 1]
        changes = _parse_fields(assignment)
        options = {**panel.options, **changes.pop("options", {})}
        spec.panels[int(num) - 1] = PanelSpec.from_dict({**panel.__dict__, **changes, "options": options})
    spec.panels += [_parse_panel(p) for p in a.add_panel or []]
    if a.out:
        spec.output = a.out
    _report(render_spec(spec), a.show)


def _report(r, show: bool = False) -> None:
    console.print(f"[green]wrote[/] {r.path}  [dim](recipe {r.spec_path.name}, script {r.script_path.name}, "
                  f"alt text {r.alt_path.name})[/]")
    for w in r.warnings:
        console.print(f"  [yellow]warning:[/] {w}")
    if show:
        from vizdesk.preview import show as show_image

        show_image(r.path)
        console.print(r.alt_text, style="dim", highlight=False)


def cmd_show(a: argparse.Namespace) -> None:
    from vizdesk.preview import show as show_image

    for image in a.images:
        path = Path(image).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"no such image: {path}")
        used = show_image(path, a.protocol, a.width)
        alt = path.with_suffix(".alt.txt")
        if alt.is_file() and not a.no_alt:
            console.print(alt.read_text(encoding="utf-8").strip(), style="dim", highlight=False)
        if used == "blocks" and not a.protocol:
            console.print("[dim]Low-resolution preview. Kitty, Ghostty, iTerm2, WezTerm and sixel terminals show the full image; "
                          "set VIZDESK_PREVIEW to force one.[/]")


def cmd_tui(a: argparse.Namespace) -> None:
    from vizdesk.tui.app import VizDeskApp

    VizDeskApp(path=a.path, out_dir=a.out).run()


# ---------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vizdesk",
        description="Scan CSV/Excel files, get cleaning and chart suggestions, and draw PNG figures. Run with no command to open the TUI.",
    )
    parser.add_argument("--version", action="version", version=f"vizdesk {__version__}")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("tui", help="open the terminal UI (default)")
    p.add_argument("path", nargs="?", help="CSV / Excel file or folder to open")
    p.add_argument("-o", "--out", default="vizdesk-output", help="where figures are saved")
    p.set_defaults(func=cmd_tui)

    p = sub.add_parser("catalog", help="list visualization techniques with descriptions and uses")
    p.add_argument("search", nargs="*", help="words to search for, e.g. 'part whole'")
    p.add_argument("--category", choices=catalog.categories())
    p.add_argument("--drawable", action="store_true", help="only charts vizdesk can draw")
    p.add_argument("--show", metavar="KEY", help="full details for one chart")
    p.set_defaults(func=cmd_catalog)

    p = sub.add_parser("show", help="preview PNGs in the terminal (Kitty, iTerm2, sixel or coloured blocks) with their alt text")
    p.add_argument("images", nargs="+")
    p.add_argument("--protocol", choices=["kitty", "iterm", "sixel", "blocks"], help="default: detected from the terminal")
    p.add_argument("--width", type=int, help="width in terminal columns")
    p.add_argument("--no-alt", action="store_true", help="do not print the alt text")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("goals", help="list the goals suggestions can target")
    p.set_defaults(func=cmd_goals)

    p = sub.add_parser("scan", help="profile a file and print cleaning and chart suggestions")
    p.add_argument("path", help="CSV / Excel file or folder")
    p.add_argument("--goal", choices=GOAL_KEYS, default="explore")
    p.add_argument("--target", help="the column to explain (default: guessed from names like churn, survived, price)")
    p.add_argument("--count", type=int, default=10)
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("auto", help="scan, apply safe cleaning, and draw the top suggestions as PNGs")
    p.add_argument("path", help="CSV / Excel file or folder")
    p.add_argument("--goal", choices=GOAL_KEYS, default="explore")
    p.add_argument("--target", help="the column to explain (default: guessed from names like churn, survived, price)")
    p.add_argument("-o", "--out", default="vizdesk-output", help="output folder")
    p.add_argument("--count", type=int, default=8, help="how many charts in total (split across figures)")
    p.add_argument("--format", choices=["png", "svg", "pdf"], default="png")
    p.add_argument("--no-clean", action="store_true", help="do not apply the safe cleaning steps")
    _add_layout_args(p)
    p.set_defaults(func=cmd_auto)

    p = sub.add_parser("draw", help="draw charts you configure yourself",
                       epilog="Example: vizdesk draw sales.csv --panel chart=bar_chart,x=region,y=revenue "
                              "--panel chart=histogram,x=revenue --rows 1 --cols 2 -o out/sales.png")
    p.add_argument("path")
    p.add_argument("--sheet", help="Excel sheet name (default: first sheet)")
    p.add_argument("--panel", action="append", required=True, metavar="SPEC",
                   help=f"chart=<key>,x=,y=,hue=,size=,columns=a+b,agg=<{'|'.join(AGGREGATIONS)}>,title=,top_n=,bins=. "
                        f"Other keys are chart options, e.g. filter=Name=AAPL or reversal=2%%. {AGG_HELP}")
    p.add_argument("-o", "--out", default="vizdesk-output/figure.png")
    p.add_argument("--no-clean", action="store_true")
    _add_layout_args(p, defaults=True)
    p.set_defaults(func=cmd_draw)

    p = sub.add_parser("redraw", help="change and redraw a figure from its recipe (.vizdesk.json or the PNG)",
                       epilog="Example: vizdesk redraw out/sales.png --set 1:chart=violin_plot,y=revenue --cols 3")
    p.add_argument("spec")
    p.add_argument("--set", action="append", metavar="N:key=value,...", help="change panel N (1-based)")
    p.add_argument("--add-panel", action="append", metavar="SPEC")
    p.add_argument("--remove-panel", action="append", type=int, metavar="N")
    p.add_argument("-o", "--out", help="save to a new file instead of overwriting")
    _add_layout_args(p, defaults=False)
    p.set_defaults(func=cmd_redraw)
    return parser


def main(argv: list[str] | None = None) -> None:
    # The command line and the TUI only write files, and the TUI draws in a worker thread,
    # so use matplotlib's file-only backend. (Library and notebook use keep their own backend.)
    import matplotlib

    matplotlib.use("Agg")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        args = parser.parse_args(["tui", *(argv if argv is not None else sys.argv[1:])])
    try:
        args.func(args)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        console.print(f"[red]error:[/] {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
