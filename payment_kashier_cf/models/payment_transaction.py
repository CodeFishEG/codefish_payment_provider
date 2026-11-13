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
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools.misc import hmac as odoo_hmac

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_kashier_cf import const
from odoo.addons.payment_kashier_cf import utils as kashier_utils
from odoo.addons.payment_kashier_cf.controllers.main import KashierController
from odoo.addons.payment_kashier_cf.exceptions import KashierError

_logger = get_payment_logger(__name__, const.SENSITIVE_KEYS)

ONLINE_OPERATIONS = ("online_redirect", "online_direct", "online_token")


class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    kashier_cf_order_ref = fields.Char(
        string="Kashier Order",
        help="The order reference sent to Kashier (merchantOrderId).",
        readonly=True,
        copy=False,
        index="btree_not_null",
    )
    kashier_cf_session_id = fields.Char(string="Kashier Session", readonly=True, copy=False)
    kashier_cf_order_id = fields.Char(
        string="Kashier Order ID",
        help="Kashier's id of the order; refunds, captures and voids use it.",
        readonly=True,
        copy=False,
        index="btree_not_null",
    )
    kashier_cf_transaction_id = fields.Char(
        string="Kashier Transaction",
        help="Kashier's id of the operation that moved the money (payment, authorization, capture, refund "
        "or void).",
        readonly=True,
        copy=False,
    )
    kashier_cf_redirect_url = fields.Char(
        string="Kashier Page URL",
        help="Kashier's page where the customer confirms a payment with a saved card.", readonly=True, copy=False,
    )
    kashier_cf_channel = fields.Char(string="Paid With (Kashier)", readonly=True, copy=False)
    kashier_cf_operation = fields.Selection(
        string="Kashier Operation",
        selection=[("capture", "Capture"), ("refund", "Refund"), ("void", "Void")],
        help="The operation a child transaction sent to Kashier.",
        readonly=True,
        copy=False,
    )
    kashier_cf_last_sync = fields.Datetime(string="Last Kashier Check", readonly=True, copy=False)
    kashier_cf_outcome_unknown = fields.Boolean(
        string="Kashier Outcome Unknown",
        help="Kashier didn't answer the request: the outcome is checked with Kashier before anything is "
        "sent again.",
        readonly=True,
        copy=False,
    )
    kashier_cf_late_check_until = fields.Datetime(string="Kashier Late Check Until", readonly=True, copy=False)
    kashier_cf_noted_legs = fields.Char(string="Kashier Refunds Noted", readonly=True, copy=False)
    kashier_cf_alerted = fields.Char(string="Kashier Alerts Sent", readonly=True, copy=False)  # By kind.
    kashier_cf_error_code = fields.Char(string="Kashier Error Code", readonly=True, copy=False)
    kashier_cf_error_details = fields.Text(string="Kashier Error Details", readonly=True, copy=False)

    _kashier_cf_transaction_unique = models.UniqueIndex(
        "(provider_id, kashier_cf_transaction_id) WHERE kashier_cf_transaction_id IS NOT NULL",
        "This Kashier operation is already linked to another transaction.",
    )

    # === BUSINESS METHODS - PAYMENT FLOW === #

    def _get_specific_rendering_values(self, processing_values):
        """Override of `payment` to send the customer to Kashier's hosted payment page.

        Note: self.ensure_one() from `_get_processing_values`
        """
        if self.provider_code != const.PROVIDER_CODE:
            return super()._get_specific_rendering_values(processing_values)
        provider = self.provider_id
        try:
            session_url = self._kashier_cf_create_session()
        except ValidationError as error:
            self._kashier_cf_set_error(error)
            # The status page explains the error to the customer.
            return {"api_url": provider._kashier_cf_url("/payment/status"), "http_method": "get", "url_params": {}}
        # A GET form drops the query string of its action: send `mode` as a hidden input.
        parts = urlsplit(session_url)
        return {
            "api_url": urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")),
            "http_method": "get",
            "url_params": dict(parse_qsl(parts.query)),
        }

    def _get_specific_processing_values(self, processing_values):
        """Override of `payment` to give the payment form Kashier's page for a saved card."""
        res = super()._get_specific_processing_values(processing_values)
        if self.provider_code == const.PROVIDER_CODE and self.operation == "online_token" \
                and self.state == "draft" and self.kashier_cf_redirect_url:
            res["kashier_cf_redirect_url"] = self.kashier_cf_redirect_url
        return res

    def _send_payment_request(self):
        """Override of `payment` to pay with a saved card.

        While the customer is there, Kashier's page opens with their saved cards: they confirm with the
        card's security code and their bank (3-D Secure). When the customer is away (subscriptions,
        invoices), the card is charged as a recurring payment.

        Note: self.ensure_one()
        """
        if self.provider_code != const.PROVIDER_CODE:
            return super()._send_payment_request()
        if not self.token_id:
            raise ValidationError(self.env._("The transaction is not linked to a saved card."))
        if self.operation == "online_token":
            try:
                self._kashier_cf_create_session(saved_card=True)
            except KashierError as error:
                self._kashier_cf_store_error(error)
                raise ValidationError(self.provider_id._kashier_cf_get_customer_error_message(error.code)) from None
            return None
        self._kashier_cf_charge_saved_card()
        return None

    def _kashier_cf_create_session(self, saved_card=False):
        """Create Kashier's payment session of the transaction and return the page's URL.

        :param bool saved_card: Whether the customer pays with a saved card (the token of the tx).
        :rtype: str
        """
        self.ensure_one()
        provider = self.provider_id.sudo()
        payload = self._kashier_cf_session_payload(saved_card=saved_card)
        session = provider._kashier_cf_client().create_payment_session(payload, reference=self.reference)
        session_url = session.get("sessionUrl") or ""
        if not session.get("_id") or not kashier_utils.is_checkout_url(session_url):
            raise KashierError(self.env._("Kashier sent an unexpected payment page."), code="bad_request")
        self.with_context(payment_safe_write=True).write({
            "kashier_cf_session_id": session["_id"],
            "kashier_cf_redirect_url": session_url if saved_card else False,
        })
        return session_url

    def _kashier_cf_session_payload(self, saved_card=False):
        self.ensure_one()
        provider = self.provider_id.sudo()
        order_ref = self._kashier_cf_ensure_order_ref()
        expire_at = datetime.now(UTC) + timedelta(minutes=provider.kashier_cf_session_expiry)
        payload = {
            "expireAt": expire_at.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "maxFailureAttempts": provider.kashier_cf_max_attempts,
            "failureRedirect": False,
            "amount": kashier_utils.format_amount(self.amount),
            "currency": self.currency_id.name,
            "order": order_ref,
            "merchantId": provider.kashier_cf_merchant_id,
            "merchantRedirect": self._kashier_cf_route_url(KashierController._return_url),
            "serverWebhook": provider._kashier_cf_url(KashierController._webhook_url),
            "type": "one-time",
            "display": "ar" if (self.partner_lang or "").startswith("ar") else "en",
            "customer": self._kashier_cf_customer(for_cards=self.tokenize or saved_card),
            "description": self.reference[:120],
            "interactionSource": "ECOMMERCE",
        }
        method = self._kashier_cf_primary_method()
        if method.code in const.CARD_METHOD_CODES or saved_card:
            payload["allowedMethods"] = "card"
            if provider.capture_manually:
                payload["manualCapture"] = True
        elif provider.kashier_cf_allowed_methods:
            payload["allowedMethods"] = ",".join(
                part.strip() for part in provider.kashier_cf_allowed_methods.split(",") if part.strip()
            )
        if self.tokenize and method.code in const.CARD_METHOD_CODES:
            payload["saveCard"] = "forced"
        if saved_card:
            payload["retrieveSavedCard"] = True
            payload["saveCard"] = "optional"
            payload["enable3DS"] = True
        return payload

    def _kashier_cf_customer(self, for_cards):
        """The `customer` of a session: a reference (required by Kashier) and the email when known.

        Cards are saved under a reference of the partner, so that their saved cards show on Kashier's
        page; other payments use a reference of the transaction only.
        """
        self.ensure_one()
        if for_cards:
            reference = self.token_id.kashier_cf_customer_reference or self._kashier_cf_partner_reference()
        else:
            reference = f"cf-g-{self._kashier_cf_ensure_order_ref()}"[:64]
        customer = {"reference": reference}
        if self.partner_email:
            customer["email"] = self.partner_email
        return customer

    def _kashier_cf_partner_reference(self):
        self.ensure_one()
        digest = odoo_hmac(self.env(su=True), "payment_kashier_cf-customer", str(self.partner_id.commercial_partner_id.id))
        return f"cf-{digest[:24]}"

    def _kashier_cf_charge_saved_card(self):
        """Charge a saved card while the customer is away (recurring payment, no security code)."""
        self.ensure_one()
        provider = self.provider_id.sudo()
        token = self.token_id.sudo()
        brand = (token.payment_method_id.code or "").lower()
        if brand in const.MIT_REFUSED_BRANDS:
            raise ValidationError(provider._kashier_cf_get_error_message("MEEZA_NOT_ALLOWED"))
        order_ref = self._kashier_cf_ensure_order_ref()
        amount = kashier_utils.format_amount(self.amount)
        currency = self.currency_id.name
        customer_reference = token.kashier_cf_customer_reference
        body = {
            "apiOperation": "PAY",
            "paymentMethod": {"type": "CARD", "card": {"cardToken": token.provider_ref, "enable3DS": False}},
            "order": {"reference": order_ref, "amount": amount, "currency": currency,
                      "description": self.reference[:120]},
            "customer": {"reference": customer_reference},
            "interactionSource": "RECURRING",
            "merchantId": provider.kashier_cf_merchant_id,
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        }
        signature = provider._kashier_cf_hash(kashier_utils.order_hash_string(
            provider.kashier_cf_merchant_id, order_ref, amount, currency, customer_reference,
        ))
        try:
            answer = provider._kashier_cf_client().pay_with_token(body, kashier_hash=signature, reference=self.reference)
        except KashierError as error:
            if error.unknown_outcome:
                self._kashier_cf_mark_unknown(error)
                return
            self._kashier_cf_store_error(error)
            raise
        response = answer.get("response") or {}
        if response.get("status") == "AUTHENTICATION_INITIATED":
            raise ValidationError(self.env._(
                "The bank asks the customer to confirm this payment. Ask the customer to pay online with "
                "the card.",
            ))
        if response.get("orderId"):
            self.with_context(payment_safe_write=True).kashier_cf_order_id = response["orderId"]
        self._kashier_cf_sync_from_provider()

    # === BUSINESS METHODS - REFUND, CAPTURE, VOID === #

    def _create_child_transaction(self, amount, is_refund=False, **custom_create_values):
        """Override of `payment` to keep Kashier's order on the child, and to leave out a deleted card
        (a child can't be created with an archived token).
        """
        if self.provider_code == const.PROVIDER_CODE:
            root = self._kashier_cf_root()
            custom_create_values.setdefault("kashier_cf_order_id", root.kashier_cf_order_id)
            if self.token_id and not self.token_id.active:
                custom_create_values["token_id"] = False
        return super()._create_child_transaction(amount, is_refund=is_refund, **custom_create_values)

    def _send_refund_request(self):
        """Override of `payment` to refund through Kashier (the refund child is self)."""
        if self.provider_code != const.PROVIDER_CODE:
            return super()._send_refund_request()
        transaction = {"amount": abs(self.amount)}
        target = self.source_transaction_id._kashier_cf_refund_target()
        if target:
            transaction["targetTransactionId"] = target
        self._kashier_cf_update_order("refund", {"apiOperation": "REFUND", "reason": self.reference, "transaction": transaction})
        return None

    def _send_capture_request(self):
        """Override of `payment` to capture an authorized payment through Kashier (self is the child)."""
        if self.provider_code != const.PROVIDER_CODE:
            return super()._send_capture_request()
        self._kashier_cf_update_order("capture", {"apiOperation": "CAPTURE", "transaction": {"amount": abs(self.amount)}})
        return None

    def _send_void_request(self):
        """Override of `payment` to release an authorization through Kashier (self is the child)."""
        if self.provider_code != const.PROVIDER_CODE:
            return super()._send_void_request()
        transaction = {"amount": abs(self.amount)}
        if self.source_transaction_id.kashier_cf_transaction_id:
            transaction["targetTransactionId"] = self.source_transaction_id.kashier_cf_transaction_id
        self._kashier_cf_update_order("void", {"apiOperation": "VOID", "transaction": transaction})
        return None

    def _kashier_cf_update_order(self, operation, body):
        """Send a refund, capture or void of the root's Kashier order; self is the child transaction."""
        self.ensure_one()
        self.with_context(payment_safe_write=True).kashier_cf_operation = operation
        root = self._kashier_cf_root()
        order_id = self.kashier_cf_order_id or root.kashier_cf_order_id
        if not order_id:
            raise ValidationError(self.env._("Kashier hasn't confirmed this payment yet: check its status first."))
        try:
            answer = self.provider_id.sudo()._kashier_cf_client().update_order(order_id, body, reference=self.reference)
        except KashierError as error:
            if error.unknown_outcome:
                self._kashier_cf_mark_unknown(error)
                return
            self._kashier_cf_store_error(error)
            raise
        # Money has moved at Kashier: from here on, only the child (created in this transaction) is
        # written. Touching the root, which notifications and the processing cron also update, could
        # end this transaction in a serialization failure, roll the child back and get the request
        # replayed, i.e. the operation sent twice. The root is reconciled later by the notification
        # Kashier sends and by the cron.
        response = answer.get("response") or {}
        transaction_id = response.get("transactionId")
        values = {"kashier_cf_order_id": order_id}
        if transaction_id:
            values["kashier_cf_transaction_id"] = transaction_id
        self.with_context(payment_safe_write=True).write(values)
        status = str(answer.get("status") or "").upper()
        leg_status = {"SUCCESS": const.LEG_SUCCESS, "FAILURE": const.LEG_FAILURE}.get(status, "PENDING")
        self._record({const.SNAPSHOT_KEY: 1, "reference": self.reference, "child_leg": {
            "op": {"capture": const.LEG_CAPTURE, "refund": const.LEG_REFUND, "void": const.LEG_VOID}[operation],
            "status": leg_status,
            "tx_id": transaction_id,
            "amount": abs(self.amount),
            "code": response.get("transactionResponseCode"),
            "message": kashier_utils.message_of(answer) if leg_status == const.LEG_FAILURE else None,
        }})

    # === BUSINESS METHODS - SYNC === #

    def _kashier_cf_sync_from_provider(self):
        """Ask Kashier (with the Secret Key) for the session and the orders of the payment, and record
        what it answered on the root transaction and on each child with an operation.

        Inbound redirects and notifications only call this: their own data are never trusted (Kashier's
        session documents give away the key that signs them).

        :return: Whether Kashier answered.
        :rtype: bool
        """
        root = self._kashier_cf_root()
        provider = root.provider_id.sudo()
        if not (provider.kashier_cf_secret_key and provider.kashier_cf_merchant_id):
            return False
        root.with_context(payment_safe_write=True).kashier_cf_last_sync = fields.Datetime.now()
        client = provider._kashier_cf_client()
        merchant_id = provider.kashier_cf_merchant_id
        session = None
        try:
            if root.kashier_cf_session_id:
                data = (client.get_payment_session(root.kashier_cf_session_id, reference=root.reference) or {}).get("data") or {}
                if data.get("merchantOrderId") == root.kashier_cf_order_ref and data.get("merchantId") == merchant_id:
                    session = {
                        "id": data.get("sessionId"),
                        "status": data.get("status"),
                        "amount": kashier_utils.to_number(data.get("amount")),
                        "currency": data.get("currency"),
                        "order_id": data.get("orderId") if data.get("orderId") not in (None, "NA") else None,
                    }
                elif data:
                    _logger.warning("Kashier session of %s belongs to another order; ignored.", root.reference)
            orders = []
            if root.kashier_cf_order_ref:
                answer = client.search_orders(search=root.kashier_cf_order_ref, limit=50, reference=root.reference) or {}
                orders = [
                    root._kashier_cf_order_snapshot(order) for order in answer.get("data") or []
                    if order.get("merchantOrderId") == root.kashier_cf_order_ref
                    and order.get("merchantId") in (merchant_id, None)
                ]
        except KashierError as error:
            _logger.warning("Kashier status check of %s failed: %s", root.reference, error)
            return False
        if session is None and not orders:
            return True
        root._record({const.SNAPSHOT_KEY: 1, "reference": root.reference, "session": session, "orders": orders})
        root._kashier_cf_dispatch_legs(orders)
        return True

    def _kashier_cf_order_snapshot(self, order):
        """The JSON-safe part of a Kashier order this module uses."""
        card = ((order.get("sourceOfFunds") or {}).get("cardInfo")) or {}
        legs = [{
            "op": leg.get("operation"),
            "status": leg.get("status"),
            "tx_id": leg.get("transactionId"),
            "amount": kashier_utils.to_number(leg.get("amount")),
            "code": leg.get("transactionResponseCode"),
            "message": ((leg.get("transactionResponseMessage") or {}).get("en") if isinstance(
                leg.get("transactionResponseMessage"), dict) else leg.get("transactionResponseMessage")),
        } for leg in order.get("transactions") or []]
        snapshot_card = {
            "brand": card.get("cardBrand"),
            "masked": card.get("maskedCard"),
            "expiry_month": card.get("expiryMonth"),
            "expiry_year": card.get("expiryYear"),
        }
        if self.tokenize and card.get("cardDataToken"):
            snapshot_card["token"] = card["cardDataToken"]
        base = order.get("order") or {}
        return {
            "order_id": order.get("orderId"),
            "session_id": order.get("sessionId"),
            "status": order.get("status"),
            "amount": kashier_utils.to_number(base.get("amount")),
            "currency": base.get("currency"),
            "captured": kashier_utils.to_number(order.get("totalCapturedAmount")) or 0.0,
            "refunded": kashier_utils.to_number(order.get("totalRefundedAmount")) or 0.0,
            "authorized": kashier_utils.to_number(order.get("totalAuthorizedAmount")) or 0.0,
            "method": order.get("method"),
            "card": snapshot_card,
            "legs": legs,
        }

    def _kashier_cf_dispatch_legs(self, orders):
        """Record the capture, refund and void legs on their child transactions; note the refunds made
        in Kashier's dashboard.
        """
        self.ensure_one()
        children = self._kashier_cf_descendants()
        claimed = set(children.mapped("kashier_cf_transaction_id")) - {False}
        operation_of_leg = {const.LEG_CAPTURE: "capture", const.LEG_REFUND: "refund", const.LEG_VOID: "void"}
        unclaimed_refunds = []
        for order in orders:
            for leg in order["legs"]:
                if leg["op"] not in operation_of_leg or not leg["tx_id"]:
                    continue
                child = children.filtered(lambda tx, leg=leg: tx.kashier_cf_transaction_id == leg["tx_id"])
                if not child:
                    child = children.filtered(lambda tx, leg=leg: (
                        tx.kashier_cf_outcome_unknown and not tx.kashier_cf_transaction_id
                        and tx._kashier_cf_operation() == operation_of_leg[leg["op"]]
                        and self.currency_id.compare_amounts(abs(tx.amount), leg["amount"] or 0.0) == 0
                    ))[:1]
                    if child:
                        child.with_context(payment_safe_write=True).kashier_cf_transaction_id = leg["tx_id"]
                        claimed.add(leg["tx_id"])
                if child:
                    child._record({const.SNAPSHOT_KEY: 1, "reference": child.reference, "child_leg": leg})
                elif leg["op"] == const.LEG_REFUND and leg["status"] == const.LEG_SUCCESS:
                    unclaimed_refunds.append(leg)
        noted = set((self.kashier_cf_noted_legs or "").split(",")) - {""}
        for leg in unclaimed_refunds:
            if leg["tx_id"] in noted:
                continue
            noted.add(leg["tx_id"])
            self._kashier_cf_note_documents(self.env._(
                "Kashier refunded %(amount)s of this payment outside Odoo (Kashier transaction %(tx)s). "
                "Record the refund in Odoo if it isn't yet.",
                amount=leg["amount"], tx=leg["tx_id"],
            ))
        if noted != set((self.kashier_cf_noted_legs or "").split(",")) - {""}:
            self.with_context(payment_safe_write=True).kashier_cf_noted_legs = ",".join(sorted(noted))

    # === BUSINESS METHODS - PROCESSING === #

    def _apply_updates(self, payment_data):
        """Override of `payment` to update the transaction from Kashier's authenticated answers."""
        if self.provider_code != const.PROVIDER_CODE:
            return super()._apply_updates(payment_data)
        if not payment_data.get(const.SNAPSHOT_KEY):
            _logger.warning("Ignored Kashier data without the snapshot marker for %s.", self.reference)
            return None
        if "child_leg" in payment_data:
            return self._kashier_cf_apply_child_leg(payment_data["child_leg"])
        return self._kashier_cf_apply_snapshot(payment_data.get("session") or {}, payment_data.get("orders") or [])

    def _extract_amount_data(self, payment_data):
        """Override of `payment` to skip core's amount check: `_kashier_cf_apply_snapshot` checks the
        amount and the currency before any state change (core can't put a cancelled payment in error).
        """
        if self.provider_code != const.PROVIDER_CODE:
            return super()._extract_amount_data(payment_data)
        return None

    def _extract_token_values(self, payment_data):
        """Override of `payment` to save the card Kashier tokenized during the paid checkout."""
        if self.provider_code != const.PROVIDER_CODE:
            return super()._extract_token_values(payment_data)
        for order in payment_data.get("orders") or []:
            card = order.get("card") or {}
            if order.get("status") in const.ORDER_PAID | const.ORDER_AUTHORIZED and card.get("token") \
                    and self._kashier_cf_is_card_order(order):
                expiry = ""
                if card.get("expiry_month") and card.get("expiry_year"):
                    expiry = f"{str(card['expiry_month']).zfill(2)}/{str(card['expiry_year'])[-2:]}"
                return {
                    "provider_ref": card["token"],
                    "payment_details": (card.get("masked") or "")[-4:],
                    "kashier_cf_customer_reference": self._kashier_cf_partner_reference(),
                    "kashier_cf_expiry": expiry,
                    "kashier_cf_is_live": self.provider_id.is_live,
                }
        return {}

    def _kashier_cf_apply_snapshot(self, session, orders):
        """Map Kashier's session and orders to the state of the root transaction (see the README)."""
        status = session.get("status")
        session_final = status in const.SESSION_FINAL
        paid = [order for order in orders if order["status"] in const.ORDER_PAID and self._kashier_cf_leg(order, (const.LEG_PAY, const.LEG_CAPTURE), const.LEG_SUCCESS)]
        authorized = [order for order in orders if order["status"] in const.ORDER_AUTHORIZED and self._kashier_cf_leg(order, (const.LEG_AUTHORIZE,), const.LEG_SUCCESS)]
        capture_children = self.child_transaction_ids.filtered(lambda tx: tx._kashier_cf_operation() == "capture")
        void_children = self.child_transaction_ids.filtered(lambda tx: tx._kashier_cf_operation() == "void")

        if paid:
            if self.state == "authorized" and capture_children:
                return None  # Core moves the source when the capture child is done.
            matching = [order for order in paid if self._kashier_cf_amount_ok(order)]
            if not matching:
                self._kashier_cf_alert("amount", self.env._(
                    "Kashier confirmed a payment whose amount or currency differs from this payment. Check "
                    "the order in Kashier's dashboard.",
                ))
                return self._kashier_cf_set_error_text(self.env._("The amount paid at Kashier doesn't match."))
            if len(paid) > 1:
                self._kashier_cf_alert("several_paid", self.env._(
                    "Kashier has several paid orders for this payment: %(orders)s. Refund the extra ones.",
                    orders=", ".join(order["order_id"] or "?" for order in paid),
                ))
            return self._kashier_cf_set_success(matching[0], authorized=False)
        if authorized:
            matching = [order for order in authorized if self._kashier_cf_amount_ok(order)]
            if matching:
                return self._kashier_cf_set_success(matching[0], authorized=True)
        if status in const.SESSION_PAID | const.SESSION_AUTHORIZED:
            return self._kashier_cf_set_state("pending")  # The order isn't listed yet.
        released = [order for order in orders if order["status"] in const.ORDER_RELEASED] or status in const.SESSION_RELEASED
        if released:
            if self.state == "done":
                self._kashier_cf_alert("released_after_done", self.env._(
                    "Kashier reversed or cancelled this payment after it was confirmed. Check the order in "
                    "Kashier's dashboard and refund or cancel the documents.",
                ))
                return None
            if self.state == "authorized" and void_children:
                return None  # Core moves the source when the void child is done.
            return self._kashier_cf_set_state("cancel", self.env._("The payment was cancelled at Kashier."))
        undetermined_money_leg = any(
            leg["op"] in const.MONEY_LEGS and (
                leg["status"] in const.LEG_UNDETERMINED
                # Kashier keeps the code of an unknown outcome on the leg it later decides.
                or (leg["code"] in const.UNDETERMINED_CODES and leg["status"] not in (const.LEG_SUCCESS, const.LEG_FAILURE))
            )
            for order in orders for leg in order["legs"]
        ) or any(order["status"] in const.ORDER_INITIATED and order["legs"] and not all(
            leg["op"] in const.LEGS_3DS for leg in order["legs"]) for order in orders)
        if not session_final:
            if orders and all(order["status"] in const.ORDER_FAILED for order in orders) and status in ("OPENED", "PENDING"):
                return None  # The customer can still try again on Kashier's page.
            if undetermined_money_leg or any(order["status"] in const.ORDER_INITIATED for order in orders) \
                    or status == "PENDING":
                return self._kashier_cf_set_state("pending")
            if not session and not orders:
                return None
            if not session:  # A saved card charged without the customer: no session.
                failed = [order for order in orders if order["status"] in const.ORDER_FAILED]
                if failed and len(failed) == len(orders):
                    return self._kashier_cf_set_failure(failed)
                return self._kashier_cf_set_state("pending")
            return None  # CREATED / OPENED: the customer is on Kashier's page.
        if undetermined_money_leg:
            self._kashier_cf_alert("undetermined", self.env._(
                "Kashier hasn't decided the outcome of this payment. Check the order in Kashier's dashboard "
                "before asking the customer to pay again.",
            ))
            return self._kashier_cf_set_state("pending")
        if status in const.SESSION_FAILED or (orders and all(order["status"] in const.ORDER_FAILED for order in orders)):
            return self._kashier_cf_set_failure([order for order in orders if order["status"] in const.ORDER_FAILED])
        # EXPIRED / ABANDONED, nothing paid: the customer left (also after leaving 3-D Secure).
        late = max(fields.Datetime.now(), self.create_date or fields.Datetime.now()) + timedelta(hours=const.LATE_CHECK_HOURS)
        self.with_context(payment_safe_write=True).kashier_cf_late_check_until = late
        return self._kashier_cf_set_state("cancel", self.env._("The payment page expired before the payment."))

    def _kashier_cf_apply_child_leg(self, leg):
        """Map a capture, refund or void leg to the state of its child transaction."""
        if self.currency_id.compare_amounts(abs(self.amount), leg.get("amount") or 0.0) != 0:
            self._kashier_cf_alert("amount", self.env._("Kashier's operation amount differs from this transaction."))
            return self._kashier_cf_set_error_text(self.env._("The amount of Kashier's operation doesn't match."))
        values = {"kashier_cf_outcome_unknown": False}
        if leg.get("tx_id") and not self.kashier_cf_transaction_id:
            values["kashier_cf_transaction_id"] = leg["tx_id"]
        self.with_context(payment_safe_write=True).write(values)
        status = leg.get("status")
        if status == const.LEG_SUCCESS:
            if self._kashier_cf_operation() == "void":
                return self._kashier_cf_set_state("cancel", self.env._("The authorization was released."))
            if not self.provider_reference:
                self.provider_reference = leg.get("tx_id")
            return self._kashier_cf_set_state("done")
        if status == const.LEG_FAILURE:
            self.write({"kashier_cf_error_code": leg.get("code") or False, "kashier_cf_error_details": leg.get("message") or False})
            return self._kashier_cf_set_error_text(
                self.provider_id._kashier_cf_get_error_message(leg.get("code"), leg.get("message")),
            )
        return self._kashier_cf_set_state("pending")

    def _kashier_cf_set_success(self, order, authorized):
        money_leg = self._kashier_cf_leg(order, (const.LEG_AUTHORIZE,) if authorized else (const.LEG_PAY, const.LEG_AUTHORIZE, const.LEG_CAPTURE), const.LEG_SUCCESS)
        values = {
            "kashier_cf_order_id": order["order_id"],
            "kashier_cf_channel": self._kashier_cf_channel_label(order),
            "kashier_cf_outcome_unknown": False,
            "kashier_cf_late_check_until": False,
        }
        if money_leg and not self.kashier_cf_transaction_id:
            values["kashier_cf_transaction_id"] = money_leg["tx_id"]
            values["provider_reference"] = money_leg["tx_id"]
        payment_method = self._kashier_cf_payment_method(order)
        if payment_method:
            values["payment_method_id"] = payment_method.id
        self.write(values)
        if self.state in ("cancel", "error") and self.operation == "offline":
            # account_payment cancelled the payment it posted before charging: staff register it again.
            self._kashier_cf_alert("late_offline_success", self.env._(
                "Kashier charged the saved card after this payment was marked failed. Register the payment "
                "of %(amount)s by hand.", amount=order.get("amount"),
            ))
            return None
        if self.state in ("cancel", "error"):
            self._kashier_cf_note_documents(self.env._("Kashier confirmed a late payment of this transaction."))
        state = "authorized" if authorized else "done"
        return self._kashier_cf_set_state(state, extra_allowed_states=("cancel", "error"))

    def _kashier_cf_set_failure(self, failed_orders):
        leg = None
        for order in failed_orders:
            for candidate in order["legs"]:
                if candidate["op"] in const.MONEY_LEGS | const.LEGS_3DS and candidate["status"] == const.LEG_FAILURE:
                    leg = candidate
        code = leg and leg.get("code")
        self.write({"kashier_cf_error_code": code or False, "kashier_cf_error_details": (leg and leg.get("message")) or False})
        # A decided failure that kept the code of an unknown outcome: the generic decline message.
        customer_code = None if code in const.UNDETERMINED_CODES else code
        return self._kashier_cf_set_error_text(self.provider_id._kashier_cf_get_customer_error_message(customer_code))

    def _kashier_cf_set_state(self, state, message=None, extra_allowed_states=()):
        if state == "pending":
            # Core moves only draft payments to pending; a later state stays as it is.
            if self.state == "draft" or self.state in extra_allowed_states:
                self._set_pending(state_message=message, extra_allowed_states=extra_allowed_states)
        elif state == "authorized":
            self._set_authorized(state_message=message, extra_allowed_states=extra_allowed_states)
        elif state == "done":
            self._set_done(state_message=message, extra_allowed_states=extra_allowed_states)
        elif state == "cancel":
            self._set_canceled(message, extra_allowed_states=extra_allowed_states)

    def _kashier_cf_set_error_text(self, message):
        self._set_error(message)

    # === BUSINESS METHODS - ERRORS === #

    def _kashier_cf_set_error(self, error):
        """Put the transaction in error: Kashier's details for the staff, the customer's message as state."""
        self._kashier_cf_store_error(error)
        code = getattr(error, "code", None)
        self.with_context(payment_safe_write=True)._set_error(self.provider_id._kashier_cf_get_customer_error_message(code))

    def _kashier_cf_store_error(self, error):
        self.with_context(payment_safe_write=True).write({
            "kashier_cf_error_code": getattr(error, "code", None) or False,
            "kashier_cf_error_details": str(error),
        })

    def _kashier_cf_mark_unknown(self, error):
        """Kashier didn't answer a request that moves money: wait for its answer, never resend."""
        tx = self.with_context(payment_safe_write=True)
        tx.write({
            "kashier_cf_outcome_unknown": True,
            "kashier_cf_error_code": getattr(error, "code", None) or False,
            "kashier_cf_error_details": str(error),
        })
        if tx.state == "draft":
            tx._set_pending(state_message=self.env._("Waiting for Kashier's answer."))
        self.env.ref("payment_kashier_cf.cron_sync_payments")._trigger(fields.Datetime.now() + timedelta(minutes=2))

    def _kashier_cf_alert(self, kind, message):
        """Tell the staff, once per payment and kind of problem: a note on the documents of the
        payment, and an activity for the person responsible for the first one.
        """
        sent = set((self.kashier_cf_alerted or "").split(",")) - {""}
        if kind in sent:
            return
        self.with_context(payment_safe_write=True).kashier_cf_alerted = ",".join(sorted(sent | {kind}))
        self._kashier_cf_note_documents(message)
        for document in self._kashier_cf_documents()[:1]:
            document = document.sudo()
            user = document.user_id if "user_id" in document._fields else False
            if not user and "invoice_user_id" in document._fields:
                user = document.invoice_user_id
            if user:
                document.activity_schedule(
                    "mail.mail_activity_data_todo",
                    summary=self.env._("Check the Kashier payment %(ref)s", ref=self.reference),
                    note=message,
                    user_id=user.id,
                )

    def _kashier_cf_note_documents(self, message):
        self._log_message_on_linked_documents(Markup("%s %s") % (message, self.env._("(%(ref)s)", ref=self.reference)))

    def _kashier_cf_documents(self):
        documents = []
        if "sale_order_ids" in self._fields:
            documents += list(self.sale_order_ids)
        documents += list(self.invoice_ids)
        return documents

    # === BUSINESS METHODS - CRON AND ACTIONS === #

    @api.model
    def _cron_kashier_cf_sync(self):
        """Ask Kashier for the status of unfinished payments, in case a notification was missed."""
        now = fields.Datetime.now()
        txs = self.search(
            Domain("provider_code", "=", const.PROVIDER_CODE)
            & (
                Domain("state", "=", "draft") & Domain("kashier_cf_session_id", "!=", False)
                & Domain("create_date", ">=", now - timedelta(days=2))
                | Domain("state", "=", "pending") & Domain("create_date", ">=", now - timedelta(days=10))
                | Domain("state", "=", "authorized") & Domain("create_date", ">=", now - timedelta(days=32))
                | Domain("state", "=", "cancel") & Domain("kashier_cf_late_check_until", ">", now)
                | Domain("kashier_cf_outcome_unknown", "=", True)
            ),
            order="kashier_cf_last_sync asc nulls first, id asc",
            limit=200,
        )
        in_cron = bool(self.env.context.get("ir_cron_progress_id"))
        if in_cron:
            self.env["ir.cron"]._commit_progress(remaining=len(txs))
        done_roots = set()
        for tx in txs:
            root = tx._kashier_cf_root()
            if root.id not in done_roots:
                done_roots.add(root.id)
                root._kashier_cf_sync_from_provider()
            tx._kashier_cf_expire_unknown_outcome(now)
            if in_cron and not self.env["ir.cron"]._commit_progress(1):
                break

    def _kashier_cf_expire_unknown_outcome(self, now):
        """After the waiting delay without Kashier's answer, put the operation in error for the staff."""
        if not self.kashier_cf_outcome_unknown or self.state not in ("draft", "pending"):
            return
        if self.create_date and self.create_date > now - timedelta(hours=const.UNKNOWN_OUTCOME_HOURS):
            return
        if self.env["payment.data"].sudo().search_count(
            [("transaction_id", "=", self.id), ("errored", "=", False)], limit=1,
        ):
            return  # Kashier's answer was just found and waits for processing.
        self.with_context(payment_safe_write=True).write({"kashier_cf_outcome_unknown": False})
        self.with_context(payment_safe_write=True)._set_error(self.env._(
            "Kashier didn't confirm this operation. Check it in Kashier's dashboard before trying again.",
        ))

    def action_kashier_cf_sync(self):
        """Fetch the latest status of the payment from Kashier."""
        self.ensure_one()
        payment_utils.check_rights_on_recordset(self)
        if not self.sudo()._kashier_cf_sync_from_provider():
            raise UserError(self.env._("Kashier didn't answer. Try again in a moment."))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": self.env._("Kashier sent the latest status. The payment is updated within a few "
                                      "seconds; reload the page to see it."),
                "sticky": False,
            },
        }

    # === BUSINESS METHODS - HELPERS === #

    def _kashier_cf_descendants(self):
        """The children of this payment and theirs (a refund of a capture is a grandchild)."""
        self.ensure_one()
        descendants = self.env["payment.transaction"]
        children = self.child_transaction_ids
        while children - descendants:
            descendants |= children
            children = children.child_transaction_ids
        return descendants.filtered(lambda tx: tx.provider_code == const.PROVIDER_CODE)

    def _kashier_cf_refund_target(self):
        """The Kashier transaction a refund of this payment applies to: the capture of a payment
        captured later, otherwise the payment itself.
        """
        self.ensure_one()
        captures = self.child_transaction_ids.filtered(
            lambda tx: tx._kashier_cf_operation() == "capture" and tx.state == "done" and tx.kashier_cf_transaction_id,
        )
        return captures[:1].kashier_cf_transaction_id or self.kashier_cf_transaction_id

    def _kashier_cf_root(self):
        """The payment transaction at the origin of this one (itself, or the source of a child)."""
        self.ensure_one()
        root = self
        while root.source_transaction_id:
            root = root.source_transaction_id
        return root

    def _kashier_cf_operation(self):
        """capture, refund or void for a child transaction sent to Kashier; False otherwise."""
        self.ensure_one()
        if self.kashier_cf_operation:
            return self.kashier_cf_operation
        return "refund" if self.operation == "refund" and self.source_transaction_id else False

    def _kashier_cf_ensure_order_ref(self):
        """The order reference sent to Kashier, created once per transaction."""
        self.ensure_one()
        if not self.kashier_cf_order_ref:
            uuid = self.env["ir.config_parameter"].sudo().get_str("database.uuid") or self.env.cr.dbname
            database_code = hashlib.sha1(uuid.encode()).hexdigest()[:6]  # noqa: S324 (not security)
            order_ref = kashier_utils.build_order_reference(self.reference, database_code, secrets.token_hex(2))
            self.with_context(payment_safe_write=True).kashier_cf_order_ref = order_ref
        return self.kashier_cf_order_ref

    def _kashier_cf_route_url(self, route):
        self.ensure_one()
        token = payment_utils.generate_access_token(self.reference, self.partner_id.id, env=self.env)
        return self.provider_id._kashier_cf_url(f"{route}/{self.id}/{token}")

    def _kashier_cf_primary_method(self):
        self.ensure_one()
        return self.payment_method_id.primary_payment_method_id or self.payment_method_id

    @staticmethod
    def _kashier_cf_leg(order, operations, status):
        legs = [leg for leg in order["legs"] if leg["op"] in operations and leg["status"] == status]
        return legs[-1] if legs else None

    def _kashier_cf_amount_ok(self, order):
        amount = order.get("amount")
        if amount is None or (order.get("currency") or self.currency_id.name) != self.currency_id.name:
            return False
        return self.currency_id.compare_amounts(amount, self.amount) == 0

    @staticmethod
    def _kashier_cf_is_card_order(order):
        return (order.get("method") or "card").lower() in ("card", "applepay", "apple_pay")

    def _kashier_cf_channel_label(self, order):
        method = (order.get("method") or "").lower()
        brand = ((order.get("card") or {}).get("brand") or "").strip()
        if self._kashier_cf_is_card_order(order):
            return f"{brand or 'Card'} {(order.get('card') or {}).get('masked') or ''}".strip()
        return method or False

    def _kashier_cf_payment_method(self, order):
        """The Odoo payment method Kashier actually used: the card brand, or the Kashier method."""
        provider = self.provider_id.with_context(active_test=False)
        if self._kashier_cf_is_card_order(order):
            brand = ((order.get("card") or {}).get("brand") or "").lower()
            code = const.CARD_BRAND_MAPPING.get(brand) or "card"
            return provider._get_pm_from_code(code) or provider._get_pm_from_code("card")
        return provider._get_pm_from_code(const.PROVIDER_WIDE_METHOD_CODE)
