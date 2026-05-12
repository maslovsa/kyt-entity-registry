/* kyt-entity-registry gallery — logic.
 *
 * Loads entities.csv + logos/_index.json from same-origin (relative),
 * renders a filterable grid, and lets reviewers flag problem logos.
 * Flags persist in localStorage; "Export flagged CSV" downloads a
 * structured report the enrichment pipeline can later parse to
 * re-source, suggest, or route to manual curation.
 *
 * No framework, no build step. Edit and reload.
 */

/* ── tiny CSV parser ──────────────────────────────────────────────────
 * Handles quoted fields with embedded commas. entities.csv uses UTF-8
 * without a BOM and LF line endings. Sufficient for our known shape —
 * not a general-purpose CSV library. */
function parseCSV(text) {
  const rows = [];
  let field = '';
  let row = [];
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else { inQuotes = false; }
      } else {
        field += c;
      }
    } else {
      if (c === '"') { inQuotes = true; }
      else if (c === ',') { row.push(field); field = ''; }
      else if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; }
      else if (c === '\r') { /* skip */ }
      else { field += c; }
    }
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  // drop trailing empty row from terminal newline
  if (rows.length && rows[rows.length - 1].every(v => v === '')) rows.pop();

  const [header, ...body] = rows;
  return body.map(cols => Object.fromEntries(header.map((h, i) => [h, cols[i] ?? ''])));
}

/* ── category → directory map (mirrors docs/CONSUMERS.md) ──────────── */
const CATEGORY_TO_DIR = {
  exchange: 'exchanges',
  dex: 'dex',
  bridge: 'bridge',
  defi: 'defi',
  wallet: 'wallet',
  mining: 'mining',
  psp: 'psp',
  bot: 'bot',
  gambling: 'gambling',
  nft_marketplace: 'nft_marketplace',
  mixer: 'mixer',
  hack: 'hack',
  sanctioned: 'sanctioned',
  custodian: 'custodian',
};

const CATEGORY_LABEL = {
  exchange: 'Exchanges',
  dex: 'DEX',
  bridge: 'Bridges',
  defi: 'DeFi',
  wallet: 'Wallets',
  mining: 'Mining',
  psp: 'PSP',
  bot: 'Bots',
  gambling: 'Gambling',
  nft_marketplace: 'NFT marketplaces',
  mixer: 'Mixers',
  hack: 'Hacks',
  sanctioned: 'Sanctioned',
  custodian: 'Custodians',
};

/* ── state ──────────────────────────────────────────────────────────── */
const FLAGS_KEY = 'kyt-registry-gallery.flags.v2';
const state = {
  rows: [],           // entities.csv rows (plain objects)
  index: {},          // logos/_index.json — { "exchanges/binance-com": true, ... }
  // flags: { "<dir>/<slug>": {
  //   reason, note, flagged_at,
  //   suggested_data_url?,    // full "data:image/png;base64,…" (canvas-normalised to 160×160)
  //   suggested_filename?,    // original filename the reviewer picked (for provenance in CSV)
  //   suggested_bytes?,       // byte length of the normalised PNG (bookkeeping for CSV sizing)
  // } }
  flags: {},
  filter: {
    category: 'all',
    search: '',
    onlyFlagged: false,
    onlyMissing: false,
    sort: 'importance',
  },
};

const CANVAS_SIZE = 160;
const MAX_INPUT_BYTES = 5 * 1024 * 1024;  // reject obviously oversized uploads client-side

/* Decode a File into something drawable on a canvas. Prefers
 * createImageBitmap (fast, respects EXIF), falls back to a classic
 * <img> + object URL dance for older Safari and any browser where
 * createImageBitmap throws on PNG transparency edge cases. */
async function decodeImage(file) {
  try {
    const bmp = await createImageBitmap(file);
    return {
      width: bmp.width,
      height: bmp.height,
      drawOn: (ctx, x, y, w, h) => ctx.drawImage(bmp, x, y, w, h),
      dispose: () => bmp.close && bmp.close(),
    };
  } catch {
    /* fall through to <img> fallback */
  }
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise((res, rej) => {
      const el = new Image();
      el.onload = () => res(el);
      el.onerror = () => rej(new Error('image load failed'));
      el.src = url;
    });
    return {
      width: img.naturalWidth,
      height: img.naturalHeight,
      drawOn: (ctx, x, y, w, h) => ctx.drawImage(img, x, y, w, h),
      dispose: () => URL.revokeObjectURL(url),
    };
  } catch (e) {
    URL.revokeObjectURL(url);
    throw e;
  }
}

