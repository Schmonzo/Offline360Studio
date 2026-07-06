package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"mime"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"os/signal"
	slashpath "path"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"time"

	_ "modernc.org/sqlite"
)

const (
	defaultHost = "127.0.0.1"
	maxZoom     = 30
)

var contentTypes = map[string]string{
	".html":    "text/html; charset=utf-8",
	".json":    "application/json; charset=utf-8",
	".js":      "text/javascript; charset=utf-8",
	".css":     "text/css; charset=utf-8",
	".jpg":     "image/jpeg",
	".jpeg":    "image/jpeg",
	".png":     "image/png",
	".webp":    "image/webp",
	".mp4":     "video/mp4",
	".gpx":     "application/gpx+xml",
	".pbf":     "application/vnd.mapbox-vector-tile",
	".mvt":     "application/vnd.mapbox-vector-tile",
	".mbtiles": "application/vnd.sqlite3",
	".woff":    "font/woff",
	".woff2":   "font/woff2",
}

type mapConfig struct {
	Path        string `json:"path"`
	MapType     string `json:"map_type"`
	Format      string `json:"format"`
	Name        string `json:"name"`
	Attribution string `json:"attribution"`
	Bounds      string `json:"bounds"`
	Center      string `json:"center"`
	MinZoom     *int   `json:"min_zoom"`
	MaxZoom     *int   `json:"max_zoom"`
}

type tourConfig struct {
	MapSource *mapConfig `json:"map_source"`
}

type portableHandler struct {
	root string
}

type apiError struct {
	Error struct {
		Code    string `json:"code"`
		Message string `json:"message"`
	} `json:"error"`
}

func main() {
	port := flag.Int("port", 0, "TCP-Port (0 wählt automatisch einen freien Port)")
	root := flag.String("root", "", "Webroot (Standard: Verzeichnis von server.exe)")
	flag.Parse()

	if *port < 0 || *port > 65535 {
		log.Fatal("--port muss zwischen 0 und 65535 liegen")
	}
	webroot, err := resolveWebroot(*root)
	if err != nil {
		log.Fatal(err)
	}
	handler, err := newPortableHandler(webroot)
	if err != nil {
		log.Fatal(err)
	}
	listener, err := listen(*port)
	if err != nil {
		log.Fatalf("Server konnte nicht gestartet werden: %v", err)
	}
	defer listener.Close()

	server := &http.Server{
		Handler:           handler,
		ReadHeaderTimeout: 10 * time.Second,
		IdleTimeout:       60 * time.Second,
	}
	url := "http://" + listener.Addr().String() + "/"
	fmt.Printf("Panorama Studio Portable Tour: %s\n", url)
	fmt.Println("Zum Beenden Strg+C drücken.")
	go func() {
		if err := openBrowser(url); err != nil {
			log.Printf("Browser konnte nicht automatisch geöffnet werden: %v", err)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-stop
		fmt.Println("\nServer wird beendet …")
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := server.Shutdown(ctx); err != nil {
			log.Printf("Fehler beim Beenden: %v", err)
		}
	}()

	if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}

func resolveWebroot(value string) (string, error) {
	if value == "" {
		executable, err := os.Executable()
		if err != nil {
			return "", fmt.Errorf("Pfad von server.exe konnte nicht bestimmt werden: %w", err)
		}
		value = filepath.Dir(executable)
	}
	absolute, err := filepath.Abs(value)
	if err != nil {
		return "", fmt.Errorf("Webroot ist ungültig: %w", err)
	}
	resolved, err := filepath.EvalSymlinks(absolute)
	if err != nil {
		return "", fmt.Errorf("Webroot ist nicht verfügbar: %w", err)
	}
	info, err := os.Stat(resolved)
	if err != nil || !info.IsDir() {
		return "", fmt.Errorf("Webroot ist kein lesbares Verzeichnis: %s", resolved)
	}
	return filepath.Clean(resolved), nil
}

func newPortableHandler(root string) (http.Handler, error) {
	resolved, err := resolveWebroot(root)
	if err != nil {
		return nil, err
	}
	return &portableHandler{root: resolved}, nil
}

func listen(port int) (net.Listener, error) {
	return net.Listen("tcp4", net.JoinHostPort(defaultHost, strconv.Itoa(port)))
}

func openBrowser(url string) error {
	if runtime.GOOS != "windows" {
		return fmt.Errorf("automatischer Browserstart ist nur unter Windows verfügbar")
	}
	return exec.Command("rundll32", "url.dll,FileProtocolHandler", url).Start()
}

func (h *portableHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Referrer-Policy", "no-referrer")
	switch {
	case r.URL.Path == "/api/maps/metadata":
		h.serveMapMetadata(w, r)
	case strings.HasPrefix(r.URL.Path, "/api/maps/tiles/"):
		h.serveMapTile(w, r)
	case r.URL.Path == "/api/maps/style.json":
		h.serveMapStyle(w, r)
	case strings.HasPrefix(r.URL.Path, "/api/"):
		writeAPIError(w, http.StatusNotFound, "api_not_found", "Der API-Endpunkt wurde nicht gefunden.")
	default:
		h.serveStatic(w, r)
	}
}

func (h *portableHandler) serveStatic(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		w.Header().Set("Allow", "GET, HEAD")
		http.Error(w, "Methode nicht erlaubt.", http.StatusMethodNotAllowed)
		return
	}
	requestPath := r.URL.Path
	if requestPath == "/" {
		requestPath = "/index.html"
	}
	target, err := h.secureFile(requestPath, "")
	if err != nil {
		http.NotFound(w, r)
		return
	}
	info, err := os.Stat(target)
	if err != nil || !info.Mode().IsRegular() {
		http.NotFound(w, r)
		return
	}
	extension := strings.ToLower(filepath.Ext(target))
	contentType := contentTypes[extension]
	if contentType == "" {
		contentType = mime.TypeByExtension(extension)
	}
	if contentType == "" {
		contentType = "application/octet-stream"
	}
	w.Header().Set("Content-Type", contentType)
	name := strings.ToLower(filepath.Base(target))
	if name == "index.html" || name == "tour.json" {
		w.Header().Set("Cache-Control", "no-store")
	} else {
		w.Header().Set("Cache-Control", "public, max-age=3600")
	}
	http.ServeFile(w, r, target)
}

