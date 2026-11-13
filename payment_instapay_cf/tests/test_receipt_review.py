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
import io
from datetime import timedelta

from PIL import Image

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Datetime
from odoo.tests import tagged
from odoo.tools import BinaryBytes

from odoo.addons.payment_instapay_cf.tests.common import (
    TRANSFER_REFERENCE,
    InstapayCommon,
    make_image,
)


@tagged("post_install", "-at_install")
class TestReceipt(InstapayCommon):

    def test_receipt_starts_the_review(self):
        tx = self._create_instapay_tx()
        receipt = self._create_receipt(tx, transfer_reference="2246 6394 3247")

        self.assertEqual(receipt.state, "submitted")
        self.assertEqual(receipt.transfer_reference, TRANSFER_REFERENCE)
        self.assertEqual(receipt.partner_id, self.partner)
        self.assertEqual(receipt.amount_expected, 1500.0)
        self.assertTrue(receipt.image_sha256)
        self.assertEqual(Image.open(io.BytesIO(receipt.image.content)).format, "PNG")
        expected_deadline = self.instapay._instapay_cf_compute_review_deadline(receipt.submitted_at)
        self.assertEqual(receipt.review_deadline, expected_deadline)

        activity = receipt.activity_ids
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity.user_id, self.reviewer, "Never the public user of the route.")
        self.assertEqual(activity.date_deadline, receipt.review_date)
        self.assertEqual(
            activity.activity_type_id,
            self.env.ref("payment_instapay_cf.mail_activity_type_instapay_review"),
        )
        self.assertTrue(receipt.message_main_attachment_id, "The screenshot shows in the preview.")
        self.assertEqual(tx.instapay_cf_status, "in_review")
        self.assertIn("received your receipt", self._get_mails(tx).subject)

    def test_activity_goes_to_the_reviewers_role(self):
        role = self.env["res.role"].create({"name": "Reviewers", "user_ids": [self.reviewer.id]})
        self.instapay.write({
            "instapay_cf_reviewer_user_id": False, "instapay_cf_reviewer_role_id": role.id,
        })
        receipt = self._create_receipt(self._create_instapay_tx())
        self.assertEqual(receipt.activity_ids.role_id, role)

    def test_receipt_of_another_provider_is_refused(self):
        tx = self._create_transaction("redirect", provider_id=self.dummy_provider.id,
                                      payment_method_id=self.dummy_payment_method.id)
        with self.assertRaises(ValidationError):
            self._create_receipt(tx)

    def test_receipt_needs_an_image(self):
        tx = self._create_instapay_tx()
        with self.assertRaises(ValidationError):
            self._create_receipt(tx, image=BinaryBytes(b"<svg/>"))
        with self.assertRaises(ValidationError):
            self._create_receipt(tx, image=False)

    def test_evidence_cant_be_changed(self):
        receipt = self._create_receipt(self._create_instapay_tx())
        for values in (
            {"amount_sent": 1.0},
            {"transfer_reference": "999999999999"},
            {"image": BinaryBytes(make_image("PNG", color=(0, 0, 0)))},
        ):
            with self.subTest(values=values), self.assertRaises(UserError):
                receipt.write(values)

    def test_accepted_receipt_cant_be_deleted(self):
        receipt = self._create_receipt(self._create_instapay_tx())
        receipt.write({"state": "accepted"})
        with self.assertRaises(UserError):
            receipt.unlink()

    # === WARNINGS === #

    def test_duplicates_are_flagged(self):
        first = self._create_receipt(self._create_instapay_tx())
        other_tx = self._create_instapay_tx(reference="S00078")
        second = self._create_receipt(other_tx)  # Same image and reference
        third = self._create_receipt(
            self._create_instapay_tx(reference="S00079"),
            transfer_reference="111122223333",
            image=BinaryBytes(make_image("PNG", color=(1, 2, 3))),
        )
        self.assertEqual(second.duplicate_receipt_ids, first)
        self.assertTrue(first.has_duplicate)
        self.assertFalse(third.has_duplicate)
        Receipt = self.env["payment.instapay.receipt"]
        self.assertEqual(Receipt.search([("has_duplicate", "=", True)]), first + second)
        self.assertEqual(
            Receipt.search([("id", "in", (first + third).ids), ("has_duplicate", "=", False)]),
            third,
        )

    def test_amount_and_time_warnings(self):
        tx = self._create_instapay_tx()
        receipt = self._create_receipt(
            tx, amount_sent=1400.0, transferred_at=Datetime.now() + timedelta(hours=2),
        )
        self.assertTrue(receipt.amount_mismatch)
        self.assertEqual(receipt.time_warning, "future")
        old = self._create_receipt(
            tx, transfer_reference="999988887777",
            image=BinaryBytes(make_image("PNG", color=(9, 9, 9))),
            transferred_at=tx.create_date - timedelta(days=2),
        )
        self.assertFalse(old.amount_mismatch)
        self.assertEqual(old.time_warning, "before_order")

    def test_overdue_receipts(self):
        receipt = self._create_receipt(self._create_instapay_tx())
        Receipt = self.env["payment.instapay.receipt"]
        self.assertFalse(receipt.is_overdue)
        receipt.review_deadline = Datetime.now() - timedelta(hours=1)
        self.assertTrue(receipt.is_overdue)
        self.assertIn(receipt, Receipt.search([("is_overdue", "=", True)]))
        receipt.state = "rejected"
        self.assertNotIn(receipt, Receipt.search([("is_overdue", "=", True)]))


