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
from odoo import http
from odoo.http import request

from odoo.addons.payment.controllers.portal import PaymentPortal
from odoo.addons.payment_kashier_cf import const


class KashierPaymentPortal(PaymentPortal):

    @http.route()
    def archive_token(self, token_id):
        """Override of `payment` to also delete the card at Kashier when the customer deletes it."""
        request.update_context(**{const.DELETE_AT_KASHIER: True})
        return super().archive_token(token_id)
