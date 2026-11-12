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

from odoo.addons.payment_fawry_cf import const
from odoo.addons.payment_fawry_cf.tests.common import MERCHANT_CODE, FawryCommon, sha256

SEND_API_REQUEST = (
    "odoo.addons.payment.models.payment_provider.PaymentProvider._send_api_request"
)
CHECKOUT_URL = (
    "https://atfawry.fawrystaging.com/atfawry/plugin?payment-id=dhq7qtUte20bL082js6IXg==&locale=en"
)


@tagged("post_install", "-at_install")
class TestPaymentTransaction(FawryCommon):

    def _processing_values(self, tx):
        return tx._get_processing_values()

    # === CHARGE REQUESTS === #

    def test_checkout_request_is_signed_with_sorted_items(self):
        tx = self._create_transaction("redirect")
        items = [
            {"itemId": "B", "description": "Mug", "price": 60.0, "quantity": 2},
            {"itemId": "A", "description": "Shipping", "price": 30.0, "quantity": 1},
        ]
        with patch.object(type(tx), "_fawry_get_charge_items", return_value=items):
            request = tx.with_context(payment_safe_write=True)._fawry_prepare_checkout_request()
        return_url = request["returnUrl"]
        self.assertTrue(return_url.endswith(f"/payment/fawry/return/{tx.id}/{tx._fawry_get_access_token()}"))
        self.assertEqual(request["paymentMethod"], "CARD")  # The checkout is locked on cards.
        self.assertEqual(request["customerMobile"], "01001234567")
        self.assertEqual(request["customerProfileId"], str(self.partner.id))
        self.assertEqual(
            request["signature"],
            sha256(MERCHANT_CODE, tx.reference, str(self.partner.id), return_url,
                   "A130.00", "B260.00"),
        )

    def test_all_methods_checkout_is_not_locked(self):
        tx = self._create_transaction("redirect", payment_method_id=self.pm_fawry.id)
        request = tx.with_context(payment_safe_write=True)._fawry_prepare_checkout_request()
        self.assertNotIn("paymentMethod", request)

    def test_single_charge_item_when_no_order(self):
        tx = self._create_transaction("redirect")
        self.assertEqual(
            tx._fawry_get_charge_items(),
            [{"itemId": tx.reference, "description": tx._fawry_get_description(), "price": 150.0,
              "quantity": 1}],
        )

    def test_redirect_to_the_hosted_checkout(self):
        tx = self._create_transaction("redirect")
        with patch(SEND_API_REQUEST, return_value=CHECKOUT_URL) as request_mock:
            processing_values = self._processing_values(tx)
        self.assertEqual(request_mock.call_args.args[1], const.ENDPOINT_INIT)
        form = self._extract_values_from_html_form(processing_values["redirect_form_html"])
        self.assertEqual(form["action"], "https://atfawry.fawrystaging.com/atfawry/plugin")
        self.assertEqual(form["method"], "get")
        self.assertEqual(
            form["inputs"], {"payment-id": "dhq7qtUte20bL082js6IXg==", "locale": "en"},
        )

    def test_unexpected_checkout_url_is_refused(self):
        tx = self._create_transaction("redirect")
        with patch(SEND_API_REQUEST, return_value="https://evil.example.com/pay"):
            self._processing_values(tx)
        self.assertEqual(tx.state, "error")

    def test_rejected_checkout_sets_the_error(self):
        tx = self._create_transaction("redirect")
        with patch(SEND_API_REQUEST, side_effect=ValidationError("Wrong Signature")):
            processing_values = self._processing_values(tx)
        self.assertEqual(processing_values["state"], "error")

    def test_popup_checkout_values(self):
        """The server creates the checkout session; the page only shows it."""
        self.fawry.fawry_display_mode = "side_page"
        tx = self._create_transaction("direct")
        with patch(SEND_API_REQUEST, return_value=CHECKOUT_URL) as request_mock:
            checkout = self._processing_values(tx)["fawry_checkout"]
        self.assertEqual(request_mock.call_args.args[1], const.ENDPOINT_INIT)
        self.assertEqual(checkout["checkout_url"], f"{CHECKOUT_URL}&mode=SIDE_PAGE")
        self.assertEqual(checkout["redirect_url"], CHECKOUT_URL)
        self.assertEqual(checkout["origin"], "https://atfawry.fawrystaging.com")
        self.assertEqual(checkout["display_mode"], "side_page")
        self.assertIn(f"/payment/fawry/return/{tx.id}/", checkout["return_url"])

    def test_popup_checkout_failure_is_reported(self):
        self.fawry.fawry_display_mode = "popup"
        tx = self._create_transaction("direct")
        with patch(SEND_API_REQUEST, side_effect=ValidationError("Wrong Signature")):
            processing_values = self._processing_values(tx)
        self.assertEqual(processing_values["state"], "error")
        self.assertFalse(processing_values["fawry_checkout"])

    def test_card_token_page_for_server_to_server_cards(self):
        self._set_integration("s2s")
        tx = self._create_transaction("redirect")
        form = self._extract_values_from_html_form(
            self._processing_values(tx)["redirect_form_html"],
        )
        self.assertEqual(
            form["action"], "https://atfawry.fawrystaging.com/atfawry/plugin/card-token",
        )
        self.assertEqual(form["inputs"]["accNo"], MERCHANT_CODE)
        self.assertEqual(form["inputs"]["customerProfileId"], str(self.partner.id))
        self.assertIn(f"/payment/fawry/card/{tx.id}/", form["inputs"]["returnUrl"])

    def test_server_to_server_methods_get_an_access_token(self):
        self._set_integration("s2s")
        tx = self._create_transaction("direct", payment_method_id=self.pm_pay_at_fawry.id)
        processing_values = self._processing_values(tx)
        self.assertEqual(
            processing_values["fawry_access_token"],
            self._generate_test_access_token(tx.reference, self.partner.id),
        )

    def test_reference_code_charge(self):
        self._set_integration("s2s")
        tx = self._create_transaction("direct", payment_method_id=self.pm_pay_at_fawry.id)
        with patch(SEND_API_REQUEST, return_value=self.reference_code_data) as request_mock:
            tx.with_context(payment_safe_write=True)._fawry_charge()
        self.assertEqual(request_mock.call_args.args[1], const.ENDPOINT_CHARGE)
        payload = request_mock.call_args.kwargs["json"]
        self.assertEqual(payload["paymentMethod"], "PAYATFAWRY")
        self.assertEqual(payload["amount"], "150.00")
        self.assertEqual(
            payload["signature"],
            sha256(MERCHANT_CODE, tx.reference, str(self.partner.id), "PAYATFAWRY", "150.00"),
        )

    def test_wallet_request_charge(self):
        self._set_integration("s2s")
        tx = self._create_transaction("direct", payment_method_id=self.pm_wallet.id)
        with patch(SEND_API_REQUEST, return_value={}) as request_mock:
            tx.with_context(payment_safe_write=True)._fawry_charge(wallet_number="01001234567")
        self.assertEqual(request_mock.call_args.args[1], const.ENDPOINT_WALLET_CHARGE)
        payload = request_mock.call_args.kwargs["json"]
        self.assertEqual(payload["debitMobileWalletNo"], "01001234567")
        self.assertEqual(
            payload["signature"],
            sha256(MERCHANT_CODE, tx.reference, str(self.partner.id), "MWALLET", "150.00",
                   "01001234567"),
        )
        self.assertEqual(tx.fawry_wallet_number, "01001234567")

    # === SAVED CARDS === #

    def test_saved_card_payment_asks_for_3ds(self):
        token = self._create_token(provider_ref=self.card_token, fawry_customer_profile_id="42")
        tx = self._create_transaction("token", token_id=token.id)
        with patch(SEND_API_REQUEST, return_value=self.three_ds_response) as request_mock:
            tx._charge_with_token()
        payload = request_mock.call_args.kwargs["json"]
        self.assertTrue(payload["enable3DS"])
        self.assertEqual(
            payload["signature"],
            sha256(MERCHANT_CODE, tx.reference, "42", "CARD", "150.00", self.card_token,
                   payload["returnUrl"]),
        )
        self.assertEqual(self._processing_values(tx)["fawry_redirect_url"], self.three_ds_url)

    def test_saved_card_redirect_must_be_fawry(self):
        token = self._create_token(provider_ref=self.card_token)
        tx = self._create_transaction("token", token_id=token.id)
        response = dict(self.three_ds_response, nextAction={"redirectUrl": "https://evil.io"})
        with patch(SEND_API_REQUEST, return_value=response):
            tx._charge_with_token()
        self.assertEqual(tx.state, "error")

    def test_saved_cards_are_not_charged_without_the_customer(self):
        token = self._create_token(provider_ref=self.card_token)
        tx = self._create_transaction("token", token_id=token.id, operation="offline")
        with patch(SEND_API_REQUEST) as request_mock:
            tx._charge_with_token()
        self.assertFalse(request_mock.called)
        self.assertEqual(tx.state, "error")

    def test_archiving_a_token_deletes_the_card_at_fawry(self):
        token = self._create_token(provider_ref=self.card_token, fawry_customer_profile_id="42")
        with patch.object(
            type(self.fawry), "_fawry_delete_card_token",
        ) as delete_mock:
            token.active = False
        delete_mock.assert_called_once_with("42", self.card_token)

    def test_switching_environment_keeps_the_cards_at_fawry(self):
        """Tokens archived because the provider changes environment keep their card."""
        token = self._create_token(provider_ref=self.card_token)
        with patch.object(type(self.fawry), "_fawry_delete_card_token") as delete_mock:
            self.fawry.is_live = not self.fawry.is_live
        self.assertFalse(token.active)
        self.assertFalse(delete_mock.called)

    # === PROCESSING === #

    def test_validation_flag_is_ignored_on_payments(self):
        """Only card-saving operations can be completed without a payment."""
        self._disable_process_patcher()
        tx = self._create_transaction("redirect")
        tx._record(dict(self.paid_data, orderStatus="FAILED", fawry_validation=True))
        self._run_processing()
        self.assertEqual(tx.state, "error")

    def test_reference_code_is_pending_with_instructions(self):
        self._disable_process_patcher()
        tx = self._create_transaction("direct", payment_method_id=self.pm_pay_at_fawry.id)
        tx._record(self.reference_code_data)
        self._run_processing()
        self.assertEqual(tx.state, "pending")
        self.assertEqual(tx.provider_reference, self.fawry_reference)
        self.assertEqual(tx.fawry_fees, 2.0)
        self.assertTrue(tx.fawry_payment_expiry)
        message = str(tx._get_status_message())
        self.assertIn("786 884 978", message)
        self.assertIn("o_fawry_instructions", message)

    def test_pending_card_payment_updates_by_itself(self):
        tx = self._create_transaction("token", state="pending")
        message = str(tx._get_status_message())
        self.assertIn("o_fawry_instructions", message)
        self.assertIn("Fawry is confirming your payment", message)
        self.assertNotIn("o_fawry_steps", message)

    def test_paid_payment_is_done_and_method_is_updated(self):
        self._disable_process_patcher()
        tx = self._create_transaction("redirect", payment_method_id=self.pm_fawry.id)
        tx._record(self.paid_data)
        self._run_processing()
        self.assertEqual(tx.state, "done")
        self.assertEqual(tx.payment_method_id, self.pm_card)
        self.assertEqual(tx.provider_reference, self.fawry_reference)

    def test_checkout_card_spelling_is_recognized(self):
        self._disable_process_patcher()
        tx = self._create_transaction("direct", payment_method_id=self.pm_fawry.id)
        tx._record(dict(self.paid_data, paymentMethod="PayUsingCC"))
        self._run_processing()
        self.assertEqual(tx.payment_method_id, self.pm_card)

    def test_amount_is_checked_without_fawry_fees(self):
        self._disable_process_patcher()
        tx = self._create_transaction("redirect")
        tx._record(dict(self.paid_data, paymentAmount=152.0, fawryFees=2.0))
        self._run_processing()
        self.assertEqual(tx.state, "done")

        tx_2 = self._create_transaction("redirect", reference="S00042-2")
        tx_2._record(dict(self.paid_data, merchantRefNumber="S00042-2", orderAmount=10.0))
        self._run_processing()
        self.assertEqual(tx_2.state, "error")

    def test_statuses(self):
        self._disable_process_patcher()
        for index, (status, state) in enumerate([
            ("NEW", "pending"),
            ("UNPAID", "pending"),
            ("EXPIRED", "cancel"),
            ("CANCELED", "cancel"),
            ("CANCELLED", "cancel"),
            ("FAILED", "error"),
            ("SOMETHING", "error"),
        ]):
            with self.subTest(status=status):
                reference = f"S00042-{index + 10}"
                tx = self._create_transaction("redirect", reference=reference)
                tx._record(dict(self.paid_data, merchantRefNumber=reference, orderStatus=status))
                self._run_processing()
                self.assertEqual(tx.state, state)

    def test_failure_reason_is_shown(self):
        self._disable_process_patcher()
        tx = self._create_transaction("redirect")
        tx._record(dict(
            self.paid_data, orderStatus="FAILED", failureErrorCode="99997",
            failureReason="Something went wrong",
        ))
        self._run_processing()
        self.assertIn("Something went wrong", tx.state_message)

    def test_refund_notifications_leave_the_payment_done(self):
        self._disable_process_patcher()
        tx = self._create_transaction("redirect", state="done")
        tx._record(dict(self.paid_data, orderStatus="PARTIAL_REFUNDED"))
        self._run_processing()
        self.assertEqual(tx.state, "done")

    def test_3ds_pending_charge_response(self):
        self._disable_process_patcher()
        token = self._create_token(provider_ref=self.card_token)
        tx = self._create_transaction("token", token_id=token.id)
        tx._record(dict(self.three_ds_response, merchantRefNumber=tx.reference))
        self._run_processing()
        self.assertEqual(tx.state, "pending")

    def test_card_is_saved_after_payment(self):
        self._disable_process_patcher()
        self._set_integration("s2s")
        tx = self._create_transaction("redirect", tokenize=True)
        self._update_transaction(
            tx,
            fawry_customer_profile_id="42",
            fawry_card_token=self.card_token,
            fawry_card_data={"lastFourDigits": "1019", "brand": "Visa Card"},
        )
        tx._record(self.paid_data)
        self._run_processing()
        self.assertEqual(tx.state, "done")
        self.assertTrue(tx.token_id)
        self.assertEqual(tx.token_id.provider_ref, self.card_token)
        self.assertEqual(tx.token_id.payment_details, "1019")
        self.assertEqual(tx.token_id.payment_method_id, self.pm_visa)
        self.assertEqual(tx.token_id.fawry_customer_profile_id, "42")

    def test_card_saved_twice_keeps_one_token(self):
        """Fawry returns the same token for a card saved again: no duplicate payment token."""
        self._disable_process_patcher()
        self._set_integration("s2s")
        existing_token = self._create_token(provider_ref=self.card_token)
        tx = self._create_transaction("redirect", tokenize=True)
        self._update_transaction(
            tx, fawry_customer_profile_id="42", fawry_card_token=self.card_token,
        )
        tx._record(self.paid_data)
        self._run_processing()
        self.assertEqual(tx.state, "done")
        tokens = self.env["payment.token"].search([("provider_ref", "=", self.card_token)])
        self.assertEqual(tokens, existing_token)

    def test_card_of_a_saved_token_is_kept_at_fawry(self):
        self._disable_post_process_patcher()
        self._create_token(provider_ref=self.card_token)
        tx = self._create_transaction("redirect", state="done")
        self._update_transaction(
            tx, fawry_customer_profile_id="42", fawry_card_token=self.card_token,
        )
        with patch.object(type(self.fawry), "_fawry_delete_card_token") as delete_mock:
            tx.with_context(payment_safe_write=True)._post_process()
        self.assertFalse(delete_mock.called)

    def test_brand_from_card_number_on_tokens(self):
        self._disable_process_patcher()
        self._set_integration("s2s")
        tx = self._create_transaction("redirect", tokenize=True)
        self._update_transaction(
            tx,
            fawry_customer_profile_id="42",
            fawry_card_token=self.card_token,
            fawry_card_data={"lastFourDigits": "0008", "firstSixDigits": "512345",
                             "brand": "BMISCARD"},
        )
        tx._record(self.paid_data)
        self._run_processing()
        self.assertEqual(
            tx.token_id.payment_method_id,
            self.env.ref("payment_fawry_cf.payment_method_mastercard"),
        )

    def test_card_used_once_is_deleted_at_fawry(self):
        self._disable_post_process_patcher()
        tx = self._create_transaction("redirect", state="done")
        self._update_transaction(
            tx, fawry_customer_profile_id="42", fawry_card_token=self.card_token,
        )
        with patch.object(type(self.fawry), "_fawry_delete_card_token") as delete_mock:
            tx.with_context(payment_safe_write=True)._post_process()
        delete_mock.assert_called_once_with("42", self.card_token)
        self.assertFalse(tx.sudo().fawry_card_token)

    def test_validation_saves_the_card(self):
        self._disable_process_patcher()
        self._set_integration("s2s")
        tx = self._create_transaction("redirect", operation="validation", amount=0, tokenize=True)
        self._update_transaction(
            tx, fawry_customer_profile_id="42", fawry_card_token=self.card_token,
            fawry_card_data={"lastFourDigits": "1019", "brand": "Visa Card"},
        )
        tx._record({"merchantRefNumber": tx.reference, "fawry_validation": True})
        self._run_processing()
        self.assertEqual(tx.state, "done")
        self.assertEqual(tx.token_id.provider_ref, self.card_token)

    # === REFUNDS AND CANCELLATIONS === #

    def test_partial_refund(self):
        self._disable_process_patcher()
        tx = self._create_transaction(
            "redirect", state="done", provider_reference=self.fawry_reference,
        )
        response = {"type": "ResponseDataModel", "statusCode": 200}
        with patch(SEND_API_REQUEST, return_value=response) as request_mock:
            tx._refund(amount_to_refund=50.0)
        payload = request_mock.call_args.kwargs["json"]
        refund_tx = tx.child_transaction_ids
        self.assertEqual(payload["referenceNumber"], self.fawry_reference)
        self.assertEqual(payload["refundAmount"], "50.00")
        self.assertEqual(
            payload["signature"],
            sha256(MERCHANT_CODE, self.fawry_reference, "50.00", refund_tx.reference),
        )
        self._run_processing()
        self.assertEqual(refund_tx.state, "done")

    def test_rejected_refund_sets_the_error(self):
        tx = self._create_transaction(
            "redirect", state="done", provider_reference=self.fawry_reference,
        )
        with patch(SEND_API_REQUEST, side_effect=ValidationError("Too much")):
            tx._refund(amount_to_refund=500.0)
        self.assertEqual(tx.child_transaction_ids.state, "error")

    def test_cancel_unpaid_reference_code(self):
        tx = self._create_transaction(
            "direct", state="pending", provider_reference=self.fawry_reference,
            payment_method_id=self.pm_pay_at_fawry.id,
        )
        with (
            patch(SEND_API_REQUEST, return_value={}) as request_mock,
            patch.object(type(tx), "_fawry_sync_from_provider") as sync_mock,
        ):
            tx._fawry_cancel_unpaid()
        payload = request_mock.call_args.kwargs["json"]
        self.assertEqual(
            payload["signature"], sha256(self.fawry_reference, MERCHANT_CODE, "en-gb"),
        )
        self.assertTrue(sync_mock.called)

    def test_paid_payments_cannot_be_canceled(self):
        tx = self._create_transaction("redirect", state="done")
        with self.assertRaises(UserError):
            tx._fawry_cancel_unpaid()

    # === STATUS SYNCHRONIZATION === #

    def test_sync_records_the_status(self):
        tx = self._create_transaction("redirect")
        with (
            patch(SEND_API_REQUEST, return_value=self.paid_data),
            patch(
                "odoo.addons.payment.models.payment_transaction.PaymentTransaction._record",
            ) as record_mock,
        ):
            self.assertTrue(tx._fawry_sync_from_provider())
        record_mock.assert_called_once_with(self.paid_data)

    def test_sync_records_the_failure_fawry_has_no_order_for(self):
        tx = self._create_transaction("redirect")
        with (
            patch.object(type(self.fawry), "_fawry_get_payment_status", return_value=None),
            patch(
                "odoo.addons.payment.models.payment_transaction.PaymentTransaction._record",
            ) as record_mock,
        ):
            self.assertTrue(tx._fawry_sync_from_provider(
                {"statusCode": "99997", "statusDescription": "Something went wrong"},
            ))
            self.assertFalse(tx._fawry_sync_from_provider({}))
        self.assertEqual(record_mock.call_args_list[0].args[0]["orderStatus"], "FAILED")
        self.assertEqual(record_mock.call_count, 1)

    def test_cron_checks_pending_payments(self):
        tx = self._create_transaction("direct", state="pending")
        done_tx = self._create_transaction("redirect", state="done", reference="S00042-9")
        recent_draft = self._create_transaction("redirect", reference="S00042-7")
        old_draft = self._create_transaction("redirect", reference="S00042-8")
        self.env.cr.execute(
            "UPDATE payment_transaction SET create_date = now() - interval '3 days' WHERE id = %s",
            [old_draft.id],
        )
        with patch.object(type(tx), "_fawry_sync_from_provider", autospec=True) as sync_mock:
            self._run_cron_job("payment_fawry_cf.cron_sync_pending_payments")
        synced = {call.args[0] for call in sync_mock.call_args_list}
        self.assertIn(tx, synced)
        self.assertIn(recent_draft, synced)
        self.assertNotIn(done_tx, synced)
        self.assertNotIn(old_draft, synced)  # Abandoned checkouts don't crowd out pending ones.

    def test_card_of_another_company_is_kept_at_fawry(self):
        """Fawry gives the same token to a card saved under the same account by another company."""
        self._disable_post_process_patcher()
        other_company = self.env["res.company"].create({"name": "Other Company"})
        other_provider = self.fawry.copy({"company_id": other_company.id})
        other_provider.fawry_merchant_code = self.fawry.fawry_merchant_code
        other_card = other_provider.payment_method_ids.filtered(lambda m: m.code == "card")[:1]
        self._create_token(
            provider_id=other_provider.id,
            payment_method_id=(other_card or self.pm_card).id,
            provider_ref=self.card_token,
        )
        tx = self._create_transaction("redirect", state="done")
        self._update_transaction(
            tx, fawry_customer_profile_id="42", fawry_card_token=self.card_token,
        )
        with patch.object(type(self.fawry), "_fawry_delete_card_token") as delete_mock:
            tx.with_context(payment_safe_write=True)._post_process()
        self.assertFalse(delete_mock.called)
