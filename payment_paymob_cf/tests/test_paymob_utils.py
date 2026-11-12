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
from datetime import date

from odoo.tests import tagged

from odoo.addons.payment_paymob_cf import utils as paymob_utils
from odoo.addons.payment_paymob_cf.tests.common import (
    DOCUMENTED_HMAC_STRING,
    DOCUMENTED_TOKEN_HMAC_STRING,
    HMAC_SECRET,
    PaymobCommon,
    sign,
)


@tagged("post_install", "-at_install")
class TestPaymobUtils(PaymobCommon):

    def test_transaction_hmac_string_matches_paymob_example(self):
        self.assertEqual(
            paymob_utils.get_transaction_hmac_string(self.paid_transaction), DOCUMENTED_HMAC_STRING,
        )

    def test_redirection_hmac_string_matches_the_callback(self):
        """The redirection flattens the order to `order` (or `order_id`) and sends strings."""
        params = {
            key: str(value).lower() if isinstance(value, bool) else str(value)
            for key, value in self.paid_transaction.items()
            if not isinstance(value, dict)
        }
        params.update({
            "order": "217503754",
            "source_data.pan": "2346",
            "source_data.sub_type": "MasterCard",
            "source_data.type": "card",
        })
        self.assertEqual(
            paymob_utils.get_transaction_hmac_string(params, is_redirection=True),
            DOCUMENTED_HMAC_STRING,
        )
        params["order_id"] = params.pop("order")
        self.assertEqual(
            paymob_utils.get_transaction_hmac_string(params, is_redirection=True),
            DOCUMENTED_HMAC_STRING,
        )

    def test_token_hmac_string_matches_paymob_example(self):
        self.assertEqual(
            paymob_utils.get_token_hmac_string(self.token_obj), DOCUMENTED_TOKEN_HMAC_STRING,
        )

    def test_hmac_is_sha512_in_lowercase_hexadecimal(self):
        digest = paymob_utils.compute_hmac(DOCUMENTED_HMAC_STRING, HMAC_SECRET)
        self.assertEqual(digest, sign(DOCUMENTED_HMAC_STRING))
        self.assertEqual(len(digest), 128)

    def test_provider_checks_the_signatures(self):
        self.assertTrue(self.paymob._paymob_cf_check_transaction_hmac(
            self.paid_transaction, sign(DOCUMENTED_HMAC_STRING),
        ))
        self.assertFalse(self.paymob._paymob_cf_check_transaction_hmac(
            self._transaction(amount_cents=1), sign(DOCUMENTED_HMAC_STRING),
        ))
        self.assertFalse(self.paymob._paymob_cf_check_transaction_hmac(self.paid_transaction, ""))
        self.assertTrue(self.paymob._paymob_cf_check_token_hmac(
            self.token_obj, sign(DOCUMENTED_TOKEN_HMAC_STRING),
        ))
        self.assertFalse(self.paymob._paymob_cf_check_token_hmac(
            dict(self.token_obj, token="another"), sign(DOCUMENTED_TOKEN_HMAC_STRING),
        ))

    def test_hmac_values_are_formatted_like_paymob(self):
        self.assertEqual(paymob_utils.format_hmac_value(True), "true")
        self.assertEqual(paymob_utils.format_hmac_value(False), "false")
        self.assertEqual(paymob_utils.format_hmac_value(None), "")
        self.assertEqual(paymob_utils.format_hmac_value(100000), "100000")

    def test_redirection_is_turned_into_a_transaction(self):
        transaction = paymob_utils.redirection_to_transaction({
            "id": "1", "success": "true", "pending": "false", "order": "217503754",
            "source_data.sub_type": "Visa", "data.message": "Approved",
            "txn_response_code": "APPROVED", "hmac": "x",
        })
        self.assertIs(transaction["success"], True)
        self.assertIs(transaction["pending"], False)
        self.assertEqual(transaction["order"]["id"], "217503754")
        self.assertEqual(transaction["source_data"]["sub_type"], "Visa")
        self.assertEqual(transaction["data"]["message"], "Approved")
        self.assertEqual(transaction["data"]["txn_response_code"], "APPROVED")
        self.assertNotIn("hmac", transaction)

    def test_declines_keep_their_acquirer_code(self):
        self.assertEqual(
            paymob_utils.get_decline({"data": {"acq_response_code": "51", "message": "Insufficient Funds"}}),
            ("51", "Insufficient Funds"),
        )
        self.assertEqual(
            paymob_utils.get_decline({"data": {"acq_response_code": "05"}}), ("5", ""),
        )
        # No acquirer code: guessed from Paymob's message, or a generic decline.
        self.assertEqual(
            paymob_utils.get_decline({"data": {"message": "Invalid card number"}}),
            ("14", "Invalid card number"),
        )
        self.assertEqual(
            paymob_utils.get_decline({"data": {"txn_response_code": "DECLINED"}}), ("declined", ""),
        )

    def test_api_errors_are_recognized(self):
        cases = [
            (401, "incorrect credentials", "credentials"),
            (404, "Integration ID/Name does not exist in our system", "integration"),
            (400, "Requested Refund Amount is greater than the maximum refund amount", "refund_amount"),
            (400, "Capture amount cannot exceed auth amount", "capture_amount"),
            (404, "Invalid transaction id", "transaction_id"),
            (400, "billing_data: phone_number: This field is required.", "billing_data"),
            (400, "items: name: This field is required.", "items"),
            (404, "Not found.", "not_found"),
            (502, "Bad gateway", "server"),
            (418, "teapot", "418"),
        ]
        for status, message, expected in cases:
            self.assertEqual(paymob_utils.classify_error(status, message), expected, message)

    def test_error_bodies_are_flattened(self):
        self.assertEqual(paymob_utils.flatten_errors({"detail": "incorrect credentials"}), "incorrect credentials")
        self.assertEqual(
            paymob_utils.flatten_errors({"billing_data": {"phone_number": ["This field is required."]}}),
            "billing_data: phone_number: This field is required.",
        )

    def test_card_helpers(self):
        self.assertEqual(paymob_utils.get_brand_code("MasterCard"), "mastercard")
        self.assertEqual(paymob_utils.get_brand_code("Visa"), "visa")
        self.assertIsNone(paymob_utils.get_brand_code("Unknown"))
        self.assertEqual(paymob_utils.get_last_digits("xxxx-xxxx-xxxx-2346"), "2346")
        self.assertEqual(paymob_utils.format_expiry("1", "38"), "01/38")
        self.assertEqual(paymob_utils.format_expiry("", "38"), "")
        today = date(2026, 11, 12)
        self.assertFalse(paymob_utils.is_card_expired("11/26", today))
        self.assertTrue(paymob_utils.is_card_expired("10/26", today))
        self.assertFalse(paymob_utils.is_card_expired("", today))
