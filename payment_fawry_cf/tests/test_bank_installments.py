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
import re
import time
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment.tests.http_common import PaymentHttpCommon
from odoo.addons.payment_fawry_cf import const
from odoo.addons.payment_fawry_cf.controllers.main import FawryController
from odoo.addons.payment_fawry_cf.tests.common import MERCHANT_CODE, FawryCommon, sha256

SEND_API_REQUEST = (
    "odoo.addons.payment.models.payment_provider.PaymentProvider._send_api_request"
)
NOW = int(time.time() * 1000)
DAY = 24 * 3600 * 1000


def _plan_entry(plan_id=1952, months=6, rate=5.0, pans=("512345",), **values):
    """An installment plan as Fawry returns it."""
    plan = {
        "id": plan_id,
        "nameAr": f"{months} شهور",
        "nameEn": f"{months} months",
        "rate": rate,
        "noOfMonths": months,
        "merchantProfileCode": "TEST525785",
        "minAmount": 100.0,
        "maxAmount": 10000.0,
        "startDate": NOW - DAY,
        "endDate": NOW + DAY,
        "online": True,
        "status": {"id": 1, "code": "ACTIVE"},
        "accountType": {"nameEn": "NBE credit card", "nameAr": "بطاقة الأهلي", "pans": list(pans)},
        "type": "INDIRECT",
        **values.pop("plan", {}),
    }
    return {
        "id": 1,
        "installmentPlan": plan,
        "applyTo": "ANY_PRODUCT",
        "products": [],
        "productsCodes": [],
        **values,
    }


