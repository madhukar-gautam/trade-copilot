// dashboard/src/app/api/scanner/route.ts
// Scans a watchlist of stocks, ranks by signal strength
// Returns sorted list with BUY/SELL signals, book ratio, walls

import { NextRequest, NextResponse } from 'next/server';
import { join } from 'path';
import { existsSync, readFileSync } from 'fs';

const GROWW_BASE = 'https://api.groww.in/v1/live-data/quote';

// Volatile mid/small cap watchlist — high intraday movement
// Edit via dashboard UI or replace this array
const DEFAULT_WATCHLIST = [
  // Power & Energy — news driven, high volatility
  'TITAGARH', 'ADANIPOWER', 'TATAPOWER', 'SUZLON', 'NHPC',
  'SJVN', 'IREDA', 'RPOWER', 'CESC', 'TORNTPOWER',
  // PSU Defence & Rail — momentum movers
  'BEL', 'HAL', 'RAILTEL', 'RVNL', 'IRFC',
  'COCHINSHIP', 'GRSE', 'MAZAGON', 'BEML', 'MIDHANI',
  // Mid cap financials & metals
  'RECLTD', 'PFC', 'HUDCO', 'SAIL', 'NMDC',
  'NALCO', 'HINDALCO', 'VEDL', 'GMDC', 'GUJALKALI',
  // High beta small caps
  'EIHOTEL', 'ZEEL', 'YESBANK', 'JSWENERGY', 'INOXWIND',
  'KAYNES', 'PCBL', 'IFCI', 'IRCON', 'NBCC',
];

function getToken() {
  const t = process.env.GROWW_API_KEY || '';
  return t.toLowerCase().startsWith('bearer ') ? t : `Bearer ${t}`;
}

function getHeaders(): Record<string, string> {
  const h: Record<string, string> = {
    Authorization: getToken(),
    Accept: 'application/json',
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0',
  };
  const c = process.env.GROWW_COOKIE;
  if (c) h['Cookie'] = c;
  return h;
}

async function fetchQuote(symbol: string): Promise<any | null> {
  try {
    const url = `${GROWW_BASE}?exchange=NSE&segment=CASH&trading_symbol=${symbol}`;
    const res = await fetch(url, { headers: getHeaders(), cache: 'no-store' });
    if (!res.ok) return null;
    const data = await res.json();
    return data.status === 'SUCCESS' ? data.payload : null;
  } catch {
    return null;
  }
}

function noDataRow(symbol: string) {
  return {
    symbol,
    ltp: 0,
    chgPct: 0,
    volume: 0,
    volQuality: 'NO_DATA',
    bookRatio: 0,
    rangePct: 0,
    spread: 0,
    dayHigh: 0,
    dayLow: 0,
    prevClose: 0,
    buyWall: null,
    sellWall: null,
    longSL: 0,
    shortSL: 0,
    longT1: 0,
    shortT1: 0,
    longRR: 0,
    shortRR: 0,
    signal: 'NO_DATA',
    confidence: 0,
    score: 0,
    alerts: ['No quote data (Groww API failed / symbol not available)'],
    upperCircuit: 0,
    lowerCircuit: 0,
    week52High: 0,
    week52Low: 0,
    totalBuy: 0,
    totalSell: 0,
    scannedAt: new Date().toISOString(),
  };
}

