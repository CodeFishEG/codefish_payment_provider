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
from . import controllers, models, wizard
from odoo.addons.payment import reset_payment_provider, setup_provider


def post_init_hook(env):
    setup_provider(env, "instapay_cf")
    Provider = env["payment.provider"]
    Provider._instapay_cf_setup_journals()
    Provider._instapay_cf_setup_reviewer_role()


def uninstall_hook(env):
    reset_payment_provider(env, "instapay_cf")
