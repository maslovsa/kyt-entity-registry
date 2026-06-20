/* kyt-entity-registry landing page — quilt + tabs + i18n + bulk upload.
 *
 * Reads logos/_lookup.json once on load (same file lookup.js + the MCP
 * servers consume). Renders every entity as a 64px tile; category tabs
 * multi-select to dim/highlight; hover shows a detail card; bulk-upload
 * zone at the bottom generates a rework CSV exactly like the per-card
 * "Use my image" in audit.html, but handling N files at once.
 *
 * No framework, no build. Single module executed at the end of <body>.
 */

const LANG_KEY = 'kyt-registry.lang.v1';
const SUPPORTED_LANGS = ['en', 'ru'];
const DEFAULT_LANG = 'en';

const CATEGORY_LABEL_EN = {
  exchange: 'Exchanges',
  dex: 'DEX',
  bridge: 'Bridges',
  defi: 'DeFi',
  wallet: 'Wallets',
  mining: 'Mining',
  psp: 'PSP',
  bot: 'Bots',
  gambling: 'Gambling',
  nft_marketplace: 'NFT',
  mixer: 'Mixers',
  hack: 'Hacks',
  sanctioned: 'Sanctioned',
};

// Render order for the quilt — determines which block of the
// patchwork an entity lands in. "Unknown" categories (shouldn't
// happen on well-formed data) get sorted last.
const CATEGORY_ORDER = Object.keys(CATEGORY_LABEL_EN);
const CATEGORY_RANK = Object.fromEntries(
  CATEGORY_ORDER.map((c, i) => [c, i]),
);
const CATEGORY_LABEL_RU = {
  exchange: 'Биржи',
  dex: 'DEX',
  bridge: 'Мосты',
  defi: 'DeFi',
  wallet: 'Кошельки',
  mining: 'Майнинг',
  psp: 'PSP',
  bot: 'Боты',
  gambling: 'Гэмблинг',
  nft_marketplace: 'NFT',
  mixer: 'Миксеры',
  hack: 'Взломы',
  sanctioned: 'Санкции',
};

/* ── i18n ─────────────────────────────────────────────────────────── */
function initialLang() {
  const saved = localStorage.getItem(LANG_KEY);
  if (saved && SUPPORTED_LANGS.includes(saved)) return saved;
  const nav = (navigator.language || '').slice(0, 2).toLowerCase();
  return SUPPORTED_LANGS.includes(nav) ? nav : DEFAULT_LANG;
}
function setLang(lang) {
  if (!SUPPORTED_LANGS.includes(lang)) lang = DEFAULT_LANG;
  document.documentElement.lang = lang;
  localStorage.setItem(LANG_KEY, lang);
  document.querySelectorAll('.lang-toggle button').forEach(b => {
    b.setAttribute('aria-pressed', String(b.dataset.lang === lang));
  });
  const si = document.getElementById('quilt-search');
  if (si) si.placeholder = lang === 'ru' ? 'Поиск…' : 'Search…';
}

/* ── state ────────────────────────────────────────────────────────── */
const state = {
  index: null,              // loaded lookup JSON
  activeCats: new Set(),    // empty = all active
  searchQuery: '',          // current search string
};

/* ── hover card ──────────────────────────────────────────────────── */
const hover = { el: null, timer: null };

function buildHoverCard() {
  const el = document.createElement('div');
  el.className = 'hover-card';
  el.setAttribute('role', 'tooltip');
  document.body.appendChild(el);
  hover.el = el;
}

