# agent/order_book_analyzer.py
"""
Replicates the manual order book analysis done in today's session:
- Buy:sell ratio tracking across snapshots
- Wall detection (single large orders)
- Momentum shift detection
- Position P&L tracking
- Emotional override alerts
"""

from collections import deque
from datetime import datetime
from typing import Optional


class SnapHistory:
    """Tracks last N snapshots per symbol for momentum analysis."""
    def __init__(self, maxlen=10):
        self.snaps = deque(maxlen=maxlen)

    def add(self, snap: dict):
        snap["recorded_at"] = datetime.now().isoformat()
        self.snaps.append(snap)

    def last(self, n=2) -> list:
        return list(self.snaps)[-n:]

    def count(self) -> int:
        return len(self.snaps)


def parse_groww_payload(symbol: str, payload: dict) -> dict:
    """Extract all useful fields from a Groww quote payload."""
    ohlc   = payload.get("ohlc") or {}
    depth  = payload.get("depth") or {}
    buy_d  = depth.get("buy") or []
    sell_d = depth.get("sell") or []

    ltp         = payload.get("last_price") or 0
    prev_close  = ohlc.get("close") or 0
    day_open    = ohlc.get("open") or 0
    day_high    = ohlc.get("high") or 0
    day_low     = ohlc.get("low") or 0
    volume      = payload.get("volume") or 0
    day_chg_pct = payload.get("day_change_perc") or 0

    total_buy_qty  = payload.get("total_buy_quantity") or 0
    total_sell_qty = payload.get("total_sell_quantity") or 0

    # Top 5 book levels
    buy_levels  = [{"price": b.get("price",0), "qty": b.get("quantity",0), "orders": b.get("orderCount",0)} for b in buy_d]
    sell_levels = [{"price": s.get("price",0), "qty": s.get("quantity",0), "orders": s.get("orderCount",0)} for s in sell_d]

    # Best bid/ask
    best_bid = buy_levels[0]["price"]  if buy_levels  else 0
    best_ask = sell_levels[0]["price"] if sell_levels else 0
    spread   = round(best_ask - best_bid, 2) if best_bid and best_ask else 0

    # Visible depth totals
    visible_buy_qty  = sum(l["qty"] for l in buy_levels)
    visible_sell_qty = sum(l["qty"] for l in sell_levels)

    # Range position (0-100%)
    day_range = day_high - day_low
    range_pct = round((ltp - day_low) / day_range * 100, 1) if day_range > 0 else 50.0

    # Book ratio
    book_ratio = round(total_buy_qty / total_sell_qty, 2) if total_sell_qty > 0 else (9.99 if total_buy_qty > 0 else 1.0)
    book_bias  = "BUY" if book_ratio > 1.2 else "SELL" if book_ratio < 0.83 else "NEUTRAL"

    return {
        "symbol":          symbol,
        "ltp":             ltp,
        "prev_close":      prev_close,
        "day_open":        day_open,
        "day_high":        day_high,
        "day_low":         day_low,
        "day_change_pct":  day_chg_pct,
        "volume":          volume,
        "total_buy_qty":   total_buy_qty,
        "total_sell_qty":  total_sell_qty,
        "book_ratio":      book_ratio,
        "book_bias":       book_bias,
        "best_bid":        best_bid,
        "best_ask":        best_ask,
        "spread":          spread,
        "visible_buy_qty": visible_buy_qty,
        "visible_sell_qty":visible_sell_qty,
        "buy_levels":      buy_levels,
        "sell_levels":     sell_levels,
        "range_pct":       range_pct,
        "upper_circuit":   payload.get("upper_circuit_limit") or 0,
        "lower_circuit":   payload.get("lower_circuit_limit") or 0,
        "week_52_high":    payload.get("week_52_high") or 0,
        "week_52_low":     payload.get("week_52_low") or 0,
        "last_trade_qty":  payload.get("last_trade_quantity") or 0,
    }


def detect_walls(snap: dict) -> dict:
    """Detect large single-order walls on buy or sell side."""
    walls = {"buy": None, "sell": None}

    for level in snap["buy_levels"]:
        if level["qty"] > 5000 and level["orders"] <= 3:
            walls["buy"] = {"price": level["price"], "qty": level["qty"], "orders": level["orders"]}
            break

    for level in snap["sell_levels"]:
        if level["qty"] > 5000 and level["orders"] <= 3:
            walls["sell"] = {"price": level["price"], "qty": level["qty"], "orders": level["orders"]}
            break

    return walls


