'use strict';

const BASEMAP_STYLE = 'https://tiles.openfreemap.org/styles/dark';

function optionalJson(url) {
  return fetch(url).then(r => r.ok ? r.json() : null).catch(() => null);
}

Promise.all([
  fetch('data/manifest.json').then(r => r.json()),
  fetch('data/risk_points.geojson').then(r => r.json()),
  optionalJson('data/hydroclimate/manifest.json'),
  optionalJson('data/validation/manifest.json'),
])
  .then(([manifest, riskPoints, hydroManifest, validationManifest]) =>
    initMap(manifest, riskPoints, hydroManifest, validationManifest))
  .catch(err => {
    document.body.innerHTML =
      `<div style="color:#e74c3c;padding:40px;font-family:monospace">
        Failed to load map data.<br>
        Run <code>python pipeline.py</code> to generate web/data/ assets first.
        <br><br>${err}
      </div>`;
  });

function initMap(manifest, riskPoints, hydroManifest, validationManifest) {
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

    Promise.all([
      initHydroClimate(map, hydroManifest),
      initOfficialValidation(map, validationManifest),
    ]).then(([hydroState, validationState]) => {
      wireControls(map, manifest.tiles, hydroState, validationState);
    });
  });
}

const LAYER_TYPES = [
  // D19 remains available as a transparent baseline, but it is not the default:
  // its region-relative score is unvalidated and the committed raster saturates
  // most land with alarm colours (see ALEKS_REVIEW_AND_ALGORITHM_PLAN.md).
  { key: 'susceptibility', defaultOpacity: 0.55, defaultVisible: false },
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
const hydroRiskMarkers = [];

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

function clearHydroRiskMarkers() {
  while (hydroRiskMarkers.length) {
    hydroRiskMarkers.pop().remove();
  }
}

function addHydroRiskPoints(map, riskPoints, visible) {
  clearHydroRiskMarkers();
  if (!riskPoints || !riskPoints.features) return;

  const popup = new maplibregl.Popup({ offset: 18, closeButton: true });
  riskPoints.features.forEach(f => {
    const p = f.properties;
    const [lng, lat] = f.geometry.coordinates;
    const el = document.createElement('div');
    el.className = 'risk-marker hydro-risk-marker';
    el.textContent = p.rank;
    el.style.display = visible ? '' : 'none';

    el.addEventListener('click', () => {
      popup.setLngLat([lng, lat]).setHTML(`
        <div class="popup-rank">Synthetic trigger review #${p.rank}</div>
        <div class="popup-row">
          <span class="popup-key">Combined index</span>
          <span class="popup-val">${Number(p.event_score).toFixed(3)}</span>
        </div>
        <div class="popup-row">
          <span class="popup-key">Terrain index</span>
          <span class="popup-val">${Number(p.static_risk_score).toFixed(3)}</span>
        </div>
        <div class="popup-row">
          <span class="popup-key">Hydro index</span>
          <span class="popup-val">${Number(p.hydro_index).toFixed(3)}</span>
        </div>
        <div class="popup-row">
          <span class="popup-key">Soil moisture</span>
          <span class="popup-val">${Number(p.soil_moisture_norm).toFixed(3)}</span>
        </div>
        <div class="popup-row">
          <span class="popup-key">90-day water</span>
          <span class="popup-val">${Number(p.water90_norm).toFixed(3)}</span>
        </div>
        <div class="popup-row">
          <span class="popup-key">Tile</span>
          <span class="popup-val">${p.tile || 'n/a'}</span>
        </div>`
      ).addTo(map);
    });

    hydroRiskMarkers.push(
      new maplibregl.Marker({ element: el, anchor: 'center' })
        .setLngLat([lng, lat])
        .addTo(map)
    );
  });
}

function setHydroRiskVisible(visible) {
  hydroRiskMarkers.forEach(m => { m.getElement().style.display = visible ? '' : 'none'; });
}

async function initHydroClimate(map, hydroManifest) {
  const emptyState = { available: false };
  if (!hydroManifest || !hydroManifest.dates || hydroManifest.dates.length === 0) {
    return emptyState;
  }

  const firstDate = hydroManifest.dates[0];
  const hydroData = await optionalJson(`data/hydroclimate/${firstDate.hydro_file}`);
  const dynamicRisk = await optionalJson(`data/hydroclimate/${firstDate.dynamic_risk_file}`);
  if (!hydroData) return emptyState;

  map.addSource('src-hydro-trigger', {
    type: 'geojson',
    data: hydroData,
  });
  map.addLayer({
    id: 'layer-hydro-trigger',
    type: 'fill',
    source: 'src-hydro-trigger',
    paint: {
      'fill-color': [
        'interpolate',
        ['linear'],
        ['get', 'hydro_index'],
        0.0, '#1d4ed8',
        0.35, '#22c55e',
        0.55, '#facc15',
        0.75, '#f97316',
        1.0, '#dc2626',
      ],
      'fill-opacity': 0.55,
      'fill-outline-color': 'rgba(255,255,255,0.20)',
    },
    layout: { visibility: 'none' },
  });

  const popup = new maplibregl.Popup({ closeButton: true });
  map.on('click', 'layer-hydro-trigger', e => {
    const p = e.features[0].properties;
    popup.setLngLat(e.lngLat).setHTML(`
        <div class="popup-rank">Synthetic hydroclimate fixture</div>
        <div class="popup-row">
          <span class="popup-key">Hydro index</span>
          <span class="popup-val">${Number(p.hydro_index).toFixed(3)}</span>
      </div>
      <div class="popup-row">
        <span class="popup-key">Soil moisture</span>
          <span class="popup-val">${Number(p.soil_moisture_norm).toFixed(3)}</span>
      </div>
      <div class="popup-row">
        <span class="popup-key">90-day water</span>
          <span class="popup-val">${Number(p.water90_norm).toFixed(3)}</span>
      </div>
      <div class="popup-row">
        <span class="popup-key">Wetting trend</span>
          <span class="popup-val">${Number(p.wetting_trend_norm).toFixed(3)}</span>
      </div>`
    ).addTo(map);
  });
  map.on('mouseenter', 'layer-hydro-trigger', () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', 'layer-hydro-trigger', () => { map.getCanvas().style.cursor = ''; });

  addHydroRiskPoints(map, dynamicRisk, false);

  return {
    available: true,
    manifest: hydroManifest,
    activeDate: firstDate.date,
    datesByValue: Object.fromEntries(hydroManifest.dates.map(d => [d.date, d])),
  };
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
  return { available: true, byScenario };
}

async function setHydroDate(map, hydroState, date, markersVisible) {
  const entry = hydroState.datesByValue[date];
  if (!entry) return;
  const hydroData = await optionalJson(`data/hydroclimate/${entry.hydro_file}`);
  const dynamicRisk = await optionalJson(`data/hydroclimate/${entry.dynamic_risk_file}`);
  if (hydroData) {
    map.getSource('src-hydro-trigger').setData(hydroData);
    hydroState.activeDate = date;
  }
  addHydroRiskPoints(map, dynamicRisk, markersVisible);
}

const KEY_ALIAS = { susc: 'susceptibility', ndvi: 'ndvi', cls: 'classification' };

function wireControls(map, tiles, hydroState, validationState) {
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

  wireHydroControls(map, hydroState);
  wireOfficialValidationControls(map, validationState);
}

function wireOfficialValidationControls(map, validationState) {
  const toggle = document.getElementById('toggle-official');
  const scenario = document.getElementById('official-scenario');
  const opacity = document.getElementById('opacity-official');
  const value = document.getElementById('val-official');

  if (!validationState || !validationState.available) {
    toggle.disabled = true;
    scenario.disabled = true;
    opacity.disabled = true;
    return;
  }

  function updateVisibility() {
    OFFICIAL_SCENARIOS.forEach(({ key }) => {
      if (!validationState.byScenario[key]) return;
      map.setLayoutProperty(
        `layer-official-${key}`,
        'visibility',
        toggle.checked && scenario.value === key ? 'visible' : 'none'
      );
    });
  }
  toggle.addEventListener('change', updateVisibility);
  scenario.addEventListener('change', updateVisibility);
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

function wireHydroControls(map, hydroState) {
  const hydroToggle = document.getElementById('toggle-hydro');
  const hydroDate = document.getElementById('hydro-date');
  const hydroOpacity = document.getElementById('opacity-hydro');
  const hydroVal = document.getElementById('val-hydro');
  const hydroRiskToggle = document.getElementById('toggle-hydro-risk');

  if (!hydroState || !hydroState.available) {
    hydroToggle.disabled = true;
    hydroDate.disabled = true;
    hydroOpacity.disabled = true;
    hydroRiskToggle.disabled = true;
    return;
  }

  hydroState.manifest.dates.forEach(entry => {
    const option = document.createElement('option');
    option.value = entry.date;
    option.textContent = entry.label || entry.date;
    hydroDate.appendChild(option);
  });

  hydroToggle.addEventListener('change', () => {
    map.setLayoutProperty(
      'layer-hydro-trigger',
      'visibility',
      hydroToggle.checked ? 'visible' : 'none'
    );
  });
  hydroOpacity.addEventListener('input', () => {
    map.setPaintProperty('layer-hydro-trigger', 'fill-opacity', hydroOpacity.value / 100);
    hydroVal.textContent = hydroOpacity.value + '%';
  });
  hydroDate.addEventListener('change', () => {
    setHydroDate(map, hydroState, hydroDate.value, hydroRiskToggle.checked);
  });
  hydroRiskToggle.addEventListener('change', e => setHydroRiskVisible(e.target.checked));
}
