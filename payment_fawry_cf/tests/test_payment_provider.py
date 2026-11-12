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
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.payment_fawry_cf import const
from odoo.addons.payment_fawry_cf.tests.common import MERCHANT_CODE, FawryCommon, sha256

SEND_API_REQUEST = (
    "odoo.addons.payment.models.payment_provider.PaymentProvider._send_api_request"
)


def _response(content, content_type="application/json", status=200):
    response = MagicMock()
    response.status_code = status
    response.headers = {"Content-Type": content_type}
    response.text = content if isinstance(content, str) else json.dumps(content)
    response.json.return_value = content
    return response


@tagged("post_install", "-at_install")
class TestPaymentProvider(FawryCommon):

    def test_default_payment_methods_are_activated(self):
        active_codes = set(self.fawry.payment_method_ids.filtered("active").mapped("code"))
        for code in const.DEFAULT_PAYMENT_METHOD_CODES | {"visa", "mastercard", "meeza"}:
            self.assertIn(code, active_codes)

    def test_only_egp_is_supported(self):
        self.assertEqual(self.fawry.available_currency_ids.mapped("name"), ["EGP"])

    def test_cards_can_only_be_saved_with_the_server_to_server_integration(self):
        self.assertEqual(self.fawry.support_refund, "partial")
        self.assertFalse(self.fawry.support_tokenization)
        self._set_integration("s2s")
        self.assertTrue(self.fawry.support_tokenization)
        self.assertTrue(self.fawry.allow_tokenization)

    def test_switching_to_the_hosted_checkout_stops_saving_cards(self):
        self._set_integration("s2s")
        self.fawry.fawry_integration = "express"
        self.assertFalse(self.fawry.allow_tokenization)

    def test_flows(self):
        self.assertEqual(self.fawry._fawry_get_flow("card"), const.FLOW_HOSTED)
        self.assertEqual(self.fawry._fawry_get_flow("pay_at_fawry"), const.FLOW_HOSTED)
        self._set_integration("s2s")
        self.assertEqual(self.fawry._fawry_get_flow("card"), const.FLOW_CARD_TOKEN)
        self.assertEqual(
            self.fawry._fawry_get_flow("dummy", is_validation=True), const.FLOW_CARD_TOKEN,
        )
        for code in ("pay_at_fawry", "mobile_wallet_eg", "myfawry"):
            self.assertEqual(self.fawry._fawry_get_flow(code), const.FLOW_S2S_CHARGE)
        for code in ("valu", "forsa", "souhoola", "fawry", "fawry_yellow_card"):
            self.assertEqual(self.fawry._fawry_get_flow(code), const.FLOW_HOSTED)

    def test_inline_form_values(self):
        self.fawry.fawry_display_mode = "popup"
        self.assertEqual(
            json.loads(self.fawry._fawry_get_inline_form_values("card")),
            {"flow": "hosted", "display_mode": "popup"},
        )
        self._set_integration("s2s")
        self.assertEqual(
            json.loads(self.fawry._fawry_get_inline_form_values("card")),
            {"flow": "card_token", "display_mode": "redirect"},
        )

    def test_api_urls_follow_the_environment(self):
        self.fawry.is_live = False
        self.assertEqual(
            self.fawry._build_request_url(const.ENDPOINT_STATUS),
            f"https://atfawry.fawrystaging.com{const.ENDPOINT_STATUS}",
        )
        self.fawry.is_live = True
        self.assertEqual(
            self.fawry._build_request_url(const.ENDPOINT_STATUS),
            f"https://www.atfawry.com{const.ENDPOINT_STATUS}",
        )

    def test_business_errors_in_the_body_are_raised(self):
        response = _response({"statusCode": 10047, "statusDescription": "Not enabled"})
        with self.assertRaisesRegex(ValidationError, "Not enabled"):
            self.fawry._parse_response_content(response)

    def test_plain_text_and_empty_responses(self):
        url = "https://atfawry.fawrystaging.com/atfawry/plugin?payment-id=abc%3D%3D&locale=en"
        self.assertEqual(self.fawry._parse_response_content(_response(url, "text/plain")), url)
        self.assertEqual(self.fawry._parse_response_content(_response("", "text/plain")), {})

    def test_error_messages_are_extracted(self):
        response = _response(
            {"errorId": "x", "code": "9901", "reason": "VALIDATION", "description": "Wrong"},
            status=400,
        )
        self.assertEqual(self.fawry._parse_response_error(response), "Wrong (code 9901)")
        response = _response({"statusCode": 9935, "statusDescription": "Too much"}, status=400)
        self.assertEqual(self.fawry._parse_response_error(response), "Too much (code 9935)")

    def test_payment_status_is_signed(self):
        with patch(SEND_API_REQUEST, return_value={"orderStatus": "PAID"}) as request_mock:
            self.fawry._fawry_get_payment_status("S00042-1")
        params = request_mock.call_args.kwargs["params"]
        self.assertEqual(params["merchantCode"], MERCHANT_CODE)
        self.assertEqual(params["signature"], sha256(MERCHANT_CODE, "S00042-1"))

    def test_unknown_orders_have_no_status(self):
        error = ValidationError("The payment provider rejected the request.\nNOT FOUND (code 9938)")
        with patch(SEND_API_REQUEST, side_effect=error):
            self.assertIsNone(self.fawry._fawry_get_payment_status("S00042-1"))

    def test_connection_test_accepts_unknown_order(self):
        with patch.object(type(self.fawry), "_fawry_get_payment_status", return_value=None):
            action = self.fawry.action_fawry_test_connection()
        self.assertEqual(action["params"]["type"], "success")

    def test_connection_test_reports_wrong_credentials(self):
        error = ValidationError("Invalid Merchant Code Or Wrong Signature (code 9901)")
        with (
            patch.object(type(self.fawry), "_fawry_get_payment_status", side_effect=error),
            self.assertRaises(UserError),
        ):
            self.fawry.action_fawry_test_connection()

    def test_card_tokens_are_listed_and_deleted_with_signatures(self):
        with patch(SEND_API_REQUEST, return_value={"cards": [self.saved_card]}) as request_mock:
            cards = self.fawry._fawry_list_card_tokens("42")
        self.assertEqual(cards, [self.saved_card])
        self.assertEqual(
            request_mock.call_args.kwargs["params"]["signature"], sha256(MERCHANT_CODE, "42"),
        )
        with patch(SEND_API_REQUEST, return_value={}) as request_mock:
            self.fawry._fawry_delete_card_token("42", self.card_token)
        self.assertEqual(request_mock.call_args.args[0], "DELETE")
        self.assertEqual(
            request_mock.call_args.kwargs["params"]["signature"],
            sha256(MERCHANT_CODE, "42", self.card_token),
        )

    def test_only_fawry_urls_are_trusted(self):
        self.fawry.is_live = False
        self.assertTrue(self.fawry._fawry_is_own_url(self.three_ds_url))
        self.assertFalse(self.fawry._fawry_is_own_url("https://atfawry.fawrystaging.com.evil.io/x"))
        self.assertFalse(self.fawry._fawry_is_own_url("https://www.atfawry.com/x"))

    def test_wallet_prefill(self):
        self.assertEqual(self.fawry._fawry_get_wallet_prefill(self.partner.id), "01001234567")
        public_partner = self.env.ref("base.public_partner")
        self.assertEqual(self.fawry._fawry_get_wallet_prefill(public_partner.id), "")
        self.assertEqual(self.fawry._fawry_get_wallet_prefill(None), "")
