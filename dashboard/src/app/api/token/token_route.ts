// dashboard/src/app/api/token/route.ts
// Update Groww API token from iPhone without redeploying
// Protected by ADMIN_PASSWORD env variable
// POST { password, token, cookie } → saves to token.json
// GET → returns token status (not the token itself)

import { NextRequest, NextResponse } from 'next/server';
import { writeFileSync, readFileSync, existsSync, mkdirSync } from 'fs';
import { join } from 'path';

// Works locally (saves next to dashboard) and on Fly.io (/app/data volume)
const TOKEN_FILE = existsSync('/app/data')
  ? '/app/data/token.json'
  : join(process.cwd(), 'token.json');

const ADMIN_PASS = process.env.ADMIN_PASSWORD || 'trade123';

export async function POST(req: NextRequest) {
  try {
    const { password, token, cookie } = await req.json();

    // Password check
    if (password !== ADMIN_PASS) {
      return NextResponse.json({ error: 'Invalid password' }, { status: 401 });
    }

    if (!token) {
      return NextResponse.json({ error: 'Token required' }, { status: 400 });
    }

    // Ensure Bearer prefix
    const cleanToken = token.trim().startsWith('Bearer ')
      ? token.trim()
      : `Bearer ${token.trim()}`;

    const data = {
      token:     cleanToken,
      cookie:    (cookie || '').trim(),
      updatedAt: new Date().toISOString(),
    };

    // Save to file — agent and scanner read this on every poll
    writeFileSync(TOKEN_FILE, JSON.stringify(data, null, 2));

    // Also update current process env so scanner picks it up immediately
    // without waiting for next file read
    process.env.GROWW_API_KEY = data.token;
    process.env.GROWW_COOKIE  = data.cookie;

    return NextResponse.json({
      success:   true,
      updatedAt: data.updatedAt,
      savedTo:   TOKEN_FILE,
      message:   'Token updated. Scanner and agent will use new token immediately.',
    });

  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 });
  }
}

export async function GET() {
  // Returns token status only — never exposes the actual token
  try {
    if (existsSync(TOKEN_FILE)) {
      const data = JSON.parse(readFileSync(TOKEN_FILE, 'utf-8'));
      const hint = data.token
        ? data.token.slice(0, 15) + '...' + data.token.slice(-6)
        : 'not set';
      return NextResponse.json({
        hasToken:  true,
        updatedAt: data.updatedAt,
        tokenHint: hint,
        savedTo:   TOKEN_FILE,
      });
    }
  } catch {}

  // Fallback — check env var
  const envToken = process.env.GROWW_API_KEY || '';
  return NextResponse.json({
    hasToken:  !!envToken,
    updatedAt: null,
    tokenHint: envToken ? envToken.slice(0, 15) + '...' : 'not set — add to .env.local',
    savedTo:   TOKEN_FILE,
  });
}
