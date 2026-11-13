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
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment_kashier_cf import const
from odoo.addons.payment_kashier_cf import utils as kashier_utils
from odoo.addons.payment_kashier_cf.exceptions import KashierError
from odoo.addons.payment_kashier_cf.tests.common import (
    CARD_TOKEN,
    MERCHANT_ID,
    ORDER_ID,
    PAY_TX_ID,
    SESSION_ID,
    KashierCommon,
    kashier_order,
    leg,
    sign,
)

TX_PATH = "odoo.addons.payment_kashier_cf.models.payment_transaction.PaymentTransaction"
SESSION_ANSWER = {"_id": SESSION_ID, "status": "CREATED",
                  "sessionUrl": f"https://payments.kashier.io/session/{SESSION_ID}?mode=test"}


@tagged("post_install", "-at_install")
class TestCheckout(KashierCommon):

    def _rendering(self, tx):
        with self._set_answer("POST", "/v3/payment/sessions", SESSION_ANSWER):
            values = tx._get_specific_rendering_values({})
        return values, self.fake.calls_to("POST", "/v3/payment/sessions")[-1]["json"]

    def test_card_session(self):
        tx = self._create_transaction("redirect")
        values, payload = self._rendering(tx)
        self.assertEqual(values["api_url"], f"https://payments.kashier.io/session/{SESSION_ID}")
        self.assertEqual(values["url_params"], {"mode": "test"})
        self.assertEqual(tx.kashier_cf_session_id, SESSION_ID)
        self.assertEqual(payload["order"], tx.kashier_cf_order_ref)
        self.assertRegex(payload["order"], r"^S00042-1-[0-9a-f]{10}$")
        self.assertEqual(payload["amount"], "10.00")
        self.assertEqual((payload["currency"], payload["merchantId"]), ("EGP", MERCHANT_ID))
        self.assertEqual(payload["allowedMethods"], "card")
        self.assertEqual(payload["maxFailureAttempts"], 3)
        self.assertFalse(payload["failureRedirect"])
        self.assertTrue(payload["merchantRedirect"].endswith(f"/payment/kashier_cf/return/{tx.id}/" + payload["merchantRedirect"].rsplit("/", 1)[-1]))
        self.assertNotIn("//payment", payload["merchantRedirect"])
        self.assertTrue(payload["serverWebhook"].endswith("/payment/kashier_cf/webhook"))
        self.assertEqual(payload["customer"]["email"], "customer@example.com")
        self.assertTrue(payload["customer"]["reference"].startswith("cf-g-"))
        self.assertNotIn("saveCard", payload)
        self.assertNotIn("manualCapture", payload)

    def test_kashier_method_and_arabic(self):
        self.partner.lang = "ar_001" if self.env["res.lang"]._lang_get("ar_001") else self.partner.lang
        self.kashier.kashier_cf_allowed_methods = "wallet , bnpl[valu]"
        tx = self._create_transaction("redirect", payment_method_id=self.pm_kashier.id)
        _values, payload = self._rendering(tx)
        self.assertEqual(payload["allowedMethods"], "wallet,bnpl[valu]")
        self.kashier.kashier_cf_allowed_methods = False
        tx = self._create_transaction("redirect", payment_method_id=self.pm_kashier.id, reference="S00042-2")
        _values, payload = self._rendering(tx)
        self.assertNotIn("allowedMethods", payload)
        if tx.partner_lang and tx.partner_lang.startswith("ar"):
            self.assertEqual(payload["display"], "ar")

    def test_tokenize_and_manual_capture(self):
        self._enable_manual_capture()
        tx = self._create_transaction("redirect", tokenize=True)
        _values, payload = self._rendering(tx)
        self.assertEqual(payload["saveCard"], "forced")
        self.assertTrue(payload["manualCapture"])
        self.assertEqual(payload["customer"]["reference"], tx._kashier_cf_partner_reference())

    def test_customer_without_email(self):
        self.partner.email = False
        tx = self._create_transaction("redirect")
        _values, payload = self._rendering(tx)
        self.assertNotIn("email", payload["customer"])
        self.assertTrue(payload["customer"]["reference"])

    @mute_logger("odoo.addons.payment_kashier_cf.models.payment_transaction")
    def test_session_error_shows_the_customer_message(self):
        tx = self._create_transaction("redirect")
        error = KashierError("staff details", code="credentials")
        with self._set_answer("POST", "/v3/payment/sessions", error):
            values = tx._get_specific_rendering_values({})
        self.assertTrue(values["api_url"].endswith("/payment/status"))
        self.assertEqual(tx.state, "error")
        self.assertNotIn("staff details", tx.state_message)
        self.assertEqual(tx.kashier_cf_error_code, "credentials")

    def test_unexpected_page_is_refused(self):
        tx = self._create_transaction("redirect")
        with self._set_answer("POST", "/v3/payment/sessions", {"_id": "1", "sessionUrl": "https://evil.example/x"}):
            values = tx._get_specific_rendering_values({})
        self.assertTrue(values["api_url"].endswith("/payment/status"))
        self.assertEqual(tx.state, "error")


