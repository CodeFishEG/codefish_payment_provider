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
from odoo.tools import BinaryBytes

from odoo.addons.payment_paymob_cf import const
from odoo.addons.payment_paymob_cf.exceptions import PaymobError
from odoo.addons.payment_paymob_cf.models import payment_provider as provider_module
from odoo.addons.payment_paymob_cf.tests.common import PaymobCommon

SEND_API_REQUEST = (
    "odoo.addons.payment.models.payment_provider.PaymentProvider._send_api_request"
)
GET_INTEGRATIONS = (
    "odoo.addons.payment_paymob_cf.models.payment_provider.PaymentProvider."
    "_paymob_cf_get_integrations"
)


@tagged("post_install", "-at_install")
class TestPaymentProvider(PaymobCommon):

    def setUp(self):
        super().setUp()
        provider_module._AUTH_TOKENS.clear()

    # === COUNTRIES === #

    def test_each_country_has_its_platform_and_currency(self):
        for country, values in const.COUNTRIES.items():
            self.paymob.paymob_cf_country = country
            self.assertEqual(self.paymob._paymob_cf_get_api_url(), values["api_url"])
            self.assertEqual(self.paymob.available_currency_ids.name, values["currency"])
            self.assertEqual(self.paymob._get_supported_currencies().name, values["currency"])

    def test_checkout_url(self):
        self.paymob.paymob_cf_country = "SA"
        self.assertEqual(
            self.paymob._paymob_cf_get_checkout_url("sau_csk_test_1"),
            "https://ksa.paymob.com/unifiedcheckout/?publicKey=egy_pk_test_dummy"
            "&clientSecret=sau_csk_test_1",
        )

    # === REQUESTS === #

    def test_requests_are_authenticated_with_the_right_key(self):
        headers = self.paymob._build_request_headers("POST", const.ENDPOINT_INTENTION, {})
        self.assertEqual(headers["Authorization"], "Token egy_sk_test_dummy")
        headers = self.paymob._build_request_headers(
            "POST", const.ENDPOINT_AUTH, {}, paymob_auth=const.AUTH_NONE,
        )
        self.assertNotIn("Authorization", headers)
        with patch.object(
            type(self.paymob), "_paymob_cf_get_auth_token", return_value="bearer-token",
        ):
            headers = self.paymob._build_request_headers(
                "GET", const.ENDPOINT_INTEGRATIONS, {}, paymob_auth=const.AUTH_BEARER,
            )
        self.assertEqual(headers["Authorization"], "Bearer bearer-token")

    def test_auth_token_is_reused(self):
        with patch(SEND_API_REQUEST, return_value={"token": "abc"}) as request_mock:
            self.assertEqual(self.paymob._paymob_cf_get_auth_token(), "abc")
            self.assertEqual(self.paymob._paymob_cf_get_auth_token(), "abc")
        self.assertEqual(request_mock.call_count, 1)
        self.assertEqual(request_mock.call_args.kwargs["json"], {"api_key": "dummy-api-key"})
        # Another API key gets its own token.
        self.paymob.paymob_cf_api_key = "another-key"
        with patch(SEND_API_REQUEST, return_value={"token": "def"}) as request_mock:
            self.assertEqual(self.paymob._paymob_cf_get_auth_token(), "def")
        self.assertEqual(request_mock.call_count, 1)

    def test_refused_api_key_is_explained(self):
        with patch(SEND_API_REQUEST, return_value={}), self.assertRaises(PaymobError) as error:
            self.paymob._paymob_cf_get_auth_token()
        self.assertEqual(error.exception.code, "credentials")

    def test_errors_are_explained(self):
        response = MagicMock(status_code=404, text="")
        response.json.return_value = {
            "detail": "Integration ID/Name does not exist in our system for this merchant",
        }
        with self.assertRaises(PaymobError) as error:
            self.paymob._parse_response_error(response)
        self.assertEqual(error.exception.code, "integration")
        self.assertIn("Sync Integrations", str(error.exception))
        self.assertIn("does not exist", error.exception.description)

    def test_inquiry_returns_nothing_for_unknown_orders(self):
        with (
            patch.object(type(self.paymob), "_paymob_cf_get_auth_token", return_value="t"),
            patch(SEND_API_REQUEST, side_effect=PaymobError("x", code="not_found")),
        ):
            self.assertIsNone(self.paymob._paymob_cf_inquire(order_id="1"))
        with (
            patch.object(type(self.paymob), "_paymob_cf_get_auth_token", return_value="t"),
            patch(SEND_API_REQUEST, return_value=self.paid_transaction) as request_mock,
        ):
            self.assertEqual(self.paymob._paymob_cf_inquire(order_id="217503754")["id"], 192036465)
        self.assertEqual(
            request_mock.call_args.kwargs["json"], {"auth_token": "t", "order_id": 217503754},
        )
        self.assertEqual(request_mock.call_args.kwargs["paymob_auth"], const.AUTH_BEARER)

    def test_cards_saved_with_an_order(self):
        # As Paymob answers: a list of card token callbacks.
        response = [
            {"type": "TOKEN", "obj": self.token_obj},
            {"type": "TOKEN", "obj": {"id": 1}},  # No token: left out.
        ]
        with (
            patch.object(type(self.paymob), "_paymob_cf_get_auth_token", return_value="t"),
            patch(SEND_API_REQUEST, return_value=response) as request_mock,
        ):
            self.assertEqual(
                self.paymob._paymob_cf_get_order_card_tokens("593881581"), [self.token_obj],
            )
        self.assertEqual(request_mock.call_args.args[1], const.ENDPOINT_ORDER_CARD_TOKENS)
        self.assertEqual(
            request_mock.call_args.kwargs["json"], {"auth_token": "t", "order_id": 593881581},
        )
        self.assertEqual(request_mock.call_args.kwargs["paymob_auth"], const.AUTH_BEARER)
        for response in ([self.token_obj], {"results": [self.token_obj]}, []):
            with (
                patch.object(type(self.paymob), "_paymob_cf_get_auth_token", return_value="t"),
                patch(SEND_API_REQUEST, return_value=response),
            ):
                self.assertEqual(
                    self.paymob._paymob_cf_get_order_card_tokens("593881581"),
                    [self.token_obj] if response else [],
                )

    # === INTEGRATIONS === #

    def test_integrations_are_matched_with_the_methods(self):
        integrations = [
            {"id": 1, "gateway_type": "MIGS", "integration_type": "online", "is_auth": False,
             "currency": "EGP", "is_live": False, "created_at": "2026-01-01T00:00:00"},
            {"id": 2, "gateway_type": "MIGS", "integration_type": "online", "is_auth": False,
             "currency": "EGP", "is_live": False, "created_at": "2026-02-01T00:00:00"},
            {"id": 3, "gateway_type": "MIGS", "integration_type": "moto", "currency": "EGP"},
            {"id": 4, "gateway_type": "MIGS", "is_auth": True, "currency": "EGP"},
            {"id": 5, "gateway_type": "UIG", "currency": "EGP"},
            {"id": 6, "gateway_type": "CAGG", "currency": "EGP"},
            {"id": 7, "gateway_type": "VALU", "currency": "SAR"},  # Another currency.
            {"id": 8, "gateway_type": "VALU", "currency": "EGP", "is_live": True},  # Live.
            {"id": 9, "gateway_type": "MIGS", "integration_name": "Apple Pay", "currency": "EGP"},
            {"id": 10, "gateway_type": "MIGS", "installments": True, "currency": "EGP"},
            {"id": 12, "gateway_type": "MIGS", "is_google_pay": True, "currency": "EGP"},
            {"id": 13, "gateway_type": "PAYPAL", "currency": "EGP"},  # Not a Paymob method of the module.
            {"id": 14, "gateway_type": "UIG", "currency": "EGP", "is_deprecated": True},
        ]
        matches, special = self.paymob._paymob_cf_match_integrations(integrations)
        self.assertEqual(matches["card"], 2)  # The newest.
        self.assertEqual(matches["mobile_wallet_eg"], 5)
        self.assertEqual(matches["kiosk"], 6)
        self.assertEqual(matches["apple_pay"], 9)
        self.assertEqual(matches["installments_eg"], 10)
        self.assertEqual(matches["google_pay"], 12)
        self.assertNotIn(13, matches.values())
        self.assertNotIn("valu", matches)
        self.assertEqual(special["paymob_cf_moto_integration_id"], 3)
        self.assertEqual(special["paymob_cf_auth_integration_id"], 4)

    def test_sync_fills_the_integration_ids(self):
        self.pm_card.paymob_cf_integration_id = 0
        integrations = [
            {"id": 11, "gateway_type": "MIGS", "currency": "EGP"},
            {"id": 12, "gateway_type": "UIG", "currency": "EGP"},
            {"id": 13, "gateway_type": "MIGS", "integration_type": "moto", "currency": "EGP"},
        ]
        with patch(GET_INTEGRATIONS, return_value=integrations):
            action = self.paymob.action_paymob_cf_sync_integrations()
        self.assertEqual(self.pm_card.paymob_cf_integration_id, 11)
        self.assertEqual(self.pm_wallet.paymob_cf_integration_id, 12)
        self.assertEqual(self.paymob.paymob_cf_moto_integration_id, 13)
        # The kiosk and valU keep their ids: nothing was found for them.
        self.assertEqual(self.pm_kiosk.paymob_cf_integration_id, 4097560)
        self.assertEqual(action["params"]["type"], "success")

    def test_sync_reports_the_methods_without_integration(self):
        self.pm_valu.paymob_cf_integration_id = 0
        with patch(GET_INTEGRATIONS, return_value=[]):
            action = self.paymob.action_paymob_cf_sync_integrations()
        self.assertEqual(action["params"]["type"], "warning")
        self.assertIn("valU", action["params"]["message"])

    def test_test_connection(self):
        with patch(GET_INTEGRATIONS, return_value=[{"id": 1}, {"id": 2}]):
            action = self.paymob.action_paymob_cf_test_connection()
        self.assertEqual(action["params"]["type"], "success")
        self.assertIn("2 integrations", action["params"]["message"])
        with (
            patch(GET_INTEGRATIONS, side_effect=ValidationError("incorrect credentials")),
            self.assertRaises(UserError),
        ):
            self.paymob.action_paymob_cf_test_connection()
        self.paymob.paymob_cf_api_key = False
        with self.assertRaises(UserError):
            self.paymob.action_paymob_cf_test_connection()

    def test_method_integration_ids(self):
        self.assertEqual(self.paymob._paymob_cf_get_integration_ids(self.pm_card), [4097558])
        self.assertEqual(self.paymob._paymob_cf_get_integration_ids(self.pm_visa), [4097558])
        self.assertEqual(
            self.paymob._paymob_cf_get_integration_ids(self.pm_paymob),
            [4097558, 4097559, 4097560, 4097561],
        )
        self.paymob.paymob_cf_auth_integration_id = 777
        self.assertEqual(
            self.paymob._paymob_cf_get_integration_ids(self.pm_card, capture_manually=True), [777],
        )
        self.assertEqual(
            self.paymob._paymob_cf_get_integration_ids(self.pm_wallet, capture_manually=True),
            [4097559],
        )
        self.pm_valu.paymob_cf_integration_id = 0
        with self.assertRaises(PaymobError) as error:
            self.paymob._paymob_cf_get_integration_ids(self.pm_valu)
        self.assertEqual(error.exception.code, "missing_integration")

    # === FEATURES === #

    def test_features_follow_the_integration(self):
        self.assertEqual(self.paymob.support_refund, "partial")
        self.assertEqual(self.paymob.support_manual_capture, "partial")
        self.assertFalse(self.paymob.support_tokenization)
        self._set_embedded()
        self.assertTrue(self.paymob.support_tokenization)
        self.assertTrue(self.paymob.allow_tokenization)
        self.paymob.paymob_cf_integration = "hosted"
        self.assertFalse(self.paymob.allow_tokenization)

    def test_manual_capture_needs_an_auth_integration(self):
        # Odoo only captures manually when every active method supports it: cards here.
        (self.pm_wallet + self.pm_kiosk + self.pm_valu + self.pm_paymob).active = False
        with self.assertRaises(ValidationError):
            self.paymob.capture_manually = True
        self.paymob.write({"paymob_cf_auth_integration_id": 777, "capture_manually": True})
        self.assertTrue(self.paymob.capture_manually)

    def test_payment_expiry_is_limited(self):
        with self.assertRaises(ValidationError):
            self.paymob.paymob_cf_payment_expiry_hours = 0
        with self.assertRaises(ValidationError):
            self.paymob.paymob_cf_payment_expiry_hours = 865

    def test_cards_are_only_saved_without_payment_with_a_verification_integration(self):
        self._set_embedded()
        self.paymob.is_published = True
        providers = self.env["payment.provider"]._find_available_providers(
            self.company.id, self.partner.id, 0.0, is_validation=True,
        )
        self.assertNotIn(self.paymob, providers)
        self.paymob.paymob_cf_verification_integration_id = 888
        providers = self.env["payment.provider"]._find_available_providers(
            self.company.id, self.partner.id, 0.0, is_validation=True,
        )
        self.assertIn(self.paymob, providers)

    # === APPLE PAY === #

    def _apple_pay_method(self):
        return self.env.ref("payment_paymob_cf.payment_method_apple_pay")

    def test_apple_pay_is_offered_where_paymob_offers_it(self):
        method = self._apple_pay_method()
        self.assertEqual(
            set(method.supported_country_ids.mapped("code")), {"EG", "SA", "AE", "OM"},
        )
        self.assertEqual(
            set(method.supported_currency_ids.mapped("name")), {"EGP", "SAR", "AED", "OMR"},
        )
        self.assertEqual(method.support_refund, "partial")

    def test_apple_pay_opens_paymob_checkout_in_a_full_page(self):
        self.paymob.paymob_cf_display_mode = "popup"
        apple_pay_values = json.loads(self.paymob._paymob_cf_get_inline_form_values("apple_pay"))
        self.assertEqual(apple_pay_values, {"flow": "hosted", "display_mode": "redirect"})
        card_values = json.loads(self.paymob._paymob_cf_get_inline_form_values("card"))
        self.assertEqual(card_values["display_mode"], "popup")
        self._set_embedded()
        apple_pay_values = json.loads(self.paymob._paymob_cf_get_inline_form_values("apple_pay"))
        self.assertEqual(apple_pay_values, {"flow": "pixel", "display_mode": "inline"})

    def test_apple_pay_needs_its_country_and_live_mode(self):
        method = self._apple_pay_method()
        method.paymob_cf_integration_id = 77
        with self.assertRaises(UserError) as error:
            self.paymob.action_paymob_cf_activate_apple_pay()  # Test mode.
        self.assertIn("live integrations only", str(error.exception))
        self.paymob.write({"paymob_cf_country": "PK", "is_live": True})
        with self.assertRaises(UserError) as error:
            self.paymob.action_paymob_cf_activate_apple_pay()
        self.assertIn("Pakistan", str(error.exception))
        self.assertFalse(method.active)

    def test_apple_pay_is_activated_with_its_live_integration(self):
        method = self._apple_pay_method()
        method.write({"active": False, "paymob_cf_integration_id": 0})
        self.paymob.is_live = True
        integrations = [
            {"id": 76, "gateway_type": "MIGS", "is_apple_pay": True, "currency": "EGP",
             "is_live": False},  # A test integration.
            {"id": 77, "gateway_type": "MIGS", "is_apple_pay": True, "currency": "EGP",
             "is_live": True},
        ]
        with patch(GET_INTEGRATIONS, return_value=integrations):
            action = self.paymob.action_paymob_cf_activate_apple_pay()
        self.assertTrue(method.active)
        self.assertEqual(method.paymob_cf_integration_id, 77)
        self.assertEqual(action["params"]["type"], "success")
        self.assertIn("77", action["params"]["message"])

    def test_apple_pay_needs_paymob_to_enable_it(self):
        method = self._apple_pay_method()
        method.write({"active": False, "paymob_cf_integration_id": 0})
        self.paymob.is_live = True
        with patch(GET_INTEGRATIONS, return_value=[]), self.assertRaises(UserError) as error:
            self.paymob.action_paymob_cf_activate_apple_pay()
        self.assertIn("Ask Paymob to enable Apple Pay", str(error.exception))
        self.assertFalse(method.active)

    def test_embedded_apple_pay_needs_the_domain_file(self):
        self._set_embedded()
        method = self._apple_pay_method()
        method.write({"active": False, "paymob_cf_integration_id": 77})
        self.paymob.is_live = True
        with self.assertRaises(UserError) as error:
            self.paymob.action_paymob_cf_activate_apple_pay()
        self.assertIn("domain file", str(error.exception))
        self.assertFalse(method.active)
        self.paymob.paymob_cf_apple_pay_domain_file = BinaryBytes(b"7B2270737049642")
        action = self.paymob.action_paymob_cf_activate_apple_pay()
        self.assertTrue(method.active)
        self.assertIn("certificates", action["params"]["message"])

    def test_apple_pay_domain_file(self):
        Provider = self.env["payment.provider"]
        self.assertIsNone(Provider._paymob_cf_get_apple_pay_domain_file("shop.example.com"))
        self.paymob.paymob_cf_apple_pay_domain_file = BinaryBytes(b"7B2270737049642")
        self.assertEqual(
            Provider._paymob_cf_get_apple_pay_domain_file("shop.example.com"), b"7B2270737049642",
        )
        with self.assertRaises(ValidationError):
            self.paymob.paymob_cf_apple_pay_domain_file = BinaryBytes(b"\x89PNG\0\0")

    def test_neutralized_credentials(self):
        reset_values = self.paymob._get_reset_values()
        for field_name in (
            "paymob_cf_secret_key", "paymob_cf_public_key", "paymob_cf_api_key",
            "paymob_cf_hmac_secret",
        ):
            self.assertIn(field_name, reset_values)
