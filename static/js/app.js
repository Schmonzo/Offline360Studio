let mediaItems = [];
let selectedItem = null;
let stats = null;
let favoritesOnly = false;
let viewMode = localStorage.getItem('ps_view_mode') || 'list';

const gallery = document.getElementById('gallery');
const statusBox = document.getElementById('statusBox');
const searchInput = document.getElementById('searchInput');
const adminPanel = document.getElementById('adminPanel');
const stageElement = document.querySelector('.stage');
const viewerRootElement = document.getElementById('viewer');
const mapViewElement = document.getElementById('mapView');
const mapControlsElement = document.getElementById('mapControls');
const editForm = document.getElementById('editForm');
const projectFilter = document.getElementById('projectFilter');
const categoryFilter = document.getElementById('categoryFilter');
const typeFilter = document.getElementById('typeFilter');
const favoritesOnlyBtn = document.getElementById('favoritesOnlyBtn');
const listViewBtn = document.getElementById('listViewBtn');
const gridViewBtn = document.getElementById('gridViewBtn');

const uiState = {
  mapViewActive: false,
  adminOpen: false
};

const ADMIN_SECTION_STORAGE_KEY = 'ps_admin_section';
const DEFAULT_ADMIN_SECTION = 'media';
const adminSectionTabs = [...document.querySelectorAll('[data-admin-section]')];
const adminSectionPanels = [...document.querySelectorAll('[data-admin-panel]')];
const adminNavigationElement = document.querySelector('.admin-navigation');
const compactAdminNavigation = window.matchMedia('(max-width: 720px)');

function updateAdminNavigationOrientation() {
  adminNavigationElement?.setAttribute(
    'aria-orientation',
    compactAdminNavigation.matches ? 'horizontal' : 'vertical'
  );
}
compactAdminNavigation.addEventListener?.('change', updateAdminNavigationOrientation);
updateAdminNavigationOrientation();

function readStoredAdminSection() {
  try {
    const storedSection = localStorage.getItem(ADMIN_SECTION_STORAGE_KEY);
    return adminSectionTabs.some(tab => tab.dataset.adminSection === storedSection)
      ? storedSection
      : DEFAULT_ADMIN_SECTION;
  } catch (error) {
    return DEFAULT_ADMIN_SECTION;
  }
}

function setAdminSection(section, { focus = false } = {}) {
  const activeSection = adminSectionTabs.some(tab => tab.dataset.adminSection === section)
    ? section
    : DEFAULT_ADMIN_SECTION;

  adminSectionTabs.forEach(tab => {
    const selected = tab.dataset.adminSection === activeSection;
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
    if (selected && focus) tab.focus();
  });
  adminSectionPanels.forEach(panel => {
    panel.hidden = panel.dataset.adminPanel !== activeSection;
  });

  try {
    localStorage.setItem(ADMIN_SECTION_STORAGE_KEY, activeSection);
  } catch (error) {
    // Navigation remains usable when storage is unavailable.
  }
  return activeSection;
}

function moveAdminTabFocus(currentTab, offset) {
  const currentIndex = adminSectionTabs.indexOf(currentTab);
  const nextIndex = (currentIndex + offset + adminSectionTabs.length) % adminSectionTabs.length;
  setAdminSection(adminSectionTabs[nextIndex].dataset.adminSection, { focus: true });
}

adminSectionTabs.forEach(tab => {
  tab.addEventListener('click', () => setAdminSection(tab.dataset.adminSection));
  tab.addEventListener('keydown', event => {
    if (['ArrowRight', 'ArrowDown'].includes(event.key)) {
      event.preventDefault();
      moveAdminTabFocus(tab, 1);
    } else if (['ArrowLeft', 'ArrowUp'].includes(event.key)) {
      event.preventDefault();
      moveAdminTabFocus(tab, -1);
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      const targetIndex = event.key === 'Home' ? 0 : adminSectionTabs.length - 1;
      setAdminSection(adminSectionTabs[targetIndex].dataset.adminSection, { focus: true });
    }
  });
});
setAdminSection(readStoredAdminSection());

window.adminNavigation = {
  activate: setAdminSection,
  getActive() {
    return adminSectionTabs.find(tab => tab.getAttribute('aria-selected') === 'true')
      ?.dataset.adminSection || DEFAULT_ADMIN_SECTION;
  },
  focusActive() {
    adminSectionTabs.find(tab => tab.getAttribute('aria-selected') === 'true')?.focus();
  }
};

function applyUiState() {
  const mapControlsVisible = uiState.mapViewActive && !uiState.adminOpen;
  viewerRootElement?.classList.toggle('hidden', uiState.mapViewActive);
  mapViewElement?.classList.toggle('hidden', !uiState.mapViewActive);
  adminPanel?.classList.toggle('hidden', !uiState.adminOpen);
  stageElement?.classList.toggle('map-mode', uiState.mapViewActive);
  stageElement?.classList.toggle('admin-open', uiState.adminOpen);
  mapControlsElement?.classList.toggle('map-controls--hidden', !mapControlsVisible);
  mapControlsElement?.setAttribute('aria-hidden', String(!mapControlsVisible));
  if (mapControlsElement) mapControlsElement.inert = !mapControlsVisible;
}

