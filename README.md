# vizdesk

A terminal app for data visualization work. Point it at a CSV or Excel file and it will:

1. **Profile every column**: numbers, categories (including ordered ones such as class 1/2/3), dates, years, IDs and codes, free text, comma-separated lists, "number + unit" values such as `90 min`, gaps, outliers, skew and capped values.
2. **Suggest cleaning and normalization**, each with a plain reason (for example "`TotalCharges` is stored as text and 11 values are only spaces").
3. **Find the target** (churn, survived, price ...) or let you pick one, and **suggest charts** for your goal, the way popular Kaggle EDA notebooks do: the target rate per category, a histogram of every numeric column, top-N rankings, trends, maps, hierarchies.
4. **Draw PNG figures** with the grid, size, DPI and padding you choose, in a colorblind-safe palette by default.
5. **Save four files per figure**: the PNG, a recipe to reopen and redraw it, a Python script that recreates it in a notebook, and alt text describing it.

All suggestions come from fixed rules and statistics computed on your data. No LLM and no internet connection are used.

The chart catalog (66 techniques, each with a description, the data it needs, when to use it and its limits) comes from the Data Scientists Handbook chart catalog, which is based on the Data Visualisation Catalogue (datavizcatalogue.com). **vizdesk can draw all 66.**

## Install

| Tool | Command |
|---|---|
| pip / pipx / uv | `pipx install vizdesk` or `uv tool install vizdesk` |
| npm | `npm install -g vizdesk` (runs the Python package through uv, pipx, or a private venv) |
| Homebrew | `brew install <your-user>/tap/vizdesk` |

Python 3.10 or newer is required (npm and Homebrew set that up for you).

## Quick start

```bash
vizdesk                                   # open the terminal UI
vizdesk churn.csv                         # open the UI with a file loaded
vizdesk auto data/ --goal target --show   # no UI: every CSV/Excel file in data/ to PNGs, previewed in the terminal
```

## The terminal UI

| Tab (key) | What you do there |
|---|---|
| Data (F1) | Load a file or folder, pick a table or Excel sheet, see the column profile and a preview. |
| Clean (F2) | Tick cleaning steps. `SAFE` steps (type fixes, trimming spaces, splitting `90 min` into number and unit, dropping empty and leftover index columns) are ticked for you. Others, such as filling gaps, capping outliers, removing capped rows, grouping ages into ranges or adding year/month columns, wait for you. Unticking undoes a step, because cleaning always re-runs from the original file. |
| Suggest (F3) | Pick a goal and, if you like, a target column, press **Auto scan**, read why each chart is suggested, then add the ticked ones to a figure or draw them all at once. |
| Compose (F4) | Edit each panel (chart type, x, y, colour, size, multi-column list, aggregation, title, top N, bins, log scale, options) and the figure layout (rows, columns, width, height, DPI, padding on/off, padding size, theme, file name). **ctrl+d** draws, **ctrl+o** opens the PNG. |
| Gallery (F5) | Every figure in the output folder. Pick one and press **Edit & redraw** to change it. |
| Catalog (F6) | Search all 66 techniques. **Use this chart** adds it as a new panel. |
| Preview (F7) | The last drawn (or picked) figure, drawn in the terminal, with its alt text and script name. |

Your original files are never changed. Figures go to `./vizdesk-output` unless you pass `-o`.

## Command line

```bash
vizdesk catalog part whole                  # search the catalog
vizdesk catalog --show sankey_diagram       # full details of one technique
vizdesk goals                               # the goals suggestions can target
vizdesk scan churn.csv --goal target        # profile, cleaning and chart suggestions, printed
vizdesk scan housing.csv --target median_house_value

# auto: safe cleaning, top suggestions, split into 2x3 grids, no padding, 300 dpi
vizdesk auto sales.csv --goal explore --count 12 --rows 2 --cols 3 --width 15 --height 9 --dpi 300 --no-padding

# manual: choose every chart yourself
vizdesk draw sales.csv \
  --panel chart=bar_chart,x=region,y=revenue,agg=sum \
  --panel chart=sunburst_diagram,columns=Category+Sub-Category,y=Sales \
  --panel chart=line_graph,x=date,y=close,filter=Name=AAPL,rolling=50 \
  --rows 1 --cols 3 --width 18 --height 5 -o out/sales.png

# redraw: change panel 1, add a panel, widen the grid
vizdesk redraw out/sales.png --set 1:chart=violin_plot,y=revenue --add-panel chart=pie_chart,x=channel --cols 3

# preview in the terminal (Kitty, Ghostty, iTerm2, WezTerm, sixel, or coloured blocks anywhere)
vizdesk show out/sales.png
```

