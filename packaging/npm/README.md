# vizdesk (npm launcher)

`npm install -g vizdesk` gives you the `vizdesk` command: a terminal app that scans CSV and Excel files, suggests cleaning and charts without any LLM, and draws PNG figures.

vizdesk itself is a Python package. On first run this launcher uses `uvx` or `pipx` if you have one, and otherwise installs vizdesk into a private Python environment in `~/.cache/vizdesk`. You need Python 3.10 or newer, or uv.

```bash
vizdesk                    # open the terminal UI
vizdesk auto sales.csv     # draw suggested charts without the UI
vizdesk --help
```

Full documentation: https://pypi.org/project/vizdesk/
