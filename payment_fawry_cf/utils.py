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
"""Pure helpers for the Fawry API: amounts, signatures, phone numbers and languages.

Every Fawry signature is the lowercase hex SHA-256 digest of the listed values concatenated
without separators, followed by the merchant's secure key. Amounts are signed with two decimals.
"""

import hashlib
import re

from odoo.addons.payment_fawry_cf import const


def format_amount(value):
    """Format an amount the way Fawry signs it: two decimals, dot separator.

    :param float|str value: The amount.
    :return: The formatted amount, e.g. ``"150.00"``.
    :rtype: str
    """
    return f"{float(value):.2f}"


def compute_signature(*values, secure_key):
    """Return the Fawry signature of the given values.

    Empty values (``None`` or ``""``) are skipped, as Fawry does for optional fields.

    :param values: The values to sign, in the order Fawry expects them.
    :param str secure_key: The merchant's secure key.
    :return: The lowercase hex SHA-256 digest.
    :rtype: str
    """
    signed_string = "".join(str(value) for value in values if value not in (None, ""))
    return hashlib.sha256(f"{signed_string}{secure_key}".encode()).hexdigest()


def compute_charge_response_signature(data, secure_key):
    """Return the expected signature of a charge response or of a return redirect.

    Optional fields are only signed when Fawry sent them.

    :param dict data: The charge response, or the query string of the return redirect.
    :param str secure_key: The merchant's secure key.
    :return: The expected signature.
    :rtype: str
    """

    def optional_amount(key):
        return format_amount(data[key]) if data.get(key) not in (None, "") else None

    return compute_signature(
        data.get("referenceNumber"),
        data.get("merchantRefNumber"),
        format_amount(data.get("paymentAmount") or 0),
        format_amount(data.get("orderAmount") or 0),
        data.get("orderStatus"),
        data.get("paymentMethod"),
        optional_amount("fawryFees"),
        optional_amount("shippingFees"),
        data.get("authNumber"),
        data.get("customerMail"),
        data.get("customerMobile"),
        secure_key=secure_key,
    )


def compute_notification_signature(data, secure_key):
    """Return the expected ``messageSignature`` of a notification or of a payment status.

    :param dict data: The server notification (V2) or the payment status (V2) payload.
    :param str secure_key: The merchant's secure key.
    :return: The expected signature.
    :rtype: str
    """
    return compute_signature(
        data.get("fawryRefNumber"),
        data.get("merchantRefNumber"),
        format_amount(data.get("paymentAmount") or 0),
        format_amount(data.get("orderAmount") or 0),
        data.get("orderStatus"),
        data.get("paymentMethod"),
        data.get("paymentRefrenceNumber"),  # Fawry's spelling.
        secure_key=secure_key,
    )


def normalize_mobile(phone):
    """Convert a phone number to the Egyptian local format Fawry expects.

    :param str phone: The phone number, in any common format (``+20 100 123 4567``...).
    :return: The number as ``01xxxxxxxxx``, or an empty string if it is not an Egyptian mobile.
    :rtype: str
    """
    digits = re.sub(r"[^\d+]", "", phone or "")
    for prefix in ("+20", "0020"):
        if digits.startswith(prefix):
            digits = "0" + digits[len(prefix) :]
            break
    else:
        if digits.startswith("20") and len(digits) == 12:
            digits = "0" + digits[2:]
    return digits if re.match(const.EG_MOBILE_PATTERN, digits) else ""


def get_fawry_language(lang_code):
    """Return the language Fawry uses for its notifications to the customer.

    :param str lang_code: The Odoo language code, e.g. ``ar_EG`` or ``en_US``.
    :return: ``"ar-eg"`` or ``"en-gb"``.
    :rtype: str
    """
    return "ar-eg" if (lang_code or "").startswith("ar") else "en-gb"


def get_fawry_locale(lang_code):
    """Return the locale of Fawry's hosted pages.

    :param str lang_code: The Odoo language code.
    :return: ``"ar"`` or ``"en"``.
    :rtype: str
    """
    return "ar" if (lang_code or "").startswith("ar") else "en"


def get_brand_code(brand, first_digits=None):
    """Return the Odoo code of a card brand.

    Fawry's brand names vary ("Visa Card", "Master Card", or an internal code such as
    "BMISCARD"), so the first digits of the card number are used when the name isn't recognized.

    :param str brand: The brand as sent by Fawry.
    :param str first_digits: The first digits of the card number, if known.
    :return: The Odoo payment method code of the brand, or ``None``.
    :rtype: str | None
    """
    brand = (brand or "").lower()
    for keyword, code in const.CARD_BRAND_KEYWORDS.items():
        if keyword in brand:
            return code
    first_digits = str(first_digits or "")
    for prefix_pattern, code in const.CARD_BRAND_PREFIXES:
        if re.match(prefix_pattern, first_digits):
            return code
    return None


def is_card_expired(expiry_date, today):
    """Return whether a card has expired.

    A card stays valid until the end of its expiry month.

    :param str expiry_date: The expiry date as Fawry sends it: "MM/YY".
    :param datetime.date today: The current date.
    :return: Whether the card has expired; ``False`` when the expiry date is unknown or malformed.
    :rtype: bool
    """
    match = re.fullmatch(r"\s*(\d{1,2})\s*/\s*(\d{2}|\d{4})\s*", expiry_date or "")
    if not match:
        return False
    month, year = int(match[1]), int(match[2])
    if not 1 <= month <= 12:
        return False
    if year < 100:
        year += 2000
    return (year, month) < (today.year, today.month)
