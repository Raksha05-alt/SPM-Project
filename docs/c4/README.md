# C4 model

| File | Level |
|---|---|
| `c4-1-context` | Level 1, system context |
| `c4-2-container` | Level 2, containers |
| `c4-3-component` | Level 3, components of the API application |
| `domain-sprint1` | Sprint 1 domain model (not part of C4) |

SVG is the source; the PNGs are exports for documents and slides.

The [equipment foundation contract](../equipment-contract.md#architecture) adds
the G03 data model and responsibilities inside the existing equipment API component.
It introduces no new container.

The existing exports are historical architecture snapshots. The
[SCRUM-89/53 supplement](lead-assignment.md) documents the new Lead actor,
allocation component interactions and transaction sequence without replacing
those earlier exports. Incorporate this supplement when preparing Sprint 3 diagrams.

The architecture steward updates these at the end of every sprint. The
Definition of Done requires an update whenever a new container or component
appears, so that the component diagram never describes a system nobody built.
