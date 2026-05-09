// PylaAI — Stats page

const { useState: useStateStats, useMemo: useMemoStats } = React;

const RANGES = ['24h', '7d', '30d', 'all'];
const RANGE_SECONDS = { '24h': 86400, '7d': 7 * 86400, '30d': 30 * 86400, 'all': null };

const WIN_RESULTS  = new Set(['victory', '1st', '2nd']);
const LOSS_RESULTS = new Set(['defeat',  '3rd', '4th']);
function classifyResult(r) {
  if (WIN_RESULTS.has(r))  return 'win';
  if (LOSS_RESULTS.has(r)) return 'loss';
  return 'draw';
}

function filterByRange(entries, range) {
  const span = RANGE_SECONDS[range];
  if (span == null) return entries.slice();
  const cutoff = Math.floor(Date.now() / 1000) - span;
  return entries.filter(e => (e.ts || 0) >= cutoff);
}

function previousPeriod(entries, range) {
  const span = RANGE_SECONDS[range];
  if (span == null) return [];
  const now = Math.floor(Date.now() / 1000);
  const prevStart = now - 2 * span;
  const prevEnd   = now - span;
  return entries.filter(e => {
    const ts = e.ts || 0;
    return ts >= prevStart && ts < prevEnd;
  });
}

function aggregateEntries(entries) {
  const per = new Map();
  let wins = 0, losses = 0, draws = 0, trophyDelta = 0;
  let durTotal = 0, durCount = 0;

  // Per-brawler aggregate. `recent` records oldest→newest within entries
  // (entries themselves are newest-first from the API, so we walk backwards
  // to keep recent[] chronological, matching how mini-squares should render).
  for (let i = entries.length - 1; i >= 0; i--) {
    const e = entries[i];
    const b = (e.brawler || '').toLowerCase();
    if (!b) continue;
    if (!per.has(b)) per.set(b, {
      brawler: b, name: e.brawler_name || b,
      wins: 0, losses: 0, draws: 0, delta: 0,
      recent: [], lastTs: 0, durTotal: 0, durCount: 0,
    });
    const p = per.get(b);
    const cls = classifyResult(e.result);
    if (cls === 'win')  { p.wins++;   wins++;   }
    else if (cls === 'loss') { p.losses++; losses++; }
    else { p.draws++; draws++; }
    const d = Number(e.delta || 0);
    if (Number.isFinite(d)) { p.delta += d; trophyDelta += d; }
    const dur = Number(e.duration_s);
    if (Number.isFinite(dur) && dur > 0) {
      p.durTotal += dur; p.durCount++; durTotal += dur; durCount++;
    }
    p.recent.push(cls);
    if ((e.ts || 0) > p.lastTs) p.lastTs = e.ts || 0;
  }

  // Best per-brawler win streak — chronological traversal across entries.
  // Tracks the brawler and end-timestamp of the longest run.
  const perStreak = new Map();
  let bestN = 0, bestB = null, bestTs = 0;
  for (let i = entries.length - 1; i >= 0; i--) {
    const e = entries[i];
    const b = (e.brawler || '').toLowerCase();
    if (!b) continue;
    if (classifyResult(e.result) === 'win') {
      const cur = (perStreak.get(b) || 0) + 1;
      perStreak.set(b, cur);
      if (cur > bestN) { bestN = cur; bestB = b; bestTs = e.ts || 0; }
    } else {
      perStreak.set(b, 0);
    }
  }

  return {
    count: entries.length,
    wins, losses, draws,
    played: wins + losses,
    wr: (wins + losses) > 0 ? Math.round(1000 * wins / (wins + losses)) / 10 : 0,
    trophyDelta,
    avgDuration: durCount > 0 ? durTotal / durCount : 0,
    bestStreak: { n: bestN, brawler: bestB, ts: bestTs },
    perBrawler: Array.from(per.values()).sort((a, b) =>
      (b.wins + b.losses + b.draws) - (a.wins + a.losses + a.draws)),
  };
}

