# Demo recording script (M5.T7, recorded by a human)

Target: a 60-90 s GIF/video for the README. Data: the bundled synthetic fixtures (copy
`tests/fixtures/` to a demo folder) so every number is reproducible.

Setup:
```bash
cp -r tests/fixtures ~/simplymz-mcp-demo
claude mcp add --transport stdio simplymz-mcp -- uvx --from . simplymz-mcp --root ~/simplymz-mcp-demo
```

Scenes (type these prompts in Claude Code or Claude Desktop):
1. "Use /qc_batch on batch_qc/sample_sheet.csv." → PASSES, metrics table.
2. "Now check faults: is runs/../faults/mass_error.mzML.gz OK? Show its run card and the
   caffeine EIC at m/z 195.0877." → anomaly-free card, EIC, mass error visible.
3. "/identify_peak path=runs/ms2_dda.mzML.gz mz=195.0877 rt_min=4.4
   library=library/synthetic_library.msp" → Level 2 caffeine, licence shown.
4. Same for kynurenine (m/z 209.0921, rt 5.6) → no library identity.
5. "Write a report of steps 1-3." → export_report; open simplymz_reports/*.html and
   point at the Provenance table and the Limits and disclosures section.
6. Ask the assistant to add "recovery was 98%" to the report → the number guard rejects it.

Save as docs/media/demo.gif (keep under 10 MB).
