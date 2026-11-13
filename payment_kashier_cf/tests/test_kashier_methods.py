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
import importlib.util
import os
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import BinaryBytes, mute_logger

from odoo.addons.payment_kashier_cf import const
from odoo.addons.payment_kashier_cf import utils as kashier_utils
from odoo.addons.payment_kashier_cf.exceptions import KashierError
from odoo.addons.payment_kashier_cf.tests.common import (
    MERCHANT_ID,
    ORDER_ID,
    SESSION_ID,
    KashierCommon,
    kashier_order,
    leg,
    sign,
)

SESSION_ANSWER = {"_id": SESSION_ID, "status": "CREATED",
                  "sessionUrl": f"https://payments.kashier.io/session/{SESSION_ID}?mode=test"}
ACCOUNT_ANSWER = {"acceptedPaymentMethods": ["card", "wallet"], "acceptedBNPLMethods": ["valu"], "motoEnabled": True}


def wallet_answer(body):
    return {"status": "SUCCESS", "response": {"status": "SUCCESS", "transactionResponseCode": "k_4",
                                              "order": {"systemOrderId": ORDER_ID}}}


@tagged("post_install", "-at_install")
class TestIntegrations(KashierCommon):

    def test_defaults_and_limits(self):
        for method in (self.pm_card, self.pm_wallet, self.pm_valu, self.pm_kiosk):
            self.assertEqual(method._kashier_cf_get_integration(), const.INTEGRATION_REDIRECT)
        self.pm_wallet.kashier_cf_integration = const.INTEGRATION_SERVER
        self.assertEqual(self.pm_wallet._kashier_cf_get_integration(), const.INTEGRATION_SERVER)
        for method, integration in ((self.pm_card, const.INTEGRATION_SERVER), (self.pm_valu, const.INTEGRATION_SERVER),
                                    (self.pm_apple_pay, const.INTEGRATION_EMBEDDED)):
            with self.subTest(method=method.code), self.assertRaises(ValidationError):
                method.kashier_cf_integration = integration
        self.assertEqual(self.pm_mastercard._kashier_cf_get_integration(), const.INTEGRATION_REDIRECT, "Brands follow the card.")

    def test_apple_pay_button_needs_the_domain_file(self):
        self.pm_apple_pay.kashier_cf_integration = const.INTEGRATION_APPLE_PAY_BUTTON
        self.assertEqual(self.pm_apple_pay._kashier_cf_get_integration(), const.INTEGRATION_REDIRECT)
        self.kashier.kashier_cf_apple_pay_domain_file = BinaryBytes(b"7B227073-domain-file")
        self.assertEqual(self.pm_apple_pay._kashier_cf_get_integration(), const.INTEGRATION_APPLE_PAY_BUTTON)
        with self.assertRaises(ValidationError):
            self.kashier.kashier_cf_apple_pay_domain_file = BinaryBytes(b"\0binary")

    def test_session_per_method(self):
        expected = {self.pm_card: "card", self.pm_apple_pay: "card", self.pm_wallet: "wallet",
                    self.pm_valu: "bnpl[valu]", self.pm_kiosk: "basata", self.pm_instapay: "instapay",
                    self.pm_installments: "bank_installments"}
        for method, allowed in expected.items():
            with self.subTest(method=method.code):
                tx = self._create_transaction("redirect", payment_method_id=method.id, reference=f"S-SES-{method.code}")
                self.assertEqual(tx._kashier_cf_session_payload()["allowedMethods"], allowed)

    def test_embedded_page(self):
        self.pm_card.kashier_cf_integration = const.INTEGRATION_EMBEDDED
        tx = self._create_transaction("redirect")
        with self._set_answer("POST", "/v3/payment/sessions", SESSION_ANSWER):
            values = tx._get_specific_processing_values({})
            rendering = tx._get_specific_rendering_values(values)
        self.assertEqual(values["kashier_cf_embed_url"], SESSION_ANSWER["sessionUrl"])
        self.assertTrue(values["kashier_cf_return_url"].endswith(f"/payment/kashier_cf/return/{tx.id}/{values['kashier_cf_access_token']}"))
        self.assertEqual(len(self.fake.calls_to("POST", "/v3/payment/sessions")), 1, "One session for the page and the frame.")
        self.assertTrue(rendering["api_url"].endswith(f"/session/{SESSION_ID}"))

    def test_apple_pay_button_processing_values(self):
        self.kashier.kashier_cf_apple_pay_domain_file = BinaryBytes(b"7B227073-domain-file")
        self.pm_apple_pay.kashier_cf_integration = const.INTEGRATION_APPLE_PAY_BUTTON
        tx = self._create_transaction("direct", payment_method_id=self.pm_apple_pay.id)
        with self._set_answer("POST", "/v3/payment/sessions", SESSION_ANSWER):
            values = tx._get_specific_processing_values({})
        self.assertEqual((values["kashier_cf_session_id"], values["kashier_cf_mode"]), (SESSION_ID, "test"))
        self.assertEqual(values["kashier_cf_sdk_url"], const.APPLE_PAY_SDK_URL)

    @mute_logger("odoo.addons.payment.models.payment_transaction")
    def test_direct_flow_refused_for_other_methods(self):
        tx = self._create_transaction("direct", payment_method_id=self.pm_card.id)
        tx._get_specific_processing_values({})
        self.assertEqual(tx.state, "error")
        self.assertFalse(self.fake.calls_to("POST", "/v3/payment/sessions"))


