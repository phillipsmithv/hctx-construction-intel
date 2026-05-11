// ════════════════════════════════════════════════════════════════════
// HCTX Construction Intel — Dashboard Logic
// Vanilla JS, no build step. Reads SQLite from repo via sql.js.
// ════════════════════════════════════════════════════════════════════

const STAGES = [
  { id: 'hot',       label: '🔥 Hot Leads',  color: 'border-hot',       desc: 'Score 70+, uncontacted' },
  { id: 'contacted', label: '📞 Contacted',  color: 'border-contacted', desc: 'Jarvis fired, awaiting reply' },
  { id: 'engaged',   label: '💬 Engaged',    color: 'border-engaged',   desc: 'Replied or picked up' },
  { id: 'quoted',    label: '✅ Quoted',     color: 'border-quoted',    desc: 'Sent quote, awaiting PO' },
  { id: 'won',       label: '🏆 Won',        color: 'border-won',       desc: 'Closed deal' },
  { id: 'cold',      label: '❄️ Cold/Dead',  color: 'border-cold',      desc: 'Tried 3x, no response' },
];

let db = null;            // sql.js Database
let allPermits = [];      // current filtered set
let map = null;
let mapMarkers = [];

// ─── Bootstrap ───────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  await loadDatabase();
  attachEventListeners();
  refreshAll();
});

async function loadDatabase() {
  try {
    const SQL = await initSqlJs({ locateFile: f => `https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.3/${f}` });
    const resp = await fetch('../db/construction_intel.db');
    if (!resp.ok) throw new Error(`Database not found (HTTP ${resp.status}). Run a scrape first.`);
    const buf = await resp.arrayBuffer();
    db = new SQL.Database(new Uint8Array(buf));
    console.log('Database loaded.');
  } catch (e) {
    console.error('DB load failed:', e);
    document.body.insertAdjacentHTML('afterbegin',
      `<div class="bg-hot text-white p-4 text-center">⚠️ ${e.message}</div>`);
  }
}

// ─── Query the DB based on current filters ──────────────────────────
function fetchPermits() {
  if (!db) return [];
  const search = document.getElementById('search-box').value.trim();
  const county = document.getElementById('filter-county').value;
  const ptype = document.getElementById('filter-type').value;
  const minScore = parseInt(document.getElementById('filter-score').value) || 0;
  const minVal = parseInt(document.getElementById('filter-valuation').value) || 0;

  let sql = `
    SELECT p.*, c.company_name AS contractor_company, c.phone AS contractor_phone,
           c.email AS contractor_email, c.outreach_tier
    FROM permits p
    LEFT JOIN contractors c ON c.id = p.contractor_id
    WHERE p.lead_score >= ?
      AND COALESCE(p.declared_valuation, 0) >= ?
  `;
  const params = [minScore, minVal];

  if (county) { sql += ' AND p.county = ?'; params.push(county); }
  if (ptype)  { sql += ' AND p.permit_type = ?'; params.push(ptype); }
  if (search) {
    sql += ' AND (p.project_address LIKE ? OR p.contractor_name_raw LIKE ? OR p.source_permit_id LIKE ?)';
    const s = `%${search}%`;
    params.push(s, s, s);
  }
  sql += ' ORDER BY p.lead_score DESC, p.issue_date DESC LIMIT 1000';

  const stmt = db.prepare(sql);
  stmt.bind(params);
  const rows = [];
  while (stmt.step()) rows.push(stmt.getAsObject());
  stmt.free();
  return rows;
}

// ─── Refresh all views with current filter ──────────────────────────
function refreshAll() {
  allPermits = fetchPermits();
  renderStats();
  renderKanban();
  renderTable();
  if (!document.getElementById('view-map').classList.contains('hidden')) renderMap();
}

function renderStats() {
  const hot = allPermits.filter(p => p.pipeline_stage === 'hot' && p.lead_score >= 70).length;
  const total = allPermits.reduce((s, p) => s + (p.declared_valuation || 0), 0);
  document.getElementById('stat-hot').textContent = hot;
  document.getElementById('stat-value').textContent = '$' + total.toLocaleString('en-US', { maximumFractionDigits: 0 });

  // Last sync from scrape_log
  if (db) {
    const stmt = db.prepare('SELECT MAX(run_completed_at) AS last FROM scrape_log WHERE status = "success"');
    if (stmt.step()) {
      const last = stmt.getAsObject().last;
      document.getElementById('stat-sync').textContent = last ? new Date(last).toLocaleString() : 'Never';
    }
    stmt.free();
  }
}

