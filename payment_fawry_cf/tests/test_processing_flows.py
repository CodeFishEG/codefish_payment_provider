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

from odoo.exceptions import ValidationError
from odoo.tests import JsonRpcException, tagged
from odoo.tools import mute_logger

from odoo.addons.payment.tests.http_common import PaymentHttpCommon
from odoo.addons.payment_fawry_cf.controllers.main import FawryController
from odoo.addons.payment_fawry_cf.tests.common import FawryCommon, sha256

RECORD = "odoo.addons.payment.models.payment_transaction.PaymentTransaction._record"
SEND_API_REQUEST = (
    "odoo.addons.payment.models.payment_provider.PaymentProvider._send_api_request"
)


@tagged("post_install", "-at_install")
class TestProcessingFlows(FawryCommon, PaymentHttpCommon):

    def _route_url(self, route, tx, access_token=None):
        token = access_token or self._generate_test_access_token(tx.reference, tx.partner_id.id)
        return self._build_url(f"{route}/{tx.id}/{token}")

    # === RETURN ROUTE === #

    @mute_logger("odoo.addons.payment_fawry_cf.controllers.main")
    def test_return_fetches_the_status_from_fawry(self):
        tx = self._create_transaction("redirect")
        with (
            patch(SEND_API_REQUEST, return_value=self.paid_data),
            patch(RECORD) as record_mock,
        ):
            response = self.url_open(
                self._route_url(FawryController._return_url, tx)
                + "?orderStatus=PAID&statusCode=200",
                allow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["Location"].endswith("/payment/status"))
        record_mock.assert_called_once_with(self.paid_data)  # Not the redirection values.

    @mute_logger("odoo.addons.payment_fawry_cf.controllers.main")
    def test_return_records_a_signed_charge_response(self):
        """The 3-D Secure return holds a charge response signed by Fawry: no status call needed."""
        tx = self._create_transaction("token")
        return_values = {
            "type": "ChargeResponse",
            "statusCode": "200",
            "referenceNumber": self.fawry_reference,
            "merchantRefNumber": tx.reference,
            "orderAmount": "150",
            "paymentAmount": "150",
            "fawryFees": "0",
            "orderStatus": "PAID",
            "paymentMethod": "CARD",
            "authNumber": "786838280",
        }
        return_values["signature"] = sha256(
            self.fawry_reference, tx.reference, "150.00", "150.00", "PAID", "CARD", "0.00",
            "786838280",
        )
        with (
            patch(SEND_API_REQUEST) as request_mock,
            patch(RECORD) as record_mock,
        ):
            self.url_open(
                self._route_url(FawryController._return_url, tx),
                # Values added to the URL by the customer are not recorded.
                params=dict(return_values, fawry_validation="1", fawryRefNumber="999"),
                allow_redirects=False,
            )
        self.assertFalse(request_mock.called)
        signed_values = {
            key: value for key, value in return_values.items()
            if key not in ("type", "statusCode", "signature")
        }
        record_mock.assert_called_once_with(signed_values)

        # A tampered response is not trusted: the status is fetched from Fawry instead.
        with (
            patch(SEND_API_REQUEST, return_value=self.paid_data) as request_mock,
            patch(RECORD) as record_mock,
        ):
            self.url_open(
                self._route_url(FawryController._return_url, tx),
                params=dict(return_values, orderAmount="1"),
                allow_redirects=False,
            )
        self.assertTrue(request_mock.called)
        record_mock.assert_called_once_with(self.paid_data)

    @mute_logger("odoo.addons.payment_fawry_cf.controllers.main", "werkzeug")
    def test_return_rejects_a_wrong_access_token(self):
        tx = self._create_transaction("redirect")
        with patch(RECORD) as record_mock:
            response = self.url_open(
                self._route_url(FawryController._return_url, tx, access_token="wrong"),
                allow_redirects=False,
            )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(record_mock.called)

    # === CARD PAGE ROUTE === #

    def _card_return(self, tx, **params):
        return self.url_open(
            self._route_url(FawryController._card_return_url, tx),
            params=params,
            allow_redirects=False,
        )

    @mute_logger("odoo.addons.payment_fawry_cf.controllers.main")
    def test_card_page_failure_is_recorded(self):
        self._set_integration("s2s")
        tx = self._create_transaction("redirect")
        with patch(RECORD) as record_mock:
            response = self._card_return(tx, statusCode="9919", statusDescription="Invalid date")
        self.assertEqual(response.status_code, 303)
        payload = record_mock.call_args.args[0]
        self.assertEqual(payload["orderStatus"], "FAILED")
        self.assertEqual(payload["failureReason"], "Invalid date")

    @mute_logger("odoo.addons.payment_fawry_cf.controllers.main", "werkzeug")
    def test_card_page_token_must_belong_to_the_customer(self):
        self._set_integration("s2s")
        tx = self._create_transaction("redirect")
        with patch(SEND_API_REQUEST, return_value={"cards": []}):
            response = self._card_return(tx, statusCode="200", token=self.card_token)
        self.assertEqual(response.status_code, 403)

    @mute_logger("odoo.addons.payment_fawry_cf.controllers.main")
    def test_card_page_charges_the_card_with_3ds(self):
        self._set_integration("s2s")
        tx = self._create_transaction("redirect")
        responses = [{"cards": [self.saved_card]}, self.three_ds_response]
        with (
            patch(SEND_API_REQUEST, side_effect=responses) as request_mock,
            patch(RECORD) as record_mock,
        ):
            response = self._card_return(
                tx, statusCode="200", token=self.card_token, lastFourDigits="1019",
            )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Location"], self.three_ds_url)
        self.assertEqual(request_mock.call_args.kwargs["json"]["cardToken"], self.card_token)
        self.assertEqual(record_mock.call_count, 1)
        tx.invalidate_recordset()
        self.assertEqual(tx.sudo().fawry_card_token, self.card_token)
        self.assertEqual(tx.fawry_card_data["lastFourDigits"], "1019")

        # Reloading the page doesn't charge the card twice.
        with patch(SEND_API_REQUEST) as request_mock:
            response = self._card_return(tx, statusCode="200", token=self.card_token)
        self.assertFalse(request_mock.called)

    @mute_logger("odoo.addons.payment_fawry_cf.controllers.main")
    def test_card_page_saves_the_card_without_payment(self):
        self._set_integration("s2s")
        tx = self._create_transaction("redirect", operation="validation", amount=0)
        with (
            patch(SEND_API_REQUEST, return_value={"cards": [self.saved_card]}) as request_mock,
            patch(RECORD) as record_mock,
        ):
            self._card_return(tx, statusCode="200", token=self.card_token)
        self.assertEqual(request_mock.call_count, 1)  # Only the token check, no charge.
        self.assertTrue(record_mock.call_args.args[0]["fawry_validation"])

    # === WEBHOOK === #

    @mute_logger("odoo.addons.payment_fawry_cf.controllers.main")
    def test_webhook_triggers_a_status_check(self):
        """The notification is verified, then the status is taken from Fawry, not from it."""
        self._create_transaction("redirect")
        fawry_status = dict(self.paid_data, requestId="from-fawry")
        with (
            patch(SEND_API_REQUEST, return_value=fawry_status) as request_mock,
            patch(RECORD) as record_mock,
        ):
            response = self._make_json_request(
                self._build_url(FawryController._webhook_url), data=self.paid_data,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "")
        self.assertEqual(request_mock.call_args.kwargs["params"]["merchantRefNumber"], self.reference)
        record_mock.assert_called_once_with(fawry_status)

    @mute_logger("odoo.addons.payment_fawry_cf.controllers.main")
    def test_webhook_is_sent_again_when_fawry_cant_be_reached(self):
        self._create_transaction("redirect")
        with (
            patch(SEND_API_REQUEST, side_effect=ValidationError("Timeout")),
            patch(RECORD) as record_mock,
        ):
            response = self._make_json_request(
                self._build_url(FawryController._webhook_url), data=self.paid_data,
            )
        self.assertEqual(response.status_code, 503)
        self.assertFalse(record_mock.called)

    @mute_logger("odoo.addons.payment_fawry_cf.controllers.main", "odoo.addons.payment")
    def test_webhook_ignores_unsigned_references(self):
        """Only `merchantRefNumber`, which Fawry signs, identifies the transaction."""
        self._create_transaction("redirect")
        data = dict(self.paid_data, merchantRefNum=self.reference)
        del data["merchantRefNumber"]
        with patch(SEND_API_REQUEST) as request_mock, patch(RECORD) as record_mock:
            response = self._make_json_request(
                self._build_url(FawryController._webhook_url), data=data,
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(request_mock.called)
        self.assertFalse(record_mock.called)

    @mute_logger("odoo.addons.payment_fawry_cf.controllers.main", "werkzeug")
    def test_webhook_with_wrong_signature_is_rejected(self):
        self._create_transaction("redirect")
        with patch(RECORD) as record_mock:
            response = self._make_json_request(
                self._build_url(FawryController._webhook_url),
                data=dict(self.paid_data, orderAmount=1.0),
            )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(record_mock.called)

    @mute_logger("odoo.addons.payment_fawry_cf.controllers.main", "odoo.addons.payment")
    def test_webhook_for_unknown_payment_is_acknowledged(self):
        response = self._make_json_request(
            self._build_url(FawryController._webhook_url),
            data=dict(self.paid_data, merchantRefNumber="UNKNOWN"),
        )
        self.assertEqual(response.status_code, 200)

    # === SERVER-TO-SERVER CHARGES === #

    def _charge(self, tx, **params):
        return self.make_jsonrpc_request(FawryController._charge_url, {
            "reference": tx.reference,
            "access_token": self._generate_test_access_token(tx.reference, tx.partner_id.id),
            **params,
        })

    @mute_logger("odoo.addons.payment_fawry_cf.models.payment_transaction")
    def test_reference_code_charge_route(self):
        self._set_integration("s2s")
        tx = self._create_transaction("direct", payment_method_id=self.pm_pay_at_fawry.id)
        with (
            patch(SEND_API_REQUEST, return_value=self.reference_code_data),
            patch(RECORD) as record_mock,
        ):
            result = self._charge(tx)
        self.assertEqual(result["redirect_url"], "/payment/status")
        record_mock.assert_called_once_with(self.reference_code_data)

    def test_charge_route_rejects_tampered_requests(self):
        self._set_integration("s2s")
        tx = self._create_transaction("direct", payment_method_id=self.pm_pay_at_fawry.id)
        with (
            mute_logger("odoo.http"),
            self.assertRaises(JsonRpcException),
        ):
            self.make_jsonrpc_request(FawryController._charge_url, {
                "reference": tx.reference, "access_token": "wrong",
            })

    def test_charge_route_rejects_invalid_wallet_numbers(self):
        self._set_integration("s2s")
        tx = self._create_transaction("direct", payment_method_id=self.pm_wallet.id)
        with (
            mute_logger("odoo.http"),
            patch(SEND_API_REQUEST) as request_mock,
            self.assertRaises(JsonRpcException),
        ):
            self._charge(tx, wallet_number="12345")
        self.assertFalse(request_mock.called)

    def test_charge_route_refuses_hosted_methods(self):
        self._set_integration("s2s")
        tx = self._create_transaction("direct", payment_method_id=self.pm_valu.id)
        with mute_logger("odoo.http"), self.assertRaises(JsonRpcException):
            self._charge(tx)

    @mute_logger("odoo.addons.payment_fawry_cf.models.payment_transaction")
    def test_rejected_charge_is_saved_and_reported(self):
        """The error is returned, not raised, so that the failed state is committed."""
        self._set_integration("s2s")
        tx = self._create_transaction("direct", payment_method_id=self.pm_wallet.id)
        with patch(SEND_API_REQUEST, side_effect=ValidationError("Wallet not registered")):
            result = self._charge(tx, wallet_number="01001234567")
        self.assertIn("Wallet not registered", result["error"])
        tx.invalidate_recordset()
        self.assertEqual(tx.state, "error")

    # === POLLING === #

    def test_poll_route_checks_the_status_with_fawry(self):
        tx = self._create_transaction("direct", state="pending")
        with patch.object(type(tx), "_fawry_sync_from_provider", return_value=False) as sync_mock:
            result = self.make_jsonrpc_request(FawryController._poll_url, {
                "reference": tx.reference,
                "access_token": self._generate_test_access_token(tx.reference, tx.partner_id.id),
            })
        self.assertEqual(result["state"], "pending")
        self.assertTrue(sync_mock.called)
