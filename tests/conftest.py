import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("MPLBACKEND", "Agg")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))

import make_examples  # noqa: E402


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("data")
    make_examples.sales().to_csv(d / "sales.csv", index=False)
    import pandas as pd

    with pd.ExcelWriter(d / "markets.xlsx") as xw:
        make_examples.prices().to_excel(xw, sheet_name="prices", index=False)
        make_examples.sites().to_excel(xw, sheet_name="sites", index=False)
    return d


@pytest.fixture
def sales_csv(data_dir) -> Path:
    return data_dir / "sales.csv"
