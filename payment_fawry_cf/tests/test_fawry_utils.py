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
from odoo.tests import BaseCase, tagged

from odoo.addons.payment_fawry_cf import utils as fawry_utils
from odoo.addons.payment_fawry_cf.tests.common import SECURE_KEY, sha256


@tagged("post_install", "-at_install")
class TestFawryUtils(BaseCase):

    def test_format_amount_uses_two_decimals(self):
        self.assertEqual(fawry_utils.format_amount(703), "703.00")
        self.assertEqual(fawry_utils.format_amount("580.5"), "580.50")
        self.assertEqual(fawry_utils.format_amount(0.1 + 0.2), "0.30")

    def test_signature_skips_empty_values(self):
        """Optional values that are missing are left out of the signed string."""
        signature = fawry_utils.compute_signature(
            "770", "REF", "", "PAYATFAWRY", "10.00", None, secure_key=SECURE_KEY,
        )
        self.assertEqual(signature, sha256("770", "REF", "PAYATFAWRY", "10.00"))

    def test_charge_response_signature_signs_present_fields_only(self):
        """The return redirect of a 3-D Secure payment, as received from Fawry's staging."""
        data = {
            "referenceNumber": "786838280",
            "merchantRefNumber": "S00042-1",
            "orderAmount": "200",
            "paymentAmount": "200",
            "fawryFees": "0",
            "orderStatus": "PAID",
            "paymentMethod": "CARD",
            "authNumber": "786838280",
        }
        self.assertEqual(
            fawry_utils.compute_charge_response_signature(data, SECURE_KEY),
            sha256("786838280", "S00042-1", "200.00", "200.00", "PAID", "CARD", "0.00",
                   "786838280"),
        )

    def test_notification_signature_includes_payment_reference_when_present(self):
        data = {
            "fawryRefNumber": "786838280",
            "merchantRefNumber": "S00042-1",
            "paymentAmount": 200.0,
            "orderAmount": 200.0,
            "orderStatus": "PAID",
            "paymentMethod": "CARD",
            "paymentRefrenceNumber": "128873549648",
        }
        self.assertEqual(
            fawry_utils.compute_notification_signature(data, SECURE_KEY),
            sha256("786838280", "S00042-1", "200.00", "200.00", "PAID", "CARD", "128873549648"),
        )
        del data["paymentRefrenceNumber"]
        self.assertEqual(
            fawry_utils.compute_notification_signature(data, SECURE_KEY),
            sha256("786838280", "S00042-1", "200.00", "200.00", "PAID", "CARD"),
        )

    def test_normalize_mobile(self):
        for raw, expected in [
            ("+20 100 123 4567", "01001234567"),
            ("00201001234567", "01001234567"),
            ("201001234567", "01001234567"),
            ("0112-345-6789", "01123456789"),
            ("01512345678", "01512345678"),
            ("01312345678", ""),  # Not an Egyptian mobile prefix.
            ("0032 12 34 56 78", ""),  # Not Egyptian.
            ("", ""),
            (False, ""),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(fawry_utils.normalize_mobile(raw), expected)

    def test_languages(self):
        self.assertEqual(fawry_utils.get_fawry_language("ar_EG"), "ar-eg")
        self.assertEqual(fawry_utils.get_fawry_language("ar_001"), "ar-eg")
        self.assertEqual(fawry_utils.get_fawry_language("en_US"), "en-gb")
        self.assertEqual(fawry_utils.get_fawry_locale("ar_EG"), "ar")
        self.assertEqual(fawry_utils.get_fawry_locale(False), "en")

    def test_brand_codes(self):
        self.assertEqual(fawry_utils.get_brand_code("Visa Card"), "visa")
        self.assertEqual(fawry_utils.get_brand_code("Master Card"), "mastercard")
        self.assertEqual(fawry_utils.get_brand_code("MEEZA"), "meeza")
        self.assertIsNone(fawry_utils.get_brand_code("Unknown"))

    def test_brand_codes_from_card_numbers(self):
        """Fawry's staging reports the Mastercard test card as "BMISCARD"."""
        self.assertEqual(fawry_utils.get_brand_code("BMISCARD", "512345"), "mastercard")
        self.assertEqual(fawry_utils.get_brand_code("", "450875"), "visa")
        self.assertEqual(fawry_utils.get_brand_code(None, "507808"), "meeza")
        self.assertEqual(fawry_utils.get_brand_code("BMISCARD", "222100"), "mastercard")
        self.assertIsNone(fawry_utils.get_brand_code("BMISCARD", "360000"))
