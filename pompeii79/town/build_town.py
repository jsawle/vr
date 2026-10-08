"""
Pompeii AD 79 town model (model version 0.1)

Builds the town for the app from the OpenStreetMap data (pompeii_osm_utm33.json):
  - the city wall circuit and its gates (from OSM);
  - city blocks (insulae) = the faces formed by the ancient streets inside the walls;
  - house plots along each block edge (frontage 8-16 m, depth 10-22 m), one or two storeys,
    with the middle of large blocks left open as gardens and courtyards
    (procedural, in the spirit of the CityEngine rules of Mueller et al. 2006);
  - named public buildings mapped in OSM (Basilica, temples, Macellum, Palestra Grande, ...)
    kept at their real footprints, taller than houses;
  - the Forum left open as a paved square, with the Temple of Jupiter at its north end;
  - the amphitheatre as an elliptical building;
  - street centre lines for the animated people.

Real footprints: wall, streets and named public buildings (OSM).
Generated: house plots and heights. Output is in UTM 33N metres, like the terrain.
"""
import json, math, random, sys
from pathlib import Path
from shapely.geometry import LineString, Polygon, Point, MultiPolygon, box
from shapely.ops import unary_union, polygonize, linemerge
from shapely import affinity
from shapely.geometry.polygon import orient

MODEL_VERSION = "0.1"
random.seed(79)
src = Path(sys.argv[1]); out = Path(sys.argv[2])
d = json.loads(src.read_text())

ANCIENT_SURFACE = {"stone", "sett", "unhewn_cobblestone", "paving_stones"}
def is_ancient_street(s):
    t = s["tags"]; n = t.get("name", "")
    if n.startswith(("Via ", "Vicolo ")) and n not in ("Via Plinio", "Via Nocera", "Via Villa dei Misteri", "Via Tenente Ravallese"):
        return True
    return t.get("highway") == "pedestrian" and t.get("surface") in ANCIENT_SURFACE

wall_ring = Polygon(d["walls"][0]["coords"])
city = wall_ring.buffer(0)
inner = city.buffer(-4)                                     # the wall itself is ~4 m thick here
streets = [LineString(s["coords"]) for s in d["streets"] if is_ancient_street(s)]
streets = [g.intersection(inner) for g in streets]
streets = [g for g in streets if not g.is_empty]
print(f"ancient streets kept: {len(streets)} pieces, {sum(g.length for g in streets)/1000:.1f} km")

# extend loose street ends by up to 12 m so they meet their neighbours (OSM lines do not always join)
def extend(ls, L=12):
    cs = list(ls.coords)
    if len(cs) < 2: return ls
    def ext(a, b):
        dx, dy = a[0] - b[0], a[1] - b[1]; n = math.hypot(dx, dy) or 1
        return (a[0] + dx / n * L, a[1] + dy / n * L)
    return LineString([ext(cs[0], cs[1])] + cs[1:-1] + [ext(cs[-1], cs[-2])])
lines = []
for g in streets:
    for part in getattr(g, "geoms", [g]):
        if part.geom_type == "LineString" and part.length > 3:
            lines.append(extend(part))
net = unary_union(lines + [inner.exterior])
faces = [f for f in polygonize(net) if f.area > 150 and inner.contains(f.representative_point())]
print(f"blocks from streets: {len(faces)}; area range {min(f.area for f in faces):.0f}-{max(f.area for f in faces):.0f} m2")

# split very large blocks (unexcavated areas have no mapped streets) with a street grid aligned to the block
def split_big(f, cell=75):
    if f.area < 9000: return [f]
    r = f.minimum_rotated_rectangle; c = list(r.exterior.coords)
    ang = math.degrees(math.atan2(c[1][1] - c[0][1], c[1][0] - c[0][0]))
    ctr = f.centroid
    g = affinity.rotate(f, -ang, origin=ctr)
    x0, y0, x1, y1 = g.bounds; parts = []
    nx, ny = max(1, round((x1 - x0) / cell)), max(1, round((y1 - y0) / (cell * 0.5)))
    for i in range(nx):
        for j in range(ny):
            b = box(x0 + i * (x1 - x0) / nx + 3, y0 + j * (y1 - y0) / ny + 3, x0 + (i + 1) * (x1 - x0) / nx - 3, y0 + (j + 1) * (y1 - y0) / ny - 3)
            p = g.intersection(b)
            for q in getattr(p, "geoms", [p]):
                if q.geom_type == "Polygon" and q.area > 150: parts.append(affinity.rotate(q, ang, origin=ctr))
    return parts or [f]
# every mapped ancient street stays open, even where the street lines do not close into blocks
street_space = unary_union([g.buffer(3.0, cap_style=2) for g in streets])
blocks = []
for f in faces:
    for p in split_big(f):
        b = p.buffer(-2.5, join_style=2).difference(street_space)   # half the street width (streets ~5 m incl. pavements)
        for q in getattr(b, "geoms", [b]):
            if q.geom_type == "Polygon" and q.area > 120: blocks.append(q.simplify(0.8))
