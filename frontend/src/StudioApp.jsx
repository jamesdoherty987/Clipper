import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import AdminEmptyState from './EmptyState';
import './styles.css';

function formatApiError(data, status, fallback) {
  const detail = data?.detail ?? data?.error;
  if (Array.isArray(detail)) {
    return detail.map((item) => item?.msg || item?.message || String(item)).join('; ');
  }
  if (detail && typeof detail === 'object') {
    return detail.msg || detail.message || JSON.stringify(detail);
  }
  if (typeof detail === 'string' && detail.trim()) return detail;
  return fallback || `Request failed (${status})`;
}

async function apiFetch(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(formatApiError(data, res.status));
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
  if (!res.ok) throw new Error(formatApiError(data, res.status, `Upload failed (${res.status})`));
  return data;
}


const NAV = [
  { id: 'dashboard', label: 'Dashboard', short: 'Home', icon: 'fa-th-large' },
  { id: 'explainers', label: 'Explainers', short: 'Explain', icon: 'fa-microphone' },
  { id: 'clips', label: 'Streamer clips', short: 'Clips', icon: 'fa-cut' },
  { id: 'library', label: 'Gameplay library', short: 'Library', icon: 'fa-folder-open' },
  { id: 'review', label: 'Review & manage', short: 'Manage', icon: 'fa-check-double' },
  { id: 'settings', label: 'Settings', short: 'Setup', icon: 'fa-cog' },
];

const EXPLAINER_TEMPLATES = [
  { id: 'facecam_top', label: 'Facecam top + gameplay bottom' },
  { id: 'fullscreen_gameplay', label: 'Full-screen gameplay + cam pip' },
  { id: 'pip', label: 'Picture-in-picture' },
];

const CLIP_TEMPLATES = [
  { id: 'fullscreen_gameplay', label: 'Full-screen vertical' },
  { id: 'reaction_stack', label: 'Split: reaction top + gameplay bottom' },
  { id: 'pip', label: 'Punch-in vertical' },
];

const CLIP_PRESETS = [
  { id: 'viral', label: 'Viral', blurb: 'Big center captions, intro card, light zoom' },
  { id: 'clean', label: 'Clean', blurb: 'Bottom captions, no intro, subtle look' },
  { id: 'split_reaction', label: 'Reaction', blurb: 'Face/gameplay split + end card' },
  { id: 'branded', label: 'Branded', blurb: 'Intro + end card + logo package' },
  { id: 'custom', label: 'Custom', blurb: 'Your own mix of options below' },
];

const CLIP_STYLE_TABS = [
  { id: 'layout', label: 'Layout', icon: 'fa-th-large' },
  { id: 'captions', label: 'Captions', icon: 'fa-closed-captioning' },
  { id: 'cards', label: 'Intro / end', icon: 'fa-clone' },
  { id: 'overlays', label: 'Overlays', icon: 'fa-layer-group' },
];

const PRESET_DEFAULTS = {
  viral: {
    template: 'fullscreen_gameplay', burn_captions: true, caption_style: 'viral',
    caption_position: 'center', caption_size: 'lg', highlight_keywords: true,
    add_intro: true, add_end_card: false, show_logo: true, logo_position: 'top_right',
    logo_size: 150, apply_zoom: true, zoom_amount: 1.14, split_ratio: 0.42,
    cam_anchor: 'top_right', intro_duration_sec: 1.5, intro_text: '', end_card_text: '',
    use_music: true,
  },
  clean: {
    template: 'fullscreen_gameplay', burn_captions: true, caption_style: 'clean',
    caption_position: 'bottom', caption_size: 'md', highlight_keywords: false,
    add_intro: false, add_end_card: false, show_logo: true, logo_position: 'top_right',
    logo_size: 140, apply_zoom: false, zoom_amount: 1.08, split_ratio: 0.42,
    cam_anchor: 'top_right', intro_duration_sec: 1.4, intro_text: '', end_card_text: '',
    use_music: true,
  },
  split_reaction: {
    template: 'reaction_stack', burn_captions: true, caption_style: 'bold',
    caption_position: 'bottom', caption_size: 'md', highlight_keywords: true,
    add_intro: false, add_end_card: true, show_logo: true, logo_position: 'top_left',
    logo_size: 130, apply_zoom: false, zoom_amount: 1.1, split_ratio: 0.42,
    cam_anchor: 'top_right', intro_duration_sec: 1.4, intro_text: '', end_card_text: 'Follow for more',
    use_music: true,
  },
  branded: {
    template: 'fullscreen_gameplay', burn_captions: true, caption_style: 'viral',
    caption_position: 'bottom', caption_size: 'md', highlight_keywords: true,
    add_intro: true, add_end_card: true, show_logo: true, logo_position: 'top_right',
    logo_size: 170, apply_zoom: true, zoom_amount: 1.1, split_ratio: 0.4,
    cam_anchor: 'top_right', intro_duration_sec: 1.8, intro_text: '', end_card_text: 'Follow for more',
    use_music: true,
  },
};

const TEMPLATES = EXPLAINER_TEMPLATES;

