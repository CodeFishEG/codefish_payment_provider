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
import json
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment.tests.http_common import PaymentHttpCommon
from odoo.addons.payment_paymob_cf import const
from odoo.addons.payment_paymob_cf import utils as paymob_utils
from odoo.addons.payment_paymob_cf.controllers.main import PaymobController
from odoo.addons.payment_paymob_cf.tests.common import (
    DOCUMENTED_HMAC_STRING,
    DOCUMENTED_TOKEN_HMAC_STRING,
    PaymobCommon,
    sign,
)

RECORD = "odoo.addons.payment.models.payment_transaction.PaymentTransaction._record"
SYNC = (
    "odoo.addons.payment_paymob_cf.models.payment_transaction.PaymentTransaction."
    "_paymob_cf_sync_from_provider"
)


@tagged("post_install", "-at_install")
class TestProcessingFlows(PaymobCommon, PaymentHttpCommon):

    def _post_callback(self, body, hmac_value):
        url = self._build_url(f"{PaymobController._webhook_url}?hmac={hmac_value}")
        return self.url_open(
            url, data=json.dumps(body), headers={"Content-Type": "application/json"},
        )

    def _route_url(self, route, tx, access_token=None):
        token = access_token or self._generate_test_access_token(tx.reference, tx.partner_id.id)
        return self._build_url(f"{route}/{tx.id}/{token}")

    # === CALLBACKS === #

    @mute_logger("odoo.addons.payment_paymob_cf.controllers.main")
    def test_signed_transaction_callback_is_recorded(self):
        tx = self._create_paymob_transaction()
        body = {"type": "TRANSACTION", "obj": self.paid_transaction}
        with patch(RECORD) as record_mock:
            response = self._post_callback(body, sign(DOCUMENTED_HMAC_STRING))
        self.assertEqual(response.status_code, 200)
        record_mock.assert_called_once()
        self.assertEqual(record_mock.call_args.args[0]["id"], 192036465)
        self.assertEqual(record_mock.call_args.args[0]["order"]["id"], 217503754)
        del tx  # Matched by the order Paymob signed.

    @mute_logger("odoo.addons.payment_paymob_cf.controllers.main", "odoo.http")
    def test_transaction_callback_with_wrong_hmac_is_rejected(self):
        self._create_paymob_transaction()
        body = {"type": "TRANSACTION", "obj": self.paid_transaction}
        with patch(RECORD) as record_mock:
            response = self._post_callback(body, "0" * 128)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(record_mock.called)

    @mute_logger("odoo.addons.payment_paymob_cf.controllers.main")
    def test_callback_of_an_unknown_order_is_acknowledged(self):
        body = {"type": "TRANSACTION", "obj": self._transaction(order={"id": 1})}
        with patch(RECORD) as record_mock:
            response = self._post_callback(body, "whatever")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(record_mock.called)

    @mute_logger("odoo.addons.payment_paymob_cf.controllers.main")
    def test_private_keys_are_removed_from_callbacks(self):
        self._create_paymob_transaction()
        obj = dict(self.paid_transaction, **{const.OWN_REQUEST_KEY: "refund"})
        with patch(RECORD) as record_mock:
            self._post_callback({"type": "TRANSACTION", "obj": obj}, sign(DOCUMENTED_HMAC_STRING))
        self.assertNotIn(const.OWN_REQUEST_KEY, record_mock.call_args.args[0])

    @mute_logger("odoo.addons.payment_paymob_cf.controllers.main")
    def test_follow_up_callback_goes_to_its_own_transaction(self):
        source_tx = self._create_paymob_transaction(state="done", provider_reference="192036465")
        refund_tx = self._create_transaction(
            "redirect",
            reference="R-S00042-1",
            amount=-100.0,
            operation="refund",
            source_transaction_id=source_tx.id,
            provider_reference="579305",
        )
        obj = self._transaction(id=579305, has_parent_transaction=True)
        signature = sign(paymob_utils.get_transaction_hmac_string(obj))
        with patch.object(type(refund_tx), "_record", autospec=True) as record_mock:
            self._post_callback({"type": "TRANSACTION", "obj": obj}, signature)
        self.assertEqual(record_mock.call_args.args[0], refund_tx)

    @mute_logger("odoo.addons.payment_paymob_cf.controllers.main")
    def test_signed_card_token_is_recorded(self):
        tx = self._create_paymob_transaction(paymob_cf_order_id="593881581")
        body = {"type": "TOKEN", "obj": self.token_obj}
        with patch.object(type(tx), "_record", autospec=True) as record_mock:
            response = self._post_callback(body, sign(DOCUMENTED_TOKEN_HMAC_STRING))
        self.assertEqual(response.status_code, 200)
        recorded_tx, payload = record_mock.call_args.args
        self.assertEqual(recorded_tx, tx)
        self.assertEqual(payload["type"], "TOKEN")
        self.assertEqual(payload["obj"]["token"], self.card_token)
        self.assertEqual(payload["obj"]["expiry_year"], "38")

    @mute_logger("odoo.addons.payment_paymob_cf.controllers.main", "odoo.http")
    def test_card_token_with_wrong_hmac_is_rejected(self):
        self._create_paymob_transaction(paymob_cf_order_id="593881581")
        body = {"type": "TOKEN", "obj": dict(self.token_obj, token="stolen")}
        with patch(RECORD) as record_mock:
            response = self._post_callback(body, sign(DOCUMENTED_TOKEN_HMAC_STRING))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(record_mock.called)

    # === RETURN ROUTES === #

    @mute_logger("odoo.addons.payment_paymob_cf.controllers.main")
    def test_return_fetches_the_status_from_paymob(self):
        tx = self._create_paymob_transaction()
        with patch(SYNC, return_value=True) as sync_mock, patch(RECORD) as record_mock:
            response = self.url_open(
                self._route_url(PaymobController._return_url, tx) + "?success=true&hmac=forged",
                allow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["Location"].endswith("/payment/status"))
        self.assertTrue(sync_mock.called)
        self.assertFalse(record_mock.called)  # The redirection values are never trusted alone.

    @mute_logger("odoo.addons.payment_paymob_cf.controllers.main")
    def test_return_uses_the_signed_redirection_when_paymob_cant_be_reached(self):
        tx = self._create_paymob_transaction()
        params = {
            key: str(value).lower() if isinstance(value, bool) else str(value)
            for key, value in self.paid_transaction.items()
            if not isinstance(value, dict)
        }
        params.update({
            "order": "217503754",
            "source_data.pan": "2346",
            "source_data.sub_type": "MasterCard",
            "source_data.type": "card",
            "data.message": "Approved",
            "hmac": sign(DOCUMENTED_HMAC_STRING),
        })
        with patch(SYNC, return_value=False), patch(RECORD) as record_mock:
            self.url_open(
                self._route_url(PaymobController._return_url, tx),
                params=params,
                allow_redirects=False,
            )
        record_mock.assert_called_once()
        recorded = record_mock.call_args.args[0]
        self.assertIs(recorded["success"], True)
        self.assertEqual(recorded["order"]["id"], "217503754")
        # Unsigned or forged redirections are ignored.
        params["amount_cents"] = "1"
        with patch(SYNC, return_value=False), patch(RECORD) as record_mock:
            self.url_open(
                self._route_url(PaymobController._return_url, tx),
                params=params,
                allow_redirects=False,
            )
        self.assertFalse(record_mock.called)

    @mute_logger("odoo.http")
    def test_return_rejects_a_wrong_access_token(self):
        tx = self._create_paymob_transaction()
        with patch(SYNC) as sync_mock:
            response = self.url_open(
                self._route_url(PaymobController._return_url, tx, access_token="wrong"),
                allow_redirects=False,
            )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(sync_mock.called)

    @mute_logger("odoo.addons.payment_paymob_cf.controllers.main")
    def test_return_in_a_frame_leaves_the_frame(self):
        tx = self._create_paymob_transaction()
        with patch(SYNC, return_value=True):
            response = self.url_open(self._route_url(PaymobController._frame_return_url, tx))
        self.assertEqual(response.status_code, 200)
        self.assertIn("window.top.location.replace", response.text)
        self.assertIn('data-redirect-url="/payment/status"', response.text)

    @mute_logger("odoo.addons.payment_paymob_cf.controllers.main")
    def test_embedded_form_completion_checks_the_status(self):
        tx = self._create_paymob_transaction("direct")
        with patch(SYNC, return_value=True) as sync_mock:
            response = self.url_open(
                self._route_url(PaymobController._complete_url, tx), allow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(sync_mock.called)

    # === POLLING === #

    def test_poll_route_checks_the_status_with_paymob(self):
        tx = self._create_paymob_transaction("direct", state="pending")
        with patch(SYNC, return_value=False) as sync_mock:
            result = self.make_jsonrpc_request(PaymobController._poll_url, {
                "reference": tx.reference,
                "access_token": self._generate_test_access_token(tx.reference, tx.partner_id.id),
            })
        self.assertEqual(result["state"], "pending")
        self.assertTrue(sync_mock.called)