window.appUiState = {
  setMapViewActive(active) {
    uiState.mapViewActive = Boolean(active);
    applyUiState();
  },
  setAdminOpen(open) {
    uiState.adminOpen = Boolean(open);
    applyUiState();
  },
  getSnapshot() {
    return { ...uiState };
  }
};
applyUiState();

function setStatus(message) { statusBox.textContent = 'Status: ' + message; }
function mediaUrl(path) { return '/' + path; }

async function loadAppVersion() {
  const versionElement = document.getElementById('appVersion');
  const adminVersionElement = document.getElementById('adminAppVersion');
  if (!versionElement && !adminVersionElement) return;
  try {
    const response = await fetch('/api/version', { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    if (typeof payload.version !== 'string' || !payload.version.trim()) {
      throw new Error('Ungültige Versionsantwort');
    }
    if (versionElement) versionElement.textContent = `v${payload.version}`;
    if (adminVersionElement) adminVersionElement.textContent = `v${payload.version}`;
  } catch (error) {
    if (versionElement) versionElement.textContent = 'Version unbekannt';
    if (adminVersionElement) adminVersionElement.textContent = 'Version unbekannt';
    console.warn('App-Version konnte nicht geladen werden:', error);
  }
}

function callOptionalUi(apiName, methodName, ...args) {
  try {
    const result = window[apiName]?.[methodName]?.(...args);
    result?.catch?.(error => {
      console.warn(`${apiName}.${methodName} wurde asynchron abgebrochen:`, error);
    });
  } catch (error) {
    console.warn(`${apiName}.${methodName} konnte nicht ausgeführt werden:`, error);
  }
}

async function loadMedia() {
  const res = await fetch('/api/media');
  const data = await res.json();
  mediaItems = data.items || [];
  stats = data.stats || null;
  updateStats();
  updateFilters();
  renderGallery();
  callOptionalUi('hotspotAdmin', 'setMediaItems', mediaItems);
  callOptionalUi('projectUi', 'setMediaItems', mediaItems);
  callOptionalUi('mapUi', 'setMediaItems', mediaItems);
  if (selectedItem) {
    selectedItem = mediaItems.find(item => item.id === selectedItem.id) || null;
    callOptionalUi('hotspotAdmin', 'setCurrentItem', selectedItem);
    callOptionalUi('mapUi', 'setCurrentItem', selectedItem);
  }
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
  callOptionalUi('hotspotAdmin', 'setCurrentItem', item);
  callOptionalUi('mapUi', 'setCurrentItem', item);
  callOptionalUi('projectUi', 'onMediaSelected', item);
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
    const status = document.getElementById('viewerMessage');
    if (!status) return;
    status.textContent = message;
    status.classList.remove('hidden');
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
callOptionalUi('viewerControls', 'setPanoramaNavigationCallback', openMediaById);

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
  try {
    const res = await fetch('/api/rescan', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error?.message || 'Neu einlesen fehlgeschlagen.');
    setStatus(`Scan fertig. Gefunden: ${data.found}, neu: ${data.inserted}, aktualisiert: ${data.updated}`);
    await loadMedia();
  } catch (error) {
    setStatus(error.message || 'Neu einlesen fehlgeschlagen.');
  }
}

async function uploadFiles(files) {
  const selectedFiles = [...files];
  renderUploadPreview(selectedFiles);
  if (!selectedFiles.length) return;
  setStatus('Upload laeuft...');
  try {
    const form = new FormData();
    selectedFiles.forEach(file => form.append('files', file));
    form.append('project', document.getElementById('uploadProject').value || 'Default');
    const res = await fetch('/api/upload', { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error?.message || 'Upload fehlgeschlagen.');
    setStatus(`Upload fertig. Gespeichert: ${data.saved}, gefunden: ${data.found}`);
    fileInput.value = '';
    renderUploadPreview([]);
    await loadMedia();
  } catch (error) {
    setStatus(error.message || 'Upload fehlgeschlagen.');
  }
}

function formatFileSize(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

document.getElementById('rescanBtn').onclick = rescan;
function setAdminMode(enabled) {
  window.appUiState.setAdminOpen(enabled);
  callOptionalUi('hotspotAdmin', 'setAdminMode', enabled);
  callOptionalUi('projectUi', 'setAdminMode', enabled);
  if (enabled) {
    window.requestAnimationFrame(() => window.adminNavigation.focusActive());
  }
}

document.getElementById('adminToggleBtn').onclick = () => setAdminMode(adminPanel.classList.contains('hidden'));
document.getElementById('closeAdminBtn').onclick = () => {
  setAdminMode(false);
  document.getElementById('adminToggleBtn').focus();
};
adminPanel.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  event.stopPropagation();
  setAdminMode(false);
  document.getElementById('adminToggleBtn').focus();
});
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
const uploadFilePreview = document.getElementById('uploadFilePreview');
function renderUploadPreview(files) {
  if (!uploadFilePreview) return;
  uploadFilePreview.replaceChildren();
  uploadFilePreview.classList.toggle('hidden', files.length === 0);
  files.forEach(file => {
    const item = document.createElement('li');
    const name = document.createElement('span');
    const meta = document.createElement('small');
    name.textContent = file.name;
    meta.textContent = formatFileSize(file.size);
    item.append(name, meta);
    uploadFilePreview.appendChild(item);
  });
}
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

loadAppVersion();
loadMedia();

