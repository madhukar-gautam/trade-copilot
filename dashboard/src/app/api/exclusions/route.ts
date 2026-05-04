// dashboard/src/app/api/exclusions/route.ts
// Persistent exclusion list — symbols removed from scanner (master + news merged list)
// GET: returns current exclusions
// POST: add symbol(s)
// DELETE: remove symbol
// PUT: replace entire exclusions list

import { NextRequest, NextResponse } from 'next/server';
import { readFileSync, writeFileSync, existsSync } from 'fs';
import { join } from 'path';

const FILE = join(process.cwd(), 'exclusions.json');

function load(): string[] {
  if (!existsSync(FILE)) {
    writeFileSync(FILE, JSON.stringify([], null, 2));
    return [];
  }
  try { return JSON.parse(readFileSync(FILE, 'utf-8')); }
  catch { return []; }
}

function save(list: string[]) {
  writeFileSync(FILE, JSON.stringify([...new Set(list)], null, 2));
}

export async function GET() {
  return NextResponse.json({ exclusions: load() });
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
  return NextResponse.json({ exclusions: list, added });
}

export async function DELETE(req: NextRequest) {
  const { symbol } = await req.json();
  const s    = symbol.trim().toUpperCase();
  const list = load().filter((x: string) => x !== s);
  save(list);
  return NextResponse.json({ exclusions: list, removed: s });
}

export async function PUT(req: NextRequest) {
  const { exclusions } = await req.json();
  const list = exclusions.map((s: string) => s.trim().toUpperCase()).filter(Boolean);
  save(list);
  return NextResponse.json({ exclusions: list });
}

