import { useCallback, useEffect, useMemo, useState } from 'react';

// All data comes from the local Python server (main.py):
//   /api/state   camera status + Firebase data (mirrored) or local data
//   /video_feed  live annotated camera stream (MJPEG)
const POLL_MS = 1000;
const ESP32_TIMEOUT_MS = 20000;
const EXPECTED_BIN = { PERFECT: 'BIN1', DEFECT: 'BIN2', INVALID: 'BIN2' };

function fmtTime(ms) {
  if (!ms) return '—';
  const d = new Date(Number(ms));
  if (Number.isNaN(d.getTime())) return '—';
  return new Intl.DateTimeFormat('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(d);
}

function fmtDateTime(ms) {
  if (!ms) return '—';
  const d = new Date(Number(ms));
  if (Number.isNaN(d.getTime())) return '—';
  return new Intl.DateTimeFormat('id-ID', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).format(d);
}

function pct(v) {
  const n = Number(v ?? 0);
  return Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : 0;
}

function tone(cls) {
  const c = String(cls || '').toUpperCase();
  if (c === 'PERFECT') return 'good';
  if (c === 'DEFECT') return 'bad';
  if (c === 'INVALID') return 'warn';
  return 'neutral';
}

async function post(url, body) {
  const res = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || json.ok === false) throw new Error(json.error || `HTTP ${res.status}`);
  return json;
}

// KPI definitions follow the proposal (section E.1).
function computeKpis(events, session, now) {
  const done = events.filter((e) => e.sortedAtMs && e.detectedAtMs && e.sortedAtMs >= e.detectedAtMs);
  const avgCt = done.length
    ? done.reduce((s, e) => s + (e.sortedAtMs - e.detectedAtMs), 0) / done.length / 1000
    : null;

  const start = Number(session?.startedAtMs) || (events.length ? Math.min(...events.map((e) => e.detectedAtMs || now)) : null);
  const end = session?.status === 'stopped' && session?.stoppedAtMs ? Number(session.stoppedAtMs) : now;
  const minutes = start ? Math.max((end - start) / 60000, 1 / 60) : null;
  const rate = minutes ? events.length / minutes : null;

  const confirmed = events.filter((e) => e.actualBin);
  const correct = confirmed.filter((e) => e.actualBin === EXPECTED_BIN[e.class]);
  const accuracy = confirmed.length ? (correct.length / confirmed.length) * 100 : null;

  return { avgCt, rate, accuracy, confirmed: confirmed.length, correct: correct.length, sorted: done.length };
}

function MetricCard({ label, value, toneClass, note }) {
  return (
    <article className="metric-card">
      <div className="metric-label">{label}</div>
      <div className={`metric-value ${toneClass || ''}`}>{value}</div>
      <div className="metric-note">{note}</div>
    </article>
  );
}

function StatusPill({ label, state }) {
  return <span className={`status-pill ${state}`}><i />{label}</span>;
}

