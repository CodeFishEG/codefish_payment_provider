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

from odoo.addons.payment_paymob_cf import const
from odoo.addons.payment_paymob_cf.tests.common import PaymobCommon


@tagged("post_install", "-at_install")
class TestAccountJournal(PaymobCommon):

    def test_provider_has_its_own_journal(self):
        self.env["payment.provider"]._paymob_cf_setup_providers(self.company)
        journal = self.paymob.journal_id
        self.assertEqual(journal.code, const.JOURNAL_CODE)
        self.assertEqual(journal.name, "Paymob")
        self.assertEqual(journal.type, "bank")
        self.assertEqual(journal.currency_id.name, "EGP")

    def test_journal_is_created_once(self):
        Provider = self.env["payment.provider"]
        Provider._paymob_cf_setup_providers(self.company)
        Provider._paymob_cf_setup_providers(self.company)
        self.assertEqual(
            self.env["account.journal"].search_count([
                ("company_id", "=", self.company.id), ("code", "=", const.JOURNAL_CODE),
            ]),
            1,
        )

    def test_journal_follows_the_country_while_it_has_no_entries(self):
        self.env["payment.provider"]._paymob_cf_setup_providers(self.company)
        self.paymob.paymob_cf_country = "AE"
        self.assertEqual(self.paymob.journal_id.currency_id.name, "AED")

    def test_another_kind_of_journal_with_the_code_is_left_alone(self):
        journal = self.env["account.journal"].search([
            ("company_id", "=", self.company.id), ("code", "=", const.JOURNAL_CODE),
        ])
        if journal:
            journal.code = "PMOLD"
            journal.flush_recordset()
        self.env["account.journal"].create({
            "name": "Paymob Sales",
            "code": const.JOURNAL_CODE,
            "type": "sale",
            "company_id": self.company.id,
        })
        self.assertFalse(self.paymob._paymob_cf_get_or_create_journal())

    def test_new_company_gets_the_country_of_its_company(self):
        company = self.env["res.company"].create({
            "name": "Paymob KSA",
            "country_id": self.env.ref("base.sa").id,
        })
        provider = self.env["payment.provider"].sudo().search(
            [("code", "=", "paymob_cf"), ("company_id", "=", company.id)], limit=1,
        ) or self.paymob.copy({"company_id": company.id})
        provider.paymob_cf_secret_key = False
        self.env["payment.provider"]._paymob_cf_setup_providers(company)
        self.assertEqual(provider.paymob_cf_country, "SA")
        self.assertEqual(provider.available_currency_ids.name, "SAR")