// ─── KANBAN ─────────────────────────────────────────────────────────
function renderKanban() {
  const container = document.querySelector('#view-kanban > div');
  container.innerHTML = '';
  STAGES.forEach(stage => {
    const items = allPermits.filter(p => p.pipeline_stage === stage.id);
    const valueSum = items.reduce((s, p) => s + (p.declared_valuation || 0), 0);
    const col = document.createElement('div');
    col.className = `bg-panel-2 rounded-lg border-t-4 ${stage.color} w-80 flex-shrink-0`;
    col.innerHTML = `
      <div class="p-3 border-b border-border-base">
        <div class="flex items-center justify-between">
          <div class="font-bold">${stage.label}</div>
          <div class="text-xs bg-panel-3 px-2 py-0.5 rounded">${items.length}</div>
        </div>
        <div class="text-xs text-gray-400 mt-1">${stage.desc}</div>
        <div class="text-xs text-accent mt-1">$${valueSum.toLocaleString('en-US', { maximumFractionDigits: 0 })}</div>
      </div>
      <div class="kanban-col p-2 space-y-2 min-h-[200px]" data-stage="${stage.id}"></div>
    `;
    const list = col.querySelector('.kanban-col');
    items.forEach(p => list.appendChild(buildPermitCard(p)));
    container.appendChild(col);

    new Sortable(list, {
      group: 'permits',
      animation: 150,
      ghostClass: 'opacity-50',
      onEnd: evt => updateStage(evt.item.dataset.permitId, evt.to.dataset.stage),
    });
  });
}

function buildPermitCard(p) {
  const card = document.createElement('div');
  card.className = 'bg-panel-3 hover:bg-opacity-80 cursor-pointer rounded p-3 border border-border-base';
  card.dataset.permitId = p.id;
  const scoreColor = p.lead_score >= 85 ? 'text-hot' : p.lead_score >= 70 ? 'text-accent-2' : 'text-gray-400';
  const tags = parseJSON(p.tags) || [];
  card.innerHTML = `
    <div class="flex justify-between items-start mb-2">
      <div class="text-xs text-gray-400">${p.source_permit_id || ''}</div>
      <div class="font-bold ${scoreColor}">${p.lead_score}</div>
    </div>
    <div class="font-medium text-sm mb-1">${truncate(p.project_address || 'No address', 50)}</div>
    <div class="text-xs text-gray-400 mb-2">${(p.permit_type || '').replace(/_/g, ' ')}</div>
    <div class="flex justify-between items-center text-xs">
      <span class="text-accent">$${(p.declared_valuation || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })}</span>
      <span class="text-gray-500">${p.issue_date || ''}</span>
    </div>
    ${tags.length ? `<div class="mt-2 flex gap-1 flex-wrap">${tags.slice(0,3).map(t =>
      `<span class="text-[10px] bg-panel border border-border-base px-1.5 py-0.5 rounded">${t}</span>`
    ).join('')}</div>` : ''}
  `;
  card.addEventListener('click', () => openModal(p));
  return card;
}

function updateStage(permitId, newStage) {
  if (!db) return;
  db.run('UPDATE permits SET pipeline_stage = ? WHERE id = ?', [newStage, permitId]);
  // NOTE: This is in-memory only — see SYNCING STAGE CHANGES in README.
  // For persistent changes, call the FastAPI endpoint or commit DB back to repo.
  console.log(`Stage updated locally: ${permitId} → ${newStage}`);
  refreshAll();
}