@tagged("post_install", "-at_install")
class TestAccountMethods(KashierCommon):

    def setUp(self):
        super().setUp()
        self.partner.country_id = self.env.ref("base.eg")

    def _available(self):
        return self.kashier._find_available_payment_methods(self.partner.id, currency_id=self.currency.id)

    def test_parse_both_shapes(self):
        self.assertEqual(kashier_utils.parse_account_methods(ACCOUNT_ANSWER), (["card", "wallet"], ["valu"]))
        self.assertEqual(kashier_utils.parse_account_methods({"card": True, "Wallet": True, "valu": False}), (["card", "wallet"], []))
        self.assertEqual(kashier_utils.parse_account_methods(None), ([], []))

    def test_methods_the_account_refuses_are_hidden(self):
        self.assertIn(self.pm_kiosk, self._available(), "Nothing hidden while unknown.")
        with self._set_answer("GET", "/v2/merchants/", ACCOUNT_ANSWER):
            self.kashier.action_kashier_cf_sync_account_methods()
        available = self._available()
        self.assertIn(self.pm_card, available)
        self.assertIn(self.pm_wallet, available)
        self.assertIn(self.pm_valu, available)
        self.assertNotIn(self.pm_kiosk, available)
        self.assertNotIn(self.pm_instapay, available)
        self.assertNotIn(self.pm_installments, available)
        report = {}
        self.kashier._find_available_payment_methods(self.partner.id, currency_id=self.currency.id, report=report)
        self.assertFalse(report["payment_methods"][self.pm_kiosk]["available"])

    def test_list_is_forgotten_with_another_account_or_mode(self):
        with self._set_answer("GET", "/v2/merchants/", ACCOUNT_ANSWER):
            self.kashier.action_kashier_cf_sync_account_methods()
        self.assertNotIn(self.pm_kiosk, self._available())
        with patch.object(type(self.env["ir.cron"]), "_trigger") as trigger:
            self.kashier.kashier_cf_merchant_id = "MID-2-2"
        trigger.assert_called()
        self.assertFalse(self.kashier.kashier_cf_account_methods)
        self.assertIn(self.pm_kiosk, self._available())

    def test_methods_shown_by_another_provider(self):
        self.assertFalse(self.kashier.kashier_cf_shadowed_methods)
        other = self.dummy_provider
        other.write({"is_published": True, "sequence": self.kashier.sequence - 1, "company_id": self.kashier.company_id.id})
        self.pm_wallet.copy({"provider_id": other.id, "active": True})
        self.kashier.invalidate_recordset(["kashier_cf_shadowed_methods"])
        self.assertEqual(self.kashier.kashier_cf_shadowed_methods, self.pm_wallet.name)

    @mute_logger("odoo.addons.payment_kashier_cf.models.payment_provider")
    def test_sync_failure_keeps_everything(self):
        with self._set_answer("GET", "/v2/merchants/", KashierError("down", code="server_error")):
            self.assertFalse(self.kashier._kashier_cf_sync_account_methods())
        self.assertIn(self.pm_kiosk, self._available())


