# agent/snapshot_agent.py
"""
GPT-4o powered snapshot agent.
Polls Groww, detects strong signals, calls GPT-4o for deep analysis.
"""

import json
import time
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path
from logzero import logger
from collections import defaultdict
from zoneinfo import ZoneInfo
import requests

IST = ZoneInfo("Asia/Kolkata")

from agent.order_book_analyzer import full_analysis, SnapHistory
from agent.gpt_advisor import GPTAdvisor
from config.settings import (
    GROWW_BASE_URL, WATCHLIST,
    OPENAI_API_KEY,
    GPT_BUY_RATIO_THRESHOLD,
    GPT_SELL_RATIO_THRESHOLD,
    GPT_MIN_CONFIDENCE,
    GPT_COOLDOWN_SEC,
)

SIGNALS_FILE    = Path("snapshot_signals.json")
GPT_ALERTS_FILE = Path("gpt_alerts.json")
POSITION_FILE   = Path("positions.json")
POLL_SEC        = 10
MAX_SIGNALS     = 200
MAX_GPT_ALERTS  = 50

_histories      = defaultdict(SnapHistory)
_session        = requests.Session()
_all_signals    = []
_gpt_alerts     = []
_last_gpt_call: dict = {}


def _sleep_if_outside_market_hours(
    market_open: dt_time = dt_time(9, 0),
    market_close: dt_time = dt_time(15, 30),
) -> None:
    """
    Run only during NSE market hours in IST (Asia/Kolkata):
    - Weekdays (Mon–Fri)
    - 09:00–15:30 IST

    Uses explicit IST timezone so this works correctly on any
    server regardless of the system timezone (e.g. Fly.io Singapore).
    """
    while True:
        now = datetime.now(IST)

        is_weekday = now.weekday() < 5          # Mon=0..Fri=4
        now_t      = now.time().replace(tzinfo=None)
        in_hours   = market_open <= now_t <= market_close

        if is_weekday and in_hours:
            return

        # Compute next open in IST
        if is_weekday and now_t < market_open:
            next_open = datetime.combine(now.date(), market_open, tzinfo=IST)
        else:
            d = now.date() + timedelta(days=1)
            while d.weekday() >= 5:             # skip Sat/Sun
                d += timedelta(days=1)
            next_open = datetime.combine(d, market_open, tzinfo=IST)

        sleep_sec = max(60, int((next_open - now).total_seconds()))
        chunk     = min(sleep_sec, 6 * 60 * 60)  # cap at 6h so we can log periodically
        logger.info(
            f"⏸ Outside market hours (IST {now.strftime('%a %H:%M')}). "
            f"Sleeping until {next_open.strftime('%a %d-%b %H:%M IST')} "
            f"({sleep_sec // 3600}h {(sleep_sec % 3600) // 60}m away)."
        )
        time.sleep(chunk)


