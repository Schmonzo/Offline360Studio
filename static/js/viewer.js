// Panorama Studio v0.3.1
// Robust viewer lifecycle for switching between multiple panoramas without refresh.

let panoramaViewer = null;
let currentScene = null;
let currentView = null;
let currentItem = null;
let currentVideoViewer = null;
let autorotateTimer = null;
let currentHotspotContainer = null;
let currentHotspots = [];
let sceneGeneration = 0;
let panoramaNavigationCallback = null;
let hotspotEditCallback = null;
let hotspotPositionSaveCallback = null;
let hotspotAdminMode = false;
let hotspotPlacementCallback = null;
let hotspotDrag = null;

const HOTSPOT_DRAG_THRESHOLD = 5;

const DEFAULT_VIEW = {
  yaw: 0,
  pitch: 0,
  fov: Math.PI / 2
};
let currentStartView = { ...DEFAULT_VIEW };

const MIN_FOV = 25 * Math.PI / 180;   // stark hineinzoomen
const MAX_FOV = 165 * Math.PI / 180;  // weit herauszoomen
const ZOOM_STEP = 0.82;

function viewerElement() {
  return document.getElementById('viewer');
}

function startViewForItem(item) {
  const startView = {
    yaw: item?.start_yaw,
    pitch: item?.start_pitch,
    fov: item?.start_fov
  };
  return Object.values(startView).every(Number.isFinite)
    ? startView
    : { ...DEFAULT_VIEW };
}

function setZoomLabel() {
  const label = document.getElementById('zoomLabel');
  if (!label) return;

  if (currentVideoViewer) {
    label.textContent = currentVideoViewer.getZoomPercent() + '%';
    return;
  }

  if (!currentView) {
    label.textContent = '0%';
    return;
  }

  const fov = currentView.fov();
  const percent = Math.round(((MAX_FOV - fov) / (MAX_FOV - MIN_FOV)) * 100);
  label.textContent = Math.max(0, Math.min(100, percent)) + '%';
}

function stopAutorotate() {
  if (autorotateTimer) {
    clearInterval(autorotateTimer);
    autorotateTimer = null;
  }
  document.getElementById('cinematicBtn')?.classList.remove('active');
}

function clearCurrentHotspots() {
  cancelHotspotDrag();
  if (currentHotspotContainer) {
    currentHotspots.forEach(hotspot => {
      try {
        currentHotspotContainer.destroyHotspot(hotspot);
      } catch (error) {
        console.warn('Hotspot cleanup warning:', error);
      }
    });
  }
  currentHotspots = [];
  currentHotspotContainer = null;
}

function setHotspotPlacementState(active) {
  viewerElement()?.classList.toggle('hotspot-placement-active', active);
  document.dispatchEvent(new CustomEvent('hotspotplacementchange', {
    detail: { active }
  }));
}

function cancelHotspotPlacement() {
  if (!hotspotPlacementCallback) return;
  hotspotPlacementCallback = null;
  setHotspotPlacementState(false);
}

function hotspotCoordinatesAt(clientX, clientY) {
  const el = viewerElement();
  if (!el || !currentView) return null;
  const bounds = el.getBoundingClientRect();
  return currentView.screenToCoordinates({
    x: clientX - bounds.left,
    y: clientY - bounds.top
  });
}

function finishHotspotDrag() {
  if (!hotspotDrag) return null;
  const drag = hotspotDrag;
  hotspotDrag = null;
  drag.marker.classList.remove('hotspot-marker--dragging');
  try {
    if (drag.marker.hasPointerCapture?.(drag.pointerId)) {
      drag.marker.releasePointerCapture(drag.pointerId);
    }
  } catch (error) {
    console.warn('Hotspot pointer cleanup warning:', error);
  }
  return drag;
}

function cancelHotspotDrag() {
  const drag = finishHotspotDrag();
  if (!drag) return;
  if (drag.moved) {
    drag.instance.setPosition(drag.originalPosition);
    drag.marker.dataset.suppressClick = 'true';
  }
}

