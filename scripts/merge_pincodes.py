#!/usr/bin/env python3
"""
merge_pincodes.py — dissolve two or more adjacent PIN-code boundaries into
one merged zone, with adjacency, overlap, hole, and area-conservation
checks.

Usage:
    python3 merge_pincodes.py --source pincodes.kml --pins 560001,560002,560034 --out zone.kml

v0.2.1 (from code review of v0.2): the individual-PIN folders in the
output now carry each PIN's ORIGINAL coordinate text verbatim (see
extract_pincode.py's v0.2.1 notes) rather than float-reformatted values —
only the merged polygon itself is computed geometry, which was always
labeled as such. The overlap check now uses the same relative tolerance
as area-conservation instead of treating any nonzero overlap as a hard
failure (which meant --tolerance could never actually apply to real
sliver overlaps). Area conservation now always runs, including when
--allow-overlap is used — it accounts for the expected overlap instead of
being skipped outright. Field values are XML-escaped before being written
(a name containing "&" would previously break the output).

Multi-part (MultiGeometry) PIN records are not yet supported for merging
— an input PIN with more than one geometry part is rejected explicitly
rather than silently merged using only its first part. Extracting such a
PIN on its own (not merging it) is fully supported by extract_pincode.py.
"""

from __future__ import annotations

__version__ = "0.2.2"

import argparse
import os
import sys
from xml.sax.saxutils import escape as xml_escape

from shapely.geometry import Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from validate import (
    ValidationError,
    check_vertex_count_match,
    check_ring_closed,
    check_round_number_fraction,
    check_minimum_complexity,
    check_valid_xml,
    check_tag_balance,
    check_area_conservation,
    check_single_contiguous_polygon,
    check_no_unexpected_holes,
    check_no_overlap,
    run_all,
)
from extract_pincode import extract_placemark, load_source, _xy


def ring_xml_from_raw(points: list[dict]) -> str:
    """Write a ring using each point's original source text verbatim."""
    coord_str = " ".join(p["raw"] for p in points)
    return f"<LinearRing><coordinates>{coord_str}</coordinates></LinearRing>"


def ring_xml_from_xy(coords: list[tuple[float, float]]) -> str:
    """Write a ring from computed (lon, lat) floats — used only for the
    merged polygon itself, which is genuinely computed geometry (a real
    union), not a copy of anything in the source file."""
    coord_str = " ".join(f"{lon},{lat}" for lon, lat in coords)
    return f"<LinearRing><coordinates>{coord_str}</coordinates></LinearRing>"


def polygon_xml_raw(part: dict) -> str:
    inner_xml = "".join(f"<innerBoundaryIs>{ring_xml_from_raw(h)}</innerBoundaryIs>" for h in part["inner"])
    return f"<Polygon><outerBoundaryIs>{ring_xml_from_raw(part['outer'])}</outerBoundaryIs>{inner_xml}</Polygon>"


def polygon_xml_xy(exterior: list[tuple[float, float]], holes: list) -> str:
    inner_xml = "".join(f"<innerBoundaryIs>{ring_xml_from_xy(h)}</innerBoundaryIs>" for h in holes)
    return f"<Polygon><outerBoundaryIs>{ring_xml_from_xy(exterior)}</outerBoundaryIs>{inner_xml}</Polygon>"