function CameraPanel({ camera, streamKey, onControl, busy }) {
  const [broken, setBroken] = useState(false);
  useEffect(() => { setBroken(false); }, [streamKey, camera.running]);
  const showStream = camera.running && !broken;
  const calibrating = camera.running && !camera.calibrated;

  return (
    <article className="panel camera-panel">
      <div className="panel-heading">
        <div>
          <div className="panel-title">LIVE CAMERA & INSPECTION</div>
          <div className="panel-subtitle">Kamera {camera.cameraIndex ?? '-'} · area kuning = ROI inspeksi</div>
        </div>
        <div className="camera-actions">
          {camera.running
            ? <button className="ghost-button" disabled={busy} onClick={() => onControl('stop')}>Stop</button>
            : <button className="primary-button" disabled={busy} onClick={() => onControl('start')}>Start Camera</button>}
          <button className="ghost-button" disabled={busy || !camera.running} onClick={() => onControl('recalibrate')}>Recalibrate</button>
          <button className="ghost-button" disabled={busy || !camera.running} onClick={() => onControl('debug')}>Debug: {camera.debug ? 'On' : 'Off'}</button>
        </div>
      </div>
      <div className="camera-frame">
        {showStream ? (
          <img className="camera-stream" src={`/video_feed?k=${streamKey}`} alt="Live camera" onError={() => setBroken(true)} />
        ) : (
          <div className="camera-placeholder">
            <div className="camera-symbol"><span /></div>
            <div className="camera-main">{camera.running ? 'Menyambungkan stream kamera…' : 'Kamera belum berjalan'}</div>
            <div className="camera-caption">
              {camera.error || 'Klik Start Camera. Kosongkan conveyor saat kalibrasi latar belakang.'}
            </div>
          </div>
        )}
      </div>
      <div className="camera-footer">
        <span>{calibrating ? `KALIBRASI ${Math.round((camera.calibrationProgress || 0) * 100)}%` : `GATE: ${camera.gate || '-'}`}</span>
        {camera.running && (
          <span className={camera.fps && camera.fps < 20 ? 'warn-text' : ''}
            title="Frame per detik dari webcam. Di bawah 20 FPS objek di belt yang berjalan mudah terlewat: tambah cahaya.">
            {camera.fps ? `${Math.round(camera.fps)} FPS${camera.fps < 20 ? ' · kurang cahaya?' : ''}` : '— FPS'}
          </span>
        )}
        <strong className={camera.running ? 'good-text' : 'muted'}>{camera.running ? (calibrating ? 'CALIBRATING' : 'RUNNING') : 'OFFLINE'}</strong>
      </div>
    </article>
  );
}

