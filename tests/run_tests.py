#!/usr/bin/env python3
"""
run_tests.py — exercise extract_pincode.py and merge_pincodes.py against
synthetic_pincodes.kml via the actual command-line interface (subprocess),
not by calling internal functions directly. Each test asserts that a known
failure mode is actually caught, or that a known-good case actually
succeeds — this is the toolkit's credibility check: if these pass, the
validation layer is doing real work, not just existing in the README.

Run: python3 generate_fixtures.py && python3 run_tests.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
FIXTURE = os.path.join(HERE, "fixtures", "synthetic_pincodes.kml")

results = []


def run(script, *args):
    cmd = [sys.executable, os.path.join(SCRIPTS, script), "--source", FIXTURE, *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append((name, condition, detail))
    print(f"[{status}] {name}" + (f"  — {detail}" if detail and not condition else ""))


def with_tmp_out():
    fd, path = tempfile.mkstemp(suffix=".kml")
    os.close(fd)
    os.remove(path)  # must not exist yet for some tests
    return path


print("=== extract_pincode.py ===\n")

# 1. Valid extraction should succeed
out = with_tmp_out()
rc, stdout, stderr = run("extract_pincode.py", "--pin", "900001", "--out", out)
check("extract: valid PIN succeeds", rc == 0 and os.path.isfile(out), stderr)
if os.path.isfile(out):
    os.remove(out)

# 2. Nonexistent PIN should fail, and must not leave a file behind
out = with_tmp_out()
rc, stdout, stderr = run("extract_pincode.py", "--pin", "999999", "--out", out)
check("extract: nonexistent PIN refused, no file written", rc != 0 and not os.path.isfile(out), stderr)

# 3. Open ring (900004) must be caught
out = with_tmp_out()
rc, stdout, stderr = run("extract_pincode.py", "--pin", "900004", "--out", out)
check("extract: open ring is caught", rc != 0 and "not closed" in stderr and not os.path.isfile(out), stderr)

# 4. Hexagon / round numbers (900003) must be caught by both checks
out = with_tmp_out()
rc, stdout, stderr = run("extract_pincode.py", "--pin", "900003", "--out", out)
check(
    "extract: hexagon+round-numbers caught",
    rc != 0 and not os.path.isfile(out) and ("vertices" in stderr or "Round-number" in stderr),
    stderr,
)

# 5. Hexagon should succeed with both overrides
out = with_tmp_out()
rc, stdout, stderr = run(
    "extract_pincode.py", "--pin", "900003", "--out", out,
    "--allow-low-complexity", "--allow-round-numbers",
)
check("extract: hexagon succeeds with overrides + warns", rc == 0 and "WARNING" in stdout, stderr)
if os.path.isfile(out):
    os.remove(out)

# 6. PIN with a real hole (900010) extracts and preserves it
out = with_tmp_out()
rc, stdout, stderr = run("extract_pincode.py", "--pin", "900010", "--out", out)
check("extract: hole preserved", rc == 0 and "holes: 1" in stdout, stdout + stderr)
if os.path.isfile(out):
    hole_written = "<innerBoundaryIs>" in open(out).read()
    check("extract: innerBoundaryIs actually in output file", hole_written)
    os.remove(out)

# 7. Duplicate PIN (900011) without --office must fail with offices listed
out = with_tmp_out()
rc, stdout, stderr = run("extract_pincode.py", "--pin", "900011", "--out", out)
check(
    "extract: duplicate PIN refused, offices listed",
    rc != 0 and "Lambda North SO" in stderr and "Lambda South SO" in stderr,
    stderr,
)

# 8. Duplicate PIN WITH --office succeeds
out = with_tmp_out()
rc, stdout, stderr = run("extract_pincode.py", "--pin", "900011", "--out", out, "--office", "North")
check("extract: --office disambiguates duplicate PIN", rc == 0 and os.path.isfile(out), stderr)
if os.path.isfile(out):
    os.remove(out)

# 9. MultiGeometry PIN (900012) extracts both parts
out = with_tmp_out()
rc, stdout, stderr = run("extract_pincode.py", "--pin", "900012", "--out", out)
check("extract: multi-part geometry extracted", rc == 0 and "parts: 2" in stdout, stdout + stderr)
if os.path.isfile(out):
    multigeom_written = "<MultiGeometry>" in open(out).read()
    check("extract: MultiGeometry actually in output file", multigeom_written)
    os.remove(out)

# 10. Verbatim check: the written coordinate text is character-for-character
# identical to the fixture's source text, not reformatted floats
out = with_tmp_out()
rc, stdout, stderr = run("extract_pincode.py", "--pin", "900001", "--out", out)
if os.path.isfile(out):
    import re
    src_text = open(FIXTURE, encoding="utf-8").read()
    pin_m = re.search(r'<Data name="Pincode"><value>900001</value></Data>', src_text)
    src_start = src_text.rfind("<Placemark>", 0, pin_m.start())
    src_end = src_text.find("</Placemark>", pin_m.start())
    src_coord = re.search(r"<coordinates>(.*?)</coordinates>", src_text[src_start:src_end], re.DOTALL).group(1).strip()
    out_coord = re.search(r"<coordinates>(.*?)</coordinates>", open(out).read(), re.DOTALL).group(1).strip()
    check("extract: output coordinates are character-for-character verbatim", src_coord == out_coord)
    os.remove(out)

# 11. Office name containing "&" (900017) must not break the run, and
# must be correctly re-escaped (not raw "&") in the written output
out = with_tmp_out()
rc, stdout, stderr = run("extract_pincode.py", "--pin", "900017", "--out", out)
check("extract: ampersand in office name doesn't break extraction", rc == 0 and os.path.isfile(out), stderr)
if os.path.isfile(out):
    written = open(out, encoding="utf-8").read()
    check("extract: ampersand correctly re-escaped as &amp; (valid XML)", "&amp;" in written and "Nu & Xi" not in written)
    os.remove(out)


print("\n=== merge_pincodes.py ===\n")

# 12. Clean adjacent pair merges successfully
out = with_tmp_out()
rc, stdout, stderr = run("merge_pincodes.py", "--pins", "900001,900002", "--out", out)
check("merge: clean adjacent pair succeeds", rc == 0 and os.path.isfile(out), stderr)
if os.path.isfile(out):
    os.remove(out)

# 13. Non-adjacent PINs refused
out = with_tmp_out()
rc, stdout, stderr = run("merge_pincodes.py", "--pins", "900001,900010", "--out", out)
check(
    "merge: non-adjacent PINs refused, no file written",
    rc != 0 and not os.path.isfile(out) and "do not touch" in stderr,
    stderr,
)

# 14. Genuinely overlapping PINs refused by default
out = with_tmp_out()
rc, stdout, stderr = run("merge_pincodes.py", "--pins", "900005,900006", "--out", out)
check(
    "merge: overlap refused by default",
    rc != 0 and not os.path.isfile(out) and "overlap" in stderr.lower(),
    stderr,
)

# 15. Overlap succeeds with --allow-overlap
out = with_tmp_out()
rc, stdout, stderr = run("merge_pincodes.py", "--pins", "900005,900006", "--out", out, "--allow-overlap")
check("merge: overlap succeeds with --allow-overlap", rc == 0 and os.path.isfile(out), stderr)
if os.path.isfile(out):
    os.remove(out)

# 16. Three PINs that surround a hole are refused by default
out = with_tmp_out()
rc, stdout, stderr = run("merge_pincodes.py", "--pins", "900007,900008,900009", "--out", out)
check(
    "merge: unexpected hole refused by default",
    rc != 0 and not os.path.isfile(out) and "hole" in stderr.lower(),
    stderr,
)

# 17. Same merge succeeds with --allow-holes, and the hole is actually written
out = with_tmp_out()
rc, stdout, stderr = run(
    "merge_pincodes.py", "--pins", "900007,900008,900009", "--out", out, "--allow-holes"
)
check("merge: hole merge succeeds with --allow-holes", rc == 0 and os.path.isfile(out), stderr)
if os.path.isfile(out):
    hole_written = "<innerBoundaryIs>" in open(out).read()
    check("merge: hole actually written to output (not silently dropped)", hole_written)
    os.remove(out)

# 18. MultiGeometry PIN is explicitly refused in a merge, not silently
#     merged using only its first part
out = with_tmp_out()
rc, stdout, stderr = run("merge_pincodes.py", "--pins", "900001,900012", "--out", out)
check(
    "merge: multi-part PIN explicitly refused (not silently truncated)",
    rc != 0 and not os.path.isfile(out) and "MultiGeometry" in stderr,
    stderr,
)

# 19. A tiny (sub-tolerance) overlap must merge successfully with NO
# flags needed — proving --tolerance actually reaches the overlap check
# (v0.2's binary overlap check meant this always required --allow-overlap
# regardless of how small the overlap was)
out = with_tmp_out()
rc, stdout, stderr = run("merge_pincodes.py", "--pins", "900015,900016", "--out", out)
check(
    "merge: sub-tolerance overlap succeeds with no flags",
    rc == 0 and os.path.isfile(out),
    stderr,
)
if os.path.isfile(out):
    os.remove(out)

# 20. Individual-PIN folders inside a merge output are also verbatim
out = with_tmp_out()
rc, stdout, stderr = run("merge_pincodes.py", "--pins", "900001,900002", "--out", out)
if os.path.isfile(out):
    import re
    src_text = open(FIXTURE, encoding="utf-8").read()
    pin_m = re.search(r'<Data name="Pincode"><value>900001</value></Data>', src_text)
    src_start = src_text.rfind("<Placemark>", 0, pin_m.start())
    src_end = src_text.find("</Placemark>", pin_m.start())
    src_coord = re.search(r"<coordinates>(.*?)</coordinates>", src_text[src_start:src_end], re.DOTALL).group(1).strip()
    out_text = open(out, encoding="utf-8").read()
    check("merge: individual-PIN folder coordinates are verbatim", src_coord in out_text)
    os.remove(out)

# 21. Ampersand in an office name must also survive the MERGE path, not
# just extraction — both scripts build XML output independently, so each
# needs its own escaping test
out = with_tmp_out()
rc, stdout, stderr = run("merge_pincodes.py", "--pins", "900017,900018", "--out", out)
check("merge: ampersand in office name doesn't break the merge", rc == 0 and os.path.isfile(out), stderr)
if os.path.isfile(out):
    written = open(out, encoding="utf-8").read()
    check("merge: ampersand correctly re-escaped as &amp; in merge output", "&amp;" in written and "Nu & Xi" not in written)
    os.remove(out)


print(f"\n{'='*40}")
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"{passed}/{total} tests passed")
if passed != total:
    print("\nFAILED TESTS:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}: {detail}")
    sys.exit(1)
sys.exit(0)