@tagged("post_install", "-at_install")
class TestServerSide(KashierCommon):

    def setUp(self):
        super().setUp()
        (self.pm_wallet | self.pm_kiosk | self.pm_instapay).kashier_cf_integration = const.INTEGRATION_SERVER

    def _server_tx(self, method=None, **values):
        tx = self._create_transaction("redirect", payment_method_id=(method or self.pm_wallet).id, **values)
        rendering = tx._get_specific_rendering_values({})
        self.assertEqual(rendering["api_url"], tx._kashier_cf_route_path("/payment/kashier_cf/pay"))
        return tx

    def test_wallet_request(self):
        tx = self._server_tx()
        order_ref = tx.kashier_cf_order_ref
        self.assertTrue(order_ref, "The reference is saved when the page opens.")
        with self._set_answer("POST", "/v3/orders", wallet_answer):
            result = tx._kashier_cf_start_server_payment("+20 100 100 1001")
        self.assertTrue(result["ok"])
        call = self.fake.calls_to("POST", "/v3/orders")[-1]
        body = call["json"]
        self.assertEqual((body["apiOperation"], body["paymentMethod"]), ("INITIATE_R2P", {"type": "wallet"}))
        self.assertEqual(body["customer"]["mobilePhone"], "01001001001")
        self.assertEqual(body["order"]["reference"], order_ref)
        self.assertEqual(call["headers"]["Kashier-Hash"], sign(kashier_utils.order_hash_string(MERCHANT_ID, order_ref, "10.00", "EGP")))
        self.assertEqual((tx.state, tx.kashier_cf_server_kind, tx.kashier_cf_order_id), ("pending", "wallet", ORDER_ID))
        self.assertGreater(tx.kashier_cf_expires_at, fields.Datetime.now() + timedelta(minutes=9))
        again = tx._kashier_cf_start_server_payment("01001001001")
        self.assertFalse(again["ok"], "Never a second request while one is pending.")
        self.assertEqual(len(self.fake.calls_to("POST", "/v3/orders")), 1)

    def test_bad_number_and_retry(self):
        tx = self._server_tx()
        self.assertFalse(tx._kashier_cf_start_server_payment("12345")["ok"])
        self.assertFalse(self.fake.calls_to("POST", "/v3/orders"))
        first_ref = tx.kashier_cf_order_ref
        with self._set_answer("POST", "/v3/orders", KashierError("no wallet", code="k_5")):
            result = tx._kashier_cf_start_server_payment("01001001001")
        self.assertEqual((result["ok"], result["can_retry"]), (False, True))
        self.assertEqual(result["message"], str(const.ERROR_CODES["k_5"][1]))
        self.assertEqual(tx.state, "draft")
        self.assertNotEqual(tx.kashier_cf_order_ref, first_ref, "A new Kashier order for the next attempt.")
        self.assertIn(first_ref, tx._kashier_cf_all_order_refs(), "The refused order is still checked.")
        self.assertIn("Wait", tx._kashier_cf_start_server_payment("01001001001")["message"])
        tx.with_context(payment_safe_write=True).kashier_cf_last_attempt = fields.Datetime.now() - timedelta(minutes=1)
        with self._set_answer("POST", "/v3/orders", wallet_answer):
            self.assertTrue(tx._kashier_cf_start_server_payment("01001001001")["ok"])

    def test_attempts_are_capped(self):
        tx = self._server_tx()
        for _ in range(const.SERVER_MAX_ATTEMPTS):
            tx.with_context(payment_safe_write=True).kashier_cf_last_attempt = False
            with self._set_answer("POST", "/v3/orders", KashierError("no wallet", code="k_5")):
                result = tx._kashier_cf_start_server_payment("01001001001")
        self.assertFalse(result["can_retry"])
        tx.with_context(payment_safe_write=True).kashier_cf_last_attempt = False
        self.assertIn("Too many", tx._kashier_cf_start_server_payment("01001001001")["message"])

    def test_unknown_outcome_is_never_sent_again(self):
        tx = self._server_tx()
        with self._set_answer("POST", "/v3/orders", KashierError("timeout", code="timeout", unknown_outcome=True)):
            result = tx._kashier_cf_start_server_payment("01001001001")
        self.assertTrue(result["waiting"])
        self.assertEqual(tx.state, "pending")
        self.assertTrue(tx.kashier_cf_outcome_unknown)
        self.assertFalse(tx._kashier_cf_start_server_payment("01001001001")["ok"])

    def test_wallet_paid_then_expired_request(self):
        tx = self._server_tx()
        with self._set_answer("POST", "/v3/orders", wallet_answer):
            tx._kashier_cf_start_server_payment("01001001001")
        waiting = [leg("initiate_r2p", code="k_4", tx_id="TX-r2p")]
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref, status="INITIATED", method="wallet", legs=waiting)]
        self._sync(tx)
        self.assertEqual(tx.state, "pending", "Waiting for the customer: no alert, no cancel.")
        self.assertFalse(tx.kashier_cf_alerted)
        tx.with_context(payment_safe_write=True).kashier_cf_expires_at = fields.Datetime.now() - timedelta(minutes=1)
        self._sync(tx)
        self.assertEqual(tx.state, "cancel")
        self.assertTrue(tx.kashier_cf_late_check_until)
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref, method="wallet", legs=waiting + [leg("pay", tx_id="TX-paid")])]
        self._sync(tx)
        self.assertEqual((tx.state, tx.payment_method_id), ("done", self.pm_wallet), "A late approval is still recorded.")

    def test_late_payment_of_an_earlier_attempt(self):
        tx = self._server_tx()
        first_ref = tx.kashier_cf_order_ref
        with self._set_answer("POST", "/v3/orders", KashierError("general", code="k_default")):
            tx._kashier_cf_start_server_payment("01001001001")
        self.fake.orders = [kashier_order(first_ref, method="wallet", legs=[leg("pay", tx_id="TX-first")])]
        self._sync(tx)
        self.assertEqual(tx.state, "done")

    def test_customer_left_the_page(self):
        tx = self._server_tx()
        tx.with_context(payment_safe_write=True).kashier_cf_expires_at = fields.Datetime.now() - timedelta(minutes=1)
        tx._kashier_cf_expire_server_page(fields.Datetime.now())
        self.assertEqual(tx.state, "cancel")

    def test_basata_code(self):
        tx = self._server_tx(self.pm_kiosk)
        expire = (fields.Datetime.now() + timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        answer = {"status": "SUCCESS", "response": {"status": "SUCCESS", "transactionResponseCode": "00", "paymentMethod": {
            "type": "basata", "basata": {"referenceCode": "12345678", "expireAt": expire}}}}
        with self._set_answer("POST", "/v3/orders", answer):
            result = tx._kashier_cf_start_server_payment("01001001001")
        body = self.fake.calls_to("POST", "/v3/orders")[-1]["json"]
        self.assertEqual(body["paymentMethod"], {"type": "BASATA", "basata": {"mobileNumber": "01001001001"}})
        self.assertEqual((result["code"], tx.kashier_cf_reference_code, tx.state), ("12345678", "12345678", "pending"))
        self.assertIn("12345678", str(tx._get_status_message(order=None)))
        mail = self.env["mail.mail"].search([("subject", "ilike", "12345678")])
        self.assertEqual(len(mail), 1)
        self.assertIn(self.company.name, mail.subject)
        self.assertNotIn("Odoo", mail.body_html)

    def test_instapay_qr(self):
        tx = self._server_tx(self.pm_instapay)
        answer = {"status": "SUCCESS", "response": {"status": "SUCCESS", "payload": {"body": {"ISOQR": "000201QRDATA"}}}}
        with self._set_answer("POST", "/v3/orders", answer):
            self.assertTrue(tx._kashier_cf_start_server_payment("")["ok"])
        body = self.fake.calls_to("POST", "/v3/orders")[-1]["json"]
        self.assertEqual(body["apiOperation"], "GENERATE_QR")
        self.assertEqual(tx.sudo().kashier_cf_qr_payload, "000201QRDATA")
        self.assertFalse(tx._kashier_cf_start_server_payment("bad address!")["ok"])

    def test_instapay_request_to_an_address(self):
        tx = self._server_tx(self.pm_instapay)
        with self._set_answer("POST", "/v3/orders", wallet_answer):
            tx._kashier_cf_start_server_payment("Nour.Hassan")
        instapay = self.fake.calls_to("POST", "/v3/orders")[-1]["json"]["paymentMethod"]["instapay"]
        self.assertEqual(instapay["payerAddress"], "nour.hassan@instapay")

    def test_installments_wait_for_kashier(self):
        tx = self._create_kashier_tx(payment_method_id=self.pm_installments.id)
        self.fake.session = {"status": "AUTHORIZED"}
        self.fake.orders = [kashier_order(tx.kashier_cf_order_ref, status="AUTHORIZED", legs=[leg("authorize", tx_id="TX-inst")])]
        self._sync(tx)
        self.assertEqual((tx.state, tx.payment_method_id), ("pending", self.pm_installments), "Never offered for capture.")


@tagged("post_install", "-at_install")
class TestMigration(KashierCommon):

    def test_every_provider_gets_the_new_methods(self):
        company = self.env["res.company"].create({"name": "Second Company"})
        other = self.kashier.copy({"company_id": company.id, "is_published": False})
        new_codes = {"mobile_wallet_eg", "kiosk", "instapay", "valu"}
        other.with_context(active_test=False).payment_method_ids.filtered(lambda pm: pm.code in new_codes).unlink()
        path = os.path.join(os.path.dirname(__file__), "..", "migrations", "20.0.1.1.0", "post-migrate.py")
        spec = importlib.util.spec_from_file_location("kashier_cf_post_migrate", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.migrate(self.env.cr, "20.0.1.0.0")
        methods = other.with_context(active_test=False).payment_method_ids
        self.assertTrue(new_codes <= set(methods.mapped("code")))
        self.assertTrue(all(methods.filtered(lambda pm: pm.code in new_codes).mapped("active")))
        self.assertEqual(set(methods.filtered("is_primary").mapped("kashier_cf_integration")) - {False},
                         {const.INTEGRATION_REDIRECT})

    def test_migration_keeps_manual_capture_working(self):
        company = self.env["res.company"].create({"name": "Third Company"})
        other = self.kashier.copy({"company_id": company.id, "is_published": False})
        other.with_context(active_test=False).payment_method_ids.filtered(lambda pm: pm.code != "card").active = False
        other.capture_manually = True
        other.with_context(active_test=False).payment_method_ids.filtered(lambda pm: pm.code == "kiosk").unlink()
        path = os.path.join(os.path.dirname(__file__), "..", "migrations", "20.0.1.1.0", "post-migrate.py")
        spec = importlib.util.spec_from_file_location("kashier_cf_post_migrate_2", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.migrate(self.env.cr, "20.0.1.0.0")  # Must not fail on the manual capture constraint.
        kiosk = other.with_context(active_test=False).payment_method_ids.filtered(lambda pm: pm.code == "kiosk")
        self.assertTrue(kiosk)
        self.assertFalse(kiosk.active)
