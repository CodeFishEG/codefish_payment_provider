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
from odoo.tests import tagged

from odoo.addons.payment_fawry_cf import const
from odoo.addons.payment_fawry_cf.tests.common import FawryCommon


@tagged("post_install", "-at_install")
class TestAccountJournal(FawryCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.egp = cls.env.ref("base.EGP")

    def _fawry_journals(self, company):
        return self.env["account.journal"].search([
            ("company_id", "=", company.id), ("code", "=", const.JOURNAL_CODE),
        ])

    def test_install_gives_the_provider_a_fawry_pay_journal(self):
        """The post-install hook created the journal and set it on the provider."""
        if not self.fawry.company_id.chart_template:
            self.skipTest("The company has no chart of accounts.")
        journal = self._fawry_journals(self.fawry.company_id)
        self.assertEqual(len(journal), 1)
        self.assertEqual(journal.with_context(lang="en_US").name, "Fawry Pay")
        self.assertEqual(journal.type, "bank")
        self.assertEqual(journal.currency_id, self.egp)
        self.assertEqual(self.fawry.journal_id, journal)
        method_line = journal.inbound_payment_method_line_ids.filtered(
            lambda line: line.payment_provider_id == self.fawry,
        )
        self.assertEqual(method_line.code, "fawry")

    def test_setup_reuses_the_journal(self):
        if not self.fawry.company_id.chart_template:
            self.skipTest("The company has no chart of accounts.")
        self.env["payment.provider"]._fawry_setup_journals()
        self.env["payment.provider"]._fawry_setup_journals()
        self.assertEqual(len(self._fawry_journals(self.fawry.company_id)), 1)

    def test_new_company_gets_its_journal_with_its_chart_of_accounts(self):
        """A company created after the install gets the journal, named in Arabic too, when its
        chart of accounts is installed.
        """
        self.env["res.lang"]._activate_lang("ar_001")
        company = self.env["res.company"].sudo().create({
            "name": "Fawry Egypt",
            "country_id": self.env.ref("base.eg").id,
            "currency_id": self.egp.id,
        })
        provider = self.env["payment.provider"].sudo().search([
            ("code", "=", "fawry"), ("company_id", "=", company.id),
        ])
        self.assertTrue(provider, "The provider is copied into new companies.")
        self.assertFalse(self._fawry_journals(company))

        self.env["account.chart.template"].sudo().try_loading(
            "generic_coa", company, install_demo=False,
        )
        journal = self._fawry_journals(company)
        self.assertEqual(len(journal), 1)
        self.assertEqual(journal.currency_id, self.egp)
        self.assertEqual(provider.journal_id, journal)
        self.assertEqual(journal.with_context(lang="en_US").name, "Fawry Pay")
        self.assertEqual(journal.with_context(lang="ar_001").name, "مدفوعات فورى")

    def test_paid_transaction_is_posted_in_the_fawry_pay_journal(self):
        if not self.fawry.company_id.chart_template:
            self.skipTest("The company has no chart of accounts.")
        self._disable_post_process_patcher()
        tx = self._create_transaction("redirect", state="done")
        tx.with_context(payment_safe_write=True)._post_process()
        self.assertTrue(tx.payment_id)
        self.assertEqual(tx.payment_id.journal_id, self._fawry_journals(tx.company_id))
