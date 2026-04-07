#!/usr/bin/env python3
"""
morning_start.py

Run this every morning before market open (8:30 AM).
Does three things:
  1. Fetches news-based watchlist from NSE
  2. Merges with your default volatile watchlist
  3. Starts the snapshot agent

Usage:
  python morning_start.py

Or schedule it via Windows Task Scheduler at 8:30 AM every weekday.
"""

import subprocess
import sys
import json
import time
from datetime import datetime
from pathlib import Path
from logzero import logger


# Your default volatile watchlist — always included
BASE_WATCHLIST = [
    'TITAGARH', 'ADANIPOWER', 'TATAPOWER', 'SUZLON', 'NHPC',
    'SJVN', 'IREDA', 'RPOWER', 'BEL', 'HAL',
    'RAILTEL', 'RVNL', 'IRFC', 'RECLTD', 'PFC',
    'SAIL', 'NMDC', 'NALCO', 'GMDC', 'GUJALKALI',
    'EIHOTEL', 'YESBANK', 'JSWENERGY', 'INOXWIND', 'PCBL',
]

SETTINGS_FILE   = Path("config/settings.py")
NEWS_FILE       = Path("news_watchlist.json")
WATCHLIST_MAX   = 40


def fetch_news_watchlist() -> list[str]:
    """Run the news fetcher and return symbols."""
    logger.info("📰 Fetching news watchlist from NSE...")
    try:
        result = subprocess.run(
            [sys.executable, "news_scanner/fetch_watchlist.py"],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0 and NEWS_FILE.exists():
            data    = json.loads(NEWS_FILE.read_text())
            symbols = data.get("top_symbols", [])
            banned  = [b["symbol"] for b in data.get("banned_stocks", [])]
            logger.info(f"  ✅ Got {len(symbols)} news stocks, {len(banned)} banned")
            return symbols, banned
        else:
            logger.warning(f"  ⚠ News fetch failed: {result.stderr[:200]}")
            return [], []
    except Exception as e:
        logger.warning(f"  ⚠ News fetch error: {e}")
        return [], []


def build_merged_watchlist(news_symbols: list[str], banned: list[str]) -> list[str]:
    """Merge news stocks with base watchlist, remove banned."""
    # News stocks first (highest priority), then base
    merged = []
    seen   = set()

    for sym in news_symbols + BASE_WATCHLIST:
        if sym not in seen and sym not in banned:
            merged.append(sym)
            seen.add(sym)

    # Cap at max
    merged = merged[:WATCHLIST_MAX]
    logger.info(f"  📋 Final watchlist: {len(merged)} stocks")
    return merged


def update_settings(watchlist: list[str]):
    """Update WATCHLIST in config/settings.py."""
    try:
        content = SETTINGS_FILE.read_text()
        # Find and replace WATCHLIST line
        lines   = content.split('\n')
        new_lines = []
        in_watchlist = False

        for line in lines:
            if line.strip().startswith('WATCHLIST') and '=' in line:
                # Replace entire WATCHLIST definition
                new_lines.append(f"WATCHLIST = {json.dumps(watchlist)}")
                in_watchlist = True
            elif in_watchlist and (line.strip().startswith(']') or line.strip().startswith("'")):
                # Skip old watchlist lines
                if line.strip() == ']':
                    in_watchlist = False
                continue
            else:
                if in_watchlist and not line.strip():
                    in_watchlist = False
                new_lines.append(line)

        SETTINGS_FILE.write_text('\n'.join(new_lines))
        logger.info(f"  ✅ Updated config/settings.py with {len(watchlist)} stocks")
    except Exception as e:
        logger.warning(f"  ⚠ Could not update settings.py: {e}")


def print_morning_brief(watchlist: list[str], news_stocks: list[str], banned: list[str]):
    """Print morning brief."""
    now = datetime.now()
    print("\n" + "="*55)
    print(f"  🌅 MORNING BRIEF — {now.strftime('%A %d %B %Y')}")
    print("="*55)

    if NEWS_FILE.exists():
        data = json.loads(NEWS_FILE.read_text())
        summary = data.get("summary", {})
        print(f"\n  📰 News stocks added:")
        print(f"     Bulk/Block deals: {summary.get('bulk_deals', 0)}")
        print(f"     Results/Announcements: {summary.get('results', 0)}")
        print(f"     Board meetings: {summary.get('board', 0)}")

        if data.get("all_stocks"):
            print(f"\n  🔥 Top news stocks today:")
            for item in data["all_stocks"][:5]:
                cats   = ", ".join(set(item["categories"]))
                detail = item["details"][0][:50] if item["details"] else ""
                print(f"     {item['symbol']:<15} [{cats}] {detail}")

    if banned:
        print(f"\n  ⛔ F&O ban (avoid): {', '.join(banned[:10])}")

    print(f"\n  📋 Scanner watchlist ({len(watchlist)} stocks):")
    # Show in rows of 5
    for i in range(0, len(watchlist), 5):
        row = watchlist[i:i+5]
        print(f"     {', '.join(f'{s:<12}' for s in row)}")

    print("\n  📌 Remember:")
    print("     • Set SL before entering any trade")
    print("     • Wait for 2:1+ book ratio before entering")
    print("     • Don't trade after 3 losses in a row")
    print("     • Scan at 9:20 AM after opening volatility settles")
    print("="*55 + "\n")


def start_agent(watchlist: list[str]):
    """Start the snapshot agent."""
    logger.info("🤖 Starting snapshot agent...")
    # Agent reads watchlist from settings.py — already updated above
    subprocess.Popen(
        [sys.executable, "run_agent.py"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    logger.info("  ✅ Agent started in background")
    logger.info("  📊 Open dashboard: http://localhost:3001")


def main():
    logger.info("🌅 Morning startup sequence beginning...")

    # Step 1: Fetch news watchlist
    news_symbols, banned = fetch_news_watchlist()
    time.sleep(1)

    # Step 2: Build merged watchlist
    watchlist = build_merged_watchlist(news_symbols, banned)

    # Step 3: Update settings.py
    update_settings(watchlist)

    # Step 4: Print morning brief
    print_morning_brief(watchlist, news_symbols, banned)

    # Step 5: Start agent
    start_agent(watchlist)

    logger.info("✅ Morning startup complete. Good trading!")


if __name__ == "__main__":
    main()
