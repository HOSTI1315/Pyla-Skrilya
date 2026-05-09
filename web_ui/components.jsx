// PylaAI UI primitives

const { useState, useEffect, useRef, useMemo } = React;

// ─── Icons ────────────────────────────────────────────────────
const Icon = {
  play:   (p) => <svg width={p.s||14} height={p.s||14} viewBox="0 0 16 16" fill="currentColor"><path d="M4 3l9 5-9 5V3z"/></svg>,
  pause:  (p) => <svg width={p.s||14} height={p.s||14} viewBox="0 0 16 16" fill="currentColor"><rect x="4" y="3" width="3" height="10" rx="0.5"/><rect x="9" y="3" width="3" height="10" rx="0.5"/></svg>,
  stop:   (p) => <svg width={p.s||14} height={p.s||14} viewBox="0 0 16 16" fill="currentColor"><rect x="3" y="3" width="10" height="10" rx="1"/></svg>,
  gear:   (p) => <svg width={p.s||14} height={p.s||14} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><circle cx="8" cy="8" r="2"/><path d="M8 1.5v1.8M8 12.7v1.8M3.4 3.4l1.3 1.3M11.3 11.3l1.3 1.3M1.5 8h1.8M12.7 8h1.8M3.4 12.6l1.3-1.3M11.3 4.7l1.3-1.3"/></svg>,
  chart:  (p) => <svg width={p.s||14} height={p.s||14} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M2 13h12M4 11V7M7 11V4M10 11V8M13 11V5"/></svg>,
  home:   (p) => <svg width={p.s||14} height={p.s||14} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M2 7l6-5 6 5v7H2z"/></svg>,
  shield: (p) => <svg width={p.s||14} height={p.s||14} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M8 1.5L2.5 3.5v4.2c0 3.4 2.5 6 5.5 6.8 3-0.8 5.5-3.4 5.5-6.8V3.5L8 1.5z"/></svg>,
  brawler:(p) => <svg width={p.s||14} height={p.s||14} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="8" cy="5.5" r="2.5"/><path d="M3 14c0-2.8 2.2-5 5-5s5 2.2 5 5"/></svg>,
  bolt:   (p) => <svg width={p.s||14} height={p.s||14} viewBox="0 0 16 16" fill="currentColor"><path d="M9 1L3 9h4l-1 6 6-8H8l1-6z"/></svg>,
  trophy: (p) => <svg width={p.s||14} height={p.s||14} viewBox="0 0 16 16" fill="currentColor"><path d="M4 2h8v2.5c0 2.2-1.3 4-3 4.5V11h2v1H5v-1h2V9C5.3 8.5 4 6.7 4 4.5V2zM2.5 3H4v2a2 2 0 01-1.5-2zM12 5V3h1.5A2 2 0 0112 5zM4 13h8v1H4z"/></svg>,
  caret:  (p) => <svg width={p.s||10} height={p.s||10} viewBox="0 0 10 10" fill="currentColor"><path d="M2 3l3 4 3-4H2z"/></svg>,
  plus:   (p) => <svg width={p.s||12} height={p.s||12} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M6 2v8M2 6h8"/></svg>,
  dot:    (p) => <svg width={p.s||6} height={p.s||6} viewBox="0 0 6 6" fill="currentColor"><circle cx="3" cy="3" r="3"/></svg>,
  refresh:(p) => <svg width={p.s||14} height={p.s||14} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M13 4a5.5 5.5 0 10.5 6M13 1.5V4h-2.5"/></svg>,
  eye:    (p) => <svg width={p.s||14} height={p.s||14} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M1.5 8S4 3 8 3s6.5 5 6.5 5-2.5 5-6.5 5S1.5 8 1.5 8z"/><circle cx="8" cy="8" r="2"/></svg>,
  log:    (p) => <svg width={p.s||14} height={p.s||14} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M3 2h7l3 3v9H3V2zM10 2v3h3M5 8h6M5 11h6"/></svg>,
  // chip-stack — два смещённых прямоугольника-«карточки», читается как «несколько инстансов»
  chips:  (p) => <svg width={p.s||14} height={p.s||14} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"><rect x="2.5" y="5.5" width="8" height="7.5" rx="1.5"/><rect x="5.5" y="2.5" width="8" height="7.5" rx="1.5" fill="var(--bg-1)"/></svg>,
  more:   (p) => <svg width={p.s||14} height={p.s||14} viewBox="0 0 16 16" fill="currentColor"><circle cx="3.5" cy="8" r="1.3"/><circle cx="8" cy="8" r="1.3"/><circle cx="12.5" cy="8" r="1.3"/></svg>,
  trash:  (p) => <svg width={p.s||14} height={p.s||14} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M3 4h10M6.5 4V2.5h3V4M4.5 4l.7 9h5.6l.7-9M7 7v4M9 7v4"/></svg>,
  search: (p) => <svg width={p.s||14} height={p.s||14} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/></svg>,
};

