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
from odoo.tools import LazyTranslate

from odoo.addons.payment.const import SENSITIVE_KEYS as PAYMENT_SENSITIVE_KEYS

_lt = LazyTranslate(__name__)

PROVIDER_CODE = "kashier_cf"

# Keys redacted from the payment logs. Kashier echoes the Payment API Key (`apiKey`) in session
# documents, its credentials check lists every key of the account, and card tokens let anyone holding
# the key charge the card again.
SENSITIVE_KEYS = {
    "apiKey", "api_key", "apiKeys", "secretKeys", "merchantAPIKeys", "key", "hash", "signature",
    "cardDataToken", "cardToken", "ccvToken", "securityCode", "token", "Kashier-Hash", "Authorization",
}
PAYMENT_SENSITIVE_KEYS.update(SENSITIVE_KEYS)

# Kashier's hosts. Test keys only work on the test hosts and live keys on the live ones.
HOSTS = {
    "dashboard": {"test": "https://test-api.kashier.io", "live": "https://api.kashier.io"},
    "fep": {"test": "https://test-fep.kashier.io", "live": "https://fep.kashier.io"},
}
# The hosted payment page: one host for both modes, the mode travels as `?mode=test|live`.
CHECKOUT_HOST = "payments.kashier.io"

# Odoo's payment methods. `card` (and its brands) opens Kashier's page on cards only; `kashier` opens it
# on every method enabled on the merchant account (wallets, installments, valU and other BNPL...).
DEFAULT_PAYMENT_METHOD_CODES = {"card", "kashier"}
CARD_METHOD_CODES = {"card", "visa", "mastercard", "meeza"}
PROVIDER_WIDE_METHOD_CODE = "kashier"
# Kashier's `cardBrand` values and the Odoo brand method of each.
CARD_BRAND_MAPPING = {"mastercard": "mastercard", "visa": "visa", "meeza": "meeza"}
SUPPORTED_CURRENCIES = ("EGP", "USD", "GBP", "EUR")

# The Kashier `order` sent for a transaction: the reference, cleaned, with a code of the database
# and a nonce so that databases sharing a merchant account never collide (Kashier refuses an `order`
# it already knows: ERR_ORD_02).
ORDER_REF_MAX_PREFIX = 30
ORDER_REF_ALLOWED = r"[^A-Za-z0-9_-]"

# Session settings (provider fields): minutes the hosted page stays valid, and the number of card
# attempts the customer gets on it before it fails.
SESSION_EXPIRY_DEFAULT = 30
SESSION_EXPIRY_RANGE = (5, 1440)
MAX_ATTEMPTS_DEFAULT = 3
MAX_ATTEMPTS_RANGE = (1, 5)

# The fields of the signed redirect query, in Kashier's signing order (`signature` and `mode` excluded).
REDIRECT_SIGNED_FIELDS = (
    "paymentStatus", "cardDataToken", "maskedCard", "merchantOrderId", "orderId", "cardBrand",
    "orderReference", "transactionId", "amount", "currency",
)

# Session statuses (GET /v3/payment/sessions/{id}/payment).
SESSION_OPEN = {"CREATED", "OPENED", "PENDING"}
SESSION_PAID = {"PAID", "REFUNDED", "PARTIALLY_REFUNDED", "REFUND_PENDING"}
SESSION_AUTHORIZED = {"AUTHORIZED"}
SESSION_FAILED = {"FAILED", "REJECTED"}
SESSION_ENDED = {"EXPIRED", "ABANDONED"}
SESSION_RELEASED = {"VOIDED", "REVERSED"}
SESSION_FINAL = SESSION_PAID | SESSION_AUTHORIZED | SESSION_FAILED | SESSION_ENDED | SESSION_RELEASED

# Order statuses (GET /v3/payment/orders).
ORDER_PAID = {"CAPTURED"}
ORDER_AUTHORIZED = {"AUTHORIZED"}
ORDER_FAILED = {"FAILED", "REJECTED"}
ORDER_INITIATED = {"INITIATED"}
ORDER_RELEASED = {"CANCELLED", "REVERSED"}
ORDER_EXPIRED = {"EXPIRED"}

# Transaction legs of an order. 3-D Secure legs never move money (`authenticate_payer` stays PENDING
# even when the payment succeeded) and are ignored when deciding the outcome.
LEGS_3DS = {"3dsecure_verify", "authenticate_payer", "3dsecure_process_acs_result"}
LEG_PAY = "pay"
LEG_AUTHORIZE = "authorize"
LEG_CAPTURE = "capture"
LEG_REFUND = "refund"
LEG_VOID = "void"
MONEY_LEGS = {LEG_PAY, LEG_AUTHORIZE}
LEG_SUCCESS = "SUCCESS"
LEG_FAILURE = "FAILURE"
LEG_UNDETERMINED = {"PENDING", "INITIATED", "UNKNOWN"}
# Response codes whose outcome is not known yet: the payment is reconciled, never retried.
UNDETERMINED_CODES = {"UNKNOWN", "CC", "k_timeout", "SUBMITTED", "TIMED_OUT", "68", "k_101", "PENDING"}

