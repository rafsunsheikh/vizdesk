"""Create small, deliberately messy example files for trying vizdesk.

    python examples/make_examples.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
rng = np.random.default_rng(42)


def sales() -> pd.DataFrame:
    n = 600
    dates = pd.to_datetime("2025-01-01") + pd.to_timedelta(rng.integers(0, 365, n), unit="D")
    region = rng.choice(["North", "South", "East", "West"], n, p=[0.35, 0.25, 0.25, 0.15])
    product = rng.choice(["Laptop", "Phone", "Tablet", "Monitor", "Headset"], n)
    base = {"Laptop": 1200, "Phone": 800, "Tablet": 450, "Monitor": 300, "Headset": 90}
    units = rng.poisson(3, n) + 1
    price = np.array([base[p] for p in product]) * rng.normal(1, 0.08, n)
    revenue = units * price
    revenue[rng.choice(n, 6, replace=False)] *= 12  # a few outliers
    df = pd.DataFrame(
        {
            "order_id": np.arange(10001, 10001 + n),
            "order_date": dates.strftime("%Y-%m-%d"),  # dates stored as text
            "region": region,
            "product": product,
            "channel": rng.choice(["Online", "Store", "online "], n, p=[0.5, 0.42, 0.08]),  # case + spaces
            "units": units,
            "unit_price": [f"${v:,.2f}" for v in price],  # numbers stored as text
            "revenue": revenue.round(2),
            "discount_pct": np.where(rng.random(n) < 0.15, np.nan, rng.uniform(0, 30, n).round(1)),
            "rating": np.where(rng.random(n) < 0.1, np.nan, rng.integers(1, 6, n)),
            "country": "Australia",  # constant column
            "comment": rng.choice(
                ["Fast delivery and great price", "Product broke after a week", "Good value, would buy again",
                 "Delivery was slow but support was helpful", "Excellent screen quality", None], n),
        }
    )
    return pd.concat([df, df.sample(8, random_state=1)], ignore_index=True)  # duplicate rows


def prices() -> pd.DataFrame:
    days = pd.bdate_range("2025-01-01", periods=160)
    close = 100 + np.cumsum(rng.normal(0, 1.5, len(days)))
    open_ = close + rng.normal(0, 1, len(days))
    high = np.maximum(open_, close) + rng.uniform(0, 2, len(days))
    low = np.minimum(open_, close) - rng.uniform(0, 2, len(days))
    return pd.DataFrame({"Date": days, "Open": open_, "High": high, "Low": low, "Close": close,
                         "Volume": rng.integers(1e5, 1e6, len(days))})


def sites() -> pd.DataFrame:
    n = 80
    return pd.DataFrame({"site": [f"S{i:03d}" for i in range(n)],
                         "state": rng.choice(["NSW", "VIC", "QLD", "WA"], n),
                         "longitude": rng.uniform(115, 153, n), "latitude": rng.uniform(-38, -12, n),
                         "visitors": rng.lognormal(7, 1, n).round()})


if __name__ == "__main__":
    sales().to_csv(HERE / "sales.csv", index=False)
    with pd.ExcelWriter(HERE / "markets.xlsx") as xw:
        prices().to_excel(xw, sheet_name="prices", index=False)
        sites().to_excel(xw, sheet_name="sites", index=False)
    print("wrote examples/sales.csv and examples/markets.xlsx")
