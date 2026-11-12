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
from odoo.tests import tagged

from odoo.addons.payment_paymob_cf import const
from odoo.addons.payment_paymob_cf.tests.common import PaymobCommon


@tagged("post_install", "-at_install")
class TestErrorCodes(PaymobCommon):

    def test_every_code_is_explained(self):
        for code, (kind, explanation) in const.ERROR_CODES.items():
            self.assertIn(kind, (const.ERROR_CUSTOMER, const.ERROR_MERCHANT), code)
            self.assertTrue(str(explanation), code)
            message = self.paymob._paymob_cf_get_error_message(code)
            self.assertIn(f"Paymob code {code}", message)

    def test_customers_see_card_errors_but_not_merchant_errors(self):
        message = self.paymob._paymob_cf_get_customer_error_message("51")
        self.assertEqual(message, "The card doesn't have enough funds for this payment.")
        message = self.paymob._paymob_cf_get_customer_error_message("credentials", "secret details")
        self.assertIn("error credentials", message)
        self.assertNotIn("secret details", message)
        self.assertNotIn("key", message)
        message = self.paymob._paymob_cf_get_customer_error_message("")
        self.assertIn("couldn't be processed", message)

    def test_staff_see_paymob_message(self):
        message = self.paymob._paymob_cf_get_error_message("5", "Do not honour")
        self.assertIn("Paymob code 5", message)
        self.assertIn("Do not honour", message)
        message = self.paymob._paymob_cf_get_error_message("999", "Strange error")
        self.assertIn("Strange error", message)
        self.assertIn("Paymob code 999", message)

    def test_customer_texts_never_mention_odoo(self):
        for code, (kind, _explanation) in const.ERROR_CODES.items():
            if kind == const.ERROR_CUSTOMER:
                message = self.paymob._paymob_cf_get_customer_error_message(code)
                self.assertNotIn("Odoo", message, code)
