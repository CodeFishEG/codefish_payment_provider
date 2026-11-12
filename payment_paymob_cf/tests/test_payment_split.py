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

from odoo.addons.payment_paymob_cf.tests.common import PaymobCommon

SEND_API_REQUEST = (
    "odoo.addons.payment.models.payment_provider.PaymentProvider._send_api_request"
)


@tagged("post_install", "-at_install")
class TestPaymentSplit(PaymobCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product_a = cls.env["product.template"].create({"name": "Product A"})
        cls.product_b = cls.env["product.template"].create({"name": "Product B"})

    def _add_merchant(self, **values):
        return self.env["payment.paymob.split.merchant"].create({
            "provider_id": self.paymob.id,
            "name": "Seller",
            "mid": "100200",
            "share": 20.0,
            **values,
        })

    def test_shares_are_sent_with_the_intention(self):
        self.paymob.paymob_cf_payment_split = True
        self._add_merchant(name="Partner", mid="100200", share=10.0)
        self._add_merchant(name="Seller A", mid="100300", share=30.0, apply_to="products",
                           product_tmpl_ids=[(6, 0, self.product_a.ids)])
        tx = self._create_transaction("redirect")
        items = [
            {"name": "A", "amount": 60000, "_product_tmpl": self.product_a},
            {"name": "B", "amount": 40000, "_product_tmpl": self.product_b},
        ]
        split_amounts = tx._paymob_cf_get_split_amounts(items)
        self.assertEqual(split_amounts, [
            {"mid": 100200, "amount_cents": 10000, "description": f"Partner {tx.reference}"},
            {"mid": 100300, "amount_cents": 18000, "description": f"Seller A {tx.reference}"},
        ])

    def test_no_split_when_turned_off_or_archived(self):
        merchant = self._add_merchant()
        tx = self._create_transaction("redirect")
        items = [{"name": "A", "amount": 100000}]
        self.assertEqual(tx._paymob_cf_get_split_amounts(items), [])
        self.paymob.paymob_cf_payment_split = True
        merchant.active = False
        self.assertEqual(tx._paymob_cf_get_split_amounts(items), [])

    def test_intention_carries_the_split(self):
        self.paymob.paymob_cf_payment_split = True
        self._add_merchant(share=25.0)
        tx = self._create_transaction("redirect")
        with patch(SEND_API_REQUEST, return_value=self.intention_response) as request_mock:
            tx._paymob_cf_create_intention([4097558])
        self.assertEqual(request_mock.call_args.kwargs["json"]["split_amounts"], [
            {"mid": 100200, "amount_cents": 25000, "description": f"Seller {tx.reference}"},
        ])

    def test_shares_are_checked(self):
        with self.assertRaises(ValidationError):
            self._add_merchant(share=0)
        with self.assertRaises(ValidationError):
            self._add_merchant(mid="abc")
        self._add_merchant(share=70.0)
        with self.assertRaises(ValidationError):
            self._add_merchant(mid="100201", share=40.0)
        self._add_merchant(mid="100202", share=30.0, apply_to="products",
                           product_tmpl_ids=[(6, 0, self.product_a.ids)])
        with self.assertRaises(ValidationError):
            self._add_merchant(mid="100203", share=10.0, apply_to="products",
                               product_tmpl_ids=[(6, 0, self.product_a.ids)])
