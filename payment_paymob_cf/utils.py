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
import hashlib
import hmac
import re

from odoo.addons.payment_paymob_cf import const


def get_value(data, path):
    """Return the value at a dotted path of nested dicts, e.g. ``order.id``.

    :param dict data: The data.
    :param str path: The keys, separated by dots.
    :return: The value, or `None` if a key is missing.
    """
    value = data
    for key in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def is_true(value):
    """Return whether a flag of Paymob's data is set: a boolean, or "true" in a URL or an example."""
    return value is True or str(value).strip().lower() == "true"


def format_hmac_value(value):
    """Format a value the way Paymob concatenates it to compute the HMAC.

    Booleans are written in lowercase, as in JSON; missing and null values are left empty.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def get_transaction_hmac_string(data, is_redirection=False):
    """Return the string Paymob signs in a transaction callback.

    :param dict data: The transaction (`obj` of the POST callback), or the query parameters of the
                      redirection (GET), where the order is flattened to `order` or `order_id`.
    :param bool is_redirection: Whether the data come from the redirection.
    :return: The concatenated values.
    :rtype: str
    """
    values = []
    for key in const.TRANSACTION_HMAC_KEYS:
        if is_redirection:
            if key == "order.id":
                value = data.get("order") or data.get("order_id")
            else:
                value = data.get(key)
        else:
            value = get_value(data, key)
        values.append(format_hmac_value(value))
    return "".join(values)


def get_token_hmac_string(token_data):
    """Return the string Paymob signs in a card token callback.

    :param dict token_data: The card token (`obj` of the callback).
    :rtype: str
    """
    return "".join(format_hmac_value(token_data.get(key)) for key in const.TOKEN_HMAC_KEYS)


def compute_hmac(message, secret):
    """Return the HMAC-SHA512 of a message, as Paymob computes it (lowercase hexadecimal).

    :param str message: The concatenated values.
    :param str secret: The HMAC secret of the Paymob account.
    :rtype: str
    """
    return hmac.new(
        (secret or "").encode("utf-8"), message.encode("utf-8"), hashlib.sha512,
    ).hexdigest()


def redirection_to_transaction(params):
    """Turn the query parameters of Paymob's redirection into a transaction, as in the callbacks.

    :param dict params: The query parameters (strings, booleans as ``true``/``false``).
    :return: The transaction, with the order and the source nested and the booleans parsed.
    :rtype: dict
    """
    def parse(value):
        if value in ("true", "false"):
            return value == "true"
        return value

    transaction = {"order": {}, "source_data": {}, "data": {}}
    for key, value in params.items():
        if key == "hmac":
            continue
        value = parse(value)
        if key in ("order", "order_id"):
            transaction["order"]["id"] = value
        elif key.startswith(("source_data.", "data.")):
            group, name = key.split(".", 1)
            transaction[group][name] = value
        elif key in ("txn_response_code", "acq_response_code"):
            transaction["data"][key] = value
        else:
            transaction[key] = value
    return transaction


def normalize_code(code):
    """Normalize an acquirer or risk code: numeric codes lose their leading zeros ("05" -> "5").

    :param code: The code, as Paymob sent it.
    :return: The normalized code, or an empty string.
    :rtype: str
    """
    code = str(code or "").strip()
    if code.isdigit():
        return str(int(code))
    return code


def get_decline(transaction):
    """Return the code and the details of a declined transaction.

    The acquirer code is preferred; otherwise the code is guessed from Paymob's message, or the
    decline stays generic.

    :param dict transaction: The transaction sent by Paymob.
    :return: The code (a key of `const.ERROR_CODES` when known) and Paymob's message.
    :rtype: tuple[str, str]
    """
    data = transaction.get("data") if isinstance(transaction.get("data"), dict) else {}
    message = str(data.get("message") or "").strip()
    for key in ("acq_response_code", "txn_response_code"):
        code = normalize_code(data.get(key))
        if code and code != "0" and code.isdigit():
            return code, message
    code = const.DECLINE_MESSAGE_CODES.get(message.lower())
    return code or const.DECLINED_CODE, message


def classify_error(status_code, description):
    """Recognize an error of Paymob's APIs from its HTTP status and its message.

    :param int status_code: The HTTP status of the response.
    :param str description: The error message.
    :return: A key of `const.ERROR_CODES`, or the HTTP status if the error isn't known.
    :rtype: str
    """
    text = (description or "").lower()
    if status_code in (401, 403) or "credentials" in text or "authentication" in text:
        return "credentials"
    if "integration" in text and ("not exist" in text or "does not" in text):
        return "integration"
    if "refund amount" in text or "maximum refund" in text:
        return "refund_amount"
    if "capture amount" in text:
        return "capture_amount"
    if "invalid transaction" in text or "transaction id" in text:
        return "transaction_id"
    if "already exist" in text or "special_reference" in text or "duplicate" in text:
        return "duplicate_reference"
    if "billing_data" in text or "phone_number" in text or "email" in text:
        return "billing_data"
    if "items" in text or "amount" in text:
        return "items"
    if status_code == 404:
        return "not_found"
    if status_code and status_code >= 500:
        return "server"
    return str(status_code or "")


def flatten_errors(content):
    """Turn the error body of a Paymob response into a readable message.

    Paymob answers errors with ``{"detail": ...}``, ``{"message": ...}`` or the errors of each
    field, possibly nested (``{"billing_data": {"phone_number": ["..."]}}``).

    :param content: The decoded body.
    :rtype: str
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "; ".join(flatten_errors(item) for item in content)
    if isinstance(content, dict):
        for key in ("detail", "message", "error", "errors"):
            if content.get(key) and not isinstance(content[key], (dict, list)):
                return str(content[key])
        parts = []
        for key, value in content.items():
            parts.append(f"{key}: {flatten_errors(value)}")
        return "; ".join(parts)
    return str(content)


def get_brand_code(card_subtype):
    """Return the code of the card brand method matching Paymob's card type, if known.

    :param str card_subtype: The card type, e.g. "MasterCard" or "Visa".
    :rtype: str | None
    """
    return const.CARD_BRAND_MAPPING.get((card_subtype or "").strip().lower())


def get_last_digits(masked_pan):
    """Return the last four digits of a masked card number ("xxxx-xxxx-xxxx-2346" -> "2346")."""
    digits = re.sub(r"\D", "", masked_pan or "")
    return digits[-4:]


def format_expiry(month, year):
    """Return the expiry date of a card as MM/YY, or an empty string if it isn't known."""
    month = str(month or "").strip()
    year = str(year or "").strip()
    if not (month.isdigit() and year.isdigit()):
        return ""
    return f"{int(month):02d}/{year[-2:]}"


def is_card_expired(expiry, today):
    """Return whether a card has expired, from its expiry date (MM/YY).

    A card is valid until the end of its expiry month.

    :param str expiry: The expiry date, MM/YY.
    :param datetime.date today: Today's date.
    :rtype: bool
    """
    match = re.fullmatch(r"(\d{1,2})/(\d{2,4})", (expiry or "").strip())
    if not match:
        return False
    month, year = int(match.group(1)), int(match.group(2))
    if year < 100:
        year += 2000
    return (year, month) < (today.year, today.month)
