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
from datetime import datetime

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import BinaryBytes

from odoo.addons.payment_instapay_cf import const
from odoo.addons.payment_instapay_cf.tests.common import (
    IBAN,
    InstapayCommon,
    make_image,
)


@tagged("post_install", "-at_install")
class TestPaymentProvider(InstapayCommon):

    # === AVAILABILITY === #

    def test_only_egp_is_supported(self):
        self.assertEqual(self.instapay._get_supported_currencies().mapped("name"), ["EGP"])

    def test_provider_is_available_for_payments(self):
        providers = self.env["payment.provider"]._find_available_providers(
            self.company.id, self.partner.id, self.amount, currency_id=self.currency.id,
        )
        self.assertIn(self.instapay, providers)

    def test_provider_is_hidden_for_validations(self):
        report = {}
        providers = self.env["payment.provider"]._find_available_providers(
            self.company.id, self.partner.id, 0.0, currency_id=self.currency.id,
            is_validation=True, report=report,
        )
        self.assertNotIn(self.instapay, providers)

    def test_provider_without_active_account_is_hidden(self):
        # The constraints forbid it; data imported or edited in SQL could still get there.
        self.env.cr.execute(
            "UPDATE payment_instapay_account SET active = false WHERE provider_id = %s",
            [self.instapay.id],
        )
        self.env.invalidate_all()
        report = {}
        providers = self.env["payment.provider"]._find_available_providers(
            self.company.id, self.partner.id, self.amount, currency_id=self.currency.id,
            report=report,
        )
        self.assertNotIn(self.instapay, providers)

    def test_provider_is_always_live(self):
        self.assertTrue(self.instapay.is_live)
        copy = self.instapay.copy()
        self.assertTrue(copy.is_live, "InstaPay has no test environment.")

    # === PUBLISHING AND SETTINGS === #

    def test_published_provider_needs_an_account(self):
        with self.assertRaises(ValidationError):
            (self.account_instapay + self.account_wallet).active = False
        self.instapay.is_published = False
        (self.account_instapay + self.account_wallet).active = False
        with self.assertRaises(ValidationError):
            self.instapay.is_published = True

    def test_last_account_of_published_provider_cant_be_deleted(self):
        self.account_wallet.unlink()
        with self.assertRaises(ValidationError):
            self.account_instapay.unlink()

    def test_days_must_be_consistent(self):
        with self.assertRaises(ValidationError):
            self.instapay.instapay_cf_review_days = 0
        with self.assertRaises(ValidationError):
            self.instapay.write({"instapay_cf_reminder_days": 3, "instapay_cf_expiry_days": 3})
        self.instapay.write({"instapay_cf_reminder_days": 3, "instapay_cf_expiry_days": 0})

    def test_reviewer_values(self):
        self.assertEqual(
            self.instapay._instapay_cf_get_review_user_values(), {"user_id": self.reviewer.id},
        )
        role = self.env["res.role"].create({"name": "Reviewers", "user_ids": [self.reviewer.id]})
        self.instapay.write({
            "instapay_cf_reviewer_user_id": False, "instapay_cf_reviewer_role_id": role.id,
        })
        self.assertEqual(self.instapay._instapay_cf_get_review_user_values(), {"role_id": role.id})
        self.assertFalse(self.instapay.instapay_cf_reviewer_warning)
        self.instapay.instapay_cf_reviewer_role_id = False
        self.assertTrue(self.instapay.instapay_cf_reviewer_warning)

    def test_calendar_working_on_friday_is_flagged(self):
        self.assertFalse(self.instapay.instapay_cf_calendar_warning)
        self.calendar.attendance_ids = [(0, 0, {"hour_from": 9, "hour_to": 17, "dayofweek": "4"})]
        self.instapay.invalidate_recordset(["instapay_cf_calendar_warning"])
        self.assertTrue(self.instapay.instapay_cf_calendar_warning)

    # === REVIEW DEADLINE === #

    def test_deadline_counts_working_time(self):
        # Thursday 12 November 2026, 15:00 in Cairo (13:00 UTC): 2 hours on Thursday, 8 on
        # Sunday, 6 on Monday.
        deadline = self.instapay._instapay_cf_compute_review_deadline(datetime(2026, 11, 12, 13, 0))
        self.assertEqual(deadline, datetime(2026, 11, 16, 13, 0), "Monday 15:00 in Cairo.")

    def test_deadline_skips_public_holidays(self):
        self.env["resource.calendar.leaves"].create({
            "name": "Public holiday",
            "calendar_id": False,
            "company_id": self.company.id,
            "date_from": datetime(2026, 11, 15, 0, 0),  # Sunday, UTC
            "date_to": datetime(2026, 11, 15, 23, 0),
        })
        deadline = self.instapay._instapay_cf_compute_review_deadline(datetime(2026, 11, 12, 13, 0))
        self.assertEqual(deadline, datetime(2026, 11, 17, 13, 0), "Tuesday 15:00 in Cairo.")

    def test_deadline_without_working_time_skips_friday_and_saturday(self):
        self.company.tz = False
        deadline = self.instapay._instapay_cf_compute_review_deadline(datetime(2026, 11, 12, 13, 0))
        self.assertEqual(deadline, datetime(2026, 11, 16, 13, 0), "Thursday + 2 days = Monday.")

    # === JOURNAL === #

    def test_provider_has_its_egp_journal(self):
        self._skip_if_account_payment_is_not_installed()
        self.instapay._instapay_cf_setup_journals(self.company)
        journal = self.instapay.journal_id
        self.assertEqual(journal.code, const.JOURNAL_CODE)
        self.assertEqual(journal.type, "bank")
        self.assertEqual(journal.currency_id.name, "EGP")
        self.instapay._instapay_cf_setup_journals(self.company)
        self.assertEqual(
            self.env["account.journal"].search_count([
                ("company_id", "=", self.company.id), ("code", "=", const.JOURNAL_CODE),
            ]),
            1,
            "The journal is reused.",
        )


