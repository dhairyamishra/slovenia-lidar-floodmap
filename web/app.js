'use strict';

const BASEMAP_STYLE = 'https://tiles.openfreemap.org/styles/dark';
const GURS_ORTHOPHOTO_URL =
  'https://ipi.eprostor.gov.si/wms-si-gurs-dts/wms?' +
  'SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&' +
  'LAYERS=SI.GURS.ZPDZ%3ADOF025&STYLES=&SRS=EPSG%3A3857&' +
  'BBOX={bbox-epsg-3857}&WIDTH=256&HEIGHT=256&' +
  'FORMAT=image%2Fpng8&TRANSPARENT=true';

function optionalJson(url) {
  return fetch(url).then(r => r.ok ? r.json() : null).catch(() => null);
}

Promise.all([
  fetch('data/manifest.json?v=16').then(r => r.json()),
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
  document.getElementById('topbar-meta').textContent =
    `${manifest.tile_count} tiles · CLSS GKOT · 2 m grid`;

  const map = window._map = new maplibregl.Map({
    container: 'map',
    style: BASEMAP_STYLE,
    center: ub.center,
    zoom: 13,
    maxZoom: 20,
    minZoom: 5,
    attributionControl: false,
  });

  map.on('styleimagemissing', event => {
    if (!map.hasImage(event.id)) {
      map.addImage(event.id, {
        width: 1,
        height: 1,
        data: new Uint8Array([0, 0, 0, 0]),
      });
    }
  });

  map.addControl(new maplibregl.NavigationControl(), 'bottom-right');
  map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
  map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');

  map.on('load', () => {
    initAerialBasemap(map);
    map.fitBounds([[ub.west, ub.south], [ub.east, ub.north]],
                  { padding: 60, duration: 0 });

    addRiskPoints(map, riskPoints);
    setRiskVisible(false);

    initOfficialValidation(map, validationManifest).then(validationState => {
      wireControls(map, manifest, validationState);
    });
  });
}

function initAerialBasemap(map) {
  map.addSource('gurs-orthophoto', {
    type: 'raster',
    tiles: [GURS_ORTHOPHOTO_URL],
    tileSize: 256,
    minzoom: 7,
    maxzoom: 20,
    bounds: [13.3400608, 44.9641309, 17.2035352, 46.8958681],
    attribution: '<a href="https://www.e-prostor.gov.si/" target="_blank">Ortofoto Â© GURS (CC BY 4.0)</a>',
  });

  const firstLabel = map.getStyle().layers.find(layer => layer.type === 'symbol')?.id;
  map.addLayer({
    id: 'gurs-orthophoto-layer',
    type: 'raster',
    source: 'gurs-orthophoto',
    minzoom: 7,
    layout: { visibility: 'none' },
    paint: {
      'raster-opacity': 1,
      'raster-fade-duration': 0,
      'raster-resampling': 'linear',
    },
  }, firstLabel);

  document.querySelectorAll('input[name="basemap"]')
    .forEach(control => control.addEventListener('change', () => {
      if (!control.checked) return;
      map.setLayoutProperty(
        'gurs-orthophoto-layer',
        'visibility',
        control.value === 'aerial' ? 'visible' : 'none',
      );
    }));
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

const VIEWPORT_LAYER_LIMITS = {
  d19_review: 48,
  d19_diagnostic: 16,
  q100_comparison: 48,
  ndvi: 16,
  classification: 32,
};

function tileIntersectsBounds(tile, bounds) {
  return tile.bounds.east >= bounds.getWest() &&
    tile.bounds.west <= bounds.getEast() &&
    tile.bounds.north >= bounds.getSouth() &&
    tile.bounds.south <= bounds.getNorth();
}

function tilesForViewport(map, tiles, limit) {
  const bounds = map.getBounds();
  const center = map.getCenter();
  const visible = tiles.filter(tile => tileIntersectsBounds(tile, bounds));
  if (visible.length <= limit) return visible;
  return visible
    .map(tile => ({
      tile,
      distance: (tile.bounds.center[0] - center.lng) ** 2 +
        (tile.bounds.center[1] - center.lat) ** 2,
    }))
    .sort((a, b) => a.distance - b.distance)
    .slice(0, limit)
    .map(item => item.tile);
}

function removeImageLayer(map, layerId, sourceId) {
  if (map.getLayer(layerId)) map.removeLayer(layerId);
  if (map.getSource(sourceId)) map.removeSource(sourceId);
}

function syncTileLayerViewport(map, tiles, key, active, opacity = null) {
  const selected = active
    ? new Set(tilesForViewport(map, tiles, VIEWPORT_LAYER_LIMITS[key]).map(tile => tile.name))
    : new Set();
  tiles.forEach(tile => {
    const layerId = `layer-${key}-${tile.name}`;
    const sourceId = `src-${key}-${tile.name}`;
    if (selected.has(tile.name)) {
      ensureTileLayer(map, tile, key);
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, 'visibility', 'visible');
        if (opacity != null) map.setPaintProperty(layerId, 'raster-opacity', opacity);
      }
    } else {
      removeImageLayer(map, layerId, sourceId);
    }
  });
}

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
  function ensureScenario(key) {
    const entry = byScenario[key];
    if (!entry || map.getSource(`src-official-${key}`)) return;
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
  }
  const extra = validationManifest.layers || {};
  const validity = extra.validity;
  function ensureValidity() {
    if (!validity || map.getSource('src-official-validity')) return;
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
  const depthKeys = depthSpecs.filter(([key]) => extra[key]).map(([key]) => key);
  function ensureDepth(key) {
    const spec = depthSpecs.find(([candidate]) => candidate === key);
    if (!spec || map.getSource(`src-official-${key}`)) return;
    const color = spec[1];
    const entry = extra[key];
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
        'fill-color': color,
        'fill-opacity': 0.48,
        'fill-outline-color': color,
      },
      layout: { visibility: 'none' },
    });
  }
  return {
    available: true,
    byScenario,
    validity: Boolean(validity),
    depthKeys,
    ensureScenario,
    ensureValidity,
    ensureDepth,
  };
}

