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
import io

from PIL import Image

from odoo.tools import BinaryBytes

from odoo.addons.payment.tests.common import PaymentCommon
from odoo.addons.payment_instapay_cf import const

LINK = "https://ipn.eg/S/testshop/instapay/AbC123"
# Example Egyptian IBAN published with the ISO 13616 registry.
IBAN = "EG380019000500000000263180002"
TRANSFER_REFERENCE = "224663943247"


def make_image(image_format="PNG", size=(360, 720), color=(80, 13, 118), **save_kwargs):
    """Return the bytes of a plain image, standing for the screenshot of a transfer."""
    image = Image.new("RGB", size, color)
    output = io.BytesIO()
    image.save(output, format=image_format, **save_kwargs)
    return output.getvalue()


class InstapayCommon(PaymentCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.enable_process_patcher = False  # The InstaPay events are applied for real.

        cls.company.tz = "Africa/Cairo"
        # Sunday to Thursday, 09:00 to 17:00: 8 hours a day.
        cls.calendar = cls.env["resource.calendar"].create({
            "name": "Sunday to Thursday",
            "attendance_ids": [
                (0, 0, {"hour_from": 9, "hour_to": 17, "dayofweek": day})
                for day in ("6", "0", "1", "2", "3")
            ],
        })
        cls.reviewer = cls._create_new_internal_user(login="instapay_reviewer")
        cls._prepare_user(cls.reviewer, "account.group_account_invoice")

        cls.instapay = cls._prepare_provider(
            "instapay_cf",
            update_values={
                "instapay_cf_calendar_id": cls.calendar.id,
                "instapay_cf_reviewer_user_id": cls.reviewer.id,
                "instapay_cf_review_days": 2,
            },
        )
        cls.provider = cls.instapay
        cls.currency = cls._enable_currency("EGP")
        cls.account_instapay = cls.env["payment.instapay.account"].create({
            "provider_id": cls.instapay.id,
            "kind": "instapay",
            "holder_name": "Test Shop",
            "payment_link": LINK,
            "mobile": "+20 100 123 4567",
            "sequence": 1,
        })
        cls.account_wallet = cls.env["payment.instapay.account"].create({
            "provider_id": cls.instapay.id,
            "kind": "wallet",
            "holder_name": "Test Shop",
            "wallet_operator": "vodafone_cash",
            "wallet_number": "01012345678",
            "sequence": 2,
        })
        cls.instapay.is_published = True

        cls.payment_method = cls.env.ref("payment_instapay_cf.payment_method_instapay")
        cls.payment_method.active = True
        cls.payment_method_id = cls.payment_method.id
        cls.payment_method_code = const.PAYMENT_METHOD_CODE
        cls.amount = 1500.0
        cls.reference = "S00077"
        cls.partner.write({"email": "norbert.buyer@example.com", "lang": "en_US"})

    def _create_instapay_tx(self, state="pending", **values):
        tx = self._create_transaction("redirect", **values)
        if state != "draft":
            self._update_transaction(tx, state=state)
        return tx

    def _create_receipt(self, tx, **values):
        return self.env["payment.instapay.receipt"].create({
            "transaction_id": tx.id,
            "source": "customer",
            "image": BinaryBytes(make_image()),
            "transfer_reference": TRANSFER_REFERENCE,
            "amount_sent": tx.amount,
            **values,
        })

    def _record_event(self, tx, event, **data):
        tx._record({"reference": tx.reference, const.EVENT_KEY: event, **data})
        self._run_processing()

    def _get_mails(self, tx):
        return self.env["mail.mail"].sudo().search([
            ("model", "=", "payment.transaction"), ("res_id", "=", tx.id),
        ])

    def _token(self, tx):
        return self._generate_test_access_token(
            const.PROVIDER_CODE, tx.id, tx.reference, tx.partner_id.id,
        )
