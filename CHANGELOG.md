# Changelog

All notable changes to this project. Each script carries its own `__version__`
string (check with `python3 extract_pincode.py --version` or
`python3 merge_pincodes.py --version`) — treat this file, not filenames, as
the authoritative record of what that version number means.

The **package version** is the latest version below. A script only changes its
own reported version when its code changes, so `extract_pincode.py` and
`validate.py` still report 0.2.1 in package v0.2.2.

## v0.2.2 — 2026-10-31 (merge_pincodes.py only — extract_pincode.py and validate.py unchanged since v0.2.1)

A third review round, this time of v0.2.1, found no new code defects —
all four prior fixes were confirmed correct by independent reading. What
it found instead:

**Fixed:**
- The "not all PINs form one connected group" error gave no way to tell
  a sub-millimetre digitization gap from a genuine, real gap between
  PINs. It now reports the nearest distance (in degrees and approximate
  metres) from each unreachable PIN to the rest of the group.
- The XML-escaping fix in v0.2.1 had a test for the extract path only.
  Added the equivalent test for the merge path (a separate code path,
  separate output-building logic) — confirmed working, not just assumed
  to work because the extract path did.
- `tests/run_tests.py` had duplicate test numbers (10 and 11 used twice)
  from incremental edits. Renumbered sequentially; now 26 tests.

**Added:**
- `docs/ai-failure-modes.md` — previously referenced by the README and
  the project's own pitch, but never actually written. Documents three
  real, measured AI failure modes (generated-not-extracted geometry,
  silent file-truncation, unverified code output) that this toolkit's
  validation layer was built in direct response to.
- `LICENSE` (MIT, for code) and `LICENSE-DOCS.md` (CC BY 4.0, for
  documentation) — the README named these licences but the files did not
  exist.

**Documentation (no code change):**
- README's "What this is/isn't" and Roadmap sections still referenced
  "v0.1" after two version bumps — corrected.
- The data-source section asserted bharatlas.com "re-hosts the same"
  dataset as data.gov.in as settled fact. Since the official portals
  don't serve a working download, this was never actually diffed against
  an official copy — reworded to say plainly what has and hasn't been
  verified, with the retrieval date (2026-10-30) the development dataset
  was pulled on.
- Added a README section disclosing that this project was built with,
  and code-reviewed by, Claude (Anthropic) across separate build/review
  passes — consistent with the project's own stated principle of not
  trusting unverified AI output without saying where it came from.
- Corrected two wording problems found in review of that disclosure and of
  the failure-modes document. (1) The README said a generated boundary's
  "areas [were] off by ~35–40%"; the measured quantity is overlap with the
  real boundary (intersection over union) of 61–65%, which is not the same
  thing, so the wording now says that. (2) The README said the reviews were
  "not one model checking its own work", but builder and reviewer were both
  Claude (separate sessions), which can share blind spots; the text now says
  so, and says the tests and real-data runs — not the reviews — are the
  evidence of correctness.
- `docs/ai-failure-modes.md` no longer says the failures were observed
  "across general-purpose AI assistants" or are "not specific to one
  vendor's model". It now says they were observed in the assistants used
  during development (late October 2026), that Failure 2 concerns a
  product's file-upload layer rather than a model, and that product
  behaviour may have changed since.
- README states the package-version convention (see the note at the top of
  this file), mentions `--version`, describes the new gap-distance error, and
  adds a data-provenance entry and a roadmap item for snap tolerance.

## v0.2.1 — 2026-10-31

Fixes from a second code review of v0.2. All four confirmed by re-reading
the v0.2 code before changing anything (not taken on trust), and by
checking against the real Uttar Pradesh dataset (1,655 records) where
relevant.

**Fixed:**
- v0.2's "verbatim" claim was not actually true at the character level:
  coordinates were parsed to Python floats and reformatted when writing
  output (numerically identical, but e.g. `77.10` would become `77.1`),
  and a third (altitude) coordinate value would have been silently
  dropped had one been present. Neither currently occurs anywhere in the
  real UP dataset (checked directly: zero altitude values, zero
  trailing-zero coordinates in the whole file), but the claim is now true
  regardless of the source data, not true by luck of this one dataset.
  Each coordinate's original source substring is now kept and written
  back unchanged; parsed floats are used only for validation math.
