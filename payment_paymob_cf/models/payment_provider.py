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
import hmac
import json
import time
from urllib.parse import urlencode

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import urls

from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_paymob_cf import const
from odoo.addons.payment_paymob_cf import utils as paymob_utils
from odoo.addons.payment_paymob_cf.controllers.main import PaymobController
from odoo.addons.payment_paymob_cf.exceptions import PaymobError

_logger = get_payment_logger(__name__, const.SENSITIVE_KEYS)

# Bearer tokens of Paymob's APIs, by database, provider and API key. Each worker keeps its own:
# a token is cheap to get and lasts an hour, and storing it would write the provider on every
# status check.
_AUTH_TOKENS = {}


class PaymentProvider(models.Model):
    _inherit = "payment.provider"

    code = fields.Selection(
        selection_add=[("paymob_cf", "Paymob")], ondelete={"paymob_cf": "set default"},
    )
    paymob_cf_country = fields.Selection(
        string="Paymob Country",
        help="The country of your Paymob account. Each country has its own Paymob platform and "
        "currency: Egypt (EGP), Saudi Arabia (SAR), United Arab Emirates (AED), Oman (OMR) and "
        "Pakistan (PKR).",
        selection=[
            ("EG", "Egypt"),
            ("SA", "Saudi Arabia"),
            ("AE", "United Arab Emirates"),
            ("OM", "Oman"),
            ("PK", "Pakistan"),
        ],
        default=const.DEFAULT_COUNTRY,
        required_if_provider="paymob_cf",
    )
    paymob_cf_secret_key = fields.Char(
        string="Secret Key",
        help="Paymob dashboard: Settings > Developers > API Keys. Test and live accounts have "
        "different secret keys.",
        required_if_provider="paymob_cf",
        copy=False,
        groups="base.group_system",
    )
    paymob_cf_public_key = fields.Char(
        string="Public Key",
        help="Paymob dashboard: Settings > Developers > API Keys. It opens Paymob's checkout and "
        "card form in the customer's browser.",
        required_if_provider="paymob_cf",
        copy=False,
    )
    paymob_cf_api_key = fields.Char(
        string="API Key",
        help="Paymob dashboard: Settings > Developers > API Keys. Used to check the status of "
        "payments and to list your integrations.",
        required_if_provider="paymob_cf",
        copy=False,
        groups="base.group_system",
    )
    paymob_cf_hmac_secret = fields.Char(
        string="HMAC Secret",
        help="Paymob dashboard: Settings > Developers > API Keys (main user only). Odoo checks "
        "every notification and redirection of Paymob with it.",
        required_if_provider="paymob_cf",
        copy=False,
        groups="base.group_system",
    )
    paymob_cf_integration = fields.Selection(
        string="Paymob Integration",
        help="Paymob Checkout: customers pay every method on Paymob's hosted checkout.\n"
        "Embedded checkout: cards are entered in Paymob's card form, embedded in your website; "
        "cards can be saved, captured manually and charged again. Other methods use Paymob "
        "Checkout.",
        selection=[
            (const.INTEGRATION_HOSTED, "Paymob Checkout"),
            (const.INTEGRATION_EMBEDDED, "Embedded checkout"),
        ],
        default=const.INTEGRATION_HOSTED,
        required_if_provider="paymob_cf",
    )
    paymob_cf_display_mode = fields.Selection(
        string="Checkout Display",
        help="How Paymob Checkout is shown to the customer.",
        selection=[
            ("redirect", "Full page"),
            ("popup", "Pop-up window"),
            ("side_page", "Side panel"),
        ],
        default="redirect",
        required_if_provider="paymob_cf",
    )
    paymob_cf_payment_expiry_hours = fields.Integer(
        string="Payment Expiry (Hours)",
        help="How long a payment can be completed, e.g. a kiosk reference paid in cash. Paymob "
        "accepts up to 864 hours (36 days).",
        default=48,
    )
    paymob_cf_webhook_url = fields.Char(
        string="Notification URL",
        help="Odoo sends it with every payment. You can also set it as the Transaction "
        "processed callback of each integration in Paymob's dashboard.",
        compute="_compute_paymob_cf_webhook_url",
    )
    paymob_cf_auth_integration_id = fields.Integer(
        string="Auth Integration ID",
        help="The card integration of type Auth, for payments captured manually. Ask Paymob to "
        "create it.",
    )
    paymob_cf_moto_integration_id = fields.Integer(
        string="MOTO Integration ID",
        help="The card integration of type MOTO, to charge saved cards while the customer is away "
        "(e.g. subscriptions). Ask Paymob to create it.",
    )
    paymob_cf_verification_integration_id = fields.Integer(
        string="Verification Integration ID",
        help="The card integration of type Verification, for customers who save a card without "
        "paying (My Account > Payment Methods). Ask Paymob to create it.",
    )
    paymob_cf_payment_split = fields.Boolean(
        string="Payment Split",
        help="Share each payment with the merchants connected to your Paymob account. Paymob "
        "pays each one its share; the rest is yours.",
    )
    paymob_cf_split_merchant_ids = fields.One2many(
        string="Connected Merchants",
        comodel_name="payment.paymob.split.merchant",
        inverse_name="provider_id",
        context={"active_test": False},
    )

    # === COMPUTE METHODS === #

    @api.depends("code", "paymob_cf_integration")
    def _compute_feature_support_fields(self):
        """Override of `payment` to enable the features supported by Paymob.

        Cards are saved by Paymob's embedded card form only, where Odoo decides whether the card is
        saved; Paymob Checkout shows its own checkbox. Manual capture uses an Auth integration.
        """
        super()._compute_feature_support_fields()
        for provider in self.filtered(lambda p: p.code == "paymob_cf"):
            provider.update({
                "support_refund": "partial",
                "support_manual_capture": "partial",
                "support_tokenization": provider.paymob_cf_integration == const.INTEGRATION_EMBEDDED,
            })

    def _compute_paymob_cf_webhook_url(self):
        for provider in self:
            provider.paymob_cf_webhook_url = urls.urljoin(
                provider.get_base_url(), PaymobController._webhook_url,
            )

    # === CONSTRAINT METHODS === #

    @api.constrains("capture_manually", "paymob_cf_auth_integration_id", "code")
    def _check_paymob_cf_manual_capture(self):
        for provider in self.filtered(lambda p: p.code == "paymob_cf" and p.capture_manually):
            if not provider.paymob_cf_auth_integration_id:
                raise ValidationError(self.env._(
                    "Paymob captures card payments manually with an Auth integration. Enter its "
                    "ID in the Auth Integration ID field first.",
                ))

    @api.constrains("paymob_cf_payment_expiry_hours")
    def _check_paymob_cf_payment_expiry(self):
        for provider in self.filtered(lambda p: p.code == "paymob_cf"):
            if not 1 <= provider.paymob_cf_payment_expiry_hours <= 864:
                raise ValidationError(self.env._(
                    "The payment expiry must be between 1 and 864 hours (36 days).",
                ))

    # === CRUD METHODS === #

    @api.model_create_multi
    def create(self, vals_list):
        providers = super().create(vals_list)
        providers._paymob_cf_check_tokenization_mode()
        providers.filtered(lambda p: p.code == "paymob_cf")._paymob_cf_apply_country()
        return providers

    def write(self, vals):
        res = super().write(vals)
        if "paymob_cf_integration" in vals or "allow_tokenization" in vals:
            # Other providers' overrides may declare fewer dependencies for the feature fields.
            self.invalidate_recordset(["support_tokenization"])
            self._paymob_cf_check_tokenization_mode()
        if "paymob_cf_country" in vals or vals.get("code") == "paymob_cf":
            self.filtered(lambda p: p.code == "paymob_cf")._paymob_cf_apply_country()
        return res

    def _paymob_cf_check_tokenization_mode(self):
        """Turn off card saving when Paymob Checkout is used: Odoo can't choose to save the card
        there.
        """
        providers_to_update = self.filtered(
            lambda p: p.code == "paymob_cf"
            and p.paymob_cf_integration != const.INTEGRATION_EMBEDDED
            and p.allow_tokenization,
        )
        if providers_to_update:
            providers_to_update.allow_tokenization = False

    def _paymob_cf_apply_country(self):
        """Give each provider the currency of its Paymob country, and its journal that currency.

        The currency is activated if needed. The journal created by the module only changes
        currency while it has no entries.
        """
        for provider in self:
            currency = provider._paymob_cf_get_currency()
            if not currency:
                continue
            if provider.available_currency_ids != currency:
                provider.available_currency_ids = currency
            journal = provider.sudo().journal_id
            if (
                journal
                and journal.code == const.JOURNAL_CODE
                and journal.currency_id != currency
                and not self.env["account.move.line"].sudo().search_count(
                    [("journal_id", "=", journal.id)], limit=1,
                )
            ):
                journal.currency_id = currency

    def _get_default_payment_method_codes(self):
        """Override of `payment` to return the default payment method codes."""
        self.ensure_one()
        if self.code != "paymob_cf":
            return super()._get_default_payment_method_codes()
        return const.DEFAULT_PAYMENT_METHOD_CODES

    def _get_supported_currencies(self):
        """Override of `payment` to return the currency of the provider's Paymob country."""
        supported_currencies = super()._get_supported_currencies()
        if self.code == "paymob_cf":
            currency_code = const.COUNTRIES[self.paymob_cf_country or const.DEFAULT_COUNTRY][
                "currency"
            ]
            supported_currencies = supported_currencies.filtered(
                lambda c: c.name == currency_code,
            )
        return supported_currencies

    def _get_reset_values(self):
        """Override of `payment` to reset the Paymob credentials."""
        reset_values = super()._get_reset_values()
        if self.code == "paymob_cf":
            reset_values.update({
                "paymob_cf_secret_key": None,
                "paymob_cf_public_key": None,
                "paymob_cf_api_key": None,
                "paymob_cf_hmac_secret": None,
            })
        return reset_values

    @api.model
    def _find_available_providers(self, *args, is_validation=False, report=None, **kwargs):
        """Override of `payment` to only offer Paymob for saving a card without paying when a
        Verification integration is set.
        """
        providers = super()._find_available_providers(
            *args, is_validation=is_validation, report=report, **kwargs,
        )
        if is_validation:
            unfit_providers = providers.filtered(
                lambda p: p.code == "paymob_cf" and not p.paymob_cf_verification_integration_id,
            )
            providers -= unfit_providers
        return providers

    # === ACTION METHODS === #

    def action_paymob_cf_test_connection(self):
        """Check the API key, then list the integrations of the account to check the secret key
        is entered.
        """
        self.ensure_one()
        provider = self.sudo()
        if not (provider.paymob_cf_api_key and provider.paymob_cf_secret_key):
            raise UserError(self.env._("Enter the secret key and the API key first."))
        try:
            integrations = self._paymob_cf_get_integrations()
        except ValidationError as error:
            raise UserError(
                self.env._("Paymob rejected the connection.\n%(error)s", error=error),
            ) from None
        return self._paymob_cf_notification(
            self.env._("Connection successful"),
            self.env._(
                "Paymob accepted the API key (%(country)s, %(env)s mode) and has %(count)s "
                "integrations in this mode.",
                country=dict(self._fields["paymob_cf_country"]._description_selection(self.env))[
                    self.paymob_cf_country
                ],
                env=self.env._("live") if self.is_live else self.env._("test"),
                count=len(integrations),
            ),
        )

    def action_paymob_cf_sync_integrations(self):
        """Fill the integration IDs of the payment methods from Paymob, by gateway type.

        Nothing is changed at Paymob. For each method, the newest integration of its gateway type
        in the provider's mode (test or live) is used; card integrations of type Auth, MOTO or
        Verification fill the matching fields of the provider.
        """
        self.ensure_one()
        try:
            integrations = self._paymob_cf_get_integrations()
        except ValidationError as error:
            raise UserError(str(error)) from None
        matches, special = self._paymob_cf_match_integrations(integrations)

        methods = self.with_context(active_test=False).payment_method_ids
        updated = []
        for method in methods:
            integration_id = matches.get(method.code)
            if integration_id and method.paymob_cf_integration_id != integration_id:
                method.paymob_cf_integration_id = integration_id
                updated.append(f"{method.name}: {integration_id}")
        for field_name, integration_id in special.items():
            if integration_id and self[field_name] != integration_id:
                self[field_name] = integration_id
                label = self._fields[field_name].get_description(self.env)["string"]
                updated.append(f"{label}: {integration_id}")
        missing = [
            method.name
            for method in methods.filtered(
                lambda m: m.active and not m.primary_payment_method_id
                and m.code != const.ALL_METHODS_CODE and not m.paymob_cf_integration_id,
            )
        ]
        message = self.env._("Integration IDs set:\n%s", "\n".join(updated)) if updated else (
            self.env._("The integration IDs were already up to date.")
        )
        if missing:
            message += "\n" + self.env._(
                "No integration found for: %s. Enter their IDs on the payment methods, or ask "
                "Paymob to enable them.",
                ", ".join(missing),
            )
        return self._paymob_cf_notification(
            self.env._("Paymob integrations"), message,
            notification_type="warning" if missing else "success", sticky=bool(missing),
        )

    def _paymob_cf_notification(self, title, message, notification_type="success", sticky=False):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": notification_type,
                "title": title,
                "message": message,
                "sticky": sticky,
            },
        }

    # === BUSINESS METHODS - SETUP === #

    @api.model
    def _paymob_cf_setup_providers(self, companies=None):
        """Set up the Paymob provider of each company: its country, from the company's when Paymob
        serves it, and its own "Paymob" bank journal.

        :param res.company companies: The companies to set up; all companies by default.
        :rtype: None
        """
        domain = [("code", "=", "paymob_cf")]
        if companies is not None:
            domain.append(("company_id", "in", companies.ids))
        for provider in self.sudo().with_context(active_test=False).search(domain):
            company_country = provider.company_id.country_id.code
            if (
                company_country in const.COUNTRIES
                and provider.paymob_cf_country != company_country
                and not provider.paymob_cf_secret_key
            ):
                provider.paymob_cf_country = company_country
            else:
                provider._paymob_cf_apply_country()
            if not provider.company_id.chart_template:
                continue  # Accounting isn't set up yet.
            journal = provider._paymob_cf_get_or_create_journal()
            if journal and provider.journal_id != journal:
                provider.journal_id = journal

    def _paymob_cf_get_currency(self):
        """Return the currency of the provider's Paymob country, activated if needed."""
        self.ensure_one()
        currency_code = const.COUNTRIES[self.paymob_cf_country or const.DEFAULT_COUNTRY]["currency"]
        currency = self.env["res.currency"].sudo().with_context(active_test=False).search(
            [("name", "=", currency_code)], limit=1,
        )
        if currency and not currency.active:
            currency.active = True
        return currency

    def _paymob_cf_get_or_create_journal(self):
        """Return the company's "Paymob" journal, created if needed.

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
                    "Journal %s of company %s isn't a bank journal: Paymob payments keep the "
                    "provider's journal.",
                    const.JOURNAL_CODE,
                    company.name,
                )
                return Journal
            return journal

        journal = Journal.with_company(company).create({
            "name": const.JOURNAL_NAME,
            "code": const.JOURNAL_CODE,
            "type": "bank",
            "currency_id": self._paymob_cf_get_currency().id,
            "company_id": company.id,
        })
        translations = {
            lang_code: const.JOURNAL_NAME_TRANSLATIONS[lang_code.split("_")[0]]
            for lang_code, _name in self.env["res.lang"].get_installed()
            if lang_code.split("_")[0] in const.JOURNAL_NAME_TRANSLATIONS
        }
        if translations:
            journal.update_field_translations("name", translations)
        _logger.info("Created the Paymob journal of company %s.", company.name)
        return journal

    # === BUSINESS METHODS - FLOWS === #

    def _paymob_cf_get_flow(self, payment_method_code):
        """Return how a payment with the given method is processed.

        :param str payment_method_code: The code of the payment method (a primary method).
        :return: One of the `FLOW_*` constants.
        :rtype: str
        """
        self.ensure_one()
        if (
            self.paymob_cf_integration == const.INTEGRATION_EMBEDDED
            and payment_method_code in const.PIXEL_METHODS
        ):
            return const.FLOW_PIXEL
        return const.FLOW_HOSTED

    def _paymob_cf_get_inline_form_values(self, payment_method_code):
        """Return the values the payment form needs to process the given method.

        :param str payment_method_code: The code of the payment method.
        :return: The JSON-encoded values.
        :rtype: str
        """
        self.ensure_one()
        flow = self._paymob_cf_get_flow(payment_method_code)
        return json.dumps({
            "flow": flow,
            "display_mode": self.paymob_cf_display_mode if flow == const.FLOW_HOSTED else "inline",
        })

    def _paymob_cf_get_integration_ids(self, payment_method, capture_manually=False,
                                       is_validation=False, is_moto=False):
        """Return the Paymob integrations a payment with the given method may use.

        :param payment.method payment_method: The payment method (a primary method).
        :param bool capture_manually: Whether card payments are only authorized.
        :param bool is_validation: Whether the card is saved without paying.
        :param bool is_moto: Whether a saved card is charged while the customer is away.
        :return: The integration IDs.
        :rtype: list[int]
        :raise PaymobError: If the method has no integration ID.
        """
        self.ensure_one()
        code = payment_method.code
        if code == const.ALL_METHODS_CODE:
            methods = self.with_context(active_test=False).payment_method_ids.filtered(
                lambda m: m.active and not m.primary_payment_method_id
                and m.code != const.ALL_METHODS_CODE and m.paymob_cf_integration_id,
            )
            integration_ids = [m._paymob_cf_get_integration_id(capture_manually) for m in methods]
        elif is_moto:
            integration_ids = [self.paymob_cf_moto_integration_id]
        elif is_validation:
            integration_ids = [self.paymob_cf_verification_integration_id]
        else:
            integration_ids = [payment_method._paymob_cf_get_integration_id(capture_manually)]
        integration_ids = [integration_id for integration_id in integration_ids if integration_id]
        if not integration_ids:
            raise PaymobError(
                self._paymob_cf_get_error_message("missing_integration"),
                code="missing_integration",
            )
        return list(dict.fromkeys(integration_ids))  # Without duplicates, in order.

    # === BUSINESS METHODS - API === #

    def _paymob_cf_get_api_url(self):
        """Return the base URL of the Paymob platform of the provider's country."""
        self.ensure_one()
        return const.COUNTRIES[self.paymob_cf_country or const.DEFAULT_COUNTRY]["api_url"]

    def _paymob_cf_get_checkout_url(self, client_secret):
        """Return the URL of Paymob Checkout for a payment intention.

        :param str client_secret: The client secret of the intention.
        :rtype: str
        """
        self.ensure_one()
        query = urlencode({"publicKey": self.paymob_cf_public_key, "clientSecret": client_secret})
        return f"{self._paymob_cf_get_api_url()}{const.ENDPOINT_CHECKOUT}?{query}"

    def _build_request_url(self, endpoint, **kwargs):
        """Override of `payment` to build the request URL."""
        if self.code != "paymob_cf":
            return super()._build_request_url(endpoint, **kwargs)
        return f"{self._paymob_cf_get_api_url()}{endpoint}"

    def _build_request_headers(self, method, endpoint, payload, **kwargs):
        """Override of `payment` to authenticate the request.

        :param str paymob_auth: One of the `AUTH_*` constants (secret key by default).
        """
        if self.code != "paymob_cf":
            return super()._build_request_headers(method, endpoint, payload, **kwargs)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        auth = kwargs.get("paymob_auth", const.AUTH_SECRET_KEY)
        if auth == const.AUTH_SECRET_KEY:
            headers["Authorization"] = f"Token {self.sudo().paymob_cf_secret_key}"
        elif auth == const.AUTH_BEARER:
            headers["Authorization"] = f"Bearer {self._paymob_cf_get_auth_token()}"
        return headers

    def _parse_response_content(self, response, **kwargs):
        """Override of `payment` to parse Paymob's responses, which are JSON or empty."""
        if self.code != "paymob_cf":
            return super()._parse_response_content(response, **kwargs)
        if not response.text.strip():
            return {}
        return response.json()

    def _parse_response_error(self, response):
        """Override of `payment` to explain the errors returned by Paymob.

        Raised here, so that the code of the error reaches the caller.
        """
        if self.code != "paymob_cf":
            return super()._parse_response_error(response)
        try:
            description = paymob_utils.flatten_errors(response.json())
        except ValueError:
            description = response.text.strip()[:500]
        code = paymob_utils.classify_error(response.status_code, description)
        raise PaymobError(
            self._paymob_cf_get_error_message(code, description), code=code, description=description,
        )

    def _paymob_cf_get_auth_token(self):
        """Return a Bearer token of Paymob's APIs, reusing it while it is valid.

        :rtype: str
        :raise ValidationError: If Paymob refuses the API key.
        """
        self.ensure_one()
        api_key = self.sudo().paymob_cf_api_key or ""
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        cache_key = (self.env.cr.dbname, self.id, key_hash)
        token, expiry = _AUTH_TOKENS.get(cache_key, (None, 0))
        if token and expiry > time.time():
            return token
        response = self._send_api_request(
            "POST", const.ENDPOINT_AUTH, json={"api_key": api_key}, paymob_auth=const.AUTH_NONE,
        )
        token = response.get("token") if isinstance(response, dict) else None
        if not token:
            raise PaymobError(self._paymob_cf_get_error_message("credentials"), code="credentials")
        _AUTH_TOKENS[cache_key] = (token, time.time() + const.AUTH_TOKEN_LIFETIME_SECONDS)
        return token

    def _paymob_cf_get_integrations(self):
        """Return the integrations of the Paymob account in the provider's mode (test or live).

        :rtype: list[dict]
        :raise ValidationError: If the request fails.
        """
        self.ensure_one()
        params = {
            "is_plugin": "true",
            "page_size": 500,
            "is_deprecated": "false",
            "is_standalone": "false",
            "is_live": "true" if self.is_live else "false",
        }
        response = self._send_api_request(
            "GET", const.ENDPOINT_INTEGRATIONS, params=params, paymob_auth=const.AUTH_BEARER,
        )
        if isinstance(response, dict):
            return response.get("results") or []
        return response or []

    def _paymob_cf_inquire(self, order_id=None, special_reference=None):
        """Return the latest Paymob transaction of an order.

        :param str order_id: The order Paymob created for the payment.
        :param str special_reference: The reference of the payment at Paymob, used when the order
                                      isn't known.
        :return: The transaction, or `None` if Paymob has none yet.
        :rtype: dict | None
        :raise ValidationError: If the request fails for another reason.
        """
        self.ensure_one()
        payload = {"auth_token": self._paymob_cf_get_auth_token()}
        if order_id:
            payload["order_id"] = int(order_id) if str(order_id).isdigit() else order_id
        else:
            payload["merchant_order_id"] = special_reference
        try:
            response = self._send_api_request(
                "POST",
                const.ENDPOINT_INQUIRY,
                json=payload,
                reference=special_reference,
                paymob_auth=const.AUTH_BEARER,
            )
        except PaymobError as error:
            if error.code == "not_found":
                return None
            raise
        if isinstance(response, dict) and response.get("id"):
            return response
        return None

    def _paymob_cf_get_order_card_tokens(self, order_id):
        """Return the cards Paymob saved with the payment of an order.

        Paymob answers with a list of card token callbacks (`{"type": "TOKEN", "obj": {...}}`).

        :param str order_id: The order Paymob created for the payment.
        :return: The card tokens, as in the `obj` of the card token callback.
        :rtype: list[dict]
        :raise ValidationError: If the request fails.
        """
        self.ensure_one()
        response = self._send_api_request(
            "POST",
            const.ENDPOINT_ORDER_CARD_TOKENS,
            json={
                "auth_token": self._paymob_cf_get_auth_token(),
                "order_id": int(order_id) if str(order_id).isdigit() else order_id,
            },
            paymob_auth=const.AUTH_BEARER,
        )
        if isinstance(response, dict):
            response = response.get("results") or response.get("card_tokens") or [response]
        tokens = []
        for item in response or []:
            if isinstance(item, dict) and isinstance(item.get("obj"), dict):
                item = item["obj"]
            if isinstance(item, dict) and item.get("token"):
                tokens.append(item)
        return tokens

    def _paymob_cf_match_integrations(self, integrations):
        """Match the integrations of the account with the payment methods.

        :param list integrations: The integrations, as listed by Paymob.
        :return: The integration ID of each method code, and the special card integrations (by
                 provider field).
        :rtype: tuple[dict, dict]
        """
        self.ensure_one()
        currency = const.COUNTRIES[self.paymob_cf_country or const.DEFAULT_COUNTRY]["currency"]
        matches = {}
        special = {}
        for integration in sorted(
            integrations, key=lambda i: str(i.get("created_at") or ""), reverse=True,
        ):
            if integration.get("currency") and integration["currency"] != currency:
                continue
            if "is_live" in integration and bool(integration["is_live"]) != self.is_live:
                continue
            if integration.get("is_deprecated"):
                continue
            integration_id = integration.get("id")
            name = (integration.get("integration_name") or "").lower()
            if integration.get("is_apple_pay") or "apple" in name:
                matches.setdefault("apple_pay", integration_id)
                continue
            if integration.get("is_google_pay") or "google" in name:
                matches.setdefault("google_pay", integration_id)
                continue
            code = const.GATEWAY_TYPE_MAPPING.get(str(integration.get("gateway_type") or "").upper())
            if not code:
                continue
            if code == "card":
                integration_type = str(integration.get("integration_type") or "").lower()
                if integration_type == "moto":
                    special.setdefault("paymob_cf_moto_integration_id", integration_id)
                    continue
                if "verif" in integration_type or "verif" in name:
                    special.setdefault("paymob_cf_verification_integration_id", integration_id)
                    continue
                if integration.get("is_auth"):
                    special.setdefault("paymob_cf_auth_integration_id", integration_id)
                    continue
                if integration.get("is_installments") or integration.get("installments"):
                    matches.setdefault("installments_eg", integration_id)
                    continue
            matches.setdefault(code, integration_id)
        return matches, special

    # === BUSINESS METHODS - ERRORS === #

    def _paymob_cf_get_error_message(self, code, description=None):
        """Explain an error returned by Paymob, for the staff.

        :param str code: The code of the error (see `const.ERROR_CODES`).
        :param str description: The message sent by Paymob.
        :return: What the error means, with its code and Paymob's message.
        :rtype: str
        """
        code = str(code or "")
        if entry := const.ERROR_CODES.get(code):
            message = self.env._(
                "%(explanation)s (Paymob code %(code)s)",
                explanation=self.env._(entry[1]),
                code=code,
            )
            if description:
                message = self.env._(
                    "%(message)s Paymob's message: %(description)s",
                    message=message,
                    description=description,
                )
            return message
        if code:
            return self.env._(
                "Paymob refused the request: %(description)s (Paymob code %(code)s)",
                description=description or self.env._("no details given"),
                code=code,
            )
        return description or self.env._("Paymob refused the request.")

    def _paymob_cf_get_customer_error_message(self, code, description=None):  # noqa: ARG002
        """Explain an error returned by Paymob, for the customer.

        Errors about the customer's card, bank or details are explained as they are. The others are
        about the merchant's account: the customer only learns that the payment failed, with the
        code to give to the merchant.

        :param str code: The code of the error (see `const.ERROR_CODES`).
        :param str description: The message sent by Paymob.
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

    # === BUSINESS METHODS - SIGNATURES === #

    def _paymob_cf_check_transaction_hmac(self, transaction, received_hmac, is_redirection=False):
        """Return whether Paymob signed a transaction callback or redirection.

        :param dict transaction: The transaction (`obj` of the callback), or the query parameters
                                 of the redirection.
        :param str received_hmac: The `hmac` query parameter.
        :param bool is_redirection: Whether the data come from the redirection.
        :rtype: bool
        """
        self.ensure_one()
        if not received_hmac or not self.sudo().paymob_cf_hmac_secret:
            return False
        expected = paymob_utils.compute_hmac(
            paymob_utils.get_transaction_hmac_string(transaction, is_redirection=is_redirection),
            self.sudo().paymob_cf_hmac_secret,
        )
        return hmac.compare_digest(expected, str(received_hmac).lower())

    def _paymob_cf_check_token_hmac(self, token_data, received_hmac):
        """Return whether Paymob signed a card token callback.

        :param dict token_data: The card token (`obj` of the callback).
        :param str received_hmac: The `hmac` query parameter.
        :rtype: bool
        """
        self.ensure_one()
        if not received_hmac or not self.sudo().paymob_cf_hmac_secret:
            return False
        expected = paymob_utils.compute_hmac(
            paymob_utils.get_token_hmac_string(token_data), self.sudo().paymob_cf_hmac_secret,
        )
        return hmac.compare_digest(expected, str(received_hmac).lower())