Panel fields: `chart`, `x`, `y`, `hue` (colour), `size`, `columns=a+b+c` (multi-column charts), `agg` (`auto`, `count`, `sum`, `mean`, `median`, `min`, `max`), `title`, `top_n`, `bins`, `log_y`. `agg=auto` sums columns whose names look like totals (sales, revenue, units ...) and averages the rest.

Any other `key=value` is a chart option. Options every chart understands:

| Option | Example | What it does |
|---|---|---|
| `filter` | `filter=Name=AAPL` or `filter=region=North\|South` | keep only matching rows |
| `split` | `split=listed_in` | count each item of a comma-separated list column |
| `order` | `order=label` | keep a natural order (1, 2, 3; age bands) instead of biggest first |
| `log` | `log=x`, `log=y`, `log=xy` | log scale (zeros use a symmetric log) |

Some charts read their own options, for example `rolling=50` (line), `reversal=4%` (kagi), `box=1; reversal=3` (point and figure), `last=120` (candlestick), `geojson=regions.geojson; key=name` (maps). The Compose tab shows the options of the selected chart.

## Goals

| Goal | Typical charts |
|---|---|
| explore | a balanced overview: the best one or two charts from each goal below |
| target | target share, the target rate in every category (100% stacked bars), numeric columns split by the target; for a numeric target, its strongest partners |
| distribution | histogram grid of every numeric column, histograms (log scale for long tails), box, violin, density, ECDF, Q-Q |
| comparison | bar, grouped bar, error bars, radar, top 15 of a many-valued column |
| relationship | scatter or hexbin for the strongest pairs, correlation heatmap, scatter matrix, bubble, parallel coordinates |
| composition | sunburst and treemap for hierarchies (Category > Sub-Category), donut, pie, 100% stacked bar, stacked area |
| trend | lines over dates or years, by group, year by month heatmap, calendar; for price data, candlestick, moving average and the most traded series |
| ranking | top 15 bars (by a total or by count, never by an average of tiny groups), lollipop, dot plot, span |
| data_quality | missing values map, outlier box plots, capped-value histograms |

Maps appear when there are longitude and latitude columns; word charts appear for free text.

## The four files of a figure

| File | What it is for |
|---|---|
| `figure.png` | the image (alt text is also stored inside it) |
| `figure.vizdesk.json` | the recipe: source file and sheet, cleaning steps, layout and panels. Used by Gallery and `vizdesk redraw`. |
| `figure.py` | a Python script that recreates the figure. Loading and cleaning are plain pandas; paste the `# %%` cells into a notebook to change them. |
| `figure.alt.txt` | alt text for reports and screen readers, written by rules from the data (for example "Laptop is highest at 652,645, 40% of the total"). |

## How it was checked

The rules were tuned against 7 popular Kaggle datasets (Telco churn, Titanic, California housing, Netflix, Superstore, S&P 500 stocks, Wine reviews) and the EDA charts of their top-voted notebooks. `tests/test_kaggle_shapes.py` keeps each fix as a regression test on a small table of the same shape, and runs on the real files too when they are in `datasets/kaggle/`.

## Development

```bash
uv venv && uv pip install -e '.[dev]'
python examples/make_examples.py   # messy sample data
pytest
```

To refresh the catalog from the handbook: `python scripts/build_catalog.py path/to/_chart_catalog_reference.md`.

See [PACKAGING.md](PACKAGING.md) for releasing to PyPI, npm and Homebrew.
