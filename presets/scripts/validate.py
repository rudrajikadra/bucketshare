#!/usr/bin/env python3
"""Validate the BucketShare presets feed (Python 3.9+).

    python3 presets/scripts/validate.py                  # check everything
    python3 presets/scripts/validate.py --write-manifest # refresh sha256, bytes and updatedAt, then check

Checks: JSON Schema for every file, unique IDs, emoji present, cross references (parents,
featured presets, tax tables, localName countries, subscription categories), manifest
hashes, and every tax sample against tax_reference.py.
"""
import datetime
import hashlib
import json
import os
import sys
import unicodedata

try:
    import jsonschema
except ImportError:
    sys.exit("jsonschema is missing. Install it with: pip3 install --user jsonschema")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tax_reference  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V1 = os.path.join(ROOT, "v1")
SCHEMA = os.path.join(ROOT, "schema")
errors = []


def fail(message):
    errors.append(message)


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def check_schema(data, name, label):
    validator = jsonschema.Draft7Validator(load(os.path.join(SCHEMA, name + ".schema.json")),
                                           format_checker=jsonschema.FormatChecker())
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        fail("%s: %s at %s" % (label, err.message, "/".join(str(p) for p in err.path)))


def is_emoji(text):
    return any(unicodedata.category(ch) == "So" or 0x1F000 <= ord(ch) <= 0x1FAFF for ch in text)


def unique(items, key, label):
    seen = set()
    for item in items:
        value = item.get(key)
        if value in seen:
            fail("%s: duplicate %s %r" % (label, key, value))
        seen.add(value)
    return seen


def feed_files():
    found = []
    for base, _, names in os.walk(V1):
        for name in names:
            if name.endswith(".json") and name != "manifest.json":
                found.append(os.path.relpath(os.path.join(base, name), V1).replace(os.sep, "/"))
    return sorted(found)


