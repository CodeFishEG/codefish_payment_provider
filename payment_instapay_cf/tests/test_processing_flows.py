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

from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment.tests.http_common import PaymentHttpCommon
from odoo.addons.payment_instapay_cf.controllers.main import InstapayController
from odoo.addons.payment_instapay_cf.tests.common import (
    TRANSFER_REFERENCE,
    InstapayCommon,
    make_image,
)


@tagged("post_install", "-at_install")
class TestProcessingFlows(InstapayCommon, PaymentHttpCommon):

    def _url(self, route, tx, token=None):
        return self._build_url(f"{route}/{tx.id}/{token or self._token(tx)}")

    def _open_pay_page(self, tx):
        response = self.url_open(self._url(InstapayController._pay_url, tx))
        self.assertEqual(response.status_code, 200)
        return response

    def _csrf_token(self, tx):
        html = self._open_pay_page(tx).text
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def _send_receipt(self, tx, image=None, **data):
        form = {
            "csrf_token": self._csrf_token(tx),
            "transfer_reference": TRANSFER_REFERENCE,
            "amount_sent": "1500",
            "transferred_at": "",
            "sender_name": "Norbert",
            **data,
        }
        files = {"receipt": ("receipt.png", image or make_image(), "image/png")}
        return self.url_open(
            self._url(InstapayController._receipt_url, tx), data=form, files=files,
            allow_redirects=False,
        )

    # === CHECKOUT === #

    def test_process_route_puts_the_payment_on_hold(self):
        tx = self._create_instapay_tx(state="draft")
        response = self.url_open(
            self._build_url(InstapayController._process_url),
            data={"reference": tx.reference, "access_token": self._token(tx)},
            allow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["Location"].endswith("/payment/status"))
        self._run_processing()
        self.assertEqual(tx.state, "pending")

    @mute_logger("odoo.http")
    def test_process_route_needs_the_token(self):
        tx = self._create_instapay_tx(state="draft")
        response = self.url_open(
            self._build_url(InstapayController._process_url),
            data={"reference": tx.reference, "access_token": "wrong"},
        )
        self.assertEqual(response.status_code, 403)
        self._run_processing()
        self.assertEqual(tx.state, "draft")

    # === PAY PAGE === #

    def test_pay_page_shows_where_to_send_the_money(self):
        tx = self._create_instapay_tx()
        response = self._open_pay_page(tx)
        self.assertIn("010 0123 4567", response.text)
        self.assertIn(self.account_instapay.payment_link, response.text)
        self.assertIn('name="receipt"', response.text)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        self.assertIn("noindex", response.headers["X-Robots-Tag"])
        html = re.sub(r"<(script|style)\b.*?</\1>", "", response.text, flags=re.DOTALL)
        title = re.search(r"<title>(.*?)</title>", html, flags=re.DOTALL).group(1)
        self.assertIn(self.company.name, title)
        # The page's own content never names Odoo. With the website module, the footer is the
        # website's, as on every page of the shop; without it, the Odoo line is hidden.
        website_installed = "website" in self.env
        content = html if not website_installed else re.search(
            r"<main\b.*?</main>", html, flags=re.DOTALL,
        ).group(0)
        visible_text = re.sub(r"<[^>]+>", " ", content)
        self.assertNotIn("Odoo", visible_text + title, "Customers only know the company.")

    @mute_logger("odoo.http")
    def test_pay_page_needs_the_token(self):
        tx = self._create_instapay_tx()
        response = self.url_open(self._url(InstapayController._pay_url, tx, token="wrong"))
        self.assertEqual(response.status_code, 403)
        response = self.url_open(self._build_url(
            f"{InstapayController._pay_url}/{tx.id + 1000}/{self._token(tx)}",
        ))
        self.assertEqual(response.status_code, 403, "Same answer for a missing payment.")

    # === RECEIPTS === #

    def test_customer_sends_a_receipt(self):
        tx = self._create_instapay_tx()
        response = self._send_receipt(tx, transferred_at="2026-11-12T15:30")
        self.assertEqual(response.status_code, 303)
        self.assertIn("receipt=sent", response.headers["Location"])
        receipt = tx.instapay_cf_receipt_ids
        self.assertEqual(len(receipt), 1)
        self.assertEqual(receipt.source, "customer")
        self.assertEqual(receipt.transfer_reference, TRANSFER_REFERENCE)
        self.assertEqual(receipt.amount_sent, 1500.0)
        self.assertEqual(str(receipt.transferred_at), "2026-11-12 13:30:00", "Cairo time to UTC.")
        self.assertFalse(receipt.account_id, "Several accounts and none chosen.")
        self.assertEqual(receipt.activity_ids.user_id, self.reviewer)

        page = self.url_open(self._build_url(response.headers["Location"]))
        self.assertIn("will confirm your payment", page.text)

    def test_same_screenshot_or_quick_resend_is_refused(self):
        tx = self._create_instapay_tx()
        self._send_receipt(tx)
        response = self._send_receipt(tx, transfer_reference="999988887777")
        self.assertEqual(response.status_code, 429, "One receipt every 30 seconds.")
        tx.instapay_cf_receipt_ids.write({"state": "rejected"})
        self.env.cr.execute(
            "UPDATE payment_instapay_receipt SET submitted_at = submitted_at - interval '1 minute'",
        )
        self.env.invalidate_all()
        response = self._send_receipt(tx, transfer_reference="999988887777")
        self.assertEqual(response.status_code, 409, "The same screenshot again.")
        self.assertEqual(len(tx.instapay_cf_receipt_ids), 1)

    def test_invalid_receipts_are_refused(self):
        tx = self._create_instapay_tx()
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        for image, data in (
            (svg, {}),
            (None, {"transfer_reference": ""}),
            (None, {"transfer_reference": "<script>"}),
            (None, {"amount_sent": "abc"}),
            (None, {"amount_sent": "0"}),
            (None, {"transferred_at": "yesterday"}),
            (None, {"account_id": "999999"}),
        ):
            with self.subTest(data=data, image=image and image[:10]):
                response = self._send_receipt(tx, image=image, **data)
                self.assertEqual(response.status_code, 400)
                self.assertIn("alert-danger", response.text)
        self.assertFalse(tx.instapay_cf_receipt_ids)

    def test_receipt_without_csrf_token_is_refused(self):
        tx = self._create_instapay_tx()
        with mute_logger("odoo.http"):
            response = self.url_open(
                self._url(InstapayController._receipt_url, tx),
                data={"transfer_reference": TRANSFER_REFERENCE, "amount_sent": "1500"},
                files={"receipt": ("receipt.png", make_image(), "image/png")},
            )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(tx.instapay_cf_receipt_ids)

    def test_no_receipt_once_the_payment_is_done(self):
        tx = self._create_instapay_tx()
        csrf_token = self._csrf_token(tx)
        self._update_transaction(tx, state="done")
        response = self.url_open(
            self._url(InstapayController._receipt_url, tx),
            data={"csrf_token": csrf_token, "transfer_reference": TRANSFER_REFERENCE,
                  "amount_sent": "1500"},
            files={"receipt": ("receipt.png", make_image(), "image/png")},
        )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(tx.instapay_cf_receipt_ids)

    # === PAY ANOTHER WAY === #

    def test_customer_cancels_to_pay_another_way(self):
        tx = self._create_instapay_tx()
        response = self.url_open(
            self._url(InstapayController._cancel_url, tx),
            data={"csrf_token": self._csrf_token(tx)},
            allow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(tx.state, "cancel")
        self.assertEqual(tx.instapay_cf_cancelled_by, "customer")

    def test_customer_cant_cancel_after_sending_a_receipt(self):
        tx = self._create_instapay_tx()
        self._send_receipt(tx)
        self.url_open(
            self._url(InstapayController._cancel_url, tx),
            data={"csrf_token": self._csrf_token(tx)},
        )
        self._run_processing()
        self.assertEqual(tx.state, "pending")
