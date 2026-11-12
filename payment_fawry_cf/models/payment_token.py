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
from datetime import timedelta

from odoo import fields, models
from odoo.exceptions import ValidationError

from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_fawry_cf import const
from odoo.addons.payment_fawry_cf import utils as fawry_utils

_logger = get_payment_logger(__name__, const.SENSITIVE_KEYS)


class PaymentToken(models.Model):
    _inherit = "payment.token"

    fawry_customer_profile_id = fields.Char(
        string="Fawry Customer Profile",
        help="The customer identifier the card is saved under at Fawry.",
        readonly=True,
    )
    fawry_card_expiry = fields.Char(
        string="Card Expiry",
        help="The month and year the card expires (MM/YY), as saved at Fawry.",
        readonly=True,
    )
    fawry_card_bin = fields.Char(
        string="Card First Digits",
        help="The first six digits of the card, which tell its bank and the installment plans it "
        "can pay with.",
        readonly=True,
    )
    fawry_last_check = fields.Datetime(
        string="Last Checked at Fawry",
        help="When Odoo last found the card among the cards the customer saved at Fawry.",
        readonly=True,
    )

    # === CRUD METHODS === #

    def _handle_archiving(self):
        """Override of `payment` to delete the card at Fawry when the customer removes it.

        The token is archived even if Fawry can't be reached, so that the customer never sees a
        card they removed. Tokens archived because the provider was archived or switched between
        test and live are kept at Fawry: the provider then points to the other environment.

        Note: called in sudo mode by `payment.token.write`.
        """
        super()._handle_archiving()
        if self.env.context.get("fawry_keep_cards"):
            return
        for token in self.filtered(lambda t: t.provider_code == "fawry"):
            try:
                token.provider_id._fawry_delete_card_token(
                    token._fawry_get_customer_profile_id(), token.provider_ref,
                )
            except ValidationError:
                _logger.warning("Unable to delete the Fawry card of token %s.", token.id)

    # === BUSINESS METHODS === #

    def _fawry_get_customer_profile_id(self):
        """Return the customer profile id the card is saved under at Fawry.

        Note: `self.ensure_one()`

        :rtype: str
        """
        self.ensure_one()
        return self.fawry_customer_profile_id or str(self.partner_id.id)

    def _fawry_refresh(self):
        """Check the Fawry cards against the cards the customer saved at Fawry.

        Fawry's list of the customer's cards is fetched, at most once every few minutes per card.
        The cards that Fawry no longer has, and the cards that have expired, are archived, without
        asking Fawry to delete them. The others get the expiry date known by Fawry. Nothing changes
        when Fawry can't be reached, so that a network issue never hides a valid card.

        Cards that Fawry has but Odoo doesn't know are never added: the customer may have entered
        them for a single payment.

        Note: called in sudo mode, when the tokens are shown to the customer.

        :return: The tokens that are still active, other providers' tokens included.
        :rtype: payment.token
        """
        fawry_tokens = self.filtered(lambda t: t.active and t.provider_code == "fawry")
        if not fawry_tokens or self.env.cr.readonly:
            return self

        now = fields.Datetime.now()
        check_limit = now - timedelta(minutes=const.CARD_CHECK_INTERVAL_MINUTES)
        tokens_to_check = fawry_tokens.filtered(
            lambda t: not t.fawry_last_check or t.fawry_last_check < check_limit,
        )
        tokens_to_archive = self.browse()
        for (provider, profile_id), tokens in tokens_to_check.grouped(
            lambda t: (t.provider_id, t._fawry_get_customer_profile_id()),
        ).items():
            if not provider.fawry_merchant_code or not provider.fawry_secure_key:
                continue
            try:
                cards = provider._fawry_list_card_tokens(profile_id)
            except ValidationError:
                _logger.warning(
                    "Unable to check the Fawry cards of customer profile %s.", profile_id,
                )
                continue
            cards_by_token = {card["token"]: card for card in cards if card.get("token")}
            for token in tokens:
                card = cards_by_token.get(token.provider_ref)
                if not card:
                    _logger.info("Fawry no longer has the card of token %s.", token.id)
                    tokens_to_archive |= token
                    continue
                values = {"fawry_last_check": now}
                if card.get("expiryDate") and card["expiryDate"] != token.fawry_card_expiry:
                    values["fawry_card_expiry"] = card["expiryDate"]
                if card.get("firstSixDigits") and card["firstSixDigits"] != token.fawry_card_bin:
                    values["fawry_card_bin"] = str(card["firstSixDigits"])
                token.write(values)

        today = fields.Date.context_today(self)
        tokens_to_archive |= fawry_tokens.filtered(
            lambda t: fawry_utils.is_card_expired(t.fawry_card_expiry, today),
        )
        if tokens_to_archive:
            _logger.info("Archiving the Fawry tokens %s.", tokens_to_archive.ids)
            tokens_to_archive.with_context(fawry_keep_cards=True).active = False
        return self.filtered("active")
