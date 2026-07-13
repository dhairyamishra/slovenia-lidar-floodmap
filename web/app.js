'use strict';

const BASEMAP_STYLE = 'https://tiles.openfreemap.org/styles/dark';

function optionalJson(url) {
  return fetch(url).then(r => r.ok ? r.json() : null).catch(() => null);
}

Promise.all([
  fetch('data/manifest.json').then(r => r.json()),
  fetch('data/risk_points.geojson').then(r => r.json()),
  optionalJson('data/validation/manifest.json'),
])
  .then(([manifest, riskPoints, validationManifest]) =>
    initMap(manifest, riskPoints, validationManifest))
  .catch(err => {
    document.body.innerHTML =
      `<div style="color:#e74c3c;padding:40px;font-family:monospace">
        Failed to load map data.<br>
        Run <code>python pipeline.py</code> to generate web/data/ assets first.
        <br><br>${err}
      </div>`;
  });

function initMap(manifest, riskPoints, validationManifest) {
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

    manifest.tiles.forEach(tile => addTileLayers(map, tile));
    addRiskPoints(map, riskPoints);
    setRiskVisible(false);

    initOfficialValidation(map, validationManifest).then(validationState => {
      wireControls(map, manifest.tiles, validationState);
    });
  });
}

const LAYER_TYPES = [
  // D19 is frozen and available in two non-hazard display modes. The sparse
  // review mask is the default when enabled; the full diagnostic surface is
  // deliberately separate and never visible on initial load.
  { key: 'd19_review',     defaultOpacity: 0.70, defaultVisible: false },
  { key: 'd19_diagnostic', defaultOpacity: 0.55, defaultVisible: false },
  { key: 'ndvi',           defaultOpacity: 0.75, defaultVisible: false },
  { key: 'classification', defaultOpacity: 0.80, defaultVisible: false },
];

const COASTAL_SCENARIOS = [
  { key: 'slr_0_5m', label: '+0.5 m' },
  { key: 'slr_1_0m', label: '+1.0 m' },
  { key: 'slr_2_0m', label: '+2.0 m' },
];

const OFFICIAL_SCENARIOS = [
  { key: 'q10', label: 'Q10' },
  { key: 'q100', label: 'Q100' },
  { key: 'q500', label: 'Q500' },
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

  if (tile.files.coastal) {
    COASTAL_SCENARIOS.forEach(({ key }) => {
      if (!tile.files.coastal[key]) return;
      map.addSource(`src-coastal-${key}-${tile.name}`, {
        type: 'image',
        url:  `data/${tile.files.coastal[key]}`,
        coordinates: tile.bounds.corners,
      });
      map.addLayer({
        id:     `layer-coastal-${key}-${tile.name}`,
        type:   'raster',
        source: `src-coastal-${key}-${tile.name}`,
        paint:  { 'raster-opacity': 0.70, 'raster-resampling': 'linear' },
        layout: { visibility: 'none' },
      });
    });
  }
}

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
        <div class="popup-rank">Review point #${p.rank}</div>
        <div class="popup-row">
          <span class="popup-key">Relative susceptibility</span>
          <span class="popup-val">${Number(p.risk_score).toFixed(3)}</span>
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
          <span class="popup-val">${lat.toFixed(5)}N, ${lng.toFixed(5)}E</span>
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

