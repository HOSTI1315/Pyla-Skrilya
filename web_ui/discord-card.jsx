// Discord notification card — 3 variants
// Designed as PNG templates to be rendered by PIL server-side.
// Size: 1200×630 (Discord embed default), dark theme matching PylaAI site.

// ── Design tokens (must match PIL render) ──────────────────
const DC_COLORS = {
  bg0: '#0B0D10',
  bg1: '#12151A',
  bg2: '#181C23',
  bg3: '#20252E',
  stroke: 'rgba(255,255,255,0.08)',
  stroke2: 'rgba(255,255,255,0.14)',
  fg: '#E6E8EC',
  fg2: '#B9BEC8',
  muted: '#8A8F98',
  accent: '#F8B733',
  accent2: '#7C5CFF',
  green: '#34D399',
  red: '#F87171',
};

// Sample session payload (what Python will pass to the PIL renderer)
const CARD_SAMPLE = {
  brawler: {
    name: 'Shelly',
    key: 'shelly',
    icon_url: '', // fallback to initial glyph
    color: '#F8B733',
  },
  mode: { name: 'Gem Grab', color: '#B45EE8' },
  goal: {
    type: 'trophies',    // 'trophies' | 'wins'
    current: 423,
    target: 500,
    start: 380,
  },
  stats: {
    games: 47,
    wins: 28,
    losses: 19,
    winRate: 60,
    netTrophies: +43,
    duration: '3h 12m',
    winStreak: 4,
  },
  // 60-point session curve (relative values, will be normalised)
  curve: [380,384,388,385,389,393,397,401,398,402,406,410,408,412,
          415,411,407,403,406,410,414,418,415,412,408,404,407,411,
          414,418,421,419,415,411,414,418,420,417,413,410,406,403,
          400,397,394,397,401,405,409,412,415,418,414,411,408,411,
          414,417,420,423],
};

// ── Shared pieces ──────────────────────────────────────────
function BrawlerGlyph({ name, color, size = 96 }) {
  return (
    <div style={{
      width: size, height: size,
      borderRadius: size * 0.22,
      background: `linear-gradient(135deg, ${color}, ${color}AA)`,
      display: 'grid', placeItems: 'center',
      color: '#fff',
      fontSize: size * 0.46,
      fontWeight: 700,
      boxShadow: `0 0 0 2px rgba(255,255,255,0.08), 0 8px 24px -8px ${color}55`,
      fontFamily: '"Space Grotesk", sans-serif',
      letterSpacing: -1,
    }}>
      {name[0]}
    </div>
  );
}

function TrophyChart({ data, width, height, stroke = DC_COLORS.accent, fill = true, showDots = false, smooth = true }) {
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = Math.max(1, max - min);
  const pad = 4;
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;
  const pts = data.map((v, i) => [
    pad + (i / (data.length - 1)) * innerW,
    pad + (1 - (v - min) / range) * innerH,
  ]);
  // Smooth catmull-rom → bezier
  const d = smooth ? catmullRom(pts) : pts.map((p, i) => (i === 0 ? 'M' : 'L') + p[0] + ',' + p[1]).join(' ');
  const fillD = d + ` L${pts[pts.length-1][0]},${height-pad} L${pts[0][0]},${height-pad} Z`;
  const first = data[0];
  const last = data[data.length-1];
  const up = last >= first;
  const col = stroke;
  return (
    <svg width={width} height={height} style={{display:'block'}}>
      <defs>
        <linearGradient id="chartfill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={col} stopOpacity="0.35"/>
          <stop offset="100%" stopColor={col} stopOpacity="0"/>
        </linearGradient>
      </defs>
      {fill && <path d={fillD} fill="url(#chartfill)"/>}
      <path d={d} fill="none" stroke={col} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round"/>
      {showDots && pts.map((p, i) =>
        (i === 0 || i === pts.length - 1) &&
        <circle key={i} cx={p[0]} cy={p[1]} r={4} fill={col} stroke={DC_COLORS.bg1} strokeWidth="2"/>
      )}
    </svg>
  );
}

