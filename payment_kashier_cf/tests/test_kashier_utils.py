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
import logging

from odoo.tests import BaseCase, tagged

from odoo.addons.payment_kashier_cf import const, logging_filters
from odoo.addons.payment_kashier_cf import utils as kashier_utils
from odoo.addons.payment_kashier_cf.tests.common import sign


@tagged("post_install", "-at_install")
class TestKashierUtils(BaseCase):

    def test_order_hash_documented_vector(self):
        """Kashier's hashing page: /?payment=mid-0-1.99.20.EGP with the key 11111."""
        string = kashier_utils.order_hash_string("mid-0-1", "99", "20", "EGP")
        self.assertEqual(string, "/?payment=mid-0-1.99.20.EGP")
        self.assertEqual(
            kashier_utils.hmac_hex("11111", string),
            "606a8a1307d64caf4e2e9bb724738f115a8972c27eccb2a8acd9194c357e4bec",
        )
        self.assertEqual(
            kashier_utils.order_hash_string("MID-1-1", "R1", "5.00", "EGP", "cf-abc"),
            "/?payment=MID-1-1.R1.5.00.EGP.cf-abc",
        )
        self.assertEqual(kashier_utils.tokenization_hash_string("MID-1-1", "cf-abc"), "/?tokenization=MID-1-1.cf-abc")

    def test_webhook_documented_vector(self):
        """Kashier's webhook page: the documented payload signs to 9610477b... with the key 11111."""
        raw = (
            '{"amount": 1, "channel": "online | e-commerce", "currency": "EGP", '
            '"kashierOrderId": "9ad06b17-755b-4e21-9774-aff3e2726ac9", "merchantOrderId": "1653481557813", '
            '"method": "card", "orderReference": "TEST-ORD-38855", "status": "SUCCESS", '
            '"transactionId": "TX-249893963", "transactionResponseCode": "00", "card": {"x": 1}, '
            '"signatureKeys": ["merchantOrderId", "kashierOrderId", "orderReference", "amount", "currency", '
            '"status", "method", "transactionId", "transactionResponseCode", "channel"]}'
        )
        data = kashier_utils.loads_keeping_numbers(raw)
        string = kashier_utils.webhook_signing_string(data)
        self.assertEqual(
            string,
            "amount=1&channel=online%20%7C%20e-commerce&currency=EGP&kashierOrderId=9ad06b17-755b-4e21-9774-"
            "aff3e2726ac9&merchantOrderId=1653481557813&method=card&orderReference=TEST-ORD-38855&status=SUCCESS"
            "&transactionId=TX-249893963&transactionResponseCode=00",
        )
        self.assertEqual(
            kashier_utils.hmac_hex("11111", string),
            "9610477b2255b2a8ef84fd89adfaa5f1305ff9c20324205851890f1ea03109f4",
        )

    def test_webhook_numbers_signed_as_sent(self):
        data = kashier_utils.loads_keeping_numbers('{"amount": 100.50, "big": 1e16, "signatureKeys": ["amount", "big"]}')
        self.assertEqual(kashier_utils.webhook_signing_string(data), "amount=100.50&big=1e16")

    def test_webhook_unsignable_values(self):
        for raw in ('{"a": {"b": 1}, "signatureKeys": ["a"]}', '{"a": null, "signatureKeys": ["a"]}',
                    '{"signatureKeys": ["missing"]}', '{"a": 1}'):
            with self.subTest(raw=raw), self.assertRaises(kashier_utils.UnsignableValue):
                kashier_utils.webhook_signing_string(kashier_utils.loads_keeping_numbers(raw))
        self.assertEqual(
            kashier_utils.webhook_signing_string({"ok": True, "signatureKeys": ["ok"]}), "ok=true",
        )

    def test_redirect_signature(self):
        params = {
            "paymentStatus": "SUCCESS", "cardDataToken": "tok", "maskedCard": "512345******0008",
            "merchantOrderId": "S1-abc", "orderId": "uuid", "cardBrand": "Mastercard",
            "orderReference": "TEST-ORD-1", "transactionId": "TX-1", "amount": "10", "currency": "EGP",
            "mode": "test", "signature": "ignored",
        }
        expected = (
            "paymentStatus=SUCCESS&cardDataToken=tok&maskedCard=512345******0008&merchantOrderId=S1-abc&orderId=uuid"
            "&cardBrand=Mastercard&orderReference=TEST-ORD-1&transactionId=TX-1&amount=10&currency=EGP"
        )
        self.assertEqual(kashier_utils.redirect_signing_string(params), expected)
        missing = dict(params)
        del missing["cardDataToken"]
        self.assertIn("cardDataToken=null&", kashier_utils.redirect_signing_string(missing))
        self.assertTrue(kashier_utils.same_signature(sign(expected).upper(), sign(expected)))
        self.assertFalse(kashier_utils.same_signature("", sign(expected)))

    def test_amounts_and_references(self):
        self.assertEqual(kashier_utils.format_amount(10), "10.00")
        self.assertEqual(kashier_utils.format_amount(1234.5), "1234.50")
        self.assertEqual(kashier_utils.to_number("10"), 10.0)
        self.assertIsNone(kashier_utils.to_number("x"))
        reference = kashier_utils.build_order_reference("INV/2026/00001-2 é", "a1b2c3", "ffff")
        self.assertEqual(reference, "INV-2026-00001-2-a1b2c3ffff")
        self.assertRegex(reference, r"^[A-Za-z0-9_-]+$")
        self.assertTrue(kashier_utils.is_checkout_url("https://payments.kashier.io/session/1?mode=test"))
        for url in ("http://payments.kashier.io/x", "https://payments.kashier.io.evil.com/x",
                    "https://user@payments.kashier.io/x", ""):
            self.assertFalse(kashier_utils.is_checkout_url(url), url)

    def test_classify_errors(self):
        cases = [
            (401, {"error": "Authorization error", "message": "Invalid token"}, "credentials"),
            (400, {"message": "API key mismatch or not found for mode: test"}, "credentials"),
            (403, {"message": "Unauthorized IP address"}, "ip_not_allowed"),
            (400, {"error": {"cause": "cannot refund order"}, "messages": {"en": "This order cannot be refunded with provided amount"}, "status": "FAILURE"}, "over_refund"),
            (400, {"messages": {"en": "Value 'AUTHORIZE' is invalid. Authorization request not permitted for this merchant."}}, "capture_disabled"),
            (400, {"status": "FAILURE", "response": {"status": "FAILED", "transactionResponseCode": "51"}}, "51"),
            (404, {"messages": {"en": "Transaction not found"}}, "not_found"),
            (502, "Bad gateway", "server_error"),
        ]
        for status, body, code in cases:
            with self.subTest(code=code):
                self.assertEqual(kashier_utils.classify_error(status, body), code)
        for code in const.ERROR_CODES:
            self.assertIn(const.ERROR_CODES[code][0], (const.ERROR_CUSTOMER, const.ERROR_MERCHANT, const.ERROR_UNKNOWN))

    def test_access_log_masking(self):
        line = ('"GET /payment/kashier_cf/return/7/abcdef0123?paymentStatus=SUCCESS&cardDataToken=6e06ddca-65fe'
                '&maskedCard=512345******0008&amount=10&signature=4659a5a2 HTTP/1.1" 303')
        masked = logging_filters.mask(line)
        for secret in ("6e06ddca", "4659a5a2", "abcdef0123", "512345"):
            self.assertNotIn(secret, masked)
        self.assertIn("amount=10", masked)
        self.assertEqual(logging_filters.mask('"GET /shop HTTP/1.1"'), '"GET /shop HTTP/1.1"')
        record = logging.LogRecord("odoo.http.server", logging.INFO, "", 0, line, (), None)
        logging_filters.KashierAccessLogFilter().filter(record)
        self.assertNotIn("6e06ddca", record.msg)
