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

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import urls

from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_fawry_cf import const
from odoo.addons.payment_fawry_cf import utils as fawry_utils
from odoo.addons.payment_fawry_cf.controllers.main import FawryController

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
            raise ValidationError(
                self.env._(
                    "Fawry rejected the request: %(message)s (code %(code)s)",
                    message=content.get("statusDescription") or "",
                    code=status_code,
                ),
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
        message = content.get("description") or content.get("statusDescription") or response.text
        code = content.get("code") or content.get("statusCode")
        return f"{message} (code {code})" if code else message

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
        except ValidationError as error:
            if f"(code {const.ORDER_NOT_FOUND_CODE})" in str(error):
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

    def _fawry_is_own_url(self, url):
        """Return whether a URL points to the Fawry environment of the provider.

        Used before redirecting the customer to a URL received from Fawry.
        """
        self.ensure_one()
        return bool(url) and url.startswith(f"{self._fawry_get_base_url()}/")
