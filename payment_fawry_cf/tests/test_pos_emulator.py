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
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment.tests.http_common import PaymentHttpCommon
from odoo.addons.payment_fawry_cf import const
from odoo.addons.payment_fawry_cf.controllers.main import FawryController
from odoo.addons.payment_fawry_cf.tests.common import FawryCommon


@tagged("post_install", "-at_install")
class TestPosEmulator(FawryCommon, PaymentHttpCommon):
    """Administrators pay the reference codes of test payments at Fawry's POS Emulator."""

    def _create_reference_code(self, **values):
        return self._create_transaction("direct", **{
            "payment_method_id": self.pm_pay_at_fawry.id,
            "state": "pending",
            "provider_reference": self.fawry_reference,
            **values,
        })

    def _page_url(self, tx):
        return self._build_url(f"{FawryController._pos_emulator_url}/{tx.id}")

    # === PROVIDER === #

    def test_provider_opens_the_emulator_in_test_mode(self):
        action = self.fawry.action_fawry_open_pos_emulator()
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertEqual(action["url"], const.POS_EMULATOR_URL)
        self.assertEqual(action["target"], "new")

    def test_provider_refuses_the_emulator_in_live_mode(self):
        self.fawry.is_live = True
        with self.assertRaises(UserError):
            self.fawry.action_fawry_open_pos_emulator()

    # === TRANSACTION === #

    def test_unpaid_test_reference_code_can_use_the_emulator(self):
        tx = self._create_reference_code()
        self.assertTrue(tx.fawry_can_use_pos_emulator)
        action = tx.action_fawry_pay_at_pos_emulator()
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertEqual(action["url"], f"{FawryController._pos_emulator_url}/{tx.id}")
        self.assertEqual(action["target"], "new")

    def test_emulator_is_only_for_unpaid_test_reference_codes(self):
        live_tx = self._create_reference_code()
        self.fawry.is_live = True
        self.assertFalse(live_tx.fawry_can_use_pos_emulator)
        with self.assertRaises(UserError):
            live_tx.action_fawry_pay_at_pos_emulator()

        self.fawry.is_live = False
        paid_tx = self._create_reference_code(reference="S00042-2", state="done")
        wallet_tx = self._create_transaction(
            "direct",
            reference="S00042-3",
            payment_method_id=self.pm_wallet.id,
            state="pending",
            provider_reference="786884979",
        )
        no_code_tx = self._create_transaction(
            "direct", reference="S00042-4", payment_method_id=self.pm_pay_at_fawry.id,
            state="pending",
        )
        for tx in paid_tx + wallet_tx + no_code_tx:
            self.assertFalse(tx.fawry_can_use_pos_emulator, tx.reference)

    def test_instructions_link_to_the_emulator_for_administrators_only(self):
        tx = self._create_reference_code()
        emulator_page = f"{FawryController._pos_emulator_url}/{tx.id}"

        # Rendered in sudo mode for the user who sees the page, as on the payment status page.
        admin_message = str(tx.with_user(self.admin_user).sudo()._get_status_message())
        self.assertIn("o_fawry_pos_emulator", admin_message)
        self.assertIn(emulator_page, admin_message)

        for user in (self.portal_user, self.internal_user, self.public_user):
            message = str(tx.with_user(user).sudo()._get_status_message())
            self.assertIn("786 884 978", message)  # The customer still gets the instructions.
            self.assertNotIn(emulator_page, message, user.login)

        self.fawry.is_live = True
        live_message = str(tx.with_user(self.admin_user).sudo()._get_status_message())
        self.assertNotIn(emulator_page, live_message)

    # === PAGE === #

    def test_page_shows_the_reference_code_to_administrators(self):
        tx = self._create_reference_code()
        self.authenticate(self.admin_user.login, self.admin_user.login)
        response = self.url_open(self._page_url(tx))
        self.assertEqual(response.status_code, 200)
        self.assertIn("786 884 978", response.text)
        self.assertIn(const.POS_EMULATOR_URL, response.text)
        self.assertIn("o_fawry_instructions", response.text)  # Updates by itself once paid.

    def test_page_shows_the_outcome_once_paid(self):
        tx = self._create_reference_code(state="done")
        self.authenticate(self.admin_user.login, self.admin_user.login)
        response = self.url_open(self._page_url(tx))
        self.assertEqual(response.status_code, 200)
        self.assertIn("Fawry received the payment", response.text)
        self.assertNotIn("o_fawry_instructions", response.text)  # No more checks with Fawry.

    @mute_logger("odoo.http")
    def test_page_is_for_administrators_only(self):
        tx = self._create_reference_code()
        for user in (self.internal_user, self.portal_user):
            self.authenticate(user.login, user.login)
            response = self.url_open(self._page_url(tx))
            self.assertEqual(response.status_code, 403, user.login)

        self.authenticate(None, None)
        response = self.url_open(self._page_url(tx), allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))  # To the login page.
        self.assertIn("/web/login", response.headers["Location"])

    @mute_logger("odoo.http")
    def test_page_is_for_test_reference_codes_only(self):
        card_tx = self._create_transaction("redirect", state="pending")
        live_tx = self._create_reference_code(reference="S00042-5")
        self.authenticate(self.admin_user.login, self.admin_user.login)
        self.assertEqual(self.url_open(self._page_url(card_tx)).status_code, 404)
        self.fawry.is_live = True
        self.assertEqual(self.url_open(self._page_url(live_tx)).status_code, 404)