function showHover(tile) {
  if (!hover.el) buildHoverCard();
  const d = tile.dataset;
  const lang = document.documentElement.lang;
  const updated = d.updated || '—';
  const sourceLabel = {
    arkham:       lang === 'ru' ? 'Arkham (CDN)'      : 'Arkham (CDN)',
    brandfetch:   lang === 'ru' ? 'Brandfetch (CDN)'  : 'Brandfetch (CDN)',
    defillama:    lang === 'ru' ? 'DefiLlama (CDN)'   : 'DefiLlama (CDN)',
    favicon:      lang === 'ru' ? 'Фавикон сайта'     : 'Site favicon',
    manual:       lang === 'ru' ? 'Ручная правка'     : 'Manual override',
    placeholder:  lang === 'ru' ? 'Плейсхолдер'       : 'Placeholder',
  }[d.source] || d.source;
  const isReal = d.real === 'true';
  const isManual = d.source === 'manual';
  const catLabels = lang === 'ru' ? CATEGORY_LABEL_RU : CATEGORY_LABEL_EN;
  const labels = {
    source:     lang === 'ru' ? 'Источник'    : 'Source',
    updated:    lang === 'ru' ? 'Обновлено'   : 'Updated',
    slug:       lang === 'ru' ? 'Slug'        : 'Slug',
    status:     lang === 'ru' ? 'Статус'      : 'Status',
    real:       lang === 'ru' ? 'Настоящий'   : 'Real logo',
    ph:         lang === 'ru' ? 'Заглушка'    : 'Placeholder',
    manual:     lang === 'ru' ? 'Locked'      : 'Locked',
  };
  const pill = isReal
    ? `<span class="hc-pill real">${labels.real}</span>`
    : `<span class="hc-pill placeholder">${labels.ph}</span>`;
  const manualPill = isManual
    ? ` <span class="hc-pill manual">${labels.manual}</span>`
    : '';
  hover.el.innerHTML = `
    <div class="hc-title">${escapeHtml(d.name || d.slug)}</div>
    <div class="hc-cat">${catLabels[d.category] || d.category}</div>
    <dl>
      <dt>${labels.source}</dt><dd>${sourceLabel}</dd>
      <dt>${labels.updated}</dt><dd>${updated}</dd>
      <dt>${labels.slug}</dt><dd><code>${escapeHtml(d.slug)}</code></dd>
      <dt>${labels.status}</dt><dd>${pill}${manualPill}</dd>
    </dl>
  `;
  positionHover(tile);
  hover.el.classList.add('visible');
}

function positionHover(tile) {
  const r = tile.getBoundingClientRect();
  const cardRect = hover.el.getBoundingClientRect();
  const margin = 8;
  let left = r.right + margin;
  let top = r.top;
  if (left + cardRect.width > window.innerWidth - margin) {
    left = r.left - cardRect.width - margin;
  }
  if (top + cardRect.height > window.innerHeight - margin) {
    top = Math.max(margin, window.innerHeight - cardRect.height - margin);
  }
  if (top < margin) top = margin;
  if (left < margin) left = margin;
  hover.el.style.left = `${left}px`;
  hover.el.style.top = `${top}px`;
}