@tagged("post_install", "-at_install")
class TestReceivingAccount(InstapayCommon):

    def _create_account(self, **values):
        return self.env["payment.instapay.account"].create({
            "provider_id": self.instapay.id, "holder_name": "Test Shop", **values,
        })

    def test_details_are_normalized(self):
        self.assertEqual(self.account_instapay.mobile, "01001234567")
        account = self._create_account(kind="bank", bank_name="CIB", iban="eg38 0019 0005 0000 0000 2631 8000 2")
        self.assertEqual(account.iban, IBAN)
        self.assertEqual(account.name, "CIB")
        self.assertEqual(self.account_wallet.name, "Vodafone Cash")

    def test_invalid_details_are_refused(self):
        for values in (
            {"kind": "instapay", "payment_link": "https://ipn.eg.evil.com/S/shop"},
            {"kind": "instapay", "mobile": "0123"},
            {"kind": "instapay", "ipa": "shop@gmail.com"},
            {"kind": "instapay"},
            {"kind": "wallet", "wallet_operator": "vodafone_cash"},
            {"kind": "bank", "bank_name": "CIB"},
            {"kind": "bank", "bank_name": "CIB", "iban": IBAN[:-1] + "3"},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                self._create_account(**values)

    def test_journal_must_be_in_egp(self):
        journal = self.env["account.journal"].create({
            "name": "USD Bank", "code": "USDB", "type": "bank",
            "currency_id": self.currency_usd.id,
        })
        if journal.currency_id.name == "EGP":
            self.skipTest("The company currency is EGP.")
        with self.assertRaises(ValidationError):
            self.account_wallet.journal_id = journal

    def test_qr_image_is_cleaned(self):
        self.account_instapay.qr_image = BinaryBytes(make_image("JPEG") + b"<trailing>")
        self.assertNotIn(b"<trailing>", self.account_instapay.qr_image.content)
        with self.assertRaises(ValidationError):
            self.account_instapay.qr_image = BinaryBytes(b"<svg/>")

    def test_customer_values(self):
        values = self.account_instapay._get_customer_values()
        self.assertEqual(values["link"], self.account_instapay.payment_link)
        self.assertTrue(values["qr_data_uri"].startswith("data:image/png;base64,"))
        mobile_row = values["rows"][0]
        self.assertEqual(mobile_row["display"], "010 0123 4567")
        self.assertEqual(mobile_row["copy"], "01001234567")
        self.assertEqual(self.account_wallet._get_label(), "Vodafone Cash 010 1234 5678")
