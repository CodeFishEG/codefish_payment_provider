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
"""Generate payment_kashier_cf/kashier_api.py, the typed Kashier client, from Kashier's OpenAPI document.

Standard library only. Run from the repository root:

    python3 -I tools/kashier_openapi/generate.py            # write the client
    python3 -I tools/kashier_openapi/generate.py --check    # exit 1 if the committed client is stale

The document is pinned in spec.lock.json (sha256). It is downloaded into .cache/ (git-ignored, the document
is proprietary) and refused if its content differs. Only the operations listed in overlay.json are
generated, each with the host and authentication the overlay expects; the generator stops if the
document says otherwise. No text from the document is copied into the output.
"""

import argparse
import hashlib
import json
import keyword
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import mini_yaml  # noqa: E402

REPO = HERE.parent.parent
DEFAULT_OUTPUT = REPO / "payment_kashier_cf" / "kashier_api.py"
HEADER = '''#################################################################################
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
'''
AUTH_LABELS = {
    "secret": "Secret Key",
    "secret+apikey": "Secret Key and Payment API Key",
    "hash": "Kashier-Hash header",
    "none": "no credential",
}
MAX_LITERAL_VALUES = 40


class GenerationError(Exception):
    pass


# === Spec loading === #

def load_spec(lock_path, spec_path=None, download=True):
    """Return the parsed document after checking it against the lock.

    :param Path lock_path: spec.lock.json.
    :param Path spec_path: A local copy to use instead of the cache.
    :param bool download: Whether to download the document when the cache is empty.
    """
    lock = json.loads(lock_path.read_text())
    path = spec_path or (lock_path.parent / lock["cache_file"])
    if not path.exists():
        if not download:
            raise GenerationError(f"{path} is missing; run without --no-download to fetch it")
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(lock["url"], timeout=60) as response:  # noqa: S310 (pinned https url)
            path.write_bytes(response.read())
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if spec_path is None and (digest != lock["sha256"] or len(raw) != lock["bytes"]):
        raise GenerationError(
            f"{path} does not match spec.lock.json (sha256 {digest}, {len(raw)} bytes). Review the new "
            "document, then update the lock deliberately.",
        )
    return mini_yaml.loads(raw.decode("utf-8")), digest, lock


# === Names === #

def snake(name):
    name = re.sub(r"[^0-9A-Za-z]+", "_", name)
    name = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name).lower().strip("_")
    if not name or name[0].isdigit():
        name = "p_" + name
    return name + "_" if keyword.iskeyword(name) else name


def pascal(name):
    parts = re.split(r"[^0-9A-Za-z]+", name)
    result = "".join(part[:1].upper() + part[1:] for part in parts if part)
    return result if result and not result[0].isdigit() else "T" + result


# === Types === #

