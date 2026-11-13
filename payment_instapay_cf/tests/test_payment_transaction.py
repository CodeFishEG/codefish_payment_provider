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
from odoo.exceptions import UserError
from odoo.fields import Date
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment_instapay_cf import const
from odoo.addons.payment_instapay_cf.controllers.main import InstapayController
from odoo.addons.payment_instapay_cf.tests.common import (
    TRANSFER_REFERENCE,
    InstapayCommon,
)


@tagged("post_install", "-at_install")
class TestPaymentTransaction(InstapayCommon):

    def _accept(self, receipt, amount=None):
        receipt.write({
            "state": "accepted",
            "reviewed_by_id": self.reviewer.id,
            "reviewed_at": Date.today(),
            "amount_received": amount if amount is not None else receipt.amount_sent,
            "received_account_id": self.account_wallet.id,
        })

    # === CHECKOUT === #

    def test_checkout_posts_to_the_process_route(self):
        tx = self._create_instapay_tx(state="draft")
        processing_values = tx._get_processing_values()
        form = self._extract_values_from_html_form(processing_values["redirect_form_html"])
        self.assertTrue(form["action"].endswith(InstapayController._process_url))
        self.assertEqual(form["inputs"]["reference"], tx.reference)
        self.assertEqual(form["inputs"]["access_token"], self._token(tx))

    def test_checkout_event_puts_the_payment_on_hold(self):
        tx = self._create_instapay_tx(state="draft")
        self._record_event(tx, const.EVENT_CHECKOUT)
        self.assertEqual(tx.state, "pending")
        self.assertEqual(tx.instapay_cf_status, "awaiting")

    def test_mark_as_confirmed_is_blocked(self):
        tx = self._create_instapay_tx()
        with self.assertRaises(UserError):
            tx.action_confirm()
        self.assertEqual(tx.state, "pending")

    # === CONFIRMATION === #

    @mute_logger("odoo.addons.payment_instapay_cf.models.payment_transaction")
    def test_confirmation_without_accepted_receipt_is_refused(self):
        tx = self._create_instapay_tx()
        self._create_receipt(tx)
        self._record_event(tx, const.EVENT_CONFIRM, account_id=self.account_wallet.id)
        self.assertEqual(tx.state, "pending")

    @mute_logger("odoo.addons.payment_instapay_cf.models.payment_transaction")
    def test_confirmation_needs_the_whole_amount(self):
        tx = self._create_instapay_tx()
        self._accept(self._create_receipt(tx, amount_sent=1000.0))
        self._record_event(tx, const.EVENT_CONFIRM, account_id=self.account_wallet.id)
        self.assertEqual(tx.state, "pending")

    def test_confirmation_with_accepted_receipt(self):
        tx = self._create_instapay_tx()
        self._accept(self._create_receipt(tx))
        self._record_event(
            tx, const.EVENT_CONFIRM,
            account_id=self.account_wallet.id, reviewer_id=self.reviewer.id,
            received_date="2026-11-12",
        )
        self.assertEqual(tx.state, "done")
        self.assertEqual(tx.instapay_cf_status, "confirmed")
        self.assertEqual(tx.provider_reference, TRANSFER_REFERENCE)
        self.assertEqual(tx.instapay_cf_account_id, self.account_wallet)
        self.assertEqual(tx.instapay_cf_amount_received, 1500.0)
        self.assertEqual(str(tx.instapay_cf_received_date), "2026-11-12")
        self.assertEqual(tx.instapay_cf_reviewer_id, self.reviewer)

    def test_late_transfer_confirms_a_cancelled_payment(self):
        tx = self._create_instapay_tx()
        self._record_event(tx, const.EVENT_EXPIRE)
        self.assertEqual(tx.state, "cancel")
        self._accept(self._create_receipt(tx, source="staff"))
        self._record_event(tx, const.EVENT_CONFIRM, account_id=self.account_wallet.id)
        self.assertEqual(tx.state, "done")

    # === CANCELLATION === #

    def test_customer_can_cancel_before_sending_a_receipt(self):
        tx = self._create_instapay_tx()
        self._record_event(tx, const.EVENT_CANCEL_BY_CUSTOMER)
        self.assertEqual(tx.state, "cancel")
        self.assertEqual(tx.instapay_cf_cancelled_by, "customer")

    def test_customer_cant_cancel_after_sending_a_receipt(self):
        tx = self._create_instapay_tx()
        self._create_receipt(tx)
        self._record_event(tx, const.EVENT_CANCEL_BY_CUSTOMER)
        self.assertEqual(tx.state, "pending")
        self._record_event(tx, const.EVENT_EXPIRE)
        self.assertEqual(tx.state, "pending", "A receipt waits for review.")

    def test_staff_cancellation_keeps_the_message(self):
        tx = self._create_instapay_tx()
        self._record_event(tx, const.EVENT_CANCEL, message="Out of stock.", notify=True)
        self.assertEqual(tx.state, "cancel")
        self.assertEqual(tx.instapay_cf_cancelled_by, "staff")
        self.assertEqual(tx.instapay_cf_cancel_message, "Out of stock.")
        self.assertEqual(tx.instapay_cf_status, "cancelled")

    # === STATUS === #

    def test_status_follows_the_receipts(self):
        tx = self._create_instapay_tx()
        receipt = self._create_receipt(tx)
        self.assertEqual(tx.instapay_cf_status, "in_review")
        self.assertEqual(tx.instapay_cf_review_deadline, receipt.review_deadline)
        receipt.write({"state": "rejected", "reviewed_at": Date.today()})
        self.assertEqual(tx.instapay_cf_status, "rejected")
        self.assertFalse(tx.instapay_cf_review_deadline)

    # === CUSTOMER DISPLAY === #

    def test_instructions_show_how_to_pay(self):
        tx = self._create_instapay_tx()
        html = str(tx._get_status_message())
        self.assertIn("010 0123 4567", html, "The mobile number of the InstaPay account.")
        self.assertIn("010 1234 5678", html, "The wallet number.")
        self.assertIn(self.account_instapay.payment_link, html)
        self.assertIn(tx._instapay_cf_get_page_path(), html, "The link to send the receipt.")
        self.assertIn('data-copy="1500"', html, "The amount, as typed in the app.")
        self.assertNotIn("Odoo", html)

    def test_instructions_dont_show_staff_notes(self):
        tx = self._create_instapay_tx()
        receipt = self._create_receipt(tx)
        receipt.write({
            "state": "rejected", "reviewed_at": Date.today(),
            "reject_reason": "unreadable", "reject_message": "Please send a clearer screenshot.",
        })
        values = tx._instapay_cf_get_instructions_values()
        self.assertEqual(values["rejection"]["reason"], "Screenshot unreadable")
        self.assertEqual(values["rejection"]["message"], "Please send a clearer screenshot.")
        self.assertNotIn("warning", values)
        self.assertTrue(values["can_upload"])

    def test_amount_to_copy(self):
        Transaction = self.env["payment.transaction"]
        self.assertEqual(Transaction._instapay_cf_amount_to_copy(1500.0), "1500")
        self.assertEqual(Transaction._instapay_cf_amount_to_copy(1500.5), "1500.5")
        self.assertEqual(Transaction._instapay_cf_amount_to_copy(99.99), "99.99")

    # === EMAILS === #

    def test_instructions_are_emailed_once(self):
        self._disable_post_process_patcher()
        tx = self._create_instapay_tx()
        tx.with_context(payment_safe_write=True)._post_process()
        tx.with_context(payment_safe_write=True)._post_process()
        mails = self._get_mails(tx)
        self.assertEqual(len(mails), 1)
        self.assertIn(tx.reference, mails.subject)
        self.assertIn(tx._instapay_cf_get_page_path(), str(mails.body_html))
        self.assertNotIn("Odoo", str(mails.body_html))
        self.assertTrue(tx.instapay_cf_instructions_sent)

    def test_no_email_when_disabled(self):
        self._disable_post_process_patcher()
        self.instapay.instapay_cf_send_emails = False
        tx = self._create_instapay_tx()
        tx.with_context(payment_safe_write=True)._post_process()
        self.assertFalse(self._get_mails(tx))

    # === ACCOUNTING === #

    def test_payment_is_posted_in_the_journal_of_the_receiving_account(self):
        self._skip_if_account_payment_is_not_installed()
        self._disable_post_process_patcher()
        journal = self.env["account.journal"].create({
            "name": "Vodafone Cash", "code": "VFC", "type": "bank",
            "currency_id": self.currency.id,
        })
        self.account_wallet.journal_id = journal
        tx = self._create_instapay_tx()
        self._accept(self._create_receipt(tx))
        self._record_event(
            tx, const.EVENT_CONFIRM, account_id=self.account_wallet.id, received_date="2026-11-10",
        )
        payment = tx.with_context(payment_safe_write=True)._create_payment()
        self.assertEqual(payment.journal_id, journal)
        self.assertEqual(payment.payment_method_line_id.code, "manual")
        self.assertEqual(payment.payment_reference, TRANSFER_REFERENCE)
        self.assertEqual(str(payment.date), "2026-11-10")
        self.assertEqual(payment.amount, 1500.0)
        self.assertTrue(
            payment.message_ids.attachment_ids, "The screenshot is kept with the payment.",
        )

    def test_payment_falls_back_to_the_provider_journal(self):
        self._skip_if_account_payment_is_not_installed()
        self.instapay._instapay_cf_setup_journals(self.company)
        tx = self._create_instapay_tx()
        self._accept(self._create_receipt(tx))
        self._record_event(tx, const.EVENT_CONFIRM, account_id=self.account_instapay.id)
        payment = tx.with_context(payment_safe_write=True)._create_payment()
        self.assertEqual(payment.journal_id, self.instapay.journal_id)
