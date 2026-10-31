#!/usr/bin/env python3
"""
generate_fixtures.py — build a small synthetic pincode-boundary KML with
entirely invented PIN codes (900xxx, not real postal codes) used only to
exercise every validation check's failure and success paths. No real
geography, no real PIN codes, no company/client data — safe to commit.

Run once: python3 generate_fixtures.py
Writes: fixtures/synthetic_pincodes.kml
"""
import math
import os

OUT_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
os.makedirs(OUT_DIR, exist_ok=True)


def noisy(v, salt=0):
    """Add deterministic, geometrically-negligible decimal entropy so
    synthetic 'good' coordinates don't coincidentally look fabricated
    (clean/round) to check_round_number_fraction — real digitized survey
    data never lands on round numbers, and the test fixtures for a
    'should pass' case need to actually look like that, not just be
    irregular in shape while having suspiciously clean values."""
    return round(v + 1e-5 * math.sin(v * 9973.123 + salt * 7919.456), 6)


def jittered_polygon(cx, cy, r, n, seed_offset=0, jitter=0.15):
    """A closed ring with n vertices, irregular enough to pass the
    round-number and minimum-complexity checks — like real digitized data."""
    pts = []
    for i in range(n):
        angle = 2 * math.pi * i / n
        rr = r * (1 + jitter * math.sin(angle * 3 + seed_offset) * 0.5)
        x = cx + rr * math.cos(angle)
        y = cy + rr * math.sin(angle)
        pts.append((noisy(x, seed_offset + i), noisy(y, seed_offset + i + 0.5)))
    pts.append(pts[0])
    return pts


def coord_str(coords):
    return " ".join(f"{x},{y}" for x, y in coords)


