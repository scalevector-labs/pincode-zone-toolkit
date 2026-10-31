#!/usr/bin/env python3
"""
extract_pincode.py — pull one PIN code's boundary polygon out of a
data.gov.in-schema pincode-boundary KML file, verbatim, with validation.

Usage:
    python3 extract_pincode.py --source pincodes.kml --pin 560001 --out output.kml

v0.2.1 (from code review of v0.2): "verbatim" is now actually true at the
character level, not just the value level. v0.2 parsed each coordinate to
a Python float and reformatted it when writing output — numerically
identical, but "77.10" became "77.1" and a third (altitude) value was
silently dropped, which contradicted the docstring's own claim. v0.2.1
keeps each coordinate's original source text alongside its parsed
(lon, lat) floats; the floats are used only for validation math (ring
closure, round-number detection, area), and the ORIGINAL TEXT is what
gets written to output. Also fixes an XML-injection bug (v0.2 wrote field
values like office names back into the output unescaped — a name
containing "&" produced invalid XML and the run would abort) and adds a
second, independent vertex count derived straight from the raw source
text (not from the XML parse), so a bug in the parser itself — not just a
bug in writing the output — would also be caught.
"""

from __future__ import annotations

__version__ = "0.2.1"

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

from validate import (
    ValidationError,
    check_vertex_count_match,
    check_ring_closed,
    check_round_number_fraction,
    check_minimum_complexity,
    check_valid_xml,
    check_tag_balance,
    run_all,
)

FIELDS = ["Pincode", "Office_Name", "Division", "Region", "Circle"]

STYLE_BLOCK = """<Style id="boundaryStyle">
  <LineStyle><color>ff0000ff</color><width>2</width></LineStyle>
  <PolyStyle><color>4d0000ff</color></PolyStyle>
</Style>"""


def _parse_coords_text(text: str) -> list[dict]:
    """
    Parse a <coordinates> element's text into a list of points, each
    keeping BOTH its original source substring ('raw', written to output
    verbatim — including any altitude component) and parsed (lon, lat)
    floats (used only for validation math: ring closure, round-number
    detection, area). The raw substring is never reconstructed from the
    floats, so reformatting (e.g. "77.10" -> "77.1") can't happen.
    """
    points = []
    for tok in text.split():
        parts = tok.split(",")
        lon, lat = float(parts[0]), float(parts[1])
        points.append({"raw": tok, "lon": lon, "lat": lat})
    return points


def _xy(points: list[dict]) -> list[tuple[float, float]]:
    """(lon, lat) float tuples for validation/geometry math only."""
    return [(p["lon"], p["lat"]) for p in points]


def _raw_coord_count(text: str) -> int:
    """Count coordinate tokens directly from raw <coordinates> text, with
    no XML parsing involved at all — used as a second, independent count
    alongside the ElementTree-based parse, so a bug in the parser itself
    (not just a bug in later serialization) has something to disagree with."""
    return len(text.split())


def _parse_polygon_el(poly_el: ET.Element) -> dict:
    """Parse one <Polygon> element into {'outer': [...], 'inner': [[...], ...]},
    each ring a list of the point dicts from _parse_coords_text."""
    outer_el = poly_el.find("./outerBoundaryIs/LinearRing/coordinates")
    if outer_el is None or not (outer_el.text or "").strip():
        raise ValidationError("Polygon has no outerBoundaryIs/coordinates — malformed source.")
    outer = _parse_coords_text(outer_el.text)

    inner = []
    for inner_ring_el in poly_el.findall("./innerBoundaryIs/LinearRing/coordinates"):
        if (inner_ring_el.text or "").strip():
            inner.append(_parse_coords_text(inner_ring_el.text))

    return {"outer": outer, "inner": inner}