function bindHotspotDragging(marker, hotspot, instance) {
  marker.addEventListener('pointerdown', event => {
    if (
      !hotspotAdminMode ||
      hotspotPlacementCallback ||
      hotspotDrag ||
      marker.classList.contains('hotspot-marker--saving') ||
      event.button !== 0 ||
      !event.isPrimary
    ) {
      return;
    }

    stopAutorotate();
    hotspotDrag = {
      pointerId: event.pointerId,
      marker,
      hotspot,
      instance,
      startX: event.clientX,
      startY: event.clientY,
      originalPosition: { yaw: hotspot.yaw, pitch: hotspot.pitch },
      position: { yaw: hotspot.yaw, pitch: hotspot.pitch },
      moved: false
    };
    marker.setPointerCapture?.(event.pointerId);
  });
}

function moveHotspotDrag(event) {
  const drag = hotspotDrag;
  if (!drag || event.pointerId !== drag.pointerId) return;

  if (!drag.moved) {
    const distance = Math.hypot(
      event.clientX - drag.startX,
      event.clientY - drag.startY
    );
    if (distance < HOTSPOT_DRAG_THRESHOLD) return;
    drag.moved = true;
    drag.marker.classList.add('hotspot-marker--dragging');
  }

  const position = hotspotCoordinatesAt(event.clientX, event.clientY);
  if (!position) return;
  event.preventDefault();
  event.stopPropagation();
  drag.position = position;
  drag.instance.setPosition(position);
}

async function saveHotspotDrag(event) {
  const drag = hotspotDrag;
  if (!drag || event.pointerId !== drag.pointerId) return;
  const completedDrag = finishHotspotDrag();
  if (!completedDrag?.moved) return;

  event.preventDefault();
  event.stopPropagation();
  completedDrag.marker.dataset.suppressClick = 'true';
  completedDrag.marker.classList.add('hotspot-marker--saving');

  try {
    if (typeof hotspotPositionSaveCallback !== 'function') {
      throw new Error('Die Hotspot-Position kann derzeit nicht gespeichert werden.');
    }
    const updated = await hotspotPositionSaveCallback(
      completedDrag.hotspot,
      completedDrag.position
    );
    completedDrag.hotspot.yaw = updated?.yaw ?? completedDrag.position.yaw;
    completedDrag.hotspot.pitch = updated?.pitch ?? completedDrag.position.pitch;
  } catch (error) {
    completedDrag.instance.setPosition(completedDrag.originalPosition);
    console.warn('Hotspot-Position konnte nicht gespeichert werden:', error);
  } finally {
    completedDrag.marker.classList.remove('hotspot-marker--saving');
  }
}

function destroyCurrentScene() {
  stopAutorotate();
  cancelHotspotPlacement();
  sceneGeneration += 1;

  clearCurrentHotspots();

  try {
    currentVideoViewer?.destroy();
  } catch (error) {
    console.warn('360°-Video cleanup warning:', error);
  }
  currentVideoViewer = null;

  // Marzipano keeps renderer/canvas state internally. For reliable image switching,
  // reset the scene AND the viewer instance, then rebuild the DOM container.
  try {
    if (currentScene && typeof currentScene.destroy === 'function') {
      currentScene.destroy();
    }
  } catch (error) {
    console.warn('Scene cleanup warning:', error);
  }

  currentScene = null;
  currentView = null;
  currentItem = null;
  currentStartView = { ...DEFAULT_VIEW };
  panoramaViewer = null;

  const el = viewerElement();
  if (el) el.replaceChildren();

  setZoomLabel();
}

function openInfoDialog(title, text) {
  const dialog = document.getElementById('hotspotInfoDialog');
  const titleElement = document.getElementById('hotspotInfoTitle');
  const textElement = document.getElementById('hotspotInfoText');
  if (!dialog || !titleElement || !textElement) return;

  titleElement.textContent = title || 'Information';
  textElement.textContent = text || 'Für diesen Hotspot sind keine weiteren Informationen hinterlegt.';

  if (typeof dialog.showModal === 'function') {
    if (!dialog.open) dialog.showModal();
  } else {
    dialog.setAttribute('open', '');
  }
  document.getElementById('closeHotspotInfoBtn')?.focus();
}

