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

    addRiskPoints(map, riskPoints);
    setRiskVisible(false);

    initOfficialValidation(map, validationManifest).then(validationState => {
      wireControls(map, manifest, validationState);
    });
  });
}

const LAYER_TYPES = [
  // D19 is frozen and available in two non-hazard display modes. The sparse
  // review mask is the default when enabled; the full diagnostic surface is
  // deliberately separate and never visible on initial load.
  { key: 'd19_review',     defaultOpacity: 0.70, defaultVisible: false },
  { key: 'd19_diagnostic', defaultOpacity: 0.55, defaultVisible: false },
  { key: 'q100_comparison', defaultOpacity: 1.00, defaultVisible: false, resampling: 'nearest' },
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

function ensureTileLayer(map, tile, key) {
  const layerId = `layer-${key}-${tile.name}`;
  if (map.getLayer(layerId) || !tile.files[key]) return layerId;
  const config = LAYER_TYPES.find(item => item.key === key);
  if (!config) return null;
  const sourceId = `src-${key}-${tile.name}`;
  map.addSource(sourceId, {
    type: 'image',
    url: `data/${tile.files[key]}`,
    coordinates: tile.bounds.corners,
  });
  const beforeOfficial = map.getStyle().layers
    .find(layer => layer.id.startsWith('layer-official-'))?.id;
  map.addLayer({
    id: layerId,
    type: 'raster',
    source: sourceId,
    paint: {
      'raster-opacity': config.defaultOpacity,
      'raster-resampling': config.resampling || 'linear',
    },
    layout: { visibility: 'none' },
  }, beforeOfficial);
  return layerId;
}

function ensureCoastalLayer(map, tile, key) {
  const layerId = `layer-coastal-${key}-${tile.name}`;
  if (map.getLayer(layerId) || !tile.files.coastal?.[key]) return layerId;
  const sourceId = `src-coastal-${key}-${tile.name}`;
  map.addSource(sourceId, {
    type: 'image',
    url: `data/${tile.files.coastal[key]}`,
    coordinates: tile.bounds.corners,
  });
  const beforeOfficial = map.getStyle().layers
    .find(layer => layer.id.startsWith('layer-official-'))?.id;
  map.addLayer({
    id: layerId,
    type: 'raster',
    source: sourceId,
    paint: { 'raster-opacity': 0.70, 'raster-resampling': 'linear' },
    layout: { visibility: 'none' },
  }, beforeOfficial);
  return layerId;
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

function wireControls(map, manifest, validationState) {
  const tiles = manifest.tiles;
  const tileNames = tiles.map(t => t.name);

  Object.entries(KEY_ALIAS).forEach(([alias, key]) => {
    const chk = document.getElementById(`toggle-${alias}`);
    chk.addEventListener('change', () => {
      const vis = chk.checked ? 'visible' : 'none';
      tiles.forEach(tile => {
        if (chk.checked) ensureTileLayer(map, tile, key);
        const layerId = `layer-${key}-${tile.name}`;
        if (map.getLayer(layerId)) map.setLayoutProperty(layerId, 'visibility', vis);
      });
    });

    const slider = document.getElementById(`opacity-${alias}`);
    const valEl  = document.getElementById(`val-${alias}`);
    slider.addEventListener('input', () => {
      const v = slider.value / 100;
      tileNames.forEach(name => {
        const layerId = `layer-${key}-${name}`;
        if (map.getLayer(layerId)) map.setPaintProperty(layerId, 'raster-opacity', v);
      });
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
        if (visible && key === activeKey) ensureCoastalLayer(map, tile, key);
        const layerId = `layer-coastal-${key}-${tile.name}`;
        if (map.getLayer(layerId)) {
          map.setLayoutProperty(
            layerId, 'visibility',
            visible && key === activeKey ? 'visible' : 'none'
          );
        }
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
          const layerId = `layer-coastal-${key}-${tile.name}`;
          if (map.getLayer(layerId)) map.setPaintProperty(layerId, 'raster-opacity', v);
        });
      });
      coastalVal.textContent = coastalOpacity.value + '%';
    });
  }

  wireOfficialValidationControls(map, validationState, manifest);
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
      tiles.forEach(tile => {
        if (toggle.checked && mode.value === key) ensureTileLayer(map, tile, key);
        const layerId = `layer-${key}-${tile.name}`;
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

const comparisonIndexCache = new Map();

function inverseBilinear(lng, lat, corners) {
  const [nw, ne, se, sw] = corners;
  const ax = nw[0], ay = nw[1];
  const bx = ne[0] - nw[0], by = ne[1] - nw[1];
  const cx = sw[0] - nw[0], cy = sw[1] - nw[1];
  const dx = nw[0] - ne[0] - sw[0] + se[0];
  const dy = nw[1] - ne[1] - sw[1] + se[1];
  let u = (lng - Math.min(nw[0], sw[0])) /
    Math.max(Math.max(ne[0], se[0]) - Math.min(nw[0], sw[0]), 1e-12);
  let v = (Math.max(nw[1], ne[1]) - lat) /
    Math.max(Math.max(nw[1], ne[1]) - Math.min(sw[1], se[1]), 1e-12);
  for (let iteration = 0; iteration < 6; iteration += 1) {
    const fx = ax + bx * u + cx * v + dx * u * v - lng;
    const fy = ay + by * u + cy * v + dy * u * v - lat;
    const j00 = bx + dx * v;
    const j01 = cx + dx * u;
    const j10 = by + dy * v;
    const j11 = cy + dy * u;
    const determinant = j00 * j11 - j01 * j10;
    if (Math.abs(determinant) < 1e-16) break;
    const du = (fx * j11 - fy * j01) / determinant;
    const dv = (fy * j00 - fx * j10) / determinant;
    u -= du;
    v -= dv;
  }
  return { u, v };
}

function loadComparisonIndex(tile) {
  if (comparisonIndexCache.has(tile.name)) return comparisonIndexCache.get(tile.name);
  const promise = new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      const context = canvas.getContext('2d', { willReadFrequently: true });
      context.drawImage(image, 0, 0);
      resolve({ context, width: canvas.width, height: canvas.height });
    };
    image.onerror = reject;
    image.src = `data/${tile.files.q100_comparison_index}`;
  });
  comparisonIndexCache.set(tile.name, promise);
  return promise;
}