function hideHover() {
  hover.el?.classList.remove('visible');
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

/* ── quilt ───────────────────────────────────────────────────────── */
function mapEntryToStatus(entry) {
  return entry.real ? 'real' : 'placeholder';
}

function renderQuilt() {
  const root = document.getElementById('quilt');
  root.innerHTML = '';
  const frag = document.createDocumentFragment();
  const idx = state.index;
  for (const e of idx.entries) {
    const tile = document.createElement('a');
    tile.className = 'tile';
    tile.href = `${idx.cdn}/logos/${idx.category_to_dir[e.cat]}/${e.slug}.png`;
    tile.target = '_blank';
    tile.rel = 'noopener';
    tile.dataset.category = e.cat;
    tile.dataset.slug = e.slug;
    tile.dataset.name = e.name;
    tile.dataset.real = String(e.real);
    tile.dataset.source = e.real ? 'arkham' : 'placeholder';
    const img = document.createElement('img');
    img.loading = 'lazy';
    img.decoding = 'async';
    img.width = 64;
    img.height = 64;
    img.alt = e.name;
    img.src = tile.href;
    tile.appendChild(img);
    frag.appendChild(tile);
  }
  root.appendChild(frag);

  // Delegate hover once, don't add 800 individual listeners.
  root.addEventListener('mouseover', e => {
    const tile = e.target.closest('.tile');
    if (!tile) return;
    clearTimeout(hover.timer);
    hover.timer = setTimeout(() => showHover(tile), 120);
  });
  root.addEventListener('mouseleave', () => {
    clearTimeout(hover.timer);
    hideHover();
  }, true);
  // Keyboard focus for accessibility
  root.addEventListener('focusin', e => {
    const tile = e.target.closest('.tile');
    if (tile) showHover(tile);
  });
  root.addEventListener('focusout', hideHover);
}

function renderTabs() {
  const root = document.getElementById('tabs');
  const entries = state.index.entries;
  const totalCounts = entries.reduce((m, e) => {
    m[e.cat] = (m[e.cat] || 0) + 1;
    return m;
  }, {});

  const q = (state.searchQuery || '').trim().toLowerCase();
  const tokens = q ? q.split(/\s+/).filter(Boolean) : null;

  const lang = document.documentElement.lang;
  const labels = lang === 'ru' ? CATEGORY_LABEL_RU : CATEGORY_LABEL_EN;
  const cats = Object.keys(CATEGORY_LABEL_EN).filter(c => totalCounts[c]);
  root.innerHTML = '';

  for (const c of cats) {
    const btn = document.createElement('button');
    btn.className = 'tab';
    btn.type = 'button';
    btn.dataset.cat = c;
    btn.setAttribute('aria-pressed', String(state.activeCats.has(c)));

    const total = totalCounts[c];
    if (tokens && tokens.length) {
      const matchCount = entries.filter(e =>
        e.cat === c && tokens.every(tok =>
          e.name.toLowerCase().includes(tok) ||
          e.slug.toLowerCase().includes(tok)
        )
      ).length;
      btn.innerHTML = `${labels[c]}<span class="count">${matchCount}/${total}</span>`;
    } else {
      btn.innerHTML = `${labels[c]}<span class="count">${total}</span>`;
    }

    btn.addEventListener('click', () => toggleCat(c));
    root.appendChild(btn);
  }

  if (state.activeCats.size) {
    const clear = document.createElement('button');
    clear.className = 'tab tab-clear';
    clear.type = 'button';
    clear.textContent = lang === 'ru' ? 'Сбросить' : 'Clear';
    clear.addEventListener('click', () => {
      state.activeCats.clear();
      applyFilter();
      renderTabs();
    });
    root.appendChild(clear);
  }
}

function toggleCat(c) {
  const wasActive = state.activeCats.has(c);
  if (wasActive) state.activeCats.delete(c);
  else state.activeCats.add(c);
  renderTabs();
  applyFilter().then(() => {
    if (!wasActive && state.activeCats.has(c)) {
      const first = document.querySelector(`.tile:not(.tile-hidden)[data-category="${c}"]`);
      if (first) first.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  });
}

let _filterGeneration = 0;

async function applyFilter() {
  const gen = ++_filterGeneration;
  const quilt = document.getElementById('quilt');

  quilt.classList.add('quilt-fading');
  await new Promise(r => setTimeout(r, 155));
  if (gen !== _filterGeneration) return;

  const active = state.activeCats;
  const q = (state.searchQuery || '').trim().toLowerCase();
  const tokens = q ? q.split(/\s+/).filter(Boolean) : null;
  const hasFilter = active.size > 0 || !!(tokens && tokens.length);

  quilt.querySelectorAll('.tile').forEach(t => {
    const catMatch = !active.size || active.has(t.dataset.category);
    const nameMatch = !tokens || tokens.every(tok =>
      t.dataset.name.toLowerCase().includes(tok) ||
      t.dataset.slug.toLowerCase().includes(tok)
    );
    const show = !hasFilter || (catMatch && nameMatch);
    t.classList.toggle('tile-hidden', !show);
    t.classList.toggle('matches', show && hasFilter);
  });

  if (hasFilter) {
    quilt.dataset.filterActive = 'true';
  } else {
    quilt.removeAttribute('data-filter-active');
  }

  updateSearchCount();
  updateBackToFilterBtn();

  // Reset any stale tile-in animations, then fade the quilt back in.
  quilt.querySelectorAll('.tile.tile-in').forEach(t => t.classList.remove('tile-in'));
  void quilt.offsetWidth; // single reflow resets CSS animation state
  quilt.classList.remove('quilt-fading');

  // Stagger visible tiles in.
  const visibleTiles = Array.from(quilt.querySelectorAll('.tile:not(.tile-hidden)'));
  visibleTiles.forEach((t, i) => {
    t.style.setProperty('--tile-i', String(Math.min(i, 50)));
    t.classList.add('tile-in');
  });
  const cleanupMs = Math.min(visibleTiles.length, 50) * 6 + 260;
  setTimeout(() => {
    if (gen === _filterGeneration) visibleTiles.forEach(t => t.classList.remove('tile-in'));
  }, cleanupMs);
}

/* ── search ──────────────────────────────────────────────────────── */
function updateSearchCount() {
  const el = document.getElementById('search-count');
  if (!el) return;
  const hasFilter = (state.searchQuery || '').trim() || state.activeCats.size;
  if (!hasFilter) { el.textContent = ''; return; }
  const n = document.querySelectorAll('#quilt .tile:not(.tile-hidden)').length;
  const total = state.index.entries.length;
  const lang = document.documentElement.lang;
  el.textContent = lang === 'ru' ? `${n} из ${total}` : `${n} of ${total}`;
}

function wireSearch() {
  const input = document.getElementById('quilt-search');
  if (!input) return;
  let debounce;
  input.addEventListener('input', () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => {
      state.searchQuery = input.value;
      renderTabs();
      applyFilter();
    }, 150);
  });
  input.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      input.value = '';
      state.searchQuery = '';
      renderTabs();
      applyFilter();
    }
  });
}

