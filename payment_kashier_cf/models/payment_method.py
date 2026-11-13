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
from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.payment_kashier_cf import const


class PaymentMethod(models.Model):
    _inherit = "payment.method"

    kashier_cf_integration = fields.Selection(
        string="Kashier Integration",
        selection=[
            (const.INTEGRATION_REDIRECT, "Kashier page"),
            (const.INTEGRATION_EMBEDDED, "Kashier page inside the checkout"),
            (const.INTEGRATION_SERVER, "Server side (no Kashier page)"),
            (const.INTEGRATION_APPLE_PAY_BUTTON, "Apple Pay button on the payment step (beta)"),
        ],
        help="How customers pay with this method:\n"
        "- Kashier page: they go to Kashier's secure page and come back.\n"
        "- Kashier page inside the checkout: the same page, shown in the checkout without leaving the shop.\n"
        "- Server side: Odoo asks Kashier for the payment and shows the next step itself (wallet request, "
        "Basata code, InstaPay QR). Not for cards: card details always stay on Kashier's page.\n"
        "- Apple Pay button: Kashier's Apple Pay button on the payment step (needs the shop's domain "
        "registered with Kashier).",
    )
    kashier_cf_provider_code = fields.Selection(related="provider_id.code", string="Kashier Provider Code")

    @api.constrains("kashier_cf_integration", "code", "provider_id")
    def _check_kashier_cf_integration(self):
        for method in self.filtered(lambda pm: pm.provider_id.code == const.PROVIDER_CODE and pm.is_primary):
            allowed = method._kashier_cf_allowed_integrations()
            if method.kashier_cf_integration and method.kashier_cf_integration not in allowed:
                labels = dict(self._fields["kashier_cf_integration"]._description_selection(self.env))
                raise ValidationError(self.env._(
                    "%(method)s can't use the integration \"%(integration)s\" with Kashier. Possible: %(allowed)s.",
                    method=method.name,
                    integration=labels.get(method.kashier_cf_integration),
                    allowed=", ".join(labels[value] for value in allowed),
                ))

    # === BUSINESS METHODS === #

    def _kashier_cf_primary(self):
        """The method that carries the settings: the method itself, or the card of a card brand."""
        self.ensure_one()
        return self.primary_payment_method_id or self

    def _kashier_cf_spec(self):
        """How Kashier knows the method (see `const.METHODS`); an unknown code is offered like the catch-all."""
        self.ensure_one()
        return const.METHODS.get(self._kashier_cf_primary().code, const.METHODS[const.PROVIDER_WIDE_METHOD_CODE])

    def _kashier_cf_allowed_integrations(self):
        self.ensure_one()
        return self._kashier_cf_spec()["integrations"]

    def _kashier_cf_get_integration(self):
        """The integration the method uses: its setting when allowed, otherwise its default (Kashier's page)."""
        self.ensure_one()
        allowed = self._kashier_cf_allowed_integrations()
        integration = self._kashier_cf_primary().kashier_cf_integration
        if integration not in allowed:
            return allowed[0]
        if integration == const.INTEGRATION_APPLE_PAY_BUTTON and not self.provider_id.sudo().kashier_cf_apple_pay_domain_file:
            return allowed[0]  # Apple Pay opens on Kashier's page until the shop's domain is registered.
        return integration
