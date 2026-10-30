"""Command line and terminal UI, driven end to end."""

from pathlib import Path

from textual.widgets import Input, OptionList, Select, SelectionList, Switch

from vizdesk.cli import main
from vizdesk.spec import load_spec
from vizdesk.tui.app import VizDeskApp


def test_cli_catalog_scan_draw_redraw(sales_csv, tmp_path, capsys):
    main(["catalog", "--show", "violin_plot"])
    main(["goals"])
    main(["scan", str(sales_csv), "--goal", "comparison", "--count", "3"])
    out = tmp_path / "m.png"
    main(["draw", str(sales_csv), "--panel", "chart=bar_chart,x=region,y=revenue", "--panel", "chart=histogram,x=unit_price",
          "--rows", "1", "--cols", "2", "--dpi", "50", "--no-padding", "-o", str(out)])
    assert out.is_file() and load_spec(out).padding is False
    main(["redraw", str(out), "--set", "1:chart=violin_plot,y=revenue", "--add-panel", "chart=pie_chart,x=channel", "--cols", "3"])
    spec = load_spec(out)
    assert [p.chart for p in spec.panels] == ["violin_plot", "histogram", "pie_chart"]
    assert spec.panels[0].x == "region"  # untouched fields survive --set
    assert spec.cols == 3 and spec.padding is False
    text = capsys.readouterr().out
    assert "Cleaning and normalization suggestions" in text and "wrote" in text


async def _wait_for(pilot, condition, tries=100):
    for _ in range(tries):
        if condition():
            return True
        await pilot.pause(0.05)
    return False


async def test_tui_full_workflow(sales_csv, tmp_path):
    app = VizDeskApp(path=str(sales_csv), out_dir=str(tmp_path))
    async with app.run_test(size=(160, 50)) as pilot:
        assert await _wait_for(pilot, lambda: app.current is not None and app.suggestions)
        # Clean tab: safe steps are pre-ticked; tick everything and apply.
        clean = app.query_one("#clean-list", SelectionList)
        assert len(clean.selected) == sum(s.safe for s in app.current.cleaning)
        clean.select_all()
        app.query_one("#clean-apply").press()
        await pilot.pause()
        assert "revenue_log" in app.current.data.columns
        # Suggest tab: change goal, add ticked suggestions to the figure.
        app.query_one("#goal", Select).value = "comparison"
        assert await _wait_for(pilot, lambda: app.suggestions and app.suggestions[0].chart in ("bar_chart", "multi_set_bar_chart", "error_bars"))
        app.query_one("#suggest-add").press()
        await pilot.pause()
        assert app.query_one("TabbedContent").active == "compose"
        assert len(app.figure.panels) == 4
        # Compose tab: manual edits to panel 1 and to the layout.
        app.query_one("#panels", OptionList).highlighted = 0
        await pilot.pause()
        app.query_one("#f-chart", Select).value = "violin_plot"
        await pilot.pause()
        app.query_one("#f-title", Input).value = "My violin"
        app.query_one("#l-cols", Input).value = "4"
        app.query_one("#l-rows", Input).value = "1"
        app.query_one("#l-padding", Switch).value = False
        out = tmp_path / "tui.png"
        app.query_one("#l-output", Input).value = str(out)
        await pilot.pause()
        assert app.figure.panels[0].chart == "violin_plot" and app.figure.panels[0].title == "My violin"
        await pilot.press("ctrl+d")
        assert await _wait_for(pilot, lambda: out.is_file())
        spec = load_spec(out)
        assert (spec.rows, spec.cols, spec.padding) == (1, 4, False)
        assert spec.theme == "colorblind" and out.with_suffix(".py").is_file() and out.with_suffix(".alt.txt").is_file()
        await pilot.press("f7")
        await pilot.pause(0.3)
        assert "▀" in str(app.query_one("#preview-image").render())
        assert spec.panels[0].chart == "violin_plot"
        # Gallery: reopen the recipe, change it, redraw to the same file.
        app.query_one("#gallery-refresh").press()
        await pilot.pause()
        app.action_tab("gallery")
        await pilot.pause()
        names = [Path(p).name for p in app._gallery_paths]
        app.query_one("#gallery-table").move_cursor(row=names.index("tui.vizdesk.json"))
        app.query_one("#gallery-edit").press()
        assert await _wait_for(pilot, lambda: app.query_one("TabbedContent").active == "compose" and app.figure.output == str(out))
        app.query_one("#panels", OptionList).highlighted = 1
        await pilot.pause()
        app.query_one("#f-chart", Select).value = "lollipop_chart"
        await pilot.pause()
        await pilot.press("ctrl+d")
        assert await _wait_for(pilot, lambda: load_spec(out).panels[1].chart == "lollipop_chart")
        # Catalog: search, pick, add as a new panel.
        app.action_tab("catalog")
        app.query_one("#catalog-search", Input).value = "ecdf"
        await pilot.pause()
        app.query_one("#catalog-list", OptionList).highlighted = 0
        await pilot.pause()
        before = len(app.figure.panels)
        app.query_one("#catalog-use").press()
        await pilot.pause()
        assert app.figure.panels[-1].chart == "ecdf_plot" and len(app.figure.panels) == before + 1