@tagged("post_install", "-at_install")
class TestStatusMapping(KashierCommon):

    def test_paid(self):
        tx = self._create_kashier_tx()
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref)]
        self._sync(tx)
        self.assertEqual(tx.state, "done")
        self.assertEqual(tx.provider_reference, PAY_TX_ID, "The pay leg, never a 3-D Secure leg.")
        self.assertEqual(tx.kashier_cf_order_id, ORDER_ID)
        self.assertEqual(tx.payment_method_id, self.pm_mastercard)
        self.assertIn("Mastercard", tx.kashier_cf_channel)

    def test_orders_map_to_their_method(self):
        for method, pm in (("wallet", self.pm_wallet), ("valu", self.pm_valu), ("basata", self.pm_kiosk),
                           ("instapay", self.pm_instapay), ("bank_installments", self.pm_installments),
                           ("someday_new", self.pm_card)):
            with self.subTest(method=method):
                tx = self._create_kashier_tx(reference=f"S-MAP-{method}")
                self.fake.orders = [kashier_order(tx.kashier_cf_order_ref, method=method, legs=[leg("pay", tx_id=f"TX-{method}")])]
                self._sync(tx)
                self.assertEqual(tx.state, "done")
                self.assertEqual(tx.payment_method_id, pm, "Unknown names keep the method the customer chose.")

    def test_other_orders_are_ignored(self):
        tx = self._create_kashier_tx()
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref + "x")]  # search is a partial match
        self.fake.session = {"status": "OPENED"}
        self._sync(tx)
        self.assertEqual(tx.state, "draft")

    @mute_logger("odoo.addons.payment.models.payment_transaction")
    def test_amount_mismatch_is_an_error(self):
        tx = self._create_kashier_tx()
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref, amount=9)]
        self._sync(tx)
        self.assertEqual(tx.state, "error")

    def test_customer_still_on_the_page(self):
        tx = self._create_kashier_tx()
        self.fake.session = {"status": "OPENED", "orderId": "NA"}
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref, status="FAILED", legs=[leg("pay", "FAILURE", code="05")])]
        self._sync(tx)
        self.assertEqual(tx.state, "draft", "Attempts are left on Kashier's page.")

    def test_declined_when_the_session_failed(self):
        tx = self._create_kashier_tx()
        self.fake.session = {"status": "FAILED"}
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref, status="FAILED", legs=[leg("pay", "FAILURE", code="51")])]
        self._sync(tx)
        self.assertEqual(tx.state, "error")
        self.assertEqual(tx.state_message, str(const.ERROR_CODES["51"][1]))
        self.assertEqual(tx.kashier_cf_error_code, "51")

    def test_unknown_outcome_stays_pending(self):
        tx = self._create_kashier_tx()
        self.fake.session = {"status": "PENDING"}
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref, status="INITIATED",
                                          legs=[leg("pay", "UNKNOWN", code="CC")])]
        self._sync(tx)
        self.assertEqual(tx.state, "pending")
        self.fake.session = {"status": "EXPIRED"}
        self._sync(tx)
        self.assertEqual(tx.state, "pending", "Never cancelled while the outcome is unknown.")

    def test_decided_failure_that_kept_the_unknown_code(self):
        """Seen live: Kashier later decides an unknown pay leg (FAILURE) but keeps its code CC."""
        tx = self._create_kashier_tx(state="pending")
        self.fake.session = {"status": "FAILED"}
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref, status="FAILED",
                                          legs=[leg("pay", "FAILURE", code="CC")])]
        self._sync(tx)
        self.assertEqual(tx.state, "error")
        self.assertEqual(tx.kashier_cf_error_code, "CC")
        self.assertNotIn("not known", tx.state_message)

    def test_staff_alerted_once(self):
        tx = self._create_kashier_tx()
        self.fake.session = {"status": "EXPIRED"}
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref, status="INITIATED",
                                          legs=[leg("pay", "UNKNOWN", code="CC")])]
        with patch(f"{TX_PATH}._kashier_cf_note_documents") as note:
            self._sync(tx)
            self._sync(tx)
            self.env["payment.transaction"]._cron_kashier_cf_sync()
            self._run_processing()
        self.assertEqual(tx.state, "pending")
        self.assertEqual(note.call_count, 1, "One note, not one per check.")
        self.assertEqual(tx.kashier_cf_alerted, "undetermined")

    def test_abandoned_3ds_is_cancelled_after_expiry(self):
        tx = self._create_kashier_tx()
        three_ds_only = [leg("3dsecure_verify", code="AUTHENTICATION_IN_PROGRESS"),
                         leg("authenticate_payer", "PENDING", code="PENDING")]
        self.fake.session = {"status": "EXPIRED"}
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref, status="INITIATED", legs=three_ds_only)]
        self._sync(tx)
        self.assertEqual(tx.state, "cancel")
        self.assertTrue(tx.kashier_cf_late_check_until)

    def test_expired_without_order(self):
        tx = self._create_kashier_tx()
        self.fake.session = {"status": "EXPIRED", "orderId": "NA"}
        self._sync(tx)
        self.assertEqual(tx.state, "cancel")

    def test_late_payment_after_cancel(self):
        tx = self._create_kashier_tx(state="cancel")
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref)]
        self._sync(tx)
        self.assertEqual(tx.state, "done")

    def test_authorized(self):
        self._enable_manual_capture()
        tx = self._create_kashier_tx()
        self.fake.session = {"status": "AUTHORIZED"}
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref, status="AUTHORIZED",
                                          legs=[leg("authorize", tx_id="TX-auth")])]
        self._sync(tx)
        self.assertEqual(tx.state, "authorized")
        self.assertEqual(tx.kashier_cf_transaction_id, "TX-auth")

    @mute_logger("odoo.addons.payment_kashier_cf.models.payment_transaction")
    def test_session_documents_of_another_order_are_ignored(self):
        tx = self._create_kashier_tx()
        self.fake.session = {"status": "PAID", "merchantOrderId": "someone-else"}
        self._sync(tx)
        self.assertEqual(tx.state, "draft")

    @mute_logger("odoo.addons.payment_kashier_cf.models.payment_transaction")
    def test_unmarked_data_are_ignored(self):
        tx = self._create_kashier_tx()
        tx._record({"reference": tx.reference, "orders": [kashier_order(tx.kashier_cf_order_ref)]})
        self._run_processing()
        self.assertEqual(tx.state, "draft")


