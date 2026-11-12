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
from odoo import SUPERUSER_ID, api
from odoo.fields import Command


def migrate(cr, version):
    """Limit Apple Pay to the countries where Paymob offers it.

    The payment methods are `noupdate` data: the countries and currencies added to Apple Pay in this
    version are set on the Apple Pay methods of existing Paymob providers, unless the administrator
    already set some.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    countries = env.ref("base.eg") | env.ref("base.sa") | env.ref("base.ae") | env.ref("base.om")
    currencies = env.ref("base.EGP") | env.ref("base.SAR") | env.ref("base.AED") | env.ref("base.OMR")
    methods = env["payment.method"].with_context(active_test=False).search([
        ("code", "=", "apple_pay"),
        ("provider_id.code", "=", "paymob_cf"),
    ])
    for method in methods:
        values = {}
        if not method.supported_country_ids:
            values["supported_country_ids"] = [Command.set(countries.ids)]
        if not method.supported_currency_ids:
            values["supported_currency_ids"] = [Command.set(currencies.ids)]
        if values:
            method.write(values)
