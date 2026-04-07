# agent/copilot.py
"""
Main orchestrator. Runs every SCAN_EVERY_SEC seconds.
Uses Groww REST API for market data (no Angel One needed).
"""

import json
import time
import threading
from datetime import datetime
from pathlib import Path
from logzero import logger

import agent.data_feed as feed
from agent.indicators import compute_all
from agent.signal_engine import pre_filter, is_tradeable_time
from agent.ai_advisor import get_decision, get_emotional_check
from config.settings import (
    WATCHLIST, NIFTY_SYMBOL, SCAN_EVERY_SEC, AI_COOLDOWN_SEC,
    MAX_DAILY_LOSS_RS
)

SIGNALS_FILE  = Path("signals.json")
CHAT_IN_FILE  = Path("chat_in.json")
CHAT_OUT_FILE = Path("chat_out.json")

_last_ai_call   = {}
_signals        = []
_daily_loss     = 0.0
_open_positions = {}
_lock = threading.Lock()


def _write_signals():
    with _lock:
        data = {
            "signals":          _signals[-50:],
            "daily_loss":       _daily_loss,
            "open_positions":   _open_positions,
            "watchlist_status": _get_watchlist_status(),
            "nifty":            _get_nifty_status(),
            "updated_at":       datetime.now().isoformat(),
        }
    SIGNALS_FILE.write_text(json.dumps(data, indent=2))


def _get_nifty_status() -> dict:
    tick = feed.get_live_tick(NIFTY_SYMBOL)
    return {
        "ltp":             tick.get("ltp", 0),
        "day_change_perc": tick.get("day_change_perc", 0),
        "day_open":        tick.get("day_open", 0),
        "day_high":        tick.get("day_high", 0),
        "day_low":         tick.get("day_low", 0),
    }


def _get_watchlist_status() -> list:
    result = []
    for sym in WATCHLIST:
        tick    = feed.get_live_tick(sym)
        candles = feed.get_candles(sym)
        ind     = compute_all(candles, tick.get("ltp", 0)) if tick and candles else {}
        result.append({
            "symbol":          sym,
            "ltp":             tick.get("ltp"),
            "day_change_perc": tick.get("day_change_perc", 0),
            "rsi":             round(ind.get("rsi") or 0, 1),
            "vwap":            round(ind.get("vwap") or 0, 2),
            "ema_fast":        round(ind.get("ema_fast") or 0, 2),
            "ema_slow":        round(ind.get("ema_slow") or 0, 2),
            "trend":           ind.get("trend", "—"),
            "volume_ratio":    round(ind.get("volume_ratio") or 0, 1),
            "atr":             round(ind.get("atr") or 0, 2),
            "support":         round(ind.get("support") or 0, 2),
            "resistance":      round(ind.get("resistance") or 0, 2),
            "above_vwap":      ind.get("above_vwap"),
            "candles":         len(candles),
            "bid":             tick.get("bid_price", 0),
            "ask":             tick.get("ask_price", 0),
            "week_52_high":    tick.get("week_52_high", 0),
            "week_52_low":     tick.get("week_52_low", 0),
            "upper_circuit":   tick.get("upper_circuit", 0),
            "lower_circuit":   tick.get("lower_circuit", 0),
        })
    return result


def _can_call_ai(symbol: str) -> bool:
    return (time.time() - _last_ai_call.get(symbol, 0)) > AI_COOLDOWN_SEC


