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

# Keys redacted from the payment logs: keys, tokens and card tokens.
SENSITIVE_KEYS = {
    "api_key", "auth_token", "token", "identifier", "client_secret", "payment_token", "key", "hmac",
}
PAYMENT_SENSITIVE_KEYS.update(SENSITIVE_KEYS)

# Paymob runs one platform per country, for test and live payments alike: the keys and the
# integration IDs decide the mode. Each country processes its own currency.
COUNTRIES = {
    "EG": {"api_url": "https://accept.paymob.com", "currency": "EGP"},
    "SA": {"api_url": "https://ksa.paymob.com", "currency": "SAR"},
    "AE": {"api_url": "https://uae.paymob.com", "currency": "AED"},
    "OM": {"api_url": "https://oman.paymob.com", "currency": "OMR"},
    "PK": {"api_url": "https://pakistan.paymob.com", "currency": "PKR"},
}
DEFAULT_COUNTRY = "EG"

# API endpoints, relative to the base URL of the country.
ENDPOINT_AUTH = "/api/auth/tokens"  # API key -> Bearer token (60 minutes)
ENDPOINT_INTENTION = "/v1/intention/"  # Secret key
ENDPOINT_CHECKOUT = "/unifiedcheckout/"  # Hosted checkout, redirects to the country's checkout host
ENDPOINT_INQUIRY = "/api/ecommerce/orders/transaction_inquiry"  # Bearer
ENDPOINT_ORDER_CARD_TOKENS = "/api/acceptance/order_card_tokens"  # Bearer
ENDPOINT_REFUND = "/api/acceptance/void_refund/refund"  # Secret key
ENDPOINT_VOID = "/api/acceptance/void_refund/void"  # Secret key
ENDPOINT_CAPTURE = "/api/acceptance/capture"  # Secret key
ENDPOINT_PAY = "/api/acceptance/payments/pay"  # Merchant-initiated charge of a saved card
ENDPOINT_INTEGRATIONS = "/api/ecommerce/integrations"  # Bearer

# How a request authenticates (see `payment.provider._build_request_headers`).
AUTH_SECRET_KEY = "secret_key"
AUTH_BEARER = "bearer"
AUTH_NONE = "none"

# The Bearer token lasts 60 minutes; it is renewed a little before.
AUTH_TOKEN_LIFETIME_SECONDS = 50 * 60

# The integrations of the provider.
INTEGRATION_HOSTED = "hosted"  # Paymob Checkout (Unified Checkout)
INTEGRATION_EMBEDDED = "embedded"  # Card form embedded in the website (Pixel) + server APIs

# How a payment is processed (see `payment.provider._paymob_cf_get_flow`).
FLOW_HOSTED = "hosted"  # Paymob Checkout, in a full page, a pop-up or a side panel
FLOW_PIXEL = "pixel"  # Paymob's card form embedded in the payment form

# The methods Paymob's embedded form (Pixel) handles, with their Pixel names.
PIXEL_METHODS = {"card": "card", "apple_pay": "apple-pay", "google_pay": "google-pay"}

# Apple Pay ("Apple Pay [All regions]" in Paymob's docs): live integrations only, in these countries.
APPLE_PAY_CODE = "apple_pay"
APPLE_PAY_COUNTRIES = ("EG", "SA", "AE", "OM")
# Where Apple fetches the file proving that the website belongs to the Apple Pay merchant (embedded
# checkout only: Paymob Checkout shows Apple Pay on Paymob's own domain).
APPLE_PAY_DOMAIN_FILE_URL = "/.well-known/apple-developer-merchantid-domain-association"
APPLE_PAY_DOMAIN_FILE_MAX_SIZE = 100 * 1024  # Apple's file is about 10 KB of text.

# Paymob's embedded form, pinned to a tested version. It sets `window.Pixel` and brings its CSS.
PIXEL_SCRIPT_URL = "https://cdn.jsdelivr.net/npm/paymob-pixel@1.2.10/main.js"

