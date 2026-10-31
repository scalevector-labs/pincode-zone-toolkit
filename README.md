# pincode-zone-toolkit

Extract, merge, and validate Indian PIN-code boundary polygons for logistics and delivery-zone mapping — built around one hard rule: **never trust AI-generated or AI-summarized geodata without mechanically verifying it against the source.**

> **Status: package v0.2.2.** `merge_pincodes.py` reports 0.2.2; `extract_pincode.py` and `validate.py` are unchanged since 0.2.1 and report that (see [`CHANGELOG.md`](CHANGELOG.md)). This is a developer-facing proof of methodology — it assumes comfort with a terminal and Python. A no-code (upload-and-click) version is planned if there's demand for one. See [Roadmap](#roadmap).
>
> **Built with AI, checked by tests.** This toolkit was written and reviewed with Claude (Anthropic): separate Claude sessions built the code and reviewed it across three rounds (the first two found real defects; the third found none in the code). Separate sessions of the same model family can share blind spots, so the reviews are not the evidence that the code is right — the tests and the real-data runs are. Dinesh Thonur set the problem, supplied the real data, and checked results against it. The defects the reviews caught are listed in [`CHANGELOG.md`](CHANGELOG.md): holes silently filled in, geometry silently dropped, a circular validation check, an unescaped-XML crash, a tolerance flag that could never actually apply. For a project whose thesis is "don't trust unverified AI output," saying where it came from is the point, not a footnote. `tests/` has a synthetic regression suite exercising every fixed defect directly, and [`docs/ai-failure-modes.md`](docs/ai-failure-modes.md) documents the failures observed during development (vertex counts, overlap with the real boundary, a 384 KiB file-ingestion cutoff) that this project's validation approach was built in response to.

## Why this exists

AI tools are very good at producing *plausible-looking* geographic boundary data that is quietly wrong — invented coordinates, truncated reads of large files, unvalidated "merged" shapes with broken geometry. Several of these failure modes are documented in [`docs/ai-failure-modes.md`](docs/ai-failure-modes.md), with measurements from the development dataset: a boundary generated from memory instead of extracted had only 15–17 vertices where the real one has 28–85, and overlapped the real boundary by only about 61–65% (intersection over union); a file-reading task silently returned 114 of 1,655 records with full confidence; a "computed" merge shipped with an open ring and a 58 km stray coordinate.

This toolkit exists to do the same extract/merge job the *correct* way — and to make the validation checks that catch those failures a built-in part of the process, not an afterthought.

## What this is / isn't

