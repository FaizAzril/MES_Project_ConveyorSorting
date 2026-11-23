import { useEffect, useMemo, useState } from 'react';
import { onValue, ref } from 'firebase/database';
import { db, firebaseConfigured } from './firebase.js';

const EMPTY_DATA = {
  conveyor: { motorStatus: 'unknown', deviceOnline: false },
  vision: { status: 'offline', lastClass: '', redCoverage: 0, lastDetection: '' },
  statistics: { total: 0, perfect: 0, defect: 0, invalid: 0 },
  detections: {},
};

function prettyDate(value) {
  if (!value) return 'Belum ada inspeksi';
  let date = value;
  if (typeof value === 'number') date = new Date(value < 1e12 ? value * 1000 : value);
  else date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('id-ID', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).format(date);
}

function normalizeCoverage(value) {
  const number = Number(value ?? 0);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(1, number > 1 ? number / 100 : number));
}

function classifyTone(value) {
  const result = String(value || '').toUpperCase();
  if (result === 'PERFECT') return 'good';
  if (result === 'DEFECT') return 'bad';
  if (result === 'INVALID') return 'warn';
  return 'neutral';
}

function SetupNotice() {
  return (
    <main className="setup-wrap">
      <section className="setup-card">
        <div className="eyebrow"><span className="brand-dot" /> CONVEYOR SORTING SYSTEM</div>
        <h1>Konfigurasi Firebase belum lengkap</h1>
        <p className="muted">Web dashboard sudah terpasang, tetapi konfigurasi Firebase Web App belum diisi.</p>
        <ol>
          <li>Salin <code>.env.example</code> menjadi <code>.env.local</code> di folder <code>web-dashboard</code>.</li>
          <li>Isi API Key, Auth Domain, Database URL, Project ID, dan App ID dari Firebase Console.</li>
          <li>Jalankan ulang server dengan <code>npm run dev</code>.</li>
        </ol>
        <p className="hint">Jangan letakkan <code>serviceAccountKey.json</code> di folder web. Web app menggunakan Firebase Web SDK dan Firebase Authentication.</p>
      </section>
    </main>
  );
}

function MetricCard({ label, value, tone, note }) {
  return (
    <article className="metric-card">
      <div className="metric-label">{label}</div>
      <div className={`metric-value ${tone || ''}`}>{Number(value || 0).toLocaleString('id-ID')}</div>
      <div className="metric-note">{note}</div>
    </article>
  );
}

function StatusPill({ label, state }) {
  return <span className={`status-pill ${state}`}><i />{label}</span>;
}

