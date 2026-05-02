// dashboard/src/app/api/watchlist/route.ts
// Persistent master watchlist — saved to watchlist.json
// GET: returns current watchlist
// POST: add symbol(s)
// DELETE: remove symbol
// PUT: replace entire watchlist

import { NextRequest, NextResponse } from 'next/server';
import { readFileSync, writeFileSync, existsSync } from 'fs';
import { join } from 'path';

const FILE = join(process.cwd(), 'watchlist.json');
const NEWS_FILE_DASH = join(process.cwd(), 'news_watchlist.json');
const NEWS_FILE_ROOT = join(process.cwd(), '..', 'news_watchlist.json');

const DEFAULT_WATCHLIST = [
  'TITAGARH', 'ADANIPOWER', 'TATAPOWER', 'SUZLON', 'NHPC',
  'SJVN', 'IREDA', 'RPOWER', 'BEL', 'HAL',
  'RAILTEL', 'RVNL', 'IRFC', 'RECLTD', 'PFC',
  'SAIL', 'NMDC', 'NALCO', 'GMDC', 'GUJALKALI',
  'EIHOTEL', 'YESBANK', 'JSWENERGY', 'INOXWIND', 'PCBL',
  'BEML', 'COCHINSHIP', 'GRSE', 'MAZAGON', 'NBCC',
  'ZEEL', 'IFCI', 'IRCON', 'HINDALCO', 'VEDL',
  'HUDCO', 'KAYNES', 'MIDHANI', 'TORNTPOWER', 'CESC',
];

function load(): string[] {
  if (!existsSync(FILE)) {
    writeFileSync(FILE, JSON.stringify(DEFAULT_WATCHLIST, null, 2));
    return DEFAULT_WATCHLIST;
  }
  try { return JSON.parse(readFileSync(FILE, 'utf-8')); }
  catch { return DEFAULT_WATCHLIST; }
}

function save(list: string[]) {
  writeFileSync(FILE, JSON.stringify([...new Set(list)], null, 2));
}

export async function GET() {
  // Also expose whether news_watchlist.json is visible to dashboard
  const hasNews = existsSync(NEWS_FILE_DASH) || existsSync(NEWS_FILE_ROOT);
  return NextResponse.json({ watchlist: load(), hasNews });
}

export async function POST(req: NextRequest) {
  const body    = await req.json();
  const symbols = Array.isArray(body.symbols) ? body.symbols : [body.symbol];
  const list    = load();
  const added: string[] = [];
  for (const sym of symbols) {
    const s = sym?.trim().toUpperCase();
    if (s && !list.includes(s)) { list.push(s); added.push(s); }
  }
  save(list);
  return NextResponse.json({ watchlist: list, added });
}

export async function DELETE(req: NextRequest) {
  const { symbol } = await req.json();
  const s    = symbol.trim().toUpperCase();
  const list = load().filter((x: string) => x !== s);
  save(list);
  return NextResponse.json({ watchlist: list, removed: s });
}

export async function PUT(req: NextRequest) {
  const { watchlist } = await req.json();
  const list = watchlist.map((s: string) => s.trim().toUpperCase()).filter(Boolean);
  save(list);
  return NextResponse.json({ watchlist: list });
}