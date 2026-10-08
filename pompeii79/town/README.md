# Pompeii AD 79 town (model 0.1)

The town for `pompeii-79-vr.html`.

## Files

- `fetch_osm_pompeii.py` downloads the excavated city from OpenStreetMap through Overpass.
  - The GitHub Action `.github/workflows/pompeii79-town.yml` runs it, because this workspace cannot reach Overpass.
  - It writes `pompeii_osm_utm33.json` and `fetch_log.txt`.
  - The Russian Overpass mirror is not used.
- `build_town.py` builds `pompeii_town_v0_1.json` for the app. Run it locally:
  `python build_town.py pompeii_osm_utm33.json pompeii_town_v0_1.json`

## What is real and what is generated

| Part | Source |
| --- | --- |
| City wall and gates | OpenStreetMap. The gates are where the ancient streets cross the wall, so they are unnamed. |
| Ancient streets | OpenStreetMap: named `Via` and `Vicolo` streets, and pedestrian ways with stone or sett paving. |
| Public buildings | OpenStreetMap footprints: Basilica, Temple of Apollo, Eumachia, Macellum, Palestra Grande and others. Heights are estimates. |
| The Forum | The open space between the mapped buildings that line it. It comes out at about 5,300 m², close to the real 150 × 38 m square. |
| Temple of Jupiter | Placed at the north end of the Forum: a 17 × 37 m podium with the temple on it. |
| Amphitheatre | The OSM arena plus a 34 m ring of stands. |
| Houses | **Generated.** Plots of 8–16 m frontage and 10–22 m depth along each block, with one or two storeys and gardens in the middle. They follow the same idea as the CityEngine rules of Müller et al. 2006. |

Only about 400 buildings in the excavated city are mapped in OpenStreetMap, so most houses are generated. The theatres and the Triangular Forum are not in this version.

The Pompeii Bibliography and Mapping Project (UMass) has a fuller city GIS on ArcGIS Online. It is copyrighted, so it needs Eric Poehler's permission before it can replace these generated houses.

## Places to stand

`spots` in the town file holds two places to stand, each with a viewing direction:
- the south end of the Forum, looking up its axis to the Temple of Jupiter and the mountain;
- Via dell'Abbondanza, looking along the street.

## Data credits

Streets, wall and public buildings © OpenStreetMap contributors, ODbL 1.0.