def extract_placemark(source_text: str, pin: str, office: str | None = None) -> dict:
    """
    Locate the Placemark(s) whose Pincode field exactly matches `pin`.

    - Zero matches: raise.
    - One match: use it.
    - Multiple matches: if `office` is given, pick the match whose
      Office_Name contains it (case-insensitive); otherwise raise and list
      every office name found, so the caller knows how to disambiguate
      with --office, rather than hitting an unhelpful generic error.

    Returns a dict with 'pin', 'fields', and 'parts' — a list of
    {'outer': [...], 'inner': [[...], ...]} dicts, each ring a list of
    point dicts (see _parse_coords_text). Most PIN records have exactly
    one part; more than one means the source geometry is a
    MultiGeometry/multiple <Polygon> elements (e.g. a PIN with a
    geographically separate exclave).

    Also raises if the raw-text coordinate count disagrees with what the
    XML parser produced — an independent cross-check on the parse itself,
    not just on later serialization.
    """
    pattern = re.compile(
        r'<Data\s+name="Pincode"\s*>\s*<value>\s*' + re.escape(pin) + r"\s*</value>\s*</Data>"
    )
    matches = list(pattern.finditer(source_text))
    if len(matches) == 0:
        raise ValidationError(f"PIN {pin} not found in source file.")

    blocks = []
    for m in matches:
        start = source_text.rfind("<Placemark>", 0, m.start())
        if start == -1:
            raise ValidationError(
                f"Found PIN {pin} but could not locate its enclosing <Placemark> "
                f"opening tag — source may be malformed."
            )
        close_idx = source_text.find("</Placemark>", m.start())
        if close_idx == -1:
            raise ValidationError(
                f"Found PIN {pin} but its <Placemark> is never closed in the "
                f"source file — source may be truncated or malformed."
            )
        end = close_idx + len("</Placemark>")
        blocks.append(source_text[start:end])

    if len(blocks) > 1:
        offices = []
        for b in blocks:
            om = re.search(r'<Data\s+name="Office_Name"\s*>\s*<value>(.*?)</value>', b, re.DOTALL)
            offices.append((om.group(1).strip() if om else "(unknown office)"))

        if office:
            filtered = [b for b, o in zip(blocks, offices) if office.lower() in o.lower()]
            if len(filtered) == 1:
                blocks = filtered
            elif len(filtered) == 0:
                raise ValidationError(
                    f"PIN {pin} matched {len(blocks)} records, but none of their "
                    f"office names contain '{office}'. Offices found: {offices}"
                )
            else:
                raise ValidationError(
                    f"PIN {pin} with --office '{office}' still matches "
                    f"{len(filtered)} records: {[o for o in offices if office.lower() in o.lower()]}"
                )
        else:
            raise ValidationError(
                f"PIN {pin} matched {len(blocks)} records — not unique. "
                f"Offices found: {offices}. Re-run with --office \"<name>\" "
                f"to disambiguate. Refusing to guess which record is correct."
            )

    block = blocks[0]

    # Independent raw-text count, computed BEFORE any XML parsing, from
    # every <coordinates>...</coordinates> span in the raw block text.
    raw_coord_spans = re.findall(r"<coordinates>(.*?)</coordinates>", block, re.DOTALL)
    raw_total = sum(_raw_coord_count(s) for s in raw_coord_spans)

    try:
        root = ET.fromstring(block)
    except ET.ParseError as e:
        raise ValidationError(f"Could not parse the <Placemark> block for PIN {pin} as XML: {e}") from e

    fields = {}
    for name in FIELDS:
        data_el = root.find(f'.//Data[@name="{name}"]/value')
        fields[name] = data_el.text.strip() if data_el is not None and data_el.text else None

    poly_els = root.findall(".//Polygon")
    if not poly_els:
        raise ValidationError(f"No <Polygon> geometry found for PIN {pin}.")

    parts = [_parse_polygon_el(p) for p in poly_els]

    parsed_total = sum(len(part["outer"]) + sum(len(r) for r in part["inner"]) for part in parts)
    if raw_total != parsed_total:
        raise ValidationError(
            f"Independent count mismatch for PIN {pin}: raw text has "
            f"{raw_total} coordinate tokens, but the XML parser produced "
            f"{parsed_total}. This means the PARSER itself dropped or "
            f"duplicated points — do not trust this extraction. (This is "
            f"checked separately from, and before, the output round-trip "
            f"check, which can only catch a bug in writing the file, not "
            f"in reading it.)"
        )

    return {"pin": pin, "fields": fields, "parts": parts}


def _ring_xml(points: list[dict]) -> str:
    coord_str = " ".join(p["raw"] for p in points)  # verbatim — never reformatted
    return f"<LinearRing><coordinates>{coord_str}</coordinates></LinearRing>"


def _polygon_xml(part: dict) -> str:
    inner_xml = "".join(
        f"<innerBoundaryIs>{_ring_xml(ring)}</innerBoundaryIs>" for ring in part["inner"]
    )
    return f"<Polygon><outerBoundaryIs>{_ring_xml(part['outer'])}</outerBoundaryIs>{inner_xml}</Polygon>"


def build_kml(record: dict) -> str:
    title_raw = f"PIN {record['pin']}"
    office = record["fields"].get("Office_Name")
    if office:
        title_raw += f" - {office}"
    title = xml_escape(title_raw)

    ext_data = "\n".join(
        f'    <Data name="{xml_escape(k)}"><value>{xml_escape(v or "")}</value></Data>'
        for k, v in record["fields"].items()
    )
    desc = xml_escape(" | ".join(f"{k}: {v}" for k, v in record["fields"].items() if v))
    n_parts = len(record["parts"])
    n_holes = sum(len(p["inner"]) for p in record["parts"])
    if n_parts > 1:
        geom_xml = "<MultiGeometry>" + "".join(_polygon_xml(p) for p in record["parts"]) + "</MultiGeometry>"
    else:
        geom_xml = _polygon_xml(record["parts"][0])

    note = ""
    if n_parts > 1:
        note = f" | multi-part geometry: {n_parts} parts"
    if n_holes:
        note += f" | contains {n_holes} hole(s) preserved as innerBoundaryIs"
    if note:
        note = xml_escape(note)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
