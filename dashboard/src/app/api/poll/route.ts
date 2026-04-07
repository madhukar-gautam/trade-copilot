// dashboard/src/app/api/poll/route.ts
// Polls live price for an open trade and returns updated P&L + signal

import { NextRequest, NextResponse } from 'next/server';

const GROWW_BASE = 'https://api.groww.in/v1/live-data/quote';

function getToken() {
  const t = process.env.GROWW_API_KEY || '';
  return t.toLowerCase().startsWith('bearer ') ? t : `Bearer ${t}`;
}

async function fetchLTP(symbol: string): Promise<number> {
  const headers: Record<string, string> = {
    Authorization: getToken(),
    Accept: 'application/json',
    'User-Agent': 'Mozilla/5.0',
  };
  const cookie = process.env.GROWW_COOKIE;
  if (cookie) headers['Cookie'] = cookie;

  const res  = await fetch(`${GROWW_BASE}?exchange=NSE&segment=CASH&trading_symbol=${symbol}`, { headers, cache: 'no-store' });
  const data = await res.json();
  if (data.status !== 'SUCCESS') throw new Error(data.error?.message || 'API error');

  const p         = data.payload;
  const ohlc      = p.ohlc || {};
  const buyLvls   = (p.depth?.buy || []).filter((b: any) => b.price > 0);
  const sellLvls  = (p.depth?.sell || []).filter((s: any) => s.price > 0);
  const totalBuy  = p.total_buy_quantity || 0;
  const totalSell = p.total_sell_quantity || 1;
  const bookRatio = parseFloat((totalBuy / totalSell).toFixed(2));
  const dayHigh   = ohlc.high || 0;
  const dayLow    = ohlc.low || 0;
  const dayRange  = dayHigh - dayLow;
  const ltp       = p.last_price || 0;
  const rangePct  = dayRange > 0 ? parseFloat(((ltp - dayLow) / dayRange * 100).toFixed(1)) : 50;
  const buyWall   = buyLvls.find((b: any) => b.quantity > 5000 && b.orderCount <= 3) || null;
  const sellWall  = sellLvls.find((s: any) => s.quantity > 5000 && s.orderCount <= 3) || null;
  const volume    = p.volume || 0;
  const chgPct    = p.day_change_perc || 0;

  return { ltp, bookRatio, rangePct, dayHigh, dayLow, buyWall, sellWall, volume, chgPct, totalBuy, totalSell } as any;
}

function getAdvice(trade: any, market: any): { action: string; reason: string; urgent: boolean } {
  const { side, entry, sl, t1 } = trade;
  const { ltp, bookRatio, rangePct, buyWall, sellWall } = market;
  const pnlPs = side === 'LONG' ? ltp - entry : entry - ltp;

  // Stop loss hit
  if (side === 'LONG' && ltp <= sl)
    return { action: 'EXIT', reason: `Stop loss ₹${sl} hit — exit immediately`, urgent: true };
  if (side === 'SHORT' && ltp >= sl)
    return { action: 'EXIT', reason: `Stop loss ₹${sl} hit — exit immediately`, urgent: true };

  // Target hit
  if (side === 'LONG' && ltp >= t1)
    return { action: 'BOOK_PROFIT', reason: `Target 1 ₹${t1} reached — consider booking profit`, urgent: false };
  if (side === 'SHORT' && ltp <= t1)
    return { action: 'BOOK_PROFIT', reason: `Target 1 ₹${t1} reached — consider booking profit`, urgent: false };

  // Book flipped against position
  if (side === 'LONG' && bookRatio < 0.6)
    return { action: 'EXIT', reason: `Book flipped bearish (${bookRatio}:1) — sellers taking over`, urgent: true };
  if (side === 'SHORT' && bookRatio > 2.5)
    return { action: 'EXIT', reason: `Book ${bookRatio}:1 buy dominant — cover now`, urgent: true };

  // Wall blocking target
  if (side === 'LONG' && sellWall && sellWall.price < t1)
    return { action: 'WATCH', reason: `Sell wall ₹${sellWall.price} (${sellWall.quantity.toLocaleString()} qty) blocking target`, urgent: false };
  if (side === 'SHORT' && buyWall && buyWall.price > t1)
    return { action: 'WATCH', reason: `Buy wall ₹${buyWall.price} (${buyWall.quantity.toLocaleString()} qty) blocking target`, urgent: false };

  // Emotional — holding loss
  if (pnlPs < -5)
    return { action: 'REVIEW', reason: `Down ₹${Math.abs(pnlPs).toFixed(2)}/share — check if SL should trigger`, urgent: false };

  return { action: 'HOLD', reason: `Trade on track — ${side === 'LONG' ? bookRatio + ':1 buy bias' : (1/bookRatio).toFixed(1) + ':1 sell bias'}`, urgent: false };
}

export async function POST(req: NextRequest) {
  try {
    const trade  = await req.json();
    const market = await fetchLTP(trade.symbol) as any;
    const ltp    = market.ltp;
    const pnlPs  = trade.side === 'LONG' ? ltp - trade.entry : trade.entry - ltp;
    const pnl    = parseFloat((pnlPs * trade.qty).toFixed(2));
    const advice = getAdvice(trade, market);

    return NextResponse.json({
      ltp, pnl, pnlPs: parseFloat(pnlPs.toFixed(2)),
      bookRatio: market.bookRatio,
      rangePct:  market.rangePct,
      dayHigh:   market.dayHigh,
      dayLow:    market.dayLow,
      buyWall:   market.buyWall,
      sellWall:  market.sellWall,
      volume:    market.volume,
      chgPct:    market.chgPct,
      advice,
      polledAt:  new Date().toISOString(),
    });
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