def _process_symbol(symbol: str, nifty_change: float):
    global _daily_loss

    if _daily_loss <= -MAX_DAILY_LOSS_RS:
        logger.warning(f"⛔ Daily loss limit ₹{abs(_daily_loss):.0f} hit. No new signals.")
        return

    tick    = feed.get_live_tick(symbol)
    candles = feed.get_candles(symbol)

    if not tick or not candles:
        logger.debug(f"⏭  {symbol}: no data yet ({len(candles)} candles)")
        return

    ind    = compute_all(candles, tick["ltp"])
    result = pre_filter(symbol, ind)

    if not result["should_call_ai"]:
        logger.debug(f"⏭  {symbol}: {result['reason']}")
        return

    if not _can_call_ai(symbol):
        logger.debug(f"⏭  {symbol}: AI cooldown active")
        return

    logger.info(f"🔍 {symbol} @ ₹{tick['ltp']} → {result['reason']}")
    _last_ai_call[symbol] = time.time()

    decision = get_decision(
        symbol       = symbol,
        ind          = ind,
        bias         = result["bias"],
        nifty_change = nifty_change,
        tick         = tick,
    )

    if decision.get("action") in ("WAIT", None):
        logger.info(f"⏸  {symbol}: WAIT — {decision.get('reasoning', '')[:80]}")
        return

    signal = {
        **decision,
        "pre_filter_reason": result["reason"],
        "ltp":               tick.get("ltp"),
        "bid":               tick.get("bid_price"),
        "ask":               tick.get("ask_price"),
        "day_change_perc":   tick.get("day_change_perc"),
        "volume":            tick.get("volume"),
        "upper_circuit":     tick.get("upper_circuit"),
        "lower_circuit":     tick.get("lower_circuit"),
    }

    with _lock:
        _signals.append(signal)

    logger.info(
        f"🚨 SIGNAL: {symbol} {decision['action']} @ ₹{decision.get('entry')} | "
        f"SL ₹{decision.get('stop_loss')} | T1 ₹{decision.get('target_1')} | "
        f"R:R {decision.get('risk_reward')}x | Conf {decision.get('confidence')}%"
    )
    _write_signals()


def _handle_chat():
    if not CHAT_IN_FILE.exists():
        return
    try:
        data = json.loads(CHAT_IN_FILE.read_text())
        if not data.get("pending"):
            return

        symbol   = data.get("symbol", WATCHLIST[0] if WATCHLIST else "NIFTY")
        question = data.get("question", "")
        tick     = feed.get_live_tick(symbol)
        candles  = feed.get_candles(symbol)
        ind      = compute_all(candles, tick.get("ltp", 0)) if tick and candles else {}
        pos      = _open_positions.get(symbol)

        answer = get_emotional_check(question, symbol, ind, pos)

        data["pending"] = False
        CHAT_IN_FILE.write_text(json.dumps(data))
        CHAT_OUT_FILE.write_text(json.dumps({
            "question": question,
            "symbol":   symbol,
            "answer":   answer,
            "ts":       datetime.now().isoformat(),
        }))
        logger.info(f"💬 {symbol}: {answer.get('action')} — {answer.get('answer','')[:60]}")
    except Exception as e:
        logger.warning(f"Chat error: {e}")


def run():
    logger.info("=" * 55)
    logger.info("  🤖 AI Trade Co-Pilot — Groww API + GPT-4o")
    logger.info("=" * 55)

    feed.start_feed()

    # Wait for candles to build up (need ~15 for indicators)
    logger.info(f"⏳ Waiting {SCAN_EVERY_SEC}s for first candles to form...")
    time.sleep(SCAN_EVERY_SEC)

    logger.info(f"👁  Scanning {len(WATCHLIST)} stocks every {SCAN_EVERY_SEC}s")
    logger.info(f"📊 Nifty: {feed.get_nifty_change():+.2f}%")

    while True:
        nifty_change = feed.get_nifty_change()

        if is_tradeable_time():
            for sym in WATCHLIST:
                try:
                    _process_symbol(sym, nifty_change)
                except Exception as e:
                    logger.error(f"Error {sym}: {e}")
        else:
            logger.debug("Outside market hours — watchdog only")

        _handle_chat()
        _write_signals()
        time.sleep(SCAN_EVERY_SEC)


if __name__ == "__main__":
    run()
