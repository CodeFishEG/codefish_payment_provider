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

_lt = LazyTranslate(__name__)

PROVIDER_CODE = "instapay_cf"
PAYMENT_METHOD_CODE = "instapay"
DEFAULT_PAYMENT_METHOD_CODES = {PAYMENT_METHOD_CODE}
CURRENCY = "EGP"

# The events recorded with `payment.transaction._record`, processed in `_apply_updates`.
EVENT_KEY = "instapay_cf_event"
EVENT_CHECKOUT = "checkout"  # The customer chose InstaPay: the payment waits for the transfer.
EVENT_CONFIRM = "confirm"  # An accountant found the money in the receiving account.
EVENT_CANCEL = "cancel"  # An accountant cancelled the payment.
EVENT_EXPIRE = "expire"  # No receipt came within the expiry delay.
EVENT_CANCEL_BY_CUSTOMER = "cancel_by_customer"  # The customer chose to pay another way.

# The "InstaPay" bank journal created in each company.
JOURNAL_CODE = "INSTA"
JOURNAL_NAME = "InstaPay"
JOURNAL_NAME_TRANSLATIONS = {"ar": "مدفوعات إنستاباي"}  # By language ISO code.
JOURNAL_CURRENCY_XMLID = "base.EGP"

# The reviewers role, created at installation with the account managers.
REVIEWER_ROLE_NAME = "InstaPay Reviewers"

# InstaPay limits (Central Bank of Egypt, October 2024): per transfer, per day and per month.
MAX_AMOUNT_PER_TRANSFER = 70000
MAX_AMOUNT_PER_DAY = 120000

# Formats of the receiving details.
IPA_PATTERN = r"^[a-z0-9][a-z0-9._-]{1,62}@instapay$"
EG_MOBILE_PATTERN = r"^01[0125]\d{8}$"  # 010 Vodafone, 011 e&, 012 Orange, 015 WE
IBAN_LENGTH = 29  # EG + 2 check digits + 4 bank + 4 branch + 17 account digits
LINK_HOSTS = {"ipn.eg"}  # InstaPay payment links: https://ipn.eg/S/<alias>/instapay/<code>
LINK_PATH_PREFIX = "/S/"
REFERENCE_PATTERN = r"^[A-Z0-9]{6,32}$"  # InstaPay references are 12 digits.

WALLET_OPERATORS = [
    ("vodafone_cash", "Vodafone Cash"),
    ("etisalat_cash", "e& cash"),
    ("orange_cash", "Orange Cash"),
    ("we_pay", "WE Pay"),
    ("bank_wallet", "Bank wallet"),
    ("other", "Other wallet"),
]

# Receipts (screenshots of the transfer) sent by customers.
RECEIPT_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB, as phones save large screenshots.
RECEIPT_MAX_REQUEST_SIZE = 12 * 1024 * 1024  # The file and the form fields.
RECEIPT_MAX_SIDE = 10000  # Pixels, before resizing.
RECEIPT_MAX_PIXELS = 20_000_000  # Checked before decoding; phone screenshots are about 5 MP.
RECEIPT_STORED_MAX_SIDE = 2560  # The long side of the stored image.
# The image formats accepted, with their MIME type. Odoo loads only some Pillow plugins
# (`Image.preinit()`), so WEBP or HEIC files can't be read.
RECEIPT_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg"}
MAX_RECEIPTS_PER_TX = 10
MIN_SECONDS_BETWEEN_RECEIPTS = 30
MAX_AMOUNT_SENT = 1000000
MAX_SENDER_NAME_LENGTH = 128
QR_MAX_SIDE = 1024

# A transfer more than this before the order, or after the receipt was sent, is flagged.
TIME_BEFORE_ORDER_TOLERANCE_MINUTES = 15
TIME_IN_FUTURE_TOLERANCE_MINUTES = 10

# The reasons an accountant gives when rejecting a receipt, and the message sent to the customer.
REJECT_REASONS = [
    ("not_received", "Transfer not found"),
    ("amount_short", "Amount lower than expected"),
    ("unreadable", "Screenshot unreadable"),
    ("already_used", "Receipt already used"),
    ("wrong_account", "Sent to another account"),
    ("still_pending", "Transfer still pending"),
    ("other", "Other reason"),
]
REJECT_MESSAGES = {
    "not_received": _lt(
        "We could not find this transfer in our account. Please check the transfer in your app and "
        "send a screenshot of the success screen, with its reference number.",
    ),
    "amount_short": _lt(
        "The amount we received is lower than the amount of your order. Please send the remaining "
        "amount and upload the receipt of that transfer.",
    ),
    "unreadable": _lt(
        "We could not read your screenshot. Please upload a clear screenshot of the whole success "
        "screen, including the amount and the reference number.",
    ),
    "already_used": _lt(
        "This receipt was already used for another payment. Please upload the receipt of the "
        "transfer you made for this order.",
    ),
    "wrong_account": _lt(
        "This transfer was sent to an account that is not ours. Please check the receiving details "
        "on this page and contact us.",
    ),
    "still_pending": _lt(
        "Your transfer is still pending at the bank. We will check it again; you can also upload a "
        "new screenshot once the transfer is successful.",
    ),
    "other": _lt("We could not confirm your transfer."),
}
