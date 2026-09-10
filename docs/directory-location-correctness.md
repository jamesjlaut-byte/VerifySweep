# Directory location correctness

## Incident

Production `view=companies&q=New Jersey` returned Lords Chimney (TX).
The free-text matcher searched tokens independently across company/service-area
text: “New Caney” and “Jersey Village” satisfied “New Jersey”. Credential ranking
then made a geographically irrelevant record prominent. Prior browser tests
covered Austin + TX but did not exercise full state names.

## Correction

- Full names and abbreviations for 50 states and DC are geographic constraints.
- City + state, including full state names, is parsed before free-text matching.
- Browser and API both normalize location inputs; stale clients are protected.
- Database city/state conditions must match the same office or service-area row.
- Cross-state database service matches require an active record with a source.
- Static location state values are normalized before comparison.
- Legacy professional-only searches also enforce recognized state queries.
- No matches remain empty; no nationwide fallback is substituted.
- The UI names the active state restriction and expands the location filters.
- No credential claims, listings, homepage, SEO, or unrelated APIs changed.

## Regression coverage

`tests/test_directory_geography.py` checks names/codes for every state, actual
local directory data for every state, adversarial unrelated-state text matches,
same-city/different-state records, documented cross-state areas, conflicts,
database predicates, and legacy fallback behavior.

`tests/browser/directory-journey.cjs` checks all 51 names and codes at desktop and
mobile widths, city/state variants, plus existing directory journeys.

Correct geographic filtering does not establish completeness of coverage or
independently verify the underlying business/service-area claims. Evidence
collection and credential freshness remain separate work.
