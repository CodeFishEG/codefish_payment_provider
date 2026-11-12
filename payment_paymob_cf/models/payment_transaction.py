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
import re
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import urls

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_paymob_cf import const
from odoo.addons.payment_paymob_cf import utils as paymob_utils
from odoo.addons.payment_paymob_cf.controllers.main import PaymobController
from odoo.addons.payment_paymob_cf.exceptions import PaymobError

_logger = get_payment_logger(__name__, const.SENSITIVE_KEYS)


class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    paymob_cf_special_reference = fields.Char(
        string="Paymob Reference",
        help="The unique reference of the payment at Paymob (special reference).",
        readonly=True,
        copy=False,
    )
    paymob_cf_intention_id = fields.Char(
        string="Paymob Intention", readonly=True, copy=False,
    )
    paymob_cf_order_id = fields.Char(
        string="Paymob Order ID",
        help="The order Paymob created for the payment. Paymob signs it in its notifications.",
        readonly=True,
        copy=False,
        index="btree_not_null",
    )
    paymob_cf_client_secret = fields.Char(readonly=True, copy=False, groups="base.group_system")
    paymob_cf_integration_ids = fields.Char(
        string="Paymob Integrations",
        help="The Paymob integrations the customer could pay with.",
        readonly=True,
        copy=False,
    )
    paymob_cf_redirect_url = fields.Char(
        help="Where the customer confirms a payment with a saved card.", readonly=True, copy=False,
    )
    paymob_cf_payment_source = fields.Char(
        string="Paid With",
        help="The card (brand and last digits) or the wallet the customer paid with.",
        readonly=True,
        copy=False,
    )
    paymob_cf_bill_reference = fields.Char(
        string="Kiosk Reference",
        help="The reference the customer pays in cash at a kiosk.",
        readonly=True,
        copy=False,
    )
    paymob_cf_installment = fields.Char(
        string="Installment Plan",
        help="The number of months, when the customer paid in installments.",
        readonly=True,
        copy=False,
    )
    paymob_cf_card_token = fields.Char(readonly=True, copy=False, groups="base.group_system")
    paymob_cf_card_data = fields.Json(readonly=True, copy=False)
    paymob_cf_last_sync = fields.Datetime(string="Last Paymob Status Check", readonly=True)
    paymob_cf_error_code = fields.Char(
        string="Paymob Error Code",
        help="The code of the last error Paymob returned for this payment.",
        readonly=True,
    )
    paymob_cf_error_details = fields.Char(
        string="Paymob Error Details",
        help="The message of the error, as Paymob sent it.",
        readonly=True,
    )
    paymob_cf_error_explanation = fields.Char(
        string="Paymob Error",
        help="What the error returned by Paymob means.",
        compute="_compute_paymob_cf_error_explanation",
    )

    # === COMPUTE METHODS === #

    @api.depends("paymob_cf_error_code", "paymob_cf_error_details")
    def _compute_paymob_cf_error_explanation(self):
        for tx in self:
            tx.paymob_cf_error_explanation = (
                tx.paymob_cf_error_code or tx.paymob_cf_error_details
            ) and tx.provider_id._paymob_cf_get_error_message(
                tx.paymob_cf_error_code, tx.paymob_cf_error_details,
            )

    # === BUSINESS METHODS - PAYMENT FLOW === #

    def _get_specific_processing_values(self, processing_values):
        """Override of `payment` to return the values the payment form needs for Paymob.

        Note: self.ensure_one() from `_get_processing_values`

        :param dict processing_values: The generic processing values of the transaction.
        :return: The provider-specific processing values.
        :rtype: dict
        """
        res = super()._get_specific_processing_values(processing_values)
        if self.provider_code != "paymob_cf":
            return res

        if self.operation == "online_token":
            if self.state in ("draft", "pending") and self.paymob_cf_redirect_url:
                res["paymob_cf_redirect_url"] = self.paymob_cf_redirect_url
            return res
        if self.operation not in ("online_direct", "validation"):
            return res

        flow = self.provider_id._paymob_cf_get_flow(self._paymob_cf_get_method().code)
        try:
            if flow == const.FLOW_PIXEL or self.operation == "validation":
                res["paymob_cf_pixel"] = self._paymob_cf_prepare_pixel_values()
            else:
                res["paymob_cf_checkout"] = self._paymob_cf_prepare_checkout_values()
        except ValidationError as error:
            self._paymob_cf_set_error(error)
            res["paymob_cf_error"] = self.state_message
        return res

    def _get_specific_rendering_values(self, processing_values):
        """Override of `payment` to send the customer to Paymob Checkout in a full page.

        Note: self.ensure_one() from `_get_processing_values`

        :param dict processing_values: The generic and specific processing values.
        :return: The values of `payment.generic_redirect_form`.
        :rtype: dict
        """
        if self.provider_code != "paymob_cf":
            return super()._get_specific_rendering_values(processing_values)

        provider = self.provider_id
        try:
            integration_ids = provider._paymob_cf_get_integration_ids(
                self._paymob_cf_get_method(), capture_manually=provider.capture_manually,
            )
            response = self._paymob_cf_create_intention(integration_ids)
        except ValidationError as error:
            self._paymob_cf_set_error(error)
            # The payment status page explains the error to the customer.
            return {
                "api_url": urls.urljoin(provider.get_base_url(), "/payment/status"),
                "http_method": "get",
                "url_params": {},
            }
        return {
            "api_url": f"{provider._paymob_cf_get_api_url()}{const.ENDPOINT_CHECKOUT}",
            "http_method": "get",
            "url_params": {
                "publicKey": provider.paymob_cf_public_key,
                "clientSecret": response["client_secret"],
            },
        }

    def _paymob_cf_prepare_checkout_values(self):
        """Create the payment intention and return what the payment form needs to show Paymob
        Checkout in a pop-up or a side panel.

        Paymob sends the customer back to a route made for the frame, which takes the whole window
        back to the payment status page. The browser may refuse that navigation (for example a
        public checkout page can't open a website on a private network), so the payment form also
        asks Odoo for the state of the payment while the checkout is open.

        :return: The checkout URL, the display mode and the access token of the payment.
        :rtype: dict
        :raise ValidationError: If Paymob refuses the intention.
        """
        provider = self.provider_id
        integration_ids = provider._paymob_cf_get_integration_ids(
            self._paymob_cf_get_method(), capture_manually=provider.capture_manually,
        )
        response = self._paymob_cf_create_intention(integration_ids, in_frame=True)
        return {
            "checkout_url": provider._paymob_cf_get_checkout_url(response["client_secret"]),
            "display_mode": provider.paymob_cf_display_mode,
            "access_token": self._paymob_cf_get_access_token(),
        }

    def _paymob_cf_prepare_pixel_values(self):
        """Create the payment intention and return what Paymob's embedded card form needs.

        The card is saved by Paymob when the customer asked to save it in the payment form, or
        when the card is saved without paying.

        :return: The keys of the intention, the methods of the form and the completion URL.
        :rtype: dict
        :raise ValidationError: If Paymob refuses the intention.
        """
        provider = self.provider_id
        method = self._paymob_cf_get_method()
        is_validation = self.operation == "validation"
        integration_ids = provider._paymob_cf_get_integration_ids(
            method, capture_manually=provider.capture_manually, is_validation=is_validation,
        )
        response = self._paymob_cf_create_intention(integration_ids)
        return {
            "script_url": const.PIXEL_SCRIPT_URL,
            "public_key": provider.paymob_cf_public_key,
            "client_secret": response["client_secret"],
            "payment_methods": [const.PIXEL_METHODS.get(method.code, "card")],
            "force_save_card": bool(self.tokenize or is_validation),
            "complete_url": self._paymob_cf_get_route_url(PaymobController._complete_url),
        }

    def _paymob_cf_create_intention(self, integration_ids, card_tokens=None, in_frame=False):
        """Create Paymob's payment intention of the transaction.

        :param list integration_ids: The Paymob integrations the customer can pay with.
        :param list card_tokens: The saved cards the customer can pay with.
        :param bool in_frame: Whether Paymob Checkout is shown in a frame of the payment page.
        :return: Paymob's response.
        :rtype: dict
        :raise ValidationError: If Paymob refuses the intention.
        """
        self.ensure_one()
        provider = self.provider_id
        special_reference = self._paymob_cf_get_special_reference()
        amount_cents = self._paymob_cf_to_cents(self.amount)
        items = self._paymob_cf_get_items(amount_cents)
        return_route = PaymobController._frame_return_url if in_frame else PaymobController._return_url
        payload = {
            "amount": amount_cents,
            "currency": self.currency_id.name,
            "payment_methods": integration_ids,
            "items": [
                {key: value for key, value in item.items() if not key.startswith("_")}
                for item in items
            ],
            "billing_data": self._paymob_cf_get_billing_data(),
            "special_reference": special_reference,
            "expiration": provider.paymob_cf_payment_expiry_hours * 3600,
            "notification_url": provider.paymob_cf_webhook_url,
            "redirection_url": self._paymob_cf_get_route_url(return_route),
            "extras": {"reference": self.reference},
        }
        if card_tokens:
            payload["card_tokens"] = card_tokens
        if split_amounts := self._paymob_cf_get_split_amounts(items):
            payload["split_amounts"] = split_amounts
        response = provider._send_api_request(
            "POST", const.ENDPOINT_INTENTION, json=payload, reference=self.reference,
        )
        if not isinstance(response, dict) or not response.get("client_secret"):
            raise ValidationError(self.env._("Paymob didn't return a payment intention."))
        self.with_context(payment_safe_write=True).write({
            "paymob_cf_special_reference": special_reference,
            "paymob_cf_intention_id": response.get("id") or False,
            "paymob_cf_order_id": str(response.get("intention_order_id") or "") or False,
            "paymob_cf_client_secret": response["client_secret"],
            "paymob_cf_integration_ids": ", ".join(str(i) for i in integration_ids),
        })
        return response

    def _send_payment_request(self):
        """Override of `payment` to pay with a saved card.

        While the customer is there, Paymob Checkout opens with the saved card: the customer
        confirms it with the card's security code and their bank (3-D Secure). When the customer
        is away (e.g. subscriptions), the card is charged through the provider's MOTO integration.

        Note: self.ensure_one()

        :raise ValidationError: If the transaction is not linked to a token.
        """
        if self.provider_code != "paymob_cf":
            return super()._send_payment_request()

        if not self.token_id:
            raise ValidationError(self.env._("The transaction is not linked to a token."))
        provider = self.provider_id
        tx = self.with_context(payment_safe_write=True)
        # Errors are raised to `_charge_with_token`, which sets the error and post-processes.
        try:
            if self.operation == "offline":
                if not provider.paymob_cf_moto_integration_id:
                    raise ValidationError(self.env._(
                        "Paymob charges saved cards while the customer is away with a MOTO "
                        "integration. Enter its ID on the Paymob provider.",
                    ))
                integration_ids = provider._paymob_cf_get_integration_ids(
                    self._paymob_cf_get_method(), is_moto=True,
                )
                response = self._paymob_cf_create_intention(integration_ids)
                payment_key = next(
                    (key["key"] for key in response.get("payment_keys") or [] if key.get("key")),
                    None,
                )
                if not payment_key:
                    raise ValidationError(self.env._("Paymob didn't return a payment key."))
                pay_response = provider._send_api_request(
                    "POST",
                    const.ENDPOINT_PAY,
                    json={
                        "source": {"identifier": self.token_id.provider_ref, "subtype": "TOKEN"},
                        "payment_token": payment_key,
                    },
                    reference=self.reference,
                )
                self._record(pay_response)
            else:
                integration_ids = provider._paymob_cf_get_integration_ids(
                    self._paymob_cf_get_method(), capture_manually=provider.capture_manually,
                )
                response = self._paymob_cf_create_intention(
                    integration_ids, card_tokens=[self.token_id.provider_ref],
                )
                tx.paymob_cf_redirect_url = provider._paymob_cf_get_checkout_url(
                    response["client_secret"],
                )
        except PaymobError as error:
            # `_charge_with_token` shows the message to the customer: explain it to them.
            tx.write({
                "paymob_cf_error_code": error.code,
                "paymob_cf_error_details": error.description,
            })
            raise ValidationError(
                provider._paymob_cf_get_customer_error_message(error.code, error.description),
            ) from None
        return None

    def _send_refund_request(self):
        """Override of `payment` to refund a Paymob payment, fully or partially.

        Note: self.ensure_one()
        """
        if self.provider_code != "paymob_cf":
            return super()._send_refund_request()

        source_tx = self.source_transaction_id
        if not source_tx.provider_reference:
            raise ValidationError(self.env._("The payment to refund has no Paymob transaction ID."))
        if source_tx._paymob_cf_get_method().code in const.NON_REFUNDABLE_METHOD_CODES:
            raise ValidationError(self.env._("Paymob can't refund kiosk payments."))
        response = self.provider_id._send_api_request(
            "POST",
            const.ENDPOINT_REFUND,
            json={
                "transaction_id": self._paymob_cf_to_int(source_tx.provider_reference),
                "amount_cents": self._paymob_cf_to_cents(-self.amount),
            },
            reference=self.reference,
        )
        self._record({**response, const.OWN_REQUEST_KEY: "refund"})
        return None

    def _send_capture_request(self):
        """Override of `payment` to capture an authorized Paymob payment, fully or partially.

        Note: self.ensure_one()
        """
        if self.provider_code != "paymob_cf":
            return super()._send_capture_request()

        source_tx = self.source_transaction_id
        response = self.provider_id._send_api_request(
            "POST",
            const.ENDPOINT_CAPTURE,
            json={
                "transaction_id": self._paymob_cf_to_int(source_tx.provider_reference),
                "amount_cents": self._paymob_cf_to_cents(self.amount),
            },
            reference=self.reference,
        )
        self._record({**response, const.OWN_REQUEST_KEY: "capture"})
        return None

    def _send_void_request(self):
        """Override of `payment` to void an authorized Paymob payment.

        Note: self.ensure_one()
        """
        if self.provider_code != "paymob_cf":
            return super()._send_void_request()

        source_tx = self.source_transaction_id
        response = self.provider_id._send_api_request(
            "POST",
            const.ENDPOINT_VOID,
            json={"transaction_id": self._paymob_cf_to_int(source_tx.provider_reference)},
            reference=self.reference,
        )
        self._record({**response, const.OWN_REQUEST_KEY: "void"})
        return None

    def _paymob_cf_set_error(self, error):
        """Put the transaction in error after Paymob refused it.

        The customer gets an explanation they can act on; the staff find the code and what it means
        in the Paymob tab of the transaction.

        :param ValidationError error: The error raised while talking to Paymob.
        :rtype: None
        """
        tx = self.with_context(payment_safe_write=True)
        if isinstance(error, PaymobError):
            tx.write({
                "paymob_cf_error_code": error.code,
                "paymob_cf_error_details": error.description,
            })
            message = self.provider_id._paymob_cf_get_customer_error_message(
                error.code, error.description,
            )
        else:
            message = str(error)
        tx._set_error(message)

    # === BUSINESS METHODS - STATUS === #

    def _paymob_cf_sync_from_provider(self):
        """Fetch the latest Paymob transaction of the payment and record it.

        :return: Whether payment data were recorded.
        :rtype: bool
        """
        self.ensure_one()
        if not (self.paymob_cf_order_id or self.paymob_cf_special_reference):
            return False
        try:
            transaction = self.provider_id._paymob_cf_inquire(
                order_id=self.paymob_cf_order_id,
                special_reference=self.paymob_cf_special_reference,
            )
        except ValidationError as error:
            _logger.warning("Unable to fetch the Paymob status of %s: %s", self.reference, error)
            return False
        if not transaction:
            return False
        if not self._paymob_cf_is_own_order(transaction):
            _logger.warning("Paymob returned another order for %s.", self.reference)
            return False
        self._record(transaction)
        self._paymob_cf_fetch_saved_card(transaction)
        return True

    def _paymob_cf_fetch_saved_card(self, transaction):
        """Fetch the card Paymob saved with the payment, in case its callback hasn't come.

        Paymob sends the saved card in its own callback; the card is also fetched when the status
        of a paid payment is fetched, so that it is saved even if that callback is late or can't
        reach Odoo.

        :param dict transaction: The Paymob transaction of the payment.
        :rtype: None
        """
        if not (
            self.tokenize
            and paymob_utils.is_true(transaction.get("success"))
            and not self.sudo().paymob_cf_card_token
        ):
            return
        try:
            tokens = self.provider_id._paymob_cf_get_order_card_tokens(self.paymob_cf_order_id)
        except ValidationError as error:
            _logger.warning("Unable to fetch the Paymob card of %s: %s", self.reference, error)
            return
        own_tokens = [
            token for token in tokens
            if str(token.get("order_id") or self.paymob_cf_order_id) == self.paymob_cf_order_id
        ]
        if own_tokens:
            self._record({"type": const.CALLBACK_TOKEN, "obj": own_tokens[0]})

    def _paymob_cf_is_own_order(self, transaction):
        """Return whether a Paymob transaction belongs to the order of this payment."""
        self.ensure_one()
        order_id = str(paymob_utils.get_value(transaction, "order.id") or "")
        return bool(order_id) and order_id == (self.paymob_cf_order_id or "")

    @api.model
    def _cron_paymob_cf_sync_pending(self):
        """Check the status of unfinished Paymob payments, in case a notification was missed.

        Pending payments (e.g. kiosk references) are checked for 10 days, payments the customer
        never came back from for 2 days. Those checked the longest ago go first.
        """
        now = fields.Datetime.now()
        online_operations = ("online_redirect", "online_direct", "online_token")
        txs = self.search(
            Domain("provider_code", "=", "paymob_cf")
            & Domain("operation", "in", online_operations)
            & Domain("paymob_cf_order_id", "!=", False)
            & (
                Domain("state", "=", "pending") & Domain("create_date", ">=", now - timedelta(days=10))
                | Domain("state", "=", "draft") & Domain("create_date", ">=", now - timedelta(days=2))
            ),
            order="paymob_cf_last_sync asc nulls first, id asc",
            limit=200,
        )
        in_cron = bool(self.env.context.get("ir_cron_progress_id"))
        if in_cron:
            self.env["ir.cron"]._commit_progress(remaining=len(txs))
        for tx in txs:
            tx.with_context(payment_safe_write=True).paymob_cf_last_sync = fields.Datetime.now()
            tx._paymob_cf_sync_from_provider()
            if in_cron and not self.env["ir.cron"]._commit_progress(1):
                break  # The cron ran out of time; the next run continues.

    def action_paymob_cf_sync(self):
        """Fetch the latest status of the payment from Paymob."""
        self.ensure_one()
        payment_utils.check_rights_on_recordset(self)
        tx_sudo = self.sudo()  # In sudo mode to use the provider's credentials.
        tx_sudo.with_context(payment_safe_write=True).paymob_cf_last_sync = fields.Datetime.now()
        if not tx_sudo._paymob_cf_sync_from_provider():
            raise UserError(self.env._("Paymob has no payment for this order yet."))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": self.env._(
                    "Paymob sent the latest status of the payment. The payment is updated within "
                    "a few seconds; reload the page to see it.",
                ),
                "sticky": False,
            },
        }

    # === BUSINESS METHODS - HELPERS === #

    def _paymob_cf_get_method(self):
        """Return the primary payment method of the transaction (e.g. Card for a Visa card)."""
        self.ensure_one()
        return self.payment_method_id.primary_payment_method_id or self.payment_method_id

    def _paymob_cf_get_special_reference(self):
        """Return the unique reference of the payment at Paymob.

        Paymob refuses a reference it already knows, and one Paymob account may serve several
        databases (e.g. copies used for tests): the reference of the transaction is followed by a
        short code of the database.
        """
        self.ensure_one()
        if self.paymob_cf_special_reference:
            return self.paymob_cf_special_reference
        database_uuid = self.env["ir.config_parameter"].sudo().get_str("database.uuid") or ""
        suffix = re.sub(r"[^0-9a-f]", "", database_uuid)[:6]
        return f"{self.reference}-{suffix}" if suffix else self.reference

    def _paymob_cf_to_cents(self, amount):
        """Return an amount in the minor units of the transaction's currency, as Paymob expects."""
        return payment_utils.to_minor_currency_units(amount, self.currency_id)

    @staticmethod
    def _paymob_cf_to_int(value):
        """Return a Paymob identifier as a number, as Paymob's APIs expect."""
        value = str(value or "")
        return int(value) if value.isdigit() else value

    def _paymob_cf_get_items(self, amount_cents):
        """Return the items of the payment intention.

        Paymob shows the items on its checkout and requires them to add up to the amount paid. The
        lines of the sales order are sent, one item per line (free lines are left out), when none is
        negative and they add up to the amount paid; otherwise a single item with the amount paid is
        sent.

        :param int amount_cents: The amount paid, in minor units.
        :return: The items; their private `_product_tmpl` key holds the product paid, if known.
        :rtype: list[dict]
        """
        self.ensure_one()
        items = self._paymob_cf_get_order_items()
        if not items or sum(item["amount"] for item in items) != amount_cents:
            description = f"{self.company_id.name or ''} {self.reference}".strip()
            items = [{
                "name": self.reference[:50],
                "amount": amount_cents,
                "description": description[:255],
                "quantity": 1,
            }]
        return items

    def _paymob_cf_get_order_items(self):
        """Return the lines of the sales order paid by this transaction, if they can be sent.

        :rtype: list[dict]
        """
        if "sale_order_ids" not in self._fields or len(self.sale_order_ids) != 1:
            return []
        items = []
        for line in self.sale_order_ids.order_line.filtered(lambda line: not line.display_type):
            amount = self._paymob_cf_to_cents(line.price_total)
            if amount < 0:
                return []  # Discounts can't be sent as items: a single item is sent instead.
            if amount == 0:
                continue  # E.g. free delivery.
            name = (line.product_id.display_name or line.name or "").strip() or self.reference
            quantity = line.product_uom_qty
            quantity_label = int(quantity) if quantity == int(quantity) else quantity
            items.append({
                "name": name[:50],
                "amount": amount,
                "description": f"{quantity_label} x {line.name or name}"[:255],
                "quantity": 1,
                "_product_tmpl": line.product_id.product_tmpl_id,  # Not sent to Paymob.
            })
        return items

    def _paymob_cf_get_split_amounts(self, items):
        """Return the share of each connected merchant when the provider splits the payments.

        Each merchant that applies to an item gets its share of the item's price; the rest stays
        with the account that takes the payment.

        :param list items: The items of the intention.
        :return: The `split_amounts` of the intention.
        :rtype: list[dict]
        """
        provider = self.provider_id
        if not provider.paymob_cf_payment_split:
            return []
        merchants = provider.sudo().paymob_cf_split_merchant_ids.filtered("active")
        totals = {}
        for item in items:
            product = item.get("_product_tmpl")
            remainder = item["amount"]
            for merchant in merchants:
                if merchant.apply_to != "all" and not (product and product in merchant.product_tmpl_ids):
                    continue
                share = min(int(item["amount"] * merchant.share / 100), remainder)
                if share > 0:
                    totals[merchant] = totals.get(merchant, 0) + share
                    remainder -= share
        return [
            {
                "mid": self._paymob_cf_to_int(merchant.mid.strip()),
                "amount_cents": amount,
                "description": f"{merchant.name} {self.reference}"[:255],
            }
            for merchant, amount in totals.items()
            if amount > 0
        ]

    def _paymob_cf_get_billing_data(self):
        """Return the customer's details, which Paymob requires.

        Missing values are sent as "NA", the way Paymob expects them; the phone number and the email
        fall back to the company's.
        """
        self.ensure_one()
        first_name, last_name = payment_utils.split_partner_name(self.partner_name or "")
        company = self.company_id
        phone = re.sub(r"[^\d+]", "", self.partner_phone or "") or re.sub(
            r"[^\d+]", "", company.phone or "",
        )
        missing = const.MISSING_VALUE
        return {
            "first_name": (first_name or missing)[:50],
            "last_name": (last_name or first_name or missing)[:50],
            "email": self.partner_email or company.email or missing,
            "phone_number": phone or missing,
            "street": (self.partner_address or missing)[:255],
            "building": missing,
            "floor": missing,
            "apartment": missing,
            "city": self.partner_city or missing,
            "state": self.partner_state_id.name or missing,
            "country": self.partner_country_id.code or missing,
            "postal_code": self.partner_zip or missing,
        }

    def _paymob_cf_get_access_token(self):
        """Return the token protecting the payment routes of this transaction."""
        return payment_utils.generate_access_token(self.reference, self.partner_id.id, env=self.env)

    def _paymob_cf_get_route_url(self, route):
        """Return the absolute URL of a Paymob route for this transaction.

        The provider's base URL is the domain the customer is on (see `website_payment`), so that
        the customer comes back to the session that follows the payment.
        """
        path = f"{route}/{self.id}/{self._paymob_cf_get_access_token()}"
        return urls.urljoin(self.provider_id.get_base_url(), path)

    # === BUSINESS METHODS - PROCESSING === #

    @api.model
    def _extract_reference(self, provider_code, payment_data):
        """Override of `payment` to extract the reference from Paymob's payment data.

        Paymob's data are matched with their transaction by the controllers, from the order that
        Paymob signs; the reference is only used in logs.
        """
        if provider_code != "paymob_cf":
            return super()._extract_reference(provider_code, payment_data)
        return paymob_utils.get_value(payment_data, "order.merchant_order_id")

    def _apply_updates(self, payment_data):
        """Override of `payment` to update the transaction from Paymob's payment data.

        The payment data are a Paymob transaction, or a card token. The kind of update is decided by
        the operation of the transaction, never by the data alone.
        """
        if self.provider_code != "paymob_cf":
            return super()._apply_updates(payment_data)

        if payment_data.get("type") == const.CALLBACK_TOKEN:
            self._paymob_cf_store_card(payment_data.get("obj") or {})
            return None

        success = paymob_utils.is_true(payment_data.get("success"))
        pending = paymob_utils.is_true(payment_data.get("pending"))
        own_request = payment_data.get(const.OWN_REQUEST_KEY)

        if self.operation == "refund" or (self.source_transaction_id and own_request):
            # A refund, capture or void requested by Odoo: Paymob answered with a new transaction.
            if success:
                self.provider_reference = str(payment_data.get("id") or "") or self.provider_reference
                if own_request == "void":
                    self._set_canceled(state_message=self.env._("The authorization was voided."))
                else:
                    self._set_done()
            else:
                self._paymob_cf_set_decline(payment_data)
            return None

        if paymob_utils.is_true(payment_data.get("has_parent_transaction")):
            # A refund, capture or void of this payment, recorded on its own transaction.
            _logger.info("Paymob reported a follow-up transaction for %s.", self.reference)
            return None

        self._paymob_cf_update_details(payment_data)
        if paymob_utils.is_true(payment_data.get("is_voided")):
            self._set_canceled(state_message=self.env._("The payment was voided at Paymob."))
        elif success:
            if paymob_utils.is_true(payment_data.get("is_auth")) and not paymob_utils.is_true(
                payment_data.get("is_captured"),
            ):
                self._set_authorized()
            else:
                self._set_done()
        elif pending:
            self._set_pending()
        else:
            self._paymob_cf_set_decline(payment_data)
        return None

    def _paymob_cf_set_decline(self, transaction):
        """Put the transaction in error after Paymob declined it, with the reason explained."""
        code, details = paymob_utils.get_decline(transaction)
        self.paymob_cf_error_code = code
        self.paymob_cf_error_details = details or False
        provider = self.provider_id
        if code in const.ERROR_CODES:
            message = provider._paymob_cf_get_customer_error_message(code, details)
        elif details:
            message = self.env._(
                "The payment was declined: %(reason)s (code %(code)s)", reason=details, code=code,
            )
        else:
            message = self.env._("The payment was declined.")
        self._set_error(message)

    def _paymob_cf_update_details(self, transaction):
        """Store Paymob's transaction ID, the method used and the payment details."""
        if transaction_id := transaction.get("id"):
            self.provider_reference = str(transaction_id)
        source = transaction.get("source_data") if isinstance(transaction.get("source_data"), dict) else {}
        source_type = str(source.get("type") or "").lower()
        sub_type = str(source.get("sub_type") or "")
        method_code = const.SOURCE_TYPE_MAPPING.get(source_type)
        if method_code == "card":
            method_code = paymob_utils.get_brand_code(sub_type) or "card"
        if method_code:
            payment_method = self.provider_id._get_pm_from_code(method_code)
            current_methods = self.payment_method_id | self.payment_method_id.primary_payment_method_id
            if payment_method and payment_method not in current_methods:
                self.payment_method_id = payment_method
        if pan := source.get("pan"):
            self.paymob_cf_payment_source = f"{sub_type or source_type} {pan}".strip()
        data = transaction.get("data") if isinstance(transaction.get("data"), dict) else {}
        if bill_reference := data.get("bill_reference") or transaction.get("bill_reference"):
            self.paymob_cf_bill_reference = str(bill_reference)
        installment = transaction.get("installment") or {}
        tenure = source.get("tenure") or (
            installment.get("tenure") if isinstance(installment, dict) else None
        ) or (transaction.get("installment_info") or {}).get("tenure")
        if tenure:
            self.paymob_cf_installment = self.env._("%s months", tenure)

    def _paymob_cf_store_card(self, token_data):
        """Keep the card Paymob saved for the transaction, until the payment token is created."""
        self.sudo().paymob_cf_card_token = token_data.get("token") or False
        self.paymob_cf_card_data = {
            "masked_pan": token_data.get("masked_pan") or "",
            "card_subtype": token_data.get("card_subtype") or "",
            "expiry": paymob_utils.format_expiry(
                token_data.get("expiry_month"), token_data.get("expiry_year"),
            ),
            "cardholder_name": token_data.get("cardholder_name") or "",
        }

    def _extract_amount_data(self, payment_data):
        """Override of `payment` to extract the amount and the currency of a Paymob payment.

        Paymob rounds down the Visa payments of some currencies (e.g. OMR) to fewer decimals.
        """
        if self.provider_code != "paymob_cf":
            return super()._extract_amount_data(payment_data)
        if (
            payment_data.get("type") == const.CALLBACK_TOKEN
            or self.operation in ("refund", "validation")
            or self.source_transaction_id
            or payment_data.get("amount_cents") in (None, "")
        ):
            return None  # Card tokens, refunds and captures are checked by Paymob.
        amount = payment_utils.to_major_currency_units(
            float(payment_data["amount_cents"]), self.currency_id,
        )
        precision_digits = None
        sub_type = paymob_utils.get_value(payment_data, "source_data.sub_type")
        if str(sub_type or "").lower() == "visa":
            precision_digits = const.VISA_CURRENCY_DECIMALS.get(self.currency_id.name)
        return {
            "amount": amount,
            "currency_code": payment_data.get("currency"),
            "precision_digits": precision_digits,
        }

    def _extract_token_values(self, payment_data):
        """Override of `payment` to save the card Paymob saved for the payment."""
        if self.provider_code != "paymob_cf":
            return super()._extract_token_values(payment_data)

        card_token = self.sudo().paymob_cf_card_token
        if not card_token:
            # Paymob sends the card in its own notification, which may come after the payment.
            _logger.info("No Paymob card token yet for %s.", self.reference)
            return {}
        existing_token = self.env["payment.token"].search([
            ("provider_id", "=", self.provider_id.id),
            ("partner_id", "=", self.partner_id.id),
            ("provider_ref", "=", card_token),
        ], limit=1)
        if existing_token:
            _logger.info("The card of %s is already saved.", self.reference)
            return {}
        card_data = self.paymob_cf_card_data or {}
        token_values = {
            "provider_ref": card_token,
            "payment_details": paymob_utils.get_last_digits(card_data.get("masked_pan")),
            "paymob_cf_card_expiry": card_data.get("expiry") or False,
            "paymob_cf_cardholder": card_data.get("cardholder_name") or False,
        }
        brand_code = paymob_utils.get_brand_code(card_data.get("card_subtype"))
        if brand := brand_code and self.provider_id._get_pm_from_code(brand_code):
            token_values["payment_method_id"] = brand.id
        return token_values

    def _tokenize(self, payment_data):
        """Override of `payment` to forget Paymob's card token once it is saved as a payment token."""
        super()._tokenize(payment_data)
        if self.provider_code == "paymob_cf" and self.token_id:
            self.sudo().paymob_cf_card_token = False

    # === BUSINESS METHODS - INSTRUCTIONS === #

    def _get_status_message(self, **kwargs):
        """Override of `payment` to show how to complete a pending Paymob payment.

        A kiosk payment shows its reference; every pending payment updates the page by itself once
        Paymob confirms it.
        """
        message = super()._get_status_message(**kwargs)
        if (
            self.provider_code == "paymob_cf"
            and self.state == "pending"
            and self.operation != "validation"
        ):
            return self.env["ir.qweb"]._render(
                "payment_paymob_cf.payment_instructions",
                {"tx": self.sudo(), "status_message": message},
            )
        return message
