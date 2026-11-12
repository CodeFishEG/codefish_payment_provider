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

# Keys redacted from the payment logs. The secure key itself is never sent to Fawry.
SENSITIVE_KEYS = {"cardToken", "token", "cardHolderName"}
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
ENDPOINT_INSTALLMENT_PLANS = "/ECommerceWeb/api/merchant/installment-plans"

# The bank journal created for the Fawry provider of each company, where Fawry payments are posted.
JOURNAL_CODE = "FAWRY"
JOURNAL_NAME = "Fawry Pay"
JOURNAL_NAME_TRANSLATIONS = {"ar": "مدفوعات فورى"}  # By language ISO code.
JOURNAL_CURRENCY_XMLID = "base.EGP"

# Fawry's secure page where customers save a card.
CARD_TOKEN_PLUGIN_PATH = "/atfawry/plugin/card-token"

# How long a saved card checked at Fawry is trusted before it is checked again, in minutes. The
# cards are checked when they are shown to the customer.
CARD_CHECK_INTERVAL_MINUTES = 10

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

# === ERROR CODES === #

# Who an error is about. Errors about the customer's card or bank are shown to the customer as they
# are; errors about the merchant's Fawry account are only explained to the staff, the customer gets
# a neutral message instead.
ERROR_CUSTOMER = "customer"
ERROR_MERCHANT = "merchant"

