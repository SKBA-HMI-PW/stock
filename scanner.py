import io
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"

# User-defined strategy
RECENT_DAYS = 20
PREVIOUS_DAYS = 20
VOLUME_MULTIPLE_MIN = 3.0
PRICE_CHANGE_MAX_PCT = 3.0

# Download tuning
BATCH_SIZE = 100
SLEEP_BETWEEN_BATCHES_SEC = 0.35
PERIOD = "4mo"


def _read_pipe_table(url: str) -> pd.DataFrame:
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), sep="|")
    # Nasdaq files end with a footer row such as "File Creation Time:..."
    first_col = df.columns[0]
    df = df[~df[first_col].astype(str).str.startswith("File Creation Time")].copy()
    return df


def load_us_stock_universe() -> pd.DataFrame:
    nas = _read_pipe_table(NASDAQ_URL)
    oth = _read_pipe_table(OTHER_URL)

    nas = nas.rename(columns={
        "Symbol": "symbol",
        "Security Name": "name",
        "Test Issue": "test_issue",
        "ETF": "etf",
    })
    nas["exchange"] = "NASDAQ"
    nas = nas[["symbol", "name", "exchange", "test_issue", "etf"]]

    oth = oth.rename(columns={
        "ACT Symbol": "symbol",
        "Security Name": "name",
        "Exchange": "exchange_code",
        "Test Issue": "test_issue",
        "ETF": "etf",
    })
    exch_map = {"N": "NYSE", "A": "NYSE American", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}
    oth["exchange"] = oth["exchange_code"].map(exch_map).fillna(oth["exchange_code"])
    oth = oth[["symbol", "name", "exchange", "test_issue", "etf"]]

    universe = pd.concat([nas, oth], ignore_index=True)
    universe["symbol"] = universe["symbol"].astype(str).str.strip()
    universe["name"] = universe["name"].astype(str).str.strip()

    # User asked for stocks, so remove ETFs and Nasdaq test issues.
    universe = universe[(universe["test_issue"] != "Y") & (universe["etf"] != "Y")]

    # Exclude obviously non-common-stock structures that Yahoo frequently cannot price cleanly.
    bad_name_terms = (
        "Warrant", "Rights", "Right", "Units", "Unit ", "Preferred", "Depositary", "Notes due",
    )
    mask_bad = universe["name"].str.contains("|".join(bad_name_terms), case=False, na=False, regex=True)
    universe = universe[~mask_bad]

    universe = universe.drop_duplicates("symbol").sort_values("symbol").reset_index(drop=True)
    return universe


def yahoo_symbol(symbol: str) -> str:
    # Yahoo uses dashes for class shares such as BRK-B.
    return symbol.replace(".", "-").replace("/", "-")


def safe_float(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except Exception:
        return None


def extract_symbol_frame(downloaded: pd.DataFrame, ticker: str, single_ticker: bool) -> pd.DataFrame | None:
    if downloaded is None or downloaded.empty:
        return None
    if single_ticker:
        frame = downloaded.copy()
    else:
        try:
            frame = downloaded[ticker].copy()
        except Exception:
            return None
    if frame.empty or "Close" not in frame.columns or "Volume" not in frame.columns:
        return None
    return frame.dropna(subset=["Close", "Volume"])


def scan_batch(batch_meta: pd.DataFrame) -> tuple[list[dict], list[str]]:
    symbols = batch_meta["symbol"].tolist()
    yf_tickers = [yahoo_symbol(s) for s in symbols]
    lookup = dict(zip(yf_tickers, symbols))
    meta_lookup = batch_meta.set_index("symbol").to_dict("index")

    try:
        px = yf.download(
            tickers=yf_tickers,
            period=PERIOD,
            interval="1d",
            auto_adjust=False,
            group_by="ticker",
            threads=True,
            progress=False,
        )
    except Exception:
        return [], symbols

    results: list[dict] = []
    failures: list[str] = []
    single = len(yf_tickers) == 1

    for yft in yf_tickers:
        original = lookup[yft]
        frame = extract_symbol_frame(px, yft, single)
        if frame is None or len(frame) < (RECENT_DAYS + PREVIOUS_DAYS + 1):
            failures.append(original)
            continue

        # Last 40 trading sessions: previous 20 vs recent 20.
        volumes = frame["Volume"].astype(float)
        closes = frame["Close"].astype(float)

        prev_vol = volumes.iloc[-(RECENT_DAYS + PREVIOUS_DAYS):-RECENT_DAYS].mean()
        recent_vol = volumes.iloc[-RECENT_DAYS:].mean()
        if not math.isfinite(prev_vol) or prev_vol <= 0 or not math.isfinite(recent_vol):
            failures.append(original)
            continue

        volume_multiple = recent_vol / prev_vol

        # Exactly 20 trading-session price change: latest close vs close 20 sessions ago.
        start_close = closes.iloc[-(RECENT_DAYS + 1)]
        end_close = closes.iloc[-1]
        if not math.isfinite(start_close) or start_close <= 0 or not math.isfinite(end_close):
            failures.append(original)
            continue
        price_change_pct = (end_close / start_close - 1.0) * 100.0

        if volume_multiple >= VOLUME_MULTIPLE_MIN and price_change_pct < PRICE_CHANGE_MAX_PCT:
            meta = meta_lookup[original]
            results.append({
                "symbol": original,
                "name": meta.get("name", ""),
                "exchange": meta.get("exchange", ""),
                "volume_multiple": round(volume_multiple, 2),
                "recent_avg_volume": int(round(recent_vol)),
                "previous_avg_volume": int(round(prev_vol)),
                "price_change_pct": round(price_change_pct, 2),
                "last_close": round(float(end_close), 4),
                "direction": "down" if price_change_pct < 0 else "flat_up",
            })

    return results, failures


def main():
    universe = load_us_stock_universe()
    all_results: list[dict] = []
    all_failures: list[str] = []

    total = len(universe)
    for start in range(0, total, BATCH_SIZE):
        batch = universe.iloc[start:start + BATCH_SIZE]
        rows, failures = scan_batch(batch)
        all_results.extend(rows)
        all_failures.extend(failures)
        done = min(start + BATCH_SIZE, total)
        print(f"Scanned {done}/{total} — matches {len(all_results)} — failures {len(all_failures)}", flush=True)
        time.sleep(SLEEP_BETWEEN_BATCHES_SEC)

    all_results.sort(key=lambda r: (-r["volume_multiple"], r["price_change_pct"], r["symbol"]))

    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "generated_at_utc": generated_at,
        "criteria": {
            "recent_days": RECENT_DAYS,
            "previous_days": PREVIOUS_DAYS,
            "min_volume_multiple": VOLUME_MULTIPLE_MIN,
            "max_price_change_pct_exclusive": PRICE_CHANGE_MAX_PCT,
            "decliners_included": True,
            "etfs_excluded": True,
        },
        "universe_count": total,
        "match_count": len(all_results),
        "data_failure_count": len(all_failures),
        "results": all_results,
    }

    (DATA_DIR / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(all_results).to_csv(DATA_DIR / "results.csv", index=False)

    print(f"Done. {len(all_results)} matches written to data/results.json")


if __name__ == "__main__":
    main()
