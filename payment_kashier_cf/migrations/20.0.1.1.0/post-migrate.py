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
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Give every Kashier provider the payment methods added in 20.0.1.1.0.

    The methods are `noupdate` data: the update creates them on the provider of the data file only. The
    Kashier providers copied for other companies get copies of them here. Every method gets its Kashier
    integration (Kashier's page). The new methods are activated on providers not published yet; a published
    provider keeps offering exactly what it offered, and the administrator activates the new methods.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    Method = env["payment.method"].with_context(active_test=False)
    main = env.ref("payment_kashier_cf.payment_provider_kashier_cf", raise_if_not_found=False)
    if not main:
        return
    templates = Method.search([("provider_id", "=", main.id), ("primary_payment_method_id", "=", False)])
    providers = env["payment.provider"].with_context(active_test=False).search([("code", "=", "kashier_cf")])
    existing_codes = {provider.id: set(Method.search([("provider_id", "=", provider.id)]).mapped("code")) for provider in providers}
    new_codes = {"apple_pay", "mobile_wallet_eg", "instapay", "installments_eg", "valu", "souhoola", "contact", "aman",
                 "forsa", "octo", "mogo", "tru", "kiosk"}
    for provider in providers:
        for template in templates:
            if template.code not in existing_codes[provider.id]:
                template.copy({"provider_id": provider.id, "active": False})
        methods = Method.search([("provider_id", "=", provider.id), ("primary_payment_method_id", "=", False)])
        methods.filtered(lambda pm: not pm.kashier_cf_integration).write({"kashier_cf_integration": "redirect"})
        if not provider.is_published and not provider.capture_manually:
            methods.filtered(lambda pm: pm.code in new_codes).write({"active": True})
        else:
            # Published: the shop keeps offering what it offered. Manual capture: only cards can be captured
            # later, so activating the other methods would be refused.
            _logger.info(
                "Kashier provider %s is published or captures manually: the new payment methods stay inactive "
                "until activated.",
                provider.id,
            )
