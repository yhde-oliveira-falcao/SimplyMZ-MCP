# ADR 0011: Bind reported values, identification evidence and batch denominators

Status: Accepted · Date: 2026-11-08 · Accepted by Yuri Falcao (chat, 2026-11-08)

## Context
The report guard previously accepted a number if it occurred anywhere in referenced
results, ignored titles and inline code, and allowed sign reversal. Identification
records were combined by m/z alone. Group-comparison sample counts came from detected
feature rows, so a sample with no detections disappeared from the denominator.

## Decision
- Require explicit `{ev:<id>:<path>}` slots for numeric report content, including titles,
  headings and inline code. A slot names the source field; numeric equality elsewhere
  is insufficient. Literal signs may not modify numeric slots. Chemical identifiers
  and body ordered-list markers remain exempt. Render title slots in HTML metadata too.
- Record the input run SHA-256, actual selected scan RT (minutes), and scan polarity
  with formula and spectrum evidence. Combining records requires one run hash, m/z
  within the existing 10 ppm tolerance, and an RT span no larger than 0.15 min. Reject
  conflicting scan polarities and adduct assignments, including passing library hits.
  Increment the confidence ruleset version. Preserve standalone mass-only formula use;
  require recomputation of legacy records before combining them.
- Persist the complete batch roster with aligned feature tables. Calculate replicate
  counts and presence denominators from that roster, impute missing sample areas using
  the existing rule, and disclose samples with no detections. Read the batch roster
  from state for older tables. Reject ambiguous legacy basename collisions and require
  redetection. New tables use full relative paths for run labels.

## Consequences
Existing report templates must replace literal measurements with slots. Older ledger
rows remain immutable. Scientific interpretation still requires review: field-level
value provenance cannot establish that surrounding prose names the right metric. The
RT window is a conservative association rule, not proof of identity for co-eluting
isomers; RT warping and reference-standard confirmation remain outside this change.
No statistical test or missing-value imputation rule changes.

## Validation
Regression tests cover report titles/code/signs and field references; cross-run,
cross-RT, polarity, adduct and legacy evidence rejection through MCP; and empty samples,
empty groups and empty tables with both persisted and legacy batch rosters.
