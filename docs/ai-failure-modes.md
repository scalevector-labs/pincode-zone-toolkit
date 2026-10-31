# AI failure modes in geodata — what this toolkit was built in response to

This document describes failures observed in AI assistants used during this project's development (late October 2026), on tasks of the kind this toolkit automates: extract a PIN-code boundary, merge adjacent ones, or read a large source file. The underlying pattern — answering from whatever text was in context instead of mechanically checking it against the source — is not specific to any one vendor.

The individual observations, however, come from the specific assistants and product behaviour in use at the time. Failure 2 in particular concerns a product's file-upload layer rather than a model. Products change, so these may not reproduce today: read the figures as measurements taken on those dates, not as claims about any current product.

All figures below are measured against the Uttar Pradesh extract of the data.gov.in pincode-boundary dataset used during this project's development (1,655 records) — not a claim about any other dataset.

## The core pattern

In every case, the failure traces back to one habit: **treating whatever text landed in the model's context as if it were the complete, authoritative data, instead of mechanically verifying it against the source.** A model asked to "read a file" or "draw a boundary" will, by default, answer from whatever it was shown — and has no way to know, on its own, whether that was the whole picture or a truncated, approximated, or silently-corrupted slice of it.

## Failure 1 — generating geometry instead of extracting it

Asked to produce a KML boundary for a specific PIN code, a general-purpose AI assistant returned a polygon with only 15–17 vertices. The real boundary for that PIN, extracted mechanically from the source file, has 28 to 85 vertices depending on which of two adjacent PINs. Measured against the real boundary, the generated shapes overlapped it by only 61–65% (intersection over union, IoU) — so roughly a third of the combined footprint did not match.

**The tell:** 14 of 15 points in one shape, and all 17 points in the other, rounded to 3 or fewer decimal places (e.g. `83.628000,26.431000`). Real surveyed boundary data is never this clean — rounded coordinates at this density are the signature of coordinates being recalled or estimated, not copied from an actual source. The same output also included confident, precise-sounding supporting detail (exact span measurements, ~30 named "anchor points" with invented coordinates) that was never derived from, or checked against, the source dataset.

**What a correct merge of the same two PINs actually required:** not hand-picked "seam" points joining two shapes, but a real geometric union (dissolve) computed from both polygons' full, exactly-extracted rings — a computation, not a guess, and one that can be verified afterward (merged area must equal the sum of the parts; see `scripts/validate.py`).

## Failure 2 — reading only a fraction of a file, confidently

Given the same ~5 MB source file and asked how many PIN-code records it contained, an assistant reported 114 — with a note that ingestion had cut off "roughly 90%" of the file. This happened identically through two different upload paths into the same product.

**Root cause, as measured then:** the actual truncation point was byte 393,081 of the file — **135 bytes short of exactly 384 KiB (393,216 bytes)**, a classic fixed ingestion-buffer size. This is not a model context-window limit (modern context windows are far larger than a 5 MB file); it was a text-extraction/preview layer that silently capped how much of an uploaded file became readable text, with no visible warning that anything was cut. This is a product behaviour observed on those dates and may have changed.

**A second, independent bug stacked on top:** of the ~198 records that genuinely were visible before the cutoff, the assistant's own listing correctly captured 196 of them — but it then reported its *total* as 113–114, undercounting its own correctly-read data by nearly half. A precise-sounding number was stated without being counted.

**The fix that is proven to work:** explicitly instructing the assistant to write and run code that opens the file from disk, parses it, and counts every record — "answer only from what the code outputs, not from what you can see in the text" — produced a fully correct result: 1,655 total records, first PIN 247342, last PIN 272205, all independently verified against the source file.

## Failure 3 — code that ran, but whose output was never checked

A later attempt to reproduce a merged-boundary file did involve real code — and still produced a file that a GIS tool (Google My Maps) rejected outright as unparseable. Inspection found, all independently verifiable:

| Check | Result |
|---|---|
| XML well-formed? | **No** — a `<Folder>` tag was opened once, never closed. |
| Polygon ring closed? (first coordinate = last) | **No** — off by 0.53°, roughly 58 km. |
| Declared vertex count vs. actual | Description claimed 104 (coincidentally the *correct* number); actual coordinate list had 286 points. |
| Shape | Not a boundary: a small tight loop near the real area, then a ~50 km straight-line run, then a vertical jump — never closing. |

The small loop sat roughly in the right location, suggesting part of the generation process started from a reasonable basis — then diverged into a runaway, the signature of a loop or parametric routine (an angle sweep, a hand-rolled offset calculation) that had a bug and never terminated or wrapped back to the start the way a closed ring must.

**Why this is a distinct lesson from the first two:** those were about never trusting free-generated or unverified-as-complete *input*. This one is about never trusting unverified *output*, even when it came from genuine code. Writing code doesn't guarantee correctness — only checking the code's actual output against hard, specific criteria does.

## What this toolkit does about it

Every check below exists because one of the three failures above would have been caught by it. They are implemented as enforced code in `scripts/validate.py` and the two scripts, not just described here:

| Check | Catches |
|---|---|
| Exact-match record lookup, zero/multiple matches both hard-stop | Guessing at which record is correct |
| Verbatim coordinate text (not re-parsed/reformatted) | Failure 1's generated-not-extracted coordinates |
| Round-number fraction check | The specific fabrication signature from Failure 1 |
| Minimum vertex-count check | A hand-drawn approximation standing in for real data |
| Raw-text vertex count vs. XML-parsed count (independent of each other) | A bug in the parser itself |
| Written-file re-parse vs. intended output (independent of the above) | Failure 3's class of bug — a serialization/writing error, not a reading error |
| Ring-closure check on every ring (not just the first) | Failure 3's open-ring, 58 km-gap defect directly |
| Tag-balance check | Failure 3's unclosed-`<Folder>` defect directly |
| Real polygon-union geometry for merges, never hand-picked points | Failure 1's invented "seam" |
| Area-conservation check (merged area = sum of parts, within tolerance) | A merge that silently drops or double-counts territory |

None of these checks are theoretical. Each was added — or tightened — because a real, observed failure would have slipped through without it.