// ─── Status pill ────────────────────────────────────────────────
function StatusPill({ state }) {
  const _t = (k, fb) => (window.t ? window.t(k, fb) : fb);
  const cfg = {
    idle:    { dot:'#8A8F98', bg:'rgba(138,143,152,0.12)', text:_t('status.idle','Idle') },
    running: { dot:'#34D399', bg:'rgba(52,211,153,0.14)',  text:_t('status.running','Running') },
    paused:  { dot:'#F59E0B', bg:'rgba(245,158,11,0.14)',  text:_t('status.paused','Paused') },
    error:   { dot:'#F87171', bg:'rgba(248,113,113,0.14)', text:_t('status.error','Error') },
  }[state] || { dot:'#8A8F98', bg:'rgba(138,143,152,0.12)', text:state };
  return (
    <div className="pill" style={{background:cfg.bg, color:cfg.dot}}>
      <span className="pulse-dot" style={{background:cfg.dot, boxShadow: state==='running'?`0 0 0 0 ${cfg.dot}`:'none'}} />
      <span style={{color:'var(--fg)'}}>{cfg.text}</span>
    </div>
  );
}

// ─── Rarity accent ──────────────────────────────────────────────
const RARITY_COLORS = {
  'Starting':   '#9AA0A6',
  'Rare':       '#5B8DEF',
  'Super Rare': '#B45EE8',
  'Epic':       '#F2A33A',
};

// ─── Brawler tile ───────────────────────────────────────────────
function BrawlerTile({ b, selected, onPick }) {
  return (
    <button className="brawler-tile" data-selected={selected} onClick={() => onPick(b)}>
      <div className="brawler-avatar" style={{background:`linear-gradient(135deg, ${b.color}, ${b.color}cc)`}}>
        {b.icon_url
          ? <img src={b.icon_url} alt="" style={{width:'100%',height:'100%',objectFit:'cover',borderRadius:'inherit'}}/>
          : <span>{b.icon}</span>}
        <div className="brawler-rarity" style={{background:RARITY_COLORS[b.rarity]}} />
      </div>
      <div className="brawler-meta">
        <div className="brawler-name">{b.name}</div>
        <div className="brawler-stats">
          <span>{b.trophies}🏆</span>
          <span className="sep">·</span>
          <span>{b.wr}% WR</span>
        </div>
      </div>
      {selected && <div className="check">✓</div>}
    </button>
  );
}

// ─── Mode card ──────────────────────────────────────────────────
function ModeCard({ m, selected, onPick }) {
  return (
    <button className="mode-card" data-selected={selected} onClick={() => onPick(m)}
      style={{'--accent': m.color}}>
      <div className="mode-ico">
        <div className="mode-badge" style={{background:m.color}} />
      </div>
      <div className="mode-name">{m.name}</div>
      <div className="mode-type">{m.type}</div>
    </button>
  );
}

// ─── Trophy chart ───────────────────────────────────────────────
// `tier` draws a target band with cap/floor labels — meaningful for the
// session chart but noise on an all-time cumulative curve, so callers can
// pass `tier={null}` to suppress the band.
function TrophyChart({ data, tier = [300, 400] }) {
  const w = 560, h = 150, pad = 20;
  const lo = tier ? tier[0] : data[0];
  const hi = tier ? tier[1] : data[data.length - 1];
  const min = Math.min(...data, lo) - 10;
  const max = Math.max(...data, hi) + 10;
  const scaleY = v => pad + (h - pad*2) * (1 - (v - min) / (max - min));
  const scaleX = i => pad + (w - pad*2) * (i / (data.length - 1));
  const pts = data.map((v,i) => `${scaleX(i).toFixed(1)},${scaleY(v).toFixed(1)}`).join(' ');
  const areaPts = `${pad},${h-pad} ${pts} ${w-pad},${h-pad}`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="trophy-svg">
      {tier && <>
        <rect x={pad} y={scaleY(tier[1])} width={w-pad*2} height={scaleY(tier[0])-scaleY(tier[1])}
              fill="rgba(255,196,0,0.09)" />
        <line x1={pad} x2={w-pad} y1={scaleY(tier[0])} y2={scaleY(tier[0])} stroke="rgba(255,196,0,0.4)" strokeWidth="0.5" strokeDasharray="3 3"/>
        <line x1={pad} x2={w-pad} y1={scaleY(tier[1])} y2={scaleY(tier[1])} stroke="rgba(255,196,0,0.4)" strokeWidth="0.5" strokeDasharray="3 3"/>
      </>}
      <polygon points={areaPts} fill="url(#grad-trophy)" />
      <polyline points={pts} fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinejoin="round" />
      <defs>
        <linearGradient id="grad-trophy" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.35"/>
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0"/>
        </linearGradient>
      </defs>
      {tier && <>
        <text x={w-pad+2} y={scaleY(tier[1])-2} fontSize="8" fill="rgba(255,196,0,0.75)" textAnchor="end">{tier[1]} cap</text>
        <text x={w-pad+2} y={scaleY(tier[0])+8} fontSize="8" fill="rgba(255,196,0,0.75)" textAnchor="end">{tier[0]} floor</text>
      </>}
    </svg>
  );
}