def reparse_written_vertex_count(path: str) -> int:
    import xml.etree.ElementTree as ET

    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    root = ET.fromstring(text)
    total = 0
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == "coordinates" and el.text and el.text.strip():
            total += len(el.text.split())
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", action="version", version=f"merge_pincodes.py {__version__}")
    ap.add_argument("--source", required=True, help="Path to the source pincode-boundary KML")
    ap.add_argument("--pins", required=True, help="Comma-separated PIN codes to merge (2 or more)")
    ap.add_argument("--out", required=True, help="Output KML path")
    ap.add_argument("--office", default=None,
                     help="Office name substring to disambiguate a duplicate PIN record "
                          "(applies to all PINs in --pins that have duplicates)")
    ap.add_argument("--tolerance", type=float, default=1e-6,
                     help="Relative tolerance (default 1e-6) used for BOTH the overlap "
                          "check and the area-conservation check — a shared threshold "
                          "for what counts as a negligible digitization sliver")
    ap.add_argument("--allow-holes", action="store_true",
                     help="Write interior holes found in the merged shape instead of failing")
    ap.add_argument("--allow-overlap", action="store_true",
                     help="Proceed even if two input PINs overlap by more than --tolerance")
    ap.add_argument("--allow-low-complexity", action="store_true")
    ap.add_argument("--allow-round-numbers", action="store_true")
    args = ap.parse_args()

    pins = [p.strip() for p in args.pins.split(",") if p.strip()]
    if len(pins) < 2:
        raise ValidationError("Need at least 2 PIN codes to merge.")

    source_text = load_source(args.source)

    print(f"Extracting {len(pins)} PIN(s) from {args.source}: {', '.join(pins)}")
    records = [extract_placemark(source_text, pin, office=args.office) for pin in pins]

    for r in records:
        if len(r["parts"]) > 1:
            raise ValidationError(
                f"PIN {r['pin']} has {len(r['parts'])} geometry parts "
                f"(MultiGeometry) — merging multi-part PINs is not yet "
                f"supported. Extract it on its own with extract_pincode.py "
                f"instead, or exclude it from this merge."
            )

    polygons = []
    for r in records:
        part = r["parts"][0]
        polygons.append(Polygon(_xy(part["outer"]), [_xy(h) for h in part["inner"]]))

    for r, poly in zip(records, polygons):
        if not poly.is_valid:
            raise ValidationError(f"Source polygon for PIN {r['pin']} is invalid (self-intersecting or malformed).")

    # Adjacency + overlap check: every polygon must touch at least one
    # other (so the merged result is one connected group, not several
    # unrelated PINs forced together). A pairwise overlap beyond
    # --tolerance (relative to the smaller polygon's area) requires
    # --allow-overlap; a sub-tolerance sliver passes with no flag needed.
    print("Checking adjacency and overlap between all PIN pairs ...")
    n = len(polygons)
    touches = [[False] * n for _ in range(n)]
    overlap_results = []
    total_overlap_area = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            overlap_area = polygons[i].intersection(polygons[j]).area
            if overlap_area > 0:
                total_overlap_area += overlap_area
                smaller_area = min(polygons[i].area, polygons[j].area)
                overlap_results.append(
                    check_no_overlap(
                        pins[i], pins[j], overlap_area, smaller_area,
                        tolerance=args.tolerance, allow_overlap=args.allow_overlap,
                    )
                )
            touches[i][j] = touches[j][i] = polygons[i].touches(polygons[j]) or overlap_area > 0

    seen = {0}
    frontier = [0]
    while frontier:
        cur = frontier.pop()
        for j in range(n):
            if touches[cur][j] and j not in seen:
                seen.add(j)
                frontier.append(j)
    if len(seen) != n:
        unreachable = [pins[i] for i in range(n) if i not in seen]
        # Report the nearest distance from each unreachable PIN to the rest
        # of the group — this is what actually tells someone whether
        # they're looking at a sub-millimetre digitization gap (bump
        # --tolerance / this is likely a real seam) vs. a genuine 30+
        # metre gap (these PINs probably really don't border each other).
        distance_notes = []
        for i in range(n):
            if i in seen:
                continue
            nearest = min(polygons[i].distance(polygons[j]) for j in seen)
            distance_notes.append(f"{pins[i]} (nearest distance to the group: {nearest:.8f} degrees, ~{nearest*111000:.1f} m)")
        raise ValidationError(
            f"Not all PINs form one connected group — {unreachable} do not "
            f"touch the rest. Refusing to force a merge of non-adjacent "
            f"areas. " + "; ".join(distance_notes)
        )

    union = unary_union(polygons)
    check_single_contiguous_polygon(union.geom_type)  # raises if not one Polygon

    n_holes = len(list(union.interiors))
    check_no_unexpected_holes(n_holes, allow_holes=args.allow_holes)

    union = orient(union, sign=1.0)
    merged_exterior = list(union.exterior.coords)
    merged_holes = [list(ring.coords) for ring in union.interiors]
    sum_area = sum(p.area for p in polygons)

    # Build output. Individual-PIN folders use each point's ORIGINAL
    # source text (ring_xml_from_raw) — they are a verbatim copy, not a
    # recomputation, even though they sit alongside the merged polygon.
    individual_styles = []
    individual_folders = []
    colors = ["ffff0000", "ff00a5ff", "ffff00ff", "ffffff00", "ff00ffff", "ffff8800"]
    for idx, r in enumerate(records):
        part = r["parts"][0]
        color = colors[idx % len(colors)]
        style_id = f"style_{xml_escape(r['pin'])}"
        individual_styles.append(
            f'<Style id="{style_id}"><LineStyle><color>{color}</color>'
            f'<width>2</width></LineStyle><PolyStyle><color>4d{color[2:]}</color>'
            f'</PolyStyle></Style>'
        )
        desc = xml_escape(" | ".join(f"{k}: {v}" for k, v in r["fields"].items() if v))
        pin_esc = xml_escape(r["pin"])
        individual_folders.append(
            f'<Folder><name>Individual - PIN {pin_esc}</name>'
            f'<Placemark><styleUrl>#{style_id}</styleUrl>'
            f'<name>PIN {pin_esc}</name><description>{desc}</description>'
            f'{polygon_xml_raw(part)}</Placemark></Folder>'
        )

    merged_desc = xml_escape(
        f"Dissolved union of PINs {', '.join(pins)} | "
        f"vertices={len(merged_exterior) + sum(len(h) for h in merged_holes)} | "
        f"holes={n_holes}"
    )
    merged_title = xml_escape(f"Merged zone: {' + '.join(pins)}")
    output_kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
