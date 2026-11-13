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
"""Tests of mini_yaml. Run: python3 -I -m unittest discover -s tools/kashier_openapi/tests"""

import json
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import mini_yaml  # noqa: E402

try:
    import yaml
except ImportError:  # PyYAML is only an optional cross-check.
    yaml = None


class TestMiniYaml(unittest.TestCase):

    def test_scalars(self):
        doc = mini_yaml.loads(
            "a: 1\nb: -2.5\nc: true\nd: null\ne: ~\nf: yes\ng: 2030-01-01T00:00:00.000Z\nh: '0042'\n"
            "i: \"tab\\tend\"\nj: it's\nk: 0x1F\n",
        )
        self.assertEqual(doc, {
            "a": 1, "b": -2.5, "c": True, "d": None, "e": None, "f": "yes",
            "g": "2030-01-01T00:00:00.000Z", "h": "0042", "i": "tab\tend", "j": "it's", "k": 31,
        })

    def test_nesting_and_sequences(self):
        doc = mini_yaml.loads(
            "paths:\n  /x:\n    get:\n      security:\n        - secretKey: []\n          apiKey: []\n"
            "      tags:\n      - One\n      - 'Two'\n",
        )
        self.assertEqual(doc, {"paths": {"/x": {"get": {
            "security": [{"secretKey": [], "apiKey": []}], "tags": ["One", "Two"],
        }}}})

    def test_flow_collections(self):
        doc = mini_yaml.loads('a: [x, "y z", 3]\nb: {k: v, n: [1, 2]}\nc: [string, "null"]\n')
        self.assertEqual(doc, {"a": ["x", "y z", 3], "b": {"k": "v", "n": [1, 2]}, "c": ["string", "null"]})

    def test_block_scalars(self):
        doc = mini_yaml.loads(
            "lit: |\n  one\n  two\n\nfold: >-\n  one\n  two\n\n  three\nstrip: |-\n  x\nkeep: |+\n  y\n\n"
            "after: 1\n",
        )
        self.assertEqual(doc["lit"], "one\ntwo\n")
        self.assertEqual(doc["fold"], "one two\nthree")
        self.assertEqual(doc["strip"], "x")
        self.assertEqual(doc["keep"], "y\n\n")
        self.assertEqual(doc["after"], 1)

    def test_multiline_plain_and_comments(self):
        doc = mini_yaml.loads("a: first\n  second  # comment\n# full line\nb: '# not a comment'\n")
        self.assertEqual(doc, {"a": "first second", "b": "# not a comment"})

    def test_quoted_keys(self):
        self.assertEqual(mini_yaml.loads("'200':\n  description: ok\n"), {"200": {"description": "ok"}})

    def test_refuses_unsupported(self):
        for source in ("a: &x 1\nb: *x\n", "--- \na: 1\n", "a: !tag 1\n", "? a\n: b\n", "a: 1\na: 2\n"):
            with self.subTest(source=source), self.assertRaises(mini_yaml.YamlError):
                mini_yaml.loads(source)


@unittest.skipIf(yaml is None, "PyYAML not installed")
class TestAgainstPyYaml(unittest.TestCase):
    """Cross-check with PyYAML set to the YAML 1.2 core schema (no timestamps)."""

    @classmethod
    def loader(cls):
        class Core12Loader(yaml.SafeLoader):
            pass

        Core12Loader.yaml_implicit_resolvers = {}
        resolvers = (
            ("null", r"^(?:~|null|Null|NULL|)$", list("~nN") + [""]),
            ("bool", r"^(?:true|True|TRUE|false|False|FALSE)$", list("tTfF")),
            ("int", r"^(?:[-+]?(?:0|[1-9][0-9]*)|0o[0-7]+|0x[0-9a-fA-F]+)$", list("-+0123456789")),
            ("float", r"^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?|[-+]?\.(?:inf|Inf|INF)"
                      r"|\.(?:nan|NaN|NAN))$", list("-+.0123456789")),
        )
        for name, regexp, first in resolvers:
            Core12Loader.add_implicit_resolver(f"tag:yaml.org,2002:{name}", re.compile(regexp), first)

        def construct_int(loader, node):
            value = loader.construct_scalar(node)
            return int(value[2:], 8) if value.startswith("0o") else int(value, 0 if value.startswith("0x") else 10)

        Core12Loader.add_constructor("tag:yaml.org,2002:int", construct_int)
        return Core12Loader

    def test_samples(self):
        for source in (
            "a: |\n  x\n\n  y\nb: >\n  p\n   q\n  r\n",
            "q: \"multi\n  line \\\n  joined\"\n",
            "s: 'it''s\n\n  ok'\n",
        ):
            with self.subTest(source=source):
                self.assertEqual(mini_yaml.loads(source), yaml.load(source, Loader=self.loader()))

    def test_pinned_spec(self):
        lock = json.loads((HERE / "spec.lock.json").read_text())
        path = HERE / lock["cache_file"]
        if not path.exists():
            self.skipTest("the pinned document is not in .cache/")
        source = path.read_text()
        self.assertEqual(mini_yaml.loads(source), yaml.load(source, Loader=self.loader()))


if __name__ == "__main__":
    unittest.main()
