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
from datetime import timedelta

from odoo.fields import Datetime
from odoo.tests import tagged

from odoo.addons.payment_instapay_cf.tests.common import InstapayCommon


@tagged("post_install", "-at_install")
class TestRemindAndExpire(InstapayCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.instapay.write({"instapay_cf_reminder_days": 1, "instapay_cf_expiry_days": 3})

    def _create_waiting_tx(self, waited, **values):
        tx = self._create_instapay_tx(**values)
        self._update_transaction(tx, last_state_change=Datetime.now() - waited)
        return tx

    def _run_cron(self):
        self.env["payment.transaction"]._cron_instapay_cf_remind_and_expire()
        self._run_processing()

    def test_customer_is_reminded_once(self):
        tx = self._create_waiting_tx(timedelta(days=1, minutes=5))
        self._run_cron()
        self._run_cron()
        mails = self._get_mails(tx)
        self.assertEqual(len(mails), 1)
        self.assertIn(tx._instapay_cf_get_page_path(), str(mails.body_html))
        self.assertTrue(tx.instapay_cf_reminder_sent)
        self.assertEqual(tx.state, "pending")

    def test_recent_payment_is_left_alone(self):
        tx = self._create_waiting_tx(timedelta(hours=5))
        self._run_cron()
        self.assertFalse(self._get_mails(tx))
        self.assertEqual(tx.state, "pending")

    def test_unpaid_payment_is_cancelled(self):
        self._disable_post_process_patcher()
        tx = self._create_waiting_tx(timedelta(days=3, minutes=5))
        self._run_cron()
        self.assertEqual(tx.state, "cancel")
        self.assertEqual(tx.instapay_cf_cancelled_by, "expiry")
        self._run_post_processing()
        self.assertIn("no receipt", str(self._get_mails(tx)[:1].body_html))

    def test_payment_with_a_receipt_to_review_is_kept(self):
        tx = self._create_waiting_tx(timedelta(days=10))
        self._create_receipt(tx)
        self._run_cron()
        self.assertEqual(tx.state, "pending")

    def test_delay_restarts_after_a_rejection(self):
        tx = self._create_waiting_tx(timedelta(days=10))
        receipt = self._create_receipt(tx)
        receipt.write({"state": "rejected", "reviewed_at": Datetime.now() - timedelta(hours=30)})
        self._run_cron()
        self.assertEqual(tx.state, "pending", "3 days from the rejection, not from the order.")
        self.assertTrue(tx.instapay_cf_reminder_sent)

    def test_nothing_happens_without_delays(self):
        self.instapay.write({"instapay_cf_reminder_days": 0, "instapay_cf_expiry_days": 0})
        tx = self._create_waiting_tx(timedelta(days=30))
        self._run_cron()
        self.assertEqual(tx.state, "pending")
        self.assertFalse(self._get_mails(tx))
