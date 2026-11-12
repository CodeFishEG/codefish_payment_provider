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
import hashlib

from odoo.addons.payment.tests.common import PaymentCommon

MERCHANT_CODE = "770000000001"
SECURE_KEY = "dummy-secure-key"


def sha256(*values):
    """Independent reference implementation of a Fawry signature, for the assertions."""
    return hashlib.sha256(("".join(values) + SECURE_KEY).encode()).hexdigest()


class FawryCommon(PaymentCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.fawry = cls._prepare_provider(
            "fawry",
            update_values={
                "fawry_merchant_code": MERCHANT_CODE,
                "fawry_secure_key": SECURE_KEY,
                "fawry_integration": "express",
                "fawry_display_mode": "redirect",
            },
        )
        cls.provider = cls.fawry
        cls.currency = cls._enable_currency("EGP")
        cls.amount = 150.0
        cls.reference = "S00042-1"
        cls.partner.write({"phone": "+20 100 123 4567", "lang": "en_US"})

        cls.pm_card = cls.env.ref("payment_fawry_cf.payment_method_card")
        cls.pm_pay_at_fawry = cls.env.ref("payment_fawry_cf.payment_method_pay_at_fawry")
        cls.pm_wallet = cls.env.ref("payment_fawry_cf.payment_method_mobile_wallet_eg")
        cls.pm_myfawry = cls.env.ref("payment_fawry_cf.payment_method_myfawry")
        cls.pm_valu = cls.env.ref("payment_fawry_cf.payment_method_valu")
        cls.pm_fawry = cls.env.ref("payment_fawry_cf.payment_method_fawry")
        cls.pm_visa = cls.env.ref("payment_fawry_cf.payment_method_visa")
        (
            cls.pm_card + cls.pm_pay_at_fawry + cls.pm_wallet + cls.pm_myfawry + cls.pm_valu
            + cls.pm_fawry
        ).active = True
        cls.payment_method = cls.pm_card
        cls.payment_method_id = cls.pm_card.id
        cls.payment_method_code = "card"

        cls.fawry_reference = "786884978"
        # Fawry payment status (V2) / server notification of a paid card payment.
        cls.paid_data = {
            "requestId": "2d2407d78d244a91ac2dce1c84668b75",
            "fawryRefNumber": cls.fawry_reference,
            "merchantRefNumber": cls.reference,
            "customerMerchantId": "42",
            "paymentAmount": 150.0,
            "orderAmount": 150.0,
            "fawryFees": 0.0,
            "orderStatus": "PAID",
            "paymentMethod": "CARD",
            "paymentTime": 1794478431391,
            "paymentRefrenceNumber": "128873549648",
            "orderExpiryDate": 1794480222056,
            "orderItems": [{"itemCode": "P1", "price": 150.0, "quantity": 1}],
        }
        cls.paid_data["messageSignature"] = sha256(
            cls.fawry_reference, cls.reference, "150.00", "150.00", "PAID", "CARD", "128873549648",
        )
        # Charge response of a Fawry reference code (PAYATFAWRY).
        cls.reference_code_data = {
            "type": "ChargeResponse",
            "statusCode": 200,
            "statusDescription": "Operation done successfully",
            "referenceNumber": cls.fawry_reference,
            "merchantRefNumber": cls.reference,
            "orderAmount": 150.0,
            "paymentAmount": 152.0,
            "fawryFees": 2.0,
            "orderStatus": "UNPAID",
            "paymentMethod": "PAYATFAWRY",
            "expirationTime": 1794564658179,
        }
        # Card saved on Fawry's secure card page (List Card Tokens).
        cls.card_token = "991a99d96aa7d02c476efc53133bb8759fa8f29ed673552678158295a0c80ce5"
        cls.saved_card = {
            "token": cls.card_token,
            "creationDate": 1794478449946,
            "lastFourDigits": "1019",
            "firstSixDigits": "450875",
            "brand": "Visa Card",
            "expiryDate": "01/39",
            "tokenStatus": "VALID",
        }
        cls.three_ds_url = "https://atfawry.fawrystaging.com/atfawry/plugin/3ds/786838280"
        cls.three_ds_response = {
            "type": "ChargeResponse",
            "statusCode": 200,
            "statusDescription": "Operation done successfully",
            "nextAction": {"type": "THREE_D_SECURE", "redirectUrl": cls.three_ds_url},
        }

    def _set_integration(self, integration):
        self.fawry.fawry_integration = integration
        if integration == "s2s":
            self.fawry.allow_tokenization = True