- **Is:** a validated way to extract a single PIN code's boundary, or merge several adjacent ones into one zone, from the Department of Posts' PIN-code boundary dataset (as obtained via a third-party mirror — see [Getting the source data](#getting-the-source-data)).
- **Isn't (yet):** a no-code tool, a gap/overlap analyzer, or a lat/long-to-PIN lookup. These are on the [roadmap](#roadmap), not built yet.
- **Isn't ever:** a source of legal or exact serviceability boundaries — see [Limitations](#limitations).

## Getting the source data

The underlying data is the Department of Posts' PIN-code boundary dataset, published on **data.gov.in** under the **Open Government Licence – India (GODL-India)**. That page is the dataset's legal source and the one to cite for attribution.

**In practice, the official portal and its AIKosh mirror do not serve a working anonymous download** — as of this writing, `data.gov.in`'s own resource page has no file attached (0 bytes, no reference URL, no working API), and the AIKosh mirror's download button redirects straight to a mandatory login/account-creation flow. Neither is usable as a simple download step for this toolkit.

The practical route that works today:
1. Go to **[bharatlas.com/view/datagov_pincodes](https://bharatlas.com/view/datagov_pincodes)** — a third-party viewer that *attributes* its data to data.gov.in (it credits "Source: data.gov.in" on the page itself, under the GODL-India licence).
2. Optionally filter by state/circle (e.g. Circle = Uttar Pradesh) to get a smaller file.
3. Export as **KML**.
4. Confirm the file has these fields on each record: `Pincode`, `Office_Name`, `Division`, `Region`, `Circle`. The toolkit is built against this exact schema.

> **What's actually been verified, and what hasn't.** bharatlas.com is an unofficial, independently-run third-party site, not a government service — and because the official data.gov.in/AIKosh portals don't serve a working anonymous download (see above), there has been no way to directly diff bharatlas's file against an official one. What this toolkit's validation layer confirms is that it faithfully extracts and merges whatever boundaries are actually in the file you give it — it does **not** confirm that bharatlas's content matches what the government would serve if its download worked. Treat that as a trust gap, not a settled fact: the dataset used during development was retrieved via bharatlas.com on **2026-10-30**; if you need to independently verify the data itself (not just this toolkit's handling of it), go to data.gov.in's catalog entry (linked above) and request the file directly — expect to need a government digital-identity login.

## Installation

```bash
git clone https://github.com/scalevector-labs/pincode-zone-toolkit.git
cd pincode-zone-toolkit
pip install shapely
```

No other dependencies. Python 3.9+.

## Usage

### Extract a single PIN code's boundary

```bash
python3 scripts/extract_pincode.py \
  --source pincodes_up.kml \
  --pin 274182 \
  --out output/single.kml
```

### Merge two or more adjacent PIN codes into one zone

```bash
python3 scripts/merge_pincodes.py \
  --source pincodes_up.kml \
  --pins 274182,274205,274204 \
  --out output/merged_zone.kml
```

Any number of PIN codes is supported, as long as they form one connected group (each one touches at least one other in the set — a straight chain is fine, they don't all need to touch each other directly). If any PIN doesn't actually border the rest, the script refuses to force a merge, tells you which one, and reports how far it is from the group (in degrees and approximate metres) so you can tell a hairline digitization gap from a real one.

Both scripts run with plain `python3` — don't use `python3 -I`, which strips the scripts' own directory from the import path and breaks the `validate` import. Both accept `--version`.

Import the resulting `.kml` into Google My Maps, QGIS, or any KML-compatible tool.

### Options (both scripts)

| Flag | What it does |
|---|---|
| `--office "<name>"` | Disambiguates a PIN with more than one record under it (uncommon, but present in the real dataset) — matched as a case-insensitive substring of the office name |
| `--allow-low-complexity` | Downgrades the "too few vertices" check to a warning, for a genuinely simple small PIN area |
| `--allow-round-numbers` | Downgrades the fabrication-pattern check to a warning, for a genuinely coarse source boundary |

### Options (`merge_pincodes.py` only)

| Flag | What it does |
|---|---|
| `--tolerance <float>` | Relative tolerance (default `1e-6`), used for **both** the overlap check and the area-conservation check — one shared threshold for what counts as a negligible digitization sliver vs. a real problem. In the Uttar Pradesh extract used during development, most adjacent PINs share an exactly-digitized border (zero difference), so the default is tight; loosen it only if you've inspected a specific failing pair. It does not bridge gaps between PINs. |
| `--allow-holes` | If the merged PINs surround an area not included in the merge, write that hole into the output explicitly instead of failing. Without this flag, a merge that would produce a hole is refused — silently filling it in was a bug fixed in v0.2. |
| `--allow-overlap` | Proceeds even if two input PINs overlap by more than `--tolerance`. **In a 400-record sample of the Uttar Pradesh extract, about 1.3% of adjacent PIN pairs had a genuine overlap above the default tolerance** (sub-100 m² slivers, likely digitization pinch points) — expect to need this occasionally. A sub-tolerance sliver passes with no flag at all (fixed in v0.2.1 — v0.2 required this flag for *any* nonzero overlap, however small). Needing the flag isn't a sign your PINs are wrong; it's the source data having a rough edge at that one spot. These are figures for one state's extract, not a claim about the national dataset. |

PIN records with more than one geometry part (`MultiGeometry` — a PIN with a disconnected exclave, which does occur in the real dataset) can be extracted individually with `extract_pincode.py`, but are explicitly refused by `merge_pincodes.py` rather than silently merged using only their first part. Multi-part merging isn't supported yet.

## How it works

Both scripts follow the same discipline, enforced in code via [`scripts/validate.py`](scripts/validate.py), not just described in a doc:

1. **Locate, don't recall.** The exact PIN record is found by an exact string match in the source file. Zero matches is a hard stop; more than one match requires `--office` to disambiguate rather than guessing.
2. **Extract completely, don't type.** The geometry is parsed with a real XML parser (not line-by-line regex), so inner rings (holes), and additional polygon parts (`MultiGeometry`), are read in full — not just the first `<coordinates>` block. "Verbatim" is literal here, not just numerically equivalent: each coordinate's original source text is kept and written back character-for-character unchanged (parsed floats are used only for validation math, never for what gets written) — covered by a regression test in `tests/`. The only computed geometry in any output is the merged polygon itself.
3. **Merge by computation, not by hand.** A merge of two or more boundaries uses real polygon-union geometry (Shapely), never hand-picked "seam" points.
4. **Count twice, independently.** Before anything is written, the number of coordinate points counted directly from the raw source text is compared with the number the XML parser produced — so a bug in the parser itself, not just in writing the file, is caught.
5. **Validate the file that was actually written, not just what was computed in memory.** Output is first written to a temp path, then re-read from disk and re-parsed — only if that round-trip matches what was intended does the file get moved to the real output path.
6. **Fail loud by default, override explicitly.** Every check below raises and writes nothing unless its specific override flag is passed:
   - Raw-text vertex count agrees with the parsed count, and both round-trip exactly to the written file
   - Every polygon ring (outer and each hole) is closed (first point = last point)
   - Fewer than ~10% of coordinates look suspiciously round (`--allow-round-numbers` to override)
   - At least ~12 vertices (`--allow-low-complexity` to override)
   - For merges: the input PINs form one connected group, none overlap beyond tolerance (`--allow-overlap` to override), the result is one contiguous polygon, any hole is either refused or explicitly written (`--allow-holes`), and merged area matches the sum of the parts within tolerance (`--tolerance`)
   - The output file is well-formed XML with every tag closed

### Testing

```bash
cd tests
python3 generate_fixtures.py   # builds synthetic_pincodes.kml — invented PIN codes, no real geography
python3 run_tests.py           # runs both scripts' real CLI against every check's pass/fail case
```

The fixtures are entirely synthetic (invented PIN codes in the `900xxx` range, no real geography or company data) and are designed to exercise each validation check's failure mode directly: an open ring, a hexagon with round-number coordinates, genuinely overlapping polygons, a merge that produces a hole, a duplicate PIN record, a multi-part geometry, and an office name containing `&` in both scripts — plus the corresponding known-good cases. This is the toolkit's actual credibility check: if these pass, the validation layer is doing real work, not just existing in this README.

## Limitations

- **Not legal boundaries.** PIN-code polygons follow postal delivery-area conventions, not cadastral or administrative legal boundaries. Don't treat them as exact serviceability lines.
- **Data provenance.** See [Getting the source data](#getting-the-source-data): the toolkit verifies its own handling of the file you give it, not that the file matches the official dataset.
- **India-specific schema.** This toolkit is built against the Indian Department of Posts' field structure (`Pincode`, `Circle`, `Division`, `Region`, `Office_Name`). It will not run as-is against another country's postal-boundary data.
- **Outside India:** search for your own country's open postal/zip-boundary dataset (e.g. US ZIP Code Tabulation Areas via the Census Bureau, UK postcode boundaries via ONS/Ordnance Survey). The *method* here — locate the exact record, extract verbatim, validate before merging — applies generally; only the field-mapping step would need adapting to a different schema.
- **Hairline gaps aren't bridged.** A full scan of the Uttar Pradesh extract found 9 PIN pairs that are very close but not technically touching — 2 are sub-centimeter apart (almost certainly meant to touch; a digitization artifact) and would currently be reported as "not adjacent" if you tried to merge them. When a merge fails the adjacency check, the error now reports the distance, so you can tell a hairline gap from a genuine one; there is no snap-tolerance flag yet to bridge it. See `CHANGELOG.md` for the specific pairs found.
- **Figures are from one extract.** Every dataset-derived number in this repo (hole and multi-part counts, overlap percentages, gap counts) comes from the Uttar Pradesh extract used during development, not from the national dataset.

## Roadmap

- No-code web tool (upload file, type a PIN, download result) — only if there's real demand after this version ships publicly
- Snap tolerance to bridge hairline gaps (needs more real-pair testing before choosing a default)
- Merging multi-part PINs
- Gap/overlap detection between zones
- Lat/long → PIN lookup
- Schema adapters for non-India postal boundary datasets

## License

- Code: **MIT** — see [`LICENSE`](LICENSE)
- Documentation (including `docs/ai-failure-modes.md`): **CC BY 4.0** — see [`LICENSE-DOCS.md`](LICENSE-DOCS.md)
- The underlying PIN-code boundary data keeps its own license — **Open Government Licence (OGL) / GODL-India** — and is not redistributed in this repo. See [data.gov.in](https://www.data.gov.in/resource/delivery-post-office-pincode-boundary) for the original listing.

---

Published by Dinesh Thonur under Scale Vector. Free to use. Feedback via GitHub issues.
