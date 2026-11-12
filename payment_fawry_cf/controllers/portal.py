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
from odoo.addons.payment.controllers import portal as payment_portal


class PaymentPortal(payment_portal.PaymentPortal):

    def _prepare_payment_form_values(self, *args, **kwargs):
        """Override of `payment` to check the customer's Fawry cards before showing them.

        Every payment form goes through this method: the checkout, the payment pages of orders and
        invoices, payment links and "My payment methods". The cards that Fawry no longer has or
        that have expired are left out.
        """
        payment_form_values = super()._prepare_payment_form_values(*args, **kwargs)
        if tokens_sudo := payment_form_values.get("tokens_sudo"):
            payment_form_values["tokens_sudo"] = tokens_sudo._fawry_refresh()
        return payment_form_values
