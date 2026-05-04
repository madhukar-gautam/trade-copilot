# agent/gpt_advisor.py
"""
GPT-4o powered trading advisor.

Called by snapshot_agent when a strong signal is detected.
Sends order book context to GPT-4o, gets back structured
trading advice with entry, SL1, SL2, T1, T2, reasoning.

Usage:
    from agent.gpt_advisor import GPTAdvisor
    advisor = GPTAdvisor(api_key="sk-...")
    advice  = advisor.analyse(symbol, snap_data, history)
"""

import json
import os
from datetime import datetime
from typing import Optional
from logzero import logger

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("openai package not installed. Run: pip install openai")


SYSTEM_PROMPT = """You are an expert NSE intraday trader specialising in order book analysis.
You analyse live Groww order book data and give precise trading signals.

Your analysis style:
- Focus on buy:sell ratio, wall detection, range position, momentum
- SL must be placed just below/above nearest significant order book level
- Give two SL levels: SL1 (tight, from order book) and SL2 (wide, day structure)
- Only recommend BUY when book ratio > 2:1 AND range position < 80%
- Only recommend SELL/SHORT when sell ratio > 1.7:1 AND buyers thin
- WAIT when signal is unclear or stock is extended (>85% range)
- Always flag emotional risks (chasing, revenge trading, FOMO)

Response format — always return valid JSON only, no markdown:
{
  "signal": "BUY|SHORT|WAIT|AVOID",
  "confidence": 0-100,
  "entry": price,
  "sl1": price,
  "sl1_reason": "Below X-unit buyer at ₹Y",
  "sl2": price,
  "sl2_reason": "Below day structure / key level",
  "t1": price,
  "t2": price,
  "rr_t1": ratio,
  "reasoning": "2-3 sentence explanation",
  "warning": "emotional/risk warning or empty string",
  "wall_alert": "significant wall description or empty string"
}"""


def _build_prompt(symbol: str, snap: dict, history: list, open_position: Optional[dict] = None) -> str:
    """Build the user prompt from order book data."""

    lines = [
        f"Stock: {symbol}",
        f"Time: {datetime.now().strftime('%H:%M:%S')}",
        f"LTP: ₹{snap.get('ltp', 0)}",
        f"Day change: {snap.get('day_change_pct', 0):.2f}%",
        f"Day range: ₹{snap.get('day_low', 0)} – ₹{snap.get('day_high', 0)}",
        f"Range position: {snap.get('range_pct', 0):.1f}% of day range",
        f"Volume: {snap.get('volume', 0):,}",
        f"Buy:sell ratio: {snap.get('book_ratio', 0):.2f}:1",
        f"Total buy queue: {snap.get('total_buy', 0):,}",
        f"Total sell queue: {snap.get('total_sell', 0):,}",
        f"Spread: ₹{snap.get('spread', 0):.2f}",
        "",
        "Order book (top 5 levels):",
        "BUY side:",
    ]

    for level in snap.get('buy_levels', []):
        lines.append(f"  ₹{level['price']} — {level['quantity']:,} qty ({level['orderCount']} orders)")

    lines.append("SELL side:")
    for level in snap.get('sell_levels', []):
        lines.append(f"  ₹{level['price']} — {level['quantity']:,} qty ({level['orderCount']} orders)")

    # Walls
    if snap.get('buy_wall'):
        w = snap['buy_wall']
        lines.append(f"\nBuy wall detected: ₹{w['price']} — {w['quantity']:,} qty ({w['orderCount']} orders)")
    if snap.get('sell_wall'):
        w = snap['sell_wall']
        lines.append(f"Sell wall detected: ₹{w['price']} — {w['quantity']:,} qty ({w['orderCount']} orders)")

    # Snapshot history (momentum)
    if history and len(history) > 1:
        lines.append(f"\nSnapshot history ({len(history)} snaps):")
        for h in history[-4:]:
            lines.append(
                f"  {h.get('time', '')} | LTP ₹{h.get('ltp', 0)} | "
                f"Ratio {h.get('book_ratio', 0):.2f}:1 | "
                f"Range {h.get('range_pct', 0):.0f}%"
            )

    # Open position context
    if open_position:
        lines.append(f"\nOpen position: {open_position.get('side')} {open_position.get('qty')} shares")
        lines.append(f"Entry: ₹{open_position.get('entry')} | Current SL: ₹{open_position.get('sl')}")
        lines.append(f"P&L: ₹{open_position.get('pnl', 0):.0f}")
        lines.append("Question: Should I HOLD, EXIT, BOOK_PARTIAL, or TRAIL_SL?")
    else:
        lines.append("\nQuestion: Should I enter a trade? If yes, give precise levels.")

    return "\n".join(lines)


class GPTAdvisor:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.client  = None
        self.call_count = 0
        self.total_tokens = 0

        if not OPENAI_AVAILABLE:
            logger.error("openai package not installed. Run: pip install openai --break-system-packages")
            return

        if not self.api_key:
            logger.error("OPENAI_API_KEY not set in settings.py or environment")
            return

        try:
            self.client = OpenAI(api_key=self.api_key)
            logger.info("✅ GPT-4o advisor initialised")
        except Exception as e:
            logger.error(f"Failed to init OpenAI client: {e}")

    def is_ready(self) -> bool:
        return self.client is not None

    def analyse(
        self,
        symbol: str,
        snap: dict,
        history: list = None,
        open_position: dict = None,
        model: str = "gpt-4o",
    ) -> Optional[dict]:
        """
        Call GPT-4o with order book data.
        Returns structured advice dict or None if call fails.
        """
        if not self.is_ready():
            return None

        try:
            prompt = _build_prompt(symbol, snap, history or [], open_position)

            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.1,      # Low temp for consistent trading advice
                max_tokens=500,
                response_format={"type": "json_object"},
            )

            self.call_count   += 1
            self.total_tokens += response.usage.total_tokens

            raw  = response.choices[0].message.content
            data = json.loads(raw)

            # Add metadata
            data["symbol"]     = symbol
            data["analysed_at"]= datetime.now().isoformat()
            data["model"]      = model
            data["ltp"]        = snap.get("ltp", 0)
            data["tokens_used"]= response.usage.total_tokens

            logger.info(
                f"🤖 GPT-4o {symbol}: {data.get('signal')} {data.get('confidence')}% | "
                f"Entry ₹{data.get('entry')} SL1 ₹{data.get('sl1')} T1 ₹{data.get('t1')} | "
                f"Tokens: {response.usage.total_tokens}"
            )

            if data.get("warning"):
                logger.warning(f"⚠ GPT-4o warning for {symbol}: {data['warning']}")

            return data

        except json.JSONDecodeError as e:
            logger.error(f"GPT-4o returned invalid JSON for {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"GPT-4o call failed for {symbol}: {e}")
            return None

    def analyse_position(self, symbol: str, snap: dict, position: dict, history: list = None) -> Optional[dict]:
        """Analyse an open position — should we hold, exit, trail SL?"""
        return self.analyse(symbol, snap, history, open_position=position)

    def usage_summary(self) -> dict:
        """Return API usage stats."""
        # GPT-4o pricing: $2.50/1M input, $10/1M output tokens
        # Rough estimate: 600 tokens per call average
        cost_usd = (self.total_tokens / 1_000_000) * 5.0  # blended rate
        cost_inr = cost_usd * 84
        return {
            "calls":        self.call_count,
            "total_tokens": self.total_tokens,
            "cost_usd":     round(cost_usd, 4),
            "cost_inr":     round(cost_inr, 2),
        }