def _get_headers() -> dict:
    from config.settings import GROWW_API_KEY
    try:
        from config.settings import GROWW_COOKIE
    except ImportError:
        GROWW_COOKIE = ""
    try:
        token_file = Path("/app/data/token.json")
        if token_file.exists():
            data   = json.loads(token_file.read_text())
            token  = data.get("token", GROWW_API_KEY)
            cookie = data.get("cookie", GROWW_COOKIE)
        else:
            token  = GROWW_API_KEY
            cookie = GROWW_COOKIE
    except Exception:
        token  = GROWW_API_KEY
        cookie = GROWW_COOKIE

    token = token.strip()
    if not token.lower().startswith("bearer "):
        token = f"Bearer {token}"
    headers = {"Authorization": token, "Accept": "application/json",
                "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    if cookie and cookie.strip():
        headers["Cookie"] = cookie.strip()
    return headers


def _fetch(symbol: str) -> dict | None:
    try:
        url    = f"{GROWW_BASE_URL}/live-data/quote"
        params = {"exchange": "NSE", "segment": "CASH", "trading_symbol": symbol}
        r = _session.get(url, params=params, headers=_get_headers(), timeout=8)
        if r.status_code == 401:
            logger.error("❌ 401 — token expired. Update via iPhone Settings tab.")
            return None
        if r.status_code == 400:
            logger.warning(f"⚠ 400 Bad Request for {symbol}")
            return None
        r.raise_for_status()
        data = r.json()
        return data["payload"] if data.get("status") == "SUCCESS" else None
    except requests.exceptions.Timeout:
        logger.warning(f"{symbol}: timeout")
        return None
    except Exception as e:
        logger.warning(f"{symbol}: {e}")
        return None


def _load_positions() -> dict:
    if POSITION_FILE.exists():
        try: return json.loads(POSITION_FILE.read_text())
        except Exception: pass
    return {}


def _should_call_gpt(symbol: str, signal: dict) -> tuple:
    ratio     = signal.get("book_ratio", 0)
    bias      = signal.get("book_bias", "")
    range_pct = signal.get("range_pct", 50)
    vol       = signal.get("vol_quality", "")
    sig       = signal.get("signal", "")

    if vol in ("DANGEROUS", "THIN"):
        return False, "volume too thin"

    last = _last_gpt_call.get(symbol, 0)
    if time.time() - last < GPT_COOLDOWN_SEC:
        return False, f"cooldown {int(GPT_COOLDOWN_SEC - (time.time()-last))}s"

    if bias == "BUY" and ratio >= GPT_BUY_RATIO_THRESHOLD and range_pct < 82:
        return True, f"BUY ratio {ratio:.2f}:1"

    if bias == "SELL" and ratio > 0 and (1/ratio) >= GPT_SELL_RATIO_THRESHOLD and range_pct > 18:
        return True, f"SELL ratio {(1/ratio):.2f}:1"

    if sig in ("BUY", "SELL") and signal.get("confidence", 0) >= GPT_MIN_CONFIDENCE:
        return True, f"rule {sig} {signal['confidence']}%"

    return False, "threshold not met"


def _build_snap_for_gpt(payload: dict, result: dict) -> dict:
    snap = result.get("snap", {})
    return {
        "ltp":          snap.get("ltp", 0),
        "day_change_pct": snap.get("day_change_pct", 0),
        "day_high":     snap.get("day_high", 0),
        "day_low":      snap.get("day_low", 0),
        "range_pct":    snap.get("range_pct", 0),
        "volume":       snap.get("volume", 0),
        "book_ratio":   snap.get("book_ratio", 0),
        "total_buy":    snap.get("total_buy", 0),
        "total_sell":   snap.get("total_sell", 0),
        "spread":       snap.get("spread", 0),
        "buy_levels":   snap.get("buy_levels", []),
        "sell_levels":  snap.get("sell_levels", []),
        "buy_wall":     result.get("walls", {}).get("buy"),
        "sell_wall":    result.get("walls", {}).get("sell"),
    }


def _build_history_for_gpt(symbol: str) -> list:
    return [
        {"time": h.get("recorded_at", "")[-8:-3],
         "ltp": h.get("ltp", 0),
         "book_ratio": h.get("book_ratio", 0),
         "range_pct": h.get("range_pct", 0)}
        for h in _histories[symbol].last(5)
    ]


def _format_signal(result: dict) -> dict:
    snap   = result["snap"]
    levels = result["levels"]
    walls  = result["walls"]
    mom    = result["momentum"]
    out = {
        "symbol":      result["symbol"],     "time":       result["timestamp"],
        "signal":      result["signal"],     "confidence": result["confidence"],
        "ltp":         snap["ltp"],          "day_change": snap["day_change_pct"],
        "book_ratio":  snap["book_ratio"],   "book_bias":  snap["book_bias"],
        "range_pct":   snap["range_pct"],    "volume":     snap["volume"],
        "vol_quality": result["volume"]["quality"],
        "spread":      snap["spread"],       "snaps":      result["snaps_so_far"],
        "momentum":    mom["reason"],        "emotion":    result["emotion"],
        "wall_buy":    walls["buy"],         "wall_sell":  walls["sell"],
    }
    if "pnl" in levels:
        out.update({"position_side": levels["side"], "entry": levels["entry"],
                    "pnl_per_share": levels["pnl"],  "sl": levels["sl"],
                    "t1": levels["t1"], "t2": levels["t2"], "rr_t1": levels["rr_t1"]})
    else:
        out.update({"long_entry": levels.get("long_entry"), "long_sl": levels.get("long_sl"),
                    "long_t1": levels.get("long_t1"),       "long_rr": levels.get("long_rr"),
                    "short_entry": levels.get("short_entry"),"short_sl": levels.get("short_sl"),
                    "short_t1": levels.get("short_t1"),     "short_rr": levels.get("short_rr")})
    return out


def _write_outputs():
    try:
        SIGNALS_FILE.write_text(json.dumps({
            "signals": _all_signals[-MAX_SIGNALS:],
            "positions": _load_positions(),
            "updated_at": datetime.now().isoformat(),
        }, indent=2))
    except Exception as e:
        logger.warning(f"signals write error: {e}")
    try:
        GPT_ALERTS_FILE.write_text(json.dumps({
            "alerts": _gpt_alerts[-MAX_GPT_ALERTS:],
            "updated_at": datetime.now().isoformat(),
        }, indent=2))
    except Exception as e:
        logger.warning(f"gpt alerts write error: {e}")


def run_once(symbol: str, positions: dict, advisor: GPTAdvisor) -> dict | None:
    try:
        payload  = _fetch(symbol)
        if not payload:
            return None

        position = positions.get(symbol)
        result   = full_analysis(symbol, payload, _histories[symbol], position)
        signal   = _format_signal(result)

        if result["signal"] in ("BUY", "SELL", "EXIT", "AVOID"):
            logger.info(f"🔔 {symbol} {result['signal']} @ ₹{signal['ltp']} | "
                       f"Book {signal['book_ratio']}:1 | Range {signal['range_pct']}% | "
                       f"Conf {signal['confidence']}%")

        if result["emotion"]:
            logger.warning(f"💭 {symbol}: {result['emotion']}")

        # GPT-4o deep analysis for strong signals
        should_call, reason = _should_call_gpt(symbol, signal)
        if should_call and advisor.is_ready():
            logger.info(f"🤖 Calling GPT-4o for {symbol} — {reason}")
            gpt_advice = advisor.analyse(
                symbol,
                _build_snap_for_gpt(payload, result),
                _build_history_for_gpt(symbol),
                position,
            )
            if gpt_advice:
                _last_gpt_call[symbol] = time.time()
                signal["gpt"]             = gpt_advice
                signal["gpt_signal"]      = gpt_advice.get("signal")
                signal["gpt_confidence"]  = gpt_advice.get("confidence")
                signal["gpt_entry"]       = gpt_advice.get("entry")
                signal["gpt_sl1"]         = gpt_advice.get("sl1")
                signal["gpt_sl1_reason"]  = gpt_advice.get("sl1_reason")
                signal["gpt_sl2"]         = gpt_advice.get("sl2")
                signal["gpt_sl2_reason"]  = gpt_advice.get("sl2_reason")
                signal["gpt_t1"]          = gpt_advice.get("t1")
                signal["gpt_t2"]          = gpt_advice.get("t2")
                signal["gpt_rr"]          = gpt_advice.get("rr_t1")
                signal["gpt_reasoning"]   = gpt_advice.get("reasoning")
                signal["gpt_warning"]     = gpt_advice.get("warning")
                signal["has_gpt"]         = True
                _gpt_alerts.append({**gpt_advice,
                    "symbol": symbol,
                    "alerted_at": datetime.now().isoformat(),
                    "rule_signal": signal["signal"],
                })
                logger.info(f"✅ GPT alert: {symbol} {gpt_advice.get('signal')} "
                           f"{gpt_advice.get('confidence')}% | "
                           f"Entry ₹{gpt_advice.get('entry')} SL1 ₹{gpt_advice.get('sl1')} "
                           f"SL2 ₹{gpt_advice.get('sl2')} T1 ₹{gpt_advice.get('t1')}")

        return signal

    except ZeroDivisionError:
        return None
    except KeyError as e:
        logger.warning(f"{symbol}: missing field {e}")
        return None
    except Exception as e:
        logger.error(f"{symbol}: {e}")
        return None


def run():
    logger.info("=" * 55)
    logger.info("  🤖 Trade Co-Pilot — GPT-4o Powered Agent")
    logger.info("=" * 55)
    logger.info(f"  Watchlist : {len(WATCHLIST)} stocks")
    logger.info(f"  Poll      : every {POLL_SEC}s")
    logger.info(f"  GPT-4o    : BUY>{GPT_BUY_RATIO_THRESHOLD} | SELL>{GPT_SELL_RATIO_THRESHOLD} | Cooldown {GPT_COOLDOWN_SEC}s")
    logger.info("=" * 55)

    advisor    = GPTAdvisor(api_key=OPENAI_API_KEY)
    poll_count = 0

    while True:
        _sleep_if_outside_market_hours()

        poll_count += 1
        positions   = _load_positions()
        wl_status   = []

        for symbol in WATCHLIST:
            sig = run_once(symbol, positions, advisor)
            if sig:
                wl_status.append(sig)
                if (sig["signal"] in ("BUY","SELL","EXIT","AVOID")
                        or sig.get("emotion") or sig.get("has_gpt")):
                    _all_signals.append(sig)
            time.sleep(1)

        _write_outputs()

        if poll_count % 10 == 0:
            usage = advisor.usage_summary()
            logger.info(f"⏱ Poll #{poll_count} | {len(wl_status)} stocks | "
                       f"GPT: {usage['calls']} calls | ₹{usage['cost_inr']:.2f}")

        time.sleep(max(0, POLL_SEC - len(WATCHLIST)))


if __name__ == "__main__":
    run()