class TypeBuilder:
    """Turn JSON schemas into Python type expressions and TypedDict definitions."""

    def __init__(self, spec):
        self.spec = spec
        self.definitions = {}  # class name -> source
        self.order = []
        self.in_progress = set()
        self.by_ref = {}

    def resolve(self, schema):
        seen = set()
        while isinstance(schema, dict) and "$ref" in schema:
            ref = schema["$ref"]
            if ref in seen or not ref.startswith("#/components/"):
                raise GenerationError(f"unsupported reference {ref}")
            seen.add(ref)
            _hash, _components, section, name = ref.split("/", 3)
            schema = self.spec["components"][section][name]
        return schema

    def type_of(self, schema, hint):
        if not isinstance(schema, dict) or not schema:
            return "Any"
        if "$ref" in schema:
            ref = schema["$ref"]
            target = self.resolve(schema)
            if self._is_object(target):
                return self._named_object(ref, target)
            return self.type_of(target, pascal(ref.rsplit("/", 1)[-1]))
        nullable = bool(schema.get("nullable"))
        for combiner in ("oneOf", "anyOf"):
            if combiner in schema:
                members = [self.type_of(member, f"{hint}{index}") for index, member in enumerate(schema[combiner], 1)]
                return self._optional(self._union(members), nullable)
        if "allOf" in schema:
            return self._optional(self._object(self._merge(schema["allOf"]), hint), nullable)
        if "const" in schema:
            return f"Literal[{schema['const']!r}]"
        kind = schema.get("type")
        if isinstance(kind, list):
            nullable = nullable or "null" in kind
            kinds = [k for k in kind if k != "null"]
            expression = self._union([self.type_of({**schema, "type": k}, hint) for k in kinds]) if kinds else "None"
            return self._optional(expression, nullable)
        if "enum" in schema and kind in (None, "string") and all(isinstance(v, str) for v in schema["enum"]):
            values = [v for v in schema["enum"] if v is not None]
            if 0 < len(values) <= MAX_LITERAL_VALUES:
                return self._optional("Literal[" + ", ".join(repr(v) for v in values) + "]", nullable)
        scalar = {"string": "str", "integer": "int", "number": "float", "boolean": "bool", "null": "None"}
        if kind in scalar:
            expression = scalar[kind]
            if kind == "number":
                expression = "int | float"
            return self._optional(expression, nullable)
        if kind == "array":
            return self._optional(f"list[{self.type_of(schema.get('items', {}), hint + 'Item')}]", nullable)
        if self._is_object(schema):
            return self._optional(self._object(schema, hint), nullable)
        return "Any"

    def _is_object(self, schema):
        return isinstance(schema, dict) and (
            schema.get("type") == "object" or "properties" in schema or "allOf" in schema
        )

    def _optional(self, expression, nullable):
        return f"{expression} | None" if nullable and expression not in ("Any", "None") else expression

    def _union(self, members):
        unique = []
        for member in members:
            for part in member.split(" | "):
                if part not in unique:
                    unique.append(part)
        if "Any" in unique:
            return "Any"
        return " | ".join(unique)

    def _merge(self, schemas):
        merged = {"type": "object", "properties": {}, "required": []}
        for part in schemas:
            part = self.resolve(part)
            if "allOf" in part:
                part = self._merge(part["allOf"])
            merged["properties"].update(part.get("properties") or {})
            merged["required"] += list(part.get("required") or [])
        return merged

    def _named_object(self, ref, schema):
        if ref in self.by_ref:
            return self.by_ref[ref]
        name = self._unique(pascal(ref.rsplit("/", 1)[-1]))
        self.by_ref[ref] = name
        self._define(name, schema)
        return name

    def _object(self, schema, hint):
        if not schema.get("properties") and "allOf" not in schema:
            extra = schema.get("additionalProperties")
            value = self.type_of(extra, hint + "Value") if isinstance(extra, dict) else "Any"
            return f"dict[str, {value}]"
        if "allOf" in schema:
            schema = self._merge(schema["allOf"])
        name = self._unique(pascal(hint))
        self._define(name, schema)
        return name

    def _unique(self, name):
        candidate, counter = name, 2
        while candidate in self.definitions or candidate in self.in_progress:
            candidate = f"{name}{counter}"
            counter += 1
        return candidate

    def _define(self, name, schema):
        self.in_progress.add(name)
        required = set(schema.get("required") or [])
        fields = []
        for key, sub in (schema.get("properties") or {}).items():
            expression = self.type_of(sub, name + pascal(key))
            if key in required:
                expression = f"Required[{expression}]"
            fields.append((key, expression))
        self.in_progress.discard(name)
        if any(not key.isidentifier() or keyword.iskeyword(key) for key, _ in fields):
            body = ", ".join(f"{key!r}: {expression}" for key, expression in fields)
            source = f"{name} = TypedDict({name!r}, {{{body}}}, total=False)\n"
        else:
            lines = [f"class {name}(TypedDict, total=False):"]
            lines += [f"    {key}: {expression}" for key, expression in fields] or ["    pass"]
            source = "\n".join(lines) + "\n"
        self.definitions[name] = source
        self.order.append(name)


# === Operations === #

def collect_operations(spec, overlay):
    found = {}
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            if not isinstance(operation, dict) or "operationId" not in operation:
                continue
            if operation["operationId"] in overlay["operations"]:
                found[operation["operationId"]] = (method.upper(), path, item, operation)
    missing = set(overlay["operations"]) - set(found)
    if missing:
        raise GenerationError(f"operations missing from the document: {sorted(missing)}")
    for excluded in overlay["excluded"]:
        if excluded in found:
            raise GenerationError(f"{excluded} is both allowed and excluded")
    return found