@tagged("post_install", "-at_install")
class TestReviewWizard(InstapayCommon):

    def _wizard(self, receipts, decision, user=None, **values):
        return self.env["payment.instapay.review.wizard"].with_user(user or self.reviewer).create({
            "transaction_id": receipts.transaction_id.id or values.pop("transaction_id"),
            "decision": decision,
            "receipt_ids": [(6, 0, receipts.ids)],
            **values,
        })

    def test_confirm(self):
        tx = self._create_instapay_tx()
        receipt = self._create_receipt(tx, account_id=self.account_wallet.id)
        wizard = self._wizard(receipt, "confirm")
        self.assertEqual(wizard.received_account_id, self.account_wallet)
        self.assertEqual(wizard.amount_received, 1500.0)
        with self.assertRaises(UserError):
            wizard.action_apply()  # The statement isn't checked.
        wizard.statement_checked = True
        wizard.action_apply()
        self._run_processing()

        self.assertEqual(receipt.state, "accepted")
        self.assertEqual(receipt.reviewed_by_id, self.reviewer)
        self.assertEqual(receipt.received_account_id, self.account_wallet)
        self.assertFalse(receipt.activity_ids, "The review activity is done.")
        self.assertEqual(tx.state, "done")
        self.assertEqual(tx.instapay_cf_reviewer_id, self.reviewer)

    def test_form_shows_only_real_warnings(self):
        # The wizard's form works on new records: a receipt must not be its own duplicate.
        tx = self._create_instapay_tx()
        receipt = self._create_receipt(tx)
        Wizard = self.env["payment.instapay.review.wizard"].with_user(self.reviewer)
        values = {"transaction_id": tx.id, "decision": "confirm", "receipt_ids": [(6, 0, receipt.ids)]}
        self.assertFalse(Wizard.new(values).warning_text)
        self._create_receipt(self._create_instapay_tx(reference="S00078"))  # Same screenshot
        self.env.invalidate_all()  # As a new request of the web client
        self.assertIn("another payment", Wizard.new(values).warning_text or "")

    def test_confirm_refuses_a_lower_amount(self):
        tx = self._create_instapay_tx()
        receipt = self._create_receipt(tx)
        wizard = self._wizard(receipt, "confirm", statement_checked=True, amount_received=1000.0)
        with self.assertRaises(UserError):
            wizard.action_apply()
        self.assertEqual(receipt.state, "submitted")

    def test_confirm_needs_the_warnings_checked(self):
        tx = self._create_instapay_tx()
        receipt = self._create_receipt(tx, amount_sent=1600.0)
        wizard = self._wizard(receipt, "confirm", statement_checked=True)
        self.assertTrue(wizard.warning_text)
        with self.assertRaises(UserError):
            wizard.action_apply()
        wizard.warnings_checked = True
        wizard.action_apply()
        self.assertEqual(receipt.state, "accepted")

    def test_reference_can_be_accepted_once(self):
        first_tx = self._create_instapay_tx()
        self._wizard(
            self._create_receipt(first_tx), "confirm", statement_checked=True,
        ).action_apply()
        second_tx = self._create_instapay_tx(reference="S00078")
        receipt = self._create_receipt(
            second_tx, image=BinaryBytes(make_image("PNG", color=(4, 5, 6))),
        )
        wizard = self._wizard(receipt, "confirm", statement_checked=True, warnings_checked=True)
        with self.assertRaises(UserError):
            wizard.action_apply()

    def test_reject_asks_for_a_new_receipt(self):
        tx = self._create_instapay_tx()
        receipt = self._create_receipt(tx)
        wizard = self._wizard(receipt, "reject", reject_reason="unreadable")
        self.assertIn("could not read", wizard.customer_message)
        wizard.action_apply()
        self._run_processing()

        self.assertEqual(receipt.state, "rejected")
        self.assertEqual(receipt.reject_reason, "unreadable")
        self.assertEqual(receipt.reject_message, wizard.customer_message)
        self.assertFalse(receipt.activity_ids)
        self.assertEqual(tx.state, "pending")
        self.assertEqual(tx.instapay_cf_status, "rejected")
        self.assertIn("couldn't confirm", " ".join(self._get_mails(tx).mapped("subject")))

    def test_reject_and_cancel(self):
        tx = self._create_instapay_tx()
        receipt = self._create_receipt(tx)
        self._wizard(receipt, "reject", reject_reason="already_used", cancel_payment=True).action_apply()
        self._run_processing()
        self.assertEqual(tx.state, "cancel")
        self.assertEqual(tx.instapay_cf_cancelled_by, "staff")
        self.assertTrue(tx.instapay_cf_cancel_message)

    def test_cancel_rejects_open_receipts(self):
        tx = self._create_instapay_tx()
        receipt = self._create_receipt(tx)
        self._wizard(receipt, "cancel", reject_reason="other").action_apply()
        self._run_processing()
        self.assertEqual(receipt.state, "rejected")
        self.assertEqual(tx.state, "cancel")

    def test_reviewed_receipts_cant_be_reviewed_again(self):
        tx = self._create_instapay_tx()
        receipt = self._create_receipt(tx)
        self._wizard(receipt, "reject", reject_reason="other").action_apply()
        with self.assertRaises(UserError):
            receipt.action_open_confirm()
        with self.assertRaises(UserError):
            self._wizard(receipt, "confirm", statement_checked=True).action_apply()

    def test_only_invoicing_users_review(self):
        readonly_user = self._create_new_internal_user(login="instapay_readonly")
        self._prepare_user(readonly_user, "account.group_account_readonly")
        receipt = self._create_receipt(self._create_instapay_tx())
        receipt.with_user(readonly_user).read(["state"])  # Can see the receipts
        with self.assertRaises(AccessError):
            self._wizard(receipt, "confirm", user=readonly_user, statement_checked=True)

    def test_paid_elsewhere_blocks_the_confirmation(self):
        tx = self._create_instapay_tx()
        receipt = self._create_receipt(tx)
        self.patch(
            type(tx), "_instapay_cf_get_paid_elsewhere_warning",
            lambda _tx: "S00077 is already paid.",
        )
        wizard = self._wizard(receipt, "confirm", statement_checked=True)
        with self.assertRaises(UserError):
            wizard.action_apply()
