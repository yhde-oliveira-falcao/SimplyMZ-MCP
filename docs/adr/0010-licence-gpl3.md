# ADR 0010: Licence is GPL-3.0-or-later
Status: Accepted · Date: 2026-10-12 · Decided by Yuri Falcao (chat, 2026-10-12)

## Context
SimplyMZ is published as open source, with commercial products (validation packages,
curated screening packs, services) planned around it. A permissive licence would let
anyone redistribute a modified, closed version.

## Decision
SimplyMZ is licensed under the **GNU General Public License v3.0 or later**
(LICENSE, `project.license = "GPL-3.0-or-later"` in pyproject.toml, README).
Anyone who distributes SimplyMZ or a modified version must release the corresponding
source under the same licence. Internal use inside a lab carries no obligation.

## Consequences
- All runtime dependencies are permissive (Apache-2.0, BSD, MIT, PSF; see
  docs/progress/dependency_licences.txt) and compatible with GPLv3.
- GPLv3 does not cover use over a network without distribution; a hosted edition by a
  third party would not have to publish changes (AGPL would). Revisit if a hosted product
  becomes the main offering.
- The copyright holder can still offer separate commercial licences. External
  contributions should come with a contributor agreement to keep that option open.
- Third-party data licences are unchanged (docs/data.md).
