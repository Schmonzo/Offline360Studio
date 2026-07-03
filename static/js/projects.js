let projectSummaries = [];
let projectMediaItems = [];
let editedProject = null;
let activeTour = null;
let projectRequestPending = false;
let projectsLoaded = false;
let mediaLoaded = false;
let restorationAttempted = false;

const ACTIVE_PROJECT_KEY = 'ps_active_project_id';
const ACTIVE_PROJECT_MEDIA_KEY = 'ps_active_project_media_id';

const tourSelect = document.getElementById('tourSelect');
const tourNavigation = document.getElementById('tourNavigation');
const tourPreviousBtn = document.getElementById('tourPreviousBtn');
const tourNextBtn = document.getElementById('tourNextBtn');
const tourPosition = document.getElementById('tourPosition');
const adminProjectSelect = document.getElementById('adminProjectSelect');
const newProjectBtn = document.getElementById('newProjectBtn');
const projectForm = document.getElementById('projectForm');
const projectName = document.getElementById('projectName');
const projectDescription = document.getElementById('projectDescription');
const saveProjectBtn = document.getElementById('saveProjectBtn');
const deleteProjectBtn = document.getElementById('deleteProjectBtn');
const projectError = document.getElementById('projectError');
const projectMediaEditor = document.getElementById('projectMediaEditor');
const projectMediaSelect = document.getElementById('projectMediaSelect');
const addProjectMediaBtn = document.getElementById('addProjectMediaBtn');
const projectMediaList = document.getElementById('projectMediaList');
const projectCardsSection = document.getElementById('projectCardsSection');
const projectCards = document.getElementById('projectCards');
const projectCoverPreview = document.getElementById('projectCoverPreview');

function storedValue(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storeValue(key, value) {
  try {
    if (value === null || value === undefined || value === '') localStorage.removeItem(key);
    else localStorage.setItem(key, String(value));
  } catch {
    // The application remains usable when browser storage is unavailable.
  }
}

function clearStoredTour() {
  storeValue(ACTIVE_PROJECT_KEY, null);
  storeValue(ACTIVE_PROJECT_MEDIA_KEY, null);
}

function option(value, label) {
  const element = document.createElement('option');
  element.value = String(value);
  element.textContent = label;
  return element;
}

function setProjectError(message = '') {
  projectError.textContent = message;
  projectError.classList.toggle('hidden', !message);
}

function apiMessage(data, fallback) {
  const message = data?.error?.message;
  return typeof message === 'string' && message.trim() ? message : fallback;
}

async function projectRequest(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(apiMessage(data, `Anfrage fehlgeschlagen (HTTP ${response.status}).`));
  }
  return data;
}

function fillSelect(select, firstLabel, selectedValue) {
  select.replaceChildren(option('', firstLabel));
  projectSummaries.forEach(project => {
    select.appendChild(option(project.id, project.name));
  });
  if (projectSummaries.some(project => String(project.id) === String(selectedValue))) {
    select.value = String(selectedValue);
  }
}

function renderProjectSelectors() {
  fillSelect(tourSelect, 'Keine Tour (Galerie)', activeTour?.id);
  fillSelect(adminProjectSelect, 'Projekt auswählen', editedProject?.id);
  renderProjectCards();
  if (typeof updateStats === 'function') updateStats();
}

async function loadProjects() {
  try {
    const data = await projectRequest('/api/projects');
    projectSummaries = data.items || [];
    projectsLoaded = true;
    renderProjectSelectors();
    restoreStoredTour();
    window.mapUi?.onProjectChanged();
  } catch (error) {
    setProjectError(error.message);
  }
}

async function fetchProject(projectId) {
  const data = await projectRequest(`/api/projects/${projectId}`);
  return data.item;
}

function canonicalTourItems() {
  if (!activeTour) return null;
  return activeTour.media.map(projectItem => {
    const current = projectMediaItems.find(item => item.id === projectItem.id);
    return current ? { ...current, sort_order: projectItem.sort_order } : projectItem;
  });
}

