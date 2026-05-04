# Trade Co-Pilot — Project Context for Claude

## What this project is
A full-stack AI trading co-pilot for live intraday trading on NSE via Groww.
Built by Madhukar Gautam (Senior Lead Engineer, Deutsche Telekom, Gurugram).

The system polls Groww's live order book API every 10 seconds, analyses buy:sell
ratios and wall detection, calls GPT-4o for strong signals, and surfaces alerts
on a Next.js dashboard accessible from iPhone.

---

## Architecture

```
trade-copilot/
├── agent/
│   ├── snapshot_agent.py       ← main polling loop (runs 24/7)
│   ├── order_book_analyzer.py  ← rule-based signal engine
│   ├── gpt_advisor.py          ← GPT-4o integration
│   └── data_feed.py            ← Groww REST fetcher
├── config/
│   └── settings.py             ← API keys, watchlist, thresholds
├── news_scanner/
│   └── fetch_watchlist.py      ← NSE bulk deals + announcements
├── dashboard/                  ← Next.js 14 App Router
│   └── src/app/
│       ├── page.tsx            ← full UI (single file, all tabs)
│       └── api/
│           ├── scanner/        ← scans watchlist, ranks by signal
│           ├── analyze/        ← single stock deep analysis
│           ├── poll/           ← live P&L for open trades
│           ├── trades/         ← trade journal CRUD
│           ├── watchlist/      ← persistent master watchlist
│           ├── signals/        ← rule signals + GPT alerts
│           └── token/          ← update Groww token from iPhone
├── morning_start.py            ← daily startup script
├── run_agent.py                ← starts snapshot_agent
├── Dockerfile                  ← for Fly.io deployment
└── fly.toml                    ← Fly.io config (Singapore region)
```

---

## Groww API

**Base URL:** `https://api.groww.in/v1`

**Quote endpoint:**
```
GET /live-data/quote?exchange=NSE&segment=CASH&trading_symbol=TITAGARH
```

**Required headers:**
```python
{
    "Authorization": "Bearer eyJ...",  # expires daily — refresh from Chrome F12
    "Cookie": "_cfuvid=...",           # optional but reduces rate limiting
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}
```

**Token refresh:** Chrome → groww.in → F12 → Network → any api.groww.in request
→ copy Authorization + Cookie → paste into `config/settings.py` AND `dashboard/.env.local`

**Rate limiting:** Groww allows ~9-12 requests before throttling. Scanner uses
sequential requests with 800ms delay between batches of 3.

**Symbol naming:** NSE symbols on Groww match NSE exactly EXCEPT:
- NALCO → `NATIONALUM`
- Cochin Shipyard → `COCHINSHPYD`
- Always verify symbol in Groww app before adding to watchlist

---

## Order Book Analysis Logic

**Core signal — buy:sell ratio:**
```python
book_ratio = total_buy_quantity / total_sell_quantity

# BUY signals
ratio >= 2.5 and range_pct < 85  → BUY high confidence
ratio >= 1.5 and range_pct < 60  → BUY moderate
ratio >= 2.5 and range_pct >= 85 → BUY breakout only (extended)

# SELL/SHORT signals
ratio <= 0.4 and range_pct > 20  → SELL high confidence
ratio <= 0.65 and range_pct > 40 → SELL moderate
```

**Range position:**
```python
range_pct = (ltp - day_low) / (day_high - day_low) * 100
# < 20% = near day low (good long entry)
# > 80% = near day high (extended, avoid long)
# 20-60% = sweet spot for entries
```

**Wall detection** (single large order from ≤3 accounts):
```python
is_wall = quantity >= 3000 and order_count <= 3
# Walls are key SL/target levels
# SL = just below nearest significant buyer (long)
# SL = just above nearest significant seller (short)
```

**Two SL system (always give both):**
- SL1: tight, from order book (nearest significant level)
- SL2: wide, day structure (day high/low, prev close)
- SL1 triggers first, check if SL2 holds before re-entry

---

## GPT-4o Integration

**Triggers:** Call GPT-4o when:
- buy:sell ratio >= 3.0 (BUY) or sell:buy >= 1.8 (SELL/SHORT)
- Rule engine confidence >= 65%
- Volume is GOOD or EXCELLENT (not THIN or DANGEROUS)
- Cooldown: 180 seconds per symbol between calls

**Model:** `gpt-4o` via OpenAI API
**Cost:** ~₹0.80/call, ~20 calls/day max = ₹16/day

**Response format (JSON):**
```json
{
  "signal": "BUY|SHORT|WAIT|AVOID",
  "confidence": 0-100,
  "entry": 701.50,
  "sl1": 700.95,
  "sl1_reason": "Below 472-unit buyer at ₹701",
  "sl2": 698.00,
  "sl2_reason": "Below day structure",
  "t1": 707.55,
  "t2": 715.00,
  "rr_t1": 8.6,
  "reasoning": "Strong 4.2:1 buy ratio with wall absorbed...",
  "warning": "Stock at 85% range — extended",
  "wall_alert": "6787-unit sell wall at ₹701"
}
```

