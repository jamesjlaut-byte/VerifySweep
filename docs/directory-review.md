# Directory review workflow

Open `/directory-review.html` using the existing `DIRECTORY_ADMIN_TOKEN` and a reviewer name. Do not send the token through chat, email, a query string, or a public profile. This is an interim interface for the existing shared-token authorization, not a multi-user login system. Reviewer names are operator-entered labels, not independently authenticated identities.

The page loads private records only after the server accepts authorization. It has no third-party scripts, stores no token in browser storage, clears data on navigation or Lock & Clear, and keeps source links separate from the authenticated API. Lock the page when finished, especially on shared computers.

## What review decisions do

Review saves require the `review_version` returned by the private queue. The server checks this against the current row version while holding a row lock. If it changed, HTTP 409 is returned without saving the decision or its audit event. The page preserves the draft note; copy it if needed, then refresh and reassess the current record before saving. Old clients missing the version must refresh/update rather than bypass this check. The version is an opaque concurrency marker, not an authorization credential.

- Claims: record pending evidence, approval, rejection, or withdrawal. Approval alone does **not** provision a user account, grant profile editing, establish employment, or verify credentials.
- Corrections: record reviewing/resolved/dismissed. Apply and verify a legitimate factual correction separately before marking it resolved. This screen never automatically deletes listings.
- Credential submissions: organize the evidence-review workflow. Ready for verification is not a verified credential. Official-source verification remains a separate authorized operation.
- Reverification: view the existing backend queue of expired/overdue or unavailable records. This queue does not cover every static-source record or provide a complete database migration.

Every saved decision requires a private audit note. If saving times out, refresh the appropriate status queue before retrying. Claims/corrections show 200 records per page and submissions show 250. Use Next Page to continue or First Page to restart. Pages are ordered by record ID and use an ID cursor so reviewed records leaving the queue do not shift later pages. Changing queue or status starts at the first page. Refresh reloads the current page; use First Page to see new or reopened earlier records. Reverification remains limited to the first 250 due records; these screens are not full-history exports.

## Outstanding completion requirements

- Configure the missing Resend DNS records with domain-owner approval, confirm the domain is verified, then implement and test transactional notifications. No automatic claim/correction emails are currently sent.
- Confirm an authorized reviewer can access real production queues and complete an appropriately authorized review. Browser fixture tests are not a substitute for this operational check.
- Profile self-service editing/account access is not implemented by claim approval.
- Independently verify credentials and affiliation evidence; do not fabricate results to fill data gaps.
