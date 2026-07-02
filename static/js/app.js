let mediaItems = [];
let selectedItem = null;
let stats = null;
let favoritesOnly = false;
let viewMode = localStorage.getItem('ps_view_mode') || 'list';

const gallery = document.getElementById('gallery');
const statusBox = document.getElementById('statusBox');
const searchInput = document.getElementById('searchInput');
const adminPanel = document.getElementById('adminPanel');
const editForm = document.getElementById('editForm');
const projectFilter = document.getElementById('projectFilter');
const categoryFilter = document.getElementById('categoryFilter');
const typeFilter = document.getElementById('typeFilter');
const favoritesOnlyBtn = document.getElementById('favoritesOnlyBtn');
const listViewBtn = document.getElementById('listViewBtn');
const gridViewBtn = document.getElementById('gridViewBtn');

function setStatus(message) { statusBox.textContent = 'Status: ' + message; }
function mediaUrl(path) { return '/' + path; }
function escapeHtml(value) {
  return String(value || '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

async function loadMedia() {
  const res = await fetch('/api/media');
  const data = await res.json();
  mediaItems = data.items || [];
  window.hotspotAdmin?.setMediaItems(mediaItems);
  if (selectedItem) {
    selectedItem = mediaItems.find(item => item.id === selectedItem.id) || null;
    window.hotspotAdmin?.setCurrentItem(selectedItem);
  }
  stats = data.stats || null;
  updateStats();
  updateFilters();
  renderGallery();
}

function updateStats() {
  const el = document.getElementById('statsGrid');
  const s = stats || { photos:0, videos:0, favorites:0, projects:[] };
  el.innerHTML = `
    <div><strong>${s.photos || 0}</strong><span>Fotos</span></div>
    <div><strong>${s.videos || 0}</strong><span>Videos</span></div>
    <div><strong>${s.favorites || 0}</strong><span>Favoriten</span></div>
    <div><strong>${(s.projects || []).length}</strong><span>Projekte</span></div>
  `;
}

function setSelectOptions(select, values, allLabel) {
  const old = select.value;
  select.innerHTML = `<option value="">${allLabel}</option>` + values.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('');
  if (values.includes(old)) select.value = old;
}

function updateFilters() {
  const projects = [...new Set(mediaItems.map(i => i.project || 'Default'))].sort((a,b)=>a.localeCompare(b));
  const categories = [...new Set(mediaItems.map(i => i.category).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
  setSelectOptions(projectFilter, projects, 'Alle Projekte');
  setSelectOptions(categoryFilter, categories, 'Alle Kategorien');
}

function filteredItems() {
  const q = searchInput.value.trim().toLowerCase();
  const project = projectFilter.value;
  const category = categoryFilter.value;
  const type = typeFilter.value;
  return mediaItems
    .filter(item => item.visible)
    .filter(item => !favoritesOnly || item.favorite)
    .filter(item => !project || (item.project || 'Default') === project)
    .filter(item => !category || (item.category || '') === category)
    .filter(item => !type || item.type === type)
    .filter(item => !q || [item.title, item.project, item.category, item.description, item.file_path].join(' ').toLowerCase().includes(q));
}

function itemPreview(item) {
  if (item.type === 'photo' && item.thumb_path) return `<img class="thumb" src="${mediaUrl(item.thumb_path)}" loading="lazy" />`;
  return `<div class="video-thumb">${item.type === 'video' ? '🎬' : '📷'}</div>`;
}

function itemCard(item) {
  const row = document.createElement('div');
  row.className = 'item' + (selectedItem?.id === item.id ? ' active' : '');
  row.innerHTML = `${itemPreview(item)}<div class="item-body"><div class="item-title">${item.favorite ? '★ ' : ''}${escapeHtml(item.title)}</div><div class="item-meta">${escapeHtml(item.project || 'Default')}${item.category ? ' · ' + escapeHtml(item.category) : ''} · ${item.type}</div></div>`;
  row.onclick = () => selectItem(item);
  return row;
}

function renderGallery() {
  const items = filteredItems();
  gallery.className = 'gallery ' + (viewMode === 'grid' ? 'grid-mode' : 'list-mode');
  gallery.innerHTML = '';

  listViewBtn.classList.toggle('active', viewMode === 'list');
  gridViewBtn.classList.toggle('active', viewMode === 'grid');
  favoritesOnlyBtn.classList.toggle('active', favoritesOnly);

  if (!items.length) {
    gallery.innerHTML = '<div class="no-results">Keine passenden Medien.</div>';
    return;
  }

  const projects = [...new Set(items.map(i => i.project || 'Default'))];
  projects.forEach(project => {
    const groupItems = items.filter(i => (i.project || 'Default') === project);
    const h = document.createElement('div');
    h.className = 'project-heading';
    h.innerHTML = `<span>📁 ${escapeHtml(project)}</span><small>${groupItems.length}</small>`;
    gallery.appendChild(h);
    groupItems.forEach(item => gallery.appendChild(itemCard(item)));
  });
}

function selectItem(item) {
  selectedItem = item;
  window.hotspotAdmin?.setCurrentItem(item);
  fillForm(item);
  renderGallery();
  loadViewer(item);
}

function showNavigationMessage(message) {
  if (window.viewerControls?.openInfoDialog) {
    window.viewerControls.openInfoDialog('Panorama nicht verfügbar', message);
  } else {
    window.alert(message);
  }
}

function openMediaById(mediaId) {
  const item = mediaItems.find(candidate => String(candidate.id) === String(mediaId));
  if (!item) {
    showNavigationMessage('Das verknüpfte Zielpanorama wurde nicht gefunden.');
    return false;
  }
  if (!item.visible) {
    showNavigationMessage('Das verknüpfte Zielpanorama ist derzeit nicht sichtbar.');
    return false;
  }
  if (item.type !== 'photo') {
    showNavigationMessage('Das verknüpfte Ziel ist kein Panorama.');
    return false;
  }

  if (!filteredItems().some(candidate => candidate.id === item.id)) {
    searchInput.value = '';
    projectFilter.value = '';
    categoryFilter.value = '';
    typeFilter.value = '';
    favoritesOnly = false;
  }
  selectItem(item);
  return true;
}

window.openMediaById = openMediaById;
window.viewerControls?.setPanoramaNavigationCallback(openMediaById);

function fillForm(item) {
  document.getElementById('editTitle').value = item.title || '';
  document.getElementById('editProject').value = item.project || 'Default';
  document.getElementById('editCategory').value = item.category || '';
  document.getElementById('editDescription').value = item.description || '';
  document.getElementById('editFavorite').checked = !!item.favorite;
  document.getElementById('editVisible').checked = !!item.visible;
}

async function rescan() {
  setStatus('scannt...');
  const res = await fetch('/api/rescan', { method: 'POST' });
  const data = await res.json();
  setStatus(`Scan fertig. Gefunden: ${data.found}, neu: ${data.inserted}, aktualisiert: ${data.updated}`);
  await loadMedia();
}

async function uploadFiles(files) {
  if (!files.length) return;
  setStatus('Upload laeuft...');
  const form = new FormData();
  [...files].forEach(file => form.append('files', file));
  form.append('project', document.getElementById('uploadProject').value || 'Default');
  const res = await fetch('/api/upload', { method: 'POST', body: form });
  const data = await res.json();
  setStatus(`Upload fertig. Gespeichert: ${data.saved}, gefunden: ${data.found}`);
  await loadMedia();
}

document.getElementById('rescanBtn').onclick = rescan;
function setAdminMode(enabled) {
  adminPanel.classList.toggle('hidden', !enabled);
  window.hotspotAdmin?.setAdminMode(enabled);
}

document.getElementById('adminToggleBtn').onclick = () => setAdminMode(adminPanel.classList.contains('hidden'));
document.getElementById('closeAdminBtn').onclick = () => setAdminMode(false);
document.getElementById('fullscreenBtn').onclick = () => window.viewerControls?.toggleFullscreen();
document.getElementById('zoomInBtn').onclick = () => window.viewerControls?.zoomIn();
document.getElementById('zoomOutBtn').onclick = () => window.viewerControls?.zoomOut();
document.getElementById('homeBtn').onclick = () => window.viewerControls?.resetView();
document.getElementById('tinyPlanetBtn').onclick = () => window.viewerControls?.toggleTinyPlanet();
document.getElementById('cinematicBtn').onclick = () => window.viewerControls?.toggleCinematic();
searchInput.oninput = renderGallery;
projectFilter.onchange = renderGallery;
categoryFilter.onchange = renderGallery;
typeFilter.onchange = renderGallery;
favoritesOnlyBtn.onclick = () => { favoritesOnly = !favoritesOnly; renderGallery(); };
listViewBtn.onclick = () => { viewMode = 'list'; localStorage.setItem('ps_view_mode', viewMode); renderGallery(); };
gridViewBtn.onclick = () => { viewMode = 'grid'; localStorage.setItem('ps_view_mode', viewMode); renderGallery(); };

const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
fileInput.onchange = () => uploadFiles(fileInput.files);
['dragenter','dragover'].forEach(evt => dropZone.addEventListener(evt, e => { e.preventDefault(); dropZone.classList.add('dragover'); }));
['dragleave','drop'].forEach(evt => dropZone.addEventListener(evt, e => { e.preventDefault(); dropZone.classList.remove('dragover'); }));
dropZone.addEventListener('drop', e => uploadFiles(e.dataTransfer.files));

editForm.onsubmit = async (e) => {
  e.preventDefault();
  if (!selectedItem) { setStatus('kein Medium ausgewaehlt'); return; }
  const payload = {
    title: document.getElementById('editTitle').value,
    project: document.getElementById('editProject').value,
    category: document.getElementById('editCategory').value,
    description: document.getElementById('editDescription').value,
    favorite: document.getElementById('editFavorite').checked ? 1 : 0,
    visible: document.getElementById('editVisible').checked ? 1 : 0
  };
  await fetch(`/api/media/${selectedItem.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  setStatus('gespeichert');
  selectedItem = { ...selectedItem, ...payload };
  await loadMedia();
};

loadMedia();