function comparisonCategoryCopy(code) {
  return {
    0: {
      official: 'Unavailable', d19: 'Not compared', validity: 'Outside',
      interpretation: 'Outside the official study domain — comparison unavailable.',
    },
    1: {
      official: 'No', d19: 'No', validity: 'Inside',
      interpretation: 'Neither layer marks this cell. This is not proof of safety.',
    },
    2: {
      official: 'Yes', d19: 'No', validity: 'Inside',
      interpretation: 'Official Q100-only reference area.',
    },
    3: {
      official: 'No', d19: 'Yes', validity: 'Inside',
      interpretation: 'D19-only experimental signal — potential overprediction for review.',
    },
    4: {
      official: 'Yes', d19: 'Yes', validity: 'Inside',
      interpretation: 'Both the official Q100 reference and D19 review mask mark this cell.',
    },
    5: {
      official: 'No', d19: 'No data', validity: 'Inside',
      interpretation: 'Outside official Q100, but D19 terrain data are unavailable for comparison.',
    },
    6: {
      official: 'Yes', d19: 'No data', validity: 'Inside',
      interpretation: 'Official Q100 marks this cell, but D19 terrain data are unavailable.',
    },
  }[code] || {
    official: 'Unknown', d19: 'Unknown', validity: 'Unknown',
    interpretation: 'Comparison class could not be read.',
  };
}

function wireComparisonClick(map, tiles, comparisonToggle) {
  const popup = new maplibregl.Popup({ offset: 12, closeButton: true });
  map.on('click', async event => {
    if (!comparisonToggle.checked) return;
    const lng = event.lngLat.lng;
    const lat = event.lngLat.lat;
    let selected = null;
    let position = null;
    for (const tile of tiles) {
      if (!tile.files.q100_comparison_index) continue;
      const bounds = tile.bounds;
      if (lng < bounds.west || lng > bounds.east || lat < bounds.south || lat > bounds.north) continue;
      const candidate = inverseBilinear(lng, lat, bounds.corners);
      if (candidate.u >= 0 && candidate.u <= 1 && candidate.v >= 0 && candidate.v <= 1) {
        selected = tile;
        position = candidate;
        break;
      }
    }
    if (!selected) return;
    try {
      const index = await loadComparisonIndex(selected);
      const x = Math.min(index.width - 1, Math.max(0, Math.floor(position.u * index.width)));
      const y = Math.min(index.height - 1, Math.max(0, Math.floor(position.v * index.height)));
      const code = index.context.getImageData(x, y, 1, 1).data[0];
      const copy = comparisonCategoryCopy(code);
      popup.setLngLat(event.lngLat).setHTML(`
        <div class="popup-rank">Categorical Q100 comparison</div>
        <div class="popup-row"><span class="popup-key">Official Q100:</span><span class="popup-val">${copy.official}</span></div>
        <div class="popup-row"><span class="popup-key">D19 review signal:</span><span class="popup-val">${copy.d19}</span></div>
        <div class="popup-row"><span class="popup-key">Official study validity:</span><span class="popup-val">${copy.validity}</span></div>
        <div class="popup-row"><span class="popup-key">Tile:</span><span class="popup-val">${selected.name}</span></div>
        <p class="popup-interpretation"><strong>Interpretation:</strong> ${copy.interpretation}</p>
      `).addTo(map);
    } catch (error) {
      console.warn('Comparison class lookup failed', error);
    }
  });
}

