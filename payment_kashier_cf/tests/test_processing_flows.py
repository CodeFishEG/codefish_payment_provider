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
from odoo.addons.payment_kashier_cf import utils as kashier_utils
from odoo.addons.payment_kashier_cf.controllers.main import KashierController
from odoo.addons.payment_kashier_cf.tests.common import (
    KashierCommon,
    kashier_order,
    sign,
)

SYNC = "odoo.addons.payment_kashier_cf.models.payment_transaction.PaymentTransaction._kashier_cf_sync_from_provider"


@tagged("post_install", "-at_install")
class TestProcessingFlows(KashierCommon, PaymentHttpCommon):

    def _return_url(self, tx, token=None):
        token = token or self._generate_test_access_token(tx.reference, tx.partner_id.id)
        return self._build_url(f"{KashierController._return_url}/{tx.id}/{token}")

    def _webhook(self, data, signature=None):
        headers = {"Content-Type": "application/json"}
        if signature:
            headers["x-kashier-signature"] = signature
        return self.url_open(self._build_url(KashierController._webhook_url),
                             data=json.dumps({"event": "pay", "data": data}), headers=headers)

    def _webhook_data(self, tx):
        return {
            "merchantOrderId": tx.kashier_cf_order_ref, "kashierOrderId": "uuid", "amount": 10, "currency": "EGP",
            "status": "SUCCESS", "transactionId": "TX-1",
            "signatureKeys": ["merchantOrderId", "kashierOrderId", "amount", "currency", "status", "transactionId"],
        }

    def test_return_syncs_and_ignores_the_query(self):
        tx = self._create_kashier_tx()
        with patch(SYNC, return_value=True) as sync:
            response = self.url_open(self._return_url(tx) + "?paymentStatus=SUCCESS&amount=10", allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["Location"].endswith("/payment/status"))
        sync.assert_called_once()
        self.assertEqual(tx.state, "draft", "The query string never changes the state.")

    @mute_logger("odoo.http")
    def test_return_needs_the_access_token(self):
        tx = self._create_kashier_tx()
        response = self.url_open(self._return_url(tx, token="wrong"))
        self.assertEqual(response.status_code, 403)

    def test_signed_webhook_triggers_a_sync(self):
        tx = self._create_kashier_tx()
        data = self._webhook_data(tx)
        signature = sign(kashier_utils.webhook_signing_string(data))
        with patch(SYNC, return_value=True) as sync:
            response = self._webhook(data, signature)
        self.assertEqual(response.status_code, 200)
        sync.assert_called_once()
        self.assertFalse(self.env["payment.data"].search([("transaction_id", "=", tx.id)]),
                         "The webhook body is never recorded.")

    @mute_logger("odoo.addons.payment_kashier_cf.controllers.main", "odoo.http")
    def test_bad_signature_is_refused(self):
        tx = self._create_kashier_tx()
        with patch(SYNC, return_value=True) as sync:
            response = self._webhook(self._webhook_data(tx), "0" * 64)
        self.assertEqual(response.status_code, 403)
        sync.assert_not_called()

    def test_unsigned_webhook_only_triggers_a_check(self):
        tx = self._create_kashier_tx()
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref)]
        response = self._webhook(self._webhook_data(tx))
        self.assertEqual(response.status_code, 200)
        self._run_processing()
        self.assertEqual(tx.state, "done", "Paid because Kashier's authenticated answer says so.")

    @mute_logger("odoo.addons.payment_kashier_cf.controllers.main")
    def test_unknown_orders(self):
        response = self._webhook({"merchantOrderId": "someone-else-123456789", "signatureKeys": []})
        self.assertEqual(response.status_code, 200)
        tx = self._create_kashier_tx()
        own_ref = tx.kashier_cf_order_ref
        self._update_transaction(tx, kashier_cf_order_ref=False)
        response = self._webhook({"merchantOrderId": own_ref, "signatureKeys": []})
        self.assertEqual(response.status_code, 503, "An order of this database not committed yet: retry.")

    @mute_logger("odoo.addons.payment_kashier_cf.models.payment_transaction")
    def test_webhook_when_kashier_is_unreachable(self):
        tx = self._create_kashier_tx()
        with patch(SYNC, return_value=False):
            response = self._webhook(self._webhook_data(tx))
        self.assertEqual(response.status_code, 503)

    def test_no_new_check_while_an_answer_waits(self):
        tx = self._create_kashier_tx()
        tx._record({"reference": tx.reference})  # An answer of Kashier waiting for processing.
        with patch(SYNC, return_value=True) as sync:
            response = self._webhook(self._webhook_data(tx))
        self.assertEqual(response.status_code, 200)
        sync.assert_not_called()
