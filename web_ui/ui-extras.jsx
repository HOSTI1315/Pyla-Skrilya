// PylaAI — UX extras (client-only): toast system, keyboard navigation
// No bot-dependent pieces here — pure UI polish that works without a
// connected device.

// ── Toast system ───────────────────────────────────────────────
// Global dispatch so any module can fire a toast without prop-drilling.
// Usage: window.pylaToast('Queued', {kind:'ok', ttl:3000})
function ToastHost() {
  const [items, setItems] = React.useState([]);
  const idRef = React.useRef(1);

  React.useEffect(() => {
    window.pylaToast = (msg, opts = {}) => {
      const id = idRef.current++;
      const ttl = opts.ttl ?? 3200;
      setItems(cur => [...cur, { id, msg, kind: opts.kind || 'info', icon: opts.icon }]);
      if (ttl > 0) setTimeout(() => {
        setItems(cur => cur.filter(t => t.id !== id));
      }, ttl);
    };
    return () => { delete window.pylaToast; };
  }, []);

  const dismiss = (id) => setItems(cur => cur.filter(t => t.id !== id));

  return (
    <div className="toast-host" aria-live="polite">
      {items.map(it => (
        <div key={it.id} className="toast" data-kind={it.kind} onClick={() => dismiss(it.id)}>
          <span className="toast-icon" aria-hidden>
            {it.icon || (it.kind === 'ok' ? '✓' : it.kind === 'warn' ? '⚠' : it.kind === 'err' ? '✕' : '·')}
          </span>
          <span className="toast-msg">{it.msg}</span>
        </div>
      ))}
    </div>
  );
}