function analyzeStock(symbol: string, p: any) {
  const ohlc     = p.ohlc || {};
  const depth    = p.depth || {};
  const buyLvls  = (depth.buy  || []).filter((b: any) => b.price > 0);
  const sellLvls = (depth.sell || []).filter((s: any) => s.price > 0);

  const ltp       = p.last_price      || 0;
  const dayHigh   = ohlc.high         || 0;
  const dayLow    = ohlc.low          || 0;
  const prevClose = ohlc.close        || 0;
  const volume    = p.volume          || 0;
  const chgPct    = p.day_change_perc || 0;
  const totalBuy  = p.total_buy_quantity  || 0;
  const totalSell = p.total_sell_quantity || 1;

  const bookRatio = parseFloat((totalBuy / Math.max(totalSell, 1)).toFixed(2));
  const dayRange  = dayHigh - dayLow;
  const rangePct  = dayRange > 0
    ? parseFloat(((ltp - dayLow) / dayRange * 100).toFixed(1))
    : 50;

  const volQuality = volume < 100000  ? 'DANGEROUS'
                   : volume < 500000  ? 'THIN'
                   : volume < 5000000 ? 'GOOD'
                   : 'EXCELLENT';

  const spread = (sellLvls[0]?.price && buyLvls[0]?.price)
    ? parseFloat((sellLvls[0].price - buyLvls[0].price).toFixed(2))
    : 0;

  // Wall detection
  const buyWall  = buyLvls.find( (b: any) => b.quantity >= 3000 && b.orderCount <= 3) || null;
  const sellWall = sellLvls.find((s: any) => s.quantity >= 3000 && s.orderCount <= 3) || null;

  // SL from order book
  const bigBuyBelow  = buyLvls.filter((l: any) => l.price < ltp && l.quantity >= 200)
                               .sort((a: any, b: any) => b.quantity - a.quantity)[0];
  const bigSellAbove = sellLvls.filter((l: any) => l.price > ltp && l.quantity >= 200)
                                .sort((a: any, b: any) => b.quantity - a.quantity)[0];

  const longSL  = bigBuyBelow  ? parseFloat((bigBuyBelow.price  - 0.05).toFixed(2)) : parseFloat((dayLow  - 0.5).toFixed(2));
  const shortSL = bigSellAbove ? parseFloat((bigSellAbove.price + 0.05).toFixed(2)) : parseFloat((dayHigh + 0.5).toFixed(2));

  const longT1  = bigSellAbove ? parseFloat((bigSellAbove.price - 0.05).toFixed(2)) : dayHigh;
  const shortT1 = bigBuyBelow  ? parseFloat((bigBuyBelow.price  + 0.05).toFixed(2)) : dayLow;

  const longRisk  = Math.max(ltp - longSL, 0.01);
  const shortRisk = Math.max(shortSL - ltp, 0.01);
  const longRR    = parseFloat(((longT1  - ltp)  / longRisk).toFixed(2));
  const shortRR   = parseFloat(((ltp - shortT1)  / shortRisk).toFixed(2));

  const volOk = volQuality === 'GOOD' || volQuality === 'EXCELLENT';

  // Signal scoring — gives a score so we can rank stocks
  let signal    = 'WAIT';
  let confidence= 0;
  let score     = 0; // for ranking: positive = bullish, negative = bearish
  const alerts: string[] = [];

  if (!volOk) {
    signal = 'AVOID';
    confidence = 90;
    score = 0;
  } else if (bookRatio >= 2.5 && rangePct < 85) {
    signal     = 'BUY';
    confidence = Math.min(92, Math.round(50 + bookRatio * 8 + (85 - rangePct) * 0.3));
    score      = bookRatio * 10 + (85 - rangePct) * 0.5;
    if (buyWall)  alerts.push(`Buy wall ₹${buyWall.price} (${buyWall.quantity.toLocaleString()})`);
    if (sellWall) alerts.push(`Sell wall ₹${sellWall.price} blocking`);
    if (chgPct > 8) alerts.push(`Extended +${chgPct.toFixed(1)}%`);
  } else if (bookRatio >= 1.5 && rangePct < 60) {
    signal     = 'BUY';
    confidence = Math.min(72, Math.round(40 + bookRatio * 6 + (60 - rangePct) * 0.3));
    score      = bookRatio * 7 + (60 - rangePct) * 0.3;
    if (sellWall) alerts.push(`Sell wall ₹${sellWall.price} ahead`);
  } else if (bookRatio >= 2.5 && rangePct >= 85) {
    signal     = 'BUY';
    confidence = Math.min(60, Math.round(35 + bookRatio * 5));
    score      = bookRatio * 5;
    alerts.push(`Extended ${rangePct}% — breakout only`);
  } else if (bookRatio <= 0.4 && rangePct > 20) {
    signal     = 'SELL';
    confidence = Math.min(92, Math.round(50 + (1/bookRatio) * 8 + (rangePct - 20) * 0.3));
    score      = -(1/bookRatio) * 10 - (rangePct - 20) * 0.5;
    if (sellWall) alerts.push(`Sell wall ₹${sellWall.price} (${sellWall.quantity.toLocaleString()})`);
    if (buyWall)  alerts.push(`Buy wall ₹${buyWall.price} — may bounce`);
  } else if (bookRatio <= 0.65 && rangePct > 40) {
    signal     = 'SELL';
    confidence = Math.min(72, Math.round(40 + (1/bookRatio) * 6));
    score      = -(1/bookRatio) * 7;
    if (buyWall) alerts.push(`Buy wall ₹${buyWall.price} may support`);
  } else {
    signal     = 'WAIT';
    confidence = 0;
    score      = 0;
    if (sellWall) alerts.push(`Sell wall ₹${sellWall.price}`);
    if (buyWall)  alerts.push(`Buy wall ₹${buyWall.price}`);
  }

  return {
    symbol, ltp, chgPct, volume, volQuality,
    bookRatio, rangePct, spread,
    dayHigh, dayLow, prevClose,
    buyWall, sellWall,
    longSL, shortSL, longT1, shortT1, longRR, shortRR,
    signal, confidence, score, alerts,
    upperCircuit: p.upper_circuit_limit || 0,
    lowerCircuit: p.lower_circuit_limit || 0,
    week52High: p.week_52_high || 0,
    week52Low:  p.week_52_low  || 0,
    totalBuy, totalSell,
    scannedAt: new Date().toISOString(),
  };
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json().catch(() => ({}));

    // Load master watchlist from watchlist.json, fallback to DEFAULT
    let masterList: string[] = DEFAULT_WATCHLIST;
    try {
      const { readFileSync, existsSync } = await import('fs');
      const { join } = await import('path');
      const wlFile = join(process.cwd(), 'watchlist.json');
      if (existsSync(wlFile)) masterList = JSON.parse(readFileSync(wlFile, 'utf-8'));
    } catch {}

    // Merge news watchlist if available
    try {
      const candidates = [
        join(process.cwd(), 'news_watchlist.json'),      // dashboard/
        join(process.cwd(), '..', 'news_watchlist.json') // repo root
      ];
      const newsPath = candidates.find(p => existsSync(p));
      if (newsPath) {
        const news   = JSON.parse(readFileSync(newsPath, 'utf-8'));
        const banned = (news.banned_stocks || []).map((b: any) => b.symbol);
        const newSym = (news.top_symbols   || []).filter((s: string) => !banned.includes(s));
        masterList   = [...new Set([...newSym, ...masterList])].filter((s: string) => !banned.includes(s));
      }
    } catch {}

    const watchlist: string[] = body.watchlist || masterList;

    // Fetch all stocks in parallel with concurrency limit
    const BATCH = 5; // 5 at a time to avoid rate limiting
    const results: any[] = [];

    for (let i = 0; i < watchlist.length; i += BATCH) {
      const batch   = watchlist.slice(i, i + BATCH);
      const fetched = await Promise.all(
        batch.map(async (symbol) => {
          const payload = await fetchQuote(symbol);
          if (!payload) return noDataRow(symbol);
          return analyzeStock(symbol, payload);
        })
      );
      results.push(...fetched);

      // Small delay between batches to be polite to Groww API
      if (i + BATCH < watchlist.length) {
        await new Promise(r => setTimeout(r, 200));
      }
    }

    // Sort by signal priority then score
    const signalPriority: Record<string, number> = {
      BUY: 3, SELL: 2, WAIT: 1, AVOID: 0, NO_DATA: -1,
    };

    results.sort((a, b) => {
      const pa = signalPriority[a.signal] || 0;
      const pb = signalPriority[b.signal] || 0;
      if (pa !== pb) return pb - pa;
      // Within same signal, sort by confidence then |score|
      if (a.confidence !== b.confidence) return b.confidence - a.confidence;
      return Math.abs(b.score) - Math.abs(a.score);
    });

    const summary = {
      total:   results.length,
      buy:     results.filter(r => r.signal === 'BUY').length,
      sell:    results.filter(r => r.signal === 'SELL').length,
      wait:    results.filter(r => r.signal === 'WAIT').length,
      avoid:   results.filter(r => r.signal === 'AVOID').length,
      noData:  results.filter(r => r.signal === 'NO_DATA').length,
      scannedAt: new Date().toISOString(),
    };

    return NextResponse.json({ results, summary, watchlist });
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}



