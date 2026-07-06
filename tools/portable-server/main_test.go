package main

import (
	"bytes"
	"compress/gzip"
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func testHandler(t *testing.T, root string) http.Handler {
	t.Helper()
	handler, err := newPortableHandler(root)
	if err != nil {
		t.Fatal(err)
	}
	return handler
}

func request(t *testing.T, handler http.Handler, method, target string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(method, target, nil)
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, req)
	return recorder
}

func writeFile(t *testing.T, path string, content []byte) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, content, 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestIndexAndSecurityHeaders(t *testing.T) {
	root := t.TempDir()
	writeFile(t, filepath.Join(root, "index.html"), []byte("<h1>Tour</h1>"))
	response := request(t, testHandler(t, root), http.MethodGet, "/")
	if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), "Tour") {
		t.Fatalf("unexpected response: %d %s", response.Code, response.Body.String())
	}
	if response.Header().Get("Content-Type") != "text/html; charset=utf-8" {
		t.Fatalf("unexpected content type: %s", response.Header().Get("Content-Type"))
	}
	if response.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("index must not be cached")
	}
	if response.Header().Get("X-Content-Type-Options") != "nosniff" {
		t.Fatalf("nosniff header missing")
	}
	if response.Header().Get("Referrer-Policy") != "no-referrer" {
		t.Fatalf("referrer policy missing")
	}
}

func TestWebrootBoundaryAndInvalidPaths(t *testing.T) {
	parent := t.TempDir()
	root := filepath.Join(parent, "root")
	if err := os.Mkdir(root, 0o755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(root, "index.html"), []byte("ok"))
	writeFile(t, filepath.Join(parent, "secret.txt"), []byte("secret"))
	handler := testHandler(t, root)
	for _, target := range []string{"/../secret.txt", "/%2e%2e/secret.txt", `/..\secret.txt`} {
		response := request(t, handler, http.MethodGet, target)
		if response.Code != http.StatusNotFound {
			t.Fatalf("%s escaped webroot: %d", target, response.Code)
		}
	}
}

func TestDirectoryListingIsDisabled(t *testing.T) {
	root := t.TempDir()
	writeFile(t, filepath.Join(root, "index.html"), []byte("ok"))
	writeFile(t, filepath.Join(root, "assets", "secret.txt"), []byte("secret"))
	response := request(t, testHandler(t, root), http.MethodGet, "/assets/")
	if response.Code != http.StatusNotFound {
		t.Fatalf("directory listing returned %d", response.Code)
	}
	if strings.Contains(response.Body.String(), "secret.txt") {
		t.Fatal("directory contents leaked")
	}
}

func TestMIMETypesAndCaching(t *testing.T) {
	root := t.TempDir()
	writeFile(t, filepath.Join(root, "index.html"), []byte("ok"))
	cases := map[string]string{
		"tour.json":                   "application/json; charset=utf-8",
		"assets/app.js":               "text/javascript; charset=utf-8",
		"assets/app.css":              "text/css; charset=utf-8",
		"assets/photo.jpg":            "image/jpeg",
		"assets/photo.jpeg":           "image/jpeg",
		"assets/photo.png":            "image/png",
		"assets/photo.webp":           "image/webp",
		"assets/video.mp4":            "video/mp4",
		"assets/track.gpx":            "application/gpx+xml",
		"assets/tile.pbf":             "application/vnd.mapbox-vector-tile",
		"assets/map.mbtiles":          "application/vnd.sqlite3",
		"assets/font.woff":            "font/woff",
		"assets/font.woff2":           "font/woff2",
	}
	for name, expected := range cases {
		writeFile(t, filepath.Join(root, filepath.FromSlash(name)), []byte("data"))
		response := request(t, testHandler(t, root), http.MethodGet, "/"+name)
		if response.Code != http.StatusOK {
			t.Fatalf("%s returned %d", name, response.Code)
		}
		if actual := response.Header().Get("Content-Type"); actual != expected {
			t.Errorf("%s: got %q, want %q", name, actual, expected)
		}
		if name == "tour.json" && response.Header().Get("Cache-Control") != "no-store" {
			t.Errorf("tour.json must not be cached")
		}
	}
}

