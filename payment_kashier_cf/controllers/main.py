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
import base64
import hashlib
from datetime import timedelta

import psycopg2.errors
from werkzeug.exceptions import Forbidden, NotFound

from odoo import fields, http
from odoo.http import request
from odoo.tools import SQL, file_open

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_kashier_cf import const
from odoo.addons.payment_kashier_cf import utils as kashier_utils

_logger = get_payment_logger(__name__, const.SENSITIVE_KEYS)


class KashierController(http.Controller):
    _return_url = "/payment/kashier_cf/return"
    _webhook_url = "/payment/kashier_cf/webhook"
    _pay_url = "/payment/kashier_cf/pay"
    _start_url = "/payment/kashier_cf/start"
    _poll_url = "/payment/kashier_cf/poll"

    @http.route(
        f"{_return_url}/<int:tx_id>/<string:access_token>",
        type="http",
        auth="public",
        methods=["GET"],
    )
    def kashier_cf_return(self, tx_id, access_token, **params):
        """Handle the customer coming back from Kashier's payment page.

        The query string is signed by Kashier, but never trusted: the key that signs it is given away
        in Kashier's session documents. The status is fetched from Kashier with the Secret Key.
        """
        tx_sudo = self._kashier_cf_get_transaction(tx_id, access_token)
        if params.get("signature"):
            signed = kashier_utils.same_signature(
                params["signature"],
                tx_sudo.provider_id._kashier_cf_hash(kashier_utils.redirect_signing_string(params)),
            )
            _logger.info("Customer back from Kashier for %s (signature %s).", tx_sudo.reference,
                         "valid" if signed else "INVALID")
        self._kashier_cf_sync(tx_sudo, force=True)
        return request.redirect("/payment/status")

    @http.route(_webhook_url, type="http", auth="public", methods=["POST"], csrf=False, save_session=False)
    def kashier_cf_webhook(self):
        """Handle Kashier's notifications: a bad signature is refused, anything else triggers a status
        check made with the Secret Key. The body itself is never recorded.

        :return: HTTP 200 (or 403 for a bad signature, 503 to make Kashier retry later).
        """
        raw = request.httprequest.get_data(as_text=True)
        try:
            payload = kashier_utils.loads_keeping_numbers(raw)
        except ValueError:
            return request.make_response("", status=200)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return request.make_response("", status=200)
        order_ref = str(data.get("merchantOrderId") or "")
        tx_sudo = self._kashier_cf_find_by_order_ref(order_ref)
        if not tx_sudo:
            if order_ref and self._kashier_cf_is_own_order_ref(order_ref):
                # An order of this database not committed yet (a charge still running): retry later.
                return request.make_response("", status=503)
            _logger.info("Kashier notification for an unknown order; acknowledged.")
            return request.make_response("", status=200)
        received = request.httprequest.headers.get("x-kashier-signature")
        if received:
            try:
                expected = tx_sudo.provider_id._kashier_cf_hash(kashier_utils.webhook_signing_string(data))
            except kashier_utils.UnsignableValue as error:
                _logger.info("Kashier notification for %s can't be checked (%s): status checked instead.",
                             tx_sudo.reference, error)
                expected = None
            if expected is not None and not kashier_utils.same_signature(received, expected):
                _logger.warning("Kashier notification for %s with an invalid signature; refused.", tx_sudo.reference)
                raise Forbidden
            if expected is not None:
                _logger.info("Kashier notification for %s (signature valid).", tx_sudo.reference)
        else:
            _logger.info("Kashier notification for %s without a signature: status checked.", tx_sudo.reference)
        if not self._kashier_cf_sync(tx_sudo):
            return request.make_response("", status=503)
        return request.make_response("", status=200)

    # === SERVER-SIDE PAYMENTS (no Kashier page) === #

    @http.route(
        f"{_pay_url}/<int:tx_id>/<string:access_token>", type="http", auth="public", methods=["GET"], website=True,
    )
    def kashier_cf_pay_page(self, tx_id, access_token):
        """The page of a payment Odoo asks Kashier for itself: the customer enters a mobile number (wallet,
        Basata) or scans a QR (InstaPay), then waits for the result here.
        """
        tx_sudo = self._kashier_cf_get_transaction(tx_id, access_token)
        if tx_sudo._kashier_cf_integration() != const.INTEGRATION_SERVER:
            return request.redirect("/payment/status")
        if tx_sudo.state == "draft":
            tx_sudo._kashier_cf_prepare_server_payment()
        partner = tx_sudo.partner_id
        values = {
            "tx": tx_sudo,
            "kind": tx_sudo.payment_method_id._kashier_cf_spec().get("server"),
            "company": tx_sudo.company_id,
            "access_token": access_token,
            "phone": kashier_utils.normalize_eg_mobile(partner.phone or ""),
            "qr_data_uri": self._kashier_cf_qr_data_uri(tx_sudo.kashier_cf_qr_payload),
            "expires_at": fields.Datetime.to_string(tx_sudo.kashier_cf_expires_at) if tx_sudo.kashier_cf_expires_at else "",
            "start_url": self._start_url,
            "poll_url": self._poll_url,
            "max_attempts": const.SERVER_MAX_ATTEMPTS,
        }
        return request.render("payment_kashier_cf.server_payment_page", values)

    @http.route(_start_url, type="jsonrpc", auth="public")
    def kashier_cf_start(self, tx_id, access_token, value=""):
        """Send the request of a server-side payment (once at a time per payment)."""
        tx_sudo = self._kashier_cf_get_transaction(tx_id, access_token)
        if not self._kashier_cf_lock(tx_sudo):
            return {"ok": False, "busy": True, "can_retry": False,
                    "message": request.env._("This payment is being processed. Wait a moment.")}
        result = tx_sudo._kashier_cf_start_server_payment(value)
        result.update(self._kashier_cf_state_values(tx_sudo))
        result["qr_data_uri"] = self._kashier_cf_qr_data_uri(tx_sudo.kashier_cf_qr_payload)
        return result

    @http.route(_poll_url, type="jsonrpc", auth="public")
    def kashier_cf_poll(self, tx_id, access_token):
        """Check the payment with Kashier (at most every few seconds) and return its state."""
        tx_sudo = self._kashier_cf_get_transaction(tx_id, access_token)
        if tx_sudo.state in ("draft", "pending", "authorized"):
            self._kashier_cf_sync(tx_sudo)
        return self._kashier_cf_state_values(tx_sudo)

    # === APPLE PAY DOMAIN FILE === #

    @http.route(
        [const.APPLE_PAY_DOMAIN_FILE_URL, f"{const.APPLE_PAY_DOMAIN_FILE_URL}.txt"],
        type="http", auth="public", methods=["GET"],
    )
    def kashier_cf_apple_pay_domain_file(self):
        """Serve the Apple Pay domain file of the shop's host.

        One file per host: Kashier's when a Kashier provider has one, else our Paymob module's, else Odoo's
        Stripe connector's (they serve the same address; this route is matched first).
        """
        host = request.httprequest.host.split(":")[0]
        Provider = request.env["payment.provider"]
        content = Provider._kashier_cf_get_apple_pay_domain_file(host)
        if content is None and hasattr(Provider, "_paymob_cf_get_apple_pay_domain_file"):
            content = Provider._paymob_cf_get_apple_pay_domain_file(host)
        if content is None:
            if request.env["ir.module.module"].sudo()._get("payment_stripe").state != "installed":
                raise NotFound
            with file_open("payment_stripe/static/files/apple-developer-merchantid-domain-association", "rb") as f:
                content = f.read()
        return request.make_response(content, headers=[("Content-Type", "text/plain")])

    # === HELPERS === #

    @staticmethod
    def _kashier_cf_find_by_order_ref(order_ref):
        """The Kashier transaction of an order reference, current or of an earlier attempt."""
        Transaction = request.env["payment.transaction"].sudo()
        if not order_ref:
            return Transaction
        tx_sudo = Transaction.search([("provider_code", "=", const.PROVIDER_CODE), ("kashier_cf_order_ref", "=", order_ref)], limit=1)
        if not tx_sudo:
            tx_sudo = Transaction.search([
                ("provider_code", "=", const.PROVIDER_CODE), ("kashier_cf_attempt_refs", "ilike", order_ref),
            ]).filtered(lambda tx: order_ref in (tx.kashier_cf_attempt_refs or "").split(","))[:1]
        return tx_sudo

    @staticmethod
    def _kashier_cf_lock(tx_sudo):
        """Lock the payment for this request; False when another request holds it."""
        try:
            with request.env.cr.savepoint(flush=False):
                request.env.cr.execute(SQL("SELECT id FROM payment_transaction WHERE id = %s FOR UPDATE NOWAIT", tx_sudo.id))
        except psycopg2.errors.LockNotAvailable:
            return False
        return True

    @staticmethod
    def _kashier_cf_state_values(tx_sudo):
        tx_sudo.invalidate_recordset()
        return {
            "state": tx_sudo.state,
            "final": tx_sudo.state in ("done", "authorized", "cancel", "error")
            or (tx_sudo.state == "pending" and tx_sudo.kashier_cf_server_kind == "basata"),
            "attempts": tx_sudo.kashier_cf_attempts,
            "expires_at": fields.Datetime.to_string(tx_sudo.kashier_cf_expires_at) if tx_sudo.kashier_cf_expires_at else "",
            "code": tx_sudo.kashier_cf_reference_code or "",
            "status_url": "/payment/status",
        }

    @staticmethod
    def _kashier_cf_qr_data_uri(payload):
        """The InstaPay QR as a PNG data URI, drawn by Odoo (the payload never reaches the page)."""
        if not payload:
            return ""
        png = request.env["ir.actions.report"].barcode("QR", payload, width=300, height=300)
        return "data:image/png;base64," + base64.b64encode(png).decode()

    @staticmethod
    def _kashier_cf_get_transaction(tx_id, access_token):
        """Return the Kashier transaction matching the id, if the access token is valid.

        :raise Forbidden: If the transaction doesn't exist or the access token is invalid.
        """
        tx_sudo = request.env["payment.transaction"].sudo().browse(tx_id).exists()
        if (
            not tx_sudo
            or tx_sudo.provider_code != const.PROVIDER_CODE
            or not payment_utils.check_access_token(access_token, tx_sudo.reference, tx_sudo.partner_id.id)
        ):
            raise Forbidden
        return tx_sudo

    @staticmethod
    def _kashier_cf_sync(tx_sudo, force=False):
        """Fetch the status from Kashier, at most every few seconds per payment, and never while an
        answer of Kashier waits for processing or is being applied.

        :return: Whether the status is known (Kashier answered, or it was checked a moment ago).
        """
        root = tx_sudo._kashier_cf_root()
        recent = root.kashier_cf_last_sync and root.kashier_cf_last_sync > (
            fields.Datetime.now() - timedelta(seconds=const.SYNC_THROTTLE_SECONDS)
        )
        if recent and not force:
            return True
        if request.env["payment.data"].sudo().search_count(
            [("transaction_id", "=", root.id), ("errored", "=", False)], limit=1,
        ):
            return True
        try:
            with request.env.cr.savepoint(flush=False):
                request.env.cr.execute(SQL(
                    "SELECT id FROM payment_transaction WHERE id = %s FOR UPDATE NOWAIT", root.id,
                ))
        except psycopg2.errors.LockNotAvailable:
            return True  # Kashier's answer is being applied right now.
        return root._kashier_cf_sync_from_provider()

    @staticmethod
    def _kashier_cf_is_own_order_ref(order_ref):
        """Whether an order reference was made by this database (it ends with the database code)."""
        uuid = request.env["ir.config_parameter"].sudo().get_str("database.uuid") or request.env.cr.dbname
        database_code = hashlib.sha1(uuid.encode()).hexdigest()[:6]  # noqa: S324 (not security)
        return order_ref.rsplit("-", 1)[-1][:6] == database_code
