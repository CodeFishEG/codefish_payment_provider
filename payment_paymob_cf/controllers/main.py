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
import pprint
from datetime import timedelta

from werkzeug.exceptions import Forbidden

from odoo import fields, http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_paymob_cf import const
from odoo.addons.payment_paymob_cf import utils as paymob_utils

_logger = get_payment_logger(__name__, const.SENSITIVE_KEYS)

# The minimum delay between two status checks triggered by a customer waiting for a payment.
POLL_SYNC_DELAY = timedelta(seconds=10)


class PaymobController(http.Controller):
    _return_url = "/payment/paymob_cf/return"
    _frame_return_url = "/payment/paymob_cf/return_frame"
    _complete_url = "/payment/paymob_cf/complete"
    _webhook_url = "/payment/paymob_cf/webhook"
    _poll_url = "/payment/paymob_cf/poll"

    @http.route(
        f"{_return_url}/<int:tx_id>/<string:access_token>",
        type="http",
        auth="public",
        methods=["GET"],
    )
    def paymob_cf_return(self, tx_id, access_token, **data):
        """Handle the customer coming back from Paymob Checkout, the card form or 3-D Secure.

        :param int tx_id: The id of the transaction.
        :param str access_token: The access token of the transaction.
        :param dict data: The values Paymob added to the redirection.
        """
        tx_sudo = self._paymob_cf_get_transaction(tx_id, access_token)
        self._paymob_cf_process_redirection(tx_sudo, data)
        return request.redirect("/payment/status")

    @http.route(
        f"{_frame_return_url}/<int:tx_id>/<string:access_token>",
        type="http",
        auth="public",
        methods=["GET"],
    )
    def paymob_cf_return_frame(self, tx_id, access_token, **data):
        """Handle the customer coming back from Paymob Checkout shown in a pop-up or a side panel.

        The page loads in the frame of the checkout: it takes the whole window to the payment
        status page.
        """
        tx_sudo = self._paymob_cf_get_transaction(tx_id, access_token)
        self._paymob_cf_process_redirection(tx_sudo, data)
        return request.render("payment_paymob_cf.frame_exit", {"redirect_url": "/payment/status"})

    @http.route(
        f"{_complete_url}/<int:tx_id>/<string:access_token>",
        type="http",
        auth="public",
        methods=["GET"],
    )
    def paymob_cf_complete(self, tx_id, access_token, **_kwargs):
        """Handle the end of a payment made in Paymob's embedded card form.

        The result is fetched from Paymob, never taken from the browser.
        """
        tx_sudo = self._paymob_cf_get_transaction(tx_id, access_token)
        self._paymob_cf_process_redirection(tx_sudo, {})
        return request.redirect("/payment/status")

    @http.route(_webhook_url, type="http", auth="public", methods=["POST"], csrf=False)
    def paymob_cf_webhook(self, **_kwargs):
        """Process a callback sent by Paymob: a transaction, or a card the customer saved.

        The callback is matched with its payment from the values Paymob signs (the order, or the
        transaction for refunds, captures and voids), then its HMAC is checked.

        :return: An empty response to acknowledge the callback.
        :raise Forbidden: If the HMAC is missing or wrong.
        """
        data = request.get_json_data()
        if not isinstance(data, dict):
            return ""
        _logger.info("Callback received from Paymob with data:\n%s", pprint.pformat(data))
        received_hmac = request.httprequest.args.get("hmac") or data.get("hmac")
        callback_type = str(data.get("type") or const.CALLBACK_TRANSACTION).upper()
        obj = data.get("obj") if isinstance(data.get("obj"), dict) else {}
        obj.pop(const.OWN_REQUEST_KEY, None)  # Only set by Odoo's own requests.
        Transaction = request.env["payment.transaction"].sudo()

        if callback_type == const.CALLBACK_TOKEN:
            tx_sudo = self._paymob_cf_find_by_order(Transaction, obj.get("order_id"))
            if tx_sudo:
                if not tx_sudo.provider_id._paymob_cf_check_token_hmac(obj, received_hmac):
                    _logger.warning("Received a Paymob card token with a wrong HMAC.")
                    raise Forbidden
                token_data = {key: obj.get(key) for key in (
                    *const.TOKEN_HMAC_KEYS, "cardholder_name", "expiry_month", "expiry_year",
                )}
                tx_sudo._record({"type": const.CALLBACK_TOKEN, "obj": token_data})
            return ""

        if callback_type != const.CALLBACK_TRANSACTION:
            _logger.info("Ignored a Paymob callback of type %s.", callback_type)
            return ""
        if paymob_utils.is_true(obj.get("has_parent_transaction")):
            # A refund, capture or void: its own transaction holds Paymob's transaction ID.
            tx_sudo = Transaction.search([
                ("provider_code", "=", "paymob_cf"),
                ("provider_reference", "=", str(obj.get("id") or "")),
                ("source_transaction_id", "!=", False),
            ], limit=1) if obj.get("id") else Transaction
        else:
            tx_sudo = self._paymob_cf_find_by_order(
                Transaction, paymob_utils.get_value(obj, "order.id"),
            )
        if tx_sudo:
            if not tx_sudo.provider_id._paymob_cf_check_transaction_hmac(obj, received_hmac):
                _logger.warning("Received a Paymob transaction with a wrong HMAC.")
                raise Forbidden
            tx_sudo._record(obj)
        return ""  # Acknowledge the callback.

    @http.route(_poll_url, type="jsonrpc", auth="public")
    def paymob_cf_poll(self, reference, access_token):
        """Return the state of a payment the customer is waiting for, checking it with Paymob.

        :param str reference: The reference of the transaction.
        :param str access_token: The access token of the transaction.
        :return: The state of the transaction.
        :rtype: dict
        """
        tx_sudo = request.env["payment.transaction"].sudo().search(
            [("reference", "=", reference), ("provider_code", "=", "paymob_cf")], limit=1,
        )
        if not tx_sudo or not payment_utils.check_access_token(
            access_token, tx_sudo.reference, tx_sudo.partner_id.id,
        ):
            raise ValidationError(request.env._("Received tampered payment request data."))
        last_sync = tx_sudo.paymob_cf_last_sync
        now = fields.Datetime.now()
        if tx_sudo.state in ("draft", "pending") and (
            not last_sync or now - last_sync >= POLL_SYNC_DELAY
        ):
            # The recorded status is processed by the payment cron once this request ends; the next
            # poll returns the new state.
            tx_sudo.with_context(payment_safe_write=True).paymob_cf_last_sync = now
            tx_sudo._paymob_cf_sync_from_provider()
        return {"state": tx_sudo.state}

    # === HELPERS === #

    @staticmethod
    def _paymob_cf_get_transaction(tx_id, access_token):
        """Return the Paymob transaction matching the id, if the access token is valid.

        :raise Forbidden: If the transaction doesn't exist or the access token is invalid.
        """
        tx_sudo = request.env["payment.transaction"].sudo().browse(tx_id).exists()
        if (
            not tx_sudo
            or tx_sudo.provider_code != "paymob_cf"
            or not payment_utils.check_access_token(
                access_token, tx_sudo.reference, tx_sudo.partner_id.id,
            )
        ):
            raise Forbidden
        return tx_sudo

    @staticmethod
    def _paymob_cf_find_by_order(Transaction, order_id):
        """Return the payment Paymob created an order for.

        :param payment.transaction Transaction: The transaction model, in sudo mode.
        :param order_id: The order, as Paymob signs it.
        :rtype: payment.transaction
        """
        order_id = str(order_id or "")
        if not order_id:
            return Transaction
        return Transaction.search([
            ("provider_code", "=", "paymob_cf"),
            ("paymob_cf_order_id", "=", order_id),
            ("source_transaction_id", "=", False),
        ], limit=1)

    @staticmethod
    def _paymob_cf_process_redirection(tx_sudo, data):
        """Update the payment after the customer came back from Paymob.

        The status is fetched from Paymob. If Paymob can't be reached, the redirection is used
        instead, when Paymob signed it and it is about this payment.

        :param payment.transaction tx_sudo: The transaction, in sudo mode.
        :param dict data: The values Paymob added to the redirection.
        """
        _logger.info(
            "Handling the return from Paymob for %s with data:\n%s",
            tx_sudo.reference,
            pprint.pformat(data),
        )
        tx_sudo.with_context(payment_safe_write=True).paymob_cf_last_sync = fields.Datetime.now()
        if tx_sudo._paymob_cf_sync_from_provider():
            return
        received_hmac = data.get("hmac")
        if received_hmac and tx_sudo.provider_id._paymob_cf_check_transaction_hmac(
            data, received_hmac, is_redirection=True,
        ):
            transaction = paymob_utils.redirection_to_transaction(data)
            if tx_sudo._paymob_cf_is_own_order(transaction):
                tx_sudo._record(transaction)