// ─── Trophy chart with adaptive time axis ──────────────────────
// Adaptive ticks: hourly under 36h, daily under 14d, weekly under 90d,
// monthly above. Ticks are aligned to natural boundaries (top of the
// hour / midnight / Monday / 1st of the month) so the labels read cleanly.
function _trophyChartTicks(minTs, maxTs) {
  const span = Math.max(1, maxTs - minTs);
  const HOUR = 3600, DAY = 86400, WEEK = 7 * DAY;
  const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  let mode, step;
  if      (span < 36 * HOUR) { mode = 'hour';  step = span < 12 * HOUR ? 2 * HOUR : 6 * HOUR; }
  else if (span < 14 * DAY)  { mode = 'day';   step = DAY; }
  else if (span < 90 * DAY)  { mode = 'week';  step = WEEK; }
  else                        { mode = 'month'; step = 30 * DAY; }

  const fmt = (d) => {
    if (mode === 'hour')  return `${String(d.getHours()).padStart(2,'0')}:00`;
    if (mode === 'month') return MONTHS[d.getMonth()];
    return `${d.getDate()}/${d.getMonth() + 1}`;
  };

  const start = new Date(minTs * 1000);
  if (mode === 'hour') {
    start.setMinutes(0, 0, 0);
    const stepHrs = step / HOUR;
    start.setHours(Math.ceil((start.getHours() + 0.0001) / stepHrs) * stepHrs);
  } else if (mode === 'day') {
    start.setHours(0, 0, 0, 0);
    start.setDate(start.getDate() + 1);
  } else if (mode === 'week') {
    start.setHours(0, 0, 0, 0);
    const dow = start.getDay();
    const daysToMon = dow === 0 ? 1 : (8 - dow);
    start.setDate(start.getDate() + daysToMon);
  } else {
    start.setHours(0, 0, 0, 0); start.setDate(1);
    start.setMonth(start.getMonth() + 1);
  }

  const ticks = [];
  let cur = Math.floor(start.getTime() / 1000);
  while (cur <= maxTs && ticks.length < 12) {
    ticks.push({ ts: cur, label: fmt(new Date(cur * 1000)) });
    if (mode === 'month') {
      const d = new Date(cur * 1000); d.setMonth(d.getMonth() + 1);
      cur = Math.floor(d.getTime() / 1000);
    } else {
      cur += step;
    }
  }
  return ticks;
}

function TrophyTimedChart({ points }) {
  if (!points || points.length < 2) return null;
  const w = 720, h = 180, padX = 28, padTop = 8, padBot = 22;
  const minTs = points[0].ts, maxTs = points[points.length - 1].ts;
  const vs = points.map(p => p.value);
  const minV = Math.min(...vs), maxV = Math.max(...vs);
  const valuePad = Math.max(5, (maxV - minV) * 0.1);
  const lo = minV - valuePad, hi = maxV + valuePad;

  const scaleX = ts => padX + (w - padX * 2) * ((ts - minTs) / Math.max(1, maxTs - minTs));
  const scaleY = v  => padTop + (h - padTop - padBot) * (1 - (v - lo) / Math.max(1, hi - lo));

  const pts = points.map(p => `${scaleX(p.ts).toFixed(1)},${scaleY(p.value).toFixed(1)}`).join(' ');
  const areaPts = `${padX},${h - padBot} ${pts} ${w - padX},${h - padBot}`;
  const ticks = _trophyChartTicks(minTs, maxTs);
  const zeroY = scaleY(0);
  const zeroVisible = zeroY >= padTop && zeroY <= h - padBot;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="trophy-svg">
      {zeroVisible && (
        <line x1={padX} x2={w - padX} y1={zeroY} y2={zeroY}
              stroke="var(--border)" strokeWidth="0.5" strokeDasharray="2 3"/>
      )}
      <polygon points={areaPts} fill="url(#grad-trophy-timed)"/>
      <polyline points={pts} fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinejoin="round"/>
      <defs>
        <linearGradient id="grad-trophy-timed" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%"   stopColor="var(--accent)" stopOpacity="0.35"/>
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0"/>
        </linearGradient>
      </defs>
      <line x1={padX} x2={w - padX} y1={h - padBot} y2={h - padBot}
            stroke="var(--border)" strokeWidth="0.5"/>
      {ticks.map((tk, i) => {
        const x = scaleX(tk.ts);
        return (
          <g key={i}>
            <line x1={x} x2={x} y1={h - padBot} y2={h - padBot + 3}
                  stroke="var(--muted)" strokeWidth="0.5"/>
            <text x={x} y={h - padBot + 13} textAnchor="middle"
                  fontSize="9" fill="var(--muted)" fontWeight="700">{tk.label}</text>
          </g>
        );
      })}
    </svg>
  );
}

