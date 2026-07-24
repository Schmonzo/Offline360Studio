# Leaflet

Offline360 Studio bundles Leaflet 1.9.4 locally for the offline map view.

Source package: `leaflet@1.9.4` from the official npm distribution.

Runtime files:

- `leaflet.js`
- `leaflet.css`
- `images/marker-icon.png`
- `images/marker-icon-2x.png`
- `images/marker-shadow.png`

The image files are retained because the bundled Leaflet runtime and stylesheet
provide the default marker implementation even though Offline360 Studio currently
uses its own CSS marker.

Leaflet is licensed under the BSD 2-Clause License. The unmodified license text
is stored in `LICENSE.txt`.

