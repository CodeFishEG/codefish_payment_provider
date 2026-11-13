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

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.http import request
from odoo.tools import format_amount, format_date
from odoo.tools.image import image_data_uri

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_instapay_cf import const
from odoo.addons.payment_instapay_cf.controllers.main import InstapayController

_logger = get_payment_logger(__name__)

# Marks the transactions whose instructions were already rendered in the current request, so that
# pages showing the payment status twice (the order portal page) show the instructions once.
RENDERED_KEY = "payment_instapay_cf.rendered_tx_ids"


class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    instapay_cf_receipt_ids = fields.One2many(
        string="InstaPay Receipts",
        comodel_name="payment.instapay.receipt",
        inverse_name="transaction_id",
        readonly=True,
    )
    instapay_cf_status = fields.Selection(
        string="InstaPay Status",
        selection=[
            ("awaiting", "Waiting for the transfer"),
            ("in_review", "Receipt to review"),
            ("rejected", "Receipt rejected"),
            ("confirmed", "Confirmed"),
            ("cancelled", "Cancelled"),
        ],
        compute="_compute_instapay_cf_status",
        store=True,
        index=True,
    )
    instapay_cf_review_deadline = fields.Datetime(
        string="Review Deadline", compute="_compute_instapay_cf_review_deadline", store=True,
    )
    instapay_cf_account_id = fields.Many2one(
        string="Received In",
        comodel_name="payment.instapay.account",
        readonly=True,
        ondelete="set null",
    )
    instapay_cf_amount_received = fields.Monetary(string="Amount Received", readonly=True)
    instapay_cf_received_date = fields.Date(string="Received On", readonly=True)
    instapay_cf_reviewer_id = fields.Many2one(
        string="Confirmed By", comodel_name="res.users", readonly=True,
    )
    instapay_cf_cancelled_by = fields.Selection(
        string="Cancelled By",
        selection=[("customer", "Customer"), ("staff", "Staff"), ("expiry", "No receipt in time")],
        readonly=True,
    )
    instapay_cf_cancel_message = fields.Text(string="Cancellation Message", readonly=True)
    instapay_cf_notify_cancel = fields.Boolean(readonly=True)
    instapay_cf_instructions_sent = fields.Boolean(readonly=True)
    instapay_cf_reminder_sent = fields.Boolean(readonly=True)

    # === COMPUTE METHODS === #

    @api.depends("provider_code", "state", "instapay_cf_receipt_ids.state")
    def _compute_instapay_cf_status(self):
        for tx in self:
            if tx.provider_code != const.PROVIDER_CODE:
                tx.instapay_cf_status = False
                continue
            states = set(tx.instapay_cf_receipt_ids.mapped("state"))
            if tx.state in ("done", "authorized"):
                status = "confirmed"
            elif tx.state in ("cancel", "error"):
                status = "cancelled"
            elif "submitted" in states:
                status = "in_review"
            elif states == {"rejected"}:
                status = "rejected"
            else:
                status = "awaiting"
            tx.instapay_cf_status = status

    @api.depends("instapay_cf_receipt_ids.state", "instapay_cf_receipt_ids.review_deadline")
    def _compute_instapay_cf_review_deadline(self):
        for tx in self:
            deadlines = tx.instapay_cf_receipt_ids.filtered(
                lambda r: r.state == "submitted" and r.review_deadline,
            ).mapped("review_deadline")
            tx.instapay_cf_review_deadline = min(deadlines) if deadlines else False

    # === ACTION METHODS === #

    def action_confirm(self):
        """Override of `payment` to confirm InstaPay payments only from their receipts, after the
        accountant checked the transfer.
        """
        if self.filtered(lambda tx: tx.provider_code == const.PROVIDER_CODE):
            raise UserError(self.env._(
                "Confirm InstaPay payments from their receipt: open the receipt and click Confirm "
                "Payment, or add the receipt the customer sent you first.",
            ))
        return super().action_confirm()

    def action_instapay_cf_review(self):
        """Open the receipts of the payment that wait for review."""
        self.ensure_one()
        receipts = self.instapay_cf_receipt_ids.filtered(lambda r: r.state == "submitted")
        action = {
            "type": "ir.actions.act_window",
            "res_model": "payment.instapay.receipt",
            "name": self.env._("Receipts of %(reference)s", reference=self.reference),
        }
        if len(receipts) == 1:
            return {**action, "view_mode": "form", "res_id": receipts.id}
        return {
            **action,
            "view_mode": "list,form",
            "domain": [("transaction_id", "=", self.id)],
        }

    def action_instapay_cf_add_receipt(self):
        """Open a new receipt for a proof the customer sent another way (e.g. by WhatsApp)."""
        self.ensure_one()
        if self.state not in ("pending", "cancel"):
            raise UserError(self.env._("Receipts can only be added to waiting or cancelled payments."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "payment.instapay.receipt",
            "name": self.env._("Add a receipt"),
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_transaction_id": self.id,
                "default_source": "staff",
            },
        }

    def action_instapay_cf_cancel(self):
        """Open the wizard cancelling the payment."""
        self.ensure_one()
        return {
            "name": self.env._("Cancel the InstaPay payment"),
            "type": "ir.actions.act_window",
            "res_model": "payment.instapay.review.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_transaction_id": self.id,
                "default_decision": "cancel",
                "default_receipt_ids": [(6, 0, self.instapay_cf_receipt_ids.filtered(
                    lambda r: r.state == "submitted",
                ).ids)],
            },
        }

    # === BUSINESS METHODS - PAYMENT FLOW === #

    def _get_specific_rendering_values(self, processing_values):
        """Override of `payment` to send the customer to the page with the transfer details.

        Note: self.ensure_one() from `_get_processing_values`
        """
        if self.provider_code != const.PROVIDER_CODE:
            return super()._get_specific_rendering_values(processing_values)
        if self.landing_route in ("/my/invoices", "/my/invoices/"):
            # Paying several invoices lands on their list, which doesn't show the payment status.
            self.landing_route = self._instapay_cf_get_page_path()
        return {
            "api_url": InstapayController._process_url,
            "url_params": {
                "reference": self.reference,
                "access_token": self._instapay_cf_get_access_token(),
            },
        }

    def _apply_updates(self, payment_data):
        """Override of `payment` to update the transaction from the InstaPay events.

        The events are only recorded by Odoo itself: the checkout route (customer), the review
        wizard (accountant) and the expiry cron. A confirmation also needs receipts accepted by a
        reviewer for the whole amount.
        """
        if self.provider_code != const.PROVIDER_CODE:
            super()._apply_updates(payment_data)
            return

        event = payment_data.get(const.EVENT_KEY)
        if event == const.EVENT_CHECKOUT:
            if self.state == "draft":
                self._set_pending()
        elif event == const.EVENT_CONFIRM:
            self._instapay_cf_apply_confirmation(payment_data)
        elif event in (const.EVENT_CANCEL, const.EVENT_EXPIRE, const.EVENT_CANCEL_BY_CUSTOMER):
            self._instapay_cf_apply_cancellation(event, payment_data)
        else:
            _logger.warning("Ignored an unknown InstaPay event for transaction %s.", self.reference)

    def _instapay_cf_apply_confirmation(self, payment_data):
        accepted = self.instapay_cf_receipt_ids.filtered(
            lambda r: r.state == "accepted" and r.reviewed_by_id,
        )
        received = sum(accepted.mapped("amount_received"))
        if not accepted or self.currency_id.compare_amounts(received, self.amount) < 0:
            _logger.warning(
                "Refused to confirm transaction %s: its accepted receipts don't cover the amount.",
                self.reference,
            )
            return
        account = self.env["payment.instapay.account"].browse(
            payment_data.get("account_id"),
        ).exists()
        reviewer = self.env["res.users"].browse(payment_data.get("reviewer_id")).exists()
        references = ", ".join(r.transfer_reference for r in accepted if r.transfer_reference)
        self.write({
            "instapay_cf_account_id": account.id,
            "instapay_cf_amount_received": received,
            "instapay_cf_received_date": payment_data.get("received_date")
            or fields.Date.context_today(self),
            "instapay_cf_reviewer_id": reviewer.id,
            "provider_reference": references or self.provider_reference,
        })
        self._set_done(extra_allowed_states=("cancel",))

    def _instapay_cf_apply_cancellation(self, event, payment_data):
        if self.state != "pending":
            return
        open_receipts = self.instapay_cf_receipt_ids.filtered(
            lambda r: r.state in ("submitted", "accepted"),
        )
        if event == const.EVENT_CANCEL_BY_CUSTOMER and open_receipts:
            return  # The customer already sent a receipt; only the accountant can cancel.
        if event == const.EVENT_EXPIRE and open_receipts:
            return  # A receipt came in the meantime.
        cancelled_by = {
            const.EVENT_CANCEL: "staff",
            const.EVENT_EXPIRE: "expiry",
            const.EVENT_CANCEL_BY_CUSTOMER: "customer",
        }[event]
        self.write({
            "instapay_cf_cancelled_by": cancelled_by,
            "instapay_cf_cancel_message": payment_data.get("message") or False,
            "instapay_cf_notify_cancel": bool(payment_data.get("notify", True)),
        })
        self._set_canceled(state_message=self.env._(
            "InstaPay payment cancelled (%(by)s).",
            by=dict(self._fields["instapay_cf_cancelled_by"]._description_selection(self.env))[
                cancelled_by
            ],
        ))

    def _extract_amount_data(self, payment_data):
        """Override of `payment` to skip the amount check: the accountant checks the amount
        received when confirming.
        """
        if self.provider_code != const.PROVIDER_CODE:
            return super()._extract_amount_data(payment_data)
        return None

    def _post_process(self):
        """Override of `payment` to email the customer: the payment details when the payment
        waits for the transfer, the confirmation when no sales order sends one, the cancellation.
        """
        super()._post_process()
        for tx in self.filtered(lambda t: t.provider_code == const.PROVIDER_CODE):
            if tx.state == "pending" and not tx.instapay_cf_instructions_sent:
                tx._instapay_cf_send_email("payment_instapay_cf.mail_template_instapay_instructions")
                tx.instapay_cf_instructions_sent = True
            elif tx.state == "done" and not tx._instapay_cf_has_sale_orders():
                tx._instapay_cf_send_email("payment_instapay_cf.mail_template_instapay_confirmed")
            elif tx.state == "cancel" and tx.instapay_cf_notify_cancel and (
                tx.instapay_cf_cancelled_by in ("staff", "expiry")
            ):
                tx._instapay_cf_send_email("payment_instapay_cf.mail_template_instapay_cancelled")

    def _create_payment(self, **extra_create_values):
        """Override of `account_payment` to post the payment in the journal of the account that
        received the money, with the InstaPay reference, and to keep the screenshots with it.
        """
        if self.provider_code != const.PROVIDER_CODE:
            return super()._create_payment(**extra_create_values)
        values = {}
        if self.provider_reference:
            values["payment_reference"] = self.provider_reference
        if self.instapay_cf_received_date:
            values["date"] = self.instapay_cf_received_date
        journal = self.instapay_cf_account_id.journal_id
        if journal and journal != self.provider_id.journal_id:
            line = self._instapay_cf_get_payment_method_line(journal)
            if line:
                values.update(journal_id=journal.id, payment_method_line_id=line.id)
        payment = super()._create_payment(**{**values, **extra_create_values})
        accepted = self.instapay_cf_receipt_ids.filtered(lambda r: r.state == "accepted")
        if accepted:
            payment.message_post(
                body=self.env._("Receipts of the InstaPay transfer."),
                attachments=[
                    (r.image_filename or f"{self.reference}-receipt.png", r.image.content)
                    for r in accepted if r.image
                ],
            )
        return payment

    def _instapay_cf_get_payment_method_line(self, journal):
        """Return the incoming payment method line to use in the journal: the provider's, else the
        manual one.
        """
        lines = journal.inbound_payment_method_line_ids
        return (
            lines.filtered(lambda line: line.payment_provider_id == self.provider_id)[:1]
            or lines.filtered(lambda line: line.code == "manual")[:1]
        )

    # === BUSINESS METHODS - CUSTOMER DISPLAY === #

    def _get_status_message(self, **kwargs):
        """Override of `payment` to show the transfer details while the payment waits, and the
        reason and a way to pay again once it is cancelled.
        """
        message = super()._get_status_message(**kwargs)
        if (
            self.provider_code != const.PROVIDER_CODE
            or self.operation == "validation"
            or self.state not in ("pending", "cancel")
        ):
            return message
        if request:
            rendered = request.httprequest.environ.setdefault(RENDERED_KEY, set())
            if self.id in rendered:
                return Markup()  # Already shown on this page.
            rendered.add(self.id)
        return self.env["ir.qweb"]._render(
            "payment_instapay_cf.payment_instructions",
            {"values": self._instapay_cf_get_instructions_values(), "status_message": message},
        )

    def _instapay_cf_get_instructions_values(self, on_pay_page=False):
        """Return what customers see about the payment: the amount, where to send it, the status
        of their receipts. Only customer-safe data: no warnings or internal notes.

        :param bool on_pay_page: Whether the values are for the page where receipts are sent.
        :rtype: dict
        """
        self.ensure_one()
        tx = self.sudo()
        provider = tx.provider_id
        company = tx.company_id
        lang = tx.partner_lang or self.env.lang
        receipts = tx.instapay_cf_receipt_ids.sorted("submitted_at")
        rejected = receipts.filtered(lambda r: r.state == "rejected")[-1:]
        submitted = receipts.filtered(lambda r: r.state == "submitted")
        review_date = submitted[:1].review_date if submitted else False
        reason_labels = dict(self.env["payment.instapay.receipt"]._fields[
            "reject_reason"
        ]._description_selection(self.with_context(lang=lang).env))
        page_url = tx._instapay_cf_get_page_url()
        status = tx.instapay_cf_status
        return {
            "tx": tx,
            "company_name": company.name,
            "company_phone": company.phone,
            "company_email": company.email,
            "amount_display": format_amount(self.env, tx.amount, tx.currency_id),
            "amount_copy": self._instapay_cf_amount_to_copy(tx.amount),
            "reference": tx.reference,
            "accounts": [account._get_customer_values() for account in provider._instapay_cf_get_accounts()],
            "status": status,
            "review_days": provider.instapay_cf_review_days,
            "review_date_text": review_date and format_date(
                self.env, review_date, lang_code=lang, date_format="EEEE d MMMM",
            ),
            "rejection": rejected and {
                "reason": reason_labels.get(rejected.reject_reason, ""),
                "message": rejected.reject_message,
            },
            "receipts": [
                {
                    "submitted_at": format_date(self.env, r.submitted_at, lang_code=lang),
                    "state": r.state,
                    "reference": r.transfer_reference,
                }
                for r in receipts
            ],
            "on_pay_page": on_pay_page,
            "pay_page_url": page_url,
            "pay_page_qr": not on_pay_page and self._instapay_cf_get_qr_data_uri(page_url),
            "can_upload": tx.state == "pending",
            "can_cancel": tx.state == "pending" and not (
                receipts.filtered(lambda r: r.state in ("submitted", "accepted"))
            ),
            "over_limit": tx.amount > const.MAX_AMOUNT_PER_TRANSFER,
            "max_per_transfer": format_amount(self.env, const.MAX_AMOUNT_PER_TRANSFER, tx.currency_id),
            "require_reference": provider.instapay_cf_require_reference,
            "cancelled_by": tx.instapay_cf_cancelled_by,
            "cancel_message": tx.instapay_cf_cancel_message,
            "document_url": tx._instapay_cf_get_document_url(),
        }

    @api.model
    def _instapay_cf_amount_to_copy(self, amount):
        """Return the amount as customers type it in the InstaPay app: 1500 or 1500.5."""
        return f"{amount:.2f}".rstrip("0").rstrip(".")

    def _instapay_cf_get_qr_data_uri(self, value):
        """Return a QR code of the value as a data URI, or False."""
        try:
            png = self.env["ir.actions.report"].sudo().barcode(
                "QR", value, width=200, height=200, barLevel="M",
            )
        except ValueError:
            return False
        return image_data_uri(png)

    def _instapay_cf_get_access_token(self):
        """Return the token protecting the InstaPay pages of this transaction."""
        self.ensure_one()
        return payment_utils.generate_access_token(
            const.PROVIDER_CODE, self.id, self.reference, self.partner_id.id, env=self.env,
        )

    def _instapay_cf_get_page_path(self):
        """Return the path of the page where the customer sends the receipt."""
        self.ensure_one()
        return f"{InstapayController._pay_url}/{self.id}/{self._instapay_cf_get_access_token()}"

    def _instapay_cf_get_page_url(self):
        """Return the absolute URL of the page where the customer sends the receipt."""
        self.ensure_one()
        return self.provider_id.get_base_url().rstrip("/") + self._instapay_cf_get_page_path()

    def _instapay_cf_get_document_url(self):
        """Return the portal page of the invoice or the order paid, to pay again."""
        self.ensure_one()
        invoice = self.invoice_ids[:1]
        if invoice:
            return invoice.get_portal_url()
        if self._instapay_cf_has_sale_orders():
            return self.sale_order_ids[:1].get_portal_url()
        return "/my"

    def _instapay_cf_has_sale_orders(self):
        return "sale_order_ids" in self._fields and bool(self.sale_order_ids)

    # === BUSINESS METHODS - EMAILS === #

    def _instapay_cf_send_email(self, template_xmlid):
        """Email the customer with the given template, in their language, without the
        "Powered by Odoo" layout: customers only know the company.
        """
        self.ensure_one()
        tx = self.sudo()
        if not tx.provider_id.instapay_cf_send_emails or not tx.partner_id.email:
            return
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if not template:
            return
        template.sudo().send_mail(tx.id, email_layout_xmlid=False)

    def _instapay_cf_get_email_body(self, kind):
        """Return the HTML body of a customer email, rendered in the customer's language.

        :param str kind: instructions, received, rejected, reminder, confirmed or cancelled.
        :rtype: Markup
        """
        self.ensure_one()
        tx = self.sudo().with_context(lang=self.partner_lang or self.env.lang)
        values = tx._instapay_cf_get_instructions_values()
        base_url = tx.provider_id.get_base_url().rstrip("/")
        document_url = values["document_url"]
        values.update({
            "kind": kind,
            "company": tx.company_id,
            "partner_name": tx.partner_name or tx.partner_id.name,
            "logo_url": f"{base_url}/payment_instapay_cf/static/img/instapay_logo.png",
            "document_absolute_url": (
                document_url if document_url.startswith("http") else f"{base_url}{document_url}"
            ),
        })
        return tx.env["ir.qweb"]._render("payment_instapay_cf.email_body", values)

    # === BUSINESS METHODS - CRON === #

    @api.model
    def _cron_instapay_cf_remind_and_expire(self):
        """Remind the customers who chose InstaPay but sent no receipt, then cancel their payment
        after the delay set on the provider.
        """
        now = fields.Datetime.now()
        PaymentData = self.env["payment.data"].sudo()
        providers = self.env["payment.provider"].sudo().search([
            ("code", "=", const.PROVIDER_CODE),
        ])
        for provider in providers:
            reminder_days = provider.instapay_cf_reminder_days
            expiry_days = provider.instapay_cf_expiry_days
            if not reminder_days and not expiry_days:
                continue
            txs = self.sudo().search(
                Domain("provider_id", "=", provider.id)
                & Domain("state", "=", "pending")
                & Domain("instapay_cf_status", "in", ("awaiting", "rejected")),
                order="last_state_change, id",
                limit=200,
            )
            for tx in txs:
                if PaymentData.search_count(
                    [("transaction_id", "=", tx.id), ("errored", "=", False)], limit=1,
                ):
                    continue  # An event is being processed.
                rejections = tx.instapay_cf_receipt_ids.filtered("reviewed_at").mapped("reviewed_at")
                start = max([tx.last_state_change or tx.create_date, *rejections])
                if expiry_days and start + timedelta(days=expiry_days) <= now:
                    tx._record({
                        "reference": tx.reference,
                        const.EVENT_KEY: const.EVENT_EXPIRE,
                    })
                elif (
                    reminder_days
                    and not tx.instapay_cf_reminder_sent
                    and start + timedelta(days=reminder_days) <= now
                ):
                    tx._instapay_cf_send_email(
                        "payment_instapay_cf.mail_template_instapay_reminder",
                    )
                    tx.with_context(payment_safe_write=True).instapay_cf_reminder_sent = True

    # === BUSINESS METHODS - REVIEW === #

    def _instapay_cf_has_pending_event(self):
        """Return whether an event of the transaction waits to be processed."""
        self.ensure_one()
        return bool(self.env["payment.data"].sudo().search_count(
            [("transaction_id", "=", self.id), ("errored", "=", False)], limit=1,
        ))

    def _instapay_cf_get_paid_elsewhere_warning(self):
        """Return why confirming would pay the documents twice, or False.

        The invoices may have been paid another way (a card, a registered payment), or the order
        confirmed by another payment, while the customer's InstaPay payment waited.
        """
        self.ensure_one()
        tx = self.sudo()
        paid_invoices = tx.invoice_ids.filtered(
            lambda inv: inv.state == "posted" and inv.payment_state in ("paid", "in_payment", "reversed"),
        )
        if paid_invoices:
            return self.env._(
                "%(invoices)s is already paid. Confirming would record a second payment.",
                invoices=", ".join(paid_invoices.mapped("display_name")),
            )
        if tx._instapay_cf_has_sale_orders():
            other_txs = tx.sale_order_ids.transaction_ids.filtered(
                lambda t: t != tx and t.state in ("done", "authorized"),
            )
            if other_txs:
                return self.env._(
                    "%(orders)s is already paid by %(payments)s. Confirming would record a second "
                    "payment.",
                    orders=", ".join(tx.sale_order_ids.mapped("name")),
                    payments=", ".join(other_txs.mapped("reference")),
                )
        return False
