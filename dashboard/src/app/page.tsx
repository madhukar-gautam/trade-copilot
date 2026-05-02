'use client';
import { useState, useEffect, useRef, useCallback } from 'react';

// ── Types ────────────────────────────────────────────────────
type Analysis = {
  symbol: string; ltp: number; chgPct: number; bookRatio: number; bookBias: string;
  rangePct: number; volume: number; volQuality: string; spread: number;
  signal: string; confidence: number; reasons: string[]; warnings: string[];
  longSL: number; shortSL: number; longT1: number; shortT1: number;
  longT2: number; shortT2: number; longRR: number; shortRR: number;
  longSLReason?: string; shortSLReason?: string;
  dayHigh: number; dayLow: number; dayOpen: number; prevClose: number;
  upperCircuit: number; lowerCircuit: number; week52High: number; week52Low: number;
  buyWall?: any; sellWall?: any; lastTradeQty: number; atr: number;
  buyLevels: any[]; sellLevels: any[]; totalBuy: number; totalSell: number;
  timestamp: string;
};

type ScanResult = {
  symbol: string; ltp: number; chgPct: number; bookRatio: number; rangePct: number;
  volume: number; volQuality: string; spread: number; signal: string; confidence: number;
  score: number; alerts: string[]; dayHigh: number; dayLow: number;
  buyWall?: any; sellWall?: any; longSL: number; shortSL: number;
  longT1: number; shortT1: number; longRR: number; shortRR: number;
  upperCircuit: number; totalBuy: number; totalSell: number; scannedAt: string;
};

type Trade = {
  id: string; symbol: string; side: 'LONG' | 'SHORT'; entry: number; qty: number;
  sl: number; t1: number; t2: number; entryTime: string; exitTime: string | null;
  exitPrice: number | null; pnl: number | null; status: 'OPEN' | 'CLOSED'; notes: string;
  analysis: Analysis | null;
};

type PollResult = {
  ltp: number; pnl: number; pnlPs: number; bookRatio: number; rangePct: number;
  dayHigh: number; dayLow: number; buyWall?: any; sellWall?: any;
  volume: number; chgPct: number;
  advice: { action: string; reason: string; urgent: boolean };
  polledAt: string;
};

// ── Design tokens ────────────────────────────────────────────
const C = {
  bg: '#080e17', bg2: '#0d1520', bg3: '#111d2b',
  card: '#131e2d', card2: '#172030',
  green: '#00c896', red: '#ff5b6b', amber: '#f5a623', blue: '#4d9fff',
  muted: '#4a6080', muted2: '#6b85a3', text: '#dce8f5', text2: '#a0b4cc',
  border: 'rgba(255,255,255,0.07)', border2: 'rgba(255,255,255,0.12)',
};

const SIG_COLOR: Record<string, string> = {
  BUY: C.green, SELL: C.red, WAIT: C.muted2, AVOID: C.amber,
  EXIT: C.red, HOLD: C.blue, BOOK_PROFIT: C.green, WATCH: C.amber, REVIEW: C.amber,
};

const fmt   = (n?: number | null, d = 2) => n == null ? '—' : n.toFixed(d);
const fmtT  = (iso?: string | null) => iso ? new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—';
const fmtD  = (iso?: string | null) => iso ? new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) : '—';
const fmtVol= (v: number) => v >= 10000000 ? `${(v/10000000).toFixed(1)}Cr` : v >= 100000 ? `${(v/100000).toFixed(1)}L` : `${(v/1000).toFixed(0)}K`;

function Badge({ text, color }: { text: string; color: string }) {
  return <span style={{ background: `${color}20`, color, border: `1px solid ${color}40`, padding: '2px 10px', borderRadius: 6, fontSize: 12, fontWeight: 700 }}>{text}</span>;
}

