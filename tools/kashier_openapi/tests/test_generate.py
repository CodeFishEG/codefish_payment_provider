#################################################################################
# Author      : mediafish(<https://www.mediafish.agency>)
# Copyright(c): 2010-Present mediafish
# All Rights Reserved.
#
#
#
# This program is copyright property of the author mentioned above.
# You can`t redistribute it and/or modify it.
#
#
# You should have received a copy of the License along with this program.
# If not, see <https://www.mediafish.agency/license.html/>
#################################################################################
"""Tests of generate.py. Run: python3 -I -m unittest discover -s tools/kashier_openapi/tests"""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import generate  # noqa: E402
import mini_yaml  # noqa: E402

MINI_SPEC = """
openapi: 3.1.0
servers:
  - url: https://test-api.kashier.io
security:
  - secretKey: []
paths:
  /v3/things/{thingId}:
    put:
      operationId: updateThing
      servers:
        - url: https://test-fep.kashier.io
      parameters:
        - name: thingId
          in: path
          required: true
          schema: {type: string}
        - name: pageSize
          in: query
          schema: {type: integer}
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Thing'
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  status: {type: string, enum: [SUCCESS, FAILURE]}
                  amount:
                    anyOf: [{type: string}, {type: number}]
  /v3/hidden:
    get:
      operationId: hiddenThing
      security: []
      responses: {}
components:
  schemas:
    Thing:
      type: object
      required: [amount]
      properties:
        amount: {type: string}
        note: {type: [string, "null"]}
        tags:
          type: array
          items: {type: string}
"""
MINI_OVERLAY = {
    "operations": {"updateThing": {"host": "fep", "auth": "secret"}},
    "excluded": {"hiddenThing": "test"},
    "hosts": {
        "dashboard": {"test": "https://test-api.kashier.io", "live": "https://api.kashier.io"},
        "fep": {"test": "https://test-fep.kashier.io", "live": "https://fep.kashier.io"},
    },
}
LOCK = {"downloaded": "2026-11-13"}


class TestGenerate(unittest.TestCase):

    def _build(self, overlay=MINI_OVERLAY):
        return generate.build(mini_yaml.loads(MINI_SPEC), overlay, "0" * 64, LOCK)

    def test_types_and_method(self):
        source = self._build()
        compile(source, "kashier_api.py", "exec")
        self.assertIn("class Thing(TypedDict, total=False):", source)
        self.assertIn("    amount: Required[str]", source)
        self.assertIn("    note: str | None", source)
        self.assertIn("    tags: list[str]", source)
        self.assertIn("    status: Literal['SUCCESS', 'FAILURE']", source)
        self.assertIn("    amount: str | int | float", source)
        self.assertIn(
            "def update_thing(self, thing_id: str, body: Thing, *, page_size: int | None = None, "
            "reference: str | None = None)", source,
        )
        self.assertNotIn("hidden", source.lower().replace("hidden by hand", ""))

    def test_client_routes_through_the_provider(self):
        namespace = {}
        exec(compile(self._build(), "kashier_api.py", "exec"), namespace)  # noqa: S102 (generated test code)
        calls = []

        class Provider:
            def _send_api_request(self, *args, **kwargs):
                calls.append((args, kwargs))
                return {"status": "SUCCESS"}

        client = namespace["KashierClient"](Provider())
        client.update_thing("a/b", {"amount": "1"}, page_size=3, reference="S1")
        (method, path), kwargs = calls[0]
        self.assertEqual((method, path), ("PUT", "/v3/things/a%2Fb"))
        self.assertEqual(kwargs["params"], {"pageSize": 3})
        self.assertEqual((kwargs["kashier_cf_host"], kwargs["kashier_cf_auth"]), ("fep", "secret"))
        self.assertEqual(kwargs["reference"], "S1")

    def test_overlay_must_match_the_document(self):
        overlay = json.loads(json.dumps(MINI_OVERLAY))
        overlay["operations"]["updateThing"]["host"] = "dashboard"
        with self.assertRaises(generate.GenerationError):
            self._build(overlay)

    def test_no_text_from_the_document(self):
        spec = mini_yaml.loads(MINI_SPEC)
        spec["paths"]["/v3/things/{thingId}"]["put"]["description"] = "UNIQUE-PROSE-MARKER"
        spec["components"]["schemas"]["Thing"]["description"] = "UNIQUE-PROSE-MARKER"
        self.assertNotIn("UNIQUE-PROSE-MARKER", generate.build(spec, MINI_OVERLAY, "0" * 64, LOCK))


class TestCommittedClient(unittest.TestCase):

    def test_up_to_date(self):
        lock = json.loads((HERE / "spec.lock.json").read_text())
        if not (HERE / lock["cache_file"]).exists():
            self.skipTest("the pinned document is not in .cache/")
        self.assertEqual(generate.main(["--check", "--no-download"]), 0)

    def test_excluded_operations_are_absent(self):
        source = generate.DEFAULT_OUTPUT.read_text()
        self.assertNotIn("def create_token(", source)
        self.assertNotIn("getPaymentSessionById", source)
        self.assertEqual(source.count("\n    def ") - 2, 19)  # __init__ and _request


if __name__ == "__main__":
    unittest.main()