print(f"blocks after splitting and street setback: {len(blocks)}")

# ---- named public buildings (real footprints) ----
PUBLIC = {   # name in OSM -> (kind, height m)
    "Basilica": ("basilica", 13), "Tempio di Apollo": ("temple", 15), "Edificio di Eumachia": ("hall", 10),
    "Santuario dei Lari Pubblici": ("hall", 10), "Tempio di Vespasiano": ("temple", 11), "Macellum": ("hall", 9),
    "Tempio d'Iside": ("temple", 10), "Granai del Foro": ("hall", 8), "Mensa Ponderaria": ("hall", 5),
    "Palestra Grande": ("palestra", 6), "Palestra Sannitica": ("palestra", 5), "Natatio": ("open", 0),
    "Castellum aquae": ("hall", 6), "Schola Armaturarum": ("hall", 7), "Lupanare Grande": ("house", 8),
    "Casa del Fauno": ("house", 8),
}
public = []
for coll in ("buildings", "other"):
    for o in d[coll]:
        n = o["tags"].get("name")
        if n in PUBLIC and len(o["coords"]) > 3:
            p = Polygon(o["coords"]).buffer(0)
            if p.area > 50 and inner.contains(p.representative_point()):
                kind, h = PUBLIC[n]; public.append({"name": n, "kind": kind, "h": h, "poly": p})
# amphitheatre: the OSM "Arena" polygon is the arena floor; the building is an ellipse around it
arena = next((Polygon(o["coords"]) for c in ("buildings", "other") for o in d[c] if o["tags"].get("name") == "Arena" and len(o["coords"]) > 3), None)
for p in public:
    if p["kind"] == "palestra": p["hole"] = p["poly"].buffer(-9, join_style=2)   # an open court inside porticoes
if arena is not None:
    a0 = arena.buffer(0)
    public.append({"name": "Amphitheatre", "kind": "amphitheatre", "h": 12, "poly": a0.buffer(34, resolution=24), "hole": a0})
print("public buildings:", sorted({p["name"] for p in public}), "arena:", bool(arena))

# ---- the Forum: the open space enclosed by the public buildings that line it (from the data) ----
FORUM_SIDE = ["Basilica", "Tempio di Apollo", "Granai del Foro", "Mensa Ponderaria", "Edificio di Eumachia",
              "Santuario dei Lari Pubblici", "Tempio di Vespasiano", "Macellum"]
side = [p["poly"] for p in public if p["name"] in FORUM_SIDE]
if len(side) < 6:
    sys.exit("not enough of the buildings around the Forum are in the data")
hull = unary_union(side).convex_hull
pub_union = unary_union([p["poly"] for p in public])
gap = hull.difference(pub_union.buffer(2))
forum_sq = max(getattr(gap, "geoms", [gap]), key=lambda g: g.area).buffer(-3, join_style=2)
forum_sq = max(getattr(forum_sq, "geoms", [forum_sq]), key=lambda g: g.area)
forum = hull.buffer(4)                                       # kept free of house plots
print(f"Forum square: {forum_sq.area:.0f} m2 (the real square is about 150 x 38 m)")
# Temple of Jupiter: on the long axis, at the north end of the square (podium ~17 x 37 m)
r = forum_sq.minimum_rotated_rectangle; c = list(r.exterior.coords)[:4]
edges = sorted([(c[i], c[(i + 1) % 4]) for i in range(4)], key=lambda e: math.dist(*e))
short = edges[:2]; north_edge = max(short, key=lambda e: (e[0][1] + e[1][1]))
mid = ((north_edge[0][0] + north_edge[1][0]) / 2, (north_edge[0][1] + north_edge[1][1]) / 2)
ctr = r.centroid; ax = (ctr.x - mid[0], ctr.y - mid[1]); L = math.hypot(*ax); ax = (ax[0] / L, ax[1] / L)
tc = (mid[0] + ax[0] * 20, mid[1] + ax[1] * 20)          # temple centre 20 m in from the north end
ang = math.degrees(math.atan2(ax[1], ax[0]))
jupiter = affinity.rotate(box(tc[0] - 18.5, tc[1] - 8.5, tc[0] + 18.5, tc[1] + 8.5), ang, origin=tc)
forum_open = forum_sq.difference(jupiter.buffer(1))