/* Client-side twin of scripts/normalize_png.py — decode the user's
 * file, resize longest edge to 160 preserving aspect, centre on a
 * transparent 160×160 canvas, re-encode as PNG. Keeps the CSV
 * downstream-friendly: no server-side ImageMagick needed. */
async function normaliseToPng(file) {
  if (file.size > MAX_INPUT_BYTES) {
    throw new Error(`file too large (${(file.size / 1e6).toFixed(1)}MB > 5MB)`);
  }
  const decoded = await decodeImage(file);
  if (!decoded.width || !decoded.height) {
    decoded.dispose?.();
    throw new Error('could not decode image');
  }
  try {
    const scale = CANVAS_SIZE / Math.max(decoded.width, decoded.height);
    const w = Math.max(1, Math.round(decoded.width * scale));
    const h = Math.max(1, Math.round(decoded.height * scale));
    const canvas = document.createElement('canvas');
    canvas.width = CANVAS_SIZE;
    canvas.height = CANVAS_SIZE;
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    decoded.drawOn(ctx, (CANVAS_SIZE - w) / 2, (CANVAS_SIZE - h) / 2, w, h);
    const blob = await new Promise(res => canvas.toBlob(res, 'image/png'));
    if (!blob) throw new Error('PNG encode failed');
    const dataUrl = await new Promise((res, rej) => {
      const fr = new FileReader();
      fr.onload = () => res(fr.result);
      fr.onerror = () => rej(fr.error || new Error('FileReader failed'));
      fr.readAsDataURL(blob);
    });
    if (typeof dataUrl !== 'string' || !dataUrl.startsWith('data:image/')) {
      throw new Error('unexpected data URL shape');
    }
    return { dataUrl, bytes: blob.size };
  } finally {
    decoded.dispose?.();
  }
}

/* ── flags persistence ──────────────────────────────────────────────── */
function loadFlags() {
  try { return JSON.parse(localStorage.getItem(FLAGS_KEY)) || {}; }
  catch { return {}; }
}

/** Persist `state.flags` to localStorage. Returns true on success.
 *  If the write fails (quota exceeded is the common case when data
 *  URLs push the serialised payload over ~5-10 MB), surface it to
 *  the reviewer and return false so the caller can decide what to
 *  do — rather than silently losing the attached image. */
function saveFlags() {
  try {
    localStorage.setItem(FLAGS_KEY, JSON.stringify(state.flags));
    return true;
  } catch (e) {
    console.error('saveFlags failed', e);
    alert(
      'Could not save flags to browser storage.\n\n' +
      `Reason: ${e.name || 'error'} — ${e.message || 'unknown'}.\n\n` +
      'The attached image is still in memory for THIS tab — ' +
      'export the CSV now before reloading the page.',
    );
    return false;
  }
}

function flagKey(row) {
  return `${CATEGORY_TO_DIR[row.category_slug] || row.category_slug}/${row.arkham_slug}`;
}

/* ── derived helpers ────────────────────────────────────────────────── */
/** True when the row has a real-source logo (arkham/brandfetch/
 *  defillama/favicon/manual). `placeholder` rows have a file on
 *  disk but it's the generic fallback glyph — treat as "missing"
 *  for the review UX. */
function hasLogo(row) {
  const dir = CATEGORY_TO_DIR[row.category_slug];
  return !!(dir && state.index[`${dir}/${row.arkham_slug}`]);
}

/** URL of the logo file on disk. Always returns something renderable:
 *  the generic 404 glyph when the slug is unknown or no PNG exists. */
function logoUrl(row) {
  const dir = CATEGORY_TO_DIR[row.category_slug];
  if (!dir || !row.arkham_slug) return 'logos/404.png';
  return `logos/${dir}/${row.arkham_slug}.png`;
}

