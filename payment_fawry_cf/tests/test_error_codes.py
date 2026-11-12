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
from odoo.tests import tagged

from odoo.addons.payment_fawry_cf import const
from odoo.addons.payment_fawry_cf.exceptions import FawryError
from odoo.addons.payment_fawry_cf.tests.common import FawryCommon
from odoo.addons.payment_fawry_cf.tests.test_payment_provider import _response

# The codes of Fawry's Error Codes page (https://developers.fawrystaging.com/fawrypay/errorCodes).
DOCUMENTED_CODES = [
    "99901", "99903", "99904", "99905", "99906", "99907", "99908", "99910", "99912", "99913",
    "99914", "99915", "99922", "99930", "99931", "99934", "99937", "99939", "99941", "99942",
    "99943", "99949", "99951", "99954", "99955", "99956", "99957", "99958", "99959", "99961",
    "99962", "99963", "99965", "99967", "99970", "99971", "99975", "99976", "99977", "99978",
    "99979", "99980", "99981", "99984", "99985", "99986", "99987", "99988", "99989", "99991",
    "99992", "99994", "99996", "21010", "55006", "21004",
]


@tagged("post_install", "-at_install")
class TestErrorCodes(FawryCommon):

    def test_every_documented_code_is_explained(self):
        self.assertEqual(len(DOCUMENTED_CODES), 56)
        for code in DOCUMENTED_CODES:
            self.assertIn(code, const.ERROR_CODES)
        for kind, explanation in const.ERROR_CODES.values():
            self.assertIn(kind, (const.ERROR_CUSTOMER, const.ERROR_MERCHANT))
            self.assertTrue(str(explanation))

    def test_business_errors_keep_their_code(self):
        response = _response({"statusCode": 99951, "statusDescription": "Insufficient Funds"})
        with self.assertRaises(FawryError) as error:
            self.fawry._parse_response_content(response)
        self.assertEqual(error.exception.code, "99951")
        self.assertEqual(error.exception.description, "Insufficient Funds")
        self.assertIn("enough funds", str(error.exception))

    def test_customers_see_card_errors_but_not_merchant_errors(self):
        message = self.fawry._fawry_get_customer_error_message("99951")
        self.assertIn("enough funds", message)
        message = self.fawry._fawry_get_customer_error_message("9901", "Invalid merchant code")
        self.assertNotIn("merchant code", message.lower())
        self.assertIn("9901", message, "The customer can give the code to the shop.")
        message = self.fawry._fawry_get_customer_error_message(None)
        self.assertIn("couldn't be processed", message)

    def test_staff_see_what_any_code_means(self):
        self.assertIn("Secure Key", self.fawry._fawry_get_error_message("9946"))
        self.assertIn("Fawry code 9946", self.fawry._fawry_get_error_message("9946"))
        unknown = self.fawry._fawry_get_error_message("77777", "Something new")
        self.assertIn("Something new", unknown)
        self.assertIn("77777", unknown)

    def test_failed_payments_are_explained(self):
        tx = self._create_transaction("redirect")
        tx.with_context(payment_safe_write=True)._apply_updates({
            "merchantRefNumber": tx.reference,
            "orderStatus": "FAILED",
            "failureErrorCode": "99954",
            "failureReason": "Expired Card",
        })
        self.assertEqual(tx.state, "error")
        self.assertIn("expired", tx.state_message)
        self.assertEqual(tx.fawry_error_code, "99954")
        self.assertEqual(tx.fawry_error_details, "Expired Card")
        self.assertIn("Fawry code 99954", tx.fawry_error_explanation)

    def test_refused_requests_are_explained(self):
        tx = self._create_transaction("direct")
        tx._fawry_set_error(FawryError("x", code="9901", description="Invalid merchant code"))
        self.assertEqual(tx.state, "error")
        self.assertNotIn("merchant code", tx.state_message.lower())
        self.assertEqual(tx.fawry_error_code, "9901")
        self.assertIn("Merchant Code", tx.fawry_error_explanation)

    def test_saved_card_errors_are_explained_to_the_customer(self):
        self._set_integration("s2s")
        token = self._create_token(provider_ref=self.card_token)
        tx = self._create_transaction("token", token_id=token.id)
        error = FawryError("x", code="99930", description="Check setup")
        raised = None
        # Not `assertRaises`: its savepoint would undo what the transaction keeps of the error.
        with patch.object(type(tx), "_fawry_charge_card_token", side_effect=error):
            try:
                tx._send_payment_request()
            except ValidationError as exception:
                raised = exception
        self.assertIsInstance(raised, ValidationError)
        self.assertNotIsInstance(raised, FawryError)
        self.assertIn("99930", str(raised))
        self.assertEqual(tx.fawry_error_code, "99930")