// ─── TABLE ──────────────────────────────────────────────────────────
function renderTable() {
  const tbody = document.getElementById('table-body');
  tbody.innerHTML = allPermits.map(p => {
    const scoreColor = p.lead_score >= 85 ? 'text-hot' : p.lead_score >= 70 ? 'text-accent-2' : 'text-gray-300';
    return `
      <tr class="hover:bg-panel-3 cursor-pointer" onclick='openModalById(${p.id})'>
        <td class="px-4 py-2 font-bold ${scoreColor}">${p.lead_score}</td>
        <td class="px-4 py-2 font-mono text-xs">${p.source_permit_id || ''}</td>
        <td class="px-4 py-2 text-sm">${(p.permit_type || '').replace(/_/g, ' ')}</td>
        <td class="px-4 py-2 text-sm">${truncate(p.project_address || '', 40)}</td>
        <td class="px-4 py-2 text-sm">${p.county || ''}</td>
        <td class="px-4 py-2 text-right text-accent">$${(p.declared_valuation || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })}</td>
        <td class="px-4 py-2 text-sm">${truncate(p.contractor_company || p.contractor_name_raw || '—', 25)}</td>
        <td class="px-4 py-2 text-xs text-gray-400">${p.issue_date || ''}</td>
        <td class="px-4 py-2 text-xs"><span class="px-2 py-0.5 rounded bg-panel-3">${p.pipeline_stage}</span></td>
        <td class="px-4 py-2 text-center">
          <a href="https://maps.google.com/maps?q=${encodeURIComponent(p.project_address || '')}"
             target="_blank" onclick="event.stopPropagation()" class="text-accent">📍</a>
        </td>
      </tr>
    `;
  }).join('');
}

// ─── MAP ────────────────────────────────────────────────────────────
function saveMapboxToken() {
  const tok = document.getElementById('mapbox-token-input').value.trim();
  if (!tok.startsWith('pk.')) { alert('Token should start with pk.'); return; }
  localStorage.setItem('mapbox_token', tok);
  document.getElementById('mapbox-token-prompt').classList.add('hidden');
  initMap();
}

function initMap() {
  const tok = localStorage.getItem('mapbox_token');
  if (!tok) { document.getElementById('mapbox-token-prompt').classList.remove('hidden'); return; }
  if (map) return;
  mapboxgl.accessToken = tok;
  map = new mapboxgl.Map({
    container: 'map',
    style: 'mapbox://styles/mapbox/dark-v11',
    center: [-95.45, 29.85],   // Greater Houston centroid
    zoom: 9,
  });
  map.addControl(new mapboxgl.NavigationControl());
  map.on('load', renderMap);
}

function renderMap() {
  if (!map || !map.isStyleLoaded()) return;
  mapMarkers.forEach(m => m.remove());
  mapMarkers = [];
  const stageColors = { hot: '#ef4444', contacted: '#f59e0b', engaged: '#3b82f6',
                        quoted: '#8b5cf6', won: '#10b981', cold: '#6b7280' };
  allPermits.filter(p => p.latitude && p.longitude).forEach(p => {
    const el = document.createElement('div');
    el.className = 'map-marker';
    el.style.cssText = `width:14px;height:14px;border-radius:50%;cursor:pointer;
      background:${stageColors[p.pipeline_stage] || '#6b7280'};
      box-shadow:0 0 0 2px white,0 2px 4px rgba(0,0,0,.5);`;
    const popup = new mapboxgl.Popup({ offset: 12 }).setHTML(`
      <div style="color:#000;min-width:200px">
        <div style="font-weight:bold">${p.project_address || ''}</div>
        <div style="font-size:12px;margin-top:4px">${(p.permit_type || '').replace(/_/g,' ')}</div>
        <div style="font-size:12px">$${(p.declared_valuation || 0).toLocaleString()}</div>
        <div style="font-size:12px;color:#888">Score: ${p.lead_score}</div>
      </div>
    `);
    const marker = new mapboxgl.Marker(el).setLngLat([p.longitude, p.latitude]).setPopup(popup).addTo(map);
    mapMarkers.push(marker);
  });
}

// ─── MODAL ──────────────────────────────────────────────────────────
function openModalById(id) {
  const p = allPermits.find(x => x.id === id);
  if (p) openModal(p);
}