@tagged("post_install", "-at_install")
class TestOperations(KashierCommon):

    def _paid_tx(self, **values):
        tx = self._create_kashier_tx(**values)
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref)]
        self._sync(tx)
        self.assertEqual(tx.state, "done")
        return tx

    def test_refund(self):
        tx = self._paid_tx()
        refund_answer = {"status": "SUCCESS", "response": {"status": "PARTIALLY_REFUNDED", "transactionId": "TX-ref1"}}
        with self._set_answer("PUT", f"/v3/orders/{ORDER_ID}", refund_answer):
            self.fake.orders[0]["transactions"].append(leg("refund", amount=3, tx_id="TX-ref1"))
            refund = tx._refund(amount_to_refund=3)
            self._run_processing()
        body = self.fake.calls_to("PUT", "/v3/orders/")[-1]["json"]
        self.assertEqual(body["apiOperation"], "REFUND")
        self.assertEqual(body["transaction"], {"amount": 3.0, "targetTransactionId": PAY_TX_ID})
        self.assertEqual(refund.kashier_cf_operation, "refund")
        self.assertEqual(refund.kashier_cf_transaction_id, "TX-ref1")
        self.assertEqual(refund.state, "done")
        self.assertEqual(tx.state, "done", "A refund never touches the source state.")

    @mute_logger("odoo.addons.payment.models.payment_transaction")
    def test_refund_refused(self):
        tx = self._paid_tx()
        error = KashierError("Over refund", code="over_refund")
        with self._set_answer("PUT", f"/v3/orders/{ORDER_ID}", error):
            refund = tx._refund(amount_to_refund=50)
        self.assertEqual(refund.state, "error")

    def test_refund_unknown_outcome_waits(self):
        tx = self._paid_tx()
        error = KashierError("No answer", code="timeout", unknown_outcome=True)
        with self._set_answer("PUT", f"/v3/orders/{ORDER_ID}", error):
            refund = tx._refund(amount_to_refund=3)
        self.assertEqual(refund.state, "pending")
        self.assertTrue(refund.kashier_cf_outcome_unknown)
        # The leg shows up later: the cron claims it for the waiting child.
        self.fake.orders[0]["transactions"].append(leg("refund", amount=3, tx_id="TX-late"))
        self._sync(tx)
        self.assertEqual(refund.kashier_cf_transaction_id, "TX-late")
        self.assertEqual(refund.state, "done")
        self.assertFalse(refund.kashier_cf_outcome_unknown)

    def test_capture_moves_the_source_through_core(self):
        self._enable_manual_capture()
        tx = self._create_kashier_tx()
        self.fake.session = {"status": "AUTHORIZED"}
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref, status="AUTHORIZED", legs=[leg("authorize", tx_id="TX-auth")])]
        self._sync(tx)
        self.assertEqual(tx.state, "authorized")
        answer = {"status": "SUCCESS", "response": {"status": "CAPTURED", "transactionId": "TX-cap"}}
        with self._set_answer("PUT", f"/v3/orders/{ORDER_ID}", answer):
            self.fake.session = {"status": "PAID"}
            self.fake.orders = [kashier_order(tx.kashier_cf_order_ref, legs=[leg("authorize", tx_id="TX-auth"), leg("capture", tx_id="TX-cap")])]
            capture = tx._capture()
            self._run_processing()
        self.assertEqual(self.fake.calls_to("PUT", "/v3/orders/")[-1]["json"]["apiOperation"], "CAPTURE")
        self.assertEqual(capture.state, "done")
        self.assertEqual(capture.kashier_cf_transaction_id, "TX-cap")
        self.assertEqual(tx.kashier_cf_transaction_id, "TX-auth", "The root keeps its authorization leg.")
        self.assertEqual(tx.state, "done")

    def test_refund_after_a_manual_capture(self):
        self._enable_manual_capture()
        tx = self._create_kashier_tx()
        self.fake.session = {"status": "AUTHORIZED"}
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref, status="AUTHORIZED", legs=[leg("authorize", tx_id="TX-auth")])]
        self._sync(tx)
        captured_legs = [leg("authorize", tx_id="TX-auth"), leg("capture", tx_id="TX-cap")]
        with self._set_answer("PUT", f"/v3/orders/{ORDER_ID}", {"status": "SUCCESS", "response": {"transactionId": "TX-cap"}}):
            self.fake.session = {"status": "PAID"}
            self.fake.orders = [kashier_order(tx.kashier_cf_order_ref, legs=captured_legs)]
            capture = tx._capture()
            self._run_processing()
        self.assertEqual(capture.state, "done")
        for source, refund_tx_id in ((capture, "TX-r1"), (tx, "TX-r2")):
            with self.subTest(source=source.reference), self._set_answer(
                "PUT", f"/v3/orders/{ORDER_ID}", {"status": "SUCCESS", "response": {"transactionId": refund_tx_id}},
            ):
                self.fake.orders[0]["transactions"].append(leg("refund", amount=2, tx_id=refund_tx_id))
                refund = source._refund(amount_to_refund=2)
                self._run_processing()
                body = self.fake.calls_to("PUT", "/v3/orders/")[-1]["json"]
                self.assertEqual(body["transaction"]["targetTransactionId"], "TX-cap")
                self.assertEqual(refund.state, "done", "A refund of the capture (a grandchild) is resolved too.")

    def test_void(self):
        self._enable_manual_capture()
        tx = self._create_kashier_tx()
        self.fake.session = {"status": "AUTHORIZED"}
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref, status="AUTHORIZED", legs=[leg("authorize", tx_id="TX-auth")])]
        self._sync(tx)
        answer = {"status": "SUCCESS", "response": {"status": "CANCELLED", "transactionId": "TX-void"}}
        with self._set_answer("PUT", f"/v3/orders/{ORDER_ID}", answer):
            self.fake.session = {"status": "VOIDED"}
            self.fake.orders = [kashier_order(tx.kashier_cf_order_ref, status="CANCELLED", legs=[leg("authorize", tx_id="TX-auth"), leg("void", tx_id="TX-void")])]
            void = tx._void()
            self._run_processing()
        body = self.fake.calls_to("PUT", "/v3/orders/")[-1]["json"]
        self.assertEqual((body["apiOperation"], body["transaction"]["targetTransactionId"]), ("VOID", "TX-auth"))
        self.assertEqual(void.state, "cancel")
        self.assertEqual(tx.state, "cancel")

    def test_operations_never_touch_the_root(self):
        """Once money has moved, a concurrent update of the root must not roll the operation back."""
        tx = self._paid_tx()
        answer = {"status": "SUCCESS", "response": {"status": "PARTIALLY_REFUNDED", "transactionId": "TX-r9"}}
        with self._set_answer("PUT", f"/v3/orders/{ORDER_ID}", answer), \
                patch(f"{TX_PATH}._kashier_cf_sync_from_provider") as sync:
            refund = tx._refund(amount_to_refund=1)
        sync.assert_not_called()
        self.assertFalse(self.env["payment.data"].search([("transaction_id", "=", tx.id)]))
        self.assertTrue(self.env["payment.data"].search([("transaction_id", "=", refund.id)]))
        self._run_processing()
        self.assertEqual((refund.state, refund.kashier_cf_transaction_id), ("done", "TX-r9"))

    def test_dashboard_refund_is_noted_once(self):
        tx = self._paid_tx()
        self.fake.orders[0]["transactions"].append(leg("refund", amount=2, tx_id="TX-dash"))
        self._sync(tx)
        self._sync(tx)
        self.assertEqual(tx.kashier_cf_noted_legs, "TX-dash")
        self.assertFalse(tx.child_transaction_ids)

    def test_check_status_button(self):
        tx = self._create_kashier_tx()
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref)]
        action = tx.action_kashier_cf_sync()
        self.assertEqual(action["tag"], "display_notification")
        self.kashier.kashier_cf_secret_key = False
        with self.assertRaises(UserError):
            tx.action_kashier_cf_sync()


