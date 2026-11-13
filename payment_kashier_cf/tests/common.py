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
import copy
import hashlib
import hmac
from contextlib import contextmanager
from unittest.mock import patch

from odoo.addons.payment.tests.common import PaymentCommon
from odoo.addons.payment_kashier_cf import const

MERCHANT_ID = "MID-1-1"
PAYMENT_API_KEY = "11111"  # The key of Kashier's documented examples.
SECRET_KEY = "test-secret"
SESSION_ID = "6af6ef0988e836a45cddc615"
ORDER_ID = "7eae5bce-2240-4677-9585-350625232d3b"
PAY_TX_ID = "TX-12345678118"
CARD_TOKEN = "6e06ddca-65fe-4ac5-b3b9-d540b2164aef"
PROVIDER_PATH = "odoo.addons.payment_kashier_cf.models.payment_provider.PaymentProvider"


def sign(message, key=PAYMENT_API_KEY):
    """Independent reference implementation of Kashier's HMAC, for the assertions."""
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


def leg(op, status="SUCCESS", amount=10, tx_id=None, code="00"):
    return {
        "operation": op, "status": status, "amount": amount, "transactionId": tx_id or f"TX-{op}",
        "transactionResponseCode": code, "transactionResponseMessage": {"en": "msg"},
    }


def kashier_order(merchant_order_id, status="CAPTURED", amount=10, legs=None, method="card", brand="Mastercard",
                  token=CARD_TOKEN, currency="EGP"):
    """A Kashier order as GET /v3/payment/orders lists it (the fields the module reads)."""
    return {
        "orderId": ORDER_ID, "merchantOrderId": merchant_order_id, "merchantId": MERCHANT_ID,
        "sessionId": SESSION_ID, "status": status, "method": method,
        "order": {"amount": amount, "currency": currency},
        "totalCapturedAmount": amount if status == "CAPTURED" else 0,
        "totalRefundedAmount": 0, "totalAuthorizedAmount": amount,
        "sourceOfFunds": {"cardInfo": {
            "cardBrand": brand, "maskedCard": "512345******0008", "cardDataToken": token,
            "expiryMonth": "12", "expiryYear": "30",
        }},
        "transactions": legs if legs is not None else [
            leg("3dsecure_verify", code="AUTHENTICATION_IN_PROGRESS", tx_id="TX-3ds1"),
            leg("authenticate_payer", status="PENDING", code="PENDING", tx_id="TX-3ds2"),
            leg("3dsecure_process_acs_result", code="APPROVED", tx_id="TX-3ds3"),
            leg("pay", tx_id=PAY_TX_ID),
        ],
    }


class FakeKashier:
    """Kashier's API as the tests need it: answers by (method, path prefix), and every call recorded."""

    def __init__(self):
        self.calls = []
        self.session = {"status": "PAID"}
        self.orders = []
        self.answers = {}
        self.order_ref = None  # merchantOrderId of the session, set by _create_kashier_tx.

    def __call__(self, provider, method, endpoint, *, params=None, data=None, json=None, reference=None, **kwargs):
        self.calls.append({
            "method": method, "endpoint": endpoint, "params": params, "json": copy.deepcopy(json),
            "reference": reference, "url": provider._build_request_url(endpoint, **kwargs),
            "headers": provider._build_request_headers(method, endpoint, json, **kwargs),
        })
        for (answer_method, prefix), answer in self.answers.items():
            if method == answer_method and endpoint.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return copy.deepcopy(answer(json) if callable(answer) else answer)
        if method == "GET" and endpoint.endswith("/payment") and endpoint.startswith("/v3/payment/sessions/"):
            data = {"sessionId": endpoint.split("/")[4], "merchantId": MERCHANT_ID, "merchantOrderId": self.order_ref,
                    "currency": "EGP", "amount": 10, "orderId": ORDER_ID, **self.session}
            return {"message": "success", "data": data}
        if method == "GET" and endpoint == "/v3/payment/orders":
            return {"status": "SUCCESS", "data": copy.deepcopy(self.orders)}
        return {}

    def calls_to(self, method, prefix):
        return [call for call in self.calls if call["method"] == method and call["endpoint"].startswith(prefix)]


class KashierCommon(PaymentCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.enable_process_patcher = False  # Kashier's snapshots are applied for real.
        cls.kashier = cls._prepare_provider(const.PROVIDER_CODE, update_values={
            "kashier_cf_merchant_id": MERCHANT_ID,
            "kashier_cf_payment_api_key": PAYMENT_API_KEY,
            "kashier_cf_secret_key": SECRET_KEY,
            "is_published": True,
        })
        cls.provider = cls.kashier
        cls.currency = cls._enable_currency("EGP")
        cls.amount = 10.0
        cls.reference = "S00042-1"
        cls.partner.write({"email": "customer@example.com", "lang": "en_US"})
        cls.pm_card = cls.env.ref("payment_kashier_cf.payment_method_card")
        cls.pm_kashier = cls.env.ref("payment_kashier_cf.payment_method_kashier")
        cls.pm_mastercard = cls.env.ref("payment_kashier_cf.payment_method_mastercard")
        cls.pm_meeza = cls.env.ref("payment_kashier_cf.payment_method_meeza")
        (cls.pm_card + cls.pm_kashier + cls.pm_mastercard + cls.pm_meeza).active = True
        cls.payment_method = cls.pm_card
        cls.payment_method_id = cls.pm_card.id
        cls.payment_method_code = "card"

    def setUp(self):
        super().setUp()
        self.fake = FakeKashier()
        self.patcher = patch(f"{PROVIDER_PATH}._send_api_request", autospec=True, side_effect=self.fake)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _create_kashier_tx(self, flow="redirect", state="draft", **values):
        tx = self._create_transaction(flow, **values)
        tx._kashier_cf_ensure_order_ref()
        self.fake.order_ref = tx.kashier_cf_order_ref
        if state != "draft":
            self._update_transaction(tx, state=state)
        if values.get("kashier_cf_session_id") is None:
            self._update_transaction(tx, kashier_cf_session_id=SESSION_ID)
        return tx

    def _enable_manual_capture(self):
        """Core refuses manual capture while a method without it (the Kashier choice) is active."""
        self.pm_kashier.active = False
        self.kashier.capture_manually = True

    def _sync(self, tx):
        """Ask the fake Kashier for the status and apply it, as the processing cron does."""
        tx._kashier_cf_sync_from_provider()
        self._run_processing()
        return tx

    @contextmanager
    def _set_answer(self, method, prefix, answer):
        self.fake.answers[method, prefix] = answer
        try:
            yield
        finally:
            self.fake.answers.pop((method, prefix), None)