// ─── Game viewport (live preview) ───────────────────────────────
function GameViewport({ running, mode, brawler }) {
  const stream = (typeof useLiveStream === 'function') ? useLiveStream() : null;
  const ips = stream ? stream.ips : 0;
  const ipsLabel = running && ips > 0 ? `${ips.toFixed(1)} ips` : (running ? '…' : '—');
  return (
    <div className="viewport" data-running={running}>
      {/* faux phone screen */}
      <div className="viewport-frame">
        <div className="vp-top">
          <span className="vp-pill"><Icon.trophy s={10}/> {brawler?.trophies || '--'}</span>
          <span className="vp-mode" style={{color: mode?.color}}>{mode?.name || '—'}</span>
          <span className="vp-pill">1:34</span>
        </div>
        {/* arena */}
        <div className="vp-arena">
          <div className="vp-grid" />
          {/* bushes */}
          <div className="vp-bush" style={{left:'18%', top:'22%'}} />
          <div className="vp-bush" style={{left:'72%', top:'18%'}} />
          <div className="vp-bush" style={{left:'42%', top:'55%'}} />
          <div className="vp-bush" style={{left:'58%', top:'74%'}} />
          {/* walls */}
          <div className="vp-wall" style={{left:'30%', top:'40%', width:'14%', height:'4%'}} />
          <div className="vp-wall" style={{left:'56%', top:'58%', width:'12%', height:'4%'}} />
          {/* gems */}
          <div className="vp-gem" style={{left:'48%', top:'48%'}} />
          <div className="vp-gem" style={{left:'52%', top:'52%'}} />
          {/* enemies */}
          <div className="vp-unit enemy" style={{left:'65%', top:'35%'}}>
            <div className="vp-bbox" />
            <div className="vp-tag">enemy_colt · 0.92</div>
          </div>
          <div className="vp-unit enemy" style={{left:'38%', top:'65%'}}>
            <div className="vp-bbox" />
            <div className="vp-tag">enemy_bull · 0.88</div>
          </div>
          {/* bot */}
          <div className="vp-unit self" style={{left:'45%', top:'45%', background: brawler?.color || '#F8B733'}}>
            <div className="vp-bbox self" />
            <div className="vp-aim" />
          </div>
        </div>
        {/* controls */}
        <div className="vp-bottom">
          <div className="vp-joy">
            <div className="vp-joy-stick" />
          </div>
          <div className="vp-buttons">
            <div className="vp-btn super"><Icon.bolt s={14}/></div>
            <div className="vp-btn attack" />
          </div>
        </div>
        {/* scanning overlay */}
        {running && <div className="vp-scan" />}
      </div>
      {/* label */}
      <div className="vp-caption">
        <span><Icon.eye s={12}/> Live vision · YOLOv8</span>
        <span className="muted">{ipsLabel}</span>
      </div>
    </div>
  );
}

// ─── Log line ───────────────────────────────────────────────────
function LogLine({ line }) {
  const color = {info:'var(--muted-2)', action:'var(--accent)', warn:'#F59E0B', ok:'#34D399', error:'#F87171'}[line.lvl];
  return (
    <div className="log-line">
      <span className="log-t">{line.t}</span>
      <span className="log-lvl" style={{color, borderColor:color}}>{line.lvl}</span>
      <span className="log-msg">{line.msg}</span>
    </div>
  );
}

// ─── Small stat card ────────────────────────────────────────────
function Stat({ label, value, delta, accent }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={{color: accent}}>{value}</div>
      {delta && <div className="stat-delta" data-pos={delta.startsWith('+')}>{delta}</div>}
    </div>
  );
}

// ─── Section header ─────────────────────────────────────────────
function SectionHead({ icon, title, right }) {
  return (
    <div className="sec-head">
      <div className="sec-title">
        {icon}<span>{title}</span>
      </div>
      {right}
    </div>
  );
}

Object.assign(window, {
  Icon, StatusPill, BrawlerTile, ModeCard, TrophyChart,
  GameViewport, LogLine, Stat, SectionHead, RARITY_COLORS,
});
