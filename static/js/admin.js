let hotspotAdminEnabled = false;
let hotspotAdminCurrentItem = null;
let hotspotAdminMediaItems = [];
let editedHotspot = null;
let hotspotRequestPending = false;
let startViewRequestPending = false;

const addHotspotBtn = document.getElementById('addHotspotBtn');
const startViewControls = document.getElementById('startViewControls');
const saveStartViewBtn = document.getElementById('saveStartViewBtn');
const resetStartViewBtn = document.getElementById('resetStartViewBtn');
const hotspotEditorDialog = document.getElementById('hotspotEditorDialog');
const hotspotEditorForm = document.getElementById('hotspotEditorForm');
const hotspotEditorTitle = document.getElementById('hotspotEditorTitle');
const hotspotType = document.getElementById('hotspotType');
const hotspotTitle = document.getElementById('hotspotTitle');
const hotspotInfoText = document.getElementById('hotspotInfoTextInput');
const hotspotTarget = document.getElementById('hotspotTarget');
const hotspotVisible = document.getElementById('hotspotVisible');
const hotspotYaw = document.getElementById('hotspotYaw');
const hotspotPitch = document.getElementById('hotspotPitch');
const hotspotEditorError = document.getElementById('hotspotEditorError');
const saveHotspotBtn = document.getElementById('saveHotspotBtn');
const cancelHotspotBtn = document.getElementById('cancelHotspotBtn');
const deleteHotspotBtn = document.getElementById('deleteHotspotBtn');

function setHotspotEditorError(message = '') {
  hotspotEditorError.textContent = message;
  hotspotEditorError.classList.toggle('hidden', !message);
}

function apiErrorMessage(data, fallback) {
  const message = data?.error?.message;
  return typeof message === 'string' && message.trim() ? message : fallback;
}

function setHotspotPositionStatus(message) {
  const statusBox = document.getElementById('statusBox');
  if (statusBox) statusBox.textContent = `Status: ${message}`;
}

function hasSavedStartView(item) {
  return [item?.start_yaw, item?.start_pitch, item?.start_fov].every(Number.isFinite);
}

function updateStartViewControls() {
  const isPhoto = hotspotAdminCurrentItem?.type === 'photo';
  startViewControls.classList.toggle('hidden', !isPhoto);
  saveStartViewBtn.disabled = !isPhoto || startViewRequestPending;
  resetStartViewBtn.disabled = !isPhoto || startViewRequestPending || !hasSavedStartView(hotspotAdminCurrentItem);
}

function setStartViewStatus(message) {
  const statusBox = document.getElementById('statusBox');
  if (statusBox) statusBox.textContent = `Status: ${message}`;
}

function applyStartViewResult(item) {
  const mediaItem = hotspotAdminMediaItems.find(
    candidate => String(candidate.id) === String(item.id)
  );
  if (mediaItem) Object.assign(mediaItem, item);
  if (String(hotspotAdminCurrentItem?.id) === String(item.id)) {
    Object.assign(hotspotAdminCurrentItem, item);
    window.viewerControls?.setCurrentStartView(item);
  }
  updateStartViewControls();
}

async function saveStartView() {
  if (startViewRequestPending || hotspotAdminCurrentItem?.type !== 'photo') return;
  const view = window.viewerControls?.getViewParameters();
  if (!view) {
    setStartViewStatus('Das Panorama ist noch nicht bereit.');
    return;
  }

  startViewRequestPending = true;
  updateStartViewControls();
  try {
    const response = await fetch(`/api/media/${hotspotAdminCurrentItem.id}/start-view`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(view)
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(apiErrorMessage(
        data,
        `Startansicht konnte nicht gespeichert werden (HTTP ${response.status}).`
      ));
    }
    applyStartViewResult(data.item);
    setStartViewStatus('Startansicht gespeichert.');
  } catch (error) {
    setStartViewStatus(`Fehler beim Speichern der Startansicht: ${error.message || 'Unbekannter Fehler.'}`);
  } finally {
    startViewRequestPending = false;
    updateStartViewControls();
  }
}

