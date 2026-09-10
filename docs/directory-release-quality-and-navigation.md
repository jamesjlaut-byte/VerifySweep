# Directory navigation and quality release

## Delivered scope

- One maintained search controller replaces layered inline rendering overrides.
- Separate Professionals / Companies views, with consistent counts and 12 items per page.
- Prominent verified-credentials filter, explicit city/state parsing, NFI credential-type options, clear/reset, shareable filters and page state.
- People are grouped within their listed company, with their individual credential evidence underneath. Same names at different company records are not merged.
- Source, expiration, and next-review information remain per credential. Conflicting statuses are retained, not collapsed into one badge.
- Profile links retain the search state. Company profiles group credentials under each person and offer retry/back actions on failure.
- Numeric company lookup queries the specific public record instead of searching only the first 100 companies. Static source IDs remain addressable as aliases of their canonical company card.
- Database-owned company cards retain matched public service-area evidence without adopting a static verification status.
- Read-only quality inventory: `python3 -B scripts/audit_directory_quality.py`.

## Test instructions

Run `python3 -B -m unittest discover -s tests -p 'test*.py' -q`.

Browser fixtures use an existing Playwright installation; no dependency or external service is installed:

`PLAYWRIGHT_MODULE=/path/to/playwright node tests/browser/directory-journey.cjs`

Set `CHROME_PATH` if Chrome is installed elsewhere. All browser-test responses are local fixtures. These tests do not create production submissions or change credentials.

## Local data audit at release preparation

123 stored credential records represent 119 distinct holder/company/state combinations. Their stored status checks currently qualify as verified: 81 CSIA, 41 NCSG, and 1 F.I.R.E. This is not a new check of issuer sources or proof of identity. There are no stored NFI verified records in this local dataset.

All 123 lack a documented expiration date; they have recheck dates. This is a research gap, not grounds to invent an expiry or declare someone uncertified. Of 377 company-source records, 219 have no documented service-area locations. Source records are not a count of unique companies.

## Still not complete

- Real authorized production admin review and pagination require an operational test.
- Email notifications require the separately approved DNS/service setup and delivery testing.
- Claim approval does not grant profile-owner editing or establish identity/affiliation.
- The normalized database's professional/credential read integration and legacy migration remain incomplete; no data migration is performed by this release.
- The database search's 100-row candidate cap remains; client pagination covers the returned result set, not an assertion of exhaustive national coverage.
- New service-area and credential evidence must be researched and reviewed. No mass scrape, invented records, or bulk verification was performed.

Homepage, other homeowner/pro tools, audit API, DNS, Vercel configuration, and environment variables are outside this release.