const KEY_ALIAS = { ndvi: 'ndvi', cls: 'classification' };

function wireControls(map, manifest, validationState) {
  const tiles = manifest.tiles;
  const tileNames = tiles.map(t => t.name);
  const hasNdvi = tiles.some(tile => tile.files.ndvi);
  const hasD19Diagnostic = tiles.some(tile => tile.files.d19_diagnostic);
  document.getElementById('layer-section-ndvi').hidden = !hasNdvi;
  if (!hasD19Diagnostic) {
    document.querySelector('#d19-display-mode option[value="d19_diagnostic"]')?.remove();
    document.getElementById('d19-display-row').hidden = true;
  }

  Object.entries(KEY_ALIAS).forEach(([alias, key]) => {
    const chk = document.getElementById(`toggle-${alias}`);
    const slider = document.getElementById(`opacity-${alias}`);
    const update = () => syncTileLayerViewport(map, tiles, key, chk.checked, slider.value / 100);
    chk.addEventListener('change', update);
    map.on('moveend', update);

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
  wireConnectivityControls(map, manifest);

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
    const selected = new Set(
      (visible ? tilesForViewport(map, coastalTiles, coastalTiles.length) : [])
        .map(tile => tile.name)
    );
    coastalTiles.forEach(tile => {
      COASTAL_SCENARIOS.forEach(({ key }) => {
        if (!tile.files.coastal[key]) return;
        const layerId = `layer-coastal-${key}-${tile.name}`;
        const sourceId = `src-coastal-${key}-${tile.name}`;
        if (selected.has(tile.name) && key === activeKey) {
          ensureCoastalLayer(map, tile, key);
          if (map.getLayer(layerId)) map.setLayoutProperty(layerId, 'visibility', 'visible');
        } else {
          removeImageLayer(map, layerId, sourceId);
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
    map.on('moveend', setCoastalVisibility);
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
  wireGuidedViews(map, manifest);
}

function setPanelOpen(open) {
  document.body.classList.toggle('panel-collapsed', !open);
  const button = document.getElementById('panel-toggle');
  button.setAttribute('aria-expanded', String(open));
  button.textContent = open ? 'Close layers' : 'Layers';
}

function setToggleState(id, checked) {
  const control = document.getElementById(id);
  if (!control || control.disabled || control.checked === checked) return;
  control.checked = checked;
  control.dispatchEvent(new Event('change'));
}

function presetTiles(manifest, preset) {
  if (preset === 'savinja') {
    return manifest.tiles.filter(tile => tile.files.connectivity?.required_stage);
  }
  if (preset === 'koper') {
    return manifest.tiles.filter(tile => tile.files.coastal);
  }
  return manifest.tiles.filter(tile => {
    const grid = tile.bounds.epsg3794;
    return grid && grid.x0 >= 455000 && grid.x0 < 465000 &&
      grid.y0 >= 96000 && grid.y0 < 106000;
  });
}

function fitTiles(map, tiles) {
  if (!tiles.length) return;
  const west = Math.min(...tiles.map(tile => tile.bounds.west));
  const east = Math.max(...tiles.map(tile => tile.bounds.east));
  const south = Math.min(...tiles.map(tile => tile.bounds.south));
  const north = Math.max(...tiles.map(tile => tile.bounds.north));
  map.fitBounds([[west, south], [east, north]], {
    padding: window.matchMedia('(max-width: 640px)').matches ? 28 : 70,
    duration: 0,
  });
}

function wireGuidedViews(map, manifest) {
  const mobile = window.matchMedia('(max-width: 640px)');
  setPanelOpen(!mobile.matches);
  document.getElementById('panel-toggle').addEventListener('click', () => {
    setPanelOpen(document.body.classList.contains('panel-collapsed'));
  });
  mobile.addEventListener('change', event => setPanelOpen(!event.matches));

  document.querySelectorAll('[data-region-preset]').forEach(button => {
    button.addEventListener('click', () => {
      const preset = button.dataset.regionPreset;
      [
        'toggle-q100-comparison', 'toggle-susc', 'toggle-required-stage',
        'toggle-scenario-depth', 'toggle-official', 'toggle-coastal',
      ].forEach(id => setToggleState(id, false));
      fitTiles(map, presetTiles(manifest, preset));
      window.requestAnimationFrame(() => {
        if (preset === 'ljubljana') {
          document.getElementById('official-scenario').value = 'q100';
          setToggleState('toggle-official', true);
        } else if (preset === 'savinja') {
          setToggleState('toggle-required-stage', true);
        } else if (preset === 'koper') {
          setToggleState('toggle-coastal', true);
        }
      });
      if (mobile.matches) setPanelOpen(false);
    });
  });
}

function ensureConnectivityLayer(map, tile, key, path, opacity, resampling = 'linear') {
  const layerId = `layer-connectivity-${key}-${tile.name}`;
  if (map.getLayer(layerId) || !path) return layerId;
  const sourceId = `src-connectivity-${key}-${tile.name}`;
  map.addSource(sourceId, {
    type: 'image',
    url: `data/${path}`,
    coordinates: tile.bounds.corners,
  });
  const beforeOfficial = map.getStyle().layers
    .find(layer => layer.id.startsWith('layer-official-'))?.id;
  map.addLayer({
    id: layerId,
    type: 'raster',
    source: sourceId,
    paint: { 'raster-opacity': opacity, 'raster-resampling': resampling },
    layout: { visibility: 'none' },
  }, beforeOfficial);
  return layerId;
}

const connectivityIndexCache = new Map();

function loadConnectivityIndex(path) {
  if (connectivityIndexCache.has(path)) return connectivityIndexCache.get(path);
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
    image.src = `data/${path}`;
  });
  connectivityIndexCache.set(path, promise);
  return promise;
}

function decodePhysicalIndex(pixel) {
  const centimetres = pixel[0] * 256 + pixel[1];
  return {
    valueM: centimetres === 65535 ? null : centimetres / 100,
    classCode: pixel[2],
  };
}

function decodeReachIndex(pixel) {
  const value = pixel[0] * 65536 + pixel[1] * 256 + pixel[2];
  return value === 0xffffff ? null : value;
}

function connectivityClassLabel(code) {
  return ({
    0: 'Unavailable',
    1: 'Assessed',
    2: 'Inundated under scenario',
    3: 'Barrier/culvert uncertainty',
    4: 'Edge-contaminated',
  })[code] || 'Unknown';
}

function wireConnectivityClick(map, tiles, requiredToggle, scenarioToggle, scenarioSelect, manifest) {
  const popup = new maplibregl.Popup({ offset: 12, closeButton: true });
  map.on('click', async event => {
    if (!requiredToggle.checked && !scenarioToggle.checked) return;
    const lng = event.lngLat.lng;
    const lat = event.lngLat.lat;
    let selected = null;
    let position = null;
    for (const tile of tiles) {
      const connectivity = tile.files.connectivity;
      if (!connectivity?.required_stage_index) continue;
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
      const files = selected.files.connectivity;
      const requiredIndex = await loadConnectivityIndex(files.required_stage_index);
      const x = Math.min(requiredIndex.width - 1, Math.max(0, Math.floor(position.u * requiredIndex.width)));
      const y = Math.min(requiredIndex.height - 1, Math.max(0, Math.floor(position.v * requiredIndex.height)));
      const required = decodePhysicalIndex(requiredIndex.context.getImageData(x, y, 1, 1).data);
      let reachId = null;
      if (files.reach_index) {
        const reachIndex = await loadConnectivityIndex(files.reach_index);
        reachId = decodeReachIndex(reachIndex.context.getImageData(x, y, 1, 1).data);
      }
      const domain = manifest.connectivity_model?.domains?.[files.domain] || {};
      let scenarioCopy = '<div class="popup-row"><span class="popup-key">Scenario depth:</span><span class="popup-val">Not displayed</span></div>';
      if (scenarioToggle.checked) {
        const scenarioFiles = files.scenarios?.[scenarioSelect.value];
        if (scenarioFiles?.depth_index) {
          const depthIndex = await loadConnectivityIndex(scenarioFiles.depth_index);
          const depth = decodePhysicalIndex(depthIndex.context.getImageData(x, y, 1, 1).data);
          scenarioCopy = `
            <div class="popup-row"><span class="popup-key">Scenario depth:</span><span class="popup-val">${depth.valueM == null ? 'Unavailable' : `${depth.valueM.toFixed(2)} m`}</span></div>
            <div class="popup-row"><span class="popup-key">Scenario class:</span><span class="popup-val">${connectivityClassLabel(depth.classCode)}</span></div>`;
        }
      }
      popup.setLngLat(event.lngLat).setHTML(`
        <div class="popup-rank">Connectivity-first riverine model</div>
        <div class="popup-row"><span class="popup-key">Minimum stage rise:</span><span class="popup-val">${required.valueM == null ? 'Unavailable' : `${required.valueM.toFixed(2)} m`}</span></div>
        <div class="popup-row"><span class="popup-key">Applicability:</span><span class="popup-val">${connectivityClassLabel(required.classCode)}</span></div>
        <div class="popup-row"><span class="popup-key">Reach:</span><span class="popup-val">${reachId == null ? 'Unresolved' : `${files.domain}:${reachId}`}</span></div>
        <div class="popup-row"><span class="popup-key">Scenario source:</span><span class="popup-val">${domain.scenario?.source?.kind || domain.scenario?.source || 'No scenario supplied'}</span></div>
        <div class="popup-row"><span class="popup-key">Model version:</span><span class="popup-val">${manifest.connectivity_model.model_version}</span></div>
        ${scenarioCopy}
        <div class="popup-row"><span class="popup-key">Tile:</span><span class="popup-val">${selected.name}</span></div>
        <p class="popup-interpretation">A dry scenario class is not proof of safety outside this scenario and applicability domain.</p>
      `).addTo(map);
    } catch (error) {
      console.warn('Connectivity value lookup failed', error);
    }
  });
}

function wireConnectivityControls(map, manifest) {
  const tiles = manifest.tiles;
  const model = manifest.connectivity_model;
  const requiredToggle = document.getElementById('toggle-required-stage');
  const requiredOpacity = document.getElementById('opacity-required-stage');
  const requiredValue = document.getElementById('val-required-stage');
  const scenarioToggle = document.getElementById('toggle-scenario-depth');
  const scenarioSelect = document.getElementById('connectivity-scenario');
  const scenarioOpacity = document.getElementById('opacity-scenario-depth');
  const scenarioValue = document.getElementById('val-scenario-depth');
  const availableTiles = tiles.filter(tile => tile.files.connectivity?.required_stage);
  if (!model || availableTiles.length === 0) return;

  requiredToggle.disabled = false;
  requiredOpacity.disabled = false;
  const scenarios = [];
  Object.values(model.domains || {}).forEach(domain => {
    if (domain.scenario && !scenarios.some(item => item.id === domain.scenario.id)) {
      scenarios.push(domain.scenario);
    }
  });
  if (scenarios.length) {
    scenarioSelect.innerHTML = '';
    scenarios.forEach(item => {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = item.label;
      scenarioSelect.appendChild(option);
    });
    scenarioToggle.disabled = false;
    scenarioSelect.disabled = false;
    scenarioOpacity.disabled = false;
  }

  function update() {
    const scenarioId = scenarioSelect.value;
    availableTiles.forEach(tile => {
      const files = tile.files.connectivity;
      if (requiredToggle.checked) {
        ensureConnectivityLayer(map, tile, 'required-stage', files.required_stage, requiredOpacity.value / 100);
      }
      const requiredLayer = `layer-connectivity-required-stage-${tile.name}`;
      if (map.getLayer(requiredLayer)) {
        map.setLayoutProperty(requiredLayer, 'visibility', requiredToggle.checked ? 'visible' : 'none');
      }
      const scenarioFiles = files.scenarios?.[scenarioId];
      if (scenarioToggle.checked && scenarioFiles) {
        ensureConnectivityLayer(map, tile, `scenario-${scenarioId}`, scenarioFiles.depth, scenarioOpacity.value / 100);
      }
      Object.keys(files.scenarios || {}).forEach(id => {
        const layer = `layer-connectivity-scenario-${id}-${tile.name}`;
        if (map.getLayer(layer)) {
          map.setLayoutProperty(layer, 'visibility', scenarioToggle.checked && id === scenarioId ? 'visible' : 'none');
        }
      });
      if (requiredToggle.checked || scenarioToggle.checked) {
        ensureConnectivityLayer(map, tile, 'applicability', files.applicability, 1.0, 'nearest');
      }
      const applicabilityLayer = `layer-connectivity-applicability-${tile.name}`;
      if (map.getLayer(applicabilityLayer)) {
        map.setLayoutProperty(applicabilityLayer, 'visibility', requiredToggle.checked || scenarioToggle.checked ? 'visible' : 'none');
      }
    });
  }
  requiredToggle.addEventListener('change', update);
  scenarioToggle.addEventListener('change', update);
  scenarioSelect.addEventListener('change', update);
  requiredOpacity.addEventListener('input', () => {
    availableTiles.forEach(tile => {
      const layer = `layer-connectivity-required-stage-${tile.name}`;
      if (map.getLayer(layer)) map.setPaintProperty(layer, 'raster-opacity', requiredOpacity.value / 100);
    });
    requiredValue.textContent = `${requiredOpacity.value}%`;
  });
  scenarioOpacity.addEventListener('input', () => {
    const id = scenarioSelect.value;
    availableTiles.forEach(tile => {
      const layer = `layer-connectivity-scenario-${id}-${tile.name}`;
      if (map.getLayer(layer)) map.setPaintProperty(layer, 'raster-opacity', scenarioOpacity.value / 100);
    });
    scenarioValue.textContent = `${scenarioOpacity.value}%`;
  });
  wireConnectivityClick(map, availableTiles, requiredToggle, scenarioToggle, scenarioSelect, manifest);
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
      syncTileLayerViewport(
        map, tiles, key, toggle.checked && mode.value === key, opacity.value / 100
      );
    });
  }

  toggle.addEventListener('change', updateVisibility);
  mode.addEventListener('change', updateVisibility);
  map.on('moveend', updateVisibility);
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
      const active = !comparing && toggle.checked && scenario.value === key;
      if (active) validationState.ensureScenario(key);
      const layerId = `layer-official-${key}`;
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, 'visibility', active ? 'visible' : 'none');
      }
    });
    if (validationState.validity) {
      const visibility = validityToggle.checked ? 'visible' : 'none';
      if (validityToggle.checked) validationState.ensureValidity();
      if (map.getLayer('layer-official-validity-fill')) {
        map.setLayoutProperty('layer-official-validity-fill', 'visibility', visibility);
        map.setLayoutProperty('layer-official-validity-line', 'visibility', visibility);
      }
    }
    validationState.depthKeys.forEach(key => {
      const active = !comparing && toggle.checked && depthToggle.checked && scenario.value === 'q100';
      if (active) validationState.ensureDepth(key);
      const layerId = `layer-official-${key}`;
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, 'visibility', active ? 'visible' : 'none');
      }
    });
    syncTileLayerViewport(map, tiles, 'q100_comparison', comparing);
    comparisonSummary.hidden = !comparing;
  }
  toggle.addEventListener('change', updateVisibility);
  scenario.addEventListener('change', updateVisibility);
  validityToggle.addEventListener('change', updateVisibility);
  depthToggle.addEventListener('change', updateVisibility);
  map.on('moveend', updateVisibility);
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
      if (validationState.byScenario[key] && map.getLayer(`layer-official-${key}`)) {
        map.setPaintProperty(`layer-official-${key}`, 'fill-opacity', next);
      }
    });
    value.textContent = opacity.value + '%';
  });
}
