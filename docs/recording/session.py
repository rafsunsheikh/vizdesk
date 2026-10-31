"""What the recording shows, as a list of actions.

Edit this rather than the recorder. Keys follow the app's own bindings:
F1 Data, F2 Clean, F3 Suggest, F4 Compose, F7 Preview, ctrl+d draws the PNG.

Timings are deliberate. A demo that moves too fast reads as a blur, and the
first three seconds decide whether anyone keeps watching, so the file is loaded
straight away rather than after a title card.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# The local source, not the installed 0.2.0, because the fix for
# `vizdesk <file>` is not released yet.
CMD = [str(ROOT / ".venv-rec/bin/python"), "-m", "vizdesk", "sales.csv"]

ESC = "\x1b"
F1, F2, F3, F4, F7 = f"{ESC}OP", f"{ESC}OQ", f"{ESC}OR", f"{ESC}OS", f"{ESC}[18~"
DOWN, UP, ENTER, TAB, SPACE = f"{ESC}[B", f"{ESC}[A", "\r", "\t", " "
CTRL_D = "\x04"

ACTIONS = [
    # Open with the data already profiled: that is the thing worth seeing.
    ("wait", 3.5),

    # Data tab: the column profile.
    ("keys", DOWN, 0.9),
    ("keys", DOWN, 0.9),
    ("keys", DOWN, 1.2),

    # Clean: what it thinks needs fixing, and why.
    ("keys", F2, 2.6),
    ("keys", DOWN, 0.8),
    ("keys", DOWN, 1.6),

    # Suggest: the heart of it. Pick a goal, see the charts it proposes.
    ("keys", F3, 2.8),
    ("keys", DOWN, 0.8),
    ("keys", DOWN, 0.8),
    ("keys", ENTER, 2.4),
    ("keys", DOWN, 0.9),
    ("keys", DOWN, 1.6),

    # Compose: the panels that will be drawn.
    ("keys", F4, 2.6),
    ("keys", DOWN, 0.9),
    ("keys", DOWN, 1.4),

    # Draw, then look at the result.
    ("keys", CTRL_D, 4.0),
    ("keys", F7, 3.5),
    ("wait", 2.0),
]
