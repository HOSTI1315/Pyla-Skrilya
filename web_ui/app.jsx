// PylaAI — main app

const { useState, useEffect, useRef, useMemo } = React;

function App({ tweaks }) {
  const [tab, setTab] = useLocalState('pyla.ui.tab', 'dashboard');
  const [lang, setLang] = useLang();
  const brawlersLive = useLiveBrawlers();
  const liveBrawlers = brawlersLive.length ? brawlersLive : (window.BRAWLERS || []);
  const live = useLiveStream();
  const matchHistory = useMatchHistory(500);
  // Aggregate metrics across every running instance subprocess. Powers the
  // Dashboard "Сессия" panel so multi-emulator runs show combined stats.
  const instAgg = useInstancesDashboard(4000);

  // Persisted dashboard form — survives reload via localStorage.
  const [brawlerKey, setBrawlerKey] = useLocalState('pyla.dash.brawlerKey', null);
  const [brawler, setBrawler] = useState(liveBrawlers[0] || BRAWLERS[0]);
  // Track first-hydration so the saved brawler is always restored on reload —
  // the previous "only-pick-when-vanished" check skipped the saved key whenever
  // the placeholder BRAWLERS[0] happened to also exist in the live roster.
  const brawlerHydrated = useRef(false);
  useEffect(() => {
    if (!liveBrawlers.length) return;
    if (!brawlerHydrated.current) {
      // Don't hydrate against the mock fallback — only against the real
      // API roster. Otherwise a saved key like "spike" (not in the mock
      // 12-brawler list) silently reverts to Shelly on every refresh.
      if (!window.BRAWLERS_FROM_API) return;
      brawlerHydrated.current = true;
      const saved   = brawlerKey && liveBrawlers.find(b => (b.key || b.id) === brawlerKey);
      const fromLive = live.currentBrawler && liveBrawlers.find(b => b.id === live.currentBrawler);
      setBrawler(saved || fromLive || liveBrawlers[0]);
      return;
    }
    // After hydration only re-pick if the current brawler vanished from the roster.
    if (!brawler || !liveBrawlers.find(b => b.id === brawler.id)) {
      setBrawler(liveBrawlers[0]);
    }
  }, [liveBrawlers.length, live.currentBrawler, brawlerKey, brawlersLive.length]);
  // Persistence is handled explicitly inside openGoalFor (the only
  // user-driven entry point that changes brawler). Hydration uses setBrawler
  // directly without persisting, so the saved key never gets clobbered by an
  // internal placeholder.

  // Active mode persists by id — store the id, derive the object so reordering
  // GAME_MODES later doesn't break old saves.
  const [modeId, setModeId] = useLocalState('pyla.dash.modeId', GAME_MODES[0].id);
  const mode = GAME_MODES.find(m => m.id === modeId) || GAME_MODES[0];
  const setMode = (m) => {
    if (!m) return;
    const changed = m.id !== modeId;
    setModeId(m.id);
    if (changed) window.pylaToast?.(`${t('inst.toast.modeSet')}: ${m.name}`, { kind: 'info' });
    if (m.botConfig && window.PylaAPI) {
      window.PylaAPI.putConfig('bot', m.botConfig).catch(err =>
        console.warn('[mode] failed to push gamemode to bot:', err && err.message));
    }
  };
  // On first mount, push the persisted mode to bot_config so the bot doesn't
  // run on whatever was on disk last session (e.g. defaulted to showdown).
  const modePushed = useRef(false);
  useEffect(() => {
    if (modePushed.current) return;
    if (!mode || !mode.botConfig || !window.PylaAPI) return;
    modePushed.current = true;
    window.PylaAPI.putConfig('bot', mode.botConfig).catch(() => {});
  }, [mode]);
  // Farming goal — matches the legacy SelectBrawler flow:
  //   farmType: "trophies" | "wins"
  //   currentValue / target are for the picked brawler
  //   winStreak only matters for trophies mode
  const [farmType, setFarmType] = useLocalState('pyla.dash.farmType', 'trophies');
  const [currentValue, setCurrentValue] = useLocalState('pyla.dash.currentValue', 0);
  const [target, setTarget] = useLocalState('pyla.dash.target', 1000);
  const [winStreak, setWinStreak] = useLocalState('pyla.dash.winStreak', 0);
  const [autoPick, setAutoPick] = useLocalState('pyla.dash.autoPick', true);
  const [runForMinutes, setRunForMinutes] = useLocalState('pyla.dash.runForMinutes', 0);
  const logRef = useRef(null);

  // Multi-emulator broadcast: when at least one instance is selected here the
  // Dashboard "Start" button fans the same session out to /api/instances/start_all
  // instead of the in-process bot. Empty list keeps the legacy single-bot path.
  const [broadcastIds, setBroadcastIds] = useLocalState('pyla.dash.broadcastIds', []);
  // When ON, broadcast Start uses each instance's own saved session (set
  // through the Instances page). OFF (default) → all instances run the same
  // session that's currently configured on the Dashboard.
  const [usePerInstanceSession, setUsePerInstanceSession] = useLocalState('pyla.dash.perInstanceSession', false);
  const [instances, setInstances] = useState([]);
  useEffect(() => {
    let alive = true;
    const pull = async () => {
      try {
        const r = await window.PylaAPI.listInstances();
        if (alive) setInstances(r.instances || []);
      } catch (_) { /* ignore — instances tab still works */ }
    };
    pull();
    const id = setInterval(pull, 4000);
    return () => { alive = false; clearInterval(id); };
  }, []);
  const toggleBroadcast = (instId) => {
    const set = new Set(broadcastIds);
    set.has(instId) ? set.delete(instId) : set.add(instId);
    setBroadcastIds([...set]);
  };
  const stopAllInstances = async () => {
    try {
      await window.PylaAPI.stopAllInstances(broadcastIds.length ? broadcastIds : null);
      window.pylaToast?.(t('inst.toast.stopAll'), { kind: 'info' });
    } catch (e) {
      window.pylaToast?.(`${t('inst.toast.stopOk')}: ${e.message || e}`, { kind: 'warn' });
    }
  };

  // Session-goal popup — opens when the user clicks a brawler tile on the
  // Brawlers page. The dashboard no longer carries the goal form; instead
  // the modal owns it and acts on the freshly-selected brawler.
  const [goalOpen, setGoalOpen] = useState(false);

  // Brawl Stars API trophies — fetched once per session when the user first
  // opens the goal modal. Returns {brawler_key: int}. Silently empty if the
  // token isn't configured; the modal falls back to whatever the user typed.
  const [apiTrophies, setApiTrophies] = useState(null);
  const [apiTrophiesLoaded, setApiTrophiesLoaded] = useState(false);
  const ensureApiTrophies = React.useCallback(async () => {
    if (apiTrophiesLoaded) return apiTrophies;
    setApiTrophiesLoaded(true);
    try {
      const r = await window.PylaAPI.getBrawlStarsApiTrophies();
      const map = (r && r.trophies) || {};
      setApiTrophies(map);
      return map;
    } catch (_) {
      setApiTrophies({});
      return {};
    }
  }, [apiTrophiesLoaded, apiTrophies]);

  // Whether the last currentValue set into the modal came from the API —
  // drives the hint under the Current Trophies input.
  const [trophiesFromApi, setTrophiesFromApi] = useState(false);

  // Push All flow — sets one common goal across every brawler under that
  // threshold via a dedicated backend endpoint that builds the payload and
  // starts the bot in one shot. Independent from per-brawler target.
  const [pushAll, setPushAll] = useState({ busy:false, status:'', detail:'' });
  const [pushAllTarget, setPushAllTarget] = useLocalState('pyla.dash.pushAllTarget', '1000');
  const runPushAll = async () => {
    const target = parseInt(pushAllTarget, 10) || 0;
    if (pushAll.busy || state !== 'idle' || target <= 0) return;
    setPushAll({ busy:true, status:'loading', detail: t('dash.pushAllStarting') });
    try {
      const r = await window.PylaAPI.pushAll(target);
      const n = r && r.count ? r.count : 0;
      setPushAll({ busy:false, status:'ok', detail: t('dash.pushAllOk').replace('{n}', n) });
      setQueue([]);
    } catch (e) {
      setPushAll({ busy:false, status:'fail',
                   detail: t('dash.pushAllFail').replace('{err}', e.message || String(e)) });
    }
  };

  // Multi-brawler queue — original bot already supports this via
  // stage_manager.brawlers_pick_data (pops the first entry once its target
  // is reached). Queue entries carry display-only metadata (_meta) stripped
  // before sending to /api/start. Persisted in localStorage so the user can
  // configure across sessions.
  const [queue, setQueue] = useLocalState('pyla.queue', []);
  // Per-brawler goal memory so switching tiles restores the values the
  // user last set for that brawler instead of whatever was in the form.
  const [goalMemory, setGoalMemory] = useLocalState('pyla.dash.goalMemory', {});

  const openGoalFor = async (b) => {
    setBrawler(b);
    const key = b.key || b.id;
    if (key) setBrawlerKey(key);
    // First try the pending queue entry (most-recent config), then per-brawler
    // memory, then fall back to the generic form state.
    const queued = queue.find(q => q.brawler === key);
    const mem = goalMemory[key];
    setTrophiesFromApi(false);
    if (queued) {
      setFarmType(queued.type || 'trophies');
      setCurrentValue(queued.type === 'wins' ? (queued.wins || 0) : (queued.trophies || 0));
      setTarget(queued.push_until || 0);
      setWinStreak(queued.win_streak || 0);
      setAutoPick(queued.automatically_pick ?? true);
      setRunForMinutes(queued.run_for_minutes || 0);
    } else if (mem) {
      setFarmType(mem.farmType || 'trophies');
      setCurrentValue(mem.currentValue ?? 0);
      setTarget(mem.target ?? 1000);
      setWinStreak(mem.winStreak ?? 0);
      setAutoPick(mem.autoPick ?? true);
      setRunForMinutes(mem.runForMinutes ?? 0);
    } else {
      // No prior config — try to auto-fill Current Trophies from Brawl Stars
      // API. Desktop SelectBrawler does the same on brawler click.
      const map = await ensureApiTrophies();
      if (map && map[key] != null) {
        setFarmType('trophies');
        setCurrentValue(map[key]);
        setTrophiesFromApi(true);
      }
    }
    setGoalOpen(true);
  };

  // OCR-driven "Refresh info" button next to the goal inputs.
  const [scan, setScan] = useState({ busy:false, status:'', detail:'', debug:null });
  const refreshFromScreen = async () => {
    if (scan.busy || !brawler) return;
    setScan({ busy:true, status:'', detail:'', debug:null });
    try {
      const r = await window.PylaAPI.scanBrawler(brawler.key || brawler.id);
      const m = r && r.match;
      if (m && (m.trophies != null || m.streak != null)) {
        if (m.trophies != null) setCurrentValue(m.trophies);
        if (m.streak != null)   setWinStreak(m.streak);
        setScan({ busy:false, status:'ok',
                  detail: `${m.name} · 🏆${m.trophies ?? '?'} · 🔥${m.streak ?? 0}`, debug:null });
      } else {
        // Surface what OCR did pick up so we can see why the match missed.
        const tiles = (r && r.tiles) || [];
        const matched = tiles.filter(t => t.matched_known).map(t => t.name).slice(0, 6);
        const raw = (r && r.raw_text) ? r.raw_text.slice(0, 12).join(' · ') : '';
        const detail = matched.length
          ? `${t('dash.scanMiss') || 'Brawler not found'}. Найдено: ${matched.join(', ')}`
          : (t('dash.scanMiss') || 'Brawler not found') + '. OCR не распознал имена.';
        setScan({ busy:false, status:'miss', detail, debug: raw });
      }
    } catch (e) {
      setScan({ busy:false, status:'fail', detail: e.message || String(e), debug:null });
    }
  };

  const state = live.status === 'running' || live.status === 'starting' ? 'running'
              : live.status === 'paused' ? 'paused'
              : live.status === 'error' ? 'error'
              : 'idle';

  const logs = live.logs.length ? live.logs : LOG_LINES.slice(0, 12);
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);

  const sStats = live.stats || {};
  const games = sStats.games || 0;
  const wins = sStats.wins || 0;
  const losses = sStats.losses || Math.max(games - wins, 0);
  const winRate = games > 0 ? Math.round(wins / games * 100) : 0;
  // Avg match duration over the current session: pull every match logged
  // since started_at that has a duration_s recorded, average it. Falls back
  // to '—' when nothing's been timed yet (older entries lack duration_s).
  const avgMatchLabel = (() => {
    const startTs = sStats.started_at;
    if (!startTs) return '—';
    const entries = (matchHistory.entries || []).filter(e =>
      e && e.ts != null && e.ts >= startTs && Number.isFinite(e.duration_s) && e.duration_s > 0);
    if (!entries.length) return '—';
    const avg = entries.reduce((a, e) => a + e.duration_s, 0) / entries.length;
    const m = Math.floor(avg / 60);
    const s = Math.round(avg % 60);
    return m > 0 ? `${m}m ${String(s).padStart(2,'0')}s` : `${s}s`;
  })();

  // ETA to goal — uses the running-session trophy/win curve to project
  // time-remaining. Null/empty when not running or when we lack signal.
  const etaCurveTs  = sStats.trophy_curve_ts  || sStats.curve_ts  || null;
  const etaCurveVal = farmType === 'trophies'
    ? (sStats.trophy_curve || null)
    : (sStats.wins_curve || null);
  const eta = useEtaToGoal({
    startedAt: (state === 'running' || state === 'paused') ? sStats.started_at : null,
    current: currentValue,
    target: target,
    ipsOrSpeed: live.ips,
    curveTs: etaCurveTs,
    curveVal: etaCurveVal,
  });

  // Fold aggregate metrics from every running instance subprocess into the
  // dashboard counters. When the legacy in-process bot AND instance bots are
  // running we sum both — the legacy figure is the source of truth for the
  // active foreground session, the instance figures cover the parallel
  // emulators driven from the broadcast panel.
  const aggTotals = (instAgg && instAgg.totals) || null;
  const aggBattles = aggTotals ? aggTotals.battles : 0;
  const aggWins = aggTotals ? aggTotals.wins : 0;
  const aggLosses = aggTotals ? aggTotals.losses : 0;
  const aggDelta = aggTotals ? aggTotals.trophies_delta : 0;
  const aggAvgSec = aggTotals && aggTotals.avg_match_sec ? aggTotals.avg_match_sec : null;
  const formatDuration = (sec) => {
    if (!sec || sec <= 0) return null;
    const m = Math.floor(sec / 60);
    const s = Math.round(sec % 60);
    return m > 0 ? `${m}m ${String(s).padStart(2,'0')}s` : `${s}s`;
  };
  const totalGames = games + aggBattles;
  const totalWins = wins + aggWins;
  const totalLosses = losses + aggLosses;
  const mergedWinRate = totalGames > 0 ? Math.round(totalWins / totalGames * 100) : winRate;
  const mergedNet = (sStats.net_trophies || 0) + aggDelta;
  // Prefer the per-match avg the legacy bot computed; fall back to instance
  // aggregate when the legacy session is empty (no in-process bot running).
  const mergedAvgMatch = avgMatchLabel !== '—'
    ? avgMatchLabel
    : (formatDuration(aggAvgSec) || '—');
  const sessionStats = {
    games: totalGames,
    wins: totalWins,
    losses: totalLosses,
    winRate: mergedWinRate,
    netTrophies: mergedNet,
    avgMatch: mergedAvgMatch,
    sessionTime: sStats.started_at ? (() => {
      const sec = Math.max(0, Math.floor(Date.now()/1000 - sStats.started_at));
      const h = Math.floor(sec/3600), m = Math.floor((sec%3600)/60);
      return `${h}h ${String(m).padStart(2,'0')}m`;
    })() : '—',
    instances_running: aggTotals ? aggTotals.instances_running : 0,
  };

  // Reflect live progress while the bot is actually running. When idle we
  // keep whatever the user typed (and what was restored from localStorage),
  // otherwise the snapshot's zero stats would clobber a saved goal.
  useEffect(() => {
    if (state !== 'running' && state !== 'paused') return;
    if (farmType === 'trophies' && sStats.trophies != null) setCurrentValue(sStats.trophies);
    if (farmType === 'wins' && sStats.wins != null) setCurrentValue(sStats.wins);
    if (sStats.win_streak != null) setWinStreak(sStats.win_streak);
  }, [sStats.trophies, sStats.wins, sStats.win_streak, farmType, state]);

  const targetNum  = parseInt(target, 10) || 0;
  const currentNum = parseInt(currentValue, 10) || 0;
  const curEntryValid = targetNum > 0 && currentNum < targetNum;
  const canStart   = state === 'idle' && (curEntryValid || queue.length > 0);
  const startHint  = state !== 'idle'
    ? ''
    : (queue.length === 0 && targetNum <= 0)
      ? (t('dash.hintTargetZero') || 'Укажите цель > 0')
      : (queue.length === 0 && currentNum >= targetNum)
        ? (t('dash.hintAlreadyReached') || 'Цель уже достигнута')
        : '';

  // Build the backend payload for the brawler currently loaded in the modal.
  const buildEntry = () => ({
    brawler: brawler.key || brawler.id,
    _meta: { name: brawler.name, icon_url: brawler.icon_url, color: brawler.color },
    type: farmType,
    push_until: targetNum,
    trophies: farmType === 'trophies' ? currentNum : 0,
    wins:     farmType === 'wins'     ? currentNum : 0,
    win_streak: parseInt(winStreak, 10) || 0,
    automatically_pick: autoPick,
    run_for_minutes: parseInt(runForMinutes, 10) || 0,
  });

  // Snapshot current goal form → per-brawler memory so switching tiles
  // preserves individual goals.
  const rememberGoal = (key) => {
    if (!key) return;
    setGoalMemory({
      ...goalMemory,
      [key]: { farmType, currentValue, target, winStreak, autoPick, runForMinutes },
    });
  };

  const addToQueue = () => {
    if (!brawler || !curEntryValid) return;
    const entry = buildEntry();
    const replaced = queue.some(q => q.brawler === entry.brawler);
    setQueue([...queue.filter(q => q.brawler !== entry.brawler), entry]);
    rememberGoal(entry.brawler);
    setGoalOpen(false);
    setTab('brawlers');  // let the user pick the next one
    window.pylaToast?.(
      replaced ? `${brawler.name} обновлён в очереди` : `${brawler.name} в очереди`,
      { kind: 'ok' }
    );
  };

  const removeFromQueue = (key) => {
    const item = queue.find(q => q.brawler === key);
    setQueue(queue.filter(q => q.brawler !== key));
    if (item) window.pylaToast?.(`${t('inst.toast.queueRemoved')}: ${item._meta?.name || key}`, { kind: 'info' });
  };
  const clearQueue = () => {
    if (queue.length) window.pylaToast?.(`${t('inst.toast.queueCleared')} (${queue.length})`, { kind: 'info' });
    setQueue([]);
  };

  const startSession = () => {
    if (!canStart) return;
    const entry = buildEntry();
    // If the current form has a valid goal, treat it as the primary brawler
    // and run the queue after it. Replace any queued entry for the same key.
    const combined = curEntryValid
      ? [entry, ...queue.filter(q => q.brawler !== entry.brawler)]
      : queue;
    if (!combined.length) return;
    if (curEntryValid) rememberGoal(entry.brawler);
    // Strip _meta before sending — Pydantic SessionConfig doesn't know it.
    const payload = combined.map(({ _meta, ...rest }) => rest);
    if (broadcastIds.length > 0) {
      // Multi-emulator broadcast — don't touch the in-process RUNNER, the bot
      // runs as one subprocess per selected instance. When the user opted into
      // per-instance saved sessions, send session=null so the backend loads
      // each instance's own brawler queue.
      const sessionPayload = usePerInstanceSession ? null : payload;
      window.PylaAPI.startAllInstances(sessionPayload, broadcastIds)
        .then(r => {
          const okN = (r.started || []).length;
          const skipN = (r.skipped || []).length;
          const errN = (r.errors || []).length;
          const note = usePerInstanceSession ? ' (own session)' : '';
          window.pylaToast?.(
            `${t('inst.toast.startBroadcast')}${note} ${okN}`
              + (skipN ? `, ${t('inst.toast.startSkipped')} ${skipN}` : '')
              + (errN ? `, ${t('inst.toast.startErrors')} ${errN}` : ''),
            { kind: errN ? 'warn' : 'ok', icon: '▶' }
          );
        })
        .catch(e => window.pylaToast?.(`${t('inst.toast.startBroadcast')}: ${e.message || e}`, { kind: 'warn' }));
      setQueue([]);
      return;
    }
    live.start(payload);
    setQueue([]);
    const noun = combined.length === 1
      ? t('inst.toast.brawler')
      : t('inst.toast.brawlersInQueue');
    window.pylaToast?.(`${t('inst.toast.singleStart')} · ${combined.length} ${noun}`, { kind: 'ok', icon: '▶' });
  };

  // Keyboard navigation — D/B/M/T/L/S switches tabs, ? opens help overlay.
  // Disabled while the goal modal is open so typing into its fields is safe.
  const { helpOpen, setHelpOpen } = useKeyboardNav(setTab, { isModalOpen: goalOpen });

  return (
    <div className="shell" data-theme={tweaks.theme} data-density={tweaks.density}>
      {/* ── Sidebar ─────────────────────────────────── */}
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
              <path d="M4 3v16M4 3h7c3 0 5 2 5 5s-2 5-5 5H4" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
              <circle cx="17" cy="17" r="2.5" fill="currentColor"/>
            </svg>
          </div>
          <div>
            <div className="brand-name">PylaAI</div>
            <div className="brand-sub">v0.6.5 · open</div>
          </div>
        </div>

        <nav className="nav">
          {[
            {id:'dashboard', k:'nav.dashboard', ic:<Icon.home/>},
            {id:'brawlers',  k:'nav.brawlers',  ic:<Icon.brawler/>},
            {id:'modes',     k:'nav.modes',     ic:<Icon.shield/>},
            {id:'instances', k:'nav.instances', ic:<Icon.chips/>},
            {id:'stats',     k:'nav.stats',     ic:<Icon.chart/>},
            {id:'logs',      k:'nav.logs',      ic:<Icon.log/>},
            {id:'settings',  k:'nav.settings',  ic:<Icon.gear/>},
          ].map(n => (
            <button key={n.id} className="nav-item" data-active={tab===n.id} onClick={()=>setTab(n.id)}>
              {n.ic}<span>{t(n.k)}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="device-card">
            <div className="device-row">
              <div className="device-dot" data-ok={live.device.connected ? true : undefined}/>
              <span>Device</span>
              <span className="device-id">{live.device.connected ? live.device.name : (t('status.idle') || 'offline')}</span>
            </div>
            <div className="device-row muted">
              <span>{live.ips ? `${Math.round(live.ips*10)/10} IPS` : '—'}</span>
            </div>
          </div>
        </div>
      </aside>

      {/* ── Main ───────────────────────────────────── */}
      <main className="main">
        {/* topbar */}
        <header className="topbar">
          <div className="breadcrumb">
            <span className="muted">PylaAI</span>
            <Icon.caret s={8}/>
            <span>{t('nav.' + tab)}</span>
          </div>
          <div className="topbar-actions">
            <div className="kbd-hint muted small">
              {live.device.connected ? live.device.name : '—'} · {live.ips ? `${live.ips} IPS` : ''}
            </div>
            <button className="kbd-shortcut-hint" onClick={() => setHelpOpen(true)}
                    title={t('topbar.shortcuts')} aria-label={t('topbar.shortcuts')}>
              ?
            </button>
            <div className="lang-toggle">
              {['ru','en'].map(l => (
                <button key={l} className="lang-btn" data-on={lang===l} onClick={()=>setLang(l)}
                        aria-label={l.toUpperCase()}>{l.toUpperCase()}</button>
              ))}
            </div>
            <StatusTicker
              state={state}
              ips={live.ips}
              netTrophies={sStats.net_trophies || 0}
              wins={sStats.wins || 0}
              games={sStats.games || 0}
              winStreak={sStats.win_streak || 0}
            />
            <StatusPill state={state}/>
          </div>
        </header>

        {tab === 'stats' && <StatsPage brawler={brawler} mode={mode}/>}
        {tab === 'settings' && <SettingsPage/>}
        {tab === 'brawlers' && <BrawlersPage brawler={brawler} setBrawler={openGoalFor}/>}
        {tab === 'modes' && <ModesPage mode={mode} setMode={setMode}/>}
        {tab === 'instances' && <InstancesPage/>}
        {tab === 'logs' && <LogsPage/>}

        {tab === 'dashboard' && <>
        {/* Hero control band */}
        <section className="hero">
          <div className="hero-left">
            <div className="hero-meta">
              <span className="badge subtle">{brawler.name}</span>
              <span className="badge subtle" style={{borderLeft:`3px solid ${mode.color || 'var(--accent)'}`}}>
                {mode.name}
              </span>
              <span className="badge">
                {t(farmType === 'trophies' ? 'dash.goalTrophies' : 'dash.goalWins')}: {currentValue} → {target}
              </span>
              {farmType === 'trophies' && <span className="badge subtle">{t('dash.winStreak')}: {winStreak}</span>}
              {autoPick && <span className="badge subtle">{t('dash.autoPick')}</span>}
              <EtaChip eta={eta}/>
            </div>
            <h1 className="hero-title">
              {state === 'running' ? t('dash.runningTitle')
                : state === 'paused'  ? t('dash.pausedTitle')
                : t('dash.readyTitle')}
            </h1>
            <div className="hero-sub">
              {state === 'running'
                ? <><b>{brawler.name}</b> · <b>{sStats.trophies || 0} 🏆</b> · {t('dash.session')} <b>{(sStats.net_trophies||0) >= 0 ? '+' : ''}{sStats.net_trophies || 0}</b></>
                : <>{t('dash.brawler')}: <b>{brawler.name}</b> · {t('dash.target')} <b>{target}</b></>}
            </div>
            {instances.length > 0 && (
              <div className="run-on-panel">
                <div className="run-on-head">
                  <span className="run-on-label"><Icon.chips s={12}/> {t('inst.runOn.label')}</span>
                  <div className="run-on-chips">
                    {instances.map(inst => {
                      const on = broadcastIds.includes(inst.id);
                      const running = ['running','starting','stale'].includes(inst.status);
                      const dot = running ? '#5be37c' : (inst.status === 'crashed' ? '#e6605b' : '#7d7777');
                      return (
                        <button key={inst.id}
                                className={`chip run-on-chip ${on ? 'on' : ''}`}
                                onClick={() => toggleBroadcast(inst.id)}
                                title={`${inst.emulator}${inst.port ? ':'+inst.port : ''} · ${inst.status}`}>
                          <span className="run-on-dot" style={{background:dot}}/>
                          <span className="run-on-chip-id">#{inst.id}</span>
                          <span className="run-on-chip-name">{inst.name}</span>
                        </button>
                      );
                    })}
                    {broadcastIds.length > 0 && (
                      <button className="chip run-on-clear" onClick={() => setBroadcastIds([])} title={t('common.clear') || 'clear'}>× {t('inst.runOn.clear')}</button>
                    )}
                  </div>
                  {broadcastIds.length > 0 && (
                    <button className="btn xs run-on-stop" onClick={stopAllInstances}>
                      <Icon.stop s={11}/> {t('inst.runOn.stopSelected')}
                    </button>
                  )}
                </div>
                {broadcastIds.length > 0 ? (
                  <div className="run-on-foot">
                    <label className="switch">
                      <input type="checkbox" checked={usePerInstanceSession}
                             onChange={e => setUsePerInstanceSession(e.target.checked)}/>
                      <span className="switch-track"><span className="switch-dot"/></span>
                      <span className="switch-label">{t('inst.runOn.perInstance')}</span>
                    </label>
                    <span className="muted small run-on-summary">
                      {usePerInstanceSession
                        ? <><b>{broadcastIds.length}</b>: {t('inst.runOn.hintOwn')}</>
                        : <><b>{broadcastIds.length}</b>: {t('inst.runOn.hintShared')}</>}
                    </span>
                  </div>
                ) : (
                  <div className="run-on-foot muted small">
                    {t('inst.runOn.hintEmpty')}
                  </div>
                )}
              </div>
            )}
            <div className="hero-controls">
              {state === 'idle' && (
                <button className="btn primary big" onClick={startSession} disabled={!canStart} title={startHint}>
                  <Icon.play s={14}/>
                  {broadcastIds.length > 0 ? ` Старт на ${broadcastIds.length} эмулятор(ов)` : ` ${t('dash.startSession')}`}
                  {(queue.length + (curEntryValid ? 1 : 0)) > 1 &&
                    <span className="badge subtle" style={{marginLeft:6}}>{queue.length + (curEntryValid ? 1 : 0)}</span>}
                </button>
              )}
              {state === 'idle' && (
                <div className="push-all-group" style={{display:'inline-flex', alignItems:'center', gap:6}}>
                  <button className="btn big" onClick={runPushAll}
                          disabled={pushAll.busy || (parseInt(pushAllTarget,10)||0) <= 0}
                          title={t('dash.pushAllHint')}>
                    <Icon.trophy s={14}/> {pushAll.busy ? t('dash.pushAllStarting') : t('dash.pushAll')}
                  </button>
                  <input type="number" min="0" step="100"
                         className="input"
                         style={{width:90}}
                         value={pushAllTarget}
                         onChange={e => setPushAllTarget(e.target.value.replace(/[^\d]/g,''))}
                         disabled={pushAll.busy}
                         placeholder="1000"
                         title={t('dash.pushAllTargetHint')}
                         aria-label={t('dash.pushAllTargetLabel')} />
                  <span className="muted small">🏆</span>
                </div>
              )}
              {state === 'idle' && pushAll.detail && (
                <span className="muted small"
                      style={{color: pushAll.status === 'fail' ? '#F87171'
                                   : pushAll.status === 'ok'   ? '#34D399' : undefined}}>
                  {pushAll.detail}
                </span>
              )}
              {state === 'idle' && startHint && !pushAll.detail && (
                <span className="muted small" style={{color:'#F87171'}}>{startHint}</span>
              )}
              {state === 'running' && <>
                <button className="btn big" onClick={live.pause}><Icon.pause s={14}/> {t('common.pause')}</button>
                <button className="btn danger big" onClick={live.stop}><Icon.stop s={14}/> {t('common.stop')}</button>
              </>}
              {state === 'paused' && <>
                <button className="btn primary big" onClick={live.resume}><Icon.play s={14}/> {t('common.resume')}</button>
                <button className="btn big" onClick={live.stop}><Icon.stop s={14}/> {t('common.stop')}</button>
              </>}
              <div className="spacer" />
              <label className="switch">
                <input type="checkbox" checked={autoPick} onChange={e=>setAutoPick(e.target.checked)}/>
                <span className="switch-track"><span className="switch-dot"/></span>
                <span className="switch-label">{t('dash.autoPick')}</span>
              </label>
            </div>
          </div>
          <div className="hero-right">
            <GameViewport running={state==='running'} mode={mode} brawler={brawler}/>
          </div>
        </section>

        {/* Main grid */}
        <section className="grid">

          {/* Trophy chart */}
          <div className="card span-2">
            <SectionHead
              icon={<Icon.trophy s={14}/>}
              title={t('dash.trophyTrend')}
            />
            <div className="trophy-band">
              <div>
                <div className="big-num">
                  {sStats.net_trophies > 0 ? '+' : ''}{sStats.net_trophies || 0}
                  <span className="trophy">🏆</span>
                </div>
                <div className="muted small">{t('dash.session')}</div>
              </div>
              <div className="tiny-stats">
                <div><span className="muted">{t('dash.games')}</span> <b>{sStats.games || 0}</b></div>
                <div><span className="muted">{t('dash.wins')}</span> <b className="pos">{sStats.wins || 0}</b></div>
                <div><span className="muted">{t('dash.losses')}</span> <b>{sStats.losses || 0}</b></div>
                <div><span className="muted">{t('dash.current')}</span> <b>{sStats.trophies || 0}</b></div>
              </div>
            </div>
            {sStats.trophy_curve && sStats.trophy_curve.length > 1
              ? <TrophyChart data={sStats.trophy_curve} tier={null}/>
              : <div className="muted" style={{textAlign:'center', padding:'24px 8px', fontSize:13}}>
                  {t('common.noData') || 'Нет данных'}
                </div>}
            {/* Per-instance trophy deltas — overlay strip below the legacy curve.
                Each running instance shows its delta since session start in its
                own color so multi-emulator progress is legible at a glance. */}
            {(instAgg.instances || []).filter(i => i && i.trophies_delta != null).length > 0 && (
              <div className="row-gap" style={{flexWrap: 'wrap', gap: 6, padding: '8px 4px 0', borderTop: '1px solid rgba(255,255,255,0.06)', marginTop: 6}}>
                {(instAgg.instances || []).map(i => {
                  if (!i) return null;
                  const delta = i.trophies_delta || 0;
                  const color = (i.status === 'running' || i.status === 'starting' || i.status === 'stale')
                    ? 'var(--accent)' : 'var(--muted)';
                  const sign = delta > 0 ? '+' : '';
                  return (
                    <div key={i.id} title={`${i.name} · ${i.current_brawler || '—'}`}
                         style={{
                           display:'inline-flex', alignItems:'center', gap: 4,
                           padding:'2px 8px', borderRadius: 999,
                           background:'rgba(248,183,51,0.08)',
                           fontSize: 11,
                         }}>
                      <span style={{
                        width: 6, height: 6, borderRadius: '50%', background: color,
                        boxShadow: `0 0 6px ${color}`,
                      }}/>
                      <span style={{opacity: 0.7}}>#{i.id}</span>
                      <strong style={{color: delta > 0 ? '#34D399' : delta < 0 ? '#F87171' : 'var(--fg)'}}>
                        {sign}{delta}
                      </strong>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Session stats */}
          <div className="card">
            <SectionHead icon={<Icon.chart s={14}/>} title={t('dash.sessionHeader')}
              right={
                <span className="muted small">
                  {sessionStats.sessionTime}
                  {sessionStats.instances_running > 0 && (
                    <span style={{marginLeft: 8, color: 'var(--accent)'}}>
                      · +{sessionStats.instances_running}
                    </span>
                  )}
                </span>
              }/>
            <div className="stats-grid">
              <Stat label={t('dash.games')}  value={sessionStats.games}/>
              <Stat label={t('dash.wins')}   value={sessionStats.wins}   accent="#34D399"/>
              <Stat label={t('dash.losses')} value={sessionStats.losses} accent="#F87171"/>
              <Stat label={t('dash.winRate')}  value={`${sessionStats.winRate}%`}/>
              <Stat label={t('dash.netTrophies')} value={`${sessionStats.netTrophies >= 0 ? '+' : ''}${sessionStats.netTrophies}`} accent="#F8B733"/>
              <Stat label={t('dash.avgMatch')} value={sessionStats.avgMatch}/>
            </div>
          </div>

          {/* Queue — pending brawlers to run after the active one */}
          {queue.length > 0 && (
            <div className="card span-3">
              <SectionHead
                icon={<Icon.brawler s={14}/>}
                title={`${t('dash.queueHeader') || 'Очередь'} · ${queue.length}`}
                right={
                  <button className="btn ghost xs" onClick={clearQueue}>
                    {t('common.clear') || 'Clear'}
                  </button>
                }
              />
              <div className="queue-list">
                {queue.map((q) => (
                  <div key={q.brawler} className="queue-item">
                    <div className="brawler-avatar"
                         style={{background:`linear-gradient(135deg, ${q._meta?.color || '#F8B733'}, ${q._meta?.color || '#F8B733'}cc)`, width:32, height:32, fontSize:11}}>
                      {q._meta?.icon_url
                        ? <img src={q._meta.icon_url} alt="" style={{width:'100%',height:'100%',objectFit:'cover',borderRadius:'inherit'}}/>
                        : <span>{(q._meta?.name || q.brawler || '?').charAt(0)}</span>}
                    </div>
                    <div className="queue-meta">
                      <div className="queue-name">{q._meta?.name || q.brawler}</div>
                      <div className="muted small">
                        {q.type === 'wins' ? q.wins : q.trophies} → {q.push_until}
                        {q.type === 'trophies' && q.win_streak > 0 && ` · 🔥${q.win_streak}`}
                      </div>
                    </div>
                    <button className="btn ghost xs" onClick={() => removeFromQueue(q.brawler)} title={t('common.remove') || 'Remove'}>×</button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Live log */}
          <div className="card span-3">
            <SectionHead
              icon={<Icon.log s={14}/>}
              title={t('dash.liveLog')}
              right={
                <button className="btn ghost xs" onClick={() => setTab('logs')}>
                  {t('dash.openLogs')}
                </button>
              }
            />
            <div className="log" ref={logRef}>
              {logs.map((l,i)=> <LogLine key={i} line={l}/>)}
              {state==='running' && <div className="log-caret">▍</div>}
            </div>
          </div>

        </section>
        </>}

        <footer className="foot">
          <span>PylaAI · open-source Brawl Stars automation</span>
          <span className="muted">This interface is a UX concept; use responsibly.</span>
        </footer>
      </main>

      {goalOpen && (
        <SessionGoalModal
          brawler={brawler}
          state={state}
          farmType={farmType} setFarmType={setFarmType}
          currentValue={currentValue}
          setCurrentValue={(v) => { setCurrentValue(v); setTrophiesFromApi(false); }}
          target={target} setTarget={setTarget}
          winStreak={winStreak} setWinStreak={setWinStreak}
          autoPick={autoPick} setAutoPick={setAutoPick}
          runForMinutes={runForMinutes} setRunForMinutes={setRunForMinutes}
          scan={scan} refreshFromScreen={refreshFromScreen}
          trophiesFromApi={trophiesFromApi}
          canStart={canStart} startHint={startHint}
          queueSize={queue.length}
          curEntryValid={curEntryValid}
          onQueue={addToQueue}
          onStart={() => { startSession(); setGoalOpen(false); setTab('dashboard'); }}
          onClose={() => setGoalOpen(false)}
        />
      )}

      <KeyboardHelp open={helpOpen} onClose={() => setHelpOpen(false)}/>
    </div>
  );
}

// ── Session-goal popup ────────────────────────────────────────────
// Form for a single brawler: farm trophies/wins, current/target values,
// win streak (trophy mode only), session duration, auto-pick toggle.
// Includes the OCR "Refresh from screen" shortcut and the Start button.
function SessionGoalModal({
  brawler, state,
  farmType, setFarmType, currentValue, setCurrentValue,
  target, setTarget, winStreak, setWinStreak,
  autoPick, setAutoPick, runForMinutes, setRunForMinutes,
  scan, refreshFromScreen, trophiesFromApi, canStart, startHint,
  queueSize, curEntryValid, onQueue, onStart, onClose,
}) {
  // Esc closes. Click on backdrop closes. Click inside panel doesn't.
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <div className="row-gap" style={{alignItems:'center'}}>
            <div className="brawler-avatar"
                 style={{background:`linear-gradient(135deg, ${brawler.color}, ${brawler.color}cc)`,
                         width:42, height:42}}>
              {brawler.icon_url
                ? <img src={brawler.icon_url} alt="" style={{width:'100%',height:'100%',objectFit:'cover',borderRadius:'inherit'}}/>
                : <span style={{fontSize:18, fontWeight:700}}>{brawler.icon}</span>}
            </div>
            <div>
              <div style={{fontWeight:600, fontSize:15}}>{brawler.name}</div>
              <div className="muted small">{t('dash.goalTitle')}</div>
            </div>
          </div>
          <button className="btn ghost xs" onClick={onClose}>×</button>
        </div>

        <div className="modal-body">
          <div className="row-gap" style={{justifyContent:'flex-end', marginBottom:10}}>
            <button className="btn ghost xs" onClick={refreshFromScreen}
                    disabled={scan.busy || state !== 'idle'}
                    title={state !== 'idle' ? (t('dash.scanWhileRunning') || '') : ''}>
              <Icon.refresh s={12}/> {scan.busy ? (t('dash.scanning') || 'Reading…') : (t('dash.refreshInfo') || 'Refresh')}
            </button>
          </div>
          {scan.detail && (
            <div className="muted small" style={{marginBottom:8, color: scan.status==='fail' ? '#F87171' : scan.status==='miss' ? '#F8B733' : undefined}}>
              {scan.detail}
              {scan.debug && <div style={{marginTop:4, opacity:.7, fontSize:11}}>OCR: {scan.debug}</div>}
            </div>
          )}

          <div className="seg" style={{width:'100%', marginBottom:12}}>
            <button className="seg-btn" data-on={farmType==='trophies'} onClick={()=>setFarmType('trophies')}>
              {t('dash.farmTrophies')}
            </button>
            <button className="seg-btn" data-on={farmType==='wins'} onClick={()=>setFarmType('wins')}>
              {t('dash.farmWins')}
            </button>
          </div>

          <div className="form-row">
            <label className="form-label">
              {farmType === 'trophies' ? t('dash.currentTrophies') : t('dash.currentWins')}
            </label>
            <input className="input" type="number" min="0" inputMode="numeric"
                   value={currentValue}
                   onChange={e=>setCurrentValue(e.target.value === '' ? 0 : Math.max(0, parseInt(e.target.value, 10) || 0))}/>
          </div>
          {trophiesFromApi && farmType === 'trophies' && (
            <div className="muted small" style={{marginTop:-4, marginBottom:8, color:'#34D399'}}>
              {t('dash.trophiesFromApi')}
            </div>
          )}

          <div className="form-row">
            <label className="form-label">{t('dash.target')}</label>
            <input className="input" type="number" min="0" inputMode="numeric"
                   value={target}
                   onChange={e=>setTarget(e.target.value === '' ? 0 : Math.max(0, parseInt(e.target.value, 10) || 0))}/>
          </div>

          {farmType === 'trophies' && (
            <div className="form-row">
              <label className="form-label">{t('dash.winStreak')}</label>
              <input className="input" type="number" min="0" inputMode="numeric"
                     value={winStreak}
                     onChange={e=>setWinStreak(e.target.value === '' ? 0 : Math.max(0, parseInt(e.target.value, 10) || 0))}/>
            </div>
          )}

          <div className="form-row">
            <label className="form-label">{t('dash.runForMinutes')}</label>
            <input className="input" type="number" min="0" inputMode="numeric"
                   value={runForMinutes}
                   onChange={e=>setRunForMinutes(e.target.value === '' ? 0 : Math.max(0, parseInt(e.target.value, 10) || 0))}/>
          </div>
          <div className="muted small" style={{marginTop:6, marginBottom:12}}>{t('dash.runForHint')}</div>

          <label className="switch" style={{marginTop:4}}>
            <input type="checkbox" checked={autoPick} onChange={e=>setAutoPick(e.target.checked)}/>
            <span className="switch-track"><span className="switch-dot"/></span>
            <span className="switch-label">{t('dash.autoPick')}</span>
          </label>
        </div>

        <div className="modal-foot">
          {state === 'idle' && startHint && (
            <span className="muted small" style={{color:'#F87171', flex:1}}>{startHint}</span>
          )}
          {state === 'idle' && !startHint && queueSize > 0 && (
            <span className="muted small" style={{flex:1}}>
              {(t('dash.queueHint') || 'В очереди: ')}{queueSize}
            </span>
          )}
          <button className="btn ghost" onClick={onClose}>{t('common.discard') || 'Cancel'}</button>
          <button className="btn ghost" onClick={onQueue}
                  disabled={state !== 'idle' || !curEntryValid}
                  title={!curEntryValid ? (t('dash.hintTargetZero') || '') : ''}>
            <Icon.plus s={12}/> {t('dash.addToQueue') || 'Add to queue'}
          </button>
          <button className="btn primary" onClick={onStart}
                  disabled={state !== 'idle' || !canStart} title={startHint}>
            <Icon.play s={12}/> {t('dash.startSession')}
            {(queueSize + (curEntryValid ? 1 : 0)) > 1 &&
              <span className="badge subtle" style={{marginLeft:6}}>{queueSize + (curEntryValid ? 1 : 0)}</span>}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Tweaks panel ─────────────────────────────────────────────────
function TweaksPanel({ tweaks, setTweaks }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const handler = (e) => {
      if (e.data?.type === '__activate_edit_mode') setOpen(true);
      if (e.data?.type === '__deactivate_edit_mode') setOpen(false);
    };
    window.addEventListener('message', handler);
    window.parent.postMessage({ type: '__edit_mode_available' }, '*');
    return () => window.removeEventListener('message', handler);
  }, []);

  const update = (k, v) => {
    setTweaks({ ...tweaks, [k]: v });
    window.parent.postMessage({ type:'__edit_mode_set_keys', edits:{ [k]: v } }, '*');
  };

  if (!open) return null;

  return (
    <div className="tweaks">
      <div className="tweaks-head">
        <b>Tweaks</b>
        <button className="btn ghost xs" onClick={()=>setOpen(false)}>×</button>
      </div>
      <div className="tweak">
        <label>Theme</label>
        <div className="seg">
          {['neo','arcade','mono'].map(t =>
            <button key={t} className="seg-btn" data-on={tweaks.theme===t} onClick={()=>update('theme',t)}>{t}</button>
          )}
        </div>
      </div>
      <div className="tweak">
        <label>Accent</label>
        <div className="swatches">
          {['#F8B733','#7C5CFF','#34D399','#F472B6','#5B8DEF'].map(c =>
            <button key={c} className="sw" data-on={tweaks.accent===c}
              style={{background:c}} onClick={()=>update('accent',c)}/>
          )}
        </div>
      </div>
      <div className="tweak">
        <label>Density</label>
        <div className="seg">
          {['cozy','compact'].map(d =>
            <button key={d} className="seg-btn" data-on={tweaks.density===d} onClick={()=>update('density',d)}>{d}</button>
          )}
        </div>
      </div>
      <div className="tweak">
        <label>Corner radius</label>
        <input type="range" min="4" max="22" value={tweaks.radius}
          onChange={e=>update('radius',+e.target.value)}/>
        <span className="muted small">{tweaks.radius}px</span>
      </div>
    </div>
  );
}

// ── Root ─────────────────────────────────────────────────────────
function Root() {
  const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
    "theme": "neo",
    "accent": "#F8B733",
    "density": "cozy",
    "radius": 12
  }/*EDITMODE-END*/;
  const [tweaks, setTweaks] = useLocalState('pyla.tweaks', TWEAK_DEFAULTS);

  // apply tweaks to CSS vars
  useEffect(() => {
    document.documentElement.style.setProperty('--accent', tweaks.accent);
    document.documentElement.style.setProperty('--r', tweaks.radius + 'px');
  }, [tweaks]);

  return <>
    <App tweaks={tweaks}/>
    <TweaksPanel tweaks={tweaks} setTweaks={setTweaks}/>
    <ToastHost/>
  </>;
}

ReactDOM.createRoot(document.getElementById('root')).render(<Root/>);
