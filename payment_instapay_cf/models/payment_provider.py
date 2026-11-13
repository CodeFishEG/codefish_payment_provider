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
import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment_instapay_cf import const

_logger = logging.getLogger(__name__)

UTC = ZoneInfo("UTC")


class PaymentProvider(models.Model):
    _inherit = "payment.provider"

    code = fields.Selection(
        selection_add=[(const.PROVIDER_CODE, "InstaPay")],
        ondelete={const.PROVIDER_CODE: "set default"},
    )
    instapay_cf_account_ids = fields.One2many(
        string="Receiving Accounts",
        help="Where your customers send the money: your InstaPay account, mobile wallets and bank "
        "accounts.",
        comodel_name="payment.instapay.account",
        inverse_name="provider_id",
        context={"active_test": False},
        copy=False,
    )
    instapay_cf_review_days = fields.Integer(
        string="Review Time (Working Days)",
        help="Working days your team needs to check a receipt. Customers see the resulting date; "
        "2 working days are 48 hours of working days.",
        default=2,
    )
    instapay_cf_calendar_id = fields.Many2one(
        string="Working Schedule",
        help="Working days and public holidays used to count the review time (in Egypt: Sunday to "
        "Thursday). The company's working schedule when empty.",
        comodel_name="resource.calendar",
        check_company=True,
        copy=False,  # Copies serve other companies, with their own schedule.
    )
    instapay_cf_reviewer_user_id = fields.Many2one(
        string="Reviewer",
        help="Who checks the receipts. Each receipt gets a review activity for this user, or for "
        "the reviewers role when empty.",
        comodel_name="res.users",
        domain=[("share", "=", False)],
        copy=False,
    )
    instapay_cf_reviewer_role_id = fields.Many2one(
        string="Reviewers Role",
        help="The role whose members check the receipts, when no reviewer is set.",
        comodel_name="res.role",
    )
    instapay_cf_require_reference = fields.Boolean(
        string="Require the Transfer Reference",
        help="Customers must type the reference number shown on their receipt.",
        default=True,
    )
    instapay_cf_reminder_days = fields.Integer(
        string="Reminder After (Days)",
        help="Remind customers who chose InstaPay but sent no receipt after this many days. 0: no "
        "reminder.",
        default=1,
    )
    instapay_cf_expiry_days = fields.Integer(
        string="Cancel After (Days)",
        help="Cancel the payments still waiting for a receipt after this many days. 0: never.",
        default=3,
    )
    instapay_cf_send_emails = fields.Boolean(
        string="Email the Customers",
        help="Send the payment details, the receipt confirmation, rejections, reminders and "
        "cancellations by email.",
        default=True,
    )
    instapay_cf_calendar_warning = fields.Char(compute="_compute_instapay_cf_warnings")
    instapay_cf_reviewer_warning = fields.Char(compute="_compute_instapay_cf_warnings")

    # === COMPUTE METHODS === #

    @api.depends(
        "code", "instapay_cf_calendar_id", "company_id.resource_calendar_id", "company_id.tz",
        "instapay_cf_reviewer_user_id", "instapay_cf_reviewer_role_id",
        "instapay_cf_reviewer_role_id.user_ids",
    )
    def _compute_instapay_cf_warnings(self):
        for provider in self:
            calendar_warning = reviewer_warning = False
            if provider.code == const.PROVIDER_CODE:
                calendar = provider._instapay_cf_get_calendar()
                if not calendar or not provider.company_id.tz:
                    calendar_warning = self.env._(
                        "Without a working schedule and a company timezone, the review time skips "
                        "Fridays and Saturdays only.",
                    )
                elif calendar.attendance_ids.filtered(lambda a: a.dayofweek == "4"):
                    calendar_warning = self.env._(
                        "The working schedule %(calendar)s works on Fridays. In Egypt, choose a "
                        "Sunday-to-Thursday schedule.",
                        calendar=calendar.display_name,
                    )
                if not provider.instapay_cf_reviewer_user_id and (
                    not provider.instapay_cf_reviewer_role_id
                    or not provider.instapay_cf_reviewer_role_id.user_ids
                ):
                    reviewer_warning = self.env._(
                        "Nobody will be asked to review the receipts: choose a reviewer, or add "
                        "users to the reviewers role.",
                    )
            provider.instapay_cf_calendar_warning = calendar_warning
            provider.instapay_cf_reviewer_warning = reviewer_warning

    # === CONSTRAINT METHODS === #

    @api.constrains("instapay_cf_review_days", "instapay_cf_reminder_days", "instapay_cf_expiry_days")
    def _check_instapay_cf_days(self):
        for provider in self.filtered(lambda p: p.code == const.PROVIDER_CODE):
            if not 1 <= provider.instapay_cf_review_days <= 10:
                raise ValidationError(self.env._("The review time must be 1 to 10 working days."))
            if provider.instapay_cf_reminder_days < 0 or provider.instapay_cf_expiry_days < 0:
                raise ValidationError(self.env._("The reminder and cancel delays can't be negative."))
            if (
                provider.instapay_cf_expiry_days
                and provider.instapay_cf_reminder_days >= provider.instapay_cf_expiry_days
            ):
                raise ValidationError(self.env._(
                    "The reminder must come before the payment is cancelled.",
                ))

    @api.constrains("is_published", "instapay_cf_account_ids", "code")
    def _check_instapay_cf_published_accounts(self):
        for provider in self.filtered(
            lambda p: p.code == const.PROVIDER_CODE and p.is_published,
        ):
            if not provider._instapay_cf_get_accounts():
                raise ValidationError(self.env._(
                    "Add at least one receiving account (InstaPay, mobile wallet or bank account) "
                    "before publishing InstaPay.",
                ))

    # === CRUD METHODS === #

    def copy_data(self, default=None):
        """Override of `base` to keep the copies live: InstaPay has no test environment. The
        payment module copies the provider into each company.
        """
        vals_list = super().copy_data(default=default)
        for provider, vals in zip(self, vals_list):
            if provider.code == const.PROVIDER_CODE:
                vals["is_live"] = True
        return vals_list

    # === BUSINESS METHODS - PAYMENT FLOW === #

    def _get_default_payment_method_codes(self):
        """Override of `payment` to return the default payment method codes."""
        self.ensure_one()
        if self.code != const.PROVIDER_CODE:
            return super()._get_default_payment_method_codes()
        return const.DEFAULT_PAYMENT_METHOD_CODES

    def _get_supported_currencies(self):
        """Override of `payment` to return EGP, the only currency of InstaPay."""
        supported_currencies = super()._get_supported_currencies()
        if self.code == const.PROVIDER_CODE:
            supported_currencies = supported_currencies.filtered(lambda c: c.name == const.CURRENCY)
        return supported_currencies

    @api.model
    def _find_available_providers(self, *args, is_validation=False, report=None, **kwargs):
        """Override of `payment` to offer InstaPay only for payments, and only when the provider
        has a receiving account to show.
        """
        providers = super()._find_available_providers(
            *args, is_validation=is_validation, report=report, **kwargs,
        )
        instapay_providers = providers.filtered(lambda p: p.code == const.PROVIDER_CODE)
        if is_validation:
            providers -= instapay_providers
            payment_utils.add_to_report(
                report, instapay_providers, available=False,
                reason=self.env._("InstaPay can't save payment methods."),
            )
        else:
            unfit_providers = instapay_providers.filtered(
                lambda p: not p.sudo()._instapay_cf_get_accounts(),
            )
            providers -= unfit_providers
            payment_utils.add_to_report(
                report, unfit_providers, available=False,
                reason=self.env._("No receiving account is set."),
            )
        return providers

    # === BUSINESS METHODS - SETUP === #

    def _instapay_cf_setup_journals(self, companies=None):
        """Give the InstaPay provider of each company its own "InstaPay" bank journal, in EGP.

        The journal is created once per company, then reused: it is found by its code. Companies
        without a chart of accounts are skipped; they get the journal when a chart is installed
        (see `account.chart.template._post_load_data`).

        :param res.company companies: The companies to set up; all companies by default.
        :rtype: None
        """
        domain = [("code", "=", const.PROVIDER_CODE)]
        if companies is not None:
            domain.append(("company_id", "in", companies.ids))
        for provider in self.sudo().with_context(active_test=False).search(domain):
            if not provider.is_live:
                provider.is_live = True  # No test environment; copies aren't live by default.
            if not provider.company_id.chart_template:
                continue  # Accounting isn't set up yet.
            journal = provider._instapay_cf_get_or_create_journal()
            if journal and provider.journal_id != journal:
                provider.journal_id = journal

    def _instapay_cf_get_or_create_journal(self):
        """Return the company's "InstaPay" journal, created if needed.

        :return: The bank journal, or an empty recordset if another kind of journal already uses
                 the code.
        :rtype: account.journal
        """
        self.ensure_one()
        Journal = self.env["account.journal"].sudo().with_context(lang="en_US")
        company = self.company_id
        journal = Journal.search(
            [("company_id", "=", company.id), ("code", "=", const.JOURNAL_CODE)], limit=1,
        )
        if journal:
            if journal.type != "bank":
                _logger.warning(
                    "Journal %s of company %s isn't a bank journal: InstaPay payments keep the "
                    "provider's journal.",
                    const.JOURNAL_CODE,
                    company.name,
                )
                return Journal
            return journal

        currency = self.env.ref(const.JOURNAL_CURRENCY_XMLID).sudo()
        if not currency.active:
            currency.active = True
        journal = Journal.with_company(company).create({
            "name": const.JOURNAL_NAME,
            "code": const.JOURNAL_CODE,
            "type": "bank",
            "currency_id": currency.id,
            "company_id": company.id,
        })
        translations = {
            lang_code: const.JOURNAL_NAME_TRANSLATIONS[lang_code.split("_")[0]]
            for lang_code, _name in self.env["res.lang"].get_installed()
            if lang_code.split("_")[0] in const.JOURNAL_NAME_TRANSLATIONS
        }
        if translations:
            journal.update_field_translations("name", translations)
        _logger.info("Created the InstaPay journal of company %s.", company.name)
        return journal

    @api.model
    def _instapay_cf_setup_reviewer_role(self):
        """Create the "InstaPay Reviewers" role with the account managers, and set it on the
        InstaPay providers that have no reviewer.

        :rtype: None
        """
        Role = self.env["res.role"].sudo()
        role = Role.search([("name", "=", const.REVIEWER_ROLE_NAME)], limit=1)
        if not role:
            managers = self.env.ref("account.group_account_manager").sudo().all_user_ids.filtered(
                lambda u: not u.share and u.active,
            )
            role = Role.create({"name": const.REVIEWER_ROLE_NAME, "user_ids": managers.ids})
        providers = self.sudo().with_context(active_test=False).search([
            ("code", "=", const.PROVIDER_CODE),
            ("instapay_cf_reviewer_user_id", "=", False),
            ("instapay_cf_reviewer_role_id", "=", False),
        ])
        providers.instapay_cf_reviewer_role_id = role

    # === BUSINESS METHODS - INSTAPAY === #

    def _instapay_cf_get_accounts(self):
        """Return the active receiving accounts of the provider, in display order."""
        self.ensure_one()
        return self.instapay_cf_account_ids.filtered("active").sorted(lambda a: (a.sequence, a.id))

    def _instapay_cf_get_calendar(self):
        """Return the working schedule used to count the review time."""
        self.ensure_one()
        return self.instapay_cf_calendar_id or self.company_id.resource_calendar_id

    def _instapay_cf_compute_review_deadline(self, start=None):
        """Return when a receipt sent at `start` must be reviewed.

        The review time is counted in working time on the working schedule, public holidays
        (global leaves) deducted: 2 working days from Thursday 15:00 on a Sunday-to-Thursday
        09:00-17:00 schedule end on Monday at 15:00. Without a schedule or a company timezone,
        whole days are added, Fridays and Saturdays skipped.

        :param datetime start: The start, naive UTC; now by default.
        :return: The deadline, naive UTC.
        :rtype: datetime
        """
        self.ensure_one()
        start = start or fields.Datetime.now()
        company = self.company_id
        calendar = self._instapay_cf_get_calendar()
        if calendar and company.tz and calendar.hours_per_day:
            calendar = calendar.with_company(company)
            deadline = calendar.plan_hours(
                self.instapay_cf_review_days * calendar.hours_per_day, start, compute_leaves=True,
            )
            if deadline:
                return deadline
            _logger.warning(
                "The working schedule %s has no working time: InstaPay reviews skip Fridays and "
                "Saturdays only.",
                calendar.display_name,
            )
        deadline = start
        days = self.instapay_cf_review_days
        while days:
            deadline += timedelta(days=1)
            if deadline.weekday() not in (4, 5):  # Friday and Saturday
                days -= 1
        return deadline

    def _instapay_cf_get_review_user_values(self):
        """Return who reviews the receipts, as the values of an activity.

        :return: `user_id` or `role_id`, or an empty dict when nobody is set.
        :rtype: dict
        """
        self.ensure_one()
        if self.instapay_cf_reviewer_user_id:
            return {"user_id": self.instapay_cf_reviewer_user_id.id}
        if self.instapay_cf_reviewer_role_id:
            return {"role_id": self.instapay_cf_reviewer_role_id.id}
        return {}
