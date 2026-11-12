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


class AccountChartTemplate(models.AbstractModel):
    _inherit = "account.chart.template"

    def _post_load_data(self, template_code, company, template_data):
        """Override of `account` to create the "Fawry Pay" journal of a company whose chart of
        accounts is installed after this module (e.g. a new company).
        """
        super()._post_load_data(template_code, company, template_data)
        self.env["payment.provider"]._fawry_setup_journals(company or self.env.company)
