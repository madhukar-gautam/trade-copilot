#!/usr/bin/env python3
"""
news_scanner/fetch_watchlist.py

Runs every morning at 8:30 AM before market open.
Fetches from NSE India public APIs (no auth needed):
  1. Bulk deals from previous trading day
  2. Corporate announcements (results, dividends, board meetings)
  3. Securities in F&O ban (avoid these)
  4. Stocks with unusually high delivery % (smart money signals)

Outputs: news_watchlist.json — auto-loaded by scanner on next scan.

Usage:
  python news_scanner/fetch_watchlist.py
  python news_scanner/fetch_watchlist.py --date 2025-04-07
  python news_scanner/fetch_watchlist.py --dry-run  (print only, don't save)
"""

import json
import time
import argparse
import requests
from datetime import datetime, timedelta
from pathlib import Path
from logzero import logger

OUTPUT_FILE = Path("news_watchlist.json")

# NSE headers — required to avoid 401
NSE_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.nseindia.com/",
    "Connection":      "keep-alive",
}

# Category → reason shown in dashboard
CATEGORY_LABELS = {
    "bulk_deal":      "Bulk deal yesterday",
    "block_deal":     "Block deal yesterday",
    "result":         "Results announced",
    "dividend":       "Dividend declared",
    "board_meeting":  "Board meeting today",
    "split":          "Stock split",
    "buyback":        "Buyback announced",
    "high_delivery":  "High delivery % (smart money)",
    "fno_ban":        "F&O ban — avoid",
}


class NSEFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(NSE_HEADERS)
        self._init_session()

    def _init_session(self):
        """NSE requires a cookie from homepage first."""
        try:
            self.session.get("https://www.nseindia.com", timeout=10)
            time.sleep(1)
        except Exception as e:
            logger.warning(f"NSE session init failed: {e}")

    def _get(self, url: str, params: dict = None) -> dict | None:
        try:
            r = self.session.get(url, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"NSE fetch failed {url}: {e}")
            return None

    def get_bulk_deals(self, date_str: str) -> list[dict]:
        """Fetch bulk deals for a given date (DD-MM-YYYY format for NSE)."""
        logger.info(f"Fetching bulk deals for {date_str}...")
        data = self._get(
            "https://www.nseindia.com/api/bulk-deal-archives",
            params={"from": date_str, "to": date_str}
        )
        if not data or "data" not in data:
            return []

        results = []
        for deal in data["data"]:
            symbol = deal.get("symbol", "").strip().upper()
            qty    = deal.get("quantity_traded_lakh", 0)
            price  = deal.get("trade_price", 0)
            client = deal.get("client_name", "")
            buysell= deal.get("buy_sell", "")
            if symbol:
                results.append({
                    "symbol":   symbol,
                    "category": "bulk_deal",
                    "detail":   f"{buysell} {qty}L shares @ ₹{price} by {client}",
                    "priority": 3,  # high priority
                })
        logger.info(f"  Found {len(results)} bulk deals")
        return results

    def get_block_deals(self, date_str: str) -> list[dict]:
        """Fetch block deals."""
        logger.info(f"Fetching block deals for {date_str}...")
        data = self._get(
            "https://www.nseindia.com/api/block-deal-archives",
            params={"from": date_str, "to": date_str}
        )
        if not data or "data" not in data:
            return []

        results = []
        for deal in data["data"]:
            symbol = deal.get("symbol", "").strip().upper()
            qty    = deal.get("quantity_traded_lakh", 0)
            price  = deal.get("trade_price", 0)
            if symbol:
                results.append({
                    "symbol":   symbol,
                    "category": "block_deal",
                    "detail":   f"Block: {qty}L shares @ ₹{price}",
                    "priority": 3,
                })
        logger.info(f"  Found {len(results)} block deals")
        return results

    def get_corporate_announcements(self) -> list[dict]:
        """Fetch today's corporate announcements — results, dividends, board meetings."""
        logger.info("Fetching corporate announcements...")
        data = self._get("https://www.nseindia.com/api/corporate-announcements?index=equities")
        if not data:
            return []

        # NSE returns a list directly sometimes
        items = data if isinstance(data, list) else data.get("data", [])

        KEYWORDS = {
            "financial result":  ("result",       2),
            "quarterly result":  ("result",       2),
            "annual result":     ("result",       2),
            "dividend":          ("dividend",     2),
            "board meeting":     ("board_meeting",2),
            "stock split":       ("split",        3),
            "buyback":           ("buyback",      3),
            "bonus":             ("dividend",     2),
            "merger":            ("result",       3),
            "acquisition":       ("result",       3),
        }

        results = []
        seen = set()
        for item in items:
            symbol  = item.get("symbol", "").strip().upper()
            subject = item.get("subject", "").lower()
            desc    = item.get("desc", "").lower()
            text    = subject + " " + desc

            if not symbol or symbol in seen:
                continue

            for keyword, (category, priority) in KEYWORDS.items():
                if keyword in text:
                    results.append({
                        "symbol":   symbol,
                        "category": category,
                        "detail":   item.get("subject", "")[:80],
                        "priority": priority,
                    })
                    seen.add(symbol)
                    break

        logger.info(f"  Found {len(results)} corporate announcements")
        return results

    def get_fno_ban(self) -> list[dict]:
        """Fetch F&O ban list — avoid trading these."""
        logger.info("Fetching F&O ban list...")
        data = self._get("https://www.nseindia.com/api/fo-ban-underlyings")
        if not data:
            return []

        symbols = data if isinstance(data, list) else data.get("data", [])
        results = []
        for s in symbols:
            symbol = (s if isinstance(s, str) else s.get("symbol", "")).strip().upper()
            if symbol:
                results.append({
                    "symbol":   symbol,
                    "category": "fno_ban",
                    "detail":   "In F&O ban period — avoid",
                    "priority": -1,  # negative = flag as dangerous
                })
        logger.info(f"  Found {len(results)} F&O ban stocks")
        return results

    def get_high_delivery(self) -> list[dict]:
        """
        Fetch stocks with high delivery percentage — indicates smart money.
        Uses NSE's most active securities by delivery.
        """
        logger.info("Fetching high delivery stocks...")
        data = self._get("https://www.nseindia.com/api/snapshot-securities-traded-value?index=equities")
        if not data or "data" not in data:
            return []

        results = []
        for item in data["data"][:20]:  # top 20 by value
            symbol   = item.get("symbol", "").strip().upper()
            delivery = float(item.get("deliveryToTradedQty", 0) or 0)
            if symbol and delivery > 60:  # >60% delivery = strong conviction
                results.append({
                    "symbol":   symbol,
                    "category": "high_delivery",
                    "detail":   f"{delivery:.1f}% delivery ratio",
                    "priority": 1,
                })
        logger.info(f"  Found {len(results)} high delivery stocks")
        return results


def get_previous_trading_day(date: datetime = None) -> tuple[str, str]:
    """Returns (DD-MM-YYYY, YYYY-MM-DD) for previous trading day."""
    d = date or datetime.now()
    d -= timedelta(days=1)
    # Skip weekends
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d -= timedelta(days=1)
    return d.strftime("%d-%m-%Y"), d.strftime("%Y-%m-%d")


def merge_and_rank(all_items: list[dict]) -> list[dict]:
    """Merge duplicate symbols, combine reasons, rank by priority."""
    merged: dict[str, dict] = {}

    for item in all_items:
        symbol = item["symbol"]
        if symbol not in merged:
            merged[symbol] = {
                "symbol":     symbol,
                "categories": [],
                "details":    [],
                "priority":   item["priority"],
                "flagged":    item["priority"] < 0,
            }
        merged[symbol]["categories"].append(item["category"])
        merged[symbol]["details"].append(item["detail"])
        merged[symbol]["priority"] = max(merged[symbol]["priority"], item["priority"])

    # Sort: flagged (avoid) last, then by priority desc
    ranked = sorted(merged.values(), key=lambda x: (x["flagged"], -x["priority"]))
    return ranked


