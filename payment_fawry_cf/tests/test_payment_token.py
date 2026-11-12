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
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment.tests.http_common import PaymentHttpCommon
from odoo.addons.payment_fawry_cf.tests.common import FawryCommon

TOKEN_LOGGER = "odoo.addons.payment_fawry_cf.models.payment_token"


@tagged("post_install", "-at_install")
class TestPaymentToken(FawryCommon, PaymentHttpCommon):

    def setUp(self):
        super().setUp()
        self._set_integration("s2s")
        self.other_card_token = "a" * 64

    def _create_card(self, **values):
        return self._create_token(**{
            "provider_ref": self.card_token,
            "payment_details": "1019",
            "payment_method_id": self.pm_visa.id,
            "fawry_customer_profile_id": str(self.partner.id),
            **values,
        })

    def _patch_list(self, **kwargs):
        return patch.object(type(self.fawry), "_fawry_list_card_tokens", **kwargs)

    def _patch_delete(self):
        return patch.object(type(self.fawry), "_fawry_delete_card_token")

    # === REFRESH === #

    @mute_logger(TOKEN_LOGGER)
    def test_cards_fawry_no_longer_has_are_archived(self):
        card = self._create_card()
        removed_card = self._create_card(provider_ref=self.other_card_token)
        with self._patch_list(return_value=[self.saved_card]), self._patch_delete() as delete_mock:
            tokens = (card + removed_card)._fawry_refresh()
        self.assertEqual(tokens, card)
        self.assertFalse(removed_card.active)
        self.assertFalse(delete_mock.called, "Fawry already removed the card.")

    def test_checked_cards_get_their_expiry_date(self):
        card = self._create_card()
        with self._patch_list(return_value=[self.saved_card]):
            card._fawry_refresh()
        self.assertEqual(card.fawry_card_expiry, "01/39")
        self.assertTrue(card.fawry_last_check)

    @mute_logger(TOKEN_LOGGER)
    def test_cards_are_kept_when_fawry_cant_be_reached(self):
        card = self._create_card()
        with self._patch_list(side_effect=ValidationError("Fawry is down")):
            tokens = card._fawry_refresh()
        self.assertEqual(tokens, card)
        self.assertFalse(card.fawry_last_check)

    def test_cards_are_listed_once_per_customer(self):
        card = self._create_card()
        other_card = self._create_card(provider_ref=self.other_card_token)
        other_customer_card = self._create_card(
            partner_id=self.portal_partner.id, fawry_customer_profile_id=False,
        )
        saved_cards = [self.saved_card, dict(self.saved_card, token=self.other_card_token)]
        with self._patch_list(return_value=saved_cards) as list_mock:
            (card + other_card + other_customer_card)._fawry_refresh()
        self.assertCountEqual(
            [call.args[0] for call in list_mock.call_args_list],
            [str(self.partner.id), str(self.portal_partner.id)],
        )

    def test_recently_checked_cards_are_not_checked_again(self):
        card = self._create_card(fawry_last_check=fields.Datetime.now())
        with self._patch_list(return_value=[]) as list_mock:
            tokens = card._fawry_refresh()
        self.assertFalse(list_mock.called)
        self.assertEqual(tokens, card)

        card.fawry_last_check = fields.Datetime.now() - timedelta(minutes=11)
        with self._patch_list(return_value=[self.saved_card]) as list_mock:
            card._fawry_refresh()
        self.assertTrue(list_mock.called)

    @mute_logger(TOKEN_LOGGER)
    def test_expired_cards_are_archived(self):
        card = self._create_card(fawry_card_expiry="01/20", fawry_last_check=fields.Datetime.now())
        with self._patch_list() as list_mock, self._patch_delete() as delete_mock:
            tokens = card._fawry_refresh()
        self.assertFalse(tokens)
        self.assertFalse(card.active)
        self.assertFalse(list_mock.called)
        self.assertFalse(delete_mock.called)

    def test_other_providers_tokens_are_left_alone(self):
        token = self._create_token(provider_id=self.dummy_provider.id)
        with self._patch_list() as list_mock:
            tokens = token._fawry_refresh()
        self.assertEqual(tokens, token)
        self.assertFalse(list_mock.called)

    # === SAVING === #

    def test_saved_card_keeps_its_expiry_date(self):
        tx = self._create_transaction(
            "redirect",
            operation="validation",
            fawry_card_token=self.card_token,
            fawry_customer_profile_id="42",
            fawry_card_data={
                key: self.saved_card[key]
                for key in ("lastFourDigits", "firstSixDigits", "brand", "expiryDate")
            },
        )
        values = tx._extract_token_values({})
        self.assertEqual(values["fawry_card_expiry"], "01/39")
        self.assertTrue(values["fawry_last_check"])

    # === PAYMENT FORMS === #

    @mute_logger(TOKEN_LOGGER)
    def test_my_payment_methods_page_shows_the_cards_fawry_still_has(self):
        self.partner = self.portal_partner
        card = self._create_card()
        removed_card = self._create_card(provider_ref=self.other_card_token)
        self.authenticate(self.portal_user.login, self.portal_user.login)
        with self._patch_list(return_value=[self.saved_card]), self._patch_delete():
            response = self._portal_payment_method()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._get_payment_context(response)["token_ids"], [card.id])
        self.assertFalse(removed_card.active)
        self.assertIn("Expires 01/39", response.text, "The expiry date known by Fawry is shown.")