@tagged("post_install", "-at_install")
class TestBankInstallments(FawryCommon, PaymentHttpCommon):

    def setUp(self):
        super().setUp()
        self._set_integration("s2s")
        self.fawry.fawry_bank_installments = True

    def _eligible(self, entries, amount=150.0, card_bin="512345", product_codes=None):
        with patch(SEND_API_REQUEST, return_value=entries):
            return self.fawry._fawry_get_eligible_installment_plans(
                amount, card_bin, product_codes=product_codes,
            )

    def _patch_plans(self, entries):
        return patch(SEND_API_REQUEST, return_value=entries)

    # === PLANS === #

    def test_plans_are_read_from_a_list_or_a_single_plan(self):
        with patch(SEND_API_REQUEST, return_value=[_plan_entry(), _plan_entry(1953, 12)]) as mock:
            plans = self.fawry._fawry_get_installment_plans()
        self.assertEqual([plan["id"] for plan in plans], [1952, 1953])
        self.assertEqual(mock.call_args.args[1], const.ENDPOINT_INSTALLMENT_PLANS)
        self.assertEqual(mock.call_args.kwargs["params"], {"accountNumber": MERCHANT_CODE})
        with patch(SEND_API_REQUEST, return_value=_plan_entry()):
            self.assertEqual(len(self.fawry._fawry_get_installment_plans()), 1)

    def test_eligible_plans(self):
        self.assertEqual([plan["id"] for plan in self._eligible([_plan_entry()])], [1952])
        self.assertFalse(self._eligible([_plan_entry()], amount=50.0), "Below the minimum")
        self.assertFalse(self._eligible([_plan_entry()], card_bin="450875"), "Other bank")
        self.assertFalse(self._eligible([_plan_entry(plan={"endDate": NOW - 1})]), "Ended")
        self.assertFalse(self._eligible([_plan_entry(plan={"online": False})]), "Offline")
        limited = _plan_entry(applyTo="SPECIFIC_PRODUCTS", products=["TV-55"])
        self.assertFalse(self._eligible([limited], product_codes=["PHONE"]))
        self.assertTrue(self._eligible([limited], product_codes=["TV-55"]))

    def test_plans_need_the_feature_and_the_server_to_server_integration(self):
        self.fawry.fawry_bank_installments = False
        self.assertFalse(self._eligible([_plan_entry()]))
        self.fawry.fawry_bank_installments = True
        self.fawry.fawry_integration = const.INTEGRATION_EXPRESS
        self.assertFalse(self._eligible([_plan_entry()]))

    def test_the_admin_can_list_the_plans(self):
        with patch(SEND_API_REQUEST, return_value=[_plan_entry()]):
            action = self.fawry.action_fawry_show_installment_plans()
        self.assertIn("6 months", action["params"]["message"])
        self.assertIn("1952", action["params"]["message"])

    # === CHARGE === #

    def test_installment_charge_is_signed_with_the_plan(self):
        tx = self._create_transaction("redirect", fawry_customer_profile_id="42")
        with patch(SEND_API_REQUEST, return_value=[_plan_entry()]):
            plan = self.fawry._fawry_get_installment_plans()[0]
        with patch(SEND_API_REQUEST, return_value=self.three_ds_response) as request_mock:
            tx._fawry_charge_card_token(self.card_token, plan)
        payload = request_mock.call_args.kwargs["json"]
        self.assertEqual(payload["installmentPlanId"], 1952)
        return_url = tx._fawry_get_route_url(FawryController._return_url)
        self.assertEqual(
            payload["signature"],
            sha256(MERCHANT_CODE, tx.reference, "42", "CARD", "150.00", self.card_token, "1952",
                   return_url),
        )
        self.assertEqual(tx.fawry_installment_plan_id, 1952)
        self.assertIn("6 months", tx.fawry_installment_plan)

    def test_saved_card_with_plans_opens_the_plan_choice(self):
        token = self._create_token(provider_ref=self.card_token, fawry_card_bin="512345")
        tx = self._create_transaction("token", token_id=token.id)
        with patch(SEND_API_REQUEST, return_value=[_plan_entry()]) as request_mock:
            tx._send_payment_request()
        self.assertEqual(request_mock.call_count, 1, "Only the plans are fetched, no charge.")
        self.assertTrue(tx.fawry_redirect_url.startswith(f"{FawryController._installments_url}/"))

    # === PAGES === #

    def _route(self, route, tx):
        token = self._generate_test_access_token(tx.reference, tx.partner_id.id)
        return self._build_url(f"{route}/{tx.id}/{token}")

    @mute_logger("odoo.addons.payment_fawry_cf.controllers.main")
    def test_card_page_leads_to_the_plan_choice(self):
        tx = self._create_transaction("redirect")
        card = dict(self.saved_card, firstSixDigits="512345")
        responses = [{"cards": [card]}, [_plan_entry()]]
        with patch(SEND_API_REQUEST, side_effect=responses):
            response = self.url_open(
                self._route(FawryController._card_return_url, tx),
                params={"statusCode": "200", "token": self.card_token},
                allow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        self.assertIn(FawryController._installments_url, response.headers["Location"])

    @mute_logger("odoo.addons.payment_fawry_cf.controllers.main")
    def test_customer_pays_with_a_plan(self):
        tx = self._create_transaction("redirect", fawry_customer_profile_id="42")
        tx.with_context(payment_safe_write=True).write({
            "fawry_card_token": self.card_token,
            "fawry_card_data": {"firstSixDigits": "512345", "lastFourDigits": "0008"},
        })
        url = self._route(FawryController._installments_url, tx)
        with patch(SEND_API_REQUEST, return_value=[_plan_entry()]):
            page = self.url_open(url)
        self.assertEqual(page.status_code, 200)
        self.assertIn("6 monthly installments", page.text)
        csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        with patch(SEND_API_REQUEST, side_effect=[[_plan_entry()], self.three_ds_response]) as mock:
            response = self.url_open(
                url, data={"plan": "1952", "csrf_token": csrf_token}, allow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Location"], self.three_ds_url)
        self.assertEqual(mock.call_args.kwargs["json"]["installmentPlanId"], 1952)
