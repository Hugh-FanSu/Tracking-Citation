# Citation processing boundaries (0.8.8)

The orchestration remains in engine/convert_batch.py. Publisher-specific evidence recovery is kept separate from extraction and workbook export.

Before extraction, the fixed English-only policy samples up to six PDF body pages with local deterministic language detection. Non-English input is excluded before engines/APIs; insufficient or mixed text is held for review. Cache repackaging follows the same gate. Exclusions are manifest entries and separate evidence files, not failed packets or zero-hit target records. No new identifiers are allocated for excluded documents.

1. **Immutable inputs**: original PDF, raw TEI and Docling outputs. Input PDF hash is checked before recovery.
2. **Shared PDF evidence**: pdf_evidence.py owns per-paper handles and bounded full-page extraction. Native region clipping is not replaced by approximate filtering. Each caller gets a mutable independent copy; errors and completion close documents and clear the session. Cache keys retain extraction options/order. Cache budget is 64 MiB of estimated retained Python objects and 192 entries; this is not a whole-process memory limit.
3. **Bibliographic repair**: merge/split/verify reference regions, then normalize the reference and citation index. This ordering is material: link recovery must see corrected reference identities.
4. **Citation evidence adapters**: numeric groups, author-year signatures, footnotes, and explicit source use contribute provenance-backed links. Their criteria differ; collapsing them into one loose regular expression would reduce precision.
5. **Context and source checks**: preserve original offsets; recover reading context separately and retain evidence for every correction.
6. **Catalogue matching**: CatalogIndex precomputes invariant title tokens and exact URL patterns once for an immutable batch catalogue snapshot. Per-paper memoization uses the original entry, parsed title and cited year. Every returned result is copied before target-specific changes. Ambiguous titles, conflicting dates and unmatched reports retain their prior handling.
7. **Export**: JSON remains the source of truth. Existing atomic numbering, per-paper cumulative Excel snapshots and readback checks are preserved.

## Remaining structural work

- Candidate creation and duplicate resolution are spread across adapters. A future typed evidence graph should give them one shared insertion/deduplication interface; preserve separate evidence types and ambiguous links rather than generalizing criteria prematurely.
- Context selection is shared only partly. Consolidating coordinate-based paragraph lookup should come after full paragraph/marker regression fixtures, not solely citation-count tests.
- Incremental Excel snapshots reread completed JSON and rebuild a workbook. Batch-end export reuses the last completed snapshot only when source JSON, template, mapping, numbering ledger, workbook and receipt/provenance fingerprints are unchanged. Final readback and optional API checks still run. Interrupted or changed snapshots fall back to export. This can become quadratic for large batches. A durable row store and verified incremental workbook writer could reduce it, but needs interrupted-run, numbering, report deduplication and template-preservation tests first.
- GROBID and Docling remain distinct engines; their shared reading of a PDF is intentional. Runtime reuse applies to deterministic postprocessing, not replacing independent parser evidence.

## Change gate

Run automated tests and compare reference identity, marker text, pages/coordinates, paragraph text, sentence provenance, ambiguity state and report matches. Counts alone cannot detect a citation linked to the wrong source. Report postprocessing and end-to-end timing separately. Keep a genuinely unseen evaluation set; debugging examples are regression cases, not unbiased accuracy estimates.