<name>{title}</name>
{STYLE_BLOCK}
<Placemark>
  <styleUrl>#boundaryStyle</styleUrl>
  <name>{title}</name>
  <ExtendedData>
{ext_data}
  </ExtendedData>
  <description>{desc}{note}</description>
  {geom_xml}
</Placemark>
</Document>
</kml>
"""


def total_vertex_count(record: dict) -> int:
    return sum(len(p["outer"]) + sum(len(r) for r in p["inner"]) for p in record["parts"])


def reparse_written_vertex_count(output_path: str) -> int:
    """Round-trip check: re-read the file we just wrote from disk (not
    from memory) and independently count its coordinate points. This
    catches a bug in build_kml()/serialization. It's deliberately separate
    from the raw-vs-parsed check in extract_placemark(), which catches a
    bug in the PARSER instead — the two checks guard different stages."""
    with open(output_path, "r", encoding="utf-8") as f:
        written_text = f.read()
    root = ET.fromstring(written_text)
    total = 0
    for el in root.iter():
        local_name = el.tag.rsplit("}", 1)[-1]
        if local_name == "coordinates" and el.text and el.text.strip():
            total += len(el.text.split())
    return total


def load_source(path: str) -> str:
    """Shared, strict-decoding file read used by both scripts. Refuses to
    silently replace corrupted bytes — a tool built around 'never trust
    unverified data' shouldn't quietly paper over encoding errors either."""
    if not os.path.isfile(path):
        raise ValidationError(f"Source file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError as e:
        raise ValidationError(
            f"{path} is not valid UTF-8 text ({e}). Refusing to silently "
            f"replace corrupted characters — check the source file's encoding."
        ) from e


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", action="version", version=f"extract_pincode.py {__version__}")
    ap.add_argument("--source", required=True, help="Path to the source pincode-boundary KML")
    ap.add_argument("--pin", required=True, help="PIN code to extract")
    ap.add_argument("--out", required=True, help="Output KML path")
    ap.add_argument("--office", default=None, help="Office name substring to disambiguate duplicate PIN records")
    ap.add_argument("--allow-low-complexity", action="store_true",
                     help="Downgrade the minimum-vertex-count check to a warning")
    ap.add_argument("--allow-round-numbers", action="store_true",
                     help="Downgrade the round-number fabrication check to a warning")
    args = ap.parse_args()

    source_text = load_source(args.source)

    print(f"Extracting PIN {args.pin} from {args.source} ...")
    record = extract_placemark(source_text, args.pin, office=args.office)

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    source_vertex_count = total_vertex_count(record)
    output_kml = build_kml(record)

    tmp_path = args.out + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(output_kml)

    print("Running validation checks:")
    try:
        reparsed_count = reparse_written_vertex_count(tmp_path)
        results = [
            check_vertex_count_match(source_vertex_count, reparsed_count, label="vertex_count_roundtrip"),
        ]
        all_points_xy = []
        for part_idx, part in enumerate(record["parts"]):
            results.append(
                check_ring_closed(_xy(part["outer"]), label=f"ring_closed[part{part_idx}.outer]")
            )
            all_points_xy.extend(_xy(part["outer"]))
            for hole_idx, hole in enumerate(part["inner"]):
                results.append(
                    check_ring_closed(_xy(hole), label=f"ring_closed[part{part_idx}.hole{hole_idx}]")
                )
                all_points_xy.extend(_xy(hole))
        results.append(check_round_number_fraction(all_points_xy, allow_override=args.allow_round_numbers))
        results.append(check_minimum_complexity(source_vertex_count, allow_override=args.allow_low_complexity))
        results.append(check_tag_balance(output_kml, ["Document", "Placemark", "Polygon", "LinearRing"]))
        results.append(check_valid_xml(output_kml))
        run_all(results)
    except ValidationError:
        os.remove(tmp_path)
        raise

    os.replace(tmp_path, args.out)
    print(f"\nWrote {args.out}")
    print(f"  PIN: {record['pin']}  |  vertices: {source_vertex_count}  |  "
          f"parts: {len(record['parts'])}  |  "
          f"holes: {sum(len(p['inner']) for p in record['parts'])}  |  "
          f"office: {record['fields'].get('Office_Name')}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValidationError as e:
        print(f"\nVALIDATION FAILED — no usable file.\n  {e}", file=sys.stderr)
        sys.exit(1)
