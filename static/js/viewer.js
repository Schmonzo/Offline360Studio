// Panorama Studio v0.3.1
// Robust viewer lifecycle for switching between multiple panoramas without refresh.

let panoramaViewer = null;
let currentScene = null;
let currentView = null;
let currentItem = null;
let autorotateTimer = null;

const DEFAULT_VIEW = {
  yaw: 0,
  pitch: 0,
  fov: Math.PI / 2
};

const MIN_FOV = 25 * Math.PI / 180;   // stark hineinzoomen
const MAX_FOV = 165 * Math.PI / 180;  // weit herauszoomen
const ZOOM_STEP = 0.82;

function viewerElement() {
  return document.getElementById('viewer');
}

function setZoomLabel() {
  const label = document.getElementById('zoomLabel');
  if (!label) return;

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

function destroyCurrentScene() {
  stopAutorotate();

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
  panoramaViewer = null;

  const el = viewerElement();
  if (el) el.replaceChildren();

  setZoomLabel();
}

function showError(message) {
  const el = viewerElement();
  if (!el) return;
  el.innerHTML = `
    <div class="empty-state">
      <h2>Fehler</h2>
      <p>${message}</p>
    </div>
  `;
}

function showPhoto(item) {
  destroyCurrentScene();
  currentItem = item;

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

  currentView = new Marzipano.RectilinearView({ ...DEFAULT_VIEW }, limiter);

  currentScene = panoramaViewer.createScene({
    source,
    geometry,
    view: currentView
  });

  currentView.addEventListener?.('change', setZoomLabel);
  currentScene.switchTo({ transitionDuration: 250 });
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

  el.innerHTML = `<video class="video-player" src="/${videoPath}" controls autoplay loop playsinline></video>`;
}

function loadViewer(item) {
  if (!item) return;

  const title = document.getElementById('currentTitle');
  const meta = document.getElementById('currentMeta');

  if (title) title.textContent = item.title || item.file_path || 'Unbenannt';
  if (meta) meta.textContent = `${item.project || 'Default'}${item.category ? ' / ' + item.category : ''} · ${item.type}`;

  if (item.type === 'photo') showPhoto(item);
  else if (item.type === 'video') showVideo(item);
  else showError('Unbekannter Medientyp: ' + (item.type || 'leer'));
}

function zoomTo(fov) {
  if (!currentView) return;
  currentView.setFov(Math.max(MIN_FOV, Math.min(MAX_FOV, fov)));
  setZoomLabel();
}

function zoomIn() {
  if (!currentView) return;
  zoomTo(currentView.fov() * ZOOM_STEP);
}

function zoomOut() {
  if (!currentView) return;
  zoomTo(currentView.fov() / ZOOM_STEP);
}

function resetView() {
  if (!currentView) return;
  currentView.setParameters({ ...DEFAULT_VIEW });
  setZoomLabel();
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
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen?.();
  } else {
    document.exitFullscreen?.();
  }
}

window.viewerControls = {
  zoomIn,
  zoomOut,
  resetView,
  toggleCinematic,
  toggleFullscreen
};

window.loadViewer = loadViewer;

document.addEventListener('keydown', (event) => {
  const tag = String(document.activeElement?.tagName || '').toLowerCase();
  if (['input', 'textarea', 'select'].includes(tag)) return;

  if (event.key === '+' || event.key === '=') zoomIn();
  if (event.key === '-' || event.key === '_') zoomOut();
  if (event.key.toLowerCase() === 'h' || event.key === 'Home') resetView();
  if (event.key.toLowerCase() === 'f') toggleFullscreen();
  if (event.key.toLowerCase() === 'c') toggleCinematic();
});