function visibleTourItems() {
  return (canonicalTourItems() || []).filter(item => item.visible);
}

function coverPreview(cover, className) {
  if (cover?.type === 'photo' && (cover.thumb_path || cover.file_path)) {
    const image = document.createElement('img');
    image.className = className;
    image.src = `/${cover.thumb_path || cover.file_path}`;
    image.loading = 'lazy';
    image.alt = '';
    return image;
  }
  const placeholder = document.createElement('div');
  placeholder.className = `${className} project-cover-placeholder`;
  placeholder.textContent = cover?.type === 'video' ? 'Video-Cover' : 'Kein Cover';
  return placeholder;
}

function renderProjectCards() {
  projectCards.replaceChildren();
  projectCardsSection.classList.toggle('hidden', projectSummaries.length === 0);
  projectSummaries.forEach(project => {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'project-card';
    card.classList.toggle('active', activeTour?.id === project.id);
    card.setAttribute('aria-pressed', activeTour?.id === project.id ? 'true' : 'false');

    const visual = document.createElement('span');
    visual.className = 'project-card-visual';
    visual.appendChild(coverPreview(project.cover_media, 'project-card-cover'));
    if (project.start_media_id) {
      const startBadge = document.createElement('span');
      startBadge.className = 'project-start-badge';
      startBadge.textContent = 'Startpanorama';
      visual.appendChild(startBadge);
    }

    const body = document.createElement('span');
    body.className = 'project-card-body';
    const name = document.createElement('strong');
    name.className = 'project-card-name';
    name.textContent = project.name;
    const description = document.createElement('span');
    description.className = 'project-card-description';
    description.textContent = project.description || 'Keine Beschreibung';
    const count = document.createElement('span');
    count.className = 'project-card-count';
    count.textContent = `${project.media_count || 0} ${project.media_count === 1 ? 'Medium' : 'Medien'}`;
    body.append(name, description, count);
    card.append(visual, body);
    card.addEventListener('click', () => selectTour(project.id));
    projectCards.appendChild(card);
  });
}

function currentTourIndex() {
  if (!selectedItem || !activeTour) return -1;
  return visibleTourItems().findIndex(item => item.id === selectedItem.id);
}

function updateTourNavigation() {
  const items = visibleTourItems();
  const index = currentTourIndex();
  tourNavigation.classList.toggle('hidden', !activeTour);
  tourPosition.textContent = index >= 0 ? `${index + 1} / ${items.length}` : `– / ${items.length}`;
  tourPreviousBtn.disabled = index <= 0;
  tourNextBtn.disabled = index < 0 || index >= items.length - 1;
}

function openTourItem(index) {
  const items = visibleTourItems();
  if (index < 0 || index >= items.length) return;
  const item = projectMediaItems.find(candidate => candidate.id === items[index].id) || items[index];
  selectItem(item);
}

function moveInTour(offset) {
  const index = currentTourIndex();
  if (index < 0) {
    if (offset > 0) openTourItem(0);
    return;
  }
  openTourItem(index + offset);
}

async function selectTour(projectId, options = {}) {
  if (!projectId) {
    activeTour = null;
    clearStoredTour();
    projectFilter.disabled = false;
    renderProjectSelectors();
    updateTourNavigation();
    renderGallery();
    window.mapUi?.onProjectChanged();
    return;
  }
  try {
    activeTour = await fetchProject(projectId);
    storeValue(ACTIVE_PROJECT_KEY, activeTour.id);
    projectFilter.value = '';
    projectFilter.disabled = true;
    renderProjectSelectors();
    renderGallery();
    window.mapUi?.onProjectChanged();
    const items = visibleTourItems();
    const restoredIndex = options.mediaId
      ? items.findIndex(item => String(item.id) === String(options.mediaId))
      : -1;
    const startIndex = items.findIndex(item => item.id === activeTour.start_media_id);
    if (restoredIndex >= 0) openTourItem(restoredIndex);
    else if (startIndex >= 0) openTourItem(startIndex);
    else if (items.length) openTourItem(0);
    else {
      storeValue(ACTIVE_PROJECT_MEDIA_KEY, null);
      updateTourNavigation();
    }
  } catch (error) {
    activeTour = null;
    if (String(storedValue(ACTIVE_PROJECT_KEY)) === String(projectId)) clearStoredTour();
    tourSelect.value = '';
    projectFilter.disabled = false;
    showNavigationMessage(error.message);
    renderProjectSelectors();
    renderGallery();
    window.mapUi?.onProjectChanged();
  }
}

