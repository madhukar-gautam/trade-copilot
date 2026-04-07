# Trade Copilot

An intraday trading co-pilot that:

- polls live market data (currently via **Groww** quote endpoint),
- computes indicators / order-book derived signals,
- optionally calls an LLM for a second opinion (entry/exit, SL/targets, reasoning),
- serves a **Next.js dashboard** for live monitoring.

> Important: this project is a decision-support tool. You are responsible for orders, risk limits, and compliance.

## What’s inside

```text
agent/                 Python: scanners, indicators, AI advisor, orchestrators
config/                Local config (settings are git-ignored)
dashboard/             Next.js UI (dev server on :3001)
news_scanner/          News-based watchlist builder (optional)
run_agent.py           Starts the snapshot agent
morning_start.py       Daily workflow helper (news watchlist + start agent)
```

## Quickstart

### Prerequisites

- **Python 3.10+**
- **Node 18+** (for `dashboard/`)

### 1) Python setup

Create a virtual environment and install dependencies:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### 2) Configure credentials (local-only)

This repo intentionally does **not** commit secrets.

- Copy `config/settings.example.py` → `config/settings.py`
- Fill in `GROWW_API_KEY` and (optionally) `OPENAI_API_KEY`
- Adjust `WATCHLIST`

### 3) Run the agent

Snapshot agent (writes to `snapshot_signals.json` for the dashboard to read):

```bash
python run_agent.py
```

Morning workflow helper (fetches news watchlist, merges it, then starts the agent):

```bash
python morning_start.py
```

### 4) Run the dashboard

```bash
cd dashboard
npm install
npm run dev
```

Open `http://localhost:3001`.

## Data flow (high level)

```text
Groww quote/order book polling
         │
         ▼
agent/* analyzers (indicators, order book, rules)
         │
         ▼
agent/* AI advisor (optional)
         │
         ▼
snapshot_signals.json / signals.json
         │
         ▼
dashboard/ (Next.js)
```

## Repo hygiene / security

- `config/settings.py` is **git-ignored** (contains credentials).
- Runtime outputs like `snapshot_signals.json`, `signals.json`, `positions.json` are **git-ignored**.
- If you accidentally committed secrets, rotate them immediately and rewrite history before pushing anywhere.

## License

See `LICENSE`.

## Maintainer

- [madhukar-gautam](https://github.com/madhukar-gautam)
