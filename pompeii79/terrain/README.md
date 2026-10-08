# Pre-AD 79 Vesuvius terrain (model 0.1)

Terrain for the planned Pompeii AD 79 case-study app. It is an illustrative
reconstruction for teaching, not a published paleo-DEM.

## What it does

1. Finds the Gran Cono summit and the surviving Somma caldera rim in today's DEM.
2. Removes the Gran Cono, which grew after AD 79, and puts a flat caldera floor at the
   measured level of the Atrio del Cavallo. Tadini et al. 2021 used the same
   simplification ([Solid Earth 12:119](https://se.copernicus.org/articles/12/119/2021/se-12-119-2021.pdf)).
3. Closes the Somma rim around the south, where AD 79 and later activity removed it.
   - The rim's radius and crest height are interpolated from the two ends of the surviving rim.
   - The crest is never lower than the floor plus three-quarters of the typical wall height.
   - The new outer flank blends into today's slopes.

The south rim's height is not known from any published source. The app's About panel
should say that this part is a reconstruction.

Not yet included: the AD 79 coastline, the old course of the Sarno, and the lower
ground surface of the plain (Vogel et al. 2011).

## How it runs

The GitHub Action `.github/workflows/pompeii79-terrain.yml` runs whenever the script
changes, or by hand from the Actions tab. It:

1. downloads the Copernicus GLO-30 tile from AWS open data, with no login;
2. runs the script;
3. commits the results to `output/`.

No ArcGIS Pro is needed. To use TINITALY 10 m instead, run the script locally on its tile:

```
pip install rasterio scipy numpy matplotlib pillow
python pre79_vesuvius.py TINITALY_TILE.tif output --source "TINITALY 1.1 (INGV), CC BY 4.0"
```

## Outputs (`output/`)

| File | What it is |
| --- | --- |
| `vesuvius_pre79_v0_1_utm33.tif` | Pre-79 terrain, GeoTIFF, UTM 33N. Add it to ArcGIS Pro or Online. |
| `vesuvius_today_utm33.tif` | The input terrain on the same grid. |
| `vesuvius_pre79_minus_today_utm33.tif` | Change in metres. Negative means the Gran Cono was removed; positive means the rim was rebuilt. |
| `vesuvius_pre79_app_terrarium.png` + `.json` | App heightmap in the Terrarium encoding the VR apps already decode, with its grid. |
| `vesuvius_today_app_terrarium.png` + `.json` | Today's terrain on the same grid, for the "today" toggle. |
| `preview_maps.png`, `preview_profile_NS.png` | Quick-look images. |
| `pre79_model_info.json` | Measured values and all parameters. |

## Versions

| Model | Version | Notes |
| --- | --- | --- |
| Pre-79 terrain | 0.1 | First version: Gran Cono removed, flat caldera floor, Somma rim closed to the south. |

## Data credits

Copernicus GLO-30: © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018,
provided under COPERNICUS by the European Union and ESA; all rights reserved.

TINITALY (if used): INGV, CC BY 4.0.

Created by Jason Sawle.
