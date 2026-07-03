import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MapAssetTests(unittest.TestCase):
    def test_leaflet_194_is_local_and_loaded_before_map_module(self) -> None:
        page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        leaflet_script = '<script src="/static/lib/leaflet/leaflet.js"></script>'
        map_script = '<script src="/static/js/map.js"></script>'
        self.assertIn(
            '<link rel="stylesheet" href="/static/lib/leaflet/leaflet.css" />',
            page,
        )
        self.assertLess(page.index(leaflet_script), page.index(map_script))
        leaflet = (ROOT / "static" / "lib" / "leaflet" / "leaflet.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("Leaflet 1.9.4", leaflet)
        self.assertTrue((ROOT / "static" / "lib" / "leaflet" / "LICENSE.txt").is_file())

    def test_maplibre_5240_is_local_and_loaded_before_map_module(self) -> None:
        page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        maplibre_script = '<script src="/static/lib/maplibre/maplibre-gl.js"></script>'
        map_script = '<script src="/static/js/map.js"></script>'
        self.assertIn(
            '<link rel="stylesheet" href="/static/lib/maplibre/maplibre-gl.css" />',
            page,
        )
        self.assertLess(page.index(maplibre_script), page.index(map_script))
        version = (ROOT / "static" / "lib" / "maplibre" / "VERSION.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("5.24.0", version)
        self.assertIn("BSD-3-Clause", version)
        self.assertTrue(
            (ROOT / "static" / "lib" / "maplibre" / "LICENSE.txt").is_file()
        )

    def test_map_source_contract_is_loaded_before_consumers(self) -> None:
        page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        contract = '<script src="/static/js/map_sources.js"></script>'
        self.assertLess(
            page.index(contract),
            page.index('<script src="/static/js/offline_maps.js"></script>'),
        )
        self.assertLess(
            page.index(contract),
            page.index('<script src="/static/js/map.js"></script>'),
        )

    def test_map_uses_only_local_tiles_and_safe_text_rendering(self) -> None:
        source = (ROOT / "static" / "js" / "map.js").read_text(encoding="utf-8")
        self.assertIn("L.tileLayer", source)
        self.assertIn("new maplibregl.Map", source)
        self.assertIn("type: 'geojson'", source)
        self.assertIn("/api/maps/tiles/", source)
        self.assertIn("/style.json", source)
        self.assertNotIn("https://", source)
        self.assertNotIn("http://", source)
        self.assertNotIn(".innerHTML", source)
        self.assertNotIn("alert(", source)
        self.assertIn("textContent", source)

    def test_maplibre_urls_are_normalized_to_the_runtime_origin(self) -> None:
        source = (ROOT / "static" / "js" / "map.js").read_text(encoding="utf-8")
        self.assertIn("function absoluteSameOriginUrl(url)", source)
        self.assertIn("new URL(url, window.location.origin)", source)
        self.assertIn("resolved.origin !== window.location.origin", source)
        self.assertIn("function normalizeMapLibreStyle(style)", source)
        self.assertIn("source.tiles.map(absoluteSameOriginUrl)", source)
        self.assertIn("style.sprite = absoluteSameOriginUrl(style.sprite)", source)
        self.assertIn("style.glyphs = absoluteSameOriginUrl(style.glyphs)", source)
        self.assertIn("transformRequest: mapLibreTransformRequest", source)
        self.assertIn("%7B([^{}%/]+)%7D", source)
        self.assertNotIn("127.0.0.1", source)
        self.assertNotIn("localhost", source)

    def test_map_and_admin_mount_points_are_accessible(self) -> None:
        page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        for marker in (
            'id="mapView"',
            'aria-label="Kartenansicht"',
            'id="stageModeBtn"',
            'aria-pressed="false"',
            'id="gpsStatus"',
            'aria-live="polite"',
            'id="gpxTrackList"',
            'id="mapTrackControl"',
            'id="mapTrackList"',
            'id="showAllMapTracksBtn"',
            'id="hideAllMapTracksBtn"',
            'id="mapControls"',
            'id="mapBasemapSelect"',
            'aria-label="Basiskarte auswählen"',
            'Keine Basiskarte',
            'id="offlineMapsTitle"',
            'id="offlineMapStatus"',
        ):
            self.assertIn(marker, page)

    def test_map_controls_visibility_uses_central_ui_state(self) -> None:
        app_source = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        map_source = (ROOT / "static" / "js" / "map.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
        self.assertIn("mapViewActive: false", app_source)
        self.assertIn("adminOpen: false", app_source)
        self.assertIn(
            "const mapControlsVisible = uiState.mapViewActive && !uiState.adminOpen",
            app_source,
        )
        self.assertIn("window.appUiState.setAdminOpen(enabled)", app_source)
        self.assertIn("window.appUiState?.setMapViewActive(enabled)", map_source)
        self.assertIn("mapControlsElement.inert = !mapControlsVisible", app_source)
        self.assertIn(".map-controls--hidden", css)
        hidden_rule = css[css.index(".map-controls--hidden"):]
        hidden_rule = hidden_rule[:hidden_rule.index("}")]
        self.assertIn("pointer-events:none", hidden_rule)
        self.assertIn("visibility:hidden", hidden_rule)

    def test_basemap_selector_lists_types_and_notifies_renderer(self) -> None:
        source = (ROOT / "static" / "js" / "offline_maps.js").read_text(
            encoding="utf-8"
        )
        source_contract = (ROOT / "static" / "js" / "map_sources.js").read_text(
            encoding="utf-8"
        )
        map_source = (ROOT / "static" / "js" / "map.js").read_text(encoding="utf-8")
        self.assertIn("neutral.textContent", source)
        self.assertIn("'Keine Basiskarte", source)
        self.assertIn("if (type === 'raster') return 'Raster'", source_contract)
        self.assertIn("if (type === 'vector') return 'Vector'", source_contract)
        self.assertIn("return 'Unbekannt'", source_contract)
        self.assertIn("source.name", source)
        self.assertIn("source.active ? ' · Aktiv' : ''", source)
        self.assertIn("option.value = String(source.source_id)", source)
        self.assertIn("JSON.stringify({ source_id: sourceId })", source)
        self.assertIn("notifyMap()", source)
        self.assertIn(
            "window.addEventListener('offline-map-source-changed'", map_source
        )
        self.assertIn("loadActiveMapSource()", map_source)

    def test_basemap_sources_are_unique_and_only_one_is_active(self) -> None:
        source = (ROOT / "static" / "js" / "map_sources.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("unique.has(source.source_id)", source)
        self.assertIn("unique.set(source.source_id, source)", source)
        self.assertIn(
            "normalized.find(source => source.active)?.source_id ?? null",
            source,
        )
        self.assertIn("active: source.source_id === activeSourceId", source)

    def test_unknown_type_is_not_vector_and_renderer_uses_backend_map_type(self) -> None:
        source = (ROOT / "static" / "js" / "map_sources.js").read_text(
            encoding="utf-8"
        )
        map_source = (ROOT / "static" / "js" / "map.js").read_text(encoding="utf-8")
        self.assertIn("source?.map_type === 'raster'", source)
        self.assertIn("source?.map_type === 'vector'", source)
        self.assertNotIn("source?.type", source)
        self.assertIn("return 'unknown'", source)
        self.assertIn("if (type === 'raster') return 'leaflet'", source)
        self.assertIn("if (type === 'vector') return 'maplibre'", source)
        self.assertIn("return 'neutral'", source)
        self.assertIn("window.mapSources.rendererFor(source)", map_source)
        self.assertIn("renderer === 'maplibre'", map_source)
        self.assertIn("renderer === 'leaflet'", map_source)
        self.assertIn("Typ der aktiven Offline-Karte ist unbekannt", map_source)

    def test_map_source_contract_behavior(self) -> None:
        contract_path = ROOT / "static" / "js" / "map_sources.js"
        script = """
const fs = require('fs');
const vm = require('vm');
global.window = {};
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
const sources = window.mapSources.normalize([
  { source_id: 7, name: 'Raster', map_type: 'raster', active: true },
  { source_id: 8, name: 'Vector', map_type: 'vector', active: true },
  { source_id: 7, name: 'Duplikat', map_type: 'vector', active: false },
  { source_id: 9, name: 'Defekt', map_type: 'other', active: false }
]);
console.log(JSON.stringify({
  ids: sources.map(source => source.source_id),
  activeIds: sources.filter(source => source.active).map(source => source.source_id),
  labels: sources.map(window.mapSources.mapTypeLabel),
  renderers: sources.map(window.mapSources.rendererFor)
}));
"""
        result = subprocess.run(
            ["node", "-e", script, str(contract_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        actual = json.loads(result.stdout)
        self.assertEqual(actual["ids"], [7, 8, 9])
        self.assertEqual(actual["activeIds"], [7])
        self.assertEqual(actual["labels"], ["Raster", "Vector", "Unbekannt"])
        self.assertEqual(actual["renderers"], ["leaflet", "maplibre", "neutral"])

    def test_renderer_switch_rebuilds_overlays_without_resetting_visibility(self) -> None:
        source = (ROOT / "static" / "js" / "map.js").read_text(encoding="utf-8")
        load_start = source.index("async function loadActiveMapSource()")
        load_end = source.index("\n  function filteredMedia()", load_start)
        loader = source[load_start:load_end]
        self.assertIn("createLeafletRenderer()", loader)
        self.assertIn("createMapLibreRenderer(source)", loader)
        self.assertIn("renderMarkers()", loader)
        self.assertIn("await renderTracks()", loader)
        destroy_start = source.index("function destroyRenderer()")
        destroy_end = source.index("\n  function createLeafletRenderer()", destroy_start)
        destroy = source[destroy_start:destroy_end]
        self.assertNotIn("visibleTrackIds.clear()", destroy)
        self.assertNotIn("mapMedia = []", destroy)

    def test_gpx_track_control_shares_visibility_across_renderers(self) -> None:
        source = (ROOT / "static" / "js" / "map.js").read_text(encoding="utf-8")
        self.assertIn("const visibleTrackIds = new Set()", source)
        self.assertIn("return availableTracks().filter(track => visibleTrackIds.has(track.id))", source)
        self.assertIn("trackLayer.clearLayers()", source)
        self.assertIn("L.polyline(", source)
        self.assertIn("map.getSource(TRACK_SOURCE)?.setData", source)
        self.assertIn("localStorage.setItem(", source)
        self.assertIn("hiddenTrackIds.delete(track.id)", source)

    def test_gpx_track_control_respects_project_filter(self) -> None:
        source = (ROOT / "static" / "js" / "map.js").read_text(encoding="utf-8")
        self.assertIn("function availableTracks()", source)
        self.assertIn("const projectId = activeProjectId()", source)
        self.assertIn("String(track.project_id) === String(projectId)", source)
        self.assertIn("renderMapTrackList()", source)

    def test_map_marker_leaves_map_before_opening_media(self) -> None:
        source = (ROOT / "static" / "js" / "map.js").read_text(encoding="utf-8")
        app_source = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        start = source.index("function openMapMedia(mediaId)")
        end = source.index("\n  }", start)
        handler = source[start:end]
        self.assertLess(handler.index("setMapMode(false)"), handler.index("selectMediaById"))
        self.assertNotIn("alert(", source)
        self.assertNotIn("alert(", app_source)


if __name__ == "__main__":
    unittest.main()
