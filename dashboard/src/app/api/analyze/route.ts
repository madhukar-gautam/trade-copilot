// dashboard/src/app/api/analyze/route.ts

import { NextRequest, NextResponse } from 'next/server';

const GROWW_BASE = 'https://api.groww.in/v1/live-data/quote';

function getToken(): string {
  const t = process.env.GROWW_API_KEY || '';
  return t.toLowerCase().startsWith('bearer ') ? t : `Bearer ${t}`;
}

async function fetchQuote(symbol: string) {
  const headers: Record<string, string> = {
    Authorization: getToken(),
    Accept: 'application/json',
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0',
  };
  const cookie = process.env.GROWW_COOKIE;
  if (cookie) headers['Cookie'] = cookie;

  const url = `${GROWW_BASE}?exchange=NSE&segment=CASH&trading_symbol=${symbol.toUpperCase()}`;
  const res = await fetch(url, { headers, cache: 'no-store' });
  if (!res.ok) throw new Error(`Groww ${res.status}: ${res.statusText}`);
  const data = await res.json();
  if (data.status !== 'SUCCESS') throw new Error(data.error?.message || 'Groww error');
  return data.payload;
}

function analyze(symbol: string, p: any) {
  const ohlc    = p.ohlc || {};
  const depth   = p.depth || {};
  const buyLvls = (depth.buy  || []).filter((b: any) => b.price > 0);
  const sellLvls= (depth.sell || []).filter((s: any) => s.price > 0);

  const ltp       = p.last_price      || 0;
  const dayOpen   = ohlc.open         || 0;
  const dayHigh   = ohlc.high         || 0;
  const dayLow    = ohlc.low          || 0;
  const prevClose = ohlc.close        || 0;
  const volume    = p.volume          || 0;
  const chgPct    = p.day_change_perc || 0;
  const totalBuy  = p.total_buy_quantity  || 0;
  const totalSell = p.total_sell_quantity || 1;

  const bookRatio = parseFloat((totalBuy / Math.max(totalSell, 1)).toFixed(2));
  const bookBias  = bookRatio > 1.3 ? 'BUY' : bookRatio < 0.77 ? 'SELL' : 'NEUTRAL';

  const dayRange = dayHigh - dayLow;
  const rangePct = dayRange > 0
    ? parseFloat(((ltp - dayLow) / dayRange * 100).toFixed(1))
    : 50;

  const spread = (sellLvls[0]?.price && buyLvls[0]?.price)
    ? parseFloat((sellLvls[0].price - buyLvls[0].price).toFixed(2))
    : 0;

  // Wall detection — single order with large qty
  const buyWall  = buyLvls.find( (b: any) => b.quantity > 3000 && b.orderCount <= 3) || null;
  const sellWall = sellLvls.find((s: any) => s.quantity > 3000 && s.orderCount <= 3) || null;

  // Volume quality
  const volQuality = volume < 100000   ? 'DANGEROUS'
                   : volume < 500000   ? 'THIN'
                   : volume < 5000000  ? 'GOOD'
                   : 'EXCELLENT';

  // ATR: use day range as proxy (realistic for intraday)
  const atr = parseFloat((dayRange * 0.5).toFixed(2));

  // ── Order-book-aware SL — mirrors what I do manually ──────────────
  // For LONG: find the strongest buyer cluster below LTP → SL just below it
  // For SHORT: find the strongest seller cluster above LTP → SL just above it
  // Fall back to day low/high if no significant level found

  // Significant level = qty > 200 OR (qty > 100 AND only 1-2 orders = conviction)
  const isSignificantBuy  = (l: any) => l.quantity >= 200 || (l.quantity >= 100 && l.orderCount <= 2);
  const isSignificantSell = (l: any) => l.quantity >= 200 || (l.quantity >= 100 && l.orderCount <= 2);

  // Long SL: strongest buy support below LTP
  const buySupport = buyLvls
    .filter((l: any) => l.price < ltp && isSignificantBuy(l))
    .sort((a: any, b: any) => b.quantity - a.quantity); // biggest first

  let longSL: number;
  let longSLReason: string;

  if (buySupport.length > 0) {
    // SL just below the strongest buyer cluster
    longSL       = parseFloat((buySupport[0].price - 0.05).toFixed(2));
    longSLReason = `Below ${buySupport[0].quantity.toLocaleString()}-unit buyer at ₹${buySupport[0].price}`;
  } else {
    // No visible support — use day low
    longSL       = parseFloat((dayLow - 0.5).toFixed(2));
    longSLReason = 'Below day low (no order book support visible)';
  }

  // Short SL: strongest sell resistance above LTP
  const sellResistance = sellLvls
    .filter((l: any) => l.price > ltp && isSignificantSell(l))
    .sort((a: any, b: any) => b.quantity - a.quantity); // biggest first

  let shortSL: number;
  let shortSLReason: string;

  if (sellResistance.length > 0) {
    shortSL       = parseFloat((sellResistance[0].price + 0.05).toFixed(2));
    shortSLReason = `Above ${sellResistance[0].quantity.toLocaleString()}-unit seller at ₹${sellResistance[0].price}`;
  } else {
    shortSL       = parseFloat((dayHigh + 0.5).toFixed(2));
    shortSLReason = 'Above day high (no order book resistance visible)';
  }

  // Long target: strongest sell resistance above LTP = T1, next level = T2
  const sellAboveLTP = sellLvls
    .filter((l: any) => l.price > ltp)
    .sort((a: any, b: any) => b.quantity - a.quantity);

  const longT1 = sellAboveLTP[0]?.price
    ? parseFloat((sellAboveLTP[0].price - 0.05).toFixed(2))  // just below big seller
    : parseFloat((dayHigh).toFixed(2));
  const longRisk = parseFloat((ltp - longSL).toFixed(2));
  const longT2   = parseFloat((ltp + longRisk * 3.0).toFixed(2));
  const longRR   = longRisk > 0
    ? parseFloat(((longT1 - ltp) / longRisk).toFixed(2))
    : 0;

  // Short target: strongest buy support below LTP = T1
  const buyBelowLTP = buyLvls
    .filter((l: any) => l.price < ltp)
    .sort((a: any, b: any) => b.quantity - a.quantity);

  const shortT1  = buyBelowLTP[0]?.price
    ? parseFloat((buyBelowLTP[0].price + 0.05).toFixed(2))   // just above big buyer
    : parseFloat((dayLow).toFixed(2));
  const shortRisk= parseFloat((shortSL - ltp).toFixed(2));
  const shortT2  = parseFloat((ltp - shortRisk * 3.0).toFixed(2));
  const shortRR  = shortRisk > 0
    ? parseFloat(((ltp - shortT1) / shortRisk).toFixed(2))
    : 0;

  // ── Signal logic — mirrors what I do manually ──────────────────────
  let signal     = 'WAIT';
  let confidence = 0;
  const reasons:  string[] = [];
  const warnings: string[] = [];

  const volOk = volQuality === 'GOOD' || volQuality === 'EXCELLENT';

  if (!volOk) {
    // ── Volume too thin ───────────────────────────────────────────────
    signal     = 'AVOID';
    confidence = 95;
    warnings.push(`Volume ${volume.toLocaleString()} is too thin — slippage risk`);

  } else if (bookRatio >= 2.5 && rangePct < 85) {
    // ── Strong BUY signal ─────────────────────────────────────────────
    signal     = 'BUY';
    confidence = Math.min(92, Math.round(50 + bookRatio * 8 + (85 - rangePct) * 0.3));
    reasons.push(`Buy queue ${bookRatio}:1 — strong institutional buying`);
    reasons.push(`Price at ${rangePct}% of day range — room to move`);
    if (buyWall)  reasons.push(`Buy wall ₹${buyWall.price} (${buyWall.quantity.toLocaleString()} units) supporting`);
    if (sellWall) warnings.push(`Sell wall ₹${sellWall.price} (${sellWall.quantity.toLocaleString()} units) — resistance ahead`);
    if (chgPct > 8) warnings.push(`Already up ${chgPct.toFixed(1)}% — extended move, size down`);

  } else if (bookRatio >= 1.5 && rangePct < 60) {
    // ── Moderate BUY ─────────────────────────────────────────────────
    signal     = 'BUY';
    confidence = Math.min(75, Math.round(40 + bookRatio * 6 + (60 - rangePct) * 0.3));
    reasons.push(`Buy queue ${bookRatio}:1 — buyers in control`);
    reasons.push(`Price at ${rangePct}% of range — decent entry zone`);
    if (sellWall) warnings.push(`Sell wall ₹${sellWall.price} ahead — watch for rejection`);

  } else if (bookRatio >= 2.5 && rangePct >= 85) {
    // ── Extended BUY — good ratio but near top ────────────────────────
    signal     = 'BUY';
    confidence = Math.min(65, Math.round(40 + bookRatio * 5));
    reasons.push(`Buy queue ${bookRatio}:1 — strong buyers`);
    warnings.push(`At ${rangePct}% of day range — extended, use tight SL`);
    warnings.push(`Only enter on breakout above ₹${dayHigh.toFixed(2)} (day high)`);

  } else if (bookRatio <= 0.4 && rangePct > 20) {
    // ── Strong SELL signal ────────────────────────────────────────────
    signal     = 'SELL';
    confidence = Math.min(92, Math.round(50 + (1/bookRatio) * 8 + (rangePct - 20) * 0.3));
    reasons.push(`Sell queue ${(1/bookRatio).toFixed(1)}:1 — sellers dominant`);
    reasons.push(`Price at ${rangePct}% of range — room to fall`);
    if (sellWall) reasons.push(`Sell wall ₹${sellWall.price} (${sellWall.quantity.toLocaleString()} units) pushing down`);
    if (chgPct < -8) warnings.push(`Already down ${Math.abs(chgPct).toFixed(1)}% — may be exhausted`);

  } else if (bookRatio <= 0.65 && rangePct > 40) {
    // ── Moderate SELL ─────────────────────────────────────────────────
    signal     = 'SELL';
    confidence = Math.min(75, Math.round(40 + (1/bookRatio) * 6));
    reasons.push(`Sell queue ${(1/bookRatio).toFixed(1)}:1 — sellers in control`);
    if (buyWall) warnings.push(`Buy wall ₹${buyWall.price} ahead — may bounce`);

  } else {
    // ── WAIT — no clear signal ────────────────────────────────────────
    signal     = 'WAIT';
    confidence = 0;
    reasons.push(`Book ratio ${bookRatio}:1 — no strong directional bias`);
    if (rangePct > 80) warnings.push(`At ${rangePct}% of day range — poor R:R for long`);
    if (rangePct < 20) warnings.push(`At ${rangePct}% of day range — poor R:R for short`);
    if (sellWall) warnings.push(`Sell wall ₹${sellWall.price} (${sellWall.quantity.toLocaleString()} qty) blocking upside`);
    if (buyWall)  warnings.push(`Buy wall ₹${buyWall.price} (${buyWall.quantity.toLocaleString()} qty) — support`);
  }

  // Extra emotional checks regardless of signal
  if (signal === 'BUY' && chgPct > 10) {
    warnings.push(`Stock up ${chgPct.toFixed(1)}% today — are you chasing? Size down.`);
  }
  if (signal === 'SELL' && chgPct < -10) {
    warnings.push(`Stock down ${Math.abs(chgPct).toFixed(1)}% — shorting into exhaustion. Be careful.`);
  }

  return {
    symbol, ltp, dayOpen, dayHigh, dayLow, prevClose,
    chgPct, volume, volQuality,
    bookRatio, bookBias, rangePct, spread, atr,
    totalBuy, totalSell,
    buyWall, sellWall,
    longSL, longT1, longT2, longRR, longRisk, longSLReason,
    shortSL, shortT1, shortT2, shortRR, shortRisk, shortSLReason,
    signal, confidence, reasons, warnings,
    upperCircuit: p.upper_circuit_limit || 0,
    lowerCircuit: p.lower_circuit_limit || 0,
    week52High:   p.week_52_high || 0,
    week52Low:    p.week_52_low  || 0,
    buyLevels:    buyLvls,
    sellLevels:   sellLvls,
    lastTradeQty: p.last_trade_quantity || 0,
    timestamp:    new Date().toISOString(),
  };
}

export async function POST(req: NextRequest) {
  try {
    const { symbol } = await req.json();
    if (!symbol) return NextResponse.json({ error: 'Symbol required' }, { status: 400 });
    const payload  = await fetchQuote(symbol.trim().toUpperCase());
    const analysis = analyze(symbol.trim().toUpperCase(), payload);
    return NextResponse.json(analysis);
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
