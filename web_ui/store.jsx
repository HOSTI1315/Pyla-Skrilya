// PylaAI — live store: wraps the REST API + WebSocket stream into hooks.
// Falls back to the mock data in data.jsx if the API is unreachable, so the
// prototype still renders.

const PYLA_COLORS = ['#F8B733','#2D7DD2','#E85D75','#8E6D3C','#D13B3B','#8FB339','#C36CD6','#5FAD56','#F7A928','#D97441','#6EBAA7','#4E4B87','#5B8DEF','#B45EE8','#64A33B','#F2A33A','#E25858','#E56BAF'];
function colorForKey(k) {
  let h = 0; for (let i = 0; i < k.length; i++) h = (h * 31 + k.charCodeAt(i)) & 0xffff;
  return PYLA_COLORS[h % PYLA_COLORS.length];
}
function firstGlyph(name) {
  const ch = (name || '').trim().charAt(0);
  return ch || '?';
}

// ── Live brawlers ──────────────────────────────────────────────────
function _mapBrawlers(payload) {
  return (payload || []).map((b) => ({
    id: b.key,
    key: b.key,
    name: b.name,
    name_en: b.name_en || (b.key || '').toUpperCase(),
    rarity: 'Rare',
    trophies: Number.isFinite(b.trophies) ? b.trophies : 0,
    streak: Number.isFinite(b.streak) ? b.streak : 0,
    scanned_at: b.scanned_at || null,
    games: Number.isFinite(b.games) ? b.games : 0,
    wins: Number.isFinite(b.wins) ? b.wins : 0,
    losses: Number.isFinite(b.losses) ? b.losses : 0,
    draws: Number.isFinite(b.draws) ? b.draws : 0,
    wr: Number.isFinite(b.wr) ? b.wr : 0,
    color: colorForKey(b.key),
    icon: firstGlyph(b.name),
    icon_url: b.icon_url,
  }));
}