def host_kind(spec, item, operation, hosts):
    servers = operation.get("servers") or item.get("servers") or spec.get("servers") or []
    urls = {server["url"].rstrip("/") for server in servers}
    for kind, by_mode in hosts.items():
        if urls & set(by_mode.values()):
            return kind
    raise GenerationError(f"unknown servers {sorted(urls)}")


def auth_kind(spec, operation, parameters):
    security = operation.get("security", spec.get("security", []))
    schemes = set()
    for requirement in security or []:
        schemes |= set(requirement)
    has_hash = any(parameter.get("in") == "header" and parameter.get("name") == "Kashier-Hash" for parameter in parameters)
    if schemes == {"secretKey", "apiKey"}:
        return "secret+apikey"
    if schemes == {"secretKey"}:
        return "secret"
    if not schemes:
        return "hash" if has_hash else "none"
    raise GenerationError(f"unsupported security {security}")


def success_schema(builder, operation):
    for code in sorted(operation.get("responses") or {}):
        if not str(code).startswith("2"):
            continue
        response = builder.resolve(operation["responses"][code])
        content = (response.get("content") or {}).get("application/json")
        if content and content.get("schema"):
            return content["schema"]
    return None


def build(spec, overlay, digest, lock):
    builder = TypeBuilder(spec)
    operations = collect_operations(spec, overlay)
    table = {}
    methods = []
    for operation_id in overlay["operations"]:
        method, path, item, operation = operations[operation_id]
        parameters = [builder.resolve(parameter) for parameter in (item.get("parameters") or []) + (operation.get("parameters") or [])]
        host = host_kind(spec, item, operation, overlay["hosts"])
        auth = auth_kind(spec, operation, parameters)
        expected = overlay["operations"][operation_id]
        if (host, auth) != (expected["host"], expected["auth"]):
            raise GenerationError(f"{operation_id}: document says {host}/{auth}, overlay expects {expected['host']}/{expected['auth']}")
        base = pascal(operation_id)
        request_type = None
        body = operation.get("requestBody")
        if body:
            content = (builder.resolve(body).get("content") or {}).get("application/json")
            if content and content.get("schema"):
                request_type = builder.type_of(content["schema"], base + "Request")
        schema = success_schema(builder, operation)
        response_type = builder.type_of(schema, base + "Response") if schema else "dict[str, Any]"
        path_params, query_params = [], []
        for parameter in parameters:
            if parameter.get("in") == "path":
                path_params.append(parameter["name"])
            elif parameter.get("in") == "query":
                query_params.append((parameter["name"], bool(parameter.get("required")),
                                     builder.type_of(parameter.get("schema", {}), base + pascal(parameter["name"]))))
        table[operation_id] = {
            "method": method, "path": path, "host": host, "auth": auth,
            "path_params": {snake(name): name for name in path_params},
            "query": {snake(name): name for name, _required, _type in query_params},
        }
        methods.append(render_method(operation_id, method, path, host, auth, path_params, query_params,
                                     request_type, response_type))
    return render_module(builder, table, methods, digest, lock)


def render_method(operation_id, method, path, host, auth, path_params, query_params, request_type, response_type):
    arguments = ["self"]
    arguments += [f"{snake(name)}: str" for name in path_params]
    if request_type:
        arguments.append(f"body: {request_type}")
    keyword_only = []
    if auth == "hash":
        keyword_only.append("kashier_hash: str")
    for name, required, expression in query_params:
        if required:
            keyword_only.append(f"{snake(name)}: {expression}")
    for name, required, expression in query_params:
        if not required:
            keyword_only.append(f"{snake(name)}: {expression} | None = None")
    keyword_only.append("reference: str | None = None")
    signature = ", ".join(arguments) + ", *, " + ", ".join(keyword_only)
    call = [f"{operation_id!r}"]
    if path_params:
        call.append("path_params={" + ", ".join(f"{snake(n)!r}: {snake(n)}" for n in path_params) + "}")
    if query_params:
        call.append("query={" + ", ".join(f"{snake(n)!r}: {snake(n)}" for n, _r, _t in query_params) + "}")
    if request_type:
        call.append("body=body")
    if auth == "hash":
        call.append("kashier_hash=kashier_hash")
    call.append("reference=reference")
    host_label = "Dashboard API" if host == "dashboard" else "payment (FEP) API"
    return (
        f"    def {snake(operation_id)}({signature}) -> {response_type}:\n"
        f'        """{method} {path} on the {host_label}; authentication: {AUTH_LABELS[auth]}."""\n'
        f"        return self._request({', '.join(call)})\n"
    )