/* ── back-to-filter sticky ───────────────────────────────────────── */
let _tabsVisible = true;

function updateBackToFilterBtn() {
  const btn = document.getElementById('back-to-filter');
  if (!btn) return;
  const hasFilter = state.activeCats.size > 0 || (state.searchQuery || '').trim().length > 0;
  btn.hidden = _tabsVisible || !hasFilter;
}

function wireBackToFilter() {
  const btn = document.getElementById('back-to-filter');
  const tabs = document.getElementById('tabs');
  if (!btn || !tabs) return;
  const obs = new IntersectionObserver(entries => {
    _tabsVisible = entries[0].isIntersecting;
    updateBackToFilterBtn();
  }, { threshold: 0.1 });
  obs.observe(tabs);
  btn.addEventListener('click', () => {
    tabs.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}

/* ── stats ───────────────────────────────────────────────────────── */
function renderStats() {
  const entries = state.index.entries;
  // total_entities = full CSV count (including placeholder-only rows);
  // falls back to entries.length for older lookup builds.
  const total = state.index.total_entities ?? entries.length;
  const real  = entries.length;  // entries now contains only real-logo rows
  const cats  = new Set(entries.map(e => e.cat)).size;
  const set = id => {
    const el = document.getElementById(id);
    if (el) el.textContent = id === 'stat-updated'
      ? state.index.generated_at
      : id === 'stat-real'
        ? real.toString()
        : id === 'stat-total'
          ? total.toString()
          : cats.toString();
  };
  ['stat-total', 'stat-real', 'stat-cats', 'stat-updated'].forEach(set);
}

/* ── bulk upload ──────────────────────────────────────────────────── */
const CANVAS_SIZE = 160;
const MAX_INPUT_BYTES = 5 * 1024 * 1024;

async function normaliseToPng(file) {
  if (file.size > MAX_INPUT_BYTES) {
    throw new Error(`file too large (${(file.size / 1e6).toFixed(1)}MB > 5MB)`);
  }
  const bitmap = await createImageBitmap(file).catch(() => null);
  if (!bitmap) throw new Error('could not decode image');
  const scale = CANVAS_SIZE / Math.max(bitmap.width, bitmap.height);
  const w = Math.max(1, Math.round(bitmap.width * scale));
  const h = Math.max(1, Math.round(bitmap.height * scale));
  const canvas = document.createElement('canvas');
  canvas.width = CANVAS_SIZE;
  canvas.height = CANVAS_SIZE;
  const ctx = canvas.getContext('2d');
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(bitmap, (CANVAS_SIZE - w) / 2, (CANVAS_SIZE - h) / 2, w, h);
  const blob = await new Promise(res => canvas.toBlob(res, 'image/png'));
  if (!blob) throw new Error('PNG encode failed');
  const dataUrl = await new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(fr.result);
    fr.onerror = () => rej(fr.error);
    fr.readAsDataURL(blob);
  });
  return { dataUrl, bytes: blob.size };
}

