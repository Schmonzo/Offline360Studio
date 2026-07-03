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

async function loadMedia() {
  const res = await fetch('/api/media');
  const data = await res.json();
  mediaItems = data.items || [];
  window.hotspotAdmin?.setMediaItems(mediaItems);
  window.projectUi?.setMediaItems(mediaItems);
  window.mapUi?.setMediaItems(mediaItems);
  if (selectedItem) {
    selectedItem = mediaItems.find(item => item.id === selectedItem.id) || null;
    window.hotspotAdmin?.setCurrentItem(selectedItem);
    window.mapUi?.setCurrentItem(selectedItem);
  }
  stats = data.stats || null;
  updateStats();
  updateFilters();
  renderGallery();
}

function updateStats() {
  const el = document.getElementById('statsGrid');
  const s = stats || { photos:0, videos:0, favorites:0, projects:[] };
  el.replaceChildren();
  [
    [s.photos || 0, 'Fotos'],
    [s.videos || 0, 'Videos'],
    [s.favorites || 0, 'Favoriten'],
    [window.projectUi?.getProjectCount() ?? (s.projects || []).length, 'Projekte']
  ].forEach(([value, label]) => {
    const cell = document.createElement('div');
    const strong = document.createElement('strong');
    const span = document.createElement('span');
    strong.textContent = String(value);
    span.textContent = label;
    cell.append(strong, span);
    el.appendChild(cell);
  });
}

function setSelectOptions(select, values, allLabel) {
  const old = select.value;
  select.replaceChildren();
  const allOption = document.createElement('option');
  allOption.value = '';
  allOption.textContent = allLabel;
  select.appendChild(allOption);
  values.forEach(value => {
    const itemOption = document.createElement('option');
    itemOption.value = value;
    itemOption.textContent = value;
    select.appendChild(itemOption);
  });
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
  const tourItems = window.projectUi?.getTourItems();
  return (tourItems || mediaItems)
    .filter(item => item.visible)
    .filter(item => !favoritesOnly || item.favorite)
    .filter(item => tourItems || !project || (item.project || 'Default') === project)
    .filter(item => !category || (item.category || '') === category)
    .filter(item => !type || item.type === type)
    .filter(item => !q || [item.title, item.project, item.category, item.description, item.file_path].join(' ').toLowerCase().includes(q));
}

function itemPreview(item) {
  if (item.type === 'photo' && item.thumb_path) {
    const image = document.createElement('img');
    image.className = 'thumb';
    image.src = mediaUrl(item.thumb_path);
    image.loading = 'lazy';
    image.alt = '';
    return image;
  }
  const preview = document.createElement('div');
  preview.className = 'video-thumb';
  preview.textContent = item.type === 'video' ? '🎬' : '📷';
  return preview;
}

function itemCard(item) {
  const row = document.createElement('div');
  row.className = 'item' + (selectedItem?.id === item.id ? ' active' : '');
  const body = document.createElement('div');
  const title = document.createElement('div');
  const meta = document.createElement('div');
  body.className = 'item-body';
  title.className = 'item-title';
  meta.className = 'item-meta';
  title.textContent = `${item.favorite ? '★ ' : ''}${item.title || ''}`;
  meta.textContent = `${item.project || 'Default'}${item.category ? ' · ' + item.category : ''} · ${item.type || ''}`;
  body.append(title, meta);
  row.append(itemPreview(item), body);
  row.onclick = () => selectItem(item);
  return row;
}

function renderGallery() {
  const items = filteredItems();
  gallery.className = 'gallery ' + (viewMode === 'grid' ? 'grid-mode' : 'list-mode');
  gallery.replaceChildren();

  listViewBtn.classList.toggle('active', viewMode === 'list');
  gridViewBtn.classList.toggle('active', viewMode === 'grid');
  favoritesOnlyBtn.classList.toggle('active', favoritesOnly);

  if (!items.length) {
    const empty = document.createElement('div');
    empty.className = 'no-results';
    empty.textContent = 'Keine passenden Medien.';
    gallery.appendChild(empty);
    return;
  }

  const activeTourName = window.projectUi?.getTourName();
  const projects = activeTourName
    ? [activeTourName]
    : [...new Set(items.map(i => i.project || 'Default'))];
  projects.forEach(project => {
    const groupItems = activeTourName
      ? items
      : items.filter(i => (i.project || 'Default') === project);
    const h = document.createElement('div');
    const name = document.createElement('span');
    const count = document.createElement('small');
    h.className = 'project-heading';
    name.textContent = `📁 ${project}`;
    count.textContent = String(groupItems.length);
    h.append(name, count);
    gallery.appendChild(h);
    groupItems.forEach(item => gallery.appendChild(itemCard(item)));
  });
}

function selectItem(item) {
  selectedItem = item;
  window.hotspotAdmin?.setCurrentItem(item);
  window.mapUi?.setCurrentItem(item);
  window.projectUi?.onMediaSelected(item);
  fillForm(item);
  renderGallery();
  loadViewer(item);
}

function selectMediaById(mediaId) {
  const item = mediaItems.find(candidate => String(candidate.id) === String(mediaId));
  if (!item || !item.visible) return false;
  selectItem(item);
  return true;
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
window.selectMediaById = selectMediaById;
window.reloadMedia = loadMedia;
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
  window.projectUi?.setAdminMode(enabled);
}

document.getElementById('adminToggleBtn').onclick = () => setAdminMode(adminPanel.classList.contains('hidden'));
document.getElementById('closeAdminBtn').onclick = () => setAdminMode(false);
document.getElementById('fullscreenBtn').onclick = () => window.viewerControls?.toggleFullscreen();
document.getElementById('zoomInBtn').onclick = () => window.viewerControls?.zoomIn();
document.getElementById('zoomOutBtn').onclick = () => window.viewerControls?.zoomOut();
document.getElementById('homeBtn').onclick = () => window.viewerControls?.resetView();
document.getElementById('normalModeBtn').onclick = () => window.viewerControls?.setProjectionMode('normal');
document.getElementById('tinyPlanetBtn').onclick = () => window.viewerControls?.toggleTinyPlanet();
document.getElementById('rabbitHoleBtn').onclick = () => window.viewerControls?.toggleRabbitHole();
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
