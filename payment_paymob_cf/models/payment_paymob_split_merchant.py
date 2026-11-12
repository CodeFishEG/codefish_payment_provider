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


class PaymentPaymobSplitMerchant(models.Model):
    """A merchant connected to the Paymob account, who receives part of the payments (Split
    Amount).

    Paymob connects the merchants to the account on request. For each item paid, every connected
    merchant that applies to the item receives its share of the item's price; the rest stays with
    the account that takes the payment.
    """

    _name = "payment.paymob.split.merchant"
    _description = "Paymob Connected Merchant"
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
    mid = fields.Char(
        string="Merchant ID (MID)",
        help="The ID of the merchant connected to your Paymob account, as given by Paymob.",
        required=True,
    )
    share = fields.Float(
        string="Share (%)",
        help="The percentage of the price of each item it applies to that Paymob pays to this "
        "merchant. The rest is yours.",
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
        help="The products whose price is shared with this merchant.",
        comodel_name="product.template",
    )
    active = fields.Boolean(default=True)

    _provider_mid_uniq = models.Constraint(
        "UNIQUE(provider_id, mid)",
        "A merchant can only be added once to a provider.",
    )

    @api.constrains("mid")
    def _check_mid(self):
        for merchant in self:
            if not merchant.mid.strip().isdigit():
                raise ValidationError(
                    self.env._(
                        "The merchant ID of %(merchant)s must be a number.",
                        merchant=merchant.name,
                    ),
                )

    @api.constrains("share")
    def _check_share(self):
        for merchant in self:
            if not 0 < merchant.share <= 100:
                raise ValidationError(
                    self.env._(
                        "The share of %(merchant)s must be more than 0%% and at most 100%%.",
                        merchant=merchant.name,
                    ),
                )

    @api.constrains("share", "apply_to", "product_tmpl_ids", "active", "provider_id")
    def _check_total_share(self):
        """Check that no item is shared out for more than its price."""
        for provider in self.provider_id:
            merchants = provider.paymob_cf_split_merchant_ids.filtered("active")
            all_items_share = sum(
                merchants.filtered(lambda m: m.apply_to == "all").mapped("share"),
            )
            if all_items_share > 100:
                raise ValidationError(
                    self.env._(
                        "The merchants that apply to all items share more than 100%% of their "
                        "price (%(share)s%%).",
                        share=round(all_items_share, 2),
                    ),
                )
            product_merchants = merchants.filtered(lambda m: m.apply_to == "products")
            for product in product_merchants.product_tmpl_ids:
                share = all_items_share + sum(
                    product_merchants.filtered(lambda m: product in m.product_tmpl_ids).mapped(
                        "share",
                    ),
                )
                if share > 100:
                    raise ValidationError(
                        self.env._(
                            "The merchants share more than 100%% of the price of %(product)s "
                            "(%(share)s%%).",
                            product=product.display_name,
                            share=round(share, 2),
                        ),
                    )