function closeInfoDialog() {
  const dialog = document.getElementById('hotspotInfoDialog');
  if (!dialog) return;
  if (typeof dialog.close === 'function' && dialog.open) dialog.close();
  else dialog.removeAttribute('open');
}

function createHotspotElement(hotspot) {
  const marker = document.createElement('button');
  const title = hotspot.title || (hotspot.action_type === 'panorama' ? 'Panorama öffnen' : 'Information öffnen');
  marker.type = 'button';
  marker.className = `hotspot-marker hotspot-marker--${hotspot.action_type}`;
  marker.classList.toggle('hotspot-marker--hidden', !hotspot.visible);
  marker.setAttribute('aria-label', title);

  const icon = document.createElement('span');
  icon.className = 'hotspot-marker__icon';
  icon.setAttribute('aria-hidden', 'true');
  icon.textContent = hotspot.action_type === 'panorama' ? '→' : 'i';

  const label = document.createElement('span');
  label.className = 'hotspot-marker__label';
  label.textContent = title;
  marker.append(icon, label);

  ['pointerdown', 'mousedown', 'touchstart'].forEach(eventName => {
    marker.addEventListener(eventName, event => event.stopPropagation());
  });
  marker.addEventListener('click', event => {
    event.preventDefault();
    event.stopPropagation();
    if (marker.dataset.suppressClick === 'true') {
      delete marker.dataset.suppressClick;
      return;
    }
    if (hotspotAdminMode && typeof hotspotEditCallback === 'function') {
      hotspotEditCallback(hotspot);
      return;
    }
    if (hotspot.action_type === 'panorama') {
      if (typeof panoramaNavigationCallback === 'function') {
        panoramaNavigationCallback(hotspot.target_media_id);
      }
    } else {
      openInfoDialog(hotspot.title, hotspot.info_text);
    }
  });

  return marker;
}

