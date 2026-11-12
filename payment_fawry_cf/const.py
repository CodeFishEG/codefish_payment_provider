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
from odoo.addons.payment.const import SENSITIVE_KEYS as PAYMENT_SENSITIVE_KEYS

# Keys redacted from the payment logs. The secure key itself is never sent to Fawry.
SENSITIVE_KEYS = {"cardToken", "token"}
PAYMENT_SENSITIVE_KEYS.update(SENSITIVE_KEYS)

# Base URLs of the Fawry platform, by environment.
API_URLS = {
    "test": "https://atfawry.fawrystaging.com",
    "live": "https://www.atfawry.com",
}

# API endpoints, relative to the base URL.
ENDPOINT_INIT = "/fawrypay-api/api/payments/init"  # Express Checkout (hosted page)
ENDPOINT_CHARGE = "/ECommerceWeb/Fawry/payments/charge"  # Server-to-server charge
ENDPOINT_WALLET_CHARGE = "/ECommerceWeb/api/payments/charge"  # Server-to-server wallet charge
ENDPOINT_STATUS = "/ECommerceWeb/Fawry/payments/status/v2"
ENDPOINT_REFUND = "/ECommerceWeb/Fawry/payments/refund"
ENDPOINT_CANCEL_UNPAID = "/ECommerceWeb/api/orders/cancel-unpaid-order"
ENDPOINT_CARD_TOKENS = "/ECommerceWeb/Fawry/cards/cardToken"  # List (GET) and delete (DELETE)

# The bank journal created for the Fawry provider of each company, where Fawry payments are posted.
JOURNAL_CODE = "FAWRY"
JOURNAL_NAME = "Fawry Pay"
JOURNAL_NAME_TRANSLATIONS = {"ar": "مدفوعات فورى"}  # By language ISO code.
JOURNAL_CURRENCY_XMLID = "base.EGP"

# Fawry's secure page where customers save a card.
CARD_TOKEN_PLUGIN_PATH = "/atfawry/plugin/card-token"

# The values Fawry signs in a charge response (see `utils.compute_charge_response_signature`).
SIGNED_CHARGE_RESPONSE_KEYS = (
    "referenceNumber",
    "merchantRefNumber",
    "paymentAmount",
    "orderAmount",
    "orderStatus",
    "paymentMethod",
    "fawryFees",
    "shippingFees",
    "authNumber",
    "customerMail",
    "customerMobile",
)

# Fawry answers with this business code when an order is not known (e.g. not created yet).
ORDER_NOT_FOUND_CODE = "9938"

# The integration types offered on the provider.
INTEGRATION_EXPRESS = "express"
INTEGRATION_S2S = "s2s"

# The flows a payment method can follow, depending on the integration type.
FLOW_HOSTED = "hosted"  # Fawry's hosted checkout page, with the method locked when possible.
FLOW_CARD_TOKEN = "card_token"  # Card tokenization plugin, then a 3-D Secure token charge.
FLOW_S2S_CHARGE = "s2s_charge"  # Server-to-server charge that returns payment instructions.

# Odoo payment method codes handled by Fawry, mapped to the `paymentMethod` value that locks
# Fawry's hosted checkout on that method. `fawry` shows every method enabled on the account.
HOSTED_METHOD_CODES = {
    "fawry": None,
    "card": "CARD",
    "pay_at_fawry": "PayAtFawry",
    "mobile_wallet_eg": "MWALLET",
    "myfawry": "MYFAWRY",
    "fawry_yellow_card": "MYFAWRYTAQSEET",
    "valu": "VALU",
    "forsa": "FORSA",
    "souhoola": "SOUHOOLA",
}

# Payment methods charged through the server-to-server API when that integration is selected,
# mapped to the `paymentMethod` value of the charge request.
S2S_CHARGE_METHOD_CODES = {
    "pay_at_fawry": "PAYATFAWRY",
    "mobile_wallet_eg": "MWALLET",
    "myfawry": "MYFAWRY",
}

# The `paymentMethod` values found in Fawry's responses and notifications, mapped to Odoo codes.
# Fawry spells some of them in several ways; they are compared in upper case.
FAWRY_TO_ODOO_METHOD_CODES = {
    "CARD": "card",
    "PAYUSINGCC": "card",  # Sent by Fawry's checkout when shown in a pop-up or a side panel.
    "PAYATFAWRY": "pay_at_fawry",
    "MWALLET": "mobile_wallet_eg",
    "MYFAWRY": "myfawry",
    "MYFAWRYTAQSEET": "fawry_yellow_card",
    "VALU": "valu",
    "FORSA": "forsa",
    "SOUHOOLA": "souhoola",
}

# The card brands returned by Fawry ("Visa Card", "Master Card", "Meeza"...), matched by keyword.
CARD_BRAND_KEYWORDS = {
    "visa": "visa",
    "master": "mastercard",
    "meeza": "meeza",
}

# The card brands, by the first digits of the card number (checked in this order).
CARD_BRAND_PREFIXES = [
    (r"^507", "meeza"),
    (r"^4", "visa"),
    (r"^(5[1-5]|2[2-7])", "mastercard"),
]

# The codes of the primary payment methods activated when the provider is installed.
DEFAULT_PAYMENT_METHOD_CODES = {"card", "pay_at_fawry", "mobile_wallet_eg"}

# Mapping of transaction states to Fawry order statuses.
PAYMENT_STATUS_MAPPING = {
    "pending": ("NEW", "UNPAID"),
    "authorized": ("AUTHORIZED",),
    "done": ("PAID",),
    "cancel": ("CANCELED", "CANCELLED", "EXPIRED"),
    "error": ("FAILED",),
    "refunded": ("REFUNDED", "PARTIAL_REFUNDED"),
}

# The display modes of Fawry's checkout shown on the page, by provider setting.
DISPLAY_MODES = {
    "popup": "POPUP",
    "side_page": "SIDE_PAGE",
}

# Egyptian mobile numbers, in the local format Fawry expects (01xxxxxxxxx).
EG_MOBILE_PATTERN = r"^01[0-25]\d{8}$"