function Dashboard({ state, connection, onControl, onConfirm, busy, message, streamKey, now }) {
  const camera = state?.camera || {};
  const data = state?.data || {};
  const stats = data.statistics || {};
  const vision = data.vision || {};
  const conveyor = data.conveyor || {};
  const session = data.session || {};

  const events = useMemo(() => Object.entries(data.detections || {})
    .map(([id, e]) => ({ ...e, id, eventId: e?.eventId || id, class: String(e?.class || 'INVALID').toUpperCase() }))
    .sort((a, b) => (b.id > a.id ? 1 : -1)), [data.detections]);
  const sessionEvents = useMemo(
    () => (session.id ? events.filter((e) => e.sessionId === session.id) : events),
    [events, session.id],
  );
  const kpi = computeKpis(sessionEvents, session, now);

  const total = Number(stats.total || 0);
  const perfect = Number(stats.perfect || 0);
  const defect = Number(stats.defect || 0);
  const invalid = Number(stats.invalid || 0);
  const ratio = (v) => (total > 0 ? Math.round((v / total) * 100) : 0);

  const heartbeat = Number(conveyor.lastHeartbeatMs || 0);
  const espOnline = state?.source === 'firebase' && heartbeat > 0 && now - heartbeat < ESP32_TIMEOUT_MS;
  const fbStatus = state?.firebase?.status || '—';
  const lastClass = String(vision.lastClass || '').toUpperCase();
  const coverage = pct(vision.redCoverage);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="heading-block">
          <div className="eyebrow"><span className="brand-dot" /> CONVEYOR SORTING SYSTEM · MINI MES</div>
          <h1>Quality Inspection <span className="web-tag">MERAH = PERFECT</span></h1>
        </div>
      </header>

      <main className="page-content">
        <section className="status-row">
          <StatusPill label={`SERVER: ${connection}`} state={connection === 'ONLINE' ? 'online' : 'offline'} />
          <StatusPill label={`KAMERA: ${camera.running ? 'ON' : 'OFF'}`} state={camera.running ? 'online' : 'offline'} />
          <StatusPill label={`FIREBASE: ${fbStatus}`} state={fbStatus === 'ONLINE' || fbStatus === 'READY' ? 'online' : 'offline'} />
          <StatusPill label={`ESP32: ${espOnline ? 'ONLINE' : 'OFFLINE'}`} state={espOnline ? 'online' : 'offline'} />
          <span className="updated-label">Sesi {session.id || '-'} · sumber data: {state?.source === 'firebase' ? 'Firebase' : 'lokal'}</span>
        </section>

        <section className="metrics-grid">
          <MetricCard label="TOTAL INSPECTION" value={total.toLocaleString('id-ID')} note="Seluruh objek diperiksa" />
          <MetricCard label="PERFECT" value={perfect.toLocaleString('id-ID')} toneClass="good-text" note={`${ratio(perfect)}% · merah polos`} />
          <MetricCard label="DEFECT" value={defect.toLocaleString('id-ID')} toneClass="bad-text" note={`${ratio(defect)}% · bercorak / bukan merah`} />
          <MetricCard label="INVALID" value={invalid.toLocaleString('id-ID')} toneClass="warn-text" note={`${ratio(invalid)}% · gagal dibaca`} />
        </section>

        <section className="metrics-grid">
          <MetricCard label="AVG CYCLE TIME" value={kpi.avgCt == null ? '—' : `${kpi.avgCt.toFixed(2)} s`} note={`deteksi → servo selesai · ${kpi.sorted} objek tersortir`} />
          <MetricCard label="PRODUCTION RATE" value={kpi.rate == null ? '—' : `${kpi.rate.toFixed(1)}/min`} note={`${sessionEvents.length} objek pada sesi ini`} />
          <MetricCard label="SORTING ACCURACY" value={kpi.accuracy == null ? '—' : `${kpi.accuracy.toFixed(1)}%`} note={`${kpi.correct}/${kpi.confirmed} dikonfirmasi operator`} />
          <MetricCard label="ESP32 SORTED" value={kpi.sorted} note={espOnline ? `RSSI ${conveyor.wifiRssi ?? '-'} dBm` : 'ESP32 belum mengirim heartbeat'} />
        </section>

        <section className="main-grid">
          <CameraPanel camera={camera} streamKey={streamKey} onControl={onControl} busy={busy} />

          <div className="side-stack">
            <article className="panel latest-panel">
              <div className="panel-title">HASIL INSPEKSI TERAKHIR</div>
              {lastClass ? (
                <>
                  <div className={`latest-result ${tone(lastClass)}`}>{lastClass}</div>
                  <div className="latest-time">{vision.lastEventId} · {fmtDateTime(vision.lastDetectionMs)}</div>
                  <div className="coverage-row"><span>Red coverage</span><strong>{(coverage * 100).toFixed(1)}%</strong></div>
                  <div className="progress-track"><div className="progress-fill coverage-fill" style={{ width: `${coverage * 100}%` }} /></div>
                </>
              ) : <div className="empty-state compact-empty">Belum ada objek diperiksa</div>}
            </article>

            <article className="panel conveyor-panel">
              <div className="panel-title">ESP32 & SERVO</div>
              <div className="info-line"><span>Status</span><strong className={espOnline ? 'good-text' : 'muted'}>{espOnline ? 'ONLINE' : 'OFFLINE'}</strong></div>
              <div className="info-line"><span>Servo</span><strong>{conveyor.servoState || '—'}</strong></div>
              <div className="info-line"><span>Antrean sortir</span><strong>{conveyor.queueLength ?? '—'}</strong></div>
              <div className="info-line"><span>Heartbeat</span><strong>{fmtTime(heartbeat)}</strong></div>
              <div className="info-line"><span>Aturan</span><strong>PERFECT → BIN1 · lainnya → BIN2</strong></div>
            </article>

            <article className="panel connection-panel">
              <div className="panel-title">DISTRIBUSI</div>
              {[
                { label: 'Perfect', value: perfect, tone: 'bar-good' },
                { label: 'Defect', value: defect, tone: 'bar-bad' },
                { label: 'Invalid', value: invalid, tone: 'bar-warn' },
              ].map((item) => (
                <div className="distribution-item" key={item.label}>
                  <div className="distribution-label"><span>{item.label}</span><strong>{item.value} <small>({ratio(item.value)}%)</small></strong></div>
                  <div className="progress-track"><div className={`progress-fill ${item.tone}`} style={{ width: `${ratio(item.value)}%` }} /></div>
                </div>
              ))}
              {state?.firebase?.error && <div className="hint small-hint">{state.firebase.error}</div>}
            </article>
          </div>
        </section>

        <section className="panel history-panel">
          <div className="panel-heading history-heading">
            <div>
              <div className="panel-title">INSPECTION HISTORY</div>
              <div className="panel-subtitle">20 event terbaru · konfirmasi wadah tempat balok benar-benar jatuh untuk sorting accuracy</div>
            </div>
            <span className="updated-label">Terbaru di atas</span>
          </div>
          {events.length ? (
            <div className="table-wrap">
              <table>
                <thead><tr><th>EVENT ID</th><th>WAKTU</th><th>HASIL</th><th>RED COVERAGE</th><th>ESP32</th><th>CYCLE TIME</th><th>WADAH AKTUAL</th></tr></thead>
                <tbody>{events.slice(0, 20).map((e) => (
                  <tr key={e.id}>
                    <td className="event-id">{e.eventId}</td>
                    <td>{fmtTime(e.detectedAtMs)}</td>
                    <td><span className={`result-tag ${tone(e.class)}`}>{e.class}</span></td>
                    <td>{(pct(e.redCoverage) * 100).toFixed(1)}%</td>
                    <td>{e.sortAction || <span className="muted">{state?.source === 'firebase' ? 'menunggu' : 'tanpa Firebase'}</span>}</td>
                    <td>{e.sortedAtMs && e.detectedAtMs ? `${((e.sortedAtMs - e.detectedAtMs) / 1000).toFixed(2)} s` : '—'}</td>
                    <td>
                      <div className="bin-buttons">
                        {['BIN1', 'BIN2'].map((bin) => (
                          <button
                            key={bin}
                            className={`bin-button ${e.actualBin === bin ? (bin === EXPECTED_BIN[e.class] ? 'is-correct' : 'is-wrong') : ''}`}
                            disabled={busy}
                            onClick={() => onConfirm(e.eventId, bin)}
                          >{bin}</button>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          ) : <div className="empty-state">Belum ada riwayat inspeksi. Letakkan balok di conveyor setelah kalibrasi selesai.</div>}
        </section>
        <footer className="page-footer">MES CONVEYOR SORTING SYSTEM <span>•</span> BIN1 = lurus (PERFECT) <span>•</span> BIN2 = dibelokkan servo (DEFECT/INVALID)</footer>
      </main>
      {message && <div className="database-error">{message}</div>}
    </div>
  );
}

export default function App() {
  const [state, setState] = useState(null);
  const [connection, setConnection] = useState('CONNECTING');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [streamKey, setStreamKey] = useState(0);
  const [now, setNow] = useState(Date.now());

  const refresh = useCallback(async () => {
    try {
      const res = await fetch('/api/state', { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setState(await res.json());
      setConnection('ONLINE');
    } catch {
      setConnection('OFFLINE');
    }
    setNow(Date.now());
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    if (!message) return undefined;
    const id = setTimeout(() => setMessage(''), 5000);
    return () => clearTimeout(id);
  }, [message]);

  const onControl = async (action) => {
    setBusy(true);
    try {
      await post('/api/control', { action });
      if (action === 'start') setStreamKey((k) => k + 1);
      await refresh();
    } catch (err) {
      setMessage(`Gagal ${action}: ${err.message}`);
    } finally {
      setBusy(false);
    }
  };

  const onConfirm = async (eventId, actualBin) => {
    setBusy(true);
    try {
      await post('/api/confirm', { eventId, actualBin });
      await refresh();
    } catch (err) {
      setMessage(`Konfirmasi gagal: ${err.message}`);
    } finally {
      setBusy(false);
    }
  };

  if (!state && connection === 'OFFLINE') {
    return (
      <main className="setup-wrap">
        <section className="setup-card">
          <div className="eyebrow"><span className="brand-dot" /> CONVEYOR SORTING SYSTEM</div>
          <h1>Server Python belum berjalan</h1>
          <p>Jalankan <code>python main.py</code> dari folder proyek, lalu buka <code>http://127.0.0.1:8765</code>.</p>
        </section>
      </main>
    );
  }
  if (!state) return <div className="loading-screen">Memuat dashboard…</div>;

  return (
    <Dashboard
      state={state} connection={connection} onControl={onControl} onConfirm={onConfirm}
      busy={busy} message={message} streamKey={streamKey} now={now}
    />
  );
}
