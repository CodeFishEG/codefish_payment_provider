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
from odoo import models

from odoo.addons.payment_instapay_cf import const


class AccountMove(models.Model):
    _inherit = "account.move"

    def _instapay_cf_get_open_transaction(self):
        """Return the InstaPay payment of the invoice that waits for the transfer or its review.

        The invoice portal page shows its details, as Odoo hides the Pay button meanwhile.
        """
        self.ensure_one()
        return self.sudo().transaction_ids.filtered(
            lambda tx: tx.provider_code == const.PROVIDER_CODE and tx.state == "pending",
        ).sorted("id", reverse=True)[:1]
