"""ERA5-Land hydroclimate trigger export for the web app.

V1 ships with a deterministic fixture so the static app can expose the feature
without CDS credentials. Real ERA5-Land NetCDF support is intentionally narrow:
provide files that contain swvl4, tp and smlt over a useful baseline period.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WEBDATA = ROOT / "web" / "data"
HYDRO_OUT = ROOT / "output" / "hydroclimate"
HYDRO_WEB = WEBDATA / "hydroclimate"
DEFAULT_DATE = "2023-08-04"
CELL_DEG = 0.08
TOP_DYNAMIC_N = 20


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def gaussian(lon: float, lat: float, center_lon: float, center_lat: float, sx: float, sy: float) -> float:
    dx = (lon - center_lon) / sx
    dy = (lat - center_lat) / sy
    return math.exp(-0.5 * (dx * dx + dy * dy))


def cell_polygon(west: float, south: float, east: float, north: float):
    return [[
        [west, south],
        [east, south],
        [east, north],
        [west, north],
        [west, south],
    ]]


def feature_collection(features):
    return {
        "type": "FeatureCollection",
        "features": features,
    }


def hydro_properties(lon: float, lat: float) -> dict:
    """Deterministic Aug-2023 fixture elevated over the Savinja/Kamnik block."""
    savinja = gaussian(lon, lat, 14.85, 46.33, 0.12, 0.08)
    ljubljana = gaussian(lon, lat, 14.47, 46.06, 0.18, 0.12)
    koper = gaussian(lon, lat, 13.73, 45.55, 0.11, 0.08)
    north_wet = clamp01((lat - 45.52) / 0.85)

    soil = clamp01(0.34 + 0.48 * savinja + 0.18 * ljubljana + 0.08 * north_wet)
    water90 = clamp01(0.28 + 0.58 * savinja + 0.14 * ljubljana + 0.06 * koper)
    trend = clamp01(0.24 + 0.40 * savinja + 0.10 * north_wet)
    score = soil + water90 + 0.5 * trend
    index = clamp01(score / 2.5)

    return {
        "soil_moisture_norm": round(soil, 3),
        "water90_norm": round(water90, 3),
        "wetting_trend_norm": round(trend, 3),
        "hydro_score": round(score, 3),
        "hydro_index": round(index, 3),
    }


def derive_fixture(args) -> None:
    manifest = read_json(WEBDATA / "manifest.json")
    ub = manifest["union_bounds"]
    west = math.floor((ub["west"] - 0.02) / CELL_DEG) * CELL_DEG
    east = math.ceil((ub["east"] + 0.02) / CELL_DEG) * CELL_DEG
    south = math.floor((ub["south"] - 0.02) / CELL_DEG) * CELL_DEG
    north = math.ceil((ub["north"] + 0.02) / CELL_DEG) * CELL_DEG

    features = []
    cell_id = 0
    lat = south
    while lat < north:
        lon = west
        while lon < east:
            cell_id += 1
            e = round(min(east, lon + CELL_DEG), 8)
            n = round(min(north, lat + CELL_DEG), 8)
            center_lon = (lon + e) / 2.0
            center_lat = (lat + n) / 2.0
            props = hydro_properties(center_lon, center_lat)
            props.update({
                "cell_id": f"fixture-{cell_id:03d}",
                "date": args.date,
                "source": "fixture",
                "center_lon": round(center_lon, 6),
                "center_lat": round(center_lat, 6),
            })
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": cell_polygon(round(lon, 8), round(lat, 8), e, n),
                },
                "properties": props,
            })
            lon += CELL_DEG
        lat += CELL_DEG

    dataset = {
        "generated": now_iso(),
        "date": args.date,
        "kind": "fixture",
        "model": "hydro_score = soil_moisture_norm + water90_norm + 0.5 * wetting_trend_norm",
        "features": feature_collection(features),
    }
    out_path = HYDRO_OUT / f"hydro_{args.date}.json"
    write_json(out_path, dataset)
    print(f"Wrote fixture hydroclimate dataset: {out_path}")


def find_coord_name(dataset, names):
    for name in names:
        if name in dataset.coords or name in dataset.dims:
            return name
    raise ValueError(f"Could not find coordinate from candidates: {', '.join(names)}")


def var_from_dataset(dataset, names):
    for name in names:
        if name in dataset:
            return dataset[name]
    raise ValueError(f"Could not find variable from candidates: {', '.join(names)}")


def minmax_norm(values):
    lo = values.min(dim="time", skipna=True)
    hi = values.max(dim="time", skipna=True)
    return ((values - lo) / (hi - lo)).clip(0, 1)


def derive_real(args) -> None:
    try:
        import xarray as xr
    except ImportError as exc:
        raise SystemExit("Real ERA5 derive requires xarray. Install xarray/netCDF support or use derive-fixture.") from exc

    files = [str(p) for p in sorted(Path(args.input_dir).glob("*.nc"))]
    if not files:
        raise SystemExit(f"No NetCDF files found in {args.input_dir}")

    ds = xr.open_mfdataset(files, combine="by_coords")
    lat_name = find_coord_name(ds, ["latitude", "lat"])
    lon_name = find_coord_name(ds, ["longitude", "lon"])
    time_name = find_coord_name(ds, ["time", "valid_time"])
    if time_name != "time":
        ds = ds.rename({time_name: "time"})

    soil = var_from_dataset(ds, ["swvl4", "volumetric_soil_water_layer_4"])
    precip = var_from_dataset(ds, ["tp", "total_precipitation"])
    snowmelt = var_from_dataset(ds, ["smlt", "snowmelt"])
    water = precip + snowmelt

    target = args.date
    soil_daily = soil.resample(time="1D").mean()
    water_daily = water.resample(time="1D").sum()

    soil_norm = minmax_norm(soil_daily).sel(time=target, method="nearest")
    water90 = water_daily.rolling(time=90, min_periods=30).sum()
    water90_norm = minmax_norm(water90).sel(time=target, method="nearest")
    trend = soil_daily - soil_daily.shift(time=365)
    trend_norm = minmax_norm(trend).sel(time=target, method="nearest").fillna(0)

    score = soil_norm + water90_norm + 0.5 * trend_norm
    index = (score / 2.5).clip(0, 1)

    lats = ds[lat_name].values.tolist()
    lons = ds[lon_name].values.tolist()
    features = []
    for lat_i, lat in enumerate(lats):
        for lon_i, lon in enumerate(lons):
            props = {
                "cell_id": f"era5-{lat_i:03d}-{lon_i:03d}",
                "date": target,
                "source": "era5-land",
                "center_lon": round(float(lon), 6),
                "center_lat": round(float(lat), 6),
                "soil_moisture_norm": round(float(soil_norm.isel({lat_name: lat_i, lon_name: lon_i}).values), 3),
                "water90_norm": round(float(water90_norm.isel({lat_name: lat_i, lon_name: lon_i}).values), 3),
                "wetting_trend_norm": round(float(trend_norm.isel({lat_name: lat_i, lon_name: lon_i}).values), 3),
                "hydro_score": round(float(score.isel({lat_name: lat_i, lon_name: lon_i}).values), 3),
                "hydro_index": round(float(index.isel({lat_name: lat_i, lon_name: lon_i}).values), 3),
            }
            half = args.cell_deg / 2.0
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": cell_polygon(lon - half, lat - half, lon + half, lat + half),
                },
                "properties": props,
            })

    out_path = HYDRO_OUT / f"hydro_{target}.json"
    write_json(out_path, {
        "generated": now_iso(),
        "date": target,
        "kind": "era5-land",
        "model": "hydro_score = soil_moisture_norm + water90_norm + 0.5 * wetting_trend_norm",
        "features": feature_collection(features),
    })
    print(f"Wrote ERA5 hydroclimate dataset: {out_path}")


def point_in_bbox(point_lon: float, point_lat: float, feature) -> bool:
    coords = feature["geometry"]["coordinates"][0]
    lons = [p[0] for p in coords]
    lats = [p[1] for p in coords]
    return min(lons) <= point_lon <= max(lons) and min(lats) <= point_lat <= max(lats)


def nearest_feature(point_lon: float, point_lat: float, features):
    best = None
    best_d2 = float("inf")
    for feature in features:
        if point_in_bbox(point_lon, point_lat, feature):
            return feature
        p = feature["properties"]
        d2 = (point_lon - p["center_lon"]) ** 2 + (point_lat - p["center_lat"]) ** 2
        if d2 < best_d2:
            best = feature
            best_d2 = d2
    return best


def dynamic_risk_points(candidates, hydro_features, date: str):
    ranked = []
    for cand in candidates:
        hydro = nearest_feature(float(cand["lon"]), float(cand["lat"]), hydro_features)
        if not hydro:
            continue
        hp = hydro["properties"]
        event_score = float(cand["score"]) * float(hp["hydro_index"])
        ranked.append({
            **cand,
            "date": date,
            "hydro_cell_id": hp["cell_id"],
            "hydro_index": hp["hydro_index"],
            "soil_moisture_norm": hp["soil_moisture_norm"],
            "water90_norm": hp["water90_norm"],
            "wetting_trend_norm": hp["wetting_trend_norm"],
            "event_score": event_score,
        })

    ranked.sort(key=lambda c: c["event_score"], reverse=True)
    features = []
    for rank, cand in enumerate(ranked[:TOP_DYNAMIC_N], start=1):
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [cand["lon"], cand["lat"]],
            },
            "properties": {
                "rank": rank,
                "date": date,
                "event_score": round(cand["event_score"], 3),
                "static_risk_score": round(cand["score"], 3),
                "hydro_index": round(cand["hydro_index"], 3),
                "soil_moisture_norm": cand["soil_moisture_norm"],
                "water90_norm": cand["water90_norm"],
                "wetting_trend_norm": cand["wetting_trend_norm"],
                "hydro_cell_id": cand["hydro_cell_id"],
                "elevation_m": round(cand["elevation_m"], 1),
                "easting_3794": round(cand["easting_3794"], 1),
                "northing_3794": round(cand["northing_3794"], 1),
                "tile": cand.get("tile"),
            },
        })
    return feature_collection(features)


def export(args) -> None:
    source_path = HYDRO_OUT / f"hydro_{args.date}.json"
    if not source_path.exists():
        raise SystemExit(f"Missing {source_path}. Run derive-fixture or derive first.")

    dataset = read_json(source_path)
    hydro_geojson = dataset["features"]
    candidates = read_json(WEBDATA / "candidates.json")
    dynamic_geojson = dynamic_risk_points(candidates, hydro_geojson["features"], args.date)

    hydro_file = f"hydro_{args.date}.geojson"
    dynamic_file = f"dynamic_risk_{args.date}.geojson"
    write_json(HYDRO_WEB / hydro_file, hydro_geojson)
    write_json(HYDRO_WEB / dynamic_file, dynamic_geojson)

    manifest = {
        "generated": now_iso(),
        "model_version": 1,
        "source": dataset["kind"],
        "model": dataset["model"],
        "baseline": dataset.get("baseline", "fixture values for V1 UI validation"),
        "dates": [
            {
                "date": args.date,
                "label": "Savinja Aug 2023 hindcast" if args.date == DEFAULT_DATE else args.date,
                "hydro_file": hydro_file,
                "dynamic_risk_file": dynamic_file,
            }
        ],
    }
    write_json(HYDRO_WEB / "manifest.json", manifest)
    print(f"Wrote web hydroclimate assets: {HYDRO_WEB}")


def build_parser():
    parser = argparse.ArgumentParser(description="Build ERA5-Land hydroclimate trigger assets.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fixture = sub.add_parser("derive-fixture", help="Build deterministic fixture data for the app.")
    p_fixture.add_argument("--date", default=DEFAULT_DATE)
    p_fixture.set_defaults(func=derive_fixture)

    p_derive = sub.add_parser("derive", help="Build hydroclimate data from ERA5-Land NetCDF files.")
    p_derive.add_argument("--input-dir", default=str(ROOT / "data" / "era5"))
    p_derive.add_argument("--date", default=DEFAULT_DATE)
    p_derive.add_argument("--cell-deg", type=float, default=0.1)
    p_derive.set_defaults(func=derive_real)

    p_export = sub.add_parser("export", help="Export derived hydroclimate data to web/data.")
    p_export.add_argument("--date", default=DEFAULT_DATE)
    p_export.set_defaults(func=export)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
