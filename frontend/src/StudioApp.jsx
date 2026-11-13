import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import AdminEmptyState from './EmptyState';
import './styles.css';

async function apiFetch(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || `Request failed (${res.status})`);
  return data;
}

async function apiUpload(path, file, fields = {}) {
  const form = new FormData();
  form.append('file', file);
  Object.entries(fields).forEach(([k, v]) => {
    if (v != null && v !== '') form.append(k, v);
  });
  const res = await fetch(path, { method: 'POST', body: form });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || `Upload failed (${res.status})`);
  return data;
}

function AdminTabHelp() { return null; }


const NAV = [
  { id: 'dashboard', label: 'Dashboard', short: 'Home', icon: 'fa-th-large' },
  { id: 'explainers', label: 'Explainers', short: 'Explain', icon: 'fa-microphone' },
  { id: 'clips', label: 'Streamer clips', short: 'Clips', icon: 'fa-cut' },
  { id: 'library', label: 'Gameplay library', short: 'Library', icon: 'fa-folder-open' },
  { id: 'review', label: 'Review', short: 'Review', icon: 'fa-check-double' },
  { id: 'settings', label: 'Settings', short: 'Setup', icon: 'fa-cog' },
];

const TEMPLATES = [
  { id: 'facecam_top', label: 'Facecam + gameplay' },
  { id: 'fullscreen_gameplay', label: 'Full-screen gameplay' },
  { id: 'pip', label: 'Picture-in-picture' },
];

function statusBadge(status) {
  const s = String(status || '').toLowerCase();
  if (['complete', 'completed', 'approved', 'ok'].includes(s)) return 'ok';
  if (['needs_review', 'pending', 'queued', 'processing', 'stub_complete'].includes(s)) return 'warn';
  if (['failed', 'rejected', 'denied'].includes(s)) return 'danger';
  return 'muted';
}

