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

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import BinaryBytes, BinaryValue
from odoo.tools.image import image_data_uri

from odoo.addons.payment_instapay_cf import const
from odoo.addons.payment_instapay_cf import utils as instapay_utils

_logger = logging.getLogger(__name__)


class PaymentInstapayAccount(models.Model):
    """A place where customers send InstaPay money: the company's InstaPay account (mobile
    number, payment link, QR), a mobile wallet or a bank account.
    """

    _name = "payment.instapay.account"
    _description = "InstaPay Receiving Account"
    _order = "sequence, id"
    _check_company_auto = True

    provider_id = fields.Many2one(
        comodel_name="payment.provider", required=True, ondelete="cascade", index=True,
    )
    company_id = fields.Many2one(related="provider_id.company_id", store=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    kind = fields.Selection(
        string="Type",
        selection=[
            ("instapay", "InstaPay"),
            ("wallet", "Mobile Wallet"),
            ("bank", "Bank Account"),
        ],
        required=True,
        default="instapay",
    )
    name = fields.Char(
        string="Name",
        help="The title customers see, e.g. \"InstaPay\", \"Vodafone Cash\" or the bank's name.",
        compute="_compute_name",
        store=True,
        readonly=False,
        translate=True,
    )
    holder_name = fields.Char(
        string="Beneficiary Name",
        help="The account holder's name, as InstaPay shows it to customers before they confirm.",
        required=True,
    )
    note = fields.Char(
        string="Note for Customers",
        help="An extra line shown to customers under this account.",
        translate=True,
    )
    journal_id = fields.Many2one(
        string="Journal",
        help="The journal of the real bank account or wallet the money lands in, to post the "
        "payments there. The InstaPay journal when empty.",
        comodel_name="account.journal",
        domain=[("type", "in", ("bank", "cash"))],
        check_company=True,
    )

    # InstaPay account
    ipa = fields.Char(
        string="InstaPay Address",
        help="Your InstaPay Payment Address, e.g. yourshop@instapay. Customers can't type it in "
        "the app any more: add the payment link or the QR too.",
    )
    mobile = fields.Char(
        string="Mobile Number",
        help="The mobile number registered on your InstaPay account.",
    )
    payment_link = fields.Char(
        string="Payment Link",
        help="The link generated in the InstaPay app (Share link), e.g. "
        "https://ipn.eg/S/yourshop/instapay/AbC123. On a phone, it opens the InstaPay app.",
    )
    qr_image = fields.Image(
        string="QR Code",
        help="The QR code exported from the InstaPay app. Without it, a QR code is made from the "
        "payment link.",
        max_width=const.QR_MAX_SIDE,
        max_height=const.QR_MAX_SIDE,
        attachment=True,
    )

    # Mobile wallet
    wallet_operator = fields.Selection(string="Wallet", selection=const.WALLET_OPERATORS)
    wallet_number = fields.Char(string="Wallet Number")

    # Bank account
    bank_name = fields.Char(string="Bank")
    account_number = fields.Char(string="Account Number")
    iban = fields.Char(string="IBAN")

    warning = fields.Char(compute="_compute_warning")

    # === COMPUTE METHODS === #

    @api.depends("kind", "wallet_operator", "bank_name")
    def _compute_name(self):
        operators = dict(self._fields["wallet_operator"]._description_selection(self.env))
        for account in self:
            if account.kind == "wallet" and account.wallet_operator:
                account.name = operators[account.wallet_operator]
            elif account.kind == "bank" and account.bank_name:
                account.name = account.bank_name
            elif account.kind == "instapay" or not account.name:
                account.name = "InstaPay"

    @api.depends("kind", "payment_link", "qr_image", "mobile", "journal_id")
    def _compute_warning(self):
        for account in self:
            warnings = []
            if account.kind == "instapay" and not (account.payment_link or account.qr_image):
                warnings.append(self.env._(
                    "Add the payment link and the QR code exported from the InstaPay app: recent "
                    "versions of the app don't let customers type an InstaPay address.",
                ))
            if not account.journal_id:
                warnings.append(self.env._(
                    "Payments are posted in the InstaPay journal: choose the journal of the real "
                    "account to reconcile them with its bank statements.",
                ))
            account.warning = " ".join(warnings) or False

    # === CONSTRAINT METHODS === #

    @api.constrains(
        "kind", "ipa", "mobile", "payment_link", "qr_image", "wallet_operator", "wallet_number",
        "bank_name", "account_number", "iban",
    )
    def _check_details(self):
        for account in self:
            if account.ipa and not instapay_utils.normalize_ipa(account.ipa):
                raise ValidationError(self.env._(
                    "%(ipa)s isn't an InstaPay address. It looks like yourshop@instapay.",
                    ipa=account.ipa,
                ))
            for number in (account.mobile, account.wallet_number):
                if number and not instapay_utils.normalize_mobile(number):
                    raise ValidationError(self.env._(
                        "%(number)s isn't an Egyptian mobile number (11 digits starting with 010, "
                        "011, 012 or 015).",
                        number=number,
                    ))
            if account.payment_link and not instapay_utils.is_instapay_link(account.payment_link):
                raise ValidationError(self.env._(
                    "The payment link must be an InstaPay link, starting with https://ipn.eg/S/. "
                    "Copy it from the InstaPay app (Share link).",
                ))
            if account.iban and not instapay_utils.is_valid_eg_iban(account.iban):
                raise ValidationError(self.env._(
                    "%(iban)s isn't a valid Egyptian IBAN (EG followed by 27 digits). Check it on "
                    "a bank document.",
                    iban=account.iban,
                ))
            if account.kind == "instapay" and not (
                account.ipa or account.mobile or account.payment_link or account.qr_image
            ):
                raise ValidationError(self.env._(
                    "Add the mobile number, the payment link or the QR code of your InstaPay "
                    "account.",
                ))
            if account.kind == "wallet" and not (account.wallet_operator and account.wallet_number):
                raise ValidationError(self.env._("Choose the wallet and enter its number."))
            if account.kind == "bank" and not (
                account.bank_name and (account.account_number or account.iban)
            ):
                raise ValidationError(self.env._(
                    "Enter the bank's name and the account number or the IBAN.",
                ))

    @api.constrains("journal_id")
    def _check_journal_currency(self):
        for account in self.filtered("journal_id"):
            currency = account.journal_id.currency_id or account.journal_id.company_id.currency_id
            if currency.name != const.CURRENCY:
                raise ValidationError(self.env._(
                    "InstaPay transfers are in EGP: choose a journal in EGP.",
                ))

    @api.constrains("active", "provider_id")
    def _check_published_provider_keeps_an_account(self):
        self.provider_id._check_instapay_cf_published_accounts()

    # === CRUD METHODS === #

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._normalize_values(vals) for vals in vals_list])

    def write(self, vals):
        return super().write(self._normalize_values(vals))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_last_account_of_published_provider(self):
        for provider in self.provider_id.filtered("is_published"):
            if not (provider._instapay_cf_get_accounts() - self):
                raise ValidationError(self.env._(
                    "A published InstaPay provider needs a receiving account: unpublish it first.",
                ))

    def _normalize_values(self, vals):
        """Return the values with the details normalized and the QR image cleaned."""
        vals = dict(vals)
        if vals.get("ipa"):
            vals["ipa"] = instapay_utils.normalize_ipa(vals["ipa"]) or vals["ipa"]
        for field_name in ("mobile", "wallet_number"):
            if vals.get(field_name):
                vals[field_name] = (
                    instapay_utils.normalize_mobile(vals[field_name]) or vals[field_name]
                )
        if vals.get("iban"):
            vals["iban"] = instapay_utils.normalize_iban(vals["iban"])
        if vals.get("account_number"):
            vals["account_number"] = instapay_utils.to_ascii_digits(vals["account_number"]).strip()
        if vals.get("payment_link"):
            vals["payment_link"] = vals["payment_link"].strip()
        if vals.get("qr_image"):
            vals["qr_image"] = self._clean_qr_image(vals["qr_image"])
        return vals

    def _clean_qr_image(self, value):
        """Return the QR image decoded and encoded again, or raise if it isn't an image."""
        if isinstance(value, BinaryValue):
            raw = value.content
        elif isinstance(value, str):
            raw = base64.b64decode(value)
        else:
            raw = bytes(value)
        try:
            clean, _extension = instapay_utils.sanitize_image(raw, const.QR_MAX_SIDE)
        except instapay_utils.ReceiptError:
            raise ValidationError(self.env._(
                "The QR code must be a PNG or JPEG image, as exported from the InstaPay app.",
            )) from None
        return BinaryBytes(clean)

    # === BUSINESS METHODS === #

    def _get_label(self):
        """Return a one-line description of the account, e.g. "Vodafone Cash 010 1234 5678"."""
        self.ensure_one()
        if self.kind == "wallet":
            detail = instapay_utils.format_mobile(self.wallet_number or "")
        elif self.kind == "bank":
            detail = (
                instapay_utils.format_iban(self.iban) if self.iban else self.account_number or ""
            )
        else:
            detail = (
                self.ipa
                or (self.mobile and instapay_utils.format_mobile(self.mobile))
                or ""
            )
        return " ".join(part for part in (self.name, detail) if part)

    def _get_qr_data_uri(self):
        """Return the QR code as a data URI: the uploaded image, else one made from the link."""
        self.ensure_one()
        if self.qr_image:
            return image_data_uri(self.qr_image.content)
        if self.payment_link and instapay_utils.is_instapay_link(self.payment_link):
            try:
                png = self.env["ir.actions.report"].sudo().barcode(
                    "QR", self.payment_link, width=240, height=240, barLevel="M",
                )
            except ValueError:
                _logger.warning("Unable to make the QR code of the account %s.", self.id)
                return False
            return image_data_uri(png)
        return False

    def _get_customer_values(self):
        """Return what customers see of the account: its title, details to copy, link and QR.

        :return: The values of `payment_instapay_cf.account_card`.
        :rtype: dict
        """
        self.ensure_one()
        rows = []

        def add_row(label, display, copy=None):
            if display:
                rows.append({"label": label, "display": display, "copy": copy or display})

        if self.kind == "instapay":
            add_row(self.env._("Mobile number"), instapay_utils.format_mobile(self.mobile or ""),
                    self.mobile)
            add_row(self.env._("InstaPay address"), self.ipa)
        elif self.kind == "wallet":
            add_row(self.env._("Wallet number"),
                    instapay_utils.format_mobile(self.wallet_number or ""), self.wallet_number)
        else:
            add_row(self.env._("Bank"), self.bank_name, self.bank_name)
            add_row(self.env._("Account number"), self.account_number)
            add_row(self.env._("IBAN"), instapay_utils.format_iban(self.iban or ""), self.iban)
        add_row(self.env._("Beneficiary"), self.holder_name)
        link = self.payment_link if instapay_utils.is_instapay_link(self.payment_link) else False
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.name or "InstaPay",
            "label": self._get_label(),
            "rows": rows,
            "link": link,
            "qr_data_uri": self._get_qr_data_uri() if self.kind == "instapay" else False,
            "note": self.note,
        }