# How often the status is asked to Kashier at most (seconds), from the return page and the poll route.
SYNC_THROTTLE_SECONDS = 10
# A cancelled transaction is still checked for a late payment during this delay after the session ended.
LATE_CHECK_HOURS = 48
# Without an answer for a refund, capture, void or saved-card charge, the outcome stays unknown for this
# delay, then the transaction is put in error with a message to check Kashier's dashboard.
UNKNOWN_OUTCOME_HOURS = 2

# The private key of the data recorded from Kashier's authenticated answers.
SNAPSHOT_KEY = "kashier_cf_snapshot"

# Card brands Kashier refuses for merchant-initiated (recurring) charges.
MIT_REFUSED_BRANDS = {"meeza"}

# === ERRORS === #

# Who the error is about: the customer (card, bank, details) or the merchant (account, settings).
ERROR_CUSTOMER = "customer"
ERROR_MERCHANT = "merchant"
ERROR_UNKNOWN = "unknown"  # The outcome is not known yet.

# Kashier's response codes and HTTP-level errors: (kind, explanation).
ERROR_CODES = {
    # ISO numeric codes (card schemes).
    "01": (ERROR_CUSTOMER, _lt("The bank couldn't process the payment. Ask the bank or use another card.")),
    "03": (ERROR_MERCHANT, _lt("The bank doesn't recognise the merchant account. Check the account with Kashier.")),
    "04": (ERROR_CUSTOMER, _lt("The card was reported lost. Use another card.")),
    "05": (ERROR_CUSTOMER, _lt("The bank declined the payment. Try again or contact the bank.")),
    "12": (ERROR_CUSTOMER, _lt("The bank couldn't process the payment. Ask the bank or use another card.")),
    "13": (ERROR_MERCHANT, _lt("The amount is not valid for this card.")),
    "14": (ERROR_CUSTOMER, _lt("The card details are not valid. Check the number and the expiry date.")),
    "41": (ERROR_CUSTOMER, _lt("The card was reported lost. Use another card.")),
    "43": (ERROR_CUSTOMER, _lt("The card was reported stolen. Use another card.")),
    "51": (ERROR_CUSTOMER, _lt("The card has not enough funds.")),
    "54": (ERROR_CUSTOMER, _lt("The card has expired.")),
    "55": (ERROR_CUSTOMER, _lt("The PIN is not correct.")),
    "57": (ERROR_CUSTOMER, _lt("The card doesn't allow this kind of payment. Ask the bank or use another card.")),
    "61": (ERROR_CUSTOMER, _lt("The payment is above the card's limit.")),
    "65": (ERROR_CUSTOMER, _lt("The card has reached its number of payments. Try later or use another card.")),
    "68": (ERROR_UNKNOWN, _lt("The bank answered too late. The outcome is checked with Kashier.")),
    "91": (ERROR_CUSTOMER, _lt("The bank is not available. Try again later.")),
    "96": (ERROR_CUSTOMER, _lt("The bank had a system error. Try again later.")),
    "AA": (ERROR_CUSTOMER, _lt("The payment failed. Try again or use another card.")),
    "BB": (ERROR_CUSTOMER, _lt("The bank had a system error. Try again later.")),
    "CC": (ERROR_UNKNOWN, _lt("The outcome of the payment is not known yet. It is checked with Kashier.")),
    # 3-D Secure.
    "N": (ERROR_CUSTOMER, _lt("The card holder's authentication (3-D Secure) failed.")),
    "P": (ERROR_CUSTOMER, _lt("The authentication failed. Check the card details.")),
    "U": (ERROR_CUSTOMER, _lt("The bank's authentication is not available. Try again later.")),
    "X": (ERROR_CUSTOMER, _lt("The bank's authentication is not available. Try again later.")),
    # Gateway codes.
    "ABORTED": (ERROR_CUSTOMER, _lt("The payment was cancelled.")),
    "CANCELLED": (ERROR_CUSTOMER, _lt("The payment was cancelled.")),
    "DECLINED": (ERROR_CUSTOMER, _lt("The bank declined the payment. Try again or use another card.")),
    "EXPIRED_CARD": (ERROR_CUSTOMER, _lt("The card has expired.")),
    "INSUFFICIENT_FUNDS": (ERROR_CUSTOMER, _lt("The card has not enough funds.")),
    "INVALID_CSC": (ERROR_CUSTOMER, _lt("The security code (CVV) is not correct.")),
    "NO_MATCH": (ERROR_CUSTOMER, _lt("The security code (CVV) is not correct.")),
    "BLOCKED": (ERROR_CUSTOMER, _lt("The card is blocked. Contact the bank.")),
    "REFERRED": (ERROR_CUSTOMER, _lt("The bank asks you to contact it before paying.")),
    "NOT_SUPPORTED": (ERROR_CUSTOMER, _lt("The card doesn't support this payment. Ask the bank or use another card.")),
    "NOT_ENROLLED_3D_SECURE": (ERROR_CUSTOMER, _lt("The card doesn't support secure online payments (3-D Secure).")),
    "EXCEEDED_RETRY_LIMIT": (ERROR_CUSTOMER, _lt("Too many attempts. Try again later.")),
    "LOCK_FAILURE": (ERROR_UNKNOWN, _lt("Another payment of this order is in progress. The outcome is checked with Kashier.")),
    "ACQUIRER_SYSTEM_ERROR": (ERROR_CUSTOMER, _lt("The bank had a system error. Try again later.")),
    "SYSTEM_ERROR": (ERROR_CUSTOMER, _lt("The payment system had an error. Try again later.")),
    "UNSPECIFIED_FAILURE": (ERROR_CUSTOMER, _lt("The payment failed. Try again or use another card.")),
    "TIMED_OUT": (ERROR_UNKNOWN, _lt("The bank answered too late. The outcome is checked with Kashier.")),
    "UNKNOWN": (ERROR_UNKNOWN, _lt("The outcome of the payment is not known yet. It is checked with Kashier.")),
    "SUBMITTED": (ERROR_UNKNOWN, _lt("The outcome of the payment is not known yet. It is checked with Kashier.")),
    "MEEZA_NOT_ALLOWED": (ERROR_CUSTOMER, _lt("Meeza cards can't be charged automatically. Pay online with the card instead.")),
    # Kashier codes.
    "k_default": (ERROR_MERCHANT, _lt("Kashier returned a general error.")),
    "k_timeout": (ERROR_UNKNOWN, _lt("Kashier answered too late. The outcome is checked with Kashier.")),
    "k_1": (ERROR_MERCHANT, _lt("The saved card was not found at Kashier.")),
    "k_5": (ERROR_CUSTOMER, _lt("This mobile number has no wallet.")),
    "k_7": (ERROR_CUSTOMER, _lt("The order was not paid.")),
    "k_10": (ERROR_MERCHANT, _lt("The payment was already refunded.")),
    "k_14": (ERROR_CUSTOMER, _lt("The payment page expired.")),
    "k_101": (ERROR_UNKNOWN, _lt("The payment is in progress. The outcome is checked with Kashier.")),
    "REFUND_DISABLED": (ERROR_MERCHANT, _lt("The bank disabled refunds for this merchant account. Ask the bank or Kashier to enable them.")),
    "ERR_ORD_02": (ERROR_MERCHANT, _lt("Kashier already has an order with this reference.")),
    "INVALID_HASH_CHECK": (ERROR_MERCHANT, _lt("Kashier refused the request signature. Check the Payment API Key and the Merchant ID.")),
    # Errors found from the HTTP answer (see utils.classify_error).
    "credentials": (ERROR_MERCHANT, _lt("Kashier refused the credentials. Check the Secret Key, the Payment API Key and the Merchant ID, and that they are for the right mode (test or live).")),
    "permission": (ERROR_MERCHANT, _lt("The user owning the Secret Key lacks a permission in Kashier (refunds need the refund permission).")),
    "ip_not_allowed": (ERROR_MERCHANT, _lt("Kashier refused the server's IP address. Add it to the allowed IP addresses in Kashier's dashboard.")),
    "not_live": (ERROR_MERCHANT, _lt("The Kashier account is not live yet. Use test mode until Kashier activates it.")),
    "over_refund": (ERROR_MERCHANT, _lt("The refund is larger than what can still be refunded on this payment.")),
    "capture_disabled": (ERROR_MERCHANT, _lt("Authorize and capture is not enabled on the Kashier account. Ask Kashier to enable it, or turn off manual capture.")),
    "not_found": (ERROR_MERCHANT, _lt("Kashier doesn't know this payment.")),
    "rate_limited": (ERROR_UNKNOWN, _lt("Kashier asked to slow down. The request is checked again later.")),
    "server_error": (ERROR_UNKNOWN, _lt("Kashier had an error. The outcome is checked with Kashier.")),
    "bad_request": (ERROR_MERCHANT, _lt("Kashier refused the request.")),
}

# The provider's bank journal, one per company, created at installation. No currency: Kashier takes EGP,
# USD, GBP and EUR.
JOURNAL_CODE = "KASHR"
JOURNAL_NAME = "Kashier"
JOURNAL_NAME_TRANSLATIONS = {"ar": "كاشير"}

# Context key set when a person deletes a saved card (portal or back office): only then is the card also
# deleted at Kashier. Archiving through a change of the provider or of the methods keeps it at Kashier.
DELETE_AT_KASHIER = "kashier_cf_delete_at_kashier"