def build_watchlist(items: list[dict]) -> dict:
    """Build final watchlist output."""
    # Actionable stocks (not banned)
    actionable = [i for i in items if not i["flagged"]]
    banned     = [i for i in items if i["flagged"]]

    # Top 20 by priority for scanner
    top_symbols = [i["symbol"] for i in actionable[:20]]

    return {
        "generated_at":  datetime.now().isoformat(),
        "trading_date":  datetime.now().strftime("%Y-%m-%d"),
        "top_symbols":   top_symbols,
        "all_stocks":    actionable,
        "banned_stocks": banned,
        "summary": {
            "total":      len(actionable),
            "bulk_deals": sum(1 for i in actionable if "bulk_deal" in i["categories"]),
            "results":    sum(1 for i in actionable if "result" in i["categories"]),
            "board":      sum(1 for i in actionable if "board_meeting" in i["categories"]),
            "banned":     len(banned),
        }
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch news-based watchlist from NSE")
    parser.add_argument("--date",    help="Date YYYY-MM-DD (default: yesterday)", default=None)
    parser.add_argument("--dry-run", help="Print only, don't save",               action="store_true")
    parser.add_argument("--output",  help="Output file path",                      default=str(OUTPUT_FILE))
    args = parser.parse_args()

    logger.info("=" * 55)
    logger.info("  📰 NSE News Watchlist Builder")
    logger.info("=" * 55)

    # Get dates
    if args.date:
        d = datetime.strptime(args.date, "%Y-%m-%d")
        nse_date, _ = d.strftime("%d-%m-%Y"), d.strftime("%Y-%m-%d")
    else:
        nse_date, _ = get_previous_trading_day()

    logger.info(f"  Fetching data for: {nse_date}")

    fetcher  = NSEFetcher()
    all_items = []

    # Fetch all data sources
    all_items += fetcher.get_bulk_deals(nse_date)
    time.sleep(0.5)
    all_items += fetcher.get_block_deals(nse_date)
    time.sleep(0.5)
    all_items += fetcher.get_corporate_announcements()
    time.sleep(0.5)
    all_items += fetcher.get_high_delivery()
    time.sleep(0.5)
    fno_ban   = fetcher.get_fno_ban()
    all_items += fno_ban

    # Merge and rank
    ranked    = merge_and_rank(all_items)
    watchlist = build_watchlist(ranked)

    # Print summary
    logger.info("=" * 55)
    logger.info(f"  ✅ Total actionable stocks: {watchlist['summary']['total']}")
    logger.info(f"  📊 Bulk/Block deals: {watchlist['summary']['bulk_deals']}")
    logger.info(f"  📋 Results/Announcements: {watchlist['summary']['results']}")
    logger.info(f"  🏛  Board meetings: {watchlist['summary']['board']}")
    logger.info(f"  ⛔ F&O banned: {watchlist['summary']['banned']}")
    logger.info("=" * 55)

    if watchlist["top_symbols"]:
        logger.info("  Top stocks for tomorrow:")
        for i, item in enumerate(watchlist["all_stocks"][:10], 1):
            cats = ", ".join(set(item["categories"]))
            logger.info(f"  {i:2}. {item['symbol']:<15} [{cats}]")
            if item["details"]:
                logger.info(f"      → {item['details'][0][:60]}")

    if watchlist["banned_stocks"]:
        banned_syms = [b["symbol"] for b in watchlist["banned_stocks"]]
        logger.info(f"\n  ⛔ AVOID (F&O ban): {', '.join(banned_syms)}")

    if args.dry_run:
        logger.info("\n  DRY RUN — not saving file")
        print(json.dumps(watchlist, indent=2))
        return

    # Save output
    out_path = Path(args.output)
    out_path.write_text(json.dumps(watchlist, indent=2))
    logger.info(f"\n  💾 Saved to {out_path.absolute()}")
    logger.info("  Run scanner in dashboard to load these stocks")


if __name__ == "__main__":
    main()