async function loadHotspots(mediaId, scene, generation) {
  try {
    const response = await fetch(`/api/media/${mediaId}/hotspots`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();

    if (generation !== sceneGeneration || scene !== currentScene) return;

    currentHotspotContainer = scene.hotspotContainer();
    (data.items || [])
      .filter(hotspot => (hotspot.visible || hotspotAdminMode) && ['panorama', 'info'].includes(hotspot.action_type))
      .filter(hotspot => Number.isFinite(hotspot.yaw) && Number.isFinite(hotspot.pitch))
      .forEach(hotspot => {
        const element = createHotspotElement(hotspot);
        const instance = currentHotspotContainer.createHotspot(element, {
          yaw: hotspot.yaw,
          pitch: hotspot.pitch
        });
        bindHotspotDragging(element, hotspot, instance);
        currentHotspots.push(instance);
      });
  } catch (error) {
    if (generation === sceneGeneration && scene === currentScene) {
      console.warn('Hotspots konnten nicht geladen werden:', error);
    }
  }
}

function reloadCurrentHotspots() {
  if (!currentScene || !currentItem || currentItem.type !== 'photo') return;
  sceneGeneration += 1;
  const generation = sceneGeneration;
  clearCurrentHotspots();
  loadHotspots(currentItem.id, currentScene, generation);
}

function showError(message) {
  const el = viewerElement();
  if (!el) return;
  const emptyState = document.createElement('div');
  const heading = document.createElement('h2');
  const text = document.createElement('p');
  emptyState.className = 'empty-state';
  heading.textContent = 'Fehler';
  text.textContent = message;
  emptyState.append(heading, text);
  el.replaceChildren(emptyState);
}

function showPhoto(item) {
  destroyCurrentScene();
  currentItem = item;
  currentStartView = startViewForItem(item);
  const generation = sceneGeneration;

  const el = viewerElement();
  if (!el) return;

  if (typeof Marzipano === 'undefined') {
    showError('Marzipano wurde nicht geladen. Bitte static/lib/marzipano.js prüfen.');
    return;
  }

  const imagePath = item.file_path || item.file;
  if (!imagePath) {
    showError('Dieses Foto hat keinen Dateipfad.');
    return;
  }

  panoramaViewer = new Marzipano.Viewer(el);

  const source = Marzipano.ImageUrlSource.fromString('/' + imagePath);
  const geometry = new Marzipano.EquirectGeometry([{ width: 4096 }]);

  // Weiter FOV-Limiter: erlaubt deutliches Herauszoomen.
  const limiter = Marzipano.RectilinearView.limit.traditional(
    8192,
    MAX_FOV,
    MAX_FOV
  );

  currentView = new Marzipano.RectilinearView({ ...currentStartView }, limiter);

  currentScene = panoramaViewer.createScene({
    source,
    geometry,
    view: currentView
  });

  currentView.addEventListener?.('change', setZoomLabel);
  currentScene.switchTo({ transitionDuration: 250 });
  loadHotspots(item.id, currentScene, generation);
  setZoomLabel();
}

function showVideo(item) {
  destroyCurrentScene();
  currentItem = item;

  const el = viewerElement();
  if (!el) return;

  const videoPath = item.file_path || item.file;
  if (!videoPath) {
    showError('Dieses Video hat keinen Dateipfad.');
    return;
  }

  if (typeof Video360Viewer === 'undefined') {
    showError('Der lokale 360°-Video-Renderer wurde nicht geladen.');
    return;
  }

  currentVideoViewer = new Video360Viewer(el, '/' + videoPath, {
    fullscreenElement: el.closest('.stage') || el,
    onViewChange: setZoomLabel
  });
  setZoomLabel();
}

function loadViewer(item) {
  if (!item) return;

  const title = document.getElementById('currentTitle');
  const meta = document.getElementById('currentMeta');

  if (title) title.textContent = item.title || item.file_path || 'Unbenannt';
  if (meta) meta.textContent = `${item.project || 'Default'}${item.category ? ' / ' + item.category : ''} · ${item.type}`;

  if (item.type === 'photo') showPhoto(item);
  else if (item.type === 'video') showVideo(item);
  else {
    destroyCurrentScene();
    showError('Unbekannter Medientyp: ' + (item.type || 'leer'));
  }
}

function zoomTo(fov) {
  if (!currentView) return;
  currentView.setFov(Math.max(MIN_FOV, Math.min(MAX_FOV, fov)));
  setZoomLabel();
}

function zoomIn() {
  if (currentVideoViewer) {
    currentVideoViewer.zoomIn();
    return;
  }
  if (!currentView) return;
  zoomTo(currentView.fov() * ZOOM_STEP);
}

function zoomOut() {
  if (currentVideoViewer) {
    currentVideoViewer.zoomOut();
    return;
  }
  if (!currentView) return;
  zoomTo(currentView.fov() / ZOOM_STEP);
}

function resetView() {
  if (currentVideoViewer) {
    currentVideoViewer.resetView();
    return;
  }
  if (!currentView) return;
  currentView.setParameters({ ...currentStartView });
  setZoomLabel();
}

function getViewParameters() {
  if (!currentView || currentItem?.type !== 'photo') return null;
  return {
    yaw: currentView.yaw(),
    pitch: currentView.pitch(),
    fov: currentView.fov()
  };
}

function setCurrentStartView(item) {
  if (
    !currentItem ||
    currentItem.type !== 'photo' ||
    String(currentItem.id) !== String(item?.id)
  ) {
    return false;
  }
  Object.assign(currentItem, item);
  currentStartView = startViewForItem(currentItem);
  return true;
}

function toggleCinematic() {
  if (!currentView) return;

  if (autorotateTimer) {
    stopAutorotate();
    return;
  }

  document.getElementById('cinematicBtn')?.classList.add('active');
  autorotateTimer = setInterval(() => {
    if (!currentView) {
      stopAutorotate();
      return;
    }
    currentView.offsetYaw(0.0025);
  }, 16);
}

function toggleFullscreen() {
  if (currentVideoViewer) {
    currentVideoViewer.toggleFullscreen();
    return;
  }
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen?.();
  } else {
    document.exitFullscreen?.();
  }
}

