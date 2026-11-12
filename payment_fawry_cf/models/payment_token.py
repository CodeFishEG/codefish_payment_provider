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
from odoo.exceptions import ValidationError

from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_fawry_cf import const

_logger = get_payment_logger(__name__, const.SENSITIVE_KEYS)


class PaymentToken(models.Model):
    _inherit = "payment.token"

    fawry_customer_profile_id = fields.Char(
        string="Fawry Customer Profile",
        help="The customer identifier the card is saved under at Fawry.",
        readonly=True,
    )

    def _handle_archiving(self):
        """Override of `payment` to delete the card at Fawry when the customer removes it.

        The token is archived even if Fawry can't be reached, so that the customer never sees a
        card they removed. Tokens archived because the provider was archived or switched between
        test and live are kept at Fawry: the provider then points to the other environment.

        Note: called in sudo mode by `payment.token.write`.
        """
        super()._handle_archiving()
        if self.env.context.get("fawry_keep_cards"):
            return
        for token in self.filtered(lambda t: t.provider_code == "fawry"):
            try:
                token.provider_id._fawry_delete_card_token(
                    token.fawry_customer_profile_id or str(token.partner_id.id),
                    token.provider_ref,
                )
            except ValidationError:
                _logger.warning("Unable to delete the Fawry card of token %s.", token.id)
