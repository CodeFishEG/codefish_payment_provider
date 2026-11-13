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
import base64
import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

from markupsafe import Markup

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import SQL, BinaryBytes, BinaryValue, format_amount

from odoo.addons.payment_instapay_cf import const
from odoo.addons.payment_instapay_cf import utils as instapay_utils

_logger = logging.getLogger(__name__)

# The values a customer or a staff member declares with a receipt: they never change after.
EVIDENCE_FIELDS = {
    "transaction_id", "source", "image", "image_sha256", "image_filename", "transfer_reference",
    "amount_sent", "transferred_at", "sender_name", "account_id", "account_label", "submitted_at",
}


class PaymentInstapayReceipt(models.Model):
    """The screenshot of an InstaPay transfer, with the details the payer declared, checked by an
    accountant before the payment is confirmed.
    """

    _name = "payment.instapay.receipt"
    _inherit = ["mail.thread.main.attachment", "mail.activity.mixin"]
    _description = "InstaPay Receipt"
    _order = "review_deadline, id"
    _check_company_auto = True

    name = fields.Char(compute="_compute_name", store=True)
    transaction_id = fields.Many2one(
        string="Transaction",
        comodel_name="payment.transaction",
        required=True,
        ondelete="restrict",
        index=True,
        readonly=True,
    )
    tx_reference = fields.Char(
        string="Payment Reference", related="transaction_id.reference", store=True,
    )
    company_id = fields.Many2one(related="transaction_id.company_id", store=True, index=True)
    partner_id = fields.Many2one(
        string="Customer", related="transaction_id.partner_id", store=True, index=True,
    )
    currency_id = fields.Many2one(related="transaction_id.currency_id", store=True)
    provider_id = fields.Many2one(related="transaction_id.provider_id", store=True)
    amount_expected = fields.Monetary(
        string="Amount to Pay", related="transaction_id.amount", store=True,
    )
    order_date = fields.Datetime(
        string="Payment Started On", related="transaction_id.create_date", store=True,
    )
    state = fields.Selection(
        string="Status",
        selection=[
            ("submitted", "To Review"),
            ("accepted", "Accepted"),
            ("rejected", "Rejected"),
        ],
        default="submitted",
        required=True,
        index=True,
        tracking=True,
        readonly=True,
    )
    source = fields.Selection(
        string="Sent By",
        selection=[("customer", "Customer"), ("staff", "Staff")],
        default="staff",
        required=True,
        readonly=True,
    )

    # Evidence and declared values (immutable).
    image = fields.Image(string="Screenshot", attachment=True)
    image_filename = fields.Char()
    image_sha256 = fields.Char(string="Screenshot Fingerprint", index=True, readonly=True)
    transfer_reference = fields.Char(
        string="InstaPay Reference",
        help="The reference number shown on the receipt of the transfer.",
        index=True,
        tracking=True,
    )
    amount_sent = fields.Monetary(string="Amount Sent")
    transferred_at = fields.Datetime(string="Transfer Date")
    sender_name = fields.Char(string="Sender", help="The payer's name or InstaPay address.")
    account_id = fields.Many2one(
        string="Sent To",
        comodel_name="payment.instapay.account",
        ondelete="set null",
        domain="[('provider_id', '=', provider_id)]",
    )
    account_label = fields.Char(string="Sent To (as shown)", readonly=True)
    submitted_at = fields.Datetime(string="Received On", readonly=True)

    # Review.
    review_deadline = fields.Datetime(string="Review Deadline", readonly=True, index=True)
    review_date = fields.Date(
        string="Review By", compute="_compute_review_date", store=True,
    )
    is_overdue = fields.Boolean(
        string="Overdue", compute="_compute_is_overdue", search="_search_is_overdue",
    )
    reviewed_by_id = fields.Many2one(string="Reviewed By", comodel_name="res.users", readonly=True)
    reviewed_at = fields.Datetime(string="Reviewed On", readonly=True)
    amount_received = fields.Monetary(string="Amount Received", readonly=True)
    received_account_id = fields.Many2one(
        string="Received In", comodel_name="payment.instapay.account", readonly=True,
        ondelete="set null",
    )
    reject_reason = fields.Selection(
        string="Rejection Reason", selection=const.REJECT_REASONS, readonly=True,
    )
    reject_message = fields.Text(string="Message to the Customer", readonly=True)

    # Warnings for the reviewer.
    duplicate_receipt_ids = fields.Many2many(
        string="Possible Duplicates",
        comodel_name="payment.instapay.receipt",
        compute="_compute_duplicate_receipt_ids",
    )
    has_duplicate = fields.Boolean(
        string="Possible Duplicate", compute="_compute_duplicate_receipt_ids",
        search="_search_has_duplicate",
    )
    amount_mismatch = fields.Boolean(
        string="Amount Mismatch", compute="_compute_amount_mismatch", store=True,
    )
    time_warning = fields.Selection(
        string="Date Warning",
        selection=[
            ("before_order", "Transfer before the order"),
            ("future", "Transfer date in the future"),
        ],
        compute="_compute_time_warning",
        store=True,
    )

    _accepted_reference_unique = models.UniqueIndex(
        "(company_id, transfer_reference) WHERE state = 'accepted' AND transfer_reference IS NOT NULL",
        "This InstaPay reference was already accepted for another payment.",
    )

    # === COMPUTE METHODS === #

    @api.depends("tx_reference")
    def _compute_name(self):
        for receipt in self:
            receipt.name = receipt.tx_reference or self.env._("InstaPay receipt")

    @api.depends("review_deadline", "company_id.tz")
    def _compute_review_date(self):
        for receipt in self:
            deadline = receipt.review_deadline
            if not deadline:
                receipt.review_date = False
                continue
            tz = ZoneInfo(receipt.company_id.tz or "UTC")
            receipt.review_date = deadline.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz).date()

    @api.depends("state", "review_deadline")
    def _compute_is_overdue(self):
        now = fields.Datetime.now()
        for receipt in self:
            receipt.is_overdue = bool(
                receipt.state == "submitted"
                and receipt.review_deadline
                and receipt.review_deadline < now,
            )

    def _search_is_overdue(self, operator, value):
        if operator != "in":
            return NotImplemented
        overdue = Domain("state", "=", "submitted") & Domain(
            "review_deadline", "<", fields.Datetime.now(),
        )
        if True in value and False in value:
            return Domain.TRUE
        return overdue if True in value else ~overdue

    @api.depends("image_sha256", "transfer_reference", "company_id")
    def _compute_duplicate_receipt_ids(self):
        Receipt = self.env["payment.instapay.receipt"].sudo()
        for receipt in self:
            conditions = []
            if receipt.image_sha256:
                conditions.append(Domain("image_sha256", "=", receipt.image_sha256))
            if receipt.transfer_reference:
                conditions.append(Domain("transfer_reference", "=", receipt.transfer_reference))
            # In forms (e.g. the review wizard) receipts are new records: compare with the saved one.
            record_id = receipt._origin.id
            duplicates = Receipt
            if conditions and record_id:
                duplicates = Receipt.search(
                    Domain("id", "!=", record_id)
                    & Domain("company_id", "=", receipt.company_id.id)
                    & Domain.OR(conditions),
                )
            receipt.duplicate_receipt_ids = self.browse(duplicates.ids)
            receipt.has_duplicate = bool(duplicates)

    def _search_has_duplicate(self, operator, value):
        if operator != "in":
            return NotImplemented
        duplicate_ids = [row[0] for row in self.env.execute_query(SQL(
            """
            SELECT receipt.id
              FROM payment_instapay_receipt receipt
             WHERE EXISTS (
                   SELECT 1
                     FROM payment_instapay_receipt other
                    WHERE other.id != receipt.id
                      AND other.company_id = receipt.company_id
                      AND (other.image_sha256 = receipt.image_sha256
                           OR other.transfer_reference = receipt.transfer_reference)
             )
            """,
        ))]
        if True in value and False in value:
            return Domain.TRUE
        domain = Domain("id", "in", duplicate_ids)
        return domain if True in value else ~domain

    @api.depends("amount_sent", "amount_expected", "currency_id")
    def _compute_amount_mismatch(self):
        for receipt in self:
            receipt.amount_mismatch = bool(
                receipt.amount_sent
                and receipt.currency_id
                and receipt.currency_id.compare_amounts(
                    receipt.amount_sent, receipt.amount_expected,
                ),
            )

    @api.depends("transferred_at", "submitted_at", "order_date")
    def _compute_time_warning(self):
        for receipt in self:
            warning = False
            if receipt.transferred_at:
                before_order_limit = receipt.order_date and receipt.order_date - timedelta(
                    minutes=const.TIME_BEFORE_ORDER_TOLERANCE_MINUTES,
                )
                future_limit = (receipt.submitted_at or fields.Datetime.now()) + timedelta(
                    minutes=const.TIME_IN_FUTURE_TOLERANCE_MINUTES,
                )
                if before_order_limit and receipt.transferred_at < before_order_limit:
                    warning = "before_order"
                elif receipt.transferred_at > future_limit:
                    warning = "future"
            receipt.time_warning = warning

    # === CRUD METHODS === #

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._instapay_cf_prepare_values(vals)
        receipts = super(PaymentInstapayReceipt, self.with_context(
            mail_create_nosubscribe=True, mail_create_nolog=True,
        )).create(vals_list)
        for receipt in receipts:
            receipt._instapay_cf_after_create()
        return receipts

    def write(self, vals):
        if EVIDENCE_FIELDS & set(vals) and not self.env.context.get("instapay_cf_allow_evidence"):
            raise UserError(self.env._(
                "The screenshot and the details declared with it can't be changed. Reject the "
                "receipt and add a new one instead.",
            ))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_accepted(self):
        if self.filtered(lambda r: r.state == "accepted"):
            raise UserError(self.env._(
                "Accepted receipts are the proof of a confirmed payment and can't be deleted.",
            ))

    def _instapay_cf_prepare_values(self, vals):
        """Clean the screenshot and complete the values of a new receipt, in place.

        :param dict vals: The create values; `transaction_id` and `image` are required.
        :raise ValidationError: If the screenshot isn't a PNG or JPEG image.
        """
        tx = self.env["payment.transaction"].sudo().browse(vals.get("transaction_id"))
        if not tx.exists() or tx.provider_code != const.PROVIDER_CODE:
            raise ValidationError(self.env._("Receipts belong to InstaPay payments."))
        image = vals.get("image")
        if not image:
            raise ValidationError(self.env._("Add the screenshot of the transfer."))
        if not self.env.context.get("instapay_cf_image_clean"):
            if isinstance(image, BinaryValue):
                raw = image.content
            elif isinstance(image, str):
                raw = base64.b64decode(image)
            else:
                raw = bytes(image)
            try:
                clean, extension, sha256 = instapay_utils.sanitize_receipt(raw)
            except instapay_utils.ReceiptError:
                raise ValidationError(self.env._(
                    "The screenshot must be a PNG or JPEG image of at most 10 MB.",
                )) from None
            vals["image"] = BinaryBytes(clean)
            vals.setdefault("image_sha256", sha256)
            vals.setdefault("image_filename", f"{tx.reference}-receipt.{extension}")
        if vals.get("transfer_reference"):
            reference = instapay_utils.normalize_reference(vals["transfer_reference"])
            if not reference:
                raise ValidationError(self.env._(
                    "The InstaPay reference has 6 to 32 letters and digits (12 digits on most "
                    "receipts).",
                ))
            vals["transfer_reference"] = reference
        if vals.get("sender_name"):
            vals["sender_name"] = instapay_utils.clean_text(
                vals["sender_name"], const.MAX_SENDER_NAME_LENGTH,
            )
        if vals.get("account_id") and not vals.get("account_label"):
            account = self.env["payment.instapay.account"].sudo().browse(vals["account_id"])
            vals["account_label"] = account._get_label()
        submitted_at = vals.get("submitted_at") or fields.Datetime.now()
        vals["submitted_at"] = submitted_at
        vals["review_deadline"] = tx.provider_id._instapay_cf_compute_review_deadline(
            fields.Datetime.to_datetime(submitted_at),
        )

    def _instapay_cf_after_create(self):
        """Post the screenshot in the chatter, ask the reviewer to check it, note it on the order
        and the invoice, and tell the customer it was received.
        """
        self.ensure_one()
        receipt = self.sudo()
        tx = receipt.transaction_id
        is_customer = receipt.source == "customer"
        author = tx.partner_id if is_customer else self.env.user.partner_id
        receipt.with_user(SUPERUSER_ID).message_post(
            body=receipt._get_summary_html(),
            attachments=[(
                receipt.image_filename or f"{tx.reference}-receipt.png", receipt.image.content,
            )],
            author_id=author.id,
            message_type="comment",
            subtype_xmlid="mail.mt_note",
        )
        reviewer_values = tx.provider_id._instapay_cf_get_review_user_values()
        if reviewer_values:
            receipt.with_user(SUPERUSER_ID).activity_schedule(
                "payment_instapay_cf.mail_activity_type_instapay_review",
                date_deadline=receipt.review_date,
                summary=self.env._(
                    "Check the InstaPay transfer of %(reference)s",
                    reference=tx.reference,
                ),
                **reviewer_values,
            )
        else:
            _logger.warning(
                "No reviewer is set on the InstaPay provider %s: the receipt of %s waits in the "
                "InstaPay Receipts menu.",
                tx.provider_id.id,
                tx.reference,
            )
        message = (
            self.env._("The customer sent the receipt of their InstaPay transfer.")
            if is_customer
            else self.env._("A receipt of the InstaPay transfer was added.")
        )
        tx.with_context(payment_backend_action=not is_customer)._log_message_on_linked_documents(
            Markup("%s %s") % (message, receipt._get_reference_line()),
        )
        if is_customer and tx.provider_id.instapay_cf_send_emails:
            tx._instapay_cf_send_email("payment_instapay_cf.mail_template_instapay_receipt_received")

    # === ACTION METHODS === #

    def action_open_confirm(self):
        """Open the wizard confirming the payment of the receipt."""
        return self._open_review_wizard("confirm")

    def action_open_reject(self):
        """Open the wizard rejecting the receipt."""
        return self._open_review_wizard("reject")

    def _open_review_wizard(self, decision):
        self.ensure_one()
        if self.state != "submitted":
            raise UserError(self.env._("This receipt was already reviewed."))
        return {
            "name": self.env._("Confirm the InstaPay payment")
            if decision == "confirm" else self.env._("Reject the receipt"),
            "type": "ir.actions.act_window",
            "res_model": "payment.instapay.review.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_transaction_id": self.transaction_id.id,
                "default_decision": decision,
                "default_receipt_ids": [(6, 0, self.ids)],
            },
        }

    # === BUSINESS METHODS === #

    def _get_reference_line(self):
        """Return the receipt's reference and amount, for notes."""
        self.ensure_one()
        parts = []
        if self.transfer_reference:
            parts.append(self.env._("Reference %(reference)s", reference=self.transfer_reference))
        if self.amount_sent:
            parts.append(format_amount(self.env, self.amount_sent, self.currency_id))
        return " · ".join(parts)

    def _get_summary_html(self):
        """Return what the payer declared, as an HTML note for the chatter."""
        self.ensure_one()
        rows = [
            (self.env._("InstaPay reference"), self.transfer_reference),
            (
                self.env._("Amount sent"),
                self.amount_sent and format_amount(self.env, self.amount_sent, self.currency_id),
            ),
            (
                self.env._("Transfer date"),
                self.transferred_at and fields.Datetime.to_string(self.transferred_at),
            ),
            (self.env._("Sender"), self.sender_name),
            (self.env._("Sent to"), self.account_label),
        ]
        items = Markup("").join(
            Markup("<li>%s: %s</li>") % (label, value) for label, value in rows if value
        )
        return Markup("<p>%s</p><ul>%s</ul>") % (
            self.env._("Receipt of the InstaPay transfer."), items,
        )
