# ADR 0004: Spectral libraries and licences
Status: Accepted · Date: 2026-10-04 · Accepted by Yuri Falcao (chat, 2026-10-04)

## Decision
Never bundle third-party spectra. Opt-in downloader for MassBank (verify the current
release format and per-record licence field when implementing M4.T4). Every library
spectrum carries its licence; `match_spectrum` reports it. Tests use the synthetic MSP in
`tests/fixtures/library/` (CC0, generated). NIST libraries are never supported for
redistribution.

## Implementation note (2026-10-05)
MassBank 2026.03 assets are MassBank.json, MassBank_NISTformat.msp and
MassBank_RIKENformat.msp. The MSP formats carry no licence; MassBank.json has one
`license` per record. scripts/download_library.py merges the two by accession (DB#) so
every spectrum keeps its licence (see docs/data.md).
