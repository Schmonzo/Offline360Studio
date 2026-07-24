(() => {
  'use strict';

  const mapCanvas = document.getElementById('mapCanvas');
  const emptyState = document.getElementById('mapEmptyState');
  const tileStatus = document.getElementById('mapTileStatus');
  const attribution = document.getElementById('mapAttribution');
  const modeButton = document.getElementById('stageModeBtn');
  const projectFilter = document.getElementById('projectFilter');
  const gpsForm = document.getElementById('gpsForm');
  const gpsStatus = document.getElementById('gpsStatus');
  const gpxStatus = document.getElementById('gpxStatus');
  const trackList = document.getElementById('gpxTrackList');
  const gpxProject = document.getElementById('gpxProject');
  const mapTrackList = document.getElementById('mapTrackList');
  const showAllMapTracksBtn = document.getElementById('showAllMapTracksBtn');
  const hideAllMapTracksBtn = document.getElementById('hideAllMapTracksBtn');

  const requiredMountIds = [
    'mapCanvas', 'mapEmptyState', 'mapTileStatus', 'mapAttribution',
    'stageModeBtn', 'gpsForm', 'gpsStatus', 'gpxStatus', 'gpxTrackList',
    'gpxProject', 'mapTrackList', 'showAllMapTracksBtn', 'hideAllMapTracksBtn',
    'gpsLatitude', 'gpsLongitude', 'gpsAltitude', 'gpsSource', 'deleteGpsBtn',
    'gpxImportForm', 'gpxFile', 'gpxMatchDifference'
  ];
  if (requiredMountIds.some(id => !document.getElementById(id))) {
    console.warn('Kartenmodul wurde wegen fehlender DOM-Elemente nicht initialisiert.');
    return;
  }

  const MEDIA_SOURCE = 'panorama-media';
  const MEDIA_LAYER = 'panorama-media-circles';
  const TRACK_SOURCE = 'panorama-gpx';
  const TRACK_LAYER = 'panorama-gpx-lines';
  const HIDDEN_TRACKS_STORAGE_KEY = 'ps_hidden_gpx_track_ids';
  const MAP_VIEW_STORAGE_KEY = 'ps_main_map_view';
  const DEFAULT_MAP_VIEW = { center: [0, 20], zoom: 2 };

  let map = null;
  let rendererType = null;
  let activeSourceId = null;
  let markerLayer = null;
  let trackLayer = null;
  let baseLayer = null;
  let selectedItem = null;
  let mapMode = false;
  let mapMedia = [];
  let tracks = [];
  let trackFeatures = [];
  let rendererGeneration = 0;
  const storedMapView = loadStoredMapView();
  let lastView = storedMapView || { ...DEFAULT_MAP_VIEW };
  let hasStoredMapView = Boolean(storedMapView);
  const projectNames = new Map();
  const visibleTrackIds = new Set();
  const hiddenTrackIds = loadHiddenTrackIds();

  function validMapView(view) {
    return (
      view
      && Array.isArray(view.center)
      && view.center.length === 2
      && Number.isFinite(view.center[0])
      && Number.isFinite(view.center[1])
      && view.center[0] >= -180
      && view.center[0] <= 180
      && view.center[1] >= -90
      && view.center[1] <= 90
      && Number.isFinite(view.zoom)
      && view.zoom >= 0
      && view.zoom <= 30
    );
  }

  function loadStoredMapView() {
    try {
      const stored = JSON.parse(sessionStorage.getItem(MAP_VIEW_STORAGE_KEY) || 'null');
      return validMapView(stored) ? stored : null;
    } catch (_error) {
      return null;
    }
  }

  function storeMapView(view) {
    if (!validMapView(view)) return;
    hasStoredMapView = true;
    try {
      sessionStorage.setItem(MAP_VIEW_STORAGE_KEY, JSON.stringify(view));
    } catch (_error) {
      // The in-memory view still preserves state for this app session.
    }
  }

  function loadHiddenTrackIds() {
    try {
      const stored = JSON.parse(localStorage.getItem(HIDDEN_TRACKS_STORAGE_KEY) || '[]');
      if (!Array.isArray(stored)) return new Set();
      return new Set(stored.filter(id => Number.isInteger(id) && id > 0));
    } catch (_error) {
      return new Set();
    }
  }

  function storeTrackVisibility() {
    const validIds = new Set(tracks.map(track => track.id));
    for (const id of [...hiddenTrackIds]) {
      if (!validIds.has(id)) hiddenTrackIds.delete(id);
    }
    try {
      localStorage.setItem(
        HIDDEN_TRACKS_STORAGE_KEY,
        JSON.stringify([...hiddenTrackIds].sort((a, b) => a - b))
      );
    } catch (_error) {
      // Track controls remain usable when browser storage is unavailable.
    }
  }

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

  function rememberView() {
    if (!map) return;
    try {
      const center = map.getCenter();
      lastView = {
        center: [center.lng, center.lat],
        zoom: map.getZoom()
      };
      storeMapView(lastView);
    } catch (_error) {
      // A renderer can be removed while its style is still loading.
    }
  }

  function installViewPersistence() {
    if (!map) return;
    map.on('moveend', rememberView);
    map.on('zoomend', rememberView);
  }

  function destroyRenderer() {
    rendererGeneration += 1;
    rememberView();
    if (map) map.remove();
    map = null;
    rendererType = null;
    activeSourceId = null;
    markerLayer = null;
    trackLayer = null;
    baseLayer = null;
    mapCanvas.replaceChildren();
    mapCanvas.className = 'map-canvas';
    mapCanvas.removeAttribute('style');
  }

  function createLeafletRenderer() {
    if (typeof L === 'undefined') {
      throw new Error('Leaflet ist lokal nicht verfÃ¼gbar.');
    }
    rendererType = 'raster';
    map = L.map(mapCanvas, {
      zoomControl: true,
      attributionControl: false,
      minZoom: 1
    });
    markerLayer = L.featureGroup().addTo(map);
    trackLayer = L.featureGroup().addTo(map);
    map.setView([lastView.center[1], lastView.center[0]], lastView.zoom);
    installViewPersistence();
  }

  function mapLibreGeoJson(features) {
    return { type: 'FeatureCollection', features };
  }

  function absoluteSameOriginUrl(url) {
    if (typeof url !== 'string' || !url) return url;
    let resolved;
    try {
      resolved = new URL(url, window.location.origin);
    } catch (_error) {
      return url;
    }
    if (resolved.origin !== window.location.origin) return url;
    return resolved.href.replace(/%7B([^{}%/]+)%7D/gi, '{$1}');
  }

  function normalizeMapLibreStyle(style) {
    if (!style || typeof style !== 'object' || Array.isArray(style)) {
      throw new Error('Der Offline-Kartenstil ist ungÃ¼ltig.');
    }
    Object.values(style.sources || {}).forEach(source => {
      if (!source || typeof source !== 'object') return;
      if (typeof source.url === 'string') {
        source.url = absoluteSameOriginUrl(source.url);
      }
      if (Array.isArray(source.tiles)) {
        source.tiles = source.tiles.map(absoluteSameOriginUrl);
      }
    });
    if (typeof style.sprite === 'string') {
      style.sprite = absoluteSameOriginUrl(style.sprite);
    } else if (Array.isArray(style.sprite)) {
      style.sprite.forEach(sprite => {
        if (sprite && typeof sprite.url === 'string') {
          sprite.url = absoluteSameOriginUrl(sprite.url);
        }
      });
    }
    if (typeof style.glyphs === 'string') {
      style.glyphs = absoluteSameOriginUrl(style.glyphs);
    }
    return style;
  }

  function mapLibreTransformRequest(url) {
    return { url: absoluteSameOriginUrl(url) };
  }

  function installMapLibreOverlays() {
    if (rendererType !== 'vector' || !map?.isStyleLoaded()) return;
    if (!map.getSource(TRACK_SOURCE)) {
      map.addSource(TRACK_SOURCE, {
        type: 'geojson',
        data: mapLibreGeoJson(trackFeatures)
      });
      map.addLayer({
        id: TRACK_LAYER,
        type: 'line',
        source: TRACK_SOURCE,
        paint: {
          'line-color': ['get', 'color'],
          'line-width': 4,
          'line-opacity': 0.88
        }
      });
    }
    if (!map.getSource(MEDIA_SOURCE)) {
      map.addSource(MEDIA_SOURCE, {
        type: 'geojson',
        data: mapLibreGeoJson([])
      });
      map.addLayer({
        id: MEDIA_LAYER,
        type: 'circle',
        source: MEDIA_SOURCE,
        paint: {
          'circle-color': '#ff7a18',
          'circle-radius': ['case', ['get', 'active'], 11, 7],
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': ['case', ['get', 'active'], 4, 2]
        }
      });
      map.on('click', MEDIA_LAYER, event => {
        const id = Number(event.features?.[0]?.properties?.id);
        if (Number.isInteger(id)) openMapMedia(id);
      });
      map.on('mouseenter', MEDIA_LAYER, () => {
        map.getCanvas().style.cursor = 'pointer';
      });
      map.on('mouseleave', MEDIA_LAYER, () => {
        map.getCanvas().style.cursor = '';
      });
    }
  }

  async function createMapLibreRenderer(source) {
    if (typeof maplibregl === 'undefined') {
      throw new Error('MapLibre GL JS ist lokal nicht verfÃ¼gbar.');
    }
    rendererType = 'vector';
    activeSourceId = source.source_id;
    const generation = rendererGeneration;
    const styleUrl = absoluteSameOriginUrl(
      `/api/maps/sources/${source.source_id}/style.json`
    );
    const style = normalizeMapLibreStyle(await jsonRequest(styleUrl));
    if (generation !== rendererGeneration || activeSourceId !== source.source_id) return;
    map = new maplibregl.Map({
      container: mapCanvas,
      style,
      center: lastView.center,
      zoom: lastView.zoom,
      attributionControl: false,
      renderWorldCopies: false,
      transformRequest: mapLibreTransformRequest
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-left');
    installViewPersistence();
    map.on('load', () => {
      if (generation !== rendererGeneration || rendererType !== 'vector') return;
      installMapLibreOverlays();
      renderMarkers();
      updateMapLibreTracks();
      tileStatus.classList.toggle('hidden', Boolean(source.style_available));
    });
    map.on('error', event => {
      if (generation !== rendererGeneration) return;
      const message = event.error?.message || 'Vector-Kartendaten konnten nicht geladen werden.';
      tileStatus.textContent = `Offline-Vector-Karte nicht verfÃ¼gbar: ${message}`;
      tileStatus.classList.remove('hidden');
    });
  }

  function useNeutralBackground(message = '') {
    if (rendererType === 'raster' && map && baseLayer) map.removeLayer(baseLayer);
    baseLayer = null;
    if (rendererType === 'raster' && map) {
      map.setMinZoom(1);
      map.setMaxZoom(20);
    }
    attribution.textContent = '';
    attribution.classList.add('hidden');
    tileStatus.textContent = message;
    tileStatus.classList.toggle('hidden', !message);
  }

  function validSource(source) {
    const minZoom = Number.isInteger(source?.min_zoom) ? source.min_zoom : 1;
    const maxZoom = Number.isInteger(source?.max_zoom) ? source.max_zoom : 20;
    return (
      Number.isInteger(source?.id)
      && minZoom >= 0
      && maxZoom <= 30
      && minZoom <= maxZoom
      && Number.isFinite(source?.file_size)
    );
  }

  function configureRasterSource(source) {
    const minZoom = Number.isInteger(source.min_zoom) ? source.min_zoom : 1;
    const maxZoom = Number.isInteger(source.max_zoom) ? source.max_zoom : 20;
    if (baseLayer) map.removeLayer(baseLayer);
    map.setMinZoom(minZoom);
    map.setMaxZoom(maxZoom);
    const currentZoom = map.getZoom();
    if (currentZoom < minZoom || currentZoom > maxZoom) {
      map.setZoom(Math.min(maxZoom, Math.max(minZoom, currentZoom)));
    }
    const layer = L.tileLayer(`/api/maps/tiles/${source.source_id}/{z}/{x}/{y}`, {
      minZoom,
      maxZoom,
      noWrap: true,
      updateWhenIdle: true
    });
    layer.on('tileerror', () => {
      if (baseLayer !== layer) return;
      tileStatus.textContent = 'Einige Offline-Kartenkacheln konnten nicht geladen werden.';
      tileStatus.classList.remove('hidden');
    });
    layer.on('load', () => {
      if (baseLayer !== layer) return;
      tileStatus.textContent = '';
      tileStatus.classList.add('hidden');
    });
    baseLayer = layer;
    activeSourceId = source.source_id;
    layer.addTo(map);
  }

  async function loadActiveMapSource() {
    if (!mapMode && !map) return;
    try {
      const data = await jsonRequest('/api/maps/active');
      const source = data.item;
      const renderer = window.mapSources.rendererFor(source);
      if (!source) {
        if (rendererType !== 'raster') {
          destroyRenderer();
          createLeafletRenderer();
        }
        useNeutralBackground();
      } else if (!validSource(source)) {
        if (rendererType !== 'raster') {
          destroyRenderer();
          createLeafletRenderer();
        }
        useNeutralBackground('Die aktive Offline-Karte ist ungÃ¼ltig oder ihre Datei fehlt.');
      } else if (renderer === 'maplibre') {
        if (rendererType !== 'vector' || activeSourceId !== source.source_id) {
          destroyRenderer();
          await createMapLibreRenderer(source);
        }
        attribution.textContent = typeof source.attribution === 'string'
          ? source.attribution
          : '';
        attribution.classList.toggle('hidden', !attribution.textContent);
        if (!source.style_available) {
          tileStatus.textContent = 'Keine vector_layers in metadata.json erkannt; nur der Offline-Hintergrund kann dargestellt werden.';
          tileStatus.classList.remove('hidden');
        } else {
          tileStatus.textContent = '';
          tileStatus.classList.add('hidden');
        }
      } else if (renderer === 'leaflet') {
        if (rendererType !== 'raster') {
          destroyRenderer();
          createLeafletRenderer();
        }
        configureRasterSource(source);
        attribution.textContent = typeof source.attribution === 'string'
          ? source.attribution
          : '';
        attribution.classList.toggle('hidden', !attribution.textContent);
      } else {
        if (rendererType !== 'raster') {
          destroyRenderer();
          createLeafletRenderer();
        }
        useNeutralBackground('Der Typ der aktiven Offline-Karte ist unbekannt.');
      }
      renderMarkers();
      await renderTracks();
      resizeMap();
    } catch (error) {
      if (rendererType !== 'raster') {
        destroyRenderer();
        createLeafletRenderer();
      }
      useNeutralBackground(`Offline-Karte nicht verfÃ¼gbar: ${error.message}`);
    }
  }

  function filteredMedia() {
    const legacyProject = projectFilter?.disabled ? '' : projectFilter?.value;
    return mapMedia.filter(
      item => !legacyProject || (item.project || 'Default') === legacyProject
    );
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
    if (!map) return;
    const filtered = filteredMedia();
    emptyState.classList.toggle('hidden', filtered.length > 0);
    if (rendererType === 'raster') {
      markerLayer.clearLayers();
      filtered.forEach(item => {
        const active = selectedItem?.id === item.id;
        const marker = L.marker([item.latitude, item.longitude], {
          icon: markerIcon(active),
          keyboard: true,
          title: item.title || 'Medium Ã¶ffnen',
          alt: item.title || 'Medium Ã¶ffnen',
          zIndexOffset: active ? 1000 : 0
        });
        marker.on('click', () => {
          openMapMedia(item.id);
        });
        marker.addTo(markerLayer);
      });
      return;
    }
    installMapLibreOverlays();
    const source = map.getSource(MEDIA_SOURCE);
    if (!source) return;
    source.setData(mapLibreGeoJson(filtered.map(item => ({
      type: 'Feature',
      geometry: {
        type: 'Point',
        coordinates: [item.longitude, item.latitude]
      },
      properties: {
        id: item.id,
        title: item.title || 'Medium Ã¶ffnen',
        active: selectedItem?.id === item.id
      }
    }))));
  }

  function trackColor(index) {
    const styles = getComputedStyle(document.documentElement);
    const names = ['--map-track-a', '--map-track-b', '--map-track-c', '--map-track-d'];
    return styles.getPropertyValue(names[index % names.length]).trim()
      || styles.getPropertyValue('--accent').trim();
  }

  function availableTracks() {
    const projectId = activeProjectId();
    if (projectId) {
      return tracks.filter(track => String(track.project_id) === String(projectId));
    }
    const legacyProject = projectFilter?.disabled ? '' : projectFilter?.value;
    return tracks.filter(track => {
      if (!legacyProject) return true;
      return (
        track.project_id === null
        || projectNames.get(String(track.project_id)) === legacyProject
      );
    });
  }

  function displayedTracks() {
    return availableTracks().filter(track => visibleTrackIds.has(track.id));
  }

  function updateMapLibreTracks() {
    if (rendererType !== 'vector') return;
    installMapLibreOverlays();
    map.getSource(TRACK_SOURCE)?.setData(mapLibreGeoJson(trackFeatures));
  }

  async function renderTracks() {
    if (!map) return;
    const displayed = displayedTracks();
    const results = await Promise.allSettled(
      displayed.map(track => jsonRequest(`/api/gpx/tracks/${track.id}`))
    );
    trackFeatures = [];
    if (rendererType === 'raster') trackLayer.clearLayers();
    results.forEach((result, index) => {
      if (result.status !== 'fulfilled') return;
      const points = result.value.item?.points || [];
      if (!points.length) return;
      const color = trackColor(index);
      const coordinates = points.map(point => [point.longitude, point.latitude]);
      trackFeatures.push({
        type: 'Feature',
        geometry: { type: 'LineString', coordinates },
        properties: { color }
      });
      if (rendererType === 'raster') {
        L.polyline(
          points.map(point => [point.latitude, point.longitude]),
          { color, weight: 4, opacity: 0.88 }
        ).addTo(trackLayer);
      }
    });
    updateMapLibreTracks();
  }

  function visibleCoordinates() {
    const coordinates = filteredMedia().map(item => [item.longitude, item.latitude]);
    trackFeatures.forEach(feature => coordinates.push(...feature.geometry.coordinates));
    return coordinates;
  }

  function fitContent() {
    if (!map) return;
    const coordinates = visibleCoordinates();
    if (!coordinates.length) {
      if (rendererType === 'raster') map.setView([20, 0], 2);
      else map.jumpTo({ center: [0, 20], zoom: 2 });
      return;
    }
    if (rendererType === 'raster') {
      const bounds = L.latLngBounds(
        coordinates.map(coordinate => [coordinate[1], coordinate[0]])
      );
      if (bounds.isValid()) map.fitBounds(bounds.pad(0.15), { maxZoom: 16 });
      return;
    }
    const bounds = coordinates.reduce(
      (result, coordinate) => result.extend(coordinate),
      new maplibregl.LngLatBounds(coordinates[0], coordinates[0])
    );
    map.fitBounds(bounds, { padding: 50, maxZoom: 16, duration: 0 });
  }

  function resizeMap() {
    if (!map) return;
    if (rendererType === 'raster') map.invalidateSize();
    else map.resize();
  }

  function createButton(label, className, handler) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    if (className) button.className = className;
    button.addEventListener('click', handler);
    return button;
  }

  async function setTrackVisibility(trackIds, visible) {
    trackIds.forEach(id => {
      if (visible) {
        visibleTrackIds.add(id);
        hiddenTrackIds.delete(id);
      } else {
        visibleTrackIds.delete(id);
        hiddenTrackIds.add(id);
      }
    });
    storeTrackVisibility();
    document.querySelectorAll('[data-gpx-track-id]').forEach(checkbox => {
      const id = Number(checkbox.dataset.gpxTrackId);
      checkbox.checked = visibleTrackIds.has(id);
      checkbox.setAttribute('aria-checked', String(checkbox.checked));
    });
    await renderTracks();
    if (mapMode) fitContent();
  }

  function createTrackCheckbox(track, className = '') {
    const label = document.createElement('label');
    if (className) label.className = className;
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.dataset.gpxTrackId = String(track.id);
    checkbox.checked = visibleTrackIds.has(track.id);
    checkbox.setAttribute('role', 'switch');
    checkbox.setAttribute('aria-checked', String(checkbox.checked));
    checkbox.setAttribute('aria-label', `GPX-Track ${track.name} anzeigen`);
    checkbox.addEventListener('change', () => {
      setTrackVisibility([track.id], checkbox.checked);
    });
    return { label, checkbox };
  }

  function renderMapTrackList() {
    mapTrackList.replaceChildren();
    const available = availableTracks();
    showAllMapTracksBtn.disabled = available.length === 0;
    hideAllMapTracksBtn.disabled = available.length === 0;
    if (!available.length) {
      const empty = document.createElement('p');
      empty.textContent = 'Keine GPX-Tracks fÃ¼r den aktuellen Projektfilter verfÃ¼gbar.';
      mapTrackList.appendChild(empty);
      return;
    }
    available.forEach(track => {
      const { label, checkbox } = createTrackCheckbox(track, 'map-track-toggle');
      const text = document.createElement('span');
      text.className = 'map-track-toggle__text';
      const name = document.createElement('span');
      name.className = 'map-track-toggle__name';
      name.textContent = track.name;
      const meta = document.createElement('span');
      meta.className = 'map-track-toggle__meta';
      meta.textContent = `${track.point_count} ${track.point_count === 1 ? 'Punkt' : 'Punkte'}`;
      text.append(name, meta);
      label.append(checkbox, text);
      mapTrackList.appendChild(label);
    });
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
      const { label: header, checkbox } = createTrackCheckbox(track);
      const name = document.createElement('span');
      const assignment = track.project_id === null
        ? 'ohne Projekt'
        : (projectNames.get(String(track.project_id)) || `Projekt ${track.project_id}`);
      name.textContent = `${track.name} (${track.point_count} Punkte Â· ${assignment})`;
      header.append(checkbox, name);
      const actions = document.createElement('div');
      actions.className = 'gpx-track-actions';
      actions.append(
        createButton('Zeit zuordnen', '', () => matchTrack(track)),
        createButton('LÃ¶schen', 'danger', () => deleteTrack(track))
      );
      row.append(header, actions);
      trackList.appendChild(row);
    });
  }

  async function loadTracks() {
    try {
      const data = await jsonRequest('/api/gpx/tracks');
      tracks = (data.items || []).filter(track => Number.isInteger(track.id) && track.id > 0);
      visibleTrackIds.clear();
      tracks.forEach(track => {
        if (!hiddenTrackIds.has(track.id)) visibleTrackIds.add(track.id);
      });
      storeTrackVisibility();
      renderTrackList();
      renderMapTrackList();
      await renderTracks();
    } catch (error) {
      setStatus(gpxStatus, error.message, true);
    }
  }

  async function refreshMap({ fit = true } = {}) {
    try {
      if (mapMode) await loadActiveMapSource();
      const data = await jsonRequest(apiUrl('/api/map/media'));
      mapMedia = data.items || [];
      renderMarkers();
      await loadTracks();
      if (mapMode) {
        resizeMap();
        if (fit) fitContent();
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
      renderMapTrackList();
    } catch (error) {
      setStatus(gpxStatus, error.message, true);
    }
  }

  async function setMapMode(enabled) {
    mapMode = enabled;
    const restoreExistingView = hasStoredMapView;
    window.appUiState?.setMapViewActive(enabled);
    modeButton.textContent = enabled ? 'Viewer' : 'Karte';
    modeButton.setAttribute('aria-pressed', String(enabled));
    if (enabled) {
      await loadActiveMapSource();
      await refreshMap({ fit: !restoreExistingView });
      requestAnimationFrame(() => {
        resizeMap();
        if (!restoreExistingView) fitContent();
      });
    }
  }

  function openMapMedia(mediaId) {
    setMapMode(false);
    return window.selectMediaById?.(mediaId) || false;
  }

  function fillGps(item) {
    selectedItem = item || null;
    document.getElementById('gpsLatitude').value = item?.latitude ?? '';
    document.getElementById('gpsLongitude').value = item?.longitude ?? '';
    document.getElementById('gpsAltitude').value = item?.altitude ?? '';
    document.getElementById('gpsSource').textContent = item?.gps_source || 'â€“';
    [...gpsForm.elements].forEach(element => {
      element.disabled = !item;
    });
    setStatus(gpsStatus, item ? 'Bereit.' : 'Kein Medium gewÃ¤hlt.');
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
      setStatus(gpsStatus, 'Position gelÃ¶scht.');
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
    setStatus(gpxStatus, 'GPX wird importiert â€¦');
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
      visibleTrackIds.delete(track.id);
      hiddenTrackIds.delete(track.id);
      storeTrackVisibility();
      setStatus(gpxStatus, `${track.name} wurde gelÃ¶scht.`);
      await loadTracks();
      if (mapMode) fitContent();
    } catch (error) {
      setStatus(gpxStatus, error.message, true);
    }
  }

  async function matchTrack(track) {
    const difference = Number(document.getElementById('gpxMatchDifference').value);
    setStatus(gpxStatus, `${track.name}: Medien werden zugeordnet â€¦`);
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
        `${data.matched} zugeordnet, ${data.skipped} Ã¼bersprungen, ${data.unmatched} ohne Treffer.`
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
    renderMapTrackList();
    await renderTracks();
    if (mapMode) fitContent();
  });
  showAllMapTracksBtn.addEventListener('click', () => {
    setTrackVisibility(availableTracks().map(track => track.id), true);
  });
  hideAllMapTracksBtn.addEventListener('click', () => {
    setTrackVisibility(availableTracks().map(track => track.id), false);
  });
  window.addEventListener('offline-map-source-changed', () => {
    if (mapMode || map) loadActiveMapSource();
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
    refresh: refreshMap,
    refreshBaseLayer: loadActiveMapSource
  };

  fillGps(null);
  loadProjects();
})();