func TestDynamicPortBindsOnlyLoopback(t *testing.T) {
	listener, err := listen(0)
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	host, port, err := netSplitHostPort(listener.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	if host != defaultHost || port == "0" || port == "" {
		t.Fatalf("unexpected listener address: %s", listener.Addr())
	}
}

func netSplitHostPort(value string) (string, string, error) {
	index := strings.LastIndex(value, ":")
	if index < 0 {
		return "", "", fmt.Errorf("missing port")
	}
	return value[:index], value[index+1:], nil
}

func createMap(t *testing.T, root, format, mapType, schema string, z, x, tmsY int, tile []byte) {
	t.Helper()
	mapDir := filepath.Join(root, "assets", "maps")
	if err := os.MkdirAll(mapDir, 0o755); err != nil {
		t.Fatal(err)
	}
	mapPath := filepath.Join(mapDir, "map.mbtiles")
	db, err := sql.Open("sqlite", mapPath)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if _, err := db.Exec("CREATE TABLE metadata (name TEXT, value TEXT)"); err != nil {
		t.Fatal(err)
	}
	layerJSON := `{"vector_layers":[{"id":"roads"}]}`
	if _, err := db.Exec("INSERT INTO metadata(name,value) VALUES ('json',?)", layerJSON); err != nil {
		t.Fatal(err)
	}
	switch schema {
	case "flat":
		if _, err := db.Exec("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)"); err != nil {
			t.Fatal(err)
		}
		if _, err := db.Exec("INSERT INTO tiles VALUES (?,?,?,?)", z, x, tmsY, tile); err != nil {
			t.Fatal(err)
		}
	case "normalized":
		if _, err := db.Exec("CREATE TABLE map (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_id TEXT)"); err != nil {
			t.Fatal(err)
		}
		if _, err := db.Exec("CREATE TABLE images (tile_id TEXT, tile_data BLOB)"); err != nil {
			t.Fatal(err)
		}
		if _, err := db.Exec("INSERT INTO map VALUES (?,?,?,'tile')", z, x, tmsY); err != nil {
			t.Fatal(err)
		}
		if _, err := db.Exec("INSERT INTO images VALUES ('tile',?)", tile); err != nil {
			t.Fatal(err)
		}
	}
	tour := map[string]any{
		"map_source": map[string]any{
			"path": "assets/maps/map.mbtiles", "map_type": mapType,
			"format": format, "name": "Testkarte", "attribution": "Test",
			"min_zoom": 0, "max_zoom": 14,
		},
	}
	content, err := json.Marshal(tour)
	if err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(root, "tour.json"), content)
	writeFile(t, filepath.Join(root, "index.html"), []byte("ok"))
}

func TestRasterTileAndTMSConversion(t *testing.T) {
	root := t.TempDir()
	tile := []byte{0x89, 'P', 'N', 'G'}
	createMap(t, root, "png", "raster", "flat", 2, 1, 2, tile)
	handler := testHandler(t, root)
	response := request(t, handler, http.MethodGet, "/api/maps/tiles/2/1/1")
	if response.Code != http.StatusOK || !bytes.Equal(response.Body.Bytes(), tile) {
		t.Fatalf("raster tile failed: %d %x", response.Code, response.Body.Bytes())
	}
	if response.Header().Get("Content-Type") != "image/png" {
		t.Fatalf("unexpected raster MIME type")
	}
	missing := request(t, handler, http.MethodGet, "/api/maps/tiles/2/1/2")
	if missing.Code != http.StatusNotFound {
		t.Fatalf("TMS conversion not applied, got %d", missing.Code)
	}
}

