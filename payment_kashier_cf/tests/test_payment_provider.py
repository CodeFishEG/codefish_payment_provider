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
from unittest.mock import MagicMock, patch

import requests

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment_kashier_cf import const
from odoo.addons.payment_kashier_cf.exceptions import KashierError
from odoo.addons.payment_kashier_cf.tests.common import (
    MERCHANT_ID,
    PAYMENT_API_KEY,
    PROVIDER_PATH,
    SECRET_KEY,
    KashierCommon,
)


@tagged("post_install", "-at_install")
class TestPaymentProvider(KashierCommon):

    def test_features_and_currencies(self):
        self.assertEqual(self.kashier.support_refund, "partial")
        self.assertEqual(self.kashier.support_manual_capture, "full_only")
        self.assertTrue(self.kashier.support_tokenization)
        self.assertEqual(sorted(self.kashier._get_supported_currencies().mapped("name")), ["EGP", "EUR", "GBP", "USD"])
        self.assertEqual(self.kashier._get_default_payment_method_codes(), const.DEFAULT_PAYMENT_METHOD_CODES)

    def test_feature_compute_on_mixed_recordsets(self):
        providers = self.kashier | self.dummy_provider
        providers._compute_feature_support_fields()
        providers.write({"sequence": 5})  # write() on several providers must not need a singleton
        self.assertEqual(self.kashier.support_manual_capture, "full_only")

    def test_settings_are_checked(self):
        for values in (
            {"kashier_cf_merchant_id": "1234"},
            {"kashier_cf_allowed_methods": "card;wallet"},
            {"kashier_cf_session_expiry": 2},
            {"kashier_cf_max_attempts": 9},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                self.kashier.write(values)
        self.kashier.write({"kashier_cf_allowed_methods": "wallet, bank_installments, bnpl[valu], applePay"})
        self.kashier.write({"kashier_cf_merchant_id": " MID-12345-678 "})
        self.assertEqual(self.kashier.kashier_cf_merchant_id, "MID-12345-678")

    def test_reset_values_and_validation_operations(self):
        self.assertTrue({"kashier_cf_secret_key", "kashier_cf_payment_api_key"} <= set(self.kashier._get_reset_values()))
        providers = self.env["payment.provider"]._find_available_providers(
            self.company.id, self.partner.id, 0.0, currency_id=self.currency.id, is_validation=True,
        )
        self.assertNotIn(self.kashier, providers)

    def test_requests_reach_the_right_host_and_credentials(self):
        self.patcher.stop()  # Inspect the real request building.
        client = self.kashier._kashier_cf_client()
        sent = []

        def fake_request(method, url, **kwargs):
            sent.append((method, url, kwargs["headers"], kwargs["timeout"]))
            return MagicMock(ok=True, status_code=200, text='{"data": []}', json=lambda: {"data": []})

        with patch("odoo.addons.payment_kashier_cf.models.payment_provider.requests.request", side_effect=fake_request):
            client.search_orders(search="S1")
            client.update_order("uuid-1", {"apiOperation": "REFUND"})
            client.retrieve_tokens(kashier_hash="h", customer_reference="cf-1", merchant_id=MERCHANT_ID)
            client.create_payment_session({"amount": "1.00"})
        (_, url1, h1, t1), (_, url2, _h2, t2), (_, url3, h3, _t3), (_, _url4, h4, _t4) = sent
        self.assertEqual(url1, "https://test-api.kashier.io/v3/payment/orders")
        self.assertEqual(h1["Authorization"], SECRET_KEY)
        self.assertNotIn("api-key", h1)
        self.assertEqual(url2, "https://test-fep.kashier.io/v3/orders/uuid-1")
        self.assertGreater(t2, t1, "Requests moving money wait longer.")
        self.assertEqual((url3, h3["Kashier-Hash"]), ("https://test-fep.kashier.io/v3/cards/customer", "h"))
        self.assertNotIn("Authorization", h3)
        self.assertEqual((h4["Authorization"], h4["api-key"]), (SECRET_KEY, PAYMENT_API_KEY))
        self.kashier.is_live = True
        with patch("odoo.addons.payment_kashier_cf.models.payment_provider.requests.request", side_effect=fake_request):
            client.search_orders(search="S1")
        self.assertEqual(sent[-1][1], "https://api.kashier.io/v3/payment/orders")
        self.patcher.start()

    @mute_logger("odoo.addons.payment.models.payment_provider")
    def test_errors_tell_unknown_outcomes(self):
        self.patcher.stop()
        path = "odoo.addons.payment_kashier_cf.models.payment_provider.requests.request"
        cases = [
            (requests.exceptions.ConnectTimeout(), False, "connection"),
            (requests.exceptions.ReadTimeout(), True, "timeout"),
        ]
        for side_effect, unknown, code in cases:
            with patch(path, side_effect=side_effect), self.assertRaises(KashierError) as error:
                self.kashier._kashier_cf_client().update_order("uuid", {"apiOperation": "REFUND"})
            self.assertEqual((error.exception.unknown_outcome, error.exception.code), (unknown, code))
        responses = [
            (502, "Bad gateway", True, "server_error"),
            (400, {"status": "FAILURE", "response": {"status": "FAILED", "transactionResponseCode": "51"}}, False, "51"),
            (401, {"message": "Invalid token"}, False, "credentials"),
        ]
        for status, body, unknown, code in responses:
            response = MagicMock(ok=False, status_code=status, text=str(body))
            response.json = (lambda body=body: body) if isinstance(body, dict) else MagicMock(side_effect=ValueError)
            with patch(path, return_value=response), self.assertRaises(KashierError) as error:
                self.kashier._kashier_cf_client().update_order("uuid", {"apiOperation": "REFUND"})
            self.assertEqual((error.exception.unknown_outcome, error.exception.code), (unknown, code))
        self.patcher.start()

    def test_urls_for_kashier_use_the_forwarded_scheme(self):
        module = "odoo.addons.payment_kashier_cf.models.payment_provider"
        forwarded = MagicMock(httprequest=MagicMock(headers={"X-Forwarded-Proto": "https"}))
        with patch(f"{PROVIDER_PATH}.get_base_url", return_value="http://shop.example.com/"), \
                patch(f"{module}.request", forwarded), patch.dict(f"{module}.config.options", {"proxy_mode": True}):
            self.assertEqual(self.kashier._kashier_cf_url("/payment/x"), "https://shop.example.com/payment/x")
        with patch(f"{PROVIDER_PATH}.get_base_url", return_value="http://shop.example.com"), \
                patch(f"{module}.request", forwarded), patch.dict(f"{module}.config.options", {"proxy_mode": False}):
            self.assertEqual(self.kashier._kashier_cf_url("payment/x"), "http://shop.example.com/payment/x",
                             "Without proxy mode the header isn't trusted.")

    def test_test_connection(self):
        with self._set_answer("POST", "/v2/merchants/validate-credentials", {"message": "Credentials validated"}):
            action = self.kashier.action_kashier_cf_test_connection()
        self.assertEqual(action["params"]["type"], "success")
        call = self.fake.calls_to("POST", "/v2/merchants/validate-credentials")[0]
        self.assertEqual(call["json"]["apiKeys"], [{"mode": "test", "key": PAYMENT_API_KEY}])
        with self._set_answer("POST", "/v2/merchants/validate-credentials",
                              KashierError("Kashier refused the credentials.", code="credentials")), \
                self.assertRaises(UserError):
            self.kashier.action_kashier_cf_test_connection()
        self.kashier.kashier_cf_secret_key = False
        with self.assertRaises(UserError):
            self.kashier.action_kashier_cf_test_connection()

    def test_journal(self):
        self._skip_if_account_payment_is_not_installed()
        self.env["payment.provider"]._kashier_cf_setup_journals(self.company)
        journal = self.kashier.journal_id
        self.assertEqual((journal.code, journal.type), (const.JOURNAL_CODE, "bank"))
        self.assertFalse(journal.currency_id)
        self.env["payment.provider"]._kashier_cf_setup_journals(self.company)
        self.assertEqual(self.env["account.journal"].search_count([
            ("company_id", "=", self.company.id), ("code", "=", const.JOURNAL_CODE),
        ]), 1)

    def test_error_messages(self):
        staff = self.kashier._kashier_cf_get_error_message("51", "Insufficient funds")
        self.assertIn("51", staff)
        self.assertIn("Insufficient funds", staff)
        customer = self.kashier._kashier_cf_get_customer_error_message("credentials")
        self.assertIn("credentials", customer)
        self.assertNotIn("Odoo", customer)
        self.assertNotIn("Secret Key", customer)
        self.assertEqual(
            self.kashier._kashier_cf_get_customer_error_message("51"), str(const.ERROR_CODES["51"][1]),
        )