function clipJobBody(clipForm, actor, extra = {}) {
  return {
    streamer_name: clipForm.streamer_name,
    video_context: clipForm.video_context,
    clip_count: clipForm.clip_count,
    target_duration_sec: clipForm.target_duration_sec,
    template: clipForm.template,
    source_id: clipForm.source_id,
    preset: clipForm.preset,
    burn_captions: clipForm.burn_captions,
    caption_style: clipForm.caption_style,
    caption_position: clipForm.caption_position,
    caption_size: clipForm.caption_size,
    highlight_keywords: clipForm.highlight_keywords,
    add_intro: clipForm.add_intro,
    add_end_card: clipForm.add_end_card,
    show_logo: clipForm.show_logo,
    logo_position: clipForm.logo_position,
    logo_size: clipForm.logo_size,
    apply_zoom: clipForm.apply_zoom,
    zoom_amount: clipForm.zoom_amount,
    split_ratio: clipForm.split_ratio,
    cam_anchor: clipForm.cam_anchor,
    intro_duration_sec: clipForm.intro_duration_sec,
    intro_text: clipForm.intro_text,
    end_card_text: clipForm.end_card_text,
    use_music: clipForm.use_music,
    created_by: actor,
    ...extra,
  };
}

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

function ReviewVideo({ src }) {
  const onPlay = (e) => {
    const current = e.currentTarget;
    document.querySelectorAll('.gta-review-card video').forEach((el) => {
      if (el !== current) {
        try { el.pause(); } catch (_) { /* ignore */ }
      }
    });
  };
  return (
    <div className="gta-video-frame">
      <video
        src={src}
        controls
        playsInline
        preload="none"
        onPlay={onPlay}
      />
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
  const [toast, setToast] = useState(null);
  const pollRef = useRef(null);
  const actor = 'local';
  const showToast = showToastProp || ((msg, type = 'success') => {
    setToast({ message: String(msg || ''), type: type === 'error' ? 'error' : 'success' });
    window.setTimeout(() => setToast(null), 4200);
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
    video_context: '',
    clip_count: 8,
    target_duration_sec: 30,
    source_id: '',
    source_url: '',
    preset: 'viral',
    ...PRESET_DEFAULTS.viral,
  });
  const [styleOpen, setStyleOpen] = useState(true);
  const [styleTab, setStyleTab] = useState('overlays');
  const [focusJobId, setFocusJobId] = useState('');
  const [showAllReviews, setShowAllReviews] = useState(false);

  const applyClipPreset = (presetId) => {
    const base = PRESET_DEFAULTS[presetId];
    if (!base) {
      setClipForm((prev) => ({ ...prev, preset: 'custom' }));
      return;
    }
    setClipForm((prev) => ({ ...prev, preset: presetId, ...base }));
  };

  const patchClipStyle = (patch) => {
    setClipForm((prev) => ({ ...prev, ...patch, preset: 'custom' }));
  };
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
  const clipJobs = useMemo(
    () => (studio?.jobs || []).filter((j) => j.type === 'clip_job' || j.type === 'explainer_render'),
    [studio?.jobs],
  );
  const latestClipJobId = useMemo(() => {
    return focusJobId || clipJobs[0]?.id || '';
  }, [clipJobs, focusJobId]);
  const focusedJob = useMemo(
    () => clipJobs.find((j) => j.id === latestClipJobId) || null,
    [clipJobs, latestClipJobId],
  );
  const reviewExports = useMemo(() => {
    const all = studio?.exports || [];
    if (showAllReviews || !latestClipJobId) return all;
    return all.filter((e) => e.job_id === latestClipJobId);
  }, [studio?.exports, latestClipJobId, showAllReviews]);
  const focusedJobClipCount = useMemo(
    () => (studio?.clips || []).filter((c) => c.job_id === latestClipJobId).length,
    [studio?.clips, latestClipJobId],
  );

  const confirmDelete = (message) => window.confirm(message);

  const deleteRun = (jobId) => {
    if (!jobId) return;
    if (!confirmDelete('Delete this entire run? All clips and exports from it will be removed.')) return;
    run(`deljob-${jobId}`, async () => {
      await apiFetch(`/api/jobs/${jobId}`, { method: 'DELETE' });
      if (focusJobId === jobId) setFocusJobId('');
      showToast?.('Run deleted', 'success');
    });
  };

  const rerunClipJob = (job) => {
    if (!job?.id) return;
    if (job.type && job.type !== 'clip_job') {
      showToast?.('Only streamer clip runs can be rerun', 'error');
      return;
    }
    const videoId = job.payload?.video_id;
    if (!videoId) {
      showToast?.('This run has no saved source video to reuse', 'error');
      return;
    }
    run(`rerun-${job.id}`, async () => {
      const data = await apiFetch(`/api/clips/jobs/${job.id}/rerun`, {
        method: 'POST',
        body: JSON.stringify({ created_by: actor }),
      });
      setFocusJobId(data.job?.id || '');
      setShowAllReviews(false);
      showToast?.('Rerun started with the same video', 'success');
      setNav('review');
    });
  };

  const deleteExportCard = (exp) => {
    const id = exp.clip_id || exp.id;
    const path = exp.clip_id ? `/api/clips/${exp.clip_id}` : `/api/exports/${exp.id}`;
    if (!confirmDelete('Delete this clip from the run?')) return;
    run(`delclip-${id}`, async () => {
      await apiFetch(path, { method: 'DELETE' });
      showToast?.('Clip deleted', 'success');
    });
  };

  const deleteSourceVideo = (videoId, name) => {
    if (!confirmDelete(`Delete source video “${name || 'video'}” and all runs that used it?`)) return;
    run(`delvid-${videoId}`, async () => {
      await apiFetch(`/api/videos/${videoId}`, { method: 'DELETE' });
      showToast?.('Source video deleted', 'success');
    });
  };

  if (loading && !studio) {
    return (
      <div className="ap-view gta-studio">
        <div className="ap-loading"><i className="fas fa-spinner fa-spin" /> Loading GTAClipper…</div>
      </div>
    );
  }

  return (
    <div className="ap-view gta-studio">
      {toast ? (
        <div className={`gta-toast${toast.type === 'error' ? ' error' : ''}`} role="status">
          {toast.message}
        </div>
      ) : null}
      <div className="gta-header ap-view-header">
        <div className="ap-view-header-leading">
          <h1><i className="fas fa-video" /> GTAClipper</h1>
          <p className="gta-header-copy">
            Turn long videos into vertical shorts, or build explainers from a script + facecam. Review everything before you ship.
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

      {(!providers?.ffmpeg?.configured || !providers?.openai?.configured) && (
        <div className="gta-banner warn">
          {!providers?.ffmpeg?.configured
            ? 'Install FFmpeg on this Mac before rendering videos.'
            : 'Add OPENAI_API_KEY to your .env file, then restart the API.'}
        </div>
      )}

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
            <h2>Start here</h2>
            <div className="gta-pipeline-grid">
              <button type="button" className="gta-pipeline-card" onClick={() => setNav('clips')}>
                <h3><i className="fas fa-cut" /> Streamer clips</h3>
                <p>Paste a URL → pick captions/logo/music → generate viral Shorts, then approve in Review.</p>
              </button>
              <button type="button" className="gta-pipeline-card" onClick={() => setNav('explainers')}>
                <h3><i className="fas fa-microphone" /> Explainers</h3>
                <p>Generate a script, upload facecam, match gameplay, and render a finished 9:16 video.</p>
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
              Generate a script first, then upload an MP4/MOV of you reading it. We match gameplay and burn captions.
            </p>
            {!selectedScriptId && (
              <p className="gta-note">Select or generate a script on the left before uploading facecam.</p>
            )}
            <div className="gta-actions">
              <label className="ap-btn secondary gta-upload-btn">
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
        <div className="gta-panel gta-clips-panel">
          <div className="gta-panel-head">
            <div>
              <h2>Streamer clips</h2>
              <p className="gta-note gta-panel-lead">
                Turn a VOD into vertical Shorts. We find the viral moments, burn your style on, then you approve in Review.
              </p>
            </div>
            {pendingClips.length > 0 && (
              <button type="button" className="ap-btn primary" onClick={() => setNav('review')}>
                Review {pendingClips.length} clip{pendingClips.length === 1 ? '' : 's'}
              </button>
            )}
          </div>

          <ol className="gta-howto">
            <li>
              <span className="gta-howto-num">1</span>
              <div>
                <strong>Add source</strong>
                <p>Paste a YouTube link or upload an MP4/MOV you have rights to.</p>
              </div>
            </li>
            <li>
              <span className="gta-howto-num">2</span>
              <div>
                <strong>Pick style & overlays</strong>
                <p>Captions, logo, intro/end cards, and music are all optional toggles below.</p>
              </div>
            </li>
            <li>
              <span className="gta-howto-num">3</span>
              <div>
                <strong>Generate → Review</strong>
                <p>We cut the best moments. Open Review to watch, keep, or delete each clip.</p>
              </div>
            </li>
          </ol>

          <section className="gta-clip-step">
            <div className="gta-clip-step-head">
              <h3><span>1</span> Source video</h3>
            </div>
            <div className="gta-form-grid">
              <div className="gta-field full">
                <label>YouTube / media URL</label>
                <input
                  value={clipForm.source_url}
                  onChange={(e) => setClipForm({ ...clipForm, source_url: e.target.value })}
                  placeholder="https://www.youtube.com/watch?v=…"
                />
              </div>
              <div className="gta-field full">
                <label>What is this video? (context for AI)</label>
                <textarea
                  value={clipForm.video_context}
                  onChange={(e) => setClipForm({ ...clipForm, video_context: e.target.value })}
                  placeholder="e.g. UFC fight highlight — find the finish / knockout. Or: GTA RP stream, funny fails and police chases."
                  rows={2}
                />
                <p className="gta-field-hint">
                  Tell the AI what matters in this video. It uses this with the full transcript + audio spikes to find the real climax — not hardcoded events.
                </p>
              </div>
              <div className="gta-field">
                <label>Streamer / creator name</label>
                <input
                  value={clipForm.streamer_name}
                  onChange={(e) => setClipForm({ ...clipForm, streamer_name: e.target.value })}
                  placeholder="Optional — used in titles"
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
                <label>How many clips to cut</label>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={clipForm.clip_count}
                  onChange={(e) => setClipForm({ ...clipForm, clip_count: Number(e.target.value) || 8 })}
                />
                <p className="gta-field-hint">Raise this for more clips from the same VOD (max 20).</p>
              </div>
              <div className="gta-field">
                <label>Target length (seconds)</label>
                <input
                  type="number"
                  min={8}
                  max={120}
                  value={clipForm.target_duration_sec}
                  onChange={(e) => setClipForm({ ...clipForm, target_duration_sec: Number(e.target.value) || 30 })}
                />
                <p className="gta-field-hint">15s target → clips between 10s and 28s. Same ratio for other targets.</p>
              </div>
            </div>
          </section>

          <section className="gta-clip-step gta-style-studio">
            <div className="gta-clip-step-head gta-style-studio-head">
              <div>
                <h3><span>2</span> Style, captions & overlays</h3>
                <p className="gta-note">
                  Start with a preset. Then open a tab to turn overlays on/off and tweak them.
                </p>
              </div>
              <button type="button" className="ap-btn secondary" onClick={() => setStyleOpen((v) => !v)}>
                {styleOpen ? 'Hide options' : 'Show options'}
              </button>
            </div>

            <div className="gta-preset-grid">
              {CLIP_PRESETS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className={`gta-preset-card${clipForm.preset === p.id ? ' active' : ''}`}
                  onClick={() => applyClipPreset(p.id)}
                >
                  <strong>{p.label}</strong>
                  <span>{p.blurb}</span>
                </button>
              ))}
            </div>

            {styleOpen && (
              <>
                <div className="gta-style-tabs" role="tablist" aria-label="Style options">
                  {CLIP_STYLE_TABS.map((tab) => (
                    <button
                      key={tab.id}
                      type="button"
                      role="tab"
                      aria-selected={styleTab === tab.id}
                      className={`gta-style-tab${styleTab === tab.id ? ' active' : ''}`}
                      onClick={() => setStyleTab(tab.id)}
                    >
                      <i className={`fas ${tab.icon}`} aria-hidden="true" />
                      {tab.label}
                    </button>
                  ))}
                </div>

                <div className="gta-style-body">
                  <div className="gta-style-controls">
                    {styleTab === 'layout' && (
                      <section className="gta-style-section">
                        <p className="gta-tip">
                          <i className="fas fa-info-circle" aria-hidden="true" />
                          Layout is how the video is framed on a 9:16 phone screen — not overlays.
                        </p>
                        <div className="gta-form-grid">
                          <div className="gta-field full">
                            <label>Composition</label>
                            <select
                              value={clipForm.template}
                              onChange={(e) => patchClipStyle({ template: e.target.value })}
                            >
                              {CLIP_TEMPLATES.map((t) => (
                                <option key={t.id} value={t.id}>{t.label}</option>
                              ))}
                            </select>
                          </div>
                          {clipForm.template === 'reaction_stack' && (
                            <>
                              <div className="gta-field">
                                <label>Reaction pane ({Math.round(clipForm.split_ratio * 100)}%)</label>
                                <input
                                  type="range"
                                  min={0.28}
                                  max={0.55}
                                  step={0.01}
                                  value={clipForm.split_ratio}
                                  onChange={(e) => patchClipStyle({ split_ratio: Number(e.target.value) })}
                                />
                              </div>
                              <div className="gta-field">
                                <label>Cam crop anchor</label>
                                <select
                                  value={clipForm.cam_anchor}
                                  onChange={(e) => patchClipStyle({ cam_anchor: e.target.value })}
                                >
                                  <option value="top_right">Top right</option>
                                  <option value="top_left">Top left</option>
                                  <option value="top_center">Top center</option>
                                  <option value="center">Center</option>
                                </select>
                              </div>
                            </>
                          )}
                          {(clipForm.template === 'fullscreen_gameplay' || clipForm.template === 'pip') && (
                            <>
                              <div className="gta-field">
                                <label className="gta-check">
                                  <input
                                    type="checkbox"
                                    checked={!!clipForm.apply_zoom}
                                    onChange={(e) => patchClipStyle({ apply_zoom: e.target.checked })}
                                  />
                                  Punch-in zoom
                                </label>
                              </div>
                              <div className="gta-field">
                                <label>Zoom strength ({Number(clipForm.zoom_amount || 1).toFixed(2)}×)</label>
                                <input
                                  type="range"
                                  min={1}
                                  max={1.35}
                                  step={0.01}
                                  value={clipForm.zoom_amount}
                                  disabled={!clipForm.apply_zoom}
                                  onChange={(e) => patchClipStyle({ zoom_amount: Number(e.target.value) })}
                                />
                              </div>
                            </>
                          )}
                        </div>
                      </section>
                    )}

                    {styleTab === 'captions' && (
                      <section className="gta-style-section">
                        <p className="gta-tip">
                          <i className="fas fa-info-circle" aria-hidden="true" />
                          Captions are burned from the transcript automatically — you don’t type them. Toggle style here.
                        </p>
                        <div className="gta-form-grid">
                          <div className="gta-field full">
                            <label className="gta-check">
                              <input
                                type="checkbox"
                                checked={!!clipForm.burn_captions}
                                onChange={(e) => patchClipStyle({ burn_captions: e.target.checked })}
                              />
                              Burn captions into each clip
                            </label>
                          </div>
                          <div className="gta-field">
                            <label>Style</label>
                            <select
                              value={clipForm.caption_style}
                              disabled={!clipForm.burn_captions}
                              onChange={(e) => patchClipStyle({ caption_style: e.target.value })}
                            >
                              <option value="viral">Viral / punchy</option>
                              <option value="bold">Bold outline</option>
                              <option value="clean">Clean</option>
                            </select>
                          </div>
                          <div className="gta-field">
                            <label>Position</label>
                            <select
                              value={clipForm.caption_position}
                              disabled={!clipForm.burn_captions}
                              onChange={(e) => patchClipStyle({ caption_position: e.target.value })}
                            >
                              <option value="top">Top</option>
                              <option value="center">Center</option>
                              <option value="bottom">Bottom</option>
                            </select>
                          </div>
                          <div className="gta-field">
                            <label>Size</label>
                            <select
                              value={clipForm.caption_size}
                              disabled={!clipForm.burn_captions}
                              onChange={(e) => patchClipStyle({ caption_size: e.target.value })}
                            >
                              <option value="sm">Small</option>
                              <option value="md">Medium</option>
                              <option value="lg">Large</option>
                            </select>
                          </div>
                          <div className="gta-field">
                            <label className="gta-check">
                              <input
                                type="checkbox"
                                checked={!!clipForm.highlight_keywords}
                                disabled={!clipForm.burn_captions}
                                onChange={(e) => patchClipStyle({ highlight_keywords: e.target.checked })}
                              />
                              Highlight keywords
                            </label>
                          </div>
                        </div>
                      </section>
                    )}

                    {styleTab === 'cards' && (
                      <section className="gta-style-section">
                        <p className="gta-tip">
                          <i className="fas fa-info-circle" aria-hidden="true" />
                          These are short title cards added before/after the clip — not separate videos.
                        </p>
                        <div className="gta-toggle-grid">
                          <label className={`gta-toggle-card${clipForm.add_intro ? ' on' : ''}`}>
                            <input
                              type="checkbox"
                              checked={!!clipForm.add_intro}
                              onChange={(e) => patchClipStyle({ add_intro: e.target.checked })}
                            />
                            <strong>Intro card</strong>
                            <span>Title flash at the start</span>
                          </label>
                          <label className={`gta-toggle-card${clipForm.add_end_card ? ' on' : ''}`}>
                            <input
                              type="checkbox"
                              checked={!!clipForm.add_end_card}
                              onChange={(e) => patchClipStyle({ add_end_card: e.target.checked })}
                            />
                            <strong>End card</strong>
                            <span>“Follow for more” style closer</span>
                          </label>
                        </div>
                        <div className="gta-form-grid" style={{ marginTop: '0.75rem' }}>
                          <div className="gta-field">
                            <label>Intro length ({Number(clipForm.intro_duration_sec || 1.5).toFixed(1)}s)</label>
                            <input
                              type="range"
                              min={0.8}
                              max={3.5}
                              step={0.1}
                              value={clipForm.intro_duration_sec}
                              disabled={!clipForm.add_intro}
                              onChange={(e) => patchClipStyle({ intro_duration_sec: Number(e.target.value) })}
                            />
                          </div>
                          <div className="gta-field">
                            <label>Custom intro text</label>
                            <input
                              value={clipForm.intro_text}
                              disabled={!clipForm.add_intro}
                              placeholder="Blank = use each clip’s title"
                              onChange={(e) => patchClipStyle({ intro_text: e.target.value })}
                            />
                          </div>
                          <div className="gta-field full">
                            <label>End card text</label>
                            <input
                              value={clipForm.end_card_text}
                              disabled={!clipForm.add_end_card}
                              placeholder="Follow for more"
                              onChange={(e) => patchClipStyle({ end_card_text: e.target.value })}
                            />
                          </div>
                        </div>
                      </section>
                    )}

                    {styleTab === 'overlays' && (
                      <section className="gta-style-section">
                        <p className="gta-tip">
                          <i className="fas fa-info-circle" aria-hidden="true" />
                          Overlays = logo watermark + background music. Upload those assets once in Settings, then turn them on here for every job.
                        </p>
                        <div className="gta-asset-status">
                          <div className={`gta-asset-pill${studio?.settings?.logo_url ? ' ready' : ' missing'}`}>
                            <i className="fas fa-image" aria-hidden="true" />
                            Logo {studio?.settings?.logo_url ? 'ready' : 'not set'}
                          </div>
                          <div className={`gta-asset-pill${studio?.settings?.music_url ? ' ready' : ' missing'}`}>
                            <i className="fas fa-music" aria-hidden="true" />
                            Music {studio?.settings?.music_url ? 'ready' : 'not set'}
                          </div>
                          <button type="button" className="ap-btn secondary" onClick={() => setNav('settings')}>
                            Open Settings
                          </button>
                        </div>
                        <div className="gta-toggle-grid">
                          <label className={`gta-toggle-card${clipForm.show_logo ? ' on' : ''}`}>
                            <input
                              type="checkbox"
                              checked={!!clipForm.show_logo}
                              onChange={(e) => patchClipStyle({ show_logo: e.target.checked })}
                            />
                            <strong>Logo watermark</strong>
                            <span>Uses the Logo URL from Settings</span>
                          </label>
                          <label className={`gta-toggle-card${clipForm.use_music ? ' on' : ''}`}>
                            <input
                              type="checkbox"
                              checked={!!clipForm.use_music}
                              onChange={(e) => patchClipStyle({ use_music: e.target.checked })}
                            />
                            <strong>Background music</strong>
                            <span>Uses the Music URL from Settings</span>
                          </label>
                        </div>
                        <div className="gta-form-grid" style={{ marginTop: '0.75rem' }}>
                          <div className="gta-field">
                            <label>Logo position</label>
                            <select
                              value={clipForm.logo_position}
                              disabled={!clipForm.show_logo}
                              onChange={(e) => patchClipStyle({ logo_position: e.target.value })}
                            >
                              <option value="top_right">Top right</option>
                              <option value="top_left">Top left</option>
                              <option value="bottom_right">Bottom right</option>
                              <option value="bottom_left">Bottom left</option>
                            </select>
                          </div>
                          <div className="gta-field">
                            <label>Logo size ({clipForm.logo_size}px)</label>
                            <input
                              type="range"
                              min={80}
                              max={280}
                              step={10}
                              value={clipForm.logo_size}
                              disabled={!clipForm.show_logo}
                              onChange={(e) => patchClipStyle({ logo_size: Number(e.target.value) })}
                            />
                          </div>
                        </div>
                        {(!studio?.settings?.logo_url || !studio?.settings?.music_url) && (
                          <p className="gta-note" style={{ marginTop: '0.65rem' }}>
                            Missing assets won’t break the job — those overlays are simply skipped until you add URLs in Settings.
                          </p>
                        )}
                      </section>
                    )}
                  </div>

                  <aside className="gta-style-preview" aria-hidden="true">
                    <div className={`gta-phone-mock tmpl-${clipForm.template}`}>
                      {clipForm.add_intro && <div className="intro-bar">INTRO</div>}
                      {clipForm.template === 'reaction_stack' ? (
                        <>
                          <div className="pane top" style={{ flex: clipForm.split_ratio }}>Reaction</div>
                          <div className="pane bot" style={{ flex: 1 - clipForm.split_ratio }}>Gameplay</div>
                        </>
                      ) : (
                        <div className="pane full">Vertical clip</div>
                      )}
                      {clipForm.burn_captions && (
                        <div className={`cap cap-${clipForm.caption_position} cap-${clipForm.caption_size}`}>
                          captions
                        </div>
                      )}
                      {clipForm.show_logo && (
                        <div className={`logo-dot pos-${clipForm.logo_position}`} />
                      )}
                      {clipForm.add_end_card && <div className="end-bar">END</div>}
                    </div>
                    <div className="gta-style-summary">
                      <div><strong>Preset</strong> {clipForm.preset}</div>
                      <div><strong>Layout</strong> {CLIP_TEMPLATES.find((t) => t.id === clipForm.template)?.label}</div>
                      <div>
                        <strong>Captions</strong>{' '}
                        {clipForm.burn_captions
                          ? `${clipForm.caption_style} · ${clipForm.caption_position}`
                          : 'off'}
                      </div>
                      <div>
                        <strong>Extras</strong>{' '}
                        {[
                          clipForm.add_intro && 'intro',
                          clipForm.add_end_card && 'end card',
                          clipForm.show_logo && 'logo',
                          clipForm.use_music && 'music',
                        ].filter(Boolean).join(' · ') || 'none'}
                      </div>
                    </div>
                  </aside>
                </div>
              </>
            )}
          </section>

          <section className="gta-clip-step">
            <div className="gta-clip-step-head">
              <h3><span>3</span> Generate</h3>
            </div>
            <div className="gta-actions gta-generate-actions">
              <button
                type="button"
                className="ap-btn primary"
                disabled={!!busy || !clipForm.source_url.trim()}
                onClick={() => {
                  run('clipurl', async () => {
                    showToast?.('Downloading video — this can take a few minutes…', 'success');
                    const data = await apiFetch('/api/clips/jobs', {
                      method: 'POST',
                      body: JSON.stringify(clipJobBody(clipForm, actor, {
                        source_url: clipForm.source_url.trim(),
                      })),
                    });
                    setFocusJobId(data.job?.id || '');
                    setShowAllReviews(false);
                    showToast?.('Clipping job started — showing only this batch in Review', 'success');
                    setClipForm((prev) => ({ ...prev, source_url: '' }));
                    setNav('review');
                  });
                }}
              >
                {busy === 'clipurl' ? 'Downloading & queuing…' : 'Import URL & generate clips'}
              </button>
              <label className="ap-btn secondary gta-upload-btn">
                {busy === 'clipupload' ? 'Uploading & queuing…' : 'Or upload MP4 / MOV'}
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
                      const data = await apiFetch('/api/clips/jobs', {
                        method: 'POST',
                        body: JSON.stringify(clipJobBody(clipForm, actor, {
                          video_id: uploaded.video?.id,
                        })),
                      });
                      setFocusJobId(data.job?.id || '');
                      setShowAllReviews(false);
                      showToast?.('Clipping job started — showing only this batch in Review', 'success');
                      setNav('review');
                    });
                  }}
                />
              </label>
            </div>
            <p className="gta-note">
              Long YouTube videos take longer to download. Keep this tab open until the job is queued, then check Review.
            </p>
          </section>

          <section className="gta-clip-step gta-clip-jobs">
            <div className="gta-clip-step-head">
              <h3>Recent clip jobs</h3>
            </div>
            {(studio?.jobs || []).filter((j) => j.type === 'clip_job').length === 0 ? (
              <AdminEmptyState
                icon="cut"
                title="No clip jobs yet"
                description="Add a URL above (or upload a file), set your style, then generate."
              />
            ) : (
              <div className="gta-job-list">
                {(studio?.jobs || []).filter((j) => j.type === 'clip_job').slice(0, 8).map((job) => (
                  <div key={job.id} className="gta-job-row">
                    <div className="gta-job-row-main">
                      <h4>{job.name}</h4>
                      <JobProgress job={job} />
                    </div>
                    <div className="gta-job-row-side">
                      <span className={`gta-badge ${statusBadge(job.status)}`}>{job.status}</span>
                      {job.payload?.video_id && !['queued', 'processing'].includes(String(job.status || '').toLowerCase()) && (
                        <button
                          type="button"
                          className="ap-btn secondary"
                          disabled={!!busy}
                          onClick={() => rerunClipJob(job)}
                        >
                          {busy === `rerun-${job.id}` ? 'Rerunning…' : 'Rerun'}
                        </button>
                      )}
                      {(job.status === 'complete' || job.status === 'completed' || job.status === 'failed') && (
                        <button
                          type="button"
                          className="ap-btn secondary"
                          onClick={() => {
                            setFocusJobId(job.id);
                            setShowAllReviews(false);
                            setNav('review');
                          }}
                        >
                          Open
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
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
        <div className="gta-manage">
          <div className="gta-panel">
            <div className="gta-panel-head">
              <div>
                <h2>Review & manage</h2>
                <p className="gta-note gta-panel-lead">
                  Select a run on the left, watch clips on the right, then approve or delete. Source videos live at the bottom.
                </p>
              </div>
              <div className="gta-actions" style={{ marginTop: 0 }}>
                <button
                  type="button"
                  className="ap-btn secondary"
                  onClick={() => setShowAllReviews((v) => !v)}
                >
                  {showAllReviews ? 'Filter to selected run' : 'Show all clips'}
                </button>
                <button type="button" className="ap-btn primary" onClick={() => setNav('clips')}>
                  New clip job
                </button>
              </div>
            </div>
          </div>

          <div className="gta-manage-grid">
            <div className="gta-panel gta-manage-sidebar">
              <h3>Runs</h3>
              {clipJobs.length === 0 ? (
                <div className="gta-note">No runs yet.</div>
              ) : (
                <div className="gta-run-list">
                  {clipJobs.map((job) => {
                    const clipN = (studio?.clips || []).filter((c) => c.job_id === job.id).length;
                    const exportN = (studio?.exports || []).filter((e) => e.job_id === job.id).length;
                    const active = !showAllReviews && job.id === latestClipJobId;
                    return (
                      <div key={job.id} className={`gta-run-card${active ? ' active' : ''}`}>
                        <button
                          type="button"
                          className="gta-run-select"
                          onClick={() => {
                            setFocusJobId(job.id);
                            setShowAllReviews(false);
                          }}
                        >
                          <div className="gta-run-title">{job.name}</div>
                          <div className="gta-meta">
                            {(job.type || '').replace(/_/g, ' ')}
                            {job.created_at ? ` · ${new Date(job.created_at).toLocaleString()}` : ''}
                          </div>
                          <JobProgress job={job} />
                          <div className="gta-run-stats">
                            <span className={`gta-badge ${statusBadge(job.status)}`}>{job.status}</span>
                            <span className="gta-meta">{exportN || clipN} clips</span>
                          </div>
                        </button>
                        <div className="gta-run-actions">
                          {job.type === 'clip_job' && job.payload?.video_id && !['queued', 'processing'].includes(String(job.status || '').toLowerCase()) && (
                            <button
                              type="button"
                              className="ap-btn secondary"
                              disabled={!!busy}
                              onClick={() => rerunClipJob(job)}
                            >
                              {busy === `rerun-${job.id}` ? 'Rerunning…' : 'Rerun same video'}
                            </button>
                          )}
                          <button
                            type="button"
                            className="ap-btn secondary gta-run-delete"
                            disabled={!!busy}
                            onClick={() => deleteRun(job.id)}
                          >
                            Delete run
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              <h3 style={{ marginTop: '1.25rem' }}>Source videos</h3>
              {(studio?.videos || []).length === 0 ? (
                <div className="gta-note">No uploaded / imported videos yet.</div>
              ) : (
                <div className="gta-video-manage-list">
                  {(studio?.videos || []).map((v) => {
                    const usedBy = clipJobs.filter((j) => (j.payload || {}).video_id === v.id).length;
                    return (
                      <div key={v.id} className="gta-video-manage-row">
                        <div className="gta-card-main">
                          <h4>{v.name || 'Video'}</h4>
                          <div className="gta-meta">
                            {v.kind || 'video'}
                            {v.streamer_name ? ` · ${v.streamer_name}` : ''}
                            {v.duration_sec ? ` · ${formatSec(v.duration_sec)}` : ''}
                            {` · ${usedBy} run${usedBy === 1 ? '' : 's'}`}
                          </div>
                          {v.url ? (
                            <a className="gta-meta" href={v.url} target="_blank" rel="noreferrer">Open source</a>
                          ) : null}
                        </div>
                        <button
                          type="button"
                          className="ap-btn secondary"
                          disabled={!!busy}
                          onClick={() => deleteSourceVideo(v.id, v.name)}
                        >
                          Delete
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="gta-panel">
              <div className="gta-panel-head">
                <div>
                  <h3>
                    {showAllReviews
                      ? 'All clips'
                      : (focusedJob?.name || 'Selected run')}
                  </h3>
                  <p className="gta-note" style={{ marginTop: 4 }}>
                    {showAllReviews
                      ? `${reviewExports.length} clips across all runs`
                      : focusedJob
                        ? `${reviewExports.length} clips in this run${focusedJobClipCount ? ` · ${focusedJobClipCount} clip records` : ''}`
                        : 'Select a run on the left'}
                  </p>
                </div>
                {!showAllReviews && focusedJob && (
                  <div className="gta-actions" style={{ marginTop: 0 }}>
                    {focusedJob.type === 'clip_job' && focusedJob.payload?.video_id && !['queued', 'processing'].includes(String(focusedJob.status || '').toLowerCase()) && (
                      <button
                        type="button"
                        className="ap-btn primary"
                        disabled={!!busy}
                        onClick={() => rerunClipJob(focusedJob)}
                      >
                        {busy === `rerun-${focusedJob.id}` ? 'Rerunning…' : 'Rerun same video'}
                      </button>
                    )}
                    <button
                      type="button"
                      className="ap-btn secondary"
                      disabled={!!busy}
                      onClick={() => deleteRun(focusedJob.id)}
                    >
                      Delete this run
                    </button>
                  </div>
                )}
              </div>

              {focusedJob && !showAllReviews && (
                <div className="gta-job-row" style={{ marginBottom: '0.85rem' }}>
                  <div className="gta-job-row-main">
                    <h4>{focusedJob.name}</h4>
                    <JobProgress job={focusedJob} />
                  </div>
                  <span className={`gta-badge ${statusBadge(focusedJob.status)}`}>{focusedJob.status}</span>
                </div>
              )}

              {reviewExports.length === 0 ? (
                <AdminEmptyState
                  icon="check-double"
                  title={showAllReviews ? 'Nothing to review' : 'No clips in this run yet'}
                  description={
                    showAllReviews
                      ? 'Generate streamer clips or an explainer to populate this desk.'
                      : 'Wait for the job to finish rendering, or pick another run.'
                  }
                  ctaLabel="Make streamer clips"
                  onCta={() => setNav('clips')}
                />
              ) : (
                <div className="gta-review-grid">
                  {reviewExports.map((exp) => {
                    const linkedClip = exp.clip_id
                      ? (studio?.clips || []).find((c) => c.id === exp.clip_id)
                      : null;
                    const draft = linkedClip
                      ? (regenDraft[linkedClip.id] || {
                        start_sec: linkedClip.source_start_sec ?? 0,
                        end_sec: linkedClip.source_end_sec ?? (linkedClip.duration_sec || 30),
                      })
                      : null;
                    return (
                      <div key={exp.id} className="gta-review-card">
                        {exp.url ? <ReviewVideo src={exp.url} /> : null}
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                          <h4 style={{ margin: 0 }}>{exp.title || exp.name}</h4>
                          {exp.score != null && (
                            <span className="gta-score" title="Virality score">
                              {Number(exp.score).toFixed(Number(exp.score) % 1 ? 1 : 0)}
                              <small>/100</small>
                            </span>
                          )}
                        </div>
                        <div className="gta-meta">
                          {(exp.pipeline || '').replace(/_/g, ' ')} · {formatSec(exp.duration_sec)}
                          {exp.source_timestamp ? ` · ${exp.source_timestamp}` : ''}
                          {formatMoney(exp.cost_estimate) ? ` · ${formatMoney(exp.cost_estimate)}` : ''}
                        </div>
                        {exp.caption ? <p className="gta-note">{exp.caption}</p> : null}
                        <span className={`gta-badge ${statusBadge(exp.status)}`}>{exp.status}</span>
                        {linkedClip && draft && (
                          <div className="gta-regen">
                            <div className="gta-field">
                              <label>Start</label>
                              <input
                                type="number"
                                value={draft.start_sec}
                                onChange={(e) => setRegenDraft((d) => ({
                                  ...d,
                                  [linkedClip.id]: { ...draft, start_sec: Number(e.target.value) },
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
                                  [linkedClip.id]: { ...draft, end_sec: Number(e.target.value) },
                                }))}
                              />
                            </div>
                            <button
                              type="button"
                              className="ap-btn secondary"
                              disabled={!!busy}
                              onClick={() => run(`regen-${linkedClip.id}`, async () => {
                                await apiFetch(`/api/clips/${linkedClip.id}/regenerate`, {
                                  method: 'POST',
                                  body: JSON.stringify({
                                    start_sec: draft.start_sec,
                                    end_sec: draft.end_sec,
                                    template: linkedClip.template || clipForm.template,
                                  }),
                                });
                                showToast?.('Clip regenerated', 'success');
                              })}
                            >
                              Regenerate
                            </button>
                          </div>
                        )}
                        <div className="gta-actions">
                          {exp.url && (
                            <a className="ap-btn secondary" href={exp.url} target="_blank" rel="noreferrer" download>
                              Download
                            </a>
                          )}
                          <button
                            type="button"
                            className="ap-btn primary"
                            disabled={exp.status === 'approved'}
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
                            disabled={exp.status === 'rejected'}
                            onClick={() => run('rejectExport', async () => {
                              await apiFetch(`/api/exports/${exp.id}/reject`, { method: 'POST' });
                              showToast?.('Rejected', 'success');
                            })}
                          >
                            Reject
                          </button>
                          <button
                            type="button"
                            className="ap-btn secondary"
                            disabled={!!busy}
                            onClick={() => deleteExportCard(exp)}
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {nav === 'settings' && settingsDraft && (
        <div className="gta-panel">
          <div className="gta-panel-head">
            <div>
              <h2>Studio settings</h2>
              <p className="gta-note gta-panel-lead">
                Logo and music here power the Overlays toggles on Streamer clips. Set them once, then turn them on per job.
              </p>
            </div>
            <button type="button" className="ap-btn secondary" onClick={() => setNav('clips')}>
              Back to clips
            </button>
          </div>
          <div className="gta-form-grid">
            <div className="gta-field">
              <label>Channel name</label>
              <input
                value={settingsDraft.channel_name || ''}
                onChange={(e) => setSettingsDraft({ ...settingsDraft, channel_name: e.target.value })}
              />
            </div>
            <div className="gta-field">
              <label>Default explainer template</label>
              <select
                value={settingsDraft.default_template || 'facecam_top'}
                onChange={(e) => setSettingsDraft({ ...settingsDraft, default_template: e.target.value })}
              >
                {TEMPLATES.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
              </select>
            </div>
            <div className="gta-field full">
              <label>Logo URL (watermark overlay)</label>
              <input
                value={settingsDraft.logo_url || ''}
                onChange={(e) => setSettingsDraft({ ...settingsDraft, logo_url: e.target.value })}
                placeholder="https://…/logo.png"
              />
              <p className="gta-field-hint">Used when “Logo watermark” is on in Streamer clips → Overlays.</p>
            </div>
            <div className="gta-field full">
              <label>Background music URL</label>
              <input
                value={settingsDraft.music_url || ''}
                onChange={(e) => setSettingsDraft({ ...settingsDraft, music_url: e.target.value })}
                placeholder="https://…/track.mp3"
              />
              <p className="gta-field-hint">Used when “Background music” is on in Streamer clips → Overlays.</p>
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
