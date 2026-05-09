// PylaAI — REST + WebSocket client
(function () {
  const API_BASE = '/api';

  async function req(path, opts) {
    const r = await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...opts,
    });
    if (!r.ok) {
      let detail = `${r.status} ${r.statusText}`;
      try { const j = await r.json(); if (j && j.detail) detail = j.detail; } catch (_) {}
      const err = new Error(detail); err.status = r.status; throw err;
    }
    if (r.status === 204) return null;
    return r.json();
  }

  const API = {
    getBrawlers:  (instance_id = null) =>
      req(`/brawlers${instance_id ? `?instance_id=${instance_id}` : ''}`),
    getStats:     (opts = {}) => {
      // opts: { instance_id?: number, aggregate?: boolean }
      const qs = new URLSearchParams();
      if (opts.instance_id) qs.set('instance_id', String(opts.instance_id));
      if (opts.aggregate === false) qs.set('aggregate', 'false');
      const s = qs.toString();
      return req(`/stats${s ? '?' + s : ''}`);
    },
    getState:     () => req('/state'),
    getConfig:    (name) => req(`/config/${name}`),
    putConfig:    (name, values) => req(`/config/${name}`, { method: 'PUT', body: JSON.stringify({ values }) }),
    getHistory:   (params) => {
      const qs = params ? ('?' + new URLSearchParams(
        Object.fromEntries(Object.entries(params).filter(([, v]) => v != null && v !== ''))
      ).toString()) : '';
      return req(`/match-history${qs}`);
    },
    getSessions:  (limit) => req(`/sessions${limit ? `?limit=${limit}` : ''}`),
    start:        (cfg) => req('/start',  { method: 'POST', body: JSON.stringify(cfg) }),
    stop:         () => req('/stop',   { method: 'POST' }),
    pause:        () => req('/pause',  { method: 'POST' }),
    resume:       () => req('/resume', { method: 'POST' }),
    scanBrawler:  (brawler) => req('/scan-brawler', { method: 'POST', body: JSON.stringify({ brawler }) }),
    scanAllBrawlers: () => req('/scan-all-brawlers', { method: 'POST' }),
    getBrawlStarsApiTrophies: () => req('/brawl-stars-api/trophies'),
    syncAllFromBsApi: () => req('/brawl-stars-api/sync-all', { method: 'POST' }),
    pushAll:      (target) => req('/push-all', { method: 'POST', body: JSON.stringify({ target_trophies: target }) }),
    listPerfProfiles: () => req('/performance-profile/list'),
    applyPerfProfile: (profile) => req('/performance-profile/apply', { method: 'POST', body: JSON.stringify({ profile }) }),
    listPlaystyles:   () => req('/playstyles/list'),
    getPlaystyleSource: (file) => req(`/playstyles/source?file=${encodeURIComponent(file)}`),
    uploadPlaystyle:  async (file, overwrite) => {
      const fd = new FormData();
      fd.append('file', file);
      const url = `/api/playstyles/upload${overwrite ? '?overwrite=true' : ''}`;
      const r = await fetch(url, { method: 'POST', body: fd });
      if (!r.ok) {
        let detail = `${r.status} ${r.statusText}`;
        try { const j = await r.json(); if (j && j.detail) detail = j.detail; } catch (_) {}
        const err = new Error(detail); err.status = r.status; throw err;
      }
      return r.json();
    },
    deletePlaystyle:  (file) => req(`/playstyles/${encodeURIComponent(file)}`, { method: 'DELETE' }),

    // ── Multi-emulator instance management ─────────────────────────
    listInstances:   () => req('/instances'),
    createInstance:  (payload) => req('/instances', { method: 'POST', body: JSON.stringify(payload) }),
    deleteInstance:  (id) => req(`/instances/${id}`, { method: 'DELETE' }),
    getInstance:     (id) => req(`/instances/${id}`),
    startInstance:   (id, cfg) => req(`/instances/${id}/start`, { method: 'POST', body: JSON.stringify(cfg) }),
    stopInstance:    (id) => req(`/instances/${id}/stop`, { method: 'POST' }),
    getInstanceLogs: (id, lines = 200, file = null) => {
      const qs = new URLSearchParams({ lines: String(lines) });
      if (file) qs.set('file', file);
      return req(`/instances/${id}/logs?${qs.toString()}`);
    },
    startAllInstances: (session, instance_ids = null) =>
      // session=null tells the backend to use each instance's saved session
      // (per-instance individual sessions UX).
      req('/instances/start_all', { method: 'POST', body: JSON.stringify({ session, instance_ids }) }),
    stopAllInstances: (instance_ids = null) =>
      req('/instances/stop_all', { method: 'POST', body: JSON.stringify({ instance_ids }) }),
    discoverEmulators: (emulator = 'LDPlayer') =>
      req(`/emulators/discover?emulator=${encodeURIComponent(emulator)}`),
    getInstanceSession: (id) => req(`/instances/${id}/session`),
    putInstanceSession: (id, session) =>
      req(`/instances/${id}/session`, { method: 'PUT', body: JSON.stringify({ session }) }),
    clearInstanceSession: (id) =>
      req(`/instances/${id}/session`, { method: 'DELETE' }),
    setInstanceAutoRestart: (id, enabled) =>
      req(`/instances/${id}/auto_restart`, { method: 'PUT', body: JSON.stringify({ enabled }) }),
    restartInstanceEmulator: (id) =>
      req(`/instances/${id}/restart_emulator`, { method: 'POST' }),
    getInstanceConfig: (id, section) =>
      req(`/instances/${id}/config/${section}`),
    putInstanceConfig: (id, section, values) =>
      req(`/instances/${id}/config/${section}`, { method: 'PUT', body: JSON.stringify({ values }) }),
    renameInstance: (id, name) =>
      req(`/instances/${id}/name`, { method: 'PUT', body: JSON.stringify({ name }) }),
    pushAllInstance: (id, target) =>
      req(`/instances/${id}/push_all`, { method: 'POST', body: JSON.stringify({ target_trophies: target }) }),
    testInstanceWebhook: (id) =>
      req(`/instances/${id}/webhook/test`, { method: 'POST' }),
    getInstancesDashboard: () => req('/instances-dashboard'),
    // WebSocket for live log tail. Returns {close} immediately, calls onLine
    // for each line (with {line, backfill, error?}).
    streamInstanceLogs: (id, onMessage) => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${proto}://${location.host}/api/instances/${id}/logs/stream`);
      ws.onmessage = (e) => {
        try { onMessage(JSON.parse(e.data)); } catch (_) {}
      };
      return { close: () => { try { ws.close(); } catch (_) {} } };
    },
  };

  // ── WebSocket stream with auto-reconnect ──────────────────────────
  function createStream(onMessage) {
    let ws = null;
    let closed = false;
    let retry = 1000;

    function connect() {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      ws = new WebSocket(`${proto}://${location.host}/api/stream`);
      ws.onopen = () => { retry = 1000; };
      ws.onmessage = (e) => {
        try { onMessage(JSON.parse(e.data)); } catch (_) {}
      };
      ws.onclose = () => {
        if (closed) return;
        setTimeout(connect, retry);
        retry = Math.min(retry * 1.5, 8000);
      };
      ws.onerror = () => { try { ws.close(); } catch (_) {} };
    }
    connect();
    return {
      close: () => { closed = true; try { ws && ws.close(); } catch (_) {} },
    };
  }

  window.PylaAPI = API;
  window.createPylaStream = createStream;
})();
