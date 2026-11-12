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
import copy
import hashlib
import hmac

from odoo.addons.payment.tests.common import PaymentCommon

HMAC_SECRET = "test-hmac-secret"

# The concatenated values of the transaction callback documented by Paymob (HMAC page).
DOCUMENTED_HMAC_STRING = (
    "1000002024-06-13T11:33:44.592345EGPfalsefalse1920364654097558truefalsefalsefalsetruefalse"
    "217503754302852false2346MasterCardcardtrue"
)
# The concatenated values of the card token callback documented by Paymob.
DOCUMENTED_TOKEN_HMAC_STRING = (
    "MasterCard2026-08-24T13:28:31.015314kiyedi3052@claspira.com15978654xxxx-xxxx-xxxx-2346"
    "10539285938815813f22ce8a4e77125c70f0bc69830e34c36df469351e2fa6be76428be4"
)


def sign(message):
    """Independent reference implementation of Paymob's HMAC, for the assertions."""
    return hmac.new(HMAC_SECRET.encode(), message.encode(), hashlib.sha512).hexdigest()


class PaymobCommon(PaymentCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.paymob = cls._prepare_provider(
            "paymob_cf",
            update_values={
                "paymob_cf_country": "EG",
                "paymob_cf_secret_key": "egy_sk_test_dummy",
                "paymob_cf_public_key": "egy_pk_test_dummy",
                "paymob_cf_api_key": "dummy-api-key",
                "paymob_cf_hmac_secret": HMAC_SECRET,
                "paymob_cf_integration": "hosted",
                "paymob_cf_display_mode": "redirect",
            },
        )
        cls.provider = cls.paymob
        cls.currency = cls._enable_currency("EGP")
        cls.amount = 1000.0
        cls.reference = "S00042-1"
        cls.partner.write({"phone": "+20 100 123 4567", "lang": "en_US"})

        def method(code):
            return cls.env.ref(f"payment_paymob_cf.payment_method_{code}")

        cls.pm_card = method("card")
        cls.pm_visa = method("visa")
        cls.pm_mastercard = method("mastercard")
        cls.pm_wallet = method("mobile_wallet_eg")
        cls.pm_kiosk = method("kiosk")
        cls.pm_valu = method("valu")
        cls.pm_paymob = method("paymob")
        (cls.pm_card + cls.pm_wallet + cls.pm_kiosk + cls.pm_valu + cls.pm_paymob).active = True
        cls.pm_card.paymob_cf_integration_id = 4097558
        cls.pm_wallet.paymob_cf_integration_id = 4097559
        cls.pm_kiosk.paymob_cf_integration_id = 4097560
        cls.pm_valu.paymob_cf_integration_id = 4097561
        cls.payment_method = cls.pm_card
        cls.payment_method_id = cls.pm_card.id
        cls.payment_method_code = "card"

        cls.order_id = "217503754"
        cls.intention_response = {
            "id": "pi_test_0123456789abcdef",
            "intention_order_id": int(cls.order_id),
            "client_secret": "egy_csk_test_0123456789",
            "payment_keys": [{"integration": 4097558, "key": "ZXlKaGJHY2lPaUpJ", "order_id": 217503754}],
            "special_reference": "S00042-1-abc123",
            "status": "intended",
        }
        # A paid card transaction, as in Paymob's documented transaction callback.
        cls.paid_transaction = {
            "id": 192036465,
            "pending": False,
            "amount_cents": 100000,
            "success": True,
            "is_auth": False,
            "is_capture": False,
            "is_standalone_payment": True,
            "is_voided": False,
            "is_refunded": False,
            "is_3d_secure": True,
            "integration_id": 4097558,
            "has_parent_transaction": False,
            "created_at": "2024-06-13T11:33:44.592345",
            "currency": "EGP",
            "error_occured": False,
            "owner": 302852,
            "order": {"id": 217503754, "merchant_order_id": "S00042-1-abc123"},
            "source_data": {"pan": "2346", "type": "card", "tenure": None, "sub_type": "MasterCard"},
            "data": {
                "message": "Approved",
                "txn_response_code": "APPROVED",
                "acq_response_code": "00",
            },
        }
        # A card token, as in Paymob's documented card token callback.
        cls.card_token = "3f22ce8a4e77125c70f0bc69830e34c36df469351e2fa6be76428be4"
        cls.token_obj = {
            "id": 15978654,
            "token": cls.card_token,
            "masked_pan": "xxxx-xxxx-xxxx-2346",
            "merchant_id": 1053928,
            "card_subtype": "MasterCard",
            "created_at": "2026-08-24T13:28:31.015314",
            "email": "kiyedi3052@claspira.com",
            "order_id": "593881581",
            "user_added": False,
            "cardholder_name": "TEST ACCOUNT",
            "expiry_month": "01",
            "expiry_year": "38",
        }

    def _transaction(self, **values):
        """Return a copy of the paid transaction, updated with the given values."""
        transaction = copy.deepcopy(self.paid_transaction)
        for key, value in values.items():
            if isinstance(value, dict) and isinstance(transaction.get(key), dict):
                transaction[key].update(value)
            else:
                transaction[key] = value
        return transaction

    def _create_paymob_transaction(self, flow="redirect", **values):
        """Create a transaction that has a Paymob payment intention."""
        return self._create_transaction(flow, **{
            "paymob_cf_order_id": self.order_id,
            "paymob_cf_special_reference": "S00042-1-abc123",
            **values,
        })

    def _set_embedded(self):
        self.paymob.write({"paymob_cf_integration": "embedded", "allow_tokenization": True})
