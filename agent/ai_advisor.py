# agent/ai_advisor.py
"""
GPT-4o trading advisor.
Takes enriched market context → returns structured trade decision.
Designed to override emotional bias with data-driven reasoning.
"""

import json
from datetime import datetime
from openai import OpenAI
from config.settings import OPENAI_API_KEY, MAX_LOSS_PER_TRADE_RS, POSITION_SIZE_RS

client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """You are a senior intraday trading advisor for Indian equity markets (NSE).
Your job is to give CLEAR, UNEMOTIONAL, DATA-DRIVEN trade decisions.

The trader struggles with emotional decisions — revenge trading after losses, holding losers too long,
cutting winners early. Your role is to override those emotions with logic.

Rules you ALWAYS follow:
1. Never suggest a trade without a clear stop loss
2. Only suggest entry if R:R ≥ 1.5
3. If the market structure is unclear, say WAIT — never force a trade
4. Keep reasoning short, direct, and specific to the numbers given
5. If the trader asks emotional questions ("should I average down?", "should I hold?"), 
   answer based ONLY on the technical data — not sentiment

Return ONLY valid JSON. No markdown, no extra text."""

DECISION_SCHEMA = """{
  "action": "BUY | SELL | WAIT | EXIT_LONG | EXIT_SHORT",
  "confidence": <0-100 integer>,
  "entry": <float or null>,
  "stop_loss": <float>,
  "target_1": <float>,
  "target_2": <float or null>,
  "risk_reward": <float>,
  "risk_rs": <estimated ₹ risk based on position size>,
  "holding_time": "<e.g. 15-45 min>",
  "reasoning": "<2-3 sentences, cite actual indicator values>",
  "emotional_alert": "<null or a warning if the setup looks like an emotional trade>",
  "rule_for_session": "<one actionable rule for the rest of today>"
}"""


def get_decision(symbol: str, ind: dict, bias: str, nifty_change: float = 0.0,
                 question: str = None, tick: dict = None) -> dict:
    """
    Main advisor call. Returns structured trade decision.
    `tick` contains raw Groww fields: bid, ask, circuits, week52, etc.
    """
    now = datetime.now().strftime("%H:%M")
    t   = tick or {}

    context = f"""
Symbol: {symbol}
Time: {now} IST
Nifty today: {'+' if nifty_change >= 0 else ''}{nifty_change:.2f}%
Pre-filter bias: {bias}

Live Groww market data:
- LTP:             ₹{ind.get('ltp', 'N/A')}
- Bid / Ask:       ₹{t.get('bid_price', '—')} / ₹{t.get('ask_price', '—')}
- Day change:      {t.get('day_change_perc', 0):+.2f}%
- Volume today:    {t.get('volume', 0):,}
- VWAP:            ₹{ind.get('vwap', 'N/A')} ({'above' if ind.get('above_vwap') else 'below'} VWAP by {ind.get('vs_vwap_pct', 0):.2f}%)
- EMA 9:           ₹{ind.get('ema_fast', 'N/A')}
- EMA 21:          ₹{ind.get('ema_slow', 'N/A')}
- RSI (14):        {ind.get('rsi', 'N/A')}
- ATR (14):        ₹{ind.get('atr', 'N/A')}
- Volume ratio:    {ind.get('volume_ratio', 'N/A')}x average
- Trend:           {ind.get('trend', 'N/A')}
- Support:         ₹{ind.get('support', 'N/A')}
- Resistance:      ₹{ind.get('resistance', 'N/A')}
- 52w High/Low:    ₹{t.get('week_52_high', '—')} / ₹{t.get('week_52_low', '—')}
- Circuits:        Upper ₹{t.get('upper_circuit', '—')} / Lower ₹{t.get('lower_circuit', '—')}

ATR-based suggested levels:
- SL (long):       ₹{ind.get('sl_long', 'N/A')}
- SL (short):      ₹{ind.get('sl_short', 'N/A')}
- Target (long):   ₹{ind.get('target_long', 'N/A')}
- Target (short):  ₹{ind.get('target_short', 'N/A')}

Risk params:
- Max loss per trade: ₹{MAX_LOSS_PER_TRADE_RS}
- Position size:      ₹{POSITION_SIZE_RS}

{f'Trader question: {question}' if question else ''}

Analyze this setup and return a trade decision using this exact JSON schema:
{DECISION_SCHEMA}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=600,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": context}
            ]
        )
        raw = response.choices[0].message.content or "{}"
        decision = json.loads(raw)
        decision["symbol"]    = symbol
        decision["timestamp"] = datetime.now().isoformat()
        decision["indicators"] = ind
        return decision

    except Exception as e:
        return {
            "action": "WAIT",
            "confidence": 0,
            "reasoning": f"AI error: {e}. Defaulting to WAIT.",
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }


def get_emotional_check(question: str, symbol: str, ind: dict, open_position: dict = None) -> dict:
    """
    For real-time chat — trader asks emotional questions like
    'should I average down?', 'should I hold this?', 'I'm down ₹3000 what do I do?'
    """
    position_ctx = ""
    if open_position:
        pnl = (ind.get("ltp", 0) - open_position.get("entry", 0)) * open_position.get("qty", 0)
        position_ctx = f"""
Open position:
- Entry: ₹{open_position.get('entry')}
- Qty:   {open_position.get('qty')}
- Side:  {open_position.get('side')}
- Current P&L: ₹{pnl:.0f}
- Stop loss was: ₹{open_position.get('sl')}
"""

    prompt = f"""
Trader question: "{question}"
Symbol: {symbol}
Current LTP: ₹{ind.get('ltp', 'N/A')}
RSI: {ind.get('rsi', 'N/A')}
Trend: {ind.get('trend', 'N/A')}
{position_ctx}

Answer this as a strict, unemotional trading coach. If the question suggests emotional trading
(averaging down on a loser, refusing to accept a stop loss, revenge trading), 
call it out directly and give the data-based answer.

Return JSON:
{{
  "answer": "<direct 2-3 sentence response citing data>",
  "action": "HOLD | EXIT | ADD | WAIT | TAKE_PROFIT",
  "warning": "<null or emotional bias warning>",
  "rule": "<one rule to follow right now>"
}}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=300,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are a strict, data-driven intraday trading coach. No emotional coddling."},
                {"role": "user",   "content": prompt}
            ]
        )
        return json.loads(response.choices[0].message.content or "{}")
    except Exception as e:
        return {"answer": f"Error: {e}", "action": "WAIT", "warning": None, "rule": "When in doubt, stay out."}
