"""
validate.py — shared validation checks for pincode-zone-toolkit.

These functions encode the self-audit checklist from the project's process
guide: never trust extracted or merged geometry until it's been mechanically
checked against hard criteria. Every check here raises ValidationError on
failure rather than returning a boolean, so a calling script cannot
accidentally ignore a failed check and write output anyway.

v0.2 changes (from code review): some checks in v0.1 were circular — they
compared two numbers derived from the same in-memory parse, so a bug in
*writing* the output file (e.g. a dropped coordinate, a corrupted tag)
could never be caught. Checks that matter for output integrity now take an
explicit "reparsed from the written file" value as a separate argument from
the "what we intended to write" value, so a real round-trip comparison is
required at the call site — see extract_pincode.py / merge_pincodes.py.
"""

from __future__ import annotations

__version__ = "0.2.1"

from dataclasses import dataclass


class ValidationError(Exception):
    """Raised when extracted or merged geometry fails a mandatory check."""


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    warning: bool = False  # True if this was an override (warned, not raised)


def check_vertex_count_match(
    expected_count: int, actual_count: int, label: str = "vertex_count_match"
) -> CheckResult:
    """
    The two counts passed in MUST come from independent sources to be a
    real check — e.g. (a) the count parsed from the original source text,
    vs (b) the count re-parsed from the file we just wrote to disk.
    Comparing two derivations of the same in-memory parse is NOT a valid
    use of this function; it will always pass and proves nothing.
    """
    passed = expected_count == actual_count
    detail = f"expected={expected_count}, actual={actual_count}"
    if not passed:
        raise ValidationError(
            f"Vertex count mismatch ({detail}). The written output does not "
            f"match what was extracted/computed — do not trust this file. "
            f"Re-check extraction/serialization logic."
        )
    return CheckResult(label, passed, detail)


def check_ring_closed(coords: list[tuple[float, float]], label: str = "ring_closed") -> CheckResult:
    """A polygon's exterior ring must start and end on the same point."""
    if len(coords) < 4:
        raise ValidationError(
            f"Ring has only {len(coords)} points — too few to be a closed polygon ring."
        )
    passed = coords[0] == coords[-1]
    detail = f"first={coords[0]}, last={coords[-1]}"
    if not passed:
        raise ValidationError(f"Ring is not closed ({detail}).")
    return CheckResult(label, passed, detail)


def check_round_number_fraction(
    coords: list[tuple[float, float]],
    max_fraction: float = 0.10,
    allow_override: bool = False,
) -> CheckResult:
    """
    Flag coordinates that look typed/invented rather than extracted from a
    real survey. Real boundary data is irregular; more than ~10% of points
    rounding to <=3 decimal places is a strong fabrication signal.

    If allow_override is True, a failure is downgraded to a printed
    warning instead of raising — use this only when you have independent
    reason to believe the source data is genuinely coarse (e.g. a small
    rural PIN area with few digitized points), never as a default.
    """
    pts = coords[:-1] if coords and coords[0] == coords[-1] else coords
    round_count = 0
    for x, y in pts:
        xs = f"{x:.6f}".rstrip("0")
        ys = f"{y:.6f}".rstrip("0")
        x_dec = len(xs.split(".")[-1]) if "." in xs else 0
        y_dec = len(ys.split(".")[-1]) if "." in ys else 0
        if x_dec <= 3 or y_dec <= 3:
            round_count += 1
    fraction = round_count / len(pts) if pts else 0
    passed = fraction <= max_fraction
    detail = f"{round_count}/{len(pts)} points ({fraction:.0%}) look rounded"
    if not passed:
        msg = (
            f"Round-number check failed: {detail}. This pattern matches "
            f"generated/invented coordinates, not real survey data."
        )
        if allow_override:
            print(f"  [WARNING - OVERRIDDEN] {msg}")
            return CheckResult("round_number_fraction", False, detail, warning=True)
        raise ValidationError(
            msg + " Re-verify the extraction came from the actual source "
            "file, or pass --allow-round-numbers if you've confirmed this "
            "source genuinely has coarse coordinates."
        )
    return CheckResult("round_number_fraction", passed, detail)


def check_minimum_complexity(
    vertex_count: int, minimum: int = 12, allow_override: bool = False
) -> CheckResult:
    """
    A real administrative/postal boundary is almost never a simple
    geometric shape. Too few vertices is a sign of a hand-drawn
    approximation — but some genuinely small/simple real PIN areas may
    exist, so this is overridable with a loud warning.
    """
    passed = vertex_count >= minimum
    detail = f"vertex_count={vertex_count}, minimum={minimum}"
    if not passed:
        msg = (
            f"Polygon has only {vertex_count} vertices (minimum expected: "
            f"{minimum}). Real PIN-code boundaries are usually irregular."
        )
        if allow_override:
            print(f"  [WARNING - OVERRIDDEN] {msg}")
            return CheckResult("minimum_complexity", False, detail, warning=True)
        raise ValidationError(
            msg + " This looks like an approximation, not extracted data. "
            "Pass --allow-low-complexity if you've confirmed this PIN "
            "genuinely has a simple source boundary."
        )
    return CheckResult("minimum_complexity", passed, detail)


def check_valid_xml(xml_text: str) -> CheckResult:
    """The output file must parse as well-formed XML."""
    from xml.dom import minidom

    try:
        minidom.parseString(xml_text)
        return CheckResult("valid_xml", True, "parses OK")
    except Exception as e:  # noqa: BLE001
        raise ValidationError(f"Output is not well-formed XML: {e}") from e