function fmtDeltaPct(cur, prev) {
  if (prev === 0) {
    if (cur === 0) return '—';
    return '▲ new';
  }
  const pct = Math.round(1000 * (cur - prev) / prev) / 10;
  return `${pct >= 0 ? '▲' : '▼'} ${Math.abs(pct).toFixed(1)}%`;
}

function fmtDuration(seconds) {
  if (!seconds || seconds <= 0) return '—';
  const s = Math.floor(seconds);
  const m = Math.floor(s / 60), sec = s % 60;
  return `${m}:${String(sec).padStart(2, '0')}`;
}

function fmtAbsTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  const days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${days[d.getDay()]} ${hh}:${mm}`;
}

function StatsPage({ brawler, mode }) {
  const [range, setRange] = useStateStats('7d');
  // Account selector — pass instance_id (or null for global aggregate) into
  // the live-stats hook. Persists between page visits.
  const [accountId, setAccountId] = useLocalState('pyla.stats.accountId', 0);
  const [accounts, setAccounts] = useStateStats([]);
  React.useEffect(() => {
    let cancelled = false;
    const fetchAccounts = async () => {
      try {
        const r = await window.PylaAPI.listInstances();
        if (cancelled) return;
        setAccounts(r.instances || []);
      } catch (_) {}
    };
    fetchAccounts();
    const id = setInterval(fetchAccounts, 8000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);
  const live = (typeof useLiveStats === 'function')
    ? useLiveStats({ instance_id: +accountId || null })
    : null;
  const history = (typeof useMatchHistory === 'function') ? useMatchHistory() : { entries: [], loaded: true };
  const sessionsHook = (typeof useRecentSessions === 'function') ? useRecentSessions(20) : { entries: [], loaded: true };
  const recentSessions = sessionsHook.entries || [];

  const rangeEntries = useMemoStats(() => filterByRange(history.entries, range), [history.entries, range]);
  const prevEntries  = useMemoStats(() => previousPeriod(history.entries, range), [history.entries, range]);
  const agg     = useMemoStats(() => aggregateEntries(rangeEntries), [rangeEntries]);
  const prevAgg = useMemoStats(() => aggregateEntries(prevEntries),  [prevEntries]);

  // Build a timestamped cumulative trophy curve from the raw match log, so the
  // chart can render a real time axis (hours / days / weeks / months) instead
  // of an index-based polyline. Server's trophy_curve_total has no timestamps.
  const trophyTimedPoints = useMemoStats(() => {
    const sorted = (history.entries || []).slice().sort((a, b) => (a.ts || 0) - (b.ts || 0));
    let running = 0;
    const out = [];
    for (const e of sorted) {
      const ts = Number(e.ts);
      if (!Number.isFinite(ts) || ts <= 0) continue;
      const d = Number(e.delta || 0);
      if (Number.isFinite(d)) running += d;
      out.push({ ts, value: running });
    }
    return out;
  }, [history.entries]);

  const brawlerPerf = (live && live.brawler_performance) || [];
  const rawModePerf = (live && live.mode_performance)    || [];
  const recentForm  = (live && live.recent_form)         || [];
  const recentMatches = (live && live.recent_matches)    || [];
  const totals      = (live && live.totals)              || { games:0, wins:0, losses:0, draws:0, wr:0, trophies_gained:0, trophies_lost:0, trophies_net:0 };
  const tGained = totals.trophies_gained || 0;
  const tLost   = totals.trophies_lost   || 0;
  const tNet    = (totals.trophies_net != null) ? totals.trophies_net : (tGained - tLost);

  const MODE_PALETTE = ['#F8B733','#2D7DD2','#E85D75','#5FAD56','#B45EE8','#F2A33A','#6EBAA7','#D13B3B'];
  const modePerf = rawModePerf.map((m, i) => ({
    ...m,
    name: m.mode || 'unknown',
    color: MODE_PALETTE[i % MODE_PALETTE.length],
  }));

  const bestStreakLine = agg.bestStreak.n > 0
    ? `${agg.bestStreak.brawler || '—'} · ${fmtAbsTime(agg.bestStreak.ts)}`
    : (t('common.noData') || '—');
  const matchesDelta = fmtDeltaPct(agg.count, prevAgg.count);
  const tdAbs = (agg.trophyDelta >= 0 ? '+' : '') + agg.trophyDelta;
  const trophiesDelta = fmtDeltaPct(Math.abs(agg.trophyDelta), Math.abs(prevAgg.trophyDelta));

  const sources = (live && live.sources) || [];

  return (
    <div className="stats-page">
      {/* Range pill + account selector */}
      <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8, gap:12, flexWrap:'wrap'}}>
        {accounts.length > 0 ? (
          <div className="row-gap" style={{gap: 8}}>
            <select className="input" style={{width: 220}}
                    value={String(accountId)}
                    onChange={e => setAccountId(parseInt(e.target.value, 10) || 0)}
                    title={t('stats.accountSelectorHint')}>
              <option value="0">{t('stats.accountAll')}</option>
              {accounts.map(a =>
                <option key={a.id} value={String(a.id)}>#{a.id} {a.name}</option>
              )}
            </select>
            {sources.length > 0 && (+accountId) === 0 && (
              <span className="muted small" title={sources.join('\n')}>
                {t('stats.sourcesLabel')}: {sources.length}
              </span>
            )}
          </div>
        ) : <div/>}
        <div className="seg">
          {RANGES.map(r =>
            <button key={r} className="seg-btn" data-on={range === r} onClick={() => setRange(r)}>
              {r}
            </button>
          )}
        </div>
      </div>

      {/* Range-aware KPI row */}
      <div className="kpi-row">
        <KPI label={t('stats.rangeMatches')} value={agg.count.toLocaleString()}
             sub={matchesDelta + ' ' + t('stats.vsPrev')}
             accent="var(--fg)"/>
        <KPI label={t('stats.rangeWR')} value={`${agg.wr}%`}
             sub={`${agg.wins}W · ${agg.losses}L${agg.draws ? ` · ${agg.draws}D` : ''}`}
             accent={agg.wr >= 55 ? '#34D399' : agg.wr >= 50 ? 'var(--accent)' : '#F87171'}/>
        <KPI label={t('stats.rangeTrophies')}
             value={tdAbs}
             sub={trophiesDelta + ' ' + t('stats.vsPrev')}
             accent={agg.trophyDelta >= 0 ? '#34D399' : '#F87171'}/>
        <KPI label={t('stats.bestStreak')}
             value={agg.bestStreak.n > 0 ? `${agg.bestStreak.n}W` : '—'}
             sub={bestStreakLine}
             accent="var(--accent)"/>
        <KPI label={t('stats.avgMatch')}
             value={fmtDuration(agg.avgDuration)}
             sub={agg.avgDuration > 0 ? 'tracked' : (t('common.noData') || 'no data')}
             accent="var(--fg)"/>
      </div>

      <div className="grid">
        {/* Per-brawler history (range-aware) — last-20 mini squares + WR gradient */}
        <div className="card span-3">
          <SectionHead
            icon={<Icon.brawler s={14}/>}
            title={t('stats.perBrawlerHistory')}
            right={<span className="muted small">{`${range} · ${agg.perBrawler.length}`}</span>}
          />
          {agg.perBrawler.length === 0
            ? <EmptyHint small text={t('stats.noMatchesPeriod')}/>
            : <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(280px, 1fr))', gap:12}}>
                {agg.perBrawler.slice(0, 9).map(p => <PerBrawlerHistory key={p.brawler} data={p}/>)}
              </div>}
        </div>

        {/* Overall trophy trend — timestamped curve with adaptive axis */}
        <div className="card span-3">
          <SectionHead
            icon={<Icon.trophy s={14}/>}
            title={t('stats.trophyTrendAllTime')}
            right={<span className="muted small">{`${tNet >= 0 ? '+' : ''}${tNet.toLocaleString()}🏆`}</span>}
          />
          {trophyTimedPoints.length > 1
            ? <TrophyTimedChart points={trophyTimedPoints}/>
            : <EmptyHint small text={t('common.noData') || 'Нет данных'}/>}
        </div>

        {/* Win rate per brawler — lifetime aggregate from /api/stats */}
        <div className="card span-2">
          <SectionHead
            icon={<Icon.brawler s={14}/>}
            title={t('stats.winRateByBrawler')}
            right={<span className="muted small">all time</span>}
          />
          {brawlerPerf.length === 0 ? (
            <EmptyHint text={t('common.noData') || 'Нет данных — запустите бота, чтобы начать собирать статистику.'}/>
          ) : (
            <div className="bar-list">
              {brawlerPerf.map(b => {
                const bg = b.trophies_gained || 0;
                const bl = b.trophies_lost   || 0;
                const bn = (b.trophies_net != null) ? b.trophies_net : (bg - bl);
                return (
                <div key={b.key || b.name} className="bar-row">
                  <div className="bar-name">
                    {b.name}
                    <span className={bn >= 0 ? 'pos' : 'neg'} style={{marginLeft:6, fontSize:11, fontWeight:600}}>
                      {bn >= 0 ? '+' : ''}{bn}🏆
                    </span>
                  </div>
                  <div className="bar-track">
                    <div className="bar-fill" style={{
                      width: `${b.wr}%`,
                      background: b.wr >= 55 ? 'linear-gradient(90deg, #34D399, #34D39980)'
                                : b.wr >= 50 ? 'linear-gradient(90deg, var(--accent), var(--accent-2))'
                                : 'linear-gradient(90deg, #F87171, #F8717180)'
                    }}/>
                    <span className="bar-label">{b.wr}%</span>
                  </div>
                  <div className="bar-meta">
                    <span className="muted">{b.games}g</span>
                    <span className="muted">{b.wins}W · {b.losses}L</span>
                    <span className="muted" title="gained · lost">+{bg}·−{bl}</span>
                  </div>
                </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Mode distribution */}
        <div className="card">
          <SectionHead icon={<Icon.shield s={14}/>} title={t('stats.byMode')}/>
          {modePerf.length === 0 ? (
            <EmptyHint small text={t('common.noData') || 'Нет данных по режимам.'}/>
          ) : (
            <>
              <ModePie modes={modePerf}/>
              <div className="mode-legend">
                {modePerf.map(m => (
                  <div key={m.name} className="mode-leg-row">
                    <span className="mode-dot" style={{background: m.color}}/>
                    <span className="mode-leg-name">{m.name}</span>
                    <span className="muted">{m.games}g</span>
                    <span className={m.wr >= 55 ? 'pos' : m.wr >= 50 ? '' : 'neg'}>{m.wr}%</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Recent form */}
        <div className="card span-3">
          <SectionHead icon={<Icon.log s={14}/>} title={t('stats.recentForm') || 'Recent form'}/>
          {recentForm.length === 0 ? (
            <EmptyHint small text={t('common.noData') || 'Нет матчей'}/>
          ) : (
            <div style={{display:'flex', gap:4, flexWrap:'wrap', padding:'4px 2px'}}>
              {recentForm.map((r, i) => {
                const color = r === 'W' ? '#34D399' : r === 'L' ? '#F87171' : '#9AA0AC';
                return (
                  <span key={i} style={{
                    width:24, height:24, display:'inline-flex', alignItems:'center', justifyContent:'center',
                    borderRadius:6, background:`${color}22`, color, fontWeight:700, fontSize:12,
                  }}>{r}</span>
                );
              })}
            </div>
          )}
        </div>

        {/* Recent sessions */}
        <div className="card span-3">
          <SectionHead icon={<Icon.log s={14}/>} title={t('stats.recentSessions') || 'Recent sessions'}/>
          {recentSessions.length === 0 ? (
            <EmptyHint text={t('common.noData') || 'Нет сессий'}/>
          ) : (
            <div className="match-list">
              {recentSessions.map((s, i) => {
                const d = new Date((s.start || 0) * 1000);
                const when = (s.start > 0)
                  ? `${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`
                  : '—';
                const played = (s.wins || 0) + (s.losses || 0) + (s.draws || 0);
                const wr = played > 0 ? Math.round(100 * (s.wins || 0) / played) : 0;
                const deltaNum = Number(s.trophy_delta || 0);
                const deltaStr = deltaNum >= 0 ? `+${deltaNum}` : String(deltaNum);
                const deltaColor = deltaNum > 0 ? '#34D399' : deltaNum < 0 ? '#F87171' : '#9AA0AC';
                const reason = s.reason || 'unknown';
                const reasonColor = reason === 'crashed' || reason === 'watchdog'
                  ? '#F87171'
                  : reason === 'finished' ? '#34D399' : '#9AA0AC';
                return (
                  <div key={i} className="match-row" style={{
                    display:'grid',
                    gridTemplateColumns:'96px 1fr 72px 72px 84px',
                    gap:8, alignItems:'center', padding:'8px 4px',
                    borderBottom:'1px solid var(--border)', fontSize:13,
                  }}>
                    <span className="muted" style={{fontSize:12}}>{when}</span>
                    <span>
                      {s.matches || played} {t('dash.games') || 'games'}
                      <span className="muted" style={{marginLeft:6, fontSize:11}}>
                        {(s.wins || 0)}W · {(s.losses || 0)}L{s.draws ? ` · ${s.draws}D` : ''}
                      </span>
                    </span>
                    <span className="muted" style={{fontSize:12, textAlign:'right'}}>{fmtDuration(s.duration_s || 0)}</span>
                    <span style={{color: deltaColor, fontWeight:600, textAlign:'right'}}>{deltaStr}</span>
                    <span style={{
                      color: reasonColor, fontWeight:600, fontSize:11, textAlign:'right',
                      padding:'2px 6px', borderRadius:6, background:`${reasonColor}22`,
                    }}>{reason}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Last matches */}
        <div className="card span-3">
          <SectionHead icon={<Icon.log s={14}/>} title={t('stats.lastMatches') || 'Last matches'}/>
          {recentMatches.length === 0 ? (
            <EmptyHint text={t('common.noData') || 'История матчей пока пустая'}/>
          ) : (
            <div className="match-list">
              {recentMatches.map((m, i) => {
                const bucket = m.bucket;
                const color = bucket === 'victory' ? '#34D399' : bucket === 'defeat' ? '#F87171' : '#9AA0AC';
                const deltaStr = m.delta > 0 ? `+${m.delta}` : (m.delta || 0).toString();
                return (
                  <div key={i} className="match-row" style={{
                    display:'grid',
                    gridTemplateColumns:'48px 1fr 88px 64px 72px',
                    gap:8, alignItems:'center', padding:'8px 4px',
                    borderBottom:'1px solid var(--border)', fontSize:13,
                  }}>
                    <span style={{
                      color, fontWeight:700, textAlign:'center',
                      padding:'2px 6px', borderRadius:6, background:`${color}22`,
                    }}>{m.result}</span>
                    <span>{m.brawler_name || m.brawler || '—'}</span>
                    <span className="muted" style={{fontSize:12}}>{m.gamemode || '—'}</span>
                    <span style={{color, fontWeight:600, textAlign:'right'}}>{deltaStr}</span>
                    <span className="muted" style={{fontSize:11, textAlign:'right'}}>
                      {m.ts ? fmtRelTime(m.ts) : '—'}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function fmtRelTime(ts) {
  const now = Math.floor(Date.now() / 1000);
  const diff = Math.max(0, now - ts);
  if (diff < 60) return `${diff}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}