func (h *portableHandler) secureFile(requestPath, requiredPrefix string) (string, error) {
	if requestPath == "" || strings.Contains(requestPath, "\\") || strings.ContainsRune(requestPath, '\x00') {
		return "", errors.New("ungültiger Pfad")
	}
	for _, segment := range strings.Split(requestPath, "/") {
		if segment == ".." {
			return "", errors.New("Pfad verlässt Webroot")
		}
	}
	cleaned := slashpath.Clean("/" + strings.TrimPrefix(requestPath, "/"))
	relative := strings.TrimPrefix(cleaned, "/")
	if relative == "" || (requiredPrefix != "" && !strings.HasPrefix(relative, requiredPrefix)) {
		return "", errors.New("Pfad ist nicht erlaubt")
	}
	candidate := filepath.Join(h.root, filepath.FromSlash(relative))
	resolved, err := filepath.EvalSymlinks(candidate)
	if err != nil {
		return "", err
	}
	if !pathInside(resolved, h.root) {
		return "", errors.New("Symlink verlässt Webroot")
	}
	if requiredPrefix != "" {
		prefixRoot, err := filepath.EvalSymlinks(filepath.Join(h.root, filepath.FromSlash(strings.TrimSuffix(requiredPrefix, "/"))))
		if err != nil || !pathInside(resolved, prefixRoot) {
			return "", errors.New("Pfad verlässt erlaubtes Kartenverzeichnis")
		}
	}
	return resolved, nil
}

func pathInside(candidate, root string) bool {
	relative, err := filepath.Rel(root, candidate)
	return err == nil && relative != ".." && !strings.HasPrefix(relative, ".."+string(filepath.Separator)) && !filepath.IsAbs(relative)
}

func writeAPIError(w http.ResponseWriter, status int, code, message string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	var payload apiError
	payload.Error.Code = code
	payload.Error.Message = message
	_ = json.NewEncoder(w).Encode(payload)
}

func requireGET(w http.ResponseWriter, r *http.Request) bool {
	if r.Method == http.MethodGet || r.Method == http.MethodHead {
		return true
	}
	w.Header().Set("Allow", "GET, HEAD")
	writeAPIError(w, http.StatusMethodNotAllowed, "method_not_allowed", "Nur GET und HEAD sind erlaubt.")
	return false
}

func (h *portableHandler) loadMap() (*mapConfig, string, error) {
	tourPath, err := h.secureFile("/tour.json", "")
	if err != nil {
		return nil, "", fmt.Errorf("tour.json fehlt")
	}
	file, err := os.Open(tourPath)
	if err != nil {
		return nil, "", fmt.Errorf("tour.json konnte nicht gelesen werden")
	}
	defer file.Close()
	var tour tourConfig
	decoder := json.NewDecoder(io.LimitReader(file, 4*1024*1024))
	if err := decoder.Decode(&tour); err != nil {
		return nil, "", fmt.Errorf("tour.json ist ungültig")
	}
	if tour.MapSource == nil || tour.MapSource.Path == "" {
		return nil, "", os.ErrNotExist
	}
	if filepath.IsAbs(tour.MapSource.Path) || strings.Contains(tour.MapSource.Path, "\\") {
		return nil, "", errors.New("Kartenpfad ist ungültig")
	}
	mapPath, err := h.secureFile("/"+tour.MapSource.Path, "assets/maps/")
	if err != nil || strings.ToLower(filepath.Ext(mapPath)) != ".mbtiles" {
		return nil, "", errors.New("Kartenpfad ist ungültig")
	}
	return tour.MapSource, mapPath, nil
}

