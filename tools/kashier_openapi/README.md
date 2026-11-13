# Kashier API client generator

Generates `payment_kashier_cf/kashier_api.py`, the typed client of the Kashier payment API, from Kashier's
OpenAPI document. Standard library only; it is not part of any module and is never installed in Odoo.

```bash
python3 -I tools/kashier_openapi/generate.py            # (re)write payment_kashier_cf/kashier_api.py
python3 -I tools/kashier_openapi/generate.py --check    # exit 1 if the committed client is stale
python3 -I -m unittest discover -s tools/kashier_openapi/tests
```

| File | What it is |
|---|---|
| `spec.lock.json` | The pinned document: URL, download date, sha256, size. Kashier's document is proprietary, so only this lock is committed. |
| `.cache/` | The downloaded document (git-ignored). `generate.py` downloads it when missing and refuses any content whose sha256 differs from the lock. |
| `overlay.json` | The payment operations to generate, with the host (`dashboard` = `test-api`/`api`, `fep` = `test-fep`/`fep`) and the authentication each must use; the generator stops if the document says otherwise. Also the excluded operations with the reason. |
| `mini_yaml.py` | A strict reader for the YAML subset OpenAPI documents use (YAML 1.2 core scalars; timestamps stay strings; anchors, tags and several documents are refused). The tests cross-check it with PyYAML when PyYAML is installed. |
| `generate.py` | Builds TypedDicts for the request and response bodies and `KashierClient`, one method per operation, which calls `payment.provider._send_api_request`. |

The output copies no text from the document: docstrings only state the method, path, host and authentication.

## Updating to a new version of the document

1. Download it to `.cache/` under a new name and review the changes to the payment operations.
2. Update `spec.lock.json` (date, sha256, bytes, cache file) and, if needed, `overlay.json`.
3. Run `generate.py`, the generator tests and the module tests (`--test-tags /payment_kashier_cf`).
