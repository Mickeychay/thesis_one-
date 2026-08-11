import { useMemo, useState } from 'react';

const FAMILIES = [
  { key: 'bm25',   baseline: 'bm25_only',  h2l: 'h2l-bm25',      label: 'BM25',     short: 'BM25'   },
  { key: 'dense',  baseline: 'naive_rag',   h2l: 'h2l-naive_rag', label: 'Dense RAG', short: 'Dense'  },
  { key: 'hyde',   baseline: 'hyde',        h2l: 'h2l-hyde',      label: 'HyDE',     short: 'HyDE'   },
  { key: 'hybrid', baseline: 'basic',       h2l: 'h2l-hybrid',    label: 'Hybrid',   short: 'Hybrid' },
];

const METRICS = [
  { id: 'MAP',    label: 'MAP',    desc: 'Mean Average Precision — คุณภาพ ranking รวมทั้งรายการ' },
  { id: 'MRR',    label: 'MRR',    desc: 'Mean Reciprocal Rank — ความเร็วในการเจอหลักฐานชิ้นแรก' },
  { id: 'nDCG@5', label: 'nDCG@5', desc: 'Normalized DCG ที่ top 5 — คุณภาพการจัดลำดับ 5 อันดับแรก' },
  { id: 'F1@5',   label: 'F1@5',   desc: 'F1 Score ที่ top 5 — สมดุลระหว่าง Precision และ Recall' },
];

// Isometric projection constants
const CX = 46;       // screen pixels per X-grid unit
const CZ = 23;       // screen pixels per Z-grid unit (CX/2 for true isometric)
const MAX_ELEV = 172; // max bar height in pixels (at value = maxVal)

const isoXY = (gx, gy, gz, orgX, orgY) => ({
  x: (gx - gz) * CX + orgX,
  y: (gx + gz) * CZ - gy + orgY,
});

const ptStr = (arr) => arr.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');

// Isometric bar: 3 visible faces (top, right/east, front/south)
function IsoBar({ gx, gz, value, isH2L, isHovered, orgX, orgY, maxVal, onEnter, onLeave, onClick }) {
  const norm = maxVal > 0 ? Math.min(1, value / maxVal) : 0;
  const h = Math.max(5, norm * MAX_ELEV);

  const pad = 0.1;
  const x0 = gx + pad;
  const x1 = gx + 1 - pad;
  const z0 = gz + pad;
  const z1 = gz + 1 - pad;

  // 7 distinct corner positions (we reuse some)
  const tBL  = isoXY(x0, h, z0, orgX, orgY); // top back-left
  const tBR  = isoXY(x1, h, z0, orgX, orgY); // top back-right (east face top-back)
  const tFR  = isoXY(x1, h, z1, orgX, orgY); // top front-right
  const tFL  = isoXY(x0, h, z1, orgX, orgY); // top front-left (south face top-left)
  const bBR  = isoXY(x1, 0, z0, orgX, orgY); // bottom back-right
  const bFR  = isoXY(x1, 0, z1, orgX, orgY); // bottom front-right
  const bFL  = isoXY(x0, 0, z1, orgX, orgY); // bottom front-left

  const glow = isHovered ? 0.22 : 0;

  const c = isH2L
    ? { top: '#0d9488', right: '#0a7870', front: '#087065', glow: '#2dd4bf', stroke: '#5eead4' }
    : { top: '#f59e0b', right: '#c17d06', front: '#a06605', glow: '#fde68a', stroke: '#fcd34d' };

  const sw = isHovered ? 1.2 : 0.4;

  return (
    <g
      style={{ cursor: 'pointer' }}
      role="button"
      tabIndex={0}
      aria-label={`${isH2L ? 'H2L' : 'Baseline'} bar, value ${value.toFixed(3)}`}
      onClick={onClick}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      onFocus={onEnter}
      onBlur={onLeave}
    >
      {/* East (right) face */}
      <polygon points={ptStr([tBR, tFR, bFR, bBR])} fill={c.right} stroke={c.stroke} strokeWidth={sw} />
      {/* South (front) face */}
      <polygon points={ptStr([tFL, tFR, bFR, bFL])} fill={c.front} stroke={c.stroke} strokeWidth={sw} />
      {/* Top face */}
      <polygon points={ptStr([tBL, tBR, tFR, tFL])} fill={c.top} stroke={c.stroke} strokeWidth={sw} />
      {/* Hover glow overlay on top */}
      {glow > 0 && (
        <polygon points={ptStr([tBL, tBR, tFR, tFL])} fill="white" fillOpacity={glow} />
      )}
      {/* Specular highlight strip along top-front edge */}
      {isHovered && (
        <line
          x1={tFL.x} y1={tFL.y} x2={tFR.x} y2={tFR.y}
          stroke="white" strokeWidth={2} strokeOpacity={0.45}
        />
      )}
    </g>
  );
}

