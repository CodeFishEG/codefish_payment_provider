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
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.payment_paymob_cf import const
from odoo.addons.payment_paymob_cf.exceptions import PaymobError
from odoo.addons.payment_paymob_cf.tests.common import PaymobCommon

SEND_API_REQUEST = (
    "odoo.addons.payment.models.payment_provider.PaymentProvider._send_api_request"
)
INQUIRE = (
    "odoo.addons.payment_paymob_cf.models.payment_provider.PaymentProvider._paymob_cf_inquire"
)


@tagged("post_install", "-at_install")
class TestPaymentTransaction(PaymobCommon):

    # === PAYMENT INTENTION === #

    def test_intention_payload(self):
        tx = self._create_transaction("redirect")
        with patch(SEND_API_REQUEST, return_value=self.intention_response) as request_mock:
            tx._paymob_cf_create_intention([4097558])
        method, endpoint = request_mock.call_args.args
        payload = request_mock.call_args.kwargs["json"]
        self.assertEqual((method, endpoint), ("POST", const.ENDPOINT_INTENTION))
        self.assertEqual(payload["amount"], 100000)
        self.assertEqual(payload["currency"], "EGP")
        self.assertEqual(payload["payment_methods"], [4097558])
        self.assertEqual(sum(item["amount"] for item in payload["items"]), 100000)
        self.assertTrue(all("_product_tmpl" not in item for item in payload["items"]))
        self.assertTrue(payload["special_reference"].startswith(f"{tx.reference}-"))
        self.assertEqual(payload["expiration"], 48 * 3600)
        self.assertTrue(payload["notification_url"].endswith("/payment/paymob_cf/webhook"))
        self.assertIn(f"/payment/paymob_cf/return/{tx.id}/", payload["redirection_url"])
        billing = payload["billing_data"]
        self.assertEqual(billing["email"], self.partner.email)
        self.assertEqual(billing["phone_number"], "+201001234567")
        self.assertEqual(billing["building"], "NA")
        self.assertNotIn("card_tokens", payload)
        self.assertNotIn("split_amounts", payload)
        # The intention is kept on the transaction.
        self.assertEqual(tx.paymob_cf_order_id, self.order_id)
        self.assertEqual(tx.paymob_cf_intention_id, "pi_test_0123456789abcdef")
        self.assertEqual(tx.sudo().paymob_cf_client_secret, "egy_csk_test_0123456789")
        self.assertEqual(tx.paymob_cf_special_reference, payload["special_reference"])

    def test_billing_data_without_phone_and_name(self):
        partner = self.env["res.partner"].create({"name": "Cher", "email": "cher@example.com"})
        tx = self._create_transaction("redirect", partner_id=partner.id)
        tx.company_id.phone = False
        billing = tx._paymob_cf_get_billing_data()
        self.assertEqual(billing["first_name"], "Cher")
        self.assertEqual(billing["last_name"], "Cher")
        self.assertEqual(billing["phone_number"], "NA")

    def test_full_page_checkout(self):
        tx = self._create_transaction("redirect")
        with patch(SEND_API_REQUEST, return_value=self.intention_response):
            processing_values = tx._get_processing_values()
        form_info = self._extract_values_from_html_form(processing_values["redirect_form_html"])
        self.assertEqual(form_info["action"], "https://accept.paymob.com/unifiedcheckout/")
        self.assertEqual(form_info["method"], "get")
        self.assertEqual(form_info["inputs"], {
            "publicKey": "egy_pk_test_dummy",
            "clientSecret": "egy_csk_test_0123456789",
        })

    def test_checkout_in_a_popup_returns_to_the_frame_route(self):
        self.paymob.paymob_cf_display_mode = "popup"
        tx = self._create_transaction("direct")
        with patch(SEND_API_REQUEST, return_value=self.intention_response) as request_mock:
            processing_values = tx._get_processing_values()
        checkout = processing_values["paymob_cf_checkout"]
        self.assertEqual(checkout["display_mode"], "popup")
        self.assertIn("clientSecret=egy_csk_test_0123456789", checkout["checkout_url"])
        self.assertIn(
            "/payment/paymob_cf/return_frame/", request_mock.call_args.kwargs["json"]["redirection_url"],
        )

    def test_embedded_card_form(self):
        self._set_embedded()
        tx = self._create_transaction("direct", tokenize=True)
        with patch(SEND_API_REQUEST, return_value=self.intention_response):
            processing_values = tx._get_processing_values()
        pixel = processing_values["paymob_cf_pixel"]
        self.assertEqual(pixel["public_key"], "egy_pk_test_dummy")
        self.assertEqual(pixel["client_secret"], "egy_csk_test_0123456789")
        self.assertEqual(pixel["payment_methods"], ["card"])
        self.assertTrue(pixel["force_save_card"])
        self.assertIn("paymob-pixel@", pixel["script_url"])
        self.assertIn(f"/payment/paymob_cf/complete/{tx.id}/", pixel["complete_url"])

    def test_refused_intention_is_explained_to_the_customer(self):
        self._set_embedded()
        tx = self._create_transaction("direct")
        error = PaymobError("staff message", code="billing_data", description="phone_number")
        with patch(SEND_API_REQUEST, side_effect=error):
            processing_values = tx._get_processing_values()
        self.assertEqual(tx.state, "error")
        self.assertEqual(tx.paymob_cf_error_code, "billing_data")
        self.assertIn("error billing_data", processing_values["paymob_cf_error"])

    def test_method_without_integration_is_refused(self):
        self.pm_valu.paymob_cf_integration_id = 0
        tx = self._create_transaction("redirect", payment_method_id=self.pm_valu.id)
        with patch(SEND_API_REQUEST) as request_mock:
            processing_values = tx._get_processing_values()
        self.assertFalse(request_mock.called)
        self.assertEqual(tx.state, "error")
        self.assertEqual(tx.paymob_cf_error_code, "missing_integration")
        # The customer is sent to the payment status page, which explains the error.
        form_info = self._extract_values_from_html_form(processing_values["redirect_form_html"])
        self.assertTrue(form_info["action"].endswith("/payment/status"))

    def test_order_lines_are_sent_as_items(self):
        if "sale_order_ids" not in self.env["payment.transaction"]._fields:
            self.skipTest("Needs the Sales app.")
        product = self.env["product.product"].create({"name": "Chair", "list_price": 400.0, "taxes_id": False})
        free_delivery = self.env["product.product"].create({"name": "Delivery", "taxes_id": False})
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "currency_id": self.currency.id,
            "order_line": [
                (0, 0, {"product_id": product.id, "product_uom_qty": 2, "price_unit": 500.0}),
                (0, 0, {"product_id": free_delivery.id, "product_uom_qty": 1, "price_unit": 0.0}),
            ],
        })
        tx = self._create_transaction("redirect", sale_order_ids=[(6, 0, order.ids)])
        items = tx._paymob_cf_get_items(100000)
        self.assertEqual(len(items), 1)  # The free line is left out.
        self.assertEqual(items[0]["amount"], 100000)
        self.assertEqual(items[0]["name"], "Chair")
        self.assertEqual(items[0]["description"], "2 x Chair")
        # Lines that don't add up to the amount paid: a single item.
        items = tx._paymob_cf_get_items(50000)
        self.assertEqual([(i["name"], i["amount"]) for i in items], [(tx.reference, 50000)])

    # === SAVED CARDS === #

    def test_saved_card_is_confirmed_on_paymob_checkout(self):
        self._set_embedded()
        token = self._create_token(provider_ref=self.card_token)
        tx = self._create_transaction("token", token_id=token.id)
        with patch(SEND_API_REQUEST, return_value=self.intention_response) as request_mock:
            tx._send_payment_request()
        payload = request_mock.call_args.kwargs["json"]
        self.assertEqual(payload["card_tokens"], [self.card_token])
        self.assertEqual(payload["payment_methods"], [4097558])
        self.assertTrue(tx.paymob_cf_redirect_url.startswith(
            "https://accept.paymob.com/unifiedcheckout/?publicKey=",
        ))
        processing_values = tx._get_processing_values()
        self.assertEqual(processing_values["paymob_cf_redirect_url"], tx.paymob_cf_redirect_url)

    def test_saved_card_is_charged_with_moto_when_the_customer_is_away(self):
        self._set_embedded()
        self.paymob.paymob_cf_moto_integration_id = 5555
        token = self._create_token(provider_ref=self.card_token)
        tx = self._create_transaction("token", token_id=token.id, operation="offline")
        pay_response = self._transaction(id=200)
        with (
            patch(SEND_API_REQUEST, side_effect=[self.intention_response, pay_response]) as request_mock,
            patch.object(type(tx), "_record") as record_mock,
        ):
            tx._send_payment_request()
        intention_call, pay_call = request_mock.call_args_list
        self.assertEqual(intention_call.kwargs["json"]["payment_methods"], [5555])
        self.assertEqual(pay_call.args[1], const.ENDPOINT_PAY)
        self.assertEqual(pay_call.kwargs["json"], {
            "source": {"identifier": self.card_token, "subtype": "TOKEN"},
            "payment_token": "ZXlKaGJHY2lPaUpJ",
        })
        record_mock.assert_called_once_with(pay_response)

    def test_moto_integration_is_needed_when_the_customer_is_away(self):
        self._set_embedded()
        token = self._create_token(provider_ref=self.card_token)
        tx = self._create_transaction("token", token_id=token.id, operation="offline")
        with patch(SEND_API_REQUEST) as request_mock, self.assertRaises(ValidationError):
            tx._send_payment_request()
        self.assertFalse(request_mock.called)

    def test_refused_saved_card_payment_is_explained(self):
        self._set_embedded()
        token = self._create_token(provider_ref=self.card_token)
        tx = self._create_transaction("token", token_id=token.id)
        error = PaymobError("staff", code="integration", description="does not exist")
        # Not `assertRaises`: its savepoint would undo the error code written before the error.
        try:
            with patch(SEND_API_REQUEST, side_effect=error):
                tx._send_payment_request()
        except ValidationError as raised:
            self.assertIn("error integration", str(raised))
        else:
            self.fail("The saved card payment should have been refused.")
        self.assertEqual(tx.paymob_cf_error_code, "integration")

    def test_card_is_saved_from_the_token_callback(self):
        self._disable_process_patcher()
        self._set_embedded()
        tx = self._create_paymob_transaction("direct", tokenize=True)
        tx._record(self.paid_transaction)
        self._run_processing()
        self.assertEqual(tx.state, "done")
        self.assertFalse(tx.token_id)  # Paymob sends the card in its own callback.
        tx._record({"type": "TOKEN", "obj": self.token_obj})
        self._run_processing()
        token = tx.token_id
        self.assertTrue(token)
        self.assertEqual(token.provider_ref, self.card_token)
        self.assertEqual(token.payment_details, "2346")
        self.assertEqual(token.paymob_cf_card_expiry, "01/38")
        self.assertEqual(token.paymob_cf_cardholder, "TEST ACCOUNT")
        self.assertEqual(token.payment_method_id, self.pm_mastercard)
        self.assertFalse(tx.sudo().paymob_cf_card_token)

    def test_card_saved_before_the_payment_is_confirmed(self):
        self._disable_process_patcher()
        self._set_embedded()
        tx = self._create_paymob_transaction("direct", tokenize=True)
        tx._record({"type": "TOKEN", "obj": self.token_obj})
        tx._record(self.paid_transaction)
        self._run_processing()
        self.assertEqual(tx.state, "done")
        self.assertEqual(tx.token_id.provider_ref, self.card_token)

    def test_card_saved_twice_is_kept_once(self):
        self._disable_process_patcher()
        self._set_embedded()
        self._create_token(provider_ref=self.card_token)
        tx = self._create_paymob_transaction("direct", tokenize=True)
        tx._record({"type": "TOKEN", "obj": self.token_obj})
        tx._record(self.paid_transaction)
        self._run_processing()
        self.assertFalse(tx.token_id)
        self.assertEqual(
            self.env["payment.token"].search_count([("provider_ref", "=", self.card_token)]), 1,
        )

    def test_expired_cards_are_left_out(self):
        self._set_embedded()
        valid = self._create_token(provider_ref="a", paymob_cf_card_expiry="01/39")
        expired = self._create_token(provider_ref="b", paymob_cf_card_expiry="01/20")
        unknown = self._create_token(provider_ref="c")
        tokens = (valid + expired + unknown)._paymob_cf_archive_expired()
        self.assertEqual(tokens, valid + unknown)
        self.assertFalse(expired.active)

    # === PROCESSING === #

    def test_paid_payment_is_done_with_its_details(self):
        self._disable_process_patcher()
        tx = self._create_paymob_transaction()
        tx._record(self.paid_transaction)
        self._run_processing()
        self.assertEqual(tx.state, "done")
        self.assertEqual(tx.provider_reference, "192036465")
        self.assertEqual(tx.payment_method_id, self.pm_mastercard)
        self.assertEqual(tx.paymob_cf_payment_source, "MasterCard 2346")

    def test_amount_mismatch_is_refused(self):
        self._disable_process_patcher()
        tx = self._create_paymob_transaction()
        tx._record(self._transaction(amount_cents=100))
        self._run_processing()
        self.assertEqual(tx.state, "error")

    def test_kiosk_payment_is_pending_with_its_reference(self):
        self._disable_process_patcher()
        tx = self._create_paymob_transaction(payment_method_id=self.pm_kiosk.id)
        tx._record(self._transaction(
            success=False, pending=True,
            source_data={"type": "aggregator", "sub_type": "AGGREGATOR", "pan": None},
            data={"bill_reference": 41234567, "message": "Pending"},
        ))
        self._run_processing()
        self.assertEqual(tx.state, "pending")
        self.assertEqual(tx.paymob_cf_bill_reference, "41234567")
        message = str(tx._get_status_message())
        self.assertIn("o_paymob_cf_instructions", message)
        self.assertIn("41234567", message)

    def test_pending_card_payment_updates_by_itself(self):
        tx = self._create_paymob_transaction(state="pending")
        message = str(tx._get_status_message())
        self.assertIn("o_paymob_cf_instructions", message)
        self.assertIn("being confirmed", message)
        self.assertNotIn("o_paymob_cf_steps", message)

    def test_declined_payment_is_explained(self):
        self._disable_process_patcher()
        tx = self._create_paymob_transaction()
        tx._record(self._transaction(
            success=False, data={"acq_response_code": "51", "message": "Insufficient Funds"},
        ))
        self._run_processing()
        self.assertEqual(tx.state, "error")
        self.assertEqual(tx.paymob_cf_error_code, "51")
        self.assertEqual(tx.paymob_cf_error_details, "Insufficient Funds")
        self.assertIn("enough funds", tx.state_message)
        self.assertIn("Paymob code 51", tx.paymob_cf_error_explanation)

    def test_authorized_payment(self):
        self._disable_process_patcher()
        tx = self._create_paymob_transaction()
        tx._record(self._transaction(is_auth=True))
        self._run_processing()
        self.assertEqual(tx.state, "authorized")

    def test_voided_payment_is_canceled(self):
        self._disable_process_patcher()
        tx = self._create_paymob_transaction(state="authorized")
        tx._record(self._transaction(is_auth=True, is_voided=True))
        self._run_processing()
        self.assertEqual(tx.state, "cancel")

    def test_follow_up_transactions_leave_the_payment_alone(self):
        self._disable_process_patcher()
        tx = self._create_paymob_transaction(state="done")
        tx._record(self._transaction(id=999, has_parent_transaction=True, is_refund=True))
        self._run_processing()
        self.assertEqual(tx.state, "done")
        self.assertNotEqual(tx.provider_reference, "999")

    # === REFUNDS, CAPTURE, VOID === #

    def test_partial_refund(self):
        self._disable_process_patcher()
        tx = self._create_paymob_transaction(state="done", provider_reference="192036465")
        refund_response = self._transaction(id=579305, amount_cents=40000, has_parent_transaction=True)
        with patch(SEND_API_REQUEST, return_value=refund_response) as request_mock:
            refund_tx = tx._refund(amount_to_refund=400.0)
        self.assertEqual(request_mock.call_args.args[1], const.ENDPOINT_REFUND)
        self.assertEqual(
            request_mock.call_args.kwargs["json"], {"transaction_id": 192036465, "amount_cents": 40000},
        )
        self._run_processing()
        self.assertEqual(refund_tx.state, "done")
        self.assertEqual(refund_tx.provider_reference, "579305")
        self.assertEqual(refund_tx.amount, -400.0)

    def test_refused_refund_is_shown(self):
        tx = self._create_paymob_transaction(state="done", provider_reference="192036465")
        error = PaymobError("The refund is higher than the amount that can still be refunded.", code="refund_amount")
        with patch(SEND_API_REQUEST, side_effect=error):
            refund_tx = tx._refund(amount_to_refund=400.0)
        self.assertEqual(refund_tx.state, "error")
        self.assertIn("still be refunded", refund_tx.state_message)

    def test_kiosk_payments_are_not_refunded(self):
        tx = self._create_paymob_transaction(
            state="done", provider_reference="1", payment_method_id=self.pm_kiosk.id,
        )
        with patch(SEND_API_REQUEST) as request_mock:
            refund_tx = tx._refund()
        self.assertFalse(request_mock.called)
        self.assertEqual(refund_tx.state, "error")

    def test_capture(self):
        self._disable_process_patcher()
        tx = self._create_paymob_transaction(state="authorized", provider_reference="590482")
        capture_response = self._transaction(id=590506, has_parent_transaction=True, is_capture=True)
        with patch(SEND_API_REQUEST, return_value=capture_response) as request_mock:
            capture_tx = tx._capture()
        self.assertEqual(request_mock.call_args.args[1], const.ENDPOINT_CAPTURE)
        self.assertEqual(
            request_mock.call_args.kwargs["json"], {"transaction_id": 590482, "amount_cents": 100000},
        )
        self._run_processing()
        self.assertEqual(capture_tx.state, "done")
        self.assertEqual(tx.state, "done")

    def test_void(self):
        self._disable_process_patcher()
        tx = self._create_paymob_transaction(state="authorized", provider_reference="590482")
        void_response = self._transaction(id=590507, has_parent_transaction=True, is_void=True)
        with patch(SEND_API_REQUEST, return_value=void_response) as request_mock:
            void_tx = tx._void()
        self.assertEqual(request_mock.call_args.args[1], const.ENDPOINT_VOID)
        self.assertEqual(request_mock.call_args.kwargs["json"], {"transaction_id": 590482})
        self._run_processing()
        self.assertEqual(void_tx.state, "cancel")
        self.assertEqual(tx.state, "cancel")

    # === STATUS CHECKS === #

    def test_status_is_fetched_from_paymob(self):
        tx = self._create_paymob_transaction()
        with (
            patch(INQUIRE, return_value=self.paid_transaction) as inquire_mock,
            patch.object(type(tx), "_record") as record_mock,
        ):
            self.assertTrue(tx._paymob_cf_sync_from_provider())
        inquire_mock.assert_called_once_with(
            order_id=self.order_id, special_reference="S00042-1-abc123",
        )
        record_mock.assert_called_once_with(self.paid_transaction)

    def test_status_of_another_order_is_ignored(self):
        tx = self._create_paymob_transaction()
        with (
            patch(INQUIRE, return_value=self._transaction(order={"id": 1})),
            patch.object(type(tx), "_record") as record_mock,
        ):
            self.assertFalse(tx._paymob_cf_sync_from_provider())
        self.assertFalse(record_mock.called)

    def test_check_status_button(self):
        tx = self._create_paymob_transaction()
        with patch(INQUIRE, return_value=None), self.assertRaises(UserError):
            tx.action_paymob_cf_sync()
        with patch(INQUIRE, return_value=self.paid_transaction), patch.object(type(tx), "_record"):
            action = tx.action_paymob_cf_sync()
        self.assertEqual(action["params"]["type"], "success")

    def test_cron_checks_unfinished_payments(self):
        pending_tx = self._create_paymob_transaction(state="pending")
        self._create_transaction("redirect", reference="S00042-2")  # No Paymob order: skipped.
        with patch.object(type(pending_tx), "_paymob_cf_sync_from_provider") as sync_mock:
            self.env["payment.transaction"]._cron_paymob_cf_sync_pending()
        self.assertEqual(sync_mock.call_count, 1)
        self.assertTrue(pending_tx.paymob_cf_last_sync)