def render_module(builder, table, methods, digest, lock):
    """The source of kashier_api.py, laid out as ruff (pycodestyle) expects."""
    preamble = HEADER + f'''"""Typed client for Kashier's payment API.

GENERATED by tools/kashier_openapi/generate.py from Kashier's OpenAPI document ({lock["downloaded"]},
sha256 {digest[:16]}...). Do not edit by hand: change the generator or overlay.json and run it again.

Request and response types are TypedDicts (total=False; `Required` marks the fields the document requires).
Every call goes through `payment.provider._send_api_request` with `kashier_cf_host` (dashboard or fep) and
`kashier_cf_auth` (secret, secret+apikey, hash or none); the provider builds the URL and the headers.
"""

from typing import Any, Literal, Required, TypedDict
from urllib.parse import quote

SPEC_SHA256 = {digest!r}
'''
    client = '''class KashierClient:
    """One method per Kashier payment operation, bound to a `payment.provider` record."""

    def __init__(self, provider):
        self._provider = provider

    def _request(self, operation_id, *, path_params=None, query=None, body=None, kashier_hash=None, reference=None):
        operation = OPERATIONS[operation_id]
        path = operation["path"]
        for argument, name in operation["path_params"].items():
            path = path.replace("{" + name + "}", quote(str((path_params or {})[argument]), safe=""))
        params = {
            operation["query"][argument]: value
            for argument, value in (query or {}).items()
            if value is not None
        }
        return self._provider._send_api_request(
            operation["method"],
            path,
            params=params or None,
            json=body,
            reference=reference,
            kashier_cf_host=operation["host"],
            kashier_cf_auth=operation["auth"],
            kashier_cf_hash=kashier_hash,
        )
'''
    top_level = "\n\n\n".join(builder.definitions[name].strip() for name in builder.order)
    body = "\n".join(method.rstrip() + "\n" for method in methods)
    return (
        preamble.rstrip() + "\n\n\n# === Types === #\n\n\n"
        + top_level + "\n\n\n# === Operations === #\n\n"
        + "OPERATIONS = " + _pretty(table).rstrip() + "\n\n\n"
        + client + "\n" + body
    )


def _pretty(value, indent=0):
    """Repr of the operations table, one operation per line block, stable for diffs."""
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        if all(not isinstance(v, dict) for v in value.values()):
            return "{" + ", ".join(f"{k!r}: {v!r}" for k, v in value.items()) + "}"
        inner = ",\n".join(f"{pad}    {k!r}: {_pretty(v, indent + 4)}" for k, v in value.items())
        return "{\n" + inner + f",\n{pad}}}"
    return repr(value)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--spec", type=Path, help="a local copy of the document (skips the lock check)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="fail if the output file is not up to date")
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args(argv)
    try:
        spec, digest, lock = load_spec(HERE / "spec.lock.json", args.spec, download=not args.no_download)
        overlay = json.loads((HERE / "overlay.json").read_text())
        source = build(spec, overlay, digest, lock)
        compile(source, str(args.output), "exec")
    except (GenerationError, mini_yaml.YamlError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.check:
        current = args.output.read_text() if args.output.exists() else ""
        if current != source:
            print(f"{args.output} is out of date: run tools/kashier_openapi/generate.py", file=sys.stderr)
            return 1
        print(f"{args.output} is up to date")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(source)
    print(f"wrote {args.output} ({len(source.splitlines())} lines, {len(table_of(source))} operations)")
    return 0


def table_of(source):
    return [n for n in re.findall(r"^    def (\w+)\(self", source, flags=re.M) if not n.startswith("_")]


if __name__ == "__main__":
    sys.exit(main())