function catmullRom(pts, tension = 0.5) {
  if (pts.length < 2) return '';
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] || p2;
    const cp1x = p1[0] + (p2[0] - p0[0]) / 6 * tension * 2;
    const cp1y = p1[1] + (p2[1] - p0[1]) / 6 * tension * 2;
    const cp2x = p2[0] - (p3[0] - p1[0]) / 6 * tension * 2;
    const cp2y = p2[1] - (p3[1] - p1[1]) / 6 * tension * 2;
    d += ` C${cp1x},${cp1y} ${cp2x},${cp2y} ${p2[0]},${p2[1]}`;
  }
  return d;
}

function Pill({ label, value, accent }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      background: DC_COLORS.bg2,
      border: `1px solid ${DC_COLORS.stroke}`,
      borderRadius: 10,
      padding: '10px 14px',
      minWidth: 90,
    }}>
      <span style={{fontSize: 11, color: DC_COLORS.muted, textTransform:'uppercase', letterSpacing:0.5, fontWeight:600}}>{label}</span>
      <span style={{fontSize: 20, color: accent || DC_COLORS.fg, fontWeight: 600, fontFamily:'"Space Grotesk", sans-serif', marginTop:2}}>{value}</span>
    </div>
  );
}

function ProgressBar({ pct, color = DC_COLORS.accent, height = 6 }) {
  return (
    <div style={{
      height, width: '100%',
      background: DC_COLORS.bg3,
      borderRadius: height,
      overflow: 'hidden',
    }}>
      <div style={{
        height: '100%',
        width: `${Math.min(100, Math.max(0, pct))}%`,
        background: `linear-gradient(90deg, ${color}, ${color}CC)`,
        borderRadius: height,
        boxShadow: `0 0 12px ${color}66`,
      }}/>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// VARIANT A — Split layout: left side info + stats, right half big chart
// ═══════════════════════════════════════════════════════════
function CardVariantA({ data = CARD_SAMPLE }) {
  const { brawler, mode, goal, stats, curve } = data;
  const pct = Math.min(100, Math.round((goal.current - goal.start) / (goal.target - goal.start) * 100));
  const net = stats.netTrophies;
  const netStr = (net >= 0 ? '+' : '') + net;

  return (
    <div style={{
      width: 1200, height: 630,
      background: DC_COLORS.bg0,
      backgroundImage: `radial-gradient(900px 500px at 15% -10%, ${brawler.color}18, transparent 60%), radial-gradient(700px 500px at 110% 110%, ${mode.color}14, transparent 60%)`,
      color: DC_COLORS.fg,
      fontFamily: '"Space Grotesk", "Inter", sans-serif',
      display: 'flex',
      position: 'relative',
      overflow: 'hidden',
    }}>
      {/* Grid texture */}
      <div style={{position:'absolute', inset:0, opacity:0.03, backgroundImage:
        'linear-gradient(to right, #fff 1px, transparent 1px), linear-gradient(to bottom, #fff 1px, transparent 1px)',
        backgroundSize:'48px 48px', pointerEvents:'none'}}/>

      {/* LEFT — 45% */}
      <div style={{width: 540, padding: '44px 40px 40px', display:'flex', flexDirection:'column', position:'relative'}}>
        {/* Header: brawler + mode */}
        <div style={{display:'flex', alignItems:'center', gap: 22}}>
          <BrawlerGlyph name={brawler.name} color={brawler.color} size={88}/>
          <div style={{minWidth: 0, flex: 1}}>
            <div style={{fontSize: 13, color: DC_COLORS.muted, fontWeight:600, letterSpacing:1.2, textTransform:'uppercase', whiteSpace:'nowrap'}}>Session Report</div>
            <div style={{fontSize: 36, fontWeight: 700, letterSpacing: -1, marginTop: 2, lineHeight: 1, whiteSpace:'nowrap'}}>{brawler.name}</div>
            <div style={{display:'inline-flex', alignItems:'center', gap: 8, marginTop: 8,
                         padding:'4px 10px 4px 8px', background: DC_COLORS.bg2,
                         border:`1px solid ${DC_COLORS.stroke}`, borderLeft:`3px solid ${mode.color}`,
                         borderRadius: 6, fontSize: 13, color: DC_COLORS.fg2, fontWeight: 500,
                         whiteSpace:'nowrap'}}>
              {mode.name}
            </div>
          </div>
        </div>

        {/* Goal */}
        <div style={{marginTop: 36}}>
          <div style={{display:'flex', justifyContent:'space-between', alignItems:'baseline', marginBottom: 10}}>
            <span style={{fontSize:12, color: DC_COLORS.muted, fontWeight:600, letterSpacing:0.8, textTransform:'uppercase'}}>
              Цель · {goal.type === 'trophies' ? 'Трофеи' : 'Победы'}
            </span>
            <span style={{fontSize: 12, color: DC_COLORS.muted, fontFamily:'var(--mono)'}}>{pct}%</span>
          </div>
          <div style={{display:'flex', alignItems:'baseline', gap: 12, fontFamily:'"Space Grotesk", sans-serif'}}>
            <span style={{fontSize: 44, fontWeight: 700, letterSpacing:-1.2}}>{goal.current}</span>
            <span style={{fontSize: 20, color: DC_COLORS.muted, fontWeight:500}}>→</span>
            <span style={{fontSize: 28, color: DC_COLORS.fg2, fontWeight: 600}}>{goal.target}</span>
            <span style={{fontSize: 22, marginLeft:4}}>{goal.type === 'trophies' ? '🏆' : '🏅'}</span>
          </div>
          <div style={{marginTop: 14}}>
            <ProgressBar pct={pct} color={brawler.color}/>
          </div>
        </div>

        {/* Stats row */}
        <div style={{marginTop: 'auto', display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap: 10}}>
          <Pill label="Games" value={stats.games}/>
          <Pill label="Wins" value={stats.wins} accent={DC_COLORS.green}/>
          <Pill label="Winrate" value={stats.winRate + '%'}/>
        </div>
        <div style={{display:'flex', justifyContent:'space-between', marginTop: 14, alignItems:'center'}}>
          <span style={{fontSize: 13, color: DC_COLORS.muted}}>
            <span style={{display:'inline-block', width:6, height:6, borderRadius:3, background: DC_COLORS.accent, marginRight:8, verticalAlign:'middle'}}/>
            Сессия: <b style={{color: DC_COLORS.fg}}>{stats.duration}</b>
          </span>
          {stats.winStreak > 0 && (
            <span style={{fontSize:13, color: DC_COLORS.fg2}}>🔥 {stats.winStreak} win streak</span>
          )}
        </div>
      </div>

      {/* RIGHT — chart half */}
      <div style={{flex:1, padding: '44px 40px 40px 20px', display:'flex', flexDirection:'column', position:'relative'}}>
        <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom: 18}}>
          <div>
            <div style={{fontSize: 13, color: DC_COLORS.muted, fontWeight:600, letterSpacing:1.2, textTransform:'uppercase'}}>Trophy Trend</div>
            <div style={{display:'flex', alignItems:'baseline', gap: 10, marginTop: 4}}>
              <span style={{
                fontSize: 54, fontWeight: 700,
                color: net >= 0 ? DC_COLORS.green : DC_COLORS.red,
                letterSpacing: -1.5, lineHeight:1,
              }}>{netStr}</span>
              <span style={{fontSize: 28, lineHeight:1}}>🏆</span>
            </div>
          </div>
          <div style={{textAlign:'right'}}>
            <div style={{fontSize: 11, color: DC_COLORS.muted, fontWeight:600, letterSpacing:0.8, textTransform:'uppercase'}}>Peak</div>
            <div style={{fontSize: 18, fontWeight: 600, marginTop: 2}}>{Math.max(...curve)}</div>
          </div>
        </div>

        <div style={{flex:1, background: DC_COLORS.bg1, borderRadius: 14, border:`1px solid ${DC_COLORS.stroke}`, padding: 14, display:'flex', flexDirection:'column'}}>
          <div style={{display:'flex', justifyContent:'space-between', fontSize: 11, color: DC_COLORS.muted, marginBottom: 8}}>
            <span>Start · {goal.start}</span>
            <span>Now · {goal.current}</span>
          </div>
          <div style={{flex:1, minHeight:0}}>
            <TrophyChart data={curve} width={540} height={280} stroke={net >= 0 ? DC_COLORS.green : DC_COLORS.red} showDots/>
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// VARIANT B — Hero chart on top, stats strip beneath
// ═══════════════════════════════════════════════════════════
function CardVariantB({ data = CARD_SAMPLE }) {
  const { brawler, mode, goal, stats, curve } = data;
  const pct = Math.min(100, Math.round((goal.current - goal.start) / (goal.target - goal.start) * 100));
  const net = stats.netTrophies;
  const netStr = (net >= 0 ? '+' : '') + net;

  return (
    <div style={{
      width: 1200, height: 630,
      background: DC_COLORS.bg0,
      color: DC_COLORS.fg,
      fontFamily: '"Space Grotesk", "Inter", sans-serif',
      display: 'flex', flexDirection:'column',
      position: 'relative',
      overflow: 'hidden',
    }}>
      {/* subtle vignette */}
      <div style={{position:'absolute', inset:0, background:
        `radial-gradient(800px 400px at 50% 0%, ${brawler.color}14, transparent 70%)`, pointerEvents:'none'}}/>

      {/* Top bar */}
      <div style={{padding:'28px 40px 0', display:'flex', alignItems:'center', gap: 20, position:'relative'}}>
        <BrawlerGlyph name={brawler.name} color={brawler.color} size={72}/>
        <div style={{flex:1}}>
          <div style={{display:'flex', alignItems:'baseline', gap: 14, flexWrap:'wrap'}}>
            <span style={{fontSize: 32, fontWeight: 700, letterSpacing: -0.8, whiteSpace:'nowrap'}}>{brawler.name}</span>
            <span style={{display:'inline-flex', padding:'3px 10px', background: DC_COLORS.bg2,
                          border:`1px solid ${DC_COLORS.stroke}`, borderLeft:`3px solid ${mode.color}`,
                          borderRadius: 5, fontSize: 12, color: DC_COLORS.fg2, fontWeight: 500,
                          whiteSpace:'nowrap'}}>
              {mode.name}
            </span>
          </div>
          <div style={{fontSize: 13, color: DC_COLORS.muted, marginTop: 4, fontWeight: 500}}>
            Цель: <b style={{color: DC_COLORS.fg}}>{goal.current} → {goal.target}</b> {goal.type === 'trophies' ? '🏆' : '🏅'} · прогресс {pct}%
          </div>
        </div>
        <div style={{textAlign:'right'}}>
          <div style={{fontSize: 11, color: DC_COLORS.muted, fontWeight:600, letterSpacing:0.8, textTransform:'uppercase'}}>За сессию</div>
          <div style={{display:'flex', alignItems:'baseline', gap: 6, justifyContent:'flex-end', marginTop: 2}}>
            <span style={{
              fontSize: 44, fontWeight: 700,
              color: net >= 0 ? DC_COLORS.green : DC_COLORS.red,
              letterSpacing: -1, lineHeight:1,
            }}>{netStr}</span>
            <span style={{fontSize: 20}}>🏆</span>
          </div>
        </div>
      </div>

      {/* Chart */}
      <div style={{flex:1, padding:'20px 40px 0', display:'flex', flexDirection:'column', minHeight:0, position:'relative'}}>
        <div style={{flex:1, minHeight:0, position:'relative'}}>
          <TrophyChart data={curve}
            width={1120} height={300}
            stroke={net >= 0 ? DC_COLORS.green : DC_COLORS.red}/>
          {/* Start / peak / now markers as floating labels */}
          <div style={{position:'absolute', left: 0, top: 0, fontSize: 11, color: DC_COLORS.muted, fontFamily:'var(--mono)'}}>
            {Math.max(...curve)}
          </div>
          <div style={{position:'absolute', left: 0, bottom: 4, fontSize: 11, color: DC_COLORS.muted, fontFamily:'var(--mono)'}}>
            {Math.min(...curve)}
          </div>
        </div>
      </div>

      {/* Stats strip */}
      <div style={{
        padding:'20px 40px 32px',
        background: `linear-gradient(180deg, transparent, ${DC_COLORS.bg1})`,
        display:'flex', gap: 12, alignItems:'stretch',
      }}>
        <Pill label="Games" value={stats.games}/>
        <Pill label="Wins" value={stats.wins} accent={DC_COLORS.green}/>
        <Pill label="Losses" value={stats.losses} accent={DC_COLORS.red}/>
        <Pill label="Winrate" value={stats.winRate + '%'} accent={DC_COLORS.accent}/>
        <div style={{flex:1, display:'flex', flexDirection:'column', justifyContent:'center',
                     padding:'10px 16px', background: DC_COLORS.bg2, border:`1px solid ${DC_COLORS.stroke}`,
                     borderRadius: 10}}>
          <div style={{fontSize:11, color: DC_COLORS.muted, textTransform:'uppercase', letterSpacing:0.5, fontWeight:600}}>
            Длительность сессии
          </div>
          <div style={{display:'flex', alignItems:'baseline', gap: 10, marginTop:2}}>
            <span style={{fontSize: 22, fontWeight: 600, fontFamily:'"Space Grotesk", sans-serif', whiteSpace:'nowrap'}}>{stats.duration}</span>
            {stats.winStreak > 0 && (
              <span style={{fontSize: 13, color: DC_COLORS.fg2, whiteSpace:'nowrap'}}>· 🔥 {stats.winStreak}</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// VARIANT C — Minimal: chart is the hero, stats bottom-right block
// ═══════════════════════════════════════════════════════════
function CardVariantC({ data = CARD_SAMPLE }) {
  const { brawler, mode, goal, stats, curve } = data;
  const net = stats.netTrophies;
  const netStr = (net >= 0 ? '+' : '') + net;
  const pct = Math.min(100, Math.round((goal.current - goal.start) / (goal.target - goal.start) * 100));

  return (
    <div style={{
      width: 1200, height: 630,
      background: DC_COLORS.bg0,
      color: DC_COLORS.fg,
      fontFamily: '"Space Grotesk", "Inter", sans-serif',
      position: 'relative',
      overflow: 'hidden',
    }}>
      {/* Huge chart as hero — full-bleed */}
      <div style={{position:'absolute', inset:0, opacity:0.9}}>
        <TrophyChart data={curve} width={1200} height={630}
          stroke={net >= 0 ? DC_COLORS.green : DC_COLORS.red}/>
      </div>
      {/* Top gradient for legibility */}
      <div style={{position:'absolute', top:0, left:0, right:0, height: 200,
        background: `linear-gradient(180deg, ${DC_COLORS.bg0} 0%, ${DC_COLORS.bg0}DD 40%, transparent 100%)`,
        pointerEvents:'none'}}/>
      {/* Bottom gradient for the stats panel */}
      <div style={{position:'absolute', bottom:0, left:0, right:0, height: 260,
        background: `linear-gradient(0deg, ${DC_COLORS.bg0} 30%, transparent 100%)`,
        pointerEvents:'none'}}/>

      {/* TOP header */}
      <div style={{position:'absolute', top:36, left:40, right:40, display:'flex', alignItems:'center', gap: 20}}>
        <BrawlerGlyph name={brawler.name} color={brawler.color} size={80}/>
        <div style={{flex:1, minWidth: 0}}>
          <div style={{fontSize: 12, color: DC_COLORS.muted, fontWeight:600, letterSpacing:1.2, textTransform:'uppercase', whiteSpace:'nowrap'}}>
            {mode.name} · Session
          </div>
          <div style={{fontSize: 40, fontWeight: 700, letterSpacing: -1, marginTop: 2, lineHeight:1, whiteSpace:'nowrap'}}>
            {brawler.name}
          </div>
        </div>
        <div style={{textAlign:'right'}}>
          <div style={{fontSize: 12, color: DC_COLORS.muted, fontWeight:600, letterSpacing:1.2, textTransform:'uppercase'}}>Net</div>
          <div style={{display:'flex', alignItems:'baseline', gap: 8, marginTop:2}}>
            <span style={{
              fontSize: 56, fontWeight: 700,
              color: net >= 0 ? DC_COLORS.green : DC_COLORS.red,
              letterSpacing: -1.5, lineHeight:1,
            }}>{netStr}</span>
            <span style={{fontSize: 26}}>🏆</span>
          </div>
        </div>
      </div>

      {/* Bottom-left: goal + duration */}
      <div style={{position:'absolute', left:40, bottom:36, display:'flex', gap: 32, alignItems:'flex-end'}}>
        <div>
          <div style={{fontSize: 11, color: DC_COLORS.muted, fontWeight:600, letterSpacing:0.8, textTransform:'uppercase'}}>Цель</div>
          <div style={{display:'flex', alignItems:'baseline', gap: 8, marginTop: 4}}>
            <span style={{fontSize: 30, fontWeight: 700, letterSpacing:-0.5}}>{goal.current}</span>
            <span style={{fontSize: 16, color: DC_COLORS.muted}}>→</span>
            <span style={{fontSize: 22, color: DC_COLORS.fg2, fontWeight: 600}}>{goal.target}</span>
            <span style={{fontSize: 16, marginLeft: 2}}>{goal.type === 'trophies' ? '🏆' : '🏅'}</span>
          </div>
          <div style={{marginTop: 8, width: 240}}>
            <ProgressBar pct={pct} color={brawler.color} height={4}/>
          </div>
        </div>
        <div>
          <div style={{fontSize: 11, color: DC_COLORS.muted, fontWeight:600, letterSpacing:0.8, textTransform:'uppercase'}}>Duration</div>
          <div style={{fontSize: 30, fontWeight: 700, letterSpacing:-0.5, marginTop: 4, whiteSpace:'nowrap'}}>{stats.duration}</div>
        </div>
      </div>

      {/* Bottom-right: stats block */}
      <div style={{position:'absolute', right:40, bottom:36, display:'grid',
                   gridTemplateColumns:'repeat(3, auto)', gap: 8,
                   background: DC_COLORS.bg1 + 'E6',
                   border: `1px solid ${DC_COLORS.stroke2}`,
                   backdropFilter: 'blur(8px)',
                   borderRadius: 14,
                   padding: 14}}>
        <StatTile label="Games" value={stats.games}/>
        <StatTile label="Wins" value={stats.wins} accent={DC_COLORS.green}/>
        <StatTile label="WR" value={stats.winRate + '%'} accent={DC_COLORS.accent}/>
      </div>
    </div>
  );
}

function StatTile({ label, value, accent }) {
  return (
    <div style={{padding: '4px 14px', textAlign:'center', minWidth: 76}}>
      <div style={{fontSize: 10, color: DC_COLORS.muted, textTransform:'uppercase', letterSpacing:0.6, fontWeight:600}}>{label}</div>
      <div style={{fontSize: 24, fontWeight: 700, color: accent || DC_COLORS.fg, fontFamily:'"Space Grotesk", sans-serif', marginTop: 2}}>{value}</div>
    </div>
  );
}

Object.assign(window, { CardVariantA, CardVariantB, CardVariantC, CARD_SAMPLE });