/* ── filtering + sorting ────────────────────────────────────────────── */
function filteredRows() {
  const { category, search, onlyFlagged, onlyMissing, sort } = state.filter;
  const q = search.trim().toLowerCase();
  let out = state.rows.filter(r => {
    if (category !== 'all' && r.category_slug !== category) return false;
    if (onlyFlagged && !state.flags[flagKey(r)]) return false;
    if (onlyMissing && hasLogo(r)) return false;
    if (q) {
      const hay = `${r.entity_name} ${r.arkham_slug} ${r.canonical_domain}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  const cmp = {
    importance: (a, b) => (+b.importance || 0) - (+a.importance || 0)
                       || a.entity_name.localeCompare(b.entity_name),
    name:       (a, b) => a.entity_name.localeCompare(b.entity_name),
    updated:    (a, b) => (b.logo_updated_at || '').localeCompare(a.logo_updated_at || ''),
    category:   (a, b) => a.category_slug.localeCompare(b.category_slug)
                       || (+b.importance || 0) - (+a.importance || 0),
  }[sort];
  out.sort(cmp);
  return out;
}

/* ── rendering ──────────────────────────────────────────────────────── */
const els = {};

function renderStatsBar() {
  const total = state.rows.length;
  const withLogo = state.rows.filter(hasLogo).length;
  const missing = total - withLogo;
  const flaggedCount = Object.keys(state.flags).length;
  const byStatus = state.rows.reduce((acc, r) => {
    const s = r.logo_status || 'none';
    acc[s] = (acc[s] || 0) + 1;
    return acc;
  }, {});

  els.statsBar.innerHTML = `
    <span><strong>${total}</strong> entities</span>
    <span><strong>${withLogo}</strong> with real logo</span>
    <span><strong>${missing}</strong> placeholder / missing</span>
    <span><strong>${flaggedCount}</strong> flagged locally</span>
    <span>status:
      arkham <strong>${byStatus.arkham || 0}</strong> ·
      brandfetch <strong>${byStatus.brandfetch || 0}</strong> ·
      defillama <strong>${byStatus.defillama || 0}</strong> ·
      favicon <strong>${byStatus.favicon || 0}</strong> ·
      manual <strong>${byStatus.manual || 0}</strong> ·
      placeholder <strong>${byStatus.placeholder || 0}</strong> ·
      none <strong>${byStatus.none || 0}</strong>
    </span>
  `;
  els.flaggedCount.textContent = String(flaggedCount);
}

function renderCategoryChips() {
  const counts = state.rows.reduce((acc, r) => {
    acc[r.category_slug] = (acc[r.category_slug] || 0) + 1;
    return acc;
  }, {});
  const cats = Object.keys(CATEGORY_LABEL).filter(c => counts[c]);
  const mkChip = (value, label, count) => {
    const selected = state.filter.category === value;
    return `<button class="chip" role="tab" aria-selected="${selected}" data-category="${value}">
      ${label}<span class="count">${count}</span>
    </button>`;
  };
  els.chips.innerHTML = [
    mkChip('all', 'All', state.rows.length),
    ...cats.map(c => mkChip(c, CATEGORY_LABEL[c], counts[c])),
  ].join('');
}

function renderCard(row) {
  const tpl = els.cardTemplate.content.cloneNode(true);
  const card = tpl.querySelector('.card');
  const key = flagKey(row);
  const flag = state.flags[key];
  const logoOk = hasLogo(row);

  card.dataset.slug = row.arkham_slug;
  card.dataset.category = row.category_slug;
  card.dataset.hasLogo = String(logoOk);
  card.dataset.flagged = String(!!flag);

  const img = card.querySelector('img');
  img.src = logoUrl(row);
  img.alt = row.entity_name;
  img.onerror = () => { card.dataset.hasLogo = 'false'; };

  card.querySelector('.card-name').textContent = row.entity_name;
  card.querySelector('.badge-category').textContent = CATEGORY_TO_DIR[row.category_slug] || row.category_slug;
  const statusBadge = card.querySelector('.badge-status');
  statusBadge.textContent = row.logo_status || 'none';
  statusBadge.dataset.status = row.logo_status || 'none';
  const lock = card.querySelector('.badge-lock');
  if (row.manual_lock === 'true') lock.hidden = false;

  card.querySelector('.imp').textContent = `imp ${row.importance || 0}`;
  card.querySelector('.updated').textContent = row.logo_updated_at || '—';

  // flag UI wiring
  const flagBtn = card.querySelector('.flag-btn');
  const uploadBtn = card.querySelector('.upload-btn');
  const uploadInput = card.querySelector('.upload-input');
  const preview = card.querySelector('.suggestion-preview');
  const previewImg = card.querySelector('.suggestion-img');
  const previewClear = card.querySelector('.suggestion-clear');
  const details = card.querySelector('.flag-details');
  const reason = card.querySelector('.flag-reason');
  const note = card.querySelector('.flag-note');

  function paintFlagState() {
    const f = state.flags[key];
    flagBtn.setAttribute('aria-pressed', String(!!f));
    flagBtn.textContent = f ? 'Flagged — click to unflag' : 'Mark as problem';
    details.hidden = !f;
    card.dataset.flagged = String(!!f);
    // Stale-suggestion guard: reason=user_provided without an actual
    // data URL is legacy state from earlier v2 where the dropdown
    // exposed user_provided. Normalise to empty so the reviewer
    // either re-attaches or picks a real reason.
    if (f && f.reason === 'user_provided' && !f.suggested_data_url) {
      f.reason = '';
    }
    if (f && f.suggested_data_url) {
      preview.hidden = false;
      previewImg.src = f.suggested_data_url;
    } else {
      preview.hidden = true;
      previewImg.removeAttribute('src');
    }
    if (f) {
      reason.value = f.reason || '';
      note.value = f.note || '';
    }
  }
  paintFlagState();

  flagBtn.addEventListener('click', () => {
    if (state.flags[key]) {
      delete state.flags[key];
    } else {
      state.flags[key] = { reason: '', note: '', flagged_at: new Date().toISOString() };
    }
    saveFlags();
    paintFlagState();
    renderStatsBar();
    if (state.filter.onlyFlagged) renderGrid();
  });

  uploadBtn.addEventListener('click', () => uploadInput.click());

  uploadInput.addEventListener('change', async () => {
    const file = uploadInput.files && uploadInput.files[0];
    if (!file) return;
    uploadBtn.dataset.state = 'busy';
    const originalLabel = uploadBtn.textContent;
    uploadBtn.textContent = 'Processing...';
    try {
      const { dataUrl, bytes } = await normaliseToPng(file);
      // Attaching a suggestion implicitly flags the row. Default the
      // problem-reason to `manual_needed` — it semantically matches
      // "I'm hand-curating this one" and it's a real dropdown option,
      // so the reviewer sees the select pre-filled instead of blank.
      // If they already picked a more specific reason (wrong_image,
      // outdated, …), keep it.
      const existing = state.flags[key] || {};
      state.flags[key] = {
        ...existing,
        reason: existing.reason || 'manual_needed',
        note: existing.note || '',
        flagged_at: existing.flagged_at || new Date().toISOString(),
        suggested_data_url: dataUrl,
        suggested_filename: file.name,
        suggested_bytes: bytes,
      };
      saveFlags();   // warns via alert if quota blows; memory stays ok
      paintFlagState();
      renderStatsBar();
    } catch (err) {
      console.error('upload failed', err);
      alert(
        `Could not attach image: ${err && err.message ? err.message : err}\n\n` +
        'Check the browser console for details.',
      );
    } finally {
      uploadBtn.dataset.state = '';
      uploadBtn.textContent = originalLabel;
      uploadInput.value = '';   // allow re-selecting the same file
    }
  });

  previewClear.addEventListener('click', e => {
    e.stopPropagation();
    const f = state.flags[key];
    if (!f) return;
    delete f.suggested_data_url;
    delete f.suggested_filename;
    delete f.suggested_bytes;
    saveFlags();
    paintFlagState();
  });

  reason.addEventListener('change', () => {
    if (!state.flags[key]) return;
    state.flags[key].reason = reason.value;
    saveFlags();
  });
  note.addEventListener('input', () => {
    if (!state.flags[key]) return;
    state.flags[key].note = note.value;
    saveFlags();
  });

  return tpl;
}

function renderGrid() {
  const rows = filteredRows();
  els.grid.innerHTML = '';
  if (!rows.length) {
    els.grid.innerHTML = '<div class="empty">No entities match the current filters.</div>';
    return;
  }
  // Render in chunks to keep the main thread responsive for 800+ rows.
  const frag = document.createDocumentFragment();
  for (const r of rows) frag.appendChild(renderCard(r));
  els.grid.appendChild(frag);
}

/* ── CSV export ─────────────────────────────────────────────────────── */
function escapeCsv(v) {
  const s = String(v ?? '');
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Report schema — keep in sync with scripts/rework_from_report.py
 *  (to be built) on the enrichment side.
 *
 *  `suggested_logo_data_url` carries the reviewer's replacement image
 *  inline as a `data:image/png;base64,…` URI. The image is already
 *  160×160 RGBA PNG (client-normalised via Canvas) so the downstream
 *  script just base64-decodes, runs normalize_png to double-check,
 *  writes to `logos/_manual/<category>/<slug>.png`, and sets
 *  `logo_status=manual` + `manual_lock=true`. No external URLs to
 *  retry, no expiring links. */
const REPORT_HEADER = [
  'category_slug',
  'arkham_slug',
  'entity_name',
  'reason',
  'note',
  'current_logo_status',
  'current_logo_updated_at',
  'current_logo_hash',
  'canonical_domain',
  'flagged_at',
  'suggested_filename',
  'suggested_bytes',
  'suggested_logo_data_url',
];

function buildReportCSV() {
  const rowsByKey = new Map(state.rows.map(r => [flagKey(r), r]));
  const lines = [REPORT_HEADER.join(',')];
  for (const [key, flag] of Object.entries(state.flags)) {
    const r = rowsByKey.get(key);
    if (!r) continue;   // row might have disappeared across exports
    lines.push([
      r.category_slug,
      r.arkham_slug,
      r.entity_name,
      flag.reason || '',
      flag.note || '',
      r.logo_status || '',
      r.logo_updated_at || '',
      r.logo_hash || '',
      r.canonical_domain || '',
      flag.flagged_at || '',
      flag.suggested_filename || '',
      flag.suggested_bytes || '',
      flag.suggested_data_url || '',
    ].map(escapeCsv).join(','));
  }
  return lines.join('\n') + '\n';
}

function downloadReportCSV() {
  const csv = buildReportCSV();
  const date = new Date().toISOString().slice(0, 10);
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `kyt-registry-rework-${date}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/* ── wire-up ────────────────────────────────────────────────────────── */
function bindEvents() {
  els.search.addEventListener('input', () => {
    state.filter.search = els.search.value;
    renderGrid();
  });
  els.sort.addEventListener('change', () => {
    state.filter.sort = els.sort.value;
    renderGrid();
  });
  els.onlyFlagged.addEventListener('change', () => {
    state.filter.onlyFlagged = els.onlyFlagged.checked;
    renderGrid();
  });
  els.onlyMissing.addEventListener('change', () => {
    state.filter.onlyMissing = els.onlyMissing.checked;
    renderGrid();
  });
  els.chips.addEventListener('click', e => {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    state.filter.category = chip.dataset.category;
    renderCategoryChips();
    renderGrid();
  });
  els.exportCsv.addEventListener('click', () => {
    if (!Object.keys(state.flags).length) {
      alert('No entries flagged yet. Click "Mark as problem" on a card first.');
      return;
    }
    downloadReportCSV();
  });
  els.clearFlags.addEventListener('click', () => {
    const n = Object.keys(state.flags).length;
    if (!n) return;
    if (!confirm(`Clear ${n} local flag(s)? This cannot be undone.`)) return;
    state.flags = {};
    saveFlags();
    renderStatsBar();
    renderGrid();
  });
}

async function fetchText(path) {
  const r = await fetch(path, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.text();
}
async function fetchJson(path) {
  const r = await fetch(path, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

async function main() {
  // cache DOM handles
  els.statsBar     = document.getElementById('stats-bar');
  els.search       = document.getElementById('search');
  els.sort         = document.getElementById('sort');
  els.onlyFlagged  = document.getElementById('only-flagged');
  els.onlyMissing  = document.getElementById('only-missing');
  els.chips        = document.getElementById('category-chips');
  els.exportCsv    = document.getElementById('export-csv');
  els.clearFlags   = document.getElementById('clear-flags');
  els.flaggedCount = document.getElementById('flagged-count');
  els.grid         = document.getElementById('grid');
  els.cardTemplate = document.getElementById('card-template');

  state.flags = loadFlags();

  try {
    const [csv, index] = await Promise.all([
      fetchText('entities.csv'),
      fetchJson('logos/_index.json').catch(() => ({})),
    ]);
    state.rows = parseCSV(csv);
    state.index = index;
  } catch (e) {
    // Use textContent so a crafted error message (e.g. a server-side
    // response echoed by fetch) cannot inject markup into the grid.
    const banner = document.createElement('div');
    banner.className = 'empty';
    banner.textContent = `Failed to load entities.csv or logos/_index.json: ${e && e.message ? e.message : String(e)}`;
    els.grid.replaceChildren(banner);
    return;
  }

  els.grid.removeAttribute('aria-busy');
  bindEvents();
  renderStatsBar();
  renderCategoryChips();
  renderGrid();
}

main();