function restoreStoredTour() {
  if (restorationAttempted || !projectsLoaded || !mediaLoaded) return;
  restorationAttempted = true;
  const projectId = storedValue(ACTIVE_PROJECT_KEY);
  if (!projectId) return;
  const exists = projectSummaries.some(project => String(project.id) === projectId);
  if (!exists) {
    clearStoredTour();
    renderProjectSelectors();
    renderGallery();
    return;
  }
  selectTour(projectId, { mediaId: storedValue(ACTIVE_PROJECT_MEDIA_KEY) });
}

function setProjectPending(pending) {
  projectRequestPending = pending;
  saveProjectBtn.disabled = pending;
  deleteProjectBtn.disabled = pending || !editedProject;
  addProjectMediaBtn.disabled = pending || !editedProject || !projectMediaSelect.value;
  projectMediaList.querySelectorAll('button').forEach(button => {
    button.disabled = pending;
  });
  if (!pending) {
    renderAvailableMedia();
    renderProjectMedia();
  }
}

function renderAvailableMedia() {
  const assigned = new Set((editedProject?.media || []).map(item => item.id));
  projectMediaSelect.replaceChildren(option('', 'Medium auswählen'));
  projectMediaItems
    .filter(item => !assigned.has(item.id))
    .forEach(item => {
      const type = item.type === 'photo' ? 'Foto' : 'Video';
      projectMediaSelect.appendChild(option(item.id, `${item.title || item.file_path} (${type})`));
    });
  addProjectMediaBtn.disabled = projectRequestPending || !editedProject || !projectMediaSelect.value;
}

function projectMediaButton(label, title, action, active = false) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = label;
  button.title = title;
  button.classList.toggle('active', active);
  button.addEventListener('click', action);
  return button;
}

function renderProjectMedia() {
  projectMediaList.replaceChildren();
  if (!editedProject) return;
  editedProject.media.forEach((item, index) => {
    const row = document.createElement('li');
    const label = document.createElement('span');
    label.className = 'project-media-title';
    label.textContent = `${item.title || item.file_path} · ${item.type}`;

    const actions = document.createElement('div');
    actions.className = 'project-media-actions';
    const up = projectMediaButton('↑', 'Nach oben', () => reorderMedia(index, -1));
    const down = projectMediaButton('↓', 'Nach unten', () => reorderMedia(index, 1));
    up.disabled = index === 0;
    down.disabled = index === editedProject.media.length - 1;
    actions.append(up, down);
    actions.appendChild(projectMediaButton(
      'Cover',
      'Als Covermedium festlegen',
      () => setProjectMedium('cover_media_id', item.id),
      editedProject.cover_media_id === item.id
    ));
    if (item.type === 'photo') {
      actions.appendChild(projectMediaButton(
        'Start',
        'Als Startpanorama festlegen',
        () => setProjectMedium('start_media_id', item.id),
        editedProject.start_media_id === item.id
      ));
    }
    actions.appendChild(projectMediaButton(
      'Entfernen',
      'Aus dem Projekt entfernen',
      () => removeProjectMedia(item)
    ));
    row.append(label, actions);
    projectMediaList.appendChild(row);
  });
}