# The code of the method that opens Paymob Checkout with every method of the account.
ALL_METHODS_CODE = "paymob"

# The methods activated when the module is installed. Methods other than cards are offered to
# customers whose country and currency the method supports.
DEFAULT_PAYMENT_METHOD_CODES = {"card", "mobile_wallet_eg", "kiosk"}

# The methods processed by Paymob's card integrations: cards and their brands.
CARD_METHOD_CODES = {"card", "visa", "mastercard", "amex", "meeza", "mada", "omannet", "jaywan"}

# Paymob's gateway types, as listed by the integrations API, and the Odoo methods they serve.
GATEWAY_TYPE_MAPPING = {
    "VPC": "card",
    "MIGS": "card",
    "UIG": "mobile_wallet_eg",
    "CAGG": "kiosk",
    "HALAN": "halan",
    "SYMPL": "sympl",
    "VALU": "valu",
    "AMANV3": "aman",
    "SOUHOOLAV3": "souhoola",
    "CONTACT": "contact",
    "PREMIUM6": "premium_card",
    "FORSA": "forsa",
    "TABBY": "tabby",
    "TAMARA": "tamara",
    "STCPAY": "stcpay",
    "OMANNET": "omannet",
    "MOGO": "mogo",
    "JAZZCASH": "jazzcash",
    "EASYPAISA": "easypaisa",
}

# The methods Paymob can't refund (Paymob's payment methods pages).
NON_REFUNDABLE_METHOD_CODES = {"kiosk"}

# The keys signed by Paymob's transaction callbacks (HMAC-SHA512 of the values concatenated in this
# order). The POST callback nests the order, the GET redirection flattens it to `order` (or
# `order_id`); see `utils.get_transaction_hmac_string`.
TRANSACTION_HMAC_KEYS = (
    "amount_cents",
    "created_at",
    "currency",
    "error_occured",
    "has_parent_transaction",
    "id",
    "integration_id",
    "is_3d_secure",
    "is_auth",
    "is_capture",
    "is_refunded",
    "is_standalone_payment",
    "is_voided",
    "order.id",
    "owner",
    "pending",
    "source_data.pan",
    "source_data.sub_type",
    "source_data.type",
    "success",
)

# The keys signed by Paymob's card token callback, in order.
TOKEN_HMAC_KEYS = (
    "card_subtype",
    "created_at",
    "email",
    "id",
    "masked_pan",
    "merchant_id",
    "order_id",
    "token",
)

# The private key that marks the payment data recorded from Odoo's own requests (refund, capture,
# void): they update the transaction that sent the request. Removed from what Paymob sends.
OWN_REQUEST_KEY = "paymob_cf_request"

# Callback types.
CALLBACK_TRANSACTION = "TRANSACTION"
CALLBACK_TOKEN = "TOKEN"

# Card brands, as Paymob names them (`source_data.sub_type`, `card_subtype`), and their methods.
CARD_BRAND_MAPPING = {
    "visa": "visa",
    "mastercard": "mastercard",
    "master card": "mastercard",
    "amex": "amex",
    "american express": "amex",
    "meeza": "meeza",
    "mada": "mada",
    "omannet": "omannet",
    "jaywan": "jaywan",
}

# Paymob's source types (`source_data.type`) and the methods they belong to.
SOURCE_TYPE_MAPPING = {
    "card": "card",
    "wallet": "mobile_wallet_eg",
    "aggregator": "kiosk",
    "cash_present": "kiosk",
    "valu": "valu",
    "souhoola": "souhoola",
    "sympl": "sympl",
    "forsa": "forsa",
    "premium": "premium_card",
    "contact": "contact",
    "halan": "halan",
    "aman": "aman",
    "tabby": "tabby",
    "tamara": "tamara",
    "apple_pay": "apple_pay",
    "applepay": "apple_pay",
    "google_pay": "google_pay",
    "googlepay": "google_pay",
    "stcpay": "stcpay",
    "jazzcash": "jazzcash",
    "easypaisa": "easypaisa",
}