export async function GET() {
  // Load persistent watchlist first, then merge with news watchlist if available
  try {
    const { readFileSync, existsSync } = await import('fs');
    const { join } = await import('path');

    // Load master watchlist
    const wlFile = join(process.cwd(), 'watchlist.json');
    let masterList = DEFAULT_WATCHLIST;
    if (existsSync(wlFile)) {
      try { masterList = JSON.parse(readFileSync(wlFile, 'utf-8')); } catch {}
    }

    // Merge with news watchlist if available (dashboard/ or repo root)
    const candidates = [
      join(process.cwd(), 'news_watchlist.json'),
      join(process.cwd(), '..', 'news_watchlist.json'),
    ];
    const newsPath = candidates.find(p => existsSync(p));
    if (newsPath) {
      const data = JSON.parse(readFileSync(newsPath, 'utf-8'));
      const newsSymbols = data.top_symbols || [];
      const banned = (data.banned_stocks || []).map((b: any) => b.symbol);
      // News stocks first, then master, remove banned
      const merged = [...new Set([...newsSymbols, ...masterList])].filter(s => !banned.includes(s));
      return NextResponse.json({
        watchlist:     merged,
        masterList,
        newsWatchlist: data,
        hasNews:       true,
      });
    }
    return NextResponse.json({ watchlist: masterList, masterList, hasNews: false });
  } catch {}
  return NextResponse.json({ watchlist: DEFAULT_WATCHLIST, masterList: DEFAULT_WATCHLIST, hasNews: false });
}