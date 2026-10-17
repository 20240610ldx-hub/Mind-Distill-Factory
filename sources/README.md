# Source Materials Are Local-Only

Mind Distill Factory uses lawful source materials under:

```text
sources/{person-slug}/raw/
```

Raw materials are intentionally excluded from this public repository. They may be copyrighted, private, or too large to redistribute. Add only files you are authorized to process.

## Supported input

The indexer currently supports `.txt`, `.md`, `.markdown`, and `.pdf`, including nested folders. EPUB is not silently accepted. PDF ingestion records a SHA-256 source registry and page-level extraction metadata under `processed/`.

PDFs are classified per page and per document as:

- pure text PDF: native text is used without OCR;
- mixed text/image PDF: native text is retained and substantive image pages are OCR candidates;
- pure image PDF: substantive image pages are OCR candidates;
- empty/unreadable PDF: blocked or sent for manual review.

Only pages containing an information-rich image, or pages whose text quality is poor, trigger OCR. The default optional backend is the CPU-oriented RapidOCR adapter. PaddleOCR is an optional high-accuracy escalation path. Native text and OCR text are kept as separate provenance layers; OCR output never silently replaces the source layer.

## Generated metadata

A normal index run writes local-only artifacts such as:

```text
sources/{slug}/processed/source_registry.json
sources/{slug}/processed/extracted/{source_id}.txt
sources/{slug}/processed/extracted/{source_id}.json
sources/{slug}/processed/local_shards/manifest.json
sources/{slug}/processed/local_shards/sampling_plan.json
sources/{slug}/processed/local_shards/dispatch_plan.json
sources/{slug}/processed/local_shards/cost_estimate.json
```

The registry binds each source to its relative path, media type, size, SHA-256, source role, origin, rights status, and duplicate relationship. PDF sidecars are accepted for provenance checks only when their `parent_sha256` matches the registered raw PDF.

Large corpora are indexed before worker dispatch. The sampling plan records the seed, strata, selected units, token coverage, and omitted strata. The dispatch plan gives the orchestrator bounded batches based on token size, OCR state, and estimated understanding difficulty. The main agent should dispatch workers incrementally so one difficult shard cannot consume the entire context window.

If the cost upper bound exceeds the configured budget, the orchestrator must ask whether to process exhaustively, use stratified sampling, reduce scope, or cancel before starting expensive workers or network supplementation. If pricing is not configured, `cost_estimate.json` reports token and request ranges with `cost_unknown`; it does not invent a currency amount.

Generated processed files such as `user_sources.json` remain part of the local workflow contract and are not committed by default in the lean public release.
