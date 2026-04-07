# agent/signal_engine.py
"""
Rule-based pre-filter. Only passes candidates to GPT-4o
when conditions suggest a real setup is forming.
This saves AI cost and avoids noise.
"""

from datetime import datetime
from config.settings import (
    MIN_VOLUME_RATIO, MIN_RR_RATIO, NO_TRADE_AFTER,
    SL_ATR_MULTIPLIER, TARGET_ATR_MULTIPLIER
)


def _now_str():
    return datetime.now().strftime("%H:%M")


def is_tradeable_time() -> bool:
    now = _now_str()
    return "09:20" <= now <= NO_TRADE_AFTER


def _rr(entry, sl, target):
    risk   = abs(entry - sl)
    reward = abs(target - entry)
    if risk == 0:
        return 0
    return round(reward / risk, 2)


def pre_filter(symbol: str, ind: dict) -> dict:
    """
    Returns {"should_call_ai": bool, "reason": str, "bias": "LONG"|"SHORT"|"NEUTRAL"}
    """
    if not ind:
        return {"should_call_ai": False, "reason": "No indicator data yet", "bias": "NEUTRAL"}

    if not is_tradeable_time():
        return {"should_call_ai": False, "reason": "Outside trading hours", "bias": "NEUTRAL"}

    ltp   = ind.get("ltp")
    rsi_v = ind.get("rsi")
    vwap  = ind.get("vwap")
    volr  = ind.get("volume_ratio")
    atr_v = ind.get("atr")
    trend_v = ind.get("trend")
    candles = ind.get("candle_count", 0)

    if candles < 15:
        return {"should_call_ai": False, "reason": f"Only {candles} candles — need 15+", "bias": "NEUTRAL"}

    if not all([ltp, rsi_v, vwap, volr, atr_v]):
        return {"should_call_ai": False, "reason": "Missing indicators", "bias": "NEUTRAL"}

    # Volume must be elevated
    if volr < MIN_VOLUME_RATIO:
        return {
            "should_call_ai": False,
            "reason": f"Volume too low ({volr:.1f}x avg, need {MIN_VOLUME_RATIO}x)",
            "bias": "NEUTRAL"
        }

    reasons = []
    bias = "NEUTRAL"
    score = 0

    # ── LONG signals ─────────────────────────────────────────
    long_conditions = {
        "Price above VWAP":          ltp > vwap,
        "RSI 45–65 (momentum zone)": 45 < rsi_v < 65,
        "Uptrend (EMA9 > EMA21)":    trend_v == "uptrend",
        "Near support":              ind.get("support") and abs(ltp - ind["support"]) < atr_v * 0.5,
        "EMA crossover":             ind.get("ema_fast") and ind.get("ema_slow") and ind["ema_fast"] > ind["ema_slow"],
    }

    # ── SHORT signals ─────────────────────────────────────────
    short_conditions = {
        "Price below VWAP":          ltp < vwap,
        "RSI 35–55 (weak zone)":     35 < rsi_v < 55,
        "Downtrend (EMA9 < EMA21)":  trend_v == "downtrend",
        "Near resistance":           ind.get("resistance") and abs(ltp - ind["resistance"]) < atr_v * 0.5,
        "EMA death cross":           ind.get("ema_fast") and ind.get("ema_slow") and ind["ema_fast"] < ind["ema_slow"],
    }

    long_score  = sum(1 for v in long_conditions.values() if v)
    short_score = sum(1 for v in short_conditions.values() if v)

    if long_score >= 3:
        bias = "LONG"
        score = long_score
        reasons = [k for k, v in long_conditions.items() if v]
    elif short_score >= 3:
        bias = "SHORT"
        score = short_score
        reasons = [k for k, v in short_conditions.items() if v]
    else:
        return {
            "should_call_ai": False,
            "reason": f"No clear setup (long:{long_score}/5, short:{short_score}/5)",
            "bias": "NEUTRAL"
        }

    # Check minimum R:R before calling AI
    if bias == "LONG":
        sl     = ind.get("sl_long")
        target = ind.get("target_long")
    else:
        sl     = ind.get("sl_short")
        target = ind.get("target_short")

    if sl and target:
        rr = _rr(ltp, sl, target)
        if rr < MIN_RR_RATIO:
            return {
                "should_call_ai": False,
                "reason": f"R:R too low ({rr:.1f}x, need {MIN_RR_RATIO}x)",
                "bias": "NEUTRAL"
            }

    return {
        "should_call_ai": True,
        "reason": f"{bias} setup: {', '.join(reasons)} | score {score}/5 | vol {volr:.1f}x",
        "bias": bias
    }