function filenameToSlug(name) {
  // "Binance Hot Wallet.png" → "binance-hot-wallet"
  return name
    .replace(/\.[^.]+$/, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/** Match a dropped filename to the best entity in the index.
 *  Strategy: exact slug match (any category) first; failing that,
 *  keyword-overlap like lookup.js. Returns matching entry or null. */
function matchFilename(name) {
  const stem = filenameToSlug(name);
  const entries = state.index.entries;
  const exact = entries.find(e => e.slug === stem);
  if (exact) return exact;
  const tokens = new Set(stem.split('-').filter(t => t.length >= 3));
  if (!tokens.size) return null;
  let best = null, bestScore = 0;
  for (const e of entries) {
    let score = 0;
    for (const k of e.kw) if (tokens.has(k)) score++;
    if (score === 0) continue;
    const effective = score + (e.real ? 0.5 : 0);
    if (effective > bestScore) { best = e; bestScore = effective; }
  }
  return best;
}

function escapeCsv(v) {
  const s = String(v ?? '');
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

const BULK_HEADER = [
  'category_slug', 'arkham_slug', 'entity_name',
  'reason', 'note',
  'current_logo_status', 'current_logo_updated_at', 'current_logo_hash',
  'canonical_domain',
  'flagged_at',
  'suggested_filename', 'suggested_bytes', 'suggested_logo_data_url',
];

async function handleBulk(files) {
  const zone = document.querySelector('.dropzone');
  const results = document.getElementById('bulk-results');
  const list = document.getElementById('bulk-matches');
  const dl = document.getElementById('bulk-download');
  list.innerHTML = '';
  results.classList.add('visible');
  const fileArr = Array.from(files).filter(f => f.type.startsWith('image/'));
  if (!fileArr.length) {
    zone.classList.remove('dragging');
    return;
  }

  const rows = [BULK_HEADER.join(',')];
  let matched = 0, unmatched = 0;
  const nowIso = new Date().toISOString();
  for (const f of fileArr) {
    const entry = matchFilename(f.name);
    const div = document.createElement('div');
    div.className = 'bulk-match' + (entry ? '' : ' unmatched');
    const info = document.createElement('div');
    info.className = 'bm-info';
    if (!entry) {
      unmatched++;
      info.innerHTML = `<div class="bm-filename">${escapeHtml(f.name)}</div>
                       <div class="bm-target">no match — skipped</div>`;
      div.appendChild(info);
      list.appendChild(div);
      continue;
    }
    let norm;
    try {
      norm = await normaliseToPng(f);
    } catch (err) {
      unmatched++;
      info.innerHTML = `<div class="bm-filename">${escapeHtml(f.name)}</div>
                       <div class="bm-target">error: ${escapeHtml(err.message)}</div>`;
      div.appendChild(info);
      list.appendChild(div);
      continue;
    }
    matched++;
    const preview = document.createElement('img');
    preview.className = 'bm-preview';
    preview.src = norm.dataUrl;
    info.innerHTML = `
      <div class="bm-filename">${escapeHtml(f.name)}</div>
      <div class="bm-target">→ ${entry.cat}/${entry.slug} (${escapeHtml(entry.name)})</div>
    `;
    div.appendChild(preview);
    div.appendChild(info);
    list.appendChild(div);

    rows.push([
      entry.cat, entry.slug, entry.name,
      'manual_needed', 'bulk-upload',
      entry.real ? 'arkham' : 'placeholder', '', '',
      '',
      nowIso,
      f.name, norm.bytes, norm.dataUrl,
    ].map(escapeCsv).join(','));
  }

  const summary = document.getElementById('bulk-summary');
  const lang = document.documentElement.lang;
  summary.textContent = lang === 'ru'
    ? `Совпало: ${matched}. Пропущено: ${unmatched}.`
    : `Matched: ${matched}. Skipped: ${unmatched}.`;

  if (matched === 0) {
    dl.style.display = 'none';
  } else {
    dl.style.display = 'inline-flex';
    dl.onclick = () => {
      const csv = rows.join('\n') + '\n';
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `kyt-registry-rework-BULK-${new Date().toISOString().slice(0,10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    };
  }

  zone.classList.remove('dragging');
}

function wireBulkUpload() {
  const zone = document.querySelector('.dropzone');
  const input = document.getElementById('bulk-input');
  zone.addEventListener('click', () => input.click());
  input.addEventListener('change', () => handleBulk(input.files));
  ['dragenter', 'dragover'].forEach(ev => {
    zone.addEventListener(ev, e => {
      e.preventDefault();
      zone.classList.add('dragging');
    });
  });
  ['dragleave', 'drop'].forEach(ev => {
    zone.addEventListener(ev, e => {
      e.preventDefault();
      if (ev === 'dragleave' && e.target !== zone) return;
      zone.classList.remove('dragging');
    });
  });
  zone.addEventListener('drop', e => handleBulk(e.dataTransfer.files));
}

/* ── lang toggle ─────────────────────────────────────────────────── */
function wireLangToggle() {
  document.querySelectorAll('.lang-toggle button').forEach(b => {
    b.addEventListener('click', () => {
      setLang(b.dataset.lang);
      renderTabs();
      updateSearchCount();
    });
  });
}

/* ── boot ─────────────────────────────────────────────────────────── */
async function boot() {
  setLang(initialLang());
  wireLangToggle();

  try {
    const r = await fetch('logos/_lookup.json', { cache: 'default' });
    if (!r.ok) throw new Error(`lookup ${r.status}`);
    state.index = await r.json();
    // Re-sort the entries for the quilt: block-by-block per
    // CATEGORY_ORDER, then importance desc, then name. The index is
    // delivered in pure importance-desc order which would scatter
    // categories; regrouping here gives a "all Exchanges then all
    // DEX then all Bridges…" visual block layout instead.
    state.index.entries.sort((a, b) => {
      const ra = CATEGORY_RANK[a.cat] ?? 99;
      const rb = CATEGORY_RANK[b.cat] ?? 99;
      if (ra !== rb) return ra - rb;
      if (a.imp !== b.imp) return b.imp - a.imp;
      return a.name.localeCompare(b.name);
    });
  } catch (e) {
    const banner = document.getElementById('quilt');
    const msg = document.createElement('div');
    msg.style.padding = '32px';
    msg.style.textAlign = 'center';
    msg.style.color = 'var(--muted-foreground)';
    msg.textContent = `Could not load registry index: ${e.message}`;
    banner.replaceChildren(msg);
    return;
  }

  renderStats();
  renderTabs();
  renderQuilt();
  wireSearch();
  wireBackToFilter();
  wireBulkUpload();

  // CTA button smooth-scroll
  document.querySelectorAll('a[href^="#"]').forEach(a => {
    a.addEventListener('click', e => {
      const target = document.querySelector(a.getAttribute('href'));
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
}

boot();