@tagged("post_install", "-at_install")
class TestSavedCards(KashierCommon):

    def test_card_saved_from_the_order(self):
        tx = self._create_kashier_tx(tokenize=True)
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref)]
        self._sync(tx)
        token = tx.token_id
        self.assertTrue(token)
        self.assertEqual(token.provider_ref, CARD_TOKEN)
        self.assertEqual(token.payment_details, "0008")
        self.assertEqual(token.kashier_cf_expiry, "12/30")
        self.assertEqual(token.kashier_cf_customer_reference, tx._kashier_cf_partner_reference())
        self.assertEqual(token.payment_method_id, self.pm_mastercard)

    def test_card_not_saved_without_tokenize(self):
        tx = self._create_kashier_tx()
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref)]
        self._sync(tx)
        self.assertFalse(tx.token_id)
        self.assertFalse(self.env["payment.data"].search([("payload", "ilike", CARD_TOKEN)]))

    def _token(self, method=None):
        return self._create_token(payment_method_id=(method or self.pm_mastercard).id, provider_ref=CARD_TOKEN,
                                  kashier_cf_customer_reference="cf-abc")

    def test_customer_present_payment(self):
        token = self._token()
        tx = self._create_transaction("token", token_id=token.id)
        with self._set_answer("POST", "/v3/payment/sessions", SESSION_ANSWER):
            tx._send_payment_request()
        payload = self.fake.calls_to("POST", "/v3/payment/sessions")[-1]["json"]
        self.assertTrue(payload["retrieveSavedCard"])
        self.assertEqual(payload["customer"]["reference"], "cf-abc")
        self.assertEqual(payload["allowedMethods"], "card")
        self.assertEqual(tx._get_specific_processing_values({})["kashier_cf_redirect_url"], SESSION_ANSWER["sessionUrl"])

    def test_merchant_initiated_charge(self):
        token = self._token()
        tx = self._create_transaction("token", token_id=token.id, operation="offline")
        answer = {"status": "SUCCESS", "response": {"status": "CAPTURED", "orderId": ORDER_ID, "transactionId": PAY_TX_ID}}

        def paid(body):
            self.fake.orders = [kashier_order(body["order"]["reference"], legs=[leg("pay", tx_id=PAY_TX_ID)])]
            return answer

        with self._set_answer("POST", "/v3/orders", paid):
            tx._send_payment_request()
            self._run_processing()
        call = self.fake.calls_to("POST", "/v3/orders")[-1]
        body = call["json"]
        self.assertEqual(body["interactionSource"], "RECURRING")
        self.assertNotIn("securityCode", body["paymentMethod"]["card"])
        self.assertEqual(body["paymentMethod"]["card"]["cardToken"], CARD_TOKEN)
        expected = sign(kashier_utils.order_hash_string(MERCHANT_ID, body["order"]["reference"], "10.00", "EGP", "cf-abc"))
        self.assertEqual(call["headers"]["Kashier-Hash"], expected)
        self.assertRegex(body["timestamp"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        self.assertEqual(tx.state, "done")

    def test_merchant_initiated_unknown_outcome(self):
        tx = self._create_transaction("token", token_id=self._token().id, operation="offline")
        with self._set_answer("POST", "/v3/orders", KashierError("No answer", code="timeout", unknown_outcome=True)):
            tx._charge_with_token()
        self.assertEqual(tx.state, "pending")
        self.assertTrue(tx.kashier_cf_outcome_unknown)

    def test_meeza_is_not_charged_without_the_customer(self):
        tx = self._create_transaction("token", token_id=self._token(self.pm_meeza).id, operation="offline")
        tx._charge_with_token()
        self.assertEqual(tx.state, "error")
        self.assertFalse(self.fake.calls_to("POST", "/v3/orders"))

    def test_card_deleted_at_kashier_only_on_delete(self):
        token = self._token()
        token.active = False
        self.assertFalse(self.fake.calls_to("DELETE", "/v3/cards/tokens/"))
        token.active = True
        token.action_kashier_cf_delete()
        call = self.fake.calls_to("DELETE", "/v3/cards/tokens/")[-1]
        self.assertEqual(call["endpoint"], f"/v3/cards/tokens/{CARD_TOKEN}")
        self.assertEqual(call["headers"]["Kashier-Hash"], sign(f"/?tokenization={MERCHANT_ID}.cf-abc"))

    def test_refund_after_the_card_was_deleted(self):
        token = self._token()
        tx = self._create_kashier_tx(token_id=token.id)
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref)]
        self._sync(tx)
        token.active = False
        answer = {"status": "SUCCESS", "response": {"transactionId": "TX-r"}}
        with self._set_answer("PUT", f"/v3/orders/{ORDER_ID}", answer):
            refund = tx._refund(amount_to_refund=1)
        self.assertFalse(refund.token_id)
        self.assertNotEqual(refund.state, "error")


