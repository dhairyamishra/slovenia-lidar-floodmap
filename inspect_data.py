"""
Quick data shape inspector for all CLSS file types.
Writes results to DATA_SAMPLES.md
"""
import laspy
import rasterio
import numpy as np
from pathlib import Path

DATA = Path("data")
OUT  = Path("DATA_SAMPLES.md")

lines = []
def h(s): lines.append(s)

h("# CLSS Slovenia — Data Samples\n")
h(f"> Workspace: `data/`  |  CRS: EPSG:3794\n")

# ─── LAZ files ────────────────────────────────────────────────────────────────

LAZ_GROUPS = {
    "GKOT — Classified Point Cloud": sorted(DATA.glob("GKOT_*.laz")),
    "DMP  — Surface Model (DSM)"   : sorted(DATA.glob("DMP_*.laz")),
    "DMR  — Terrain Model (DTM)"   : sorted(DATA.glob("DMR_*.laz")),
}

for group_name, files in LAZ_GROUPS.items():
    h(f"---\n\n## {group_name}\n")
    if not files:
        h("_No files found._\n")
        continue

    # Only fully inspect first file; show names for the rest
    for i, f in enumerate(files):
        h(f"### `{f.name}`\n")
        las = laspy.read(str(f))
        pts = len(las.points)
        dims = [str(d.name) for d in las.point_format.dimensions]

        h(f"| Field | Value |")
        h(f"|---|---|")
        h(f"| Point count | `{pts:,}` |")
        h(f"| Point format ID | `{las.point_format.id}` |")
        h(f"| Dimensions | `{', '.join(dims)}` |")

        x = np.asarray(las.x)
        y = np.asarray(las.y)
        z = np.asarray(las.z)
        h(f"| X range | `{x.min():.2f}` → `{x.max():.2f}` m |")
        h(f"| Y range | `{y.min():.2f}` → `{y.max():.2f}` m |")
        h(f"| Z range | `{z.min():.2f}` → `{z.max():.2f}` m |")
        h(f"| Bounding box (XY) | `{x.max()-x.min():.0f} × {y.max()-y.min():.0f}` m |")

        # Classification breakdown (GKOT only — others may not have it)
        if "classification" in dims:
            cls = np.asarray(las.classification)
            unique, counts = np.unique(cls, return_counts=True)
            CLASS_NAMES = {
                0:"Never classified", 1:"Unclassified", 2:"Ground",
                3:"Low veg", 4:"Med veg", 5:"High veg", 6:"Building",
                7:"Low noise", 8:"Reserved", 9:"Water", 10:"Rail",
                11:"Road surface", 12:"Reserved", 13:"Wire guard",
                14:"Wire conductor", 15:"Tower", 17:"Bridge deck",
                18:"High noise"
            }
            h(f"\n**Classification breakdown:**\n")
            h(f"| Class | Label | Point count | % |")
            h(f"|---|---|---:|---:|")
            for c, n in sorted(zip(unique, counts)):
                label = CLASS_NAMES.get(int(c), f"Class {c}")
                h(f"| `{c}` | {label} | `{n:,}` | `{100*n/pts:.1f}` |")

        # First 5 points as sample
        h(f"\n**First 5 points (X, Y, Z{', classification' if 'classification' in dims else ''}):**\n")
        h("```")
        for j in range(min(5, pts)):
            row = f"  X={x[j]:.3f}  Y={y[j]:.3f}  Z={z[j]:.3f}"
            if "classification" in dims:
                cls_arr = np.asarray(las.classification)
                row += f"  class={int(cls_arr[j])}"
            h(row)
        h("```\n")

# ─── TIF files ────────────────────────────────────────────────────────────────

TIF_GROUPS = {
    "nDMP — Normalized Height above Ground (.tif)": sorted(DATA.glob("nDMP_*.tif")),
    "PAS  — Analytic Hillshade (.tif)"            : sorted(DATA.glob("PAS_*.tif")),
    "POF  — RGB Orthophoto (.tif)"                : sorted(DATA.glob("POF_*.tif")),
    "POFI — Infrared Orthophoto (.tif)"           : sorted(DATA.glob("POFI_*.tif")),
}

for group_name, files in TIF_GROUPS.items():
    h(f"---\n\n## {group_name}\n")
    if not files:
        h("_No files found._\n")
        continue

    for f in files:
        h(f"### `{f.name}`\n")
        with rasterio.open(str(f)) as src:
            h(f"| Field | Value |")
            h(f"|---|---|")
            h(f"| Driver | `{src.driver}` |")
            h(f"| CRS | `{src.crs}` |")
            h(f"| Width × Height | `{src.width} × {src.height}` px |")
            h(f"| Band count | `{src.count}` |")
            h(f"| Pixel size | `{src.res[0]:.4f} × {src.res[1]:.4f}` m |")
            h(f"| Bounding box | `{src.bounds}` |")
            h(f"| dtype | `{src.dtypes[0]}` |")

            # Read band 1 stats
            data = src.read(1, masked=True)
            h(f"| Band 1 min | `{float(data.min()):.4f}` |")
            h(f"| Band 1 max | `{float(data.max()):.4f}` |")
            h(f"| Band 1 mean | `{float(data.mean()):.4f}` |")
            h(f"| Band 1 nodata | `{src.nodata}` |")

            # Multi-band: show per-band stats
            if src.count > 1:
                h(f"\n**Per-band stats (min / max / mean):**\n")
                h(f"| Band | Min | Max | Mean |")
                h(f"|---|---|---|---|")
                for b in range(1, src.count + 1):
                    bd = src.read(b, masked=True)
                    h(f"| {b} | `{float(bd.min()):.2f}` | `{float(bd.max()):.2f}` | `{float(bd.mean()):.2f}` |")

            # 3×3 pixel sample from centre
            cx, cy = src.width // 2, src.height // 2
            h(f"\n**3×3 pixel window at centre (band 1):**\n")
            h("```")
            window = rasterio.windows.Window(cx-1, cy-1, 3, 3)
            patch = src.read(1, window=window)
            for row in patch:
                h("  " + "  ".join(f"{v:>10.4f}" for v in row))
            h("```\n")

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"Written: {OUT}")