function setPanoramaNavigationCallback(callback) {
  panoramaNavigationCallback = typeof callback === 'function' ? callback : null;
}

function setHotspotEditCallback(callback) {
  hotspotEditCallback = typeof callback === 'function' ? callback : null;
}

function setHotspotPositionSaveCallback(callback) {
  hotspotPositionSaveCallback = typeof callback === 'function' ? callback : null;
}

function setHotspotAdminMode(enabled) {
  const nextValue = !!enabled;
  if (hotspotAdminMode === nextValue) return;
  hotspotAdminMode = nextValue;
  if (!hotspotAdminMode) {
    cancelHotspotPlacement();
    cancelHotspotDrag();
  }
  reloadCurrentHotspots();
}

function beginHotspotPlacement(callback) {
  if (
    !hotspotAdminMode ||
    !currentView ||
    !currentItem ||
    currentItem.type !== 'photo' ||
    typeof callback !== 'function'
  ) {
    return false;
  }

  stopAutorotate();
  hotspotPlacementCallback = callback;
  setHotspotPlacementState(true);
  return true;
}

window.viewerControls = {
  zoomIn,
  zoomOut,
  resetView,
  getViewParameters,
  setCurrentStartView,
  toggleCinematic,
  toggleFullscreen,
  openInfoDialog,
  closeInfoDialog,
  setPanoramaNavigationCallback,
  setHotspotEditCallback,
  setHotspotPositionSaveCallback,
  setHotspotAdminMode,
  beginHotspotPlacement,
  cancelHotspotPlacement,
  reloadCurrentHotspots
};

window.loadViewer = loadViewer;

document.getElementById('closeHotspotInfoBtn')?.addEventListener('click', closeInfoDialog);
document.addEventListener('pointermove', moveHotspotDrag);
document.addEventListener('pointerup', saveHotspotDrag);
document.addEventListener('pointercancel', cancelHotspotDrag);

viewerElement()?.addEventListener('click', event => {
  if (!hotspotPlacementCallback || !currentView) return;
  if (event.target.closest('button, input, select, textarea, dialog, .hotspot-marker')) return;

  const bounds = viewerElement().getBoundingClientRect();
  const coordinates = currentView.screenToCoordinates({
    x: event.clientX - bounds.left,
    y: event.clientY - bounds.top
  });
  const callback = hotspotPlacementCallback;
  hotspotPlacementCallback = null;
  setHotspotPlacementState(false);
  callback(coordinates);
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && hotspotDrag) {
    event.preventDefault();
    cancelHotspotDrag();
    return;
  }

  if (event.key === 'Escape' && hotspotPlacementCallback) {
    event.preventDefault();
    cancelHotspotPlacement();
    return;
  }

  if (document.getElementById('hotspotInfoDialog')?.open) {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeInfoDialog();
    }
    return;
  }

  const tag = String(document.activeElement?.tagName || '').toLowerCase();
  if (['input', 'textarea', 'select'].includes(tag)) return;

  if (currentVideoViewer) {
    if (tag === 'button') return;
    if (event.code === 'Space') {
      event.preventDefault();
      currentVideoViewer.togglePlay();
      return;
    }
    const directions = {
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
      ArrowUp: [0, 1],
      ArrowDown: [0, -1]
    };
    if (directions[event.key]) {
      event.preventDefault();
      currentVideoViewer.lookBy(...directions[event.key]);
      return;
    }
  }

  if (event.key === '+' || event.key === '=') zoomIn();
  if (event.key === '-' || event.key === '_') zoomOut();
  if (event.key.toLowerCase() === 'h' || event.key === 'Home') resetView();
  if (event.key.toLowerCase() === 'f') toggleFullscreen();
  if (event.key.toLowerCase() === 'c') toggleCinematic();
});
