# agent/indicators.py
"""
Computes all technical indicators from raw OHLCV candles.
Pure Python + numpy — no TA-Lib dependency.
"""

import numpy as np
from typing import Optional
from config.settings import RSI_PERIOD, EMA_FAST, EMA_SLOW, ATR_PERIOD, VOLUME_AVG_PERIODS


def _np(arr): return np.array(arr, dtype=float)


# ── VWAP ─────────────────────────────────────────────────────
def vwap(candles: list) -> Optional[float]:
    """Session VWAP = Σ(TP × Volume) / Σ(Volume)"""
    if len(candles) < 2:
        return None
    tp  = _np([(c["high"] + c["low"] + c["close"]) / 3 for c in candles])
    vol = _np([c["volume"] for c in candles])
    total_vol = vol.sum()
    if total_vol == 0:
        return None
    return float((tp * vol).sum() / total_vol)


# ── EMA ──────────────────────────────────────────────────────
def ema(candles: list, period: int) -> Optional[float]:
    if len(candles) < period:
        return None
    closes = _np([c["close"] for c in candles])
    k = 2 / (period + 1)
    e = closes[0]
    for price in closes[1:]:
        e = price * k + e * (1 - k)
    return float(e)


def ema_series(candles: list, period: int) -> list:
    if len(candles) < period:
        return []
    closes = _np([c["close"] for c in candles])
    k = 2 / (period + 1)
    result = [closes[0]]
    for price in closes[1:]:
        result.append(price * k + result[-1] * (1 - k))
    return result


# ── RSI ──────────────────────────────────────────────────────
def rsi(candles: list, period: int = RSI_PERIOD) -> Optional[float]:
    if len(candles) < period + 1:
        return None
    closes = _np([c["close"] for c in candles[-(period + 1):]])
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains[:period].mean()
    avg_loss = losses[:period].mean()
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


# ── ATR ──────────────────────────────────────────────────────
def atr(candles: list, period: int = ATR_PERIOD) -> Optional[float]:
    if len(candles) < period + 1:
        return None
    recent = candles[-(period + 1):]
    trs = []
    for i in range(1, len(recent)):
        h, l, pc = recent[i]["high"], recent[i]["low"], recent[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return float(np.mean(trs[-period:]))


# ── Volume ratio ─────────────────────────────────────────────
def volume_ratio(candles: list) -> Optional[float]:
    """Current candle volume vs rolling average."""
    if len(candles) < VOLUME_AVG_PERIODS + 1:
        return None
    avg = np.mean([c["volume"] for c in candles[-(VOLUME_AVG_PERIODS + 1):-1]])
    if avg == 0:
        return None
    return float(candles[-1]["volume"] / avg)


# ── Support / Resistance ──────────────────────────────────────
def support_resistance(candles: list, lookback: int = 20):
    if len(candles) < lookback:
        return None, None
    recent = candles[-lookback:]
    highs = [c["high"] for c in recent]
    lows  = [c["low"]  for c in recent]
    return float(min(lows)), float(max(highs))


# ── Trend ────────────────────────────────────────────────────
def trend(candles: list) -> str:
    fast = ema(candles, EMA_FAST)
    slow = ema(candles, EMA_SLOW)
    if fast is None or slow is None:
        return "unknown"
    if fast > slow * 1.002:
        return "uptrend"
    if fast < slow * 0.998:
        return "downtrend"
    return "sideways"


# ── All indicators in one call ────────────────────────────────
def compute_all(candles: list, live_price: float) -> dict:
    """Returns a dict of all indicators for a symbol."""
    if len(candles) < 2:
        return {}

    _atr  = atr(candles)
    sup, res = support_resistance(candles)

    return {
        "ltp":          live_price,
        "vwap":         vwap(candles),
        "ema_fast":     ema(candles, EMA_FAST),
        "ema_slow":     ema(candles, EMA_SLOW),
        "rsi":          rsi(candles),
        "atr":          _atr,
        "volume_ratio": volume_ratio(candles),
        "support":      sup,
        "resistance":   res,
        "trend":        trend(candles),
        "candle_count": len(candles),
        # Derived
        "above_vwap":   (live_price > vwap(candles)) if vwap(candles) else None,
        "vs_vwap_pct":  round((live_price - vwap(candles)) / vwap(candles) * 100, 3) if vwap(candles) else None,
        "sl_long":      round(live_price - _atr * 1.5, 2) if _atr else None,
        "sl_short":     round(live_price + _atr * 1.5, 2) if _atr else None,
        "target_long":  round(live_price + _atr * 2.5, 2) if _atr else None,
        "target_short": round(live_price - _atr * 2.5, 2) if _atr else None,
    }