function renderProjectCoverPreview() {
  projectCoverPreview.replaceChildren();
  if (!editedProject) return;
  const cover = editedProject.cover_media
    || editedProject.media.find(item => item.id === editedProject.cover_media_id)
    || null;
  projectCoverPreview.appendChild(coverPreview(cover, 'project-cover-preview-media'));
}

function renderProjectEditor() {
  adminProjectSelect.value = editedProject ? String(editedProject.id) : '';
  projectName.value = editedProject?.name || '';
  projectDescription.value = editedProject?.description || '';
  saveProjectBtn.textContent = editedProject ? 'Änderungen speichern' : 'Projekt anlegen';
  deleteProjectBtn.disabled = projectRequestPending || !editedProject;
  projectMediaEditor.classList.toggle('hidden', !editedProject);
  renderProjectCoverPreview();
  renderAvailableMedia();
  renderProjectMedia();
}

function updateProjectState(project) {
  editedProject = project;
  const coverMedia = project.media.find(item => item.id === project.cover_media_id) || null;
  const summary = {
    id: project.id,
    name: project.name,
    description: project.description,
    cover_media_id: project.cover_media_id,
    cover_media: coverMedia,
    start_media_id: project.start_media_id,
    created_at: project.created_at,
    updated_at: project.updated_at,
    media_count: project.media.length
  };
  const index = projectSummaries.findIndex(item => item.id === project.id);
  if (index >= 0) projectSummaries[index] = summary;
  else projectSummaries.push(summary);
  if (activeTour?.id === project.id) {
    activeTour = project;
    renderGallery();
    updateTourNavigation();
  }
  renderProjectSelectors();
  renderProjectEditor();
  window.mapUi?.onProjectChanged();
}

async function saveProject(event) {
  event.preventDefault();
  setProjectError();
  const name = projectName.value.trim();
  if (!name) {
    setProjectError('Bitte einen Projektnamen eingeben.');
    projectName.focus();
    return;
  }
  setProjectPending(true);
  try {
    const creating = !editedProject;
    const data = await projectRequest(
      creating ? '/api/projects' : `/api/projects/${editedProject.id}`,
      {
        method: creating ? 'POST' : 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          description: projectDescription.value
        })
      }
    );
    updateProjectState(data.item);
  } catch (error) {
    setProjectError(error.message);
  } finally {
    setProjectPending(false);
  }
}

async function deleteProject() {
  if (!editedProject || projectRequestPending) return;
  if (!window.confirm(`Projekt „${editedProject.name}“ wirklich löschen? Die Medien bleiben erhalten.`)) return;
  const projectId = editedProject.id;
  setProjectPending(true);
  setProjectError();
  try {
    await projectRequest(`/api/projects/${projectId}`, { method: 'DELETE' });
    projectSummaries = projectSummaries.filter(item => item.id !== projectId);
    editedProject = null;
    if (String(storedValue(ACTIVE_PROJECT_KEY)) === String(projectId)) clearStoredTour();
    if (activeTour?.id === projectId) {
      activeTour = null;
      projectFilter.disabled = false;
      renderGallery();
      updateTourNavigation();
    }
    renderProjectSelectors();
    renderProjectEditor();
    window.mapUi?.onProjectChanged();
  } catch (error) {
    setProjectError(error.message);
  } finally {
    setProjectPending(false);
  }
}

async function addProjectMedia() {
  const mediaId = Number(projectMediaSelect.value);
  if (!editedProject || !mediaId || projectRequestPending) return;
  setProjectPending(true);
  setProjectError();
  try {
    const data = await projectRequest(`/api/projects/${editedProject.id}/media`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ media_id: mediaId })
    });
    updateProjectState(data.item);
  } catch (error) {
    setProjectError(error.message);
  } finally {
    setProjectPending(false);
  }
}