function FloorGrid({ orgX, orgY }) {
  const lines = [];
  // Vertical lines (along Z, varying X)
  for (let i = 0; i <= 4; i++) {
    const a = isoXY(i, 0, 0, orgX, orgY);
    const b = isoXY(i, 0, 2, orgX, orgY);
    lines.push(<line key={`gx${i}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#94a3b8" strokeWidth={0.6} opacity={0.25} />);
  }
  // Horizontal lines (along X, varying Z)
  for (let j = 0; j <= 2; j++) {
    const a = isoXY(0, 0, j, orgX, orgY);
    const b = isoXY(4, 0, j, orgX, orgY);
    lines.push(<line key={`gz${j}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#94a3b8" strokeWidth={0.6} opacity={0.25} />);
  }
  return <g>{lines}</g>;
}

function ValueAxis({ orgX, orgY, maxVal, ticks = 4 }) {
  const items = [];
  for (let i = 1; i <= ticks; i++) {
    const frac = i / ticks;
    const elev = frac * MAX_ELEV;
    const p = isoXY(0, elev, 0, orgX, orgY);
    const label = (frac * maxVal).toFixed(3);
    items.push(
      <g key={i}>
        <line x1={p.x - 14} y1={p.y} x2={p.x} y2={p.y} stroke="#64748b" strokeWidth={0.8} opacity={0.4} />
        <text x={p.x - 17} y={p.y + 3.5} textAnchor="end" fontSize={8.5} fill="#64748b" opacity={0.75}>{label}</text>
      </g>
    );
  }
  return <g>{items}</g>;
}

export default function PerformanceLandscape3D({ rows }) {
  const [metric, setMetric] = useState('MAP');
  const [hovered, setHovered] = useState(null); // { gx, gz }
  const metricDef = METRICS.find((m) => m.id === metric) || METRICS[0];

  const valueMap = useMemo(() => {
    const map = {};
    (rows || []).forEach((row) => { if (row.strategy) map[row.strategy] = row; });
    return map;
  }, [rows]);

  const bars = useMemo(() => {
    const result = [];
    FAMILIES.forEach((fam, gx) => {
      const bRow = valueMap[fam.baseline] || {};
      const hRow = valueMap[fam.h2l] || {};
      // gz=1: Baseline (back row)
      result.push({ gx, gz: 1, isH2L: false, family: fam.key, label: fam.label, strategy: fam.baseline, value: Number(bRow[metric]) || 0 });
      // gz=0: H2L (front row, closer to viewer)
      result.push({ gx, gz: 0, isH2L: true,  family: fam.key, label: fam.label, strategy: fam.h2l, value: Number(hRow[metric]) || 0 });
    });
    return result;
  }, [valueMap, metric]);

  const maxVal = useMemo(() => {
    const vals = bars.map((b) => b.value).filter((v) => v > 0);
    return vals.length ? Math.max(...vals) * 1.15 : 0.5;
  }, [bars]);

  // Render order: back-right to front-left
  const renderOrder = [...bars].sort((a, b) => b.gz - a.gz || b.gx - a.gx);

  const orgX = 248;
  const orgY = 210;

  const hovBar = hovered ? bars.find((b) => b.gx === hovered.gx && b.gz === hovered.gz) : null;

  // Companion bar for delta calculation
  const companion = hovBar ? bars.find((b) => b.gx === hovBar.gx && b.isH2L !== hovBar.isH2L) : null;

  // Column labels at base of each family
  const colLabels = FAMILIES.map((fam, i) => {
    const p = isoXY(i + 0.5, 0, 2.1, orgX, orgY);
    return { x: p.x, y: p.y + 16, label: fam.label };
  });

  // Row labels
  const rowLabelH2L  = isoXY(-0.18, 0, 0.5, orgX, orgY);
  const rowLabelBase = isoXY(-0.18, 0, 1.5, orgX, orgY);

  // Value labels for each bar
  const valLabels = bars.map((b) => {
    const norm = maxVal > 0 ? Math.min(1, b.value / maxVal) : 0;
    const h = Math.max(5, norm * MAX_ELEV);
    const p = isoXY(b.gx + 0.5, h + 10, b.gz + 0.5, orgX, orgY);
    const isHov = hovered?.gx === b.gx && hovered?.gz === b.gz;
    return { ...b, p, isHov };
  });

  const hasData = bars.some((b) => b.value > 0);

  return (
    <div className="rounded-xl border border-outline-variant/20 bg-surface-container-lowest p-4 sm:p-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">3D Performance Landscape</div>
          <h3 className="mt-1 break-words font-headline text-xl font-extrabold text-on-surface">ภูมิทัศน์ประสิทธิภาพ Baseline vs H2L</h3>
          <p className="mt-1 max-w-xl text-sm leading-relaxed text-on-surface-variant">{metricDef.desc}</p>
        </div>
        <div className="flex flex-wrap gap-2 shrink-0">
          {METRICS.map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() => setMetric(m.id)}
              className={`rounded-lg px-3 py-2 text-xs font-bold transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 ${
                metric === m.id
                  ? 'bg-teal-600 text-white shadow-sm'
                  : 'bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high'
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {/* Canvas */}
      <div className="mt-5 overflow-x-auto">
        {hasData ? (
          <svg
            viewBox="0 0 580 400"
            className="mx-auto w-full max-w-2xl"
            style={{ minWidth: 300 }}
            aria-label={`Isometric 3D bar chart showing ${metric} for each strategy family`}
          >
            <FloorGrid orgX={orgX} orgY={orgY} />
            <ValueAxis orgX={orgX} orgY={orgY} maxVal={maxVal} />

            {/* Bars */}
            {renderOrder.map((b) => (
              <IsoBar
                key={`${b.gx}-${b.gz}`}
                gx={b.gx} gz={b.gz}
                value={b.value} isH2L={b.isH2L}
                isHovered={hovered?.gx === b.gx && hovered?.gz === b.gz}
                orgX={orgX} orgY={orgY} maxVal={maxVal}
                onEnter={() => setHovered({ gx: b.gx, gz: b.gz })}
                onLeave={() => setHovered(null)}
                onClick={() => {}}
              />
            ))}

            {/* Value labels */}
            {valLabels.map((vl) => (
              vl.value > 0 && (
                <text
                  key={`vl-${vl.gx}-${vl.gz}`}
                  x={vl.p.x} y={vl.p.y}
                  textAnchor="middle"
                  fontSize={vl.isHov ? 11 : 8.5}
                  fontWeight={vl.isHov ? '800' : '600'}
                  fill={vl.isH2L ? '#0f766e' : '#92400e'}
                  opacity={vl.isHov ? 1 : 0.7}
                >
                  {vl.value.toFixed(3)}
                </text>
              )
            ))}

            {/* Column labels */}
            {colLabels.map((cl, i) => (
              <text key={i} x={cl.x} y={cl.y} textAnchor="middle" fontSize={11} fontWeight="700" fill="#475569" opacity={0.85}>
                {cl.label}
              </text>
            ))}

            {/* Row labels */}
            <text x={rowLabelH2L.x - 8} y={rowLabelH2L.y + 4} textAnchor="end" fontSize={10} fontWeight="700" fill="#0f766e">H2L+</text>
            <text x={rowLabelBase.x - 8} y={rowLabelBase.y + 4} textAnchor="end" fontSize={10} fontWeight="700" fill="#b45309">Base</text>

            {/* Metric label */}
            <text x={32} y={28} fontSize={11} fontWeight="800" fill="#0d9488" opacity={0.8}>{metric}</text>
            <text x={32} y={40} fontSize={8.5} fill="#64748b" opacity={0.6}>↑ ยิ่งสูงยิ่งดี</text>
          </svg>
        ) : (
          <div className="flex h-40 items-center justify-center rounded-lg bg-surface-container-low text-sm text-on-surface-variant">
            ยังไม่มีข้อมูล benchmark สำหรับ strategy เหล่านี้ — โหลด artifact ก่อนแล้วลองใหม่
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="mt-3 flex flex-wrap items-center gap-5 text-sm">
        <div className="flex items-center gap-2">
          <div className="h-3 w-6 rounded-sm" style={{ background: '#0d9488' }} />
          <span className="font-semibold text-on-surface">H2L Enhanced</span>
          <span className="text-xs text-on-surface-variant">(แถวหน้า)</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="h-3 w-6 rounded-sm" style={{ background: '#f59e0b' }} />
          <span className="font-semibold text-on-surface">Baseline</span>
          <span className="text-xs text-on-surface-variant">(แถวหลัง)</span>
        </div>
      </div>

      {/* Hover detail card */}
      {hovBar && (
        <div className={`mt-3 rounded-lg p-3 transition-all ${hovBar.isH2L ? 'bg-teal-50 dark:bg-teal-950/40' : 'bg-amber-50 dark:bg-amber-950/40'}`}>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-bold text-on-surface">{hovBar.label}</span>
            <span className={`rounded px-2 py-0.5 text-xs font-bold ${
              hovBar.isH2L ? 'bg-teal-100 text-teal-900 dark:bg-teal-900/60 dark:text-teal-100'
                           : 'bg-amber-100 text-amber-900 dark:bg-amber-900/60 dark:text-amber-100'
            }`}>{hovBar.isH2L ? 'H2L Enhanced' : 'Baseline'}</span>
            <code className="rounded bg-surface-container-high px-1.5 py-0.5 text-xs text-on-surface">{hovBar.strategy}</code>
          </div>
          <div className="mt-2 font-mono text-xl font-extrabold text-on-surface">
            {metric}: <span className={hovBar.isH2L ? 'text-teal-700 dark:text-teal-200' : 'text-amber-700 dark:text-amber-200'}>
              {hovBar.value > 0 ? hovBar.value.toFixed(4) : 'N/A'}
            </span>
          </div>
          {companion && companion.value > 0 && hovBar.value > 0 && (
            <div className="mt-2 flex flex-wrap gap-3 text-xs text-on-surface-variant">
              <span>เทียบกับ {companion.isH2L ? 'H2L' : 'Baseline'}: <strong className="text-on-surface">{companion.value.toFixed(4)}</strong></span>
              {(() => {
                const delta = hovBar.isH2L ? hovBar.value - companion.value : companion.value - hovBar.value;
                const pct = (delta / companion.value) * 100;
                const sign = delta >= 0 ? '+' : '';
                return (
                  <span className={delta >= 0 ? 'font-bold text-teal-700 dark:text-teal-300' : 'font-bold text-amber-700 dark:text-amber-300'}>
                    Δ H2L−Base: {sign}{delta.toFixed(4)} ({sign}{pct.toFixed(1)}%)
                  </span>
                );
              })()}
            </div>
          )}
        </div>
      )}

      {/* How to read */}
      <p className="mt-3 rounded-lg bg-surface-container-low px-3 py-2 text-xs leading-relaxed text-on-surface-variant">
        <strong className="text-on-surface">วิธีอ่าน:</strong> แท่ง{' '}
        <span className="font-bold text-teal-600 dark:text-teal-300">teal (แถวหน้า)</span> = H2L Enhanced ·{' '}
        <span className="font-bold text-amber-600 dark:text-amber-300">amber (แถวหลัง)</span> = Baseline ·{' '}
        ยิ่งสูงยิ่งดี · ชี้เมาส์บนแท่งเพื่อดูค่า Δ เปรียบเทียบ
      </p>
    </div>
  );
}
