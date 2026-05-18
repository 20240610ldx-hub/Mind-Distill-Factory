# Source Materials Are Local-Only

Mind Distill Factory is designed to work with user-provided source materials under:

```text
sources/{person-slug}/raw/
```

Those raw materials are intentionally not included in this public repository.

Reasons:

- Many books, PDFs, recordings, and research archives are third-party copyrighted works.
- Local corpora may contain private notes, OCR scratch files, or provenance metadata.
- The public repo should remain lightweight and reproducible as tooling, not as a redistribution channel for source texts.

To use the pipeline, create the folder for a thinker locally and add lawful source files yourself:

```text
sources/
  sun-tzu/
    raw/
      art_of_war_translation.txt
      notes_from_public_domain_source.md
```

Generated processed files such as `sources/{slug}/processed/user_sources.json` remain part of the local workflow contract, but they are not committed by default in the lean public release.
