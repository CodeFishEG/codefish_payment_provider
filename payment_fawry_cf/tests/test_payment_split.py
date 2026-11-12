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

from odoo.addons.payment_fawry_cf.tests.common import MERCHANT_CODE, FawryCommon, sha256

SEND_API_REQUEST = (
    "odoo.addons.payment.models.payment_provider.PaymentProvider._send_api_request"
)


@tagged("post_install", "-at_install")
class TestPaymentSplit(FawryCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.template"].create({"name": "Chair"})
        cls.other_product = cls.env["product.template"].create({"name": "Table"})

    def setUp(self):
        super().setUp()
        self.fawry.fawry_payment_split = True

    def _add_account(self, code, share, products=None):
        return self.env["payment.fawry.split.account"].create({
            "provider_id": self.fawry.id,
            "name": code,
            "code": code,
            "share": share,
            "apply_to": "products" if products else "all",
            "product_tmpl_ids": [(6, 0, products.ids)] if products else [],
        })

    def test_items_are_shared_between_the_sub_accounts_and_the_merchant(self):
        self._add_account("SUB-1", 10)
        tx = self._create_transaction("redirect")
        items = tx._fawry_get_charge_items()
        self.assertEqual(items[0]["accounts"], [
            {"accountCode": "SUB-1", "amount": 15.0},
            {"accountCode": MERCHANT_CODE, "amount": 135.0},
        ])
        self.assertTrue(all(not key.startswith("_") for item in items for key in item))

    def test_sub_accounts_of_some_products(self):
        self._add_account("SELLER", 80, products=self.product)
        tx = self._create_transaction("redirect")
        items = [
            {"itemId": "1", "price": 33.33, "quantity": 3, "_product_tmpl": self.product},
            {"itemId": "2", "price": 50.0, "quantity": 1, "_product_tmpl": self.other_product},
        ]
        tx._fawry_add_split_accounts(items)
        self.assertEqual(items[0]["accounts"], [
            {"accountCode": "SELLER", "amount": 79.99},
            {"accountCode": MERCHANT_CODE, "amount": 20.0},
        ])
        total = sum(account["amount"] for account in items[0]["accounts"])
        self.assertAlmostEqual(total, 99.99, places=2, msg="The shares add up to the item.")
        self.assertEqual(items[1]["accounts"], [{"accountCode": MERCHANT_CODE, "amount": 50.0}])

    def test_full_share_leaves_nothing_to_the_merchant(self):
        self._add_account("SUB-1", 100)
        tx = self._create_transaction("redirect")
        self.assertEqual(
            tx._fawry_get_charge_items()[0]["accounts"],
            [{"accountCode": "SUB-1", "amount": 150.0}],
        )

    def test_no_split_when_turned_off(self):
        self._add_account("SUB-1", 10)
        self.fawry.fawry_payment_split = False
        tx = self._create_transaction("redirect")
        self.assertNotIn("accounts", tx._fawry_get_charge_items()[0])

    def test_shares_above_the_price_are_refused(self):
        self._add_account("SUB-1", 60)
        with self.assertRaises(ValidationError):
            self._add_account("SUB-2", 50)
        self._add_account("SELLER", 30, products=self.product)
        with self.assertRaises(ValidationError):
            self._add_account("SELLER-2", 20, products=self.product)
        with self.assertRaises(ValidationError):
            self._add_account("ZERO", 0)

    def test_checkout_request_carries_the_split_with_the_same_signature(self):
        self._add_account("SUB-1", 10)
        tx = self._create_transaction("redirect")
        payload = tx.with_context(payment_safe_write=True)._fawry_prepare_checkout_request()
        item = payload["chargeItems"][0]
        self.assertEqual(len(item["accounts"]), 2)
        self.assertEqual(
            payload["signature"],
            sha256(
                MERCHANT_CODE, tx.reference, payload["customerProfileId"], payload["returnUrl"],
                f"{item['itemId']}1150.00",
            ),
        )

    def test_server_to_server_charges_carry_the_split(self):
        self._set_integration("s2s")
        self._add_account("SUB-1", 10)
        tx = self._create_transaction("direct", payment_method_id=self.pm_pay_at_fawry.id)
        with patch(SEND_API_REQUEST, return_value=self.reference_code_data) as request_mock:
            tx.with_context(payment_safe_write=True)._fawry_charge()
        self.assertEqual(
            request_mock.call_args.kwargs["json"]["chargeItems"][0]["accounts"][0],
            {"accountCode": "SUB-1", "amount": 15.0},
        )