# ---- house plots ----
taken = unary_union([p["poly"].buffer(1) for p in public] + [forum])
lots = []
def lots_for(block):
    bl = block.difference(taken)
    for b in getattr(bl, "geoms", [bl]):
        if b.geom_type != "Polygon" or b.area < 60: continue
        b = orient(b, 1.0)                                      # counter-clockwise, so the left normal points inwards
        ring = list(b.exterior.coords)
        used = Polygon()
        for i in range(len(ring) - 1):
            p0, p1 = ring[i], ring[i + 1]; L = math.dist(p0, p1)
            if L < 6: continue
            ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
            nx, ny = -uy, ux                                   # inward normal (rings are made counter-clockwise below)
            s = 0.0
            while s < L - 4:
                w = min(random.uniform(8, 16), L - s)
                dep = random.uniform(10, 22)
                a = (p0[0] + ux * s, p0[1] + uy * s); bpt = (p0[0] + ux * (s + w), p0[1] + uy * (s + w))
                q = Polygon([a, bpt, (bpt[0] + nx * dep, bpt[1] + ny * dep), (a[0] + nx * dep, a[1] + ny * dep)])
                q = q.intersection(b).difference(used)
                for piece in getattr(q, "geoms", [q]):
                    if piece.geom_type == "Polygon" and piece.area > 35:
                        used = used.union(piece)
                        storeys = 2 if random.random() < 0.35 else 1
                        lots.append({"poly": piece.simplify(0.3), "h": 4.6 + 3.2 * (storeys - 1) + random.uniform(-0.4, 0.6)})
                s += w
        rest = b.difference(used)                               # the middle: gardens and courtyards
        for g in getattr(rest, "geoms", [rest]):
            if g.geom_type == "Polygon" and g.area > 30: gardens.append(g.simplify(0.5))
gardens = []
for b in blocks:
    lots_for(orient(b, 1.0))
print(f"house plots: {len(lots)}, gardens: {len(gardens)}")

# ---- gates: where the ancient streets cross the wall (from the data, unnamed) ----
gates = []
for st in d["streets"]:
    if not is_ancient_street(st): continue
    x = LineString(st["coords"]).intersection(city.exterior)
    for pt in getattr(x, "geoms", [x]):
        if pt.geom_type == "Point" and all(math.dist((pt.x, pt.y), g["xy"]) > 60 for g in gates):
            gates.append({"xy": [round(pt.x, 1), round(pt.y, 1)]})
print(f"gates found: {len(gates)}")

# ---- people's paths: the ancient streets (merged) ----
paths = []
for g in streets:
    for part in getattr(g, "geoms", [g]):
        if part.geom_type == "LineString" and part.length > 15:
            paths.append([[round(x, 1), round(y, 1)] for x, y in part.coords])

# ---- places to stand (from the data) ----
south_end = (2 * ctr.x - mid[0], 2 * ctr.y - mid[1])        # opposite the Temple of Jupiter
spot_forum = (south_end[0] - ax[0] * 25, south_end[1] - ax[1] * 25)
abb = [LineString(st["coords"]) for st in d["streets"] if st["tags"].get("name") == "Via dell'Abbondanza"]
abb = max(abb, key=lambda g: g.length) if abb else None
spot_abb = abb.interpolate(0.35, normalized=True) if abb else None
# each spot has a direction to look in: the Forum looks up its axis to the temple and the mountain;
# the street spot looks along the street, in the direction closer to the mountain
VENT = (451861.7, 4519196.8)
def towards_vent(dx, dy, x, y):
    vx, vy = VENT[0] - x, VENT[1] - y
    return (dx, dy) if dx * vx + dy * vy >= 0 else (-dx, -dy)
spots = {"forum": {"xy": [round(spot_forum[0], 1), round(spot_forum[1], 1)], "look": [round(-ax[0], 3), round(-ax[1], 3)]}}
if spot_abb is not None:
    d0 = abb.project(spot_abb); p0, p1 = abb.interpolate(max(0, d0 - 10)), abb.interpolate(min(abb.length, d0 + 10))
    L = math.hypot(p1.x - p0.x, p1.y - p0.y); dx, dy = towards_vent((p1.x - p0.x) / L, (p1.y - p0.y) / L, spot_abb.x, spot_abb.y)
    spots["abbondanza"] = {"xy": [round(spot_abb.x, 1), round(spot_abb.y, 1)], "look": [round(dx, 3), round(dy, 3)]}
print("spots:", spots)

def P(poly): return [[round(x, 1), round(y, 1)] for x, y in poly.exterior.coords]
res = {
    "model": "Pompeii town", "version": MODEL_VERSION, "crs": "EPSG:32633",
    "source": d["source"], "fetched": d["fetched"],
    "wall": P(wall_ring),
    "gates": gates,
    "forum": P(forum_open if forum_open.geom_type == "Polygon" else max(forum_open.geoms, key=lambda g: g.area)),
    "jupiter": P(jupiter),
    "public": [dict({"name": p["name"], "kind": p["kind"], "h": p["h"], "poly": P(p["poly"])}, **({"hole": P(p["hole"])} if p.get("hole") is not None and not p["hole"].is_empty else {})) for p in public],
    "arena": P(arena) if arena else None,
    "lots": [{"poly": P(l["poly"]), "h": round(l["h"], 1)} for l in lots if l["poly"].geom_type == "Polygon"],
    "gardens": [P(g) for g in gardens],
    "paths": paths,
    "spots": spots,
    "centre": [round(city.centroid.x, 1), round(city.centroid.y, 1)],
}
out.write_text(json.dumps(res, separators=(",", ":")))
print(f"wrote {out} ({out.stat().st_size/1e6:.1f} MB)")
