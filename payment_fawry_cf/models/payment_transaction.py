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
import time
from datetime import UTC, datetime, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import float_is_zero, float_round, urls

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_fawry_cf import const
from odoo.addons.payment_fawry_cf import utils as fawry_utils
from odoo.addons.payment_fawry_cf.controllers.main import FawryController
from odoo.addons.payment_fawry_cf.exceptions import FawryError

_logger = get_payment_logger(__name__, const.SENSITIVE_KEYS)


class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    fawry_payment_expiry = fields.Datetime(
        string="Fawry Payment Deadline",
        help="The date after which the Fawry reference code, wallet request or QR code expires.",
        readonly=True,
    )
    fawry_fees = fields.Monetary(
        string="Fawry Fees",
        help="The fees Fawry added to the amount paid by the customer.",
        currency_field="currency_id",
        readonly=True,
    )
    fawry_qr_code = fields.Text(
        string="Fawry QR Code",
        help="The QR code the customer scans with a wallet or the myFawry app.",
        readonly=True,
    )
    fawry_deep_link = fields.Char(
        string="myFawry Link",
        help="The link that opens the payment in the myFawry app.",
        readonly=True,
    )
    fawry_wallet_number = fields.Char(
        string="Fawry Wallet Number",
        help="The mobile wallet that received the payment request.",
        readonly=True,
    )
    fawry_customer_profile_id = fields.Char(
        string="Fawry Customer Profile",
        help="The customer identifier sent to Fawry, under which the cards are saved.",
        readonly=True,
    )
    fawry_card_token = fields.Char(
        string="Fawry Card Token",
        help="The token of the card the customer entered on Fawry's secure page for this payment.",
        readonly=True,
        groups="base.group_system",
    )
    fawry_card_data = fields.Json(
        string="Fawry Card Details",
        help="The masked details of the card entered for this payment.",
        readonly=True,
    )
    fawry_redirect_url = fields.Char(
        string="Fawry 3-D Secure URL",
        help="Where the customer authenticates the payment with their bank, or chooses an "
        "installment plan.",
        readonly=True,
    )
    fawry_last_sync = fields.Datetime(string="Fawry Last Status Check", readonly=True)
    fawry_installment_plan_id = fields.Integer(
        string="Fawry Installment Plan ID",
        help="The Fawry installment plan the customer chose to pay with.",
        readonly=True,
    )
    fawry_installment_plan = fields.Char(
        string="Installment Plan",
        help="The installment plan the customer chose to pay with.",
        readonly=True,
    )
    fawry_error_code = fields.Char(
        string="Fawry Error Code",
        help="The code of the last error Fawry returned for this payment.",
        readonly=True,
    )
    fawry_error_details = fields.Char(
        string="Fawry Error Details",
        help="The description of the error, as Fawry sent it.",
        readonly=True,
    )
    fawry_error_explanation = fields.Char(
        string="Fawry Error",
        help="What the error returned by Fawry means.",
        compute="_compute_fawry_error_explanation",
    )
    fawry_can_use_pos_emulator = fields.Boolean(
        string="Payable at Fawry's POS Emulator",
        help="Whether the reference code of this test payment can be paid at Fawry's POS Emulator.",
        compute="_compute_fawry_can_use_pos_emulator",
    )

    # === COMPUTE METHODS === #

    @api.depends("provider_id.is_live", "state", "provider_reference", "payment_method_id")
    def _compute_fawry_can_use_pos_emulator(self):
        for tx in self:
            tx.fawry_can_use_pos_emulator = (
                tx.provider_code == "fawry"
                and not tx.provider_id.is_live
                and tx.state == "pending"
                and tx._fawry_is_reference_code()
            )

    @api.depends("fawry_error_code", "fawry_error_details")
    def _compute_fawry_error_explanation(self):
        for tx in self:
            tx.fawry_error_explanation = (tx.fawry_error_code or tx.fawry_error_details) and (
                tx.provider_id._fawry_get_error_message(
                    tx.fawry_error_code, tx.fawry_error_details,
                )
            )

    # === BUSINESS METHODS - PAYMENT FLOW === #

    def _get_specific_processing_values(self, processing_values):
        """Override of `payment` to return the values the payment form needs for Fawry.

        Note: self.ensure_one() from `_get_processing_values`

        :param dict processing_values: The generic processing values of the transaction.
        :return: The provider-specific processing values.
        :rtype: dict
        """
        res = super()._get_specific_processing_values(processing_values)
        if self.provider_code != "fawry":
            return res

        if self.operation == "online_token":
            if self.state in ("draft", "pending") and self.fawry_redirect_url:
                res["fawry_redirect_url"] = self.fawry_redirect_url
        elif self.operation == "online_direct":
            flow = self.provider_id._fawry_get_flow(self.payment_method_code)
            if flow == const.FLOW_HOSTED:
                res["fawry_checkout"] = self._fawry_prepare_checkout_values()
            elif flow == const.FLOW_S2S_CHARGE:
                res["fawry_access_token"] = self._fawry_get_access_token()
        return res

    def _get_specific_rendering_values(self, processing_values):
        """Override of `payment` to return the redirection values for Fawry.

        Cards paid through the server-to-server integration, and cards saved from the customer
        portal, go to Fawry's secure card page. Every other payment goes to Fawry's hosted checkout.

        Note: self.ensure_one() from `_get_processing_values`

        :param dict processing_values: The generic and specific processing values.
        :return: The values of `payment.generic_redirect_form`.
        :rtype: dict
        """
        if self.provider_code != "fawry":
            return super()._get_specific_rendering_values(processing_values)

        provider = self.provider_id
        flow = provider._fawry_get_flow(
            self.payment_method_code, is_validation=self.operation == "validation",
        )
        if flow == const.FLOW_CARD_TOKEN:
            self.fawry_customer_profile_id = self._fawry_get_customer_profile_id()
            api_url, url_params = provider._fawry_get_card_token_url(
                self.fawry_customer_profile_id,
                self._fawry_get_route_url(FawryController._card_return_url),
                self.partner_lang,
            )
            return {"api_url": api_url, "http_method": "get", "url_params": url_params}

        try:
            checkout_url = self._fawry_init_checkout()
        except ValidationError as error:
            self._fawry_set_error(error)
            return {}
        return {
            "api_url": checkout_url.split("?", 1)[0],
            "http_method": "get",
            "url_params": payment_utils.extract_url_params(checkout_url),
        }

    def _fawry_init_checkout(self):
        """Create a session on Fawry's hosted checkout and return its URL.

        :return: The URL of the hosted checkout.
        :rtype: str
        :raise ValidationError: If Fawry rejects the request or returns an unexpected URL.
        """
        payload = self._fawry_prepare_checkout_request()
        checkout_url = self.provider_id._send_api_request(
            "POST", const.ENDPOINT_INIT, json=payload, reference=self.reference,
        )
        if not isinstance(checkout_url, str) or not self.provider_id._fawry_is_own_url(
            checkout_url,
        ):
            raise ValidationError(
                self.env._("Fawry returned an unexpected checkout address: %s", checkout_url),
            )
        return checkout_url

    def _fawry_prepare_checkout_request(self):
        """Return the signed charge request of Fawry's hosted checkout (Express Checkout).

        :return: The charge request.
        :rtype: dict
        """
        provider = self.provider_id
        self.fawry_customer_profile_id = self._fawry_get_customer_profile_id()
        return_url = self._fawry_get_route_url(FawryController._return_url)
        items = self._fawry_get_charge_items()
        request_values = {
            **self._fawry_get_customer_values(),
            "merchantCode": provider.fawry_merchant_code,
            "merchantRefNum": self.reference,
            "customerProfileId": self.fawry_customer_profile_id,
            "language": fawry_utils.get_fawry_language(self.partner_lang),
            "chargeItems": items,
            "returnUrl": return_url,
            "orderWebHookUrl": provider.fawry_webhook_url,
            "authCaptureModePayment": False,
            "paymentExpiry": self._fawry_get_expiry_timestamp(),
        }
        locked_method = const.HOSTED_METHOD_CODES.get(self.payment_method_code)
        if locked_method:
            request_values["paymentMethod"] = locked_method
        items_string = "".join(
            f"{item['itemId']}{item['quantity']}{fawry_utils.format_amount(item['price'])}"
            for item in sorted(items, key=lambda item: item["itemId"])
        )
        request_values["signature"] = provider._fawry_sign(
            provider.fawry_merchant_code,
            self.reference,
            self.fawry_customer_profile_id,
            return_url,
            items_string,
        )
        return request_values

    def _fawry_prepare_checkout_values(self):
        """Create Fawry's checkout session and return what the payment form needs to show it in a
        pop-up or a side panel.

        The session is created by the server, like for the full-page checkout: Fawry's JavaScript
        library creates it from the browser instead, which Fawry only accepts from the websites it
        registered.

        :return: The checkout URL, Fawry's origin (which posts the result back to the page), the
                 return URL and the display mode; or an empty dict if the checkout failed.
        :rtype: dict
        """
        provider = self.provider_id
        try:
            checkout_url = self._fawry_init_checkout()
        except ValidationError as error:
            self._fawry_set_error(error)
            return {}
        mode = const.DISPLAY_MODES.get(provider.fawry_display_mode, "POPUP")
        return {
            "checkout_url": f"{checkout_url}&mode={mode}",
            "redirect_url": checkout_url,
            "origin": provider._fawry_get_base_url(),
            "return_url": self._fawry_get_route_url(FawryController._return_url),
            "display_mode": provider.fawry_display_mode,
        }

    def _fawry_charge(self, wallet_number=None):
        """Create a Fawry reference code, wallet request or myFawry payment for this transaction.

        The response holds the instructions shown to the customer: a reference code to pay at a
        Fawry outlet, a QR code to scan with a wallet, or a link to the myFawry app.

        :param str wallet_number: The mobile wallet that should receive a payment request; the
                                  customer gets a QR code to scan instead when it is empty.
        :return: The charge response.
        :rtype: dict
        :raise ValidationError: If Fawry rejects the charge.
        """
        provider = self.provider_id
        fawry_method = const.S2S_CHARGE_METHOD_CODES[self.payment_method_code]
        self.fawry_customer_profile_id = self._fawry_get_customer_profile_id()
        amount = fawry_utils.format_amount(self.amount)
        payload = {
            **self._fawry_get_customer_values(),
            "merchantCode": provider.fawry_merchant_code,
            "merchantRefNum": self.reference,
            "customerProfileId": self.fawry_customer_profile_id,
            "paymentMethod": fawry_method,
            "amount": amount,
            "currencyCode": self.currency_id.name,
            "language": fawry_utils.get_fawry_language(self.partner_lang),
            "description": self._fawry_get_description(),
            "chargeItems": self._fawry_get_charge_items(),
            "orderWebHookUrl": provider.fawry_webhook_url,
            "paymentExpiry": self._fawry_get_expiry_timestamp(),
        }
        signed_values = [
            provider.fawry_merchant_code,
            self.reference,
            self.fawry_customer_profile_id,
            fawry_method,
            amount,
        ]
        endpoint = const.ENDPOINT_CHARGE
        if fawry_method == "MWALLET":
            endpoint = const.ENDPOINT_WALLET_CHARGE
            if wallet_number:
                payload["debitMobileWalletNo"] = wallet_number
                signed_values.append(wallet_number)
                self.fawry_wallet_number = wallet_number
        payload["signature"] = provider._fawry_sign(*signed_values)
        return provider._send_api_request(
            "POST", endpoint, json=payload, reference=self.reference,
        )

    def _fawry_charge_card_token(self, card_token, installment_plan=None):
        """Charge a card saved at Fawry, with 3-D Secure.

        :param str card_token: The Fawry card token.
        :param dict installment_plan: The bank installment plan to pay with, if any.
        :return: The charge response; it holds the 3-D Secure redirection when one is needed.
        :rtype: dict
        :raise ValidationError: If Fawry rejects the charge.
        """
        provider = self.provider_id
        amount = fawry_utils.format_amount(self.amount)
        return_url = self._fawry_get_route_url(FawryController._return_url)
        payload = {
            **self._fawry_get_customer_values(),
            "merchantCode": provider.fawry_merchant_code,
            "merchantRefNum": self.reference,
            "customerProfileId": self.fawry_customer_profile_id,
            "paymentMethod": "CARD",
            "cardToken": card_token,
            "amount": amount,
            "currencyCode": self.currency_id.name,
            "language": fawry_utils.get_fawry_language(self.partner_lang),
            "description": self._fawry_get_description(),
            "chargeItems": self._fawry_get_charge_items(),
            "enable3DS": True,
            "authCaptureModePayment": False,
            "returnUrl": return_url,
            "orderWebHookUrl": provider.fawry_webhook_url,
        }
        plan_id = ""
        if installment_plan:
            plan_id = str(installment_plan["id"])
            payload["installmentPlanId"] = installment_plan["id"]
            self.with_context(payment_safe_write=True).write({
                "fawry_installment_plan_id": installment_plan["id"],
                "fawry_installment_plan": provider._fawry_get_installment_plan_label(
                    installment_plan,
                ),
            })
        # The CVV is not collected: it is signed as an empty value. The installment plan, if any,
        # is signed before the return URL.
        payload["signature"] = provider._fawry_sign(
            provider.fawry_merchant_code,
            self.reference,
            self.fawry_customer_profile_id,
            "CARD",
            amount,
            card_token,
            plan_id,
            return_url,
        )
        return provider._send_api_request(
            "POST", const.ENDPOINT_CHARGE, json=payload, reference=self.reference,
        )

    def _fawry_handle_charge_response(self, response):
        """Store the 3-D Secure redirection of a card charge, then record the response.

        :param dict response: The charge response.
        :return: The URL where the customer authenticates the payment, if any.
        :rtype: str | None
        """
        redirect_url = (response.get("nextAction") or {}).get("redirectUrl")
        if redirect_url and not self.provider_id._fawry_is_own_url(redirect_url):
            raise ValidationError(
                self.env._("Fawry returned an unexpected authentication address."),
            )
        if redirect_url:
            self.with_context(payment_safe_write=True).fawry_redirect_url = redirect_url
        self._record(response)
        return redirect_url

    def _send_payment_request(self):
        """Override of `payment` to charge a saved card.

        Fawry requires 3-D Secure for every card payment unless the account is approved for
        payments without it, so the customer authenticates each payment with their bank.

        Note: self.ensure_one()

        :raise ValidationError: If the transaction is not linked to a token.
        """
        if self.provider_code != "fawry":
            return super()._send_payment_request()

        if not self.token_id:
            raise ValidationError(self.env._("The transaction is not linked to a token."))
        if self.operation == "offline":
            raise ValidationError(
                self.env._(
                    "Fawry asks the customer to authenticate every card payment with their bank, "
                    "so saved cards can't be charged while the customer is away.",
                ),
            )

        # Errors are raised to `_charge_with_token`, which sets the error and post-processes.
        self.with_context(payment_safe_write=True).fawry_customer_profile_id = (
            self.token_id.fawry_customer_profile_id or self._fawry_get_customer_profile_id()
        )
        if self._fawry_get_installment_plans(self.token_id.fawry_card_bin):
            # The customer first chooses between paying in full and the installment plans.
            self.with_context(payment_safe_write=True).fawry_redirect_url = (
                f"{FawryController._installments_url}/{self.id}/{self._fawry_get_access_token()}"
            )
            return None
        try:
            response = self._fawry_charge_card_token(self.token_id.provider_ref)
        except FawryError as error:
            # `_charge_with_token` shows the message to the customer: explain it to them.
            self.with_context(payment_safe_write=True).write({
                "fawry_error_code": error.code,
                "fawry_error_details": error.description,
            })
            raise ValidationError(
                self.provider_id._fawry_get_customer_error_message(error.code, error.description),
            ) from None
        self._fawry_handle_charge_response(response)

    def _fawry_get_card(self):
        """Return the Fawry token and the first six digits of the card paying this transaction.

        :return: The card token and the first digits, either of the saved card or of the card
                 entered on Fawry's secure page.
        :rtype: tuple[str, str]
        """
        self.ensure_one()
        if self.token_id:
            return self.token_id.provider_ref, self.token_id.fawry_card_bin
        return self.sudo().fawry_card_token, (self.fawry_card_data or {}).get("firstSixDigits")

    def _fawry_get_installment_options(self, plans):
        """Return what each installment plan costs the customer, to show the plans.

        Fawry adds the rate of the plan to the amount of the order; the bank confirms the final
        amount during the payment.

        :param list plans: The installment plans.
        :return: For each plan: its id, label, number of months, rate, total and monthly amount.
        :rtype: list[dict]
        """
        self.ensure_one()
        rounding = self.currency_id.rounding
        options = []
        for plan in plans:
            total = float_round(
                self.amount * (1 + (plan["rate"] or 0) / 100), precision_rounding=rounding,
            )
            options.append({
                "id": plan["id"],
                "label": self.provider_id._fawry_get_installment_plan_label(plan),
                "months": plan["months"],
                "rate": plan["rate"],
                "total": total,
                "monthly": float_round(total / plan["months"], precision_rounding=rounding),
            })
        return options

    def _fawry_get_installment_plans(self, card_bin):
        """Return the bank installment plans the customer can pay this transaction with.

        :param str card_bin: The first six digits of the card.
        :rtype: list[dict]
        """
        self.ensure_one()
        if self.operation not in ("online_redirect", "online_direct", "online_token"):
            return []
        return self.provider_id._fawry_get_eligible_installment_plans(
            self.amount, card_bin, product_codes=self._fawry_get_product_codes(),
        )

    def _fawry_set_error(self, error):
        """Put the transaction in error after Fawry refused it.

        The customer gets an explanation they can act on; the staff find the code and what it means
        in the Fawry tab of the transaction.

        :param ValidationError error: The error raised while talking to Fawry.
        :rtype: None
        """
        tx = self.with_context(payment_safe_write=True)
        if isinstance(error, FawryError):
            tx.write({"fawry_error_code": error.code, "fawry_error_details": error.description})
            message = self.provider_id._fawry_get_customer_error_message(
                error.code, error.description,
            )
        else:
            message = str(error)
        tx._set_error(message)

    def _send_refund_request(self):
        """Override of `payment` to refund a Fawry payment, fully or partially.

        Note: self.ensure_one()
        """
        if self.provider_code != "fawry":
            return super()._send_refund_request()

        source_tx = self.source_transaction_id
        if not source_tx.provider_reference:
            raise ValidationError(
                self.env._("The payment to refund has no Fawry reference number."),
            )
        provider = self.provider_id
        amount = fawry_utils.format_amount(-self.amount)
        reason = self.reference  # Signed by Fawry: kept to plain ASCII.
        payload = {
            "merchantCode": provider.fawry_merchant_code,
            "referenceNumber": source_tx.provider_reference,
            "refundAmount": amount,
            "reason": reason,
            "signature": provider._fawry_sign(
                provider.fawry_merchant_code, source_tx.provider_reference, amount, reason,
            ),
        }
        response = provider._send_api_request(
            "POST", const.ENDPOINT_REFUND, json=payload, reference=self.reference,
        )
        self._record({**response, "merchantRefNumber": self.reference, "fawry_refund": True})

    def _fawry_sync_from_provider(self, fallback_values=None):
        """Fetch the status of the payment from Fawry and record it.

        :param dict fallback_values: The values Fawry sent with the customer back to Odoo. They
                                     are used when Fawry has no order yet, e.g. when the hosted
                                     checkout failed before creating it.
        Note: the transaction itself is not written, so that the processing can run in the same
        request (`_run_processing` processes it from another cursor, which would wait forever on a
        transaction locked by this request).

        :return: Whether payment data were recorded.
        :rtype: bool
        """
        self.ensure_one()
        try:
            status = self.provider_id._fawry_get_payment_status(self.reference)
        except ValidationError as error:
            _logger.warning("Unable to fetch the Fawry status of %s: %s", self.reference, error)
            return False
        if status:
            self._record(status)
            return True
        fallback_values = fallback_values or {}
        status_code = str(fallback_values.get("statusCode") or "")
        if status_code and status_code != "200":
            self._record({
                "merchantRefNumber": self.reference,
                "orderStatus": "FAILED",
                "failureErrorCode": status_code,
                "failureReason": fallback_values.get("statusDescription"),
            })
            return True
        return False

    def _fawry_cancel_unpaid(self):
        """Cancel the Fawry order of an unpaid reference code, wallet request or myFawry payment.

        :rtype: None
        :raise UserError: If the payment can't be canceled.
        """
        self.ensure_one()
        if self.provider_code != "fawry" or self.state != "pending" or not self.provider_reference:
            raise UserError(self.env._("Only unpaid Fawry payments can be canceled."))
        provider = self.provider_id
        lang = fawry_utils.get_fawry_language(self.partner_lang)
        payload = {
            "orderRefNo": self.provider_reference,
            "merchantAccount": provider.fawry_merchant_code,
            "lang": lang,
            "signature": provider._fawry_sign(
                self.provider_reference, provider.fawry_merchant_code, lang,
            ),
        }
        try:
            provider._send_api_request(
                "POST", const.ENDPOINT_CANCEL_UNPAID, json=payload, reference=self.reference,
            )
        except ValidationError as error:
            raise UserError(str(error)) from None
        self._fawry_sync_from_provider()

    # === BUSINESS METHODS - HELPERS === #

    def _fawry_get_customer_profile_id(self):
        """Return the identifier of the customer at Fawry, under which their cards are saved."""
        self.ensure_one()
        return self.fawry_customer_profile_id or str(self.partner_id.id)

    def _fawry_get_customer_values(self):
        """Return the customer details sent to Fawry, which notifies the customer with them."""
        values = {"customerName": (self.partner_name or "")[:100]}
        if mobile := fawry_utils.normalize_mobile(self.partner_phone):
            values["customerMobile"] = mobile
        if self.partner_email:
            values["customerEmail"] = self.partner_email
        return values

    def _fawry_get_description(self):
        """Return the description of the payment shown by Fawry."""
        company = self.company_id.name or ""
        return f"{company} {self.reference}".strip()[:100]

    def _fawry_get_charge_items(self):
        """Return the items of the charge request.

        Fawry shows the items on its checkout and signs their whole quantities, so the order lines
        are only sent when they all have a whole quantity and add up to the amount paid. Otherwise,
        a single line with the amount paid is sent.

        :return: The charge items.
        :rtype: list[dict]
        """
        self.ensure_one()
        currency = self.currency_id
        items = self._fawry_get_order_items()
        total = sum(item["price"] * item["quantity"] for item in items)
        if not items or not float_is_zero(total - self.amount, precision_rounding=currency.rounding):
            items = [{
                "itemId": self.reference,
                "description": self._fawry_get_description(),
                "price": float_round(self.amount, precision_rounding=currency.rounding),
                "quantity": 1,
            }]
        self._fawry_add_split_accounts(items)
        return [
            {key: value for key, value in item.items() if not key.startswith("_")}
            for item in items
        ]

    def _fawry_add_split_accounts(self, items):
        """Add the accounts that share each item when the provider splits the payments.

        Each sub-account that applies to an item gets its share of the item's price; the rest goes
        to the merchant's own account. Fawry requires the shares of an item to add up to its price.

        :param list items: The charge items; their private `_product_tmpl` key holds the product
                           paid, if known.
        :rtype: None
        """
        provider = self.provider_id
        accounts = provider.sudo().fawry_split_account_ids.filtered("active")
        if not provider.fawry_payment_split:
            return
        rounding = self.currency_id.rounding
        for item in items:
            item_total = float_round(item["price"] * item["quantity"], precision_rounding=rounding)
            product = item.get("_product_tmpl")
            item_accounts = accounts.filtered(
                lambda a, product=product: a.apply_to == "all"
                or (product and product in a.product_tmpl_ids),
            )
            shares = []
            remainder = item_total
            for account in item_accounts:
                amount = min(
                    float_round(item_total * account.share / 100, precision_rounding=rounding),
                    remainder,
                )
                if amount > 0:
                    shares.append({"accountCode": account.code, "amount": amount})
                    remainder = float_round(remainder - amount, precision_rounding=rounding)
            if remainder > 0:
                shares.append({"accountCode": provider.fawry_merchant_code, "amount": remainder})
            item["accounts"] = shares

    def _fawry_get_order_items(self):
        """Return the lines of the sales order paid by this transaction, if they can be sent.

        :return: The charge items, or an empty list.
        :rtype: list[dict]
        """
        if "sale_order_ids" not in self._fields or len(self.sale_order_ids) != 1:
            return []
        items = []
        for line in self.sale_order_ids.order_line.filtered(lambda line: not line.display_type):
            quantity = line.product_uom_qty
            if not quantity or quantity != int(quantity) or line.price_total <= 0:
                return []
            price = float_round(
                line.price_total / quantity, precision_rounding=self.currency_id.rounding,
            )
            items.append({
                "itemId": f"{line.id}",
                "description": (line.name or line.product_id.display_name or "")[:100],
                "price": price,
                "quantity": int(quantity),
                "_product_tmpl": line.product_id.product_tmpl_id,  # Not sent to Fawry.
            })
        return items

    def _fawry_get_product_codes(self):
        """Return the internal references of the products paid, for the installment plans that
        are limited to some products.
        """
        if "sale_order_ids" not in self._fields:
            return []
        lines = self.sale_order_ids.order_line.filtered(lambda line: not line.display_type)
        return [code for code in lines.product_id.mapped("default_code") if code]

    def _fawry_get_expiry_timestamp(self):
        """Return when the payment expires at Fawry, in milliseconds since the epoch."""
        hours = self.provider_id.fawry_payment_expiry_hours or 48
        return int((time.time() + hours * 3600) * 1000)

    def _fawry_get_access_token(self):
        """Return the token protecting the payment routes of this transaction."""
        return payment_utils.generate_access_token(self.reference, self.partner_id.id, env=self.env)

    def _fawry_get_route_url(self, route):
        """Return the absolute URL of a Fawry route for this transaction."""
        path = f"{route}/{self.id}/{self._fawry_get_access_token()}"
        return urls.urljoin(self.get_base_url(), path)

    # === BUSINESS METHODS - PROCESSING === #

    @api.model
    def _extract_reference(self, provider_code, payment_data):
        """Override of `payment` to extract the reference from Fawry's payment data."""
        if provider_code != "fawry":
            return super()._extract_reference(provider_code, payment_data)
        # Only the key Fawry signs is used, so that unsigned data can't target a transaction.
        return payment_data.get("merchantRefNumber")

    def _apply_updates(self, payment_data):
        """Override of `payment` to update the transaction from Fawry's payment data.

        The kind of update is decided by the operation of the transaction, never by the data.
        """
        if self.provider_code != "fawry":
            return super()._apply_updates(payment_data)

        if self.operation == "refund":
            self._set_done()  # Only successful refunds are recorded.
            return
        if self.operation == "validation" and payment_data.get("fawry_validation"):
            self._set_done()  # The card was saved and verified with 3-D Secure.
            return

        order_status = (payment_data.get("orderStatus") or "").upper()
        if not order_status and (payment_data.get("nextAction") or {}).get("redirectUrl"):
            self._set_pending()  # The customer must still authenticate the payment.
            return

        self._fawry_update_details(payment_data)

        if order_status in const.PAYMENT_STATUS_MAPPING["pending"]:
            self._set_pending()
        elif order_status in const.PAYMENT_STATUS_MAPPING["done"]:
            self._set_done()
        elif order_status in const.PAYMENT_STATUS_MAPPING["authorized"]:
            # Payments are never sent for authorization only; wait for Fawry to capture them.
            self._set_pending()
        elif order_status in const.PAYMENT_STATUS_MAPPING["cancel"]:
            if order_status == "EXPIRED":
                message = self.env._("The payment expired before it was made.")
            else:
                message = self.env._("The payment was canceled at Fawry.")
            self._set_canceled(state_message=message)
        elif order_status in const.PAYMENT_STATUS_MAPPING["error"]:
            reason = payment_data.get("failureReason") or payment_data.get("statusDescription")
            code = payment_data.get("failureErrorCode")
            if code or reason:
                self.fawry_error_code = str(code) if code else False
                self.fawry_error_details = reason or False
            if code and str(code) in const.ERROR_CODES:
                message = self.provider_id._fawry_get_customer_error_message(code, reason)
            elif reason:
                message = self.env._(
                    "The payment was declined: %(reason)s (code %(code)s)",
                    reason=reason,
                    code=code or "-",
                )
            else:
                message = self.env._("The payment was declined.")
            self._set_error(message)
        elif order_status in const.PAYMENT_STATUS_MAPPING["refunded"]:
            # Refunds are tracked by their own transactions; the payment itself stays done.
            _logger.info("Fawry reported %s for %s.", order_status, self.reference)
        else:
            _logger.warning(
                "Received data with an unknown Fawry status (%s) for %s.",
                order_status,
                self.reference,
            )
            self._set_error(
                self.env._("Received data with an unknown payment status: %s", order_status),
            )

    def _fawry_update_details(self, payment_data):
        """Store the Fawry reference, the method used and the payment instructions."""
        if fawry_reference := payment_data.get("fawryRefNumber") or payment_data.get(
            "referenceNumber",
        ):
            self.provider_reference = str(fawry_reference).lstrip("/")

        fawry_method = (payment_data.get("paymentMethod") or "").upper()
        if method_code := const.FAWRY_TO_ODOO_METHOD_CODES.get(fawry_method):
            payment_method = self.provider_id._get_pm_from_code(method_code)
            current_methods = self.payment_method_id | self.payment_method_id.primary_payment_method_id
            if payment_method and payment_method not in current_methods:
                self.payment_method_id = payment_method

        if (fees := payment_data.get("fawryFees")) not in (None, ""):
            self.fawry_fees = float(fees)
        expiry = payment_data.get("expirationTime") or payment_data.get("orderExpiryDate")
        if isinstance(expiry, (int, float)) and expiry > 10**11:  # Milliseconds since the epoch.
            self.fawry_payment_expiry = datetime.fromtimestamp(expiry / 1000, tz=UTC).replace(
                tzinfo=None,
            )
        if qr_code := payment_data.get("walletQr") or payment_data.get("paymentQr"):
            self.fawry_qr_code = qr_code
        if deep_link := payment_data.get("paymentDeepLink") or payment_data.get("deepLink"):
            self.fawry_deep_link = deep_link

    def _extract_amount_data(self, payment_data):
        """Override of `payment` to extract the amount of the order, without Fawry's fees."""
        if self.provider_code != "fawry":
            return super()._extract_amount_data(payment_data)
        if self.operation in ("refund", "validation"):
            return None  # Refunds are checked by Fawry; validations have no amount.
        amount = payment_data.get("orderAmount")
        if amount in (None, ""):
            return None
        return {
            "amount": float(amount),
            "currency_code": self.currency_id.name,
            "precision_digits": 2,
        }

    def _extract_token_values(self, payment_data):
        """Override of `payment` to save the card the customer entered on Fawry's secure page."""
        if self.provider_code != "fawry":
            return super()._extract_token_values(payment_data)

        card_token = self.sudo().fawry_card_token
        if not card_token:
            _logger.warning("No Fawry card token to save for %s.", self.reference)
            return {}
        if self._fawry_get_saved_tokens(card_token):
            # Fawry gives the same token to a card saved twice: keep the existing payment token.
            _logger.info("The card of %s is already saved.", self.reference)
            return {}
        card_data = self.fawry_card_data or {}
        token_values = {
            "provider_ref": card_token,
            "payment_details": card_data.get("lastFourDigits") or "",
            "fawry_customer_profile_id": self.fawry_customer_profile_id,
            "fawry_card_expiry": card_data.get("expiryDate") or False,
            "fawry_card_bin": card_data.get("firstSixDigits") or False,
            "fawry_last_check": fields.Datetime.now(),  # The card was just found at Fawry.
        }
        brand_code = fawry_utils.get_brand_code(
            card_data.get("brand"), card_data.get("firstSixDigits"),
        )
        if brand := brand_code and self.provider_id._get_pm_from_code(brand_code):
            token_values["payment_method_id"] = brand.id
        return token_values

    def _fawry_get_saved_tokens(self, card_token, same_provider=True):
        """Return the active payment tokens that use the given Fawry card.

        :param str card_token: The Fawry card token.
        :param bool same_provider: Whether to only look at this provider's tokens; otherwise, the
                                   tokens of every provider using the same Fawry account (e.g. in
                                   other companies) are returned.
        :rtype: payment.token
        """
        provider_domain = (
            Domain("provider_id", "=", self.provider_id.id)
            if same_provider
            else Domain("provider_id.code", "=", "fawry")
            & Domain("provider_id.fawry_merchant_code", "=", self.provider_id.fawry_merchant_code)
        )
        return self.env["payment.token"].sudo().search(
            provider_domain & Domain("provider_ref", "=", card_token),
        )

    def _post_process(self):
        """Override of `payment` to delete the cards that customers didn't ask to save.

        Fawry's secure page saves every card it receives; a card used for a single payment is
        deleted once the payment is over, unless a payment token still uses it.
        """
        super()._post_process()
        for tx in self.filtered(
            lambda t: t.provider_code == "fawry"
            and t.state in ("done", "cancel", "error")
            and t.operation != "validation"
            and not t.token_id
            and t.sudo().fawry_card_token,
        ):
            tx_sudo = tx.sudo()
            if tx._fawry_get_saved_tokens(tx_sudo.fawry_card_token, same_provider=False):
                tx_sudo.with_context(payment_safe_write=True).fawry_card_token = False
                continue
            try:
                tx.provider_id._fawry_delete_card_token(
                    tx.fawry_customer_profile_id, tx_sudo.fawry_card_token,
                )
            except ValidationError:
                _logger.warning("Unable to delete the Fawry card used by %s.", tx.reference)
                continue
            tx_sudo.with_context(payment_safe_write=True).fawry_card_token = False

    # === BUSINESS METHODS - INSTRUCTIONS === #

    def _get_status_message(self, **kwargs):
        """Override of `payment` to show how to complete a pending Fawry payment.

        The instructions (reference code, QR code, myFawry link) appear wherever Odoo shows the
        status of the payment: payment status, order confirmation, customer portal. Every pending
        Fawry payment also updates the page by itself once Fawry confirms it.
        """
        message = super()._get_status_message(**kwargs)
        if (
            self.provider_code == "fawry"
            and self.state == "pending"
            and self.operation != "validation"
        ):
            return self.env["ir.qweb"]._render(
                "payment_fawry_cf.payment_instructions",
                {"tx": self.sudo(), "status_message": message},
            )
        return message

    def _fawry_is_reference_code(self):
        """Return whether the customer pays a Fawry reference code at an outlet."""
        return bool(self.provider_reference) and self.payment_method_code == "pay_at_fawry"

    def _fawry_get_instructions_values(self):
        """Return the values of the payment instructions template."""
        self.ensure_one()
        reference = self.provider_reference or ""
        grouped_reference = " ".join(
            reference[index : index + 3] for index in range(0, len(reference), 3)
        )
        if self._fawry_is_reference_code():
            kind = "reference"
        elif self.payment_method_code == "myfawry" and (self.fawry_qr_code or self.fawry_deep_link):
            kind = "myfawry"
        elif self.fawry_qr_code or self.fawry_wallet_number:
            kind = "wallet"
        else:
            kind = "confirming"  # E.g. a card payment Fawry hasn't confirmed yet.
        # Administrators testing their checkout can pay test reference codes at the POS Emulator.
        pos_emulator_url = (
            self.fawry_can_use_pos_emulator
            and self.env.user._is_system()
            and self._fawry_get_pos_emulator_page_url()
        )
        return {
            "kind": kind,
            "reference": reference,
            "grouped_reference": grouped_reference,
            "amount": self.amount + (self.fawry_fees or 0.0),
            "access_token": self._fawry_get_access_token(),
            "pos_emulator_url": pos_emulator_url,
        }

    # === CRON === #

    @api.model
    def _cron_fawry_sync_pending(self):
        """Check the status of unfinished Fawry payments, in case a notification was missed.

        Pending payments (reference codes, wallet requests...) are checked for 10 days, payments
        the customer never came back from for 2 days. Those checked the longest ago go first.
        """
        now = fields.Datetime.now()
        online_operations = ("online_redirect", "online_direct", "online_token")
        txs = self.search(
            Domain("provider_code", "=", "fawry")
            & Domain("operation", "in", online_operations)
            & (
                Domain("state", "=", "pending") & Domain("create_date", ">=", now - timedelta(days=10))
                | Domain("state", "=", "draft") & Domain("create_date", ">=", now - timedelta(days=2))
            ),
            order="fawry_last_sync asc nulls first, id asc",
            limit=200,
        )
        in_cron = bool(self.env.context.get("ir_cron_progress_id"))
        if in_cron:
            self.env["ir.cron"]._commit_progress(remaining=len(txs))
        for tx in txs:
            tx.with_context(payment_safe_write=True).fawry_last_sync = fields.Datetime.now()
            tx._fawry_sync_from_provider()
            if in_cron and not self.env["ir.cron"]._commit_progress(1):
                break  # The cron ran out of time; the next run continues.

    # === ACTIONS === #

    def action_fawry_sync(self):
        """Fetch the latest status of the payment from Fawry."""
        self.ensure_one()
        payment_utils.check_rights_on_recordset(self)
        tx_sudo = self.sudo()  # In sudo mode to use the provider's credentials.
        if not tx_sudo._fawry_sync_from_provider():
            raise UserError(self.env._("Fawry has no order for this payment yet."))
        return self._fawry_get_notification_action(
            self.env._("Fawry sent the latest status of the payment."),
        )

    def action_fawry_cancel(self):
        """Cancel the unpaid Fawry order of the payment."""
        self.ensure_one()
        payment_utils.check_rights_on_recordset(self)
        self.sudo()._fawry_cancel_unpaid()  # In sudo mode to use the provider's credentials.
        return self._fawry_get_notification_action(
            self.env._("The payment was canceled at Fawry."),
        )

    def action_fawry_pay_at_pos_emulator(self):
        """Open the page that pays the reference code of a test payment at Fawry's POS Emulator."""
        self.ensure_one()
        payment_utils.check_rights_on_recordset(self)
        if not self.fawry_can_use_pos_emulator:
            raise UserError(self.env._(
                "Only the unpaid reference codes of test payments can be paid at Fawry's POS "
                "Emulator.",
            ))
        return {
            "type": "ir.actions.act_url",
            "url": self._fawry_get_pos_emulator_page_url(),
            "target": "new",
        }

    def _fawry_get_pos_emulator_page_url(self):
        """Return the URL of the page that pays the reference code at Fawry's POS Emulator."""
        self.ensure_one()
        return f"{FawryController._pos_emulator_url}/{self.id}"

    def _fawry_get_notification_action(self, message):
        """Return a notification for a status recorded by an action.

        The recorded status is applied by the payment processing cron once the action's
        transaction is committed, so it can't be applied (and shown) within the action itself.
        """
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": self.env._(
                    "%(message)s The payment is updated within a few seconds; reload the page to "
                    "see it.",
                    message=message,
                ),
                "sticky": False,
            },
        }