<name>{merged_title}</name>
<Style id="style_merged">
  <LineStyle><color>ff00ff00</color><width>3</width></LineStyle>
  <PolyStyle><color>3300ff00</color></PolyStyle>
</Style>
{chr(10).join(individual_styles)}
<Folder>
  <name>Merged boundary</name>
  <Placemark>
    <styleUrl>#style_merged</styleUrl>
    <name>{merged_title}</name>
    <description>{merged_desc}</description>
    {polygon_xml_xy(merged_exterior, merged_holes)}
  </Placemark>
</Folder>
{chr(10).join(individual_folders)}
</Document>
</kml>
"""

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    tmp_path = args.out + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(output_kml)

    print("Running validation checks:")
    try:
        expected_total = (
            len(merged_exterior) + sum(len(h) for h in merged_holes)
            + sum(len(r["parts"][0]["outer"]) + sum(len(h) for h in r["parts"][0]["inner"]) for r in records)
        )
        reparsed_total = reparse_written_vertex_count(tmp_path)
        results = list(overlap_results)
        results.append(check_vertex_count_match(expected_total, reparsed_total, label="vertex_count_roundtrip"))
        results.append(check_ring_closed(merged_exterior, label="merged_ring_closed"))
        for hidx, h in enumerate(merged_holes):
            results.append(check_ring_closed(h, label=f"merged_hole_closed[{hidx}]"))
        results.append(check_round_number_fraction(merged_exterior, allow_override=args.allow_round_numbers))
        results.append(check_minimum_complexity(len(merged_exterior), allow_override=args.allow_low_complexity))
        # Area conservation ALWAYS runs now, including with --allow-overlap:
        # a confirmed overlap is expected to double-count that area, so the
        # expected union area is sum_of_parts MINUS the overlap, not equal
        # to it. This replaces v0.2's behavior of skipping the check
        # entirely when overlap was allowed.
        expected_area = sum_area - total_overlap_area
        results.append(check_area_conservation(expected_area, 0, union.area, tolerance=args.tolerance))
        results.append(check_tag_balance(output_kml, ["Document", "Folder", "Placemark", "Polygon", "LinearRing"]))
        results.append(check_valid_xml(output_kml))
        run_all(results)
    except ValidationError:
        os.remove(tmp_path)
        raise

    os.replace(tmp_path, args.out)

    print(f"\nWrote {args.out}")
    print(f"  Merged {len(pins)} PINs  |  merged exterior vertices: {len(merged_exterior)}  |  "
          f"holes: {n_holes}  |  "
          f"area conserved: sum(parts)-overlap={expected_area:.8f} vs union={union.area:.8f}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValidationError as e:
        print(f"\nVALIDATION FAILED — no usable file.\n  {e}", file=sys.stderr)
        sys.exit(1)
