(function () {
  'use strict';
  if (location.protocol === 'file:') return;

  const state = { tour: null, current: -1, panorama: null, special: null, video: null, map: null };
  const $ = id => document.getElementById(id);
  const gallery = $('gallery');
  const viewer = $('viewer');

  function destroyViewer() {
    state.panorama?.destroy();
    state.special?.destroy();
    state.video?.destroy();
    state.panorama = state.special = state.video = null;
    viewer.replaceChildren();
  }

  function viewValues(item) {
    const start = item.start_view || {};
    return {
      yaw: Number.isFinite(start.yaw) ? start.yaw : 0,
      pitch: Number.isFinite(start.pitch) ? start.pitch : 0,
      fov: Number.isFinite(start.fov) ? start.fov : Math.PI / 2
    };
  }

  function hotspotElement(hotspot) {
    const button = document.createElement('button');
    button.className = `hotspot ${hotspot.action_type === 'info' ? 'info' : ''}`;
    button.type = 'button';
    button.textContent = `${hotspot.action_type === 'info' ? 'i' : '→'} ${hotspot.title || (hotspot.action_type === 'info' ? 'Information' : 'Panorama')}`;
    button.addEventListener('click', () => {
      if (hotspot.action_type === 'info') {
        $('infoTitle').textContent = hotspot.title || 'Information';
        $('infoText').textContent = hotspot.info_text || '';
        $('infoDialog').showModal();
      } else {
        const index = state.tour.media.findIndex(item => item.id === hotspot.target_media_id);
        if (index >= 0) openMedia(index);
      }
    });
    return button;
  }

  function openNormal(item) {
    destroyViewer();
    $('normalBtn').disabled = item.type !== 'photo';
    $('tinyBtn').disabled = item.type !== 'photo';
    $('rabbitBtn').disabled = item.type !== 'photo';
    if (!item.available || !item.local_path) {
      const message = document.createElement('div');
      message.className = 'unavailable';
      message.textContent = 'Diese Mediendatei war beim Export nicht verfügbar.';
      viewer.appendChild(message);
      return;
    }
    const start = viewValues(item);
    if (item.type === 'video') {
      state.video = new window.Video360Viewer(viewer, item.local_path, {
        yaw: start.yaw, pitch: start.pitch, fov: start.fov, fullscreenElement: viewer
      });
      return;
    }
    state.panorama = new Marzipano.Viewer(viewer);
    const source = Marzipano.ImageUrlSource.fromString(item.local_path);
    const geometry = new Marzipano.EquirectGeometry([{ width: 4096 }]);
    const limiter = Marzipano.RectilinearView.limit.traditional(4096, Math.PI * 100 / 180);
    const view = new Marzipano.RectilinearView(start, limiter);
    const scene = state.panorama.createScene({ source, geometry, view, pinFirstLevel: true });
    item.hotspots.filter(h => h.visible).forEach(hotspot => {
      scene.hotspotContainer().createHotspot(hotspotElement(hotspot), {
        yaw: hotspot.yaw, pitch: hotspot.pitch
      });
    });
    scene.switchTo();
  }

  function openProjection(mode) {
    const item = state.tour.media[state.current];
    if (!item || item.type !== 'photo' || !item.available) return;
    destroyViewer();
    state.special = new window.TinyPlanetRenderer(viewer, item.local_path, {
      projectionMode: mode, yaw: viewValues(item).yaw
    });
  }

  function openMedia(index) {
    if (index < 0 || index >= state.tour.media.length) return;
    state.current = index;
    const item = state.tour.media[index];
    $('mediaTitle').textContent = item.title || `Medium ${item.id}`;
    $('mediaDescription').textContent = item.description || '';
    $('previousBtn').disabled = index === 0;
    $('nextBtn').disabled = index === state.tour.media.length - 1;
    gallery.classList.add('hidden');
    $('mapScreen').classList.add('hidden');
    $('viewerScreen').classList.remove('hidden');
    openNormal(item);
  }

  function mediaCard(item, cover) {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = `card ${cover ? 'cover' : ''}`;
    const image = document.createElement(item.thumbnail || (item.type === 'photo' && item.local_path) ? 'img' : 'div');
    if (image.tagName === 'IMG') {
      image.src = item.thumbnail || item.local_path;
      image.alt = '';
      image.loading = 'lazy';
    } else {
      image.className = 'card-placeholder';
      image.textContent = item.type === 'video' ? '360° Video' : 'Panorama';
    }
    const body = document.createElement('span');
    body.className = 'card-body';
    const title = document.createElement('strong');
    title.textContent = item.title || `Medium ${item.id}`;
    const type = document.createElement('span');
    type.textContent = `${item.type === 'video' ? 'Video' : 'Foto'}${item.available ? '' : ' · Datei fehlt'}`;
    body.append(title, type);
    card.append(image, body);
    card.addEventListener('click', () => openMedia(state.tour.media.indexOf(item)));
    return card;
  }

  function showGallery() {
    destroyViewer();
    $('viewerScreen').classList.add('hidden');
    $('mapScreen').classList.add('hidden');
    gallery.classList.remove('hidden');
  }

  function mapCoordinates() {
    const result = [];
    state.tour.media.filter(item => item.gps).forEach(item => {
      result.push([item.gps.longitude, item.gps.latitude]);
    });
    state.tour.gpx_tracks.forEach(track => {
      track.points.forEach(point => result.push([point.longitude, point.latitude]));
    });
    return result;
  }

  function mapCenter() {
    const configured = String(state.tour.map_source?.center || '').split(',').map(Number);
    if (configured.length >= 2 && configured.slice(0, 2).every(Number.isFinite)) {
      return [configured[0], configured[1]];
    }
    const points = mapCoordinates();
    if (!points.length) return [0, 0];
    return [
      points.reduce((sum, point) => sum + point[0], 0) / points.length,
      points.reduce((sum, point) => sum + point[1], 0) / points.length
    ];
  }

  function addLeafletOverlays(map) {
    const bounds = [];
    state.tour.media.filter(item => item.gps).forEach(item => {
      const point = [item.gps.latitude, item.gps.longitude];
      bounds.push(point);
      L.marker(point).addTo(map).bindPopup(item.title || `Medium ${item.id}`)
        .on('click', () => openMedia(state.tour.media.indexOf(item)));
    });
    state.tour.gpx_tracks.forEach(track => {
      const points = track.points.map(point => [point.latitude, point.longitude]);
      if (points.length) {
        bounds.push(...points);
        L.polyline(points, { color: '#ff7a18', weight: 4 }).addTo(map).bindPopup(track.name);
      }
    });
    if (bounds.length) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 15 });
  }

  function createLeafletMap() {
    const center = mapCenter();
    const map = L.map('map', { attributionControl: true }).setView([center[1], center[0]], 2);
    const source = state.tour.map_source;
    if (source?.map_type === 'raster') {
      L.tileLayer('/api/maps/tiles/{z}/{x}/{y}', {
        minZoom: Number.isFinite(source.min_zoom) ? source.min_zoom : 0,
        maxZoom: Number.isFinite(source.max_zoom) ? source.max_zoom : 22,
        attribution: source.attribution || ''
      }).on('tileerror', () => {
        $('mapStatus').textContent = 'Einige Kartenkacheln konnten nicht geladen werden. Galerie und Viewer bleiben verfügbar.';
      }).addTo(map);
      $('mapStatus').textContent = `Offline-Karte „${source.name}“ · Raster-MBTiles`;
    } else {
      $('mapStatus').textContent = 'Keine Offline-Basiskarte enthalten. GPS-Marker und GPX-Tracks werden auf neutralem Hintergrund dargestellt.';
    }
    addLeafletOverlays(map);
    return map;
  }

  function addMapLibreOverlays(map) {
    state.tour.media.filter(item => item.gps).forEach(item => {
      const marker = document.createElement('button');
      marker.className = 'map-marker';
      marker.type = 'button';
      marker.title = item.title || `Medium ${item.id}`;
      marker.setAttribute('aria-label', marker.title);
      marker.addEventListener('click', () => openMedia(state.tour.media.indexOf(item)));
      new maplibregl.Marker({ element: marker })
        .setLngLat([item.gps.longitude, item.gps.latitude])
        .addTo(map);
    });
    const features = state.tour.gpx_tracks
      .filter(track => track.points.length)
      .map(track => ({
        type: 'Feature',
        properties: { name: track.name },
        geometry: {
          type: 'LineString',
          coordinates: track.points.map(point => [point.longitude, point.latitude])
        }
      }));
    if (features.length) {
      map.addSource('tour-tracks', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features }
      });
      map.addLayer({
        id: 'tour-tracks',
        type: 'line',
        source: 'tour-tracks',
        paint: { 'line-color': '#ff7a18', 'line-width': 4 }
      });
    }
    const coordinates = mapCoordinates();
    if (coordinates.length) {
      const bounds = coordinates.reduce(
        (current, coordinate) => current.extend(coordinate),
        new maplibregl.LngLatBounds(coordinates[0], coordinates[0])
      );
      map.fitBounds(bounds, { padding: 30, maxZoom: 15, duration: 0 });
    }
  }

  function createVectorMap() {
    const source = state.tour.map_source;
    const map = new maplibregl.Map({
      container: 'map',
      style: '/api/maps/style.json',
      center: mapCenter(),
      zoom: 2,
      attributionControl: true
    });
    map.addControl(new maplibregl.NavigationControl(), 'top-right');
    map.once('load', () => {
      addMapLibreOverlays(map);
      $('mapStatus').textContent = `Offline-Karte „${source.name}“ · Vector-MBTiles`;
    });
    map.on('error', event => {
      console.error('Offline-Kartenfehler:', event.error || event);
      $('mapStatus').textContent = 'Die Offline-Karte konnte nicht vollständig geladen werden. Galerie und Viewer bleiben verfügbar.';
    });
    return map;
  }

  function showMap() {
    destroyViewer();
    gallery.classList.add('hidden');
    $('viewerScreen').classList.add('hidden');
    $('mapScreen').classList.remove('hidden');
    if (!state.map) {
      try {
        state.map = state.tour.map_source?.map_type === 'vector'
          ? createVectorMap()
          : createLeafletMap();
      } catch (error) {
        console.error('Karte konnte nicht initialisiert werden:', error);
        $('mapStatus').textContent = 'Die Karte konnte nicht initialisiert werden. Galerie und Viewer bleiben verfügbar.';
      }
    }
    setTimeout(() => {
      if (typeof state.map?.invalidateSize === 'function') state.map.invalidateSize();
      else if (typeof state.map?.resize === 'function') state.map.resize();
    }, 0);
  }

  async function initialize() {
    try {
      const response = await fetch('tour.json', { cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.tour = await response.json();
      $('projectName').textContent = state.tour.project.name;
      $('projectDescription').textContent = state.tour.project.description || '';
      const cover = state.tour.media.find(item => item.id === state.tour.project.cover_media_id);
      if (cover) gallery.appendChild(mediaCard(cover, true));
      state.tour.media.filter(item => item !== cover).forEach(item => gallery.appendChild(mediaCard(item, false)));
    } catch (error) {
      gallery.textContent = `Die Tourdaten konnten nicht geladen werden: ${error.message}`;
    }
  }

  $('galleryBtn').addEventListener('click', showGallery);
  $('mapBtn').addEventListener('click', showMap);
  $('normalBtn').addEventListener('click', () => openNormal(state.tour.media[state.current]));
  $('tinyBtn').addEventListener('click', () => openProjection('tiny-planet'));
  $('rabbitBtn').addEventListener('click', () => openProjection('rabbit-hole'));
  $('previousBtn').addEventListener('click', () => openMedia(state.current - 1));
  $('nextBtn').addEventListener('click', () => openMedia(state.current + 1));
  $('closeInfoBtn').addEventListener('click', () => $('infoDialog').close());
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') showGallery();
    if (event.key === 'ArrowLeft' && !$('viewerScreen').classList.contains('hidden')) openMedia(state.current - 1);
    if (event.key === 'ArrowRight' && !$('viewerScreen').classList.contains('hidden')) openMedia(state.current + 1);
    if (event.key.toLowerCase() === 'g') showGallery();
    if (event.key.toLowerCase() === 'm') showMap();
  });
  initialize();
}());
