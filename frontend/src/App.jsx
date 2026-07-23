import React, { useEffect, useMemo, useState } from 'react';
import ClinicalShell from './components/ClinicalShell.jsx';

const configuredApiBase = import.meta.env.VITE_API_BASE_URL?.trim();
const API_BASE_URL = (configuredApiBase || (import.meta.env.DEV ? '/api' : '')).replace(/\/$/, '');
const REQUEST_TIMEOUT_MS = 120000;
const DOC_SCALING_OPTIONS = [5, 10, 15, 20];
const DEFAULT_DOC_TOP_K = 15;
const DEFAULT_L2_MODEL = 'qwen2.5:7b';
const SAMPLE_CASE = 'เด็กหญิงถูกแม่ดุด่าเป็นประจำ ครอบครัวรายได้น้อย เครียดมากและไม่อยากไปโรงเรียน';
const PUBLIC_DEMO_MODE = import.meta.env.VITE_PUBLIC_DEMO === 'true';

const DEFAULT_STRATEGY_PAIRS = [
  { family: 'bm25', label: 'BM25', baseline: 'bm25_only', enhanced: 'h2l-bm25', description: 'ค้นจากคำตรงและคำใกล้เคียง' },
  { family: 'dense', label: 'Dense / Naive RAG', baseline: 'naive_rag', enhanced: 'h2l-naive_rag', description: 'ค้นด้วย embedding อย่างเดียว' },
  { family: 'hyde', label: 'HyDE', baseline: 'hyde', enhanced: 'h2l-hyde', description: 'ใช้ hypothetical document ก่อนค้น' },
  { family: 'hybrid', label: 'Hybrid', baseline: 'basic', enhanced: 'h2l-hybrid', description: 'รวม BM25 + embedding + rerank' },
];

const STRATEGY_LOOKUP = DEFAULT_STRATEGY_PAIRS.reduce((acc, pair) => {
  acc[pair.baseline] = { family: pair.family, familyLabel: pair.label, role: 'baseline', label: `${pair.label} Baseline`, shortLabel: pair.label };
  acc[pair.enhanced] = { family: pair.family, familyLabel: pair.label, role: 'h2l', label: `${pair.label} + H2L`, shortLabel: `H2L ${pair.label}` };
  return acc;
}, {});

const emptyResult = {
  status: 'empty',
  mode: 'runtime-rag-h2l',
  requested_strategy: 'h2l-hybrid',
  top_k: DEFAULT_DOC_TOP_K,
  doc_scaling: { selected_top_k: DEFAULT_DOC_TOP_K, options: DOC_SCALING_OPTIONS },
  case_description: '',
  severity_level: 'NOT_ASSESSED',
  problems: [],
  filtered_out: [],
  tools: [],
  metrics: { type: 'case_operational_metrics', avg_confidence: 0, problems_found: 0, candidate_count: 0, accepted_count: 0, filtered_count: 0, retrieved_docs_count: 0, ground_truth_metrics_available: false },
  score_components: [],
  detection_info: {
    l1_count: 0,
    l2_count: 0,
    final_count: 0,
    filtered_count: 0,
    l2_requested: true,
    l2_ready: false,
    l2_applied: false,
    conflicts: {},
    needs_l2_validation: [],
    ambiguity_summary: {
      label: 'Review Load',
      count: 0,
      level: 'low',
      review_codes: [],
      review_count: 0,
      conflict_codes: [],
      conflict_code_count: 0,
      conflict_links: 0,
      needs_validation_count: 0,
      l1_filtered_count: 0,
      interpretation: '',
    },
  },
  candidate_trace: { candidates: [], filter_reasons: [], candidate_count: 0, final_accepted: 0, filtered_out: 0 },
  candidates: [],
  filter_reasons: [],
  retrieved_docs: [],
  retrieved_docs_count: 0,
  retrieval_trace: { errors: [], docs_returned: 0 },
  h2l_scoring_trace: [],
  keyword_analysis: { total_keywords: 0, unique_keywords: [], rows: [], filtered_out: [] },
  sentence_profile: {
    length: 0,
    length_category: 'short',
    negation_markers: [],
    actors: [],
    actor_roles: { agents: [], targets: [], actions: [], voice: 'active', relation_summary: '', mentions: [] },
    has_negation: false,
  },
  polarity_effect: { rows: [], interpretation: '' },
  vector_space: { nodes: [], edges: [], projection: 'not-generated', note: 'Run analysis after runtime is ready.' },
  detection_flow: { steps: [], filtered_count: 0, phase_timings_ms: {} },
  runtime_status: { status: 'loading', stage: 'not-started', components: {}, errors: [] },
};

const navItems = [
  {
    id: 'analysis',
    label: 'ทบทวนเคส',
    description: 'Case review and professional assessment',
    icon: 'clinical_notes',
    group: 'clinical',
    groupLabel: 'งานสังคมสงเคราะห์คลินิก',
  },
  {
    id: 'explainability',
    label: 'เหตุผลของระบบ',
    description: 'Language, evidence map and processing trace',
    icon: 'manage_search',
    group: 'explainability',
    groupLabel: 'ความโปร่งใสและการตรวจสอบ',
  },
  {
    id: 'evaluation',
    label: 'หลักฐานงานวิจัย',
    description: 'Benchmark, statistics and provenance',
    icon: 'query_stats',
    group: 'research',
    groupLabel: 'คุณภาพและงานวิจัย',
  },
];

const explainabilityTabs = [
  { id: 'keywords', label: 'บริบทภาษา', icon: 'biotech' },
  { id: 'pipeline', label: 'ลำดับการวิเคราะห์', icon: 'account_tree' },
  { id: 'vectors', label: 'แผนที่หลักฐาน', icon: 'hub' },
];

const FINDING_REVIEW_OPTIONS = [
  { id: 'accepted', label: 'รับไว้', icon: 'check_circle', tone: 'emerald' },
  { id: 'review', label: 'ต้องทบทวน', icon: 'help', tone: 'amber' },
  { id: 'excluded', label: 'ไม่นำไปใช้', icon: 'block', tone: 'slate' },
];

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'N/A';
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function formatNumber(value, digits = 3) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'N/A';
  return Number(value).toFixed(digits);
}

function formatDurationMs(value) {
  const duration = Number(value);
  if (!Number.isFinite(duration) || duration <= 0) return 'n/a';
  if (duration < 1000) return `${duration >= 100 ? duration.toFixed(0) : duration.toFixed(1)} ms`;
  return `${(duration / 1000).toFixed(duration >= 10000 ? 1 : 2)} s`;
}

function formatDateTime(value) {
  if (!value) return 'N/A';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('th-TH', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

function shortArtifactLabel(value) {
  if (!value) return 'N/A';
  const text = String(value);
  const parts = text.split('/');
  return parts[parts.length - 1] || text;
}

function progressCountLabel(completed, total) {
  const done = Number(completed);
  const all = Number(total);
  if (!Number.isFinite(done) || !Number.isFinite(all) || all <= 0) return 'N/A';
  return `${done}/${all}`;
}

function strategyDisplayName(strategy) {
  const meta = STRATEGY_LOOKUP[strategy];
  if (meta?.shortLabel) return meta.shortLabel;
  if (!strategy) return 'Unknown';
  return String(strategy).replaceAll('_', ' ');
}

function problemCodeGroup(code) {
  const value = String(code || '').trim();
  const match = value.match(/^(\d{2})/);
  if (match) return match[1];
  if (value.startsWith('F')) return 'F';
  if (value.startsWith('T')) return 'T';
  if (value.startsWith('X')) return 'X';
  if (value.startsWith('Z')) return 'Z';
  return 'other';
}

function problemCodeGroupLabel(group) {
  if (!group || group === 'other') return 'Other';
  return String(group).toUpperCase();
}

function problemSourceMeta(source) {
  if (source === 'detected') {
    return {
      label: 'System-detected problems',
      shortLabel: 'detected',
      meaning: 'ใช้ปัญหาที่ระบบตรวจพบเองจากข้อความจริง เป็นผลหลักแบบ end-to-end',
    };
  }
  if (source === 'gold') {
    return {
      label: 'Reference problems',
      shortLabel: 'reference',
      meaning: 'ใช้ปัญหาอ้างอิงจาก ground truth เพื่อดูศักยภาพสูงสุดของ retriever',
    };
  }
  return {
    label: String(source || 'unknown'),
    shortLabel: String(source || 'unknown'),
    meaning: 'ยังไม่มีคำอธิบายสำหรับ source นี้',
  };
}

function severityStyle(severity) {
  const value = Number(severity || 1);
  if (value >= 4) return { label: 'High', soft: 'bg-red-50 dark:bg-red-950/40', chip: 'bg-red-600 text-white', line: 'border-red-500', node: '#ef4444' };
  if (value === 3) return { label: 'Moderate', soft: 'bg-yellow-50 dark:bg-yellow-950/40', chip: 'bg-yellow-500 text-slate-950', line: 'border-yellow-400', node: '#facc15' };
  return { label: 'Low', soft: 'bg-green-50 dark:bg-green-950/40', chip: 'bg-green-600 text-white', line: 'border-green-500', node: '#10b981' };
}

function metricBackground(value, invert = false) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'bg-surface-container-lowest';
  const number = Math.max(0, Math.min(1, Number(value)));
  const score = invert ? 1 - number : number;
  if (score >= 0.7) return 'bg-green-50 dark:bg-green-950/40';
  if (score >= 0.4) return 'bg-yellow-50 dark:bg-yellow-950/40';
  return 'bg-red-50 dark:bg-red-950/40';
}

function statusTone(status) {
  if (status === 'ready' || status === 'ok' || status === 'live') return 'live';
  if (status === 'degraded' || status === 'warning') return 'warning';
  if (status === 'error' || status === 'failed') return 'error';
  return 'neutral';
}

function StatusBadge({ label, tone = 'neutral' }) {
  const toneClass = {
    live: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-200',
    warning: 'bg-amber-100 text-amber-900 dark:bg-amber-950/60 dark:text-amber-200',
    error: 'bg-red-100 text-red-800 dark:bg-red-950/60 dark:text-red-200',
    neutral: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
  }[tone] || 'bg-surface-container-high text-on-surface-variant';

  return <span className={`inline-flex min-h-6 items-center rounded-full px-2.5 py-1 text-xs font-semibold leading-none ${toneClass}`}>{label}</span>;
}

function MetricTile({ label, value, hint, tone = 'bg-surface-container-lowest' }) {
  return (
    <div className={`min-h-[116px] rounded-lg p-4 transition-colors duration-200 ${tone}`} title={hint || label}>
      <div className="text-xs font-semibold text-on-surface-variant">{label}</div>
      <div className="mt-2 font-headline text-2xl font-bold tabular-nums text-on-surface">{value}</div>
      {hint && <div className="mt-1 text-xs leading-relaxed text-on-surface-variant">{hint}</div>}
    </div>
  );
}

function SegmentedBar({ value, tone = 'teal' }) {
  const filled = Math.max(0, Math.min(10, Math.round((Number(value) || 0) * 10)));
  const fillClass = tone === 'error' ? 'bg-error' : tone === 'warning' ? 'bg-yellow-400' : 'bg-teal-500';
  return (
    <div className="flex h-1.5 gap-1.5">
      {Array.from({ length: 10 }, (_, index) => (
        <div key={index} className={`flex-1 rounded-sm ${index < filled ? fillClass : 'bg-surface-container-highest/60'}`} />
      ))}
    </div>
  );
}

async function fetchJson(path, options = {}, timeoutMs = REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, { ...options, signal: controller.signal });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data?.detail;
      const message = typeof detail === 'string' ? detail : detail?.message || data?.message || `API returned ${response.status}`;
      const error = new Error(message);
      error.payload = data;
      throw error;
    }
    return data;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function problemInterpretation(problem) {
  const severity = Number(problem.severity || 1);
  const confidence = Number(problem.confidence || 0);
  const keywords = (problem.matched_keywords || []).join(', ') || 'ไม่พบ keyword ตรง';
  const risk = severity >= 4 ? 'ความเสี่ยงสูง ต้องมีผู้เชี่ยวชาญทบทวน' : severity === 3 ? 'ความเสี่ยงระดับกลาง ควรอ่านร่วมกับ evidence' : 'สัญญาณสนับสนุนภาพรวมของเคส';
  const confidenceText = confidence >= 0.7 ? 'detector มั่นใจสูง' : confidence >= 0.45 ? 'detector มั่นใจปานกลาง' : 'detector มั่นใจต่ำ';
  return `${risk}; ${confidenceText}; keyword หลัก: ${keywords}`;
}

function resultInterpretation(result) {
  const problems = result.problems || [];
  if (!problems.length) return 'ระบบไม่พบประเด็นที่ผ่านเกณฑ์จากข้อความที่ให้ ผลนี้ไม่ใช่การยืนยันว่าปลอดภัย ผู้ปฏิบัติงานยังต้องตรวจข้อมูลต้นฉบับ บริบทความเสี่ยง และข้อมูลที่อาจยังไม่ได้บันทึก';
  const high = problems.filter((item) => Number(item.severity || 1) >= 4).length;
  const moderate = problems.filter((item) => Number(item.severity || 1) === 3).length;
  const docs = result.retrieved_docs_count || 0;
  return `พบรหัสปัญหา ${problems.length} รายการ ระดับสูง ${high} รายการ ระดับกลาง ${moderate} รายการ และมีเอกสาร evidence จาก retrieval ${docs} รายการ ผลนี้เป็น decision support สำหรับ human review ไม่ใช่คำวินิจฉัยสุดท้าย`;
}

function tokenizeCaseText(text, lexicalTokens) {
  if (!text) return [];
  const matches = [];
  lexicalTokens
    .filter((token) => token.value)
    .sort((a, b) => {
      const leftHasSpan = Number.isInteger(a.start) && Number.isInteger(a.end) && a.end > a.start;
      const rightHasSpan = Number.isInteger(b.start) && Number.isInteger(b.end) && b.end > b.start;
      const priority = { agent: 0, target: 1, action: 2, negation: 3, keyword: 4 };
      if (leftHasSpan && rightHasSpan) {
        return (priority[a.type] ?? 9) - (priority[b.type] ?? 9)
          || (b.end - b.start) - (a.end - a.start)
          || a.start - b.start;
      }
      if (leftHasSpan !== rightHasSpan) return leftHasSpan ? -1 : 1;
      return (priority[a.type] ?? 9) - (priority[b.type] ?? 9)
        || b.value.length - a.value.length;
    })
    .forEach((token) => {
      const hasExplicitSpan = Number.isInteger(token.start) && Number.isInteger(token.end) && token.end > token.start;
      if (hasExplicitSpan) {
        const overlaps = matches.some((match) => token.start < match.end && token.end > match.start);
        if (!overlaps) matches.push({ ...token });
        return;
      }

      let start = text.indexOf(token.value);
      while (start >= 0) {
        const end = start + token.value.length;
        const overlaps = matches.some((match) => start < match.end && end > match.start);
        if (!overlaps) matches.push({ ...token, start, end });
        start = text.indexOf(token.value, end);
      }
    });
  matches.sort((a, b) => a.start - b.start);

  const parts = [];
  let cursor = 0;
  matches.forEach((match) => {
    if (match.start > cursor) parts.push({ type: 'plain', value: text.slice(cursor, match.start), start: cursor, end: match.start });
    parts.push({ ...match, value: text.slice(match.start, match.end) });
    cursor = match.end;
  });
  if (cursor < text.length) parts.push({ type: 'plain', value: text.slice(cursor), start: cursor, end: text.length });
  return parts;
}

function spanOverlaps(leftStart, leftEnd, rightStart, rightEnd) {
  return leftStart < rightEnd && rightStart < leftEnd;
}

function findAllSpanOccurrences(text, needle) {
  if (!text || !needle) return [];
  const spans = [];
  let start = text.indexOf(needle);
  while (start >= 0) {
    spans.push({ start, end: start + needle.length });
    start = text.indexOf(needle, start + needle.length);
  }
  return spans;
}

function RuntimeBanner({ runtimeStatus, onRefresh }) {
  const status = runtimeStatus?.status || 'loading';
  const components = runtimeStatus?.components || {};
  const loadedCount = Object.values(components).filter(Boolean).length;
  const totalCount = Object.keys(components).length;
  const errors = runtimeStatus?.errors || [];
  const isLoading = status === 'loading';
  const [expandedOverride, setExpandedOverride] = useState(null);
  const detailsVisible = expandedOverride ?? status === 'error';
  const percent = totalCount ? Math.round((loadedCount / totalCount) * 100) : status === 'ready' ? 100 : 0;
  const statusMeta = {
    ready: {
      icon: 'verified',
      title: 'ระบบพร้อมสำหรับการวิเคราะห์',
      detail: 'โมเดล ดัชนีเอกสาร และระบบค้นคืนข้อมูลพร้อมใช้งาน',
      tone: 'live',
    },
    degraded: {
      icon: 'warning',
      title: 'ระบบทำงานในโหมดจำกัด',
      detail: 'บางองค์ประกอบไม่พร้อม ระบบจะระบุวิธีที่ใช้จริงในผลลัพธ์',
      tone: 'warning',
    },
    loading: {
      icon: 'progress_activity',
      title: 'กำลังเตรียมระบบวิเคราะห์',
      detail: 'กำลังโหลดโมเดลและดัชนีเอกสาร',
      tone: 'neutral',
    },
    error: {
      icon: 'error',
      title: 'ไม่สามารถเชื่อมต่อระบบวิเคราะห์',
      detail: 'ตรวจสอบ backend หรือกดตรวจสอบระบบอีกครั้ง',
      tone: 'error',
    },
  }[status] || {
    icon: 'info',
    title: 'สถานะระบบไม่ทราบค่า',
    detail: runtimeStatus?.stage || 'กรุณาตรวจสอบระบบ',
    tone: 'neutral',
  };

  return (
    <section className="mb-5 overflow-hidden rounded-lg border border-slate-200/80 bg-white dark:border-slate-800 dark:bg-slate-900/60" aria-label="สถานะระบบวิเคราะห์">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-5">
        <div className="flex min-w-0 items-center gap-3">
          <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${status === 'error' ? 'bg-red-50 text-red-600 dark:bg-red-950/50 dark:text-red-300' : status === 'degraded' ? 'bg-amber-50 text-amber-600 dark:bg-amber-950/50 dark:text-amber-300' : 'bg-teal-50 text-teal-700 dark:bg-teal-950/50 dark:text-teal-300'}`}>
            <span aria-hidden="true" className={`material-symbols-outlined text-[21px] ${isLoading ? 'animate-spin' : ''}`}>{statusMeta.icon}</span>
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-sm font-semibold text-on-surface">{statusMeta.title}</h2>
              <StatusBadge label={runtimeStatus?.l2_ready ? 'L2 พร้อม' : 'L2 ไม่พร้อม'} tone={runtimeStatus?.l2_ready ? 'live' : 'warning'} />
            </div>
            <p className="mt-0.5 truncate text-xs text-on-surface-variant">{statusMeta.detail}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            aria-label="ตรวจสอบสถานะระบบอีกครั้ง"
            className="flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm font-semibold text-slate-600 transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 dark:text-slate-300 dark:hover:bg-slate-800"
            onClick={onRefresh}
            type="button"
          >
            <span aria-hidden="true" className={`material-symbols-outlined text-[19px] ${isLoading ? 'animate-spin' : ''}`}>sync</span>
            <span className="hidden sm:inline">ตรวจสอบอีกครั้ง</span>
          </button>
          <button
            aria-expanded={detailsVisible}
            className="flex h-11 w-11 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 dark:text-slate-300 dark:hover:bg-slate-800"
            onClick={() => setExpandedOverride(!detailsVisible)}
            type="button"
          >
            <span aria-hidden="true" className={`material-symbols-outlined transition-transform ${detailsVisible ? 'rotate-180' : ''}`}>expand_more</span>
            <span className="sr-only">{detailsVisible ? 'ซ่อนรายละเอียดระบบ' : 'แสดงรายละเอียดระบบ'}</span>
          </button>
        </div>
      </div>

      {isLoading && (
        <div className="h-1 bg-slate-100 dark:bg-slate-800">
          <div className="h-1 bg-teal-600 transition-[width] duration-300" style={{ width: `${percent}%` }} />
        </div>
      )}

      {detailsVisible && (
        <div className="border-t border-slate-200/80 bg-slate-50/70 px-4 py-4 dark:border-slate-800 dark:bg-slate-950/30 sm:px-5">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Object.entries(components).map(([name, ready]) => (
              <div className="flex items-center justify-between gap-3 rounded-lg bg-white px-3 py-2.5 text-sm dark:bg-slate-900" key={name}>
                <span className="truncate font-medium text-on-surface">{name.replaceAll('_', ' ')}</span>
                <span aria-hidden="true" className={`material-symbols-outlined text-[18px] ${ready ? 'text-emerald-600 dark:text-emerald-300' : 'text-amber-500'}`}>{ready ? 'check_circle' : 'pending'}</span>
              </div>
            ))}
            {!Object.keys(components).length && <div className="text-sm text-on-surface-variant">ยังไม่ได้รับรายละเอียดองค์ประกอบจาก runtime</div>}
          </div>
          <div className="mt-3 flex flex-wrap gap-2 text-xs text-on-surface-variant">
            <span>Stage: <strong className="text-on-surface">{runtimeStatus?.stage || 'unknown'}</strong></span>
            <span>พร้อม {loadedCount}/{totalCount || 0} องค์ประกอบ</span>
          </div>
          {errors.length > 0 && (
            <div className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-950 dark:bg-amber-950/40 dark:text-amber-100" role="alert">
              <div className="font-semibold">รายละเอียดที่ต้องตรวจสอบ</div>
              <ul className="mt-2 space-y-1">
                {errors.slice(0, 4).map((item, index) => (
                  <li key={`${item.component}-${index}`}><strong>{item.component}:</strong> {item.message}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function StrategySelector({ pairs, strategyOptions, selectedFamily, setSelectedFamily, selectedMode, setSelectedMode, selectedStrategy, enableL2, setEnableL2, disabled }) {
  const selectedPair = pairs.find((pair) => pair.family === selectedFamily) || pairs[0];

  const getOptionStatus = (id) => {
    if (!strategyOptions) return { available: true };
    return strategyOptions.find(opt => opt.id === id) || { available: true };
  };

  return (
    <fieldset className="rounded-lg bg-white p-4 dark:bg-slate-900/70 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <legend className="font-headline text-base font-semibold text-on-surface">วิธีค้นคืนข้อมูล</legend>
          <p className="mt-1 text-sm text-on-surface-variant">เลือกเฉพาะเมื่อทำการเปรียบเทียบเชิงวิจัย</p>
        </div>
        <StatusBadge label={selectedStrategy} tone={selectedMode === 'enhanced' ? 'live' : 'neutral'} />
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {pairs.map((pair) => {
          const baselineStatus = getOptionStatus(pair.baseline);
          const enhancedStatus = getOptionStatus(pair.enhanced);
          const isFamilyAvailable = baselineStatus.available || enhancedStatus.available;
          const isActive = pair.family === selectedFamily;
          return (
            <button
              aria-pressed={isActive}
              className={`min-h-12 rounded-lg border px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 ${
                isActive
                  ? 'border-teal-600 bg-teal-50 text-teal-900 dark:bg-teal-950/40 dark:text-teal-100'
                  : 'border-slate-200 bg-slate-50 text-on-surface hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800/70 dark:hover:bg-slate-800'
              }`}
              disabled={disabled || !isFamilyAvailable}
              key={pair.family}
              onClick={() => setSelectedFamily(pair.family)}
              type="button"
            >
              <span className="block text-sm font-semibold">{pair.label}</span>
              <span className="mt-0.5 block line-clamp-1 text-xs text-on-surface-variant">{isFamilyAvailable ? pair.description : 'ไม่พร้อมใน runtime ปัจจุบัน'}</span>
            </button>
          );
        })}
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(260px,0.7fr)] lg:items-start">
        <div>
          <div className="mb-2 text-sm font-semibold text-on-surface">ระดับการประมวลผล</div>
          <div className="inline-grid w-full grid-cols-2 rounded-lg bg-slate-100 p-1 dark:bg-slate-800 sm:w-auto sm:min-w-[360px]" role="group" aria-label="ระดับการประมวลผล">
            {[
              { id: 'baseline', label: 'Baseline', strategy: selectedPair?.baseline },
              { id: 'enhanced', label: 'H2L Enhanced', strategy: selectedPair?.enhanced },
            ].map((mode) => {
              const optionStatus = getOptionStatus(mode.strategy);
              const active = selectedMode === mode.id;
              return (
                <button
                  aria-pressed={active}
                  className={`min-h-11 rounded-md px-3 py-2 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 ${active ? 'bg-white text-[#0f766e] shadow-sm dark:bg-slate-700 dark:text-teal-200' : 'text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white'}`}
                  disabled={disabled || !optionStatus.available}
                  key={mode.id}
                  onClick={() => setSelectedMode(mode.id)}
                  type="button"
                >
                  <span className="block">{mode.label}</span>
                  <span className="mt-0.5 block truncate text-xs font-normal opacity-70">{mode.strategy}</span>
                </button>
              );
            })}
          </div>
        </div>

        <label className={`flex min-h-14 items-center justify-between gap-4 rounded-lg bg-slate-50 px-3 py-2.5 dark:bg-slate-800/70 ${disabled || selectedMode === 'baseline' ? 'opacity-55' : ''}`}>
          <span className="flex min-w-0 items-center gap-3">
            <span aria-hidden="true" className="material-symbols-outlined shrink-0 text-[20px] text-teal-600 dark:text-teal-300">verified_user</span>
            <span className="min-w-0">
              <span className="block text-sm font-semibold text-on-surface">ตรวจสอบเชิงความหมาย L2</span>
              <span className="mt-0.5 block text-xs text-on-surface-variant">{selectedMode === 'baseline' ? 'ปิดในโหมด Baseline' : 'เพิ่มการตรวจบริบทโดยโมเดลภาษา'}</span>
            </span>
          </span>
          <span className="relative inline-flex shrink-0 items-center">
            <input
              aria-label="เปิดการตรวจสอบเชิงความหมาย L2"
              checked={enableL2 && selectedMode !== 'baseline'}
              className="peer sr-only"
              disabled={disabled || selectedMode === 'baseline'}
              name="enable-l2"
              onChange={(event) => setEnableL2(event.target.checked)}
              type="checkbox"
            />
            <span className="h-6 w-11 rounded-full bg-slate-300 after:absolute after:left-0.5 after:top-0.5 after:h-5 after:w-5 after:rounded-full after:bg-white after:transition-transform after:content-[''] peer-checked:bg-teal-600 peer-checked:after:translate-x-5 peer-focus-visible:ring-2 peer-focus-visible:ring-teal-600 peer-focus-visible:ring-offset-2" />
          </span>
        </label>
      </div>
    </fieldset>
  );
}


function L2ModelSelector({ disabled, enabled, modelOptions, onChange, value }) {
  const selected = modelOptions.find((option) => option.id === value);
  const controlDisabled = disabled || !enabled;

  return (
    <section className={`rounded-lg bg-white p-4 dark:bg-slate-900/70 sm:p-5 ${controlDisabled ? 'opacity-60' : ''}`} aria-labelledby="l2-model-label">
      <div className="grid gap-3 lg:grid-cols-[minmax(0,0.9fr)_minmax(260px,1.1fr)] lg:items-center">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold text-on-surface" id="l2-model-label">โมเดลอ่านบริบท L2</h2>
            {selected && <StatusBadge label={selected.available ? 'พร้อมใช้' : 'ไม่พร้อม'} tone={selected.available ? 'live' : 'warning'} />}
          </div>
          <p className="mt-1 text-xs leading-relaxed text-on-surface-variant">เปลี่ยนเฉพาะ semantic validation โดย embedding, reranker และสูตร H2L คงเดิม</p>
        </div>
        <div>
          <label className="sr-only" htmlFor="l2-model-select">เลือกโมเดลอ่านบริบท L2</label>
          <select
            aria-describedby="l2-model-detail"
            className="min-h-12 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-base font-semibold text-on-surface focus:border-teal-600 focus:outline-none focus:ring-2 focus:ring-teal-600/20 disabled:cursor-not-allowed dark:border-slate-700 dark:bg-slate-950"
            disabled={controlDisabled}
            id="l2-model-select"
            onChange={(event) => onChange(event.target.value)}
            value={value}
          >
            {modelOptions.map((option) => (
              <option disabled={!option.available} key={option.id} value={option.id}>
                {option.label}{option.default ? ' (ค่าเริ่มต้น)' : ''}{option.available ? '' : ' - ไม่พร้อม'}
              </option>
            ))}
          </select>
          <p className="mt-2 text-xs text-on-surface-variant" id="l2-model-detail">
            {selected ? `${selected.parameters || 'N/A'} · ${selected.size_gb ? `${selected.size_gb.toFixed(2)} GiB` : 'ไม่ระบุขนาด'} · ${selected.detail}` : 'กำลังอ่านรายการโมเดลจาก runtime'}
          </p>
        </div>
      </div>
    </section>
  );
}


function DocScalingSelector({ value, onChange, disabled }) {
  const currentIndex = Math.max(0, DOC_SCALING_OPTIONS.indexOf(Number(value)));
  const progress = currentIndex / (DOC_SCALING_OPTIONS.length - 1 || 1);
  const currentLabel = {
    5: 'เฉพาะเจาะจง',
    10: 'สมดุล',
    15: 'ครอบคลุม',
    20: 'สูงสุด',
  }[Number(value)] || 'custom';
  const handleScaleChange = (event) => {
    onChange(Number(event.target.value));
  };

  return (
    <div className="rounded-lg bg-white px-4 py-4 dark:bg-slate-900/70">
      <div className="grid gap-3 lg:grid-cols-[minmax(170px,0.9fr)_minmax(280px,1.6fr)_auto] lg:items-center">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-on-surface">จำนวนหลักฐานที่ค้นคืน</div>
          <p className="mt-0.5 text-xs text-on-surface-variant">Top-K 5–20 รายการ</p>
        </div>

        <div className="relative pt-3">
          <div className="pointer-events-none absolute left-0 right-0 top-[24px] h-1.5 rounded-full bg-surface-container-high">
            <div
              className="h-1.5 rounded-full bg-teal-600 transition-[width]"
              style={{ width: `${progress * 100}%` }}
            />
          </div>
          <input
            aria-label="จำนวนหลักฐาน Top K สำหรับเคส"
            className="relative z-10 h-7 w-full cursor-pointer appearance-none bg-transparent accent-teal-600 disabled:cursor-not-allowed disabled:opacity-50 [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-white [&::-moz-range-thumb]:bg-teal-600 [&::-moz-range-thumb]:shadow-md [&::-moz-range-track]:bg-transparent [&::-webkit-slider-runnable-track]:h-1.5 [&::-webkit-slider-runnable-track]:rounded-full [&::-webkit-slider-runnable-track]:bg-transparent [&::-webkit-slider-thumb]:-mt-1.5 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-white [&::-webkit-slider-thumb]:bg-teal-600 [&::-webkit-slider-thumb]:shadow-md"
            disabled={disabled}
            max="20"
            min="5"
            name="case-evidence-top-k"
            onChange={handleScaleChange}
            step="5"
            type="range"
            value={value}
          />
          <div className="mt-0.5 grid grid-cols-4 gap-1">
            {DOC_SCALING_OPTIONS.map((option) => {
              const isActive = option === Number(value);
              return (
                <button
                  aria-pressed={isActive}
                  className={`min-h-10 rounded-md px-1.5 py-1 text-center text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 ${isActive ? 'bg-teal-600 text-white shadow-sm' : 'text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface'}`}
                  disabled={disabled}
                  key={option}
                  onClick={() => onChange(option)}
                  type="button"
                >
                  {option}
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex items-center justify-between gap-2 lg:justify-end">
          <div className="rounded-lg bg-[#0d2734] px-3 py-2 text-right text-white shadow-sm">
            <span className="font-headline text-lg font-bold leading-none">Top {value}</span>
          </div>
          <div className="hidden min-w-[116px] text-xs lg:block">
            <div className="font-semibold text-on-surface">{currentLabel}</div>
            <div className="text-on-surface-variant">ใช้กับเคสนี้</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ProblemCard({ active, disabled, onFocus, onReviewChange, problem, reviewState = 'pending' }) {
  const severity = Number(problem.severity || 1);
  const confidence = Number(problem.confidence || 0);
  const tone = severityStyle(severity);
  const isL2 = String(problem.detection_level || 'L1').includes('L2') || String(problem.detection_level || 'L1').includes('Implicit');
  const reviewTone = problem.review_tone || (problem.review_status === 'confirmed' ? 'live' : problem.review_status === 'filtered' ? 'neutral' : 'warning');
  const reviewLabel = problem.review_status === 'confirmed'
    ? 'ระบบพบหลักฐานสนับสนุน'
    : problem.review_status === 'filtered'
      ? 'ระบบไม่นำไปใช้'
      : problem.review_label || 'ต้องให้ผู้ปฏิบัติงานทบทวน';
  const [expanded, setExpanded] = useState(false);

  const toggleExpanded = () => {
    setExpanded((value) => !value);
    onFocus?.(problem.code);
  };

  return (
    <article className={`overflow-hidden rounded-lg border-l-4 ${tone.line} bg-white shadow-sm shadow-slate-900/5 transition-shadow dark:bg-slate-900 ${active ? 'ring-2 ring-teal-500/60 ring-offset-2 ring-offset-surface-container-low' : ''}`}>
      <button
        aria-expanded={expanded}
        className="flex min-h-[112px] w-full items-start justify-between gap-4 p-4 text-left transition-colors hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-teal-600 dark:hover:bg-slate-800/70 sm:p-5"
        onClick={toggleExpanded}
        type="button"
      >
        <span className="flex min-w-0 gap-3 sm:gap-4">
          <span className={`flex h-11 min-w-14 shrink-0 items-center justify-center rounded-lg px-2 font-headline text-base font-bold ${tone.soft} text-on-surface`}>{problem.code}</span>
          <span className="min-w-0">
            <span className="block text-base font-semibold text-on-surface">{problem.name}</span>
            <span className="mt-1 block text-sm text-on-surface-variant">{problem.category || 'บริบทสังคมและสุขภาพ'}</span>
            <span className="mt-3 flex flex-wrap items-center gap-2">
              <StatusBadge label={reviewLabel} tone={reviewTone} />
              <StatusBadge label={`ความรุนแรง ${severity}/5`} tone={severity >= 4 ? 'error' : severity === 3 ? 'warning' : 'neutral'} />
              <span className="text-xs font-semibold tabular-nums text-teal-700 dark:text-teal-300">ความมั่นใจ {formatPercent(confidence)}</span>
            </span>
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-2 pt-1 text-xs font-semibold text-on-surface-variant">
          <span className="hidden sm:inline">{expanded ? 'ซ่อนรายละเอียด' : 'ดูเหตุผล'}</span>
          <span aria-hidden="true" className={`material-symbols-outlined text-[20px] transition-transform ${expanded ? 'rotate-180' : ''}`}>expand_more</span>
        </span>
      </button>

      {expanded && (
        <div className="border-t border-slate-200 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-950/30 sm:p-5">
          <div className="grid gap-3 lg:grid-cols-3">
            <div className="rounded-lg bg-white p-3 dark:bg-slate-900">
              <div className="flex items-center gap-2 text-xs font-semibold text-on-surface-variant">
                <span aria-hidden="true" className="material-symbols-outlined text-[18px] text-sky-600 dark:text-sky-300">{isL2 ? 'auto_awesome' : 'rule'}</span>
                ระดับการตรวจพบ
              </div>
              <p className="mt-2 text-sm font-semibold text-on-surface">{problem.detection_level || 'L1'}</p>
              <p className="mt-1 text-xs text-on-surface-variant">{problem.context_valid ? 'บริบทสนับสนุนผลที่พบ' : 'ควรตรวจบริบทเพิ่มเติม'}</p>
            </div>
            <div className="rounded-lg bg-white p-3 dark:bg-slate-900 lg:col-span-2">
              <div className="text-xs font-semibold text-on-surface-variant">คำและวลีที่เชื่อมโยง</div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(problem.matched_keywords || []).length ? problem.matched_keywords.map((keyword) => (
                  <span key={`${problem.code}-${keyword}`} className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-on-surface dark:bg-slate-800">{keyword}</span>
                )) : <span className="text-xs text-on-surface-variant">พบจากความหมายโดยรวม ไม่ได้อาศัยคำตรงเพียงอย่างเดียว</span>}
              </div>
            </div>
          </div>
          <div className="mt-3 rounded-lg bg-white p-4 dark:bg-slate-900">
            <div className="text-xs font-semibold text-teal-700 dark:text-teal-300">เหตุผลที่ระบบเชื่อมโยง</div>
            <p className="mt-2 text-sm leading-relaxed text-on-surface">{problem.grounded_explanation?.summary || problem.reasoning || 'ไม่มีเหตุผลประกอบ'}</p>
            {problem.grounded_explanation?.evidence_quote && (
              <blockquote className="mt-3 border-l-2 border-teal-600 pl-3 text-sm leading-relaxed text-on-surface-variant">
                ข้อความจากเคส: “{problem.grounded_explanation.evidence_quote}”
              </blockquote>
            )}
            {(problem.evidence_aspects || []).length > 0 && (
              <div className="mt-4 border-t border-slate-200 pt-3 dark:border-slate-700">
                <div className="text-xs font-semibold text-on-surface-variant">มิติของเหตุการณ์ที่มีหลักฐานรองรับ</div>
                <div className="mt-2 divide-y divide-slate-200 dark:divide-slate-700">
                  {problem.evidence_aspects.map((aspect) => (
                    <div className="py-3 first:pt-0 last:pb-0" key={aspect.id}>
                      <div className="text-sm font-semibold text-on-surface">{aspect.label}</div>
                      <p className="mt-1 text-sm leading-relaxed text-on-surface-variant">{aspect.summary}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {problem.reasoning && problem.grounded_explanation?.summary && (
              <details className="clinical-details mt-3 text-xs text-on-surface-variant">
                <summary className="min-h-11 py-2 font-semibold text-teal-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 dark:text-teal-300">ดูเหตุผลจาก detector</summary>
                <p className="pb-2 leading-relaxed">{problem.reasoning}</p>
              </details>
            )}
            <p className="mt-3 text-sm leading-relaxed text-on-surface"><strong>ข้อควรพิจารณา:</strong> {problemInterpretation(problem)}</p>
          </div>
          <div className="mt-3 rounded-lg bg-white p-4 dark:bg-slate-900">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <div className="text-sm font-semibold text-on-surface">การตัดสินใจของผู้ทบทวน</div>
                <p className="mt-1 text-xs leading-relaxed text-on-surface-variant">เลือกสถานะจากข้อมูลเคสจริง ระบบจะนำไปใช้เมื่อส่งต่อให้ผู้เชี่ยวชาญ</p>
              </div>
              {active && <StatusBadge label="กำลังเชื่อมโยงหลักฐาน" tone="live" />}
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-3" role="group" aria-label={`สถานะการทบทวนประเด็น ${problem.code}`}>
              {FINDING_REVIEW_OPTIONS.map((option) => {
                const selected = reviewState === option.id;
                const selectedClass = option.tone === 'emerald'
                  ? 'border-emerald-600 bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200'
                  : option.tone === 'amber'
                    ? 'border-amber-500 bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-100'
                    : 'border-slate-500 bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100';
                return (
                  <button
                    aria-pressed={selected}
                    className={`flex min-h-11 items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 disabled:cursor-not-allowed disabled:opacity-50 ${selected ? selectedClass : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800'}`}
                    disabled={disabled}
                    key={option.id}
                    onClick={() => {
                      onFocus?.(problem.code);
                      onReviewChange?.(problem.code, option.id);
                    }}
                    type="button"
                  >
                    <span className="material-symbols-outlined text-[18px]" aria-hidden="true">{option.icon}</span>
                    {option.label}
                  </button>
                );
              })}
            </div>
            {reviewState === 'pending' && <p className="mt-2 text-xs font-medium text-amber-700 dark:text-amber-300">ยังไม่ได้ระบุสถานะรายการนี้</p>}
          </div>
        </div>
      )}
    </article>
  );
}

function CandidateFilterPanel({ displayResult }) {
  const trace = displayResult.candidate_trace || {};
  const candidates = trace.candidates || displayResult.candidates || [];
  const reasons = trace.filter_reasons || displayResult.filter_reasons || [];

  return (
    <section className="rounded-xl bg-surface-container-low p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-headline text-lg font-bold">รายละเอียดการคัดกรอง</h2>
          <p className="mt-1 text-sm text-on-surface-variant">รายการที่ระบบพิจารณา ผ่านเกณฑ์ หรือไม่นำไปใช้</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatusBadge label={`Candidates ${trace.candidate_count ?? candidates.length}`} />
          <StatusBadge label={`Accepted ${trace.final_accepted ?? 0}`} tone="live" />
          <StatusBadge label={`Filtered ${trace.filtered_out ?? 0}`} tone={(trace.filtered_out ?? 0) ? 'warning' : 'neutral'} />
        </div>
      </div>
      <div className="mt-5 grid gap-4 lg:grid-cols-4">
        <MetricTile label="L1 Candidates" value={trace.l1_candidates ?? 0} hint="keyword + context candidates" />
        <MetricTile label="L2 Candidates" value={trace.l2_candidates ?? 0} hint="semantic/implicit candidates" tone={(trace.l2_candidates ?? 0) ? 'bg-green-50 dark:bg-green-950/40' : 'bg-yellow-50 dark:bg-yellow-950/40'} />
        <MetricTile label="Final Accepted" value={trace.final_accepted ?? 0} hint="kept after gates" tone="bg-green-50 dark:bg-green-950/40" />
        <MetricTile label="Filtered Out" value={trace.filtered_out ?? 0} hint="low confidence/context/L2" tone={(trace.filtered_out ?? 0) ? 'bg-yellow-50 dark:bg-yellow-950/40' : 'bg-surface-container-lowest'} />
      </div>
      <div className="mt-5 overflow-x-auto rounded-lg bg-surface-container-lowest">
        <div className="min-w-[760px]">
        <div className="grid grid-cols-[90px_1fr_120px_120px_120px] gap-3 bg-surface-container-high px-4 py-3 text-xs font-semibold text-on-surface-variant">
          <span>Code</span>
          <span>Rule / Keywords</span>
          <span>Confidence</span>
          <span>L2 Need</span>
          <span>Decision</span>
        </div>
        {candidates.length ? candidates.map((candidate, index) => (
          <div key={`${candidate.code}-${index}`} className={`grid grid-cols-[90px_1fr_120px_120px_120px] gap-3 px-4 py-4 text-sm ${candidate.final_decision === 'filtered' ? 'bg-yellow-50/70 dark:bg-yellow-950/30' : ''}`}>
            <span className="font-headline font-extrabold text-teal-700">{candidate.code}</span>
            <div>
              <div className="font-semibold text-on-surface">{candidate.name}</div>
              <div className="mt-1 text-xs text-on-surface-variant">{candidate.context_rule}</div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(candidate.matched_keywords || []).slice(0, 5).map((keyword) => <span key={`${candidate.code}-${keyword}`} className="rounded bg-surface-container px-2 py-0.5 text-[10px] font-bold">{keyword}</span>)}
              </div>
            </div>
            <span className="font-bold">{formatPercent(candidate.confidence)}</span>
            <span>{candidate.needs_l2 ? 'needs L2' : 'not required'}</span>
            <span className={candidate.final_decision === 'filtered' ? 'font-bold text-yellow-700 dark:text-yellow-300' : 'font-bold text-teal-700'}>{candidate.final_decision}</span>
          </div>
        )) : <div className="px-4 py-5 text-sm text-on-surface-variant">ยังไม่มีรายละเอียดการคัดกรอง</div>}
        </div>
      </div>
      {reasons.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {reasons.map((reason) => (
            <span key={reason.reason} className="rounded bg-surface-container-high px-3 py-1 text-xs font-semibold text-on-surface-variant">{reason.reason}: {reason.count}</span>
          ))}
        </div>
      )}
    </section>
  );
}

function H2LEquationBreakdown({ displayResult }) {
  const rows = useMemo(
    () => [...(displayResult.h2l_scoring_trace || [])].sort((left, right) => {
      const leftScore = Number(left?.final_score ?? left?.breakdown?.S_final ?? Number.NEGATIVE_INFINITY);
      const rightScore = Number(right?.final_score ?? right?.breakdown?.S_final ?? Number.NEGATIVE_INFINITY);
      if (rightScore !== leftScore) return rightScore - leftScore;
      return Number(left?.rank ?? Number.MAX_SAFE_INTEGER) - Number(right?.rank ?? Number.MAX_SAFE_INTEGER);
    }),
    [displayResult.h2l_scoring_trace]
  );
  const docs = displayResult.retrieved_docs || [];
  const problems = displayResult.problems || [];
  const detectionInfo = displayResult.detection_info || {};
  const requestedStrategy = displayResult.requested_strategy || '';
  const isEnhancedStrategy = requestedStrategy.startsWith('h2l-');
  const polarityEffect = displayResult.polarity_effect || {};
  const polarityRows = polarityEffect.rows || [];
  const negationMarkers = polarityEffect.negation_markers || [];
  const polarityAdjustedRows = polarityRows.filter((row) => Number(row.gate ?? 1) < 1 || row.decision === 'filtered');
  const [selectedKey, setSelectedKey] = useState('');

  const rowKeys = rows.map((row) => `${row.rank}-${row.doc_id}`);
  const activeKey = rowKeys.includes(selectedKey) ? selectedKey : rowKeys[0];
  const selectedRow = rows.find((row) => `${row.rank}-${row.doc_id}` === activeKey) || rows[0];
  const selectedDoc = docs.find((doc) => doc.rank === selectedRow?.rank && doc.id === selectedRow?.doc_id);
  const breakdown = selectedRow?.breakdown || {};
  const sortedFactors = [...(Array.isArray(breakdown.factors) ? breakdown.factors : [])].sort((left, right) => {
    const rightWeight = Number(right?.['w·Φ'] ?? Number.NEGATIVE_INFINITY);
    const leftWeight = Number(left?.['w·Φ'] ?? Number.NEGATIVE_INFINITY);
    if (rightWeight !== leftWeight) return rightWeight - leftWeight;
    return Number(right?.['Φ_i'] ?? Number.NEGATIVE_INFINITY) - Number(left?.['Φ_i'] ?? Number.NEGATIVE_INFINITY);
  });
  const hasBreakdown = rows.length > 0 && Object.keys(breakdown).length > 0;
  const alphaEff = Number(breakdown['α_eff']);
  const meanSignal = Number(breakdown['mean(w·Φ)']);
  const boost = Number(breakdown.boost);
  const profilePrior = Number(breakdown['P(rel|profile)']);
  const caseSummaryItems = [
    {
      key: 'problem_scope',
      label: 'Problem Scope',
      value: breakdown.n_problems ?? detectionInfo.final_count ?? problems.length,
      meaning: 'จำนวน problem ที่เข้ามามีผลกับสมการของเคสนี้',
    },
    {
      key: 'alpha_base',
      label: 'alpha0',
      value: breakdown['α₀'],
      meaning: 'น้ำหนักตั้งต้นของ H2L ก่อนปรับตามเคส',
    },
    {
      key: 'alpha_adaptive',
      label: 'alpha adaptive',
      value: breakdown['α_adaptive'],
      meaning: 'น้ำหนัก H2L หลังดูจำนวนปัญหาและความเข้มของเคส',
    },
    {
      key: 'severity_entropy',
      label: 'Severity Entropy',
      value: breakdown.H_severity,
      meaning: 'ยิ่งสูงยิ่งแปลว่าความรุนแรงกระจายหลายปัญหา ไม่ได้กองอยู่ปัญหาเดียว',
    },
    {
      key: 'kl_penalty',
      label: 'KL Penalty',
      value: breakdown.KL_penalty,
      meaning: 'ตัวเบรกไม่ให้ prior เอียงไปทาง problem เดียวมากเกินไป',
    },
    {
      key: 'filtered',
      label: 'Filtered Candidates',
      value: detectionInfo.filtered_count ?? 0,
      meaning: 'จำนวน candidate ที่ถูก context / polarity / L2 ตัดออกจากเคสนี้',
    },
    {
      key: 'polarity_gate',
      label: 'Polarity Gate',
      value: polarityAdjustedRows.length,
      meaning: negationMarkers.length
        ? `ลดน้ำหนักหรือกรอง ${polarityAdjustedRows.length} candidate จาก ${polarityRows.length} แถว โดยอิง negation เช่น ${negationMarkers.slice(0, 3).join(', ')}`
        : 'ไม่พบ negation marker ชัดเจน จึงไม่เกิดการลดน้ำหนักจาก polarity gate',
    },
  ].filter((item) => item.value !== undefined && item.value !== null);
  const topDrivers = sortedFactors.slice(0, 3);
  const visualSteps = [
    { id: 'base', label: 'คะแนนตั้งต้น', value: breakdown.S_rerank, x: 70, tone: '#14b8a6' },
    { id: 'alpha', label: 'alpha ที่ใช้จริง', value: breakdown['α_eff'], x: 250, tone: '#0ea5e9' },
    { id: 'signal', label: 'สัญญาณปัญหา', value: breakdown['mean(w·Φ)'], x: 430, tone: '#8b5cf6' },
    { id: 'boost', label: 'ตัวคูณ', value: breakdown.boost, x: 610, tone: '#10b981' },
    { id: 'final', label: 'คะแนนสุดท้าย', value: breakdown.S_final, x: 790, tone: '#ef4444' },
  ].filter((step) => step.value !== undefined && step.value !== null);
  const contributionBars = [
    {
      id: 'alpha',
      label: 'alpha / น้ำหนัก H2L',
      value: Number.isFinite(alphaEff) ? Math.min(1, Math.max(0, alphaEff / 3)) : null,
      raw: breakdown['α_eff'],
      purpose: 'กำหนดว่า H2L จะเข้าไปปรับคะแนนตั้งต้นมากแค่ไหน',
      low: 'คะแนนค้นหาเดิมมีอิทธิพลมากกว่า',
      high: 'สัญญาณปัญหาใน H2L มีแรงดันคะแนนมากขึ้น',
      effect: alphaEff >= 1.5 ? 'ตอนนี้ H2L มีบทบาทสูงในการปรับคะแนน' : 'ตอนนี้ยังให้คะแนนตั้งต้นนำมากกว่า',
    },
    {
      id: 'signal',
      label: 'problem signal / สัญญาณปัญหา',
      value: Number.isFinite(meanSignal) ? Math.min(1, Math.max(0, meanSignal)) : null,
      raw: breakdown['mean(w·Φ)'],
      purpose: 'วัดว่าเอกสารนี้ตอบกับปัญหาที่ระบบตรวจพบได้ชัดแค่ไหน',
      low: 'เอกสารยังเชื่อมกับปัญหานี้ไม่ชัด',
      high: 'เอกสารสนับสนุนปัญหาที่พบในเคสได้ชัดขึ้น',
      effect: meanSignal >= 0.35 ? 'สัญญาณนี้ช่วยเพิ่มคะแนนเอกสาร' : 'สัญญาณนี้เพิ่มคะแนนไม่มาก',
    },
    {
      id: 'boost',
      label: 'boost / ตัวคูณคะแนน',
      value: Number.isFinite(boost) ? Math.min(1, Math.max(0, (boost - 1) / 2)) : null,
      raw: breakdown.boost,
      purpose: 'แปลง alpha และสัญญาณปัญหาให้เป็นตัวคูณคะแนน',
      low: 'ต่ำกว่า 1 คือกดคะแนนลง',
      high: 'มากกว่า 1 คือยกคะแนนขึ้น',
      effect: boost > 1.05 ? 'คะแนนหลังปรับสูงกว่าคะแนนตั้งต้น' : boost < 0.95 ? 'คะแนนหลังปรับต่ำกว่าคะแนนตั้งต้น' : 'คะแนนแทบไม่เปลี่ยนจากคะแนนตั้งต้น',
    },
    {
      id: 'profile',
      label: 'profile prior / ความเข้ากับโปรไฟล์',
      value: Number.isFinite(profilePrior) ? Math.min(1, Math.max(0, profilePrior)) : null,
      raw: breakdown['P(rel|profile)'],
      purpose: 'ตรวจว่าเอกสารเข้ากับภาพรวมของเคสและกลุ่มปัญหาที่พบหรือไม่',
      low: 'เอกสารอาจไม่ตรงบริบทเคส จึงถ่วงคะแนนลง',
      high: 'เอกสารเข้ากับโปรไฟล์เคส จึงช่วยรักษาหรือยกคะแนน',
      effect: profilePrior >= 0.65 ? 'โปรไฟล์ช่วยยืนยันความเกี่ยวข้องของเอกสาร' : 'โปรไฟล์ยังเป็นตัวถ่วงความมั่นใจ',
    },
  ].filter((item) => item.value !== null);
  const summaryTerms = [
    { key: 'S_rerank', label: 'S rerank', meaning: 'คะแนนตั้งต้นจากตัวค้นหา/ตัวจัดอันดับเอกสาร' },
    { key: 'α₀', label: 'alpha เริ่มต้น', meaning: 'น้ำหนักพื้นฐานของ H2L' },
    { key: 'α_adaptive', label: 'alpha ตามเคส', meaning: 'ปรับตามจำนวนปัญหาและความมั่นใจของเคสนี้' },
    { key: 'KL_penalty', label: 'KL penalty', meaning: 'ตัวเบรกเมื่อ prior กระจุกที่ปัญหาใดปัญหาหนึ่งมากเกินไป' },
    { key: 'α_eff', label: 'alpha ที่ใช้จริง', meaning: 'น้ำหนักสุดท้ายหลังผ่าน entropy และ KL penalty' },
    { key: 'mean(w·Φ)', label: 'สัญญาณปัญหาเฉลี่ย', meaning: 'ค่าเฉลี่ยของสัญญาณแต่ละปัญหาที่สัมพันธ์กับเอกสารนี้' },
    { key: 'boost', label: 'ตัวคูณเพิ่มคะแนน', meaning: 'ค่าที่เอาไปคูณกับคะแนนตั้งต้น' },
    { key: 'P(rel|profile)', label: 'โอกาสเข้ากับโปรไฟล์', meaning: 'prior รวมจากปัญหาที่พบในเคสนี้' },
    { key: 'S_final', label: 'คะแนนสุดท้าย', meaning: 'คะแนนหลัง H2L ปรับแล้ว' },
  ].filter((item) => breakdown[item.key] !== undefined && breakdown[item.key] !== null);

  if (!hasBreakdown) {
    return (
      <div className="mt-6 rounded-xl bg-surface-container-lowest p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="font-headline font-bold">H2L Document Score Breakdown</h3>
            <p className="mt-1 text-sm text-on-surface-variant">
              {isEnhancedStrategy
                ? 'ยังไม่มี breakdown จริงจาก runtime สำหรับเคสนี้'
                : 'ไม่มี H2L breakdown เพราะ strategy นี้ไม่ได้ใช้ H2L scoring'}
            </p>
          </div>
          <StatusBadge label={isEnhancedStrategy ? 'waiting for real h2l trace' : 'baseline: no h2l scoring'} tone="warning" />
        </div>
        <p className="mt-3 text-sm leading-relaxed text-on-surface-variant">
          {isEnhancedStrategy
            ? 'ระบบจะแสดงสมการส่วนนี้เมื่อ API ส่ง `h2l_scoring_trace` พร้อม `h2l_breakdown` กลับมาเท่านั้น เพื่อหลีกเลี่ยงการเติมข้อมูลจำลองเอง'
            : 'baseline จะรายงานเฉพาะ retrieval score เดิมของเอกสาร และจะไม่สร้าง H2L breakdown เพิ่ม เพื่อไม่ให้ผู้ใช้เข้าใจผิดว่า strategy นี้ผ่านสมการ H2L แล้ว'}
        </p>
      </div>
    );
  }

  return (
    <div className="mt-6 rounded-xl bg-surface-container-lowest p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-headline font-bold">H2L Document Score Breakdown</h3>
          <p className="mt-1 text-sm leading-relaxed text-on-surface-variant">
            สมการนี้คำนวณต่อ 1 เอกสาร โดยใช้คะแนนเอกสารจริงร่วมกับสัญญาณจากเคสที่กำลังวิเคราะห์ เช่น problem prior, severity, negation และ profile prior
          </p>
        </div>
        <StatusBadge label={breakdown.method || 'h2l trace'} tone="live" />
      </div>

      <div className="mt-4 rounded-lg bg-surface-container-low p-3 text-xs leading-relaxed text-on-surface-variant">
        อ่านแบบง่าย: ส่วนนี้ไม่ใช่ relevance ของเอกสารอย่างเดียว แต่เป็น <strong className="text-on-surface">doc-level final score</strong> ที่เกิดจาก 2 ฝั่งรวมกัน คือ <strong className="text-on-surface">คะแนนเอกสารตั้งต้น</strong> และ <strong className="text-on-surface">สัญญาณจากเคสที่วิเคราะห์จริง</strong>
      </div>

      <div className="mt-4 rounded-xl bg-surface-container-low p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Case H2L Summary</div>
            <p className="mt-1 text-sm leading-relaxed text-on-surface-variant">
              บล็อกนี้สรุปตัวแปรระดับเคสที่ไปมีผลกับเอกสารทุกชิ้น ก่อนจะค่อยแตกลงมาดูรายละเอียดรายเอกสารด้านล่าง
            </p>
          </div>
          <StatusBadge label={`${problems.length} problems`} tone={problems.length ? 'live' : 'neutral'} />
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {caseSummaryItems.map((item) => (
            <div className="rounded-lg bg-surface-container-lowest p-3" key={item.key}>
              <div className="flex items-start justify-between gap-3">
                <span className="text-xs font-bold text-on-surface-variant">{item.label}</span>
                <span className="font-headline text-lg font-extrabold text-teal-700 dark:text-teal-300">
                  {typeof item.value === 'number' ? formatNumber(item.value, item.key === 'problem_scope' || item.key === 'filtered' || item.key === 'polarity_gate' ? 0 : 4) : item.value}
                </span>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">{item.meaning}</p>
            </div>
          ))}
        </div>
        <div className="mt-4 rounded-lg bg-surface-container-lowest p-3">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Detected Problems In This Case</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {problems.length
              ? problems.slice(0, 8).map((problem) => (
                <span className="rounded bg-teal-50 px-2 py-1 text-xs font-bold text-teal-800 dark:bg-teal-950/40 dark:text-teal-100" key={problem.code}>
                  {problem.code} · {problem.name}
                </span>
              ))
              : <span className="text-xs text-on-surface-variant">ยังไม่มี detected problems จาก runtime</span>}
          </div>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {rows.map((row, index) => {
          const key = `${row.rank}-${row.doc_id}`;
          return (
            <button
              className={`rounded-lg px-3 py-2 text-left text-xs font-bold ${key === activeKey ? 'bg-teal-600 text-white' : 'bg-surface-container-low text-on-surface'}`}
              key={key}
              onClick={() => setSelectedKey(key)}
              type="button"
            >
              <div>#{index + 1} final {formatNumber(row.final_score ?? row.breakdown?.S_final, 4)}</div>
              <div className={`mt-1 text-[10px] ${key === activeKey ? 'text-white/80' : 'text-on-surface-variant'}`}>runtime rank {row.rank}</div>
            </button>
          );
        })}
      </div>

      <div className="mt-4 rounded-lg bg-surface-container-low p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-widest text-teal-700">Document Score Breakdown</div>
            <div className="mt-1 font-semibold text-on-surface">{selectedDoc?.title || `Doc ${selectedRow?.doc_id}`}</div>
            <p className="mt-1 text-xs text-on-surface-variant">{selectedDoc?.source || 'source not provided by runtime'}</p>
          </div>
          <div className="text-right text-xs text-on-surface-variant">
            <div>base <strong className="text-on-surface">{formatNumber(selectedRow?.base_score, 4)}</strong></div>
            <div>final <strong className="text-on-surface">{formatNumber(selectedRow?.final_score, 4)}</strong></div>
          </div>
        </div>
        <div className="mt-4 rounded bg-surface-container-lowest p-3 text-sm leading-relaxed text-on-surface">
          คะแนนสุดท้าย = คะแนนตั้งต้น × ตัวคูณจากปัญหาที่พบ × โอกาสที่เอกสารเข้ากับโปรไฟล์เคส
        </div>
        <div className="mt-2 rounded bg-surface-container-lowest p-3 text-xs leading-relaxed text-on-surface-variant">
          <span className="font-bold text-on-surface">สูตรจริง:</span> S_final = S_rerank × exp(α_eff × mean(w·Φ)) × P(rel|profile)
        </div>
        {!!topDrivers.length && (
          <div className="mt-3 rounded bg-surface-container-lowest p-3 text-xs leading-relaxed text-on-surface-variant">
            <span className="font-bold text-on-surface">ตัวดันคะแนนหลักของเอกสารนี้:</span>{' '}
            {topDrivers.map((factor) => `${factor.code} (${formatNumber(factor['w·Φ'], 4)})`).join(' · ')}
          </div>
        )}
      </div>

      <div className="mt-4 overflow-hidden rounded-xl bg-surface-container-low p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Realtime score path</div>
            <p className="mt-1 text-sm text-on-surface-variant">เส้นนี้ใช้ค่าจริงของเอกสารที่เลือก แสดงลำดับการปรับคะแนนจากซ้ายไปขวา</p>
          </div>
          <StatusBadge label={selectedRow?.semantic_used ? 'semantic used' : 'keyword/fallback'} tone={selectedRow?.semantic_used ? 'live' : 'neutral'} />
        </div>
        <svg className="h-[230px] w-full select-none" viewBox="0 0 880 230">
          <defs>
            <marker id="h2l-score-arrow" markerHeight="7" markerWidth="7" orient="auto" refX="6" refY="3.5">
              <polygon fill="#14b8a6" points="0 0, 7 3.5, 0 7" />
            </marker>
          </defs>
          <path className="h2l-equation-edge" d="M 70 112 C 160 112, 160 112, 250 112 S 340 112, 430 112 S 520 112, 610 112 S 700 112, 790 112" fill="none" markerEnd="url(#h2l-score-arrow)" stroke="#14b8a6" strokeOpacity="0.45" strokeWidth="3" />
          <circle className="h2l-score-packet" fill="#14b8a6" r="6">
            <animateMotion dur="2.8s" path="M 70 112 C 160 112, 160 112, 250 112 S 340 112, 430 112 S 520 112, 610 112 S 700 112, 790 112" repeatCount="indefinite" />
          </circle>
          {visualSteps.map((step) => (
            <g key={step.id}>
              <rect fill="#f8fafc" height="86" rx="8" stroke={step.tone} strokeOpacity="0.55" strokeWidth="1.6" width="142" x={step.x - 71} y="69" />
              <rect fill={step.tone} height="5" opacity="0.9" rx="2.5" width="92" x={step.x - 46} y="142" />
              <text fill="#0f172a" fontSize="12" fontWeight="800" textAnchor="middle" x={step.x} y="94">{step.label}</text>
              <text fill={step.tone} fontSize="19" fontWeight="900" textAnchor="middle" x={step.x} y="122">{formatNumber(step.value, 4)}</text>
            </g>
          ))}
          <text fill="#64748b" fontSize="12" fontWeight="700" x="245" y="40">exp(alpha × signal)</text>
          <text fill="#64748b" fontSize="12" fontWeight="700" x="598" y="40">× profile prior</text>
        </svg>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {contributionBars.map((item) => (
            <div key={item.id} className="rounded-lg bg-surface-container-lowest p-3">
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="font-bold text-on-surface">{item.label}</span>
                <span className="font-bold text-teal-700 dark:text-teal-300">{formatNumber(item.raw, 4)}</span>
              </div>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-container-high">
                <div className="h-full rounded-full bg-teal-500 transition-[width]" style={{ width: `${Math.round(item.value * 100)}%` }} />
              </div>
              <p className="mt-3 text-xs leading-relaxed text-on-surface">{item.purpose}</p>
              <div className="mt-3 space-y-2 text-[11px] leading-relaxed text-on-surface-variant">
                <p><span className="font-bold text-on-surface">ค่าน้อย:</span> {item.low}</p>
                <p><span className="font-bold text-on-surface">ค่ามาก:</span> {item.high}</p>
                <p className="rounded-md bg-surface-container-low px-2 py-1.5"><span className="font-bold text-on-surface">ผลตอนนี้:</span> {item.effect}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {summaryTerms.map((term) => (
          <div key={term.key} className="rounded-lg bg-surface-container-low p-3">
            <div className="flex items-start justify-between gap-3">
              <span className="text-xs font-bold text-on-surface-variant">{term.label}</span>
              <span className="font-headline text-lg font-extrabold text-teal-700">{formatNumber(breakdown[term.key], 4)}</span>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">{term.meaning}</p>
          </div>
        ))}
      </div>

      {sortedFactors.length > 0 && (
        <div className="mt-5 overflow-x-auto rounded-lg bg-surface-container-low">
          <div className="min-w-[900px]">
            <div className="grid grid-cols-[90px_90px_90px_90px_90px_90px_90px_90px_1fr] gap-2 bg-surface-container-high px-3 py-3 text-[10px] font-bold uppercase text-on-surface-variant">
              <span>Code</span>
              <span>C(p|q)</span>
              <span>P(d|p)</span>
              <span>P(p)</span>
              <span>IDF</span>
              <span>G neg</span>
              <span>Φ</span>
              <span>w·Φ</span>
              <span>วิธีจับคู่</span>
            </div>
            {sortedFactors.map((factor) => (
              <div key={`${activeKey}-${factor.code}`} className="grid grid-cols-[90px_90px_90px_90px_90px_90px_90px_90px_1fr] gap-2 border-t border-outline-variant/15 px-3 py-3 text-xs text-on-surface">
                <span className="font-headline font-extrabold text-teal-700">{factor.code}</span>
                <span>{formatNumber(factor['C(p|q)'], 4)}</span>
                <span>{formatNumber(factor['P(d|p)'], 4)}</span>
                <span>{formatNumber(factor['P(p)'], 4)}</span>
                <span>{formatNumber(factor.IDF, 4)}</span>
                <span>{formatNumber(factor.G_neg, 4)}</span>
                <span>{formatNumber(factor['Φ_i'], 4)}</span>
                <span>{formatNumber(factor['w·Φ'], 4)}</span>
                <span className="text-on-surface-variant">{factor.match_method || 'runtime did not provide method'}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-4 grid gap-3 text-xs leading-relaxed text-on-surface-variant md:grid-cols-2">
        <p><strong className="text-on-surface">alpha</strong> คือระดับที่ระบบให้ความสำคัญกับปัญหาที่ตรวจพบในเคสนี้</p>
        <p><strong className="text-on-surface">KL penalty</strong> คือเบรกกันคะแนนพุ่ง เมื่อ prior เอียงไปที่ปัญหาเดียวมากเกินไป</p>
        <p><strong className="text-on-surface">Φ</strong> คือสัญญาณรวมของปัญหาหนึ่ง เช่น ความมั่นใจ ความใกล้กับเอกสาร prior IDF และ negation gate</p>
        <p><strong className="text-on-surface">boost</strong> คือตัวคูณที่ H2L ใช้เพิ่มหรือลดคะแนนเอกสารจากคะแนนตั้งต้น</p>
      </div>
    </div>
  );
}

function EvidenceSection({ activeFindingCode, displayResult, onClearFinding }) {
  const docs = displayResult.retrieved_docs || [];
  const trace = displayResult.retrieval_trace || {};
  const docScaling = displayResult.doc_scaling || {};
  const selectedTopK = displayResult.top_k || docScaling.selected_top_k || trace.docs_requested || docs.length;
  const hasErrors = (trace.errors || []).length > 0;
  const topDocs = docs.slice(0, 3);
  const extraDocs = docs.slice(3);
  const getEvidenceCodes = (doc) => (doc.matched_problem_evidence || [])
    .map((item) => (typeof item === 'string' ? item : item?.code))
    .filter(Boolean);
  const linkedDocumentCount = activeFindingCode
    ? docs.filter((doc) => getEvidenceCodes(doc).includes(activeFindingCode)).length
    : 0;

  const renderDocCard = (doc) => {
    const evidenceCodes = getEvidenceCodes(doc);
    const linkedToActiveFinding = activeFindingCode && evidenceCodes.includes(activeFindingCode);
    return (
    <details key={`${doc.rank}-${doc.id}`} className={`clinical-details group rounded-lg bg-surface-container-lowest transition-shadow ${linkedToActiveFinding ? 'ring-2 ring-teal-500 ring-offset-2 ring-offset-surface-container-low' : ''}`}>
      <summary className="flex min-h-[112px] items-start justify-between gap-3 p-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-teal-600">
        <span className="flex min-w-0 gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-teal-50 text-sm font-bold text-teal-700 dark:bg-teal-950/50 dark:text-teal-200">{doc.rank}</span>
          <span className="min-w-0">
            <span className="block line-clamp-2 font-semibold text-on-surface">{doc.title}</span>
            <span className="mt-1 block truncate text-xs text-on-surface-variant">{doc.source}</span>
            <span className="mt-2 block line-clamp-2 text-sm leading-relaxed text-on-surface-variant">{doc.snippet}</span>
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <StatusBadge label={`คะแนน ${formatNumber(doc.h2l_final_score ?? doc.score, 2)}`} tone="live" />
          <span aria-hidden="true" className="details-chevron material-symbols-outlined text-[20px] text-on-surface-variant transition-transform">expand_more</span>
        </span>
      </summary>
      <div className="border-t border-slate-200 p-4 dark:border-slate-800">
        <p className="text-sm leading-relaxed text-on-surface">{doc.snippet}</p>
        <div className="mt-4 grid grid-cols-3 gap-2 text-xs tabular-nums text-on-surface-variant">
          <span className="rounded-md bg-slate-50 p-2 dark:bg-slate-800">Base <strong className="block text-on-surface">{formatNumber(doc.base_score, 3)}</strong></span>
          <span className="rounded-md bg-slate-50 p-2 dark:bg-slate-800">Rerank <strong className="block text-on-surface">{formatNumber(doc.rerank_score, 3)}</strong></span>
          <span className="rounded-md bg-slate-50 p-2 dark:bg-slate-800">H2L <strong className="block text-on-surface">{formatNumber(doc.h2l_final_score, 3)}</strong></span>
        </div>
        <div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs leading-relaxed text-on-surface dark:bg-slate-800/70">
          {doc.reason}
          {(doc.matched_problem_evidence || []).length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {evidenceCodes.map((code) => <span key={`${doc.id}-${code}`} className={`rounded-md px-2 py-1 font-semibold ${code === activeFindingCode ? 'bg-teal-600 text-white' : 'bg-teal-50 text-teal-700 dark:bg-teal-950/60 dark:text-teal-200'}`}>{code}</span>)}
            </div>
          )}
        </div>
      </div>
    </details>
    );
  };

  return (
    <section className="rounded-xl bg-surface-container-low p-6">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-headline text-lg font-bold">หลักฐานและแนวทางที่เกี่ยวข้อง</h2>
          <p className="mt-1 text-sm text-on-surface-variant">เปิดแต่ละรายการเพื่อดูข้อความ แหล่งที่มา และเหตุผลเชื่อมโยง</p>
        </div>
        <div className="flex gap-2">
          <StatusBadge label={`Top ${selectedTopK}`} tone={docs.length ? 'live' : 'neutral'} />
          <StatusBadge label={`Returned ${docs.length}`} tone={docs.length ? 'live' : 'neutral'} />
          <StatusBadge label={trace.strategy || displayResult.requested_strategy || 'strategy'} />
        </div>
      </div>
      {activeFindingCode && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-teal-50 p-3 text-sm text-teal-950 dark:bg-teal-950/40 dark:text-teal-100" role="status">
          <span className="flex min-w-0 items-center gap-2">
            <span className="material-symbols-outlined text-[19px]" aria-hidden="true">link</span>
            <span>กำลังไฮไลต์หลักฐานของ <strong>{activeFindingCode}</strong> · เชื่อมโยง {linkedDocumentCount} รายการ</span>
          </span>
          <button className="min-h-11 rounded-lg px-3 py-2 font-semibold text-teal-800 transition-colors hover:bg-teal-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 dark:text-teal-100 dark:hover:bg-teal-900/60" onClick={onClearFinding} type="button">ล้างการไฮไลต์</button>
        </div>
      )}
      {hasErrors && (
        <div className="mb-4 rounded-lg bg-error-container p-3 text-sm text-on-error-container">
          Retrieval error: {(trace.errors || []).join('; ')}
        </div>
      )}
      <div className="grid gap-3 xl:grid-cols-3">
        {!docs.length && !hasErrors && (
          <div className="rounded-xl bg-surface-container-lowest p-4 text-sm text-on-surface-variant">
            ยังไม่มี retrieved documents จาก runtime สำหรับเคสนี้
          </div>
        )}
        {topDocs.map(renderDocCard)}
      </div>
      {extraDocs.length > 0 && (
        <details className="mt-4 rounded-xl bg-surface-container-lowest p-4">
          <summary className="flex min-h-11 items-center justify-between gap-3 text-sm font-semibold text-teal-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 dark:text-teal-300">
            <span>แสดงหลักฐานเพิ่มเติมอีก {extraDocs.length} รายการ</span>
            <span aria-hidden="true" className="details-chevron material-symbols-outlined transition-transform">expand_more</span>
          </summary>
          <div className="mt-4 grid gap-3 xl:grid-cols-3">
            {extraDocs.map(renderDocCard)}
          </div>
        </details>
      )}
      <details className="clinical-details mt-4 rounded-lg bg-surface-container-lowest p-4">
        <summary className="flex min-h-11 items-center justify-between gap-3 text-sm font-semibold text-on-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600">
          <span>รายละเอียดคะแนน H2L ของเอกสาร</span>
          <span aria-hidden="true" className="details-chevron material-symbols-outlined transition-transform">expand_more</span>
        </summary>
        <H2LEquationBreakdown displayResult={displayResult} />
      </details>
    </section>
  );
}

function AnalysisTab({ displayResult, findingReviewStates, onFindingReviewChange, reviewDisabled }) {
  const problems = displayResult.problems || [];
  const metrics = displayResult.metrics || {};
  const maxSeverity = Number(metrics.max_severity ?? Math.max(0, ...problems.map((problem) => Number(problem.severity || 0))));
  const highSeverityCount = Number(metrics.high_severity_count ?? problems.filter((problem) => Number(problem.severity || 0) >= 4).length);
  const reviewCount = Number(displayResult.detection_info?.ambiguity_summary?.review_count ?? problems.filter((problem) => problem.review_status !== 'confirmed').length);
  const priorityRank = { mandatory: 0, critical: 0, high: 1, medium: 2, moderate: 2, low: 3 };
  const tools = [...(displayResult.tools || [])].sort((left, right) => {
    const leftRank = priorityRank[String(left.priority || '').toLowerCase()] ?? 4;
    const rightRank = priorityRank[String(right.priority || '').toLowerCase()] ?? 4;
    return leftRank - rightRank || String(left.name || '').localeCompare(String(right.name || ''), 'th');
  });
  const topTools = tools.slice(0, 3);
  const extraTools = tools.slice(3);
  const [focusedFindingCode, setFocusedFindingCode] = useState('');
  const activeFindingCode = problems.some((problem) => problem.code === focusedFindingCode) ? focusedFindingCode : '';
  const reviewedFindingCount = problems.filter((problem) => Boolean(findingReviewStates[problem.code])).length;
  const pendingFindingCount = Math.max(0, problems.length - reviewedFindingCount);
  const safetyLabel = !problems.length
    ? 'ยังสรุปความปลอดภัยไม่ได้'
    : maxSeverity >= 4
      ? 'ต้องทบทวนโดยเร่งด่วน'
      : maxSeverity === 3
        ? 'ควรทบทวนเพิ่มเติม'
        : 'ติดตามตามบริบทของเคส';
  const safetyTone = !problems.length ? 'text-slate-100' : maxSeverity >= 4 ? 'text-red-300' : maxSeverity === 3 ? 'text-amber-300' : 'text-emerald-300';

  const renderTool = (tool) => {
    const priority = tool.priority || tool.urgency;
    const tone = ['mandatory', 'critical'].includes(String(priority || '').toLowerCase()) ? 'error' : String(priority || '').toLowerCase() === 'high' ? 'warning' : 'neutral';
    return (
      <div className="rounded-lg bg-white p-3 dark:bg-slate-900" key={tool.name}>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="font-semibold text-on-surface">{tool.name}</div>
          {priority && <StatusBadge label={priority} tone={tone} />}
        </div>
        <div className="mt-1 text-sm leading-relaxed text-on-surface-variant">{tool.reason}</div>
      </div>
    );
  };

  return (
    <div className="page-enter space-y-5">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(300px,0.65fr)]">
        <section className="rounded-lg bg-surface-container-low p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-xs font-semibold text-teal-700 dark:text-teal-300">Assessment summary</div>
              <h2 className="mt-1 font-headline text-xl font-bold text-on-surface">สรุปการประเมินเคส</h2>
            </div>
            <StatusBadge label="ผลจาก runtime ปัจจุบัน" tone="live" />
          </div>
          <p className="mt-4 max-w-4xl text-sm leading-relaxed text-on-surface">{resultInterpretation(displayResult)}</p>
          <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricTile label="ประเด็นที่พบ" value={metrics.accepted_count ?? problems.length} hint="รายการที่ผ่านเกณฑ์ระบบ" tone="bg-white dark:bg-slate-900" />
            <MetricTile label="ต้องทบทวน" value={reviewCount} hint="รายการที่ควรอ่านร่วมกับหลักฐาน" tone={reviewCount ? 'bg-amber-50 dark:bg-amber-950/40' : 'bg-white dark:bg-slate-900'} />
            <MetricTile label="หลักฐาน" value={metrics.retrieved_docs_count ?? displayResult.retrieved_docs_count ?? 0} hint="เอกสารและแนวทางที่ค้นคืน" tone="bg-white dark:bg-slate-900" />
            <MetricTile label="ระดับสูงสุด" value={maxSeverity || 'N/A'} hint={`${highSeverityCount} รายการระดับสูง`} tone={severityStyle(maxSeverity || 1).soft} />
          </div>
        </section>

        <aside className="rounded-lg bg-[#0d2734] p-5 text-white sm:p-6">
          <div className="flex items-center justify-between gap-3">
            <div className="text-sm font-semibold text-slate-300">ความปลอดภัยและความเร่งด่วน</div>
            <span aria-hidden="true" className="material-symbols-outlined text-teal-300">health_and_safety</span>
          </div>
          <div className={`mt-5 font-headline text-2xl font-bold ${safetyTone}`}>{safetyLabel}</div>
          <p className="mt-3 text-sm leading-relaxed text-slate-300">{problems.length ? 'ระดับนี้อ้างอิงจาก severity สูงสุดของประเด็นที่ระบบพบ และต้องอ่านร่วมกับบริบทจริงโดยผู้ปฏิบัติงาน' : 'ระบบไม่พบสัญญาณจากข้อความที่ให้ แต่ไม่เท่ากับยืนยันว่าปลอดภัย ผู้ปฏิบัติงานยังต้องประเมินความเสี่ยงจากข้อมูลจริง'}</p>
          <div className="mt-5 grid grid-cols-2 gap-3 border-t border-white/10 pt-4 text-sm">
            <div><span className="block text-xs text-slate-400">High risk</span><strong className="mt-1 block text-xl tabular-nums">{highSeverityCount}</strong></div>
            <div><span className="block text-xs text-slate-400">Review load</span><strong className="mt-1 block text-xl tabular-nums">{reviewCount}</strong></div>
          </div>
        </aside>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(300px,0.65fr)]">
        <section className="rounded-lg bg-surface-container-low p-5 sm:p-6">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-headline text-lg font-bold">ประเด็นปัญหาและความต้องการ</h2>
              <p className="mt-1 text-sm text-on-surface-variant">เปิดแต่ละรายการเพื่อดูเหตุผล ระบุผลการทบทวน และเชื่อมโยงหลักฐาน</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <StatusBadge label={`${problems.length} รายการ`} tone={problems.length ? 'live' : 'neutral'} />
              <StatusBadge label={pendingFindingCount ? `ค้างทบทวน ${pendingFindingCount}` : 'ทบทวนครบแล้ว'} tone={pendingFindingCount ? 'warning' : 'live'} />
            </div>
          </div>
          <div className="space-y-3">
            {problems.length ? problems.map((problem) => (
              <ProblemCard
                active={activeFindingCode === problem.code}
                disabled={reviewDisabled}
                key={problem.code}
                onFocus={setFocusedFindingCode}
                onReviewChange={onFindingReviewChange}
                problem={problem}
                reviewState={findingReviewStates[problem.code] || 'pending'}
              />
            )) : (
              <div className="rounded-lg bg-white p-5 text-sm text-on-surface-variant dark:bg-slate-900">ระบบไม่พบประเด็นที่ผ่านเกณฑ์ในเคสนี้ ควรพิจารณาข้อมูลต้นฉบับและบริบทเพิ่มเติม</div>
            )}
          </div>
        </section>

        <aside className="space-y-4">
          <section className="rounded-lg bg-surface-container-low p-5">
            <div className="flex items-center gap-2">
              <span aria-hidden="true" className="material-symbols-outlined text-[20px] text-teal-700 dark:text-teal-300">assignment</span>
              <h2 className="font-headline font-bold">เครื่องมือประเมินที่แนะนำ</h2>
            </div>
            <div className="mt-4 space-y-3">
              {topTools.length ? topTools.map(renderTool) : <div className="text-sm text-on-surface-variant">ยังไม่มีเครื่องมือที่ระบบแนะนำ</div>}
            </div>
            {extraTools.length > 0 && (
              <details className="clinical-details mt-3">
                <summary className="flex min-h-11 items-center justify-between gap-3 rounded-lg px-2 text-sm font-semibold text-teal-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 dark:text-teal-300">
                  <span>ดูเครื่องมือเพิ่มเติม {extraTools.length} รายการ</span>
                  <span aria-hidden="true" className="details-chevron material-symbols-outlined transition-transform">expand_more</span>
                </summary>
                <div className="mt-2 space-y-3">{extraTools.map(renderTool)}</div>
              </details>
            )}
          </section>

          <section className="rounded-lg bg-surface-container-low p-5">
            <div className="flex items-center gap-2">
              <span aria-hidden="true" className="material-symbols-outlined text-[20px] text-slate-500">tune</span>
              <h2 className="font-headline font-bold">วิธีที่ใช้วิเคราะห์</h2>
            </div>
            <div className="mt-3 rounded-lg bg-white p-3 dark:bg-slate-900">
              <div className="font-semibold text-on-surface">{displayResult.strategy_profile?.label || displayResult.effective_strategy || displayResult.requested_strategy}</div>
              <p className="mt-1 text-xs leading-relaxed text-on-surface-variant">{displayResult.strategy_profile?.execution_note || displayResult.strategy_note}</p>
              <dl className="mt-3 space-y-2 border-t border-slate-200 pt-3 text-xs dark:border-slate-700">
                <div className="flex items-start justify-between gap-3"><dt className="text-on-surface-variant">L2 model</dt><dd className="break-all text-right font-semibold text-on-surface">{displayResult.model_provenance?.effective_l2_model || 'ไม่ได้เรียกในเคสนี้'}</dd></div>
                <div className="flex items-start justify-between gap-3"><dt className="text-on-surface-variant">Embedding</dt><dd className="break-all text-right font-semibold text-on-surface">{displayResult.model_provenance?.embedding_model || 'N/A'}</dd></div>
                <div className="flex items-start justify-between gap-3"><dt className="text-on-surface-variant">Reranker</dt><dd className="break-all text-right font-semibold text-on-surface">{displayResult.model_provenance?.rerank_model || 'N/A'}</dd></div>
              </dl>
            </div>
          </section>
        </aside>
      </div>

      <EvidenceSection activeFindingCode={activeFindingCode} displayResult={displayResult} onClearFinding={() => setFocusedFindingCode('')} />

      <details className="clinical-details rounded-lg bg-surface-container-low p-4 sm:p-5">
        <summary className="flex min-h-11 items-center justify-between gap-3 font-semibold text-on-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600">
          <span className="flex items-center gap-2"><span aria-hidden="true" className="material-symbols-outlined text-[20px] text-slate-500">data_object</span>รายละเอียดทางเทคนิค</span>
          <span aria-hidden="true" className="details-chevron material-symbols-outlined transition-transform">expand_more</span>
        </summary>
        <div className="mt-4"><CandidateFilterPanel displayResult={displayResult} /></div>
      </details>
    </div>
  );
}

function KeywordsTab({ displayResult }) {
  const analysis = displayResult.keyword_analysis || {};
  const rows = (analysis.rows || []).map((row) => ({ ...row, keywords: row.keywords || row.matched_keywords || [] }));
  const profile = displayResult.sentence_profile || {};
  const roles = profile.actor_roles || {};
  const agents = roles.agents || [];
  const targets = roles.targets || [];
  const actions = roles.actions || [];
  const events = profile.events || [];
  const polarityRows = displayResult.polarity_effect?.rows || [];
  const candidateRows = [
    ...(displayResult.problems || []).map((row) => ({ ...row, keywords: row.keywords || row.matched_keywords || [], decision: 'accepted' })),
    ...(displayResult.filtered_out || []).map((row) => ({ ...row, keywords: row.keywords || row.matched_keywords || [], decision: 'filtered' })),
  ];
  const caseText = displayResult.case_description || '';
  const eventById = new Map(events.map((event) => [event.event_id, event]));
  const supportEntries = [];
  const uniqueProblemSummaries = (items) => {
    const seen = new Set();
    return items.filter((item) => {
      const key = `${item.code}-${item.decision}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  };
  const uniquePolarityRows = (items) => {
    const seen = new Set();
    return items.filter((item, index) => {
      const key = `${item.code}-${item.event_id || ''}-${item.actor || ''}-${item.action || ''}-${item.target || ''}-${index}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  };

  const addSupportEntry = (support, event, type, label, detail) => {
    const start = Number(support?.start);
    const end = Number(support?.end);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;
    supportEntries.push({
      type,
      label,
      detail,
      start,
      end,
      value: caseText.slice(start, end),
      eventId: event?.event_id || '',
      supportId: support?.id || '',
      supportLabel: support?.label || '',
      relatedEventSeed: event ? [event] : [],
      roleSource: `${type}:${support?.id || `${start}-${end}`}`,
    });
  };

  events.forEach((event) => {
    (event.agent_mentions || []).forEach((mention) => addSupportEntry(
      mention,
      event,
      'agent',
      'Agent',
      'บทบาทผู้กระทำหรือผู้ที่เป็นต้นทางของ action ใน clause ที่ระบบจับได้',
    ));
    (event.target_mentions || []).forEach((mention) => addSupportEntry(
      mention,
      event,
      'target',
      'Target',
      'บทบาทผู้ถูกกระทำหรือผู้ที่ได้รับผลจากเหตุการณ์ในประโยคนี้',
    ));
    (event.action_mentions || []).forEach((mention) => addSupportEntry(
      mention,
      event,
      'action',
      'Action',
      'คำกริยาหลักที่เชื่อมความสัมพันธ์ระหว่างผู้กระทำกับผู้ถูกกระทำใน event นี้',
    ));
  });

  (roles.mentions || []).forEach((mention) => {
    const start = Number(mention?.start);
    const end = Number(mention?.end);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;
    const matchingEvents = events.filter((event) => (
      (event.agent_mentions || []).some((entry) => entry.mention_id === mention.mention_id)
      || (event.target_mentions || []).some((entry) => entry.mention_id === mention.mention_id)
    ));
    if (matchingEvents.length) return;
    const rolesForMention = mention.roles || [];
    if (!rolesForMention.some((role) => role === 'agent' || role === 'target')) return;
    const mentionType = rolesForMention.includes('agent') ? 'agent' : 'target';
    supportEntries.push({
      type: mentionType,
      label: mentionType === 'agent' ? 'Agent' : 'Target',
      detail: mentionType === 'agent'
        ? 'บทบาทผู้กระทำที่ระบบพบจาก mention นี้ แต่ยังไม่ได้ผูกเข้ากับ event ชัดเจน'
        : 'บทบาทผู้ถูกกระทำที่ระบบพบจาก mention นี้ แต่ยังไม่ได้ผูกเข้ากับ event ชัดเจน',
      start,
      end,
      value: caseText.slice(start, end),
      eventId: '',
      supportId: mention.mention_id || '',
      supportLabel: mention.mention_text || mention.label || mention.normalized || '',
      relatedEventSeed: [],
      roleSource: `${mentionType}:${mention.mention_id || `${start}-${end}`}`,
    });
  });

  const supportTokensBySpan = new Map();
  supportEntries.forEach((entry) => {
    const key = `${entry.type}-${entry.start}-${entry.end}`;
    const existing = supportTokensBySpan.get(key);
    if (existing) {
      const nextEvents = [...existing.relatedEvents];
      entry.relatedEventSeed.forEach((event) => {
        if (event?.event_id && !nextEvents.some((existingEvent) => existingEvent.event_id === event.event_id)) {
          nextEvents.push(event);
        }
      });
      supportTokensBySpan.set(key, { ...existing, relatedEvents: nextEvents });
      return;
    }
    supportTokensBySpan.set(key, {
      ...entry,
      relatedEvents: [...entry.relatedEventSeed],
    });
  });

  const negationTokens = (profile.negation_markers || []).flatMap((value) => (
    findAllSpanOccurrences(caseText, value).map((span, index) => ({
      type: 'negation',
      value: caseText.slice(span.start, span.end),
      label: 'Negation',
      detail: 'คำปฏิเสธที่อาจลดน้ำหนักหรือกรองบาง candidate ออกจากผลสุดท้าย',
      start: span.start,
      end: span.end,
      relatedEvents: [],
      relatedPolarity: polarityRows.filter((row) => (
        (Number(row.gate || 1) < 1 || row.decision === 'filtered')
        && (row.explanation?.includes(value) || (row.trigger_terms || []).includes(value))
      )),
      relatedProblems: candidateRows
        .filter((row) => (
          row.polarity_negated
          && (row.polarity_reason?.includes(value) || (row.polarity_negated_terms || []).includes(value))
        ))
        .map((row) => ({
          code: row.code,
          name: row.name,
          confidence: row.confidence_after_polarity ?? row.confidence,
          decision: row.decision,
          reasoning: row.polarity_reason || row.reasoning || row.validation_notes,
        })),
      negationKey: `${value}-${index}`,
    }))
  ));

  const keywordTokens = candidateRows.flatMap((row, rowIndex) => (
    (row.matched_spans || []).map((span, spanIndex) => {
      const start = Number(span?.start);
      const end = Number(span?.end);
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
      const relatedEvents = [];
      const eventId = polarityRows.find((item) => item.code === row.code)?.event_id;
      if (eventId && eventById.has(eventId)) relatedEvents.push(eventById.get(eventId));
      events.forEach((event) => {
        if (spanOverlaps(start, end, Number(event.span_start || 0), Number(event.span_end || 0))) {
          if (!relatedEvents.some((existingEvent) => existingEvent.event_id === event.event_id)) relatedEvents.push(event);
        }
      });
      return {
        type: 'keyword',
        value: caseText.slice(start, end),
        label: 'Keyword',
        detail: 'คำสำคัญเชิง lexical ที่ detector ใช้เป็นสัญญาณตั้งต้นก่อนเช็คบริบทและ polarity',
        start,
        end,
        relatedEvents,
        relatedPolarity: polarityRows.filter((item) => item.code === row.code),
        relatedProblems: [{
          code: row.code,
          name: row.name,
          confidence: row.confidence,
          decision: row.decision,
          reasoning: row.reasoning || row.validation_notes,
        }],
        keywordKey: `${row.code}-${rowIndex}-${spanIndex}`,
      };
    }).filter(Boolean)
  ));

  const lexicalTokens = [
    ...Array.from(supportTokensBySpan.values()).map((token) => {
      const relatedProblems = candidateRows
        .filter((row) => (
          (row.polarity_event_id && token.relatedEvents.some((event) => event.event_id === row.polarity_event_id))
          || (row.matched_spans || []).some((span) => spanOverlaps(token.start, token.end, Number(span.start || 0), Number(span.end || 0)))
          || (row.evidence_spans || []).some((span) => spanOverlaps(token.start, token.end, Number(span.start || 0), Number(span.end || 0)))
        ))
        .map((row) => ({
          code: row.code,
          name: row.name,
          confidence: row.confidence,
          decision: row.decision,
          reasoning: row.reasoning || row.validation_notes,
        }));
      const relatedPolarity = uniquePolarityRows(polarityRows.filter((row) => (
        (row.event_id && token.relatedEvents.some((event) => event.event_id === row.event_id))
        || (
          !row.event_id
          && (
            (token.type === 'agent' && row.actor === token.value)
            || (token.type === 'target' && row.target === token.value)
            || (token.type === 'action' && row.action === token.value)
          )
        )
      )));
      return {
        ...token,
        relatedProblems: uniqueProblemSummaries(relatedProblems),
        relatedPolarity,
      };
    }),
    ...negationTokens,
    ...keywordTokens,
  ];
  const tokenizedParts = tokenizeCaseText(caseText, lexicalTokens).map((token, index) => {
    const tokenKey = `${token.type}-${token.start}-${token.end}-${index}`;
    if (token.type === 'plain') return { ...token, tokenKey };

    let contextNote = null;
    let filteredRelatedEvents = token.relatedEvents || [];

    if (!filteredRelatedEvents.length) {
      filteredRelatedEvents = events.filter((event) => (
        Number.isFinite(Number(event.span_start))
        && Number.isFinite(Number(event.span_end))
        && spanOverlaps(token.start, token.end, Number(event.span_start), Number(event.span_end))
      ));
    }

    if (filteredRelatedEvents.length) {
      const roleMatches = filteredRelatedEvents.some((event) => {
        if (token.type === 'agent') {
          return (event.agent_mentions || []).some((mention) => spanOverlaps(token.start, token.end, Number(mention.start || 0), Number(mention.end || 0)));
        }
        if (token.type === 'target') {
          return (event.target_mentions || []).some((mention) => spanOverlaps(token.start, token.end, Number(mention.start || 0), Number(mention.end || 0)));
        }
        if (token.type === 'action') {
          return (event.action_mentions || []).some((mention) => spanOverlaps(token.start, token.end, Number(mention.start || 0), Number(mention.end || 0)));
        }
        return true;
      });

      if (!roleMatches && token.type !== 'keyword' && token.type !== 'negation') {
        contextNote = `occurrence นี้อยู่ใกล้ event จริง แต่ไม่ได้ทำหน้าที่เป็น ${token.label} หลักของ event นั้น`;
      }
    }

    return {
      ...token,
      tokenKey,
      contextNote,
      relatedEvents: filteredRelatedEvents
    };
  });
  const interactiveTokens = tokenizedParts.filter((token) => token.type !== 'plain');
  const matchedKeywords = analysis.unique_keywords || [];
  const caseKey = `${displayResult.case_id || 'no-case'}::${displayResult.case_description || ''}`;
  const [tokenSelection, setTokenSelection] = useState({ caseKey: '', tokenKey: null });
  const [eventSelection, setEventSelection] = useState({ caseKey: '', index: 0 });
  const [detectorSortMode, setDetectorSortMode] = useState('result');
  const [detectorGroupState, setDetectorGroupState] = useState({ scope: '', groups: {} });
  const selectedTokenKey = tokenSelection.caseKey === caseKey ? tokenSelection.tokenKey : null;
  const selectedEventIndex = eventSelection.caseKey === caseKey ? eventSelection.index : 0;
  const activeToken = interactiveTokens.find((token) => token.tokenKey === selectedTokenKey) || interactiveTokens[0] || null;
  const activeEvent = events[selectedEventIndex] || events[0] || null;
  const sortedDetectorRows = [...rows].sort((a, b) => {
    if (detectorSortMode === 'category') {
      return problemCodeGroup(a.code).localeCompare(problemCodeGroup(b.code), undefined, { numeric: true })
        || String(a.code || '').localeCompare(String(b.code || ''), undefined, { numeric: true })
        || Number(b.confidence || 0) - Number(a.confidence || 0);
    }
    return Number(b.confidence || 0) - Number(a.confidence || 0)
      || String(a.code || '').localeCompare(String(b.code || ''), undefined, { numeric: true });
  });
  const detectorGroups = (() => {
    const grouped = new Map();
    sortedDetectorRows.forEach((row) => {
      const group = problemCodeGroup(row.code);
      if (!grouped.has(group)) grouped.set(group, []);
      grouped.get(group).push(row);
    });
    return Array.from(grouped.entries()).map(([group, items]) => ({ group, items }));
  })();
  const detectorGroupScope = `${caseKey}::${detectorSortMode}`;
  const collapsedDetectorGroups = detectorGroupState.scope === detectorGroupScope ? detectorGroupState.groups : {};
  const activeTokenTypeClass = activeToken?.type === 'negation'
    ? 'bg-error-container text-on-error-container'
    : activeToken?.type === 'agent'
      ? 'bg-yellow-100 text-slate-950 dark:bg-yellow-900/60 dark:text-yellow-100'
      : activeToken?.type === 'target'
        ? 'bg-green-100 text-green-950 dark:bg-green-950/60 dark:text-green-100'
        : activeToken?.type === 'action'
          ? 'bg-red-100 text-red-950 dark:bg-red-950/60 dark:text-red-100'
          : 'bg-teal-100 text-teal-950 dark:bg-teal-950/60 dark:text-teal-100';

  const focusToken = (matcher) => {
    const token = interactiveTokens.find(matcher);
    if (token) setTokenSelection({ caseKey, tokenKey: token.tokenKey });
  };

  const toggleDetectorGroup = (group) => {
    setDetectorGroupState((current) => {
      const groups = current.scope === detectorGroupScope ? current.groups : {};
      return { scope: detectorGroupScope, groups: { ...groups, [group]: !groups[group] } };
    });
  };

  const setAllDetectorGroups = (collapsed) => {
    const next = {};
    detectorGroups.forEach(({ group }) => {
      next[group] = collapsed;
    });
    setDetectorGroupState({ scope: detectorGroupScope, groups: next });
  };

  const renderDetectorCard = (row) => (
    <div key={row.code} className="rounded-xl bg-surface-container-lowest p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <div className="font-headline text-base font-extrabold text-teal-700">{row.code}</div>
            <span className="rounded bg-surface-container-low px-2 py-0.5 text-[10px] font-bold uppercase text-on-surface-variant">group {problemCodeGroup(row.code)}</span>
          </div>
          <p className="mt-1 break-words text-sm font-semibold leading-snug text-on-surface">{row.name}</p>
        </div>
        <span className="rounded-lg bg-surface-container-low px-2.5 py-1 text-xs font-bold text-on-surface">{formatPercent(row.confidence)}</span>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {(row.keywords || []).length ? (row.keywords || []).map((keyword) => (
          <span className="rounded-lg bg-teal-100 px-2.5 py-1 text-[11px] font-bold text-teal-950 dark:bg-teal-950/60 dark:text-teal-100" key={`${row.code}-${keyword}`}>
            {keyword}
          </span>
        )) : <span className="text-xs text-on-surface-variant">No keyword match</span>}
      </div>
      {row.reasoning && <p className="mt-3 text-xs leading-relaxed text-on-surface-variant">{compactText(row.reasoning, 180)}</p>}
    </div>
  );

  return (
    <div className="space-y-6">
      <section className="space-y-6">
        <div className="rounded-xl bg-surface-container-lowest p-6">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-headline text-lg font-bold">Lexical Breakdown</h2>
              <p className="mt-1 text-xs text-on-surface-variant">ผูกกับ case_id: {displayResult.case_id || 'ยังไม่มี case id'}</p>
            </div>
            <div className="flex flex-wrap gap-2 text-[10px] font-bold uppercase text-slate-500">
              <span className="flex items-center gap-1"><span className="h-3 w-3 rounded-sm bg-green-500" />Target</span>
              <span className="flex items-center gap-1"><span className="h-3 w-3 rounded-sm bg-yellow-400" />Agent</span>
              <span className="flex items-center gap-1"><span className="h-3 w-3 rounded-sm bg-red-200" />Action</span>
              <span className="flex items-center gap-1"><span className="h-3 w-3 rounded-sm bg-red-500" />Negation</span>
              <span className="flex items-center gap-1"><span className="h-3 w-3 rounded-sm bg-teal-200" />Keyword</span>
            </div>
          </div>
          <div className="rounded-xl bg-surface-container-low p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Analyzed Case Text</div>
              <StatusBadge label={interactiveTokens.length ? `${interactiveTokens.length} interactive tokens` : 'no token'} tone={interactiveTokens.length ? 'live' : 'neutral'} />
            </div>
            <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">
              กดหรือชี้คำที่ถูกไฮไลต์เพื่อดูว่าระบบตีความคำนั้นอย่างไร และเชื่อมกับ problem code ไหนบ้างแบบ realtime
            </p>
            <div className="mt-3 text-xl leading-[2.1]">
              {tokenizedParts.length ? tokenizedParts.map((token, index) => (
                token.type === 'plain' ? (
                  <span key={`${token.type}-${token.start}-${index}`} className="whitespace-pre-wrap text-on-surface">
                    {token.value}
                  </span>
                ) : (
                  <button
                    className={`mb-1 mr-1 inline-flex items-center rounded-lg px-2 py-1 font-headline transition-all hover:-translate-y-0.5 hover:shadow-sm ${
                      token.type === 'negation' ? 'bg-error-container text-on-error-container'
                        : token.type === 'agent' ? 'bg-yellow-100 text-slate-950 dark:bg-yellow-900/60 dark:text-yellow-100'
                          : token.type === 'target' ? 'bg-green-100 text-green-950 dark:bg-green-950/60 dark:text-green-100'
                            : token.type === 'action' ? 'bg-red-100 text-red-950 dark:bg-red-950/60 dark:text-red-100'
                              : 'bg-teal-100 text-teal-950 dark:bg-teal-950/60 dark:text-teal-100'
                    } ${activeToken?.tokenKey === token.tokenKey ? 'ring-2 ring-teal-500/60 ring-offset-2 ring-offset-surface-container-low' : ''}`}
                    key={token.tokenKey}
                    onClick={() => setTokenSelection({ caseKey, tokenKey: token.tokenKey })}
                    onFocus={() => setTokenSelection({ caseKey, tokenKey: token.tokenKey })}
                    onMouseEnter={() => setTokenSelection({ caseKey, tokenKey: token.tokenKey })}
                    type="button"
                  >
                    {token.value}
                  </button>
                )
              )) : <span className="text-sm text-on-surface-variant">Run analysis to extract polarity roles.</span>}
            </div>
            <div className="mt-4 rounded-xl bg-surface-container-lowest p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Live Token Inspector</div>
                  <h3 className="mt-1 font-headline text-sm font-bold text-on-surface">
                    {activeToken ? activeToken.value : 'เลือกคำที่ไฮไลต์'}
                  </h3>
                </div>
                {activeToken && <span className={`rounded-lg px-2.5 py-1 text-xs font-bold ${activeTokenTypeClass}`}>{activeToken.label || activeToken.type}</span>}
              </div>
              {activeToken ? (
                <>
                  {activeToken.contextNote && (
                    <div className="mt-4 flex items-center gap-1.5 rounded-lg bg-yellow-50 p-2.5 text-[11px] font-medium text-yellow-800 dark:bg-yellow-900/20 dark:text-yellow-200 border border-yellow-200/50">
                      <span aria-hidden="true" className="material-symbols-outlined text-sm">info</span>
                      {activeToken.contextNote}
                    </div>
                  )}
                  <div className="mt-4 grid gap-3 sm:grid-cols-4">
                    <MetricTile label="Type" value={activeToken.label || activeToken.type} hint={`position ${activeToken.start}-${activeToken.end}`} tone="bg-surface-container-low" />
                    <MetricTile label="Related Codes" value={activeToken.relatedProblems?.length || 0} hint="problem rows ที่เชื่อมกับคำนี้" tone="bg-surface-container-low" />
                    <MetricTile label="Event Frames" value={activeToken.relatedEvents?.length || 0} hint="เหตุการณ์ที่ใช้คำนี้ใน clause" tone="bg-surface-container-low" />
                    <MetricTile label="Polarity Rows" value={activeToken.relatedPolarity?.length || 0} hint="แถว polarity ที่เกี่ยวข้อง" tone="bg-surface-container-low" />
                  </div>
                  <p className="mt-4 text-sm leading-relaxed text-on-surface-variant">{activeToken.detail}</p>

                  {activeToken.relatedProblems?.length > 0 && (
                    <div className="mt-4">
                      <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Related Problem Codes</div>
                      <div className="mt-2 grid gap-3 sm:grid-cols-2">
                        {activeToken.relatedProblems.map((item, itemIndex) => (
                          <div className="rounded-xl bg-surface-container-low p-3" key={`${activeToken.tokenKey}-problem-${item.code}-${itemIndex}`}>
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-headline font-extrabold text-teal-700">{item.code}</span>
                              <span className={`rounded-lg px-2 py-1 text-[11px] font-bold ${item.decision === 'filtered' ? 'bg-yellow-100 text-yellow-900 dark:bg-yellow-950/50 dark:text-yellow-100' : 'bg-green-100 text-green-900 dark:bg-green-950/50 dark:text-green-100'}`}>
                                {item.decision === 'filtered' ? 'filtered' : 'accepted'}
                              </span>
                            </div>
                            <p className="mt-1 text-sm font-semibold text-on-surface">{item.name}</p>
                            <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">{compactText(item.reasoning, 180)}</p>
                            <p className="mt-2 text-[11px] font-bold text-on-surface">confidence {formatPercent(item.confidence)}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {activeToken.relatedEvents?.length > 0 && (
                    <div className="mt-4">
                      <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Related Event Frames</div>
                      <div className="mt-2 space-y-3">
                        {activeToken.relatedEvents.map((event, eventIndex) => (
                          <div className="rounded-xl bg-surface-container-low p-3" key={`${activeToken.tokenKey}-event-${eventIndex}`}>
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <span className="font-semibold text-on-surface">{event.agent} → {event.action} → {event.target}</span>
                              <StatusBadge label={event.pattern} tone={event.needs_review ? 'warning' : 'live'} />
                            </div>
                            <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">{event.evidence_span}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {activeToken.relatedPolarity?.length > 0 && (
                    <div className="mt-4">
                      <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Related Polarity Rows</div>
                      <div className="mt-2 space-y-2">
                        {activeToken.relatedPolarity.map((row, rowIndex) => (
                          <div className="rounded-xl bg-surface-container-low p-3" key={`${activeToken.tokenKey}-polarity-${row.code}-${rowIndex}`}>
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <span className="font-semibold text-on-surface">{row.code} · {row.actor} → {row.action} → {row.target}</span>
                              <span className="text-xs font-bold text-on-surface">{formatPercent(row.after_polarity_gate ?? row.gate ?? 0)}</span>
                            </div>
                            <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">{compactText(row.explanation, 180)}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <p className="mt-3 text-sm text-on-surface-variant">ยังไม่มี token ให้ inspect จากเคสปัจจุบัน</p>
              )}
            </div>
            {matchedKeywords.length > 0 && (
              <div className="mt-4 rounded-lg bg-surface-container-lowest p-3">
                <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Matched Keywords</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {matchedKeywords.map((keyword) => (
                    <button
                      className={`rounded-lg px-2.5 py-1 text-xs font-bold transition-colors ${activeToken?.type === 'keyword' && activeToken.value === keyword ? 'bg-teal-600 text-white' : 'bg-teal-100 text-teal-950 dark:bg-teal-950/60 dark:text-teal-100'}`}
                      key={keyword}
                      onClick={() => focusToken((token) => token.type === 'keyword' && token.value === keyword)}
                      onMouseEnter={() => focusToken((token) => token.type === 'keyword' && token.value === keyword)}
                      type="button"
                    >
                      {keyword}
                    </button>
                  ))}
                </div>
                <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">
                  ถ้าคำสั้นซ้อนอยู่ในคำยาว เช่น <strong className="text-on-surface">เครียด</strong> อยู่ใน <strong className="text-on-surface">เครียดมาก</strong>
                  ตัวไฮไลต์ในประโยคจะโชว์คำยาวก่อนเพื่อไม่ให้กล่องทับกัน แต่ระบบยังนับ keyword ทั้งสองคำตามรายการนี้
                </p>
              </div>
            )}
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <MetricTile label="ผู้ถูกกระทำ / Target" value={targets.join(', ') || 'ไม่พบชัดเจน'} hint="noun phrase ก่อน/หลัง passive marker" />
            <MetricTile label="ผู้กระทำ / Agent" value={agents.join(', ') || 'ไม่พบชัดเจน'} hint="บุคคลที่สัมพันธ์กับ action" />
            <MetricTile label="Action" value={actions.join(', ') || 'ไม่พบชัดเจน'} hint={roles.relation_summary || 'no relation'} />
          </div>
          <div className="mt-4 space-y-4">
            <div className="rounded-xl bg-surface-container-low p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Case Signal Overview</div>
                  <h3 className="mt-1 font-headline text-base font-bold text-on-surface">Sentence Profile</h3>
                </div>
                <StatusBadge label={roles.voice || 'active'} tone={(profile.negation_markers || []).length ? 'warning' : 'live'} />
              </div>
              <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">สรุปสัญญาณของประโยคแบบเต็มแถว เพื่อไม่ให้ข้อมูลเรื่องความยาว, negation และ relation ถูกบีบในคอลัมน์แคบ</p>
              <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <MetricTile label="Sentence Length" value={profile.length ?? 'N/A'} hint={profile.length_category} />
                <MetricTile label="Negation Markers" value={(profile.negation_markers || []).length} hint={(profile.negation_markers || []).join(', ') || 'ไม่พบคำปฏิเสธ'} tone={(profile.negation_markers || []).length ? 'bg-yellow-50 dark:bg-yellow-950/40' : 'bg-green-50 dark:bg-green-950/40'} />
                <MetricTile label="Relation" value={roles.relation_summary || 'N/A'} hint={`voice=${roles.voice || 'active'}`} />
                <MetricTile label="Role Mentions" value={(roles.mentions || []).length || (agents.length + targets.length + actions.length)} hint={`agent ${agents.length} · target ${targets.length} · action ${actions.length}`} />
              </div>
            </div>

            <div className="rounded-xl bg-surface-container-low p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Detector View</div>
                  <h2 className="mt-1 font-headline text-base font-bold text-on-surface">Keyword / Context Detection</h2>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge label={`${rows.length} rows`} tone={rows.length ? 'live' : 'neutral'} />
                  <button
                    className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-colors ${detectorSortMode === 'result' ? 'bg-teal-600 text-white' : 'bg-surface-container-lowest text-on-surface hover:bg-surface-container'}`}
                    onClick={() => setDetectorSortMode('result')}
                    type="button"
                  >
                    ตามผลลัพธ์
                  </button>
                  <button
                    className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-colors ${detectorSortMode === 'category' ? 'bg-teal-600 text-white' : 'bg-surface-container-lowest text-on-surface hover:bg-surface-container'}`}
                    onClick={() => setDetectorSortMode('category')}
                    type="button"
                  >
                    ตามกลุ่มรหัส
                  </button>
                  {detectorSortMode === 'category' && detectorGroups.length > 1 && (
                    <>
                      <button
                        className="rounded-lg bg-surface-container-lowest px-3 py-1.5 text-xs font-bold text-on-surface transition-colors hover:bg-surface-container"
                        onClick={() => setAllDetectorGroups(false)}
                        type="button"
                      >
                        ขยายทั้งหมด
                      </button>
                      <button
                        className="rounded-lg bg-surface-container-lowest px-3 py-1.5 text-xs font-bold text-on-surface transition-colors hover:bg-surface-container"
                        onClick={() => setAllDetectorGroups(true)}
                        type="button"
                      >
                        ย่อทั้งหมด
                      </button>
                    </>
                  )}
                </div>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">ค่าเริ่มต้นเรียงตามผลลัพธ์ของ detector; ถ้าต้องการอ่านเชิง taxonomy สามารถสลับเป็นกลุ่มรหัส เช่น 01, 02, 03 ได้</p>
              {sortedDetectorRows.length ? (
                detectorSortMode === 'category' ? (
                  <div className="mt-4 space-y-3">
                    {detectorGroups.map(({ group, items }) => {
                      const isCollapsed = collapsedDetectorGroups[group];
                      return (
                        <section key={`detector-group-${group}`} className="rounded-xl bg-surface-container-lowest p-4">
                          <button
                            className="flex w-full items-center justify-between gap-3 text-left"
                            onClick={() => toggleDetectorGroup(group)}
                            type="button"
                          >
                            <div>
                              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Detector Group</div>
                              <h3 className="mt-1 font-headline text-sm font-bold text-on-surface">Group {problemCodeGroupLabel(group)}</h3>
                            </div>
                            <div className="flex items-center gap-2">
                              <span className="rounded-lg bg-surface-container-low px-2.5 py-1 text-[11px] font-bold text-on-surface">{items.length} rows</span>
                              <span aria-hidden="true" className="material-symbols-outlined text-on-surface-variant">{isCollapsed ? 'expand_more' : 'expand_less'}</span>
                            </div>
                          </button>
                          {!isCollapsed && (
                            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                              {items.map(renderDetectorCard)}
                            </div>
                          )}
                        </section>
                      );
                    })}
                  </div>
                ) : (
                  <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {sortedDetectorRows.map(renderDetectorCard)}
                  </div>
                )
              ) : <p className="mt-4 text-sm text-on-surface-variant">No keyword rows yet.</p>}
            </div>
          </div>
          <div className="mt-4 rounded-xl bg-surface-container-low p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-headline text-sm font-bold text-on-surface">Event Frames</h3>
                <p className="mt-1 text-xs text-on-surface-variant">แยกเหตุการณ์ตาม clause เพื่อไม่ลากผู้พูดถึงคนละช่วงมาเป็นผู้กระทำ</p>
              </div>
              <StatusBadge label={`${events.length} events`} tone={events.length ? 'live' : 'neutral'} />
            </div>
            {events.length ? (
              <div className="mt-4 space-y-4">
                <div className="rounded-xl bg-surface-container-lowest p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Selected Event</div>
                      <h4 className="mt-1 break-words font-headline text-sm font-bold text-on-surface">
                        {activeEvent?.agent} → {activeEvent?.action} → {activeEvent?.target}
                      </h4>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <StatusBadge label={activeEvent?.event_type || 'event'} tone="live" />
                      <StatusBadge label={activeEvent?.pattern || 'pattern'} tone={activeEvent?.needs_review ? 'warning' : 'neutral'} />
                    </div>
                  </div>
                  <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                    <MetricTile label="Confidence" value={formatPercent(activeEvent?.confidence ?? 0)} hint="event-level confidence" tone="bg-surface-container-low" />
                    <MetricTile label="Agent" value={activeEvent?.agents?.length || (activeEvent?.agent ? 1 : 0)} hint={activeEvent?.agent || 'ไม่พบ'} tone="bg-surface-container-low" />
                    <MetricTile label="Target" value={activeEvent?.targets?.length || (activeEvent?.target ? 1 : 0)} hint={activeEvent?.target || 'ไม่พบ'} tone="bg-surface-container-low" />
                    <MetricTile label="Context Actors" value={activeEvent?.context_actors?.length || 0} hint="ตัวแปรแวดล้อมของ clause" tone="bg-surface-container-low" />
                  </div>
                  <div className="mt-4 grid gap-3 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
                    <div className="rounded-xl bg-surface-container-low p-4">
                      <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Evidence Span</div>
                      <p className="mt-2 text-sm leading-relaxed text-on-surface">{activeEvent?.evidence_span || 'ไม่มี evidence span'}</p>
                      {activeEvent?.note && <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">{activeEvent.note}</p>}
                    </div>
                    <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-1">
                      {[
                        { type: 'agent', label: 'Agent', value: activeEvent?.agent },
                        { type: 'action', label: 'Action', value: activeEvent?.action },
                        { type: 'target', label: 'Target', value: activeEvent?.target },
                      ].map((item) => (
                        <button
                          className="rounded-xl bg-surface-container-low p-4 text-left transition-colors hover:bg-surface-container"
                          key={`${item.type}-${item.value}`}
                          onClick={() => item.value && focusToken((token) => token.type === item.type && token.value === item.value)}
                          type="button"
                        >
                          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">{item.label}</div>
                          <div className="mt-2 break-words text-sm font-bold text-on-surface">{item.value || 'ไม่พบ'}</div>
                          <div className="mt-2 text-xs text-teal-700 dark:text-teal-300">กดเพื่อโฟกัสคำนี้ใน Analyzed Case Text</div>
                        </button>
                      ))}
                    </div>
                  </div>
                  {(activeEvent?.context_actors || []).length > 0 && (
                    <div className="mt-4">
                      <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Context Actors</div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {activeEvent.context_actors.map((actor) => (
                          <span className="rounded-lg bg-surface-container-low px-2.5 py-1 text-xs font-bold text-on-surface" key={`${activeEvent.event_type}-${actor}`}>
                            {actor}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {events.map((event, index) => {
                    const isActive = index === selectedEventIndex;
                    return (
                      <button
                        className={`rounded-xl border p-4 text-left transition-all ${isActive ? 'border-teal-500 bg-teal-50 shadow-sm dark:bg-teal-950/30' : 'border-outline-variant/20 bg-surface-container-lowest hover:border-teal-400/40 hover:bg-surface-container'}`}
                        key={`${event.event_type}-${index}`}
                        onClick={() => setEventSelection({ caseKey, index })}
                        onMouseEnter={() => setEventSelection({ caseKey, index })}
                        type="button"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div className="min-w-0">
                            <div className="text-[10px] font-bold uppercase tracking-widest text-teal-700 dark:text-teal-300">{event.event_type}</div>
                            <div className="mt-1 break-words text-sm font-semibold leading-relaxed text-on-surface">{event.agent} → {event.action} → {event.target}</div>
                          </div>
                          <StatusBadge label={event.pattern} tone={event.needs_review ? 'warning' : 'live'} />
                        </div>
                        <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">{compactText(event.evidence_span, 200)}</p>
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : <div className="mt-3 rounded-lg bg-surface-container-lowest p-3 text-sm text-on-surface-variant">ยังไม่มี event frame จากเคสปัจจุบัน</div>}
          </div>
        </div>

        <div className="rounded-xl bg-surface-container-low p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-headline text-lg font-bold">เมื่อมี Sentence Polarity แล้วผลเปลี่ยนอย่างไร</h2>
              <p className="mt-1 text-sm text-on-surface-variant">{displayResult.polarity_effect?.interpretation || 'ยังไม่มี polarity effect'}</p>
            </div>
            <StatusBadge label={`${polarityRows.length} candidate rows`} />
          </div>
          <div className="mt-5 overflow-x-auto rounded-lg bg-surface-container-lowest">
            <div className="min-w-[620px]">
              <div className="grid grid-cols-[90px_1fr_110px_110px_100px] gap-3 bg-surface-container-high px-4 py-3 text-[10px] font-bold uppercase text-on-surface-variant">
                <span>Code</span>
                <span>Actor / Target / Action</span>
                <span>Before</span>
                <span>After</span>
                <span>Decision</span>
              </div>
              {polarityRows.length ? polarityRows.map((row, index) => (
                <div key={`${row.code}-${index}`} className="grid grid-cols-[90px_1fr_110px_110px_100px] gap-3 px-4 py-4 text-sm">
                  <span className="font-headline font-extrabold text-teal-700">{row.code}</span>
                  <div>
                    <div className="font-semibold text-on-surface">{row.actor} → {row.action} → {row.target}</div>
                    <p className="mt-1 text-xs leading-relaxed text-on-surface-variant">{row.explanation}</p>
                  </div>
                  <span>{formatPercent(row.before_confidence)}</span>
                  <span>{formatPercent(row.after_polarity_gate)}</span>
                  <span className={row.decision === 'filtered' ? 'font-bold text-yellow-700 dark:text-yellow-300' : 'font-bold text-teal-700'}>{row.decision}</span>
                </div>
              )) : <div className="px-4 py-5 text-sm text-on-surface-variant">ยังไม่มีผลจาก polarity gate</div>}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

function vectorInterpretation(node, queryNode, edge) {
  if (!node) return 'เลือกหรือ hover ที่ node เพื่อดูรายละเอียด';
  if (node.type === 'query') return 'นี่คือข้อความเคสที่กำลังวิเคราะห์ ใช้เป็นจุดเริ่มต้นในการดูว่าระบบเชื่อมไปยังปัญหาและเอกสารใดบ้าง';
  const distance = node.semantic_distance_to_query ?? edge?.distance;
  const readableDistance = formatNumber(distance, 3);
  const readableScore = formatNumber(node.score, 3);
  if (node.type === 'document') {
    return `${node.id} คือเอกสารที่ระบบดึงมาเพื่อช่วยอธิบายหรือรองรับรหัสปัญหา ถ้า distance ต่ำ แปลว่าเนื้อหาเอกสารใกล้กับบริบทของเคสมากขึ้น ตอนนี้ distance=${readableDistance}, score=${readableScore}. ${node.explanation || ''}`;
  }
  return `${node.id} คือรหัสปัญหาที่ระบบพบในเคสนี้ ใช้ดูว่าเคสมีแนวโน้มเกี่ยวข้องกับปัญหานั้นมากแค่ไหน ถ้า distance ต่ำและ confidence สูง ควรพิจารณารหัสนี้มากขึ้น ตอนนี้ distance=${readableDistance}, confidence=${formatPercent(node.score)}. ${node.explanation || ''}`;
}

function prettyNodeId(id) {
  return String(id || '').replace(/^D_(\d+)$/, 'D$1');
}

function compactText(value, maxLength = 640) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  return text.length > maxLength ? `${text.slice(0, maxLength).trim()}…` : text;
}

function nodeTypeLabel(type) {
  if (type === 'query') return 'Case Query';
  if (type === 'problem') return 'Problem Code';
  if (type === 'document') return 'Evidence Document';
  return type || 'Node';
}

const SEMANTIC_MAP_WIDTH = 1000;
const SEMANTIC_MAP_HEIGHT = 680;

function VectorScene({ nodes, edges, selectedNodeId, onSelectNode, retrievedDocs = [], problems = [] }) {
  const [showZones, setShowZones] = useState(true);
  const [showLinks, setShowLinks] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [showSignal, setShowSignal] = useState(true);
  const [layoutMode, setLayoutMode] = useState('result');
  const [manualPositions, setManualPositions] = useState({});
  const [dragNodeId, setDragNodeId] = useState(null);
  const [interactionNote, setInteractionNote] = useState('เลือก problem code หรือ evidence doc เพื่อดูระยะ semantic และเหตุผลประกอบ');

  const edgeColor = (edge) => {
    if (edge.edge_type === 'query-document') return '#38bdf8';
    if (edge.edge_type === 'problem-document') return '#a78bfa';
    return '#5eead4';
  };

  const nodeTone = (node) => {
    if (node.type === 'query') return { fill: '#0f1c2c', stroke: '#14b8a6', text: '#ffffff', chip: '#ccfbf1' };
    if (node.type === 'document') return { fill: '#e0f2fe', stroke: '#38bdf8', text: '#075985', chip: '#0ea5e9' };
    const severity = Number(node.severity || 1);
    if (severity >= 4) return { fill: '#fee2e2', stroke: '#ef4444', text: '#7f1d1d', chip: '#ef4444' };
    if (severity === 3) return { fill: '#fef9c3', stroke: '#eab308', text: '#713f12', chip: '#eab308' };
    return { fill: '#dcfce7', stroke: '#10b981', text: '#064e3b', chip: '#10b981' };
  };

  const positionedNodes = useMemo(() => {
    const queryNodes = nodes.filter((node) => node.type === 'query');
    const baseProblemNodes = nodes.filter((node) => node.type === 'problem');
    const baseDocumentNodes = nodes.filter((node) => node.type === 'document');
    const otherNodes = nodes.filter((node) => !['query', 'problem', 'document'].includes(node.type));
    const supportEdges = edges.filter((edge) => edge.edge_type === 'problem-document');
    const problemNodes = [...baseProblemNodes].sort((a, b) => {
      if (layoutMode === 'category') {
        return problemCodeGroup(a.code || a.id).localeCompare(problemCodeGroup(b.code || b.id), undefined, { numeric: true })
          || String(a.code || a.id).localeCompare(String(b.code || b.id), undefined, { numeric: true })
          || Number(b.score || 0) - Number(a.score || 0);
      }
      return Number(b.score || 0) - Number(a.score || 0)
        || String(a.code || a.id).localeCompare(String(b.code || b.id), undefined, { numeric: true });
    });
    const documentNodes = [...baseDocumentNodes].sort((a, b) => {
      const aDoc = retrievedDocs.find((item) => (
        String(item.id) === String(a.doc_id)
        || Number(item.rank) === Number(a.rank)
        || `D_${item.rank}` === a.id
      ));
      const bDoc = retrievedDocs.find((item) => (
        String(item.id) === String(b.doc_id)
        || Number(item.rank) === Number(b.rank)
        || `D_${item.rank}` === b.id
      ));
      if (layoutMode === 'category') {
        const aGroup = problemCodeGroup(aDoc?.matched_problem_evidence?.[0]?.code);
        const bGroup = problemCodeGroup(bDoc?.matched_problem_evidence?.[0]?.code);
        return aGroup.localeCompare(bGroup, undefined, { numeric: true })
          || Number(aDoc?.rank || a.rank || 999) - Number(bDoc?.rank || b.rank || 999);
      }
      return Number(aDoc?.rank || a.rank || 999) - Number(bDoc?.rank || b.rank || 999)
        || Number(b.score || 0) - Number(a.score || 0);
    });
    const problemY = Object.fromEntries(problemNodes.map((node, index) => {
      const y = problemNodes.length <= 1 ? 340 : 132 + (index * (416 / Math.max(1, problemNodes.length - 1)));
      return [node.id, y];
    }));
    const docsWithAnchor = [];
    const docsWithoutProblem = [];

    documentNodes.forEach((doc) => {
      const linkedProblemIds = supportEdges
        .filter((edge) => edge.target === doc.id || edge.source === doc.id)
        .map((edge) => (edge.target === doc.id ? edge.source : edge.target))
        .filter((id) => problemY[id] !== undefined);
      if (!linkedProblemIds.length) {
        docsWithoutProblem.push(doc);
        return;
      }
      const primaryProblemId = linkedProblemIds.sort((a, b) => problemY[a] - problemY[b])[0];
      docsWithAnchor.push({
        ...doc,
        primaryProblemId,
        primaryProblemY: problemY[primaryProblemId] || 340,
        rankOrder: Number(doc.rank) || 999,
      });
    });

    const spreadY = (index, total) => {
      if (total <= 1) return 340;
      return 132 + (index * (416 / Math.max(1, total - 1)));
    };
    const positionedDocs = [];
    const sortedAnchoredDocs = [...docsWithAnchor].sort((a, b) => (
      Number(a.primaryProblemY) - Number(b.primaryProblemY)
      || (layoutMode === 'category'
        ? problemCodeGroup(a.primaryProblemId).localeCompare(problemCodeGroup(b.primaryProblemId), undefined, { numeric: true })
        : 0)
      || Number(a.rankOrder) - Number(b.rankOrder)
      || String(a.id).localeCompare(String(b.id))
    ));
    sortedAnchoredDocs.forEach((doc, index) => {
      positionedDocs.push({
        ...doc,
        px: 850,
        py: spreadY(index, sortedAnchoredDocs.length || 1),
        width: 230,
        height: 70,
      });
    });
    docsWithoutProblem
      .sort((a, b) => (Number(a.rank) || 999) - (Number(b.rank) || 999) || String(a.id).localeCompare(String(b.id)))
      .forEach((doc, index) => {
        const offsetIndex = sortedAnchoredDocs.length + index;
        const totalDocs = sortedAnchoredDocs.length + docsWithoutProblem.length;
        positionedDocs.push({ ...doc, px: 850, py: spreadY(offsetIndex, totalDocs || 1), width: 230, height: 70 });
      });

    const mapped = [
      ...queryNodes.map((node) => ({ ...node, px: 112, py: 340, width: 170, height: 66 })),
      ...problemNodes.map((node) => ({ ...node, px: 460, py: problemY[node.id] || 340, width: 230, height: 78 })),
      ...positionedDocs,
      ...otherNodes.map((node, index) => ({ ...node, px: 460, py: 96 + index * 84, width: 180, height: 68 })),
    ].map((node) => {
      const manual = manualPositions[node.id];
      return manual ? { ...node, px: manual.x, py: manual.y } : node;
    });
    return mapped;
  }, [edges, layoutMode, manualPositions, nodes, retrievedDocs]);

  const byId = Object.fromEntries(positionedNodes.map((node) => [node.id, node]));
  const fallbackNodeId = positionedNodes.find((node) => node.type !== 'query')?.id || positionedNodes[0]?.id;
  const activeNode = byId[selectedNodeId] || byId[fallbackNodeId] || positionedNodes[0];
  const queryNode = positionedNodes.find((node) => node.type === 'query');
  const activeEdge = edges.find((edge) => edge.target === activeNode?.id || edge.source === activeNode?.id);
  const hasProblemDocumentLinks = edges.some((edge) => edge.edge_type === 'problem-document');
  const visibleEdges = showLinks
    ? edges.filter((edge) => byId[edge.source] && byId[edge.target] && !(hasProblemDocumentLinks && edge.edge_type === 'query-document'))
    : [];
  const activeEdges = visibleEdges.filter((edge) => edge.source === activeNode?.id || edge.target === activeNode?.id || activeNode?.type === 'query');
  const averageDistance = positionedNodes.filter((node) => node.type !== 'query').reduce((sum, node) => sum + Number(node.semantic_distance_to_query || 0), 0) / Math.max(1, positionedNodes.filter((node) => node.type !== 'query').length);
  const activeDoc = activeNode?.type === 'document'
    ? retrievedDocs.find((doc) => (
      String(doc.id) === String(activeNode.doc_id)
      || Number(doc.rank) === Number(activeNode.rank)
      || `D_${doc.rank}` === activeNode.id
    ))
    : null;
  const activeProblem = activeNode?.type === 'problem'
    ? problems.find((problem) => String(problem.code) === String(activeNode.code || activeNode.id))
    : null;
  const linkedNodeIds = activeEdges
    .map((edge) => (edge.source === activeNode?.id ? edge.target : edge.source))
    .filter(Boolean);
  const linkedNodes = linkedNodeIds
    .map((id) => byId[id])
    .filter(Boolean);
  const nodeTitle = activeDoc?.title || activeProblem?.name || activeNode?.label || 'No node selected';
  const detailText = compactText(
    activeDoc?.content || activeDoc?.snippet || activeNode?.raw_text || activeProblem?.reasoning || activeNode?.explanation,
    activeDoc ? 980 : 520
  );
  const activeScore = activeDoc?.h2l_final_score ?? activeDoc?.score ?? activeProblem?.confidence ?? activeNode?.score;

  const edgeAnchor = (node, side) => {
    const x = side === 'source' ? node.px + node.width / 2 : node.px - node.width / 2;
    return { x, y: node.py };
  };

  const edgePath = (source, target) => {
    const sourceAnchor = edgeAnchor(source, 'source');
    const targetAnchor = edgeAnchor(target, 'target');
    const sourceX = sourceAnchor.x;
    const targetX = targetAnchor.x;
    const sourceY = sourceAnchor.y;
    const targetY = targetAnchor.y;
    const curve = sourceX < targetX ? 118 : -118;
    return `M ${sourceX} ${sourceY} C ${sourceX + curve} ${sourceY}, ${targetX - curve} ${targetY}, ${targetX} ${targetY}`;
  };

  const handleNodeFocus = (node, action = 'selected') => {
    onSelectNode?.(node.id);
    setInteractionNote(`${action} ${node.id}: ${node.label || node.type}`);
  };

  const pointFromEvent = (event) => {
    const point = event.currentTarget.createSVGPoint();
    const transform = event.currentTarget.getScreenCTM();
    if (!transform) return { x: SEMANTIC_MAP_WIDTH / 2, y: SEMANTIC_MAP_HEIGHT / 2 };
    point.x = event.clientX;
    point.y = event.clientY;
    return point.matrixTransform(transform.inverse());
  };

  const clampNodePosition = (node, point) => ({
    x: Math.max(node.width / 2 + 18, Math.min(SEMANTIC_MAP_WIDTH - node.width / 2 - 18, point.x)),
    y: Math.max(node.height / 2 + 18, Math.min(SEMANTIC_MAP_HEIGHT - node.height / 2 - 18, point.y)),
  });

  const handleNodeDragStart = (event, node) => {
    event.preventDefault();
    event.stopPropagation();
    setDragNodeId(node.id);
    handleNodeFocus(node, 'drag');
  };

  const handleMapPointerMove = (event) => {
    if (!dragNodeId) return;
    const node = byId[dragNodeId];
    if (!node) return;
    const point = pointFromEvent(event);
    setManualPositions((current) => ({ ...current, [dragNodeId]: clampNodePosition(node, point) }));
  };

  const draggedCount = Object.keys(manualPositions).length;
  const resetManualLayout = () => {
    setManualPositions({});
    setDragNodeId(null);
    setInteractionNote('คืนค่าแผนที่กลับสู่ layout มาตรฐานแล้ว');
  };

  const applyLayoutMode = (mode) => {
    setLayoutMode(mode);
    setManualPositions({});
    setInteractionNote(mode === 'category'
      ? 'จัดเรียงแผนที่ตามกลุ่มรหัสแล้ว'
      : 'จัดเรียงแผนที่ตามผลลัพธ์แล้ว');
  };

  return (
    <div className="overflow-hidden rounded-xl border border-outline-variant/25 bg-surface-container-lowest shadow-sm">
      <div className="border-b border-outline-variant/20 bg-surface-container-low p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-widest text-teal-700">Semantic Evidence Map</div>
            <h3 className="mt-1 font-headline text-xl font-extrabold text-on-surface">Case Meaning Network</h3>
            <p className="mt-1 text-sm leading-relaxed text-on-surface-variant">แผนที่ความสัมพันธ์ระหว่างข้อความเคส รหัสปัญหา และเอกสาร evidence จาก runtime embedding จริง</p>
          </div>
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div className="rounded bg-surface-container-lowest px-3 py-2"><span className="block font-bold text-on-surface">{nodes.length}</span><span className="text-on-surface-variant">nodes</span></div>
            <div className="rounded bg-surface-container-lowest px-3 py-2"><span className="block font-bold text-on-surface">{edges.length}</span><span className="text-on-surface-variant">links</span></div>
            <div className="rounded bg-surface-container-lowest px-3 py-2"><span className="block font-bold text-on-surface">{formatNumber(averageDistance, 2)}</span><span className="text-on-surface-variant">avg d</span></div>
          </div>
        </div>
      </div>
      <div className="p-5">
        <div className="mb-4 flex flex-wrap gap-2 text-xs">
          <button aria-pressed={showZones} className={`min-h-11 rounded-lg px-3 py-2 font-semibold ${showZones ? 'bg-teal-600 text-white' : 'bg-surface-container-high text-on-surface'}`} onClick={() => setShowZones((value) => !value)} type="button">Radius Zones</button>
          <button aria-pressed={showLinks} className={`min-h-11 rounded-lg px-3 py-2 font-semibold ${showLinks ? 'bg-teal-600 text-white' : 'bg-surface-container-high text-on-surface'}`} onClick={() => setShowLinks((value) => !value)} type="button">Semantic Links</button>
          <button aria-pressed={showSignal} className={`min-h-11 rounded-lg px-3 py-2 font-semibold ${showSignal ? 'bg-teal-600 text-white' : 'bg-surface-container-high text-on-surface'}`} onClick={() => setShowSignal((value) => !value)} type="button">Live Signal</button>
          <button aria-pressed={showLabels} className={`min-h-11 rounded-lg px-3 py-2 font-semibold ${showLabels ? 'bg-teal-600 text-white' : 'bg-surface-container-high text-on-surface'}`} onClick={() => setShowLabels((value) => !value)} type="button">Labels</button>
          <button aria-pressed={layoutMode === 'result'} className={`min-h-11 rounded-lg px-3 py-2 font-semibold ${layoutMode === 'result' ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-950' : 'bg-surface-container-high text-on-surface'}`} onClick={() => applyLayoutMode('result')} type="button">Layout: Result</button>
          <button aria-pressed={layoutMode === 'category'} className={`min-h-11 rounded-lg px-3 py-2 font-semibold ${layoutMode === 'category' ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-950' : 'bg-surface-container-high text-on-surface'}`} onClick={() => applyLayoutMode('category')} type="button">Layout: Category</button>
          <button className="min-h-11 rounded-lg bg-surface-container-high px-3 py-2 font-semibold text-on-surface transition-colors hover:bg-surface-container-highest" onClick={resetManualLayout} type="button">Reset Layout</button>
        </div>
        <p className="mb-3 text-xs font-semibold text-on-surface-variant">
          ลาก query/problem/evidence node เพื่อจัดตำแหน่งใหม่ได้ เมื่อ node ทับเส้นหรือข้อมูลสำคัญ
          {draggedCount ? ` ตอนนี้มี ${draggedCount} node ที่ถูกย้ายจากตำแหน่งมาตรฐาน` : ' ตอนนี้แผนที่ยังอยู่ในตำแหน่งมาตรฐาน'}
        </p>
        <svg
          className={`semantic-map h-[680px] w-full select-none overflow-hidden rounded-xl border border-outline-variant/25 bg-surface-container-low ${dragNodeId ? 'cursor-grabbing' : ''}`}
          data-testid="vector-space-scene"
          onPointerLeave={() => setDragNodeId(null)}
          onPointerMove={handleMapPointerMove}
          onPointerUp={() => setDragNodeId(null)}
          viewBox={`0 0 ${SEMANTIC_MAP_WIDTH} ${SEMANTIC_MAP_HEIGHT}`}
        >
          <defs>
            <marker id="semantic-arrow-teal" markerHeight="6" markerWidth="6" orient="auto" refX="5" refY="3"><polygon fill="#14b8a6" points="0 0, 6 3, 0 6" /></marker>
            <marker id="semantic-arrow-sky" markerHeight="6" markerWidth="6" orient="auto" refX="5" refY="3"><polygon fill="#38bdf8" points="0 0, 6 3, 0 6" /></marker>
            <marker id="semantic-arrow-violet" markerHeight="6" markerWidth="6" orient="auto" refX="5" refY="3"><polygon fill="#a78bfa" points="0 0, 6 3, 0 6" /></marker>
          </defs>
          {showZones && (
            <g opacity="0.95">
              <rect fill="#ccfbf1" height="540" opacity="0.14" rx="8" width="282" x="318" y="70" />
              <rect fill="#e0f2fe" height="540" opacity="0.16" rx="8" width="276" x="708" y="70" />
              <rect fill="none" height="540" rx="8" stroke="#14b8a6" strokeDasharray="7 8" strokeOpacity="0.28" width="282" x="318" y="70" />
              <rect fill="none" height="540" rx="8" stroke="#38bdf8" strokeDasharray="7 8" strokeOpacity="0.28" width="276" x="708" y="70" />
              <text fill="#0f766e" fontSize="12" fontWeight="700" x="54" y="58">query</text>
              <text fill="#0f766e" fontSize="12" fontWeight="700" x="402" y="58">problems</text>
              <text fill="#0369a1" fontSize="12" fontWeight="700" x="772" y="58">supporting docs</text>
            </g>
          )}
          {visibleEdges.map((edge, index) => {
            const source = byId[edge.source];
            const target = byId[edge.target];
            const path = edgePath(source, target);
            const isActive = activeEdges.includes(edge);
            const markerId = edge.edge_type === 'query-document' ? 'url(#semantic-arrow-sky)' : edge.edge_type === 'problem-document' ? 'url(#semantic-arrow-violet)' : 'url(#semantic-arrow-teal)';
            return (
              <g key={`${edge.source}-${edge.target}-${edge.edge_type}`}>
                <path className={showSignal && isActive ? 'semantic-edge semantic-edge-active' : 'semantic-edge'} d={path} fill="none" markerEnd={markerId} stroke={edgeColor(edge)} strokeOpacity={isActive ? 0.85 : 0.28} strokeWidth={isActive ? 2.6 : 1.5} />
                {showSignal && isActive && (
                  <circle className="semantic-packet" fill={edgeColor(edge)} r="4">
                    <animateMotion begin={`${index * 0.18}s`} dur="2.2s" path={path} repeatCount="indefinite" />
                  </circle>
                )}
              </g>
            );
          })}
          {positionedNodes.map((node) => {
            const tone = nodeTone(node);
            const isActive = node.id === activeNode?.id;
            const scoreWidth = Math.max(16, Math.min(node.width - 24, Number(node.score || 0) * (node.width - 24)));
            const distance = node.semantic_distance_to_query ?? 0;
            return (
              <g
                aria-label={`${node.id} ${node.label || node.type || ''} score ${formatNumber(node.score, 2)}`}
                className="semantic-node"
                data-vector-node={node.id}
                key={node.id}
                onClick={() => handleNodeFocus(node)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    handleNodeFocus(node, 'keyboard');
                  }
                }}
                onPointerDown={(event) => handleNodeDragStart(event, node)}
                onPointerEnter={() => !dragNodeId && handleNodeFocus(node, 'hover')}
                role="button"
                tabIndex="0"
              >
                <rect fill={tone.fill} height={node.height} rx="8" stroke={tone.stroke} strokeOpacity={isActive ? 1 : 0.55} strokeWidth={isActive ? 2.5 : 1.4} width={node.width} x={node.px - node.width / 2} y={node.py - node.height / 2} />
                <rect fill={tone.stroke} height="5" opacity="0.9" rx="2" width={scoreWidth} x={node.px - node.width / 2 + 12} y={node.py + node.height / 2 - 13} />
                <text fill={tone.text} fontSize="13" fontWeight="800" x={node.px - node.width / 2 + 12} y={node.py - 12}>{node.id}</text>
                {showLabels && (
                  <text fill={tone.text} fontSize="10" fontWeight="600" x={node.px - node.width / 2 + 12} y={node.py + 7}>
                    {(node.label || node.type || '').slice(0, 34)}
                  </text>
                )}
                <text fill={tone.text} fontSize="9" fontWeight="700" opacity="0.72" x={node.px - node.width / 2 + 12} y={node.py + 24}>{node.type === 'query' ? 'case query' : `d=${formatNumber(distance, 2)} score=${formatNumber(node.score, 2)}`}</text>
                {isActive && <rect fill="none" height={node.height + 10} rx="10" stroke="#14b8a6" strokeDasharray="4 4" strokeWidth="1.5" width={node.width + 10} x={node.px - node.width / 2 - 5} y={node.py - node.height / 2 - 5} />}
              </g>
            );
          })}
        </svg>
        <div className="mt-4 grid gap-3 lg:grid-cols-[0.9fr_1.2fr]">
          <div className="semantic-detail-panel max-h-[260px] overflow-y-auto rounded-xl bg-surface-container-low p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Selected Node</div>
            <h4 className="mt-1 flex items-center gap-2 font-headline text-lg font-bold text-on-surface">
              {prettyNodeId(activeNode?.id) || 'N/A'}
              {activeNode && <span className="rounded bg-surface-container-high px-2 py-0.5 text-[10px] font-bold uppercase text-on-surface-variant">{nodeTypeLabel(activeNode.type)}</span>}
            </h4>
            <p className="mt-2 text-sm font-semibold leading-relaxed text-on-surface">{nodeTitle}</p>
            <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">{interactionNote}</p>
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
              <span className="rounded bg-surface-container-lowest p-2">score <strong>{formatNumber(activeScore, 3)}</strong></span>
              <span className="rounded bg-surface-container-lowest p-2">distance <strong>{formatNumber(activeNode?.semantic_distance_to_query, 3)}</strong></span>
              <span className="rounded bg-surface-container-lowest p-2">severity <strong>{activeNode?.severity || 'N/A'}</strong></span>
              <span className="rounded bg-surface-container-lowest p-2">links <strong>{activeEdges.length}</strong></span>
            </div>
          </div>
          <div className="semantic-detail-panel max-h-[360px] overflow-y-auto rounded-xl bg-surface-container-low p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Interpretation</div>
            <p className="mt-2 border-l-2 border-teal-500 bg-surface-container-lowest px-3 py-2 text-sm leading-relaxed text-on-surface-variant">
              <strong className="text-on-surface">{prettyNodeId(activeNode?.id)}</strong>: {vectorInterpretation(activeNode, queryNode, activeEdge)}
            </p>
            {activeNode?.type === 'document' && (
              <div className="mt-3 space-y-3">
                <div className="grid gap-2 sm:grid-cols-3">
                  <div className="rounded-lg bg-surface-container-lowest p-3">
                    <div className="text-[10px] font-bold uppercase tracking-widest text-sky-700 dark:text-sky-300">Document</div>
                    <div className="mt-1 text-sm font-bold text-on-surface">Rank {activeDoc?.rank ?? activeNode.rank ?? 'N/A'}</div>
                    <div className="mt-1 text-xs text-on-surface-variant">{activeDoc?.source || activeNode.source || 'ไม่พบ source'}</div>
                  </div>
                  <div className="rounded-lg bg-surface-container-lowest p-3">
                    <div className="text-[10px] font-bold uppercase tracking-widest text-teal-700 dark:text-teal-300">Retrieval</div>
                    <div className="mt-1 text-sm font-bold text-on-surface">H2L {formatNumber(activeDoc?.h2l_final_score ?? activeNode.score, 3)}</div>
                    <div className="mt-1 text-xs text-on-surface-variant">base {formatNumber(activeDoc?.base_score, 3)} · rerank {formatNumber(activeDoc?.rerank_score, 3)}</div>
                  </div>
                  <div className="rounded-lg bg-surface-container-lowest p-3">
                    <div className="text-[10px] font-bold uppercase tracking-widest text-violet-700 dark:text-violet-300">Semantic</div>
                    <div className="mt-1 text-sm font-bold text-on-surface">d={formatNumber(activeNode?.semantic_distance_to_query, 3)}</div>
                    <div className="mt-1 text-xs text-on-surface-variant">ยิ่งต่ำยิ่งใกล้เคส</div>
                  </div>
                </div>
                <section className="rounded-lg bg-surface-container-lowest p-3">
                  <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Supported Problems</div>
                  {(activeDoc?.matched_problem_evidence || []).length ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {activeDoc.matched_problem_evidence.map((item) => (
                        <span className="rounded bg-teal-50 px-2 py-1 text-xs font-bold text-teal-800 dark:bg-teal-950/40 dark:text-teal-100" key={`${activeDoc.id}-${item.code}`}>
                          {item.code} · {(item.matched_keywords || item.matched_name_terms || []).slice(0, 3).join(', ') || item.name}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">ยังไม่พบ keyword evidence ที่ผูกกับ problem code โดยตรง ต้องอ่านเนื้อหาเอกสารร่วมกับ score</p>
                  )}
                </section>
                <section className="rounded-lg bg-surface-container-lowest p-3">
                  <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Document Text</div>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-on-surface-variant">{detailText || 'ไม่มีข้อความเอกสารให้แสดง'}</p>
                </section>
              </div>
            )}
            {activeNode?.type === 'problem' && (
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg bg-surface-container-lowest p-3">
                  <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Detector Evidence</div>
                  <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">{activeProblem?.reasoning || activeNode.explanation || 'ไม่มีคำอธิบายเพิ่มเติม'}</p>
                </div>
                <div className="rounded-lg bg-surface-container-lowest p-3">
                  <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Matched Keywords</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {(activeProblem?.matched_keywords || []).length
                      ? activeProblem.matched_keywords.map((keyword) => <span className="rounded bg-teal-50 px-2 py-1 text-xs font-bold text-teal-800 dark:bg-teal-950/40 dark:text-teal-100" key={keyword}>{keyword}</span>)
                      : <span className="text-xs text-on-surface-variant">ไม่พบ keyword ที่ส่งมาจาก detector</span>}
                  </div>
                </div>
              </div>
            )}
            {activeNode?.type === 'query' && (
              <section className="mt-3 rounded-lg bg-surface-container-lowest p-3">
                <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Case Text</div>
                <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">{activeNode.raw_text || activeNode.label}</p>
              </section>
            )}
            {!!linkedNodes.length && (
              <div className="mt-3 rounded-lg bg-surface-container-lowest p-3">
                <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Linked Nodes</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {linkedNodes.map((node) => <span className="rounded bg-surface-container-high px-2 py-1 text-xs font-bold text-on-surface" key={node.id}>{prettyNodeId(node.id)} · {nodeTypeLabel(node.type)}</span>)}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function VectorTab({ displayResult }) {
  const vector = displayResult.vector_space || {};
  const nodes = vector.nodes || [];
  const edges = vector.edges || [];
  const [selectedNodeId, setSelectedNodeId] = useState('');
  const [nodeListSortMode, setNodeListSortMode] = useState('result');
  const [nodeGroupState, setNodeGroupState] = useState({ scope: '', groups: {} });
  const sortedNodeList = [...nodes].sort((a, b) => {
    const typeOrder = { query: 0, problem: 1, document: 2 };
    const aType = typeOrder[a.type] ?? 9;
    const bType = typeOrder[b.type] ?? 9;
    if (aType !== bType) return aType - bType;

    if (a.type === 'problem' && b.type === 'problem') {
      if (nodeListSortMode === 'category') {
        return problemCodeGroup(a.code || a.id).localeCompare(problemCodeGroup(b.code || b.id), undefined, { numeric: true })
          || String(a.code || a.id).localeCompare(String(b.code || b.id), undefined, { numeric: true })
          || Number(b.score || 0) - Number(a.score || 0);
      }
      return Number(b.score || 0) - Number(a.score || 0)
        || String(a.code || a.id).localeCompare(String(b.code || b.id), undefined, { numeric: true });
    }

    if (a.type === 'document' && b.type === 'document') {
      const aDoc = (displayResult.retrieved_docs || []).find((item) => (
        String(item.id) === String(a.doc_id)
        || Number(item.rank) === Number(a.rank)
        || `D_${item.rank}` === a.id
      ));
      const bDoc = (displayResult.retrieved_docs || []).find((item) => (
        String(item.id) === String(b.doc_id)
        || Number(item.rank) === Number(b.rank)
        || `D_${item.rank}` === b.id
      ));
      if (nodeListSortMode === 'category') {
        const aGroup = problemCodeGroup(aDoc?.matched_problem_evidence?.[0]?.code);
        const bGroup = problemCodeGroup(bDoc?.matched_problem_evidence?.[0]?.code);
        return aGroup.localeCompare(bGroup, undefined, { numeric: true })
          || Number(aDoc?.rank || a.rank || 999) - Number(bDoc?.rank || b.rank || 999);
      }
      return Number(aDoc?.rank || a.rank || 999) - Number(bDoc?.rank || b.rank || 999)
        || Number(b.score || 0) - Number(a.score || 0);
    }

    return String(a.id).localeCompare(String(b.id), undefined, { numeric: true });
  });
  const vectorCaseKey = `${displayResult.case_id || 'no-case'}::${displayResult.case_description || ''}::${nodes.length}`;
  const nodeGroups = useMemo(() => {
    const grouped = new Map();
    sortedNodeList.forEach((node) => {
      let key = 'query';
      let label = 'Case Query';
      if (node.type === 'problem') {
        const group = problemCodeGroup(node.code || node.id);
        key = `problem:${group}`;
        label = `Problem Group ${problemCodeGroupLabel(group)}`;
      } else if (node.type === 'document') {
        const doc = (displayResult.retrieved_docs || []).find((item) => (
          String(item.id) === String(node.doc_id)
          || Number(item.rank) === Number(node.rank)
          || `D_${item.rank}` === node.id
        ));
        const group = problemCodeGroup(doc?.matched_problem_evidence?.[0]?.code);
        key = `document:${group}`;
        label = `Evidence Group ${problemCodeGroupLabel(group)}`;
      }
      if (!grouped.has(key)) grouped.set(key, { key, label, items: [] });
      grouped.get(key).items.push(node);
    });
    return Array.from(grouped.values());
  }, [displayResult.retrieved_docs, sortedNodeList]);
  const activeListNodeId = sortedNodeList.some((node) => node.id === selectedNodeId)
    ? selectedNodeId
    : (sortedNodeList.find((node) => node.type !== 'query')?.id || sortedNodeList[0]?.id || '');
  const nodeGroupScope = `${vectorCaseKey}::${nodeListSortMode}`;
  const collapsedNodeGroups = nodeGroupState.scope === nodeGroupScope ? nodeGroupState.groups : {};

  const toggleNodeGroup = (groupKey) => {
    setNodeGroupState((current) => {
      const groups = current.scope === nodeGroupScope ? current.groups : {};
      return { scope: nodeGroupScope, groups: { ...groups, [groupKey]: !groups[groupKey] } };
    });
  };

  const setAllNodeGroups = (collapsed) => {
    const next = {};
    nodeGroups.forEach(({ key }) => {
      next[key] = collapsed;
    });
    setNodeGroupState({ scope: nodeGroupScope, groups: next });
  };

  const renderNodeButton = (node) => {
    const isActive = node.id === activeListNodeId;
    const doc = node.type === 'document'
      ? (displayResult.retrieved_docs || []).find((item) => (
        String(item.id) === String(node.doc_id)
        || Number(item.rank) === Number(node.rank)
        || `D_${item.rank}` === node.id
      ))
      : null;
    return (
      <button
        className={`w-full rounded border p-3 text-left text-sm transition-all ${isActive ? 'border-teal-500 bg-teal-50 text-teal-950 ring-2 ring-teal-600/15 dark:bg-teal-950/40 dark:text-teal-100' : 'border-transparent bg-surface-container-low text-on-surface hover:border-teal-500/30 hover:bg-surface-container'}`}
        key={node.id}
        onClick={() => setSelectedNodeId(node.id)}
        type="button"
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <span className="font-bold text-on-surface">{prettyNodeId(node.id)}</span>
            {node.type !== 'query' && (
              <span className="rounded bg-surface-container-high px-2 py-0.5 text-[10px] font-bold uppercase text-on-surface-variant">
                {node.type === 'document' ? `group ${problemCodeGroup(doc?.matched_problem_evidence?.[0]?.code)}` : `group ${problemCodeGroup(node.code || node.id)}`}
              </span>
            )}
          </div>
          <StatusBadge label={nodeTypeLabel(node.type)} tone={node.type === 'query' ? 'neutral' : 'live'} />
        </div>
        <p className="mt-1 text-xs leading-relaxed text-on-surface-variant">{doc?.title || node.label}</p>
        <p className="mt-1 text-xs text-on-surface">distance {formatNumber(node.semantic_distance_to_query, 3)}</p>
        {isActive && node.type === 'document' && (
          <div className="mt-3 rounded-lg bg-surface-container-lowest p-3 text-xs leading-relaxed text-on-surface-variant">
            <div className="font-bold text-on-surface">Doc {doc?.rank ?? node.rank ?? prettyNodeId(node.id)} · {doc?.source || node.source || 'source N/A'}</div>
            <p className="mt-1">{compactText(doc?.snippet || node.raw_text, 180) || 'ไม่มี preview'}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <span className="rounded bg-surface-container-high px-2 py-1 font-bold text-on-surface">score {formatNumber(doc?.h2l_final_score ?? node.score, 3)}</span>
              <span className="rounded bg-surface-container-high px-2 py-1 font-bold text-on-surface">support {(doc?.matched_problem_evidence || []).length}</span>
            </div>
          </div>
        )}
      </button>
    );
  };

  return (
    <section className="rounded-xl bg-surface-container-low p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-headline text-lg font-bold">Semantic Evidence Map</h2>
          <p className="mt-1 text-sm text-on-surface-variant">{vector.note || 'Projection appears after runtime retrieval.'}</p>
          <p className="mt-1 text-xs leading-relaxed text-on-surface-variant">ต่างจาก Problem-Document Matrix ที่เน้นความหนาแน่นของการรองรับ ส่วนแผนที่นี้ใช้สำหรับดู semantic distance, linked nodes และรายละเอียดเชิงลึกของหลักฐาน</p>
        </div>
        <StatusBadge label={vector.projection || 'not-generated'} tone={vector.embedding_status === 'ready' ? 'live' : vector.embedding_status === 'error' ? 'error' : 'warning'} />
      </div>
      <div className="mt-6 grid grid-cols-12 gap-6">
        <div className="col-span-12">
          {nodes.length ? <VectorScene edges={edges} nodes={nodes} onSelectNode={setSelectedNodeId} problems={displayResult.problems || []} retrievedDocs={displayResult.retrieved_docs || []} selectedNodeId={activeListNodeId} /> : (
            <div className="rounded-xl bg-surface-container-lowest p-8 text-sm text-on-surface-variant">ยังไม่มี semantic map จาก embedding จริง ตรวจ runtime status ของ embedding_model/vector_index แล้วรันวิเคราะห์ใหม่</div>
          )}
        </div>
        <div className="col-span-12 grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
          <div className="space-y-4">
            <div className="rounded-xl bg-surface-container-lowest p-5">
            <h3 className="font-headline text-lg font-bold">How to Read This Map</h3>
            <div className="mt-3 space-y-3 text-sm leading-relaxed text-on-surface-variant">
              <p><strong className="text-on-surface">query:</strong> เคสจริงที่กำลังวิเคราะห์ เป็นจุดเริ่มต้นทางซ้ายของแผนที่</p>
              <p><strong className="text-on-surface">problems:</strong> รหัสปัญหาที่ระบบคิดว่าเกี่ยวข้องกับเคส ยิ่ง score สูงยิ่งมั่นใจว่ารหัสนั้นควรพิจารณา</p>
              <p><strong className="text-on-surface">supporting docs:</strong> เอกสารที่ดึงมาเพื่อช่วยอธิบายหรือรองรับ problem นั้น ๆ ไม่ใช่คำตอบสุดท้าย แต่เป็นหลักฐานประกอบ</p>
              <p><strong className="text-on-surface">distance:</strong> ระยะความหมายจากเคส ยิ่งต่ำยิ่งใกล้บริบทของเคส แต่ต้องอ่านคู่กับ score และเส้น support</p>
              <p><strong className="text-on-surface">score bar:</strong> แถบใน node คือคะแนนจริงจาก runtime เช่น confidence ของ problem หรือ retrieval/H2L score ของ doc</p>
              <p><strong className="text-on-surface">live signal:</strong> จุดวิ่งบนเส้นช่วยบอก path ที่กำลังเลือกอ่าน ไม่ได้เป็นคะแนนใหม่</p>
            </div>
            <div className="mt-4 rounded-lg bg-surface-container-low p-3 text-xs leading-relaxed text-on-surface">
              อ่านแบบง่าย: ถ้า query เชื่อมไป problem แล้ว problem เชื่อมต่อไปยัง doc ที่ score ดี แปลว่ารหัสปัญหานั้นมีหลักฐาน retrieval รองรับมากขึ้น
            </div>
            </div>
            <div className="rounded-xl bg-surface-container-lowest p-5">
              <h3 className="font-headline font-bold">Legend</h3>
              <div className="mt-3 space-y-2 text-sm">
                {(vector.legend || [
                  { edge_type: 'query-problem', label: 'ข้อความเคส ↔ รหัสปัญหา' },
                  { edge_type: 'query-document', label: 'ข้อความเคส ↔ เอกสารหลักฐาน' },
                  { edge_type: 'problem-document', label: 'รหัสปัญหา ↔ เอกสารหลักฐาน' },
                ]).map((item) => (
                  <div key={item.edge_type} className="flex items-center gap-2 text-on-surface-variant">
                    <span className={`h-2 w-8 rounded ${item.edge_type === 'query-document' ? 'bg-sky-400' : item.edge_type === 'problem-document' ? 'bg-violet-400' : 'bg-teal-300'}`} />
                    {item.label}
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="rounded-xl bg-surface-container-lowest p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-headline font-bold">Node List</h3>
                <p className="mt-1 text-xs text-on-surface-variant">ค่าเริ่มต้นเรียงตามลำดับผลลัพธ์ และสลับเป็นตามกลุ่มรหัสได้</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge label={activeListNodeId || 'none'} tone={activeListNodeId ? 'live' : 'neutral'} />
                <button
                  className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-colors ${nodeListSortMode === 'result' ? 'bg-teal-600 text-white' : 'bg-surface-container-low text-on-surface hover:bg-surface-container'}`}
                  onClick={() => setNodeListSortMode('result')}
                  type="button"
                >
                  ตามผลลัพธ์
                </button>
                <button
                  className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-colors ${nodeListSortMode === 'category' ? 'bg-teal-600 text-white' : 'bg-surface-container-low text-on-surface hover:bg-surface-container'}`}
                  onClick={() => setNodeListSortMode('category')}
                  type="button"
                >
                  ตามกลุ่มรหัส
                </button>
                {nodeListSortMode === 'category' && nodeGroups.length > 1 && (
                  <>
                    <button
                      className="rounded-lg bg-surface-container-low px-3 py-1.5 text-xs font-bold text-on-surface transition-colors hover:bg-surface-container"
                      onClick={() => setAllNodeGroups(false)}
                      type="button"
                    >
                      ขยายทั้งหมด
                    </button>
                    <button
                      className="rounded-lg bg-surface-container-low px-3 py-1.5 text-xs font-bold text-on-surface transition-colors hover:bg-surface-container"
                      onClick={() => setAllNodeGroups(true)}
                      type="button"
                    >
                      ย่อทั้งหมด
                    </button>
                  </>
                )}
              </div>
            </div>
            {nodeListSortMode === 'category' ? (
              <div className="mt-3 space-y-3">
                {nodeGroups.map((group) => {
                  const isCollapsed = collapsedNodeGroups[group.key];
                  return (
                    <section key={group.key} className="rounded-xl bg-surface-container-low p-3">
                      <button
                        className="flex w-full items-center justify-between gap-3 text-left"
                        onClick={() => toggleNodeGroup(group.key)}
                        type="button"
                      >
                        <div>
                          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Node Group</div>
                          <h4 className="mt-1 font-headline text-sm font-bold text-on-surface">{group.label}</h4>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="rounded-lg bg-surface-container-lowest px-2.5 py-1 text-[11px] font-bold text-on-surface">{group.items.length} nodes</span>
                          <span aria-hidden="true" className="material-symbols-outlined text-on-surface-variant">{isCollapsed ? 'expand_more' : 'expand_less'}</span>
                        </div>
                      </button>
                      {!isCollapsed && <div className="mt-3 space-y-2">{group.items.map(renderNodeButton)}</div>}
                    </section>
                  );
                })}
              </div>
            ) : (
              <div className="mt-3 space-y-2">
                {sortedNodeList.map(renderNodeButton)}
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function PipelineTab({ displayResult, runtimeStatus }) {
  const flow = displayResult.detection_flow || {};
  const info = displayResult.detection_info || {};
  const steps = flow.steps || [];
  const runtime = displayResult.runtime_status || runtimeStatus || {};
  const hasResult = steps.length > 0;
  const [expandedStep, setExpandedStep] = React.useState(null);
  const [animPhase, setAnimPhase] = React.useState(0);
  const [replayKey, setReplayKey] = React.useState(0);
  const [l1Panel, setL1Panel] = React.useState('accepted');
  const [l1FocusKey, setL1FocusKey] = React.useState(null);

  React.useEffect(() => {
    if (!hasResult) { setAnimPhase(0); return; }
    let phase = 0;
    const interval = setInterval(() => { phase += 1; setAnimPhase(phase); if (phase >= 6) clearInterval(interval); }, 350);
    return () => clearInterval(interval);
  }, [hasResult, steps.length, replayKey]);

  const problems = displayResult.problems || [];
  const filtered = displayResult.filtered_out || [];
  const caseDesc = displayResult.case_description || '';
  const sentenceProfile = displayResult.sentence_profile || {};
  const keywordAnalysis = displayResult.keyword_analysis || {};
  const phaseTimings = flow.phase_timings_ms || displayResult.phase_timings_ms || {};
  const l1Total = (info.l1_count || 0) + (info.filtered_count || 0);
  const filteredCount = info.filtered_count ?? flow.filtered_count ?? 0;
  const ambiguitySummary = info.ambiguity_summary || flow.ambiguity_summary || {};
  const reviewLoadCount = Number(
    ambiguitySummary.count ??
    ambiguitySummary.review_count ??
    Object.keys(info.conflicts || {}).length,
  ) || 0;
  const reviewLoadLevel = ambiguitySummary.level || (reviewLoadCount ? 'medium' : 'low');
  const reviewLoadToneClass = reviewLoadLevel === 'high'
    ? 'text-red-700 dark:text-red-300'
    : reviewLoadLevel === 'medium'
      ? 'text-yellow-700 dark:text-yellow-300'
      : 'text-teal-700 dark:text-teal-300';
  const reviewLoadTone = reviewLoadLevel === 'high' || reviewLoadLevel === 'medium' ? 'warning' : 'teal';
  const reviewLoadHint = ambiguitySummary.interpretation
    || (reviewLoadCount ? `${reviewLoadCount} candidate ต้องทบทวนเพิ่ม` : 'ไม่พบสัญญาณกำกวมที่ต้องทบทวนเพิ่ม');
  const retrievedDocsCount = displayResult.retrieved_docs_count ?? 0;
  const totalRuntimeMs = phaseTimings.total ?? ((displayResult.execution_time || 0) * 1000);
  const retrievalMs = phaseTimings.retrieval ?? 0;
  const formatProblemLabel = (problem) => `[${problem.code}] ${problem.name || problem.category || 'ไม่ระบุชื่อปัญหา'}`;
  const acceptedKeywordRows = [...(keywordAnalysis.rows || [])].sort((a, b) => Number(b.confidence || 0) - Number(a.confidence || 0));
  const filteredKeywordRows = [...(keywordAnalysis.filtered_out || filtered || [])].sort((a, b) => Number(b.confidence || 0) - Number(a.confidence || 0));
  const rawL2Status = steps[2]?.status || (info.l2_applied ? 'complete' : info.l2_requested ? 'not-run' : 'skipped');
  const l2NotTriggered = rawL2Status === 'not-run' && info.l2_requested;
  const keywordPool = (() => {
    const counts = new Map();
    [...acceptedKeywordRows, ...filteredKeywordRows].forEach((item) => {
      const keywords = item.keywords || item.matched_keywords || [];
      keywords.forEach((keyword) => {
        if (!keyword) return;
        counts.set(keyword, (counts.get(keyword) || 0) + 1);
      });
    });
    return Array.from(counts.entries())
      .map(([keyword, count]) => ({ keyword, count }))
      .sort((a, b) => b.count - a.count || b.keyword.length - a.keyword.length);
  })();

  const pipeSteps = hasResult ? [
    {
      key: 'case-input',
      icon: 'inbox',
      eyebrow: 'ingest',
      label: 'Case Input',
      count: 1,
      status: 'complete',
      tone: 'teal',
      durationMs: phaseTimings.case_input ?? steps[0]?.duration_ms ?? 0,
      detail: 'รับข้อความเคสจริงเข้าสู่ runtime และเตรียมข้อมูลก่อนเริ่ม detector',
      sub: `"${compactText(caseDesc, 140)}"`,
    },
    {
      key: 'l1',
      icon: 'manage_search',
      eyebrow: 'detect',
      label: 'L1 Keyword Detection',
      count: l1Total,
      status: 'complete',
      tone: 'sky',
      durationMs: phaseTimings.l1 ?? steps[1]?.duration_ms ?? 0,
      detail: `Keyword matching จับ candidate ได้ ${l1Total} รายการ และแยก accepted/filtered จาก evidence เชิงคำ`,
      sub: problems.map(formatProblemLabel).join(', ') || 'ยังไม่มี accepted candidate',
    },
    {
      key: 'l2',
      icon: rawL2Status === 'complete' ? 'auto_awesome' : rawL2Status === 'not-run' ? 'pause_circle' : 'skip_next',
      eyebrow: rawL2Status === 'complete' ? 'validate' : l2NotTriggered ? 'idle' : 'baseline',
      label: rawL2Status === 'complete' ? 'L2 Semantic Validation' : l2NotTriggered ? 'L2 Not Triggered' : 'L2 Skipped (Baseline)',
      count: info.l2_applied ? info.l2_count || 0 : 'skip',
      status: rawL2Status === 'complete' ? 'complete' : 'skipped',
      tone: rawL2Status === 'complete' ? 'violet' : 'slate',
      durationMs: phaseTimings.l2 ?? steps[2]?.duration_ms ?? 0,
      detail: rawL2Status === 'complete'
        ? `Semantic/context gate ตรวจต่อจาก L1 และคัดออก ${filteredCount} รายการ`
        : l2NotTriggered
          ? 'รอบนี้ไม่พบ conflict หรือ candidate ที่ต้อง escalate ไปยัง L2 จึงจบที่ L1'
          : 'Baseline mode จงใจไม่ใช้ L2 semantic validation',
      sub: filtered.length ? `Filtered: ${filtered.map(formatProblemLabel).join(', ')}` : l2NotTriggered ? 'ไม่มีรายการที่ต้องส่งต่อให้ L2 ตรวจเพิ่ม' : 'ไม่มีรายการที่ถูกคัดออก',
    },
    {
      key: 'final',
      icon: 'verified',
      eyebrow: 'output',
      label: 'Final Problems',
      count: problems.length,
      status: 'complete',
      tone: 'emerald',
      durationMs: phaseTimings.finalize ?? steps[3]?.duration_ms ?? 0,
      detail: `สรุป problem codes สุดท้าย ${problems.length} รายการ พร้อมส่งต่อไปยัง retrieval และ visualization`,
      sub: problems.map(formatProblemLabel).join(', ') || 'ไม่พบปัญหา',
    },
  ] : [
    { key: 'case-input', icon: 'inbox', eyebrow: 'ingest', label: 'Case Input', count: '—', status: 'waiting', tone: 'teal', durationMs: 0 },
    { key: 'l1', icon: 'manage_search', eyebrow: 'detect', label: 'L1 Keyword Detection', count: '—', status: 'waiting', tone: 'sky', durationMs: 0 },
    { key: 'l2', icon: 'auto_awesome', eyebrow: 'validate', label: 'L2 Semantic Validation', count: '—', status: 'waiting', tone: 'violet', durationMs: 0 },
    { key: 'final', icon: 'verified', eyebrow: 'output', label: 'Final Problems', count: '—', status: 'waiting', tone: 'emerald', durationMs: 0 },
  ];
  const activeStageCount = hasResult ? Math.min(pipeSteps.length, animPhase) : 0;
  const pipelineProgress = hasResult ? Math.max(0, Math.min(100, ((activeStageCount - 1) / Math.max(1, pipeSteps.length - 1)) * 100)) : 0;
  const selectedStepIndex = expandedStep !== null ? expandedStep : Math.max(0, activeStageCount - 1);
  const selectedStep = pipeSteps[selectedStepIndex];
  const l2Retention = l1Total ? Math.max(0, Math.min(1, (l1Total - filteredCount) / l1Total)) : 0;
  const stageTone = {
    teal: {
      icon: 'bg-teal-600 text-white',
      text: 'text-teal-700 dark:text-teal-300',
      soft: 'bg-teal-50 dark:bg-teal-950/40',
      border: 'border-teal-500/40',
      glow: 'shadow-[0_18px_45px_-28px_rgba(13,148,136,0.75)]',
      rail: 'bg-teal-500',
    },
    sky: {
      icon: 'bg-sky-500 text-white',
      text: 'text-sky-700 dark:text-sky-300',
      soft: 'bg-sky-50 dark:bg-sky-950/40',
      border: 'border-sky-400/50',
      glow: 'shadow-[0_18px_45px_-28px_rgba(14,165,233,0.75)]',
      rail: 'bg-sky-400',
    },
    violet: {
      icon: 'bg-violet-500 text-white',
      text: 'text-violet-700 dark:text-violet-300',
      soft: 'bg-violet-50 dark:bg-violet-950/40',
      border: 'border-violet-400/50',
      glow: 'shadow-[0_18px_45px_-28px_rgba(139,92,246,0.75)]',
      rail: 'bg-violet-400',
    },
    slate: {
      icon: 'bg-surface-container-highest text-on-surface-variant',
      text: 'text-on-surface-variant',
      soft: 'bg-surface-container-low',
      border: 'border-outline-variant/40',
      glow: '',
      rail: 'bg-surface-container-highest',
    },
    emerald: {
      icon: 'bg-emerald-600 text-white',
      text: 'text-emerald-700 dark:text-emerald-300',
      soft: 'bg-emerald-50 dark:bg-emerald-950/40',
      border: 'border-emerald-500/40',
      glow: 'shadow-[0_18px_45px_-28px_rgba(16,185,129,0.75)]',
      rail: 'bg-emerald-500',
    },
  };
  const selectedTone = stageTone[selectedStep?.tone] || stageTone.slate;

  React.useEffect(() => {
    if (selectedStep?.key !== 'l1') {
      setL1FocusKey(null);
    }
  }, [selectedStep?.key]);

  const selectedStats = [];
  let selectedNarrative = selectedStep?.detail || 'เลือก stage เพื่อดู runtime detail';
  let selectedBody = null;

  if (selectedStep?.key === 'case-input') {
    const actorRoles = sentenceProfile.actor_roles || {};
    selectedStats.push(
      { label: 'Phase Time', value: formatDurationMs(selectedStep.durationMs), tone: 'bg-teal-50 text-teal-700 dark:bg-teal-950/40 dark:text-teal-200' },
      { label: 'Characters', value: `${caseDesc.length}`, tone: 'bg-surface-container-low text-on-surface' },
      { label: 'Negation', value: `${(sentenceProfile.negation_markers || []).length}`, tone: 'bg-surface-container-low text-on-surface' },
      { label: 'Actor Mentions', value: `${(actorRoles.mentions || []).length}`, tone: 'bg-surface-container-low text-on-surface' },
    );
    selectedNarrative = 'ส่วนนี้แสดงข้อความเคสต้นทางและตัวบ่งชี้พื้นฐานที่ใช้ตั้งต้นการวิเคราะห์ เช่น negation, actor mentions และขนาดของข้อความ';
    selectedBody = (
      <>
        <div className="mt-4 rounded-xl bg-surface-container-low p-4">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Original Case</div>
          <p className="mt-2 text-sm leading-relaxed text-on-surface">{caseDesc || 'ไม่มีข้อความเคส'}</p>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl bg-surface-container-low p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Negation Markers</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {(sentenceProfile.negation_markers || []).length
                ? (sentenceProfile.negation_markers || []).map((marker) => (
                  <span className="rounded-lg bg-error-container px-2.5 py-1 text-xs font-bold text-on-error-container" key={marker}>
                    {marker}
                  </span>
                ))
                : <span className="text-xs text-on-surface-variant">ไม่พบ negation marker</span>}
            </div>
          </div>
          <div className="rounded-xl bg-surface-container-low p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Actors + Actions</div>
            <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">
              agent {(sentenceProfile.actor_roles?.agents || []).join(', ') || 'ไม่พบ'} | target {(sentenceProfile.actor_roles?.targets || []).join(', ') || 'ไม่พบ'} | action {(sentenceProfile.actor_roles?.actions || []).join(', ') || 'ไม่พบ'}
            </p>
          </div>
        </div>
      </>
    );
  } else if (selectedStep?.key === 'l1') {
    const l1Items = l1Panel === 'accepted' ? acceptedKeywordRows : filteredKeywordRows;
    selectedStats.push(
      { label: 'Phase Time', value: formatDurationMs(selectedStep.durationMs), tone: 'bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-200' },
      { label: 'Candidates', value: `${l1Total}`, tone: 'bg-surface-container-low text-on-surface' },
      { label: 'Accepted', value: `${acceptedKeywordRows.length}`, tone: 'bg-green-50 text-green-700 dark:bg-green-950/40 dark:text-green-200' },
      { label: 'Filtered', value: `${filteredKeywordRows.length}`, tone: filteredKeywordRows.length ? 'bg-yellow-50 text-yellow-700 dark:bg-yellow-950/40 dark:text-yellow-200' : 'bg-surface-container-low text-on-surface' },
      { label: 'Keyword Pool', value: `${keywordPool.length}`, tone: 'bg-surface-container-low text-on-surface' },
    );
    selectedNarrative = 'L1 เป็นชั้นที่อ่าน evidence เชิงคำโดยตรงจากข้อความเคส คุณกดสลับดู accepted, filtered และ keyword pool ได้เพื่อเช็กว่าระบบจับอะไรจาก lexical signal จริง';
    selectedBody = (
      <>
        <div className="mt-4 flex flex-wrap gap-2">
          {[
            { id: 'accepted', label: `Accepted ${acceptedKeywordRows.length}` },
            { id: 'filtered', label: `Filtered ${filteredKeywordRows.length}` },
            { id: 'keywords', label: `Keyword Pool ${keywordPool.length}` },
          ].map((panel) => (
            <button
              className={`rounded-lg px-3 py-2 text-xs font-bold transition-colors ${l1Panel === panel.id ? 'bg-sky-500 text-white shadow-sm' : 'bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high'}`}
              key={panel.id}
              onClick={() => { setL1Panel(panel.id); setL1FocusKey(null); }}
              type="button"
            >
              {panel.label}
            </button>
          ))}
        </div>

        {l1Panel === 'keywords' ? (
          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            {keywordPool.length ? keywordPool.map((item) => (
              <div className="flex items-center justify-between rounded-xl bg-surface-container-low p-3" key={item.keyword}>
                <span className="text-sm font-semibold text-on-surface">{item.keyword}</span>
                <span className="rounded-lg bg-sky-100 px-2 py-1 text-xs font-bold text-sky-900 dark:bg-sky-950/50 dark:text-sky-100">{item.count} hits</span>
              </div>
            )) : (
              <div className="rounded-xl bg-surface-container-low p-4 text-sm text-on-surface-variant">ยังไม่มี keyword ที่ detector บันทึกไว้</div>
            )}
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            {l1Items.length ? l1Items.slice(0, 8).map((item, index) => {
              const itemKey = `${l1Panel}-${item.code || 'unknown'}-${index}`;
              const isOpen = l1FocusKey === itemKey;
              const keywords = item.keywords || item.matched_keywords || [];
              const reasoning = item.reasoning || item.validation_notes || 'ไม่มีคำอธิบายเพิ่มเติม';
              const reviewTone = item.review_tone || (item.review_status === 'confirmed' ? 'live' : item.review_status === 'filtered' ? 'neutral' : 'warning');
              const reviewLabel = item.review_label || item.review_status || (l1Panel === 'accepted' ? 'Accepted' : 'Filtered');
              return (
                <button
                  className={`w-full rounded-xl border p-4 text-left transition-all ${isOpen ? 'border-sky-400 bg-sky-50 shadow-sm dark:bg-sky-950/30' : 'border-outline-variant/20 bg-surface-container-low hover:border-sky-300/50 hover:bg-surface-container'}`}
                  key={itemKey}
                  onClick={() => setL1FocusKey(isOpen ? null : itemKey)}
                  type="button"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="text-[11px] font-bold uppercase tracking-wider text-sky-700 dark:text-sky-300">{item.code || 'Unknown code'}</div>
                      <h5 className="mt-1 text-sm font-bold leading-snug text-on-surface">{item.name || 'ไม่ระบุชื่อปัญหา'}</h5>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <span className={`rounded-lg px-2.5 py-1 text-xs font-bold ${l1Panel === 'accepted' ? 'bg-green-100 text-green-900 dark:bg-green-950/50 dark:text-green-100' : 'bg-yellow-100 text-yellow-900 dark:bg-yellow-950/50 dark:text-yellow-100'}`}>
                        {l1Panel === 'accepted' ? 'ผ่าน' : 'ถูกคัดออก'}
                      </span>
                      <StatusBadge label={reviewLabel} tone={reviewTone} />
                      <span className="rounded-lg bg-surface-container-lowest px-2.5 py-1 text-xs font-bold text-on-surface">{formatPercent(item.confidence || 0)}</span>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {keywords.length ? keywords.map((keyword) => (
                      <span className="rounded-lg bg-sky-100 px-2 py-1 text-[11px] font-bold text-sky-900 dark:bg-sky-950/50 dark:text-sky-100" key={`${itemKey}-${keyword}`}>
                        {keyword}
                      </span>
                    )) : (
                      <span className="text-xs text-on-surface-variant">ไม่มี matched keyword</span>
                    )}
                  </div>
                  {isOpen && (
                    <div className="mt-4 grid gap-3 md:grid-cols-[180px_1fr]">
                      <div className="rounded-xl bg-surface-container-lowest p-3">
                        <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">L1 Decision</div>
                        <p className="mt-2 text-xs leading-relaxed text-on-surface">
                          detection level {item.detection_level || 'L1'}<br />
                          context {item.context_valid === false ? 'ยังไม่ผ่านบริบท' : 'ผ่านบริบท'}
                        </p>
                      </div>
                      <div className="rounded-xl bg-surface-container-lowest p-3">
                        <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Why This Item</div>
                        <p className="mt-2 text-xs leading-relaxed text-on-surface">{compactText(reasoning, 320)}</p>
                      </div>
                    </div>
                  )}
                </button>
              );
            }) : (
              <div className="rounded-xl bg-surface-container-low p-4 text-sm text-on-surface-variant">
                {l1Panel === 'accepted' ? 'ยังไม่มี candidate ที่ผ่านจาก L1' : 'ยังไม่มี candidate ที่ถูกคัดออกจาก L1/L2'}
              </div>
            )}
          </div>
        )}
      </>
    );
  } else if (selectedStep?.key === 'l2') {
    selectedStats.push(
      { label: 'Phase Time', value: formatDurationMs(selectedStep.durationMs), tone: info.l2_applied ? 'bg-violet-50 text-violet-700 dark:bg-violet-950/40 dark:text-violet-200' : 'bg-surface-container-low text-on-surface' },
      { label: 'Validated', value: `${info.l2_count || 0}`, tone: 'bg-surface-container-low text-on-surface' },
      { label: 'Filtered', value: `${filteredCount}`, tone: filteredCount ? 'bg-yellow-50 text-yellow-700 dark:bg-yellow-950/40 dark:text-yellow-200' : 'bg-surface-container-low text-on-surface' },
      { label: 'Review Load', value: `${reviewLoadCount}`, tone: reviewLoadCount ? 'bg-yellow-50 text-yellow-700 dark:bg-yellow-950/40 dark:text-yellow-200' : 'bg-surface-container-low text-on-surface' },
    );
    selectedNarrative = info.l2_applied
      ? 'L2 ใช้ semantic/context validation เพื่อลด false positives จาก L1 และคุม conflict ระหว่าง code ที่คล้ายกัน'
      : l2NotTriggered
        ? 'L2 พร้อมใช้งาน แต่เคสนี้ไม่มี conflict/candidate ที่ต้องเรียก semantic validation เพิ่ม จึงจบได้จาก L1'
        : 'รอบนี้ L2 ถูกข้ามเพราะ strategy เป็น baseline หรือ runtime ยังไม่พร้อมสำหรับ semantic validation';
    selectedBody = (
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl bg-surface-container-low p-4">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Phase Note</div>
          <p className="mt-2 text-sm leading-relaxed text-on-surface">{selectedStep.detail}</p>
        </div>
        <div className="rounded-xl bg-surface-container-low p-4">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Filtered Preview</div>
          <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">
            {filtered.length ? filtered.slice(0, 3).map(formatProblemLabel).join(', ') : 'ไม่มีรายการที่ถูกคัดออกในขั้น semantic/context'}
          </p>
        </div>
      </div>
    );
  } else if (selectedStep?.key === 'final') {
    selectedStats.push(
      { label: 'Phase Time', value: formatDurationMs(selectedStep.durationMs), tone: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200' },
      { label: 'Final Problems', value: `${problems.length}`, tone: 'bg-surface-container-low text-on-surface' },
      { label: 'Evidence Retrieval', value: formatDurationMs(retrievalMs), tone: 'bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-200' },
      { label: 'Total Runtime', value: formatDurationMs(totalRuntimeMs), tone: 'bg-surface-container-low text-on-surface' },
    );
    selectedNarrative = 'ขั้นนี้คือรายการ problem codes ที่ผ่านทุกชั้นแล้ว และถูกใช้ต่อสำหรับ evidence retrieval, score trace และ visualization อื่น ๆ';
    selectedBody = (
      <div className="mt-4 space-y-3">
        {problems.length ? problems.map((problem) => (
          <div className="rounded-xl bg-surface-container-low p-4" key={`${problem.code}-${problem.name}`}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-[11px] font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-300">{problem.code}</div>
                <h5 className="mt-1 text-sm font-bold leading-snug text-on-surface">{problem.name}</h5>
              </div>
              <span className="rounded-lg bg-surface-container-lowest px-2.5 py-1 text-xs font-bold text-on-surface">{formatPercent(problem.confidence || 0)}</span>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">{compactText(problem.reasoning, 240)}</p>
          </div>
        )) : (
          <div className="rounded-xl bg-surface-container-low p-4 text-sm text-on-surface-variant">ยังไม่มี problem code ที่ผ่านถึงขั้น final</div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <section className="overflow-hidden rounded-xl bg-surface-container-low">
        <div className="relative overflow-hidden border-b border-outline-variant/20 bg-surface-container-lowest px-6 py-6">
          <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-teal-500 via-sky-400 to-emerald-500" />
          <div className="relative z-10 flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-[10px] font-bold uppercase tracking-widest text-teal-700">Runtime Flow</div>
              <h2 className="mt-1 font-headline text-2xl font-extrabold tracking-tight text-on-surface">System Pipeline</h2>
              <p className="mt-2 max-w-2xl text-sm leading-relaxed text-on-surface-variant">
                {hasResult ? 'Interactive realtime visual ของ H2L Detection Pipeline จากผลวิเคราะห์เคสปัจจุบัน' : 'กรุณาวิเคราะห์เคสเพื่อให้ runtime สร้าง flow, candidates และผลลัพธ์จริง'}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge label={runtime.status || 'runtime'} tone={statusTone(runtime.status)} />
              <StatusBadge label={info.l2_applied ? 'L2 Applied' : info.l2_requested ? 'L2 Degraded' : 'L1 Only'} tone={info.l2_applied ? 'live' : info.l2_requested ? 'warning' : 'neutral'} />
            </div>
          </div>
          <div className="relative z-10 mt-5 grid gap-3 md:grid-cols-4">
            <div className="rounded-lg bg-surface-container-low px-4 py-3">
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Candidates</div>
              <div className="mt-1 font-headline text-xl font-extrabold text-on-surface">{l1Total || '—'}</div>
            </div>
            <div className="rounded-lg bg-surface-container-low px-4 py-3">
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Filtered</div>
              <div className="mt-1 font-headline text-xl font-extrabold text-yellow-700">{hasResult ? filteredCount : '—'}</div>
            </div>
            <div className="rounded-lg bg-surface-container-low px-4 py-3">
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Evidence</div>
              <div className="mt-1 font-headline text-xl font-extrabold text-sky-700 dark:text-sky-300">{hasResult ? retrievedDocsCount : '—'}</div>
            </div>
            <div className="rounded-lg bg-surface-container-low px-4 py-3">
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Final</div>
              <div className="mt-1 font-headline text-xl font-extrabold text-teal-700">{hasResult ? problems.length : '—'}</div>
            </div>
          </div>
        </div>

        <div className="p-6">
          <div className="space-y-6">
            <div className="pipeline-grid relative min-h-[390px] overflow-hidden rounded-xl border border-outline-variant/30 bg-surface-container-lowest p-5">
              <div className="absolute inset-x-5 top-1/2 hidden h-1 -translate-y-1/2 rounded-full bg-surface-container-high lg:block">
                <div className="h-full rounded-full bg-gradient-to-r from-teal-500 via-sky-400 to-emerald-500 transition-all duration-700" style={{ width: `${pipelineProgress}%` }} />
                {hasResult && (
                  <>
                    <span className="pipeline-packet bg-teal-400" style={{ animationDelay: '0ms' }} />
                    <span className="pipeline-packet bg-sky-400" style={{ animationDelay: '700ms' }} />
                    <span className="pipeline-packet bg-emerald-400" style={{ animationDelay: '1400ms' }} />
                  </>
                )}
              </div>
              <div className="relative z-10 flex items-center justify-between gap-3">
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Live Execution Path</div>
                  <p className="mt-1 text-sm text-on-surface-variant">{hasResult ? `Phase ${activeStageCount}/${pipeSteps.length} กำลัง replay flow ล่าสุด` : 'Waiting for case analysis'}</p>
                </div>
                <button
                  className="rounded-lg bg-surface-container-high px-3 py-2 text-xs font-bold text-on-surface transition-colors hover:bg-surface-container-highest"
                  onClick={() => hasResult && setReplayKey((current) => current + 1)}
                  type="button"
                >
                  Replay
                </button>
              </div>

              <div className="relative z-10 mt-7 grid gap-3 lg:grid-cols-4">
                {pipeSteps.map((step, idx) => {
                  const isActive = hasResult && animPhase >= idx + 1;
                  const isOpen = expandedStep === idx;
                  const tone = stageTone[step.tone] || stageTone.slate;
                  return (
                    <button key={step.label} type="button" onClick={() => hasResult && setExpandedStep(isOpen ? null : idx)}
                      className={`group min-h-[210px] rounded-xl border p-4 text-left transition-all duration-500 ${isActive ? `${tone.border} ${tone.soft} ${tone.glow} opacity-100` : 'border-outline-variant/20 bg-surface-container-lowest opacity-55'} ${isOpen ? 'ring-2 ring-teal-600/40 ring-offset-2 ring-offset-surface-container-lowest' : ''}`}
                      style={{ transitionDelay: `${idx * 90}ms` }}>
                      <div className="flex items-start justify-between gap-3">
                        <span className={`pipeline-live-ring flex h-11 w-11 items-center justify-center rounded-lg transition-transform duration-300 ${isActive ? `${tone.icon} scale-100` : 'bg-surface-container-high text-on-surface-variant scale-90'}`}>
                          <span aria-hidden="true" className="material-symbols-outlined text-[22px]">{step.icon}</span>
                        </span>
                        <span className={`rounded bg-surface-container-lowest/70 px-2 py-1 text-[10px] font-bold uppercase tracking-wider ${step.status === 'complete' ? tone.text : step.status === 'skipped' ? 'text-on-surface-variant' : 'text-outline-variant'}`}>
                          {step.status === 'complete' ? 'Done' : step.status === 'skipped' ? 'Skip' : 'Wait'}
                        </span>
                      </div>
                      <div className={`mt-4 text-[10px] font-bold uppercase tracking-widest ${isActive ? tone.text : 'text-on-surface-variant'}`}>{step.eyebrow}</div>
                      <h3 className="mt-1 min-h-[40px] text-sm font-bold leading-snug text-on-surface">{step.label}</h3>
                      <div className={`mt-3 font-headline text-3xl font-extrabold transition-all duration-500 ${isActive ? tone.text : 'text-outline-variant'}`}>{isActive ? step.count : '—'}</div>
                      <div className="mt-2 text-[11px] font-semibold text-on-surface-variant">{formatDurationMs(step.durationMs)}</div>
                      <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-surface-container-high">
                        <div className={`h-full rounded-full transition-all duration-700 ${isActive ? tone.rail : 'bg-outline-variant/30'}`} style={{ width: isActive ? `${Math.min(100, 38 + idx * 18)}%` : '18%' }} />
                      </div>
                      {hasResult && <div className="mt-3 text-[11px] font-semibold text-on-surface-variant">{isOpen ? 'ซ่อนรายละเอียด' : 'ดูรายละเอียด'}</div>}
                    </button>
                  );
                })}
              </div>

              {hasResult && (
                <div className="relative z-10 mt-5 grid gap-3 md:grid-cols-[1fr_1.2fr]">
                  <div className="rounded-xl border border-outline-variant/25 bg-surface-container-lowest p-4 shadow-sm">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Selected Node</div>
                        <h4 className="mt-1 font-headline font-bold text-on-surface">{selectedStep?.label}</h4>
                      </div>
                      <span className={`flex h-10 w-10 items-center justify-center rounded-lg ${selectedTone.icon}`}>
                        <span aria-hidden="true" className="material-symbols-outlined text-[21px]">{selectedStep?.icon}</span>
                      </span>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      {selectedStats.map((stat) => (
                        <div className={`rounded-lg px-3 py-2 ${stat.tone}`} key={`${selectedStep?.key}-${stat.label}`}>
                          <div className="text-[10px] font-bold uppercase tracking-widest opacity-80">{stat.label}</div>
                          <div className="mt-1 text-sm font-bold">{stat.value}</div>
                        </div>
                      ))}
                    </div>
                    <p className="mt-4 text-sm leading-relaxed text-on-surface-variant">{selectedNarrative}</p>
                    {selectedStep?.sub && selectedStep.key !== 'l1' && (
                      <p className="mt-4 rounded-xl bg-surface-container-low p-3 text-xs leading-relaxed text-on-surface">{selectedStep.sub}</p>
                    )}
                    {selectedBody}
                  </div>
                  <div className="rounded-xl border border-outline-variant/25 bg-surface-container-lowest p-4 shadow-sm">
                    <div className="flex items-center justify-between">
                      <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Flow Summary</div>
                      <span className="text-xs font-bold text-teal-700 dark:text-teal-300">{Math.round(pipelineProgress)}%</span>
                    </div>
                    <div className="mt-4 grid gap-2 sm:grid-cols-2">
                      {pipeSteps.map((step, idx) => {
                        const tone = stageTone[step.tone] || stageTone.slate;
                        const isSelected = selectedStepIndex === idx;
                        return (
                          <button
                            className={`rounded-xl border p-3 text-left transition-colors ${isSelected ? `${tone.border} ${tone.soft}` : 'border-outline-variant/20 bg-surface-container-low hover:bg-surface-container'}`}
                            key={`${step.label}-summary`}
                            onClick={() => hasResult && setExpandedStep(isSelected ? null : idx)}
                            type="button"
                          >
                            <div className="flex items-start justify-between gap-3">
                              <div>
                                <div className={`text-[10px] font-bold uppercase tracking-widest ${isSelected ? tone.text : 'text-on-surface-variant'}`}>{step.eyebrow}</div>
                                <div className="mt-1 text-sm font-bold text-on-surface">{step.label}</div>
                              </div>
                              <span className="rounded-lg bg-surface-container-lowest px-2 py-1 text-[11px] font-bold text-on-surface">
                                {formatDurationMs(step.durationMs)}
                              </span>
                            </div>
                            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                              <span className={`rounded-lg px-2 py-1 font-bold ${tone.soft} ${tone.text}`}>{typeof step.count === 'number' ? `${step.count} items` : step.count}</span>
                              <span className="text-on-surface-variant">
                                {step.key === 'l2' && l2NotTriggered ? 'no semantic escalation needed' : step.status === 'skipped' ? 'semantic stage skipped' : 'measured runtime'}
                              </span>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                    <div className="mt-4 flex flex-wrap items-center gap-2">
                      <span className="rounded-lg bg-sky-50 px-3 py-1 text-xs font-bold text-sky-700 dark:bg-sky-950/40 dark:text-sky-300">Evidence Retrieval {formatDurationMs(retrievalMs)}</span>
                      <span className="rounded-lg bg-surface-container-low px-3 py-1 text-xs font-bold text-on-surface">Total Runtime {formatDurationMs(totalRuntimeMs)}</span>
                    </div>
                    <p className="mt-3 text-xs leading-relaxed text-on-surface-variant">
                      แต่ละการ์ดด้านบนแสดงเวลา phase จริงจากเคสล่าสุด คุณกดเลือก phase เพื่อให้ Selected Node เปลี่ยนรายละเอียดตามขั้นที่สนใจได้ทันที
                    </p>
                  </div>
                </div>
              )}
            </div>

            <aside className="rounded-xl border border-outline-variant/25 bg-surface-container-lowest p-5">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Realtime Telemetry</div>
                  <h3 className="mt-1 font-headline font-bold text-on-surface">Runtime Pulse</h3>
                </div>
                <span className={`h-3 w-3 rounded-full ${hasResult ? 'animate-pulse bg-teal-500' : 'bg-outline-variant'}`} />
              </div>
              <div className="mt-5 space-y-4">
                <div>
                  <div className="flex items-center justify-between text-xs font-bold">
                    <span className="text-on-surface-variant">L2 Retention</span>
                    <span className="text-on-surface">{hasResult && l1Total ? formatPercent(l2Retention) : 'N/A'}</span>
                  </div>
                  <SegmentedBar value={hasResult ? l2Retention : 0} tone={info.l2_applied ? 'teal' : 'warning'} />
                </div>
                <div>
                  <div className="flex items-center justify-between text-xs font-bold">
                    <span className="text-on-surface-variant">Evidence Loaded</span>
                    <span className="text-on-surface">{retrievedDocsCount}</span>
                  </div>
                  <SegmentedBar value={Math.min(1, retrievedDocsCount / 5)} tone="teal" />
                </div>
                <div>
                  <div className="flex items-center justify-between text-xs font-bold">
                    <span className="text-on-surface-variant">{ambiguitySummary.label || 'Review Load'}</span>
                    <span className={reviewLoadToneClass}>{reviewLoadCount}</span>
                  </div>
                  <SegmentedBar value={Math.min(1, reviewLoadCount / 5)} tone={reviewLoadTone} />
                  <div className="mt-1 text-[11px] leading-relaxed text-on-surface-variant">{reviewLoadHint}</div>
                </div>
              </div>
              <div className="mt-5 rounded-lg bg-surface-container-low p-4">
                <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Stage Log</div>
                <div className="mt-3 space-y-2">
                  {pipeSteps.map((step, index) => {
                    const isActive = hasResult && animPhase >= index + 1;
                    const tone = stageTone[step.tone] || stageTone.slate;
                    return (
                      <div key={`${step.label}-log`} className="flex items-center justify-between gap-3 text-xs">
                        <div className="flex items-center gap-3">
                          <span className={`h-2.5 w-2.5 rounded-full ${isActive ? tone.rail : 'bg-outline-variant/40'}`} />
                          <span className={isActive ? 'font-bold text-on-surface' : 'text-on-surface-variant'}>{step.label}</span>
                        </div>
                        <span className="font-medium text-on-surface-variant">{formatDurationMs(step.durationMs)}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </aside>
          </div>
        </div>

        {/* Metrics */}
        <div className="grid gap-3 border-t border-outline-variant/20 p-6 lg:grid-cols-4">
          <MetricTile label="Review Load" value={reviewLoadCount} hint={reviewLoadHint} tone={reviewLoadCount ? 'bg-yellow-50 dark:bg-yellow-950/40' : 'bg-surface-container-lowest'} />
          <MetricTile label="Filtered" value={filteredCount} hint="context/polarity filtered" tone={filteredCount ? 'bg-yellow-50 dark:bg-yellow-950/40' : 'bg-surface-container-lowest'} />
          <MetricTile label="Retrieved Docs" value={retrievedDocsCount} hint="real runtime retrieval" />
          <MetricTile label="Runtime" value={runtime.status || 'N/A'} hint={runtime.stage || 'stage'} tone={runtime.status === 'ready' ? 'bg-surface-container-lowest' : 'bg-surface-container-lowest'} />
        </div>
      </section>
      <CandidateFilterPanel displayResult={displayResult} />
    </div>
  );
}

function ProcessingCasePanel({ caseDescription, selectedStrategy, enableL2, evidenceTopK, runtimeStatus, selectedL2Model }) {
  const [elapsedMs, setElapsedMs] = useState(0);
  const [focusedStage, setFocusedStage] = useState(0);

  const stages = [
    { icon: 'upload_file', label: 'Prepare Case', detail: 'ส่งข้อความเคสและ strategy ไปยัง runtime จริง', tone: 'teal' },
    { icon: 'rule', label: 'Sentence Profile', detail: 'อ่าน polarity, actors, negation และบริบทประโยค', tone: 'sky' },
    { icon: 'manage_search', label: 'L1 Detection', detail: 'ค้น candidate problem codes ด้วย keyword และ rule layer', tone: 'sky' },
    { icon: 'travel_explore', label: 'Evidence Retrieval', detail: 'ดึงเอกสารหลักฐานด้วย retrieval strategy ที่เลือก', tone: 'violet' },
    { icon: enableL2 ? 'auto_awesome' : 'skip_next', label: enableL2 ? 'L2 Validation' : 'L2 Skipped', detail: enableL2 ? `ตรวจ semantic/context ด้วย ${selectedL2Model}` : 'baseline mode จะข้าม semantic validation', tone: enableL2 ? 'violet' : 'slate' },
    { icon: 'fact_check', label: 'Compose Result', detail: 'รวม final problems, trace, metrics และ visualization payload', tone: 'emerald' },
  ];

  useEffect(() => {
    const startedAt = Date.now();
    const interval = window.setInterval(() => {
      const nextElapsed = Date.now() - startedAt;
      setElapsedMs(nextElapsed);
      setFocusedStage(Math.min(stages.length - 1, Math.floor(nextElapsed / 1800)));
    }, 250);
    return () => window.clearInterval(interval);
  }, [stages.length]);

  const elapsedSeconds = elapsedMs / 1000;
  const activeStage = Math.min(stages.length - 1, Math.floor(elapsedSeconds / 1.8));
  const estimatedProgress = Math.min(94, Math.round(9 + elapsedSeconds * 7 + activeStage * 7));
  const selectedStage = stages[focusedStage] || stages[activeStage] || stages[0];
  const caseLength = caseDescription.trim().length;
  const runtimeTone = statusTone(runtimeStatus.status);
  const toneClass = {
    teal: 'bg-teal-50 text-teal-700 dark:bg-teal-950/40 dark:text-teal-200',
    sky: 'bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-200',
    violet: 'bg-violet-50 text-violet-700 dark:bg-violet-950/40 dark:text-violet-200',
    slate: 'bg-surface-container-high text-on-surface-variant',
    emerald: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200',
  };

  return (
    <section className="mb-6 overflow-hidden rounded-xl border border-teal-500/25 bg-surface-container-lowest shadow-sm">
      <div className="processing-grid relative p-5">
        <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-teal-500 via-sky-400 to-emerald-500" />
        <div className="relative z-10 flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-4">
            <div className="processing-core flex h-14 w-14 items-center justify-center rounded-lg bg-teal-600 text-white shadow-[0_18px_38px_-20px_rgba(13,148,136,0.8)]">
              <span aria-hidden="true" className="material-symbols-outlined text-[28px]">data_object</span>
            </div>
            <div>
              <div className="text-[10px] font-bold uppercase tracking-widest text-teal-700">Live Processing</div>
              <h3 className="mt-1 font-headline text-xl font-extrabold text-on-surface">กำลังประมวลผลเคสจริง</h3>
              <p className="mt-1 max-w-2xl text-sm leading-relaxed text-on-surface-variant">
                Runtime กำลังวิเคราะห์ด้วย {selectedStrategy}; หน้านี้เป็น live progress ระหว่างรอผลลัพธ์จาก API จริง
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge label={`${elapsedSeconds.toFixed(1)}s`} tone="neutral" />
            <StatusBadge label={runtimeStatus.status || 'runtime'} tone={runtimeTone} />
          </div>
        </div>

        <div className="relative z-10 mt-5 overflow-hidden rounded-lg bg-surface-container-low p-3">
          <div className="flex items-center justify-between text-xs font-bold text-on-surface-variant">
            <span>Estimated runtime progress</span>
            <span className="text-teal-700">{estimatedProgress}%</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-container-high">
            <div className="processing-progress h-full rounded-full bg-gradient-to-r from-teal-500 via-sky-400 to-emerald-500 transition-[width] duration-300" style={{ width: `${estimatedProgress}%` }} />
          </div>
        </div>

        <div className="relative z-10 mt-5 grid gap-3 lg:grid-cols-6">
          {stages.map((stage, index) => {
            const isDone = index < activeStage;
            const isActive = index === activeStage;
            const isFocused = index === focusedStage;
            return (
              <button
                className={`min-h-[132px] rounded-xl border p-3 text-left transition-all ${isFocused ? 'border-teal-500/60 ring-2 ring-teal-600/20' : 'border-outline-variant/20'} ${isActive ? toneClass[stage.tone] : isDone ? 'bg-surface-container-low text-on-surface' : 'bg-surface-container-lowest text-on-surface-variant'}`}
                key={stage.label}
                onClick={() => setFocusedStage(index)}
                type="button"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className={`flex h-9 w-9 items-center justify-center rounded-lg ${isActive ? 'bg-teal-600 text-white' : isDone ? 'bg-teal-50 text-teal-700 dark:bg-teal-950/40 dark:text-teal-200' : 'bg-surface-container-high text-on-surface-variant'}`}>
                    <span aria-hidden="true" className="material-symbols-outlined text-[20px]">{isDone ? 'check' : stage.icon}</span>
                  </span>
                  <span className={`text-[10px] font-bold uppercase ${isActive ? 'text-teal-700 dark:text-teal-200' : 'text-on-surface-variant'}`}>{isDone ? 'done' : isActive ? 'running' : 'queued'}</span>
                </div>
                <h4 className="mt-3 text-sm font-bold leading-snug text-on-surface">{stage.label}</h4>
                <p className="mt-2 text-[11px] leading-relaxed text-on-surface-variant">{stage.detail}</p>
              </button>
            );
          })}
        </div>

        <div className="relative z-10 mt-5 grid gap-3 lg:grid-cols-[1fr_1.2fr]">
          <div className="rounded-lg bg-surface-container-low p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Current Stage</div>
                <h4 className="mt-1 font-headline font-bold text-on-surface">{selectedStage.label}</h4>
              </div>
              <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-teal-600 text-white">
                <span aria-hidden="true" className="material-symbols-outlined text-[21px]">{selectedStage.icon}</span>
              </span>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-on-surface-variant">{selectedStage.detail}</p>
          </div>
          <div className="rounded-lg bg-surface-container-low p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Request Telemetry</div>
            <div className="mt-3 grid gap-2 text-xs md:grid-cols-3">
              <span className="rounded bg-surface-container-lowest px-3 py-2 font-bold text-on-surface">chars {caseLength}</span>
              <span className="rounded bg-surface-container-lowest px-3 py-2 font-bold text-on-surface">{selectedStrategy}</span>
              <span className="rounded bg-surface-container-lowest px-3 py-2 font-bold text-on-surface">L2 {String(enableL2)}</span>
              <span className="rounded bg-surface-container-lowest px-3 py-2 font-bold text-on-surface">Top {evidenceTopK}</span>
            </div>
            <p className="mt-3 text-xs leading-relaxed text-on-surface-variant">
              ระบบยังไม่แสดงผลลัพธ์เดิมปนกับเคสนี้ จนกว่า API จะส่ง response กลับมาและสร้าง trace ใหม่สำเร็จ
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

function DocScalingPlot({ runs, selectedTopK, onSelectTopK }) {
  const [metric, setMetric] = useState('MAP');
  const [source, setSource] = useState('detected');
  const [focusedTopK, setFocusedTopK] = useState(null);
  const metricOptions = [
    { id: 'MAP', label: 'MAP' },
    { id: 'MRR', label: 'MRR' },
    { id: 'nDCG@5', label: 'nDCG@5' },
    { id: 'nDCG@10', label: 'nDCG@10' },
  ];
  const sourceOptions = ['detected', 'gold'].map((id) => ({ id, ...problemSourceMeta(id) }));
  const activeSource = sourceOptions.find((item) => item.id === source) || sourceOptions[0];
  const sourceRuns = DOC_SCALING_OPTIONS.map((topK) => (
    (runs || []).find((run) => run.problem_source === source && Number(run.top_k) === topK) || { top_k: topK, missing: true }
  ));
  const scoreFor = (run, strategy) => {
    const row = (run.rows || []).find((item) => item.strategy === strategy) || {};
    return Number(row[metric]);
  };
  const plottedRuns = sourceRuns.map((run) => {
    const h2lScore = scoreFor(run, 'h2l-hybrid');
    const baselineScore = scoreFor(run, 'basic');
    return {
      ...run,
      h2lScore,
      baselineScore,
      delta: Number.isFinite(h2lScore) && Number.isFinite(baselineScore) ? h2lScore - baselineScore : NaN,
    };
  });
  const scoredRuns = plottedRuns.filter((run) => Number.isFinite(run.h2lScore));
  const baselineRuns = plottedRuns.filter((run) => Number.isFinite(run.baselineScore));
  const scoreValues = [...scoredRuns.map((run) => run.h2lScore), ...baselineRuns.map((run) => run.baselineScore)];
  const rawMinScore = scoreValues.length ? Math.min(...scoreValues) : 0;
  const rawMaxScore = scoreValues.length ? Math.max(...scoreValues) : 1;
  const scorePadding = Math.max(0.015, Math.abs(rawMaxScore - rawMinScore) * 0.16);
  const minScore = Math.max(0, rawMinScore - scorePadding);
  const maxScore = Math.min(1, rawMaxScore + scorePadding);
  const chart = { left: 58, right: 706, top: 30, bottom: 300 };
  const chartWidth = chart.right - chart.left;
  const chartHeight = chart.bottom - chart.top;
  const yFor = (score) => {
    if (!Number.isFinite(score)) return chart.bottom;
    if (Math.abs(maxScore - minScore) < 0.000001) return chart.top + chartHeight / 2;
    return chart.bottom - ((score - minScore) / (maxScore - minScore)) * chartHeight;
  };
  const xFor = (topK) => chart.left + ((topK - 5) / 15) * chartWidth;
  const pointsFor = (key) => plottedRuns
    .filter((run) => Number.isFinite(run[key]))
    .map((run) => ({ topK: Number(run.top_k), x: xFor(Number(run.top_k)), y: yFor(run[key]), score: run[key] }));
  const h2lPoints = pointsFor('h2lScore');
  const baselinePoints = pointsFor('baselineScore');
  const pathFor = (points) => points.map((point, index) => `${index ? 'L' : 'M'} ${point.x} ${point.y}`).join(' ');
  const h2lPath = pathFor(h2lPoints);
  const baselinePath = pathFor(baselinePoints);
  const areaPath = h2lPoints.length
    ? `M ${h2lPoints[0].x} ${chart.bottom} ${h2lPoints.map((point) => `L ${point.x} ${point.y}`).join(' ')} L ${h2lPoints[h2lPoints.length - 1].x} ${chart.bottom} Z`
    : '';
  const bestRun = scoredRuns.length ? [...scoredRuns].sort((a, b) => b.h2lScore - a.h2lScore)[0] : null;
  const selectedRun = plottedRuns.find((run) => Number(run.top_k) === Number(selectedTopK));
  const focusedRun = plottedRuns.find((run) => Number(run.top_k) === Number(focusedTopK));
  const activePoint = [focusedRun, selectedRun, bestRun].find((run) => Number.isFinite(run?.h2lScore)) || null;
  const activeTopK = Number(activePoint?.top_k || selectedTopK || bestRun?.top_k || 5);
  const activeDelta = Number(activePoint?.delta);
  const bestDeltaRun = plottedRuns
    .filter((run) => Number.isFinite(run.delta))
    .sort((a, b) => b.delta - a.delta)[0] || null;
  const axisTicks = [maxScore, minScore + (maxScore - minScore) / 2, minScore];
  const nearestTopKFromEvent = (event) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const approximateTopK = 5 + ratio * 15;
    return DOC_SCALING_OPTIONS.reduce((nearest, option) => (
      Math.abs(option - approximateTopK) < Math.abs(nearest - approximateTopK) ? option : nearest
    ), DOC_SCALING_OPTIONS[0]);
  };
  const handleChartMove = (event) => {
    const topK = nearestTopKFromEvent(event);
    if (plottedRuns.some((run) => Number(run.top_k) === topK && Number.isFinite(run.h2lScore))) {
      setFocusedTopK(topK);
    }
  };
  const handleChartSelect = () => {
    if (Number.isFinite(activePoint?.h2lScore)) {
      onSelectTopK?.(Number(activePoint.top_k));
    }
  };
  const activeDeltaLabel = Number.isFinite(activeDelta)
    ? `${activeDelta >= 0 ? '+' : ''}${formatNumber(activeDelta)}`
    : 'N/A';
  const tooltipWidth = 170;
  const tooltipHeight = 66;
  const tooltipX = activePoint
    ? Math.min(Math.max(xFor(activeTopK) + 18, chart.left + 8), chart.right - tooltipWidth - 8)
    : chart.left;
  const tooltipY = chart.top + 10;

  return (
    <div className="rounded-xl border border-outline-variant/20 bg-surface-container-lowest p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Top-K Plot</div>
          <h3 className="mt-1 break-words font-headline text-xl font-extrabold text-on-surface">Evidence Scaling by Top-K</h3>
          <p className="mt-1 max-w-3xl text-sm leading-relaxed text-on-surface-variant">ลากบนกราฟเพื่ออ่านค่า กดจุดเพื่อเลือก K เดียวกันทั้งหน้า และสลับได้ว่าต้องการดูผลหลักของระบบจากปัญหาที่ระบบตรวจพบเอง หรือดูเพดานบนจากปัญหาอ้างอิงใน ground truth</p>
        </div>
        <div className="flex max-w-full flex-wrap gap-2">
          <StatusBadge label={bestRun ? `best top ${bestRun.top_k}` : 'artifact missing'} tone={bestRun ? 'live' : 'warning'} />
          <StatusBadge label={`selected top ${selectedTopK}`} tone="neutral" />
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          {sourceOptions.map((item) => (
            <button
              className={`rounded-lg px-3 py-2 text-xs font-bold uppercase transition-all ${source === item.id ? 'bg-teal-600 text-white shadow-sm' : 'bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high'}`}
              key={item.id}
              onClick={() => {
                setSource(item.id);
                setFocusedTopK(null);
              }}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          {metricOptions.map((item) => (
            <button
              className={`rounded-lg px-3 py-2 text-xs font-bold transition-all ${metric === item.id ? 'bg-slate-900 text-white shadow-sm dark:bg-slate-100 dark:text-slate-950' : 'bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high'}`}
              key={item.id}
              onClick={() => {
                setMetric(item.id);
                setFocusedTopK(null);
              }}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-3 rounded-xl bg-surface-container-low p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Current Evidence Source</div>
            <div className="mt-1 font-bold text-on-surface">{activeSource.label}</div>
          </div>
          <StatusBadge label={activeSource.shortLabel} tone={source === 'detected' ? 'live' : 'warning'} />
        </div>
        <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">{activeSource.meaning}</p>
      </div>

      <div className="mt-5 space-y-4">
        <div className="topk-plot-panel overflow-hidden rounded-xl border border-outline-variant/20 bg-surface-container-low p-3 sm:p-4 lg:p-5">
          <svg
            aria-label="Interactive Top K performance plot"
            className="h-[24rem] w-full md:h-[30rem]"
            onClick={handleChartSelect}
            onMouseLeave={() => setFocusedTopK(null)}
            onMouseMove={handleChartMove}
            preserveAspectRatio="none"
            role="img"
            viewBox="0 0 760 380"
          >
            <defs>
              <linearGradient id="topk-h2l-area" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="#14b8a6" stopOpacity="0.28" />
                <stop offset="100%" stopColor="#14b8a6" stopOpacity="0.02" />
              </linearGradient>
              <linearGradient id="topk-h2l-line" x1="0" x2="1" y1="0" y2="0">
                <stop offset="0%" stopColor="#0f766e" />
                <stop offset="100%" stopColor="#22d3ee" />
              </linearGradient>
            </defs>
            <rect x={chart.left} y={chart.top} width={chartWidth} height={chartHeight} rx="8" className="topk-plot-stage" />
            {axisTicks.map((tick, index) => {
              const y = yFor(tick);
              return (
                <g key={`axis-${index}`}>
                  <line x1={chart.left} x2={chart.right} y1={y} y2={y} className="topk-grid-line" strokeWidth="1" strokeDasharray={index === 1 ? '6 8' : '0'} opacity={index === 1 ? 0.58 : 0.86} />
                  <text x="18" y={y + 4} fill="currentColor" className="text-[11px] font-bold text-on-surface-variant">{formatNumber(tick)}</text>
                </g>
              );
            })}
            <rect x={xFor(Number(selectedTopK)) - 28} y={chart.top} width="56" height={chartHeight} rx="8" className="topk-selected-band" />
            <line x1={xFor(activeTopK)} x2={xFor(activeTopK)} y1={chart.top} y2={chart.bottom} className="topk-active-line animate-pulse" strokeWidth="2" strokeDasharray="7 8" />
            {[5, 10, 15, 20].map((topK) => (
              <g key={`tick-${topK}`}>
                <line x1={xFor(topK)} x2={xFor(topK)} y1={chart.bottom - 5} y2={chart.bottom + 8} className="topk-grid-line" strokeWidth="1" />
                <text x={xFor(topK)} y={chart.bottom + 30} textAnchor="middle" fill="currentColor" className="text-[12px] font-extrabold text-on-surface-variant">Top {topK}</text>
              </g>
            ))}
            {areaPath && <path d={areaPath} fill="url(#topk-h2l-area)" />}
            {baselinePath && <path d={baselinePath} fill="none" className="topk-baseline-line" strokeWidth="3" strokeDasharray="9 9" strokeLinecap="round" strokeLinejoin="round" />}
            {h2lPath && <path d={h2lPath} fill="none" stroke="url(#topk-h2l-line)" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />}
            {plottedRuns.map((run) => {
              const topK = Number(run.top_k);
              const missing = !Number.isFinite(run.h2lScore);
              const isSelected = topK === Number(selectedTopK);
              const isBest = bestRun && topK === Number(bestRun.top_k);
              const isActive = topK === activeTopK;
              const y = missing ? chart.bottom : yFor(run.h2lScore);
              return (
                <g key={`${source}-${topK}`}>
                  {Number.isFinite(run.baselineScore) && (
                    <rect
                      x={xFor(topK) - 7}
                      y={yFor(run.baselineScore) - 7}
                      width="14"
                      height="14"
                      rx="3"
                      fill="#64748b"
                      opacity="0.9"
                    />
                  )}
                  {isSelected && !missing && (
                    <circle cx={xFor(topK)} cy={y} fill="none" opacity="0.38" r="14" className="topk-point-ring" strokeWidth="2">
                      <animate attributeName="r" dur="1.6s" repeatCount="indefinite" values="12;24;12" />
                      <animate attributeName="opacity" dur="1.6s" repeatCount="indefinite" values="0.42;0.06;0.42" />
                    </circle>
                  )}
                  <circle
                    aria-disabled={missing}
                    aria-label={`select top ${topK}`}
                    className="topk-h2l-point cursor-pointer transition-all"
                    cx={xFor(topK)}
                    cy={y}
                    fill={missing ? '#cbd5e1' : isBest ? '#0f766e' : '#14b8a6'}
                    onClick={(event) => {
                      event.stopPropagation();
                      if (!missing) {
                        setFocusedTopK(topK);
                        onSelectTopK?.(topK);
                      }
                    }}
                    onFocus={() => !missing && setFocusedTopK(topK)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        if (!missing) setFocusedTopK(topK);
                        if (!missing) onSelectTopK?.(topK);
                      }
                    }}
                    opacity={missing ? 0.55 : isActive ? 1 : 0.88}
                    r={isSelected ? 9 : isActive ? 8 : 6}
                    role="button"
                    strokeWidth="2.5"
                    tabIndex={missing ? '-1' : '0'}
                  />
                  {isBest && !missing && (
                    <text x={xFor(topK)} y={y - 18} textAnchor="middle" fill="currentColor" className="text-[11px] font-extrabold text-teal-700 dark:text-teal-200">best</text>
                  )}
                </g>
              );
            })}
            {activePoint && (
              <g pointerEvents="none">
                <rect x={tooltipX} y={tooltipY} width={tooltipWidth} height={tooltipHeight} rx="8" className="topk-tooltip-box" />
                <text x={tooltipX + 14} y={tooltipY + 22} className="topk-tooltip-title text-[12px] font-bold">Top {activePoint.top_k}</text>
                <text x={tooltipX + 14} y={tooltipY + 42} className="topk-tooltip-value text-[13px] font-extrabold">{metric}: {formatNumber(activePoint.h2lScore)}</text>
                <text x={tooltipX + 14} y={tooltipY + 59} className="topk-tooltip-muted text-[10px] font-bold">delta vs basic {activeDeltaLabel}</text>
              </g>
            )}
          </svg>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs font-bold text-on-surface-variant">
            <span className="inline-flex min-w-0 items-center gap-2"><span className="h-1 w-8 shrink-0 rounded-full bg-teal-600" />H2L</span>
            <span className="inline-flex min-w-0 items-center gap-2"><span className="h-1 w-8 shrink-0 rounded-full border-t-2 border-dashed border-slate-500 dark:border-slate-300" />Baseline</span>
            <span className="min-w-0 break-words text-teal-700 dark:text-teal-200">live readout follows pointer</span>
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div className="min-w-0 rounded-xl bg-surface-container-low p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Live Focus</div>
              <div className="mt-2 font-headline text-3xl font-extrabold text-on-surface">Top {activePoint?.top_k ?? selectedTopK}</div>
            </div>
            <StatusBadge label={activeSource.shortLabel} tone="neutral" />
          </div>
          <div className="mt-1 break-words text-sm font-bold text-teal-700 dark:text-teal-200">{activePoint ? formatNumber(activePoint.h2lScore) : 'N/A'} {metric}</div>
          <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">ค่า live readout จะตามตำแหน่ง pointer หรือ Top-K ที่ถูกเลือกอยู่</p>
        </div>
        <div className="min-w-0 rounded-xl bg-surface-container-low p-4">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Best K</div>
          <div className="mt-2 font-headline text-2xl font-extrabold text-on-surface">{bestRun ? `Top ${bestRun.top_k}` : 'N/A'}</div>
          <div className="mt-1 break-words text-sm text-on-surface-variant">{bestRun ? `${formatNumber(bestRun.h2lScore)} ${metric}` : 'artifact missing'}</div>
          <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">ค่า top-k ที่ให้คะแนน H2L สูงสุดใน source และ metric ที่กำลังดูอยู่</p>
        </div>
        <div className={`min-w-0 rounded-xl p-4 ${Number.isFinite(activeDelta) && activeDelta >= 0 ? 'bg-teal-50 dark:bg-teal-950/40' : 'bg-yellow-50 dark:bg-yellow-950/40'}`}>
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Delta vs Baseline</div>
          <div className="mt-2 font-headline text-2xl font-extrabold text-on-surface">{activeDeltaLabel}</div>
          <div className="mt-1 break-words text-sm text-on-surface-variant">{bestDeltaRun ? `best gain Top ${bestDeltaRun.top_k}` : 'no paired value'}</div>
          <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">ค่าเป็นบวกแปลว่า H2L สูงกว่า baseline ใน top-k ที่กำลังโฟกัส</p>
        </div>
        <div className="min-w-0 rounded-xl bg-surface-container-low p-4">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Reading Rule</div>
          <div className="mt-2 text-sm font-bold text-on-surface">{source === 'gold' ? 'Reference problems from ground truth' : 'System-detected problems from the case text'}</div>
          <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">ใช้ source เดียวกันทั้ง plot และค่าอ่านด้านล่างเพื่อลดความสับสน: `detected` คือผลหลักของระบบ, ส่วน `reference` คือมุมมองเพดานบนเพื่อเทียบศักยภาพ retrieval</p>
        </div>
      </div>

      <div className="mt-4 grid gap-2 md:grid-cols-4">
        {plottedRuns.map((run) => {
          const topK = Number(run.top_k);
          const isSelected = topK === Number(selectedTopK);
          const missing = !Number.isFinite(run.h2lScore);
          return (
            <button
              className={`rounded-lg border px-3 py-2 text-left transition-all ${isSelected ? 'border-teal-600 bg-teal-50 text-teal-950 shadow-sm dark:bg-teal-950/40 dark:text-teal-100' : 'border-outline-variant/20 bg-surface-container-low text-on-surface hover:border-teal-500/50'}`}
              disabled={missing}
              key={`strip-${source}-${topK}`}
              onClick={() => {
                setFocusedTopK(topK);
                onSelectTopK?.(topK);
              }}
              type="button"
            >
              <span className="block truncate text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Top {topK}</span>
              <span className="mt-1 block truncate font-headline text-lg font-extrabold">{missing ? 'N/A' : formatNumber(run.h2lScore)}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function PairComparisonBarChart({ pairs, selectedNdcgKey }) {
  const [metric, setMetric] = useState('MAP');
  const [activeFamily, setActiveFamily] = useState(pairs[0]?.family || '');
  const metricOptions = [
    {
      id: 'MAP',
      label: 'MAP',
      base: (pair) => Number(pair.base_quality),
      h2l: (pair) => Number(pair.h2l_quality),
      meaning: 'วัดคุณภาพ ranking ตลอดรายการ ยิ่งสูงยิ่งดี',
    },
    {
      id: 'MRR',
      label: 'MRR',
      base: (pair) => Number(pair.base_mrr),
      h2l: (pair) => Number(pair.h2l_mrr),
      meaning: 'ดูว่าเจอหลักฐานที่เกี่ยวข้องชิ้นแรกเร็วแค่ไหน',
    },
    {
      id: selectedNdcgKey,
      label: selectedNdcgKey,
      base: (pair) => Number(selectedNdcgKey === 'nDCG@10' ? pair.base_ndcg_at_10 : pair.base_ndcg_at_5),
      h2l: (pair) => Number(selectedNdcgKey === 'nDCG@10' ? pair.h2l_ndcg_at_10 : pair.h2l_ndcg_at_5),
      meaning: `ดูคุณภาพการจัดอันดับใน ${selectedNdcgKey.replace('nDCG@', 'top ')} อันดับแรก`,
    },
  ];
  const metricOption = metricOptions.find((item) => item.id === metric) || metricOptions[0];
  const rows = pairs
    .map((pair) => {
      const base = metricOption.base(pair);
      const h2l = metricOption.h2l(pair);
      return {
        ...pair,
        base,
        h2l,
        delta: Number.isFinite(base) && Number.isFinite(h2l) ? h2l - base : NaN,
      };
    })
    .filter((pair) => Number.isFinite(pair.base) || Number.isFinite(pair.h2l));
  const resolvedActiveFamily = rows.some((pair) => pair.family === activeFamily) ? activeFamily : rows[0]?.family;
  const activeRow = rows.find((pair) => pair.family === resolvedActiveFamily) || rows[0] || null;
  const maxValue = rows.length
    ? Math.max(0.01, ...rows.flatMap((pair) => [pair.base, pair.h2l]).filter((value) => Number.isFinite(value)))
    : 1;
  const widthPct = (value) => {
    if (!Number.isFinite(value) || maxValue <= 0) return '0%';
    return `${Math.max(6, Math.min(100, (value / maxValue) * 100))}%`;
  };

  return (
    <div className="rounded-xl border border-outline-variant/20 bg-surface-container-lowest p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Comparison Bar Chart</div>
          <h3 className="mt-1 break-words font-headline text-xl font-extrabold text-on-surface">Baseline vs H2L by Family</h3>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-on-surface-variant">กดแต่ละคู่เพื่อดูว่า H2L ดีกว่าหรือด้อยกว่าตรงไหนใน metric เดียวกัน</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {metricOptions.map((item) => (
            <button
              className={`rounded-lg px-3 py-2 text-xs font-bold transition-all ${metric === item.id ? 'bg-teal-600 text-white shadow-sm' : 'bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high'}`}
              key={item.id}
              onClick={() => setMetric(item.id)}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-4 grid gap-4 2xl:grid-cols-[minmax(0,1.35fr)_minmax(340px,0.8fr)]">
        <div className="space-y-3">
          {rows.map((pair) => {
            const isActive = pair.family === activeRow?.family;
            const deltaPositive = Number(pair.delta) >= 0;
            return (
              <button
                className={`w-full rounded-xl border p-4 text-left transition-all ${isActive ? 'border-teal-600 bg-teal-50 shadow-sm dark:bg-teal-950/40' : 'border-outline-variant/20 bg-surface-container-low hover:border-teal-500/40'}`}
                key={`pair-bar-${pair.family}`}
                onClick={() => setActiveFamily(pair.family)}
                onMouseEnter={() => setActiveFamily(pair.family)}
                type="button"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">{pair.label || pair.family}</div>
                    <div className="mt-1 text-sm font-bold text-on-surface">{metricOption.label} delta {Number.isFinite(pair.delta) ? `${pair.delta >= 0 ? '+' : ''}${formatNumber(pair.delta)}` : 'N/A'}</div>
                  </div>
                  <span className={`rounded px-2 py-1 text-[10px] font-bold ${deltaPositive ? 'bg-teal-600 text-white' : 'bg-yellow-500 text-slate-950'}`}>
                    {Number.isFinite(pair.delta) ? (deltaPositive ? 'H2L higher' : 'Baseline higher') : 'missing'}
                  </span>
                </div>

                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <div>
                    <div className="flex items-center justify-between gap-2 text-[11px] font-bold uppercase tracking-widest text-on-surface-variant">
                      <span>Baseline</span>
                      <span>{Number.isFinite(pair.base) ? formatNumber(pair.base) : 'N/A'}</span>
                    </div>
                    <div className="mt-2 h-3 rounded-full bg-surface-container-high">
                      <div className="h-3 rounded-full bg-slate-500 dark:bg-slate-300" style={{ width: widthPct(pair.base) }} />
                    </div>
                  </div>
                  <div>
                    <div className="flex items-center justify-between gap-2 text-[11px] font-bold uppercase tracking-widest text-on-surface-variant">
                      <span>H2L</span>
                      <span>{Number.isFinite(pair.h2l) ? formatNumber(pair.h2l) : 'N/A'}</span>
                    </div>
                    <div className="mt-2 h-3 rounded-full bg-surface-container-high">
                      <div className="h-3 rounded-full bg-gradient-to-r from-teal-600 to-cyan-400" style={{ width: widthPct(pair.h2l) }} />
                    </div>
                  </div>
                </div>
                <div className="mt-3 grid gap-2 text-xs text-on-surface-variant md:grid-cols-3">
                  <div className="rounded-lg bg-surface-container-lowest p-2.5">base: <span className="font-bold text-on-surface">{pair.base_strategy}</span></div>
                  <div className="rounded-lg bg-surface-container-lowest p-2.5">h2l: <span className="font-bold text-on-surface">{pair.h2l_strategy}</span></div>
                  <div className="rounded-lg bg-surface-container-lowest p-2.5">delta: <span className={`font-bold ${deltaPositive ? 'text-teal-700 dark:text-teal-200' : 'text-yellow-900 dark:text-yellow-100'}`}>{Number.isFinite(pair.delta) ? `${pair.delta >= 0 ? '+' : ''}${formatNumber(pair.delta)}` : 'N/A'}</span></div>
                </div>
              </button>
            );
          })}
          {!rows.length && (
            <div className="rounded-xl bg-surface-container-low p-4 text-sm text-on-surface-variant">
              ยังไม่มี comparison pair artifact ที่พร้อมทำ bar chart
            </div>
          )}
        </div>

        <div className="space-y-3">
          <div className="rounded-xl bg-surface-container-low p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Active Pair</div>
            <div className="mt-2 break-words font-headline text-2xl font-extrabold text-on-surface">{activeRow?.label || 'N/A'}</div>
            <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">{metricOption.meaning}</p>
          </div>
          <div className={`rounded-xl p-4 ${Number(activeRow?.delta) >= 0 ? 'bg-teal-50 dark:bg-teal-950/40' : 'bg-yellow-50 dark:bg-yellow-950/40'}`}>
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Metric Readout</div>
            <div className="mt-2 font-headline text-3xl font-extrabold text-on-surface">
              {Number.isFinite(activeRow?.delta) ? `${Number(activeRow.delta) >= 0 ? '+' : ''}${formatNumber(activeRow.delta)}` : 'N/A'}
            </div>
            <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">
              {Number.isFinite(activeRow?.delta)
                ? Number(activeRow.delta) >= 0
                  ? 'ค่า H2L สูงกว่า baseline ใน metric ที่กำลังดูอยู่'
                  : 'ค่า baseline ยังสูงกว่า H2L ใน metric ที่กำลังดูอยู่'
                : 'ยังไม่มีค่าพอสำหรับสรุปคู่ที่เลือก'}
            </p>
          </div>
          <div className="rounded-xl bg-surface-container-low p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Quick Reading</div>
            <div className="mt-3 space-y-2 text-sm text-on-surface-variant">
              <div className="break-words rounded-lg bg-surface-container-lowest p-3">
                baseline {activeRow?.base_strategy || 'N/A'} = {Number.isFinite(activeRow?.base) ? formatNumber(activeRow.base) : 'N/A'}
              </div>
              <div className="break-words rounded-lg bg-surface-container-lowest p-3">
                h2l {activeRow?.h2l_strategy || 'N/A'} = {Number.isFinite(activeRow?.h2l) ? formatNumber(activeRow.h2l) : 'N/A'}
              </div>
              <div className="break-words rounded-lg bg-surface-container-lowest p-3">
                {activeRow?.interpretation || 'ยังไม่มีข้อความตีความจาก artifact'}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function QualityTradeoffScatter({ rows, selectedNdcgKey }) {
  const [xMetric, setXMetric] = useState('MAP');
  const [activeStrategy, setActiveStrategy] = useState(rows[0]?.strategy || '');
  const xOptions = [
    { id: 'MAP', label: 'MAP' },
    { id: 'MRR', label: 'MRR' },
    { id: selectedNdcgKey, label: selectedNdcgKey },
  ];
  const chart = { left: 62, right: 698, top: 32, bottom: 336 };
  const plottedRows = rows
    .map((row) => ({
      ...row,
      xValue: Number(row[xMetric]),
      yValue: Number(row.retrieval_time),
    }))
    .filter((row) => Number.isFinite(row.xValue) && Number.isFinite(row.yValue));
  const resolvedActiveStrategy = plottedRows.some((row) => row.strategy === activeStrategy) ? activeStrategy : plottedRows[0]?.strategy;
  const activePoint = plottedRows.find((row) => row.strategy === resolvedActiveStrategy) || plottedRows[0] || null;
  const xValues = plottedRows.map((row) => row.xValue);
  const yValues = plottedRows.map((row) => row.yValue);
  const minX = xValues.length ? Math.max(0, Math.min(...xValues) - 0.02) : 0;
  const maxX = xValues.length ? Math.min(1, Math.max(...xValues) + 0.02) : 1;
  const minY = yValues.length ? Math.min(...yValues) : 0;
  const maxY = yValues.length ? Math.max(...yValues) : 1;
  const chartWidth = chart.right - chart.left;
  const chartHeight = chart.bottom - chart.top;
  const xFor = (value) => {
    if (!Number.isFinite(value) || Math.abs(maxX - minX) < 0.000001) return chart.left + chartWidth / 2;
    return chart.left + ((value - minX) / (maxX - minX)) * chartWidth;
  };
  const yFor = (value) => {
    if (!Number.isFinite(value) || Math.abs(maxY - minY) < 0.000001) return chart.top + chartHeight / 2;
    const speedScore = (maxY - value) / Math.max(0.000001, maxY - minY);
    return chart.bottom - (speedScore * chartHeight);
  };
  const yTicks = [minY, minY + ((maxY - minY) / 2), maxY].filter((value, index, array) => index === 0 || Math.abs(value - array[index - 1]) > 0.000001);
  const xTicks = [minX, minX + ((maxX - minX) / 2), maxX];
  const normalizedQuality = (value) => {
    if (!Number.isFinite(value) || Math.abs(maxX - minX) < 0.000001) return 0.5;
    return (value - minX) / Math.max(0.000001, maxX - minX);
  };
  const normalizedSpeed = (value) => {
    if (!Number.isFinite(value) || Math.abs(maxY - minY) < 0.000001) return 0.5;
    return (maxY - value) / Math.max(0.000001, maxY - minY);
  };
  const tradeoffScore = (row) => (normalizedQuality(row.xValue) * 0.72) + (normalizedSpeed(row.yValue) * 0.28);
  const bestBaseline = [...plottedRows]
    .filter((row) => row.group !== 'H2L-enhanced')
    .sort((a, b) => tradeoffScore(b) - tradeoffScore(a))[0] || null;
  const bestH2L = [...plottedRows]
    .filter((row) => row.group === 'H2L-enhanced')
    .sort((a, b) => tradeoffScore(b) - tradeoffScore(a))[0] || null;
  const highlightTone = (kind) => (kind === 'baseline'
    ? { ring: '#f59e0b', fill: '#fbbf24', text: '#92400e', badge: 'bg-amber-100 text-amber-950 dark:bg-amber-950/50 dark:text-amber-100' }
    : { ring: '#0f766e', fill: '#14b8a6', text: '#0f766e', badge: 'bg-teal-100 text-teal-950 dark:bg-teal-950/50 dark:text-teal-100' });
  const highlightMap = new Map();
  if (bestBaseline) highlightMap.set(bestBaseline.strategy, { kind: 'baseline', label: 'Best Baseline' });
  if (bestH2L) highlightMap.set(bestH2L.strategy, { kind: 'h2l', label: 'Best H2L' });
  const visibleLabels = [...plottedRows]
    .filter((row) => row.strategy === activePoint?.strategy || highlightMap.has(row.strategy))
    .map((row) => {
      const highlight = highlightMap.get(row.strategy);
      const isH2L = row.group === 'H2L-enhanced';
      const labelText = highlight ? `${highlight.label}: ${strategyDisplayName(row.strategy)}` : strategyDisplayName(row.strategy);
      return {
        strategy: row.strategy,
        x: xFor(row.xValue),
        y: yFor(row.yValue),
        labelText,
        labelTone: highlight?.kind || (isH2L ? 'h2l' : 'baseline'),
        isHighlighted: Boolean(highlight),
      };
    })
    .sort((a, b) => a.x - b.x);
  const placedLabels = visibleLabels.reduce((acc, label) => {
    const estimatedWidth = Math.max(82, Math.min(220, label.labelText.length * 6.8 + 22));
    const estimatedHeight = 24;
    let centerX = label.x;
    let baselineY = label.y - (label.isHighlighted ? 28 : 22);
    acc.forEach((placed, placedIndex) => {
      const horizontalOverlap = Math.abs(centerX - placed.centerX) < ((estimatedWidth + placed.width) / 2) + 10;
      const verticalOverlap = Math.abs(baselineY - placed.baselineY) < estimatedHeight + 10;
      if (horizontalOverlap && verticalOverlap) {
        const direction = placedIndex % 2 === 0 ? -1 : 1;
        baselineY += direction * (estimatedHeight + 10);
      }
    });
    centerX = Math.max(chart.left + (estimatedWidth / 2) + 6, Math.min(chart.right - (estimatedWidth / 2) - 6, centerX));
    baselineY = Math.max(chart.top + 16, Math.min(chart.bottom - 12, baselineY));
    acc.push({
      ...label,
      width: estimatedWidth,
      height: estimatedHeight,
      centerX,
      baselineY,
    });
    return acc;
  }, []);
  const quadrantLabels = [
    { x: chart.left + 12, y: chart.top + 18, text: 'เร็วแต่คุณภาพยังต่ำ', anchor: 'start', className: 'text-[10px] font-bold text-on-surface-variant' },
    { x: chart.right - 12, y: chart.top + 18, text: 'คุณภาพสูง + เร็ว', anchor: 'end', className: 'text-[10px] font-bold text-teal-700 dark:text-teal-200' },
    { x: chart.left + 12, y: chart.bottom - 10, text: 'ช้าและคุณภาพต่ำ', anchor: 'start', className: 'text-[10px] font-bold text-on-surface-variant' },
    { x: chart.right - 12, y: chart.bottom - 10, text: 'คุณภาพดีแต่ใช้เวลามาก', anchor: 'end', className: 'text-[10px] font-bold text-on-surface-variant' },
  ];

  return (
    <div className="rounded-xl border border-outline-variant/20 bg-surface-container-lowest p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Scatter Plot</div>
          <h3 className="mt-1 break-words font-headline text-xl font-extrabold text-on-surface">Quality vs Time Balance</h3>
          <p className="mt-1 max-w-3xl text-sm leading-relaxed text-on-surface-variant">แกน X คือ quality metric ที่เลือก ส่วนแกน Y คือ retrieval time ซึ่งกลับทิศไว้ให้จุดที่อยู่สูงกว่าแปลว่าเร็วกว่า ขวาบนจึงคือโซนที่สมดุลดีที่สุด</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {xOptions.map((item) => (
            <button
              className={`rounded-lg px-3 py-2 text-xs font-bold transition-all ${xMetric === item.id ? 'bg-slate-900 text-white shadow-sm dark:bg-slate-100 dark:text-slate-950' : 'bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high'}`}
              key={item.id}
              onClick={() => setXMetric(item.id)}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl bg-surface-container-low p-4">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Axis X</div>
          <div className="mt-2 font-headline text-lg font-extrabold text-on-surface">{xMetric}</div>
          <p className="mt-1 text-xs leading-relaxed text-on-surface-variant">ซ้าย = ค่าต่ำกว่า, ขวา = ค่าสูงกว่า</p>
        </div>
        <div className="rounded-xl bg-surface-container-low p-4">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Axis Y</div>
          <div className="mt-2 font-headline text-lg font-extrabold text-on-surface">Retrieval Time</div>
          <p className="mt-1 text-xs leading-relaxed text-on-surface-variant">บน = เร็วกว่า, ล่าง = ช้ากว่า</p>
        </div>
        <div className="rounded-xl bg-surface-container-low p-4">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Realtime Highlights</div>
          <div className="mt-2 flex flex-wrap gap-2 text-xs">
            <span className={`rounded px-2 py-1 font-bold ${highlightTone('baseline').badge}`}>{bestBaseline ? strategyDisplayName(bestBaseline.strategy) : 'No baseline'}</span>
            <span className={`rounded px-2 py-1 font-bold ${highlightTone('h2l').badge}`}>{bestH2L ? strategyDisplayName(bestH2L.strategy) : 'No H2L'}</span>
          </div>
          <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">สองจุดที่กระพริบคือ baseline ที่สมดุลดีที่สุดและ H2L ที่สมดุลดีที่สุดภายใต้ metric ที่เลือก</p>
        </div>
        <div className="rounded-xl bg-surface-container-low p-4">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">How To Read</div>
          <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">ถ้าจุดขยับไปทางขวาแปลว่าคุณภาพดีขึ้น ถ้าขยับขึ้นบนแปลว่าใช้เวลาน้อยลง การเลือกจุดดูแบบคู่ช่วยตอบได้ว่าโมเดลดีขึ้นเพราะ rank ดีขึ้นจริงหรือเพราะเร็วกว่า</p>
        </div>
      </div>

      <div className="mt-4 space-y-4">
        <div className="overflow-hidden rounded-xl border border-outline-variant/20 bg-surface-container-low p-3 sm:p-4">
          <svg
            aria-label="Quality and time scatter plot"
            className="h-[28rem] w-full md:h-[32rem]"
            preserveAspectRatio="none"
            role="img"
            viewBox="0 0 760 400"
          >
            <defs>
              <linearGradient id="scatter-good-zone" x1="0" x2="1" y1="0" y2="1">
                <stop offset="0%" stopColor="#14b8a6" stopOpacity="0.18" />
                <stop offset="100%" stopColor="#0ea5e9" stopOpacity="0.02" />
              </linearGradient>
            </defs>
            <rect x={chart.left} y={chart.top} width={chartWidth} height={chartHeight} rx="10" className="topk-plot-stage" />
            <rect x={chart.left + chartWidth / 2} y={chart.top} width={chartWidth / 2} height={chartHeight / 2} fill="url(#scatter-good-zone)" rx="10" />
            <line x1={chart.left + chartWidth / 2} x2={chart.left + chartWidth / 2} y1={chart.top} y2={chart.bottom} className="topk-grid-line" strokeDasharray="8 8" />
            <line x1={chart.left} x2={chart.right} y1={chart.top + chartHeight / 2} y2={chart.top + chartHeight / 2} className="topk-grid-line" strokeDasharray="8 8" />
            {yTicks.map((tick, index) => (
              <g key={`scatter-y-${index}`}>
                <line x1={chart.left} x2={chart.right} y1={yFor(tick)} y2={yFor(tick)} className="topk-grid-line" strokeOpacity="0.28" />
                <text x="12" y={yFor(tick) + 4} fill="currentColor" className="text-[11px] font-bold text-on-surface-variant">{formatNumber(tick, 4)}s</text>
              </g>
            ))}
            {xTicks.map((tick, index) => (
              <g key={`scatter-x-${index}`}>
                <line x1={xFor(tick)} x2={xFor(tick)} y1={chart.top} y2={chart.bottom} className="topk-grid-line" strokeOpacity="0.18" />
                <text x={xFor(tick)} y={chart.bottom + 26} fill="currentColor" textAnchor="middle" className="text-[11px] font-bold text-on-surface-variant">{formatNumber(tick)}</text>
              </g>
            ))}
            <text x={chart.left - 34} y={chart.top + 4} fill="currentColor" className="text-[11px] font-bold text-on-surface-variant">เร็ว</text>
            <text x={chart.left - 34} y={chart.bottom + 4} fill="currentColor" className="text-[11px] font-bold text-on-surface-variant">ช้า</text>
            <text x={chart.left + chartWidth / 2} y={chart.bottom + 42} fill="currentColor" textAnchor="middle" className="text-[11px] font-bold text-on-surface-variant">{xMetric} สูงขึ้น →</text>
            {quadrantLabels.map((item) => (
              <text key={`${item.text}-${item.x}-${item.y}`} x={item.x} y={item.y} fill="currentColor" textAnchor={item.anchor} className={item.className}>{item.text}</text>
            ))}
            {plottedRows.map((row) => {
              const isActive = row.strategy === activePoint?.strategy;
              const isH2L = row.group === 'H2L-enhanced';
              const highlight = highlightMap.get(row.strategy);
              const highlightStyle = highlight ? highlightTone(highlight.kind) : null;
              return (
                <g key={`scatter-${row.strategy}`}>
                  {highlightStyle && (
                    <circle cx={xFor(row.xValue)} cy={yFor(row.yValue)} fill="none" opacity="0.42" r="14" stroke={highlightStyle.ring} strokeWidth="2.4">
                      <animate attributeName="r" dur="1.5s" repeatCount="indefinite" values="11;22;11" />
                      <animate attributeName="opacity" dur="1.5s" repeatCount="indefinite" values="0.55;0.05;0.55" />
                    </circle>
                  )}
                  {isActive && !highlightStyle && (
                    <circle cx={xFor(row.xValue)} cy={yFor(row.yValue)} fill="none" opacity="0.28" r="18" className="topk-point-ring" strokeWidth="2">
                      <animate attributeName="r" dur="1.7s" repeatCount="indefinite" values="14;24;14" />
                      <animate attributeName="opacity" dur="1.7s" repeatCount="indefinite" values="0.3;0.04;0.3" />
                    </circle>
                  )}
                  <circle
                    aria-label={`${row.strategy}: ${xMetric} ${formatNumber(row.xValue)}, retrieval time ${formatNumber(row.yValue, 4)} seconds`}
                    className="cursor-pointer transition-all"
                    cx={xFor(row.xValue)}
                    cy={yFor(row.yValue)}
                    fill={isH2L ? '#14b8a6' : '#64748b'}
                    onClick={() => setActiveStrategy(row.strategy)}
                    onFocus={() => setActiveStrategy(row.strategy)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        setActiveStrategy(row.strategy);
                      }
                    }}
                    onMouseEnter={() => setActiveStrategy(row.strategy)}
                    r={highlightStyle ? 9 : isActive ? 9 : 6}
                    stroke={highlightStyle?.ring || (isH2L ? '#0f766e' : '#334155')}
                    strokeWidth="2"
                    role="button"
                    tabIndex="0"
                  />
                </g>
              );
            })}
            {placedLabels.map((label) => {
              const tone = label.labelTone === 'h2l' ? highlightTone('h2l') : label.labelTone === 'baseline' ? highlightTone('baseline') : null;
              const fillColor = tone ? tone.text : 'currentColor';
              const pointerStroke = tone ? tone.ring : '#64748b';
              const rectFill = tone ? `${tone.fill}22` : '#0f172a12';
              return (
                <g key={`scatter-label-${label.strategy}`}>
                  <line
                    x1={label.x}
                    x2={label.centerX}
                    y1={label.y - 8}
                    y2={label.baselineY - 6}
                    stroke={pointerStroke}
                    strokeOpacity="0.35"
                    strokeWidth="1.5"
                  />
                  <rect
                    x={label.centerX - (label.width / 2)}
                    y={label.baselineY - label.height + 3}
                    width={label.width}
                    height={label.height}
                    rx="8"
                    fill={rectFill}
                    stroke={pointerStroke}
                    strokeOpacity="0.18"
                  />
                  <text
                    x={label.centerX}
                    y={label.baselineY - 6}
                    textAnchor="middle"
                    fill={fillColor}
                    className="text-[11px] font-bold"
                  >
                    {label.labelText}
                  </text>
                </g>
              );
            })}
          </svg>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs font-bold text-on-surface-variant">
            <span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-teal-500" />H2L-enhanced</span>
            <span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-slate-500" />Baseline</span>
            <span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-amber-400" />Best Baseline</span>
            <span>แกน Y ถูกกลับทิศเพื่อให้อยู่สูงขึ้นเมื่อเร็วกว่า</span>
          </div>
          <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {plottedRows.map((row) => {
              const isActive = row.strategy === activePoint?.strategy;
              const isH2L = row.group === 'H2L-enhanced';
              return (
                <button
                  className={`rounded-lg border px-3 py-2 text-left text-xs transition-all ${isActive ? 'border-teal-600 bg-teal-50 text-teal-950 dark:bg-teal-950/40 dark:text-teal-100' : 'border-outline-variant/20 bg-surface-container-low text-on-surface hover:border-teal-500/40'}`}
                  key={`scatter-chip-${row.strategy}`}
                  onClick={() => setActiveStrategy(row.strategy)}
                  type="button"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-bold">{strategyDisplayName(row.strategy)}</span>
                    <span className={`h-2.5 w-2.5 rounded-full ${isH2L ? 'bg-teal-500' : 'bg-slate-500'}`} />
                  </div>
                  <div className="mt-1 text-[11px] text-on-surface-variant">{xMetric} {formatNumber(row.xValue)} · {formatNumber(row.yValue, 4)}s</div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid gap-3 lg:grid-cols-3">
          <div className="rounded-xl bg-surface-container-low p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Selected Strategy</div>
            <div className="mt-2 break-words font-headline text-2xl font-extrabold text-on-surface">{strategyDisplayName(activePoint?.strategy)}</div>
            <div className="mt-2 text-sm text-on-surface-variant">{activePoint?.group === 'H2L-enhanced' ? 'กลุ่ม H2L-enhanced' : 'กลุ่ม Baseline'}</div>
            <div className="mt-3 grid gap-2 text-xs text-on-surface-variant">
              <div className="rounded-lg bg-surface-container-lowest p-3">{xMetric}: <span className="font-bold text-on-surface">{Number.isFinite(activePoint?.xValue) ? formatNumber(activePoint.xValue) : 'N/A'}</span></div>
              <div className="rounded-lg bg-surface-container-lowest p-3">time: <span className="font-bold text-on-surface">{Number.isFinite(activePoint?.yValue) ? formatNumber(activePoint.yValue, 4) : 'N/A'}s</span></div>
            </div>
          </div>
          <div className="rounded-xl bg-surface-container-low p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Best Baseline</div>
            <div className="mt-2 break-words font-headline text-2xl font-extrabold text-on-surface">{strategyDisplayName(bestBaseline?.strategy)}</div>
            <div className="mt-2 text-sm text-on-surface-variant">{bestBaseline ? `${xMetric} ${formatNumber(bestBaseline.xValue)} · ${formatNumber(bestBaseline.yValue, 4)}s` : 'ยังไม่มี baseline rows'}</div>
            <div className="mt-3 rounded-lg bg-surface-container-lowest p-3 text-xs leading-relaxed text-on-surface-variant">
              ใช้เป็น baseline ตัวแทนของจุดที่คุณภาพและเวลา balance ดีที่สุดในกลุ่ม baseline สำหรับ metric ที่เลือก
            </div>
          </div>
          <div className="rounded-xl bg-surface-container-low p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Best H2L</div>
            <div className="mt-2 break-words font-headline text-2xl font-extrabold text-on-surface">{strategyDisplayName(bestH2L?.strategy)}</div>
            <div className="mt-2 text-sm text-on-surface-variant">{bestH2L ? `${xMetric} ${formatNumber(bestH2L.xValue)} · ${formatNumber(bestH2L.yValue, 4)}s` : 'ยังไม่มี H2L rows'}</div>
            <div className="mt-3 rounded-lg bg-surface-container-lowest p-3 text-xs leading-relaxed text-on-surface-variant">
              ถ้าจุดนี้อยู่ขวากว่าและยังสูงพอ แปลว่า H2L รุ่นนั้นรักษาคุณภาพที่ดีขึ้นได้โดยไม่แลกกับเวลาเกินจำเป็น
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ProblemDocumentMatrix({ caseText, problems, docs }) {
  const topProblems = useMemo(
    () => [...(problems || [])].sort((a, b) => Number(b.confidence || 0) - Number(a.confidence || 0)).slice(0, 6),
    [problems],
  );
  const topDocs = useMemo(
    () => [...(docs || [])].slice(0, 6),
    [docs],
  );
  const matrixCells = useMemo(() => topProblems.flatMap((problem) => (
    topDocs.map((doc) => {
      const evidence = (doc.matched_problem_evidence || []).find((item) => item.code === problem.code) || null;
      const keywordCount = (evidence?.matched_keywords || []).length;
      const nameCount = (evidence?.matched_name_terms || []).length;
      const supportScore = keywordCount + nameCount;
      const normalized = evidence ? Math.max(0.16, Math.min(1, supportScore / 5 || 0.2)) : 0;
      return {
        id: `${problem.code}__${doc.id}`,
        problem,
        doc,
        evidence,
        supportScore,
        normalized,
      };
    })
  )), [topDocs, topProblems]);
  const strongestCell = matrixCells
    .filter((cell) => cell.evidence)
    .sort((a, b) => b.supportScore - a.supportScore || Number(a.doc.rank || 999) - Number(b.doc.rank || 999))[0] || null;
  const [selection, setSelection] = useState({ type: 'cell', problemCode: strongestCell?.problem.code || topProblems[0]?.code || '', docId: strongestCell?.doc.id || topDocs[0]?.id || '' });
  const activeCell = matrixCells.find((cell) => cell.problem.code === selection.problemCode && cell.doc.id === selection.docId) || strongestCell || null;
  const activeProblem = topProblems.find((problem) => problem.code === selection.problemCode) || activeCell?.problem || topProblems[0] || null;
  const activeDoc = topDocs.find((doc) => doc.id === selection.docId) || activeCell?.doc || topDocs[0] || null;
  const rowSupportCount = (problemCode) => matrixCells.filter((cell) => cell.problem.code === problemCode && cell.evidence).length;
  const colSupportCount = (docId) => matrixCells.filter((cell) => cell.doc.id === docId && cell.evidence).length;
  const docCoverageLeader = [...topDocs]
    .sort((a, b) => colSupportCount(b.id) - colSupportCount(a.id) || Number(a.rank || 999) - Number(b.rank || 999))[0] || null;
  const problemCoverageLeader = [...topProblems]
    .sort((a, b) => rowSupportCount(b.code) - rowSupportCount(a.code) || Number(b.confidence || 0) - Number(a.confidence || 0))[0] || null;
  const activeModeLabel = activeCell?.evidence ? 'มีหลักฐานรองรับ' : 'ยังไม่พบการเชื่อมตรง';

  return (
    <div className="rounded-xl border border-outline-variant/20 bg-surface-container-lowest p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Problem-Document Matrix</div>
          <h3 className="mt-1 break-words font-headline text-xl font-extrabold text-on-surface">Case Evidence Structure</h3>
          <p className="mt-1 max-w-3xl text-sm leading-relaxed text-on-surface-variant">
            มุมมองนี้ต่างจาก Semantic Evidence Map ตรงที่เน้นว่า problem ไหนมี evidence doc หนุนอยู่กี่ชิ้นและหนุนแรงแค่ไหน โดยไม่ลงรายละเอียด semantic distance
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatusBadge label={`${topProblems.length} problems`} tone={topProblems.length ? 'live' : 'warning'} />
          <StatusBadge label={`${topDocs.length} docs`} tone={topDocs.length ? 'live' : 'warning'} />
          <StatusBadge label={strongestCell ? 'matrix ready' : 'no support links'} tone={strongestCell ? 'live' : 'warning'} />
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <div className="rounded-xl bg-surface-container-low p-4">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Case Query</div>
          <p className="mt-2 text-sm leading-relaxed text-on-surface">{compactText(caseText, 180) || 'ไม่มีข้อความเคส'}</p>
        </div>
        <div className="rounded-xl bg-surface-container-low p-4">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Most Supported Problem</div>
          <div className="mt-2 font-headline text-lg font-extrabold text-on-surface">{problemCoverageLeader?.code || 'N/A'}</div>
          <p className="mt-1 text-sm leading-relaxed text-on-surface-variant">
            {problemCoverageLeader ? `${problemCoverageLeader.name || 'ไม่ระบุชื่อ'} · support ${rowSupportCount(problemCoverageLeader.code)} docs` : 'ยังไม่มี problem ที่เชื่อมกับ evidence'}
          </p>
        </div>
        <div className="rounded-xl bg-surface-container-low p-4">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Most Reused Document</div>
          <div className="mt-2 font-headline text-lg font-extrabold text-on-surface">{docCoverageLeader ? `D${docCoverageLeader.rank}` : 'N/A'}</div>
          <p className="mt-1 text-sm leading-relaxed text-on-surface-variant">
            {docCoverageLeader ? `${compactText(docCoverageLeader.title || docCoverageLeader.source || 'ไม่ระบุชื่อ', 42)} · support ${colSupportCount(docCoverageLeader.id)} problems` : 'ยังไม่มี evidence doc ที่เชื่อมกับ problem'}
          </p>
        </div>
      </div>

      <div className="mt-4 grid gap-4 2xl:grid-cols-[minmax(0,1.2fr)_minmax(340px,0.82fr)]">
        <div className="overflow-hidden rounded-xl border border-outline-variant/20 bg-surface-container-low p-3 sm:p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Matrix Reading</div>
              <p className="mt-1 text-xs leading-relaxed text-on-surface-variant">แถว = problem, คอลัมน์ = evidence doc, ช่องสีเข้ม = support มากกว่า</p>
            </div>
            <div className="flex items-center gap-2 text-[11px] font-bold text-on-surface-variant">
              <span className="rounded bg-surface-container-high px-2 py-1">ไม่มี support</span>
              <span className="rounded bg-teal-100 px-2 py-1 text-teal-900 dark:bg-teal-950/60 dark:text-teal-100">support ต่ำ</span>
              <span className="rounded bg-teal-600 px-2 py-1 text-white">support สูง</span>
            </div>
          </div>
          <div className="overflow-x-auto">
            <div
              className="grid gap-2"
              style={{
                gridTemplateColumns: `minmax(210px, 1.3fr) repeat(${Math.max(1, topDocs.length)}, minmax(110px, 1fr))`,
                minWidth: `${Math.max(560, 240 + (topDocs.length * 120))}px`,
              }}
            >
              <div className="rounded-lg bg-surface-container-high px-3 py-3 text-[11px] font-bold uppercase tracking-widest text-on-surface-variant">Problem \\ Doc</div>
              {topDocs.map((doc) => {
                const isSelectedCol = selection.docId === doc.id;
                return (
                  <button
                    className={`rounded-lg px-3 py-3 text-left transition-all ${isSelectedCol ? 'bg-sky-100 text-sky-950 shadow-sm dark:bg-sky-950/50 dark:text-sky-100' : 'bg-surface-container-high text-on-surface hover:bg-surface-container'}`}
                    key={`matrix-doc-${doc.id}`}
                    onClick={() => setSelection({ type: 'doc', problemCode: activeProblem?.code || topProblems[0]?.code || '', docId: doc.id })}
                    type="button"
                  >
                    <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">D{doc.rank}</div>
                    <div className="mt-1 text-xs font-bold leading-snug">{compactText(doc.title || doc.source || `Doc ${doc.rank}`, 28)}</div>
                    <div className="mt-2 text-[10px] text-on-surface-variant">support {colSupportCount(doc.id)}</div>
                  </button>
                );
              })}

              {topProblems.map((problem) => (
                <React.Fragment key={`matrix-row-${problem.code}`}>
                  <button
                    className={`rounded-lg px-3 py-3 text-left transition-all ${selection.problemCode === problem.code ? 'bg-teal-50 text-teal-950 shadow-sm dark:bg-teal-950/40 dark:text-teal-100' : 'bg-surface-container-high text-on-surface hover:bg-surface-container'}`}
                    onClick={() => setSelection({ type: 'problem', problemCode: problem.code, docId: activeDoc?.id || topDocs[0]?.id || '' })}
                    type="button"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-headline text-sm font-extrabold">{problem.code}</span>
                      <span className="rounded bg-surface-container-lowest px-2 py-0.5 text-[10px] font-bold text-on-surface-variant">{rowSupportCount(problem.code)} docs</span>
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-on-surface-variant">{compactText(problem.name, 70)}</p>
                  </button>
                  {topDocs.map((doc) => {
                    const cell = matrixCells.find((item) => item.problem.code === problem.code && item.doc.id === doc.id);
                    const isActive = activeCell?.id === cell?.id;
                    const hasEvidence = Boolean(cell?.evidence);
                    const intensity = cell?.normalized || 0;
                    const bgStyle = hasEvidence
                      ? { backgroundColor: `rgba(20, 184, 166, ${Math.max(0.12, intensity * 0.78)})` }
                      : undefined;
                    return (
                      <button
                        className={`min-h-[88px] rounded-lg border px-3 py-3 text-left transition-all ${isActive ? 'border-teal-600 ring-2 ring-teal-600/20' : 'border-outline-variant/20'} ${hasEvidence ? 'text-slate-950 dark:text-white' : 'bg-surface-container-lowest text-on-surface-variant hover:bg-surface-container'}`}
                        key={cell?.id || `${problem.code}-${doc.id}`}
                        onClick={() => setSelection({ type: 'cell', problemCode: problem.code, docId: doc.id })}
                        style={bgStyle}
                        type="button"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[10px] font-bold uppercase tracking-widest">{hasEvidence ? 'linked' : 'empty'}</span>
                          <span className="text-[11px] font-bold">{hasEvidence ? `${cell.supportScore}` : '0'}</span>
                        </div>
                        <div className="mt-2 text-xs leading-relaxed">
                          {hasEvidence ? `${(cell.evidence?.matched_keywords || []).length} keyword · ${(cell.evidence?.matched_name_terms || []).length} name` : 'ไม่มี support ตรง'}
                        </div>
                      </button>
                    );
                  })}
                </React.Fragment>
              ))}
            </div>
          </div>
        </div>

        <div className="space-y-3">
          <div className="rounded-xl bg-surface-container-low p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Selected Relation</div>
                <div className="mt-2 font-headline text-2xl font-extrabold text-on-surface">
                  {activeProblem?.code || 'N/A'} ↔ {activeDoc ? `D${activeDoc.rank}` : 'N/A'}
                </div>
              </div>
              <StatusBadge label={activeModeLabel} tone={activeCell?.evidence ? 'live' : 'warning'} />
            </div>
            <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">
              {activeCell?.evidence
                ? 'ช่องนี้บอกว่าเอกสารชิ้นนี้มี evidence ที่ระบบจับได้ว่าสนับสนุน problem code นี้โดยตรง'
                : 'ช่องนี้ยังไม่พบหลักฐานเชิงปัญหาที่เชื่อม problem กับ doc โดยตรง แม้ doc อาจยังอยู่ในผล retrieval'}
            </p>
          </div>

          <div className="rounded-xl bg-surface-container-low p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Problem View</div>
            <div className="mt-2 text-sm font-bold text-on-surface">{activeProblem?.code || 'N/A'} · {activeProblem?.name || 'ไม่ระบุชื่อ'}</div>
            <div className="mt-3 grid gap-2 text-sm text-on-surface-variant">
              <div className="rounded-lg bg-surface-container-lowest p-3">confidence <span className="font-bold text-on-surface">{formatPercent(activeProblem?.confidence)}</span></div>
              <div className="rounded-lg bg-surface-container-lowest p-3">support docs <span className="font-bold text-on-surface">{activeProblem ? rowSupportCount(activeProblem.code) : 0}</span></div>
              <div className="rounded-lg bg-surface-container-lowest p-3">{compactText(activeProblem?.reasoning || problemInterpretation(activeProblem || {}), 220)}</div>
            </div>
          </div>

          <div className="rounded-xl bg-surface-container-low p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Document View</div>
            <div className="mt-2 text-sm font-bold text-on-surface">{activeDoc ? `D${activeDoc.rank}` : 'N/A'} · {compactText(activeDoc?.title || activeDoc?.source || 'ไม่ระบุชื่อเอกสาร', 52)}</div>
            <div className="mt-3 grid gap-2 text-sm text-on-surface-variant">
              <div className="rounded-lg bg-surface-container-lowest p-3">support problems <span className="font-bold text-on-surface">{activeDoc ? colSupportCount(activeDoc.id) : 0}</span></div>
              <div className="rounded-lg bg-surface-container-lowest p-3">score <span className="font-bold text-on-surface">{formatNumber(activeDoc?.h2l_final_score ?? activeDoc?.score, 3)}</span></div>
              <div className="break-words rounded-lg bg-surface-container-lowest p-3">{compactText(activeDoc?.snippet || activeDoc?.content, 220) || 'ไม่มี snippet'}</div>
            </div>
          </div>

          <div className="rounded-xl bg-surface-container-low p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Cell Evidence</div>
            {activeCell?.evidence ? (
              <div className="mt-3 space-y-2 text-sm text-on-surface-variant">
                <div className="rounded-lg bg-surface-container-lowest p-3">matched keywords <span className="font-bold text-on-surface">{(activeCell.evidence.matched_keywords || []).join(', ') || 'ไม่มี'}</span></div>
                <div className="rounded-lg bg-surface-container-lowest p-3">matched name terms <span className="font-bold text-on-surface">{(activeCell.evidence.matched_name_terms || []).join(', ') || 'ไม่มี'}</span></div>
                <div className="rounded-lg bg-surface-container-lowest p-3">support score <span className="font-bold text-on-surface">{activeCell.supportScore}</span></div>
              </div>
            ) : (
              <div className="mt-3 rounded-lg bg-surface-container-lowest p-3 text-sm leading-relaxed text-on-surface-variant">
                doc นี้ยังไม่ถูกบันทึกว่า support problem นี้โดยตรง จึงเหมาะใช้ดูช่องว่างของ retrieval มากกว่าการยืนยันเชิงหลักฐาน
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function EvaluationTab({ displayResult, evaluationSummary, runtimeStatus, selectedTopK, onSelectTopK, onRefreshPerformance, evaluationLastSyncedAt }) {
  const summary = displayResult.evaluation_summary || evaluationSummary || {};
  const proper = summary.proper_eval || {};
  const polarity = summary.polarity_eval || {};
  const research = summary.research_report || {};
  const dataSources = summary.data_sources || {};
  const datasetInfo = dataSources.dataset || research.provenance?.dataset || {};
  const freshness = dataSources.freshness || research.provenance?.freshness || {};
  const reviewActions = dataSources.review_actions || research.provenance?.review_actions || {};
  const evaluationProgress = dataSources.evaluation_progress || summary.evaluation_progress || {};
  const artifactInventory = dataSources.artifact_inventory || summary.artifact_inventory || {};
  const thesisProtocol = summary.thesis_protocol || {};
  const sensitivity = research.sensitivity || {};
  const problemSourceRuns = summary.benchmark?.problem_source_runs || research.problem_source_runs || {};
  const problemSourceRunRows = Object.values(problemSourceRuns || {}).filter((run) => ['detected', 'gold'].includes(run?.problem_source));
  const docScaling = summary.benchmark?.doc_scaling || research.doc_scaling || {};
  const fullStrategyReference = summary.benchmark?.full_strategy_reference || research.full_strategy_reference || {};
  const isolatedPairRuns = summary.benchmark?.isolated_pair_runs || research.isolated_pair_runs || {};
  const docScalingRuns = docScaling.runs || [];
  const docScalingBySource = docScaling.by_problem_source || {};
  const detectedDocScalingRuns = docScalingBySource.detected || [];
  const selectedExperimentTopK = Number(selectedTopK || displayResult.top_k || proper.top_k || DEFAULT_DOC_TOP_K);
  const selectedGoldRun = docScalingRuns.find((run) => run.problem_source === 'gold' && Number(run.top_k) === selectedExperimentTopK);
  const selectedDetectedRun = docScalingRuns.find((run) => run.problem_source === 'detected' && Number(run.top_k) === selectedExperimentTopK);
  const selectedReportRun = selectedDetectedRun || selectedGoldRun || null;
  const selectedReportRows = selectedReportRun?.rows || [];
  const selectedH2LRow = selectedReportRows.find((row) => row.strategy === 'h2l-hybrid') || {};
  const selectedBaseRow = selectedReportRows.find((row) => row.strategy === 'basic') || {};
  const selectedReportDelta = selectedReportRun?.delta_h2l_minus_basic || {};
  const selectedReportAvailable = Boolean(selectedReportRun);
  const selectedNdcgKey = selectedExperimentTopK >= 10 ? 'nDCG@10' : 'nDCG@5';
  const selectedMetric = (key, fallback = null) => (
    Number.isFinite(Number(selectedH2LRow[key])) ? Number(selectedH2LRow[key]) : fallback
  );
  let experimentDiagnostics = summary.benchmark?.experiment_diagnostics || research.experiment_diagnostics || {};
  if (selectedReportRun?.experiment_diagnostics?.pairs?.length) {
    experimentDiagnostics = selectedReportRun.experiment_diagnostics;
  }
  const experimentPair = experimentDiagnostics.pairs?.[0] || null;
  const diagnosticMetrics = experimentPair?.metrics || [];
  const detectorGapRun = detectedDocScalingRuns.find((run) => Number(run.top_k) === selectedExperimentTopK) || null;
  const detectorGap = detectorGapRun?.detector_gap || {};
  const currentProblemSource = selectedReportRun?.problem_source || proper.problem_source || experimentDiagnostics.metadata?.problem_source || 'legacy';
  const benchmarkScopeLabel = selectedReportRun?.problem_source === 'gold' ? 'upper-bound benchmark' : 'test split benchmark';
  const benchmarkSourceLabel = selectedReportRun?.source || proper.source || research.provenance?.benchmark?.source || 'ยังไม่มี benchmark artifact';
  const benchmarkUpdatedAt = selectedReportRun?.timestamp || proper.timestamp || freshness.proper_eval_timestamp || null;
  const datasetSource = datasetInfo.source || research.dataset_source || 'expanded_ground_truth.json';
  const benchmarkNeedsRefresh = Boolean(freshness.needs_review);
  const benchmarkFreshnessLabel = benchmarkNeedsRefresh ? 'benchmark needs review' : 'benchmark current';
  const polaritySourceLabel = polarity.source || 'ยังไม่มี polarity artifact';
  const polarityUpdatedAt = polarity.timestamp || freshness.polarity_eval_timestamp || null;
  const evaluationSyncLabel = evaluationLastSyncedAt ? formatDateTime(evaluationLastSyncedAt) : 'ยังไม่ sync';
  const properEvalProgress = evaluationProgress.proper_eval || {};
  const polarityEvalProgress = evaluationProgress.sentence_polarity || {};
  const progressRunning = evaluationProgress.status === 'running';
  const categoryDiagnostics = [...(experimentPair?.by_category || [])]
    .filter((row) => Number(row.n_cases) > 0)
    .sort((a, b) => Math.abs(Number(b.MAP?.delta_mean || 0)) - Math.abs(Number(a.MAP?.delta_mean || 0)))
    .slice(0, 6);
  const significantDiagnosticMetrics = diagnosticMetrics.filter((row) => row.paired_test?.significant);
  const runtime = runtimeStatus || {};
  const metrics = displayResult.metrics || {};
  const candidateTrace = displayResult.candidate_trace || {};
  const reviewSummary = displayResult.review_summary || displayResult.detection_info?.review_summary || {};
  const polarityRows = displayResult.polarity_effect?.rows || [];
  const h2lTrace = displayResult.h2l_scoring_trace || [];
  const currentCaseReady = displayResult.status === 'ok';
  const sensitivityEntries = Object.entries(sensitivity || {});
  const metricWinner = (baseValue, h2lValue, higherIsBetter = true) => {
    const base = Number(baseValue);
    const h2l = Number(h2lValue);
    if (!Number.isFinite(base) || !Number.isFinite(h2l)) {
      return { winner: 'N/A', label: 'ไม่มีข้อมูล', diff: null, className: 'bg-surface-container-high text-on-surface-variant' };
    }
    const diff = h2l - base;
    if (Math.abs(diff) < 0.000001) {
      return { winner: 'Tie', label: 'เสมอ', diff, className: 'bg-surface-container-high text-on-surface' };
    }
    const h2lWins = higherIsBetter ? h2l > base : h2l < base;
    return {
      winner: h2lWins ? 'H2L' : 'Baseline',
      label: h2lWins ? 'H2L ชนะ' : 'Baseline ชนะ',
      diff,
      className: h2lWins ? 'bg-teal-50 text-teal-800 dark:bg-teal-950/40 dark:text-teal-100' : 'bg-yellow-50 text-yellow-900 dark:bg-yellow-950/40 dark:text-yellow-100',
    };
  };
  const selectedQualityDeltas = [selectedReportDelta.MAP, selectedReportDelta.MRR, selectedReportDelta[selectedNdcgKey]]
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
  const selectedQualityWins = {
    h2l: selectedQualityDeltas.filter((value) => value > 0.000001).length,
    baseline: selectedQualityDeltas.filter((value) => value < -0.000001).length,
    tie: selectedQualityDeltas.filter((value) => Math.abs(value) <= 0.000001).length,
  };
  const selectedHybridPair = selectedReportAvailable ? {
    family: 'hybrid',
    label: `Hybrid Top ${selectedExperimentTopK}`,
    base_strategy: 'basic',
    h2l_strategy: 'h2l-hybrid',
    base_quality: selectedBaseRow.MAP,
    h2l_quality: selectedH2LRow.MAP,
    quality_delta: selectedReportDelta.MAP,
    base_time: selectedBaseRow.retrieval_time,
    h2l_time: selectedH2LRow.retrieval_time,
    time_delta: selectedReportDelta.retrieval_time,
    base_mrr: selectedBaseRow.MRR,
    h2l_mrr: selectedH2LRow.MRR,
    base_ndcg_at_5: selectedBaseRow[selectedNdcgKey],
    h2l_ndcg_at_5: selectedH2LRow[selectedNdcgKey],
    base_ndcg_at_10: selectedBaseRow['nDCG@10'],
    h2l_ndcg_at_10: selectedH2LRow['nDCG@10'],
    base_p_at_5: selectedBaseRow['P@5'],
    h2l_p_at_5: selectedH2LRow['P@5'],
    base_f1_at_5: selectedBaseRow['F1@5'],
    h2l_f1_at_5: selectedH2LRow['F1@5'],
    case_diagnostics: { quality_metric_wins: selectedQualityWins, metrics: [] },
    interpretation: `อ่านจาก artifact ${selectedReportRun.problem_source} ที่ top_k ${selectedExperimentTopK}`,
  } : null;
  const pairHasData = (pair) => Number.isFinite(Number(pair?.base_quality)) && Number.isFinite(Number(pair?.h2l_quality));
  const isolatedPairComparisonPairs = (isolatedPairRuns.comparison_pairs || []).filter(pairHasData);
  const isolatedPairRows = isolatedPairRuns.rows || [];
  const fullReferencePairs = (fullStrategyReference.comparison_pairs || []).filter(pairHasData);
  const benchmarkPairs = (summary.benchmark?.comparison_pairs || []).filter(pairHasData);
  const usingIsolatedPairRuns = isolatedPairComparisonPairs.length >= 2;
  const usingFullReferencePairs = fullReferencePairs.length >= 2;
  const comparisonTopK = usingIsolatedPairRuns
    ? Number(isolatedPairRuns.top_k || selectedExperimentTopK)
    : usingFullReferencePairs
    ? Number(fullStrategyReference.top_k || selectedExperimentTopK)
    : selectedExperimentTopK;
  const comparisonProblemSource = usingIsolatedPairRuns
    ? isolatedPairRuns.problem_source || currentProblemSource
    : usingFullReferencePairs
    ? fullStrategyReference.problem_source || 'legacy'
    : currentProblemSource;
  const reportComparisonPairs = usingIsolatedPairRuns
    ? isolatedPairComparisonPairs
    : fullReferencePairs.length >= 2
    ? fullReferencePairs
    : benchmarkPairs.length >= 2
      ? benchmarkPairs
      : selectedHybridPair
        ? [selectedHybridPair]
        : [];
  const comparisonSourceLabel = usingIsolatedPairRuns
    ? `isolated pair reruns · ${comparisonProblemSource} top ${comparisonTopK}`
    : usingFullReferencePairs
    ? `${comparisonProblemSource} top ${comparisonTopK} full matrix`
    : benchmarkPairs.length >= 2
      ? `${comparisonProblemSource} top ${comparisonTopK} matrix`
      : selectedHybridPair
        ? `${selectedReportRun.problem_source} hybrid pair`
        : 'no pair artifact';
  const comparisonTableRows = usingIsolatedPairRuns
    ? isolatedPairRows
    : usingFullReferencePairs
    ? fullStrategyReference.rows || []
    : selectedReportRows;
  const comparisonNdcgKey = comparisonTopK >= 10 ? 'nDCG@10' : 'nDCG@5';
  const strongestPair = reportComparisonPairs.length
    ? [...reportComparisonPairs].sort((a, b) => Number(b.quality_delta || 0) - Number(a.quality_delta || 0))[0]
    : null;
  const bestRowBy = (field, higherIsBetter = true) => {
    const validRows = comparisonTableRows.filter((row) => Number.isFinite(Number(row[field])));
    if (!validRows.length) return null;
    return [...validRows].sort((a, b) => higherIsBetter ? Number(b[field]) - Number(a[field]) : Number(a[field]) - Number(b[field]))[0];
  };
  const standoutRows = [
    { label: 'MAP สูงสุด', field: 'MAP', row: bestRowBy('MAP'), meaning: `จาก ${comparisonSourceLabel}` },
    { label: 'MRR สูงสุด', field: 'MRR', row: bestRowBy('MRR'), meaning: `จาก ${comparisonSourceLabel}` },
    { label: 'nDCG สูงสุด', field: comparisonNdcgKey, row: bestRowBy(comparisonNdcgKey), meaning: `จาก ${comparisonSourceLabel}` },
    { label: 'เร็วสุด', field: 'retrieval_time', row: bestRowBy('retrieval_time', false), meaning: 'ใช้เวลาน้อยกว่า' },
  ];
  const pairQualityWins = (pair) => pair?.case_diagnostics?.quality_metric_wins || {};
  const h2lHelpfulPairs = reportComparisonPairs.filter((pair) => Number(pairQualityWins(pair).h2l || 0) > Number(pairQualityWins(pair).baseline || 0));
  const baselineConcernPairs = reportComparisonPairs.filter((pair) => Number(pairQualityWins(pair).baseline || 0) > Number(pairQualityWins(pair).h2l || 0));
  const balancedPairs = reportComparisonPairs.filter((pair) => Number(pairQualityWins(pair).baseline || 0) === Number(pairQualityWins(pair).h2l || 0));
  const benchmarkInsightCards = [
    {
      id: 'h2l_advantage',
      eyebrow: 'H2L Advantage Areas',
      title: 'คู่ที่ H2L ช่วยด้านคุณภาพ ranking',
      tone: 'bg-teal-50 dark:bg-teal-950/40',
      description: `อ่านจาก ${comparisonSourceLabel}; ใช้ MAP, MRR และ ${selectedNdcgKey} เป็นแกนหลักของคุณภาพ ranking`,
      items: h2lHelpfulPairs,
      empty: 'artifact นี้ยังไม่มีคู่ที่ H2L ชนะคุณภาพชัดเจน',
    },
    {
      id: 'baseline_advantage',
      eyebrow: 'Baseline Advantage Areas',
      title: 'คู่ที่ baseline ยังนำอยู่',
      tone: 'bg-yellow-50 dark:bg-yellow-950/40',
      description: 'ถ้า H2L แพ้ มักสะท้อนว่าการดัน problem-aware signal ยังไม่ตรง relevance judge หรือ detector ยังส่งปัญหาไม่ครบ',
      items: baselineConcernPairs,
      empty: 'ไม่มีคู่ที่ baseline นำด้านคุณภาพใน artifact นี้',
    },
    {
      id: 'benchmark_synthesis',
      eyebrow: 'Benchmark Synthesis',
      title: 'ข้อสรุปที่ใช้เขียนผลได้อย่างมืออาชีพ',
      tone: 'bg-surface-container-lowest',
      description: 'ใช้ผลแบบจับคู่ใน test split เพื่อสรุปว่า H2L ช่วย backbone ใดบ้าง และต้องระวังการสรุปเกินจริงเมื่อ delta ยังเล็กหรือยังไม่ผ่าน significance',
      footer: `คู่ที่ผลสูสี: ${balancedPairs.length ? balancedPairs.map((pair) => pair.label || pair.family).join(', ') : 'ไม่มี'}`,
    },
  ];
  const experimentChecklist = [
    {
      id: 'proper_eval',
      icon: 'fact_check',
      title: 'ยืนยันผลรอบล่าสุด',
      status: selectedReportAvailable ? 'done' : 'todo',
      state: selectedReportAvailable ? 'พร้อม' : 'ค้าง',
      summary: selectedReportAvailable
        ? `artifact ${currentProblemSource} · ${selectedReportRun.num_cases ?? 'N/A'} cases · top ${selectedExperimentTopK}`
        : `ยังไม่พบ proper evaluation สำหรับ top ${selectedExperimentTopK}`,
      why: 'ก่อนเขียนผล ต้องแน่ใจว่า artifact ที่ใช้สรุปเป็นผลจริงหลังแก้ detector และตั้งค่า top_k ตรงกับที่จะรายงาน',
      next: selectedReportAvailable
        ? 'ถ้ามีการแก้ detector หรือ retriever หลัง artifact นี้ ควรรัน proper evaluation ซ้ำอีกครั้ง'
        : `รัน proper evaluation ที่ top ${selectedExperimentTopK} สำหรับชุดที่ต้องใช้เขียนผล`,
    },
    {
      id: 'problem_source',
      icon: 'compare_arrows',
      title: 'แยก detector ออกจาก scoring',
      status: problemSourceRuns.gold && problemSourceRuns.detected ? 'done' : 'todo',
      state: problemSourceRuns.gold && problemSourceRuns.detected ? 'พร้อม' : 'ค้าง',
      summary: problemSourceRuns.gold && problemSourceRuns.detected
        ? 'มีทั้ง gold และ detected runs'
        : 'ยังไม่มี run แยก gold vs detected ครบ',
      why: 'หัวข้อนี้ตอบให้ได้ว่าถ้า H2L ยังแพ้หรือชนะ สาเหตุมาจาก detector ส่งปัญหา หรือมาจาก retrieval/scoring กันแน่',
      next: problemSourceRuns.gold && problemSourceRuns.detected
        ? 'ใช้ delta ของ gold เทียบ detected เพื่อเขียน discussion เรื่อง detector gap'
        : 'รันทั้ง --problem-source detected และ --problem-source gold',
    },
    {
      id: 'significance',
      icon: 'query_stats',
      title: 'ทดสอบนัยสำคัญ',
      status: diagnosticMetrics.length ? 'done' : 'todo',
      state: diagnosticMetrics.length ? 'พร้อม' : 'ค้าง',
      summary: diagnosticMetrics.length
        ? `${significantDiagnosticMetrics.length}/${diagnosticMetrics.length} metrics มีนัยสำคัญ`
        : 'ยังไม่มี paired significance / CI',
      why: 'ช่วยกันการสรุปแรงเกินไปเมื่อค่าเฉลี่ยต่างกันนิดเดียว แต่ความไม่แน่นอนยังสูง',
      next: diagnosticMetrics.length
        ? 'ใช้เฉพาะ metric ที่มี paired test และ CI รองรับเมื่อเขียนคำว่า “ดีกว่า”'
        : 'สร้าง experiment_diagnostics ที่มี paired test, bootstrap CI และ Bayesian signed-rank',
    },
    {
      id: 'category_analysis',
      icon: 'category',
      title: 'วิเคราะห์ตามหมวดปัญหา',
      status: categoryDiagnostics.length ? 'done' : 'todo',
      state: categoryDiagnostics.length ? 'พร้อม' : 'ค้าง',
      summary: categoryDiagnostics.length
        ? `มี category rows ${experimentPair?.by_category?.length ?? categoryDiagnostics.length} กลุ่ม`
        : 'ยังไม่มี category-level diagnostics',
      why: 'ทำให้ discussion จับต้องได้ว่า H2L ช่วยกับกลุ่มไหน และยังเสียกับกลุ่มไหน',
      next: categoryDiagnostics.length
        ? 'เลือก 2-3 กลุ่มที่ดีขึ้น และ 1-2 กลุ่มที่ยังแพ้ไปเขียนอภิปราย'
        : 'รัน evaluator ที่ export by-category diagnostics',
    },
    {
      id: 'doc_scaling',
      icon: 'tune',
      title: 'ตรวจผลตาม top-k',
      status: docScalingRuns.length
        ? ((docScaling.missing_top_k || []).length || (docScaling.missing_by_problem_source?.detected || []).length || (docScaling.missing_by_problem_source?.gold || []).length ? 'partial' : 'done')
        : 'todo',
      state: docScalingRuns.length
        ? ((docScaling.missing_top_k || []).length || (docScaling.missing_by_problem_source?.detected || []).length || (docScaling.missing_by_problem_source?.gold || []).length ? 'บางส่วน' : 'พร้อม')
        : 'ค้าง',
      summary: docScalingRuns.length
        ? `กำลังอ่าน top ${selectedExperimentTopK}; available: ${docScaling.available_top_k?.join(', ') || 'N/A'}`
        : 'ยังไม่มี doc scaling artifact',
      why: 'ช่วยยืนยันว่าผลของ H2L ไม่ได้เกิดจากการเลือก top_k ที่เข้าทางเพียงค่าเดียว',
      next: docScalingRuns.length
        ? 'เลือก top_k หลักที่จะรายงาน และชี้แจงว่าค่านี้คงเส้นคงวาหรือไวต่อ scaling แค่ไหน'
        : 'รัน doc scaling อย่างน้อย top 5, 10, 15, 20',
    },
  ];
  const checklistCounts = experimentChecklist.reduce((acc, item) => {
    acc[item.status] = (acc[item.status] || 0) + 1;
    return acc;
  }, { done: 0, partial: 0, todo: 0 });
  const [activeChecklistFilter, setActiveChecklistFilter] = useState('open');
  const [activeChecklistId, setActiveChecklistId] = useState('');
  const checklistFilters = [
    { id: 'open', label: 'ต้องทำต่อ', count: (checklistCounts.partial || 0) + (checklistCounts.todo || 0) },
    { id: 'all', label: 'ทั้งหมด', count: experimentChecklist.length },
    { id: 'done', label: 'พร้อมแล้ว', count: checklistCounts.done || 0 },
  ];
  const filteredChecklist = experimentChecklist.filter((item) => {
    if (activeChecklistFilter === 'done') return item.status === 'done';
    if (activeChecklistFilter === 'open') return item.status !== 'done';
    return true;
  });
  const fallbackChecklist = filteredChecklist.find((item) => item.status !== 'done')
    || filteredChecklist[0]
    || experimentChecklist[0]
    || null;
  const activeChecklist = filteredChecklist.find((item) => item.id === activeChecklistId)
    || experimentChecklist.find((item) => item.id === activeChecklistId)
    || fallbackChecklist;
  const checklistTone = (status) => (
    status === 'done' ? 'live' : status === 'partial' ? 'warning' : 'neutral'
  );
  const checklistCardTone = (status, isActive) => {
    if (isActive) return 'border-teal-600 bg-teal-50 text-teal-950 shadow-sm dark:bg-teal-950/40 dark:text-teal-100';
    if (status === 'done') return 'border-emerald-500/30 bg-emerald-50 text-emerald-950 dark:bg-emerald-950/25 dark:text-emerald-100';
    if (status === 'partial') return 'border-yellow-500/30 bg-yellow-50 text-yellow-950 dark:bg-yellow-950/25 dark:text-yellow-100';
    return 'border-outline-variant/20 bg-surface-container-low text-on-surface hover:border-teal-500/40';
  };
  const ablationLabel = (row) => row?.alpha ?? row?.variant ?? 'N/A';
  const ablationBaselineRow = (key, rows) => {
    if (!rows?.length) return null;
    if (key === 'alpha') return rows.find((row) => String(row.alpha) === '0.0') || rows[0];
    if (key === 'l2_filtering') return rows.find((row) => String(row.variant || '').toLowerCase().includes('l1 only')) || rows[0];
    if (key === 'matching_method') return rows.find((row) => String(row.variant || '').toLowerCase().includes('keyword')) || rows[0];
    if (key === 'prior') return rows.find((row) => String(row.variant || '').toLowerCase().includes('uniform')) || rows[0];
    return rows[0];
  };
  const ablationQuestion = (key) => ({
    alpha: 'ควรให้น้ำหนัก H2L มากแค่ไหน',
    l2_filtering: 'L2 semantic validation ช่วยเพิ่มผลไหม',
    matching_method: 'จับคู่แบบ semantic ดีกว่า keyword ตรง ๆ ไหม',
    prior: 'ใช้ severity prior ดีกว่า uniform prior ไหม',
  }[key] || 'องค์ประกอบนี้ส่งผลต่อคะแนนอย่างไร');
  const ablationTakeaway = (key, block, baselineRow) => {
    const best = block.best || {};
    const bestName = ablationLabel(best);
    const baseName = ablationLabel(baselineRow);
    const mapDelta = Number(best.map) - Number(baselineRow?.map);
    const ndcgDelta = Number(best.ndcg_at_k) - Number(baselineRow?.ndcg_at_k);
    const hasDelta = Number.isFinite(mapDelta) || Number.isFinite(ndcgDelta);
    if (!block.rows?.length || !block.best) return 'ยังไม่มีข้อมูลทดลองจริงสำหรับสรุปผลส่วนนี้';
    if (hasDelta && Math.abs(mapDelta || 0) < 0.000001 && Math.abs(ndcgDelta || 0) < 0.000001) {
      return `${bestName} และ ${baseName} ให้ผลใกล้เคียงกันใน artifact นี้ จึงควรอ่านว่า “ยังไม่เห็นความต่างชัด” มากกว่าจะสรุปว่าชนะเด็ดขาด`;
    }
    if (key === 'alpha') return `ค่า ${bestName} ให้ผลดีที่สุดใน artifact นี้ เมื่อเทียบกับ alpha ${baseName}; ใช้เพื่อเลือกน้ำหนัก H2L ที่ไม่แรงเกินจำเป็น`;
    if (key === 'l2_filtering') return `${bestName} ให้ผลดีที่สุดเมื่อเทียบกับ ${baseName}; ใช้อธิบายว่า semantic validation ส่งผลต่อการจัดอันดับหรือไม่`;
    if (key === 'matching_method') return `${bestName} ให้ผลดีที่สุดเมื่อเทียบกับ ${baseName}; ถ้าคะแนนสูงกว่า แปลว่า semantic matching จับความหมายได้ดีกว่า keyword ตรงตัว`;
    if (key === 'prior') return `${bestName} ให้ผลดีที่สุดเมื่อเทียบกับ ${baseName}; ใช้ดูว่า prior จากความรุนแรงช่วยจัดอันดับเอกสารหรือไม่`;
    return `${bestName} ให้ผลดีที่สุดเมื่อเทียบกับ ${baseName} ใน artifact นี้`;
  };
  const protocolReadinessItems = thesisProtocol.readiness_items || [];
  const protocolMetricGroups = Object.entries(thesisProtocol.metric_policy || {});
  const baselineLimitationRows = thesisProtocol.baseline_limitations || [];
  const capacityChecks = thesisProtocol.capacity_checks || [];

  return (
    <div className="space-y-6">
      <section className="relative overflow-hidden rounded-xl bg-primary-container p-6 text-white">
        <div className="relative z-10 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="font-headline text-lg font-bold">Evaluation Design for Thesis</h2>
            <p className="mt-1 text-sm italic text-slate-300">แยกการประเมินเป็น 2 ส่วน: เคสที่กำลังวิเคราะห์ และชุดทดลอง/ทดสอบที่มี artifact จริง</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              className="rounded-lg bg-white/12 px-3 py-2 text-xs font-bold text-white transition-colors hover:bg-white/18"
              onClick={() => onRefreshPerformance?.()}
              type="button"
            >
              {reviewActions.refresh_label || 'Reload Performance Snapshot'}
            </button>
            <StatusBadge label={runtime.status === 'ready' ? 'Runtime Ready' : runtime.status === 'degraded' ? 'Runtime Degraded' : 'Model Loading'} tone={statusTone(runtime.status)} />
            <StatusBadge label={summary.benchmark?.source ? 'Research Artifacts Loaded' : 'Artifacts Missing'} tone={summary.benchmark?.source ? 'live' : 'warning'} />
            <StatusBadge label={benchmarkFreshnessLabel} tone={benchmarkNeedsRefresh ? 'warning' : 'live'} />
          </div>
        </div>
      </section>

      <section className="rounded-xl bg-surface-container-low p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Performance Provenance</div>
            <h2 className="mt-1 font-headline text-lg font-bold text-on-surface">ผลบนหน้านี้มาจาก runtime เคสปัจจุบันหรือจาก benchmark test split</h2>
            <p className="mt-2 max-w-4xl text-sm leading-relaxed text-on-surface-variant">
              {research.interpretation || 'Research Report จะแยกผลจากเคสปัจจุบันออกจากผล benchmark บน test split เพื่อไม่ให้ตีความข้ามระดับกัน'}
            </p>
          </div>
        <div className="flex flex-wrap gap-2">
          <StatusBadge label={datasetInfo.split_mode || 'split field'} tone="neutral" />
          <StatusBadge label={benchmarkScopeLabel} tone={selectedReportRun?.problem_source === 'gold' ? 'warning' : 'live'} />
          <StatusBadge label={isolatedPairRuns.status === 'ready' ? 'isolated pairs current' : isolatedPairRuns.status === 'partial' ? 'isolated pairs partial' : 'isolated pairs missing'} tone={isolatedPairRuns.status === 'ready' ? 'live' : isolatedPairRuns.status === 'partial' ? 'warning' : 'neutral'} />
        </div>
      </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-4">
          <div className="rounded-lg bg-surface-container-lowest p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Dataset Split</div>
            <div className="mt-2 font-headline text-2xl font-extrabold text-on-surface">{datasetInfo.train_count ?? research.train_count ?? 'N/A'} / {datasetInfo.test_count ?? research.test_count ?? 'N/A'}</div>
            <p className="mt-1 text-xs leading-relaxed text-on-surface-variant">train / test จาก {datasetSource}</p>
          </div>
          <div className="rounded-lg bg-surface-container-lowest p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Ground Truth Updated</div>
            <div className="mt-2 font-headline text-lg font-extrabold text-on-surface">{formatDateTime(datasetInfo.dataset_updated_at || research.dataset_updated_at)}</div>
            <p className="mt-1 text-xs leading-relaxed text-on-surface-variant">{datasetInfo.source_note || research.ground_truth_note}</p>
          </div>
          <div className="rounded-lg bg-surface-container-lowest p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Benchmark Artifact</div>
            <div className="mt-2 font-headline text-lg font-extrabold text-on-surface">{formatDateTime(benchmarkUpdatedAt)}</div>
            <p className="mt-1 text-xs leading-relaxed text-on-surface-variant break-words">{benchmarkSourceLabel}</p>
          </div>
          <div className={`rounded-lg p-4 ${benchmarkNeedsRefresh ? 'bg-yellow-50 text-yellow-950 dark:bg-yellow-950/40 dark:text-yellow-100' : 'bg-teal-50 text-teal-950 dark:bg-teal-950/40 dark:text-teal-100'}`}>
            <div className="text-[10px] font-bold uppercase tracking-widest">Review Status</div>
            <div className="mt-2 font-headline text-lg font-extrabold">{benchmarkNeedsRefresh ? 'Needs Review' : 'Current'}</div>
            <p className="mt-1 text-xs leading-relaxed">{freshness.interpretation || reviewActions.note || 'กด reload เพื่ออ่าน performance snapshot ล่าสุดจาก artifact จริง'}</p>
          </div>
        </div>

        <div className="mt-4 grid gap-3 xl:grid-cols-3">
          <div className="rounded-lg bg-surface-container-lowest p-4">
            <div className="flex flex-wrap items-center gap-2">
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Benchmark Provenance</div>
              <StatusBadge label={shortArtifactLabel(benchmarkSourceLabel)} tone="neutral" />
            </div>
            <p className="mt-2 break-words text-sm leading-relaxed text-on-surface">{benchmarkSourceLabel}</p>
            <p className="mt-2 text-xs text-on-surface-variant">artifact time {formatDateTime(benchmarkUpdatedAt)}</p>
          </div>
          <div className="rounded-lg bg-surface-container-lowest p-4">
            <div className="flex flex-wrap items-center gap-2">
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Polarity Provenance</div>
              <StatusBadge label={shortArtifactLabel(polaritySourceLabel)} tone="neutral" />
            </div>
            <p className="mt-2 break-words text-sm leading-relaxed text-on-surface">{polaritySourceLabel}</p>
            <p className="mt-2 text-xs text-on-surface-variant">artifact time {formatDateTime(polarityUpdatedAt)}</p>
          </div>
          <div className="rounded-lg bg-surface-container-lowest p-4">
            <div className="flex flex-wrap items-center gap-2">
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Live Sync</div>
              <StatusBadge label="auto refresh active" tone="live" />
            </div>
            <p className="mt-2 text-sm leading-relaxed text-on-surface">หน้า report จะอ่าน `/evaluation-summary` ซ้ำอัตโนมัติเมื่อเปิดใช้งาน เพื่อสะท้อน artifact ล่าสุดจากดิสก์โดยไม่สร้างค่าจำลองขึ้นมาเอง</p>
            <p className="mt-2 text-xs text-on-surface-variant">last synced {evaluationSyncLabel}</p>
          </div>
        </div>

        <div className="mt-4 grid gap-3 xl:grid-cols-3">
          <div className={`rounded-lg p-4 ${progressRunning ? 'bg-teal-50 text-teal-950 dark:bg-teal-950/40 dark:text-teal-100' : 'bg-surface-container-lowest'}`}>
            <div className="flex flex-wrap items-center gap-2">
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Live Evaluation Progress</div>
              <StatusBadge label={evaluationProgress.status || 'idle'} tone={progressRunning ? 'live' : evaluationProgress.status === 'error' ? 'error' : 'neutral'} />
            </div>
            <div className="mt-3 grid gap-2 text-xs text-on-surface-variant">
              <div className="rounded-lg bg-surface-container-low p-3">
                proper eval <span className="font-bold text-on-surface">{progressCountLabel(properEvalProgress.completed_case_count, properEvalProgress.total_case_count)}</span>
                <div className="mt-1 break-words">{properEvalProgress.current_strategy ? `${properEvalProgress.current_strategy} · ${properEvalProgress.phase || 'running'}` : properEvalProgress.phase || 'idle'}</div>
              </div>
              <div className="rounded-lg bg-surface-container-low p-3">
                polarity <span className="font-bold text-on-surface">{progressCountLabel(polarityEvalProgress.completed_case_count, polarityEvalProgress.total_case_count)}</span>
                <div className="mt-1 break-words">{polarityEvalProgress.current_case_id || polarityEvalProgress.phase || 'idle'}</div>
              </div>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">{evaluationProgress.interpretation || 'ตัวเลขนี้มาจาก progress artifact ที่ evaluator เขียนระหว่างรันจริง'}</p>
          </div>
          <div className="rounded-lg bg-surface-container-lowest p-4">
            <div className="flex flex-wrap items-center gap-2">
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Artifact Retention</div>
              <StatusBadge label={`proper ${artifactInventory.proper_eval_history_count ?? 0}`} tone="neutral" />
            </div>
            <div className="mt-3 grid gap-2 text-xs text-on-surface-variant">
              <div className="rounded-lg bg-surface-container-low p-3">proper history <span className="font-bold text-on-surface">{artifactInventory.proper_eval_history_count ?? 0}</span></div>
              <div className="rounded-lg bg-surface-container-low p-3">polarity history <span className="font-bold text-on-surface">{artifactInventory.polarity_history_count ?? 0}</span></div>
              <div className="rounded-lg bg-surface-container-low p-3 break-words">pair families <span className="font-bold text-on-surface">{(artifactInventory.pair_family_dirs || []).join(', ') || 'N/A'}</span></div>
            </div>
          </div>
          <div className="rounded-lg bg-surface-container-lowest p-4">
            <div className="flex flex-wrap items-center gap-2">
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Retention Policy</div>
              <StatusBadge label="latest + checkpoint" tone="neutral" />
            </div>
            <div className="mt-3 space-y-2 text-xs text-on-surface-variant">
              {Object.entries(artifactInventory.history_retention_policy || {}).map(([key, value]) => (
                <div key={key} className="rounded-lg bg-surface-container-low p-3">
                  <span className="font-bold text-on-surface">{key}</span>: {value}
                </div>
              ))}
            </div>
            <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">{artifactInventory.interpretation || 'เก็บ history เท่าที่จำเป็นและให้ UI อ่าน stable aliases เป็นหลัก'}</p>
          </div>
        </div>
      </section>

      <section className="rounded-xl bg-surface-container-low p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Thesis Protocol Readiness</div>
            <h2 className="mt-1 font-headline text-lg font-bold text-on-surface">ใช้ข้อมูลจริงและเทียบ baseline อย่างยุติธรรมหรือยัง</h2>
            <p className="mt-2 max-w-4xl text-sm leading-relaxed text-on-surface-variant">
              {thesisProtocol.interpretation || 'ยังไม่มี protocol summary จาก backend'}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusBadge label={thesisProtocol.status || 'unknown'} tone={thesisProtocol.status === 'ready' ? 'live' : thesisProtocol.status === 'needs_work' ? 'warning' : 'neutral'} />
            <StatusBadge label={thesisProtocol.current_artifact_role || 'artifact role'} tone="neutral" />
            {fullStrategyReference.status && (
              <StatusBadge label={`${fullStrategyReference.problem_source || 'source'} top ${fullStrategyReference.top_k || '?'}`} tone={fullStrategyReference.status === 'ready' ? 'live' : 'neutral'} />
            )}
          </div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          {protocolReadinessItems.map((item) => (
            <div key={item.id} className={`rounded-lg p-3 ${item.status === 'ready' ? 'bg-teal-50 text-teal-900 dark:bg-teal-950/40 dark:text-teal-100' : item.status === 'missing' ? 'bg-yellow-50 text-yellow-950 dark:bg-yellow-950/40 dark:text-yellow-100' : 'bg-surface-container-lowest text-on-surface'}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="font-bold text-on-surface">{item.label}</div>
                <span className="rounded bg-surface-container-high px-2 py-1 text-[10px] font-bold uppercase text-on-surface-variant">{item.status}</span>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">{item.meaning}</p>
            </div>
          ))}
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
          <div className="rounded-lg bg-surface-container-lowest p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Metric Policy</div>
            <p className="mt-2 text-sm leading-relaxed text-on-surface">
              {thesisProtocol.headline_rule || 'ใช้ top-k และ metric ตาม artifact ที่เลือก'}
            </p>
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              {protocolMetricGroups.map(([group, metricsList]) => (
                <div key={group} className="rounded bg-surface-container-low p-3">
                  <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">{group}</div>
                  <div className="mt-2 space-y-2">
                    {(metricsList || []).map((item) => (
                      <p key={`${group}-${item.metric}`} className="text-xs leading-relaxed text-on-surface-variant">
                        <strong className="text-on-surface">{item.metric}</strong>: {item.why}
                      </p>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg bg-surface-container-lowest p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Capacity Checks</div>
            <p className="mt-2 text-sm leading-relaxed text-on-surface">
              ตรวจว่า baseline/H2L แต่ละตัวได้ใช้ศักยภาพตามที่ควรหรือยัง โดยเฉพาะ HyDE ที่ต้องพึ่ง LLM จริง
            </p>
            <div className="mt-3 space-y-2">
              {capacityChecks.map((item) => (
                <div key={item.strategy} className={`rounded p-3 text-xs ${item.status === 'ready' ? 'bg-teal-50 text-teal-900 dark:bg-teal-950/40 dark:text-teal-100' : 'bg-yellow-50 text-yellow-900 dark:bg-yellow-950/40 dark:text-yellow-100'}`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-bold text-on-surface">{item.strategy}</span>
                    <span className="font-bold uppercase">{item.status}</span>
                  </div>
                  <p className="mt-1 leading-relaxed text-on-surface-variant">{item.meaning}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <details className="rounded-xl bg-surface-container-low p-5">
        <summary className="cursor-pointer font-headline font-bold text-on-surface">Baseline Limitations → H2L Response</summary>
        <div className="mt-4 grid gap-3 lg:grid-cols-4">
          {baselineLimitationRows.map((row) => (
            <div key={row.family} className="rounded-lg bg-surface-container-lowest p-4">
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">{row.baseline}</div>
              <h3 className="mt-1 font-bold text-on-surface">ข้อจำกัดที่ต้องแก้</h3>
              <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">{row.limitation}</p>
              <h3 className="mt-4 font-bold text-on-surface">H2L ช่วยตรงไหน</h3>
              <p className="mt-2 text-sm leading-relaxed text-on-surface">{row.h2l_response}</p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {(row.primary_metrics || []).map((metric) => (
                  <span key={`${row.family}-${metric}`} className="rounded bg-surface-container-high px-2 py-1 text-[10px] font-bold text-on-surface-variant">{metric}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </details>

      <details className="clinical-details rounded-lg bg-surface-container-low p-5">
        <summary className="flex min-h-12 flex-wrap items-center justify-between gap-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600">
          <div>
            <h2 className="font-headline text-lg font-bold">บริบทเคสปัจจุบัน (ข้อมูลเสริม)</h2>
            <p className="mt-1 text-sm text-on-surface-variant">เปิดเมื่อจำเป็นต้องเทียบ runtime ของเคสเดียวกับขอบเขต benchmark</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusBadge label={currentCaseReady ? 'live case result' : 'no current result'} tone={currentCaseReady ? 'live' : 'neutral'} />
            <span aria-hidden="true" className="details-chevron material-symbols-outlined text-on-surface-variant transition-transform">expand_more</span>
          </div>
        </summary>
        <div className="mt-5 grid gap-3 lg:grid-cols-3">
          <div className="rounded-xl bg-surface-container-lowest p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Result Origin</div>
            <p className="mt-2 text-sm leading-relaxed text-on-surface">ผลในส่วนนี้มาจาก `/analyze` ของเคสปัจจุบันโดยตรง รวม detector, polarity และ retrieval trace ของข้อความนี้เท่านั้น</p>
          </div>
          <div className="rounded-xl bg-surface-container-lowest p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">What It Answers</div>
            <p className="mt-2 text-sm leading-relaxed text-on-surface">ตอบว่าเคสนี้ระบบรับ problem อะไร ตัด candidate อะไร และดึง evidence doc อะไรขึ้นมาหนุน</p>
          </div>
          <div className="rounded-xl bg-surface-container-lowest p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Limit</div>
            <p className="mt-2 text-sm leading-relaxed text-on-surface">ไม่มี ground truth เฉพาะเคส จึงไม่ควรใช้ส่วนนี้สรุปว่าโมเดลชนะ baseline โดยรวม</p>
          </div>
        </div>
        <div className="mt-5 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <MetricTile label="Accepted Problems" value={metrics.accepted_count ?? displayResult.problems?.length ?? 0} hint="รหัสปัญหาที่ระบบรับไว้" tone="bg-green-50 dark:bg-green-950/40" />
          <MetricTile label="Filtered Candidates" value={metrics.filtered_count ?? candidateTrace.filtered_out ?? 0} hint="ถูกลด/ตัดด้วย context หรือ polarity" tone={(metrics.filtered_count ?? candidateTrace.filtered_out ?? 0) ? 'bg-yellow-50 dark:bg-yellow-950/40' : 'bg-surface-container-lowest'} />
          <MetricTile label="Evidence Docs" value={metrics.retrieved_docs_count ?? displayResult.retrieved_docs_count ?? 0} hint="เอกสารที่ runtime ดึงมาจริง" />
          <MetricTile label="H2L Traces" value={h2lTrace.length} hint="เอกสารที่มีสมการ breakdown จริง" tone={h2lTrace.length ? 'bg-green-50 dark:bg-green-950/40' : 'bg-yellow-50 dark:bg-yellow-950/40'} />
        </div>
        <div className="mt-5 rounded-xl bg-surface-container-lowest p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Review Status Summary</div>
              <p className="mt-2 text-sm leading-relaxed text-on-surface">{reviewSummary.interpretation || 'ยังไม่มีการสรุปสถานะ review ของเคสนี้'}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <StatusBadge label={reviewSummary.baseline_mode ? 'baseline preview mode' : 'review-ready labels'} tone={reviewSummary.baseline_mode ? 'neutral' : 'live'} />
            </div>
          </div>
          {reviewSummary.baseline_mode ? (
            <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
              <MetricTile label="Baseline Candidates" value={reviewSummary.baseline_candidate ?? 0} hint="preview จาก baseline detector" tone="bg-surface-container-low" />
              <MetricTile label="Baseline Filtered" value={reviewSummary.baseline_filtered ?? 0} hint="ถูกลดน้ำหนักใน baseline preview" tone="bg-surface-container-low" />
              <MetricTile label="Verify Documents" value={reviewSummary.verify_documents ?? 0} hint="ยังควรตรวจสิทธิ/เอกสาร" tone={(reviewSummary.verify_documents ?? 0) ? 'bg-yellow-50 dark:bg-yellow-950/40' : 'bg-surface-container-low'} />
              <MetricTile label="Total Review Items" value={reviewSummary.total ?? 0} hint="accepted + filtered" tone="bg-surface-container-low" />
            </div>
          ) : (
            <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
              <MetricTile label="System-supported" value={reviewSummary.confirmed ?? 0} hint="ระบบพบหลักฐานสนับสนุน รอผู้ปฏิบัติงานทบทวน" tone={(reviewSummary.confirmed ?? 0) ? 'bg-green-50 dark:bg-green-950/40' : 'bg-surface-container-low'} />
              <MetricTile label="Needs Review" value={reviewSummary.needs_review ?? 0} hint="ควรทบทวนบริบทเพิ่ม" tone={(reviewSummary.needs_review ?? 0) ? 'bg-yellow-50 dark:bg-yellow-950/40' : 'bg-surface-container-low'} />
              <MetricTile label="Verify Documents" value={reviewSummary.verify_documents ?? 0} hint="ต้องยืนยันด้วยสิทธิ/ทะเบียน/เอกสาร" tone={(reviewSummary.verify_documents ?? 0) ? 'bg-yellow-50 dark:bg-yellow-950/40' : 'bg-surface-container-low'} />
              <MetricTile label="Filtered" value={reviewSummary.filtered ?? 0} hint="ถูกตัดออกจากผลสุดท้าย" tone={(reviewSummary.filtered ?? 0) ? 'bg-surface-container-high' : 'bg-surface-container-low'} />
            </div>
          )}
        </div>
        <div className="mt-5 rounded-xl bg-surface-container-lowest p-4">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Polarity In This Case</div>
          <p className="mt-2 text-sm leading-relaxed text-on-surface">{displayResult.polarity_effect?.interpretation || 'ยังไม่มีผล sentence polarity ของเคสปัจจุบัน'}</p>
          <div className="mt-3 text-xs font-bold text-teal-700">{polarityRows.length} candidate rows</div>
        </div>
        <div className="mt-5">
          <ProblemDocumentMatrix caseText={displayResult.case_description || ''} problems={displayResult.problems || []} docs={displayResult.retrieved_docs || []} />
        </div>
      </details>

      <section className="rounded-xl bg-surface-container-low p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-headline text-lg font-bold">2. Benchmark Performance Review</h2>
            <p className="mt-1 text-sm text-on-surface-variant">ส่วนนี้ใช้ benchmark artifacts บน test split และรายงานตาม Top K ที่เลือกเท่านั้น เพื่อใช้สรุปผลเปรียบเทียบ baseline vs H2L</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusBadge label={`top ${selectedExperimentTopK}`} tone={selectedReportAvailable ? 'live' : 'warning'} />
            <StatusBadge label={selectedReportAvailable ? `${selectedReportRun.problem_source} artifact` : 'artifact missing'} tone={selectedReportAvailable ? 'live' : 'warning'} />
            <StatusBadge label="test split scope" tone="neutral" />
          </div>
        </div>
        <div className="mt-5 grid gap-3 lg:grid-cols-4">
          <div className="rounded-xl bg-surface-container-lowest p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Benchmark Source</div>
            <p className="mt-2 break-words text-sm leading-relaxed text-on-surface">{benchmarkSourceLabel}</p>
          </div>
          <div className="rounded-xl bg-surface-container-lowest p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Dataset Scope</div>
            <p className="mt-2 text-sm leading-relaxed text-on-surface">{datasetInfo.test_count ?? research.test_count ?? 'N/A'} test cases from {datasetSource}</p>
          </div>
          <div className="rounded-xl bg-surface-container-lowest p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Artifact Timestamp</div>
            <p className="mt-2 text-sm leading-relaxed text-on-surface">{formatDateTime(benchmarkUpdatedAt)}</p>
          </div>
          <div className={`rounded-xl p-4 ${benchmarkNeedsRefresh ? 'bg-yellow-50 dark:bg-yellow-950/40' : 'bg-teal-50 dark:bg-teal-950/40'}`}>
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Review Action</div>
            <p className="mt-2 text-sm leading-relaxed text-on-surface">{benchmarkNeedsRefresh ? 'ground truth ใหม่กว่า artifact บางส่วน ควร reload และรัน evaluator ใหม่ก่อนสรุปผล' : 'artifact รุ่นปัจจุบันพร้อมใช้สำหรับการ review performance'}</p>
          </div>
        </div>
        <div className="mt-5 grid grid-cols-2 gap-4 lg:grid-cols-5">
          <MetricTile label="Test Cases" value={selectedReportRun?.num_cases ?? 'N/A'} hint={selectedReportRun?.source || `missing top ${selectedExperimentTopK}`} />
          <MetricTile label="MAP" value={formatNumber(selectedMetric('MAP'))} hint={`Δ ${formatNumber(selectedReportDelta.MAP)}`} tone={metricBackground(selectedMetric('MAP'))} />
          <MetricTile label="MRR" value={formatNumber(selectedMetric('MRR'))} hint={`baseline ${formatNumber(selectedBaseRow.MRR)}`} tone={metricBackground(selectedMetric('MRR'))} />
          <MetricTile label={selectedNdcgKey} value={formatNumber(selectedMetric(selectedNdcgKey))} hint={`top ${selectedExperimentTopK}`} tone={metricBackground(selectedMetric(selectedNdcgKey))} />
          <MetricTile label="Polarity Acc." value={formatPercent(polarity.accuracy)} hint={`${polarity.total_cases ?? 'N/A'} polarity cases`} tone={metricBackground(polarity.accuracy)} />
        </div>
        {progressRunning && (
          <div className="mt-4 rounded-lg bg-teal-50 p-3 text-sm leading-relaxed text-teal-950 dark:bg-teal-950/40 dark:text-teal-100">
            evaluator กำลังรันอยู่: proper eval {progressCountLabel(properEvalProgress.completed_case_count, properEvalProgress.total_case_count)} / polarity {progressCountLabel(polarityEvalProgress.completed_case_count, polarityEvalProgress.total_case_count)}.
            หน้านี้จะอ่าน progress และ artifact ล่าสุดจากดิสก์ต่อเนื่องจนกว่าจะจบ โดยไม่เติมค่าจำลองเอง.
          </div>
        )}
        {!selectedReportAvailable && (
          <div className="mt-4 rounded-lg bg-yellow-50 p-3 text-sm leading-relaxed text-yellow-900 dark:bg-yellow-950/40 dark:text-yellow-100">
            ยังไม่มีผลทดลองจริงสำหรับ Top {selectedExperimentTopK}. หน้านี้จึงไม่ดึงค่า Top อื่นมาแทน เพื่อป้องกันการตีความสับสน.
          </div>
        )}

        <div className="mt-5 rounded-xl bg-surface-container-lowest p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Latest Pair Reruns</div>
              <h3 className="mt-1 font-bold text-on-surface">ผล pair-run ล่าสุดที่อ่านจากโฟลเดอร์จริงบนดิสก์</h3>
              <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">
                การ์ดชุดนี้อ่านจาก <span className="font-bold text-on-surface">{isolatedPairRuns.source_root || 'evaluation_results/pairs'}</span> โดยตรง เพื่อยืนยันคู่ baseline vs H2L ทีละ family
                และใช้เป็นแหล่งล่าสุดสำหรับกราฟเปรียบเทียบด้านล่างเมื่อ artifact ครบทุกคู่
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <StatusBadge label={`ready ${isolatedPairRuns.ready_count || 0}/${isolatedPairRuns.expected_count || 4}`} tone={isolatedPairRuns.status === 'ready' ? 'live' : isolatedPairRuns.status === 'partial' ? 'warning' : 'neutral'} />
              <StatusBadge label={isolatedPairRuns.latest_timestamp ? formatDateTime(isolatedPairRuns.latest_timestamp) : 'no timestamp'} tone="neutral" />
            </div>
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-2 xl:grid-cols-4">
            {(isolatedPairRuns.runs || []).map((run) => {
              const pair = run.comparison_pair || {};
              const ndcgTest = run.paired_test || {};
              const mapTest = run.map_test || {};
              const tone = run.status === 'ready'
                ? (ndcgTest.significant ? 'bg-teal-50 dark:bg-teal-950/40' : 'bg-surface-container-low')
                : run.status === 'partial'
                  ? 'bg-yellow-50 dark:bg-yellow-950/40'
                  : 'bg-surface-container-low';
              return (
                <div key={`${run.family}-${run.top_k}`} className={`rounded-xl p-4 ${tone}`}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">{run.label || run.family}</div>
                      <div className="mt-1 break-words font-headline text-lg font-extrabold text-on-surface">{run.status === 'ready' ? `Top ${run.top_k}` : 'artifact missing'}</div>
                    </div>
                    <StatusBadge label={run.status || 'missing'} tone={run.status === 'ready' ? 'live' : run.status === 'partial' ? 'warning' : 'neutral'} />
                  </div>
                  {run.status === 'ready' ? (
                    <>
                      <div className="mt-3 grid gap-2 text-xs text-on-surface-variant">
                        <div className="rounded-lg bg-surface-container-lowest p-3">baseline <span className="font-bold text-on-surface">{pair.base_strategy || run.baseline}</span> MAP <span className="font-bold text-on-surface">{formatNumber(pair.base_quality)}</span></div>
                        <div className="rounded-lg bg-surface-container-lowest p-3">h2l <span className="font-bold text-on-surface">{pair.h2l_strategy || run.enhanced}</span> MAP <span className="font-bold text-on-surface">{formatNumber(pair.h2l_quality)}</span></div>
                        <div className="rounded-lg bg-surface-container-lowest p-3">ΔMAP <span className={`font-bold ${Number(pair.quality_delta) >= 0 ? 'text-teal-700 dark:text-teal-200' : 'text-yellow-900 dark:text-yellow-100'}`}>{Number.isFinite(Number(pair.quality_delta)) ? `${Number(pair.quality_delta) >= 0 ? '+' : ''}${formatNumber(pair.quality_delta)}` : 'N/A'}</span></div>
                      </div>
                      <div className="mt-3 grid gap-2 text-xs text-on-surface-variant">
                        <div className="rounded-lg bg-surface-container-lowest p-3">nDCG@5 p-value <span className="font-bold text-on-surface">{formatNumber(ndcgTest.p_value, 4)}</span></div>
                        <div className="rounded-lg bg-surface-container-lowest p-3">MAP p-value <span className="font-bold text-on-surface">{formatNumber(mapTest.p_value, 4)}</span></div>
                        <div className="rounded-lg bg-surface-container-lowest p-3 break-words">source <span className="font-bold text-on-surface">{run.source}</span></div>
                      </div>
                    </>
                  ) : (
                    <div className="mt-3 rounded-lg bg-surface-container-lowest p-3 text-sm text-on-surface-variant">ยังไม่พบ artifact ล่าสุดของคู่นี้ในโฟลเดอร์ pair reruns</div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="mt-5">
          <DocScalingPlot runs={docScalingRuns} selectedTopK={selectedExperimentTopK} onSelectTopK={onSelectTopK} />
        </div>

        <div className="mt-5">
          <PairComparisonBarChart pairs={reportComparisonPairs} selectedNdcgKey={comparisonNdcgKey} />
        </div>

        <div className="mt-5">
          <QualityTradeoffScatter rows={comparisonTableRows} selectedNdcgKey={comparisonNdcgKey} />
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          {standoutRows.map((item) => (
            <div key={item.label} className={`rounded-xl p-4 ${item.row?.group === 'H2L-enhanced' ? 'bg-teal-50 dark:bg-teal-950/40' : item.row ? 'bg-yellow-50 dark:bg-yellow-950/40' : 'bg-surface-container-lowest'}`}>
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">{item.label}</div>
              <div className="mt-2 font-headline text-lg font-extrabold text-on-surface">{item.row?.strategy || 'N/A'}</div>
              <div className="mt-1 text-sm font-bold text-teal-700">{item.row ? formatNumber(item.row[item.field], item.field === 'retrieval_time' ? 4 : 3) : 'N/A'}{item.field === 'retrieval_time' && item.row ? 's' : ''}</div>
              <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">{item.meaning}</p>
            </div>
          ))}
        </div>
        <div className="mt-3 rounded-lg bg-surface-container-lowest p-3 text-sm leading-relaxed text-on-surface">
          หมายเหตุ: กล่อง “สูงสุด” เป็นการดูข้ามทุก strategy เพื่อดูภาพรวมเท่านั้น ไม่ใช่การตัดสินแบบจับคู่ที่ยุติธรรม.
          ถ้าจะตอบว่า H2L ช่วยหรือไม่ ให้ดูคู่ Baseline vs H2L ใน family เดียวกัน และอ่านคุณภาพ ranking แยกจากเวลา.
        </div>

        <div className="mt-5 rounded-xl bg-surface-container-lowest p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">System Evaluation Status</div>
              <h3 className="mt-1 font-bold text-on-surface">สถานะการประเมินระบบและหลักฐานอ้างอิง</h3>
              <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">
                ส่วนนี้รวมข้อสรุประดับ benchmark ว่า H2L เด่นตรงไหน baseline ยังนำตรงไหน และหัวข้อใดของการประเมินระบบพร้อมใช้เขียนผลหรือยังต้อง review ต่อ
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <StatusBadge label={proper.raw_source ? 'raw artifact loaded' : 'raw artifact missing'} tone={proper.raw_source ? 'live' : 'warning'} />
              <StatusBadge label="benchmark / test split only" tone="neutral" />
            </div>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            {benchmarkInsightCards.map((card) => (
              <div key={card.id} className={`rounded-xl p-4 ${card.tone}`}>
                <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">{card.eyebrow}</div>
                <h3 className="mt-1 font-bold text-on-surface">{card.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">{card.description}</p>
                {card.items ? (
                  <div className="mt-3 space-y-2 text-sm">
                    {card.items.map((pair) => {
                      const wins = pairQualityWins(pair);
                      return (
                        <div key={`${card.id}-${pair.family}`} className="rounded-lg bg-surface-container-lowest p-3">
                          <div className="font-bold text-on-surface">{pair.label || pair.family}</div>
                          <div className="mt-1 text-xs text-on-surface-variant">quality wins H2L {wins.h2l || 0}:{wins.baseline || 0} Baseline; ΔMAP {formatNumber(pair.quality_delta)}</div>
                        </div>
                      );
                    })}
                    {!card.items.length && <div className="rounded-lg bg-surface-container-lowest p-3 text-sm text-on-surface-variant">{card.empty}</div>}
                  </div>
                ) : (
                  <div className="mt-3 rounded-lg bg-surface-container-low p-3 text-xs leading-relaxed text-on-surface-variant">
                    {card.footer}
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-lg bg-surface-container-low p-4">
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Evaluation Coverage</div>
              <div className="mt-2 font-headline text-3xl font-extrabold text-on-surface">{checklistCounts.done || 0}/{experimentChecklist.length}</div>
              <div className="mt-1 text-sm text-on-surface-variant">หัวข้อที่พร้อมใช้อ้างอิงใน benchmark summary</div>
            </div>
            <div className="rounded-lg bg-surface-container-low p-4">
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Open Review Items</div>
              <div className="mt-2 font-headline text-3xl font-extrabold text-on-surface">{(checklistCounts.partial || 0) + (checklistCounts.todo || 0)}</div>
              <div className="mt-1 text-sm text-on-surface-variant">หัวข้อที่ยังต้องระวังก่อนอ้างผล benchmark</div>
            </div>
            <div className="rounded-lg bg-surface-container-low p-4">
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Benchmark Focus</div>
              <div className="mt-2 font-headline text-3xl font-extrabold text-on-surface">Top {selectedExperimentTopK}</div>
              <div className="mt-1 text-sm text-on-surface-variant">{selectedReportAvailable ? `${currentProblemSource} artifact loaded` : 'artifact ยังไม่ครบ'}</div>
            </div>
            <div className="rounded-lg bg-surface-container-low p-4">
              <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Active Review Item</div>
              <div className="mt-2 font-headline text-2xl font-extrabold text-on-surface">{activeChecklist?.title || 'N/A'}</div>
              <div className="mt-1 text-sm text-on-surface-variant">{activeChecklist?.state || 'ไม่มีรายการ'}</div>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap gap-2">
            {checklistFilters.map((filter) => (
              <button
                className={`rounded-lg px-3 py-2 text-xs font-bold transition-all ${activeChecklistFilter === filter.id ? 'bg-teal-600 text-white' : 'bg-surface-container-low text-on-surface hover:bg-surface-container'}`}
                key={filter.id}
                onClick={() => setActiveChecklistFilter(filter.id)}
                type="button"
              >
                {filter.label} · {filter.count}
              </button>
            ))}
          </div>

          <div className="mt-5 grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
            <div className="space-y-3">
              {filteredChecklist.map((item) => {
                const isActive = item.id === activeChecklist?.id;
                return (
                  <button
                    className={`w-full rounded-xl border p-4 text-left transition-all ${checklistCardTone(item.status, isActive)}`}
                    key={item.id}
                    onClick={() => setActiveChecklistId(item.id)}
                    type="button"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex min-w-0 items-start gap-3">
                        <span aria-hidden="true" className={`material-symbols-outlined mt-0.5 ${isActive ? 'text-current' : 'text-on-surface-variant'}`}>{item.icon}</span>
                        <div className="min-w-0">
                          <div className="font-bold">{item.title}</div>
                          <p className={`mt-1 text-xs leading-relaxed ${isActive ? 'text-current/85' : 'text-on-surface-variant'}`}>{item.summary}</p>
                        </div>
                      </div>
                      <StatusBadge label={item.state} tone={checklistTone(item.status)} />
                    </div>
                  </button>
                );
              })}
              {!filteredChecklist.length && (
                <div className="rounded-xl bg-surface-container-low p-4 text-sm text-on-surface-variant">
                  ไม่มีรายการใน filter นี้
                </div>
              )}
            </div>

            <div className="rounded-xl bg-surface-container-low p-4">
              {activeChecklist ? (
                <>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Selected Checklist Item</div>
                      <h4 className="mt-1 font-headline text-xl font-extrabold text-on-surface">{activeChecklist.title}</h4>
                      <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">{activeChecklist.summary}</p>
                    </div>
                    <StatusBadge label={activeChecklist.state} tone={checklistTone(activeChecklist.status)} />
                  </div>

                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    <div className="rounded-lg bg-surface-container-lowest p-3">
                      <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Why It Matters</div>
                      <p className="mt-2 text-sm leading-relaxed text-on-surface">{activeChecklist.why}</p>
                    </div>
                    <div className="rounded-lg bg-surface-container-lowest p-3">
                      <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Next Step</div>
                      <p className="mt-2 text-sm leading-relaxed text-on-surface">{activeChecklist.next}</p>
                    </div>
                  </div>

                  {activeChecklist.id === 'proper_eval' && (
                    <div className="mt-4 grid gap-3 md:grid-cols-3">
                      <div className="rounded-lg bg-surface-container-lowest p-3">
                        <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Artifact</div>
                        <p className="mt-2 text-sm text-on-surface">{proper.raw_source || 'ยังไม่พบ raw artifact'}</p>
                      </div>
                      <div className="rounded-lg bg-surface-container-lowest p-3">
                        <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Cases</div>
                        <p className="mt-2 text-sm text-on-surface">{selectedReportRun?.num_cases ?? proper.num_cases ?? 'N/A'}</p>
                      </div>
                      <div className="rounded-lg bg-surface-container-lowest p-3">
                        <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Problem Source</div>
                        <p className="mt-2 text-sm text-on-surface">{currentProblemSource}</p>
                      </div>
                    </div>
                  )}

                  {activeChecklist.id === 'doc_scaling' && (
                    <div className="mt-4 space-y-3">
                      <div className="rounded-lg bg-surface-container-lowest p-3">
                        <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Available Top-K</div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {(docScaling.available_top_k || []).length
                            ? docScaling.available_top_k.map((topK) => (
                              <span className={`rounded px-2 py-1 text-xs font-bold ${Number(topK) === Number(selectedExperimentTopK) ? 'bg-teal-600 text-white' : 'bg-surface-container-high text-on-surface'}`} key={`available-topk-${topK}`}>
                                Top {topK}
                              </span>
                            ))
                            : <span className="text-xs text-on-surface-variant">ยังไม่มี top-k list</span>}
                        </div>
                      </div>
                      <div className="grid gap-3 md:grid-cols-2">
                        {docScalingRuns.slice(0, 6).map((run) => {
                          const delta = run.delta_h2l_minus_basic || {};
                          const improved = Number(delta.MAP || 0) > 0 || Number(delta.MRR || 0) > 0 || Number(delta['nDCG@10'] || 0) > 0;
                          return (
                            <div className={`rounded-lg p-3 text-xs ${improved ? 'bg-teal-50 text-teal-900 dark:bg-teal-950/40 dark:text-teal-100' : 'bg-surface-container-lowest text-on-surface-variant'}`} key={`${run.problem_source}-${run.top_k}-${run.source}`}>
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-bold uppercase">{run.problem_source} top {run.top_k}</span>
                                <span>{run.reporting_role || 'supporting'}</span>
                              </div>
                              <div className="mt-2 grid grid-cols-3 gap-2">
                                <span>ΔMAP {formatNumber(delta.MAP)}</span>
                                <span>ΔMRR {formatNumber(delta.MRR)}</span>
                                <span>ΔnDCG10 {formatNumber(delta['nDCG@10'])}</span>
                              </div>
                            </div>
                          );
                        })}
                        {!docScalingRuns.length && <div className="rounded-lg bg-surface-container-lowest p-3 text-xs text-on-surface-variant">ยังไม่มี doc scaling artifact</div>}
                      </div>
                      {(docScaling.missing_top_k || []).length > 0 && (
                        <div className="rounded bg-yellow-50 p-3 text-xs leading-relaxed text-yellow-900 dark:bg-yellow-950/40 dark:text-yellow-100">
                          ยังไม่มี artifact สำหรับ top {docScaling.missing_top_k.join(', ')}
                        </div>
                      )}
                    </div>
                  )}

                  {activeChecklist.id === 'problem_source' && (
                    <div className="mt-4 space-y-3">
                      <div className="grid gap-3 md:grid-cols-2">
                        {problemSourceRunRows.map((run) => {
                          const delta = run.delta_h2l_minus_basic || {};
                          const sourceMeta = problemSourceMeta(run.problem_source);
                          return (
                            <div className={`rounded-lg p-3 text-xs ${run.problem_source === currentProblemSource ? 'bg-teal-50 text-teal-900 dark:bg-teal-950/40 dark:text-teal-100' : 'bg-surface-container-lowest text-on-surface-variant'}`} key={run.problem_source}>
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-bold">{sourceMeta.label}</span>
                                <span>{run.num_cases ?? 'N/A'} cases</span>
                              </div>
                              <div className="mt-1 leading-relaxed">{sourceMeta.meaning}</div>
                              <div className="mt-2 grid grid-cols-3 gap-2">
                                <span>ΔMAP {formatNumber(delta.MAP)}</span>
                                <span>ΔMRR {formatNumber(delta.MRR)}</span>
                                <span>ΔnDCG {formatNumber(delta['nDCG@5'])}</span>
                              </div>
                            </div>
                          );
                        })}
                        {!problemSourceRunRows.length && <div className="rounded-lg bg-surface-container-lowest p-3 text-xs text-on-surface-variant">ยังไม่มี run ที่แยก problem source</div>}
                      </div>
                      {detectorGapRun && (
                        <div className="rounded-lg bg-surface-container-lowest p-3 text-xs leading-relaxed text-on-surface-variant">
                          <div className="font-bold text-on-surface">Detector gap ที่ top {detectorGapRun.top_k}</div>
                          <div className="mt-2 grid grid-cols-2 gap-2">
                            <span>exact {formatPercent(detectorGap.exact_match_rate)}</span>
                            <span>overlap {formatPercent(detectorGap.avg_jaccard)}</span>
                          </div>
                          <p className="mt-2">
                            missing: {(detectorGap.top_missing_codes || []).slice(0, 3).map((item) => `${item.code}(${item.count})`).join(', ') || 'ไม่มี'}; extra: {(detectorGap.top_extra_codes || []).slice(0, 3).map((item) => `${item.code}(${item.count})`).join(', ') || 'ไม่มี'}
                          </p>
                        </div>
                      )}
                    </div>
                  )}

                  {activeChecklist.id === 'significance' && (
                    <div className="mt-4 space-y-3">
                      {diagnosticMetrics.slice(0, 5).map((row) => {
                        const ci = row.bootstrap_ci || {};
                        const bayes = row.bayesian_signed_rank || {};
                        const significant = row.paired_test?.significant;
                        return (
                          <div className={`rounded-lg p-3 text-xs ${significant ? 'bg-teal-50 text-teal-900 dark:bg-teal-950/40 dark:text-teal-100' : 'bg-surface-container-lowest text-on-surface-variant'}`} key={`diagnostic-${row.metric}`}>
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-bold text-on-surface">{row.metric}</span>
                              <span className="font-bold">{significant ? 'มีนัยสำคัญ' : 'ยังไม่ชัด'}</span>
                            </div>
                            <div className="mt-2 grid grid-cols-2 gap-2">
                              <span>Δ {formatNumber(row.delta_mean)}</span>
                              <span>p {formatNumber(row.paired_test?.p_value, 4)}</span>
                              <span>CI {formatNumber(ci.ci_lower)} ถึง {formatNumber(ci.ci_upper)}</span>
                              <span>P(H2L) {formatPercent(bayes.p_h2l_wins)}</span>
                            </div>
                          </div>
                        );
                      })}
                      {!diagnosticMetrics.length && <div className="rounded-lg bg-surface-container-lowest p-3 text-xs text-on-surface-variant">ยังไม่มี paired diagnostics</div>}
                    </div>
                  )}

                  {activeChecklist.id === 'category_analysis' && (
                    <div className="mt-4 space-y-3">
                      {categoryDiagnostics.slice(0, 5).map((row) => {
                        const deltaMap = Number(row.MAP?.delta_mean || 0);
                        const tone = deltaMap > 0.000001
                          ? 'bg-teal-50 text-teal-900 dark:bg-teal-950/40 dark:text-teal-100'
                          : deltaMap < -0.000001
                            ? 'bg-yellow-50 text-yellow-900 dark:bg-yellow-950/40 dark:text-yellow-100'
                            : 'bg-surface-container-lowest text-on-surface-variant';
                        return (
                          <div className={`rounded-lg p-3 text-xs ${tone}`} key={`category-${row.name}`}>
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-bold text-on-surface">{row.name}</span>
                              <span>{row.n_cases} cases</span>
                            </div>
                            <div className="mt-2 grid grid-cols-3 gap-2">
                              <span>ΔMAP {formatNumber(row.MAP?.delta_mean)}</span>
                              <span>H2L {row.MAP?.h2l_wins ?? 0}</span>
                              <span>Base {row.MAP?.baseline_wins ?? 0}</span>
                            </div>
                          </div>
                        );
                      })}
                      {!categoryDiagnostics.length && <div className="rounded-lg bg-surface-container-lowest p-3 text-xs text-on-surface-variant">ยังไม่มี category-level rows</div>}
                    </div>
                  )}
                </>
              ) : (
                <div className="rounded-lg bg-surface-container-lowest p-4 text-sm text-on-surface-variant">
                  ยังไม่มีรายการ checklist ให้แสดง
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="mt-5 grid gap-4 lg:grid-cols-3">
          <div className="rounded-xl bg-surface-container-lowest p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">RQ1</div>
            <h3 className="mt-1 font-bold text-on-surface">H2L ช่วย retrieval ดีขึ้นไหม</h3>
            <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">ตอบด้วย MAP, MRR, nDCG และคู่ Baseline vs H2L ใน family เดียวกัน</p>
            <div className="mt-3 rounded bg-surface-container-low p-3 text-sm">
              {strongestPair ? `คู่ที่ดีขึ้นมากสุด: ${strongestPair.label || strongestPair.family} ΔMAP ${formatNumber(strongestPair.quality_delta)}` : 'ยังไม่มี comparison pair จาก artifact'}
            </div>
          </div>
          <div className="rounded-xl bg-surface-container-lowest p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">RQ2</div>
            <h3 className="mt-1 font-bold text-on-surface">Sentence polarity ลด false positive ได้ไหม</h3>
            <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">ตอบด้วย polarity accuracy/F1 และดูในเคสจริงว่า candidate ใดถูกลดน้ำหนักเพราะ negation หรือ actor-target ไม่ตรง</p>
            <div className="mt-3 rounded bg-surface-container-low p-3 text-sm">
              Accuracy {formatPercent(polarity.accuracy)}; F1 {formatPercent(polarity.f1_score)}
            </div>
          </div>
          <div className="rounded-xl bg-surface-container-lowest p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">RQ3</div>
            <h3 className="mt-1 font-bold text-on-surface">องค์ประกอบใดของ H2L สำคัญ</h3>
            <p className="mt-2 text-sm leading-relaxed text-on-surface-variant">ตอบด้วย ablation/sensitivity เช่น alpha, L2 filtering, soft matching และ severity prior</p>
            <div className="mt-3 rounded bg-surface-container-low p-3 text-sm">
              {sensitivityEntries.length ? `${sensitivityEntries.length} ablation groups loaded` : 'ยังไม่มี ablation artifact'}
            </div>
          </div>
        </div>
      </section>

      <details className="rounded-xl bg-surface-container-low p-6">
        <summary className="cursor-pointer font-headline font-bold text-on-surface">Detailed Baseline vs H2L Pairs</summary>
        <div className="mt-4 rounded-lg bg-surface-container-lowest p-3 text-sm leading-relaxed text-on-surface">
          Source: <strong>{comparisonSourceLabel}</strong>. ถ้าเป็น legacy/reference ให้ใช้เป็นหลักฐานเบื้องต้น และควรรัน detected top15 matrix ใหม่ก่อนเขียนผลสุดท้าย.
        </div>
        <div className="mt-5 grid gap-4 lg:grid-cols-4">
          {reportComparisonPairs.map((pair) => {
            const pairBaseNdcg = comparisonTopK >= 10 ? pair.base_ndcg_at_10 ?? pair.base_ndcg_at_5 : pair.base_ndcg_at_5;
            const pairH2lNdcg = comparisonTopK >= 10 ? pair.h2l_ndcg_at_10 ?? pair.h2l_ndcg_at_5 : pair.h2l_ndcg_at_5;
            const winners = [
              { metric: 'MAP', ...metricWinner(pair.base_quality, pair.h2l_quality, true), diffDigits: 3 },
              { metric: 'MRR', ...metricWinner(pair.base_mrr, pair.h2l_mrr, true), diffDigits: 3 },
              { metric: comparisonNdcgKey, ...metricWinner(pairBaseNdcg, pairH2lNdcg, true), diffDigits: 3 },
              { metric: 'Speed', ...metricWinner(pair.base_time, pair.h2l_time, false), diffDigits: 4 },
            ];
            const qualityWinners = winners.filter((item) => item.metric !== 'Speed');
            const speedWinner = winners.find((item) => item.metric === 'Speed');
            const h2lQualityWins = qualityWinners.filter((item) => item.winner === 'H2L').length;
            const baselineQualityWins = qualityWinners.filter((item) => item.winner === 'Baseline').length;
            const qualityLabel = h2lQualityWins > baselineQualityWins ? 'H2L คุณภาพดีกว่า' : baselineQualityWins > h2lQualityWins ? 'Baseline คุณภาพดีกว่า' : 'คุณภาพสูสี';
            const cardTone = h2lQualityWins > baselineQualityWins ? 'bg-teal-50 dark:bg-teal-950/40' : baselineQualityWins > h2lQualityWins ? 'bg-yellow-50 dark:bg-yellow-950/40' : 'bg-surface-container-lowest';
            return (
              <div key={`${pair.base_strategy}-${pair.h2l_strategy}`} className={`rounded-xl p-4 ${cardTone}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">{pair.label || pair.family}</div>
                  <span className={`rounded px-2 py-1 text-[10px] font-bold ${h2lQualityWins > baselineQualityWins ? 'bg-teal-600 text-white' : baselineQualityWins > h2lQualityWins ? 'bg-yellow-500 text-slate-950' : 'bg-surface-container-high text-on-surface'}`}>
                    {qualityLabel}
                  </span>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <div className="text-[10px] font-bold uppercase text-on-surface-variant">Baseline</div>
                    <div className="font-headline text-lg font-extrabold text-on-surface">{formatNumber(pair.base_quality)}</div>
                    <div className="text-xs text-on-surface-variant">{pair.base_strategy}</div>
                  </div>
                  <div>
                    <div className="text-[10px] font-bold uppercase text-on-surface-variant">H2L</div>
                    <div className="font-headline text-lg font-extrabold text-on-surface">{formatNumber(pair.h2l_quality)}</div>
                    <div className="text-xs text-on-surface-variant">{pair.h2l_strategy}</div>
                  </div>
                </div>
                <div className="mt-3 rounded bg-surface-container-lowest p-3 text-xs leading-relaxed text-on-surface">
                  ΔMAP {formatNumber(pair.quality_delta)}; Δlatency {formatNumber(pair.time_delta, 4)}s. {pair.interpretation}
                </div>
                <div className="mt-2 rounded bg-surface-container-lowest p-3 text-xs leading-relaxed text-on-surface-variant">
                  คุณภาพ ranking ชนะ {h2lQualityWins}:{baselineQualityWins} จาก MAP/MRR/{selectedNdcgKey}; เวลาอ่านแยกต่างหาก:
                  {' '}{speedWinner?.label || 'ไม่มีข้อมูลเวลา'}
                </div>
                {pair.limitation_coverage?.limitation && (
                  <div className="mt-2 rounded bg-surface-container-lowest p-3 text-xs leading-relaxed text-on-surface-variant">
                    <strong className="text-on-surface">ข้อจำกัด baseline:</strong> {pair.limitation_coverage.limitation}
                    <br />
                    <strong className="text-on-surface">สิ่งที่ H2L พยายามแก้:</strong> {pair.limitation_coverage.h2l_response}
                  </div>
                )}
                {pair.case_diagnostics?.metrics?.length > 0 && (
                  <div className="mt-2 rounded bg-surface-container-lowest p-3">
                    <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Case-level votes from raw artifact</div>
                    <div className="mt-2 space-y-1.5 text-[11px] text-on-surface-variant">
                      {pair.case_diagnostics.metrics.map((row) => (
                        <div key={`${pair.family}-${row.metric}-cases`} className="flex items-center justify-between gap-2">
                          <span className="font-bold text-on-surface">{row.metric}</span>
                          <span>H2L {row.h2l_wins} / Baseline {row.baseline_wins} / เสมอ {row.ties}</span>
                        </div>
                      ))}
                    </div>
                    <p className="mt-2 text-[11px] leading-relaxed text-on-surface-variant">{pair.case_diagnostics.takeaway}</p>
                  </div>
                )}
                <div className="mt-3 grid gap-2">
                  {winners.map((item) => (
                    <div key={`${pair.family}-${item.metric}`} className={`flex items-center justify-between gap-2 rounded px-3 py-2 text-xs ${item.className}`}>
                      <span className="font-bold">{item.metric}</span>
                      <span>{item.label}{item.diff !== null ? ` (${item.metric === 'Speed' ? 'Δtime' : 'Δ'} ${formatNumber(item.diff, item.diffDigits)}${item.metric === 'Speed' ? 's' : ''})` : ''}</span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
          {!reportComparisonPairs.length && <div className="rounded-xl bg-surface-container-lowest p-4 text-sm text-on-surface-variant">No comparison pair artifact loaded for selected Top K.</div>}
        </div>
        <div className="mt-6 overflow-hidden rounded-lg bg-surface-container-lowest">
          <div className="grid grid-cols-6 gap-3 bg-surface-container-high px-4 py-3 text-[10px] font-bold uppercase text-on-surface-variant">
            <span>Strategy</span><span>Group</span><span>MAP</span><span>MRR</span><span>{selectedNdcgKey}</span><span>Time</span>
          </div>
          {comparisonTableRows.map((row) => (
            <div key={row.strategy} className={`grid grid-cols-6 gap-3 px-4 py-3 text-sm ${row.group === 'H2L-enhanced' ? 'bg-teal-50/60 dark:bg-teal-950/25' : ''}`}>
              <span className="font-bold">{row.strategy}</span>
              <span className={row.group === 'H2L-enhanced' ? 'font-bold text-teal-700' : 'text-on-surface-variant'}>{row.group}</span>
              <span>{formatNumber(row.MAP)}</span>
              <span>{formatNumber(row.MRR)}</span>
              <span>{formatNumber(row[selectedNdcgKey])}</span>
              <span>{formatNumber(row.retrieval_time, 4)}s</span>
            </div>
          ))}
          {!comparisonTableRows.length && <div className="px-4 py-4 text-sm text-on-surface-variant">No benchmark rows loaded for selected Top K.</div>}
        </div>
      </details>

      <details className="rounded-xl bg-surface-container-low p-6">
        <summary className="cursor-pointer font-headline font-bold text-on-surface">Dataset + Ablation Interpretation</summary>
        <div className="mt-5 grid gap-4 lg:grid-cols-4">
          <MetricTile label="Train Cases" value={research.train_count ?? 'N/A'} hint={research.dataset_source || research.train_source || 'expanded_ground_truth.json'} />
          <MetricTile label="Test Cases" value={research.test_count ?? 'N/A'} hint={`${research.dataset_source || research.test_source || 'expanded_ground_truth.json'}`} />
          <MetricTile label="Polarity Cases" value={research.polarity_cases ?? 'N/A'} hint={`affirmative ${research.test_affirmative_cases ?? 'N/A'} · negated ${research.test_negated_cases ?? 'N/A'}`} tone={metricBackground(research.polarity_f1)} />
          <MetricTile label="Split" value={research.split_ratio || 'N/A'} hint={research.ground_truth_note || 'dataset split'} />
        </div>
        <div className="mt-5 rounded-xl bg-surface-container-lowest p-4">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">อ่านส่วนนี้อย่างไร</div>
          <p className="mt-2 text-sm leading-relaxed text-on-surface">
            Ablation คือการปิด/เปลี่ยนองค์ประกอบของ H2L ทีละส่วน แล้วดูว่า MAP, nDCG และ F1 เปลี่ยนไหม เพื่อบอกว่าส่วนไหนช่วยระบบจริง
          </p>
          <p className="mt-2 text-xs leading-relaxed text-on-surface-variant">
            ตารางนี้ใช้ artifact จริงจาก `ablation_results` เท่านั้น ถ้าจำนวน rows/cases น้อย ให้ใช้เป็นผลทดลองเบื้องต้น ไม่ใช่ข้อสรุปสุดท้ายของทั้งงาน
          </p>
        </div>
        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          {sensitivityEntries.map(([key, block]) => {
            const rows = block.rows || [];
            const baselineRow = ablationBaselineRow(key, rows);
            const best = block.best || {};
            const mapDelta = Number(best.map) - Number(baselineRow?.map);
            const ndcgDelta = Number(best.ndcg_at_k) - Number(baselineRow?.ndcg_at_k);
            const f1Delta = Number(best.f1_at_k) - Number(baselineRow?.f1_at_k);
            const bestName = ablationLabel(best);
            const baselineName = ablationLabel(baselineRow);
            const hasPositiveGain = [mapDelta, ndcgDelta, f1Delta].some((value) => Number.isFinite(value) && value > 0.000001);
            const isTie = rows.length > 0 && !hasPositiveGain && [mapDelta, ndcgDelta, f1Delta].every((value) => !Number.isFinite(value) || Math.abs(value) < 0.000001);
            return (
              <div key={key} className={`rounded-xl p-4 ${hasPositiveGain ? 'bg-teal-50 dark:bg-teal-950/40' : isTie ? 'bg-surface-container-lowest' : 'bg-yellow-50 dark:bg-yellow-950/40'}`}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">{ablationQuestion(key)}</div>
                    <h4 className="mt-1 font-bold text-on-surface">{block.title || key}</h4>
                  </div>
                  <StatusBadge label={block.source ? `${rows.length} settings` : 'missing'} tone={block.source ? 'live' : 'warning'} />
                </div>
                <p className="mt-3 text-sm leading-relaxed text-on-surface">{ablationTakeaway(key, block, baselineRow)}</p>
                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  <div className="rounded-lg bg-surface-container-low p-3">
                    <div className="text-[10px] font-bold uppercase text-on-surface-variant">ดีที่สุดใน artifact นี้</div>
                    <div className="mt-1 font-headline text-lg font-extrabold text-teal-700">{bestName}</div>
                    <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-on-surface-variant">
                      <span>MAP {formatNumber(best.map)}</span>
                      <span>nDCG {formatNumber(best.ndcg_at_k)}</span>
                      <span>F1 {formatNumber(best.f1_at_k)}</span>
                    </div>
                  </div>
                  <div className="rounded-lg bg-surface-container-low p-3">
                    <div className="text-[10px] font-bold uppercase text-on-surface-variant">เทียบกับฐาน</div>
                    <div className="mt-1 font-semibold text-on-surface">{baselineName}</div>
                    <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-on-surface-variant">
                      <span>ΔMAP {formatNumber(mapDelta)}</span>
                      <span>ΔnDCG {formatNumber(ndcgDelta)}</span>
                      <span>ΔF1 {formatNumber(f1Delta)}</span>
                    </div>
                  </div>
                </div>
                <div className="mt-3 rounded-lg bg-surface-container-low p-3 text-xs leading-relaxed text-on-surface-variant">
                  <strong className="text-on-surface">ควรตีความ:</strong> {block.meaning} {block.best?.count ? `ผลนี้สรุปจาก ${block.best.count} แถวใน artifact กลุ่มนี้` : ''}
                </div>
                <details className="mt-3 rounded-lg bg-surface-container-low p-3">
                  <summary className="cursor-pointer text-xs font-bold text-teal-700">ดูค่าดิบจาก artifact</summary>
                  <div className="mt-3 max-h-36 overflow-auto text-xs text-on-surface-variant">
                    {rows.slice(0, 8).map((row, index) => (
                      <div key={`${key}-${index}`} className="grid grid-cols-4 gap-2 border-t border-outline-variant/20 py-1">
                        <span className="font-bold">{ablationLabel(row)}</span>
                        <span>MAP {formatNumber(row.map)}</span>
                        <span>nDCG {formatNumber(row.ndcg_at_k)}</span>
                        <span>F1 {formatNumber(row.f1_at_k)}</span>
                      </div>
                    ))}
                    {!rows.length && <div>ไม่มี rows จาก artifact</div>}
                  </div>
                </details>
              </div>
            );
          })}
          {!sensitivityEntries.length && <div className="rounded-xl bg-surface-container-lowest p-4 text-sm text-on-surface-variant">No sensitivity artifact loaded.</div>}
        </div>
        {research.ablation_highlights && (
          <details className="mt-5 rounded-xl bg-surface-container-lowest p-4">
            <summary className="cursor-pointer text-sm font-bold text-on-surface">ดูข้อความจาก ablation report เดิม</summary>
            <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap text-xs leading-relaxed text-on-surface-variant">{research.ablation_highlights}</pre>
          </details>
        )}
      </details>
    </div>
  );
}

function AuditAndFinalizePanel({
  auditLoading,
  auditPacket,
  disabled,
  expertOverrideAdded,
  expertOverrideRejected,
  finalizeLoading,
  onPrepareAudit,
  onSubmitReview,
  publicPreview,
  reviewSummary,
  reviewerNote,
  setExpertOverrideAdded,
  setExpertOverrideRejected,
  setReviewerNote,
  setZeroFindingAcknowledged,
  signoffPacket,
  zeroFindingAcknowledged,
}) {
  const busy = auditLoading || finalizeLoading;
  const interactionDisabled = disabled || publicPreview || busy;
  const reviewComplete = reviewSummary.pending === 0 && (reviewSummary.total > 0 || zeroFindingAcknowledged);
  const submitDisabled = interactionDisabled || !reviewComplete || Boolean(signoffPacket);

  return (
    <section className="mt-5 rounded-lg bg-surface-container-low p-5 sm:p-6" aria-labelledby="professional-review-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span aria-hidden="true" className="material-symbols-outlined text-[21px] text-teal-700 dark:text-teal-300">fact_check</span>
            <h2 className="font-headline text-lg font-bold text-on-surface" id="professional-review-title">การทบทวนโดยผู้ปฏิบัติงาน</h2>
          </div>
          <p className="mt-1 text-sm text-on-surface-variant">บันทึกประเด็นที่แตกต่างจากผลของระบบก่อนส่งเข้าสู่การทบทวนโดยผู้เชี่ยวชาญ</p>
        </div>
        <StatusBadge label={signoffPacket ? 'ส่งเพื่อทบทวนแล้ว' : 'รอการทบทวน'} tone={signoffPacket ? 'live' : 'warning'} />
      </div>

      {publicPreview && (
        <div className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
          โหมดสาธิตภายนอกปิดการจัดเตรียม audit packet และการส่งผลเพื่อทบทวน
        </div>
      )}

      <div className="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-lg bg-slate-200 dark:bg-slate-700 sm:grid-cols-4" aria-label="สรุปสถานะการทบทวนประเด็น">
        {[
          { label: 'รับไว้', value: reviewSummary.accepted, tone: 'text-emerald-700 dark:text-emerald-300' },
          { label: 'ต้องทบทวน', value: reviewSummary.review, tone: 'text-amber-700 dark:text-amber-300' },
          { label: 'ไม่นำไปใช้', value: reviewSummary.excluded, tone: 'text-slate-700 dark:text-slate-200' },
          { label: 'ยังไม่ระบุ', value: reviewSummary.pending, tone: reviewSummary.pending ? 'text-red-700 dark:text-red-300' : 'text-emerald-700 dark:text-emerald-300' },
        ].map((item) => (
          <div className="bg-white px-3 py-3 text-center dark:bg-slate-900" key={item.label}>
            <strong className={`block text-xl tabular-nums ${item.tone}`}>{item.value}</strong>
            <span className="mt-0.5 block text-xs text-on-surface-variant">{item.label}</span>
          </div>
        ))}
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(300px,0.75fr)]">
        <div className="rounded-lg bg-white p-4 dark:bg-slate-900">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="block">
              <span className="mb-1.5 block text-sm font-semibold text-on-surface">เพิ่มประเด็นที่ระบบไม่พบ</span>
              <input
                className="min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-on-surface focus:border-teal-600 focus:outline-none focus:ring-2 focus:ring-teal-600/20 dark:border-slate-700 dark:bg-slate-950"
                autoComplete="off"
                disabled={interactionDisabled}
                name="expert-override-added"
                onChange={(event) => setExpertOverrideAdded(event.target.value)}
                placeholder="เช่น 0102, F32"
                type="text"
                value={expertOverrideAdded}
              />
              <span className="mt-1 block text-xs text-on-surface-variant">คั่นหลายรหัสด้วยเครื่องหมายจุลภาค</span>
            </label>
            <label className="block">
              <span className="mb-1.5 block text-sm font-semibold text-on-surface">เพิ่มรหัสที่ไม่นำไปใช้</span>
              <input
                className="min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-on-surface focus:border-teal-600 focus:outline-none focus:ring-2 focus:ring-teal-600/20 dark:border-slate-700 dark:bg-slate-950"
                autoComplete="off"
                disabled={interactionDisabled}
                name="expert-override-rejected"
                onChange={(event) => setExpertOverrideRejected(event.target.value)}
                placeholder="เช่น Z63"
                type="text"
                value={expertOverrideRejected}
              />
              <span className="mt-1 block text-xs text-on-surface-variant">ใช้เมื่อข้อมูลจริงไม่สนับสนุนข้อเสนอของระบบ</span>
            </label>
          </div>

          <label className="mt-4 block">
            <span className="mb-1.5 block text-sm font-semibold text-on-surface">บันทึกของผู้ทบทวน</span>
            <textarea
              className="min-h-28 w-full rounded-lg border border-slate-300 bg-white p-3 text-sm text-on-surface focus:border-teal-600 focus:outline-none focus:ring-2 focus:ring-teal-600/20 dark:border-slate-700 dark:bg-slate-950"
              autoComplete="off"
              disabled={interactionDisabled}
              name="reviewer-note"
              onChange={(event) => setReviewerNote(event.target.value)}
              placeholder="บันทึกข้อสังเกต การตรวจสอบเพิ่มเติม หรือเหตุผลประกอบการตัดสินใจ"
              value={reviewerNote}
            />
          </label>

          {reviewSummary.total === 0 && (
            <label className="mt-4 flex min-h-12 items-start gap-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-950 dark:bg-amber-950/40 dark:text-amber-100">
              <input
                checked={zeroFindingAcknowledged}
                className="mt-0.5 h-5 w-5 rounded border-amber-400 text-teal-700 focus:ring-teal-600"
                disabled={interactionDisabled}
                onChange={(event) => setZeroFindingAcknowledged(event.target.checked)}
                type="checkbox"
              />
              <span>
                <strong className="block">ยืนยันการตรวจกรณีไม่พบประเด็น</strong>
                <span className="mt-0.5 block leading-relaxed">ตรวจข้อมูลต้นฉบับและบริบทความปลอดภัยแล้ว และไม่พบประเด็นเพิ่มเติมจากข้อมูลที่มี</span>
              </span>
            </label>
          )}

          <div className="mt-4 flex flex-wrap justify-end gap-2">
            <button
              className="min-h-11 rounded-lg bg-slate-100 px-4 py-2 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-200 disabled:opacity-50 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
              disabled={interactionDisabled}
              onClick={onPrepareAudit}
              type="button"
            >
              {auditLoading ? 'กำลังจัดเตรียม…' : 'จัดเตรียมข้อมูลสำหรับทบทวนซ้ำ'}
            </button>
            <button
              className="min-h-11 rounded-lg bg-[#0d2734] px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-[#16394a] disabled:cursor-not-allowed disabled:bg-slate-400"
              aria-describedby="review-submit-help"
              disabled={submitDisabled}
              onClick={onSubmitReview}
              type="button"
            >
              {finalizeLoading ? 'กำลังส่ง…' : 'ส่งเพื่อให้ผู้เชี่ยวชาญทบทวน'}
            </button>
          </div>
          <p className={`mt-2 text-right text-xs ${reviewComplete ? 'text-on-surface-variant' : 'font-semibold text-amber-700 dark:text-amber-300'}`} id="review-submit-help">
            {signoffPacket
              ? 'ส่งข้อมูลชุดนี้แล้ว แก้ไขบันทึกหรือสถานะ finding เพื่อจัดเตรียมฉบับใหม่'
              : reviewComplete
                ? 'พร้อมส่งเมื่อข้อมูลเคสและการตั้งค่าตรงกับผลวิเคราะห์ปัจจุบัน'
                : reviewSummary.total === 0
                  ? 'กรุณายืนยันว่าได้ตรวจข้อมูลต้นฉบับและบริบทความปลอดภัยแล้ว'
                  : `กรุณาระบุสถานะ finding ที่เหลือ ${reviewSummary.pending} รายการก่อนส่ง`}
          </p>
        </div>

        <aside className="rounded-lg bg-white p-4 dark:bg-slate-900">
          <h3 className="font-semibold text-on-surface">สถานะการทบทวน</h3>
          <div className="mt-3 space-y-2 text-sm text-on-surface-variant">
            {[
              { label: 'วิเคราะห์เคสปัจจุบันแล้ว', done: !disabled },
              { label: 'ระบุสถานะประเด็นครบแล้ว', done: reviewComplete },
              { label: 'บันทึกข้อสังเกตหรือ override (ถ้ามี)', done: Boolean(reviewerNote.trim() || expertOverrideAdded.trim() || expertOverrideRejected.trim() || signoffPacket) },
              { label: 'ส่งเข้าสู่ human review', done: Boolean(signoffPacket) },
            ].map((item) => (
              <div className="flex items-start gap-2" key={item.label}>
                <span aria-hidden="true" className={`material-symbols-outlined mt-0.5 text-[18px] ${item.done ? 'text-emerald-600 dark:text-emerald-300' : 'text-slate-300 dark:text-slate-600'}`}>{item.done ? 'check_circle' : 'radio_button_unchecked'}</span>
                <span>{item.label}</span>
              </div>
            ))}
          </div>

          {auditPacket && (
            <details className="clinical-details mt-4 rounded-lg bg-slate-50 p-3 dark:bg-slate-800/70">
              <summary className="flex min-h-11 items-center justify-between gap-3 text-sm font-semibold text-on-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600">
                <span>Audit packet {auditPacket.audit_id}</span>
                <span aria-hidden="true" className="details-chevron material-symbols-outlined transition-transform">expand_more</span>
              </summary>
              <div className="mt-2 grid gap-1 text-xs text-on-surface-variant">
                <span className="mb-1 font-semibold text-on-surface">ผลการคัดกรองจากระบบ</span>
                <span>ระบบนำไปใช้: <strong>{(auditPacket.accepted_problems || []).length}</strong></span>
                <span>ระบบกรองออก: <strong>{(auditPacket.rejected_candidates || []).length}</strong></span>
                <span>เอกสารหลักฐาน: <strong>{(auditPacket.evidence_docs || []).length}</strong></span>
              </div>
              <pre className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-slate-950 p-3 text-xs text-teal-200">{auditPacket.export_markdown}</pre>
            </details>
          )}

          {signoffPacket && (
            <div className="mt-4 rounded-lg bg-emerald-50 p-3 dark:bg-emerald-950/30">
              <StatusBadge label={signoffPacket.status} tone="live" />
              <div className="mt-3 space-y-2">
                {(signoffPacket.checklist || []).map((item) => (
                  <div className="flex items-start gap-2 text-sm text-on-surface-variant" key={item.item}>
                    <span aria-hidden="true" className={`material-symbols-outlined mt-0.5 text-[18px] ${item.done ? 'text-emerald-600' : 'text-amber-500'}`}>{item.done ? 'check_circle' : 'radio_button_unchecked'}</span>
                    {item.item}
                  </div>
                ))}
              </div>
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}

function WorkspaceEmptyState({ actionLabel, disabled, icon = 'clinical_notes', message, onAction, title }) {
  return (
    <section className="page-enter flex min-h-[320px] flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white px-5 py-12 text-center dark:border-slate-700 dark:bg-slate-900/60">
      <div className="flex h-14 w-14 items-center justify-center rounded-lg bg-teal-50 text-teal-700 dark:bg-teal-950/50 dark:text-teal-200">
        <span aria-hidden="true" className="material-symbols-outlined text-[28px]">{icon}</span>
      </div>
      <h2 className="mt-5 font-headline text-xl font-bold text-on-surface">{title}</h2>
      <p className="mt-2 max-w-xl text-sm leading-relaxed text-on-surface-variant">{message}</p>
      {onAction && (
        <button
          className="mt-6 min-h-11 rounded-lg bg-[#0d2734] px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[#16394a] disabled:bg-slate-400"
          disabled={disabled}
          onClick={onAction}
          type="button"
        >
          {actionLabel}
        </button>
      )}
    </section>
  );
}

export default function App() {
  const [caseDescription, setCaseDescription] = useState('');
  const [analyzedCase, setAnalyzedCase] = useState('');
  const [userAdjustedSpans, setUserAdjustedSpans] = useState([]);
  const [pendingAnchorSpan, setPendingAnchorSpan] = useState(null);
  const [analyzedUserAdjustedSpans, setAnalyzedUserAdjustedSpans] = useState([]);
  const [analyzedStrategy, setAnalyzedStrategy] = useState('h2l-hybrid');
  const [analyzedL2, setAnalyzedL2] = useState(true);
  const [analyzedL2Model, setAnalyzedL2Model] = useState(DEFAULT_L2_MODEL);
  const [analyzedTopK, setAnalyzedTopK] = useState(DEFAULT_DOC_TOP_K);
  const [selectedFamily, setSelectedFamily] = useState('hybrid');
  const [selectedMode, setSelectedMode] = useState('enhanced');
  const [enableL2, setEnableL2] = useState(true);
  const [selectedL2Model, setSelectedL2Model] = useState(DEFAULT_L2_MODEL);
  const [evidenceTopK, setEvidenceTopK] = useState(DEFAULT_DOC_TOP_K);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [actionMessage, setActionMessage] = useState(null);
  const [hasSubmitted, setHasSubmitted] = useState(false);
  const [activeTab, setActiveTab] = useState(() => {
    const hash = typeof window !== 'undefined' ? window.location.hash.replace(/^#\/?/, '') : '';
    if (hash === 'explainability') return 'keywords';
    return ['analysis', 'keywords', 'pipeline', 'vectors', 'evaluation'].includes(hash) ? hash : 'analysis';
  });
  const [evaluationSummary, setEvaluationSummary] = useState(null);
  const [evaluationLastSyncedAt, setEvaluationLastSyncedAt] = useState(null);
  const [benchmarkTopK, setBenchmarkTopK] = useState(DEFAULT_DOC_TOP_K);
  const [, setThesisStatus] = useState(null);
  const [runtimeStatus, setRuntimeStatus] = useState({ status: 'loading', stage: 'not-started', components: {}, errors: [] });
  const [theme, setTheme] = useState(() => localStorage.getItem('h2l-theme') || 'light');
  const [auditPacket, setAuditPacket] = useState(null);
  const [signoffPacket, setSignoffPacket] = useState(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [finalizeLoading, setFinalizeLoading] = useState(false);
  const [reviewerNote, setReviewerNote] = useState('');
  const [expertOverrideAdded, setExpertOverrideAdded] = useState('');
  const [expertOverrideRejected, setExpertOverrideRejected] = useState('');
  const [findingReviewStates, setFindingReviewStates] = useState({});
  const [zeroFindingAcknowledged, setZeroFindingAcknowledged] = useState(false);
  const publicOrigin = typeof window !== 'undefined' ? window.location.origin : '';
  const publicHostname = typeof window !== 'undefined' ? window.location.hostname : '';
  const isPublicPreview = PUBLIC_DEMO_MODE;

  const strategyPairs = runtimeStatus?.strategy_pairs || evaluationSummary?.strategy_pairs || DEFAULT_STRATEGY_PAIRS;
  const selectedPair = strategyPairs.find((pair) => pair.family === selectedFamily) || strategyPairs[0] || DEFAULT_STRATEGY_PAIRS[3];
  const selectedStrategy = selectedMode === 'baseline' ? selectedPair.baseline : selectedPair.enhanced;
  const selectedStrategyUnavailable = runtimeStatus?.strategy_options
    ?.find((option) => option.id === selectedStrategy)
    ?.available === false;
  const l2ModelOptions = runtimeStatus?.l2_model_options?.length
    ? runtimeStatus.l2_model_options
    : [{ id: DEFAULT_L2_MODEL, label: 'Qwen 2.5 7B', detail: 'Current local baseline', parameters: '7.6B', size_gb: 4.36, available: false, default: true }];
  const selectedL2Option = l2ModelOptions.find((option) => option.id === selectedL2Model);
  const serializeUserAdjustedSpans = (spans) => JSON.stringify(
    (spans || [])
      .map((span) => ({
        start: Number(span.start || 0),
        end: Number(span.end || 0),
        text: String(span.text || ''),
      }))
      .sort((left, right) => left.start - right.start || left.end - right.end || left.text.localeCompare(right.text, 'th')),
  );
  const userAdjustedSignature = serializeUserAdjustedSpans(userAdjustedSpans);
  const analyzedUserAdjustedSignature = serializeUserAdjustedSpans(analyzedUserAdjustedSpans);
  const activeWorkspace = explainabilityTabs.some((tab) => tab.id === activeTab) ? 'explainability' : activeTab;
  const navigateWorkspace = (workspaceId) => {
    if (workspaceId === 'explainability') {
      setActiveTab((current) => explainabilityTabs.some((tab) => tab.id === current) ? current : 'keywords');
      return;
    }
    setActiveTab(workspaceId);
  };

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    localStorage.setItem('h2l-theme', theme);
  }, [theme]);

  useEffect(() => {
    if (!runtimeStatus?.l2_model_options?.length) return;
    const current = runtimeStatus.l2_model_options.find((option) => option.id === selectedL2Model);
    if (current?.available) return;
    const fallback = runtimeStatus.l2_model_options.find((option) => option.default && option.available)
      || runtimeStatus.l2_model_options.find((option) => option.available);
    if (fallback) setSelectedL2Model(fallback.id);
  }, [runtimeStatus?.l2_model_options, selectedL2Model]);

  useEffect(() => {
    const nextHash = `#/${activeTab}`;
    if (window.location.hash !== nextHash) window.history.replaceState(null, '', nextHash);
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.scrollTo({ top: 0, behavior: reduceMotion ? 'auto' : 'smooth' });
  }, [activeTab]);

  const refreshEvaluationSummary = async () => {
    try {
      const data = await fetchJson('/evaluation-summary', {}, 20000);
      setEvaluationSummary(data);
      setEvaluationLastSyncedAt(new Date().toISOString());
      return data;
    } catch {
      return null;
    }
  };

  const refreshRuntime = async () => {
    try {
      const data = await fetchJson('/runtime/status', {}, 15000);
      setRuntimeStatus(data);
      return data;
    } catch (err) {
      setRuntimeStatus((current) => ({ ...current, status: 'error', stage: 'runtime/status unavailable', errors: [{ component: 'api', message: err.message }] }));
      return null;
    }
  };

  const refreshThesisStatus = async () => {
    try {
      const data = await fetchJson('/thesis/status', {}, 20000);
      setThesisStatus(data);
      if (data.runtime_status) setRuntimeStatus(data.runtime_status);
      return data;
    } catch (err) {
      setThesisStatus((current) => ({
        ...(current || {}),
        status: 'error',
        thesis_ready: false,
        interpretation: `อ่าน /thesis/status ไม่สำเร็จ: ${err.message}`,
        checks: [],
        features: [],
        blockers: [{ id: 'thesis_status', label: '/thesis/status unavailable', status: 'error' }],
      }));
      return null;
    }
  };

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      if (cancelled) return;
      await refreshRuntime();
    };
    poll();
    const interval = window.setInterval(poll, runtimeStatus.status === 'loading' ? 2000 : 8000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [runtimeStatus.status]);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      if (cancelled) return;
      await refreshThesisStatus();
    };
    poll();
    const interval = window.setInterval(poll, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    refreshEvaluationSummary();
  }, []);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      if (cancelled) return;
      await refreshEvaluationSummary();
    };
    poll();
    
    // Dynamic polling interval: fast (2s) when loading/degraded, medium (10s) when ready
    const isRuntimeWaiting = runtimeStatus.status === 'loading';
    const pollInterval = isRuntimeWaiting ? 2000 : 10000;
    
    const interval = window.setInterval(poll, pollInterval);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [activeTab, runtimeStatus.status]);

  const analyzeCase = async () => {
    const trimmedCase = caseDescription.trim();
    if (!trimmedCase) {
      setResult(null);
      setAnalyzedCase('');
      setAnalyzedUserAdjustedSpans([]);
      setHasSubmitted(true);
      setError('กรุณาป้อนข้อมูลเคสก่อนเริ่มวิเคราะห์');
      return;
    }

    setLoading(true);
    setError('');
    setAuditPacket(null);
    setSignoffPacket(null);
    setActionMessage({
      tone: 'neutral',
      title: 'กำลังวิเคราะห์เคสและค้นหาแนวทาง',
      detail: `วิธีที่ร้องขอ ${selectedStrategy} · L2 ${selectedMode === 'enhanced' && enableL2 ? selectedL2Model : 'ปิด'} · หลักฐาน Top ${evidenceTopK}`,
    });
    setHasSubmitted(true);

    try {
      const data = await fetchJson('/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          case_description: caseDescription,
          strategy: selectedStrategy,
          enable_l2: enableL2,
          llm_model: selectedL2Model,
          top_k: evidenceTopK,
          user_adjusted_spans: userAdjustedSpans,
        }),
      });
      setResult(data);
      setFindingReviewStates({});
      setReviewerNote('');
      setExpertOverrideAdded('');
      setExpertOverrideRejected('');
      setZeroFindingAcknowledged(false);
      setRuntimeStatus(data.runtime_status || runtimeStatus);
      setAnalyzedCase(trimmedCase);
      setAnalyzedUserAdjustedSpans(userAdjustedSpans);
      setAnalyzedStrategy(data.requested_strategy || selectedStrategy);
      setAnalyzedL2(enableL2);
      setAnalyzedL2Model(data.model_provenance?.selected_l2_model || selectedL2Model);
      setAnalyzedTopK(data.top_k || evidenceTopK);
      setActionMessage({
        tone: data.runtime_status?.status === 'degraded' ? 'warning' : 'live',
        title: 'วิเคราะห์เคสเสร็จแล้ว',
        detail: `เคส ${data.case_id} · วิธีที่ใช้จริง ${data.effective_strategy || data.requested_strategy} · L2 ${data.model_provenance?.effective_l2_model || 'ไม่ได้เรียก'} · พบ ${data.problems?.length || 0} ประเด็น · หลักฐาน ${data.retrieved_docs_count || 0} รายการ${data.effective_strategy && data.requested_strategy !== data.effective_strategy ? ` · เปลี่ยนจาก ${data.requested_strategy} เนื่องจากข้อจำกัด runtime` : ''}`,
      });
      setActiveTab('analysis');
    } catch (err) {
      console.error(err);
      const runtimePayload = err.payload?.detail?.runtime_status;
      if (runtimePayload) setRuntimeStatus(runtimePayload);
      setResult(null);
      setFindingReviewStates({});
      setAnalyzedCase('');
      setAnalyzedUserAdjustedSpans([]);
      setError(err.name === 'AbortError' ? 'API ใช้เวลานานเกินกำหนด กรุณาดู Runtime Status ว่าโมเดล/index พร้อมหรือไม่' : `เชื่อมต่อ/ประมวลผล API ไม่สำเร็จ: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleCaseDescriptionChange = (event) => {
    const nextValue = event.target.value;
    const hadAnchors = userAdjustedSpans.length > 0;
    setCaseDescription(event.target.value);
    setPendingAnchorSpan(null);
    if (hadAnchors) setUserAdjustedSpans([]);
    setError('');
    if (result && nextValue.trim() !== analyzedCase) {
      setActionMessage({
        tone: 'neutral',
        title: 'ข้อความเคสเปลี่ยนแล้ว',
        detail: hadAnchors
          ? 'ข้อความเคสเปลี่ยนแล้ว จึงล้างตำแหน่งคำสำคัญเดิมเพื่อป้องกันตำแหน่งคลาดเคลื่อน กรุณาวิเคราะห์ใหม่'
          : 'ผลเดิมถูกพักไว้ กรุณาวิเคราะห์เคสปัจจุบันใหม่ก่อนทบทวนหรือส่งผล',
      });
    }
  };

  const handleCaseSelection = (event) => {
    const start = Number(event.target.selectionStart || 0);
    const end = Number(event.target.selectionEnd || 0);
    if (end <= start) {
      setPendingAnchorSpan(null);
      return;
    }
    const text = event.target.value.slice(start, end);
    if (!text.trim()) {
      setPendingAnchorSpan(null);
      return;
    }
    setPendingAnchorSpan({
      start,
      end,
      text,
      keyword: text,
      scope: 'match',
      position_source: 'user_adjusted',
      user_adjusted: true,
    });
  };

  const addPendingAnchorSpan = () => {
    if (!pendingAnchorSpan) return;
    setUserAdjustedSpans((current) => {
      const alreadyExists = current.some((span) => span.start === pendingAnchorSpan.start && span.end === pendingAnchorSpan.end);
      if (alreadyExists) return current;
      return [...current, pendingAnchorSpan].sort((left, right) => left.start - right.start || left.end - right.end);
    });
    if (result) {
      setActionMessage({
        tone: 'neutral',
        title: 'เพิ่ม anchor position แล้ว',
        detail: 'ตำแหน่งที่เลือกจะถูกใช้ในการวิเคราะห์รอบถัดไป กรุณาวิเคราะห์ใหม่เพื่ออัปเดตผล',
      });
    }
  };

  const removeUserAdjustedSpan = (start, end) => {
    setUserAdjustedSpans((current) => current.filter((span) => span.start !== start || span.end !== end));
    if (result) {
      setActionMessage({
        tone: 'neutral',
        title: 'ลบ anchor position แล้ว',
        detail: 'ผลปัจจุบันยังอ้างตำแหน่งเดิมอยู่ กดวิเคราะห์เคสอีกครั้งเพื่อประเมินตามตำแหน่งล่าสุด',
      });
    }
  };

  const clearUserAdjustedSpans = () => {
    setUserAdjustedSpans([]);
    setPendingAnchorSpan(null);
    if (result) {
      setActionMessage({
        tone: 'neutral',
        title: 'ล้าง anchor position แล้ว',
        detail: 'ผลปัจจุบันยังอ้างตำแหน่งเดิมอยู่ กดวิเคราะห์เคสอีกครั้งเพื่อประเมินโดยไม่ใช้ตำแหน่งที่กำหนดเอง',
      });
    }
  };

  const verifyDataset = async () => {
    setError('');
    setActionMessage({ tone: 'neutral', title: 'กำลังตรวจสอบระบบ', detail: 'กำลังอ่านสถานะ API, runtime และข้อมูลประเมิน…' });
    try {
      const [health, runtime, thesis, evaluation] = await Promise.all([fetchJson('/health', {}, 15000), fetchJson('/runtime/status', {}, 15000), fetchJson('/thesis/status', {}, 20000), refreshEvaluationSummary()]);
      setRuntimeStatus(runtime);
      setThesisStatus(thesis);
      setActionMessage({
        tone: evaluation?.data_sources?.freshness?.needs_review ? 'warning' : thesis.status === 'ready' ? 'live' : thesis.status === 'degraded' ? 'warning' : 'neutral',
        title: 'ตรวจสอบสถานะระบบแล้ว',
        detail: `api=${health.status}; runtime=${runtime.status}; thesis=${thesis.status}; checks=${(thesis.checks || []).filter((check) => check.status === 'ready').length}/${(thesis.checks || []).length}; performance=${evaluation?.data_sources?.freshness?.needs_review ? 'needs review' : 'current'}; l2_ready=${String(runtime.l2_ready)}`,
      });
    } catch (err) {
      setActionMessage({ tone: 'error', title: 'ตรวจสอบระบบไม่สำเร็จ', detail: `${err.message} กรุณาตรวจสอบ backend แล้วลองอีกครั้ง` });
    }
  };

  const reviewPerformanceSnapshot = async () => {
    setActionMessage({
      tone: 'neutral',
      title: 'กำลังอัปเดตผลประเมินงานวิจัย',
      detail: 'กำลังอ่าน evaluation artifacts ชุดล่าสุด…',
    });
    try {
      const [evaluation, thesis] = await Promise.all([refreshEvaluationSummary(), refreshThesisStatus()]);
      if (!evaluation) throw new Error('ไม่สามารถอ่าน evaluation artifacts ล่าสุดได้');
      const freshness = evaluation?.data_sources?.freshness || {};
      setActionMessage({
        tone: freshness.needs_review ? 'warning' : 'live',
        title: 'อัปเดตผลประเมินงานวิจัยแล้ว',
        detail: freshness.interpretation || thesis?.interpretation || 'Updated evaluation summary from current artifacts.',
      });
    } catch (err) {
      setActionMessage({ tone: 'error', title: 'อัปเดตผลประเมินไม่สำเร็จ', detail: `${err.message} กรุณาตรวจสอบ artifacts แล้วลองอีกครั้ง` });
    }
  };

  const invalidateSubmittedReview = () => {
    if (!signoffPacket) return;
    setSignoffPacket(null);
    setActionMessage({
      tone: 'neutral',
      title: 'แก้ไขข้อมูลการทบทวนแล้ว',
      detail: 'ฉบับที่ส่งก่อนหน้าถูกเก็บไว้ แต่หน้าจอนี้กลับมาเป็นฉบับร่าง กรุณาตรวจสอบและส่งใหม่เมื่อพร้อม',
    });
  };

  const updateFindingReviewState = (code, state) => {
    setFindingReviewStates((current) => ({ ...current, [code]: state }));
    invalidateSubmittedReview();
  };

  const updateReviewerNote = (value) => {
    setReviewerNote(value);
    invalidateSubmittedReview();
  };

  const updateExpertOverrideAdded = (value) => {
    setExpertOverrideAdded(value);
    invalidateSubmittedReview();
  };

  const updateExpertOverrideRejected = (value) => {
    setExpertOverrideRejected(value);
    invalidateSubmittedReview();
  };

  const updateZeroFindingAcknowledged = (value) => {
    setZeroFindingAcknowledged(value);
    invalidateSubmittedReview();
  };

  const requestSecondaryAudit = async () => {
    if (isPublicPreview) {
      setActionMessage({ tone: 'warning', title: 'โหมดสาธิตภายนอก', detail: 'การจัดเตรียม audit packet ถูกปิดในโหมดสาธิตภายนอก' });
      return;
    }
    const resultMatchesInput = result
      && caseDescription.trim() === analyzedCase
      && userAdjustedSignature === analyzedUserAdjustedSignature
      && selectedStrategy === analyzedStrategy
      && enableL2 === analyzedL2
      && evidenceTopK === analyzedTopK;
    if (!resultMatchesInput) {
      setActionMessage({ tone: 'warning', title: 'ผลเคสไม่ตรงกับการตั้งค่าปัจจุบัน', detail: 'กรุณาวิเคราะห์เคสอีกครั้งก่อนจัดเตรียมข้อมูลสำหรับทบทวนซ้ำ' });
      return;
    }
    setAuditLoading(true);
    try {
      const packet = await fetchJson('/audit/prepare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ case_id: result.case_id }),
      });
      setAuditPacket(packet);
      setActionMessage({ tone: 'live', title: 'จัดเตรียมข้อมูลสำหรับทบทวนซ้ำแล้ว', detail: `Audit ${packet.audit_id} · หลักฐาน ${(packet.evidence_docs || []).length} รายการ · รายการที่ระบบไม่นำไปใช้ ${(packet.rejected_candidates || []).length}` });
    } catch (err) {
      setActionMessage({ tone: 'error', title: 'จัดเตรียมข้อมูลทบทวนไม่สำเร็จ', detail: err.message });
    } finally {
      setAuditLoading(false);
    }
  };

  const finalizeCase = async () => {
    if (isPublicPreview) {
      setActionMessage({ tone: 'warning', title: 'โหมดสาธิตภายนอก', detail: 'การส่งผลเพื่อให้ผู้เชี่ยวชาญทบทวนถูกปิดในโหมดสาธิตภายนอก' });
      return;
    }
    const resultMatchesInput = result
      && caseDescription.trim() === analyzedCase
      && userAdjustedSignature === analyzedUserAdjustedSignature
      && selectedStrategy === analyzedStrategy
      && enableL2 === analyzedL2
      && evidenceTopK === analyzedTopK;
    if (!resultMatchesInput) {
      setActionMessage({ tone: 'warning', title: 'ยังส่งผลเพื่อทบทวนไม่ได้', detail: 'ข้อความเคสหรือการตั้งค่าถูกเปลี่ยน กรุณาวิเคราะห์ใหม่ก่อนส่งผล' });
      return;
    }
    const unresolvedFindings = (result.problems || []).filter((problem) => !findingReviewStates[problem.code]);
    if (unresolvedFindings.length) {
      setActionMessage({ tone: 'warning', title: 'ยังทบทวนประเด็นไม่ครบ', detail: `กรุณาระบุสถานะของ ${unresolvedFindings.map((problem) => problem.code).join(', ')} ก่อนส่งผล` });
      return;
    }
    if (!(result.problems || []).length && !zeroFindingAcknowledged) {
      setActionMessage({ tone: 'warning', title: 'ต้องยืนยันการตรวจข้อมูลต้นฉบับ', detail: 'ระบบไม่พบ finding จากข้อความที่ให้ กรุณาตรวจบริบทความปลอดภัยและยืนยันก่อนส่งผล' });
      return;
    }
    setFinalizeLoading(true);
    try {
      const normalizeCodes = (value) => [...new Set(value.split(',').map((code) => code.trim()).filter(Boolean))];
      const addedList = normalizeCodes(expertOverrideAdded);
      const reviewExcludedCodes = (result.problems || [])
        .filter((problem) => findingReviewStates[problem.code] === 'excluded')
        .map((problem) => problem.code);
      const rejectedList = [...new Set([...normalizeCodes(expertOverrideRejected), ...reviewExcludedCodes])];
      const invalidCodes = [...addedList, ...rejectedList].filter((code) => !/^[A-Za-z0-9._-]+$/.test(code));
      if (invalidCodes.length) throw new Error(`รูปแบบรหัสไม่ถูกต้อง: ${invalidCodes.join(', ')}`);
      const rejectedSet = new Set(rejectedList);
      const conflictingCodes = addedList.filter((code) => rejectedSet.has(code));
      if (conflictingCodes.length) throw new Error(`รหัสเดียวกันอยู่ทั้งรายการเพิ่มและไม่นำไปใช้: ${conflictingCodes.join(', ')}`);
      const selectedFindings = (result.problems || []).map((problem) => problem.code).filter((code) => !rejectedSet.has(code));

      const packet = await fetchJson('/case/finalize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          case_id: result.case_id,
          reviewer_note: reviewerNote,
          selected_findings: selectedFindings,
          finding_review_states: findingReviewStates,
          zero_finding_acknowledged: zeroFindingAcknowledged,
          expert_override_added: addedList,
          expert_override_rejected: rejectedList,
          final_status: 'Ready for Human Review',
        }),
      });
      setSignoffPacket(packet);
      setActionMessage({ tone: 'live', title: 'ส่งเคสเพื่อให้ผู้เชี่ยวชาญทบทวนแล้ว', detail: `เคส ${packet.case_id} · checklist ${(packet.checklist || []).filter((item) => item.done).length}/${(packet.checklist || []).length}` });
    } catch (err) {
      setActionMessage({ tone: 'error', title: 'ส่งเคสเพื่อทบทวนไม่สำเร็จ', detail: err.message });
    } finally {
      setFinalizeLoading(false);
    }
  };

  const loadSampleCase = () => {
    setCaseDescription(SAMPLE_CASE);
    setPendingAnchorSpan(null);
    setUserAdjustedSpans([]);
    setError('');
    if (result) {
      setActionMessage({ tone: 'neutral', title: 'โหลดเคสตัวอย่างแล้ว', detail: 'กรุณาวิเคราะห์ใหม่เพื่อสร้างผลที่ตรงกับข้อความตัวอย่าง' });
    }
  };

    const isCaseDirty = Boolean(
      result
      && (
        caseDescription.trim() !== analyzedCase
        || userAdjustedSignature !== analyzedUserAdjustedSignature
        || selectedStrategy !== analyzedStrategy
        || enableL2 !== analyzedL2
        || selectedL2Model !== analyzedL2Model
        || evidenceTopK !== analyzedTopK
      )
    );
  const hasFreshResult = Boolean(result && !isCaseDirty);
  const reviewSummary = (result?.problems || []).reduce((summary, problem) => {
    const state = findingReviewStates[problem.code];
    if (state === 'accepted' || state === 'review' || state === 'excluded') summary[state] += 1;
    else summary.pending += 1;
    summary.total += 1;
    return summary;
  }, { accepted: 0, review: 0, excluded: 0, pending: 0, total: 0 });
  const displayResult = isCaseDirty ? { ...emptyResult, status: 'stale', case_description: analyzedCase || '' } : result || emptyResult;
  const dataTone = loading
    ? 'neutral'
    : !isCaseDirty && result
      ? 'live'
      : error || runtimeStatus.status === 'error'
        ? 'error'
        : runtimeStatus.status === 'degraded'
          ? 'warning'
          : 'neutral';
  const dataLabel = loading
    ? 'กำลังวิเคราะห์'
    : isCaseDirty
      ? 'ต้องวิเคราะห์ใหม่'
      : result
        ? 'มีผลเคสปัจจุบัน'
        : error
          ? 'เกิดข้อผิดพลาด'
          : runtimeStatus.status === 'error'
            ? 'ระบบไม่พร้อม'
            : runtimeStatus.status === 'loading'
              ? 'กำลังเตรียมระบบ'
              : runtimeStatus.status === 'degraded'
                ? 'ระบบจำกัด'
                : hasSubmitted
                  ? 'รอผล'
                  : 'ยังไม่ได้ประเมิน';
  const selectedL2Unavailable = selectedMode === 'enhanced' && enableL2 && selectedL2Option?.available === false;
  const analyzeDisabled = loading || !caseDescription.trim() || selectedStrategyUnavailable || selectedL2Unavailable || runtimeStatus.status === 'loading' || runtimeStatus.status === 'error';

  const runtimeHint = useMemo(() => {
    if (selectedStrategyUnavailable) return `วิธี ${selectedStrategy} ไม่พร้อมใน runtime ปัจจุบัน กรุณาเลือกวิธีอื่น`;
    if (selectedL2Unavailable) return `โมเดล ${selectedL2Model} ไม่พร้อมใน local runtime กรุณาเลือกโมเดลอื่น`;
    if (runtimeStatus.status === 'loading') return 'กำลังโหลดโมเดลและดัชนีเอกสาร';
    if (runtimeStatus.status === 'degraded') return 'ระบบจะใช้เฉพาะองค์ประกอบที่พร้อม และระบุวิธีที่ใช้จริงในผลลัพธ์';
    if (runtimeStatus.status === 'ready') return 'พร้อมวิเคราะห์เคสและค้นหาแนวทางจากเอกสารจริง';
    return 'กรุณาตรวจสอบการเชื่อมต่อ backend';
  }, [runtimeStatus.status, selectedL2Model, selectedL2Unavailable, selectedStrategy, selectedStrategyUnavailable]);

  return (
    <ClinicalShell
      activeTab={activeWorkspace}
      caseStatusLabel={dataLabel}
      caseStatusTone={dataTone}
      navItems={navItems}
      onNavigate={navigateWorkspace}
      onToggleTheme={() => setTheme((current) => (current === 'dark' ? 'light' : 'dark'))}
      onVerifyRuntime={verifyDataset}
      runtimeStatus={runtimeStatus}
      theme={theme}
    >
      {isPublicPreview && (
        <section className="mb-5 flex flex-wrap items-start justify-between gap-3 rounded-lg bg-amber-50 p-4 text-amber-950 dark:bg-amber-950/40 dark:text-amber-100">
          <div className="flex min-w-0 gap-3">
            <span aria-hidden="true" className="material-symbols-outlined shrink-0 text-[21px]">public</span>
            <div>
              <h2 className="text-sm font-semibold">โหมดสาธิตผ่านลิงก์ภายนอก</h2>
              <p className="mt-1 text-sm leading-relaxed">การวิเคราะห์ยังใช้งานได้เพื่อการสาธิต แต่ audit packet และการส่งเคสเพื่อทบทวนถูกปิด กรุณาอย่าป้อนข้อมูลระบุตัวบุคคลจริง</p>
            </div>
          </div>
          <StatusBadge label={publicHostname || publicOrigin} tone="warning" />
        </section>
      )}

      {runtimeStatus.status !== 'ready' && <RuntimeBanner runtimeStatus={runtimeStatus} onRefresh={verifyDataset} />}

      {error && (
        <section className="mb-5 flex items-start justify-between gap-3 rounded-lg bg-red-50 p-4 text-red-900 dark:bg-red-950/50 dark:text-red-100" role="alert">
          <div className="flex min-w-0 gap-3">
            <span aria-hidden="true" className="material-symbols-outlined shrink-0 text-[21px]">error</span>
            <div>
              <h2 className="text-sm font-semibold">ไม่สามารถดำเนินการได้</h2>
              <p className="mt-1 text-sm leading-relaxed">{error}</p>
            </div>
          </div>
          <button aria-label="ปิดข้อความผิดพลาด" className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-600 dark:hover:bg-red-900/50" onClick={() => setError('')} type="button">
            <span aria-hidden="true" className="material-symbols-outlined">close</span>
          </button>
        </section>
      )}

      {actionMessage && (
        <section
          aria-live="polite"
          className={`mb-5 flex items-start justify-between gap-3 rounded-lg p-4 ${actionMessage.tone === 'error' ? 'bg-red-50 text-red-900 dark:bg-red-950/50 dark:text-red-100' : actionMessage.tone === 'live' ? 'bg-emerald-50 text-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-100' : actionMessage.tone === 'warning' ? 'bg-amber-50 text-amber-950 dark:bg-amber-950/40 dark:text-amber-100' : 'bg-slate-100 text-on-surface dark:bg-slate-800'}`}
        >
          <div className="flex min-w-0 gap-3">
            <span aria-hidden="true" className="material-symbols-outlined shrink-0 text-[21px]">{actionMessage.tone === 'error' ? 'error' : actionMessage.tone === 'live' ? 'check_circle' : 'info'}</span>
            <div>
              <h2 className="text-sm font-semibold">{actionMessage.title}</h2>
              <p className="mt-1 text-sm leading-relaxed">{actionMessage.detail}</p>
            </div>
          </div>
          <button aria-label="ปิดข้อความสถานะ" className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 dark:hover:bg-white/10" onClick={() => setActionMessage(null)} type="button">
            <span aria-hidden="true" className="material-symbols-outlined">close</span>
          </button>
        </section>
      )}

      {activeWorkspace === 'analysis' && (
        <div>
          <section className="mb-5 rounded-lg bg-surface-container-low p-5 sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="text-xs font-semibold text-teal-700 dark:text-teal-300">Clinical case workspace</div>
                <h1 className="mt-1 font-headline text-2xl font-bold text-on-surface sm:text-3xl">ประเมินเคสสังคมสงเคราะห์ทางคลินิก</h1>
                <p className="mt-2 max-w-3xl text-sm leading-relaxed text-on-surface-variant">บันทึกสถานการณ์ทางสังคม สุขภาพ ครอบครัว และความเสี่ยงที่เกี่ยวข้อง เพื่อใช้ประกอบการทบทวนโดยผู้ปฏิบัติงาน</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <StatusBadge label={hasFreshResult ? `เคส ${result.case_id}` : 'ยังไม่ได้ประเมิน'} tone={hasFreshResult ? 'live' : 'neutral'} />
                {hasFreshResult && (displayResult.problems || []).length > 0 && displayResult.severity_level && displayResult.severity_level !== 'NOT_ASSESSED' && (
                  <StatusBadge label={`ระดับ ${displayResult.severity_level}`} tone={['CRITICAL', 'SEVERE'].includes(displayResult.severity_level) ? 'error' : displayResult.severity_level === 'MODERATE' ? 'warning' : 'neutral'} />
                )}
              </div>
            </div>

            <div className="mt-6">
              <label className="block text-sm font-semibold text-on-surface" htmlFor="case-description">รายละเอียดสถานการณ์และบริบทสุขภาพ <span className="text-red-600">*</span></label>
              <textarea
                aria-describedby="case-description-help"
                autoComplete="off"
                className="mt-2 min-h-36 w-full resize-y rounded-lg border border-slate-300 bg-white p-4 text-base leading-relaxed text-on-surface placeholder:text-slate-400 focus:border-teal-600 focus:outline-none focus:ring-2 focus:ring-teal-600/20 dark:border-slate-700 dark:bg-slate-950"
                id="case-description"
                name="case-description"
                onChange={handleCaseDescriptionChange}
                onSelect={handleCaseSelection}
                placeholder="ระบุสถานการณ์ ความสัมพันธ์ สภาพครอบครัว ปัจจัยสุขภาพ ความเสี่ยง และสิ่งสนับสนุนที่เกี่ยวข้อง"
                value={caseDescription}
              />
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-on-surface-variant" id="case-description-help">
                <span className="flex items-center gap-1.5"><span aria-hidden="true" className="material-symbols-outlined text-[17px] text-teal-700 dark:text-teal-300">shield_person</span>หลีกเลี่ยงชื่อ เลขประจำตัว ที่อยู่ หรือข้อมูลที่ระบุตัวบุคคลได้</span>
                <button className="min-h-11 rounded-lg px-3 py-2 text-sm font-semibold text-teal-700 transition-colors hover:bg-teal-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 dark:text-teal-300 dark:hover:bg-teal-950/40" onClick={loadSampleCase} type="button">โหลดเคสตัวอย่าง</button>
              </div>
            </div>

            <details className="clinical-details mt-4 rounded-lg bg-white dark:bg-slate-900/70">
              <summary className="flex min-h-14 items-center justify-between gap-3 px-4 py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-teal-600">
                <span className="flex min-w-0 items-center gap-3">
                  <span aria-hidden="true" className="material-symbols-outlined text-[21px] text-slate-500">tune</span>
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold text-on-surface">การตั้งค่าการวิเคราะห์ขั้นสูง</span>
                    <span className="mt-0.5 block truncate text-xs text-on-surface-variant">{selectedStrategy} · L2 {selectedMode === 'enhanced' && enableL2 ? selectedL2Model : 'ปิด'} · Top {evidenceTopK} · ตำแหน่งคำสำคัญ {userAdjustedSpans.length}</span>
                  </span>
                </span>
                <span aria-hidden="true" className="details-chevron material-symbols-outlined text-on-surface-variant transition-transform">expand_more</span>
              </summary>
              <div className="space-y-4 border-t border-slate-200 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-950/30">
                <section className="rounded-lg bg-white p-4 dark:bg-slate-900/70">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h2 className="text-sm font-semibold text-on-surface">ตำแหน่งคำหรือวลีสำคัญ</h2>
                      <p className="mt-1 text-xs leading-relaxed text-on-surface-variant">เลือกข้อความในช่องเคส แล้วบันทึกตำแหน่งเมื่อคำเดียวกันปรากฏหลายครั้ง</p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge label={`${userAdjustedSpans.length} ตำแหน่ง`} tone={userAdjustedSpans.length ? 'live' : 'neutral'} />
                      <button className="min-h-11 rounded-lg bg-teal-600 px-3 py-2 text-sm font-semibold text-white disabled:bg-slate-300 dark:disabled:bg-slate-700" disabled={!pendingAnchorSpan || loading} onClick={addPendingAnchorSpan} type="button">บันทึกช่วงที่เลือก</button>
                      <button className="min-h-11 rounded-lg bg-slate-100 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-200 disabled:opacity-50 dark:bg-slate-800 dark:text-slate-200" disabled={!userAdjustedSpans.length || loading} onClick={clearUserAdjustedSpans} type="button">ล้างทั้งหมด</button>
                    </div>
                  </div>
                  {pendingAnchorSpan && (
                    <div className="mt-3 rounded-lg bg-teal-50 p-3 text-sm text-teal-950 dark:bg-teal-950/40 dark:text-teal-100">ช่วงที่เลือก: {pendingAnchorSpan.start}–{pendingAnchorSpan.end} · “{pendingAnchorSpan.text}”</div>
                  )}
                  {userAdjustedSpans.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {userAdjustedSpans.map((span) => (
                        <button aria-label={`ลบตำแหน่ง ${span.text}`} className="inline-flex min-h-11 max-w-full items-center gap-2 rounded-full bg-teal-100 px-3 py-2 text-xs font-semibold text-teal-950 transition-colors hover:bg-teal-200 dark:bg-teal-950/50 dark:text-teal-100" key={`${span.start}-${span.end}-${span.text}`} onClick={() => removeUserAdjustedSpan(span.start, span.end)} type="button">
                          <span className="tabular-nums">{span.start}–{span.end}</span>
                          <span className="max-w-[220px] truncate">“{span.text}”</span>
                          <span aria-hidden="true" className="material-symbols-outlined text-[17px]">close</span>
                        </button>
                      ))}
                    </div>
                  )}
                </section>

                <StrategySelector
                  disabled={loading}
                  enableL2={enableL2}
                  pairs={strategyPairs}
                  selectedFamily={selectedFamily}
                  selectedMode={selectedMode}
                  selectedStrategy={selectedStrategy}
                  setEnableL2={setEnableL2}
                  setSelectedFamily={(family) => {
                    setSelectedFamily(family);
                    if (result) setActionMessage({ tone: 'neutral', title: 'เปลี่ยนวิธีค้นคืนข้อมูลแล้ว', detail: 'กรุณาวิเคราะห์เคสใหม่ก่อนทบทวนหรือส่งผล' });
                  }}
                  setSelectedMode={(mode) => {
                    setSelectedMode(mode);
                    if (result) setActionMessage({ tone: 'neutral', title: 'เปลี่ยนระดับการประมวลผลแล้ว', detail: 'กรุณาวิเคราะห์เคสใหม่ก่อนทบทวนหรือส่งผล' });
                  }}
                  strategyOptions={runtimeStatus?.strategy_options}
                />
                <L2ModelSelector
                  disabled={loading || selectedMode === 'baseline'}
                  enabled={enableL2 && selectedMode !== 'baseline'}
                  modelOptions={l2ModelOptions}
                  onChange={(model) => {
                    setSelectedL2Model(model);
                    if (result) setActionMessage({ tone: 'neutral', title: 'เปลี่ยนโมเดลอ่านบริบทแล้ว', detail: 'กรุณาวิเคราะห์เคสใหม่ก่อนทบทวนหรือส่งผล' });
                  }}
                  value={selectedL2Model}
                />
                <DocScalingSelector
                  disabled={loading}
                  onChange={(topK) => {
                    setEvidenceTopK(topK);
                    if (result) setActionMessage({ tone: 'neutral', title: 'เปลี่ยนจำนวนหลักฐานแล้ว', detail: `กรุณาวิเคราะห์ใหม่เพื่อใช้ Top ${topK} กับเคสปัจจุบัน` });
                  }}
                  value={evidenceTopK}
                />
              </div>
            </details>

            <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-4 dark:border-slate-800">
              <p className="text-sm text-on-surface-variant">{runtimeHint}</p>
              <button aria-busy={loading} className="min-h-12 w-full rounded-lg bg-teal-700 px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-slate-400 sm:w-auto" disabled={analyzeDisabled} onClick={analyzeCase} type="button">
                {loading ? 'กำลังวิเคราะห์เคส…' : isCaseDirty ? 'วิเคราะห์เคสที่แก้ไขแล้ว' : 'วิเคราะห์เคสและค้นหาแนวทาง'}
              </button>
            </div>
          </section>

          {loading && (
            <ProcessingCasePanel caseDescription={caseDescription} enableL2={selectedMode === 'enhanced' && enableL2} evidenceTopK={evidenceTopK} runtimeStatus={runtimeStatus} selectedL2Model={selectedL2Model} selectedStrategy={selectedStrategy} />
          )}

          {isCaseDirty && !loading && (
            <section className="mb-5 flex items-start gap-3 rounded-lg bg-amber-50 p-4 text-amber-950 dark:bg-amber-950/40 dark:text-amber-100" role="status">
              <span aria-hidden="true" className="material-symbols-outlined text-[21px]">pending_actions</span>
              <div>
                <h2 className="text-sm font-semibold">ผลเดิมถูกพักไว้</h2>
                <p className="mt-1 text-sm">ข้อความเคสหรือการตั้งค่าถูกเปลี่ยน ระบบจะไม่ใช้ผลเก่าในการ audit หรือส่งเพื่อทบทวน</p>
              </div>
            </section>
          )}

          {hasFreshResult ? (
            <>
              <AnalysisTab
                displayResult={result}
                findingReviewStates={findingReviewStates}
                onFindingReviewChange={updateFindingReviewState}
                reviewDisabled={loading || auditLoading || finalizeLoading || isPublicPreview}
              />
              <AuditAndFinalizePanel
                auditLoading={auditLoading}
                auditPacket={auditPacket}
                disabled={loading || isCaseDirty}
                expertOverrideAdded={expertOverrideAdded}
                expertOverrideRejected={expertOverrideRejected}
                finalizeLoading={finalizeLoading}
                onPrepareAudit={requestSecondaryAudit}
                onSubmitReview={finalizeCase}
                publicPreview={isPublicPreview}
                reviewSummary={reviewSummary}
                reviewerNote={reviewerNote}
                setExpertOverrideAdded={updateExpertOverrideAdded}
                setExpertOverrideRejected={updateExpertOverrideRejected}
                setReviewerNote={updateReviewerNote}
                setZeroFindingAcknowledged={updateZeroFindingAcknowledged}
                signoffPacket={signoffPacket}
                zeroFindingAcknowledged={zeroFindingAcknowledged}
              />
              <footer className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 py-5 text-xs text-on-surface-variant dark:border-slate-800">
                <span>API {result.mode} · เวลาประมวลผล {formatNumber(result.execution_time, 3)} วินาที · runtime {runtimeStatus.status}</span>
                <span className="flex flex-wrap gap-2">
                  {(result.pii_redacted_count || 0) > 0 && <StatusBadge label={`ลดการระบุตัวบุคคล ${result.pii_redacted_count} จุด`} tone="live" />}
                  <StatusBadge label="Decision support · Human review required" tone="neutral" />
                </span>
              </footer>
            </>
          ) : !loading && (
            <WorkspaceEmptyState actionLabel={isCaseDirty ? 'วิเคราะห์เคสใหม่' : undefined} disabled={analyzeDisabled} icon={isCaseDirty ? 'pending_actions' : 'clinical_notes'} message={isCaseDirty ? 'ผลก่อนหน้าถูกพักไว้เพื่อป้องกันการใช้ข้อมูลที่ไม่ตรงกับข้อความหรือการตั้งค่าปัจจุบัน' : 'กรอกรายละเอียดเคสด้านบน ระบบจะแสดงประเด็นที่ควรทบทวน เครื่องมือประเมิน และหลักฐานที่เกี่ยวข้องโดยไม่สรุปแทนผู้ปฏิบัติงาน'} onAction={isCaseDirty ? analyzeCase : undefined} title={isCaseDirty ? 'ต้องวิเคราะห์เคสอีกครั้ง' : 'ยังไม่มีผลการประเมิน'} />
          )}
        </div>
      )}

      {activeWorkspace === 'explainability' && (
        <div className="page-enter">
          <section className="mb-5 rounded-lg bg-surface-container-low p-4 sm:p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="text-xs font-semibold text-teal-700 dark:text-teal-300">Explainability workspace</div>
                <h1 className="mt-1 font-headline text-2xl font-bold text-on-surface">เหตุผลและเส้นทางการประมวลผล</h1>
                <p className="mt-2 text-sm text-on-surface-variant">ตรวจสอบบริบทภาษา ลำดับการคัดกรอง และความสัมพันธ์ระหว่างเคสกับหลักฐาน</p>
              </div>
              <StatusBadge label={hasFreshResult ? `เคส ${result.case_id}` : 'ยังไม่มีผลเคส'} tone={hasFreshResult ? 'live' : 'neutral'} />
            </div>
            <div className="mt-5 grid grid-cols-1 gap-2 rounded-lg bg-slate-100 p-1 dark:bg-slate-800 sm:grid-cols-3" role="tablist" aria-label="มุมมองเหตุผลของระบบ">
              {explainabilityTabs.map((tab) => {
                const selected = activeTab === tab.id;
                return (
                  <button aria-selected={selected} className={`flex min-h-11 items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 ${selected ? 'bg-white text-teal-700 shadow-sm dark:bg-slate-700 dark:text-teal-200' : 'text-slate-500 hover:text-slate-950 dark:text-slate-400 dark:hover:text-white'}`} key={tab.id} onClick={() => setActiveTab(tab.id)} role="tab" type="button">
                    <span aria-hidden="true" className="material-symbols-outlined text-[19px]">{tab.icon}</span>
                    {tab.label}
                  </button>
                );
              })}
            </div>
          </section>

          {hasFreshResult ? (
            <div role="tabpanel">
              {activeTab === 'keywords' && <KeywordsTab displayResult={result} />}
              {activeTab === 'pipeline' && <PipelineTab displayResult={result} runtimeStatus={runtimeStatus} />}
              {activeTab === 'vectors' && <VectorTab displayResult={result} />}
            </div>
          ) : (
            <WorkspaceEmptyState actionLabel="ไปที่หน้าทบทวนเคส" icon="manage_search" message="มุมมองนี้ต้องใช้ผลจากเคสปัจจุบัน เพื่อให้บริบทภาษา แผนที่หลักฐาน และลำดับการประมวลผลอ้างอิงข้อมูลชุดเดียวกัน" onAction={() => setActiveTab('analysis')} title="ยังไม่มีข้อมูลสำหรับอธิบายผล" />
          )}
        </div>
      )}

      {activeWorkspace === 'evaluation' && (
        <div className="page-enter">
          <EvaluationTab
            displayResult={hasFreshResult ? result : emptyResult}
            evaluationLastSyncedAt={evaluationLastSyncedAt}
            evaluationSummary={evaluationSummary}
            onRefreshPerformance={reviewPerformanceSnapshot}
            onSelectTopK={(topK) => setBenchmarkTopK(topK)}
            runtimeStatus={runtimeStatus}
            selectedTopK={benchmarkTopK}
          />
        </div>
      )}
    </ClinicalShell>
  );
}
