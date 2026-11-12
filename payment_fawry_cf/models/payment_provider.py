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
import json
import time

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import urls

from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_fawry_cf import const
from odoo.addons.payment_fawry_cf import utils as fawry_utils
from odoo.addons.payment_fawry_cf.controllers.main import FawryController
from odoo.addons.payment_fawry_cf.exceptions import FawryError

_logger = get_payment_logger(__name__, const.SENSITIVE_KEYS)


class PaymentProvider(models.Model):
    _inherit = "payment.provider"

    code = fields.Selection(selection_add=[("fawry", "Fawry")], ondelete={"fawry": "set default"})
    fawry_merchant_code = fields.Char(
        string="Fawry Merchant Code",
        help="The merchant code (account number) that Fawry sent when your account was created.",
        required_if_provider="fawry",
        copy=False,
    )
    fawry_secure_key = fields.Char(
        string="Fawry Secure Key",
        help="The secure hash key used to sign every request sent to Fawry.",
        required_if_provider="fawry",
        copy=False,
        groups="base.group_system",
    )
    fawry_integration = fields.Selection(
        string="Fawry Integration",
        help="FawryPay Express Checkout: customers pay on Fawry's hosted checkout.\n"
        "Server-to-Server APIs: cards are saved on Fawry's secure card page and charged by Odoo "
        "with 3-D Secure, and Fawry reference codes, mobile wallets and myFawry are created by "
        "Odoo and shown on your website. Other methods always use the hosted checkout.",
        selection=[
            (const.INTEGRATION_EXPRESS, "FawryPay Express Checkout"),
            (const.INTEGRATION_S2S, "Server-to-Server APIs"),
        ],
        default=const.INTEGRATION_EXPRESS,
        required_if_provider="fawry",
    )
    fawry_display_mode = fields.Selection(
        string="Checkout Display",
        help="How Fawry's hosted checkout is shown to the customer. Apple devices always open it "
        "in a full page, as Fawry requires.",
        selection=[
            ("redirect", "Full page"),
            ("popup", "Pop-up window"),
            ("side_page", "Side panel"),
        ],
        default="redirect",
        required_if_provider="fawry",
    )
    fawry_payment_expiry_hours = fields.Integer(
        string="Payment Expiry (Hours)",
        help="How long a Fawry reference code, wallet request or QR code stays payable.",
        default=48,
    )
    fawry_webhook_url = fields.Char(
        string="Notification URL",
        help="Give this URL to Fawry so that they send the payment notifications to Odoo. Odoo "
        "also sends it with every payment.",
        compute="_compute_fawry_webhook_url",
    )
    fawry_bank_installments = fields.Boolean(
        string="Bank Installments",
        help="Let customers pay by card in monthly installments, with the plans that Fawry "
        "activated on your account for their bank. After entering the card, the customer chooses "
        "to pay in full or with one of the plans available for the card and the amount. "
        "Server-to-Server APIs only.",
    )
    fawry_payment_split = fields.Boolean(
        string="Payment Split",
        help="Share each payment between your Fawry account and sub-accounts created in Fawry's "
        "dashboard. Fawry pays the share of each sub-account to its own bank account.",
    )
    fawry_split_account_ids = fields.One2many(
        string="Split Sub-Accounts",
        comodel_name="payment.fawry.split.account",
        inverse_name="provider_id",
        context={"active_test": False},
    )

    # === COMPUTE METHODS === #

    @api.depends("code", "fawry_integration")
    def _compute_feature_support_fields(self):
        """Override of `payment` to enable the features supported by Fawry.

        Cards can only be saved through the server-to-server integration, as Fawry's hosted
        checkout doesn't hand the card token back to the merchant.
        """
        super()._compute_feature_support_fields()
        for provider in self.filtered(lambda p: p.code == "fawry"):
            provider.update({
                "support_refund": "partial",
                "support_tokenization": provider.fawry_integration == const.INTEGRATION_S2S,
            })

    def _compute_fawry_webhook_url(self):
        for provider in self:
            provider.fawry_webhook_url = urls.urljoin(
                provider.get_base_url(), FawryController._webhook_url,
            )

    # === CRUD METHODS === #

    @api.model_create_multi
    def create(self, vals_list):
        providers = super().create(vals_list)
        providers._fawry_check_tokenization_mode()
        return providers

    def write(self, vals):
        provider = self
        if {"is_live", "active"} & set(vals):
            # The tokens archived by `payment` keep their cards at Fawry (see payment.token).
            provider = self.with_context(fawry_keep_cards=True)
        res = super(PaymentProvider, provider).write(vals)
        if "fawry_integration" in vals or "allow_tokenization" in vals:
            # Other providers' overrides may declare fewer dependencies for the feature fields.
            self.invalidate_recordset(["support_tokenization"])
            self._fawry_check_tokenization_mode()
        return res

    def _fawry_check_tokenization_mode(self):
        """Turn off card saving when the hosted checkout is used, as it can't save cards."""
        providers_to_update = self.filtered(
            lambda p: p.code == "fawry"
            and p.fawry_integration != const.INTEGRATION_S2S
            and p.allow_tokenization,
        )
        if providers_to_update:
            providers_to_update.allow_tokenization = False

    def _get_default_payment_method_codes(self):
        """Override of `payment` to return the default payment method codes."""
        self.ensure_one()
        if self.code != "fawry":
            return super()._get_default_payment_method_codes()
        return const.DEFAULT_PAYMENT_METHOD_CODES

    def _get_supported_currencies(self):
        """Override of `payment` to return EGP, the only currency Fawry processes."""
        supported_currencies = super()._get_supported_currencies()
        if self.code == "fawry":
            supported_currencies = supported_currencies.filtered(lambda c: c.name == "EGP")
        return supported_currencies

    def _get_reset_values(self):
        """Override of `payment` to reset the Fawry credentials."""
        reset_values = super()._get_reset_values()
        if self.code == "fawry":
            reset_values.update({"fawry_merchant_code": None, "fawry_secure_key": None})
        return reset_values

    # === ACTION METHODS === #

    def action_fawry_test_connection(self):
        """Check the credentials by asking Fawry for the status of an order that doesn't exist.

        Fawry answers "order not found" when the merchant code and the signature are valid, and a
        validation error otherwise.
        """
        self.ensure_one()
        if not (self.fawry_merchant_code and self.fawry_secure_key):
            raise UserError(self.env._("Enter the merchant code and the secure key first."))
        try:
            self._fawry_get_payment_status("ODOO-CONNECTION-TEST")
        except ValidationError as error:
            raise UserError(
                self.env._("Fawry rejected the credentials.\n%(error)s", error=error),
            ) from None
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": self.env._("Connection successful"),
                "message": self.env._(
                    "Fawry accepted the merchant code and the secure key (%(env)s environment).",
                    env=self.env._("live") if self.is_live else self.env._("test"),
                ),
                "sticky": False,
            },
        }

    def action_fawry_open_pos_emulator(self):
        """Open Fawry's POS Emulator, which pays the reference codes of test payments."""
        self.ensure_one()
        if self.is_live:
            raise UserError(self.env._(
                "Fawry's POS Emulator only pays the reference codes of test payments. Use it while "
                "the provider is in test mode.",
            ))
        return {"type": "ir.actions.act_url", "url": const.POS_EMULATOR_URL, "target": "new"}

    def action_fawry_show_installment_plans(self):
        """Show the installment plans that Fawry activated on the merchant account."""
        self.ensure_one()
        if not (self.fawry_merchant_code and self.fawry_secure_key):
            raise UserError(self.env._("Enter the merchant code and the secure key first."))
        try:
            plans = self._fawry_get_installment_plans()
        except ValidationError as error:
            raise UserError(str(error)) from None
        if plans:
            notification_type = "info"
            message = "\n".join(self._fawry_describe_installment_plan(plan) for plan in plans)
        else:
            notification_type = "warning"
            message = self.env._(
                "Fawry has no active installment plan on this account. Ask Fawry to activate the "
                "plans of the banks you work with.",
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": notification_type,
                "title": self.env._("Fawry installment plans"),
                "message": message,
                "sticky": True,
            },
        }

    # === BUSINESS METHODS - ACCOUNTING === #

    @api.model
    def _fawry_setup_journals(self, companies=None):
        """Give the Fawry provider of each company its own "Fawry Pay" bank journal, in EGP.

        The journal is created once per company, then reused: it is found by its code. Companies
        without a chart of accounts are skipped; they get the journal when a chart is installed
        (see `account.chart.template._post_load_data`).

        :param res.company companies: The companies to set up; all companies by default.
        :rtype: None
        """
        domain = [("code", "=", "fawry")]
        if companies is not None:
            domain.append(("company_id", "in", companies.ids))
        for provider in self.sudo().with_context(active_test=False).search(domain):
            company = provider.company_id
            if not company.chart_template:
                continue  # Accounting isn't set up yet.
            journal = provider._fawry_get_or_create_journal()
            if journal and provider.journal_id != journal:
                provider.journal_id = journal

    def _fawry_get_or_create_journal(self):
        """Return the company's "Fawry Pay" journal, created if needed.

        :return: The bank journal, or an empty recordset if another kind of journal already uses
                 the code.
        :rtype: account.journal
        """
        self.ensure_one()
        Journal = self.env["account.journal"].sudo().with_context(lang="en_US")
        company = self.company_id
        journal = Journal.search(
            [("company_id", "=", company.id), ("code", "=", const.JOURNAL_CODE)], limit=1,
        )
        if journal:
            if journal.type != "bank":
                _logger.warning(
                    "Journal %s of company %s isn't a bank journal: Fawry payments keep the "
                    "provider's journal.",
                    const.JOURNAL_CODE,
                    company.name,
                )
                return Journal
            return journal

        currency = self.env.ref(const.JOURNAL_CURRENCY_XMLID).sudo()
        if not currency.active:
            currency.active = True
        journal = Journal.with_company(company).create({
            "name": const.JOURNAL_NAME,
            "code": const.JOURNAL_CODE,
            "type": "bank",
            "currency_id": currency.id,
            "company_id": company.id,
        })
        translations = {
            lang_code: const.JOURNAL_NAME_TRANSLATIONS[lang_code.split("_")[0]]
            for lang_code, _name in self.env["res.lang"].get_installed()
            if lang_code.split("_")[0] in const.JOURNAL_NAME_TRANSLATIONS
        }
        if translations:
            journal.update_field_translations("name", translations)
        _logger.info("Created the Fawry Pay journal of company %s.", company.name)
        return journal

    # === BUSINESS METHODS - FLOWS === #

    def _fawry_get_flow(self, payment_method_code, is_validation=False):
        """Return how a payment with the given method is processed.

        :param str payment_method_code: The code of the payment method (a primary method).
        :param bool is_validation: Whether the operation saves a payment method without paying.
        :return: One of the `FLOW_*` constants.
        :rtype: str
        """
        self.ensure_one()
        if self.fawry_integration == const.INTEGRATION_S2S:
            if payment_method_code == "card" or is_validation:
                return const.FLOW_CARD_TOKEN
            if payment_method_code in const.S2S_CHARGE_METHOD_CODES:
                return const.FLOW_S2S_CHARGE
        return const.FLOW_HOSTED

    def _fawry_get_inline_form_values(self, payment_method_code, is_validation=False):
        """Return the values the payment form needs to process the given method.

        :param str payment_method_code: The code of the payment method.
        :param bool is_validation: Whether the form saves a payment method.
        :return: The JSON-encoded values.
        :rtype: str
        """
        self.ensure_one()
        flow = self._fawry_get_flow(payment_method_code, is_validation=is_validation)
        return json.dumps({
            "flow": flow,
            "display_mode": self.fawry_display_mode if flow == const.FLOW_HOSTED else "redirect",
        })

    def _fawry_get_wallet_prefill(self, partner_id):
        """Return the customer's Egyptian mobile number, to suggest it as their wallet number.

        :param int partner_id: The id of the customer, if known.
        :return: The number as ``01xxxxxxxxx``, or an empty string.
        :rtype: str
        """
        if not partner_id:
            return ""
        partner = self.env["res.partner"].sudo().browse(int(partner_id)).exists()
        if not partner or partner == self.env.ref("base.public_partner"):
            return ""
        return fawry_utils.normalize_mobile(partner.phone)

    # === BUSINESS METHODS - API === #

    def _fawry_get_base_url(self):
        """Return the base URL of the Fawry environment of the provider."""
        self.ensure_one()
        return const.API_URLS["live" if self.is_live else "test"]

    def _fawry_sign(self, *values):
        """Return the Fawry signature of the given values, made with this provider's key."""
        self.ensure_one()
        return fawry_utils.compute_signature(*values, secure_key=self.sudo().fawry_secure_key)

    def _build_request_url(self, endpoint, **kwargs):
        """Override of `payment` to build the request URL."""
        if self.code != "fawry":
            return super()._build_request_url(endpoint, **kwargs)
        return f"{self._fawry_get_base_url()}{endpoint}"

    def _build_request_headers(self, method, endpoint, payload, **kwargs):
        """Override of `payment` to build the request headers."""
        if self.code != "fawry":
            return super()._build_request_headers(method, endpoint, payload, **kwargs)
        return {"Accept": "application/json, text/plain, */*"}

    def _parse_response_content(self, response, **kwargs):
        """Override of `payment` to parse Fawry's responses.

        The checkout initialization returns a plain-text URL and order cancellations return an
        empty body; the other endpoints return JSON. Fawry reports most business errors with an
        HTTP 200 and an error `statusCode` in the body, so they are raised here.

        :raise ValidationError: If the body holds a business error.
        """
        if self.code != "fawry":
            return super()._parse_response_content(response, **kwargs)
        if not response.text.strip():
            return {}
        if "json" not in response.headers.get("Content-Type", ""):
            return response.text.strip()
        content = response.json()
        if not isinstance(content, dict):
            return content
        status_code = str(content.get("statusCode", 200))
        if status_code != "200":
            description = content.get("statusDescription") or ""
            raise FawryError(
                self._fawry_get_error_message(status_code, description),
                code=status_code,
                description=description,
            )
        return content

    def _parse_response_error(self, response):
        """Override of `payment` to extract the error message from Fawry's error bodies.

        Fawry answers errors either with `{"code", "reason", "description"}` or with
        `{"statusCode", "statusDescription"}`.
        """
        if self.code != "fawry":
            return super()._parse_response_error(response)
        content = response.json()
        description = (
            content.get("description") or content.get("statusDescription") or response.text
        )
        code = content.get("code") or content.get("statusCode")
        # Raised here, so that the code of the error reaches the caller.
        raise FawryError(
            self._fawry_get_error_message(code, description), code=code, description=description,
        )

    def _fawry_get_error_message(self, code, description=None):
        """Explain an error returned by Fawry, for the staff.

        :param str code: The error code sent by Fawry.
        :param str description: The description sent by Fawry.
        :return: What the error means, with its code.
        :rtype: str
        """
        code = str(code or "")
        if entry := const.ERROR_CODES.get(code):
            return self.env._(
                "%(explanation)s (Fawry code %(code)s)",
                explanation=self.env._(entry[1]),
                code=code,
            )
        if code:
            return self.env._(
                "Fawry refused the request: %(description)s (Fawry code %(code)s)",
                description=description or self.env._("no details given"),
                code=code,
            )
        return description or self.env._("Fawry refused the request.")

    def _fawry_get_customer_error_message(self, code, description=None):  # noqa: ARG002
        """Explain an error returned by Fawry, for the customer.

        Errors about the customer's card or bank are explained as they are. The others are about
        the merchant's account: the customer only learns that the payment failed, with the code to
        give to the merchant.

        :param str code: The error code sent by Fawry.
        :param str description: The description sent by Fawry.
        :return: The message shown to the customer.
        :rtype: str
        """
        code = str(code or "")
        kind, explanation = const.ERROR_CODES.get(code, (None, None))
        if kind == const.ERROR_CUSTOMER:
            return self.env._(explanation)
        if code:
            return self.env._(
                "The payment couldn't be processed. Please try again later or choose another "
                "payment method (error %(code)s).",
                code=code,
            )
        return self.env._(
            "The payment couldn't be processed. Please try again later or choose another payment "
            "method.",
        )

    def _fawry_get_payment_status(self, merchant_reference):
        """Fetch the status of an order from Fawry (Get Payment Status V2).

        :param str merchant_reference: The reference of the order in Odoo.
        :return: The status payload, or `None` if Fawry doesn't know the order.
        :rtype: dict | None
        :raise ValidationError: If the request fails for another reason.
        """
        self.ensure_one()
        params = {
            "merchantCode": self.fawry_merchant_code,
            "merchantRefNumber": merchant_reference,
            "signature": self._fawry_sign(self.fawry_merchant_code, merchant_reference),
        }
        try:
            return self._send_api_request(
                "GET", const.ENDPOINT_STATUS, params=params, reference=merchant_reference,
            )
        except FawryError as error:
            if error.code == const.ORDER_NOT_FOUND_CODE:
                return None
            raise

    def _fawry_list_card_tokens(self, customer_profile_id):
        """Fetch the cards saved at Fawry for a customer.

        :param str customer_profile_id: The customer profile id the cards were saved under.
        :return: The saved cards, as returned by Fawry.
        :rtype: list[dict]
        :raise ValidationError: If the request fails.
        """
        self.ensure_one()
        params = {
            "merchantCode": self.fawry_merchant_code,
            "customerProfileId": customer_profile_id,
            "signature": self._fawry_sign(self.fawry_merchant_code, customer_profile_id),
        }
        response = self._send_api_request("GET", const.ENDPOINT_CARD_TOKENS, params=params)
        return response.get("cards") or []

    def _fawry_delete_card_token(self, customer_profile_id, card_token):
        """Delete a card saved at Fawry.

        :param str customer_profile_id: The customer profile id the card was saved under.
        :param str card_token: The card token.
        :rtype: None
        :raise ValidationError: If the request fails.
        """
        self.ensure_one()
        params = {
            "merchantCode": self.fawry_merchant_code,
            "customerProfileId": customer_profile_id,
            "cardToken": card_token,
            "signature": self._fawry_sign(
                self.fawry_merchant_code, customer_profile_id, card_token,
            ),
        }
        self._send_api_request("DELETE", const.ENDPOINT_CARD_TOKENS, params=params)

    def _fawry_get_card_token_url(self, customer_profile_id, return_url, lang_code):
        """Return the URL of Fawry's secure page where the customer saves a card.

        :param str customer_profile_id: The customer profile id to save the card under.
        :param str return_url: Where Fawry redirects the customer, with the card token.
        :param str lang_code: The customer's language.
        :return: The URL, without its query string, and its query parameters.
        :rtype: tuple[str, dict]
        """
        self.ensure_one()
        url = f"{self._fawry_get_base_url()}{const.CARD_TOKEN_PLUGIN_PATH}"
        params = {
            "accNo": self.fawry_merchant_code,
            "customerProfileId": customer_profile_id,
            "returnUrl": return_url,
            "locale": fawry_utils.get_fawry_locale(lang_code),
        }
        return url, params

    # === BUSINESS METHODS - BANK INSTALLMENTS === #

    def _fawry_get_installment_plans(self):
        """Fetch the installment plans that Fawry activated on the merchant account.

        Fawry only returns the active plans; the request isn't signed.

        :return: The plans, each as a dict with the keys `id`, `name_en`, `name_ar`, `months`,
                 `rate`, `min_amount`, `max_amount`, `start` and `end` (in ms), `online`,
                 `status`, `bins` (the card prefixes the plan accepts), `bank_en`, `bank_ar`,
                 `apply_to` and `product_codes`.
        :rtype: list[dict]
        :raise ValidationError: If the request fails.
        """
        self.ensure_one()
        content = self._send_api_request(
            "GET",
            const.ENDPOINT_INSTALLMENT_PLANS,
            params={"accountNumber": self.fawry_merchant_code},
        )
        if isinstance(content, dict):  # Fawry's documentation shows a single plan.
            content = [content] if content.get("installmentPlan") else []
        plans = []
        for entry in content if isinstance(content, list) else []:
            plan = isinstance(entry, dict) and entry.get("installmentPlan")
            if not isinstance(plan, dict) or plan.get("id") is None:
                continue
            account_type = plan.get("accountType") or {}
            bank = account_type.get("bank") or {}
            product_codes = (entry.get("products") or []) + (entry.get("productsCodes") or [])
            plans.append({
                "id": plan["id"],
                "name_en": plan.get("nameEn") or "",
                "name_ar": plan.get("nameAr") or plan.get("nameEn") or "",
                "months": plan.get("noOfMonths") or 0,
                "rate": plan.get("rate") or 0.0,
                "min_amount": plan.get("minAmount"),
                "max_amount": plan.get("maxAmount"),
                "start": plan.get("startDate"),
                "end": plan.get("endDate"),
                "online": plan.get("online", True),
                "status": str((plan.get("status") or {}).get("code") or "ACTIVE").upper(),
                "bins": [str(pan) for pan in account_type.get("pans") or [] if pan],
                "bank_en": account_type.get("nameEn") or bank.get("nameEn") or "",
                "bank_ar": account_type.get("nameAr") or bank.get("nameAr") or "",
                "apply_to": str(entry.get("applyTo") or "ANY_PRODUCT").upper(),
                "product_codes": [
                    str(code.get("code") or code.get("sku") or "") if isinstance(code, dict)
                    else str(code)
                    for code in product_codes
                ],
            })
        return plans

    def _fawry_get_eligible_installment_plans(self, amount, card_bin, product_codes=None):
        """Return the installment plans with which a card can pay an amount.

        A plan is eligible when it is active and online, in its validity period, when the amount
        is within its limits, when the card starts with one of its prefixes, and, for the plans
        limited to some products, when every product paid is one of them.

        :param float amount: The amount to pay.
        :param str card_bin: The first six digits of the card.
        :param list product_codes: The internal references of the products paid.
        :return: The eligible plans, by number of months.
        :rtype: list[dict]
        """
        self.ensure_one()
        if not (
            self.code == "fawry"
            and self.fawry_bank_installments
            and self.fawry_integration == const.INTEGRATION_S2S
            and card_bin
        ):
            return []
        try:
            plans = self._fawry_get_installment_plans()
        except ValidationError as error:
            _logger.warning("Unable to fetch the Fawry installment plans: %s", error)
            return []
        card_bin = str(card_bin)
        now = int(time.time() * 1000)
        eligible = []
        for plan in plans:
            if plan["status"] != "ACTIVE" or not plan["online"] or plan["months"] < 1:
                continue
            if (plan["start"] and now < plan["start"]) or (plan["end"] and now > plan["end"]):
                continue
            if plan["min_amount"] is not None and amount < plan["min_amount"]:
                continue
            if plan["max_amount"] is not None and amount > plan["max_amount"]:
                continue
            if plan["bins"] and not any(
                card_bin.startswith(pan) or pan.startswith(card_bin) for pan in plan["bins"]
            ):
                continue
            if plan["apply_to"] != "ANY_PRODUCT" and not (
                product_codes and set(product_codes) <= set(plan["product_codes"])
            ):
                continue
            eligible.append(plan)
        return sorted(eligible, key=lambda plan: (plan["months"], plan["rate"]))

    def _fawry_get_installment_plan_label(self, plan):
        """Return the name of an installment plan in the current language."""
        is_arabic = (self.env.lang or "").startswith("ar")
        name = (plan["name_ar"] if is_arabic else plan["name_en"]) or plan["name_en"]
        bank = (plan["bank_ar"] if is_arabic else plan["bank_en"]) or plan["bank_en"]
        return f"{name} ({bank})" if bank and bank not in name else name

    def _fawry_describe_installment_plan(self, plan):
        """Describe an installment plan for the staff."""
        return self.env._(
            "%(name)s: %(months)s months, rate %(rate)s%%, from %(min)s to %(max)s, plan %(id)s",
            name=self._fawry_get_installment_plan_label(plan),
            months=plan["months"],
            rate=plan["rate"],
            min=plan["min_amount"] if plan["min_amount"] is not None else "-",
            max=plan["max_amount"] if plan["max_amount"] is not None else "-",
            id=plan["id"],
        )

    def _fawry_is_own_url(self, url):
        """Return whether a URL points to the Fawry environment of the provider.

        Used before redirecting the customer to a URL received from Fawry.
        """
        self.ensure_one()
        return bool(url) and url.startswith(f"{self._fawry_get_base_url()}/")