def check_tag_balance(xml_text: str, tags: list[str]) -> CheckResult:
    """Every opening tag must have a matching closing tag (catches the
    'unclosed <Folder>' class of bug directly, even before full XML
    parsing)."""
    mismatches = []
    for tag in tags:
        open_count = xml_text.count(f"<{tag}>")
        close_count = xml_text.count(f"</{tag}>")
        if open_count != close_count:
            mismatches.append(f"<{tag}>: {open_count} open vs {close_count} close")
    passed = not mismatches
    detail = "; ".join(mismatches) if mismatches else "all tags balanced"
    if not passed:
        raise ValidationError(f"Tag balance check failed: {detail}")
    return CheckResult("tag_balance", passed, detail)


def check_area_conservation(
    poly1_area: float,
    poly2_area: float,
    union_area: float,
    tolerance: float = 1e-6,
) -> CheckResult:
    """
    For a clean merge of two touching, non-overlapping polygons, the
    merged area should equal the sum of the parts. Real adjacent PIN
    boundaries can have tiny digitization slivers along a shared edge, so
    this uses a looser default tolerance (1e-6 relative) than exact
    floating-point equality, and always reports the actual mismatch
    magnitude — including on a pass — so a borderline case is visible
    rather than hidden behind a flat PASS/FAIL.
    """
    expected = poly1_area + poly2_area
    diff = abs(union_area - expected)
    rel_diff = diff / max(expected, 1e-15)
    passed = rel_diff <= tolerance
    pct = rel_diff * 100
    detail = (
        f"sum_of_parts={expected:.10f}, union_area={union_area:.10f}, "
        f"diff={diff:.2e} ({pct:.6f}% of total area)"
    )
    if not passed:
        raise ValidationError(
            f"Area conservation check failed: {detail}. This usually means "
            f"an unexpected overlap or gap between the input polygons, not "
            f"a clean shared border. Inspect the inputs before merging, or "
            f"pass --tolerance to accept known sliver geometry explicitly."
        )
    return CheckResult("area_conservation", passed, detail)


def check_single_contiguous_polygon(geom_type: str) -> CheckResult:
    """A merge of adjacent PINs should produce one polygon, not a
    MultiPolygon (which would mean the inputs don't actually touch)."""
    passed = geom_type == "Polygon"
    detail = f"geom_type={geom_type}"
    if not passed:
        raise ValidationError(
            f"Merge did not produce a single contiguous polygon ({detail}). "
            f"The input PINs may not actually be adjacent — do not force a merge."
        )
    return CheckResult("single_contiguous_polygon", passed, detail)


def check_no_unexpected_holes(n_holes: int, allow_holes: bool = False) -> CheckResult:
    """
    If the merged polygons surround an unlisted PIN area, Shapely's union
    produces an interior ring (a hole). Silently dropping that hole and
    writing only the exterior ring would fill in territory that was never
    part of any merged PIN — a real geographic error, not a cosmetic one.
    This fails by default; pass allow_holes=True only if you've confirmed
    the hole is expected and the caller writes it into the output KML as
    an <innerBoundaryIs>.
    """
    passed = n_holes == 0
    detail = f"interior_rings={n_holes}"
    if not passed and not allow_holes:
        raise ValidationError(
            f"Merge produced {n_holes} hole(s) in the merged shape ({detail}). "
            f"This means the merged PINs surround an area not included in "
            f"the merge. Writing only the exterior ring would silently fill "
            f"in that area. Pass --allow-holes to write the holes into the "
            f"output explicitly, or include the missing PIN(s) in the merge."
        )
    return CheckResult("no_unexpected_holes", passed or allow_holes, detail)


def check_no_overlap(
    pin_a: str,
    pin_b: str,
    overlap_area: float,
    smaller_area: float,
    tolerance: float = 1e-6,
    allow_overlap: bool = False,
) -> CheckResult:
    """
    Two real postal PIN areas should essentially never overlap — but real
    adjacent boundaries can have a tiny digitization sliver at a shared
    edge, the same phenomenon check_area_conservation already tolerates.
    This is judged against the SAME relative tolerance (overlap area as a
    fraction of the smaller polygon's area), so a sub-tolerance sliver
    passes with no flag needed, and only a genuine overlap requires
    --allow-overlap. (v0.2 treated ANY nonzero overlap as a hard failure,
    which meant --tolerance could never actually apply to real sliver
    overlaps — only to the area-conservation check, which ran after this
    one already raised. That mismatch is what this fixes.)
    """
    rel = overlap_area / max(smaller_area, 1e-15)
    passed = rel <= tolerance
    detail = f"PIN {pin_a} / PIN {pin_b} overlap_area={overlap_area:.2e} ({rel*100:.6f}% of smaller polygon)"
    if not passed and not allow_overlap:
        raise ValidationError(
            f"{detail}, above tolerance ({tolerance*100:.6f}%). Real "
            f"PIN-code areas should not overlap this much — this suggests "
            f"a source data issue, not a clean adjacency. Pass "
            f"--allow-overlap if you've confirmed this is expected, or "
            f"--tolerance to accept known sliver geometry explicitly."
        )
    return CheckResult("no_overlap", passed or allow_overlap, detail, warning=not passed and allow_overlap)


def run_all(results: list[CheckResult]) -> None:
    """Print a pass/fail/warning summary. Any hard failure would already
    have raised before reaching here."""
    for r in results:
        status = "WARN" if r.warning else ("PASS" if r.passed else "FAIL")
        print(f"  [{status}] {r.name}: {r.detail}")