function EmptyHint({ text, small }) {
  return (
    <div className="muted" style={{
      textAlign:'center',
      padding: small ? '14px 8px' : '28px 8px',
      fontSize: small ? 12 : 13,
    }}>
      {text}
    </div>
  );
}

function KPI({ label, value, sub, accent }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value" style={{color: accent}}>{value}</div>
      <div className="kpi-sub">{sub}</div>
    </div>
  );
}

function ModePie({ modes }) {
  const total = modes.reduce((a,b)=>a+b.games,0);
  const size = 140, r = 50, cx = size/2, cy = size/2;
  let acc = 0;
  const arcs = modes.map(m => {
    const frac = m.games / total;
    const start = acc * Math.PI * 2 - Math.PI/2;
    acc += frac;
    const end = acc * Math.PI * 2 - Math.PI/2;
    const large = frac > 0.5 ? 1 : 0;
    const x1 = cx + r * Math.cos(start), y1 = cy + r * Math.sin(start);
    const x2 = cx + r * Math.cos(end),   y2 = cy + r * Math.sin(end);
    return { d: `M${cx},${cy} L${x1.toFixed(1)},${y1.toFixed(1)} A${r},${r} 0 ${large} 1 ${x2.toFixed(1)},${y2.toFixed(1)} Z`, color: m.color };
  });
  return (
    <svg viewBox={`0 0 ${size} ${size}`} style={{width:'100%', maxWidth:160, margin:'0 auto', display:'block'}}>
      {arcs.map((a,i) => <path key={i} d={a.d} fill={a.color} stroke="var(--bg-1)" strokeWidth="1.5"/>)}
      <circle cx={cx} cy={cy} r="24" fill="var(--bg-1)"/>
      <text x={cx} y={cy-2} textAnchor="middle" fontSize="14" fontWeight="700" fill="var(--fg)">{total}</text>
      <text x={cx} y={cy+10} textAnchor="middle" fontSize="8" fill="var(--muted)">games</text>
    </svg>
  );
}