// ── Keyboard navigation ────────────────────────────────────────
// D→Dashboard, B→Brawlers, M→Modes, T→Stats, L→Logs, S→Settings,
// G→open project site (github), ?→help cheatsheet.
// Ignored when user is typing in an input or a modal is open.
const PYLA_SITE_URL = 'https://github.com/pylaai/pylaai';
function useKeyboardNav(setTab, { isModalOpen }) {
  const [helpOpen, setHelpOpen] = React.useState(false);
  React.useEffect(() => {
    const onKey = (e) => {
      if (isModalOpen) return;
      const el = document.activeElement;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      const map = {
        d: 'dashboard',
        b: 'brawlers',
        m: 'modes',
        t: 'stats',
        l: 'logs',
        s: 'settings',
      };
      if (map[k]) {
        setTab(map[k]);
        window.pylaToast?.(`→ ${map[k]}`, { kind: 'info', ttl: 1400 });
        e.preventDefault();
        return;
      }
      if (k === 'g') {
        window.open(PYLA_SITE_URL, '_blank', 'noopener');
        window.pylaToast?.('Открываю сайт проекта', { kind: 'info', icon: '↗' });
        e.preventDefault();
        return;
      }
      if (e.key === '?' || (e.key === '/' && e.shiftKey)) {
        setHelpOpen(v => !v);
        e.preventDefault();
      } else if (e.key === 'Escape') {
        setHelpOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setTab, isModalOpen]);
  return { helpOpen, setHelpOpen };
}

function KeyboardHelp({ open, onClose }) {
  if (!open) return null;
  const rows = [
    { k: 'D', label: 'Панель' },
    { k: 'B', label: 'Бравлеры' },
    { k: 'M', label: 'Режимы' },
    { k: 'T', label: 'Статистика' },
    { k: 'L', label: 'Логи' },
    { k: 'S', label: 'Настройки' },
    { k: 'G', label: 'Сайт проекта ↗' },
    { k: '?', label: 'Эта шпаргалка' },
    { k: 'Esc', label: 'Закрыть окно / меню' },
  ];
  return (
    <div className="kbd-help-backdrop" onClick={onClose}>
      <div className="kbd-help" onClick={e => e.stopPropagation()}>
        <div className="kbd-help-head">
          <b>Горячие клавиши</b>
          <button className="btn ghost xs" onClick={onClose}>×</button>
        </div>
        <div className="kbd-help-body">
          {rows.map(r => (
            <div key={r.k} className="kbd-help-row">
              <kbd>{r.k}</kbd>
              <span>{r.label}</span>
            </div>
          ))}
        </div>
        <div className="kbd-help-foot muted small">
          Нажатия игнорируются в полях ввода.
        </div>
      </div>
    </div>
  );
}

// ── ETA chip ───────────────────────────────────────────────────
// Projects time-to-goal from recent progress. Needs a start timestamp
// (sStats.started_at), current value, and target. Returns either a
// "2h 14m" label or "—" when there's no useful signal yet.
function useEtaToGoal({ startedAt, current, target, ipsOrSpeed, curveTs, curveVal }) {
  return React.useMemo(() => {
    if (!startedAt) return null;
    const tgt = +target || 0;
    const cur = +current || 0;
    if (tgt <= 0 || cur >= tgt) return { done: cur >= tgt && tgt > 0, label: cur >= tgt && tgt > 0 ? 'цель достигнута' : null };
    // Use trophy curve if available: rate = (last - first) / (lastTs - firstTs)
    let rate = 0;
    if (Array.isArray(curveTs) && Array.isArray(curveVal) && curveTs.length >= 2) {
      const n = curveTs.length;
      // sample last ~10 points so it's reactive; fall back to full range
      const k = Math.min(10, n);
      const dt = curveTs[n - 1] - curveTs[n - k];
      const dv = curveVal[n - 1] - curveVal[n - k];
      if (dt > 0) rate = dv / dt;   // units/sec
    }
    if (!rate) {
      const elapsed = Math.max(1, Date.now() / 1000 - startedAt);
      // fall back to net / elapsed — still meaningful even if curve missing
      rate = (cur - curveVal?.[0] ?? cur) / elapsed;
    }
    if (!Number.isFinite(rate) || rate <= 0) return { done: false, label: null };
    const remaining = tgt - cur;
    const eta = remaining / rate; // seconds
    if (!Number.isFinite(eta) || eta <= 0) return { done: false, label: null };
    const h = Math.floor(eta / 3600);
    const m = Math.floor((eta % 3600) / 60);
    const label = h > 0 ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`;
    return { done: false, label };
  }, [startedAt, current, target, ipsOrSpeed, curveTs?.length, curveTs?.[curveTs?.length - 1], curveVal?.[curveVal?.length - 1]]);
}

function EtaChip({ eta }) {
  if (!eta || (!eta.label && !eta.done)) return null;
  if (eta.done) {
    return (
      <span className="eta-chip done" title="Цель достигнута">
        <span className="eta-dot"/>
        <span>✓ готово</span>
      </span>
    );
  }
  return (
    <span className="eta-chip" title="Прогноз времени до цели">
      <span className="eta-dot"/>
      <span>ETA <b style={{color:'var(--fg)'}}>{eta.label}</b></span>
    </span>
  );
}

// ── Status ticker ───────────────────────────────────────────────
// Short "ips · 🏆 +12 · W 4/7" summary next to the status pill.
function StatusTicker({ state, ips, netTrophies, wins, games, winStreak }) {
  if (state !== 'running' && state !== 'paused') return null;
  const pos = (netTrophies || 0) > 0;
  const neg = (netTrophies || 0) < 0;
  const sign = pos ? '+' : '';
  return (
    <div className="status-ticker" title="Текущая сессия">
      {ips ? <>
        <span><span className="tk-val">{(+ips).toFixed(1)}</span><span className="tk-key"> ips</span></span>
        <span className="tk-sep"/>
      </> : null}
      <span>
        <span className="tk-key">🏆 </span>
        <span className={`tk-val ${pos ? 'tk-pos' : neg ? 'tk-neg' : ''}`}>
          {sign}{netTrophies || 0}
        </span>
      </span>
      <span className="tk-sep"/>
      <span>
        <span className="tk-key">W </span>
        <span className="tk-val">{wins || 0}/{games || 0}</span>
      </span>
      {winStreak > 0 && <>
        <span className="tk-sep"/>
        <span><span className="tk-key">🔥</span> <span className="tk-val">{winStreak}</span></span>
      </>}
    </div>
  );
}

// ── Skeleton primitives ─────────────────────────────────────────
function Skel({ w = '100%', h = 12, r, style }) {
  return <span className="skel" style={{
    display: 'block',
    width: typeof w === 'number' ? `${w}px` : w,
    height: typeof h === 'number' ? `${h}px` : h,
    borderRadius: r != null ? r : undefined,
    ...style,
  }}/>;
}

function BrawlerSkeleton() {
  return (
    <div className="skel-card">
      <div className="skel-row" style={{justifyContent:'space-between'}}>
        <Skel w={44} h={44} r={8}/>
        <Skel w={48} h={14} r={4}/>
      </div>
      <Skel w="60%" h={14}/>
      <div className="skel-row" style={{gap:14}}>
        <div style={{flex:1}}>
          <Skel w={40} h={9} style={{marginBottom:4}}/>
          <Skel w="70%" h={14}/>
        </div>
        <div style={{flex:1}}>
          <Skel w={40} h={9} style={{marginBottom:4}}/>
          <Skel w="70%" h={14}/>
        </div>
      </div>
      <Skel w="100%" h={3} r={999}/>
    </div>
  );
}

Object.assign(window, {
  ToastHost,
  useKeyboardNav, KeyboardHelp,
  useEtaToGoal, EtaChip, StatusTicker,
  Skel, BrawlerSkeleton,
});