def detect_momentum_shift(history: list) -> dict:
    """
    Compare last 2 snapshots for momentum changes.
    Mirrors what I was doing manually today.
    """
    if len(history) < 2:
        return {"shift": False, "direction": None, "reason": "Need more data"}

    prev = history[-2]
    curr = history[-1]

    prev_ratio = prev["book_ratio"]
    curr_ratio = curr["book_ratio"]
    prev_ltp   = prev["ltp"]
    curr_ltp   = curr["ltp"]
    prev_buy   = prev["total_buy_qty"]
    curr_buy   = curr["total_buy_qty"]

    reasons = []
    direction = None

    # Ratio flip
    if prev_ratio > 1.2 and curr_ratio < 0.83:
        reasons.append(f"Book flipped BUY→SELL ({prev_ratio:.2f}x → {curr_ratio:.2f}x)")
        direction = "BEARISH"
    elif prev_ratio < 0.83 and curr_ratio > 1.2:
        reasons.append(f"Book flipped SELL→BUY ({prev_ratio:.2f}x → {curr_ratio:.2f}x)")
        direction = "BULLISH"

    # Buy queue collapse (>40% drop)
    if prev_buy > 0 and curr_buy < prev_buy * 0.6:
        drop_pct = round((1 - curr_buy/prev_buy) * 100)
        reasons.append(f"Buy queue dropped {drop_pct}% ({prev_buy:,} → {curr_buy:,})")
        if direction != "BULLISH":
            direction = "BEARISH"

    # Buy queue surge (>50% increase)
    if prev_buy > 0 and curr_buy > prev_buy * 1.5:
        surge_pct = round((curr_buy/prev_buy - 1) * 100)
        reasons.append(f"Buy queue surged +{surge_pct}% ({prev_buy:,} → {curr_buy:,})")
        if direction != "BEARISH":
            direction = "BULLISH"

    # Price moving against large book ratio
    if curr_ratio > 3 and curr_ltp < prev_ltp:
        reasons.append(f"Dip into strong buy wall ({curr_ratio:.1f}:1) — likely bounce")
        direction = "BULLISH"
    elif curr_ratio < 0.5 and curr_ltp > prev_ltp:
        reasons.append(f"Rally into strong sell wall ({curr_ratio:.1f}:1) — likely reject")
        direction = "BEARISH"

    return {
        "shift":     len(reasons) > 0,
        "direction": direction,
        "reason":    " | ".join(reasons) if reasons else "No significant shift",
    }


def compute_levels(snap: dict, position: Optional[dict] = None) -> dict:
    """
    Compute SL and targets the same way I was doing manually:
    - SL below day low (long) or above day high (short)
    - Targets at day high, then round numbers, then circuit
    """
    ltp        = snap["ltp"]
    day_high   = snap["day_high"]
    day_low    = snap["day_low"]
    circuit_up = snap["upper_circuit"]
    circuit_dn = snap["lower_circuit"]
    atr_est    = round((day_high - day_low) * 0.5, 2)  # rough ATR from day range

    if position and position.get("side") == "LONG":
        entry = position.get("entry", ltp)
        sl    = round(day_low - 0.5, 2)
        t1    = day_high
        t2    = round(day_high + atr_est, 2)
        t3    = circuit_up
        pnl   = round((ltp - entry), 2)
        rr_t1 = round((t1 - entry) / (entry - sl), 2) if (entry - sl) > 0 else 0.0
        return {
            "side":   "LONG",
            "entry":  entry,
            "ltp":    ltp,
            "pnl":    pnl,
            "sl":     sl,
            "t1":     t1,
            "t2":     t2,
            "t3":     t3,
            "rr_t1":  rr_t1,
            "sl_dist": round(max(ltp - sl, 0), 2),
            "t1_dist": round(max(t1 - ltp, 0), 2),
        }
    elif position and position.get("side") == "SHORT":
        entry = position.get("entry", ltp)
        sl    = round(day_high + 0.5, 2)
        t1    = day_low
        t2    = round(day_low - atr_est, 2)
        t3    = circuit_dn
        pnl   = round((entry - ltp), 2)
        rr_t1 = round((entry - t1) / (sl - entry), 2) if (sl - entry) > 0 else 0.0
        return {
            "side":   "SHORT",
            "entry":  entry,
            "ltp":    ltp,
            "pnl":    pnl,
            "sl":     sl,
            "t1":     t1,
            "t2":     t2,
            "t3":     t3,
            "rr_t1":  rr_t1,
            "sl_dist": round(max(sl - ltp, 0), 2),
            "t1_dist": round(max(ltp - t1, 0), 2),
        }
    else:
        # No position — suggest potential levels
        long_sl  = round(day_low - 0.5, 2)
        short_sl = round(day_high + 0.5, 2)
        return {
            "long_entry":  snap["best_ask"],
            "long_sl":     long_sl,
            "long_t1":     day_high,
            "long_rr":     round((day_high - ltp) / (ltp - long_sl), 2) if (ltp - long_sl) > 0 else 0.0,
            "short_entry": snap["best_bid"],
            "short_sl":    short_sl,
            "short_t1":    day_low,
            "short_rr":    round((ltp - day_low) / (short_sl - ltp), 2) if (short_sl - ltp) > 0 else 0.0,
        }