async function initOfficialValidation(map, validationManifest) {
  if (!validationManifest || !validationManifest.scenarios) {
    return { available: false };
  }
  const byScenario = Object.fromEntries(
    validationManifest.scenarios.map(entry => [entry.scenario, entry])
  );
  OFFICIAL_SCENARIOS.forEach(({ key }) => {
    const entry = byScenario[key];
    if (!entry) return;
    map.addSource(`src-official-${key}`, {
      type: 'geojson',
      data: `data/validation/${entry.file}`,
    });
    map.addLayer({
      id: `layer-official-${key}`,
      type: 'fill',
      source: `src-official-${key}`,
      paint: {
        'fill-color': '#38bdf8',
        'fill-opacity': 0.32,
        'fill-outline-color': '#bae6fd',
      },
      layout: { visibility: 'none' },
    });
  });
  const extra = validationManifest.layers || {};
  const validity = extra.validity;
  if (validity) {
    map.addSource('src-official-validity', {
      type: 'geojson',
      data: `data/validation/${validity.file}`,
    });
    map.addLayer({
      id: 'layer-official-validity-fill',
      type: 'fill',
      source: 'src-official-validity',
      paint: { 'fill-color': '#94a3b8', 'fill-opacity': 0.05 },
      layout: { visibility: 'none' },
    });
    map.addLayer({
      id: 'layer-official-validity-line',
      type: 'line',
      source: 'src-official-validity',
      paint: {
        'line-color': '#cbd5e1',
        'line-width': 1.4,
        'line-opacity': 0.9,
        'line-dasharray': [3, 2],
      },
      layout: { visibility: 'none' },
    });
  }

  const depthSpecs = [
    ['depth_lt_0_5m', '#bae6fd'],
    ['depth_0_5_to_1_5m', '#38bdf8'],
    ['depth_ge_1_5m', '#075985'],
  ];
  const depthKeys = [];
  depthSpecs.forEach(([key, color]) => {
    const entry = extra[key];
    if (!entry) return;
    depthKeys.push(key);
    map.addSource(`src-official-${key}`, {
      type: 'geojson',
      data: `data/validation/${entry.file}`,
    });
    map.addLayer({
      id: `layer-official-${key}`,
      type: 'fill',
      source: `src-official-${key}`,
      paint: {
        'fill-color': color,
        'fill-opacity': 0.48,
        'fill-outline-color': color,
      },
      layout: { visibility: 'none' },
    });
  });
  return { available: true, byScenario, validity: Boolean(validity), depthKeys };
}

const KEY_ALIAS = { ndvi: 'ndvi', cls: 'classification' };

function wireControls(map, tiles, validationState) {
  const tileNames = tiles.map(t => t.name);

  Object.entries(KEY_ALIAS).forEach(([alias, key]) => {
    const chk = document.getElementById(`toggle-${alias}`);
    chk.addEventListener('change', () => {
      const vis = chk.checked ? 'visible' : 'none';
      tileNames.forEach(name =>
        map.setLayoutProperty(`layer-${key}-${name}`, 'visibility', vis));
    });

    const slider = document.getElementById(`opacity-${alias}`);
    const valEl  = document.getElementById(`val-${alias}`);
    slider.addEventListener('input', () => {
      const v = slider.value / 100;
      tileNames.forEach(name =>
        map.setPaintProperty(`layer-${key}-${name}`, 'raster-opacity', v));
      valEl.textContent = slider.value + '%';
    });
  });

  wireD19Controls(map, tiles);

  document.getElementById('toggle-risk')
    .addEventListener('change', e => setRiskVisible(e.target.checked));

  const coastalTiles = tiles.filter(t => t.files.coastal);
  const coastalToggle = document.getElementById('toggle-coastal');
  const coastalScenario = document.getElementById('coastal-scenario');
  const coastalOpacity = document.getElementById('opacity-coastal');
  const coastalVal = document.getElementById('val-coastal');

  function setCoastalVisibility() {
    const activeKey = coastalScenario.value;
    const visible = coastalToggle.checked;
    coastalTiles.forEach(tile => {
      COASTAL_SCENARIOS.forEach(({ key }) => {
        if (!tile.files.coastal[key]) return;
        map.setLayoutProperty(
          `layer-coastal-${key}-${tile.name}`,
          'visibility',
          visible && key === activeKey ? 'visible' : 'none'
        );
      });
    });
  }

  if (coastalTiles.length === 0) {
    coastalToggle.disabled = true;
    coastalScenario.disabled = true;
    coastalOpacity.disabled = true;
  } else {
    coastalToggle.addEventListener('change', setCoastalVisibility);
    coastalScenario.addEventListener('change', setCoastalVisibility);
    coastalOpacity.addEventListener('input', () => {
      const v = coastalOpacity.value / 100;
      coastalTiles.forEach(tile => {
        COASTAL_SCENARIOS.forEach(({ key }) => {
          if (!tile.files.coastal[key]) return;
          map.setPaintProperty(`layer-coastal-${key}-${tile.name}`, 'raster-opacity', v);
        });
      });
      coastalVal.textContent = coastalOpacity.value + '%';
    });
  }

  wireOfficialValidationControls(map, validationState);
}