func TestVectorGzipTileNormalizedSchema(t *testing.T) {
	root := t.TempDir()
	var compressed bytes.Buffer
	writer := gzip.NewWriter(&compressed)
	if _, err := writer.Write([]byte("vector")); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	createMap(t, root, "pbf", "vector", "normalized", 1, 0, 1, compressed.Bytes())
	response := request(t, testHandler(t, root), http.MethodGet, "/api/maps/tiles/1/0/0")
	if response.Code != http.StatusOK {
		t.Fatalf("vector tile returned %d: %s", response.Code, response.Body.String())
	}
	if response.Header().Get("Content-Type") != "application/vnd.mapbox-vector-tile" {
		t.Fatalf("unexpected vector MIME type")
	}
	if response.Header().Get("Content-Encoding") != "gzip" {
		t.Fatalf("gzip encoding missing")
	}
}

func TestMissingMBTilesAndInvalidConfiguredPath(t *testing.T) {
	root := t.TempDir()
	writeFile(t, filepath.Join(root, "index.html"), []byte("ok"))
	writeFile(t, filepath.Join(root, "tour.json"), []byte(`{"map_source":{"path":"assets/maps/missing.mbtiles","map_type":"raster","format":"png","name":"Missing"}}`))
	handler := testHandler(t, root)
	response := request(t, handler, http.MethodGet, "/api/maps/metadata")
	if response.Code != http.StatusNotFound || !strings.Contains(response.Body.String(), "map_unavailable") {
		t.Fatalf("unexpected missing-map response: %d %s", response.Code, response.Body.String())
	}
	writeFile(t, filepath.Join(root, "tour.json"), []byte(`{"map_source":{"path":"../outside.mbtiles","map_type":"raster","format":"png","name":"Invalid"}}`))
	response = request(t, handler, http.MethodGet, "/api/maps/metadata")
	if response.Code != http.StatusNotFound || !strings.Contains(response.Body.String(), "map_unavailable") {
		t.Fatalf("unexpected invalid-path response: %d %s", response.Code, response.Body.String())
	}
}

func TestMetadataAndStyleEndpoint(t *testing.T) {
	root := t.TempDir()
	createMap(t, root, "mvt", "vector", "flat", 0, 0, 0, []byte("vector"))
	handler := testHandler(t, root)
	metadata := request(t, handler, http.MethodGet, "/api/maps/metadata")
	if metadata.Code != http.StatusOK || !strings.Contains(metadata.Body.String(), `"map_type":"vector"`) {
		t.Fatalf("metadata failed: %d %s", metadata.Code, metadata.Body.String())
	}
	style := request(t, handler, http.MethodGet, "/api/maps/style.json")
	if style.Code != http.StatusOK {
		t.Fatalf("style failed: %d %s", style.Code, style.Body.String())
	}
	var payload map[string]any
	if err := json.Unmarshal(style.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	sources := payload["sources"].(map[string]any)
	source := sources["offline-map"].(map[string]any)
	tiles := source["tiles"].([]any)
	if tiles[0] != "/api/maps/tiles/{z}/{x}/{y}" {
		t.Fatalf("style uses unexpected tile URL: %v", tiles)
	}
	encoded := style.Body.String()
	if strings.Contains(encoded, "glyphs") || strings.Contains(encoded, "sprite") || strings.Contains(encoded, "http://") || strings.Contains(encoded, "https://") {
		t.Fatalf("style contains external resources: %s", encoded)
	}
	if !strings.Contains(encoded, `"source-layer":"roads"`) {
		t.Fatalf("vector layer missing: %s", encoded)
	}
}

func TestNoMapConfigured(t *testing.T) {
	root := t.TempDir()
	writeFile(t, filepath.Join(root, "index.html"), []byte("ok"))
	writeFile(t, filepath.Join(root, "tour.json"), []byte(`{"map_source":null}`))
	response := request(t, testHandler(t, root), http.MethodGet, "/api/maps/metadata")
	if response.Code != http.StatusNotFound || !strings.Contains(response.Body.String(), "map_not_configured") {
		t.Fatalf("unexpected response: %d %s", response.Code, response.Body.String())
	}
}
