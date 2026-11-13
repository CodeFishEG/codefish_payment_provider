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
import io

from PIL import Image

from odoo.tests import BaseCase, tagged

from odoo.addons.payment_instapay_cf import utils
from odoo.addons.payment_instapay_cf.tests.common import IBAN, LINK, make_image


@tagged("post_install", "-at_install")
class TestInstapayUtils(BaseCase):

    # === TEXT === #

    def test_arabic_digits_are_converted(self):
        self.assertEqual(utils.to_ascii_digits("٠١٠ ۱۲۳"), "010 123")

    def test_mobile_numbers_are_normalized(self):
        for value in ("01001234567", "+20 100 123 4567", "0020-100-123-4567", "201001234567",
                      "٠١٠٠١٢٣٤٥٦٧"):
            with self.subTest(value=value):
                self.assertEqual(utils.normalize_mobile(value), "01001234567")
        for value in ("0100123456", "01301234567", "+33 6 12 34 56 78", ""):
            with self.subTest(value=value):
                self.assertEqual(utils.normalize_mobile(value), "")
        self.assertEqual(utils.format_mobile("01001234567"), "010 0123 4567")

    def test_egyptian_ibans_are_checked(self):
        self.assertTrue(utils.is_valid_eg_iban(IBAN))
        self.assertTrue(utils.is_valid_eg_iban(utils.normalize_iban("eg38 0019-0005 0000 0000 2631 8000 2")))
        self.assertFalse(utils.is_valid_eg_iban(IBAN[:-1] + "3"), "Wrong check digits.")
        self.assertFalse(utils.is_valid_eg_iban("GB82WEST12345698765432"), "Not Egyptian.")
        self.assertEqual(utils.format_iban(IBAN), "EG38 0019 0005 0000 0000 2631 8000 2")

    def test_instapay_addresses_are_normalized(self):
        self.assertEqual(utils.normalize_ipa(" TestShop@InstaPay "), "testshop@instapay")
        self.assertEqual(utils.normalize_ipa("testshop@gmail.com"), "")
        self.assertEqual(utils.normalize_ipa("@instapay"), "")

    def test_only_instapay_links_are_accepted(self):
        self.assertTrue(utils.is_instapay_link(LINK))
        for url in (
            "http://ipn.eg/S/testshop/instapay/AbC123",  # Not https
            "https://ipn.eg.evil.com/S/testshop/instapay/AbC123",  # Look-alike host
            "https://user@ipn.eg/S/testshop/instapay/AbC123",  # User info
            "https://ipn.eg:8443/S/testshop/instapay/AbC123",  # Port
            "https://ipn.eg/X/testshop",  # Other path
            "https://ipn.eg/S/",  # No account
            "javascript:alert(1)",
            "",
        ):
            with self.subTest(url=url):
                self.assertFalse(utils.is_instapay_link(url))

    def test_transfer_references_are_normalized(self):
        self.assertEqual(utils.normalize_reference("2246 6394 3247"), "224663943247")
        self.assertEqual(utils.normalize_reference("٢٢٤٦٦٣٩٤٣٢٤٧"), "224663943247")
        self.assertEqual(utils.normalize_reference("ab-12cd34"), "AB12CD34")
        self.assertEqual(utils.normalize_reference("12345"), "", "Too short.")
        self.assertEqual(utils.normalize_reference("1234567<b>"), "")

    def test_text_is_cleaned(self):
        self.assertEqual(utils.clean_text(" Ahmed\x00 Ali\n ", 128), "Ahmed Ali")
        self.assertEqual(utils.clean_text("x" * 200, 128), "x" * 128)

    def test_amounts_are_parsed(self):
        self.assertEqual(utils.parse_amount("1500"), 1500.0)
        self.assertEqual(utils.parse_amount("1,500.50"), 1500.5)
        self.assertEqual(utils.parse_amount("١٬٥٠٠٫٥"), 1500.5)
        for value in ("", "abc", "-5", "1.234", "1e3"):
            with self.subTest(value=value):
                self.assertIsNone(utils.parse_amount(value))

    # === IMAGES === #

    def test_png_screenshot_is_kept_as_png(self):
        raw = make_image("PNG")
        clean, extension, sha256 = utils.sanitize_receipt(raw)
        self.assertEqual(extension, "png")
        self.assertEqual(sha256, hashlib.sha256(raw).hexdigest(), "The hash is the uploaded file's.")
        self.assertEqual(Image.open(io.BytesIO(clean)).format, "PNG")

    def test_jpeg_screenshot_is_stored_as_jpeg(self):
        clean, extension, _sha256 = utils.sanitize_receipt(make_image("JPEG"))
        self.assertEqual(extension, "jpg")
        self.assertEqual(Image.open(io.BytesIO(clean)).format, "JPEG")
        self.assertEqual(utils.receipt_accept(), "image/png,image/jpeg")

    def test_metadata_and_trailing_bytes_are_removed(self):
        image = Image.new("RGB", (200, 400), (255, 111, 100))
        exif = image.getexif()
        exif[0x0110] = "Secret Phone Model"  # Model
        output = io.BytesIO()
        image.save(output, format="JPEG", exif=exif)
        raw = output.getvalue() + b"<script>alert(1)</script>"
        clean, _extension, _sha256 = utils.sanitize_receipt(raw)
        self.assertNotIn(b"Secret Phone Model", clean)
        self.assertNotIn(b"<script>", clean)

    def test_large_screenshots_are_shrunk(self):
        clean, _extension, _sha256 = utils.sanitize_receipt(make_image("PNG", size=(1200, 4000)))
        self.assertEqual(max(Image.open(io.BytesIO(clean)).size), 2560)

    def test_other_files_are_refused(self):
        gif = make_image("GIF")
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
        png, jpeg = make_image("PNG"), make_image("JPEG")
        cases = [(gif, "type"), (svg, "unreadable"), (pdf, "unreadable"),
                 (png[:len(png) // 2], "unreadable"), (jpeg[:len(jpeg) // 2], "unreadable"),
                 (b"", "unreadable")]
        for raw, code in cases:
            with self.subTest(code=code, start=raw[:8]), self.assertRaises(utils.ReceiptError) as error:
                utils.sanitize_receipt(raw)
            self.assertEqual(error.exception.code, code)

    def test_too_many_pixels_are_refused_before_decoding(self):
        with self.assertRaises(utils.ReceiptError) as error:
            utils.sanitize_receipt(make_image("PNG", size=(12000, 100)))
        self.assertEqual(error.exception.code, "size")
