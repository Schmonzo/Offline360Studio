(() => {
  'use strict';

  function mapType(source) {
    if (source?.map_type === 'raster') return 'raster';
    if (source?.map_type === 'vector') return 'vector';
    return 'unknown';
  }

  function mapTypeLabel(source) {
    const type = mapType(source);
    if (type === 'raster') return 'Raster';
    if (type === 'vector') return 'Vector';
    return 'Unbekannt';
  }

  function rendererFor(source) {
    const type = mapType(source);
    if (type === 'raster') return 'leaflet';
    if (type === 'vector') return 'maplibre';
    return 'neutral';
  }

  function normalize(items) {
    const unique = new Map();
    if (Array.isArray(items)) {
      items.forEach(source => {
        if (!Number.isInteger(source?.source_id) || unique.has(source.source_id)) return;
        unique.set(source.source_id, source);
      });
    }
    const normalized = [...unique.values()];
    const activeSourceId = normalized.find(source => source.active)?.source_id ?? null;
    return normalized.map(source => ({
      ...source,
      active: source.source_id === activeSourceId
    }));
  }

  window.mapSources = Object.freeze({
    mapType,
    mapTypeLabel,
    normalize,
    rendererFor
  });
})();

