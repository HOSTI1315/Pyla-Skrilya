// PylaAI — Brawlers, Modes, Logs pages

const { useState: useS2, useMemo: useM2 } = React;

// ── Brawlers page ──────────────────────────────────────────────
function BrawlersPage({ brawler, setBrawler }) {
  const [rarity, setRarity] = useS2('all');
  const [sort, setSort] = useS2('trophies');
  const [search, setSearch] = useS2('');
  const [scanState, setScanState] = useS2({ busy: false, msg: null, error: null });
  // Account selector — null/0 = global aggregate, N = specific instance.
  // Persists so user's choice survives nav between pages.
  const [accountId, setAccountId] = useLocalState('pyla.brawlers.accountId', 0);
  const [accounts, setAccounts] = useS2([]);
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
  const liveList = (typeof useLiveBrawlers === 'function')
    ? useLiveBrawlers(+accountId || null)
    : [];
  const source = liveList.length ? liveList : BRAWLERS;

  const scanAll = async () => {
    if (scanState.busy) return;
    setScanState({ busy: true, msg: t('brawlers.scanRunning'), error: null });
    try {
      const r = await window.PylaAPI.syncAllFromBsApi();
      const tmpl = t('brawlers.scanDone');
      const msg = tmpl.replace('{n}', r.count).replace('{s}', r.duration);
      setScanState({ busy: false, msg, error: null });
      if (typeof liveList.refresh === 'function') liveList.refresh();
    } catch (e) {
      setScanState({ busy: false, msg: null, error: e.message || String(e) });
    }
  };

  const filtered = useM2(() => {
    let list = [...source];
    if (rarity !== 'all') list = list.filter(b => b.rarity === rarity);
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(b =>
        (b.name || '').toLowerCase().includes(q) ||
        (b.name_en || '').toLowerCase().includes(q) ||
        (b.key || b.id || '').toLowerCase().includes(q)
      );
    }
    if (sort === 'trophies') list.sort((a,b)=>b.trophies-a.trophies);
    if (sort === 'wr') list.sort((a,b)=>b.wr-a.wr);
    if (sort === 'name') list.sort((a,b)=>(a.name||'').localeCompare(b.name||''));
    return list;
  }, [rarity, sort, search, source.length]);

  const rarities = ['all', ...new Set(source.map(b=>b.rarity))];
  const inRange = source.filter(b => b.trophies >= 300 && b.trophies <= 400).length;
  // Average WR over brawlers that actually have games — including 0-game
  // brawlers as "0%" used to dilute the average towards zero.
  const played = source.filter(b => (b.games || 0) > 0);
  const avgWR = played.length ? Math.round(played.reduce((a,b)=>a+(b.wr||0),0) / played.length) : 0;

  return (
    <div className="stats-page">
      <div className="kpi-row">
        <KPI label={t('brawlers.total')}      value={source.length} sub="" accent="var(--fg)"/>
        <KPI label={t('brawlers.inRange')}    value={inRange} sub="300–400 🏆" accent="var(--accent)"/>
        <KPI label={t('brawlers.avgWR')}      value={`${avgWR}%`} sub="" accent="#34D399"/>
        <KPI label={t('brawlers.activePick')} value={brawler.name} sub={`${brawler.trophies||0} 🏆`} accent="var(--fg)"/>
      </div>

      <div className="card">
        <SectionHead
          icon={<Icon.brawler s={14}/>}
          title={t('brawlers.roster')}
          right={
            <div className="row-gap">
              {accounts.length > 0 && (
                <select className="input" style={{width: 200}}
                        value={String(accountId)}
                        onChange={e => setAccountId(parseInt(e.target.value, 10) || 0)}
                        title={t('brawlers.accountSelectorHint')}>
                  <option value="0">{t('brawlers.accountAll')}</option>
                  {accounts.map(a =>
                    <option key={a.id} value={String(a.id)}>#{a.id} {a.name}</option>
                  )}
                </select>
              )}
              <button className="btn ghost" onClick={scanAll} disabled={scanState.busy}>
                {scanState.busy ? t('brawlers.scanning') : t('brawlers.scanAll')}
              </button>
              <input className="input" style={{width:180}} placeholder={t('common.search')}
                     value={search} onChange={e=>setSearch(e.target.value)}/>
              <div className="seg">
                {rarities.map(r =>
                  <button key={r} className="seg-btn" data-on={rarity===r} onClick={()=>setRarity(r)}>
                    {r === 'all' ? t('common.all') : r}
                  </button>)}
              </div>
              <div className="seg">
                {[['trophies',t('brawlers.sortTrophies')],['wr',t('brawlers.sortWR')],['name',t('brawlers.sortName')]].map(([v,l]) =>
                  <button key={v} className="seg-btn" data-on={sort===v} onClick={()=>setSort(v)}>{l}</button>)}
              </div>
            </div>
          }
        />
        {(scanState.msg || scanState.error) && (
          <div className="muted small" style={{padding:'4px 12px 8px', color: scanState.error ? '#F87171' : 'var(--muted)'}}>
            {scanState.error ? `⚠ ${scanState.error}` : scanState.msg}
          </div>
        )}
        <div className="roster-grid">
          {source.length === 0 && Array.from({length: 8}).map((_, i) => (
            <BrawlerSkeleton key={`sk-${i}`}/>
          ))}
          {filtered.map(b => (
            <button key={b.id} className="roster-card" data-selected={b.id===brawler.id}
                    onClick={()=>setBrawler(b)}>
              <div className="roster-top">
                <div className="brawler-avatar" style={{background:`linear-gradient(135deg, ${b.color}, ${b.color}cc)`, width:44, height:44}}>
                  {b.icon_url
                    ? <img src={b.icon_url} alt="" style={{width:'100%',height:'100%',objectFit:'cover',borderRadius:'inherit'}}/>
                    : <span style={{fontSize:18, fontWeight:700}}>{b.icon}</span>}
                </div>
                <div className="rarity-chip" style={{background: RARITY_COLORS[b.rarity]}}>{b.rarity}</div>
              </div>
              <div className="roster-name">{b.name}</div>
              <div className="roster-stats-row">
                <div className="roster-stat">
                  <div className="muted small">{t('brawlers.trophies')}</div>
                  {(b.trophies || 0) > 0
                    ? <div className="roster-stat-v">{b.trophies}<span className="trophy">🏆</span></div>
                    : <div className="roster-stat-v" style={{color:'var(--muted)'}} title={t('common.noData') || 'no data'}>—</div>}
                </div>
                <div className="roster-stat">
                  <div className="muted small">{t('brawlers.winRate')}</div>
                  {(b.games || 0) > 0
                    ? <div className="roster-stat-v" style={{color: b.wr>=55?'#34D399':b.wr>=50?'var(--fg)':'#F87171'}}>{b.wr}%</div>
                    : <div className="roster-stat-v" style={{color:'var(--muted)'}} title={t('common.noData') || 'no data'}>—</div>}
                </div>
              </div>
              <div className="mini-progress">
                <div className="mini-progress-bar" style={{width:`${Math.min((b.trophies||0)/600*100,100)}%`, background: b.color}}/>
              </div>
              {b.id===brawler.id && <div className="active-tag">{t('brawlers.active')}</div>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Modes page ─────────────────────────────────────────────────
function ModesPage({ mode, setMode }) {
  // Persist priority across sessions; reconcile with current GAME_MODES so
  // newly-added modes show up at the bottom and removed ids drop out silently.
  const [savedPriority, setSavedPriority] = useLocalState('pyla.modes.priority', GAME_MODES.map(m=>m.id));
  const validIds = GAME_MODES.map(m=>m.id);
  const validSet = new Set(validIds);
  const known = savedPriority.filter(id => validSet.has(id));
  const missing = validIds.filter(id => !known.includes(id));
  const priority = [...known, ...missing];
  const setPriority = setSavedPriority;
  const live = (typeof useLiveStats === 'function') ? useLiveStats() : null;
  const modePerf = (live && live.mode_performance) || [];
  const bestMode = modePerf.length ? modePerf[0] : null;

  const move = (id, dir) => {
    const idx = priority.indexOf(id);
    const next = idx + dir;
    if (next < 0 || next >= priority.length) return;
    const np = [...priority];
    [np[idx], np[next]] = [np[next], np[idx]];
    setPriority(np);
  };

  return (
    <div className="stats-page">
      <div className="grid">
        <div className="card span-2">
          <SectionHead icon={<Icon.shield s={14}/>} title={t('modes.active')}
            right={<span className="muted small">{t('modes.queueFirst')}</span>}/>
          <div className="mode-grid" style={{gridTemplateColumns:'repeat(3,1fr)'}}>
            {GAME_MODES.map(m =>
              <ModeCard key={m.id} m={m} selected={m.id===mode.id} onPick={setMode}/>
            )}
          </div>
        </div>

        <div className="card">
          <SectionHead icon={<Icon.chart s={14}/>} title={t('modes.best')}/>
          {bestMode ? (
            <div style={{textAlign:'center', padding:'16px 0'}}>
              <div style={{width:48, height:48, borderRadius:12, background:bestMode.color || 'var(--accent)',
                           margin:'0 auto 10px', boxShadow:'inset 0 -3px 0 rgba(0,0,0,0.3)'}}/>
              <div style={{fontWeight:600, fontSize:15}}>{bestMode.name}</div>
              <div className="muted small">{bestMode.games} games · {bestMode.wr}% WR</div>
            </div>
          ) : (
            <div className="muted" style={{textAlign:'center', padding:'28px 8px', fontSize:13}}>
              {t('common.noData') || 'Нет данных'}
            </div>
          )}
        </div>

        <div className="card span-3">
          <SectionHead
            icon={<Icon.bolt s={14}/>}
            title={t('modes.priority')}
            right={<span className="muted small">{t('modes.dragHint')}</span>}
          />
          <div className="priority-list">
            {priority.map((id, i) => {
              const m = GAME_MODES.find(x=>x.id===id);
              const perf = modePerf.find(p=>p.name===m.name);
              return (
                <div key={id} className="priority-row">
                  <div className="priority-num">{i+1}</div>
                  <div className="mode-badge" style={{background:m.color, width:24, height:24, borderRadius:6}}/>
                  <div style={{flex:1}}>
                    <div style={{fontWeight:600, fontSize:13}}>{m.name}</div>
                    <div className="muted small">{m.type}</div>
                  </div>
                  <div style={{textAlign:'right'}}>
                    <div className="small">{perf ? `${perf.games} games` : '—'}</div>
                    <div className="small" style={{color: perf ? (perf.wr>=55?'#34D399':perf.wr>=50?'var(--fg-2)':'#F87171') : 'var(--muted)'}}>
                      {perf ? `${perf.wr}% WR` : '—'}
                    </div>
                  </div>
                  <div className="row-gap" style={{marginLeft:12}}>
                    <button className="btn ghost xs" onClick={()=>move(id,-1)} disabled={i===0}>↑</button>
                    <button className="btn ghost xs" onClick={()=>move(id,1)} disabled={i===priority.length-1}>↓</button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Log stream page ────────────────────────────────────────────
function LogsPage() {
  const [filter, setFilter] = useS2('all');
  const [paused, setPaused] = useS2(false);
  const live = (typeof useLiveStream === 'function') ? useLiveStream() : null;
  const [frozen, setFrozen] = useS2([]);

  const lines = paused ? frozen : (live && live.logs && live.logs.length ? live.logs : []);
  const setLines = (fn) => setFrozen(typeof fn === 'function' ? fn(frozen) : fn);
  const logRef = React.useRef(null);

  React.useEffect(() => {
    if (paused && live && live.logs) {
      setFrozen(live.logs.slice(-200));
    }
  }, [paused]);

  React.useEffect(() => {
    if (logRef.current && !paused) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [lines, paused]);

  const filtered = filter === 'all' ? lines : lines.filter(l => l.lvl === filter);

  const exportLogs = () => {
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    const body = (filtered.length ? filtered : lines)
      .map(l => {
        const ts = l.ts || l.time || '';
        const lvl = (l.lvl || 'info').toUpperCase();
        const msg = l.msg || l.text || '';
        return `[${ts}] ${lvl.padEnd(6)} ${msg}`;
      })
      .join('\n');
    const blob = new Blob([body || '(empty)'], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `pyla-logs-${stamp}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const counts = {
    all: lines.length,
    info: lines.filter(l=>l.lvl==='info').length,
    action: lines.filter(l=>l.lvl==='action').length,
    warn: lines.filter(l=>l.lvl==='warn').length,
    ok: lines.filter(l=>l.lvl==='ok').length,
  };

  return (
    <div className="stats-page">
      <div className="card">
        <SectionHead
          icon={<Icon.log s={14}/>}
          title={t('logs.title')}
          right={
            <div className="row-gap">
              <button className="btn ghost xs" onClick={()=>setPaused(!paused)}>
                {paused ? <><Icon.play s={12}/> {t('common.resume')}</> : <><Icon.pause s={12}/> {t('common.pause')}</>}
              </button>
              <button className="btn ghost xs" onClick={()=>setLines([])}>{t('logs.clear')}</button>
              <button className="btn ghost xs" onClick={exportLogs} disabled={!lines.length}>{t('logs.export')}</button>
            </div>
          }
        />
        <div className="log-filters" style={{marginBottom:10}}>
          {[['all',t('common.all')],['info',t('logs.filter.info')],['action',t('logs.filter.action')],['warn',t('logs.filter.warn')],['ok',t('logs.filter.ok')]].map(([v,l]) => (
            <button key={v} className={`chip ${filter===v?'on':''}`} onClick={()=>setFilter(v)}>
              {l} <span className="muted">{counts[v]||0}</span>
            </button>
          ))}
        </div>
        <div className="log" ref={logRef} style={{height: 520}}>
          {filtered.map((l,i) => <LogLine key={i} line={l}/>)}
          {!paused && <div className="log-caret">▍</div>}
        </div>
        <div className="log-foot">
          <span className="muted small">{filtered.length} / {lines.length}</span>
          <span className="muted small">{paused ? t('status.paused') : t('logs.streaming')}</span>
        </div>
      </div>
    </div>
  );
}

// Tiny searchable brawler picker for the per-instance session modal. We
// can't reuse the full BrawlersPage tile grid here — too heavy for a modal.
function BrawlerPicker({ value, onChange }) {
  const [filter, setFilter] = useS2('');
  const all = (typeof useLiveBrawlers === 'function' ? useLiveBrawlers() : null)
    || window.BRAWLERS || [];
  const norm = (filter || '').trim().toLowerCase();
  const matches = norm
    ? all.filter(b => (b.name || '').toLowerCase().includes(norm) || (b.id || b.key || '').toLowerCase().includes(norm))
    : all;
  return (
    <label>
      <div className="muted small">{t('inst.session.brawlerLabel')}</div>
      <input className="input" placeholder={t('inst.session.brawlerSearch')}
             value={filter} onChange={e => setFilter(e.target.value)}/>
      <div style={{
        display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(110px, 1fr))',
        gap: 6, marginTop: 6, maxHeight: 180, overflowY: 'auto',
      }}>
        {matches.slice(0, 60).map(b => {
          const key = b.key || b.id;
          return (
            <button key={key}
                    className={`chip ${value === key ? 'on' : ''}`}
                    onClick={() => onChange(key)}
                    title={b.name}
                    style={{justifyContent:'flex-start'}}>
              {value === key && '● '}{b.name}
            </button>
          );
        })}
        {matches.length === 0 && <div className="muted small">{t('inst.session.notFound')}</div>}
      </div>
      <div className="muted small" style={{marginTop: 4}}>
        {t('inst.session.brawlerSelected')}: <strong>{value || '—'}</strong>
      </div>
    </label>
  );
}

// ── Instances (multi-emulator) ────────────────────────────────
function InstancesPage() {
  const [instances, setInstances] = useS2([]);
  const [busy, setBusy] = useS2(false);
  const [showCreate, setShowCreate] = useS2(false);
  const [logsFor, setLogsFor] = useS2(null);   // instance id whose logs we're viewing
  const [logTail, setLogTail] = useS2([]);
  const [sessionFor, setSessionFor] = useS2(null);   // instance id we're editing
  // sessionDraft is now an OBJECT { queue: [entry, ...] } so the modal can edit
  // a multi-brawler queue, not just the head. Older code that touched a single
  // entry has been migrated to operate on queue[0].
  const [sessionDraft, setSessionDraft] = useS2(null);
  const [cfgFor, setCfgFor] = useS2(null);
  const [cfgDraft, setCfgDraft] = useS2(null);          // general
  const [cfgApiDraft, setCfgApiDraft] = useS2(null);    // brawl_stars_api
  const [cfgWhDraft, setCfgWhDraft] = useS2(null);      // webhook_config
  const [cfgTab, setCfgTab] = useS2('general');         // 'general' | 'api' | 'webhook'
  const [whTesting, setWhTesting] = useS2(false);
  const [renameFor, setRenameFor] = useS2(null);
  const [renameDraft, setRenameDraft] = useS2('');
  const [pushAllFor, setPushAllFor] = useS2(null);
  const [pushAllTarget, setPushAllTarget] = useS2(1000);
  const logScrollRef = React.useRef(null);
  const [createForm, setCreateForm] = useS2({ name: '', emulator: 'LDPlayer', port: 5555 });
  const [error, setError] = useS2('');
  const [discovered, setDiscovered] = useS2(null);
  const [discovering, setDiscovering] = useS2(false);

  const discover = async (emu) => {
    setDiscovering(true);
    try {
      const r = await window.PylaAPI.discoverEmulators(emu);
      setDiscovered(r);
    } catch (e) {
      setDiscovered({ instances: [], error: e.message || String(e) });
    } finally {
      setDiscovering(false);
    }
  };

  const refresh = React.useCallback(async () => {
    try {
      const r = await window.PylaAPI.listInstances();
      setInstances(r.instances || []);
      setError('');
    } catch (e) {
      setError(e.message || String(e));
    }
  }, []);

  React.useEffect(() => {
    refresh();
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, [refresh]);

  React.useEffect(() => {
    if (logsFor == null) {
      setLogTail([]);
      return;
    }
    setLogTail([]);
    // Live tail via WebSocket — backfill arrives as the first batch, then new
    // lines stream in real-time as the subprocess writes them.
    const conn = window.PylaAPI.streamInstanceLogs(logsFor, (msg) => {
      if (msg.error) {
        setLogTail(prev => [...prev, `[stream error: ${msg.error}]`]);
        return;
      }
      if (msg.line == null) return;
      setLogTail(prev => {
        const next = [...prev, msg.line];
        return next.length > 1500 ? next.slice(-1500) : next;
      });
    });
    return () => { try { conn.close(); } catch (_) {} };
  }, [logsFor]);

  React.useEffect(() => {
    // Auto-scroll the log modal to the bottom as new lines arrive.
    if (logsFor != null && logScrollRef.current) {
      logScrollRef.current.scrollTop = logScrollRef.current.scrollHeight;
    }
  }, [logTail, logsFor]);

  const create = async () => {
    setBusy(true);
    try {
      await window.PylaAPI.createInstance({
        name: createForm.name || '',
        emulator: createForm.emulator || 'LDPlayer',
        port: parseInt(createForm.port, 10) || 0,
      });
      setShowCreate(false);
      setCreateForm({ name: '', emulator: 'LDPlayer', port: 5555 });
      await refresh();
      window.pylaToast?.(t('inst.create.toastOk'), { kind: 'ok' });
    } catch (e) {
      window.pylaToast?.(`${t('inst.toast.error')}: ${e.message || e}`, { kind: 'warn' });
    } finally {
      setBusy(false);
    }
  };

  const dashboardSession = () => {
    // Snapshot the Dashboard's current goal as a starter session — used when
    // an instance card has no per-instance session saved yet.
    const ls = (k, def) => {
      try { const v = JSON.parse(localStorage.getItem(k)); return v == null ? def : v; }
      catch (_) { return def; }
    };
    const farmType = ls('pyla.dash.farmType', 'trophies');
    const target = ls('pyla.dash.target', 1000);
    const currentValue = ls('pyla.dash.currentValue', 0);
    const winStreak = ls('pyla.dash.winStreak', 0);
    const autoPick = ls('pyla.dash.autoPick', true);
    const brawlerKey = ls('pyla.dash.brawlerKey', null);
    if (!brawlerKey) return null;
    return [{
      brawler: brawlerKey,
      type: farmType,
      push_until: parseInt(target, 10) || 1000,
      trophies: farmType === 'trophies' ? (parseInt(currentValue, 10) || 0) : 0,
      wins: farmType === 'wins' ? (parseInt(currentValue, 10) || 0) : 0,
      win_streak: parseInt(winStreak, 10) || 0,
      automatically_pick: !!autoPick,
    }];
  };

  const start = async (id) => {
    // Per-instance saved session takes priority. Fall back to the Dashboard
    // form so users that haven't customised per-instance still get one click.
    const inst = instances.find(i => i.id === id);
    const hasSaved = inst && inst.session && inst.session.brawler;
    let payload = null;
    if (!hasSaved) {
      payload = dashboardSession();
      if (!payload) {
        window.pylaToast?.(t('inst.session.toastNoSession'), { kind: 'warn' });
        return;
      }
    }
    try {
      // payload=null lets the backend use the saved per-instance session.
      await (payload === null
        ? window.PylaAPI.startInstance(id, [])  // backend treats empty as "use saved"
        : window.PylaAPI.startInstance(id, payload));
      window.pylaToast?.(`#${id}: ${t('inst.toast.startOk')}`, { kind: 'ok' });
      await refresh();
    } catch (e) {
      // If the backend refused empty-as-saved (legacy single-instance start
      // route requires a non-empty payload), retry through start_all which
      // accepts session=null for "use saved".
      if (payload === null) {
        try {
          await window.PylaAPI.startAllInstances(null, [id]);
          window.pylaToast?.(`#${id}: ${t('inst.toast.startOk')}`, { kind: 'ok' });
          await refresh();
          return;
        } catch (e2) {
          window.pylaToast?.(`${t('inst.toast.startInst')} #${id}: ${e2.message || e2}`, { kind: 'warn' });
          return;
        }
      }
      window.pylaToast?.(`${t('inst.toast.startInst')} #${id}: ${e.message || e}`, { kind: 'warn' });
    }
  };

  const toggleAutoRestart = async (id, current) => {
    try {
      await window.PylaAPI.setInstanceAutoRestart(id, !current);
      await refresh();
    } catch (e) {
      window.pylaToast?.(`Auto-restart: ${e.message || e}`, { kind: 'warn' });
    }
  };

  const openSessionEditor = async (id) => {
    setSessionFor(id);
    let queue = [];
    try {
      const r = await window.PylaAPI.getInstanceSession(id);
      if (r.brawlers_data && r.brawlers_data.length) {
        queue = r.brawlers_data.map(e => ({...e}));
      }
    } catch (_) {}
    if (queue.length === 0) {
      // Pre-fill from Dashboard so editing the first instance is one click.
      const d = dashboardSession();
      queue = (d && d.length) ? d : [{
        brawler: '', type: 'trophies', push_until: 1000,
        trophies: 0, wins: 0, win_streak: 0, automatically_pick: true,
      }];
    }
    setSessionDraft({ queue });
  };

  const updateQueueEntry = (idx, patch) => {
    setSessionDraft(prev => {
      if (!prev) return prev;
      const queue = prev.queue.map((e, i) => i === idx ? { ...e, ...patch } : e);
      return { ...prev, queue };
    });
  };

  const addQueueEntry = () => {
    setSessionDraft(prev => {
      const queue = [...(prev?.queue || []), {
        brawler: '', type: 'trophies', push_until: 1000,
        trophies: 0, wins: 0, win_streak: 0, automatically_pick: true,
      }];
      return { ...(prev || {}), queue };
    });
  };

  const removeQueueEntry = (idx) => {
    setSessionDraft(prev => {
      if (!prev) return prev;
      const queue = prev.queue.filter((_, i) => i !== idx);
      return { ...prev, queue };
    });
  };

  const saveSessionDraft = async () => {
    if (!sessionFor || !sessionDraft) return;
    const queue = sessionDraft.queue || [];
    if (queue.length === 0) {
      window.pylaToast?.(t('inst.session.queueEmpty'), { kind: 'warn' });
      return;
    }
    if (queue.some(e => !e.brawler)) {
      window.pylaToast?.(t('inst.session.toastNeedBrawler'), { kind: 'warn' });
      return;
    }
    const entries = queue.map(e => ({
      brawler: e.brawler,
      type: e.type || 'trophies',
      push_until: parseInt(e.push_until, 10) || 1000,
      trophies: e.type === 'trophies' ? (parseInt(e.trophies, 10) || 0) : 0,
      wins: e.type === 'wins' ? (parseInt(e.wins, 10) || 0) : 0,
      win_streak: parseInt(e.win_streak, 10) || 0,
      automatically_pick: e.automatically_pick !== false,
    }));
    try {
      await window.PylaAPI.putInstanceSession(sessionFor, entries);
      window.pylaToast?.(`${t('inst.session.toastSaved')} · #${sessionFor}`, { kind: 'ok' });
      setSessionFor(null);
      setSessionDraft(null);
      await refresh();
    } catch (e) {
      window.pylaToast?.(`${t('inst.toast.saveErr')}: ${e.message || e}`, { kind: 'warn' });
    }
  };

  const clearSessionForInstance = async (id) => {
    if (!confirm(`${t('inst.session.toastClearAsk')} #${id}?`)) return;
    try {
      await window.PylaAPI.clearInstanceSession(id);
      await refresh();
    } catch (e) {
      window.pylaToast?.(`${t('inst.session.clear')}: ${e.message || e}`, { kind: 'warn' });
    }
  };

  const restartEmulatorFor = async (id) => {
    if (!confirm(`${t('inst.action.restartEmu')} #${id}?`)) return;
    try {
      const r = await window.PylaAPI.restartInstanceEmulator(id);
      window.pylaToast?.(
        r.ok ? `LDPlayer #${r.ld_index}: рестарт инициирован` : `Не удалось: ${r.message}`,
        { kind: r.ok ? 'ok' : 'warn' }
      );
      await refresh();
    } catch (e) {
      window.pylaToast?.(`${t('inst.action.restartEmu')}: ${e.message || e}`, { kind: 'warn' });
    }
  };

  const openCfgEditor = async (id) => {
    setCfgFor(id);
    setCfgTab('general');
    // Read all three configs in parallel — keeps the modal snappy when the
    // user switches tabs without a roundtrip per tab.
    const [g, a, w] = await Promise.allSettled([
      window.PylaAPI.getInstanceConfig(id, 'general'),
      window.PylaAPI.getInstanceConfig(id, 'brawl_stars_api'),
      window.PylaAPI.getInstanceConfig(id, 'webhook'),
    ]);
    setCfgDraft(g.status === 'fulfilled' ? (g.value.values || {}) : {});
    setCfgApiDraft(a.status === 'fulfilled' ? (a.value.values || {}) : {});
    setCfgWhDraft(w.status === 'fulfilled' ? (w.value.values || {}) : {});
    if (g.status === 'rejected') {
      window.pylaToast?.(`${t('inst.toast.cfgReadErr')}: ${g.reason?.message || g.reason}`, { kind: 'warn' });
    }
  };

  const saveCfgDraft = async () => {
    if (!cfgFor) return;
    // Coerce numeric fields back to numbers — TOML treats "5555" as a string
    // and the bot's WindowController expects an int port.
    const toNum = (v) => {
      if (v === '' || v == null) return 0;
      const n = Number(v);
      return Number.isFinite(n) ? n : v;
    };
    // Save ALL three sections (general / brawl_stars_api / webhook) atomically
    // — the modal is one scrolling form now, not tabs, so the "Save" button
    // commits everything the user touched. Empty drafts are skipped.
    const tasks = [];
    if (cfgDraft) {
      const patched = { ...cfgDraft };
      for (const k of ['emulator_port', 'emulator_profile_index', 'max_ips', 'run_for_minutes']) {
        if (k in patched) patched[k] = toNum(patched[k]);
      }
      tasks.push(window.PylaAPI.putInstanceConfig(cfgFor, 'general', patched));
    }
    if (cfgApiDraft) {
      // Per-instance Brawl Stars API now stores ONLY player_tag — token,
      // dev_email, dev_password live in global Settings and are merged in
      // server-side by _resolve_brawl_stars_api_cfg.
      const patched = { player_tag: String(cfgApiDraft.player_tag || '').trim() };
      tasks.push(window.PylaAPI.putInstanceConfig(cfgFor, 'brawl_stars_api', patched));
    }
    if (cfgWhDraft) {
      const patched = { ...cfgWhDraft };
      // webhook_url_draft is a UI-only stash so toggling "use global" ON/OFF
      // restores the user's last typed URL — never persist it to TOML.
      delete patched.webhook_url_draft;
      for (const k of ['ping_every_x_match', 'ping_every_x_minutes']) {
        if (k in patched) patched[k] = toNum(patched[k]);
      }
      tasks.push(window.PylaAPI.putInstanceConfig(cfgFor, 'webhook', patched));
    }
    try {
      await Promise.all(tasks);
      window.pylaToast?.(`${t('inst.cfg.toastSaved')} · #${cfgFor}`, { kind: 'ok' });
      await refresh();
    } catch (e) {
      window.pylaToast?.(`${t('inst.toast.saveErr')}: ${e.message || e}`, { kind: 'warn' });
    }
  };

  const closeCfgEditor = () => {
    setCfgFor(null);
    setCfgDraft(null);
    setCfgApiDraft(null);
    setCfgWhDraft(null);
  };

  const sendWebhookTest = async () => {
    if (!cfgFor) return;
    setWhTesting(true);
    try {
      // Save current webhook draft first so the test uses what the user typed,
      // not whatever was on disk before the modal opened.
      if (cfgWhDraft) {
        const patched = { ...cfgWhDraft };
        delete patched.webhook_url_draft;  // UI-only field
        for (const k of ['ping_every_x_match', 'ping_every_x_minutes']) {
          const n = Number(patched[k]);
          if (Number.isFinite(n)) patched[k] = n;
        }
        await window.PylaAPI.putInstanceConfig(cfgFor, 'webhook', patched);
      }
      await window.PylaAPI.testInstanceWebhook(cfgFor);
      window.pylaToast?.(t('inst.cfg.webhook.testOk'), { kind: 'ok' });
    } catch (e) {
      window.pylaToast?.(`${t('inst.cfg.webhook.testFail')}: ${e.message || e}`, { kind: 'warn' });
    } finally {
      setWhTesting(false);
    }
  };

  const openRename = (inst) => {
    setRenameFor(inst.id);
    setRenameDraft(inst.name || '');
  };

  const saveRename = async () => {
    if (!renameFor) return;
    const clean = (renameDraft || '').trim();
    if (!clean) return;
    try {
      await window.PylaAPI.renameInstance(renameFor, clean);
      window.pylaToast?.(`${t('inst.rename.toastOk')} · #${renameFor}`, { kind: 'ok' });
      setRenameFor(null);
      setRenameDraft('');
      await refresh();
    } catch (e) {
      window.pylaToast?.(`${t('inst.toast.saveErr')}: ${e.message || e}`, { kind: 'warn' });
    }
  };

  const openPushAll = (id) => {
    setPushAllFor(id);
    setPushAllTarget(1000);
  };

  const runPushAll = async () => {
    if (!pushAllFor) return;
    const target = parseInt(pushAllTarget, 10) || 1000;
    try {
      const r = await window.PylaAPI.pushAllInstance(pushAllFor, target);
      window.pylaToast?.(
        `${t('inst.pushAll.toastOk')} #${pushAllFor} · ${r.count}`,
        { kind: 'ok' }
      );
      setPushAllFor(null);
      await refresh();
    } catch (e) {
      window.pylaToast?.(`${t('inst.pushAll.toastFail')}: ${e.message || e}`, { kind: 'warn' });
    }
  };

  const stop = async (id) => {
    try {
      await window.PylaAPI.stopInstance(id);
      window.pylaToast?.(`#${id}: ${t('inst.toast.stopOk')}`, { kind: 'info' });
      await refresh();
    } catch (e) {
      window.pylaToast?.(`${t('inst.toast.stopInst')} #${id}: ${e.message || e}`, { kind: 'warn' });
    }
  };

  const remove = async (id) => {
    if (!confirm(`${t('inst.toast.deleteAsk')} #${id}?`)) return;
    try {
      await window.PylaAPI.deleteInstance(id);
      await refresh();
    } catch (e) {
      window.pylaToast?.(`${t('inst.toast.deleteOk')}: ${e.message || e}`, { kind: 'warn' });
    }
  };

  const STATUS_COLORS = {
    running: '#5be37c',
    starting: '#f4d35e',
    stale: '#f4a35e',
    crashed: '#e6605b',
    stopped: '#7d7777',
    uninitialized: '#7d7777',
  };
  const STATUS_LABEL = {
    running:       t('inst.status.running'),
    starting:      t('inst.status.starting'),
    stale:         t('inst.status.stale'),
    crashed:       t('inst.status.crashed'),
    stopped:       t('inst.status.stopped'),
    uninitialized: t('inst.status.uninitialized'),
  };

  // Build the status-rail counters from current instances list
  const counts = instances.reduce((acc, i) => {
    const k = i.status || 'uninitialized';
    acc[k] = (acc[k] || 0) + 1;
    return acc;
  }, {});
  const railOrder = ['running','starting','stale','crashed','stopped','uninitialized'];

  // Overflow menu state — which card has its ⋯-menu open
  const [overflowFor, setOverflowFor] = useS2(null);
  React.useEffect(() => {
    if (overflowFor == null) return;
    const close = () => setOverflowFor(null);
    window.addEventListener('click', close);
    return () => window.removeEventListener('click', close);
  }, [overflowFor]);

  // Tiny SVG sparkline of the heartbeat IPS history (if present), else flat bars.
  const Sparkline = ({ values, color }) => {
    const data = (values && values.length) ? values.slice(-20) : [];
    if (!data.length) {
      // synthetic flat bars to keep card height stable
      return (
        <div className="inst-spark inst-spark-empty">
          {Array.from({length: 12}).map((_,i) => <span key={i}/>)}
        </div>
      );
    }
    const max = Math.max(...data, 1);
    return (
      <div className="inst-spark" style={{'--spark-color': color}}>
        {data.map((v,i) => (
          <span key={i} style={{height: `${Math.max(8, (v/max)*100)}%`}}/>
        ))}
      </div>
    );
  };

  return (
    <div className="stats-page inst-page">
      {/* Header card with status-rail */}
      <div className="card inst-header">
        <div className="inst-header-row">
          <div className="inst-header-title">
            <Icon.chips s={16}/>
            <h2>{t('inst.title')}</h2>
            <span className="inst-count-badge">{instances.length}</span>
          </div>
          <div className="row-gap">
            <button className="btn ghost xs" onClick={refresh} disabled={busy}>
              <Icon.refresh s={11}/> {t('inst.refresh')}
            </button>
            <button className="btn primary xs" onClick={() => setShowCreate(true)} disabled={busy}>
              <Icon.plus s={11}/> {t('inst.add')}
            </button>
          </div>
        </div>

        {instances.length > 0 && (
          <div className="inst-rail">
            {railOrder.map(k => (
              <div key={k} className={`inst-rail-cell ${(counts[k]||0) > 0 ? 'has' : 'empty'}`}>
                <span className="inst-rail-dot" style={{background: STATUS_COLORS[k]}}/>
                <span className="inst-rail-num">{counts[k] || 0}</span>
                <span className="inst-rail-name">{STATUS_LABEL[k]}</span>
              </div>
            ))}
          </div>
        )}

        {error && (
          <div className="inst-error">
            <span>⚠</span> {t('inst.errorPrefix')}: {error}
          </div>
        )}
      </div>

      {/* Empty-state */}
      {instances.length === 0 && !error && (
        <div className="card inst-empty">
          <div className="inst-empty-icon"><Icon.chips s={28}/></div>
          <div className="inst-empty-title">{t('inst.empty.title')}</div>
          <div className="inst-empty-sub muted small">{t('inst.empty.sub')}</div>
          <button className="btn primary" onClick={() => setShowCreate(true)}>
            <Icon.plus s={12}/> {t('inst.empty.cta')}
          </button>
        </div>
      )}

      {/* Cards */}
      {instances.length > 0 && (
        <div className="inst-cards">
          {instances.map(inst => {
            const beat = inst.heartbeat || {};
            const dot = STATUS_COLORS[inst.status] || '#7d7777';
            const sess = inst.session;
            const sessProgress = sess && sess.target > 0
              ? Math.min(100, Math.max(0, ((sess.current||0) / sess.target) * 100))
              : 0;
            const isLive = ['running','starting','stale'].includes(inst.status);
            const ips = beat.ips != null ? beat.ips : (beat.actions_per_sec || null);
            const heartbeatHistory = beat.ips_history || beat.history || null;

            return (
              <div key={inst.id} className={`inst-card status-${inst.status || 'uninitialized'}`}>
                {/* Top bar — identity + status + flags + primary actions */}
                <div className="inst-top">
                  <div className="inst-ident">
                    <span className="inst-status-dot" style={{background: dot, boxShadow: `0 0 12px ${dot}`}}/>
                    <div className="inst-ident-text">
                      <div className="inst-name-row">
                        <span className="inst-id">#{inst.id}</span>
                        <strong className="inst-name">{inst.name}</strong>
                        <span className={`inst-status-pill status-${inst.status}`}>
                          {STATUS_LABEL[inst.status] || inst.status}
                        </span>
                      </div>
                      <div className="inst-meta">
                        <span>{inst.emulator}{inst.port ? `:${inst.port}` : ''}</span>
                        {inst.pid && <span className="muted-2">PID {inst.pid}</span>}
                        {inst.auto_restart && (
                          <span className="inst-flag flag-auto">↻ {t('inst.flag.autorestart')}</span>
                        )}
                        {inst.exit_code != null && (
                          <span className="inst-flag flag-exit">{t('inst.flag.exit')}={inst.exit_code}</span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="inst-actions">
                    {isLive ? (
                      <button className="btn xs inst-stop" onClick={() => stop(inst.id)}>
                        <Icon.stop s={10}/> {t('inst.action.stop')}
                      </button>
                    ) : (
                      <button className="btn primary xs" onClick={() => start(inst.id)}>
                        <Icon.play s={10}/> {t('inst.action.start')}
                      </button>
                    )}
                    <button className="btn ghost xs" onClick={() => openSessionEditor(inst.id)}>
                      ✎ {t('inst.session.label')}
                    </button>
                    <button className="btn ghost xs" onClick={() => setLogsFor(inst.id)}>
                      <Icon.log s={11}/> {t('inst.action.logs')}
                    </button>
                    <div className="inst-overflow" onClick={e => e.stopPropagation()}>
                      <button className="btn ghost xs"
                              onClick={() => setOverflowFor(overflowFor === inst.id ? null : inst.id)}>
                        <Icon.more s={12}/>
                      </button>
                      {overflowFor === inst.id && (
                        <div className="inst-overflow-menu">
                          <button onClick={() => { setOverflowFor(null); openRename(inst); }}>
                            ✎ {t('inst.action.rename')}
                          </button>
                          <button onClick={() => { setOverflowFor(null); openPushAll(inst.id); }}
                                  title={t('inst.action.pushAllTip')}>
                            {t('inst.action.pushAll')}
                          </button>
                          <button onClick={() => { setOverflowFor(null); openCfgEditor(inst.id); }}>
                            <Icon.gear s={11}/> {t('inst.action.config')}
                          </button>
                          <button onClick={() => { setOverflowFor(null); toggleAutoRestart(inst.id, inst.auto_restart); }}>
                            ↻ {t('inst.action.autorestart')}: {inst.auto_restart ? 'ON' : 'OFF'}
                          </button>
                          {inst.emulator === 'LDPlayer' && (
                            <button onClick={() => { setOverflowFor(null); restartEmulatorFor(inst.id); }}>
                              🔁 {t('inst.action.restartEmu')}
                            </button>
                          )}
                          <div className="inst-overflow-sep"/>
                          <button className="danger" onClick={() => { setOverflowFor(null); remove(inst.id); }}>
                            <Icon.trash s={11}/> {t('inst.action.delete')}
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                {/* Body grid — left: session block, right: metric grid */}
                <div className="inst-body">
                  {/* Active session */}
                  <div className={`inst-session ${sess ? 'has' : 'empty'}`}>
                    {sess ? (
                      <>
                        <div className="inst-session-label">{t('inst.session.active')}</div>
                        <div className="inst-session-name">
                          {sess.brawler} <span className="muted small">· {sess.type === 'wins' ? t('inst.session.types.wins') : t('inst.session.types.trophies')}</span>
                        </div>
                        <div className="inst-session-progress">
                          <div className="inst-progress-track">
                            <div className="inst-progress-fill" style={{width: `${sessProgress}%`, background: dot}}/>
                          </div>
                          <div className="inst-progress-text">
                            <strong>{sess.current ?? 0}</strong> / {sess.target}
                            {sess.queue_length > 1 && (
                              <span className="muted small"> · +{sess.queue_length - 1} {t('inst.session.queueExtra')}</span>
                            )}
                          </div>
                        </div>
                        <button className="inst-session-clear muted small"
                                onClick={() => clearSessionForInstance(inst.id)}>
                          {t('inst.session.clear')}
                        </button>
                      </>
                    ) : (
                      <>
                        <div className="inst-session-label">{t('inst.session.label')}</div>
                        <div className="inst-session-empty-text muted small">
                          {t('inst.session.empty')}
                        </div>
                        <button className="btn ghost xs" onClick={() => openSessionEditor(inst.id)}>
                          <Icon.plus s={10}/> {t('inst.session.assign')}
                        </button>
                      </>
                    )}
                  </div>

                  {/* Metric grid 2×3 */}
                  <div className="inst-metrics">
                    <div className="inst-metric">
                      <div className="inst-metric-label">{t('inst.metric.brawler')}</div>
                      <div className="inst-metric-value">{beat.current_brawler || '—'}</div>
                    </div>
                    <div className="inst-metric">
                      <div className="inst-metric-label">{t('inst.metric.state')}</div>
                      <div className="inst-metric-value mono small">{beat.current_state || '—'}</div>
                    </div>
                    <div className="inst-metric">
                      <div className="inst-metric-label">
                        {t('inst.metric.ips')} {isLive && ips != null && <span className="ips-pulse"/>}
                      </div>
                      <div className="inst-metric-value">
                        {ips != null ? (Math.round(ips * 10) / 10) : '—'}
                      </div>
                    </div>
                    <div className="inst-metric">
                      <div className="inst-metric-label">Heartbeat</div>
                      <Sparkline values={heartbeatHistory} color={dot}/>
                    </div>
                    <div className="inst-metric">
                      <div className="inst-metric-label">Hb age</div>
                      <div className="inst-metric-value">
                        {beat.age_sec != null ? `${beat.age_sec}s` : '—'}
                      </div>
                    </div>
                    <div className="inst-metric">
                      <div className="inst-metric-label">{t('inst.metric.queue')}</div>
                      <div className="inst-metric-value">{beat.brawlers_left ?? '—'}</div>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Create modal ───────────────────────────── */}
      {showCreate && (
        <div className="modal-backdrop" onClick={() => setShowCreate(false)}>
          <div className="modal-panel" onClick={e => e.stopPropagation()} style={{maxWidth: 520}}>
            <div className="modal-head">
              <div className="modal-title">
                <div className="modal-title-main">{t('inst.create.title')}</div>
                <div className="modal-title-sub">{t('inst.create.sub')}</div>
              </div>
              <button className="modal-close" onClick={() => setShowCreate(false)}>×</button>
            </div>
            <div className="modal-body">
              <div className="form-row">
                <label className="form-label">{t('inst.create.fieldName')}</label>
                <input className="input" value={createForm.name}
                       onChange={e => setCreateForm({...createForm, name: e.target.value})}
                       placeholder={t('inst.create.namePlaceholder')}/>
              </div>
              <div className="form-row">
                <label className="form-label">{t('inst.create.fieldEmu')}</label>
                <select className="input" value={createForm.emulator}
                        onChange={e => { setCreateForm({...createForm, emulator: e.target.value}); setDiscovered(null); }}>
                  <option>LDPlayer</option>
                  <option>MuMu</option>
                  <option>BlueStacks</option>
                </select>
              </div>

              {createForm.emulator === 'LDPlayer' && (
                <div className="inst-discover">
                  <div className="inst-discover-head">
                    <button className="btn ghost xs" onClick={() => discover('LDPlayer')} disabled={discovering}>
                      <Icon.search s={11}/> {discovering ? t('inst.create.discovering') : t('inst.create.discover')}
                    </button>
                    <span className="muted small">{t('inst.create.discoverHint')}</span>
                  </div>
                  {discovered && discovered.error && (
                    <div className="inst-discover-error">
                      <code>{discovered.error}</code>
                    </div>
                  )}
                  {discovered && discovered.instances && discovered.instances.length > 0 && (
                    <div className="inst-discover-list">
                      <div className="muted small" style={{marginBottom: 4}}>
                        {t('inst.create.found')}: <strong>{discovered.instances.length}</strong>. {t('inst.create.foundHint')}
                      </div>
                      {discovered.instances.map(ld => (
                        <button key={ld.index}
                                className="inst-discover-item"
                                onClick={() => setCreateForm({...createForm, name: ld.name, port: ld.port})}>
                          <span className="ld-idx">#{ld.index}</span>
                          <span className="ld-name">{ld.name}</span>
                          <span className="ld-port muted small">:{ld.port}</span>
                          <span className={`ld-state ${ld.running ? 'on' : ''}`}>
                            {ld.running ? `● ${t('inst.status.running')}` : `○ ${t('inst.status.uninitialized')}`}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                  {discovered && discovered.instances && discovered.instances.length === 0 && !discovered.error && (
                    <div className="muted small" style={{padding: '6px 0'}}>
                      {t('inst.create.notFound')}
                    </div>
                  )}
                </div>
              )}

              <div className="form-row">
                <label className="form-label">{t('inst.create.fieldPort')}</label>
                <input className="input" type="number" value={createForm.port}
                       onChange={e => setCreateForm({...createForm, port: e.target.value})}
                       placeholder={t('inst.create.portPlaceholder')}/>
              </div>
              <div className="muted small" style={{marginTop: 6}}>
                {t('inst.create.foot')}
              </div>
            </div>
            <div className="modal-foot">
              <button className="btn ghost" onClick={() => setShowCreate(false)}>{t('inst.create.cancel')}</button>
              <button className="btn primary" onClick={create} disabled={busy}>
                <Icon.plus s={11}/> {t('inst.create.create')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Session modal (multi-brawler queue) ────── */}
      {sessionFor != null && sessionDraft && (
        <div className="modal-backdrop" onClick={() => { setSessionFor(null); setSessionDraft(null); }}>
          <div className="modal-panel" onClick={e => e.stopPropagation()} style={{maxWidth: 560}}>
            <div className="modal-head">
              <div className="modal-title">
                <div className="modal-title-main">{t('inst.session.modalTitle')} #{sessionFor}</div>
                <div className="modal-title-sub">{t('inst.session.modalSub')}</div>
              </div>
              <button className="modal-close" onClick={() => { setSessionFor(null); setSessionDraft(null); }}>×</button>
            </div>
            <div className="modal-body" style={{maxHeight: '70vh', overflowY: 'auto'}}>
              <div className="muted small" style={{marginBottom: 6}}>
                <strong>{t('inst.session.queueHead')}</strong> · {t('inst.session.queueTip')}
              </div>
              {(sessionDraft.queue || []).map((entry, idx) => (
                <div key={idx} className="card" style={{padding: 10, marginBottom: 10, background:'rgba(255,255,255,0.02)'}}>
                  <div className="row-gap" style={{justifyContent:'space-between', marginBottom: 6}}>
                    <strong className="small">#{idx + 1}{idx === 0 ? ' · main' : ''}</strong>
                    <button className="btn ghost xs danger"
                            onClick={() => removeQueueEntry(idx)}
                            disabled={(sessionDraft.queue || []).length === 1}>
                      {t('inst.session.queueRemove')}
                    </button>
                  </div>
                  <BrawlerPicker
                    value={entry.brawler}
                    onChange={(key) => updateQueueEntry(idx, { brawler: key })}
                  />
                  <div className="seg" style={{width:'100%', marginTop: 10, marginBottom: 10}}>
                    <button className="seg-btn" data-on={entry.type === 'trophies'}
                            onClick={() => updateQueueEntry(idx, { type: 'trophies' })}>
                      {t('inst.session.optTrophies')}
                    </button>
                    <button className="seg-btn" data-on={entry.type === 'wins'}
                            onClick={() => updateQueueEntry(idx, { type: 'wins' })}>
                      {t('inst.session.optWins')}
                    </button>
                  </div>
                  <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap: 8}}>
                    <div className="form-row">
                      <label className="form-label">{t('inst.session.fieldCurrent')}</label>
                      <input className="input" type="number"
                             value={entry.type === 'wins' ? (entry.wins || 0) : (entry.trophies || 0)}
                             onChange={e => updateQueueEntry(idx, entry.type === 'wins'
                                ? { wins: e.target.value }
                                : { trophies: e.target.value })}/>
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t('inst.session.fieldTarget')}</label>
                      <input className="input" type="number"
                             value={entry.push_until || 1000}
                             onChange={e => updateQueueEntry(idx, { push_until: e.target.value })}/>
                    </div>
                  </div>
                  {entry.type === 'trophies' && (
                    <div className="form-row">
                      <label className="form-label">{t('inst.session.fieldStreak')}</label>
                      <input className="input" type="number"
                             value={entry.win_streak || 0}
                             onChange={e => updateQueueEntry(idx, { win_streak: e.target.value })}/>
                    </div>
                  )}
                  <label className="switch" style={{marginTop: 4}}>
                    <input type="checkbox"
                           checked={entry.automatically_pick !== false}
                           onChange={e => updateQueueEntry(idx, { automatically_pick: e.target.checked })}/>
                    <span className="switch-track"><span className="switch-dot"/></span>
                    <span className="switch-label">{t('inst.session.autoPickToggle')}</span>
                  </label>
                </div>
              ))}
              <button className="btn ghost xs" onClick={addQueueEntry}>
                <Icon.plus s={10}/> {t('inst.session.queueAdd')}
              </button>
            </div>
            <div className="modal-foot">
              <button className="btn ghost" onClick={() => { setSessionFor(null); setSessionDraft(null); }}>{t('inst.session.cancel')}</button>
              <button className="btn primary" onClick={saveSessionDraft}>{t('inst.session.save')}</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Rename modal ───────────────────────────── */}
      {renameFor != null && (
        <div className="modal-backdrop" onClick={() => setRenameFor(null)}>
          <div className="modal-panel" onClick={e => e.stopPropagation()} style={{maxWidth: 420}}>
            <div className="modal-head">
              <div className="modal-title">
                <div className="modal-title-main">{t('inst.rename.title')} #{renameFor}</div>
              </div>
              <button className="modal-close" onClick={() => setRenameFor(null)}>×</button>
            </div>
            <div className="modal-body">
              <input className="input" autoFocus
                     value={renameDraft}
                     placeholder={t('inst.rename.placeholder')}
                     onChange={e => setRenameDraft(e.target.value)}
                     onKeyDown={e => { if (e.key === 'Enter') saveRename(); }}/>
            </div>
            <div className="modal-foot">
              <button className="btn ghost" onClick={() => setRenameFor(null)}>{t('inst.rename.cancel')}</button>
              <button className="btn primary" onClick={saveRename} disabled={!renameDraft.trim()}>
                {t('inst.rename.save')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Push All modal ─────────────────────────── */}
      {pushAllFor != null && (
        <div className="modal-backdrop" onClick={() => setPushAllFor(null)}>
          <div className="modal-panel" onClick={e => e.stopPropagation()} style={{maxWidth: 420}}>
            <div className="modal-head">
              <div className="modal-title">
                <div className="modal-title-main">{t('inst.pushAll.title')} #{pushAllFor}</div>
                <div className="modal-title-sub">{t('inst.pushAll.sub')}</div>
              </div>
              <button className="modal-close" onClick={() => setPushAllFor(null)}>×</button>
            </div>
            <div className="modal-body">
              <div className="form-row">
                <label className="form-label">{t('inst.pushAll.fieldTarget')}</label>
                <input className="input" type="number" autoFocus
                       value={pushAllTarget}
                       onChange={e => setPushAllTarget(e.target.value)}
                       onKeyDown={e => { if (e.key === 'Enter') runPushAll(); }}/>
              </div>
              <div className="muted small" style={{marginTop: 6}}>
                {t('inst.action.pushAllTip')}
              </div>
            </div>
            <div className="modal-foot">
              <button className="btn ghost" onClick={() => setPushAllFor(null)}>{t('inst.create.cancel')}</button>
              <button className="btn primary" onClick={runPushAll}>
                {t('inst.pushAll.go')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Logs modal ─────────────────────────────── */}
      {logsFor != null && (
        <div className="modal-backdrop" onClick={() => setLogsFor(null)}>
          <div className="modal-panel" onClick={e => e.stopPropagation()} style={{maxWidth: 1000, width: '92%'}}>
            <div className="modal-head">
              <div className="modal-title">
                <div className="modal-title-main">
                  {t('inst.logs.title')} #{logsFor}
                  <span className="inst-log-live"><span className="ips-pulse"/> live tail</span>
                </div>
                <div className="modal-title-sub">{t('inst.logs.sub')}</div>
              </div>
              <div className="row-gap">
                <button className="btn ghost xs" onClick={() => setLogTail([])}>{t('inst.logs.clear')}</button>
                <button className="modal-close" onClick={() => setLogsFor(null)}>×</button>
              </div>
            </div>
            <div ref={logScrollRef} className="log inst-log" style={{height: 520, fontSize: 12}}>
              {logTail.length === 0
                ? <div className="muted small inst-log-connecting">
                    <span className="ips-pulse"/> {t('inst.logs.connecting')}
                  </div>
                : logTail.map((line, i) => <div key={i} className="inst-log-line">{line}</div>)}
            </div>
          </div>
        </div>
      )}

      {/* ── Cfg modal (single scrolling form, sections divided) ────── */}
      {cfgFor != null && (cfgDraft || cfgApiDraft || cfgWhDraft) && (
        <div className="modal-backdrop" onClick={closeCfgEditor}>
          <div className="modal-panel" onClick={e => e.stopPropagation()} style={{maxWidth: 720, width: '92%'}}>
            <div className="modal-head">
              <div className="modal-title">
                <div className="modal-title-main">{t('inst.cfg.title')} #{cfgFor}</div>
                <div className="modal-title-sub">{t('inst.cfg.sub')}</div>
              </div>
              <button className="modal-close" onClick={closeCfgEditor}>×</button>
            </div>
            <div className="modal-body" style={{maxHeight: '74vh', overflowY: 'auto'}}>
              {/* === GENERAL SECTION === */}
              {cfgDraft && (
                <>
                  <h4 style={{margin:'2px 0 10px', fontSize: 13, opacity: 0.85}}>
                    {t('inst.cfg.section.general')}
                  </h4>
                  <div className="form-row">
                    <label className="form-label">{t('inst.cfg.fieldEmu')}</label>
                    <select className="input" value={cfgDraft.current_emulator || 'LDPlayer'}
                            onChange={e => setCfgDraft({...cfgDraft, current_emulator: e.target.value})}>
                      <option>LDPlayer</option>
                      <option>MuMu</option>
                      <option>BlueStacks</option>
                    </select>
                  </div>
                  <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap: 10}}>
                    <div className="form-row">
                      <label className="form-label">{t('inst.cfg.fieldPort')}</label>
                      <input className="input" type="number" value={cfgDraft.emulator_port ?? ''}
                             onChange={e => setCfgDraft({...cfgDraft, emulator_port: e.target.value})}/>
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t('inst.cfg.fieldProfileIdx')}</label>
                      <input className="input" type="number" value={cfgDraft.emulator_profile_index ?? ''}
                             onChange={e => setCfgDraft({...cfgDraft, emulator_profile_index: e.target.value})}/>
                    </div>
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t('inst.cfg.fieldConsole')}</label>
                    <input className="input" value={cfgDraft.ldplayer_console_path || ''}
                           onChange={e => setCfgDraft({...cfgDraft, ldplayer_console_path: e.target.value})}
                           placeholder={t('inst.cfg.consolePlaceholder')}/>
                  </div>
                  <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap: 10}}>
                    <div className="form-row">
                      <label className="form-label">{t('inst.cfg.fieldMaxIps')}</label>
                      <input className="input" type="number" value={cfgDraft.max_ips ?? ''}
                             onChange={e => setCfgDraft({...cfgDraft, max_ips: e.target.value})}/>
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t('inst.cfg.fieldRunFor')}</label>
                      <input className="input" type="number" value={cfgDraft.run_for_minutes ?? ''}
                             onChange={e => setCfgDraft({...cfgDraft, run_for_minutes: e.target.value})}/>
                    </div>
                  </div>
                  <div className="row-gap" style={{gap: 16, marginTop: 6}}>
                    <label className="switch">
                      <input type="checkbox"
                             checked={String(cfgDraft.super_debug || 'no').toLowerCase() === 'yes'}
                             onChange={e => setCfgDraft({...cfgDraft, super_debug: e.target.checked ? 'yes' : 'no'})}/>
                      <span className="switch-track"><span className="switch-dot"/></span>
                      <span className="switch-label">super_debug</span>
                    </label>
                    <label className="switch">
                      <input type="checkbox"
                             checked={String(cfgDraft.terminal_logging || 'no').toLowerCase() === 'yes'}
                             onChange={e => setCfgDraft({...cfgDraft, terminal_logging: e.target.checked ? 'yes' : 'no'})}/>
                      <span className="switch-track"><span className="switch-dot"/></span>
                      <span className="switch-label">terminal_logging</span>
                    </label>
                  </div>
                </>
              )}

              {/* === BRAWL STARS API SECTION === */}
              {cfgApiDraft && (
                <>
                  <hr style={{margin:'18px 0 12px', opacity: 0.15}}/>
                  <h4 style={{margin:'2px 0 6px', fontSize: 13, opacity: 0.85}}>
                    {t('inst.cfg.section.api')}
                  </h4>
                  <div className="muted small" style={{marginBottom: 8}}>
                    {t('inst.cfg.api.hintShared')}
                  </div>
                  <div className="form-row">
                    <label className="form-label">{t('inst.cfg.api.tag')}</label>
                    <input className="input" value={cfgApiDraft.player_tag || ''}
                           placeholder="#XXXXXX"
                           onChange={e => setCfgApiDraft({...cfgApiDraft, player_tag: e.target.value})}/>
                  </div>
                </>
              )}

              {/* === DISCORD SECTION === */}
              {cfgWhDraft && (
                <>
                  <hr style={{margin:'18px 0 12px', opacity: 0.15}}/>
                  <h4 style={{margin:'2px 0 6px', fontSize: 13, opacity: 0.85}}>
                    {t('inst.cfg.section.discord')}
                  </h4>
                  {/* Toggle "use global webhook" — default ON when the
                      per-instance URL is empty. ON saves webhook_url=""
                      so discord_notifier.load_webhook_settings auto-falls
                      back to general_config.personal_webhook. OFF shows the
                      override field for users who want a separate channel
                      per emulator. */}
                  <label className="switch" style={{marginBottom: 8}}>
                    <input type="checkbox"
                           checked={!String(cfgWhDraft.webhook_url || '').trim()}
                           onChange={e => setCfgWhDraft({
                             ...cfgWhDraft,
                             webhook_url: e.target.checked ? '' : (cfgWhDraft.webhook_url_draft || ''),
                             // Stash the user's last typed URL so toggling
                             // global ON then OFF restores it.
                             webhook_url_draft: e.target.checked
                               ? (cfgWhDraft.webhook_url || cfgWhDraft.webhook_url_draft || '')
                               : (cfgWhDraft.webhook_url_draft || ''),
                           })}/>
                    <span className="switch-track"><span className="switch-dot"/></span>
                    <span className="switch-label">{t('inst.cfg.webhook.useGlobal')}</span>
                  </label>
                  {!String(cfgWhDraft.webhook_url || '').trim() ? (
                    <div className="muted small" style={{marginTop: -2, marginBottom: 8}}>
                      {t('inst.cfg.webhook.useGlobalHint')}
                    </div>
                  ) : (
                    <div className="form-row">
                      <label className="form-label">{t('inst.cfg.webhook.url')}</label>
                      <input className="input" value={cfgWhDraft.webhook_url || ''}
                             placeholder="https://discord.com/api/webhooks/…"
                             autoFocus
                             onChange={e => setCfgWhDraft({...cfgWhDraft, webhook_url: e.target.value, webhook_url_draft: e.target.value})}/>
                    </div>
                  )}
                  <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap: 10}}>
                    <div className="form-row">
                      <label className="form-label">{t('inst.cfg.webhook.username')}</label>
                      <input className="input" value={cfgWhDraft.username || 'PylaAI'}
                             onChange={e => setCfgWhDraft({...cfgWhDraft, username: e.target.value})}/>
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t('inst.cfg.webhook.discordId')}</label>
                      <input className="input" value={cfgWhDraft.discord_id || ''}
                             placeholder="123456789012345678"
                             onChange={e => setCfgWhDraft({...cfgWhDraft, discord_id: e.target.value})}/>
                    </div>
                  </div>
                  <div className="row-gap" style={{flexWrap:'wrap', gap: 12, marginTop: 6}}>
                    <label className="switch">
                      <input type="checkbox"
                             checked={!!cfgWhDraft.send_match_summary}
                             onChange={e => setCfgWhDraft({...cfgWhDraft, send_match_summary: e.target.checked})}/>
                      <span className="switch-track"><span className="switch-dot"/></span>
                      <span className="switch-label">{t('inst.cfg.webhook.matchSummary')}</span>
                    </label>
                    <label className="switch">
                      <input type="checkbox"
                             checked={cfgWhDraft.include_screenshot !== false}
                             onChange={e => setCfgWhDraft({...cfgWhDraft, include_screenshot: e.target.checked})}/>
                      <span className="switch-track"><span className="switch-dot"/></span>
                      <span className="switch-label">{t('inst.cfg.webhook.includeShot')}</span>
                    </label>
                    <label className="switch">
                      <input type="checkbox"
                             checked={!!cfgWhDraft.ping_when_stuck}
                             onChange={e => setCfgWhDraft({...cfgWhDraft, ping_when_stuck: e.target.checked})}/>
                      <span className="switch-track"><span className="switch-dot"/></span>
                      <span className="switch-label">{t('inst.cfg.webhook.pingStuck')}</span>
                    </label>
                    <label className="switch">
                      <input type="checkbox"
                             checked={!!cfgWhDraft.ping_when_target_is_reached}
                             onChange={e => setCfgWhDraft({...cfgWhDraft, ping_when_target_is_reached: e.target.checked})}/>
                      <span className="switch-track"><span className="switch-dot"/></span>
                      <span className="switch-label">{t('inst.cfg.webhook.pingTarget')}</span>
                    </label>
                  </div>
                  <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap: 10, marginTop: 6}}>
                    <div className="form-row">
                      <label className="form-label">{t('inst.cfg.webhook.pingEveryN')}</label>
                      <input className="input" type="number" value={cfgWhDraft.ping_every_x_match ?? 0}
                             onChange={e => setCfgWhDraft({...cfgWhDraft, ping_every_x_match: e.target.value})}/>
                    </div>
                    <div className="form-row">
                      <label className="form-label">{t('inst.cfg.webhook.pingEveryMin')}</label>
                      <input className="input" type="number" value={cfgWhDraft.ping_every_x_minutes ?? 0}
                             onChange={e => setCfgWhDraft({...cfgWhDraft, ping_every_x_minutes: e.target.value})}/>
                    </div>
                  </div>
                  <div style={{marginTop: 10}}>
                    <button className="btn ghost xs" onClick={sendWebhookTest}
                            disabled={whTesting}>
                      {whTesting ? t('inst.cfg.webhook.testing') : t('inst.cfg.webhook.test')}
                    </button>
                  </div>
                </>
              )}
            </div>
            <div className="modal-foot">
              <button className="btn ghost" onClick={closeCfgEditor}>{t('inst.create.cancel')}</button>
              <button className="btn primary" onClick={saveCfgDraft}>{t('inst.session.save')}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
Object.assign(window, { BrawlersPage, ModesPage, LogsPage, InstancesPage });