// ── Scanner Row ───────────────────────────────────────────────
function ScanRow({ r, onAnalyze }: { r: ScanResult; onAnalyze: (symbol: string) => void }) {
  const color  = SIG_COLOR[r.signal] || C.muted2;
  const isGood = r.signal === 'BUY' || r.signal === 'SELL';

  return (
    <div onClick={() => isGood && onAnalyze(r.symbol)}
      style={{
        display: 'grid', gridTemplateColumns: '1fr 0.7fr 0.7fr 0.8fr 0.7fr 0.7fr 0.9fr 1.5fr',
        gap: 0, padding: '10px 16px', borderBottom: `0.5px solid ${C.border}`,
        alignItems: 'center', cursor: isGood ? 'pointer' : 'default',
        background: isGood ? `${color}06` : 'transparent',
        transition: 'background 0.15s',
      }}
      onMouseEnter={e => isGood && ((e.currentTarget as HTMLElement).style.background = `${color}12`)}
      onMouseLeave={e => isGood && ((e.currentTarget as HTMLElement).style.background = `${color}06`)}
    >
      <div>
        <span style={{ fontWeight: 700, fontSize: 13, color: C.text }}>{r.symbol}</span>
        {r.buyWall  && <span style={{ fontSize: 9, color: C.green, marginLeft: 6 }}>BW</span>}
        {r.sellWall && <span style={{ fontSize: 9, color: C.red,   marginLeft: 4 }}>SW</span>}
      </div>
      <span style={{ fontFamily: 'monospace', fontSize: 13, color: C.text }}>₹{fmt(r.ltp)}</span>
      <span style={{ fontFamily: 'monospace', fontSize: 12, color: r.chgPct >= 0 ? C.green : C.red }}>
        {r.chgPct >= 0 ? '+' : ''}{fmt(r.chgPct)}%
      </span>
      <span style={{ fontFamily: 'monospace', fontSize: 12, color: r.bookRatio > 1.3 ? C.green : r.bookRatio < 0.77 ? C.red : C.muted2 }}>
        {fmt(r.bookRatio)}:1
      </span>
      <span style={{ fontSize: 12, color: r.rangePct > 80 ? C.red : r.rangePct < 20 ? C.green : C.text2, fontFamily: 'monospace' }}>
        {fmt(r.rangePct, 0)}%
      </span>
      <span style={{ fontSize: 11, color: r.volQuality === 'EXCELLENT' ? C.green : r.volQuality === 'GOOD' ? C.blue : r.volQuality === 'THIN' ? C.amber : C.red }}>
        {fmtVol(r.volume)}
      </span>
      <Badge text={`${r.signal}${r.confidence > 0 ? ` ${r.confidence}%` : ''}`} color={color} />
      <div style={{ fontSize: 11, color: C.muted2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {r.alerts.length > 0 ? r.alerts[0] : isGood ? `SL ₹${fmt(r.signal === 'BUY' ? r.longSL : r.shortSL)} · T1 ₹${fmt(r.signal === 'BUY' ? r.longT1 : r.shortT1)}` : '—'}
      </div>
    </div>
  );
}

// ── Scanner Tab ───────────────────────────────────────────────
function ScannerTab({ onAnalyze }: { onAnalyze: (symbol: string) => void }) {
  const [results,    setResults]    = useState<ScanResult[]>([]);
  const [summary,    setSummary]    = useState<any>(null);
  const [loading,    setLoading]    = useState(false);
  const [autoOn,     setAutoOn]     = useState(false);
  const [autoSec,    setAutoSec]    = useState(60);
  const [lastScan,   setLastScan]   = useState<string>('');
  const [filter,     setFilter]     = useState<string>('ALL');
  const [masterList, setMasterList] = useState<string[]>([]);
  const [showMaster, setShowMaster] = useState(false);
  const [addInput,   setAddInput]   = useState('');
  const [saving,     setSaving]     = useState(false);
  const timerRef = useRef<any>(null);

  // Load master watchlist on mount
  useEffect(() => {
    fetch('/api/watchlist').then(r => r.json()).then(d => setMasterList(d.watchlist || [])).catch(() => {});
  }, []);

  const scan = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/scanner', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
      const d = await r.json();
      if (d.results) { setResults(d.results); setSummary(d.summary); setLastScan(new Date().toLocaleTimeString('en-IN')); }
      if (d.masterList) setMasterList(d.masterList);
    } catch {} finally { setLoading(false); }
  }, []);

  useEffect(() => {
    if (autoOn) { timerRef.current = setInterval(scan, autoSec * 1000); }
    else { clearInterval(timerRef.current); }
    return () => clearInterval(timerRef.current);
  }, [autoOn, autoSec, scan]);

  async function addToMaster(syms: string) {
    const symbols = syms.split(/[\s,\n]+/).map(s => s.trim().toUpperCase()).filter(Boolean);
    if (!symbols.length) return;
    setSaving(true);
    try {
      const r = await fetch('/api/watchlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbols }) });
      const d = await r.json();
      setMasterList(d.watchlist);
      setAddInput('');
    } catch {} finally { setSaving(false); }
  }

  async function removeFromMaster(symbol: string) {
    try {
      const r = await fetch('/api/watchlist', { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol }) });
      const d = await r.json();
      setMasterList(d.watchlist);
    } catch {}
  }

  // When scan result is clicked — also add to master
  function handleAnalyze(symbol: string) {
    // Add to master if not already there
    if (!masterList.includes(symbol)) {
      fetch('/api/watchlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol }) })
        .then(r => r.json()).then(d => setMasterList(d.watchlist)).catch(() => {});
    }
    onAnalyze(symbol);
  }

  const filtered = filter === 'ALL' ? results : results.filter(r => r.signal === filter);
  const buys     = results.filter(r => r.signal === 'BUY');
  const sells    = results.filter(r => r.signal === 'SELL');

  return (
    <div>
      {/* Controls */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 14 }}>
        <button onClick={scan} disabled={loading}
          style={{ background: loading ? C.muted : C.green, border: 'none', borderRadius: 9, padding: '9px 20px', color: '#080e17', fontWeight: 700, fontSize: 13, cursor: loading ? 'wait' : 'pointer', fontFamily: 'DM Sans' }}>
          {loading ? 'Scanning...' : '⚡ Scan now'}
        </button>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: C.muted2, cursor: 'pointer' }}>
          <input type="checkbox" checked={autoOn} onChange={e => setAutoOn(e.target.checked)} />
          Auto every
        </label>
        <select value={autoSec} onChange={e => setAutoSec(parseInt(e.target.value))}
          style={{ background: C.bg3, border: `1px solid ${C.border}`, borderRadius: 7, padding: '7px 10px', color: C.text, fontSize: 13, fontFamily: 'DM Sans' }}>
          <option value={30}>30 sec</option>
          <option value={60}>1 min</option>
          <option value={120}>2 min</option>
          <option value={300}>5 min</option>
        </select>
        <button onClick={() => setShowMaster(m => !m)}
          style={{ background: showMaster ? `${C.blue}20` : C.bg3, border: `1px solid ${showMaster ? C.blue : C.border2}`, borderRadius: 8, padding: '7px 14px', color: showMaster ? C.blue : C.muted2, fontSize: 12, cursor: 'pointer', fontFamily: 'DM Sans' }}>
          📋 Master list ({masterList.length})
        </button>
        {lastScan && <span style={{ fontSize: 11, color: C.muted2, marginLeft: 'auto' }}>Last scan: {lastScan}</span>}
      </div>

      {/* Master watchlist manager */}
      {showMaster && (
        <div style={{ background: C.card, border: `1px solid ${C.border2}`, borderRadius: 12, padding: 16, marginBottom: 14 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: C.text, marginBottom: 12 }}>
            Master Watchlist — {masterList.length} stocks
          </div>

          {/* Add stocks */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
            <input value={addInput} onChange={e => setAddInput(e.target.value.toUpperCase())}
              onKeyDown={e => e.key === 'Enter' && addToMaster(addInput)}
              placeholder="Add symbols: SBIN, TITAGARH, GALLANT..."
              style={{ flex: 1, background: C.bg2, border: `1px solid ${C.border2}`, borderRadius: 8, padding: '8px 12px', color: C.text, fontSize: 13, fontFamily: 'DM Sans' }} />
            <button onClick={() => addToMaster(addInput)} disabled={saving || !addInput.trim()}
              style={{ background: C.green, border: 'none', borderRadius: 8, padding: '8px 16px', color: '#080e17', fontWeight: 700, fontSize: 13, cursor: 'pointer', fontFamily: 'DM Sans', opacity: !addInput.trim() ? 0.5 : 1 }}>
              {saving ? '...' : '+ Add'}
            </button>
          </div>

          {/* Stock chips */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {masterList.map(sym => (
              <div key={sym} style={{ display: 'flex', alignItems: 'center', gap: 4, background: C.bg3, border: `1px solid ${C.border}`, borderRadius: 7, padding: '4px 10px' }}>
                <span onClick={() => handleAnalyze(sym)}
                  style={{ fontSize: 12, fontWeight: 600, color: C.text, cursor: 'pointer', fontFamily: 'monospace' }}
                  onMouseEnter={e => (e.target as HTMLElement).style.color = C.green}
                  onMouseLeave={e => (e.target as HTMLElement).style.color = C.text}>
                  {sym}
                </span>
                <button onClick={() => removeFromMaster(sym)}
                  style={{ background: 'none', border: 'none', color: C.muted, fontSize: 14, cursor: 'pointer', padding: '0 2px', lineHeight: 1 }}>
                  ×
                </button>
              </div>
            ))}
          </div>

          <div style={{ fontSize: 11, color: C.muted2, marginTop: 10 }}>
            Click any symbol to analyze · × to remove · Stocks auto-save to watchlist.json
          </div>
        </div>
      )}

      {/* Summary bar */}
      {summary && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8, marginBottom: 14 }}>
          {[
            { l: 'Scanned', v: summary.total, c: C.text },
            { l: 'BUY signals', v: summary.buy, c: C.green },
            { l: 'SELL signals', v: summary.sell, c: C.red },
            { l: 'WAIT', v: summary.wait, c: C.muted2 },
            { l: 'AVOID', v: summary.avoid, c: C.amber },
          ].map(({ l, v, c }) => (
            <div key={l} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: '10px 14px', textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: C.muted2, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>{l}</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: c, fontFamily: 'monospace' }}>{v}</div>
            </div>
          ))}
        </div>
      )}

      {/* Top opportunities */}
      {(buys.length > 0 || sells.length > 0) && (
        <div style={{ display: 'grid', gridTemplateColumns: sells.length > 0 ? '1fr 1fr' : '1fr', gap: 10, marginBottom: 14 }}>
          {buys.length > 0 && (
            <div style={{ background: `${C.green}08`, border: `1px solid ${C.green}20`, borderRadius: 10, padding: '12px 14px' }}>
              <div style={{ fontSize: 11, color: C.green, fontWeight: 600, marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.04em' }}>Top BUY opportunities</div>
              {buys.slice(0, 3).map(r => (
                <div key={r.symbol} onClick={() => handleAnalyze(r.symbol)}
                  style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 0', borderBottom: `0.5px solid ${C.border}`, cursor: 'pointer' }}>
                  <div>
                    <span style={{ fontWeight: 700, fontSize: 13, color: C.text }}>{r.symbol}</span>
                    <span style={{ fontSize: 11, color: C.muted2, marginLeft: 8 }}>{fmt(r.bookRatio)}:1 · {fmt(r.rangePct, 0)}% range</span>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: 13, fontFamily: 'monospace', color: C.green }}>+{fmt(r.chgPct)}%</div>
                    <div style={{ fontSize: 11, color: C.muted2 }}>Conf {r.confidence}%</div>
                  </div>
                </div>
              ))}
            </div>
          )}
          {sells.length > 0 && (
            <div style={{ background: `${C.red}08`, border: `1px solid ${C.red}20`, borderRadius: 10, padding: '12px 14px' }}>
              <div style={{ fontSize: 11, color: C.red, fontWeight: 600, marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.04em' }}>Top SELL opportunities</div>
              {sells.slice(0, 3).map(r => (
                <div key={r.symbol} onClick={() => handleAnalyze(r.symbol)}
                  style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 0', borderBottom: `0.5px solid ${C.border}`, cursor: 'pointer' }}>
                  <div>
                    <span style={{ fontWeight: 700, fontSize: 13, color: C.text }}>{r.symbol}</span>
                    <span style={{ fontSize: 11, color: C.muted2, marginLeft: 8 }}>{fmt(r.bookRatio)}:1 · {fmt(r.rangePct, 0)}% range</span>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: 13, fontFamily: 'monospace', color: C.red }}>{fmt(r.chgPct)}%</div>
                    <div style={{ fontSize: 11, color: C.muted2 }}>Conf {r.confidence}%</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Filter tabs */}
      {results.length > 0 && (
        <div style={{ display: 'flex', gap: 4, marginBottom: 10, flexWrap: 'wrap' }}>
          {['ALL', 'BUY', 'SELL', 'WAIT', 'AVOID'].map(f => (
            <button key={f} onClick={() => setFilter(f)}
              style={{ padding: '5px 14px', borderRadius: 6, fontSize: 12, fontWeight: 500, cursor: 'pointer', border: `1px solid ${filter === f ? (SIG_COLOR[f] || C.green) : C.border}`, fontFamily: 'DM Sans', background: filter === f ? `${SIG_COLOR[f] || C.green}15` : 'none', color: filter === f ? (SIG_COLOR[f] || C.green) : C.muted2 }}>
              {f} {f !== 'ALL' && `(${results.filter(r => r.signal === f).length})`}
            </button>
          ))}
        </div>
      )}

      {/* Results table */}
      {filtered.length > 0 ? (
        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 12, overflow: 'hidden' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 0.7fr 0.7fr 0.8fr 0.7fr 0.7fr 0.9fr 1.5fr', gap: 0, padding: '9px 16px', borderBottom: `1px solid ${C.border}` }}>
            {['Symbol', 'LTP', 'Change', 'Book', 'Range', 'Volume', 'Signal', 'Note'].map(h => (
              <span key={h} style={{ fontSize: 10, color: C.muted2, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h}</span>
            ))}
          </div>
          {filtered.map(r => <ScanRow key={r.symbol} r={r} onAnalyze={handleAnalyze} />)}
          <div style={{ padding: '8px 16px', fontSize: 11, color: C.muted2 }}>
            Click any BUY/SELL row → full analysis + auto-adds to master list
          </div>
        </div>
      ) : (
        <div style={{ textAlign: 'center', padding: '60px 0', color: C.muted }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>📡</div>
          <div style={{ fontSize: 15, marginBottom: 6 }}>
            {loading ? 'Scanning stocks...' : 'Click "Scan now" to find opportunities'}
          </div>
          <div style={{ fontSize: 13 }}>Scans your master watchlist · ranks by signal strength</div>
        </div>
      )}
    </div>
  );
}


// ── Analysis Card ─────────────────────────────────────────────
function AnalysisCard({ a, onEnter }: { a: Analysis; onEnter: (a: Analysis) => void }) {
  const [showBook, setShowBook] = useState(false);
  const color = SIG_COLOR[a.signal] || C.muted2;

  return (
    <div style={{ background: C.card, border: `1.5px solid ${color}30`, borderLeft: `3px solid ${color}`, borderRadius: 14, padding: '18px 20px', marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
        <span style={{ fontSize: 20, fontWeight: 700, color: C.text }}>{a.symbol}</span>
        <Badge text={a.signal} color={color} />
        <span style={{ fontSize: 13, color: a.chgPct >= 0 ? C.green : C.red, fontWeight: 600 }}>
          {a.chgPct >= 0 ? '+' : ''}{fmt(a.chgPct)}%
        </span>
        <span style={{ fontSize: 13, color: C.text, fontFamily: 'monospace' }}>₹{fmt(a.ltp)}</span>
        <span style={{ marginLeft: 'auto', fontSize: 12, color: C.muted2 }}>Conf {a.confidence}% · {fmtT(a.timestamp)}</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 6, marginBottom: 14 }}>
        {[
          { l: 'Book ratio', v: `${fmt(a.bookRatio)}:1`, c: a.bookBias === 'BUY' ? C.green : a.bookBias === 'SELL' ? C.red : C.muted2 },
          { l: 'Range pos', v: `${fmt(a.rangePct, 0)}%`, c: a.rangePct > 80 ? C.red : a.rangePct < 20 ? C.green : C.text2 },
          { l: 'Volume', v: a.volQuality, c: a.volQuality === 'EXCELLENT' ? C.green : a.volQuality === 'GOOD' ? C.blue : a.volQuality === 'THIN' ? C.amber : C.red },
          { l: 'Spread', v: `₹${fmt(a.spread)}`, c: C.text2 },
          { l: 'ATR', v: `₹${fmt(a.atr)}`, c: C.text2 },
        ].map(({ l, v, c }) => (
          <div key={l} style={{ background: C.bg2, borderRadius: 8, padding: '8px 10px' }}>
            <div style={{ fontSize: 10, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 3 }}>{l}</div>
            <div style={{ fontSize: 13, fontWeight: 600, color: c, fontFamily: 'monospace' }}>{v}</div>
          </div>
        ))}
      </div>

      {a.warnings?.map((w, i) => (
        <div key={i} style={{ background: `${C.amber}10`, border: `1px solid ${C.amber}25`, borderRadius: 8, padding: '8px 12px', fontSize: 12, color: C.amber, marginBottom: 8, lineHeight: 1.5 }}>⚠ {w}</div>
      ))}

      {a.reasons?.map((r, i) => (
        <div key={i} style={{ fontSize: 12, color: C.text2, padding: '4px 0', lineHeight: 1.5 }}>• {r}</div>
      ))}

      {(a.buyWall || a.sellWall) && (
        <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
          {a.buyWall  && <span style={{ background: `${C.green}10`, border: `1px solid ${C.green}25`, color: C.green, fontSize: 11, padding: '3px 10px', borderRadius: 6, fontFamily: 'monospace' }}>Buy wall ₹{a.buyWall.price} · {a.buyWall.quantity.toLocaleString()} qty</span>}
          {a.sellWall && <span style={{ background: `${C.red}10`, border: `1px solid ${C.red}25`, color: C.red, fontSize: 11, padding: '3px 10px', borderRadius: 6, fontFamily: 'monospace' }}>Sell wall ₹{a.sellWall.price} · {a.sellWall.quantity.toLocaleString()} qty</span>}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 14 }}>
        <div style={{ background: `${C.green}07`, border: `1px solid ${C.green}20`, borderRadius: 10, padding: '12px 14px' }}>
          <div style={{ fontSize: 11, color: C.green, fontWeight: 600, marginBottom: 8 }}>LONG setup</div>
          <div style={{ fontSize: 12, color: C.text2, lineHeight: 2, fontFamily: 'monospace' }}>
            SL: ₹{fmt(a.longSL)} · T1: ₹{fmt(a.longT1)} · T2: ₹{fmt(a.longT2)}<br/>
            R:R → T1: <span style={{ color: a.longRR >= 1.5 ? C.green : C.amber }}>{fmt(a.longRR)}x</span>
          </div>
          {a.longSLReason && <div style={{ fontSize: 11, color: C.muted2, marginTop: 6, lineHeight: 1.5 }}>SL reason: {a.longSLReason}</div>}
        </div>
        <div style={{ background: `${C.red}07`, border: `1px solid ${C.red}20`, borderRadius: 10, padding: '12px 14px' }}>
          <div style={{ fontSize: 11, color: C.red, fontWeight: 600, marginBottom: 8 }}>SHORT setup</div>
          <div style={{ fontSize: 12, color: C.text2, lineHeight: 2, fontFamily: 'monospace' }}>
            SL: ₹{fmt(a.shortSL)} · T1: ₹{fmt(a.shortT1)} · T2: ₹{fmt(a.shortT2)}<br/>
            R:R → T1: <span style={{ color: a.shortRR >= 1.5 ? C.green : C.amber }}>{fmt(a.shortRR)}x</span>
          </div>
          {a.shortSLReason && <div style={{ fontSize: 11, color: C.muted2, marginTop: 6, lineHeight: 1.5 }}>SL reason: {a.shortSLReason}</div>}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 6, marginTop: 10 }}>
        {[
          { l: 'Day low', v: `₹${fmt(a.dayLow)}`, c: C.text2 },
          { l: 'Day high', v: `₹${fmt(a.dayHigh)}`, c: C.text2 },
          { l: 'Lower circuit', v: `₹${fmt(a.lowerCircuit)}`, c: C.red },
          { l: 'Upper circuit', v: `₹${fmt(a.upperCircuit)}`, c: C.green },
        ].map(({ l, v, c }) => (
          <div key={l} style={{ background: C.bg3, borderRadius: 7, padding: '6px 10px', textAlign: 'center' }}>
            <div style={{ fontSize: 10, color: C.muted, marginBottom: 2 }}>{l}</div>
            <div style={{ fontSize: 12, fontWeight: 600, color: c, fontFamily: 'monospace' }}>{v}</div>
          </div>
        ))}
      </div>

      <button onClick={() => setShowBook(b => !b)}
        style={{ marginTop: 10, background: 'none', border: `1px solid ${C.border}`, borderRadius: 7, padding: '5px 12px', color: C.muted2, fontSize: 12, cursor: 'pointer', fontFamily: 'DM Sans' }}>
        {showBook ? 'Hide' : 'Show'} order book
      </button>

      {showBook && (
        <div style={{ marginTop: 10, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <div>
            <div style={{ fontSize: 11, color: C.green, marginBottom: 6, fontWeight: 500 }}>Buy side</div>
            {a.buyLevels?.slice(0, 5).map((l: any, i: number) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, fontFamily: 'monospace', padding: '3px 0', borderBottom: `0.5px solid ${C.border}` }}>
                <span style={{ color: C.green }}>₹{l.price}</span>
                <span style={{ color: C.text2 }}>{l.quantity?.toLocaleString()}</span>
                <span style={{ color: C.muted }}>{l.orderCount}x</span>
              </div>
            ))}
          </div>
          <div>
            <div style={{ fontSize: 11, color: C.red, marginBottom: 6, fontWeight: 500 }}>Sell side</div>
            {a.sellLevels?.slice(0, 5).map((l: any, i: number) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, fontFamily: 'monospace', padding: '3px 0', borderBottom: `0.5px solid ${C.border}` }}>
                <span style={{ color: C.red }}>₹{l.price}</span>
                <span style={{ color: C.text2 }}>{l.quantity?.toLocaleString()}</span>
                <span style={{ color: C.muted }}>{l.orderCount}x</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {a.signal !== 'AVOID' && (
        <button onClick={() => onEnter(a)}
          style={{ marginTop: 14, width: '100%', background: color, border: 'none', borderRadius: 10, padding: '11px 0', color: '#080e17', fontWeight: 700, fontSize: 14, cursor: 'pointer', fontFamily: 'DM Sans' }}>
          Log this trade →
        </button>
      )}
    </div>
  );
}

// ── Open Trade Card ───────────────────────────────────────────
function OpenTradeCard({ trade, onExit }: { trade: Trade; onExit: (id: string, price: string) => void }) {
  const [poll,    setPoll]   = useState<PollResult | null>(null);
  const [loading, setLoad]   = useState(false);
  const [exitP,   setExitP]  = useState('');
  const [autoSec, setAutoSec]= useState(300);
  const [autoOn,  setAutoOn] = useState(false);
  const timerRef             = useRef<any>(null);

  const refresh = useCallback(async () => {
    setLoad(true);
    try {
      const r = await fetch('/api/poll', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(trade) });
      const d = await r.json();
      if (!d.error) setPoll(d);
    } catch {} finally { setLoad(false); }
  }, [trade]);

  useEffect(() => { refresh(); }, []);
  useEffect(() => {
    if (autoOn) { timerRef.current = setInterval(refresh, autoSec * 1000); }
    else { clearInterval(timerRef.current); }
    return () => clearInterval(timerRef.current);
  }, [autoOn, autoSec, refresh]);

  const ltp    = poll?.ltp ?? trade.entry;
  const pnl    = poll?.pnl ?? 0;
  const pnlPs  = poll?.pnlPs ?? 0;
  const advice = poll?.advice;
  const advCol = advice ? (SIG_COLOR[advice.action] || C.muted2) : C.muted2;

  return (
    <div style={{ background: C.card, border: `1.5px solid ${pnl >= 0 ? C.green : C.red}30`, borderRadius: 14, padding: '16px 18px', marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
        <span style={{ fontSize: 16, fontWeight: 700, color: C.text }}>{trade.symbol}</span>
        <Badge text={trade.side} color={trade.side === 'LONG' ? C.green : C.red} />
        <span style={{ fontSize: 22, fontWeight: 700, fontFamily: 'monospace', color: pnl >= 0 ? C.green : C.red }}>
          {pnl >= 0 ? '+' : ''}₹{pnl.toFixed(0)}
        </span>
        <span style={{ fontSize: 13, color: C.muted2 }}>({pnlPs >= 0 ? '+' : ''}₹{fmt(pnlPs)}/share)</span>
        <span style={{ marginLeft: 'auto', fontSize: 11, color: C.muted2 }}>Entered {fmtT(trade.entryTime)}</span>
      </div>

      {advice && (
        <div style={{ background: `${advCol}12`, border: `1px solid ${advCol}30`, borderRadius: 9, padding: '10px 14px', fontSize: 13, color: advCol, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 10 }}>
          <Badge text={advice.action} color={advCol} />
          <span>{advice.reason}</span>
          {advice.urgent && <span style={{ marginLeft: 'auto', fontSize: 11, fontWeight: 700, color: C.red }}>URGENT</span>}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 6, marginBottom: 12 }}>
        {[
          { l: 'Entry', v: `₹${fmt(trade.entry)}`, c: C.text2 },
          { l: 'LTP', v: `₹${fmt(ltp)}`, c: C.text },
          { l: 'Stop loss', v: `₹${fmt(trade.sl)}`, c: C.red },
          { l: 'Target 1', v: `₹${fmt(trade.t1)}`, c: C.green },
          { l: 'Qty', v: `${trade.qty}`, c: C.text2 },
        ].map(({ l, v, c }) => (
          <div key={l} style={{ background: C.bg2, borderRadius: 8, padding: '7px 10px' }}>
            <div style={{ fontSize: 10, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 3 }}>{l}</div>
            <div style={{ fontSize: 13, fontWeight: 600, color: c, fontFamily: 'monospace' }}>{v}</div>
          </div>
        ))}
      </div>

      {poll && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, background: C.bg3, borderRadius: 6, padding: '4px 10px', color: poll.bookRatio > 1.3 ? C.green : poll.bookRatio < 0.77 ? C.red : C.muted2, fontFamily: 'monospace' }}>
            Book {fmt(poll.bookRatio)}:1
          </span>
          <span style={{ fontSize: 12, background: C.bg3, borderRadius: 6, padding: '4px 10px', color: C.text2, fontFamily: 'monospace' }}>
            Range {fmt(poll.rangePct, 0)}%
          </span>
          <span style={{ fontSize: 12, background: C.bg3, borderRadius: 6, padding: '4px 10px', color: poll.chgPct >= 0 ? C.green : C.red, fontFamily: 'monospace' }}>
            {poll.chgPct >= 0 ? '+' : ''}{fmt(poll.chgPct)}% today
          </span>
          <span style={{ fontSize: 11, color: C.muted, marginLeft: 'auto', alignSelf: 'center' }}>
            {loading ? 'Refreshing...' : `Polled ${fmtT(poll.polledAt)}`}
          </span>
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
        <button onClick={refresh} disabled={loading}
          style={{ background: C.bg3, border: `1px solid ${C.border2}`, borderRadius: 8, padding: '7px 14px', color: C.text2, fontSize: 12, cursor: 'pointer', fontFamily: 'DM Sans' }}>
          {loading ? 'Polling...' : '↻ Poll now'}
        </button>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: C.muted2, cursor: 'pointer' }}>
          <input type="checkbox" checked={autoOn} onChange={e => setAutoOn(e.target.checked)} />
          Auto every
        </label>
        <select value={autoSec} onChange={e => setAutoSec(parseInt(e.target.value))}
          style={{ background: C.bg3, border: `1px solid ${C.border}`, borderRadius: 7, padding: '6px 10px', color: C.text, fontSize: 12, fontFamily: 'DM Sans' }}>
          <option value={60}>1 min</option>
          <option value={180}>3 min</option>
          <option value={300}>5 min</option>
          <option value={600}>10 min</option>
        </select>
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input type="number" value={exitP} onChange={e => setExitP(e.target.value)}
          placeholder={`Exit price (LTP: ₹${fmt(ltp)})`}
          style={{ flex: 1, background: C.bg2, border: `1px solid ${C.border2}`, borderRadius: 8, padding: '9px 12px', color: C.text, fontSize: 13, fontFamily: 'DM Sans' }} />
        <button onClick={() => exitP && onExit(trade.id, exitP)} disabled={!exitP}
          style={{ background: C.red, border: 'none', borderRadius: 8, padding: '9px 18px', color: '#fff', fontWeight: 700, fontSize: 13, cursor: exitP ? 'pointer' : 'not-allowed', opacity: exitP ? 1 : 0.5, fontFamily: 'DM Sans' }}>
          Exit trade
        </button>
      </div>
    </div>
  );
}

// ── Enter Trade Modal ─────────────────────────────────────────
function EnterModal({ analysis, onClose, onSave }: { analysis: Analysis; onClose: () => void; onSave: (d: any) => void }) {
  const [side,  setSide]  = useState<'LONG'|'SHORT'>(analysis.signal === 'SELL' ? 'SHORT' : 'LONG');
  const [entry, setEntry] = useState(fmt(analysis.ltp));
  const [qty,   setQty]   = useState('');
  const [sl,    setSL]    = useState(fmt(analysis.longSL));
  const [t1,    setT1]    = useState(fmt(analysis.longT1));
  const [t2,    setT2]    = useState(fmt(analysis.longT2));
  const [notes, setNotes] = useState('');

  function flip(s: 'LONG'|'SHORT') {
    setSide(s);
    setSL(fmt(s === 'LONG' ? analysis.longSL : analysis.shortSL));
    setT1(fmt(s === 'LONG' ? analysis.longT1 : analysis.shortT1));
    setT2(fmt(s === 'LONG' ? analysis.longT2 : analysis.shortT2));
  }

  const rr   = entry && sl && t1 && Math.abs(parseFloat(entry) - parseFloat(sl)) > 0
    ? Math.abs((parseFloat(t1) - parseFloat(entry)) / (parseFloat(entry) - parseFloat(sl))).toFixed(2) : '—';
  const risk = entry && sl && qty
    ? Math.abs((parseFloat(entry) - parseFloat(sl)) * parseInt(qty)).toFixed(0) : '—';

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100, padding: 16 }}>
      <div style={{ background: C.card, border: `1px solid ${C.border2}`, borderRadius: 16, padding: 24, width: '100%', maxWidth: 460 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: C.text }}>Log trade — {analysis.symbol}</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: C.muted2, fontSize: 22, cursor: 'pointer' }}>×</button>
        </div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
          {(['LONG','SHORT'] as const).map(s => (
            <button key={s} onClick={() => flip(s)}
              style={{ flex: 1, padding: '9px 0', borderRadius: 9, border: `1.5px solid ${side === s ? (s==='LONG'?C.green:C.red) : C.border}`, background: side === s ? `${s==='LONG'?C.green:C.red}15` : 'none', color: side === s ? (s==='LONG'?C.green:C.red) : C.muted2, fontWeight: 700, fontSize: 14, cursor: 'pointer', fontFamily: 'DM Sans' }}>
              {s}
            </button>
          ))}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
          {[
            { label: 'Entry ₹', val: entry, set: setEntry },
            { label: 'Quantity', val: qty, set: setQty },
            { label: 'Stop loss ₹', val: sl, set: setSL },
            { label: 'Target 1 ₹', val: t1, set: setT1 },
            { label: 'Target 2 ₹', val: t2, set: setT2 },
          ].map(({ label, val, set }) => (
            <div key={label}>
              <div style={{ fontSize: 11, color: C.muted2, marginBottom: 4 }}>{label}</div>
              <input type="number" value={val} onChange={e => set(e.target.value)}
                style={{ width: '100%', background: C.bg2, border: `1px solid ${C.border2}`, borderRadius: 8, padding: '8px 12px', color: C.text, fontSize: 13, fontFamily: 'DM Sans', boxSizing: 'border-box' }} />
            </div>
          ))}
        </div>

        <div style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
          <div style={{ flex: 1, background: C.bg3, borderRadius: 8, padding: '8px 12px', textAlign: 'center' }}>
            <div style={{ fontSize: 10, color: C.muted, marginBottom: 3 }}>R:R</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: parseFloat(rr) >= 1.5 ? C.green : C.amber, fontFamily: 'monospace' }}>{rr}x</div>
          </div>
          <div style={{ flex: 1, background: C.bg3, borderRadius: 8, padding: '8px 12px', textAlign: 'center' }}>
            <div style={{ fontSize: 10, color: C.muted, marginBottom: 3 }}>MAX RISK</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: C.red, fontFamily: 'monospace' }}>₹{risk}</div>
          </div>
        </div>

        <textarea value={notes} onChange={e => setNotes(e.target.value)} placeholder="Notes (optional)"
          style={{ width: '100%', background: C.bg2, border: `1px solid ${C.border}`, borderRadius: 8, padding: '8px 12px', color: C.text, fontSize: 13, fontFamily: 'DM Sans', resize: 'none', height: 56, marginBottom: 14, boxSizing: 'border-box' }} />

        <button onClick={() => onSave({ symbol: analysis.symbol, side, entry: parseFloat(entry), qty: parseInt(qty), sl: parseFloat(sl), t1: parseFloat(t1), t2: parseFloat(t2), notes, analysis })}
          disabled={!entry || !qty || !sl || !t1}
          style={{ width: '100%', background: side === 'LONG' ? C.green : C.red, border: 'none', borderRadius: 10, padding: '12px 0', color: '#080e17', fontWeight: 700, fontSize: 14, cursor: 'pointer', fontFamily: 'DM Sans', opacity: (!entry || !qty) ? 0.5 : 1 }}>
          Start tracking this trade
        </button>
      </div>
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────
export default function App() {
  const [tab,       setTab]      = useState<'scanner'|'analyze'|'open'|'history'>('scanner');
  const [symbol,    setSymbol]   = useState('');
  const [analysis,  setAnalysis] = useState<Analysis | null>(null);
  const [analyzing, setAnalyzing]= useState(false);
  const [error,     setError]    = useState('');
  const [trades,    setTrades]   = useState<Trade[]>([]);
  const [modal,     setModal]    = useState<Analysis | null>(null);

  useEffect(() => {
    fetch('/api/trades').then(r => r.json()).then(setTrades).catch(() => {});
  }, []);

  const openTrades   = trades.filter(t => t.status === 'OPEN');
  const closedTrades = trades.filter(t => t.status === 'CLOSED');
  const dayPnL       = closedTrades.reduce((s, t) => s + (t.pnl || 0), 0);

  async function analyze(sym?: string) {
    const s = (sym || symbol).trim().toUpperCase();
    if (!s) return;
    setSymbol(s);
    setTab('analyze');
    setAnalyzing(true); setError(''); setAnalysis(null);
    try {
      const r = await fetch('/api/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: s }) });
      const d = await r.json();
      if (d.error) throw new Error(d.error);
      setAnalysis(d);
    } catch (e: any) { setError(e.message); }
    finally { setAnalyzing(false); }
  }

  async function saveTrade(data: any) {
    const r = await fetch('/api/trades', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
    const t = await r.json();
    setTrades(prev => [t, ...prev]);
    setModal(null); setTab('open');
  }

  async function exitTrade(id: string, exitPrice: string) {
    const r = await fetch('/api/trades', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, exitPrice }) });
    const updated = await r.json();
    setTrades(prev => prev.map(t => t.id === id ? updated : t));
  }

  const TABS = [
    { id: 'scanner', label: '📡 Scanner' },
    { id: 'analyze', label: '🎯 Analyze' },
    { id: 'open',    label: `📊 Active${openTrades.length > 0 ? ` (${openTrades.length})` : ''}` },
    { id: 'history', label: `📜 History${closedTrades.length > 0 ? ` (${closedTrades.length})` : ''}` },
  ] as const;

  return (
    <div style={{ background: C.bg, minHeight: '100vh', fontFamily: 'DM Sans, system-ui, sans-serif', color: C.text }}>
      {/* Top bar */}
      <div style={{ background: C.bg2, borderBottom: `1px solid ${C.border}`, padding: '12px 24px', display: 'flex', alignItems: 'center', gap: 16, position: 'sticky', top: 0, zIndex: 10 }}>
        <div style={{ width: 30, height: 30, background: C.green, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#080e17" strokeWidth="2.5"><polyline points="22 7 13.5 15.5 8.5 10.5 1 18"/></svg>
        </div>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700 }}>Trade Co-Pilot</div>
          <div style={{ fontSize: 11, color: C.muted2 }}>Groww · Live order book · Scanner</div>
        </div>
        {closedTrades.length > 0 && (
          <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
            <div style={{ fontSize: 11, color: C.muted2 }}>Day P&L</div>
            <div style={{ fontSize: 16, fontWeight: 700, fontFamily: 'monospace', color: dayPnL >= 0 ? C.green : C.red }}>
              {dayPnL >= 0 ? '+' : ''}₹{dayPnL.toFixed(0)}
            </div>
          </div>
        )}
        {openTrades.length > 0 && (
          <div style={{ background: `${C.amber}20`, border: `1px solid ${C.amber}40`, borderRadius: 8, padding: '4px 12px', fontSize: 12, color: C.amber }}>
            {openTrades.length} open
          </div>
        )}
      </div>

      <div style={{ maxWidth: 900, margin: '0 auto', padding: '20px 16px' }}>
        {/* Tabs */}
        <div style={{ display: 'flex', gap: 3, background: C.bg3, border: `1px solid ${C.border}`, borderRadius: 11, padding: 3, marginBottom: 20, width: 'fit-content' }}>
          {TABS.map(({ id, label }) => (
            <button key={id} onClick={() => setTab(id as any)}
              style={{ padding: '7px 16px', borderRadius: 8, fontSize: 13, fontWeight: 500, cursor: 'pointer', border: 'none', fontFamily: 'DM Sans', background: tab === id ? C.card2 : 'none', color: tab === id ? C.text : C.muted2, whiteSpace: 'nowrap' }}>
              {label}
            </button>
          ))}
        </div>

        {/* Scanner tab */}
        {tab === 'scanner' && (
          <ScannerTab onAnalyze={(sym) => analyze(sym)} />
        )}

        {/* Analyze tab */}
        {tab === 'analyze' && (
          <div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
              <input value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())}
                onKeyDown={e => e.key === 'Enter' && analyze()}
                placeholder="NSE symbol — e.g. SBIN, TITAGARH, RELIANCE"
                style={{ flex: 1, background: C.card, border: `1.5px solid ${C.border2}`, borderRadius: 10, padding: '12px 16px', color: C.text, fontSize: 15, fontFamily: 'DM Sans', outline: 'none' }} />
              <button onClick={() => analyze()} disabled={analyzing || !symbol.trim()}
                style={{ background: analyzing ? C.muted : C.green, border: 'none', borderRadius: 10, padding: '12px 24px', color: '#080e17', fontWeight: 700, fontSize: 14, cursor: analyzing ? 'wait' : 'pointer', fontFamily: 'DM Sans', whiteSpace: 'nowrap' }}>
                {analyzing ? 'Analyzing...' : 'Analyze →'}
              </button>
            </div>

            {error && (
              <div style={{ background: `${C.red}15`, border: `1px solid ${C.red}30`, borderRadius: 10, padding: '12px 16px', color: C.red, fontSize: 13, marginBottom: 16 }}>
                {error.includes('401') ? '⚠ Token expired — update GROWW_API_KEY in dashboard/.env.local' : error}
              </div>
            )}

            {analysis && <AnalysisCard a={analysis} onEnter={a => setModal(a)} />}

            {!analysis && !analyzing && !error && (
              <div style={{ textAlign: 'center', padding: '60px 0', color: C.muted }}>
                <div style={{ fontSize: 40, marginBottom: 12 }}>🎯</div>
                <div style={{ fontSize: 15, marginBottom: 6 }}>Type a stock symbol above</div>
                <div style={{ fontSize: 13 }}>Or click any BUY/SELL row in the Scanner tab</div>
              </div>
            )}
          </div>
        )}

        {/* Open trades */}
        {tab === 'open' && (
          <div>
            {openTrades.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '60px 0', color: C.muted }}>
                <div style={{ fontSize: 40, marginBottom: 12 }}>📊</div>
                <div style={{ fontSize: 15 }}>No open trades</div>
                <div style={{ fontSize: 13, marginTop: 6 }}>Scan for opportunities → analyze → log a trade</div>
              </div>
            ) : openTrades.map(t => (
              <OpenTradeCard key={t.id} trade={t} onExit={exitTrade} />
            ))}
          </div>
        )}

        {/* History */}
        {tab === 'history' && (
          <div>
            {closedTrades.length > 0 && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 16 }}>
                {[
                  { l: 'Total', v: closedTrades.length.toString(), c: C.text },
                  { l: 'Wins', v: closedTrades.filter(t => (t.pnl||0) > 0).length.toString(), c: C.green },
                  { l: 'Losses', v: closedTrades.filter(t => (t.pnl||0) < 0).length.toString(), c: C.red },
                  { l: 'Net P&L', v: `${dayPnL >= 0 ? '+' : ''}₹${dayPnL.toFixed(0)}`, c: dayPnL >= 0 ? C.green : C.red },
                ].map(({ l, v, c }) => (
                  <div key={l} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: '12px 14px', textAlign: 'center' }}>
                    <div style={{ fontSize: 11, color: C.muted2, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.04em' }}>{l}</div>
                    <div style={{ fontSize: 22, fontWeight: 700, color: c, fontFamily: 'monospace' }}>{v}</div>
                  </div>
                ))}
              </div>
            )}
            {closedTrades.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '60px 0', color: C.muted }}>
                <div style={{ fontSize: 40, marginBottom: 12 }}>📜</div>
                <div style={{ fontSize: 15 }}>No closed trades yet</div>
              </div>
            ) : (
              <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 12, overflow: 'hidden' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '0.8fr 0.5fr 0.7fr 0.7fr 0.5fr 0.7fr 0.6fr 1fr', gap: 0, padding: '10px 14px', borderBottom: `1px solid ${C.border}` }}>
                  {['Symbol','Side','Entry','Exit','Qty','P&L','Date','Time'].map(h => (
                    <span key={h} style={{ fontSize: 11, color: C.muted2, textTransform: 'uppercase', letterSpacing: '0.04em' }}>{h}</span>
                  ))}
                </div>
                {closedTrades.map(t => {
                  const pnl = t.pnl ?? 0;
                  return (
                    <div key={t.id} style={{ display: 'grid', gridTemplateColumns: '0.8fr 0.5fr 0.7fr 0.7fr 0.5fr 0.7fr 0.6fr 1fr', gap: 0, padding: '10px 14px', borderBottom: `0.5px solid ${C.border}`, fontSize: 13, alignItems: 'center' }}>
                      <span style={{ fontWeight: 600, color: C.text }}>{t.symbol}</span>
                      <Badge text={t.side} color={t.side === 'LONG' ? C.green : C.red} />
                      <span style={{ fontFamily: 'monospace', color: C.text2 }}>₹{fmt(t.entry)}</span>
                      <span style={{ fontFamily: 'monospace', color: C.text2 }}>₹{fmt(t.exitPrice)}</span>
                      <span style={{ fontFamily: 'monospace', color: C.muted2 }}>{t.qty}</span>
                      <span style={{ fontFamily: 'monospace', fontWeight: 700, color: pnl >= 0 ? C.green : C.red }}>{pnl >= 0 ? '+' : ''}₹{pnl.toFixed(0)}</span>
                      <span style={{ fontSize: 11, color: C.muted2 }}>{fmtD(t.entryTime)}</span>
                      <span style={{ fontSize: 11, color: C.muted2 }}>{fmtT(t.entryTime)} → {fmtT(t.exitTime)}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>

      {modal && <EnterModal analysis={modal} onClose={() => setModal(null)} onSave={saveTrade} />}
    </div>
  );
}
