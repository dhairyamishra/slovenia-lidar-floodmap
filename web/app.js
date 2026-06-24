'use strict';

// ── Constants ────────────────────────────────────────────────────────────────
const BASEMAP_STYLE = 'https://tiles.openfreemap.org/styles/dark';

const RISK_POINTS = {"type":"FeatureCollection","features":[
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.728729,45.80237]},"properties":{"rank":1,"risk_score":1.0,"elevation_m":422.9,"easting_3794":478913.9,"northing_3794":73647.9}},
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.727857,45.80176]},"properties":{"rank":2,"risk_score":1.0,"elevation_m":423.0,"easting_3794":478845.9,"northing_3794":73579.9}},
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.726148,45.80400]},"properties":{"rank":3,"risk_score":1.0,"elevation_m":423.3,"easting_3794":478713.9,"northing_3794":73829.9}},
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.724471,45.80493]},"properties":{"rank":4,"risk_score":1.0,"elevation_m":423.6,"easting_3794":478583.9,"northing_3794":73933.9}},
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.725577,45.80494]},"properties":{"rank":5,"risk_score":1.0,"elevation_m":422.4,"easting_3794":478669.9,"northing_3794":73933.9}},
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.728194,45.80120]},"properties":{"rank":6,"risk_score":1.0,"elevation_m":423.4,"easting_3794":478871.9,"northing_3794":73517.9}},
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.727865,45.80554]},"properties":{"rank":7,"risk_score":1.0,"elevation_m":422.0,"easting_3794":478847.9,"northing_3794":73999.9}},
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.726375,45.80494]},"properties":{"rank":8,"risk_score":1.0,"elevation_m":422.5,"easting_3794":478731.9,"northing_3794":73933.9}},
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.726296,45.80532]},"properties":{"rank":9,"risk_score":1.0,"elevation_m":422.2,"easting_3794":478725.9,"northing_3794":73975.9}},
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.725294,45.80494]},"properties":{"rank":10,"risk_score":1.0,"elevation_m":422.6,"easting_3794":478647.9,"northing_3794":73933.9}},
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.729727,45.80358]},"properties":{"rank":11,"risk_score":1.0,"elevation_m":423.2,"easting_3794":478991.9,"northing_3794":73781.9}},
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.729249,45.80120]},"properties":{"rank":12,"risk_score":1.0,"elevation_m":423.4,"easting_3794":478953.9,"northing_3794":73517.9}},
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.729585,45.80099]},"properties":{"rank":13,"risk_score":1.0,"elevation_m":423.5,"easting_3794":478979.9,"northing_3794":73493.9}},
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.726690,45.80372]},"properties":{"rank":14,"risk_score":1.0,"elevation_m":422.9,"easting_3794":478755.9,"northing_3794":73797.9}},
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.724339,45.80553]},"properties":{"rank":15,"risk_score":1.0,"elevation_m":423.7,"easting_3794":478573.9,"northing_3794":73999.9}},
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.723928,45.80553]},"properties":{"rank":16,"risk_score":1.0,"elevation_m":426.3,"easting_3794":478541.9,"northing_3794":73999.9}},
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.729372,45.80241]},"properties":{"rank":17,"risk_score":1.0,"elevation_m":423.2,"easting_3794":478963.9,"northing_3794":73651.9}},
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.727237,45.80242]},"properties":{"rank":18,"risk_score":1.0,"elevation_m":422.9,"easting_3794":478797.9,"northing_3794":73653.9}},
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.728446,45.80242]},"properties":{"rank":19,"risk_score":1.0,"elevation_m":422.8,"easting_3794":478891.9,"northing_3794":73653.9}},
  {"type":"Feature","geometry":{"type":"Point","coordinates":[14.728607,45.80093]},"properties":{"rank":20,"risk_score":1.0,"elevation_m":423.2,"easting_3794":478903.9,"northing_3794":73487.9}}
]};

// ── Bootstrap ────────────────────────────────────────────────────────────────
fetch('data/bounds.json')
  .then(r => r.json())
  .then(bounds => initMap(bounds))
  .catch(err => {
    document.body.innerHTML =
      `<div style="color:#e74c3c;padding:40px;font-family:monospace">
        Failed to load data/bounds.json — run export_web_assets.py first.<br>${err}
      </div>`;
  });