// Per-brawler card: name, totals, WR gradient bar, last-20 mini squares.
function PerBrawlerHistory({ data }) {
  const total = data.wins + data.losses + data.draws;
  const played = data.wins + data.losses;
  const wr = played > 0 ? Math.round(1000 * data.wins / played) / 10 : 0;
  const last20 = data.recent.slice(-20);
  const cut = Math.max(0.01, Math.min(0.99, wr / 100));
  const deltaStr = (data.delta >= 0 ? '+' : '') + data.delta;
  const lastSeen = data.lastTs
    ? (() => {
        const diff = Math.max(0, Date.now()/1000 - data.lastTs);
        if (diff < 60) return 'now';
        if (diff < 3600) return `${Math.floor(diff/60)}m`;
        if (diff < 86400) return `${Math.floor(diff/3600)}h`;
        return `${Math.floor(diff/86400)}d`;
      })()
    : '—';

  return (
    <div style={{
      border:'1px solid var(--border)', borderRadius:10, padding:'10px 12px',
      background:'var(--bg-1)', display:'flex', flexDirection:'column', gap:8,
    }}>
      <div style={{display:'flex', alignItems:'baseline', justifyContent:'space-between', gap:8}}>
        <div style={{fontWeight:700, fontSize:13}}>{data.name}</div>
        <div className="muted" style={{fontSize:10, fontWeight:600, letterSpacing:0.5}}>{lastSeen}</div>
      </div>
      <div className="muted" style={{fontSize:11, fontWeight:600}}>
        {total} games · {data.wins}W / {data.losses}L{data.draws ? ` / ${data.draws}D` : ''}
      </div>
      <div style={{display:'flex', justifyContent:'space-between', fontSize:11, fontWeight:700}}>
        <span style={{color:'#34D399'}}>{wr}% WIN</span>
        <span style={{color:'#F87171'}}>{(100 - wr).toFixed(1)}% LOSS</span>
      </div>
      <div style={{
        height:6, borderRadius:3,
        background:`linear-gradient(90deg, #34D399 0%, #34D399 ${cut*100}%, #F87171 ${cut*100}%, #F87171 100%)`,
      }}/>
      <div style={{display:'flex', gap:3, flexWrap:'wrap'}}>
        {last20.map((cls, i) => {
          const color = cls === 'win' ? '#34D399' : cls === 'loss' ? '#F87171' : '#9AA0AC';
          return <span key={i} style={{width:10, height:14, borderRadius:2, background:color}}/>;
        })}
        {Array.from({length: 20 - last20.length}, (_, i) =>
          <span key={'e'+i} style={{width:10, height:14, borderRadius:2, background:'var(--border)'}}/>
        )}
      </div>
      <div style={{display:'flex', justifyContent:'space-between', fontSize:11, paddingTop:2}}>
        <span className="muted">TROPHY Δ</span>
        <span style={{color: data.delta >= 0 ? '#34D399' : '#F87171', fontWeight:700}}>{deltaStr}</span>
      </div>
    </div>
  );
}

Object.assign(window, { StatsPage, EmptyHint });