# The currencies whose Visa payments Paymob rounds down to fewer decimals than ISO 4217 gives them.
VISA_CURRENCY_DECIMALS = {"OMR": 2}

# Billing values Paymob requires but the customer may not have given.
MISSING_VALUE = "NA"

# The bank journal created for the Paymob provider of each company.
JOURNAL_CODE = "PAYMB"
JOURNAL_NAME = "Paymob"
JOURNAL_NAME_TRANSLATIONS = {"ar": "مدفوعات باي موب"}  # By language ISO code.

# Published test data (Paymob's "Test Credentials" page), shown to administrators in test mode.
TEST_CARDS = (
    ("Mastercard", "5123 4567 8901 2346"),
    ("Mastercard", "5123 4500 0000 0008"),
    ("Visa", "4111 1111 1111 1111"),
)
WEBHOOK_TESTER_URL = "https://hooks.paymob.com"
HMAC_CHECKER_URL = "https://wizard.paymob.com"

# How the error codes are explained to the customer: the errors about their card, bank or details
# are explained as they are; the others are about the merchant's account and only shown to the staff.
ERROR_CUSTOMER = "customer"
ERROR_MERCHANT = "merchant"

# Generic decline, when Paymob gives no acquirer code.
DECLINED_CODE = "declined"

# Paymob's response codes and errors, with what they mean.
# - Numeric codes: the acquirer response codes of card payments (ISO 8583, as listed in Paymob's
#   "Error messages" page, completed with the card networks' usual codes) and Paymob's risk
#   declines. Leading zeros are dropped ("05" -> "5").
# - Other codes: the errors of Paymob's APIs, recognized from their message (`utils.classify_error`).
ERROR_CODES = {
    # Acquirer response codes.
    "1": (ERROR_CUSTOMER, _lt("Your bank asks you to contact them about this payment. Please contact your bank or use another card.")),
    "2": (ERROR_CUSTOMER, _lt("Your bank asks you to contact them about this payment. Please contact your bank or use another card.")),
    "3": (ERROR_MERCHANT, _lt("The card network doesn't recognize the merchant account. Ask Paymob to check the card payments of your account.")),
    "4": (ERROR_CUSTOMER, _lt("The bank refused the card. Please contact your bank or use another card.")),
    "5": (ERROR_CUSTOMER, _lt("The bank declined the payment. Please contact your bank or use another card.")),
    "6": (ERROR_CUSTOMER, _lt("The bank couldn't process the payment. Please try again or use another card.")),
    "7": (ERROR_CUSTOMER, _lt("The bank refused the card. Please contact your bank or use another card.")),
    "8": (ERROR_CUSTOMER, _lt("The bank asks for more identification for this payment. Please contact your bank.")),
    "9": (ERROR_CUSTOMER, _lt("The bank is still processing a previous request. Please try again in a few minutes.")),
    "10": (ERROR_CUSTOMER, _lt("The bank approved only part of the amount. Please use another card.")),
    "12": (ERROR_CUSTOMER, _lt("The bank doesn't allow this kind of payment with this card. Please use another card.")),
    "13": (ERROR_CUSTOMER, _lt("The bank refused the amount of the payment. Please try again or use another card.")),
    "14": (ERROR_CUSTOMER, _lt("The card number isn't valid. Please check it and try again.")),
    "15": (ERROR_CUSTOMER, _lt("The bank of this card couldn't be found. Please check the card number and try again.")),
    "16": (ERROR_CUSTOMER, _lt("A technical error at the bank stopped the payment. Please try again later.")),
    "17": (ERROR_CUSTOMER, _lt("The payment was canceled.")),
    "18": (ERROR_CUSTOMER, _lt("The cardholder disputes this payment. Please contact your bank.")),
    "19": (ERROR_CUSTOMER, _lt("The bank asks to make the payment again. Please try again.")),
    "20": (ERROR_CUSTOMER, _lt("A technical error at the bank stopped the payment. Please try again later.")),
    "21": (ERROR_CUSTOMER, _lt("The bank took no action on the payment. Please try again.")),
    "22": (ERROR_CUSTOMER, _lt("A technical error at the bank stopped the payment. Please try again later.")),
    "23": (ERROR_CUSTOMER, _lt("A technical error at the bank stopped the payment. Please try again later.")),
    "24": (ERROR_CUSTOMER, _lt("A technical error at the bank stopped the payment. Please try again later.")),
    "25": (ERROR_MERCHANT, _lt("The bank couldn't find the original record of the payment. Contact Paymob's support with the transaction ID.")),
    "26": (ERROR_MERCHANT, _lt("The bank found a duplicate record of the payment. Contact Paymob's support with the transaction ID.")),
    "27": (ERROR_MERCHANT, _lt("The bank found an error in a field of the payment. Contact Paymob's support with the transaction ID.")),
    "28": (ERROR_CUSTOMER, _lt("The bank's system is temporarily unavailable. Please try again later.")),
    "29": (ERROR_MERCHANT, _lt("The bank couldn't update its records for the payment. Contact Paymob's support with the transaction ID.")),
    "30": (ERROR_MERCHANT, _lt("The payment request had a format error. Contact Paymob's support with the transaction ID.")),
    "33": (ERROR_CUSTOMER, _lt("The card has expired. Please use another card.")),
    "34": (ERROR_CUSTOMER, _lt("The bank flagged this payment as suspected fraud. Please contact your bank.")),
    "41": (ERROR_CUSTOMER, _lt("The card was reported lost. Please contact your bank.")),
    "43": (ERROR_CUSTOMER, _lt("The card was reported stolen. Please contact your bank.")),
    "51": (ERROR_CUSTOMER, _lt("The card doesn't have enough funds for this payment.")),
    "54": (ERROR_CUSTOMER, _lt("The card has expired. Please use another card.")),
    "55": (ERROR_CUSTOMER, _lt("The PIN is incorrect. Please try again.")),
    "57": (ERROR_CUSTOMER, _lt("The card isn't allowed to make this kind of payment. Please contact your bank or use another card.")),
    "58": (ERROR_MERCHANT, _lt("The card network doesn't allow this payment on the merchant account. Ask Paymob to check the card payments of your account.")),
    "59": (ERROR_CUSTOMER, _lt("The bank flagged this payment as suspected fraud. Please contact your bank.")),
    "61": (ERROR_CUSTOMER, _lt("The payment exceeds the limit of the card. Please contact your bank or use another card.")),
    "62": (ERROR_CUSTOMER, _lt("The card is restricted. Please contact your bank or use another card.")),
    "63": (ERROR_CUSTOMER, _lt("The bank refused the payment for a security reason. Please contact your bank.")),
    "65": (ERROR_CUSTOMER, _lt("The card has made too many payments. Please contact your bank or use another card.")),
    "75": (ERROR_CUSTOMER, _lt("The PIN was entered wrongly too many times. Please contact your bank.")),
    "91": (ERROR_CUSTOMER, _lt("The bank of the card can't be reached right now. Please try again later.")),
    "96": (ERROR_CUSTOMER, _lt("A technical error stopped the payment. Please try again later.")),
    # Paymob's risk declines.
    "111": (ERROR_CUSTOMER, _lt("Payments from your country aren't accepted for this order. Please choose another payment method.")),
    "112": (ERROR_CUSTOMER, _lt("Payments from your country aren't accepted for this order. Please choose another payment method.")),
    "113": (ERROR_CUSTOMER, _lt("Payments from your network aren't accepted for this order. Please try another connection or choose another payment method.")),
    "114": (ERROR_CUSTOMER, _lt("Payments from your network aren't accepted for this order. Please try another connection or choose another payment method.")),
    "121": (ERROR_CUSTOMER, _lt("This card isn't accepted for this order. Please use another card.")),
    "122": (ERROR_CUSTOMER, _lt("This card isn't accepted for this order. Please use another card.")),
    "123": (ERROR_CUSTOMER, _lt("Cards from this country aren't accepted for this order. Please use another card.")),
    "124": (ERROR_CUSTOMER, _lt("Cards from this country aren't accepted for this order. Please use another card.")),
    "131": (ERROR_CUSTOMER, _lt("The amount is above the limit allowed for this payment method. Please choose another payment method.")),
    "141": (ERROR_MERCHANT, _lt("The amount is above the limit allowed for charges without the customer (MOTO). Ask Paymob to raise the limit.")),
    "153": (ERROR_CUSTOMER, _lt("Your email address couldn't be verified. Please check it and try again.")),
    "154": (ERROR_CUSTOMER, _lt("Disposable email addresses aren't accepted. Please use another email address.")),
    "200": (ERROR_MERCHANT, _lt("Test keys were used with a live integration ID. Check that the keys and the integration IDs of the Paymob provider are all test ones or all live ones.")),
    "201": (ERROR_CUSTOMER, _lt("The fraud checks refused this payment. Please choose another payment method.")),
    "202": (ERROR_CUSTOMER, _lt("The fraud checks refused this payment. Please choose another payment method.")),
    "301": (ERROR_CUSTOMER, _lt("The fraud checks refused this payment. Please choose another payment method.")),
    # Declines without an acquirer code.
    DECLINED_CODE: (ERROR_CUSTOMER, _lt("The payment was declined. Please try again or choose another payment method.")),
    # Errors of Paymob's APIs.
    "credentials": (ERROR_MERCHANT, _lt("Paymob refused the keys. Check the secret key, the public key and the API key of the Paymob provider, and that they belong to its country and mode (test or live).")),
    "integration": (ERROR_MERCHANT, _lt("Paymob doesn't know the integration ID, or it belongs to the other mode (test or live) or another currency. Check the integration IDs of the Paymob provider and of its payment methods, or click Sync Integrations.")),
    "missing_integration": (ERROR_MERCHANT, _lt("The payment method has no Paymob integration ID. Enter it on the payment method, or click Sync Integrations on the Paymob provider.")),
    "billing_data": (ERROR_MERCHANT, _lt("Paymob refused the customer's details: a required value is missing or invalid (first name, last name, email or phone number).")),
    "items": (ERROR_MERCHANT, _lt("Paymob refused the order lines: their amounts must add up to the amount paid.")),
    "duplicate_reference": (ERROR_MERCHANT, _lt("Paymob already has a payment with this reference.")),
    "refund_amount": (ERROR_MERCHANT, _lt("The refund is higher than the amount that can still be refunded.")),
    "capture_amount": (ERROR_MERCHANT, _lt("The capture is higher than the authorized amount.")),
    "transaction_id": (ERROR_MERCHANT, _lt("Paymob doesn't know this transaction, or it can't be captured, voided or refunded (for example, it was declined or isn't an authorization).")),
    "not_found": (ERROR_MERCHANT, _lt("Paymob has no payment for this reference yet.")),
    "server": (ERROR_MERCHANT, _lt("Paymob's servers had an error. Try again later; if it persists, contact Paymob's support.")),
}

# The messages Paymob sends for declined card payments (`data.message`) and their codes, used when
# no acquirer code comes with them.
DECLINE_MESSAGE_CODES = {
    "insufficient funds": "51",
    "invalid card number": "14",
    "expired card": "54",
    "do not honour": "5",
    "do not honor": "5",
    "lost card": "41",
    "stolen card": "43",
    "suspected fraud": "59",
    "restricted card": "62",
    "incorrect pin": "55",
}
