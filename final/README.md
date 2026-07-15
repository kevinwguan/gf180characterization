# Final external-GDS deliverable

This directory is produced by `make final-gds` and `make signoff-final`.

The flow uses `../gds/padring_test_structures.gds` as the complete incoming
layout. It does **not** generate, import, or merge the padring defined by this
repository. The only geometry added before sign-off is the Wafer.Space GF180MCU
seal ring from the pinned Wafer.Space PDK.

Run:

```sh
make final-gds
make signoff-final
```

Override `FINAL_GDS_SOURCE`, `FINAL_GDS_TOP`, or `FINAL_GDS_SLOT` when needed.
`manifest.json` records hashes and verifies that all incoming geometry remains
present in the sealed output.