@tagged("post_install", "-at_install")
class TestCron(KashierCommon):

    def test_cron_finds_a_missed_payment(self):
        tx = self._create_kashier_tx()
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref)]
        self.env["payment.transaction"]._cron_kashier_cf_sync()
        self._run_processing()
        self.assertEqual(tx.state, "done")

    def test_cron_skips_finished_payments(self):
        tx = self._create_kashier_tx(state="done")
        self.env["payment.transaction"]._cron_kashier_cf_sync()
        self.assertFalse(self.fake.calls_to("GET", f"/v3/payment/sessions/{tx.kashier_cf_session_id}"))

    def test_unknown_outcome_expires(self):
        tx = self._create_kashier_tx()
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref)]
        self._sync(tx)
        with self._set_answer("PUT", f"/v3/orders/{ORDER_ID}", KashierError("No answer", code="timeout", unknown_outcome=True)):
            refund = tx._refund(amount_to_refund=3)
        later = fields.Datetime.now() + timedelta(hours=const.UNKNOWN_OUTCOME_HOURS + 1)
        refund._kashier_cf_expire_unknown_outcome(fields.Datetime.now())
        self.assertEqual(refund.state, "pending", "Too early to give up.")
        refund._kashier_cf_expire_unknown_outcome(later)
        self.assertEqual(refund.state, "error")
        self.assertFalse(refund.kashier_cf_outcome_unknown)

    def test_answer_found_late_is_not_expired(self):
        tx = self._create_kashier_tx()
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref)]
        self._sync(tx)
        with self._set_answer("PUT", f"/v3/orders/{ORDER_ID}", KashierError("No answer", code="timeout", unknown_outcome=True)):
            refund = tx._refund(amount_to_refund=3)
        self.fake.orders[0]["transactions"].append(leg("refund", amount=3, tx_id="TX-late"))
        tx._kashier_cf_sync_from_provider()  # Queued, not processed yet.
        refund._kashier_cf_expire_unknown_outcome(fields.Datetime.now() + timedelta(hours=3))
        self.assertEqual(refund.state, "pending")
        self._run_processing()
        self.assertEqual(refund.state, "done")

    def test_late_success_of_a_charge_without_the_customer(self):
        token = self._create_token(payment_method_id=self.pm_mastercard.id, provider_ref=CARD_TOKEN,
                                   kashier_cf_customer_reference="cf-abc")
        tx = self._create_kashier_tx(flow="token", state="error", token_id=token.id, operation="offline",
                                     kashier_cf_session_id=False)
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref)]
        with patch(f"{TX_PATH}._kashier_cf_alert") as alert:
            self._sync(tx)
        self.assertEqual(tx.state, "error", "The payment account_payment cancelled is never revived.")
        alert.assert_called_once()
        self.assertEqual(tx.kashier_cf_order_id, ORDER_ID)