function wireComparisonSummary(comparison) {
  const panel = document.getElementById('comparison-summary');
  const select = document.getElementById('comparison-summary-region');
  if (!comparison || !comparison.regions) {
    panel.hidden = true;
    return;
  }
  Object.entries(comparison.regions).forEach(([region, summary]) => {
    const option = document.createElement('option');
    option.value = region;
    option.textContent = summary.label;
    select.appendChild(option);
  });
  if (comparison.regions['05-ljubljana']) select.value = '05-ljubljana';
  function update() {
    const summary = comparison.regions[select.value];
    if (!summary) return;
    Object.entries(summary.shares_percent).forEach(([name, value]) => {
      const element = document.getElementById(`comparison-share-${name.replaceAll('_', '-')}`);
      if (element) element.textContent = value == null ? 'n/a' : `${value.toFixed(2)}%`;
    });
    document.getElementById('comparison-coverage').textContent =
      `${summary.comparable_coverage_of_validity_percent.toFixed(2)}% of official-validity cells have D19 data (${summary.comparable_area_km2.toFixed(3)} km² compared).`;
  }
  select.addEventListener('change', update);
  update();
}

function wireOfficialValidationControls(map, validationState, manifest) {
  const tiles = manifest.tiles;
  const toggle = document.getElementById('toggle-official');
  const scenario = document.getElementById('official-scenario');
  const opacity = document.getElementById('opacity-official');
  const value = document.getElementById('val-official');
  const validityToggle = document.getElementById('toggle-official-validity');
  const depthToggle = document.getElementById('toggle-official-depth');
  const comparisonToggle = document.getElementById('toggle-q100-comparison');
  const comparisonSummary = document.getElementById('comparison-summary');
  const d19Toggle = document.getElementById('toggle-susc');
  const d19Mode = document.getElementById('d19-display-mode');
  const d19Opacity = document.getElementById('opacity-susc');
  const comparisonAvailable = Boolean(
    manifest.q100_comparison && tiles.every(tile => tile.files.q100_comparison)
  );

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
  comparisonToggle.disabled = !comparisonAvailable;
  wireComparisonSummary(manifest.q100_comparison);
  if (comparisonAvailable) wireComparisonClick(map, tiles, comparisonToggle);

  function updateVisibility() {
    const comparing = comparisonToggle.checked;
    OFFICIAL_SCENARIOS.forEach(({ key }) => {
      if (!validationState.byScenario[key]) return;
      map.setLayoutProperty(
        `layer-official-${key}`,
        'visibility',
        !comparing && toggle.checked && scenario.value === key ? 'visible' : 'none'
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
        !comparing && toggle.checked && depthToggle.checked && scenario.value === 'q100' ? 'visible' : 'none'
      );
    });
    tiles.forEach(tile => {
      if (comparing) ensureTileLayer(map, tile, 'q100_comparison');
      const layerId = `layer-q100_comparison-${tile.name}`;
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, 'visibility', comparing ? 'visible' : 'none');
      }
    });
    comparisonSummary.hidden = !comparing;
  }
  toggle.addEventListener('change', updateVisibility);
  scenario.addEventListener('change', updateVisibility);
  validityToggle.addEventListener('change', updateVisibility);
  depthToggle.addEventListener('change', updateVisibility);
  comparisonToggle.addEventListener('change', () => {
    const enabled = comparisonToggle.checked;
    toggle.checked = false;
    d19Toggle.checked = false;
    if (enabled) {
      scenario.value = 'q100';
      depthToggle.checked = false;
      validityToggle.checked = true;
    }
    d19Toggle.dispatchEvent(new Event('change'));
    toggle.disabled = enabled;
    scenario.disabled = enabled;
    opacity.disabled = enabled;
    depthToggle.disabled = enabled || validationState.depthKeys.length === 0;
    validityToggle.disabled = enabled || !validationState.validity;
    d19Toggle.disabled = enabled;
    d19Mode.disabled = enabled;
    d19Opacity.disabled = enabled;
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
