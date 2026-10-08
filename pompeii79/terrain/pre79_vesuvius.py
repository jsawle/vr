"""
Pre-AD 79 Vesuvius terrain model  (model version 0.1)

Rebuilds an illustrative pre-79 surface of Somma-Vesuvius from a modern DEM:
  1. removes the Gran Cono (grew after AD 79) and replaces the caldera interior
     with a flat floor, as in the simplified pre-79 DEM of Tadini et al. 2021;
  2. finds the surviving Somma caldera rim in the modern DEM (radial profiles);
  3. closes the rim across the gap to the south (where the AD 79 collapse and
     later activity removed it) by interpolating rim radius and crest height,
     with an inner wall and an outer flank that blends into today's slopes.

Everything is measured from the input DEM; the only fixed inputs are the
approximate Gran Cono summit position and the tuning parameters below.
It is a reconstruction for teaching, not a published paleo-DEM.

Usage:
  python3 pre79_vesuvius.py INPUT_DEM.tif OUTPUT_DIR
Input: any GeoTIFF DEM (TINITALY, Esri World Elevation export, Copernicus).
It is reprojected to UTM 33N (EPSG:32633) for processing.
"""
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform as warp_xy
from scipy import ndimage

MODEL_VERSION = "0.1"

PARAMS = {
    "summit_lonlat": [14.426, 40.821],   # Gran Cono summit, Smithsonian GVP (approx.)
    "summit_search_m": 1500,             # look for the highest point within this distance
    "az_step_deg": 2.0,
    "profile_max_m": 5000,
    "moat_search_m": [600, 3000],        # where the inner moat (Atrio del Cavallo) can be
    "rim_search_max_m": 4500,
    "min_wall_height_m": 60,
    "profile_smooth_m": 150,             # smooth profiles (trees/buildings in surface models)             # crest minus moat floor needed to count as a rim
    "edge_blend_deg": 6,                # azimuth ramp where the rebuilt rim meets the real one
    "outer_flank_m": 2500,               # rebuilt outer flank length before it meets today's slope
    "floor_smooth_m": 120,
    "rim_end_samples": 5,                # azimuths averaged at each end of the surviving rim
    "min_rebuilt_wall_frac": 0.75,       # rebuilt crest >= floor + this x median wall height
    "work_crs": "EPSG:32633",
}


def load_to_utm(path, crs, bbox=None):
    """Read the DEM (optionally only the lon/lat bbox) and reproject to the work CRS."""
    from rasterio.windows import from_bounds
    from rasterio.warp import transform_bounds
    with rasterio.open(path) as src:
        if bbox:
            b = transform_bounds("EPSG:4326", src.crs, *bbox)
            win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
            data = src.read(1, window=win).astype("float32")
            s_tr = src.window_transform(win)
        else:
            data = src.read(1).astype("float32")
            s_tr = src.transform
        if src.nodata is not None:
            data[data == src.nodata] = np.nan
        h0, w0 = data.shape
        left, top = s_tr.c, s_tr.f
        right, bottom = left + w0 * s_tr.a, top + h0 * s_tr.e
        transform, w, h = calculate_default_transform(src.crs, crs, w0, h0, left, bottom, right, top)
        dst = np.full((h, w), np.nan, dtype="float32")
        reproject(data, dst, src_transform=s_tr, src_crs=src.crs, dst_transform=transform,
                  dst_crs=crs, resampling=Resampling.bilinear, src_nodata=np.nan, dst_nodata=np.nan)
    return dst, transform


def save_terrarium(path, arr, transform, crs, step):
    """App heightmap: Terrarium-encoded PNG (height = R*256 + G + B/256 - 32768),
    the same encoding the Vesuvius VR apps already decode, plus a JSON of its grid."""
    from PIL import Image
    from rasterio.warp import transform_bounds
    a = arr[::step, ::step]
    v = np.nan_to_num(a, nan=0.0) + 32768.0
    r = np.floor(v / 256); g = np.floor(v - r * 256); b = np.floor((v - np.floor(v)) * 256)
    rgb = np.stack([r, g, b], axis=-1).astype("uint8")
    Image.fromarray(rgb, "RGB").save(path)
    res = abs(transform.a) * step
    left, top = transform.c, transform.f
    right, bottom = left + a.shape[1] * res, top - a.shape[0] * res
    meta = {"encoding": "terrarium", "crs": crs, "cell_m": res, "width": a.shape[1], "height": a.shape[0],
            "bounds_utm": [left, bottom, right, top],
            "bounds_lonlat": list(transform_bounds(crs, "EPSG:4326", left, bottom, right, top))}
    Path(str(path).replace(".png", ".json")).write_text(json.dumps(meta, indent=2))