async function resetStartView() {
  if (startViewRequestPending || hotspotAdminCurrentItem?.type !== 'photo') return;
  startViewRequestPending = true;
  updateStartViewControls();
  try {
    const response = await fetch(`/api/media/${hotspotAdminCurrentItem.id}/start-view`, {
      method: 'DELETE'
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(apiErrorMessage(
        data,
        `Startansicht konnte nicht zurückgesetzt werden (HTTP ${response.status}).`
      ));
    }
    applyStartViewResult(data.item);
    setStartViewStatus('Startansicht zurückgesetzt; es gelten wieder die Standardwerte.');
  } catch (error) {
    setStartViewStatus(`Fehler beim Zurücksetzen der Startansicht: ${error.message || 'Unbekannter Fehler.'}`);
  } finally {
    startViewRequestPending = false;
    updateStartViewControls();
  }
}

async function saveHotspotPosition(hotspot, position) {
  try {
    const response = await fetch(`/api/hotspots/${hotspot.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        yaw: position.yaw,
        pitch: position.pitch
      })
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(apiErrorMessage(
        data,
        `Position konnte nicht gespeichert werden (HTTP ${response.status}).`
      ));
    }
    setHotspotPositionStatus('Hotspot-Position gespeichert.');
    return data?.item;
  } catch (error) {
    setHotspotPositionStatus(
      `Fehler beim Speichern der Hotspot-Position: ${error.message || 'Unbekannter Fehler.'}`
    );
    throw error;
  }
}

function updateHotspotTargetState() {
  const isPanorama = hotspotType.value === 'panorama';
  hotspotTarget.disabled = !isPanorama;
  hotspotTarget.required = isPanorama;
  if (!isPanorama) hotspotTarget.value = '';
}

function populateHotspotTargets(selectedId = null) {
  hotspotTarget.replaceChildren();

  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = 'Zielpanorama wählen';
  hotspotTarget.appendChild(placeholder);

  hotspotAdminMediaItems
    .filter(item => item.visible && item.type === 'photo')
    .filter(item => String(item.id) !== String(hotspotAdminCurrentItem?.id))
    .sort((a, b) => String(a.title || a.file_path || '').localeCompare(
      String(b.title || b.file_path || ''),
      'de'
    ))
    .forEach(item => {
      const option = document.createElement('option');
      option.value = String(item.id);
      option.textContent = item.title || item.file_path || `Panorama ${item.id}`;
      hotspotTarget.appendChild(option);
    });

  if (selectedId !== null && selectedId !== undefined) {
    hotspotTarget.value = String(selectedId);
  }
}

function setHotspotRequestPending(pending) {
  hotspotRequestPending = pending;
  saveHotspotBtn.disabled = pending;
  cancelHotspotBtn.disabled = pending;
  deleteHotspotBtn.disabled = pending;
  hotspotEditorForm.querySelectorAll('input, textarea, select').forEach(field => {
    field.disabled = pending || (field === hotspotTarget && hotspotType.value !== 'panorama');
  });
  hotspotYaw.readOnly = true;
  hotspotPitch.readOnly = true;
}

function closeHotspotEditor() {
  if (hotspotRequestPending) return;
  if (hotspotEditorDialog.open && typeof hotspotEditorDialog.close === 'function') {
    hotspotEditorDialog.close();
  } else {
    hotspotEditorDialog.removeAttribute('open');
  }
  editedHotspot = null;
  setHotspotEditorError();
}

function showHotspotEditor(hotspot) {
  if (!hotspotAdminEnabled || hotspotAdminCurrentItem?.type !== 'photo') return;

  editedHotspot = hotspot.id ? hotspot : null;
  hotspotEditorTitle.textContent = editedHotspot ? 'Hotspot bearbeiten' : 'Hotspot anlegen';
  hotspotType.value = hotspot.action_type || 'panorama';
  hotspotTitle.value = hotspot.title || '';
  hotspotInfoText.value = hotspot.info_text || '';
  hotspotVisible.checked = hotspot.visible === undefined ? true : !!hotspot.visible;
  hotspotYaw.value = Number(hotspot.yaw).toFixed(6);
  hotspotPitch.value = Number(hotspot.pitch).toFixed(6);
  populateHotspotTargets(hotspot.target_media_id);
  updateHotspotTargetState();
  deleteHotspotBtn.classList.toggle('hidden', !editedHotspot);
  setHotspotEditorError();
  setHotspotRequestPending(false);

  if (typeof hotspotEditorDialog.showModal === 'function') {
    if (!hotspotEditorDialog.open) hotspotEditorDialog.showModal();
  } else {
    hotspotEditorDialog.setAttribute('open', '');
  }
  hotspotType.focus();
}

function beginHotspotPlacement() {
  if (!hotspotAdminEnabled || hotspotAdminCurrentItem?.type !== 'photo') return;
  closeHotspotEditor();
  const started = window.viewerControls?.beginHotspotPlacement(coordinates => {
    showHotspotEditor({
      action_type: 'panorama',
      yaw: coordinates.yaw,
      pitch: coordinates.pitch,
      title: '',
      info_text: '',
      target_media_id: null,
      visible: true
    });
  });
  if (!started) {
    document.getElementById('statusBox').textContent = 'Status: Das Panorama ist noch nicht bereit.';
  }
}

function hotspotPayload() {
  return {
    action_type: hotspotType.value,
    yaw: Number(hotspotYaw.value),
    pitch: Number(hotspotPitch.value),
    title: hotspotTitle.value,
    info_text: hotspotInfoText.value,
    target_media_id: hotspotType.value === 'panorama' ? Number(hotspotTarget.value) : null,
    visible: hotspotVisible.checked
  };
}

async function saveHotspot(event) {
  event.preventDefault();
  setHotspotEditorError();

  if (hotspotType.value === 'panorama' && !hotspotTarget.value) {
    setHotspotEditorError('Bitte ein Zielpanorama auswählen.');
    hotspotTarget.focus();
    return;
  }

  const url = editedHotspot
    ? `/api/hotspots/${editedHotspot.id}`
    : `/api/media/${hotspotAdminCurrentItem.id}/hotspots`;
  const method = editedHotspot ? 'PATCH' : 'POST';

  setHotspotRequestPending(true);
  try {
    const response = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(hotspotPayload())
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(apiErrorMessage(data, `Speichern fehlgeschlagen (HTTP ${response.status}).`));
    }
    setHotspotRequestPending(false);
    closeHotspotEditor();
    window.viewerControls?.reloadCurrentHotspots();
  } catch (error) {
    setHotspotEditorError(error.message || 'Der Hotspot konnte nicht gespeichert werden.');
    setHotspotRequestPending(false);
  }
}

async function deleteHotspot() {
  if (!editedHotspot || hotspotRequestPending) return;
  if (!window.confirm('Diesen Hotspot wirklich löschen?')) return;

  setHotspotEditorError();
  setHotspotRequestPending(true);
  try {
    const response = await fetch(`/api/hotspots/${editedHotspot.id}`, {
      method: 'DELETE'
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(apiErrorMessage(data, `Löschen fehlgeschlagen (HTTP ${response.status}).`));
    }
    setHotspotRequestPending(false);
    closeHotspotEditor();
    window.viewerControls?.reloadCurrentHotspots();
  } catch (error) {
    setHotspotEditorError(error.message || 'Der Hotspot konnte nicht gelöscht werden.');
    setHotspotRequestPending(false);
  }
}

function setHotspotAdminEnabled(enabled) {
  hotspotAdminEnabled = !!enabled;
  window.viewerControls?.setHotspotAdminMode(hotspotAdminEnabled);
  if (!hotspotAdminEnabled) {
    window.viewerControls?.cancelHotspotPlacement();
    closeHotspotEditor();
  }
}

function setCurrentItem(item) {
  const changed = String(hotspotAdminCurrentItem?.id ?? '') !== String(item?.id ?? '');
  hotspotAdminCurrentItem = item || null;
  addHotspotBtn.classList.toggle('hidden', hotspotAdminCurrentItem?.type !== 'photo');
  addHotspotBtn.disabled = hotspotAdminCurrentItem?.type !== 'photo';
  updateStartViewControls();
  if (changed) {
    window.viewerControls?.cancelHotspotPlacement();
    closeHotspotEditor();
  }
}

function setMediaItems(items) {
  hotspotAdminMediaItems = Array.isArray(items) ? items : [];
}

addHotspotBtn.addEventListener('click', beginHotspotPlacement);
saveStartViewBtn.addEventListener('click', saveStartView);
resetStartViewBtn.addEventListener('click', resetStartView);
hotspotType.addEventListener('change', updateHotspotTargetState);
hotspotEditorForm.addEventListener('submit', saveHotspot);
cancelHotspotBtn.addEventListener('click', closeHotspotEditor);
deleteHotspotBtn.addEventListener('click', deleteHotspot);
hotspotEditorDialog.addEventListener('cancel', event => {
  event.preventDefault();
  closeHotspotEditor();
});
document.addEventListener('hotspotplacementchange', event => {
  const active = !!event.detail?.active;
  addHotspotBtn.classList.toggle('active', active);
  addHotspotBtn.setAttribute('aria-pressed', String(active));
  addHotspotBtn.textContent = active
    ? 'Position im Panorama wählen (Esc zum Abbrechen)'
    : 'Hotspot hinzufügen';
});

window.viewerControls?.setHotspotEditCallback(showHotspotEditor);
window.viewerControls?.setHotspotPositionSaveCallback(saveHotspotPosition);
window.hotspotAdmin = {
  setAdminMode: setHotspotAdminEnabled,
  setCurrentItem,
  setMediaItems
};

async function loadSystemDiagnostics() {
  const status = document.getElementById('diagnosticsStatus');
  const container = document.getElementById('diagnosticsData');
  if (!status || !container) return;
  try {
    const response = await fetch('/api/diagnostics', { cache: 'no-store' });
    const report = await response.json();
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const values = [
      ['Version', report.OFFLINE360_STUDIO_version],
      ['Python', report.python_version],
      ['Betriebssystem', report.operating_system],
      ['Datenbank', report.paths.database],
      ['Medien', report.paths.media],
      ['Log', report.paths.log],
      ['Freier Speicher', `${(report.free_disk_bytes / (1024 ** 3)).toFixed(1)} GiB`],
      ['Projekte', report.counts.projects],
      ['Medienanzahl', report.counts.media],
      ['Hotspots', report.counts.hotspots],
      ['GPX-Tracks', report.counts.gpx_tracks],
      ['MBTiles-Quellen', report.counts.mbtiles_sources],
      ['Daten beschreibbar', report.writable.data ? 'Ja' : 'Nein'],
      ['Medien beschreibbar', report.writable.media ? 'Ja' : 'Nein'],
      ['Portable Server', report.portable_server.present ? 'Vorhanden' : 'Fehlt'],
      ['Server SHA-256', report.portable_server.sha256_valid ? 'Gültig' : 'Ungültig'],
      ['Letztes Backup', report.last_backup_at || 'Nicht ermittelbar']
    ];
    container.replaceChildren();
    for (const [label, value] of values) {
      const term = document.createElement('dt');
      const detail = document.createElement('dd');
      term.textContent = String(label);
      detail.textContent = String(value);
      container.append(term, detail);
    }
    status.textContent = 'Diagnose aktuell.';
  } catch (error) {
    status.textContent = `Diagnose nicht verfügbar: ${error.message || 'Unbekannter Fehler'}`;
  }
}

loadSystemDiagnostics();

