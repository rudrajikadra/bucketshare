# BucketShare presets feed

The public feed behind the BucketShare app: categories, subscription services, country packs and tax tables. It holds no user data and no app code. The app ships a copy of these files and reads this feed on GitHub Pages at most once a day, so presets can change without an app update.

```text
v1/
  manifest.json        version, updatedAt, minAppVersion, files[] with sha256 and size
  catalog.json         income, expense, savings, investing and transfer presets
  subscriptions.json   subscription services (text and emoji only, no logos)
  countries.json       country packs: currency, financial year, pay frequency, terms, featured presets, tax tables
  tax/<ID>.json        one tax table per country (and variant) per year
schema/*.schema.json   JSON Schema (draft-07) for every file
scripts/validate.py    schema, unique IDs, emoji, cross references, hashes, tax samples
scripts/tax_reference.py  reference tax calculator used to check every sample
```

## Rules

- **IDs are forever.** Never reuse or rename a preset, service, pack or table ID. To retire one, add `"deprecated": true`. Apps keep the user's own copy of any category they adopted, so removing or renaming a preset never changes their data.
- **Unknown fields are ignored** by the app, so you can add fields. Changing the meaning of an existing field needs a new `v2/` folder.
- `localNames` keys are country pack codes (ISO 3166 alpha-2, plus `INTL`). A name missing for a country falls back to `name`.
- **Tax tables** record `source`, `sources` and `verifiedAt`. Set `"verified": false` and list `unverifiedItems` for any figure you couldn't check on an official site; the app then shows "unverified" beside "Estimate only". Every table has at least 3 samples, and `validate.py` recomputes them.
- A file that needs a newer app gets `"minAppVersion"` on its manifest entry; older apps keep their current copy of that file.

## Edit and publish

1. Edit the JSON under `v1/`.
2. Run `python3 scripts/validate.py --write-manifest` (Python 3.9+, `pip3 install --user jsonschema`). It refreshes the hashes and `updatedAt`, then checks everything. Fix every `FAIL` line.
3. Bump `version` in `v1/manifest.json`.
4. Commit and push to `main`. GitHub Pages serves it within a minute or two, and apps pick it up within 24 hours.

## First-time publishing (owner)

The feed lives in the `presets/` folder of the public site repository `rudrajikadra/bucketshare`, next to the app's public pages (privacy policy, terms, support).

1. Copy **only** the contents of the app project's `presets/` folder into `presets/` of a clean clone of the public repository (never push from the app repository).
2. Settings → Pages: deploy from the `main` branch, root folder.
3. Check that `https://rudrajikadra.github.io/bucketshare/presets/v1/manifest.json` opens in a browser.