def sample(dem, transform, xs, ys):
    """Bilinear sample at map coordinates (arrays)."""
    inv = ~transform
    cols, rows = inv * (xs, ys)
    return ndimage.map_coordinates(dem, [rows - 0.5, cols - 0.5], order=1, mode="nearest")


def periodic_fill(az, values, valid):
    """Linear interpolation of values over invalid azimuths, wrapping at 360."""
    a, v = az[valid], values[valid]
    a3 = np.concatenate([a - 360, a, a + 360])
    v3 = np.concatenate([v, v, v])
    return np.interp(az, a3, v3)


def reconstruct(dem, transform, p=PARAMS, log=print):
    res = abs(transform.a)
    rows, cols = np.indices(dem.shape)
    X, Y = transform * (cols + 0.5, rows + 0.5)

    # 1. Gran Cono summit: highest cell near the GVP position
    sx, sy = warp_xy("EPSG:4326", p["work_crs"], [p["summit_lonlat"][0]], [p["summit_lonlat"][1]])
    d = np.hypot(X - sx[0], Y - sy[0])
    near = np.where(d < p["summit_search_m"], dem, -np.inf)
    r0, c0 = np.unravel_index(np.nanargmax(near), dem.shape)
    cx, cy, summit_z = X[r0, c0], Y[r0, c0], float(dem[r0, c0])
    log(f"Gran Cono summit found: {summit_z:.0f} m")

    # 2. Radial profiles: moat floor and Somma crest for each azimuth
    az = np.arange(0, 360, p["az_step_deg"])
    r = np.arange(0, p["profile_max_m"], res)
    moat_r = np.full(az.size, np.nan); moat_z = np.full(az.size, np.nan)
    crest_r = np.full(az.size, np.nan); crest_z = np.full(az.size, np.nan)
    for i, a in enumerate(np.radians(az)):
        px, py = cx + r * np.sin(a), cy + r * np.cos(a)        # azimuth from north, clockwise
        z = sample(dem, transform, px, py)
        # Walk outward from the cone: the rim is where the profile first climbs
        # min_wall_height above the lowest point passed so far (the moat).
        z = ndimage.uniform_filter1d(z, max(1, int(p["profile_smooth_m"] / res)))
        start = np.searchsorted(r, p["moat_search_m"][0])
        stop = np.searchsorted(r, p["rim_search_max_m"])
        seg = z[start:stop]
        runmin = np.minimum.accumulate(seg)
        rise = seg - runmin
        hit = np.flatnonzero(rise >= p["min_wall_height_m"])
        if not hit.size:
            continue
        h0 = hit[0]
        im = start + int(np.argmin(seg[:h0 + 1]))
        if r[im] > p["moat_search_m"][1]:
            continue
        # crest: keep climbing until the profile falls clearly below its highest point
        top = h0
        for j in range(h0, seg.size):
            if seg[j] > seg[top]:
                top = j
            elif seg[top] - seg[j] > p["min_wall_height_m"]:
                break
        else:
            continue  # still climbing at the search limit: not a rim
        ic = start + top
        moat_r[i], moat_z[i], crest_r[i], crest_z[i] = r[im], z[im], r[ic], z[ic]
    rim = ~np.isnan(crest_r)
    if rim.sum() < 10:
        for a_deg in (330, 0, 30):          # help diagnose: print a few profiles
            a = np.radians(a_deg)
            zz = sample(dem, transform, cx + r * np.sin(a), cy + r * np.cos(a))
            k = max(1, int(150 / res))
            log(f"profile {a_deg} deg (every {k*res:.0f} m): " + " ".join(f"{v:.0f}" for v in zz[::k]))
        raise RuntimeError("Could not find enough of the Somma rim; check the DEM covers the volcano")
    log(f"Somma rim found on {rim.sum()} of {az.size} azimuths "
        f"(crest {np.nanmin(crest_z):.0f}-{np.nanmax(crest_z):.0f} m, radius "
        f"{np.nanmin(crest_r)/1000:.1f}-{np.nanmax(crest_r)/1000:.1f} km)")

    # keep the largest continuous run of rim azimuths (the real Somma wall)
    lab, n = ndimage.label(np.concatenate([rim, rim]))
    best = max(range(1, n + 1), key=lambda k: (lab == k).sum())
    run = (lab == best)
    keep = run[:az.size] | run[az.size:]
    rim &= keep

    floor_z = float(np.nanmedian(moat_z[rim]))
    wall_w = float(np.nanmedian(crest_r[rim] - moat_r[rim]))
    R = periodic_fill(az, crest_r, rim)
    # Crest height across the gap: robust value at each end of the surviving
    # rim (median of the nearest few azimuths), interpolated across the gap,
    # and never lower than floor + the median wall height (so the caldera is closed).
    n_end = p["rim_end_samples"]
    idx = np.flatnonzero(rim)
    order = np.argsort((idx - idx[0]) % az.size)  # rim indices in run order
    run_idx = idx[order]
    gaps = np.flatnonzero(np.diff(np.r_[run_idx, run_idx[0] + az.size]) % az.size > 1)
    H = crest_z.copy()
    if gaps.size:
        g = gaps[0]
        end_a = run_idx[max(0, g - n_end + 1):g + 1]          # last azimuths before the gap
        start_b = run_idx[g + 1:g + 1 + n_end] if g + 1 < run_idx.size else run_idx[:n_end]
        ha, hb = float(np.median(crest_z[end_a])), float(np.median(crest_z[start_b]))
        ia, ib = run_idx[g], (run_idx[(g + 1) % run_idx.size])
        span = (ib - ia) % az.size
        for k in range(1, span):
            H[(ia + k) % az.size] = ha + (hb - ha) * k / span
    wall_h = float(np.nanmedian(crest_z[rim] - moat_z[rim]))
    min_crest = float(np.nanmedian(moat_z[rim])) + p["min_rebuilt_wall_frac"] * wall_h
    H = np.where(rim, crest_z, np.maximum(H, min_crest))
    Rm = periodic_fill(az, moat_r, rim)
    # in the gap, inner wall width = median wall width
    Rm = np.where(rim, Rm, R - wall_w)
    log(f"Caldera floor set to {floor_z:.0f} m (median of the moat floor); "
        f"rebuilt rim gap: {az.size - rim.sum()} azimuths")

    # weight: 0 on the real rim, ramping to 1 inside the gap
    dist_to_rim = ndimage.distance_transform_edt(np.tile(~rim, 3))[az.size:2 * az.size] * p["az_step_deg"]
    w_gap = np.clip(dist_to_rim / p["edge_blend_deg"], 0, 1)

    # 3. Build the surface cell by cell (polar lookup)
    ang = (np.degrees(np.arctan2(X - cx, Y - cy)) + 360) % 360
    rr = np.hypot(X - cx, Y - cy)
    Ri = np.interp(ang, np.r_[az, 360], np.r_[R, R[0]])
    Hi = np.interp(ang, np.r_[az, 360], np.r_[H, H[0]])
    Rmi = np.interp(ang, np.r_[az, 360], np.r_[Rm, Rm[0]])
    Wi = np.interp(ang, np.r_[az, 360], np.r_[w_gap, w_gap[0]])

    new = dem.copy()
    # a) flat caldera floor inside the moat line (removes the Gran Cono)
    inside = rr < Rmi
    new[inside] = floor_z
    # b) inner wall in the gap: smooth rise from floor to crest
    wall = (rr >= Rmi) & (rr < Ri)
    t = np.clip((rr - Rmi) / np.maximum(Ri - Rmi, 1), 0, 1)
    s = t * t * (3 - 2 * t)
    wall_z = floor_z + (Hi - floor_z) * s
    new[wall] = (1 - Wi[wall]) * dem[wall] + Wi[wall] * wall_z[wall]
    # c) outer flank in the gap: from crest down to today's terrain at R + L
    L = p["outer_flank_m"]
    flank = (rr >= Ri) & (rr < Ri + L)
    edge_x = cx + (Ri + L) * np.sin(np.radians(ang))
    edge_y = cy + (Ri + L) * np.cos(np.radians(ang))
    z_edge = sample(dem, transform, edge_x.ravel(), edge_y.ravel()).reshape(dem.shape)
    tf = np.clip((rr - Ri) / L, 0, 1)
    flank_z = Hi - (Hi - z_edge) * (1 - (1 - tf) ** 2)
    fz = np.maximum(dem, flank_z)                              # never cut below today here
    new[flank] = (1 - Wi[flank]) * dem[flank] + Wi[flank] * fz[flank]

    # 4. Smooth only the edited zone, feathered
    edited = np.abs(new - dem) > 0.01
    k = p["floor_smooth_m"] / res
    sm = ndimage.gaussian_filter(np.nan_to_num(new, nan=floor_z), k)
    feather = np.clip(ndimage.gaussian_filter(edited.astype("float32"), k) * 2, 0, 1)
    out = np.where(np.isnan(dem), np.nan, feather * sm + (1 - feather) * new).astype("float32")

    info = {
        "model": "Pre-79 terrain", "version": MODEL_VERSION, "params": p,
        "gran_cono_summit_m": round(summit_z), "caldera_floor_m": round(floor_z),
        "somma_crest_range_m": [round(float(np.nanmin(crest_z[rim]))), round(float(np.nanmax(crest_z[rim])))],
        "rim_azimuths_found_deg": [float(a) for a in az[rim]],
        "rebuilt_rim_crest_range_m": [round(float(H[~rim].min())), round(float(H[~rim].max()))] if (~rim).any() else None,
        "max_lowering_m": round(float(np.nanmax(dem - out))),
        "max_raising_m": round(float(np.nanmax(out - dem))),
        "centre_xy": [float(cx), float(cy)],
    }
    return out, info, (az, R, H, Rm, rim)