def sha256(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def write_manifest():
    path = os.path.join(V1, "manifest.json")
    manifest = load(path) if os.path.exists(path) else {"version": 1, "schemaVersion": 1, "minAppVersion": "1.0"}
    old = {f["path"]: f for f in manifest.get("files", [])}
    files = []
    for rel in feed_files():
        full = os.path.join(V1, rel)
        entry = {"path": rel, "sha256": sha256(full), "bytes": os.path.getsize(full)}
        if "minAppVersion" in old.get(rel, {}):
            entry["minAppVersion"] = old[rel]["minAppVersion"]
        files.append(entry)
    manifest["files"] = files
    manifest["updatedAt"] = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print("wrote manifest.json (%d files)" % len(files))


def main():
    if "--write-manifest" in sys.argv:
        write_manifest()

    manifest = load(os.path.join(V1, "manifest.json"))
    check_schema(manifest, "manifest", "manifest.json")
    listed = {f["path"]: f for f in manifest["files"]}
    for rel in feed_files():
        if rel not in listed:
            fail("manifest.json: %s is not listed" % rel)
    for rel, entry in listed.items():
        full = os.path.join(V1, rel)
        if not os.path.exists(full):
            fail("manifest.json: %s is listed but missing" % rel)
        elif sha256(full) != entry["sha256"] or os.path.getsize(full) != entry["bytes"]:
            fail("manifest.json: %s hash or size is stale (run --write-manifest)" % rel)

    catalog = load(os.path.join(V1, "catalog.json"))
    check_schema(catalog, "catalog", "catalog.json")
    countries = load(os.path.join(V1, "countries.json"))
    check_schema(countries, "countries", "countries.json")
    subs = load(os.path.join(V1, "subscriptions.json"))
    check_schema(subs, "subscriptions", "subscriptions.json")

    pack_codes = unique(countries["packs"], "code", "countries.json")
    parents = {(p["kind"], p["key"]) for p in catalog["parents"]}
    unique(catalog["parents"], "key", "catalog.json parents")
    preset_ids = unique(catalog["presets"], "id", "catalog.json")
    for p in catalog["presets"]:
        label = "catalog.json %s" % p["id"]
        if not p["id"].startswith(p["kind"] + "."):
            fail("%s: id must start with its kind" % label)
        if p["id"].split(".")[1] != p["parent"]:
            fail("%s: id's middle part must be its parent %r" % (label, p["parent"]))
        if (p["kind"], p["parent"]) not in parents:
            fail("%s: unknown parent %r" % (label, p["parent"]))
        if not is_emoji(p["emoji"]):
            fail("%s: emoji missing" % label)
        for code in list(p.get("localNames", {})) + p["countries"]["include"] + p["countries"]["exclude"]:
            if code not in pack_codes:
                fail("%s: unknown country %s" % (label, code))
    for parent in catalog["parents"]:
        if not is_emoji(parent["emoji"]):
            fail("catalog.json parent %s: emoji missing" % parent["key"])

    unique(subs["services"], "id", "subscriptions.json")
    for s in subs["services"]:
        if s["categoryId"] not in preset_ids:
            fail("subscriptions.json %s: unknown category %s" % (s["id"], s["categoryId"]))
        if not is_emoji(s["emoji"]):
            fail("subscriptions.json %s: emoji missing" % s["id"])
        for code in s["countries"]["include"] + s["countries"]["exclude"]:
            if code not in pack_codes:
                fail("subscriptions.json %s: unknown country %s" % (s["id"], code))

    tables = {}
    for rel in feed_files():
        if rel.startswith("tax/"):
            table = load(os.path.join(V1, rel))
            label = rel
            check_schema(table, "tax", label)
            if rel != "tax/%s.json" % table.get("id"):
                fail("%s: file name must match id %s" % (label, table.get("id")))
            tables[table["id"]] = table
            if not table["verified"] and not table.get("unverifiedItems"):
                fail("%s: unverified tables must list unverifiedItems" % label)
            if table["verified"] and table.get("unverifiedItems"):
                fail("%s: verified tables can't have unverifiedItems" % label)
            for sample in table["samples"]:
                got = tax_reference.estimate(table, sample["gross"])
                for key in ("incomeTax", "levies", "socialContributions", "net"):
                    if got[key] != tax_reference.D(sample[key]):
                        fail("%s: sample %s %s is %s, reference gives %s" % (label, sample["gross"], key, sample[key], got[key]))
            for sample in table.get("studentLoanSamples", []):
                got = tax_reference.student_loan(table, sample["plan"], sample["income"])
                if got != tax_reference.D(sample["repayment"]):
                    fail("%s: student loan sample %s is %s, reference gives %s" % (label, sample["income"], sample["repayment"], got))

    for pack in countries["packs"]:
        label = "countries.json %s" % pack["code"]
        if not is_emoji(pack["flag"]):
            fail("%s: flag missing" % label)
        for pid in pack["featuredExpenses"] + pack["featuredIncome"] + pack.get("featuredSavings", []):
            if pid not in preset_ids:
                fail("%s: unknown featured preset %s" % (label, pid))
        for tid in pack["taxTables"]:
            if tid not in tables:
                fail("%s: unknown tax table %s" % (label, tid))
            elif tables[tid]["country"] != pack["code"]:
                fail("%s: tax table %s is for %s" % (label, tid, tables[tid]["country"]))
        if pack["taxEstimator"] in ("full", "federal", "simplified") and not pack["taxTables"]:
            fail("%s: estimator %s needs tax tables" % (label, pack["taxEstimator"]))

    if errors:
        for message in errors:
            print("FAIL " + message)
        print("%d problem(s)" % len(errors))
        return 1
    print("OK: %d presets, %d subscriptions, %d country packs, %d tax tables, %d files hashed"
          % (len(catalog["presets"]), len(subs["services"]), len(countries["packs"]), len(tables), len(listed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
