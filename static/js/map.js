(() => {
  'use strict';

  const mapView = document.getElementById('mapView');
  const mapCanvas = document.getElementById('mapCanvas');
  const emptyState = document.getElementById('mapEmptyState');
  const modeButton = document.getElementById('stageModeBtn');
  const stage = document.querySelector('.stage');
  const viewer = document.getElementById('viewer');
  const projectFilter = document.getElementById('projectFilter');
  const gpsForm = document.getElementById('gpsForm');
  const gpsStatus = document.getElementById('gpsStatus');
  const gpxStatus = document.getElementById('gpxStatus');
  const trackList = document.getElementById('gpxTrackList');
  const gpxProject = document.getElementById('gpxProject');

  let map = null;
  let markerLayer = null;
  let trackLayer = null;
  let selectedItem = null;
  let mapMode = false;
  let mapMedia = [];
  let tracks = [];
  const projectNames = new Map();
  const markers = new Map();
  const visibleTrackIds = new Set();

  function setStatus(element, message, isError = false) {
    element.textContent = message;
    element.classList.toggle('inline-status--error', isError);
  }

  async function jsonRequest(url, options) {
    const response = await fetch(url, options);
    let data = {};
    try {
      data = await response.json();
    } catch (_error) {
      // The status below remains actionable even for an invalid server response.
    }
    if (!response.ok) {
      throw new Error(data.error?.message || `Anfrage fehlgeschlagen (${response.status}).`);
    }
    return data;
  }

  function activeProjectId() {
    return window.projectUi?.getActiveProjectId?.() || null;
  }

  function apiUrl(path) {
    const projectId = activeProjectId();
    if (!projectId) return path;
    const separator = path.includes('?') ? '&' : '?';
    return `${path}${separator}project_id=${encodeURIComponent(projectId)}`;
  }

  function ensureMap() {
    if (map || typeof L === 'undefined') return;
    map = L.map(mapCanvas, {
      zoomControl: true,
      attributionControl: false,
      minZoom: 1
    });
    markerLayer = L.featureGroup().addTo(map);
    trackLayer = L.featureGroup().addTo(map);
    map.setView([20, 0], 2);
  }

  function markerIcon(active) {
    return L.divIcon({
      className: `media-map-marker${active ? ' media-map-marker--active' : ''}`,
      html: '<span aria-hidden="true"></span>',
      iconSize: active ? [24, 24] : [18, 18],
      iconAnchor: active ? [12, 12] : [9, 9]
    });
  }

  function renderMarkers() {
    ensureMap();
    if (!map) return;
    markerLayer.clearLayers();
    markers.clear();
    const legacyProject = projectFilter?.disabled ? '' : projectFilter?.value;
    const filtered = mapMedia.filter(
      item => !legacyProject || (item.project || 'Default') === legacyProject
    );
    filtered.forEach(item => {
      const active = selectedItem?.id === item.id;
      const marker = L.marker([item.latitude, item.longitude], {
        icon: markerIcon(active),
        keyboard: true,
        title: item.title || 'Medium öffnen',
        alt: item.title || 'Medium öffnen',
        zIndexOffset: active ? 1000 : 0
      });
      marker.on('click', () => {
        if (window.selectMediaById?.(item.id)) setMapMode(false);
      });
      marker.addTo(markerLayer);
      markers.set(item.id, marker);
    });
    emptyState.classList.toggle('hidden', filtered.length > 0);
  }

  function trackColor(index) {
    const styles = getComputedStyle(document.documentElement);
    const names = ['--map-track-a', '--map-track-b', '--map-track-c', '--map-track-d'];
    return styles.getPropertyValue(names[index % names.length]).trim()
      || styles.getPropertyValue('--accent').trim();
  }

  async function renderTracks() {
    ensureMap();
    if (!map) return;
    trackLayer.clearLayers();
    const legacyProject = projectFilter?.disabled ? '' : projectFilter?.value;
    const displayed = tracks.filter(track => {
      if (!visibleTrackIds.has(track.id)) return false;
      if (!legacyProject) return true;
      return (
        track.project_id === null
        || projectNames.get(String(track.project_id)) === legacyProject
      );
    });
    const results = await Promise.allSettled(
      displayed.map(track => jsonRequest(`/api/gpx/tracks/${track.id}`))
    );
    results.forEach((result, index) => {
      if (result.status !== 'fulfilled') return;
      const points = result.value.item?.points || [];
      if (!points.length) return;
      L.polyline(
        points.map(point => [point.latitude, point.longitude]),
        { color: trackColor(index), weight: 4, opacity: 0.88 }
      ).addTo(trackLayer);
    });
  }

  function fitContent() {
    if (!map) return;
    const layers = [...markerLayer.getLayers(), ...trackLayer.getLayers()];
    if (!layers.length) {
      map.setView([20, 0], 2);
      return;
    }
    const group = L.featureGroup(layers);
    const bounds = group.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds.pad(0.15), { maxZoom: 16 });
  }

  function createButton(label, className, handler) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    if (className) button.className = className;
    button.addEventListener('click', handler);
    return button;
  }

  function renderTrackList() {
    trackList.replaceChildren();
    if (!tracks.length) {
      const empty = document.createElement('p');
      empty.textContent = 'Noch keine GPX-Tracks importiert.';
      trackList.appendChild(empty);
      return;
    }
    tracks.forEach(track => {
      const row = document.createElement('div');
      row.className = 'gpx-track';
      const header = document.createElement('label');
      const checkbox = document.createElement('input');
      const name = document.createElement('span');
      checkbox.type = 'checkbox';
      checkbox.checked = visibleTrackIds.has(track.id);
      checkbox.setAttribute('aria-label', `Track ${track.name} auf der Karte anzeigen`);
      checkbox.addEventListener('change', async () => {
        if (checkbox.checked) visibleTrackIds.add(track.id);
        else visibleTrackIds.delete(track.id);
        await renderTracks();
        if (mapMode) fitContent();
      });
      const assignment = track.project_id === null
        ? 'ohne Projekt'
        : (projectNames.get(String(track.project_id)) || `Projekt ${track.project_id}`);
      name.textContent = `${track.name} (${track.point_count} Punkte · ${assignment})`;
      header.append(checkbox, name);
      const actions = document.createElement('div');
      actions.className = 'gpx-track-actions';
      actions.append(
        createButton('Zeit zuordnen', '', () => matchTrack(track)),
        createButton('Löschen', 'danger', () => deleteTrack(track))
      );
      row.append(header, actions);
      trackList.appendChild(row);
    });
  }

  async function loadTracks() {
    try {
      const data = await jsonRequest(apiUrl('/api/gpx/tracks'));
      const previousIds = new Set(tracks.map(track => track.id));
      tracks = data.items || [];
      tracks.forEach(track => {
        if (!previousIds.has(track.id)) visibleTrackIds.add(track.id);
      });
      for (const id of [...visibleTrackIds]) {
        if (!tracks.some(track => track.id === id)) visibleTrackIds.delete(id);
      }
      renderTrackList();
      await renderTracks();
    } catch (error) {
      setStatus(gpxStatus, error.message, true);
    }
  }

  async function refreshMap() {
    try {
      const data = await jsonRequest(apiUrl('/api/map/media'));
      mapMedia = data.items || [];
      renderMarkers();
      await loadTracks();
      if (mapMode) {
        map.invalidateSize();
        fitContent();
      }
    } catch (error) {
      setStatus(gpxStatus, error.message, true);
    }
  }

  async function loadProjects() {
    try {
      const data = await jsonRequest('/api/projects');
      const old = gpxProject.value;
      projectNames.clear();
      gpxProject.replaceChildren();
      const none = document.createElement('option');
      none.value = '';
      none.textContent = 'Kein Projekt';
      gpxProject.appendChild(none);
      (data.items || []).forEach(project => {
        projectNames.set(String(project.id), project.name);
        const option = document.createElement('option');
        option.value = String(project.id);
        option.textContent = project.name;
        gpxProject.appendChild(option);
      });
      if ([...gpxProject.options].some(option => option.value === old)) {
        gpxProject.value = old;
      }
      renderTrackList();
    } catch (error) {
      setStatus(gpxStatus, error.message, true);
    }
  }

  function setMapMode(enabled) {
    mapMode = enabled;
    viewer.classList.toggle('hidden', enabled);
    mapView.classList.toggle('hidden', !enabled);
    stage.classList.toggle('map-mode', enabled);
    modeButton.textContent = enabled ? 'Viewer' : 'Karte';
    modeButton.setAttribute('aria-pressed', String(enabled));
    if (enabled) {
      ensureMap();
      refreshMap();
      requestAnimationFrame(() => {
        map?.invalidateSize();
        fitContent();
      });
    }
  }

  function fillGps(item) {
    selectedItem = item || null;
    document.getElementById('gpsLatitude').value = item?.latitude ?? '';
    document.getElementById('gpsLongitude').value = item?.longitude ?? '';
    document.getElementById('gpsAltitude').value = item?.altitude ?? '';
    document.getElementById('gpsSource').textContent = item?.gps_source || '–';
    [...gpsForm.elements].forEach(element => {
      element.disabled = !item;
    });
    setStatus(gpsStatus, item ? 'Bereit.' : 'Kein Medium gewählt.');
    renderMarkers();
  }

  gpsForm.addEventListener('submit', async event => {
    event.preventDefault();
    if (!selectedItem) return;
    const altitude = document.getElementById('gpsAltitude').value.trim();
    const payload = {
      latitude: Number(document.getElementById('gpsLatitude').value),
      longitude: Number(document.getElementById('gpsLongitude').value),
      altitude: altitude === '' ? null : Number(altitude),
      gps_source: 'manual'
    };
    try {
      await jsonRequest(`/api/media/${selectedItem.id}/gps`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      setStatus(gpsStatus, 'Position gespeichert.');
      await window.reloadMedia?.();
      await refreshMap();
    } catch (error) {
      setStatus(gpsStatus, error.message, true);
    }
  });

  document.getElementById('deleteGpsBtn').addEventListener('click', async () => {
    if (!selectedItem) return;
    try {
      await jsonRequest(`/api/media/${selectedItem.id}/gps`, { method: 'DELETE' });
      setStatus(gpsStatus, 'Position gelöscht.');
      await window.reloadMedia?.();
      await refreshMap();
    } catch (error) {
      setStatus(gpsStatus, error.message, true);
    }
  });

  document.getElementById('gpxImportForm').addEventListener('submit', async event => {
    event.preventDefault();
    const file = document.getElementById('gpxFile').files[0];
    if (!file) return;
    const body = new FormData();
    body.append('file', file);
    body.append('project_id', gpxProject.value);
    setStatus(gpxStatus, 'GPX wird importiert …');
    try {
      const data = await jsonRequest('/api/gpx/import', { method: 'POST', body });
      document.getElementById('gpxFile').value = '';
      setStatus(gpxStatus, `${data.item.name}: ${data.item.point_count} Punkte importiert.`);
      await loadTracks();
      if (mapMode) fitContent();
    } catch (error) {
      setStatus(gpxStatus, error.message, true);
    }
  });

  async function deleteTrack(track) {
    try {
      await jsonRequest(`/api/gpx/tracks/${track.id}`, { method: 'DELETE' });
      setStatus(gpxStatus, `${track.name} wurde gelöscht.`);
      await loadTracks();
      if (mapMode) fitContent();
    } catch (error) {
      setStatus(gpxStatus, error.message, true);
    }
  }

  async function matchTrack(track) {
    const difference = Number(document.getElementById('gpxMatchDifference').value);
    setStatus(gpxStatus, `${track.name}: Medien werden zugeordnet …`);
    try {
      const data = await jsonRequest(`/api/gpx/tracks/${track.id}/match-media`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          max_time_difference_seconds: difference,
          project_id: track.project_id
        })
      });
      setStatus(
        gpxStatus,
        `${data.matched} zugeordnet, ${data.skipped} übersprungen, ${data.unmatched} ohne Treffer.`
      );
      await window.reloadMedia?.();
      await refreshMap();
    } catch (error) {
      setStatus(gpxStatus, error.message, true);
    }
  }

  modeButton.addEventListener('click', () => setMapMode(!mapMode));
  projectFilter?.addEventListener('change', async () => {
    renderMarkers();
    await renderTracks();
    if (mapMode) fitContent();
  });

  window.mapUi = {
    setMediaItems() {
      refreshMap();
    },
    setCurrentItem: fillGps,
    onProjectChanged() {
      loadProjects();
      refreshMap();
    },
    refresh: refreshMap
  };

  fillGps(null);
  loadProjects();
})();
