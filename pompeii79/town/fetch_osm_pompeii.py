"""Fetch the excavated city of Pompeii from OpenStreetMap (ODbL) via Overpass
and save buildings, streets and walls in UTM 33N metres (same CRS as the terrain).
Data (c) OpenStreetMap contributors, ODbL 1.0."""
import json, sys, time, urllib.request, urllib.parse
from pathlib import Path
from pyproj import Transformer
from shapely.geometry import Polygon, LineString, Point, shape
from shapely.ops import unary_union

BBOX = (40.7440, 14.4720, 40.7560, 14.4960)   # S, W, N, E around the Scavi
Q = f"""[out:json][timeout:120];
(
  way["historic"="archaeological_site"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  relation["historic"="archaeological_site"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["building"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["historic"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["highway"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["barrier"="city_wall"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["amenity"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["leisure"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["landuse"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
);
out geom tags;"""

ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter",
]

def fetch():
    for url in ENDPOINTS:
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": Q}).encode(),
                                         headers={"User-Agent": "pompeii79-education-app (github.com/jsawle/vr)"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r), url
        except Exception as e:
            print("failed", url, e); time.sleep(5)
    sys.exit("all Overpass endpoints failed")

data, used = fetch()
els = data["elements"]
print(f"{len(els)} elements from {used}")
tr = Transformer.from_crs("EPSG:4326", "EPSG:32633", always_xy=True)

def ring(geom):
    return [tr.transform(p["lon"], p["lat"]) for p in geom]

# the site boundary: the largest archaeological_site polygon containing the Forum
forum = Point(*tr.transform(14.4848, 40.7486))
sites = []
for e in els:
    t = e.get("tags", {})
    if t.get("historic") != "archaeological_site":
        continue
    polys = []
    if e["type"] == "way" and len(e.get("geometry", [])) > 3:
        polys = [Polygon(ring(e["geometry"]))]
    elif e["type"] == "relation":
        outers = [m for m in e.get("members", []) if m.get("role") == "outer" and m.get("geometry")]
        lines = [LineString(ring(m["geometry"])) for m in outers]
        from shapely.ops import polygonize
        polys = list(polygonize(unary_union(lines)))
    for p in polys:
        if p.is_valid and p.contains(forum):
            sites.append((p.area, t.get("name"), p))
sites.sort(key=lambda s: -s[0])
print("site polygons containing the Forum:", [(round(a / 1e4, 1), n) for a, n, _ in sites])
site = sites[0][2] if sites else None
if site is None:
    sys.exit("no archaeological site polygon around the Forum")
site_b = site.buffer(30)

buildings, streets, walls, other = [], [], [], []
for e in els:
    if e["type"] != "way" or "geometry" not in e:
        continue
    t = e.get("tags", {}); g = ring(e["geometry"])
    closed = len(g) > 3 and e["geometry"][0] == e["geometry"][-1]
    geom = Polygon(g) if closed else LineString(g)
    if not geom.is_valid or not site_b.intersects(geom):
        continue
    keep = {k: t[k] for k in ("name", "building", "historic", "amenity", "highway", "barrier",
                              "leisure", "ruins", "heritage", "tourism", "landuse", "area", "surface") if k in t}
    rec = {"id": e["id"], "tags": keep, "coords": [[round(x, 1), round(y, 1)] for x, y in g]}
    if "building" in t and closed:
        buildings.append(rec)
    elif "highway" in t and not closed:
        streets.append(rec)
    elif t.get("barrier") == "city_wall" or t.get("historic") == "citywalls":
        walls.append(rec)
    elif closed and t.get("historic") != "archaeological_site":
        other.append(rec)

out = {"source": "OpenStreetMap contributors, ODbL 1.0 (fetched via Overpass " + used + ")",
       "crs": "EPSG:32633", "fetched": time.strftime("%Y-%m-%d"),
       "site": [[round(x, 1), round(y, 1)] for x, y in site.exterior.coords],
       "buildings": buildings, "streets": streets, "walls": walls, "other": other}
Path(sys.argv[1]).write_text(json.dumps(out, separators=(",", ":")))
from collections import Counter
print(f"buildings {len(buildings)}, streets {len(streets)}, walls {len(walls)}, other {len(other)}")
print("building tags:", Counter(b["tags"].get("building") for b in buildings).most_common(10))
print("highway tags:", Counter(s["tags"].get("highway") for s in streets).most_common(10))
print("named:", sorted({b["tags"]["name"] for b in buildings + other if "name" in b["tags"]})[:80])
print("site area ha:", round(site.area / 1e4, 1))
