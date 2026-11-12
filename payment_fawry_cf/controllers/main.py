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
from odoo.tools import consteq

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_fawry_cf import const
from odoo.addons.payment_fawry_cf import utils as fawry_utils

_logger = get_payment_logger(__name__, const.SENSITIVE_KEYS)

# The minimum delay between two status checks triggered by a customer waiting for a payment.
POLL_SYNC_DELAY = timedelta(seconds=10)


class FawryController(http.Controller):
    _return_url = "/payment/fawry/return"
    _card_return_url = "/payment/fawry/card"
    _webhook_url = "/payment/fawry/webhook"
    _charge_url = "/payment/fawry/charge"
    _poll_url = "/payment/fawry/poll"
    _installments_url = "/payment/fawry/installments"

    @http.route(
        f"{_return_url}/<int:tx_id>/<string:access_token>",
        type="http",
        auth="public",
        methods=["GET"],
    )
    def fawry_return(self, tx_id, access_token, **data):
        """Handle the customer coming back from Fawry's checkout or from 3-D Secure.

        A charge response signed by Fawry is recorded as is. Otherwise (Fawry's checkout leaves
        out some signed values from the redirection), the status of the payment is fetched from
        Fawry; the redirection values are then only used to report a failure Fawry has no order
        for.

        :param int tx_id: The id of the transaction.
        :param str access_token: The access token of the transaction.
        :param dict data: The values Fawry added to the redirection.
        """
        _logger.info(
            "Handling redirection from Fawry for transaction %s with data:\n%s",
            tx_id,
            pprint.pformat(data),
        )
        tx_sudo = self._fawry_get_transaction(tx_id, access_token)
        if self._fawry_is_signed_charge_response(tx_sudo, data):
            # Only the signed values are recorded: anything else in the URL can be added by anyone.
            tx_sudo._record({
                key: data[key] for key in const.SIGNED_CHARGE_RESPONSE_KEYS if key in data
            })
        else:
            tx_sudo._fawry_sync_from_provider(fallback_values=data)
        return request.redirect("/payment/status")

    @http.route(
        f"{_card_return_url}/<int:tx_id>/<string:access_token>",
        type="http",
        auth="public",
        methods=["GET"],
    )
    def fawry_card_return(self, tx_id, access_token, **data):
        """Handle the customer coming back from Fawry's secure card page.

        The card token is checked against the cards Fawry saved for the customer, then either
        saved (when the customer only adds a card) or charged with 3-D Secure.

        :param int tx_id: The id of the transaction.
        :param str access_token: The access token of the transaction.
        :param dict data: The card details sent by Fawry: `token`, `lastFourDigits`, `brand`...
        """
        _logger.info(
            "Handling redirection from Fawry's card page for transaction %s with data:\n%s",
            tx_id,
            pprint.pformat(data),
        )
        tx_sudo = self._fawry_get_transaction(tx_id, access_token)
        if tx_sudo.state != "draft" or tx_sudo.fawry_card_token:
            # Already handled (e.g. the customer reloaded the page).
            if tx_sudo.state in ("draft", "pending") and tx_sudo.fawry_redirect_url:
                return request.redirect(tx_sudo.fawry_redirect_url, local=False)
            return request.redirect("/payment/status")

        card_token = data.get("token")
        if str(data.get("statusCode")) != "200" or not card_token:
            self._fawry_record_failure(
                tx_sudo,
                data.get("statusDescription") or self.env._("The card could not be saved."),
                data.get("statusCode"),
            )
            return request.redirect("/payment/status")

        provider_sudo = tx_sudo.provider_id
        profile_id = tx_sudo._fawry_get_customer_profile_id()
        try:
            cards = provider_sudo._fawry_list_card_tokens(profile_id)
        except ValidationError as error:
            self._fawry_record_error(tx_sudo, error)
            return request.redirect("/payment/status")
        card = next((card for card in cards if card.get("token") == card_token), None)
        if not card:
            _logger.warning(
                "Fawry has no such card for the customer of transaction %s.", tx_sudo.reference,
            )
            raise Forbidden

        tx_sudo.with_context(payment_safe_write=True).write({
            "fawry_customer_profile_id": profile_id,
            "fawry_card_token": card_token,
            "fawry_card_data": {
                key: card.get(key)
                for key in ("lastFourDigits", "firstSixDigits", "brand", "expiryDate")
            },
        })
        if tx_sudo.operation == "validation":
            tx_sudo._record({"merchantRefNumber": tx_sudo.reference, "fawry_validation": True})
            return request.redirect("/payment/status")

        if tx_sudo._fawry_get_installment_plans(card.get("firstSixDigits")):
            # The customer first chooses between paying in full and the installment plans.
            return request.redirect(
                f"{self._installments_url}/{tx_sudo.id}/{tx_sudo._fawry_get_access_token()}",
            )
        try:
            response = tx_sudo._fawry_charge_card_token(card_token)
            redirect_url = tx_sudo._fawry_handle_charge_response(response)
        except ValidationError as error:
            self._fawry_record_error(tx_sudo, error)
            return request.redirect("/payment/status")
        if redirect_url:
            return request.redirect(redirect_url, local=False)
        return request.redirect("/payment/status")

    @http.route(
        f"{_installments_url}/<int:tx_id>/<string:access_token>",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        website=True,
        sitemap=False,
    )
    def fawry_installments(self, tx_id, access_token, plan=None, **_kwargs):
        """Let the customer pay a card payment in full or with a bank installment plan.

        The page is shown after the card was entered on Fawry's secure page, or a saved card was
        chosen, when Fawry has installment plans for the card and the amount. The chosen plan is
        checked again against the plans Fawry offers before the card is charged.

        :param int tx_id: The id of the transaction.
        :param str access_token: The access token of the transaction.
        :param str plan: The id of the chosen plan, or "full" to pay in full (POST only).
        """
        tx_sudo = self._fawry_get_transaction(tx_id, access_token)
        card_token, card_bin = tx_sudo._fawry_get_card()
        provider_sudo = tx_sudo.provider_id
        if tx_sudo.state != "draft" or not card_token:
            return request.redirect("/payment/status")
        if provider_sudo._fawry_is_own_url(tx_sudo.fawry_redirect_url):
            # The card was already charged; the customer still has to authenticate the payment.
            return request.redirect(tx_sudo.fawry_redirect_url, local=False)

        plans = tx_sudo._fawry_get_installment_plans(card_bin)
        if request.httprequest.method == "GET" and plans:
            return request.render("payment_fawry_cf.installment_plans", {
                "tx": tx_sudo,
                "plans": plans,
                "plan_options": tx_sudo._fawry_get_installment_options(plans),
                "action_url": f"{self._installments_url}/{tx_sudo.id}/{access_token}",
            })

        installment_plan = None
        if plan and plan != "full":
            installment_plan = next((p for p in plans if str(p["id"]) == plan), None)
            if not installment_plan:
                _logger.warning(
                    "The installment plan %s is not available for transaction %s.",
                    plan,
                    tx_sudo.reference,
                )
                return request.redirect(
                    f"{self._installments_url}/{tx_sudo.id}/{access_token}",
                )
        try:
            response = tx_sudo._fawry_charge_card_token(card_token, installment_plan)
            redirect_url = tx_sudo._fawry_handle_charge_response(response)
        except ValidationError as error:
            self._fawry_record_error(tx_sudo, error)
            return request.redirect("/payment/status")
        if redirect_url:
            return request.redirect(redirect_url, local=False)
        return request.redirect("/payment/status")

    @http.route(_webhook_url, type="http", auth="public", methods=["POST"], csrf=False)
    def fawry_webhook(self):
        """Process a server notification (V2) sent by Fawry when a payment changes.

        The notification only triggers a status check: its signature is verified, then the status
        is fetched from Fawry, as Fawry signs values concatenated without separators, which
        doesn't bind each value to its field.

        :return: An empty response to acknowledge the notification, or an HTTP 503 so that Fawry
                 sends it again when Fawry's status couldn't be fetched.
        """
        data = request.get_json_data()
        _logger.info("Notification received from Fawry with data:\n%s", pprint.pformat(data))
        tx_sudo = self.env["payment.transaction"].sudo()._search_by_reference("fawry", data)
        if tx_sudo:
            expected_signature = fawry_utils.compute_notification_signature(
                data, tx_sudo.provider_id.fawry_secure_key,
            )
            payment_utils.verify_signature(data.get("messageSignature", ""), expected_signature)
            try:
                status = tx_sudo.provider_id._fawry_get_payment_status(tx_sudo.reference)
            except ValidationError:
                _logger.warning("Unable to fetch the Fawry status of %s.", tx_sudo.reference)
                return request.make_response("", status=503)
            if status:
                tx_sudo._record(status)
        return ""  # Acknowledge the notification.

    @http.route(_charge_url, type="jsonrpc", auth="public")
    def fawry_charge(self, reference, access_token, wallet_number=None):
        """Create the Fawry reference code, wallet request or myFawry payment of a transaction.

        :param str reference: The reference of the transaction.
        :param str access_token: The access token of the transaction.
        :param str wallet_number: The mobile wallet to send a payment request to, if any.
        :return: Where to send the customer next, or the error if Fawry rejected the charge (the
                 error is returned rather than raised, so that the failed state is saved).
        :rtype: dict
        :raise ValidationError: If the request is invalid.
        """
        tx_sudo = self._fawry_get_transaction_by_reference(reference, access_token)
        if tx_sudo.state != "draft" or tx_sudo.provider_reference:
            return {"redirect_url": "/payment/status"}  # Already created.
        flow = tx_sudo.provider_id._fawry_get_flow(tx_sudo.payment_method_code)
        if flow != const.FLOW_S2S_CHARGE:
            raise ValidationError(self.env._("This payment method can't be paid this way."))

        if wallet_number:
            normalized_number = fawry_utils.normalize_mobile(wallet_number)
            if not normalized_number:
                raise ValidationError(
                    self.env._("Enter the mobile number of your wallet, such as 01012345678."),
                )
            wallet_number = normalized_number

        try:
            response = tx_sudo.with_context(payment_safe_write=True)._fawry_charge(
                wallet_number=wallet_number,
            )
        except ValidationError as error:
            tx_sudo._fawry_set_error(error)
            return {"error": tx_sudo.state_message}
        tx_sudo._record(response)
        return {"redirect_url": "/payment/status"}

    @http.route(_poll_url, type="jsonrpc", auth="public")
    def fawry_poll(self, reference, access_token):
        """Return the state of a payment the customer is waiting for, checking it with Fawry.

        :param str reference: The reference of the transaction.
        :param str access_token: The access token of the transaction.
        :return: The state of the transaction.
        :rtype: dict
        """
        tx_sudo = self._fawry_get_transaction_by_reference(reference, access_token)
        last_sync = tx_sudo.fawry_last_sync
        now = fields.Datetime.now()
        if tx_sudo.state in ("draft", "pending") and (
            not last_sync or now - last_sync >= POLL_SYNC_DELAY
        ):
            # The recorded status is processed by the payment cron once this request ends (the
            # transaction stays locked until then); the next poll returns the new state.
            tx_sudo.with_context(payment_safe_write=True).fawry_last_sync = now
            tx_sudo._fawry_sync_from_provider()
        return {"state": tx_sudo.state}

    # === HELPERS === #

    def _fawry_get_transaction(self, tx_id, access_token):
        """Return the Fawry transaction matching the id, if the access token is valid.

        :raise Forbidden: If the transaction doesn't exist or the access token is invalid.
        """
        tx_sudo = self.env["payment.transaction"].sudo().browse(tx_id).exists()
        if (
            not tx_sudo
            or tx_sudo.provider_code != "fawry"
            or not payment_utils.check_access_token(
                access_token, tx_sudo.reference, tx_sudo.partner_id.id,
            )
        ):
            raise Forbidden
        return tx_sudo

    def _fawry_get_transaction_by_reference(self, reference, access_token):
        """Return the Fawry transaction matching the reference, if the access token is valid.

        :raise ValidationError: If the transaction doesn't exist or the access token is invalid.
        """
        tx_sudo = self.env["payment.transaction"].sudo().search(
            [("reference", "=", reference), ("provider_code", "=", "fawry")], limit=1,
        )
        if not tx_sudo or not payment_utils.check_access_token(
            access_token, tx_sudo.reference, tx_sudo.partner_id.id,
        ):
            raise ValidationError(self.env._("Received tampered payment request data."))
        return tx_sudo

    @staticmethod
    def _fawry_is_signed_charge_response(tx_sudo, data):
        """Return whether the redirection values are a charge response of this transaction that
        Fawry signed.
        """
        received_signature = data.get("signature")
        if not received_signature or data.get("merchantRefNumber") != tx_sudo.reference:
            return False
        expected_signature = fawry_utils.compute_charge_response_signature(
            data, tx_sudo.provider_id.fawry_secure_key,
        )
        return consteq(received_signature, expected_signature)

    @classmethod
    def _fawry_record_error(cls, tx_sudo, error):
        """Record a request Fawry refused before it created an order, with Fawry's error code."""
        cls._fawry_record_failure(
            tx_sudo,
            getattr(error, "description", None) or str(error),
            getattr(error, "code", None),
        )

    @staticmethod
    def _fawry_record_failure(tx_sudo, message, code=None):
        """Record a failure that happened before Fawry created an order."""
        tx_sudo._record({
            "merchantRefNumber": tx_sudo.reference,
            "orderStatus": "FAILED",
            "failureErrorCode": code,
            "failureReason": message,
        })
