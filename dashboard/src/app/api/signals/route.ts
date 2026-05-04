import { NextResponse } from 'next/server';
import { readFileSync, writeFileSync, existsSync } from 'fs';
import { join } from 'path';

const SIGNALS_FILE  = join(process.cwd(), '..', 'snapshot_signals.json');
const POSITION_FILE = join(process.cwd(), '..', 'positions.json');
const GPT_FILE      = join(process.cwd(), '..', 'gpt_alerts.json');

// Also check inside dashboard folder (for cloud deployment)
const SIGNALS_FILE2 = join(process.cwd(), 'snapshot_signals.json');
const GPT_FILE2     = join(process.cwd(), 'gpt_alerts.json');

export async function GET() {
  // ── Rule-based signals (existing) ──────────────────────────
  let signals  = [];
  let watchlist= [];
  let positions= {};
  let updated_at = null;

  const sigFile = existsSync(SIGNALS_FILE) ? SIGNALS_FILE : SIGNALS_FILE2;
  if (existsSync(sigFile)) {
    try {
      const data = JSON.parse(readFileSync(sigFile, 'utf-8'));
      signals    = data.signals   || [];
      watchlist  = data.watchlist || [];
      positions  = data.positions || {};
      updated_at = data.updated_at || null;
    } catch {}
  }

  // ── GPT-4o alerts (new) ─────────────────────────────────────
  let gptAlerts: any[] = [];
  const gptFile = existsSync(GPT_FILE) ? GPT_FILE : GPT_FILE2;
  if (existsSync(gptFile)) {
    try {
      const data = JSON.parse(readFileSync(gptFile, 'utf-8'));
      // Newest first, last 10 only
      gptAlerts  = (data.alerts || []).slice(-10).reverse();
    } catch {}
  }

  return NextResponse.json({
    // Existing fields — unchanged, dashboard still works
    signals,
    watchlist,
    positions,
    updated_at,
    // New field — GPT-4o alerts for banner notifications
    gptAlerts,
    hasGptAlerts: gptAlerts.length > 0,
  });
}

export async function PUT(req: Request) {
  // Existing — save positions, unchanged
  const body = await req.json();
  if (body.positions) {
    writeFileSync(POSITION_FILE, JSON.stringify(body.positions, null, 2));
  }
  return NextResponse.json({ ok: true });
}