function useLiveBrawlers(instance_id = null) {
  // Only seed from window.BRAWLERS if we have a verified API snapshot from
  // earlier in this page session AND we're showing the same scope (global vs
  // a specific instance). After a hard refresh window.BRAWLERS holds the
  // 12-entry mock list from data.jsx — using it as the initial value makes
  // downstream hydration commit to the wrong roster.
  const sameScope = window.BRAWLERS_SCOPE_ID === (instance_id || 0);
  const [list, setList] = React.useState(() =>
    (window.BRAWLERS_FROM_API && sameScope) ? window.BRAWLERS : []
  );
  const [tick, setTick] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    window.PylaAPI.getBrawlers(instance_id)
      .then((data) => {
        if (cancelled || !data || !data.brawlers) return;
        const mapped = _mapBrawlers(data.brawlers);
        // Always commit — empty list is a valid result for a fresh instance.
        setList(mapped);
        if (mapped.length) {
          window.BRAWLERS = mapped;
          window.BRAWLERS_FROM_API = true;
          window.BRAWLERS_SCOPE_ID = instance_id || 0;
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [tick, instance_id]);

  const refresh = React.useCallback(() => setTick((t) => t + 1), []);
  list.refresh = refresh;
  return list;
}

// ── Live bot state via WebSocket ──────────────────────────────────
function useLiveStream() {
  const [status, setStatus] = React.useState('idle');
  const [stats, setStats] = React.useState({ games:0, wins:0, losses:0, trophies:0, net_trophies:0, win_streak:0 });
  const [device, setDevice] = React.useState({ connected:false, name:'—' });
  const [ips, setIps] = React.useState(0);
  const [currentBrawler, setCurrentBrawler] = React.useState(null);
  const [logs, setLogs] = React.useState([]);

  React.useEffect(() => {
    let cancelled = false;
    window.PylaAPI.getState().then((snap) => {
      if (cancelled || !snap) return;
      setStatus(snap.status || 'idle');
      if (snap.stats) setStats(snap.stats);
      if (snap.device) setDevice(snap.device);
      if (snap.ips != null) setIps(snap.ips);
      if (snap.current_brawler) setCurrentBrawler(snap.current_brawler);
      if (snap.log_tail) setLogs(snap.log_tail);
    }).catch(() => {});

    let lastStatus = null;
    const stream = window.createPylaStream((msg) => {
      if (msg.type === 'snapshot' && msg.snapshot) {
        const s = msg.snapshot;
        setStatus(s.status || 'idle');
        if (s.stats) setStats(s.stats);
        if (s.device) setDevice(s.device);
        if (s.log_tail) setLogs(s.log_tail);
        if (s.ips != null) setIps(s.ips);
        if (s.current_brawler) setCurrentBrawler(s.current_brawler);
      } else if (msg.type === 'status') {
        setStatus(msg.status);
        if (lastStatus && lastStatus !== msg.status) {
          if (msg.status === 'running')      window.pylaToast?.('Запущено', { kind:'ok', icon:'▶' });
          else if (msg.status === 'error')   window.pylaToast?.('Ошибка — бот остановлен', { kind:'err' });
          else if (msg.status === 'idle' && (lastStatus === 'running' || lastStatus === 'paused'))
            window.pylaToast?.('Сессия завершена', { kind:'info' });
        }
        lastStatus = msg.status;
      } else if (msg.type === 'stats') {
        setStats(msg.stats);
      } else if (msg.type === 'device') {
        setDevice(msg.device);
      } else if (msg.type === 'ips') {
        setIps(msg.ips);
      } else if (msg.type === 'brawler') {
        setCurrentBrawler(msg.brawler);
      } else if (msg.type === 'log' && msg.line) {
        setLogs((prev) => {
          const next = prev.concat([msg.line]);
          return next.length > 400 ? next.slice(next.length - 400) : next;
        });
      }
    });
    return () => { cancelled = true; stream.close(); };
  }, []);

  const startingRef = React.useRef(false);
  const start = React.useCallback(async (payload) => {
    if (startingRef.current) return;
    startingRef.current = true;
    setStatus('starting');
    try { await window.PylaAPI.start(payload); }
    catch (e) {
      console.error('start failed', e);
      setStatus('idle');
    }
    finally {
      setTimeout(() => { startingRef.current = false; }, 1500);
    }
  }, []);
  const stop   = React.useCallback(async () => {
    try { await window.PylaAPI.stop(); window.pylaToast?.('Остановлено', { kind:'info', icon:'■' }); }
    catch (e) { window.pylaToast?.('Ошибка остановки', { kind:'err' }); }
  }, []);
  const pause  = React.useCallback(async () => {
    try { await window.PylaAPI.pause(); window.pylaToast?.('Пауза', { kind:'warn', icon:'❙❙' }); }
    catch (e) { window.pylaToast?.('Ошибка паузы', { kind:'err' }); }
  }, []);
  const resume = React.useCallback(async () => {
    try { await window.PylaAPI.resume(); window.pylaToast?.('Продолжение', { kind:'ok', icon:'▶' }); }
    catch (e) { window.pylaToast?.('Ошибка', { kind:'err' }); }
  }, []);

  return { status, stats, device, ips, currentBrawler, logs, start, stop, pause, resume };
}

// ── Live aggregate stats (match history) ──────────────────────────
// instance_id=null and aggregate=true (default) -> sums global cfg + every
// instances/N/cfg/. Pass an instance id to scope to one account.
function useLiveStats(opts = {}) {
  const { instance_id = null, aggregate = true } = opts;
  const [data, setData] = React.useState({
    brawler_performance: [],
    mode_performance: [],
    recent_form: [],
    recent_matches: [],
    totals: { games:0, wins:0, losses:0, draws:0, wr:0 },
    sources: [],
  });
  const [loaded, setLoaded] = React.useState(false);

  const refresh = React.useCallback(async () => {
    try {
      const s = await window.PylaAPI.getStats({ instance_id, aggregate });
      if (s) setData(s);
    } catch (_) {}
    setLoaded(true);
  }, [instance_id, aggregate]);

  React.useEffect(() => { refresh(); }, [refresh]);

  // Refresh on every stats update pushed through WS
  React.useEffect(() => {
    const stream = window.createPylaStream((msg) => {
      if (msg && msg.type === 'stats') refresh();
    });
    return () => stream.close();
  }, [refresh]);

  return { ...data, loaded, refresh };
}

// ── Raw match history (for client-side range aggregates) ─────────
function useMatchHistory(limit = 3000) {
  const [entries, setEntries] = React.useState([]);
  const [loaded, setLoaded] = React.useState(false);

  const refresh = React.useCallback(async () => {
    try {
      const r = await window.PylaAPI.getHistory({ limit });
      if (r && Array.isArray(r.entries)) setEntries(r.entries);
    } catch (_) {}
    setLoaded(true);
  }, [limit]);

  React.useEffect(() => { refresh(); }, [refresh]);

  // Re-fetch on stats updates so a freshly-finished match shows up in the
  // range aggregates without forcing a manual reload.
  React.useEffect(() => {
    const stream = window.createPylaStream((msg) => {
      if (msg && msg.type === 'stats') refresh();
    });
    return () => stream.close();
  }, [refresh]);

  return { entries, loaded, refresh };
}

// ── Recent bot-run sessions (cfg/sessions.jsonl) ─────────────────
function useRecentSessions(limit = 20) {
  const [entries, setEntries] = React.useState([]);
  const [loaded, setLoaded] = React.useState(false);

  const refresh = React.useCallback(async () => {
    try {
      const r = await window.PylaAPI.getSessions(limit);
      if (r && Array.isArray(r.entries)) setEntries(r.entries);
    } catch (_) {}
    setLoaded(true);
  }, [limit]);

  React.useEffect(() => { refresh(); }, [refresh]);

  React.useEffect(() => {
    const stream = window.createPylaStream((msg) => {
      if (msg && (msg.type === 'session_end' || msg.type === 'state')) refresh();
    });
    return () => stream.close();
  }, [refresh]);

  return { entries, loaded, refresh };
}

// ── Instances dashboard aggregate (totals across all running instances) ──
// Powers the global "Сессия" panel so the dashboard counters reflect every
// emulator, not just the legacy single in-process bot.
function useInstancesDashboard(intervalMs = 4000) {
  const [data, setData] = React.useState({ totals: null, instances: [] });
  const [loaded, setLoaded] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await window.PylaAPI.getInstancesDashboard();
        if (!cancelled && r) setData(r);
      } catch (_) {}
      if (!cancelled) setLoaded(true);
    };
    tick();
    const id = setInterval(tick, intervalMs);
    return () => { cancelled = true; clearInterval(id); };
  }, [intervalMs]);

  return { ...data, loaded };
}

// ── Language hook ─────────────────────────────────────────────────
function useLang() {
  const [lang, setLang] = React.useState(window.getLang ? window.getLang() : 'ru');
  React.useEffect(() => {
    if (!window.onLangChange) return;
    return window.onLangChange(setLang);
  }, []);
  return [lang, (l) => window.setLang && window.setLang(l)];
}

// ── Persistent local state ────────────────────────────────────────
// Same shape as useState, but mirrors the value to localStorage under
// `key` so it survives reload. For object defaults the stored payload
// is merged on top of the default — new keys added later still appear.
function useLocalState(key, defaultValue) {
  const [value, setValue] = React.useState(() => {
    try {
      const raw = localStorage.getItem(key);
      if (raw == null) return defaultValue;
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)
          && defaultValue && typeof defaultValue === 'object' && !Array.isArray(defaultValue)) {
        return { ...defaultValue, ...parsed };
      }
      return parsed;
    } catch (_) { return defaultValue; }
  });
  React.useEffect(() => {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) {}
  }, [key, value]);
  return [value, setValue];
}

Object.assign(window, { useLiveBrawlers, useLiveStream, useLiveStats, useMatchHistory, useRecentSessions, useInstancesDashboard, useLang, useLocalState });
