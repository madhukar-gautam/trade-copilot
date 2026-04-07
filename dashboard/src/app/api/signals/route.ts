import { NextResponse } from 'next/server';
import { readFileSync, writeFileSync, existsSync } from 'fs';
import { join } from 'path';

const SIGNALS_FILE  = join(process.cwd(), '..', 'snapshot_signals.json');
const POSITION_FILE = join(process.cwd(), '..', 'positions.json');

export async function GET() {
  if (!existsSync(SIGNALS_FILE)) {
    return NextResponse.json({ signals: [], watchlist: [], positions: {}, updated_at: null });
  }
  return NextResponse.json(JSON.parse(readFileSync(SIGNALS_FILE, 'utf-8')));
}

export async function PUT(req: Request) {
  const body = await req.json();
  if (body.positions) {
    writeFileSync(POSITION_FILE, JSON.stringify(body.positions, null, 2));
  }
  return NextResponse.json({ ok: true });
}