function initMap(bounds) {
  const center  = bounds.center;   // [lon, lat]
  const corners = bounds.corners;  // [[lon,lat] x4] TL TR BR BL

  const map = window._map = new maplibregl.Map({
    container: 'map',
    style: BASEMAP_STYLE,
    center: center,
    zoom: 13,
    maxZoom: 20,
    minZoom: 5,
    attributionControl: false,
  });

  map.addControl(new maplibregl.NavigationControl(), 'bottom-right');
  map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
  map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');

  // Everything waits for 'load' so the map projection is fully initialised
  // before we calculate any screen positions.
  map.on('load', () => {
    map.fitBounds(
      [[bounds.west, bounds.south], [bounds.east, bounds.north]],
      { padding: 60, duration: 0 }
    );
    addOverlays(map, corners);
    addRiskPoints(map);   // DOM markers — after load so project() is ready
    wireControls(map);
  });
}

// ── Raster overlays ──────────────────────────────────────────────────────────
function addOverlays(map, corners) {
  const layers = [
    { id: 'susc', file: 'data/susceptibility.png', opacity: 0.75, visible: true  },
    { id: 'ndvi', file: 'data/ndvi.png',            opacity: 0.75, visible: false },
    { id: 'cls',  file: 'data/classification.png',  opacity: 0.80, visible: false },
  ];

  layers.forEach(({ id, file, opacity, visible }) => {
    map.addSource(`src-${id}`, {
      type: 'image',
      url: file,
      coordinates: corners,
    });
    map.addLayer({
      id: `layer-${id}`,
      type: 'raster',
      source: `src-${id}`,
      paint: { 'raster-opacity': opacity, 'raster-resampling': 'linear' },
      layout: { visibility: visible ? 'visible' : 'none' },
    });
  });
}

// ── Risk point markers ────────────────────────────────────────────────────────
// Uses maplibregl.Marker (DOM-based). Markers call map.project(lngLat) on
// every render frame — no async web worker involved, so there is zero lag
// against the basemap during pan or zoom. Must be created AFTER map.on('load')
// so the projection transform is initialised before the first project() call.
const riskMarkers = [];

function addRiskPoints(map) {
  const popup = new maplibregl.Popup({ offset: 18, closeButton: true });

  RISK_POINTS.features.forEach(f => {
    const p = f.properties;
    const [lng, lat] = f.geometry.coordinates;

    const el = document.createElement('div');
    el.className = 'risk-marker';
    el.textContent = p.rank;

    el.addEventListener('click', () => {
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
          <span class="popup-val">${p.easting_3794.toFixed(0)}</span>
        </div>
        <div class="popup-row">
          <span class="popup-key">Northing (3794)</span>
          <span class="popup-val">${p.northing_3794.toFixed(0)}</span>
        </div>
        <div class="popup-row">
          <span class="popup-key">WGS84</span>
          <span class="popup-val">${lat.toFixed(5)}°N, ${lng.toFixed(5)}°E</span>
        </div>`
      ).addTo(map);
    });

    const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
      .setLngLat([lng, lat])
      .addTo(map);

    riskMarkers.push(marker);
  });
}

function setRiskVisible(visible) {
  riskMarkers.forEach(m => {
    m.getElement().style.display = visible ? '' : 'none';
  });
}

// ── UI controls ───────────────────────────────────────────────────────────────
function wireControls(map) {
  ['susc', 'ndvi', 'cls'].forEach(id => {
    const chk = document.getElementById(`toggle-${id}`);
    chk.addEventListener('change', () => {
      map.setLayoutProperty(`layer-${id}`, 'visibility', chk.checked ? 'visible' : 'none');
    });

    const slider = document.getElementById(`opacity-${id}`);
    const valEl  = document.getElementById(`val-${id}`);
    slider.addEventListener('input', () => {
      map.setPaintProperty(`layer-${id}`, 'raster-opacity', slider.value / 100);
      valEl.textContent = slider.value + '%';
    });
  });

  document.getElementById('toggle-risk')
    .addEventListener('change', e => setRiskVisible(e.target.checked));
}
