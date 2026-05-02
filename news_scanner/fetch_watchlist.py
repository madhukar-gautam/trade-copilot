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
import csv
import io
import re
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
    def __init__(self, debug: bool = False):
        self.session = requests.Session()
        self.session.headers.update(NSE_HEADERS)
        self.debug = debug
        self._init_session()

    def _init_session(self):
        """NSE requires a cookie from homepage first."""
        try:
            if self.debug:
                logger.info("NSE init → GET https://www.nseindia.com")
            r = self.session.get("https://www.nseindia.com", timeout=10)
            if self.debug:
                logger.info(
                    f"NSE init ← {r.status_code} content-type={r.headers.get('content-type','')}"
                )
            time.sleep(1)
        except Exception as e:
            logger.warning(f"NSE session init failed: {e}")

    def _get(self, url: str, params: dict = None) -> dict | None:
        try:
            t0 = time.time()
            if self.debug:
                qp = f" params={params}" if params else ""
                logger.info(f"NSE → GET {url}{qp}")

            r = self.session.get(url, params=params, timeout=10)
            dt_ms = int((time.time() - t0) * 1000)

            if self.debug:
                ct = r.headers.get("content-type", "")
                logger.info(f"NSE ← {r.status_code} {dt_ms}ms content-type={ct}")

            r.raise_for_status()

            # If NSE returns HTML/WAF page, log a small preview to help debugging.
            ct = (r.headers.get("content-type") or "").lower()
            if self.debug and ("text/html" in ct or "text/plain" in ct):
                preview = (r.text or "").replace("\n", " ").strip()[:300]
                if preview:
                    logger.info(f"NSE body preview: {preview}")

            return r.json()
        except Exception as e:
            if self.debug:
                try:
                    ct = r.headers.get("content-type", "")  # type: ignore[name-defined]
                    preview = (getattr(r, "text", "") or "").replace("\n", " ").strip()[:300]
                    logger.warning(
                        f"NSE fetch failed {url} status={getattr(r,'status_code','?')} content-type={ct} body={preview}"
                    )
                except Exception:
                    # fall back to original error message
                    pass
            logger.warning(f"NSE fetch failed {url}: {e}")
            return None

    def get_bulk_deals(self, date_str: str) -> list[dict]:
        """Fetch bulk deals for a given date (DD-MM-YYYY format for NSE)."""
        logger.info(f"Fetching bulk deals for {date_str}...")

        # JSON endpoints started returning 404 in 2026. Use the published CSV.
        # Note: bulk.csv is an end-of-day report and typically reflects the latest trading day.
        url = "https://archives.nseindia.com/content/equities/bulk.csv"
        try:
            if self.debug:
                logger.info(f"NSE → GET {url}")
            r = self.session.get(url, timeout=20)
            if self.debug:
                logger.info(f"NSE ← {r.status_code} content-type={r.headers.get('content-type','')}")
            r.raise_for_status()
        except Exception as e:
            logger.warning(f"Bulk deals CSV fetch failed: {e}")
            return []

        text = (r.text or "").strip()
        if not text:
            return []

        results: list[dict] = []
        try:
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                symbol = (row.get("Symbol") or row.get("SYMBOL") or "").strip().upper()
                if not symbol:
                    continue
                client = (row.get("Client Name") or row.get("CLIENT NAME") or "").strip()
                buysell = (row.get("Buy/Sell") or row.get("BUY/SELL") or "").strip()
                qty = (row.get("Quantity Traded") or row.get("QUANTITY TRADED") or "").strip()
                price = (row.get("Trade Price / WAP") or row.get("TRADE PRICE / WAP") or "").strip()
                detail = " ".join(p for p in [buysell, qty, f"@ ₹{price}" if price else "", f"by {client}" if client else ""] if p).strip()
                results.append({
                    "symbol": symbol,
                    "category": "bulk_deal",
                    "detail": detail,
                    "priority": 3,
                })
        except Exception as e:
            logger.warning(f"Bulk deals parse failed: {e}")
            return []

        logger.info(f"  Found {len(results)} bulk deals")
        return results

    def get_block_deals(self, date_str: str) -> list[dict]:
        """Fetch block deals."""
        logger.info(f"Fetching block deals for {date_str}...")
        url = "https://archives.nseindia.com/content/equities/block.csv"
        try:
            if self.debug:
                logger.info(f"NSE → GET {url}")
            r = self.session.get(url, timeout=20)
            if self.debug:
                logger.info(f"NSE ← {r.status_code} content-type={r.headers.get('content-type','')}")
            r.raise_for_status()
        except Exception as e:
            logger.warning(f"Block deals CSV fetch failed: {e}")
            return []

        text = (r.text or "").strip()
        if not text:
            return []

        results: list[dict] = []
        try:
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                symbol = (row.get("Symbol") or row.get("SYMBOL") or "").strip().upper()
                if not symbol:
                    continue
                qty = (row.get("Quantity Traded") or row.get("QUANTITY TRADED") or "").strip()
                price = (row.get("Trade Price / WAP") or row.get("TRADE PRICE / WAP") or "").strip()
                detail = " ".join(p for p in [f"Block:", qty, f"@ ₹{price}" if price else ""] if p).strip()
                results.append({
                    "symbol": symbol,
                    "category": "block_deal",
                    "detail": detail,
                    "priority": 3,
                })
        except Exception as e:
            logger.warning(f"Block deals parse failed: {e}")
            return []

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
        # NSE's old JSON endpoint started returning 404 in 2026.
        # Fallback to NSE Clearing's published CSV link (updated periodically).
        position_limits_url = "https://www.nseclearing.in/risk-management/equity-derivatives/position-limits"
        csv_url = None
        try:
            if self.debug:
                logger.info(f"NSE → GET {position_limits_url}")
            r = self.session.get(position_limits_url, timeout=15)
            if self.debug:
                logger.info(f"NSE ← {r.status_code} content-type={r.headers.get('content-type','')}")
            r.raise_for_status()
            m = re.search(r'href="([^"]*fo_secban\\.csv[^"]*)"', r.text, flags=re.IGNORECASE)
            if m:
                csv_url = m.group(1)
                if csv_url.startswith("/"):
                    csv_url = "https://www.nseclearing.in" + csv_url
        except Exception as e:
            logger.warning(f"F&O ban source page fetch failed: {e}")

        if not csv_url:
            return []

        try:
            if self.debug:
                logger.info(f"NSE → GET {csv_url}")
            r = self.session.get(csv_url, timeout=15)
            if self.debug:
                logger.info(f"NSE ← {r.status_code} content-type={r.headers.get('content-type','')}")
            r.raise_for_status()
            raw = (r.text or "").strip()
        except Exception as e:
            logger.warning(f"F&O ban CSV fetch failed: {e}")
            return []

        # CSV is tiny; may contain only header when nothing is banned.
        symbols: list[str] = []
        try:
            reader = csv.DictReader(io.StringIO(raw))
            for row in reader:
                sym = (row.get("Symbol") or row.get("SYMBOL") or "").strip().upper()
                if sym:
                    symbols.append(sym)
        except Exception:
            # Fallback: try first column split (in case headers change)
            for line in raw.splitlines()[1:]:
                parts = [p.strip() for p in line.split(",")]
                if parts and parts[0]:
                    symbols.append(parts[0].upper())

        results = []
        for s in symbols:
            results.append({
                "symbol":   s,
                "category": "fno_ban",
                "detail":   "In F&O ban period — avoid",
                "priority": -1,  # negative = flag as dangerous
            })
        logger.info(f"  Found {len(results)} F&O ban stocks")
        return results

    def get_high_delivery(self, trade_date_yyyymmdd: str | None = None) -> list[dict]:
        """
        Fetch stocks with high delivery percentage — indicates smart money.
        Uses NSE archives delivery bhavcopy CSV (no NSE JSON endpoint dependency).
        """
        logger.info("Fetching high delivery stocks...")

        # Use previous trading day by default (same date we use for bulk/block deals)
        if trade_date_yyyymmdd:
            d = datetime.strptime(trade_date_yyyymmdd, "%Y-%m-%d")
        else:
            _, trade_date_yyyymmdd = get_previous_trading_day()
            d = datetime.strptime(trade_date_yyyymmdd, "%Y-%m-%d")

        ddmmyyyy = d.strftime("%d%m%Y")
        url = f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"

        try:
            if self.debug:
                logger.info(f"NSE → GET {url}")
            r = self.session.get(url, timeout=20)
            if self.debug:
                logger.info(f"NSE ← {r.status_code} content-type={r.headers.get('content-type','')}")
            r.raise_for_status()
        except Exception as e:
            logger.warning(f"High delivery CSV fetch failed: {e}")
            return []

        text = (r.text or "").strip()
        if not text:
            return []

        # Columns usually include: SYMBOL, SERIES, TOTTRDQTY, DELIV_QTY, DELIV_PER
        results = []
        try:
            reader = csv.DictReader(io.StringIO(text))
            rows = []
            for row in reader:
                if (row.get("SERIES") or "").strip().upper() != "EQ":
                    continue
                symbol = (row.get("SYMBOL") or "").strip().upper()
                if not symbol:
                    continue
                try:
                    deliv_per = float((row.get("DELIV_PER") or "0").strip() or 0)
                except Exception:
                    deliv_per = 0.0
                try:
                    tot_qty = float((row.get("TOTTRDQTY") or "0").strip() or 0)
                except Exception:
                    tot_qty = 0.0
                rows.append((symbol, deliv_per, tot_qty))

            # Prefer meaningful liquidity, then high delivery %
            rows.sort(key=lambda x: (x[1], x[2]), reverse=True)
            for symbol, deliv_per, _tot_qty in rows[:50]:
                if deliv_per > 60:
                    results.append({
                        "symbol":   symbol,
                        "category": "high_delivery",
                        "detail":   f"{deliv_per:.1f}% delivery ratio",
                        "priority": 1,
                    })
                if len(results) >= 20:
                    break
        except Exception as e:
            logger.warning(f"High delivery parse failed: {e}")
            return []

        logger.info(f"  Found {len(results)} high delivery stocks")
        return results

    def get_high_delivery_legacy(self) -> list[dict]:
        """Legacy (now 404): kept for reference only."""
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
    parser.add_argument("--debug",   help="Verbose request/response logging",      action="store_true")
    args = parser.parse_args()

    logger.info("=" * 55)
    logger.info("  📰 NSE News Watchlist Builder")
    logger.info("=" * 55)

    # Get dates
    trade_date_iso = None
    if args.date:
        d = datetime.strptime(args.date, "%Y-%m-%d")
        nse_date, _ = d.strftime("%d-%m-%Y"), d.strftime("%Y-%m-%d")
        trade_date_iso = args.date
    else:
        nse_date, trade_date_iso = get_previous_trading_day()

    logger.info(f"  Fetching data for: {nse_date}")

    fetcher  = NSEFetcher(debug=args.debug)
    all_items = []

    # Fetch all data sources
    all_items += fetcher.get_bulk_deals(nse_date)
    time.sleep(0.5)
    all_items += fetcher.get_block_deals(nse_date)
    time.sleep(0.5)
    all_items += fetcher.get_corporate_announcements()
    time.sleep(0.5)
    all_items += fetcher.get_high_delivery(trade_date_iso)
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
