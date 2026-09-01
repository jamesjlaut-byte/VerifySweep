#!/usr/bin/env python3
"""Validate and build the static VerifySweep appliance-manual catalog."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "appliance-manuals.json"
INDEX = ROOT / "data" / "appliance-manual-index.json"
RECORDS = ROOT / "data" / "appliance-records"
APPLIANCE_TYPES = {"Factory-Built Fireplace", "Wood Stove", "Wood Insert", "Gas Fireplace", "Gas Insert", "Gas Stove", "Pellet Stove", "Pellet Insert", "Electric Fireplace", "Outdoor Fireplace", "Other Hearth Appliance"}
FUEL_TYPES = {"Wood", "Gas", "Pellet", "Electric", "Multi-Fuel", "Other"}
PRODUCT_STATUSES = {"Current", "Discontinued", "Unknown"}
SOURCE_TYPES = {"OFFICIAL MANUFACTURER", "OFFICIAL ARCHIVED MANUFACTURER DOCUMENT", "TRUSTED DOCUMENT ARCHIVE", "TECHNICIAN-SUBMITTED DOCUMENT", "UNVERIFIED DOCUMENT"}
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def read_catalog() -> dict:
    with CATALOG.open(encoding="utf-8") as handle:
        return json.load(handle)


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    appliances = data.get("appliances")
    if not isinstance(appliances, list): return ["appliances must be an array"]
    appliance_ids: set[str] = set()
    document_ids: set[str] = set()
    document_urls: set[str] = set()
    for pos, appliance in enumerate(appliances, 1):
        where = f"appliance #{pos}"
        aid = appliance.get("id", "")
        if not ID_RE.fullmatch(aid): errors.append(f"{where}: invalid id {aid!r}")
        if aid in appliance_ids: errors.append(f"{where}: duplicate appliance id {aid}")
        appliance_ids.add(aid)
        for key in ("manufacturer", "brand"):
            if not isinstance(appliance.get(key), str) or not appliance[key].strip(): errors.append(f"{where}: {key} is required")
        models = appliance.get("models")
        if not isinstance(models, list) or not models or any(not isinstance(x, str) or not x.strip() for x in models):
            errors.append(f"{where}: at least one non-empty model is required"); models = []
        if appliance.get("appliance_type") not in APPLIANCE_TYPES: errors.append(f"{where}: unsupported appliance_type {appliance.get('appliance_type')!r}")
        if appliance.get("fuel_type") not in FUEL_TYPES: errors.append(f"{where}: unsupported fuel_type {appliance.get('fuel_type')!r}")
        if appliance.get("product_status") not in PRODUCT_STATUSES: errors.append(f"{where}: unsupported product_status {appliance.get('product_status')!r}")
        docs = appliance.get("documents")
        if not isinstance(docs, list) or not docs:
            errors.append(f"{where}: at least one document is required"); continue
        normalized_models = {re.sub(r"[^a-z0-9]", "", x.lower()) for x in models}
        for doc_pos, doc in enumerate(docs, 1):
            dwhere = f"{where} document #{doc_pos}"
            did = doc.get("id", ""); composite = f"{aid}/{did}"
            if not ID_RE.fullmatch(did): errors.append(f"{dwhere}: invalid id {did!r}")
            if composite in document_ids: errors.append(f"{dwhere}: duplicate document id {composite}")
            document_ids.add(composite)
            if not isinstance(doc.get("title"), str) or not doc["title"].strip(): errors.append(f"{dwhere}: title is required")
            if doc.get("source_type") not in SOURCE_TYPES: errors.append(f"{dwhere}: unsupported source_type")
            url = doc.get("url", ""); parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.netloc: errors.append(f"{dwhere}: HTTPS source URL is required")
            if url in document_urls: errors.append(f"{dwhere}: duplicate source URL {url}")
            document_urls.add(url)
            for key in ("date_added", "last_source_check"):
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(doc.get(key, ""))): errors.append(f"{dwhere}: {key} must be YYYY-MM-DD")
            doc_models = doc.get("models")
            if not isinstance(doc_models, list) or not doc_models: errors.append(f"{dwhere}: document model association is required")
            elif not ({re.sub(r'[^a-z0-9]', '', x.lower()) for x in doc_models} & normalized_models): errors.append(f"{dwhere}: document models do not match the appliance models")
    return errors


def compact_record(appliance: dict) -> dict:
    return {"id": appliance["id"], "manufacturer": appliance["manufacturer"], "brand": appliance.get("brand"), "models": appliance["models"], "model_family": appliance.get("model_family"), "appliance_type": appliance["appliance_type"], "fuel_type": appliance["fuel_type"], "product_status": appliance["product_status"], "document_count": len(appliance.get("documents", [])), "source_types": sorted({d["source_type"] for d in appliance.get("documents", [])})}


def build(data: dict) -> None:
    RECORDS.mkdir(parents=True, exist_ok=True)
    expected = set()
    for appliance in data["appliances"]:
        path = RECORDS / f"{appliance['id']}.json"; expected.add(path.name)
        path.write_text(json.dumps(appliance, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    for old in RECORDS.glob("*.json"):
        if old.name not in expected: old.unlink()
    index = {"schema_version": data.get("schema_version", 1), "updated_at": data.get("updated_at"), "source_policy": data.get("source_policy"), "record_count": len(data["appliances"]), "document_count": sum(len(a.get("documents", [])) for a in data["appliances"]), "appliances": [compact_record(a) for a in data["appliances"]]}
    INDEX.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=("validate", "build")); args = parser.parse_args()
    data = read_catalog(); errors = validate(data)
    if errors:
        print("Manual catalog validation failed:", file=sys.stderr)
        for error in errors: print(f"- {error}", file=sys.stderr)
        return 1
    count = sum(len(a["documents"]) for a in data["appliances"])
    print(f"Validated {len(data['appliances'])} appliances and {count} documents.")
    if args.command == "build": build(data); print(f"Built compact index and {len(data['appliances'])} sharded records.")
    return 0


if __name__ == "__main__": raise SystemExit(main())
