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
"""Kashier's signatures, amounts and references. Pure functions, tested with Kashier's documented examples."""

import hashlib
import hmac
import json
import re
from urllib.parse import quote, urlsplit

from odoo.addons.payment_kashier_cf import const


class UnsignableValue(ValueError):
    """A signed webhook field holds a value whose signed form Kashier doesn't document."""


# === Signatures === #

def hmac_hex(key, message):
    """HMAC-SHA256 of the message with the Payment API Key, as lowercase hex."""
    return hmac.new(key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def same_signature(received, expected):
    """Compare two hex signatures in constant time, ignoring the case."""
    return bool(received) and hmac.compare_digest(str(received).lower(), str(expected).lower())


def order_hash_string(merchant_id, reference, amount, currency, customer_reference=None):
    """The string Kashier signs for a payment (`Kashier-Hash` header): `/?payment=mid.ref.amount.cur`.

    Payments with a saved card add `.customerReference`. Parts are joined with dots and not encoded.
    """
    string = f"/?payment={merchant_id}.{reference}.{amount}.{currency}"
    return f"{string}.{customer_reference}" if customer_reference else string


def tokenization_hash_string(merchant_id, customer_reference):
    """The string Kashier signs to list, read or delete a customer's saved cards."""
    return f"/?tokenization={merchant_id}.{customer_reference}"


def redirect_signing_string(params):
    """The string Kashier signs on the return to the merchant: the fixed fields in order, `k=v` joined
    with `&`, with the decoded values and the literal `null` for a missing field.
    """
    return "&".join(f"{field}={params.get(field, 'null')}" for field in const.REDIRECT_SIGNED_FIELDS)


def webhook_signing_string(data):
    """The string Kashier signs in a webhook: the keys listed in `data.signatureKeys`, sorted, each
    value URL-encoded (RFC 3986), `k=v` joined with `&`.

    `data` must come from `loads_keeping_numbers`, so that numbers are signed as Kashier wrote them.

    :raise UnsignableValue: If a signed key is missing or holds an object, a list or null.
    """
    keys = data.get("signatureKeys")
    if not isinstance(keys, list) or not keys:
        message = "no signatureKeys"
        raise UnsignableValue(message)
    pairs = []
    for key in sorted(str(key) for key in keys):
        if key not in data:
            raise UnsignableValue(f"missing signed key {key}")
        value = data[key]
        if isinstance(value, bool):
            value = "true" if value else "false"
        elif value is None or isinstance(value, (dict, list)):
            raise UnsignableValue(f"signed key {key} holds {type(value).__name__}")
        pairs.append(f"{key}={quote(str(value), safe='')}")
    return "&".join(pairs)


def loads_keeping_numbers(raw):
    """Parse a JSON body keeping every number as the text Kashier sent (`1`, `100.5`, `1e+16`)."""
    return json.loads(raw, parse_int=str, parse_float=str)


# === Amounts and references === #

def format_amount(amount):
    """The amount as Kashier takes it in sessions and payments: a string with two decimals."""
    return f"{amount:.2f}"


def to_number(value):
    """Kashier's amounts are numbers in answers (and strings in some): return a float, or None."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_order_reference(reference, database_code, nonce):
    """The `order` sent to Kashier: the cleaned Odoo reference, a database code and a nonce.

    Kashier refuses an `order` it already knows (ERR_ORD_02): the code separates databases sharing one
    merchant account, and the nonce lets a transaction try again after a rolled-back attempt.
    """
    prefix = re.sub(const.ORDER_REF_ALLOWED, "-", reference)[: const.ORDER_REF_MAX_PREFIX].strip("-") or "tx"
    return f"{prefix}-{database_code}{nonce}"


def is_checkout_url(url):
    """Whether the URL is Kashier's hosted payment page (never redirect a customer elsewhere)."""
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return False
    return parts.scheme == "https" and parts.hostname == const.CHECKOUT_HOST and not parts.username


# === Errors === #

def message_of(body):
    """A readable message from one of Kashier's error bodies (they come in several shapes)."""
    if isinstance(body, str):
        return body.strip()[:500]
    if not isinstance(body, dict):
        return ""
    messages = body.get("messages")
    if isinstance(messages, dict) and messages.get("en"):
        return str(messages["en"])
    for key in ("message", "error"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            cause = value.get("cause") or value.get("message")
            if cause:
                return str(cause)
    if isinstance(body.get("more_info"), list):
        return "; ".join(str(item.get("message", item)) if isinstance(item, dict) else str(item)
                         for item in body["more_info"])[:500]
    response = body.get("response")
    if isinstance(response, dict):
        message = response.get("transactionResponseMessage")
        if isinstance(message, dict) and message.get("en"):
            return str(message["en"])
    return ""


def code_of(body):
    """The response code in one of Kashier's error bodies, if any."""
    if not isinstance(body, dict):
        return None
    response = body.get("response")
    if isinstance(response, dict) and response.get("transactionResponseCode"):
        return str(response["transactionResponseCode"])
    for key in ("transactionResponseCode", "code", "errorCode"):
        if body.get(key):
            return str(body[key])
    error = body.get("error")
    if isinstance(error, dict) and error.get("code"):
        return str(error["code"])
    return None


def classify_error(status, body):
    """Return the `const.ERROR_CODES` key of an error answer, or None.

    :param int status: The HTTP status.
    :param body: The decoded body (dict) or its text.
    """
    code = code_of(body)
    if code and code in const.ERROR_CODES:
        return code
    text = (message_of(body) or "").lower()
    if status == 401 or "invalid secret key" in text or "invalid token" in text:
        return "permission" if "permission" in text else "credentials"
    if status == 403:
        if "ip" in text and "unauthorized" in text:
            return "ip_not_allowed"
        if "hash" in text:
            return "INVALID_HASH_CHECK"
        if "not live" in text:
            return "not_live"
        return "credentials"
    if "api key mismatch" in text or "invalid merchantid" in text:
        return "credentials"
    if "not live" in text:
        return "not_live"
    if "cannot be refunded" in text or "cannot refund" in text:
        return "over_refund"
    if "authorization request not permitted" in text:
        return "capture_disabled"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    if status and status >= 500:
        return "server_error"
    if code:
        return code
    return "bad_request" if status and status >= 400 else None