function wireD19Controls(map, tiles) {
  const toggle = document.getElementById('toggle-susc');
  const mode = document.getElementById('d19-display-mode');
  const opacity = document.getElementById('opacity-susc');
  const value = document.getElementById('val-susc');
  const keys = ['d19_review', 'd19_diagnostic'];
  const tileNames = tiles.map(tile => tile.name);

  function updateVisibility() {
    keys.forEach(key => {
      tileNames.forEach(name => {
        const layerId = `layer-${key}-${name}`;
        if (!map.getLayer(layerId)) return;
        map.setLayoutProperty(
          layerId,
          'visibility',
          toggle.checked && mode.value === key ? 'visible' : 'none'
        );
      });
    });
  }

  toggle.addEventListener('change', updateVisibility);
  mode.addEventListener('change', updateVisibility);
  opacity.addEventListener('input', () => {
    const next = opacity.value / 100;
    keys.forEach(key => tileNames.forEach(name => {
      const layerId = `layer-${key}-${name}`;
      if (map.getLayer(layerId)) map.setPaintProperty(layerId, 'raster-opacity', next);
    }));
    value.textContent = opacity.value + '%';
  });
}

function wireOfficialValidationControls(map, validationState) {
  const toggle = document.getElementById('toggle-official');
  const scenario = document.getElementById('official-scenario');
  const opacity = document.getElementById('opacity-official');
  const value = document.getElementById('val-official');
  const validityToggle = document.getElementById('toggle-official-validity');
  const depthToggle = document.getElementById('toggle-official-depth');
  const comparisonToggle = document.getElementById('toggle-q100-comparison');
  const d19Toggle = document.getElementById('toggle-susc');
  const d19Mode = document.getElementById('d19-display-mode');

  if (!validationState || !validationState.available) {
    toggle.disabled = true;
    scenario.disabled = true;
    opacity.disabled = true;
    validityToggle.disabled = true;
    depthToggle.disabled = true;
    comparisonToggle.disabled = true;
    return;
  }

  validityToggle.disabled = !validationState.validity;
  depthToggle.disabled = validationState.depthKeys.length === 0;

  function updateVisibility() {
    OFFICIAL_SCENARIOS.forEach(({ key }) => {
      if (!validationState.byScenario[key]) return;
      map.setLayoutProperty(
        `layer-official-${key}`,
        'visibility',
        toggle.checked && scenario.value === key ? 'visible' : 'none'
      );
    });
    if (validationState.validity) {
      const visibility = validityToggle.checked ? 'visible' : 'none';
      map.setLayoutProperty('layer-official-validity-fill', 'visibility', visibility);
      map.setLayoutProperty('layer-official-validity-line', 'visibility', visibility);
    }
    validationState.depthKeys.forEach(key => {
      map.setLayoutProperty(
        `layer-official-${key}`,
        'visibility',
        toggle.checked && depthToggle.checked && scenario.value === 'q100' ? 'visible' : 'none'
      );
    });
  }
  toggle.addEventListener('change', updateVisibility);
  scenario.addEventListener('change', updateVisibility);
  validityToggle.addEventListener('change', updateVisibility);
  depthToggle.addEventListener('change', updateVisibility);
  comparisonToggle.addEventListener('change', () => {
    const enabled = comparisonToggle.checked;
    toggle.checked = enabled;
    validityToggle.checked = enabled;
    d19Toggle.checked = enabled;
    if (enabled) {
      scenario.value = 'q100';
      depthToggle.checked = false;
      d19Mode.value = 'd19_review';
    }
    d19Toggle.dispatchEvent(new Event('change'));
    updateVisibility();
  });
  opacity.addEventListener('input', () => {
    const next = opacity.value / 100;
    OFFICIAL_SCENARIOS.forEach(({ key }) => {
      if (validationState.byScenario[key]) {
        map.setPaintProperty(`layer-official-${key}`, 'fill-opacity', next);
      }
    });
    value.textContent = opacity.value + '%';
  });
}
