# agent/snapshot_agent.py
"""
The agentic workflow — polls Groww every POLL_SEC seconds,
runs full_analysis on each quote, writes insights to snapshot_signals.json.
Mirrors exactly what was done manually in today's session.
"""

import json
import time
import requests
from datetime import datetime
from pathlib import Path
from logzero import logger
from collections import defaultdict

from agent.order_book_analyzer import full_analysis, SnapHistory
from config.settings import GROWW_BASE_URL, WATCHLIST

SIGNALS_FILE  = Path("snapshot_signals.json")
POSITION_FILE = Path("positions.json")
POLL_SEC      = 10
MAX_SIGNALS   = 100

_histories   = defaultdict(SnapHistory)
_session     = requests.Session()
_all_signals = []


def _get_headers() -> dict:
    """Build headers fresh every call so token updates take effect immediately."""
    from config.settings import GROWW_API_KEY
    token = GROWW_API_KEY.strip()
    # Ensure Bearer prefix
    if not token.lower().startswith("bearer "):
        token = f"Bearer {token}"
    headers = {
        "Authorization": token,
        "Accept":        "application/json",
        "Content-Type":  "application/json",
        "User-Agent":    "Mozilla/5.0",
    }
    # Add cookie if set
   
    return headers


def _fetch(symbol: str) -> dict | None:
    """Fetch a single Groww quote. Returns payload dict or None."""
    try:
        # Print curl for first call to help debug
        url    = f"{GROWW_BASE_URL}/live-data/quote"
        params = {"exchange": "NSE", "segment": "CASH", "trading_symbol": symbol}
        r = _session.get(url, params=params, headers=_get_headers(), timeout=8)

        if r.status_code == 401:
            logger.error(f"❌ 401 Unauthorized — token expired. Update GROWW_API_KEY in settings.py")
            return None
        if r.status_code == 400:
            logger.warning(f"⚠ 400 Bad Request for {symbol} — check symbol name in WATCHLIST")
            return None

        r.raise_for_status()
        data = r.json()

        if data.get("status") == "SUCCESS":
            return data["payload"]

        logger.warning(f"{symbol}: API returned {data.get('error', data)}")
        return None

    except requests.exceptions.Timeout:
        logger.warning(f"{symbol}: request timed out")
        return None
    except Exception as e:
        logger.warning(f"{symbol}: {e}")
        return None


def _load_positions() -> dict:
    if POSITION_FILE.exists():
        try:
            return json.loads(POSITION_FILE.read_text())
        except Exception:
            pass
    return {}


def _write_output(signals: list, watchlist_status: list):
    try:
        SIGNALS_FILE.write_text(json.dumps({
            "signals":    signals[-MAX_SIGNALS:],
            "watchlist":  watchlist_status,
            "positions":  _load_positions(),
            "updated_at": datetime.now().isoformat(),
        }, indent=2))
    except Exception as e:
        logger.warning(f"Could not write signals file: {e}")


def _format_signal(result: dict) -> dict:
    """Format analysis result for dashboard."""
    snap   = result["snap"]
    levels = result["levels"]
    walls  = result["walls"]
    mom    = result["momentum"]

    out = {
        "symbol":      result["symbol"],
        "time":        result["timestamp"],
        "signal":      result["signal"],
        "confidence":  result["confidence"],
        "ltp":         snap["ltp"],
        "day_change":  snap["day_change_pct"],
        "book_ratio":  snap["book_ratio"],
        "book_bias":   snap["book_bias"],
        "range_pct":   snap["range_pct"],
        "volume":      snap["volume"],
        "vol_quality": result["volume"]["quality"],
        "spread":      snap["spread"],
        "snaps":       result["snaps_so_far"],
        "momentum":    mom["reason"],
        "emotion":     result["emotion"],
        "wall_buy":    walls["buy"],
        "wall_sell":   walls["sell"],
    }

    if "pnl" in levels:
        out.update({
            "position_side": levels["side"],
            "entry":         levels["entry"],
            "pnl_per_share": levels["pnl"],
            "sl":            levels["sl"],
            "t1":            levels["t1"],
            "t2":            levels["t2"],
            "t3":            levels.get("t3"),
            "rr_t1":         levels["rr_t1"],
            "sl_distance":   levels["sl_dist"],
            "t1_distance":   levels["t1_dist"],
        })
    else:
        out.update({
            "long_entry":  levels.get("long_entry"),
            "long_sl":     levels.get("long_sl"),
            "long_t1":     levels.get("long_t1"),
            "long_rr":     levels.get("long_rr"),
            "short_entry": levels.get("short_entry"),
            "short_sl":    levels.get("short_sl"),
            "short_t1":    levels.get("short_t1"),
            "short_rr":    levels.get("short_rr"),
        })

    return out


def run_once(symbol: str, positions: dict) -> dict | None:
    """Process one symbol — fetch, analyse, format. All errors caught."""
    try:
        payload = _fetch(symbol)
        if not payload:
            return None

        position = positions.get(symbol)
        result   = full_analysis(symbol, payload, _histories[symbol], position)
        signal   = _format_signal(result)

        sig = result["signal"]
        if sig in ("BUY", "SELL", "EXIT", "AVOID"):
            logger.info(
                f"🔔 {symbol} {sig} @ ₹{signal['ltp']} | "
                f"Book {signal['book_ratio']}:1 | "
                f"Range {signal['range_pct']}% | "
                f"Vol {signal['vol_quality']} | "
                f"Conf {signal['confidence']}%"
            )
        if result["emotion"]:
            logger.warning(f"💭 {symbol}: {result['emotion']}")

        return signal

    except ZeroDivisionError:
        logger.warning(f"{symbol}: skipping — zero division (likely after-hours data)")
        return None
    except KeyError as e:
        logger.warning(f"{symbol}: missing field {e} in response")
        return None
    except Exception as e:
        logger.error(f"{symbol}: unexpected error — {e}")
        return None


def run():
    logger.info("=" * 50)
    logger.info("  🤖 Snapshot Agent — Groww Order Book Analyzer")
    logger.info("=" * 50)
    logger.info(f"  Watchlist: {', '.join(WATCHLIST)}")
    logger.info(f"  Poll interval: {POLL_SEC}s")
    logger.info(f"  Signals file: {SIGNALS_FILE.absolute()}")
    logger.info("=" * 50)

    poll_count = 0

    while True:
        poll_count += 1
        positions        = _load_positions()
        watchlist_status = []

        for symbol in WATCHLIST:
            sig = run_once(symbol, positions)
            if sig:
                watchlist_status.append(sig)
                if sig["signal"] in ("BUY", "SELL", "EXIT", "AVOID", "TRAIL_SL") or sig.get("emotion"):
                    _all_signals.append(sig)
            time.sleep(1)   # stagger to avoid rate limiting

        _write_output(_all_signals, watchlist_status)

        if poll_count % 10 == 0:
            logger.info(f"⏱  Poll #{poll_count} complete — {len(watchlist_status)} stocks active")

        time.sleep(max(0, POLL_SEC - len(WATCHLIST)))


if __name__ == "__main__":
    run()