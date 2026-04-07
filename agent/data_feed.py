# agent/data_feed.py
"""
Groww REST API data feed.
Polls /v1/live-data/quote every POLL_INTERVAL_SEC seconds per stock.
Builds 1-min OHLCV candles from successive quote snapshots.
No WebSocket, no tokens, no TOTP — just the API key you already have.
"""

import time
import threading
import requests
from collections import defaultdict
from datetime import datetime
from logzero import logger

from config.settings import (
    GROWW_API_KEY, GROWW_BASE_URL, GROWW_EXCHANGE, GROWW_SEGMENT,
    WATCHLIST, NIFTY_SYMBOL, POLL_INTERVAL_SEC, CANDLE_INTERVAL_SEC
)

# ── Shared state ──────────────────────────────────────────────
candles   = defaultdict(list)   # symbol → list of completed OHLCV dicts
live_tick = {}                   # symbol → latest quote snapshot
_current  = {}                   # symbol → incomplete current candle
_lock     = threading.Lock()

_session  = requests.Session()


def _build_headers() -> dict:
    """Build headers fresh each call — token may be updated at runtime."""
    from config.settings import GROWW_API_KEY
    token = GROWW_API_KEY.strip()

    # Groww accepts token directly OR as Bearer — try both formats
    # If token already starts with "Bearer " strip it
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    return {
        "Authorization": token,          # Groww uses raw token, not "Bearer xxx"
        "Accept":        "application/json",
        "Content-Type":  "application/json",
        "User-Agent":    "Mozilla/5.0",
    }


# ── Groww quote fetcher ───────────────────────────────────────
def _fetch_quote(symbol: str) -> dict | None:
    """
    GET /v1/live-data/quote?exchange=NSE&segment=CASH&trading_symbol=SYMBOL
    Returns the payload dict or None on error.
    """
    try:
        url = f"{GROWW_BASE_URL}/live-data/quote"
        params = {
            "exchange":       GROWW_EXCHANGE,
            "segment":        GROWW_SEGMENT,
            "trading_symbol": symbol,
        }
        resp = _session.get(url, params=params, headers=_build_headers(), timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "SUCCESS":
            return data["payload"]
        else:
            logger.warning(f"Groww API error for {symbol}: {data}")
            return None
    except requests.exceptions.RequestException as e:
        logger.warning(f"Quote fetch error {symbol}: {e}")
        return None


def _parse_quote(symbol: str, payload: dict):
    """Extract key fields from Groww quote payload."""
    ltp    = payload.get("last_price") or 0.0
    volume = payload.get("volume") or 0
    ohlc   = payload.get("ohlc") or {}
    ts     = int(time.time())

    # Use last_trade_time if available, else now
    ltt = payload.get("last_trade_time")
    if ltt and isinstance(ltt, (int, float)) and ltt > 1e9:
        ts = int(ltt)

    return {
        "symbol":          symbol,
        "ltp":             ltp,
        "volume":          volume,
        "day_open":        ohlc.get("open", 0),
        "day_high":        ohlc.get("high", 0),
        "day_low":         ohlc.get("low", 0),
        "prev_close":      ohlc.get("close", 0),
        "day_change":      payload.get("day_change", 0),
        "day_change_perc": payload.get("day_change_perc", 0),
        "week_52_high":    payload.get("week_52_high", 0),
        "week_52_low":     payload.get("week_52_low", 0),
        "upper_circuit":   payload.get("upper_circuit_limit", 0),
        "lower_circuit":   payload.get("lower_circuit_limit", 0),
        "total_buy_qty":   payload.get("total_buy_quantity", 0),
        "total_sell_qty":  payload.get("total_sell_quantity", 0),
        "bid_price":       (payload.get("depth", {}).get("buy", [{}])[0] or {}).get("price", 0),
        "ask_price":       (payload.get("depth", {}).get("sell", [{}])[0] or {}).get("price", 0),
        "ts":              ts,
    }


def _update_candle(symbol: str, tick: dict):
    """Accumulate ticks into 1-min OHLCV candles."""
    ltp    = tick["ltp"]
    volume = tick["volume"]
    ts     = tick["ts"]

    if ltp <= 0:
        return

    candle_start = (ts // CANDLE_INTERVAL_SEC) * CANDLE_INTERVAL_SEC

    if symbol not in _current:
        _current[symbol] = {
            "open": ltp, "high": ltp, "low": ltp,
            "close": ltp, "volume": volume,
            "start_ts": candle_start,
        }
        return

    cur = _current[symbol]

    if candle_start > cur["start_ts"]:
        # Candle closed — save it
        completed = {**cur, "ts": cur["start_ts"]}
        candles[symbol].append(completed)
        if len(candles[symbol]) > 500:
            candles[symbol] = candles[symbol][-500:]
        # New candle
        _current[symbol] = {
            "open": ltp, "high": ltp, "low": ltp,
            "close": ltp, "volume": volume,
            "start_ts": candle_start,
        }
    else:
        cur["high"]   = max(cur["high"], ltp)
        cur["low"]    = min(cur["low"],  ltp)
        cur["close"]  = ltp
        cur["volume"] = volume  # Groww gives cumulative day volume


def _poll_symbol(symbol: str):
    """Fetch one symbol, update shared state."""
    payload = _fetch_quote(symbol)
    if not payload:
        return
    tick = _parse_quote(symbol, payload)
    with _lock:
        live_tick[symbol] = tick
        _update_candle(symbol, tick)


def _poll_loop(symbols: list, interval: float):
    """Continuously poll all symbols with staggered requests."""
    stagger = interval / max(len(symbols), 1)
    while True:
        for sym in symbols:
            try:
                _poll_symbol(sym)
            except Exception as e:
                logger.error(f"Poll error {sym}: {e}")
            time.sleep(stagger)
        # Sleep remaining time in interval
        time.sleep(max(0, interval - stagger * len(symbols)))


# ── Public API ────────────────────────────────────────────────
def start_feed():
    """Start background polling threads — one per batch of symbols."""
    all_symbols = list(WATCHLIST) + [NIFTY_SYMBOL]
    logger.info(f"🚀 Starting Groww data feed for {len(all_symbols)} symbols")
    logger.info(f"   Polling every {POLL_INTERVAL_SEC}s")

    # Single thread for all symbols (REST is lightweight)
    thread = threading.Thread(
        target=_poll_loop,
        args=(all_symbols, POLL_INTERVAL_SEC),
        daemon=True
    )
    thread.start()

    # Initial fetch — fill at least one tick before agent starts
    logger.info("⏳ Initial quote fetch...")
    for sym in all_symbols:
        try:
            _poll_symbol(sym)
            logger.info(f"   ✅ {sym}: ₹{live_tick.get(sym, {}).get('ltp', '—')}")
        except Exception as e:
            logger.warning(f"   ⚠️  {sym}: {e}")

    logger.info("✅ Data feed ready")
    return thread


def get_candles(symbol: str) -> list:
    with _lock:
        return list(candles.get(symbol, []))


def get_live_tick(symbol: str) -> dict:
    with _lock:
        return dict(live_tick.get(symbol, {}))


def get_live_candle(symbol: str) -> dict:
    with _lock:
        return dict(_current.get(symbol, {}))


def get_nifty_change() -> float:
    """Return Nifty day change % from live tick."""
    tick = get_live_tick(NIFTY_SYMBOL)
    return tick.get("day_change_perc", 0.0)
