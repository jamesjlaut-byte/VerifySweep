# VerifySweep manual-library sourcing rules

The catalog stores appliance metadata and source links. It does not store or
republish manufacturer PDFs unless VerifySweep has express permission.

## Required review before bulk ingestion

For every source, record:

- the official source owner;
- the public search or feed URL;
- robots directives;
- the applicable terms-of-use URL and review date;
- whether automated collection is permitted;
- whether deep links and commercial reuse are permitted;
- whether PDF copying is permitted;
- the approved request rate or feed schedule;
- a contact or written license when permission is required.

An `Allow` rule in `robots.txt` is not permission to copy, republish, or create
a commercial bulk directory. Terms, copyright, and source-specific restrictions
still control the ingestion decision.

## Current HHT finding

Reviewed 2026-09-01:

- Heat & Glo exposes a public manual finder and its robots file currently allows
  crawling.
- The linked Hearth & Home Technologies Website Terms of Use, last modified
  2026-01-22, prohibit automated access/copying without prior written consent,
  restrict commercial use, and restrict deep linking.
- Therefore no automated bulk import from Heat & Glo, Majestic, Heatilator,
  SimpliFire, or other covered HHT sites is approved for VerifySweep.
- Existing records must remain link-only and should be reviewed with counsel or
  the source owner before the catalog is commercialized at scale.

Terms reviewed:
https://hearthnhome.com/pages/hearth-home-technologies-website-terms-of-use

## Approved scale path

The path to 10,000 records is one or more of:

1. a written manufacturer license or official data feed;
2. a distributor/manufacturer export that expressly permits catalog use;
3. technician-submitted metadata and links, reviewed before publication;
4. public-domain or permissively licensed documents; or
5. source-owner partnerships that provide update and removal procedures.

Every record still passes `python3 scripts/manual_library.py validate`, and the
published compact index and record shards are generated with
`python3 scripts/manual_library.py build`.
