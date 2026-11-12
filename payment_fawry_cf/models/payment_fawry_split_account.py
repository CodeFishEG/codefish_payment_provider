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
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PaymentFawrySplitAccount(models.Model):
    """A sub-account that receives part of the payments made with Fawry (Payment Split).

    Sub-accounts are created in Fawry's dashboard (My Accounts > Payment Splitting). For each item
    paid, every sub-account that applies to the item receives its share of the item's price; the
    rest goes to the merchant's own Fawry account.
    """

    _name = "payment.fawry.split.account"
    _description = "Fawry Split Sub-Account"
    _order = "provider_id, sequence, id"

    sequence = fields.Integer(default=10)
    provider_id = fields.Many2one(
        string="Provider",
        comodel_name="payment.provider",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(related="provider_id.company_id", store=True)
    name = fields.Char(
        string="Name",
        help="Who receives this share, for example a seller or a partner.",
        required=True,
    )
    code = fields.Char(
        string="Sub-Account Code",
        help="The code of the sub-account in Fawry's dashboard (My Accounts > Payment Splitting).",
        required=True,
    )
    share = fields.Float(
        string="Share (%)",
        help="The percentage of the price of each item it applies to that Fawry pays to this "
        "sub-account. The rest goes to your own Fawry account.",
        digits=(5, 2),
        default=100.0,
        required=True,
    )
    apply_to = fields.Selection(
        string="Applies To",
        selection=[("all", "All items"), ("products", "Selected products")],
        default="all",
        required=True,
    )
    product_tmpl_ids = fields.Many2many(
        string="Products",
        help="The products whose price is shared with this sub-account.",
        comodel_name="product.template",
    )
    active = fields.Boolean(default=True)

    _provider_code_uniq = models.Constraint(
        "UNIQUE(provider_id, code)",
        "A sub-account can only be added once to a provider.",
    )

    @api.constrains("share")
    def _check_share(self):
        for account in self:
            if not 0 < account.share <= 100:
                raise ValidationError(
                    self.env._(
                        "The share of %(account)s must be more than 0%% and at most 100%%.",
                        account=account.name,
                    ),
                )

    @api.constrains("share", "apply_to", "product_tmpl_ids", "active", "provider_id")
    def _check_total_share(self):
        """Check that no item is shared out for more than its price."""
        for provider in self.provider_id:
            accounts = provider.fawry_split_account_ids.filtered("active")
            all_items_share = sum(accounts.filtered(lambda a: a.apply_to == "all").mapped("share"))
            if all_items_share > 100:
                raise ValidationError(
                    self.env._(
                        "The sub-accounts that apply to all items share more than 100%% of their "
                        "price (%(share)s%%).",
                        share=round(all_items_share, 2),
                    ),
                )
            product_accounts = accounts.filtered(lambda a: a.apply_to == "products")
            for product in product_accounts.product_tmpl_ids:
                share = all_items_share + sum(
                    product_accounts.filtered(lambda a: product in a.product_tmpl_ids).mapped(
                        "share",
                    ),
                )
                if share > 100:
                    raise ValidationError(
                        self.env._(
                            "The sub-accounts share more than 100%% of the price of %(product)s "
                            "(%(share)s%%).",
                            product=product.display_name,
                            share=round(share, 2),
                        ),
                    )