# Fawry's error codes and what they mean: the codes of Fawry's Error Codes page
# (https://developers.fawrystaging.com/fawrypay/errorCodes), then the `statusCode` values of the
# APIs used by the module, then codes met on Fawry's platform.
ERROR_CODES = {
    # Card and issuing bank errors (Error Codes page).
    "99901": (ERROR_CUSTOMER, _lt("The bank that issued the card refused the payment. Please contact your bank or use another card.")),
    "99903": (ERROR_MERCHANT, _lt("The payment details were refused, or the card terminal of the merchant account is inactive. Ask Fawry to check the card payments of your account.")),
    "99904": (ERROR_CUSTOMER, _lt("The bank refused the payment because the card is reported lost or stolen. Please contact your bank.")),
    "99905": (ERROR_CUSTOMER, _lt("The bank won't accept this payment. Please use another card or contact your bank.")),
    "99906": (ERROR_CUSTOMER, _lt("The bank flagged the card as fraudulent. Please contact your bank.")),
    "99907": (ERROR_CUSTOMER, _lt("The bank declined the payment. Please contact your bank.")),
    "99908": (ERROR_CUSTOMER, _lt("This payment can't be made right now. Please try again later or use another card.")),
    "99910": (ERROR_CUSTOMER, _lt("This payment can't be made right now. Please try again later or use another card.")),
    "99912": (ERROR_MERCHANT, _lt("Fawry couldn't process the card because the card payments of the merchant account aren't set up correctly. Ask Fawry to check them.")),
    "99913": (ERROR_MERCHANT, _lt("The amount of the payment was refused as invalid.")),
    "99914": (ERROR_CUSTOMER, _lt("The card number isn't valid. Please check it and try again.")),
    "99915": (ERROR_CUSTOMER, _lt("The bank of this card doesn't exist. Please check the card number and try again.")),
    "99922": (ERROR_CUSTOMER, _lt("The bank didn't respond. Please try again.")),
    "99930": (ERROR_MERCHANT, _lt("The merchant account isn't set up for this payment. Ask Fawry to check your account.")),
    "99931": (ERROR_CUSTOMER, _lt("The bank doesn't allow this card for this kind of payment. Please use another card.")),
    "99934": (ERROR_CUSTOMER, _lt("The bank declined the payment because it suspects fraud on this card. Please contact your bank.")),
    "99937": (ERROR_CUSTOMER, _lt("The bank refused the payment. Please contact your bank.")),
    "99939": (ERROR_CUSTOMER, _lt("The bank refused the payment. Please contact your bank.")),
    "99941": (ERROR_CUSTOMER, _lt("The card is reported lost. Please contact your bank.")),
    "99942": (ERROR_CUSTOMER, _lt("This card can't be used for this kind of payment. Please use another card.")),
    "99943": (ERROR_CUSTOMER, _lt("The card is reported stolen. Please contact your bank.")),
    "99949": (ERROR_CUSTOMER, _lt("The bank doesn't allow this card for online payments. Please contact your bank or use another card.")),
    "99951": (ERROR_CUSTOMER, _lt("The card doesn't have enough funds for this payment.")),
    "99954": (ERROR_CUSTOMER, _lt("The card has expired. Please use another card.")),
    "99955": (ERROR_CUSTOMER, _lt("The card PIN is incorrect. Please try again.")),
    "99956": (ERROR_CUSTOMER, _lt("The bank says this card number doesn't exist. Please use another card.")),
    "99957": (ERROR_CUSTOMER, _lt("The bank doesn't allow this card for this kind of payment. Please use another card.")),
    "99958": (ERROR_MERCHANT, _lt("The card processing account of the merchant isn't set up correctly. Ask Fawry to check it.")),
    "99959": (ERROR_CUSTOMER, _lt("The bank declined the payment because it looks fraudulent. Please contact your bank.")),
    "99961": (ERROR_CUSTOMER, _lt("The payment would exceed the limit of the card.")),
    "99962": (ERROR_CUSTOMER, _lt("The card can't be used in this region or country.")),
    "99963": (ERROR_CUSTOMER, _lt("The bank declined the payment because it failed a security check. Please contact your bank.")),
    "99965": (ERROR_CUSTOMER, _lt("The payment would exceed the usual spending limit of the card. Please contact your bank.")),
    "99967": (ERROR_CUSTOMER, _lt("The bank declined the payment because the card is suspected to be counterfeit. Please contact your bank.")),
    "99970": (ERROR_CUSTOMER, _lt("The bank refused the payment. Please contact your bank.")),
    "99971": (ERROR_CUSTOMER, _lt("The bank refused the payment because the card PIN was never changed. Please contact your bank.")),
    "99975": (ERROR_CUSTOMER, _lt("The PIN was entered wrongly too many times. Please contact your bank.")),
    "99976": (ERROR_CUSTOMER, _lt("This payment can't be made right now. Please try again later or use another card.")),
    "99977": (ERROR_CUSTOMER, _lt("This payment can't be made right now. Please try again later or use another card.")),
    "99978": (ERROR_CUSTOMER, _lt("This payment can't be made right now. Please try again later or use another card.")),
    "99979": (ERROR_CUSTOMER, _lt("This payment can't be made right now. Please try again later or use another card.")),
    "99980": (ERROR_CUSTOMER, _lt("This payment can't be made right now. Please try again later or use another card.")),
    "99981": (ERROR_CUSTOMER, _lt("This payment can't be made right now. Please try again later or use another card.")),
    "99984": (ERROR_CUSTOMER, _lt("The payment failed on the side of the bank. Please contact your bank.")),
    "99985": (ERROR_CUSTOMER, _lt("The payment failed because of its amount. Please try again with another amount or another card.")),
    "99986": (ERROR_CUSTOMER, _lt("A technical error at the bank stopped the payment. Please try again later.")),
    "99987": (ERROR_CUSTOMER, _lt("This payment can't be made right now. Please try again later or use another card.")),
    "99988": (ERROR_CUSTOMER, _lt("A technical error at the bank stopped the payment. Please try again later.")),
    "99989": (ERROR_CUSTOMER, _lt("A technical error at the bank stopped the payment. Please try again later.")),
    "99991": (ERROR_CUSTOMER, _lt("Fawry couldn't reach the bank to approve the payment. Please try again.")),
    "99992": (ERROR_CUSTOMER, _lt("The payment couldn't be sent to the bank. Please try again.")),
    "99994": (ERROR_CUSTOMER, _lt("A technical error stopped the payment. Please try again later.")),
    "99996": (ERROR_CUSTOMER, _lt("A technical error stopped the payment. Please try again later.")),
    "21004": (ERROR_MERCHANT, _lt("Fawry couldn't validate the amount of the payment.")),
    "21010": (ERROR_CUSTOMER, _lt("The amount is above the limit allowed for this payment method. Please choose another payment method.")),
    "55006": (ERROR_CUSTOMER, _lt("This card isn't allowed for this payment. Please use another card.")),
    # API status codes (FawryPay API pages).
    "9901": (ERROR_MERCHANT, _lt("The merchant code is missing or invalid. Check the Merchant Code of the Fawry provider.")),
    "9903": (ERROR_MERCHANT, _lt("Fawry couldn't process the request. Check the Merchant Code of the Fawry provider; if it is right, the payment uses an option Fawry hasn't enabled on the account.")),
    "9910": (ERROR_CUSTOMER, _lt("The mobile number is missing or invalid. Please check your phone number and try again.")),
    "9919": (ERROR_CUSTOMER, _lt("The card isn't valid or its expiry date is wrong. Please use another card.")),
    "9935": (ERROR_MERCHANT, _lt("The refund is higher than the amount paid.")),
    "9938": (ERROR_MERCHANT, _lt("Fawry has no order with this reference.")),
    "9944": (ERROR_MERCHANT, _lt("Fawry found the request invalid: a required value is missing, such as the customer profile or the card token, or a value isn't accepted, such as an installment plan.")),
    "9946": (ERROR_MERCHANT, _lt("The signature is wrong. Check the Secure Key of the Fawry provider, and that Live matches the environment of your credentials.")),
    "9954": (ERROR_MERCHANT, _lt("The order isn't paid.")),
    "9984": (ERROR_MERCHANT, _lt("The order is already canceled.")),
    # Codes met on Fawry's platform but missing from its documentation.
    "9985": (ERROR_MERCHANT, _lt("The amounts shared between the accounts don't add up to the price of an item (Payment Split).")),
    "8000453": (ERROR_MERCHANT, _lt("A sub-account of the Payment Split doesn't exist at Fawry. Check the sub-account codes in the Payment Split tab of the Fawry provider.")),
    "10027": (ERROR_MERCHANT, _lt("Fawry doesn't know this saved card: it may have been deleted already.")),
    "10044": (ERROR_MERCHANT, _lt("Card payments without 3-D Secure aren't enabled on the merchant account.")),
}
