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
from odoo.addons.payment_paymob_cf import const
from odoo.addons.payment_paymob_cf import utils as paymob_utils

_logger = get_payment_logger(__name__, const.SENSITIVE_KEYS)


class PaymentToken(models.Model):
    _inherit = "payment.token"

    paymob_cf_card_expiry = fields.Char(
        string="Card Expiry",
        help="The month and year the card expires (MM/YY), as Paymob saved it.",
        readonly=True,
    )
    paymob_cf_cardholder = fields.Char(
        string="Cardholder",
        help="The name on the card, as Paymob saved it.",
        readonly=True,
    )

    def _paymob_cf_archive_expired(self):
        """Archive the Paymob cards that have expired, so that customers never pick them.

        Paymob has no API to list or delete saved cards: a removed card is only archived in Odoo,
        and Paymob keeps the token, which nothing can use any more.

        Note: called in sudo mode, when the tokens are shown to the customer.

        :return: The tokens that are still active, other providers' tokens included.
        :rtype: payment.token
        """
        today = fields.Date.context_today(self)
        expired_tokens = self.filtered(
            lambda t: t.active
            and t.provider_code == "paymob_cf"
            and paymob_utils.is_card_expired(t.paymob_cf_card_expiry, today),
        )
        if expired_tokens and not self.env.cr.readonly:
            _logger.info("Archiving the expired Paymob cards %s.", expired_tokens.ids)
            expired_tokens.active = False
        return self.filtered("active") - expired_tokens