async function removeProjectMedia(item) {
  if (!editedProject || projectRequestPending) return;
  if (!window.confirm(`„${item.title || item.file_path}“ aus diesem Projekt entfernen?`)) return;
  setProjectPending(true);
  setProjectError();
  try {
    const data = await projectRequest(
      `/api/projects/${editedProject.id}/media/${item.id}`,
      { method: 'DELETE' }
    );
    updateProjectState(data.item);
  } catch (error) {
    setProjectError(error.message);
  } finally {
    setProjectPending(false);
  }
}

async function reorderMedia(index, offset) {
  if (!editedProject || projectRequestPending) return;
  const target = index + offset;
  if (target < 0 || target >= editedProject.media.length) return;
  const mediaIds = editedProject.media.map(item => item.id);
  [mediaIds[index], mediaIds[target]] = [mediaIds[target], mediaIds[index]];
  setProjectPending(true);
  setProjectError();
  try {
    const data = await projectRequest(`/api/projects/${editedProject.id}/media/order`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ media_ids: mediaIds })
    });
    updateProjectState(data.item);
  } catch (error) {
    setProjectError(error.message);
  } finally {
    setProjectPending(false);
  }
}

async function setProjectMedium(field, mediaId) {
  if (!editedProject || projectRequestPending) return;
  const value = editedProject[field] === mediaId ? null : mediaId;
  setProjectPending(true);
  setProjectError();
  try {
    const data = await projectRequest(`/api/projects/${editedProject.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [field]: value })
    });
    updateProjectState(data.item);
  } catch (error) {
    setProjectError(error.message);
  } finally {
    setProjectPending(false);
  }
}

tourSelect.addEventListener('change', () => selectTour(tourSelect.value));
tourPreviousBtn.addEventListener('click', () => moveInTour(-1));
tourNextBtn.addEventListener('click', () => moveInTour(1));
newProjectBtn.addEventListener('click', () => {
  editedProject = null;
  setProjectError();
  renderProjectEditor();
  projectName.focus();
});
adminProjectSelect.addEventListener('change', async () => {
  setProjectError();
  if (!adminProjectSelect.value) {
    editedProject = null;
    renderProjectEditor();
    return;
  }
  try {
    editedProject = await fetchProject(adminProjectSelect.value);
    renderProjectEditor();
  } catch (error) {
    setProjectError(error.message);
  }
});
projectForm.addEventListener('submit', saveProject);
deleteProjectBtn.addEventListener('click', deleteProject);
projectMediaSelect.addEventListener('change', () => {
  addProjectMediaBtn.disabled = projectRequestPending || !editedProject || !projectMediaSelect.value;
});
addProjectMediaBtn.addEventListener('click', addProjectMedia);
document.addEventListener('keydown', event => {
  if (!activeTour || !['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
  const tag = String(document.activeElement?.tagName || '').toLowerCase();
  if (['input', 'textarea', 'select'].includes(tag) || document.querySelector('dialog[open]')) return;
  event.preventDefault();
  moveInTour(event.key === 'ArrowLeft' ? -1 : 1);
});

window.projectUi = {
  setMediaItems(items) {
    projectMediaItems = Array.isArray(items) ? items : [];
    mediaLoaded = true;
    renderAvailableMedia();
    renderProjectCards();
    restoreStoredTour();
  },
  setAdminMode() {
    setProjectError();
  },
  getTourItems: canonicalTourItems,
  getTourName() {
    return activeTour?.name || '';
  },
  getActiveProjectId() {
    return activeTour?.id || null;
  },
  isTourActive() {
    return !!activeTour;
  },
  getProjectCount() {
    return projectSummaries.length;
  },
  onMediaSelected(item) {
    if (activeTour && visibleTourItems().some(candidate => candidate.id === item?.id)) {
      storeValue(ACTIVE_PROJECT_MEDIA_KEY, item.id);
    }
    updateTourNavigation();
  }
};

renderProjectEditor();
updateTourNavigation();
loadProjects();