function Dashboard({ data, connection }) {
  const stats = data.statistics || EMPTY_DATA.statistics;
  const vision = data.vision || EMPTY_DATA.vision;
  const conveyor = data.conveyor || EMPTY_DATA.conveyor;
  const total = Number(stats.total || 0);
  const perfect = Number(stats.perfect || 0);
  const defect = Number(stats.defect || 0);
  const invalid = Number(stats.invalid || 0);
  const coverage = normalizeCoverage(vision.redCoverage);
  const currentClass = String(vision.lastClass || '').toUpperCase();
  const history = useMemo(() => Object.entries(data.detections || {}).map(([id, item]) => ({
    id,
    eventId: item?.eventId || id,
    classification: String(item?.class || 'INVALID').toUpperCase(),
    redCoverage: normalizeCoverage(item?.redCoverage),
    timestamp: item?.timestamp || '',
  })).sort((a, b) => {
    const parse = (v) => {
      if (!v) return 0;
      const d = typeof v === 'number' ? new Date(v < 1e12 ? v * 1000 : v) : new Date(v);
      return Number.isNaN(d.getTime()) ? 0 : d.getTime();
    };
    return parse(b.timestamp) - parse(a.timestamp);
  }).slice(0, 12), [data.detections]);

  const ratio = (value) => total > 0 ? Math.round((value / total) * 100) : 0;
  const visionOnline = String(vision.status || '').toLowerCase() === 'online';
  const deviceOnline = Boolean(conveyor.deviceOnline);
  const motorStatus = String(conveyor.motorStatus || 'unknown').toLowerCase();

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="heading-block">
          <div className="eyebrow"><span className="brand-dot" /> CONVEYOR SORTING SYSTEM</div>
          <h1>Quality Inspection <span className="web-tag">WEB MONITOR</span></h1>
        </div>

      </header>

      <main className="page-content">
        <section className="status-row">
          <StatusPill label={`FIREBASE: ${connection}`} state={connection === 'ONLINE' ? 'online' : 'offline'} />
          <StatusPill label={`VISION: ${visionOnline ? 'ONLINE' : 'OFFLINE'}`} state={visionOnline ? 'online' : 'offline'} />
          <StatusPill label={`ESP32: ${deviceOnline ? 'ONLINE' : 'OFFLINE'}`} state={deviceOnline ? 'online' : 'offline'} />
          <StatusPill label={`MOTOR: ${motorStatus.toUpperCase()}`} state={motorStatus === 'running' ? 'online' : 'neutral'} />
          <span className="updated-label">Data diperbarui realtime</span>
        </section>

        <section className="metrics-grid">
          <MetricCard label="TOTAL INSPECTION" value={total} note="Seluruh objek diperiksa" />
          <MetricCard label="PERFECT" value={perfect} tone="good-text" note={`${ratio(perfect)}% dari total inspeksi`} />
          <MetricCard label="DEFECT" value={defect} tone="bad-text" note={`${ratio(defect)}% dari total inspeksi`} />
          <MetricCard label="INVALID" value={invalid} tone="warn-text" note={`${ratio(invalid)}% dari total inspeksi`} />
        </section>

        <section className="main-grid">
          <article className="panel camera-panel">
            <div className="panel-heading">
              <div><div className="panel-title">CAMERA & VISION STATUS</div><div className="panel-subtitle">Status pemrosesan dari aplikasi desktop</div></div>
              <span className={`small-dot ${visionOnline ? 'is-online' : ''}`} />
            </div>
            <div className="camera-placeholder">
              <div className="camera-symbol"><span /></div>
              <div className="camera-main">{visionOnline ? 'Computer Vision sedang berjalan' : 'Menunggu aplikasi Computer Vision'}</div>
              <div className="camera-caption">Preview video tersedia di aplikasi desktop Python. Web dashboard menampilkan status dan data inspeksi.</div>
            </div>
            <div className="camera-footer"><span>VISION STATUS</span><strong className={visionOnline ? 'good-text' : 'muted'}>{visionOnline ? 'RUNNING' : 'OFFLINE'}</strong></div>
          </article>

          <div className="side-stack">
            <article className="panel latest-panel">
              <div className="panel-title">HASIL INSPEKSI TERAKHIR</div>
              {currentClass ? (
                <>
                  <div className={`latest-result ${classifyTone(currentClass)}`}>{currentClass}</div>
                  <div className="latest-time">{prettyDate(vision.lastDetection)}</div>
                  <div className="coverage-row"><span>Red coverage</span><strong>{(coverage * 100).toFixed(1)}%</strong></div>
                  <div className="progress-track"><div className="progress-fill coverage-fill" style={{ width: `${coverage * 100}%` }} /></div>
                </>
              ) : <div className="empty-state compact-empty">Belum ada objek diperiksa</div>}
            </article>

            <article className="panel conveyor-panel">
              <div className="panel-title">CONVEYOR STATUS</div>
              <div className="info-line"><span>Device connection</span><strong className={deviceOnline ? 'good-text' : 'muted'}>{deviceOnline ? 'ONLINE' : 'OFFLINE'}</strong></div>
              <div className="info-line"><span>Motor status</span><strong>{motorStatus.toUpperCase()}</strong></div>
              <div className="info-line"><span>Last inspection</span><strong>{history[0] ? prettyDate(history[0].timestamp) : '—'}</strong></div>
            </article>
          </div>
        </section>

        <section className="bottom-grid">
          <article className="panel distribution-panel">
            <div className="panel-heading"><div><div className="panel-title">INSPECTION DISTRIBUTION</div><div className="panel-subtitle">Komposisi hasil pemeriksaan</div></div><span className="total-chip">{total} TOTAL</span></div>
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
          </article>

          <article className="panel connection-panel">
            <div className="panel-title">SYSTEM INFORMATION</div>
            <div className="info-line"><span>Database listener</span><strong className={connection === 'ONLINE' ? 'good-text' : 'warn-text'}>{connection}</strong></div>
            <div className="info-line"><span>Web access</span><strong>READ ONLY</strong></div>
            <div className="info-line"><span>Data source</span><strong>Firebase RTDB</strong></div>
          </article>
        </section>

        <section className="panel history-panel">
          <div className="panel-heading history-heading"><div><div className="panel-title">INSPECTION HISTORY</div><div className="panel-subtitle">12 inspeksi terbaru dari Firebase</div></div><span className="updated-label">Terbaru di bagian atas</span></div>
          {history.length ? (
            <div className="table-wrap">
              <table>
                <thead><tr><th>EVENT ID</th><th>WAKTU</th><th>CLASSIFICATION</th><th>RED COVERAGE</th></tr></thead>
                <tbody>{history.map((item) => (
                  <tr key={item.id}>
                    <td className="event-id">{item.eventId}</td>
                    <td>{prettyDate(item.timestamp)}</td>
                    <td><span className={`result-tag ${classifyTone(item.classification)}`}>{item.classification}</span></td>
                    <td>{(item.redCoverage * 100).toFixed(1)}%</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          ) : <div className="empty-state">Belum ada riwayat inspeksi. Jalankan kamera desktop untuk mulai mengirim hasil ke Firebase.</div>}
        </section>
        <footer className="page-footer">MES CONVEYOR SORTING SYSTEM <span>•</span> WEB MONITOR</footer>
      </main>
    </div>
  );
}

export default function App() {
  const [data, setData] = useState(EMPTY_DATA);
  const [connection, setConnection] = useState('CONNECTING');
  const [databaseError, setDatabaseError] = useState('');

  useEffect(() => {
    if (!firebaseConfigured || !db) {
      setConnection('NOT CONFIGURED');
      return undefined;
    }
    setConnection('CONNECTING');
    const unsubscribe = onValue(ref(db, '/'), (snapshot) => {
      setData(snapshot.val() || EMPTY_DATA);
      setConnection('ONLINE');
      setDatabaseError('');
    }, (error) => {
      setConnection('ERROR');
      setDatabaseError(error.message || 'Tidak dapat membaca Realtime Database.');
    });
    return unsubscribe;
  }, []);

  if (!firebaseConfigured) return <SetupNotice />;
  return <>
    <Dashboard data={data} connection={connection} />
    {databaseError && <div className="database-error">Database error: {databaseError}. Periksa Security Rules Firebase.</div>}
  </>;
}