---

## Dashboard (Next.js 14)

**Port:** 3001 (local), Fly.io URL (cloud)
**Tabs:** Scanner | Analyze | Active Trades | History | Settings

**Scanner tab:**
- Reads from `dashboard/watchlist.json` (persistent master list)
- Scans all stocks, ranks by signal strength
- Clicking BUY/SELL row auto-adds to master list + opens Analyze
- Auto-scan configurable (30s/1m/2m/5m)

**Settings tab:**
- Update Groww token from iPhone without laptop
- Protected by ADMIN_PASSWORD env var
- Saves to `/app/data/token.json` (cloud) or local file

**GPT Alert banners:**
- Auto-appear when agent writes to `gpt_alerts.json`
- Dashboard polls `/api/signals` every 30 seconds
- Shows entry, SL1, SL2, T1, T2, reasoning, warnings
- "Analyze →" button opens full analysis for that stock

**File paths (important):**
```
process.cwd() = dashboard/ folder in Next.js
watchlist.json → dashboard/watchlist.json
gpt_alerts.json → ../gpt_alerts.json (parent) or dashboard/gpt_alerts.json
snapshot_signals.json → ../snapshot_signals.json or dashboard/snapshot_signals.json
token.json → /app/data/token.json (cloud) or local
```

---

## Trading Rules (Madhukar's style)

**Entry criteria:**
- Book ratio > 2:1 minimum, prefer > 3:1
- Range position 20-80% (not extended)
- Volume GOOD (>5L) or EXCELLENT (>50L)
- No massive sell wall directly above entry (long)
- Always confirm with 2 consecutive snapshots

**Position sizing:** ~200-700 shares typically
- Large caps (>₹1000): 150-220 shares
- Mid caps (₹200-700): 400-700 shares
- Small caps (<₹200): 700-1500 shares

**SL rules:**
- SL1 always set in Groww BEFORE entering trade
- SL2 is mental stop — if SL1 triggers, check SL2 before re-entry
- Never move SL further away — only trail it toward profit
- Stop-market orders preferred over stop-limit (avoids slippage)

**Exit rules:**
- T1 hit → book 30-40% of position
- Trail SL to entry price after T1 (risk-free trade)
- If price bounces > ₹1.50 against short after SL1 → exit at SL1, don't hold
- Never hold through lunch (12:30-1:30 PM) without clear trend

**Emotional patterns to flag:**
- Re-entering same stock immediately after exit = revenge trading
- Entering at 90%+ of day range = chasing
- Buying into existing sell wall = premature entry
- Adding to losing position = averaging down (never do this)

---

## Volume Quality
```python
volume < 100_000   → DANGEROUS (skip)
volume < 500_000   → THIN (caution)
volume < 5_000_000 → GOOD
volume >= 5_000_000 → EXCELLENT
```

---

## Daily Workflow
```bash
# Morning (8:30 AM)
python morning_start.py     # fetches NSE news watchlist + starts agent

# Dashboard
cd dashboard && npm run dev  # http://localhost:3001

# Token refresh (daily — token expires)
# Chrome → groww.in → F12 → Network → copy Authorization + Cookie
# Paste into config/settings.py AND dashboard/.env.local
```

---

## Cloud Deployment (Fly.io)
- Region: sin (Singapore)
- Free tier: 512MB RAM, always-on
- Volume: trade_data mounted at /app/data
- Token update: Settings tab on iPhone → no redeploy needed
- Logs: `fly logs` or `fly ssh console -C "cat /var/log/agent.log | tail -50"`

---

## Key Files to Know
- `config/settings.py` — all credentials and thresholds (never commit)
- `agent/gpt_advisor.py` — GPT-4o prompt and response parsing
- `agent/order_book_analyzer.py` — core signal logic (don't break this)
- `dashboard/src/app/page.tsx` — entire UI in one file (~800 lines)
- `dashboard/src/app/api/scanner/route.ts` — most frequently edited

---

## Common Issues

**Scanner returning < 20 results:**
Wrong symbol names or Groww rate limiting.
Fix: Check `npm run dev` terminal for `FAILED: SYMBOL → HTTP 400` lines.
Solution: Find correct symbol on Groww app, update watchlist.

**Token expired (401 errors):**
Update `GROWW_API_KEY` in `config/settings.py` and `dashboard/.env.local`.
On cloud: use Settings tab on iPhone.

**GPT-4o not triggering:**
Check `OPENAI_API_KEY` in settings.py.
Check thresholds: `GPT_BUY_RATIO_THRESHOLD = 3.0` — needs strong signal.
Check cooldown: `GPT_COOLDOWN_SEC = 180` — 3 min between calls per stock.

**watchlist.json not found:**
File saves to `dashboard/watchlist.json` (process.cwd() = dashboard folder).
Do not use `../watchlist.json` in Next.js routes.