def emotional_override(snap: dict, position: Optional[dict], history: list) -> Optional[str]:
    """
    Detect emotional trading patterns and return a warning.
    Based on what I observed in today's session.
    """
    if not position:
        return None

    ltp   = snap["ltp"]
    entry = position.get("entry", ltp)
    side  = position.get("side", "LONG")

    # Trading against strong book
    ratio = snap["book_ratio"]
    if side == "SHORT" and ratio > 2.5:
        return f"⚠ EMOTIONAL ALERT: You are short into {ratio:.1f}:1 buy pressure. Data says cover now."
    if side == "LONG" and ratio < 0.4:
        return f"⚠ EMOTIONAL ALERT: You are long into {ratio:.1f}:1 sell pressure. Data says exit now."

    # Holding a loss too long
    loss = (ltp - entry) if side == "LONG" else (entry - ltp)
    if loss < -5 and len(history) >= 3:
        return f"⚠ EMOTIONAL ALERT: −₹{abs(loss):.2f}/share and holding. Cut loss now — SL was set for a reason."

    # At 99% of day range — wrong entry zone
    if snap["range_pct"] > 95 and side == "LONG":
        return f"⚠ EMOTIONAL ALERT: Bought at {snap['range_pct']}% of day range. Almost no upside left today."
    if snap["range_pct"] < 5 and side == "SHORT":
        return f"⚠ EMOTIONAL ALERT: Shorted at {snap['range_pct']}% of day range. Almost no downside left today."

    # Revenge trade pattern — position entered after loss
    if position.get("after_loss") and abs(entry - ltp) < 0.5:
        return "⚠ EMOTIONAL ALERT: You entered this after a loss. Is this a revenge trade? Verify the setup."

    return None


def volume_quality(snap: dict) -> dict:
    """Assess whether volume supports intraday trading."""
    vol = snap["volume"]
    visible = snap["visible_buy_qty"] + snap["visible_sell_qty"]

    if vol < 100000:
        quality = "DANGEROUS"
        reason  = f"Only {vol:,} shares — your orders will move the price against you."
    elif vol < 500000:
        quality = "THIN"
        reason  = f"{vol:,} shares — manageable but watch slippage."
    elif vol < 5000000:
        quality = "GOOD"
        reason  = f"{vol:,} shares — liquid enough for intraday."
    else:
        quality = "EXCELLENT"
        reason  = f"{vol:,} shares — highly liquid, minimal slippage."

    return {"quality": quality, "reason": reason, "volume": vol}


def full_analysis(symbol: str, payload: dict, history: SnapHistory,
                  position: Optional[dict] = None) -> dict:
    """
    Main entry point. Call this with every Groww quote.
    Returns the same insights I was giving you manually.
    """
    snap = parse_groww_payload(symbol, payload)
    history.add(snap)

    snaps    = history.last(5)
    walls    = detect_walls(snap)
    momentum = detect_momentum_shift(snaps)
    levels   = compute_levels(snap, position)
    emotion  = emotional_override(snap, position, snaps)
    vol_q    = volume_quality(snap)

    # Overall signal
    signal = "WAIT"
    confidence = 0

    if not position:
        ratio      = snap["book_ratio"]
        range_pct  = snap["range_pct"]
        vol_ok     = vol_q["quality"] in ("GOOD", "EXCELLENT")

        if ratio > 2 and range_pct < 70 and vol_ok:
            signal     = "BUY"
            confidence = min(95, int(ratio * 20 + (70 - range_pct) * 0.5))
        elif ratio < 0.5 and range_pct > 30 and vol_ok:
            signal     = "SELL"
            confidence = min(95, int((1/ratio) * 20 + (range_pct - 30) * 0.5))
        elif vol_q["quality"] == "DANGEROUS":
            signal     = "AVOID"
            confidence = 100
    else:
        # Position management
        lvl  = levels
        side = position.get("side")
        pnl  = lvl.get("pnl", 0)

        if emotion:
            signal     = "EXIT"
            confidence = 90
        elif side == "LONG" and snap["book_ratio"] < 0.7 and momentum.get("direction") == "BEARISH":
            signal     = "EXIT"
            confidence = 80
        elif side == "SHORT" and snap["book_ratio"] > 1.5 and momentum.get("direction") == "BULLISH":
            signal     = "EXIT"
            confidence = 80
        elif pnl > 0 and walls.get("sell" if side=="LONG" else "buy"):
            wall = walls.get("sell" if side=="LONG" else "buy")
            signal     = "TRAIL_SL"
            confidence = 75
        else:
            signal     = "HOLD"
            confidence = 60

    return {
        "symbol":    symbol,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "signal":    signal,
        "confidence":confidence,
        "snap":      snap,
        "levels":    levels,
        "walls":     walls,
        "momentum":  momentum,
        "emotion":   emotion,
        "volume":    vol_q,
        "snaps_so_far": history.count(),
    }