func openMapDatabase(path string) (*sql.DB, error) {
	urlPath := filepath.ToSlash(path)
	if filepath.VolumeName(path) != "" && !strings.HasPrefix(urlPath, "/") {
		urlPath = "/" + urlPath
	}
	dsn := (&url.URL{
		Scheme:   "file",
		Path:     urlPath,
		RawQuery: "mode=ro&immutable=1",
	}).String()
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	if err := db.Ping(); err != nil {
		db.Close()
		return nil, err
	}
	return db, nil
}

func (h *portableHandler) serveMapMetadata(w http.ResponseWriter, r *http.Request) {
	if !requireGET(w, r) {
		return
	}
	config, _, err := h.loadMap()
	if err != nil {
		writeMapLoadError(w, err)
		return
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	_ = json.NewEncoder(w).Encode(config)
}

func writeMapLoadError(w http.ResponseWriter, err error) {
	if errors.Is(err, os.ErrNotExist) {
		writeAPIError(w, http.StatusNotFound, "map_not_configured", "Diese Tour enthält keine Offline-Karte.")
		return
	}
	writeAPIError(w, http.StatusNotFound, "map_unavailable", err.Error())
}

func parseTilePath(value string) (int, int, int, error) {
	parts := strings.Split(strings.TrimPrefix(value, "/api/maps/tiles/"), "/")
	if len(parts) != 3 {
		return 0, 0, 0, errors.New("ungültige Kachelkoordinaten")
	}
	values := make([]int, 3)
	for index, part := range parts {
		number, err := strconv.Atoi(part)
		if err != nil || number < 0 {
			return 0, 0, 0, errors.New("ungültige Kachelkoordinaten")
		}
		values[index] = number
	}
	z, x, y := values[0], values[1], values[2]
	if z > maxZoom || int64(x) >= int64(1)<<uint(z) || int64(y) >= int64(1)<<uint(z) {
		return 0, 0, 0, errors.New("Kachelkoordinaten außerhalb des gültigen Bereichs")
	}
	return z, x, y, nil
}

func xyzToTMS(z, y int) int {
	return (1 << uint(z)) - 1 - y
}

func (h *portableHandler) serveMapTile(w http.ResponseWriter, r *http.Request) {
	if !requireGET(w, r) {
		return
	}
	z, x, y, err := parseTilePath(r.URL.Path)
	if err != nil {
		writeAPIError(w, http.StatusBadRequest, "invalid_tile", err.Error())
		return
	}
	config, mapPath, err := h.loadMap()
	if err != nil {
		writeMapLoadError(w, err)
		return
	}
	db, err := openMapDatabase(mapPath)
	if err != nil {
		writeAPIError(w, http.StatusInternalServerError, "map_open_failed", "Die MBTiles-Datei konnte nicht geöffnet werden.")
		return
	}
	defer db.Close()
	tile, err := readTile(db, z, x, xyzToTMS(z, y))
	if errors.Is(err, sql.ErrNoRows) {
		writeAPIError(w, http.StatusNotFound, "tile_not_found", "Die Kachel ist nicht vorhanden.")
		return
	}
	if err != nil {
		writeAPIError(w, http.StatusInternalServerError, "map_read_failed", "Die MBTiles-Datei konnte nicht gelesen werden.")
		return
	}
	contentType, vector := tileContentType(config.Format)
	if contentType == "" {
		writeAPIError(w, http.StatusUnsupportedMediaType, "map_format_unsupported", "Das Kartenformat wird nicht unterstützt.")
		return
	}
	w.Header().Set("Content-Type", contentType)
	w.Header().Set("Cache-Control", "public, max-age=86400")
	if vector && len(tile) >= 2 && tile[0] == 0x1f && tile[1] == 0x8b {
		w.Header().Set("Content-Encoding", "gzip")
	}
	w.WriteHeader(http.StatusOK)
	if r.Method != http.MethodHead {
		_, _ = w.Write(tile)
	}
}

func readTile(db *sql.DB, z, x, tmsY int) ([]byte, error) {
	var hasTiles, hasMap, hasImages int
	if err := db.QueryRow("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='tiles'").Scan(&hasTiles); err != nil {
		return nil, err
	}
	var tile []byte
	if hasTiles > 0 {
		err := db.QueryRow(
			"SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
			z, x, tmsY,
		).Scan(&tile)
		return tile, err
	}
	if err := db.QueryRow("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='map'").Scan(&hasMap); err != nil {
		return nil, err
	}
	if err := db.QueryRow("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='images'").Scan(&hasImages); err != nil {
		return nil, err
	}
	if hasMap == 0 || hasImages == 0 {
		return nil, errors.New("unbekanntes MBTiles-Schema")
	}
	err := db.QueryRow(
		`SELECT images.tile_data FROM map
		 JOIN images ON images.tile_id=map.tile_id
		 WHERE map.zoom_level=? AND map.tile_column=? AND map.tile_row=?`,
		z, x, tmsY,
	).Scan(&tile)
	return tile, err
}

func tileContentType(format string) (string, bool) {
	switch strings.ToLower(format) {
	case "png":
		return "image/png", false
	case "jpg", "jpeg":
		return "image/jpeg", false
	case "webp":
		return "image/webp", false
	case "pbf", "mvt":
		return "application/vnd.mapbox-vector-tile", true
	default:
		return "", false
	}
}

type vectorMetadata struct {
	VectorLayers []struct {
		ID string `json:"id"`
	} `json:"vector_layers"`
}

func vectorLayerIDs(db *sql.DB) []string {
	var raw string
	if err := db.QueryRow("SELECT value FROM metadata WHERE name='json' LIMIT 1").Scan(&raw); err != nil {
		return nil
	}
	var metadata vectorMetadata
	if json.Unmarshal([]byte(raw), &metadata) != nil {
		return nil
	}
	var result []string
	for _, layer := range metadata.VectorLayers {
		if layer.ID != "" {
			result = append(result, layer.ID)
		}
	}
	return result
}

func (h *portableHandler) serveMapStyle(w http.ResponseWriter, r *http.Request) {
	if !requireGET(w, r) {
		return
	}
	config, mapPath, err := h.loadMap()
	if err != nil {
		writeMapLoadError(w, err)
		return
	}
	if config.MapType != "vector" {
		writeAPIError(w, http.StatusNotFound, "style_not_available", "Für Rasterkarten ist kein MapLibre-Stil erforderlich.")
		return
	}
	db, err := openMapDatabase(mapPath)
	if err != nil {
		writeAPIError(w, http.StatusInternalServerError, "map_open_failed", "Die MBTiles-Datei konnte nicht geöffnet werden.")
		return
	}
	defer db.Close()

	source := map[string]any{
		"type":        "vector",
		"tiles":       []string{"/api/maps/tiles/{z}/{x}/{y}"},
		"scheme":      "xyz",
		"attribution": config.Attribution,
	}
	if config.MinZoom != nil {
		source["minzoom"] = *config.MinZoom
	}
	if config.MaxZoom != nil {
		source["maxzoom"] = *config.MaxZoom
	}
	layers := []map[string]any{{
		"id": "background", "type": "background",
		"paint": map[string]any{"background-color": "#11151d"},
	}}
	colors := []string{"#5e81ac", "#88c0d0", "#a3be8c", "#d08770", "#b48ead"}
	for index, layerID := range vectorLayerIDs(db) {
		color := colors[index%len(colors)]
		base := map[string]any{"source": "offline-map", "source-layer": layerID}
		layers = append(layers,
			mergeLayer(base, map[string]any{
				"id": "fill-" + strconv.Itoa(index), "type": "fill",
				"filter": []any{"==", []any{"geometry-type"}, "Polygon"},
				"paint": map[string]any{"fill-color": color, "fill-opacity": 0.45},
			}),
			mergeLayer(base, map[string]any{
				"id": "line-" + strconv.Itoa(index), "type": "line",
				"filter": []any{"==", []any{"geometry-type"}, "LineString"},
				"paint": map[string]any{"line-color": color, "line-width": 1.5},
			}),
			mergeLayer(base, map[string]any{
				"id": "point-" + strconv.Itoa(index), "type": "circle",
				"filter": []any{"==", []any{"geometry-type"}, "Point"},
				"paint": map[string]any{"circle-color": color, "circle-radius": 3},
			}),
		)
	}
	style := map[string]any{
		"version": 8,
		"name":    config.Name,
		"sources": map[string]any{"offline-map": source},
		"layers":  layers,
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	_ = json.NewEncoder(w).Encode(style)
}

func mergeLayer(base, values map[string]any) map[string]any {
	result := make(map[string]any, len(base)+len(values))
	for key, value := range base {
		result[key] = value
	}
	for key, value := range values {
		result[key] = value
	}
	return result
}