def save(path, arr, transform, crs):
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                       dtype="float32", crs=crs, transform=transform, nodata=np.nan,
                       compress="deflate", predictor=3, tiled=True) as dst:
        dst.write(arr, 1)


def previews(today, pre79, transform, info, rimdata, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource

    res = abs(transform.a)
    ls = LightSource(azdeg=315, altdeg=40)
    ext = [transform.c, transform.c + today.shape[1] * res, transform.f - today.shape[0] * res, transform.f]
    fig, ax = plt.subplots(1, 3, figsize=(18, 6.4))
    vmax = np.nanmax(today)
    for a, arr, title in [(ax[0], today, "Today"), (ax[1], pre79, f"Pre-AD 79 reconstruction (model {MODEL_VERSION})")]:
        a.imshow(ls.shade(np.nan_to_num(arr), cmap=plt.cm.gist_earth, vert_exag=1.5, blend_mode="soft",
                          vmin=0, vmax=vmax, dx=res, dy=res), extent=ext)
        a.contour(np.flipud(arr), levels=np.arange(200, 1400, 200), colors="k", linewidths=0.3,
                  extent=ext, origin="lower")
        a.set_title(title); a.set_xticks([]); a.set_yticks([])
    diff = pre79 - today
    lim = np.nanmax(np.abs(diff))
    im = ax[2].imshow(diff, cmap="RdBu", vmin=-lim, vmax=lim, extent=ext)
    ax[2].set_title("Change (m): blue = rebuilt rim, red = Gran Cono removed")
    ax[2].set_xticks([]); ax[2].set_yticks([])
    fig.colorbar(im, ax=ax[2], fraction=0.046)
    fig.tight_layout(); fig.savefig(outdir / "preview_maps.png", dpi=110); plt.close(fig)

    # N-S profile through the summit
    cx, cy = info["centre_xy"]
    s = np.arange(-6000, 6000, res)
    zs_t = sample(today, transform, np.full_like(s, cx), cy + s)
    zs_p = sample(pre79, transform, np.full_like(s, cx), cy + s)
    fig, a = plt.subplots(figsize=(10, 3.6))
    a.plot(s / 1000, zs_t, color="0.5", label="Today")
    a.plot(s / 1000, zs_p, color="C3", label=f"Pre-AD 79 model {MODEL_VERSION}")
    a.set_xlabel("km from the Gran Cono summit (south  ←  →  north)")
    a.set_ylabel("Elevation (m)"); a.legend(); a.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(outdir / "preview_profile_NS.png", dpi=110); plt.close(fig)


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dem"); ap.add_argument("outdir")
    ap.add_argument("--bbox", type=float, nargs=4, metavar=("W", "S", "E", "N"),
                    default=[14.30, 40.68, 14.62, 40.90], help="area to process, lon/lat")
    ap.add_argument("--source", default="unknown DEM", help="name of the input DEM, for the info file")
    ap.add_argument("--app-cell-m", type=float, default=30, help="cell size of the app heightmap")
    args = ap.parse_args()
    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)
    crs = PARAMS["work_crs"]
    dem, transform = load_to_utm(args.dem, crs, args.bbox)
    pre79, info, rimdata = reconstruct(dem, transform)
    info["source_dem"] = args.source
    info["bbox_lonlat"] = args.bbox
    info["cell_m"] = abs(transform.a)
    save(outdir / "vesuvius_today_utm33.tif", dem, transform, crs)
    save(outdir / f"vesuvius_pre79_v{MODEL_VERSION.replace('.', '_')}_utm33.tif", pre79, transform, crs)
    save(outdir / "vesuvius_pre79_minus_today_utm33.tif", pre79 - dem, transform, crs)
    step = max(1, int(round(args.app_cell_m / abs(transform.a))))
    save_terrarium(outdir / "vesuvius_pre79_app_terrarium.png", pre79, transform, crs, step)
    save_terrarium(outdir / "vesuvius_today_app_terrarium.png", dem, transform, crs, step)
    (outdir / "pre79_model_info.json").write_text(json.dumps(info, indent=2))
    previews(dem, pre79, transform, info, rimdata, outdir)
    print(json.dumps({k: v for k, v in info.items() if k not in ("params", "rim_azimuths_found_deg")}, indent=2))


if __name__ == "__main__":
    main()
