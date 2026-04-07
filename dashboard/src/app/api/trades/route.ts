// dashboard/src/app/api/trades/route.ts
// Persists trade journal to trades.json

import { NextRequest, NextResponse } from 'next/server';
import { readFileSync, writeFileSync, existsSync } from 'fs';
import { join } from 'path';

const FILE = join(process.cwd(), '..', 'trades.json');

function load() {
  if (!existsSync(FILE)) return [];
  try { return JSON.parse(readFileSync(FILE, 'utf-8')); } catch { return []; }
}

function save(trades: any[]) {
  writeFileSync(FILE, JSON.stringify(trades, null, 2));
}

export async function GET() {
  return NextResponse.json(load());
}

export async function POST(req: NextRequest) {
  const body   = await req.json();
  const trades = load();
  const trade  = {
    id:        Date.now().toString(),
    symbol:    body.symbol,
    side:      body.side,           // LONG | SHORT
    entry:     body.entry,
    qty:       body.qty,
    sl:        body.sl,
    t1:        body.t1,
    t2:        body.t2,
    entryTime: new Date().toISOString(),
    exitTime:  null,
    exitPrice: null,
    pnl:       null,
    status:    'OPEN',             // OPEN | CLOSED
    notes:     body.notes || '',
    analysis:  body.analysis || null,  // store the full analysis snapshot
  };
  trades.unshift(trade);
  save(trades);
  return NextResponse.json(trade);
}

export async function PUT(req: NextRequest) {
  const body   = await req.json();   // { id, exitPrice, notes }
  const trades = load();
  const idx    = trades.findIndex((t: any) => t.id === body.id);
  if (idx === -1) return NextResponse.json({ error: 'Trade not found' }, { status: 404 });

  const trade    = trades[idx];
  const exit     = parseFloat(body.exitPrice);
  const pnl      = trade.side === 'LONG'
    ? parseFloat(((exit - trade.entry) * trade.qty).toFixed(2))
    : parseFloat(((trade.entry - exit) * trade.qty).toFixed(2));

  trades[idx] = {
    ...trade,
    exitPrice: exit,
    exitTime:  new Date().toISOString(),
    pnl,
    status:   'CLOSED',
    notes:    body.notes || trade.notes,
  };
  save(trades);
  return NextResponse.json(trades[idx]);
}

export async function DELETE(req: NextRequest) {
  const { id } = await req.json();
  const trades  = load().filter((t: any) => t.id !== id);
  save(trades);
  return NextResponse.json({ ok: true });
}
