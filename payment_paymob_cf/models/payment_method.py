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

from odoo.addons.payment_paymob_cf import const


class PaymentMethod(models.Model):
    _inherit = "payment.method"

    paymob_cf_integration_id = fields.Integer(
        string="Paymob Integration ID",
        help="The ID of the Paymob integration that processes this method, in the mode of the "
        "provider (test or live). Paymob dashboard: Settings > Payment Integrations. Sync "
        "Integrations on the provider fills it.",
    )
    paymob_cf_provider_code = fields.Selection(related="provider_id.code", string="Provider Code")

    def _paymob_cf_get_integration_id(self, capture_manually=False):
        """Return the Paymob integration of the method.

        Card payments that are only authorized use the provider's Auth integration.

        :param bool capture_manually: Whether card payments are only authorized.
        :rtype: int
        """
        self.ensure_one()
        method = self.primary_payment_method_id or self
        if capture_manually and method.code in const.CARD_METHOD_CODES:
            return method.provider_id.paymob_cf_auth_integration_id
        return method.paymob_cf_integration_id