def placemark(pin, office, division, outer, inner_rings=None, extra_polys=None):
    inner_xml = ""
    for ring in (inner_rings or []):
        inner_xml += f"<innerBoundaryIs><LinearRing><coordinates>{coord_str(ring)}</coordinates></LinearRing></innerBoundaryIs>"
    geom = f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{coord_str(outer)}</coordinates></LinearRing></outerBoundaryIs>{inner_xml}</Polygon>"
    if extra_polys:
        parts = [geom]
        for extra_outer in extra_polys:
            parts.append(f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{coord_str(extra_outer)}</coordinates></LinearRing></outerBoundaryIs></Polygon>")
        geom = "<MultiGeometry>" + "".join(parts) + "</MultiGeometry>"
    return f"""<Placemark><name></name><ExtendedData>
<Data name="Pincode"><value>{pin}</value></Data>
<Data name="Office_Name"><value>{office}</value></Data>
<Data name="Division"><value>{division}</value></Data>
<Data name="Region"><value>Test Region</value></Data>
<Data name="Circle"><value>Test Circle</value></Data>
</ExtendedData>{geom}</Placemark>"""


placemarks = []

# 900001 / 900002: two valid, touching, irregular polygons — positive
# control for a clean merge (share an exact vertical seam at x=1.0).
def seam_pair(cx1, cx2, cy, n=16):
    # build each as irregular but force them to share an exact edge
    left = jittered_polygon(cx1, cy, 1.0, n, seed_offset=1)
    right = jittered_polygon(cx2, cy, 1.0, n, seed_offset=2)
    return left, right

left, right = seam_pair(0.0, 2.0, 0.0)
# Instead of relying on jitter to create a real shared edge (unreliable),
# build two rectangles with a shared straight edge plus irregular jitter
# only on the outer sides, so they provably touch along x=1.0.
def half_blob(sign, n=50):
    # Shared seam at x=0 must stay EXACT between the two halves (that's
    # what makes them truly touch), so no noise on the seam endpoints —
    # only on the irregular outer points. n is large enough that these 2
    # unavoidably-round seam points stay under the 10% round-number
    # threshold on their own.
    pts = [(sign * 0.0, -1.0), (sign * 0.0, 1.0)]
    for i in range(1, n):
        t = i / n
        angle = math.pi * t
        x = sign * (0.2 + 0.8 * math.sin(angle) * (1 + 0.1 * math.sin(angle * 5)))
        y = 1.0 - 2.0 * t
        pts.append((noisy(x, i), noisy(y, i + 0.5)))
    pts.append(pts[0])
    return pts

poly_a = half_blob(-1)
poly_b = half_blob(1)
placemarks.append(placemark("900001", "Alpha SO", "Test Division", poly_a))
placemarks.append(placemark("900002", "Beta SO", "Test Division", poly_b))

# 900003: hexagon, round-number coordinates — should fail BOTH
# minimum_complexity and round_number_fraction.
hexagon = [
    (10.000, 10.000), (10.500, 10.000), (10.750, 10.500),
    (10.500, 11.000), (10.000, 11.000), (9.750, 10.500),
    (10.000, 10.000),
]
placemarks.append(placemark("900003", "Gamma SO", "Test Division", hexagon))

# 900004: valid-complexity polygon but an OPEN ring (first != last) —
# hand-broken on purpose, should fail ring_closed.
open_ring = jittered_polygon(20.0, 20.0, 1.0, 16, seed_offset=4)
open_ring[-1] = (open_ring[-1][0] + 0.5, open_ring[-1][1] + 0.5)  # break closure
placemarks.append(placemark("900004", "Delta SO", "Test Division", open_ring))

# 900005 / 900006: two polygons that genuinely OVERLAP (not just touch) —
# should fail check_no_overlap in merge.
placemarks.append(placemark("900005", "Epsilon SO", "Test Division",
                             jittered_polygon(30.0, 30.0, 1.0, 16, seed_offset=5, jitter=0.05)))
placemarks.append(placemark("900006", "Zeta SO", "Test Division",
                             jittered_polygon(30.6, 30.0, 1.0, 16, seed_offset=6, jitter=0.05)))

# 900015 / 900016: two polygons with a TINY overlap (well under the
# default 1e-6 relative tolerance) — should merge successfully with NO
# flags needed, proving --tolerance actually reaches the overlap check
# now (v0.2's check failed on any nonzero overlap, making --tolerance
# meaningless for this exact scenario).
placemarks.append(placemark("900015", "Rho SO", "Test Division",
                             jittered_polygon(60.0, 60.0, 1.0, 30, seed_offset=15, jitter=0.0)))
placemarks.append(placemark("900016", "Sigma SO", "Test Division",
                             jittered_polygon(61.99995, 60.0, 1.0, 30, seed_offset=16, jitter=0.0)))

# 900017 / 900018: a touching pair, one of them with an office name
# containing "&" — covers both the extract path AND the merge path for
# the XML-escaping fix (v0.2.1 only had an extract-path test). The source
# text uses the correctly pre-escaped form, exactly as any real, valid
# KML file would already have to.
def touching_pair(cx, cy, n=24, seed=(17, 18)):
    """Two irregular halves sharing an exact vertical seam at x=cx."""
    pts_a = [(0.0, -1.0), (0.0, 1.0)]
    pts_b = [(0.0, -1.0), (0.0, 1.0)]
    for i in range(1, n):
        t = i / n
        angle = math.pi * t
        y = 1.0 - 2.0 * t
        xa = -(0.2 + 0.8 * math.sin(angle))
        xb = 0.2 + 0.8 * math.sin(angle)
        pts_a.append((noisy(xa, seed[0] + i), noisy(y, seed[0] + i + 0.5)))
        pts_b.append((noisy(xb, seed[1] + i), noisy(y, seed[1] + i + 0.5)))
    pts_a.append(pts_a[0])
    pts_b.append(pts_b[0])
    shift_a = [(cx + x, cy + y) for x, y in pts_a]
    shift_b = [(cx + x, cy + y) for x, y in pts_b]
    return shift_a, shift_b

amp_a, amp_b = touching_pair(65.0, 65.0)
placemarks.append(placemark("900017", "Nu &amp; Xi S.O", "Test &amp; Division", amp_a))
placemarks.append(placemark("900018", "Omicron SO", "Test Division", amp_b))

# 900007 / 900008 / 900009: three polygons arranged around a central gap
# that is NOT itself a listed PIN — merging all three should produce a
# hole, which must fail by default (check_no_unexpected_holes) and
# succeed only with --allow-holes.
def ring_segment(cx, cy, r_in, r_out, a0, a1, n=20):
    # Adjacent segments share boundary vertices at their common division
    # angles. noisy()'s salt must be a function of the point's OWN value
    # (constant salt), not the loop index — two separate calls computing
    # the same angle must perturb it identically, or the "shared" edge
    # between segments silently stops being shared (a microscopic
    # overlap/gap from a fixture bug, not real geometry).
    pts = []
    for i in range(n + 1):
        a = a0 + (a1 - a0) * i / n
        x, y = cx + r_out * math.cos(a), cy + r_out * math.sin(a)
        pts.append((noisy(x, 0), noisy(y, 0)))
    for i in range(n + 1):
        a = a1 - (a1 - a0) * i / n
        x, y = cx + r_in * math.cos(a), cy + r_in * math.sin(a)
        pts.append((noisy(x, 1), noisy(y, 1)))
    pts.append(pts[0])
    return pts

cx, cy = 40.0, 40.0
placemarks.append(placemark("900007", "Eta SO", "Test Division",
                             ring_segment(cx, cy, 1.0, 2.0, 0, 2 * math.pi / 3)))
placemarks.append(placemark("900008", "Theta SO", "Test Division",
                             ring_segment(cx, cy, 1.0, 2.0, 2 * math.pi / 3, 4 * math.pi / 3)))
placemarks.append(placemark("900009", "Iota SO", "Test Division",
                             ring_segment(cx, cy, 1.0, 2.0, 4 * math.pi / 3, 2 * math.pi)))

# 900010: has a real hole of its own (innerBoundaryIs), for single-PIN
# extraction hole support.
outer = jittered_polygon(50.0, 50.0, 2.0, 20, seed_offset=10)
inner = jittered_polygon(50.0, 50.0, 0.5, 20, seed_offset=11)
placemarks.append(placemark("900010", "Kappa SO", "Test Division", outer, inner_rings=[inner]))

# 900011: a duplicate PIN (two offices share the same code) — for
# --office disambiguation testing.
placemarks.append(placemark("900011", "Lambda North SO", "Test Division",
                             jittered_polygon(60.0, 60.0, 1.0, 16, seed_offset=12)))
placemarks.append(placemark("900011", "Lambda South SO", "Test Division",
                             jittered_polygon(60.0, 61.5, 1.0, 16, seed_offset=13)))

# 900012: MultiGeometry (two disjoint parts), for extract-only support
# testing and for confirming merge correctly refuses it.
placemarks.append(placemark(
    "900012", "Mu SO", "Test Division",
    jittered_polygon(70.0, 70.0, 1.0, 16, seed_offset=14),
    extra_polys=[jittered_polygon(75.0, 75.0, 1.0, 16, seed_offset=15)],
))

kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document><name>synthetic_test_pincodes.kml</name>
{''.join(placemarks)}
</Document>
</kml>
"""

out_path = os.path.join(OUT_DIR, "synthetic_pincodes.kml")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(kml)
print(f"Wrote {out_path} with {len(placemarks)} synthetic placemarks")
