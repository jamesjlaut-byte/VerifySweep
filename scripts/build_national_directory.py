#!/usr/bin/env python3
"""Build a conservative, public directory seed from VerifySweep research candidates."""
import argparse
import hashlib
import json
import re
from datetime import date
from urllib.parse import urlparse

CONFIRMED_SINGLE_COMPANIES={
    "a step in time chimney sweeps",
    "the original chimney sweep, inc.",
    "dakota chimney & restoration, inc.",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def domain(value):
    try:
        host = (urlparse(clean(value)).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except ValueError:
        return ""


def state_code(value):
    match=re.search(r"(?:^|/)([A-Z]{2})(?:/|$)",clean(value).upper())
    return match.group(1) if match else ""


def location(value, fallback_state=""):
    text = clean(value)
    match = re.match(r"^(.*?),\s*([A-Z]{2})$", text)
    if match:
        return {"city": clean(match.group(1)), "state": match.group(2)}
    return {"city": text, "state": fallback_state} if text else None


def unique_strings(values):
    found = []
    seen = set()
    for value in values:
        text = clean(value)
        key = text.casefold()
        if text and key not in seen:
            found.append(text)
            seen.add(key)
    return found


def source_kind(url, website):
    source_domain = domain(url)
    website_domain = domain(website)
    if source_domain and website_domain and source_domain == website_domain:
        return "company_owned"
    if source_domain in {"web.csia.org", "csia.org", "www.csia.org", "nficertified.org", "www.nficertified.org"}:
        return "official_credential_directory"
    return "third_party" if source_domain else "not_recorded"


def merge_records(records):
    groups = {}
    for index, row in enumerate(records):
        website_domain = domain(row.get("website"))
        name = clean(row.get("company")).casefold()
        hq = (clean(row.get("hq_city")).casefold(), state_code(row.get("hq_state")))
        # Same domain is the strongest supplied identifier. Keep same-name/different-HQ records separate.
        if name in CONFIRMED_SINGLE_COMPANIES:
            key=("research_confirmed",name)
        else:
            key = ("domain", website_domain) if website_domain else ("identity", name, *hq, index)
        groups.setdefault(key, []).append(row)

    output = []
    for key, rows in groups.items():
        primary = max(rows, key=lambda r: (bool(clean(r.get("website"))), bool(clean(r.get("source_url"))), len(r.get("service_areas") or [])))
        website = clean(primary.get("website"))
        website_domain = domain(website)
        hq_city = clean(primary.get("hq_city"))
        hq_state = state_code(primary.get("hq_state"))
        company = clean(primary.get("company"))
        service_rows = []
        service_seen = set()
        claims = []
        sources = []
        candidate_people = []
        states_discovered = []
        for row in rows:
            states_discovered.append(clean(row.get("state")).upper())
            area_source = clean(row.get("service_area_source_url"))
            area_kind = source_kind(area_source, clean(row.get("website")) or website)
            for raw_area in row.get("service_areas") or []:
                parsed = location(raw_area, clean(row.get("state")).upper())
                if not parsed:
                    continue
                area_key = (parsed["city"].casefold(), parsed["state"])
                if area_key in service_seen:
                    continue
                service_seen.add(area_key)
                active = bool(area_source) and area_kind == "company_owned"
                service_rows.append({
                    **parsed,
                    "area_type": "city",
                    "source_url": area_source or None,
                    "evidence_type": area_kind,
                    "evidence_status": "active" if active else "review_needed",
                    "last_checked_at": None,
                })
            source_url = clean(row.get("source_url"))
            if source_url:
                sources.append({"url": source_url, "type": source_kind(source_url, clean(row.get("website")) or website)})
            if area_source:
                sources.append({"url": area_source, "type": area_kind})
            evidence = clean(row.get("credential_evidence"))
            for claim in row.get("credentials_claimed") or []:
                claims.append({
                    "claim": clean(claim),
                    "classification": "UNVERIFIED CLAIM",
                    "source_url": source_url or None,
                    "evidence_note": evidence or None,
                })
            for person in row.get("verified_people") or []:
                candidate_people.append({
                    "name_or_note": clean(person),
                    "status": "VERIFICATION NEEDED",
                    "source_url": source_url or None,
                    "note": "Imported research lead; not published as a verified credential.",
                })
        stable = website_domain or "|".join((company.casefold(), hq_city.casefold(), hq_state))
        output.append({
            "id": "national-" + hashlib.sha256(stable.encode()).hexdigest()[:14],
            "company": company,
            "website": website or None,
            "normalized_domain": website_domain or None,
            "hq_city": hq_city or None,
            "hq_state": hq_state or None,
            "public_status": "unverified",
            "display_status": "UNVERIFIED COMPANY RECORD",
            "states_discovered": unique_strings(states_discovered),
            "service_locations": service_rows,
            "company_claims": list({json.dumps(c, sort_keys=True): c for c in claims if c["claim"]}.values()),
            "professional_candidates": list({json.dumps(p, sort_keys=True): p for p in candidate_people if p["name_or_note"]}.values()),
            "sources": list({json.dumps(s, sort_keys=True): s for s in sources}.values()),
            "last_reviewed_at": None,
            "record_notice": "Company discovery record only. Credential claims are not verified individual credentials.",
        })
    return sorted(output, key=lambda r: (r["company"].casefold(), r.get("hq_state") or "", r.get("hq_city") or ""))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("master")
    parser.add_argument("output")
    args = parser.parse_args()
    with open(args.master, encoding="utf-8") as source:
        payload = json.load(source)
    records = merge_records(payload["records"])
    result = {
        "schema_version": 1,
        "generated_from": "VerifySweep National Directory Research Master",
        "source_generated_at": payload.get("generated_at"),
        "built_at": date.today().isoformat(),
        "source_record_count": len(payload["records"]),
        "canonical_record_count": len(records),
        "policy": "Candidate company discovery data. Company claims and professional leads are not verified credentials.",
        "records": records,
    }
    with open(args.output, "w", encoding="utf-8") as target:
        json.dump(result, target, indent=2, ensure_ascii=False)
        target.write("\n")


if __name__ == "__main__":
    main()
