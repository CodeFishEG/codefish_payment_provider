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
from odoo import fields, models

from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_kashier_cf import const
from odoo.addons.payment_kashier_cf import utils as kashier_utils
from odoo.addons.payment_kashier_cf.exceptions import KashierError

_logger = get_payment_logger(__name__, const.SENSITIVE_KEYS)


class PaymentToken(models.Model):
    _inherit = "payment.token"

    kashier_cf_customer_reference = fields.Char(
        string="Kashier Customer",
        help="The customer reference Kashier saved the card under.",
        readonly=True,
        copy=False,
    )
    kashier_cf_expiry = fields.Char(string="Kashier Card Expiry", help="MM/YY", readonly=True, copy=False)
    kashier_cf_is_live = fields.Boolean(string="Kashier Live Card", readonly=True, copy=False)

    def _handle_archiving(self):
        """Override of `payment` to delete the card at Kashier when a person deletes it."""
        super()._handle_archiving()
        if not self.env.context.get(const.DELETE_AT_KASHIER):
            return
        for token in self.filtered(lambda t: t.provider_code == const.PROVIDER_CODE and t.kashier_cf_customer_reference):
            token._kashier_cf_delete_at_kashier()

    def action_kashier_cf_delete(self):
        """Delete the saved card in Odoo and at Kashier (back office)."""
        self.with_context(**{const.DELETE_AT_KASHIER: True}).write({"active": False})

    def _kashier_cf_delete_at_kashier(self):
        self.ensure_one()
        provider = self.provider_id.sudo()
        if not provider.kashier_cf_merchant_id or provider.is_live != self.kashier_cf_is_live:
            return
        signature = provider._kashier_cf_hash(kashier_utils.tokenization_hash_string(
            provider.kashier_cf_merchant_id, self.kashier_cf_customer_reference,
        ))
        try:
            provider._kashier_cf_client().delete_token(
                self.provider_ref,
                kashier_hash=signature,
                customer_reference=self.kashier_cf_customer_reference,
                merchant_id=provider.kashier_cf_merchant_id,
            )
        except KashierError as error:
            _logger.warning("Kashier didn't delete saved card %s: %s", self.id, error)
