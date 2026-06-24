'use strict';

const BASEMAP_STYLE = 'https://tiles.openfreemap.org/styles/dark';

// ── Bootstrap: load manifest + risk points, then init map ────────────────────
Promise.all([
  fetch('data/manifest.json').then(r => r.json()),
  fetch('data/risk_points.geojson').then(r => r.json()),
])
  .then(([manifest, riskPoints]) => initMap(manifest, riskPoints))
  .catch(err => {
    document.body.innerHTML =
      `<div style="color:#e74c3c;padding:40px;font-family:monospace">
        Failed to load map data.<br>
        Run <code>python pipeline.py</code> (or <code>python export_web_assets.py</code>)
        to generate web/data/ assets first.<br><br>${err}
      </div>`;
  });

// ── Map init ──────────────────────────────────────────────────────────────────
function initMap(manifest, riskPoints) {
  const ub = manifest.union_bounds;

  const map = window._map = new maplibregl.Map({
    container: 'map',
    style: BASEMAP_STYLE,
    center: ub.center,
    zoom: 13,
    maxZoom: 20,
    minZoom: 5,
    attributionControl: false,
  });

  map.addControl(new maplibregl.NavigationControl(), 'bottom-right');
  map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
  map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');

  map.on('load', () => {
    map.fitBounds([[ub.west, ub.south], [ub.east, ub.north]],
                  { padding: 60, duration: 0 });

    // Add one set of raster layers per tile
    manifest.tiles.forEach(tile => addTileLayers(map, tile));

    // DOM markers — added inside load so map.project() is ready
    addRiskPoints(map, riskPoints);

    wireControls(map, manifest.tiles);
  });
}

// ── Raster overlays (one set per tile) ────────────────────────────────────────
const LAYER_TYPES = [
  { key: 'susceptibility', defaultOpacity: 0.75, defaultVisible: true  },
  { key: 'ndvi',           defaultOpacity: 0.75, defaultVisible: false },
  { key: 'classification', defaultOpacity: 0.80, defaultVisible: false },
];

function addTileLayers(map, tile) {
  LAYER_TYPES.forEach(({ key, defaultOpacity, defaultVisible }) => {
    map.addSource(`src-${key}-${tile.name}`, {
      type: 'image',
      url:  `data/${tile.files[key]}`,
      coordinates: tile.bounds.corners,
    });
    map.addLayer({
      id:     `layer-${key}-${tile.name}`,
      type:   'raster',
      source: `src-${key}-${tile.name}`,
      paint:  { 'raster-opacity': defaultOpacity, 'raster-resampling': 'linear' },
      layout: { visibility: defaultVisible ? 'visible' : 'none' },
    });
  });
}

// ── Risk markers ──────────────────────────────────────────────────────────────
// maplibregl.Marker calls map.project(lngLat) on every render frame —
// no async worker, no tile pipeline — so markers track the map with zero lag.
const riskMarkers = [];

function addRiskPoints(map, riskPoints) {
  const popup = new maplibregl.Popup({ offset: 18, closeButton: true });

  riskPoints.features.forEach(f => {
    const p = f.properties;
    const [lng, lat] = f.geometry.coordinates;

    const el = document.createElement('div');
    el.className = 'risk-marker';
    el.textContent = p.rank;

    el.addEventListener('click', () => {
      const tileLabel = p.tile ? `<div class="popup-row">
          <span class="popup-key">Tile</span>
          <span class="popup-val">${p.tile}</span></div>` : '';
      popup.setLngLat([lng, lat]).setHTML(`
        <div class="popup-rank">Risk location #${p.rank}</div>
        <div class="popup-row">
          <span class="popup-key">Risk score</span>
          <span class="popup-val">${(p.risk_score * 100).toFixed(1)}%</span>
        </div>
        <div class="popup-row">
          <span class="popup-key">Elevation</span>
          <span class="popup-val">${p.elevation_m} m</span>
        </div>
        <div class="popup-row">
          <span class="popup-key">Easting (3794)</span>
          <span class="popup-val">${Number(p.easting_3794).toFixed(0)}</span>
        </div>
        <div class="popup-row">
          <span class="popup-key">Northing (3794)</span>
          <span class="popup-val">${Number(p.northing_3794).toFixed(0)}</span>
        </div>
        <div class="popup-row">
          <span class="popup-key">WGS84</span>
          <span class="popup-val">${lat.toFixed(5)}°N, ${lng.toFixed(5)}°E</span>
        </div>${tileLabel}`
      ).addTo(map);
    });

    const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
      .setLngLat([lng, lat])
      .addTo(map);
    riskMarkers.push(marker);
  });
}

function setRiskVisible(visible) {
  riskMarkers.forEach(m => { m.getElement().style.display = visible ? '' : 'none'; });
}

// ── UI controls ───────────────────────────────────────────────────────────────
// Toggle IDs in HTML use short aliases: susc / ndvi / cls
const KEY_ALIAS = { susc: 'susceptibility', ndvi: 'ndvi', cls: 'classification' };

function wireControls(map, tiles) {
  const tileNames = tiles.map(t => t.name);

  Object.entries(KEY_ALIAS).forEach(([alias, key]) => {
    // Visibility toggle — applies to all tiles
    const chk = document.getElementById(`toggle-${alias}`);
    chk.addEventListener('change', () => {
      const vis = chk.checked ? 'visible' : 'none';
      tileNames.forEach(name =>
        map.setLayoutProperty(`layer-${key}-${name}`, 'visibility', vis));
    });

    // Opacity slider — applies to all tiles
    const slider = document.getElementById(`opacity-${alias}`);
    const valEl  = document.getElementById(`val-${alias}`);
    slider.addEventListener('input', () => {
      const v = slider.value / 100;
      tileNames.forEach(name =>
        map.setPaintProperty(`layer-${key}-${name}`, 'raster-opacity', v));
      valEl.textContent = slider.value + '%';
    });
  });

  document.getElementById('toggle-risk')
    .addEventListener('change', e => setRiskVisible(e.target.checked));
}
