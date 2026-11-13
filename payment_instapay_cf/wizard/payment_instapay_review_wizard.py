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
from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import format_amount

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment_instapay_cf import const


class PaymentInstapayReviewWizard(models.TransientModel):
    """Confirm an InstaPay payment after finding the transfer, reject a receipt, or cancel the
    payment.
    """

    _name = "payment.instapay.review.wizard"
    _description = "InstaPay Payment Review"

    transaction_id = fields.Many2one(
        comodel_name="payment.transaction", required=True, readonly=True, ondelete="cascade",
    )
    decision = fields.Selection(
        selection=[
            ("confirm", "Confirm the payment"),
            ("reject", "Reject the receipt"),
            ("cancel", "Cancel the payment"),
        ],
        required=True,
        default="confirm",
    )
    receipt_ids = fields.Many2many(
        string="Receipts",
        comodel_name="payment.instapay.receipt",
        domain="[('transaction_id', '=', transaction_id), ('state', '=', 'submitted')]",
    )
    currency_id = fields.Many2one(related="transaction_id.currency_id")
    amount_expected = fields.Monetary(string="Amount to Pay", related="transaction_id.amount")
    provider_id = fields.Many2one(related="transaction_id.provider_id")
    company_id = fields.Many2one(related="transaction_id.company_id")

    # Confirmation
    received_account_id = fields.Many2one(
        string="Received In",
        help="The account where you found the money. The payment is posted in its journal.",
        comodel_name="payment.instapay.account",
        domain="[('provider_id', '=', provider_id)]",
        compute="_compute_confirm_defaults",
        store=True,
        readonly=False,
    )
    amount_received = fields.Monetary(
        string="Amount Received",
        compute="_compute_confirm_defaults",
        store=True,
        readonly=False,
    )
    date_received = fields.Date(string="Received On", default=fields.Date.context_today)
    statement_checked = fields.Boolean(
        string="I found this transfer in the statement of the receiving account",
        help="Check the bank, wallet or InstaPay app history of the account: never confirm from "
        "the screenshot or an SMS alone.",
    )
    warning_text = fields.Text(compute="_compute_warning_text")
    warnings_checked = fields.Boolean(string="I checked the warnings above")
    paid_elsewhere = fields.Char(compute="_compute_paid_elsewhere")

    # Rejection and cancellation
    reject_reason = fields.Selection(
        string="Reason", selection=const.REJECT_REASONS, default="not_received",
    )
    customer_message = fields.Text(
        string="Message to the Customer",
        compute="_compute_customer_message",
        store=True,
        readonly=False,
    )
    cancel_payment = fields.Boolean(
        string="Also cancel the payment",
        help="The customer can't send another receipt for this payment, and must pay again.",
    )

    # === COMPUTE METHODS === #

    @api.depends("receipt_ids", "transaction_id")
    def _compute_confirm_defaults(self):
        for wizard in self:
            receipts = wizard.receipt_ids
            wizard.received_account_id = (
                receipts.account_id[:1]
                or wizard.transaction_id.provider_id._instapay_cf_get_accounts()[:1]
            )
            declared = sum(receipts.mapped("amount_sent"))
            wizard.amount_received = declared or wizard.transaction_id.amount

    @api.depends("receipt_ids")
    def _compute_warning_text(self):
        for wizard in self:
            lines = []
            for receipt in wizard.receipt_ids:
                if receipt.has_duplicate:
                    lines.append(self.env._(
                        "%(receipt)s: the same screenshot or reference was sent for another "
                        "payment (%(others)s).",
                        receipt=receipt.transfer_reference or receipt.display_name,
                        others=", ".join(receipt.duplicate_receipt_ids.mapped("display_name")),
                    ))
                if receipt.amount_mismatch:
                    lines.append(self.env._(
                        "%(receipt)s: the amount sent differs from the amount to pay.",
                        receipt=receipt.transfer_reference or receipt.display_name,
                    ))
                if receipt.time_warning == "before_order":
                    lines.append(self.env._(
                        "%(receipt)s: the transfer is dated before the order.",
                        receipt=receipt.transfer_reference or receipt.display_name,
                    ))
                elif receipt.time_warning == "future":
                    lines.append(self.env._(
                        "%(receipt)s: the transfer is dated in the future.",
                        receipt=receipt.transfer_reference or receipt.display_name,
                    ))
                if receipt.source == "staff":
                    lines.append(self.env._(
                        "%(receipt)s: added by a staff member, not by the customer.",
                        receipt=receipt.transfer_reference or receipt.display_name,
                    ))
            wizard.warning_text = "\n".join(lines) or False

    @api.depends("transaction_id")
    def _compute_paid_elsewhere(self):
        for wizard in self:
            wizard.paid_elsewhere = (
                wizard.transaction_id
                and wizard.transaction_id._instapay_cf_get_paid_elsewhere_warning()
            ) or False

    @api.depends("reject_reason", "transaction_id")
    def _compute_customer_message(self):
        for wizard in self:
            lang = wizard.transaction_id.partner_lang or self.env.lang or "en_US"
            message = const.REJECT_MESSAGES.get(wizard.reject_reason or "other")
            wizard.customer_message = message._translate(lang) if message else False

    # === ACTION METHODS === #

    def action_apply(self):
        """Apply the decision: confirm the payment, reject the receipts or cancel the payment."""
        self.ensure_one()
        tx = self.transaction_id
        payment_utils.check_rights_on_recordset(tx)
        self.receipt_ids.check_access("write")
        if not tx.sudo().try_lock_for_update(allow_referencing=True):
            raise UserError(self.env._(
                "Someone else is handling this payment right now. Try again in a moment.",
            ))
        if tx._instapay_cf_has_pending_event():
            raise UserError(self.env._(
                "A decision on this payment is being applied. Reload the page in a few seconds.",
            ))
        if self.receipt_ids.filtered(lambda r: r.state != "submitted"):
            raise UserError(self.env._("Some of these receipts were already reviewed."))
        if self.decision == "confirm":
            return self._apply_confirm(tx)
        if self.decision == "reject":
            return self._apply_reject(tx)
        return self._apply_cancel(tx)

    def _apply_confirm(self, tx):
        if tx.state not in ("pending", "cancel"):
            raise UserError(self.env._("Only waiting or cancelled payments can be confirmed."))
        receipts = self.receipt_ids
        if not receipts:
            raise UserError(self.env._("Select the receipts of the transfer you found."))
        if self.paid_elsewhere:
            raise UserError(self.paid_elsewhere)
        if not self.statement_checked:
            raise UserError(self.env._(
                "Find the transfer in the statement of the receiving account first, then tick the "
                "box. A screenshot or an SMS alone can be faked.",
            ))
        if self.warning_text and not self.warnings_checked:
            raise UserError(self.env._("Check the warnings, then tick the box."))
        if not self.received_account_id:
            raise UserError(self.env._("Choose the account that received the money."))
        if self.currency_id.compare_amounts(self.amount_received, tx.amount) < 0:
            raise UserError(self.env._(
                "%(received)s were received but %(expected)s are due. Reject the receipt with "
                "the reason \"Amount lower than expected\" instead, so the customer sends the rest.",
                received=format_amount(self.env, self.amount_received, self.currency_id),
                expected=format_amount(self.env, tx.amount, self.currency_id),
            ))
        journal = self.received_account_id.journal_id
        if journal and not tx._instapay_cf_get_payment_method_line(journal):
            raise UserError(self.env._(
                "The journal %(journal)s has no incoming payment method: add a manual one in its "
                "Incoming Payments tab.",
                journal=journal.display_name,
            ))
        Receipt = self.env["payment.instapay.receipt"].sudo()
        for receipt in receipts.filtered("transfer_reference"):
            if Receipt.search_count([
                ("id", "not in", receipts.ids),
                ("company_id", "=", receipt.company_id.id),
                ("transfer_reference", "=", receipt.transfer_reference),
                ("state", "=", "accepted"),
            ], limit=1):
                raise UserError(self.env._(
                    "The InstaPay reference %(reference)s was already accepted for another payment.",
                    reference=receipt.transfer_reference,
                ))

        now = fields.Datetime.now()
        remaining = self.amount_received
        for index, receipt in enumerate(receipts):
            share = receipt.amount_sent if index < len(receipts) - 1 else remaining
            remaining -= share
            receipt.sudo().write({
                "state": "accepted",
                "reviewed_by_id": self.env.user.id,
                "reviewed_at": now,
                "amount_received": share,
                "received_account_id": self.received_account_id.id,
            })
        receipts.sudo().activity_feedback(
            ["payment_instapay_cf.mail_activity_type_instapay_review"],
            feedback=self.env._("Payment confirmed."),
        )
        tx.sudo()._record({
            "reference": tx.reference,
            const.EVENT_KEY: const.EVENT_CONFIRM,
            "account_id": self.received_account_id.id,
            "reviewer_id": self.env.user.id,
            "received_date": fields.Date.to_string(self.date_received or fields.Date.today()),
        })
        tx.sudo().with_context(payment_backend_action=True)._log_message_on_linked_documents(
            Markup("%s") % self.env._(
                "%(user)s found the InstaPay transfer of %(amount)s in %(account)s and confirmed "
                "the payment.",
                user=self.env.user.name,
                amount=format_amount(self.env, self.amount_received, self.currency_id),
                account=self.received_account_id._get_label(),
            ),
        )
        return self._notification(self.env._(
            "Payment confirmed. The order and the invoice are updated within a few seconds.",
        ))

    def _apply_reject(self, tx):
        receipts = self.receipt_ids
        if not receipts:
            raise UserError(self.env._("Select the receipts to reject."))
        if not self.reject_reason:
            raise UserError(self.env._("Choose the reason of the rejection."))
        receipts.sudo().write({
            "state": "rejected",
            "reviewed_by_id": self.env.user.id,
            "reviewed_at": fields.Datetime.now(),
            "reject_reason": self.reject_reason,
            "reject_message": self.customer_message,
        })
        receipts.sudo().activity_feedback(
            ["payment_instapay_cf.mail_activity_type_instapay_review"],
            feedback=self.env._("Receipt rejected."),
        )
        reason = dict(self._fields["reject_reason"]._description_selection(self.env))[
            self.reject_reason
        ]
        tx.sudo().with_context(payment_backend_action=True)._log_message_on_linked_documents(
            Markup("%s") % self.env._(
                "%(user)s rejected the InstaPay receipt: %(reason)s.",
                user=self.env.user.name,
                reason=reason,
            ),
        )
        if self.cancel_payment and tx.state == "pending":
            tx.sudo()._record({
                "reference": tx.reference,
                const.EVENT_KEY: const.EVENT_CANCEL,
                "message": self.customer_message,
                "notify": True,  # The cancellation email carries the message.
            })
            return self._notification(self.env._("Receipt rejected and payment cancelled."))
        tx._instapay_cf_send_email("payment_instapay_cf.mail_template_instapay_rejected")
        return self._notification(self.env._(
            "Receipt rejected. The customer was asked to send a new receipt.",
        ))

    def _apply_cancel(self, tx):
        if tx.state != "pending":
            raise UserError(self.env._("Only waiting payments can be cancelled."))
        open_receipts = tx.instapay_cf_receipt_ids.filtered(lambda r: r.state == "submitted")
        if open_receipts:
            open_receipts.sudo().write({
                "state": "rejected",
                "reviewed_by_id": self.env.user.id,
                "reviewed_at": fields.Datetime.now(),
                "reject_reason": self.reject_reason or "other",
                "reject_message": self.customer_message,
            })
            open_receipts.sudo().activity_feedback(
                ["payment_instapay_cf.mail_activity_type_instapay_review"],
                feedback=self.env._("Payment cancelled."),
            )
        tx.sudo()._record({
            "reference": tx.reference,
            const.EVENT_KEY: const.EVENT_CANCEL,
            "message": self.customer_message,
            "notify": True,
        })
        tx.sudo().with_context(payment_backend_action=True)._log_message_on_linked_documents(
            Markup("%s") % self.env._(
                "%(user)s cancelled the InstaPay payment.", user=self.env.user.name,
            ),
        )
        return self._notification(self.env._(
            "The payment is cancelled within a few seconds; the customer gets an email.",
        ))

    def _notification(self, message):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": message,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
