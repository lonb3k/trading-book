"""Run the book after the US close: revalue, explain, risk, axes. Writes the outputs and the morning sheet.

    python scripts/run_book.py [--offline]
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from book import risk  # noqa: E402
from book.build import run  # noqa: E402
from book.sheet import build_sheet  # noqa: E402

OUT = ROOT / "data" / "out"
SHEET = ROOT / "sheet" / "latest.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="use the mirrored data only")
    args = ap.parse_args()
    res = run(offline=args.offline)
    OUT.mkdir(parents=True, exist_ok=True)
    res.daily.round(2).to_csv(OUT / "daily_pnl.csv")
    res.explain.round(2).to_csv(OUT / "explain_by_trade.csv", index=False)
    res.risk.round(4).to_csv(OUT / "risk_by_underlying.csv", index=False)
    res.positions.round(2).to_csv(OUT / "positions.csv", index=False)
    marks = res.marks
    pd.concat({"atm30": marks.atm30, "atm90": marks.atm90, "beta": marks.beta, "model_atm30": marks.model_atm30},
              axis=1).round(4).to_csv(OUT / "marks.csv")
    risk.axes(res).round(4).to_csv(OUT / "axes.csv", index=False)
    sheet = build_sheet(res)
    SHEET.parent.mkdir(exist_ok=True)
    SHEET.write_text(json.dumps(sheet, separators=(",", ":"), allow_nan=False))
    print(f"{SHEET} ({SHEET.stat().st_size / 1024:.0f} KB), as of {sheet['as_of']}, warnings: {sheet['warnings'] or 'none'}")
    print(sheet["headline"])
    for i in sheet["ideas"]:
        print(f"  {i['rank']}. {i['title']}  [{i['condition']}]")


if __name__ == "__main__":
    main()
