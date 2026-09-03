# Directory Phase 1 migration notes

Phase 1 is an additive trust-data foundation. It does not delete, rewrite, or automatically publish legacy `pro_directory` records.

## Safety rules

- Keep `pro_directory` intact as the compatibility source until migrated records have been compared field by field.
- Create separate company, professional, credential type, professional credential, affiliation, verification, source, evidence, and audit entities.
- Record every legacy mapping in `directory_legacy_migration_map`.
- Mark ambiguous relationships `ambiguous`; do not invent a company affiliation or identity match.
- Preserve an existing credential verification only when its current source and verification date support that exact individual credential claim.
- Never convert a company claim, logo, directory listing, or profile claim into a verified professional credential.
- Default evidence to private and expose only an explicit public summary.
- Preserve append-only verification and audit history.

## Proposed migration sequence

1. Take a database snapshot using the hosting provider's supported backup mechanism.
2. Inventory legacy records without changing them.
3. Normalize companies and flag possible duplicate domains, phones, and names for review.
4. Create professional records without marking identity verified.
5. Create credential types, then link professional credential records.
6. Create affiliation records as pending unless separate reviewed evidence establishes the relationship.
7. Create verification and source records for supported legacy evidence.
8. Compare legacy and normalized public responses before switching reads.
9. Keep rollback available by retaining legacy reads and the migration map.

No automatic data-copy step runs in Phase 1. Production reads remain backward-compatible while the normalized model is reviewed and populated deliberately.