function formatSec(n) {
  if (n == null || Number.isNaN(Number(n))) return '—';
  const s = Math.round(Number(n));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}m ${String(r).padStart(2, '0')}s`;
}

function formatMoney(est) {
  if (est == null) return null;
  const n = typeof est === 'object' ? est.estimate : est;
  if (n == null || Number.isNaN(Number(n))) return null;
  return `~$${Number(n).toFixed(2)}`;
}

function JobProgress({ job }) {
  if (!job) return null;
  const pct = Math.max(0, Math.min(100, Number(job.progress_percent) || 0));
  const cost = formatMoney(job.cost_estimate);
  return (
    <div>
      <div className="gta-meta">
        {job.progress || job.stage || job.status || ''}
        {cost ? ` · ${cost}` : ''}
        {job.error ? ` · ${job.error}` : ''}
      </div>
      <div className="gta-progress" aria-hidden="true">
        <span style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function GTAClipperApp({
  showToast: showToastProp,
} = {}) {
  const [nav, setNav] = useState('dashboard');
  const [loading, setLoading] = useState(true);
  const [overview, setOverview] = useState(null);
  const [studio, setStudio] = useState(null);
  const [busy, setBusy] = useState('');
  const [toast, setToast] = useState('');
  const pollRef = useRef(null);
  const actor = 'local';
  const showToast = showToastProp || ((msg) => {
    setToast(String(msg || ''));
    window.setTimeout(() => setToast(''), 3200);
  });

  const loadAll = useCallback(async () => {
    const [ov, st] = await Promise.all([
      apiFetch('/api/overview'),
      apiFetch('/api/studio'),
    ]);
    setOverview(ov);
    setStudio(st);
  }, []);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      await loadAll();
    } catch (e) {
      showToast?.(e.message || 'Failed to load GTAClipper', 'error');
    } finally {
      setLoading(false);
    }
  }, [loadAll]);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    const jobs = studio?.jobs || [];
    const active = jobs.some((j) => ['queued', 'processing'].includes(String(j.status || '').toLowerCase()));
    if (!active) {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return undefined;
    }
    pollRef.current = setInterval(() => { loadAll().catch(() => {}); }, 2500);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [studio?.jobs, loadAll]);

  const settings = studio?.settings || overview?.settings || {};
  const providers = overview?.providers || {};

  const run = async (key, fn) => {
    setBusy(key);
    try {
      await fn();
      await loadAll();
    } catch (e) {
      showToast?.(e.message || 'Request failed', 'error');
    } finally {
      setBusy('');
    }
  };

  /* Explainers */
  const [topicSeed, setTopicSeed] = useState('');
  const [scriptForm, setScriptForm] = useState({
    title: '', topic: '', hook: '', target_duration_sec: 45, notes: '', topic_id: '',
  });
  const [selectedScriptId, setSelectedScriptId] = useState('');
  const [selectedRecordingId, setSelectedRecordingId] = useState('');
  const [renderTemplate, setRenderTemplate] = useState('facecam_top');
  const [requireCommercial, setRequireCommercial] = useState(true);

  const selectedScript = useMemo(
    () => (studio?.scripts || []).find((s) => s.id === selectedScriptId) || null,
    [studio?.scripts, selectedScriptId],
  );

  const explainerStep = selectedRecordingId ? 3 : selectedScriptId ? 2 : 1;

  /* Clips */
  const [clipForm, setClipForm] = useState({
    streamer_name: '',
    clip_count: 8,
    target_duration_sec: 30,
    template: 'fullscreen_gameplay',
    source_id: '',
    source_url: '',
  });
  const [regenDraft, setRegenDraft] = useState({});

  /* Library */
  const [libSearch, setLibSearch] = useState('');
  const [libForm, setLibForm] = useState({
    name: '', tags: '', description: '', source_id: '', start_sec: 0, end_sec: 0,
  });
  const [sourceForm, setSourceForm] = useState({
    name: '',
    provider: '',
    permission_status: 'approved',
    commercial_use: true,
    platforms_allowed: 'YouTube, TikTok, Instagram',
    attribution_required: false,
    notes: '',
  });
  const [settingsDraft, setSettingsDraft] = useState(null);

  useEffect(() => {
    if (studio?.settings) setSettingsDraft(studio.settings);
  }, [studio?.settings]);

  const filteredSegments = useMemo(() => {
    const all = studio?.segments || [];
    const q = libSearch.trim().toLowerCase();
    if (!q) return all;
    return all.filter((s) => {
      const blob = `${s.name || ''} ${s.description || ''} ${(s.tags || []).join(' ')}`.toLowerCase();
      return blob.includes(q);
    });
  }, [studio?.segments, libSearch]);

  const pendingExports = (studio?.exports || []).filter((e) => e.status === 'needs_review');
  const pendingClips = (studio?.clips || []).filter((c) => c.status === 'pending');

  if (loading && !studio) {
    return (
      <div className="ap-view gta-studio">
        <div className="ap-loading"><i className="fas fa-spinner fa-spin" /> Loading GTAClipper…</div>
      </div>
    );
  }

  return (
    <div className="ap-view gta-studio">
      {toast ? <div className="gta-toast">{toast}</div> : null}
      <div className="gta-header ap-view-header">
        <div className="ap-view-header-leading">
          <h1><i className="fas fa-video" /> GTAClipper</h1>
          <AdminTabHelp label="How it works" panelTitle="GTAClipper">
            <p>
              Pipeline B builds explainers from a script + facecam + your gameplay library.
              Pipeline A turns long streamer VODs into ranked short clips with captions.
              Everything renders 9:16 and lands in Review before publish.
            </p>
          </AdminTabHelp>
          <p className="gta-header-copy">
            Daily content desk — research topics, cut streamer moments, index gameplay, ship vertical videos.
          </p>
        </div>
        <button type="button" className="ap-btn secondary" onClick={() => refresh()} disabled={!!busy}>
          <i className="fas fa-sync" /> Refresh
        </button>
      </div>

      <nav className="gta-nav" aria-label="GTA studio sections">
        {NAV.map((item) => (
          <button
            key={item.id}
            type="button"
            className={nav === item.id ? 'active' : ''}
            onClick={() => setNav(item.id)}
          >
            <i className={`fas ${item.icon}`} />
            <span className="gta-nav-label">{item.label}</span>
            <span className="gta-nav-short">{item.short}</span>
          </button>
        ))}
      </nav>

      <div className="gta-provider-row">
        <span className={`gta-badge ${providers?.ffmpeg?.configured ? 'ok' : 'danger'}`}>
          <i className="fas fa-film" /> FFmpeg {providers?.ffmpeg?.configured ? 'ready' : 'missing'}
        </span>
        <span className={`gta-badge ${providers?.openai?.configured ? 'ok' : 'warn'}`}>
          <i className="fas fa-brain" /> OpenAI {providers?.openai?.configured ? 'ready' : 'not set'}
        </span>
        {(pendingExports.length + pendingClips.length) > 0 && (
          <button type="button" className="gta-badge warn" onClick={() => setNav('review')}>
            <i className="fas fa-inbox" /> {pendingExports.length + pendingClips.length} awaiting review
          </button>
        )}
      </div>

      {nav === 'dashboard' && (
        <>
          <div className="gta-stats">
            <div className="gta-stat">
              <div className="gta-stat-value">{overview?.videos_created ?? 0}</div>
              <div className="gta-stat-label">Videos created</div>
            </div>
            <div className="gta-stat">
              <div className="gta-stat-value">{overview?.awaiting_review ?? 0}</div>
              <div className="gta-stat-label">Awaiting review</div>
            </div>
            <div className="gta-stat">
              <div className="gta-stat-value">{overview?.completed ?? 0}</div>
              <div className="gta-stat-label">Approved</div>
            </div>
          </div>

          <div className="gta-panel">
            <h2>Create new content</h2>
            <div className="gta-pipeline-grid">
              <button type="button" className="gta-pipeline-card" onClick={() => setNav('clips')}>
                <h3><i className="fas fa-cut" /> Streamer clips</h3>
                <p>Upload a long VOD. AI finds highlights, scores them, and renders vertical shorts with captions.</p>
                <span className="gta-pipe-tag">Pipeline A</span>
              </button>
              <button type="button" className="gta-pipeline-card" onClick={() => setNav('explainers')}>
                <h3><i className="fas fa-microphone" /> GTA explainer</h3>
                <p>Generate a short script, record facecam, auto-match gameplay, render a finished 9:16 video.</p>
                <span className="gta-pipe-tag">Pipeline B</span>
              </button>
            </div>
          </div>

          <div className="gta-two-col">
            <div className="gta-panel">
              <div className="gta-panel-head">
                <h2>Recent jobs</h2>
              </div>
              {(studio?.jobs || []).length === 0 ? (
                <div className="gta-empty gta-note">No jobs yet — start an explainer or clip job.</div>
              ) : (
                <div className="gta-job-list">
                  {(studio?.jobs || []).slice(0, 8).map((job) => (
                    <div key={job.id} className="gta-job-row">
                      <div className="gta-job-row-main">
                        <h4>{job.name}</h4>
                        <div className="gta-meta">
                          {(job.type || '').replace(/_/g, ' ')}
                          {job.created_at ? ` · ${new Date(job.created_at).toLocaleString()}` : ''}
                        </div>
                        <JobProgress job={job} />
                      </div>
                      <span className={`gta-badge ${statusBadge(job.status)}`}>{job.status}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="gta-panel">
              <div className="gta-panel-head">
                <h2>Today&apos;s topics</h2>
                <button type="button" className="ap-btn secondary" onClick={() => setNav('explainers')}>
                  Open explainers
                </button>
              </div>
              {(studio?.topics || []).length === 0 ? (
                <AdminEmptyState
                  icon="lightbulb"
                  title="No topics yet"
                  description="Generate three short-form GTA ideas to kick off today’s content."
                  ctaLabel="Generate topics"
                  onCta={() => setNav('explainers')}
                />
              ) : (
                <div className="gta-topic-grid">
                  {(studio?.topics || []).slice(0, 3).map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      className="gta-topic-card"
                      onClick={() => {
                        setScriptForm((f) => ({
                          ...f,
                          topic_id: t.id,
                          title: t.title || f.title,
                          topic: t.summary || t.title || '',
                          hook: t.hook || '',
                        }));
                        setNav('explainers');
                      }}
                    >
                      <h4>{t.title}</h4>
                      <div className="gta-meta">{t.hook || t.summary}</div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {nav === 'explainers' && (
        <div className="gta-two-col">
          <div className="gta-panel">
            <div className="gta-panel-head">
              <h2>Explainer pipeline</h2>
            </div>
            <div className="gta-steps">
              <span className={`gta-step-pill ${explainerStep > 1 ? 'done' : explainerStep === 1 ? 'active' : ''}`}>1 · Script</span>
              <span className={`gta-step-pill ${explainerStep > 2 ? 'done' : explainerStep === 2 ? 'active' : ''}`}>2 · Facecam</span>
              <span className={`gta-step-pill ${explainerStep === 3 ? 'active' : ''}`}>3 · Render</span>
            </div>

            <div className="gta-form-grid">
              <div className="gta-field full">
                <label>Research focus</label>
                <input
                  value={topicSeed}
                  onChange={(e) => setTopicSeed(e.target.value)}
                  placeholder="e.g. launch day prep, money tips, confirmed features only"
                />
              </div>
            </div>
            <div className="gta-actions">
              <button
                type="button"
                className="ap-btn primary"
                disabled={!!busy}
                onClick={() => run('topics', async () => {
                  const data = await apiFetch('/api/topics/generate', {
                    method: 'POST',
                    body: JSON.stringify({ count: 3, seed: topicSeed, created_by: actor }),
                  });
                  showToast?.(`Generated ${(data.topics || []).length} topics`, 'success');
                  const first = (data.topics || [])[0];
                  if (first) {
                    setScriptForm((f) => ({
                      ...f,
                      topic_id: first.id,
                      title: first.title || f.title,
                      topic: first.summary || first.title || f.topic,
                      hook: first.hook || f.hook,
                    }));
                  }
                })}
              >
                {busy === 'topics' ? 'Researching…' : 'Generate 3 topics'}
              </button>
            </div>

            {(studio?.topics || []).length > 0 && (
              <div className="gta-topic-grid">
                {(studio?.topics || []).slice(0, 6).map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    className={`gta-topic-card${scriptForm.topic_id === t.id ? ' active' : ''}`}
                    onClick={() => setScriptForm((f) => ({
                      ...f,
                      topic_id: t.id,
                      title: t.title || f.title,
                      topic: t.summary || t.title || '',
                      hook: t.hook || '',
                    }))}
                  >
                    <h4>{t.title}</h4>
                    <div className="gta-meta">{t.hook || t.summary}</div>
                    {(t.speculation || []).length > 0 && (
                      <div className="gta-note">Includes speculation — keep clearly labelled.</div>
                    )}
                  </button>
                ))}
              </div>
            )}

            <div className="gta-form-grid" style={{ marginTop: '1rem' }}>
              <div className="gta-field full">
                <label>Title</label>
                <input value={scriptForm.title} onChange={(e) => setScriptForm({ ...scriptForm, title: e.target.value })} />
              </div>
              <div className="gta-field full">
                <label>Topic / brief</label>
                <textarea value={scriptForm.topic} onChange={(e) => setScriptForm({ ...scriptForm, topic: e.target.value })} />
              </div>
              <div className="gta-field">
                <label>Duration (sec)</label>
                <input
                  type="number"
                  min={20}
                  max={90}
                  value={scriptForm.target_duration_sec}
                  onChange={(e) => setScriptForm({ ...scriptForm, target_duration_sec: Number(e.target.value) || 45 })}
                />
              </div>
              <div className="gta-field">
                <label>Hook</label>
                <input value={scriptForm.hook} onChange={(e) => setScriptForm({ ...scriptForm, hook: e.target.value })} />
              </div>
            </div>
            <div className="gta-actions">
              <button
                type="button"
                className="ap-btn primary"
                disabled={!!busy || (!scriptForm.topic && !scriptForm.title && !scriptForm.topic_id)}
                onClick={() => run('script', async () => {
                  const data = await apiFetch('/api/scripts', {
                    method: 'POST',
                    body: JSON.stringify({ generate: true, ...scriptForm, created_by: actor }),
                  });
                  setSelectedScriptId(data.script?.id || '');
                  showToast?.('Script ready — record your facecam next', 'success');
                })}
              >
                {busy === 'script' ? 'Writing…' : 'Generate script'}
              </button>
            </div>

            {selectedScript && (
              <div style={{ marginTop: '1rem' }}>
                <h2 style={{ fontSize: '0.95rem' }}>{selectedScript.title}</h2>
                <div className="gta-script-preview">{selectedScript.full_text}</div>
                <div className="gta-actions">
                  <button
                    type="button"
                    className="ap-btn secondary"
                    onClick={() => {
                      const next = window.prompt('Edit full script', selectedScript.full_text || '');
                      if (next == null) return;
                      run('editscript', async () => {
                        await apiFetch(`/api/scripts/${selectedScript.id}`, {
                          method: 'PUT',
                          body: JSON.stringify({ full_text: next }),
                        });
                        showToast?.('Script updated', 'success');
                      });
                    }}
                  >
                    Edit script
                  </button>
                </div>
              </div>
            )}

            {(studio?.scripts || []).length > 0 && (
              <div className="gta-field" style={{ marginTop: '1rem' }}>
                <label>Existing scripts</label>
                <select value={selectedScriptId} onChange={(e) => setSelectedScriptId(e.target.value)}>
                  <option value="">Select…</option>
                  {(studio?.scripts || []).map((s) => (
                    <option key={s.id} value={s.id}>{s.title}</option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <div className="gta-panel">
            <h2>Facecam & render</h2>
            <p className="gta-note">
              Upload MP4/MOV of you reading the script. We transcribe, align sections, match gameplay, and burn keyword captions.
            </p>
            <div className="gta-actions">
              <label className={`ap-btn secondary gta-upload-btn${!selectedScriptId ? '' : ''}`}>
                {busy === 'recording' ? 'Uploading…' : 'Upload facecam'}
                <input
                  type="file"
                  accept="video/mp4,video/quicktime,video/*"
                  hidden
                  disabled={!!busy || !selectedScriptId}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    e.target.value = '';
                    if (!file || !selectedScriptId) return;
                    run('recording', async () => {
                      const data = await apiUpload(
                        '/api/recordings/upload',
                        file,
                        { script_id: selectedScriptId, created_by: actor, name: file.name },
                      );
                      setSelectedRecordingId(data.recording?.id || '');
                      showToast?.('Facecam uploaded', 'success');
                    });
                  }}
                />
              </label>
            </div>

            <div className="gta-form-grid" style={{ marginTop: '0.85rem' }}>
              <div className="gta-field">
                <label>Recording</label>
                <select value={selectedRecordingId} onChange={(e) => setSelectedRecordingId(e.target.value)}>
                  <option value="">Select…</option>
                  {(studio?.recordings || []).map((r) => (
                    <option key={r.id} value={r.id}>{r.name}</option>
                  ))}
                </select>
              </div>
              <div className="gta-field">
                <label>Template</label>
                <select value={renderTemplate} onChange={(e) => setRenderTemplate(e.target.value)}>
                  {TEMPLATES.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
                </select>
              </div>
              <div className="gta-field full">
                <label className="gta-check">
                  <input
                    type="checkbox"
                    checked={requireCommercial}
                    onChange={(e) => setRequireCommercial(e.target.checked)}
                  />
                  Require approved commercial footage rights
                </label>
              </div>
            </div>

            <div className="gta-actions">
              <button
                type="button"
                className="ap-btn primary"
                disabled={!!busy || !selectedScriptId || !selectedRecordingId}
                onClick={() => run('render', async () => {
                  await apiFetch('/api/explainers/render', {
                    method: 'POST',
                    body: JSON.stringify({
                      script_id: selectedScriptId,
                      recording_id: selectedRecordingId,
                      template: renderTemplate,
                      created_by: actor,
                      require_commercial: requireCommercial,
                    }),
                  });
                  showToast?.('Render started — watch progress in Review', 'success');
                  setNav('review');
                })}
              >
                {busy === 'render' ? 'Starting…' : 'Render explainer'}
              </button>
            </div>
            <p className="gta-note">
              Need footage? Index gameplay in Library with an approved rights source first.
            </p>

            {(studio?.jobs || []).filter((j) => j.type === 'explainer_render').slice(0, 4).map((job) => (
              <div key={job.id} className="gta-job-row" style={{ marginTop: '0.65rem' }}>
                <div className="gta-job-row-main">
                  <h4>{job.name}</h4>
                  <JobProgress job={job} />
                </div>
                <span className={`gta-badge ${statusBadge(job.status)}`}>{job.status}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {nav === 'clips' && (
        <div className="gta-panel">
          <div className="gta-panel-head">
            <div>
              <h2>Streamer clipping</h2>
              <p className="gta-note" style={{ marginTop: 4 }}>
                Upload a permitted MP4/MOV. We transcribe, find audio spikes & scene cuts, score moments with vision + GPT, then render vertical clips.
              </p>
            </div>
          </div>

          <div className="gta-form-grid">
            <div className="gta-field">
              <label>Streamer name</label>
              <input
                value={clipForm.streamer_name}
                onChange={(e) => setClipForm({ ...clipForm, streamer_name: e.target.value })}
                placeholder="Creator name"
              />
            </div>
            <div className="gta-field">
              <label>Rights source</label>
              <select
                value={clipForm.source_id}
                onChange={(e) => setClipForm({ ...clipForm, source_id: e.target.value })}
              >
                <option value="">None</option>
                {(studio?.sources || []).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.permission_status}{s.commercial_use ? ', commercial' : ''})
                  </option>
                ))}
              </select>
            </div>
            <div className="gta-field">
              <label>How many clips</label>
              <input
                type="number"
                min={1}
                max={20}
                value={clipForm.clip_count}
                onChange={(e) => setClipForm({ ...clipForm, clip_count: Number(e.target.value) || 8 })}
              />
            </div>
            <div className="gta-field">
              <label>Target duration (sec)</label>
              <input
                type="number"
                min={12}
                max={75}
                value={clipForm.target_duration_sec}
                onChange={(e) => setClipForm({ ...clipForm, target_duration_sec: Number(e.target.value) || 30 })}
              />
            </div>
            <div className="gta-field">
              <label>Template</label>
              <select
                value={clipForm.template}
                onChange={(e) => setClipForm({ ...clipForm, template: e.target.value })}
              >
                {TEMPLATES.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
              </select>
            </div>
            <div className="gta-field">
              <label>URL (blocked)</label>
              <input
                value={clipForm.source_url}
                onChange={(e) => setClipForm({ ...clipForm, source_url: e.target.value })}
                placeholder="Don’t paste scraped URLs — upload a file you have rights to"
              />
            </div>
          </div>

          <div className="gta-actions">
            <label className="ap-btn primary gta-upload-btn">
              {busy === 'clipupload' ? 'Uploading & queuing…' : 'Upload MP4 and generate clips'}
              <input
                type="file"
                accept="video/mp4,video/quicktime,video/*"
                hidden
                disabled={!!busy}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = '';
                  if (!file) return;
                  run('clipupload', async () => {
                    if (clipForm.source_url.trim()) {
                      throw new Error('URL ingestion is not available. Upload an MP4/MOV you have permission to use.');
                    }
                    const uploaded = await apiUpload(
                      '/api/videos/upload',
                      file,
                      {
                        kind: 'streamer',
                        name: file.name,
                        streamer_name: clipForm.streamer_name,
                        source_id: clipForm.source_id,
                        created_by: actor,
                      },
                    );
                    await apiFetch('/api/clips/jobs', {
                      method: 'POST',
                      body: JSON.stringify({
                        video_id: uploaded.video?.id,
                        streamer_name: clipForm.streamer_name,
                        clip_count: clipForm.clip_count,
                        target_duration_sec: clipForm.target_duration_sec,
                        template: clipForm.template,
                        source_id: clipForm.source_id,
                        created_by: actor,
                      }),
                    });
                    showToast?.('Clipping job started', 'success');
                    setNav('review');
                  });
                }}
              />
            </label>
          </div>

          {(studio?.jobs || []).filter((j) => j.type === 'clip_job').slice(0, 5).map((job) => (
            <div key={job.id} className="gta-job-row" style={{ marginTop: '0.75rem' }}>
              <div className="gta-job-row-main">
                <h4>{job.name}</h4>
                <JobProgress job={job} />
              </div>
              <span className={`gta-badge ${statusBadge(job.status)}`}>{job.status}</span>
            </div>
          ))}

          <h2 style={{ marginTop: '1.25rem' }}>Clip candidates</h2>
          {(studio?.clips || []).length === 0 ? (
            <AdminEmptyState
              icon="cut"
              title="No clips yet"
              description="Upload a long streamer recording to generate scored short clips for review."
            />
          ) : (
            <div className="gta-review-grid" style={{ marginTop: '0.75rem' }}>
              {(studio?.clips || []).map((clip) => {
                const draft = regenDraft[clip.id] || {
                  start_sec: clip.source_start_sec ?? 0,
                  end_sec: clip.source_end_sec ?? (clip.duration_sec || 30),
                };
                return (
                  <div key={clip.id} className="gta-review-card">
                    {clip.url ? (
                      <div className="gta-video-frame">
                        <video src={clip.url} controls playsInline preload="metadata" />
                      </div>
                    ) : null}
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                      <h4 style={{ margin: 0 }}>{clip.title || 'Clip'}</h4>
                      {clip.score != null && <span className="gta-score">{clip.score}</span>}
                    </div>
                    <div className="gta-meta">
                      {formatSec(clip.duration_sec)}
                      {clip.source_start_sec != null ? ` · source ${formatSec(clip.source_start_sec)}–${formatSec(clip.source_end_sec)}` : ''}
                    </div>
                    {clip.caption ? <p className="gta-note">{clip.caption}</p> : null}
                    {clip.reason ? <p className="gta-note">{clip.reason}</p> : null}
                    <span className={`gta-badge ${statusBadge(clip.status)}`}>{clip.status}</span>

                    <div className="gta-regen">
                      <div className="gta-field">
                        <label>Start</label>
                        <input
                          type="number"
                          value={draft.start_sec}
                          onChange={(e) => setRegenDraft((d) => ({
                            ...d,
                            [clip.id]: { ...draft, start_sec: Number(e.target.value) },
                          }))}
                        />
                      </div>
                      <div className="gta-field">
                        <label>End</label>
                        <input
                          type="number"
                          value={draft.end_sec}
                          onChange={(e) => setRegenDraft((d) => ({
                            ...d,
                            [clip.id]: { ...draft, end_sec: Number(e.target.value) },
                          }))}
                        />
                      </div>
                      <button
                        type="button"
                        className="ap-btn secondary"
                        disabled={!!busy}
                        onClick={() => run(`regen-${clip.id}`, async () => {
                          await apiFetch(`/api/clips/${clip.id}/regenerate`, {
                            method: 'POST',
                            body: JSON.stringify({
                              start_sec: draft.start_sec,
                              end_sec: draft.end_sec,
                              template: clip.template || clipForm.template,
                            }),
                          });
                          showToast?.('Clip regenerated', 'success');
                        })}
                      >
                        Regenerate
                      </button>
                    </div>

                    <div className="gta-actions" style={{ marginTop: 0 }}>
                      {clip.url && (
                        <a className="ap-btn secondary" href={clip.url} target="_blank" rel="noreferrer" download>
                          Download
                        </a>
                      )}
                      <button
                        type="button"
                        className="ap-btn primary"
                        onClick={() => run('approveclip', async () => {
                          await apiFetch(`/api/clips/${clip.id}/approve`, { method: 'POST' });
                        })}
                      >
                        Approve
                      </button>
                      <button
                        type="button"
                        className="ap-btn secondary"
                        onClick={() => run('rejectclip', async () => {
                          await apiFetch(`/api/clips/${clip.id}/reject`, { method: 'POST' });
                        })}
                      >
                        Reject
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {nav === 'library' && (
        <div className="gta-two-col">
          <div className="gta-panel">
            <h2>Gameplay library</h2>
            <p className="gta-note">
              Upload footage you have rights to. We detect scenes, sample frames, AI-tag segments, and embed them for semantic search.
            </p>
            <div className="gta-form-grid">
              <div className="gta-field">
                <label>Name</label>
                <input value={libForm.name} onChange={(e) => setLibForm({ ...libForm, name: e.target.value })} />
              </div>
              <div className="gta-field">
                <label>Extra tags</label>
                <input
                  value={libForm.tags}
                  onChange={(e) => setLibForm({ ...libForm, tags: e.target.value })}
                  placeholder="police, chase, night"
                />
              </div>
              <div className="gta-field full">
                <label>Notes</label>
                <textarea
                  value={libForm.description}
                  onChange={(e) => setLibForm({ ...libForm, description: e.target.value })}
                />
              </div>
              <div className="gta-field">
                <label>Rights source</label>
                <select
                  value={libForm.source_id}
                  onChange={(e) => setLibForm({ ...libForm, source_id: e.target.value })}
                >
                  <option value="">None</option>
                  {(studio?.sources || []).map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="gta-actions">
              <label className="ap-btn primary gta-upload-btn">
                {busy === 'libupload' ? 'Uploading…' : 'Upload & AI-index'}
                <input
                  type="file"
                  accept="video/mp4,video/quicktime,video/*"
                  hidden
                  disabled={!!busy}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    e.target.value = '';
                    if (!file) return;
                    run('libupload', async () => {
                      const uploaded = await apiUpload(
                        '/api/videos/upload',
                        file,
                        {
                          kind: 'gameplay',
                          name: libForm.name || file.name,
                          tags: libForm.tags,
                          source_id: libForm.source_id,
                          created_by: actor,
                        },
                      );
                      await apiFetch('/api/library/ingest', {
                        method: 'POST',
                        body: JSON.stringify({
                          video_id: uploaded.video?.id,
                          name: libForm.name || file.name,
                          description: libForm.description,
                          tags: libForm.tags,
                          source_id: libForm.source_id,
                          created_by: actor,
                        }),
                      });
                      showToast?.('Indexing started', 'success');
                    });
                  }}
                />
              </label>
            </div>

            {(studio?.jobs || []).filter((j) => j.type === 'library_ingest').slice(0, 3).map((job) => (
              <div key={job.id} className="gta-job-row" style={{ marginTop: '0.75rem' }}>
                <div className="gta-job-row-main">
                  <h4>{job.name}</h4>
                  <JobProgress job={job} />
                </div>
                <span className={`gta-badge ${statusBadge(job.status)}`}>{job.status}</span>
              </div>
            ))}

            <div className="gta-field" style={{ marginTop: '1rem' }}>
              <label>Search library</label>
              <input
                value={libSearch}
                onChange={(e) => setLibSearch(e.target.value)}
                placeholder="police chase, beach sunset, explosion…"
              />
            </div>

            <div className="gta-seg-grid">
              {filteredSegments.length === 0 ? (
                <div className="gta-note">No segments yet.</div>
              ) : filteredSegments.map((seg) => (
                <div key={seg.id} className="gta-seg-card">
                  {seg.thumbnail_url ? (
                    <img className="gta-thumb" src={seg.thumbnail_url} alt="" />
                  ) : (
                    <div className="gta-thumb" />
                  )}
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <h4>{seg.name}</h4>
                    <div className="gta-meta">
                      {formatSec(seg.start_sec)}–{formatSec(seg.end_sec)}
                      {seg.setting ? ` · ${seg.setting}` : ''}
                      {seg.action_level != null ? ` · action ${seg.action_level}/5` : ''}
                    </div>
                    {seg.description ? <p className="gta-note">{seg.description}</p> : null}
                    <div className="gta-tag-row">
                      {(seg.tags || []).slice(0, 8).map((t) => (
                        <span key={t} className="gta-tag">{t}</span>
                      ))}
                    </div>
                    <div className="gta-actions" style={{ marginTop: 8 }}>
                      <button
                        type="button"
                        className="ap-btn secondary"
                        onClick={() => {
                          const tags = window.prompt('Edit tags', (seg.tags || []).join(', '));
                          if (tags == null) return;
                          run('edittag', async () => {
                            await apiFetch(`/api/library/segments/${seg.id}`, {
                              method: 'PUT',
                              body: JSON.stringify({ tags }),
                            });
                          });
                        }}
                      >
                        Edit tags
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="gta-panel">
            <h2>Footage rights</h2>
            <p className="gta-note">
              Commercial exports require approved + commercial-use sources. Sort this before publishing.
            </p>
            <div className="gta-form-grid">
              <div className="gta-field">
                <label>Name</label>
                <input value={sourceForm.name} onChange={(e) => setSourceForm({ ...sourceForm, name: e.target.value })} />
              </div>
              <div className="gta-field">
                <label>Provider / creator</label>
                <input value={sourceForm.provider} onChange={(e) => setSourceForm({ ...sourceForm, provider: e.target.value })} />
              </div>
              <div className="gta-field">
                <label>Permission</label>
                <select
                  value={sourceForm.permission_status}
                  onChange={(e) => setSourceForm({ ...sourceForm, permission_status: e.target.value })}
                >
                  <option value="pending">Pending</option>
                  <option value="approved">Approved</option>
                  <option value="denied">Denied</option>
                  <option value="expired">Expired</option>
                </select>
              </div>
              <div className="gta-field">
                <label>Platforms</label>
                <input
                  value={sourceForm.platforms_allowed}
                  onChange={(e) => setSourceForm({ ...sourceForm, platforms_allowed: e.target.value })}
                />
              </div>
              <div className="gta-field full">
                <label className="gta-check">
                  <input
                    type="checkbox"
                    checked={!!sourceForm.commercial_use}
                    onChange={(e) => setSourceForm({ ...sourceForm, commercial_use: e.target.checked })}
                  />
                  Commercial use allowed
                </label>
              </div>
            </div>
            <div className="gta-actions">
              <button
                type="button"
                className="ap-btn primary"
                disabled={!!busy || !sourceForm.name}
                onClick={() => run('source', async () => {
                  await apiFetch('/api/sources', {
                    method: 'POST',
                    body: JSON.stringify({ ...sourceForm, created_by: actor }),
                  });
                  showToast?.('Source saved', 'success');
                  setSourceForm({
                    name: '',
                    provider: '',
                    permission_status: 'approved',
                    commercial_use: true,
                    platforms_allowed: 'YouTube, TikTok, Instagram',
                    attribution_required: false,
                    notes: '',
                  });
                })}
              >
                Add source
              </button>
            </div>
            <div className="gta-card-list" style={{ marginTop: '0.85rem' }}>
              {(studio?.sources || []).map((s) => (
                <div key={s.id} className="gta-card">
                  <div className="gta-card-main">
                    <h4>{s.name}</h4>
                    <div className="gta-meta">
                      {s.provider || '—'} · {s.permission_status}
                      {s.commercial_use ? ' · commercial' : ' · non-commercial'}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="ap-btn secondary"
                    onClick={() => run('approveSource', async () => {
                      await apiFetch(`/api/sources/${s.id}`, {
                        method: 'PUT',
                        body: JSON.stringify({ permission_status: 'approved', commercial_use: true }),
                      });
                    })}
                  >
                    Approve
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {nav === 'review' && (
        <div className="gta-panel">
          <div className="gta-panel-head">
            <div>
              <h2>Review desk</h2>
              <p className="gta-note" style={{ marginTop: 4 }}>
                Approve, reject, download, or email finished videos. Nothing publishes automatically.
              </p>
            </div>
          </div>

          {(studio?.exports || []).length === 0 && (studio?.clips || []).length === 0 ? (
            <AdminEmptyState
              icon="check-double"
              title="Nothing to review"
              description="Finished explainers and streamer clips show up here."
            />
          ) : (
            <div className="gta-review-grid">
              {(studio?.exports || []).map((exp) => (
                <div key={exp.id} className="gta-review-card">
                  {exp.url ? (
                    <div className="gta-video-frame">
                      <video src={exp.url} controls playsInline preload="metadata" />
                    </div>
                  ) : null}
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                    <h4 style={{ margin: 0 }}>{exp.title || exp.name}</h4>
                    {exp.score != null && <span className="gta-score">{exp.score}</span>}
                  </div>
                  <div className="gta-meta">
                    {exp.pipeline} · {formatSec(exp.duration_sec)} · {exp.template}
                    {exp.source_timestamp ? ` · ${exp.source_timestamp}` : ''}
                    {formatMoney(exp.cost_estimate) ? ` · ${formatMoney(exp.cost_estimate)}` : ''}
                  </div>
                  {exp.caption ? <p className="gta-note">{exp.caption}</p> : null}
                  <span className={`gta-badge ${statusBadge(exp.status)}`}>{exp.status}</span>
                  <div className="gta-actions">
                    {exp.url && (
                      <a className="ap-btn secondary" href={exp.url} target="_blank" rel="noreferrer" download>
                        Download
                      </a>
                    )}
                    <button
                      type="button"
                      className="ap-btn primary"
                      onClick={() => run('approveExport', async () => {
                        await apiFetch(`/api/exports/${exp.id}/approve`, { method: 'POST' });
                        showToast?.('Approved', 'success');
                      })}
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      className="ap-btn secondary"
                      onClick={() => run('rejectExport', async () => {
                        await apiFetch(`/api/exports/${exp.id}/reject`, { method: 'POST' });
                      })}
                    >
                      Reject
                    </button>
                    <button
                      type="button"
                      className="ap-btn secondary"
                      onClick={() => run('emailExport', async () => {
                        const email = window.prompt('Email to', settings.notify_email || '');
                        if (!email) return;
                        await apiFetch(`/api/exports/${exp.id}/email`, {
                          method: 'POST',
                          body: JSON.stringify({ to_email: email }),
                        });
                        showToast?.('Email sent', 'success');
                      })}
                    >
                      Email
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          <h2 style={{ marginTop: '1.35rem' }}>Active & recent jobs</h2>
          <div className="gta-job-list">
            {(studio?.jobs || []).slice(0, 12).map((job) => (
              <div key={job.id} className="gta-job-row">
                <div className="gta-job-row-main">
                  <h4>{job.name}</h4>
                  <JobProgress job={job} />
                </div>
                <span className={`gta-badge ${statusBadge(job.status)}`}>{job.status}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {nav === 'settings' && settingsDraft && (
        <div className="gta-panel">
          <h2>Studio settings</h2>
          <div className="gta-form-grid">
            <div className="gta-field">
              <label>Channel name</label>
              <input
                value={settingsDraft.channel_name || ''}
                onChange={(e) => setSettingsDraft({ ...settingsDraft, channel_name: e.target.value })}
              />
            </div>
            <div className="gta-field">
              <label>Default template</label>
              <select
                value={settingsDraft.default_template || 'facecam_top'}
                onChange={(e) => setSettingsDraft({ ...settingsDraft, default_template: e.target.value })}
              >
                {TEMPLATES.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
              </select>
            </div>
            <div className="gta-field full">
              <label>Logo URL</label>
              <input
                value={settingsDraft.logo_url || ''}
                onChange={(e) => setSettingsDraft({ ...settingsDraft, logo_url: e.target.value })}
                placeholder="https://…/logo.png"
              />
            </div>
            <div className="gta-field full">
              <label>Background music URL</label>
              <input
                value={settingsDraft.music_url || ''}
                onChange={(e) => setSettingsDraft({ ...settingsDraft, music_url: e.target.value })}
              />
            </div>
            <div className="gta-field">
              <label>Music volume (0–1)</label>
              <input
                type="number"
                min={0}
                max={1}
                step={0.01}
                value={settingsDraft.music_volume ?? 0.12}
                onChange={(e) => setSettingsDraft({ ...settingsDraft, music_volume: Number(e.target.value) })}
              />
            </div>
            <div className="gta-field">
              <label>Notify email</label>
              <input
                value={settingsDraft.notify_email || ''}
                onChange={(e) => setSettingsDraft({ ...settingsDraft, notify_email: e.target.value })}
              />
            </div>
            <div className="gta-field full">
              <label className="gta-check">
                <input
                  type="checkbox"
                  checked={!!settingsDraft.email_finished_videos}
                  onChange={(e) => setSettingsDraft({ ...settingsDraft, email_finished_videos: e.target.checked })}
                />
                Email me when videos finish
              </label>
            </div>
          </div>
          <div className="gta-actions">
            <button
              type="button"
              className="ap-btn primary"
              disabled={!!busy}
              onClick={() => run('settings', async () => {
                await apiFetch('/api/settings', {
                  method: 'PUT',
                  body: JSON.stringify(settingsDraft),
                });
                showToast?.('Settings saved', 'success');
              })}
            >
              Save settings
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