- The overlap check failed on any overlap greater than zero, before
  `--tolerance` was ever consulted — meaning the `--tolerance` flag could
  never actually apply to the ~1.3% of real adjacent-PIN pairs (sample of
  400 records) with a tiny genuine overlap. It now judges overlap against
  the same relative tolerance as area-conservation. Area conservation now
  always runs (including with `--allow-overlap`), checked against
  `sum_of_parts - confirmed_overlap_area` instead of being skipped.
- Field values (e.g. an office name containing `&`) were decoded on read
  but written back to the output file unescaped, producing invalid XML
  and aborting the run. Checked the real UP dataset directly: no field
  currently contains `&`/`<`/`>`, so this hadn't been hit yet, but it's a
  live regression from v0.1 (which round-tripped already-escaped text via
  regex and never had this problem). All text is now XML-escaped on write.
- The vertex-count check compared a count derived from the XML parser
  against a round-trip re-read of the written file — this catches a
  *writing* bug but not a bug in the parser itself, since both numbers
  trace back to the same parse. A second, independent count — taken
  directly from the raw `<coordinates>` text before any XML parsing —
  is now compared against the parser's own count, closing that gap.

**Diagnostic findings, not yet acted on (documented, not fixed):**
- A full scan of the real UP dataset (1,655 records) found 9 PIN pairs
  that are very close but not technically touching. 2 of these are
  sub-centimeter apart (clear floating-point/digitization noise — almost
  certainly meant to touch) and would currently be wrongly reported as
  "not adjacent" by a merge attempt; the rest are tens of metres apart,
  which may be genuine small gaps rather than a data artifact. A
  configurable snap tolerance is a reasonable fix, but needs more
  real-pair testing before picking a default that doesn't also mask
  actual non-adjacency — not implemented yet.

**Scoping note:** every dataset-derived number in this file and the
README (hole/multi-part counts, overlap percentages, gap counts) is
specific to the Uttar Pradesh extract of the data.gov.in pincode-boundary
dataset used during development, not a claim about the full national
dataset or any other country's data.

## v0.2.0 — 2026-10-31

Fixes from code review of v0.1, plus a test suite.

**Fixed:**
- Merges that produced a hole (merged PINs surrounding an area not included
  in the merge) silently filled it in instead of failing or writing it.
  Now fails by default; `--allow-holes` writes the hole explicitly.
- Geometry extraction used regex and only read the first `<coordinates>`
  block per record, silently dropping inner rings (holes) and any
  additional polygon parts (`MultiGeometry`). Confirmed against the real
  dataset: 38 of 1,655 PIN records have holes, 58 have multi-part geometry
  — this was not a theoretical edge case. Extraction now uses a real XML
  parser and reads all of it.
- The vertex-count check compared two numbers derived from the same
  in-memory parse, so it could never catch a bug in writing the output
  file. Output is now written to a temp path, re-read from disk, and
  independently re-parsed before being moved to the real output path.

**Added:**
- `--office` to disambiguate a PIN with more than one record
- `--allow-low-complexity`, `--allow-round-numbers`, `--allow-holes`,
  `--allow-overlap` — explicit overrides for checks that fail by default,
  each printing a loud warning when used
- `--tolerance` for the merge area-conservation check (default loosened
  from exact floating-point equality to 1e-6 relative, since real adjacent
  PINs can have tiny digitization slivers — confirmed via a 400-record
  sample: ~1.3% of adjacent pairs have a genuine tiny overlap rather than
  a clean shared edge)
- `tests/` — a synthetic fixture generator and test runner exercising
  every validation check's pass/fail path through the real CLI
- `--version` on both scripts

**Known limitations carried into v0.2:**
- Merging a PIN with multi-part (`MultiGeometry`) geometry is explicitly
  refused, not supported. Extracting it alone works fully.

## v0.1.0 — 2026-10-30

Initial version: single-PIN extraction, two-or-more-PIN merge, basic
validation (vertex count, ring closure, round-number fabrication check,
minimum complexity, area conservation). Built and tested against the
Uttar Pradesh pincode-boundary dataset.