function openModal(p) {
  const m = document.getElementById('lead-modal');
  document.getElementById('modal-content').innerHTML = `
    <div class="flex justify-between items-start mb-4">
      <div>
        <div class="text-xs text-gray-400 font-mono">${p.source_permit_id}</div>
        <div class="text-xl font-bold">${p.project_address || ''}</div>
      </div>
      <button onclick="document.getElementById('lead-modal').classList.add('hidden')" class="text-gray-400 hover:text-white text-2xl">×</button>
    </div>
    <div class="grid grid-cols-2 gap-4 mb-4">
      <div><div class="text-xs text-gray-400">Lead Score</div><div class="text-2xl font-bold text-accent">${p.lead_score}</div></div>
      <div><div class="text-xs text-gray-400">Valuation</div><div class="text-2xl font-bold text-accent-2">$${(p.declared_valuation || 0).toLocaleString()}</div></div>
      <div><div class="text-xs text-gray-400">Permit Type</div><div>${(p.permit_type || '').replace(/_/g,' ')}</div></div>
      <div><div class="text-xs text-gray-400">Issued</div><div>${p.issue_date || '—'}</div></div>
      <div><div class="text-xs text-gray-400">County</div><div>${p.county || '—'}</div></div>
      <div><div class="text-xs text-gray-400">Stage</div><div>${p.pipeline_stage}</div></div>
    </div>
    <div class="mb-4">
      <div class="text-xs text-gray-400 mb-1">Contractor</div>
      <div class="bg-panel-3 p-3 rounded">
        <div class="font-medium">${p.contractor_company || p.contractor_name_raw || 'Unknown'}</div>
        ${p.contractor_phone ? `<div class="text-sm">📞 ${p.contractor_phone}</div>` : ''}
        ${p.contractor_email ? `<div class="text-sm">✉️ ${p.contractor_email}</div>` : ''}
      </div>
    </div>
    ${p.description ? `<div class="mb-4"><div class="text-xs text-gray-400 mb-1">Description</div><div class="text-sm bg-panel-3 p-3 rounded">${p.description}</div></div>` : ''}
    <div class="flex gap-2 mt-4">
      <a href="https://maps.google.com/maps?q=${encodeURIComponent(p.project_address || '')}" target="_blank"
         class="bg-accent text-black px-4 py-2 rounded font-medium">📍 Directions</a>
      ${p.contractor_phone ? `<a href="tel:${p.contractor_phone}" class="bg-accent-2 text-black px-4 py-2 rounded font-medium">📞 Call</a>` : ''}
    </div>
  `;
  m.classList.remove('hidden');
}

// ─── EVENTS ─────────────────────────────────────────────────────────
function attachEventListeners() {
  document.querySelectorAll('.view-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('bg-accent', 'text-black'));
      btn.classList.add('bg-accent', 'text-black');
      const view = btn.dataset.view;
      document.querySelectorAll('.view-panel').forEach(p => p.classList.add('hidden'));
      document.getElementById(`view-${view}`).classList.remove('hidden');
      if (view === 'map') initMap();
    });
  });
  document.getElementById('search-box').addEventListener('input', debounce(refreshAll, 300));
  ['filter-county', 'filter-type', 'filter-score', 'filter-valuation'].forEach(id =>
    document.getElementById(id).addEventListener('change', refreshAll));
  document.getElementById('btn-export').addEventListener('click', exportToCSV);
  document.getElementById('lead-modal').addEventListener('click', e => {
    if (e.target.id === 'lead-modal') e.target.classList.add('hidden');
  });
}

function exportToCSV() {
  const headers = ['Permit ID', 'Address', 'County', 'Type', 'Valuation', 'Score', 'Stage', 'Contractor', 'Phone', 'Email'];
  const rows = allPermits.map(p => [
    p.source_permit_id, p.project_address, p.county, p.permit_type,
    p.declared_valuation, p.lead_score, p.pipeline_stage,
    p.contractor_company || p.contractor_name_raw || '',
    p.contractor_phone || '', p.contractor_email || '',
  ]);
  const csv = [headers, ...rows].map(r => r.map(c => `"${(c ?? '').toString().replace(/"/g,'""')}"`).join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `hctx_construction_leads_${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
}

// ─── UTIL ───────────────────────────────────────────────────────────
function truncate(s, n) { return (s || '').length > n ? s.slice(0, n) + '…' : (s || ''); }
function parseJSON(s) { try { return JSON.parse(s); } catch { return null; } }
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
