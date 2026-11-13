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

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
from odoo.tools import config, urls

from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_kashier_cf import const
from odoo.addons.payment_kashier_cf import utils as kashier_utils
from odoo.addons.payment_kashier_cf.controllers.main import KashierController
from odoo.addons.payment_kashier_cf.exceptions import KashierError
from odoo.addons.payment_kashier_cf.kashier_api import KashierClient

_logger = get_payment_logger(__name__, const.SENSITIVE_KEYS)

# Kashier's merchant IDs look like MID-123-456.
_MID_PATTERN = re.compile(r"^MID-\d+-\d+$")
# allowedMethods: a comma list of methods, each optionally with a provider filter: card, bnpl[valu].
_ALLOWED_METHODS_PATTERN = re.compile(r"^\s*[A-Za-z_]+(\[[A-Za-z0-9_]+\])?(\s*,\s*[A-Za-z_]+(\[[A-Za-z0-9_]+\])?)*\s*$")
# Requests that move money may take longer than core's 10 seconds; the others keep a short timeout.
_TIMEOUTS = {"default": 15, "money": 45}
_MONEY_ENDPOINTS = re.compile(r"^/v3/(orders(/|$)|payment/(refund|void|capture|reversal)/)")


class PaymentProvider(models.Model):
    _inherit = "payment.provider"

    code = fields.Selection(
        selection_add=[(const.PROVIDER_CODE, "Kashier")], ondelete={const.PROVIDER_CODE: "set default"},
    )
    kashier_cf_merchant_id = fields.Char(
        string="Kashier Merchant ID",
        help="Kashier dashboard: shown under your name (MID-xxx-xxx).",
        required_if_provider=const.PROVIDER_CODE,
        copy=False,
    )
    kashier_cf_payment_api_key = fields.Char(
        string="Kashier Payment API Key",
        help="Kashier dashboard: Integrate now > Payment API keys. Test and live modes have different "
        "keys. It also signs Kashier's notifications.",
        required_if_provider=const.PROVIDER_CODE,
        copy=False,
        groups="base.group_system",
    )
    kashier_cf_secret_key = fields.Char(
        string="Kashier Secret Key",
        help="Kashier dashboard: Integrate now > Secret key. Test and live modes have different keys. "
        "It confirms payments, refunds and captures; the dashboard user it belongs to needs the refund "
        "permission for refunds.",
        required_if_provider=const.PROVIDER_CODE,
        copy=False,
        groups="base.group_system",
    )
    kashier_cf_allowed_methods = fields.Char(
        string="Kashier Methods",
        help="The methods offered when customers choose the Kashier payment method, as Kashier names "
        "them, separated by commas (e.g. 'wallet, bank_installments, bnpl[valu]'). Leave empty to offer "
        "every method enabled on your Kashier account. Cards are always offered by the Card payment "
        "method.",
    )
    kashier_cf_session_expiry = fields.Integer(
        string="Payment Page Validity (Minutes)",
        help="How long the customer can pay on Kashier's page after choosing Kashier.",
        default=const.SESSION_EXPIRY_DEFAULT,
    )
    kashier_cf_max_attempts = fields.Integer(
        string="Attempts on Kashier's Page",
        help="How many times the customer can try again on Kashier's page after a declined card, before "
        "the payment fails.",
        default=const.MAX_ATTEMPTS_DEFAULT,
    )
    kashier_cf_webhook_url = fields.Char(
        string="Kashier Notification URL",
        help="Odoo sends it with every payment. You can also add it as a webhook in Kashier's "
        "dashboard.",
        compute="_compute_kashier_cf_webhook_url",
    )

    # === COMPUTE METHODS === #

    @api.depends("code")
    def _compute_feature_support_fields(self):
        """Override of `payment` to enable the features supported by Kashier."""
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == const.PROVIDER_CODE).update({
            "support_refund": "partial",
            "support_manual_capture": "full_only",
            "support_tokenization": True,
        })

    def _compute_kashier_cf_webhook_url(self):
        for provider in self:
            provider.kashier_cf_webhook_url = provider._kashier_cf_url(KashierController._webhook_url)

    # === CONSTRAINT METHODS === #

    @api.constrains("kashier_cf_merchant_id", "kashier_cf_allowed_methods", "kashier_cf_session_expiry",
                    "kashier_cf_max_attempts", "code")
    def _check_kashier_cf_settings(self):
        for provider in self.filtered(lambda p: p.code == const.PROVIDER_CODE):
            merchant_id = (provider.kashier_cf_merchant_id or "").strip()
            if merchant_id and not _MID_PATTERN.match(merchant_id):
                raise ValidationError(self.env._(
                    "The Kashier Merchant ID looks like MID-123-456 (it is shown under your name in "
                    "Kashier's dashboard).",
                ))
            methods = provider.kashier_cf_allowed_methods
            if methods and not _ALLOWED_METHODS_PATTERN.match(methods):
                raise ValidationError(self.env._(
                    "Write the Kashier methods as Kashier names them, separated by commas, e.g. "
                    "'wallet, bank_installments, bnpl[valu]'.",
                ))
            low, high = const.SESSION_EXPIRY_RANGE
            if not low <= provider.kashier_cf_session_expiry <= high:
                raise ValidationError(self.env._(
                    "The payment page validity must be between %(low)s and %(high)s minutes.",
                    low=low, high=high,
                ))
            low, high = const.MAX_ATTEMPTS_RANGE
            if not low <= provider.kashier_cf_max_attempts <= high:
                raise ValidationError(self.env._(
                    "The attempts on Kashier's page must be between %(low)s and %(high)s.",
                    low=low, high=high,
                ))

    # === CRUD METHODS === #

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("kashier_cf_merchant_id"):
                vals["kashier_cf_merchant_id"] = vals["kashier_cf_merchant_id"].strip()
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("kashier_cf_merchant_id"):
            vals = {**vals, "kashier_cf_merchant_id": vals["kashier_cf_merchant_id"].strip()}
        for field in ("kashier_cf_payment_api_key", "kashier_cf_secret_key"):
            if vals.get(field):
                vals = {**vals, field: vals[field].strip()}
        return super().write(vals)

    # === BUSINESS METHODS - PROVIDER CONTRACT === #

    def _get_default_payment_method_codes(self):
        """Override of `payment` to return the default payment method codes."""
        self.ensure_one()
        if self.code != const.PROVIDER_CODE:
            return super()._get_default_payment_method_codes()
        return const.DEFAULT_PAYMENT_METHOD_CODES

    def _get_supported_currencies(self):
        """Override of `payment` to return the currencies Kashier processes."""
        supported_currencies = super()._get_supported_currencies()
        if self.code == const.PROVIDER_CODE:
            supported_currencies = supported_currencies.filtered(
                lambda c: c.name in const.SUPPORTED_CURRENCIES,
            )
        return supported_currencies

    def _get_reset_values(self):
        """Override of `payment` to reset the Kashier credentials."""
        reset_values = super()._get_reset_values()
        if self.code == const.PROVIDER_CODE:
            reset_values.update({
                "kashier_cf_merchant_id": None,
                "kashier_cf_payment_api_key": None,
                "kashier_cf_secret_key": None,
            })
        return reset_values

    @api.model
    def _find_available_providers(self, *args, is_validation=False, report=None, **kwargs):
        """Override of `payment` to leave Kashier out of saving a card without paying: Kashier saves
        cards during a paid checkout only.
        """
        providers = super()._find_available_providers(
            *args, is_validation=is_validation, report=report, **kwargs,
        )
        if is_validation:
            providers = providers.filtered(lambda p: p.code != const.PROVIDER_CODE)
        return providers

    # === ACTION METHODS === #

    def action_kashier_cf_test_connection(self):
        """Ask Kashier to check the Secret Key and the Payment API Key of the provider's mode."""
        self.ensure_one()
        provider = self.sudo()
        if not (provider.kashier_cf_secret_key and provider.kashier_cf_payment_api_key
                and provider.kashier_cf_merchant_id):
            raise UserError(self.env._("Enter the Merchant ID, the Payment API Key and the Secret Key first."))
        mode = provider._kashier_cf_mode()
        try:
            # The answer lists every key of the account: it is never logged nor shown.
            provider._send_api_request(
                "POST",
                "/v2/merchants/validate-credentials",
                json={
                    "secretKeys": [{"mode": mode, "key": provider.kashier_cf_secret_key}],
                    "apiKeys": [{"mode": mode, "key": provider.kashier_cf_payment_api_key}],
                },
                kashier_cf_host="dashboard",
                kashier_cf_auth="secret",
                kashier_cf_quiet=True,
            )
        except ValidationError as error:
            raise UserError(self.env._("Kashier rejected the connection.\n%(error)s", error=error)) from None
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": self.env._("Connection successful"),
                "message": self.env._(
                    "Kashier accepted the Secret Key and the Payment API Key (%(mode)s mode).",
                    mode=self.env._("live") if mode == "live" else self.env._("test"),
                ),
                "sticky": False,
            },
        }

    # === BUSINESS METHODS - REQUESTS === #

    def _kashier_cf_mode(self):
        self.ensure_one()
        return "live" if self.is_live else "test"

    def _kashier_cf_client(self):
        """The typed Kashier client bound to this provider (see `kashier_api.py`)."""
        self.ensure_one()
        return KashierClient(self.sudo())

    def _kashier_cf_hash(self, message):
        """Sign a Kashier hash string with the Payment API Key."""
        self.ensure_one()
        return kashier_utils.hmac_hex(self.sudo().kashier_cf_payment_api_key or "", message)

    def _kashier_cf_url(self, path):
        """An absolute URL of this database: `path` joined to the base URL without a double slash.

        Behind a TLS proxy that sends X-Forwarded-Proto but not X-Forwarded-Host (Cloudflare tunnels),
        Odoo keeps the http scheme of the proxied request; Kashier wants https addresses.
        """
        self.ensure_one()
        base = self.get_base_url().rstrip("/")
        if base.startswith("http://") and request and config["proxy_mode"]:
            forwarded = request.httprequest.headers.get("X-Forwarded-Proto", "").split(",")[0].strip().lower()
            if forwarded == "https":
                base = "https://" + base.removeprefix("http://")
        return urls.urljoin(base + "/", path.lstrip("/"))

    def _send_api_request(self, method, endpoint, *, params=None, data=None, json=None, reference=None,
                          **kwargs):
        """Override of `payment` to tell Kashier's refusals from unknown outcomes.

        Core turns every timeout into a generic error after 10 seconds. For Kashier, a request that
        reached Kashier but got no answer (read timeout, connection lost, server error) may have
        moved money: it raises a `KashierError` with `unknown_outcome`, and the caller reconciles
        instead of sending it again. A request that never reached Kashier is a plain error.

        :param str kashier_cf_host: "dashboard" or "fep".
        :param str kashier_cf_auth: "secret", "secret+apikey", "hash" or "none".
        :param str kashier_cf_hash: The `Kashier-Hash` header, for "hash".
        :param bool kashier_cf_quiet: Don't log the response body.
        """
        if self.code != const.PROVIDER_CODE:
            return super()._send_api_request(
                method, endpoint, params=params, data=data, json=json, reference=reference, **kwargs,
            )
        self.ensure_one()
        url = self._build_request_url(endpoint, **kwargs)
        headers = self._build_request_headers(method, endpoint, params or data or json, **kwargs)
        self._log_request(method, url, params or data or json, reference=reference)
        moves_money = method in ("POST", "PUT") and bool(_MONEY_ENDPOINTS.match(endpoint))
        timeout = _TIMEOUTS["money" if moves_money else "default"]
        try:
            response = requests.request(
                method, url, params=params, data=data, json=json, headers=headers, timeout=timeout,
            )
        except requests.exceptions.ConnectTimeout:
            raise KashierError(
                self.env._("Could not reach Kashier. Try again in a moment."), code="connection",
            ) from None
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            raise KashierError(
                self.env._(
                    "Kashier didn't answer in time. The request may still have been processed: it is "
                    "checked with Kashier before anything is sent again.",
                ),
                code="timeout",
                unknown_outcome=True,
            ) from None
        if kwargs.get("kashier_cf_quiet") and response.ok:
            _logger.info("Kashier answered %s %s with HTTP %s.", method, endpoint, response.status_code)
        else:
            self._log_response(response, reference=reference)
        if not response.ok:
            self._parse_response_error(response)
        return self._parse_response_content(response, **kwargs)

    def _build_request_url(self, endpoint, **kwargs):
        """Override of `payment` to target Kashier's dashboard or payment (FEP) host of the mode."""
        if self.code != const.PROVIDER_CODE:
            return super()._build_request_url(endpoint, **kwargs)
        host = const.HOSTS[kwargs.get("kashier_cf_host") or "dashboard"][self._kashier_cf_mode()]
        return f"{host}{endpoint}"

    def _build_request_headers(self, method, endpoint, payload, **kwargs):
        """Override of `payment` to authenticate the request as the operation requires."""
        if self.code != const.PROVIDER_CODE:
            return super()._build_request_headers(method, endpoint, payload, **kwargs)
        provider = self.sudo()
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        auth = kwargs.get("kashier_cf_auth") or "secret"
        if auth in ("secret", "secret+apikey"):
            headers["Authorization"] = provider.kashier_cf_secret_key or ""
        if auth == "secret+apikey":
            headers["api-key"] = provider.kashier_cf_payment_api_key or ""
        if auth == "hash":
            headers["Kashier-Hash"] = kwargs.get("kashier_cf_hash") or ""
        return headers

    def _parse_response_content(self, response, **kwargs):
        """Override of `payment` to parse Kashier's answers and raise the refusals sent with HTTP 200."""
        if self.code != const.PROVIDER_CODE:
            return super()._parse_response_content(response, **kwargs)
        if not response.text.strip():
            return {}
        try:
            content = response.json()
        except ValueError:
            raise KashierError(self.env._("Kashier sent an answer Odoo can't read."), code="server_error",
                               unknown_outcome=True) from None
        if isinstance(content, dict) and str(content.get("status", "")).upper() == "FAILURE" \
                and "response" not in content:
            raise self._kashier_cf_error(response.status_code, content)
        return content

    def _parse_response_error(self, response):
        """Override of `payment` to explain Kashier's errors; raised here so that the code reaches the caller."""
        if self.code != const.PROVIDER_CODE:
            return super()._parse_response_error(response)
        try:
            body = response.json()
        except ValueError:
            body = response.text
        raise self._kashier_cf_error(response.status_code, body)

    def _kashier_cf_error(self, status, body):
        """The KashierError for an error answer of Kashier."""
        code = kashier_utils.classify_error(status, body)
        description = kashier_utils.message_of(body)
        kind = const.ERROR_CODES.get(code, (None,))[0]
        return KashierError(
            self._kashier_cf_get_error_message(code, description),
            code=code,
            description=description,
            unknown_outcome=kind == const.ERROR_UNKNOWN or status >= 500,
            status=status,
        )

    # === BUSINESS METHODS - ERRORS === #

    def _kashier_cf_get_error_message(self, code, description=None):
        """Explain an error returned by Kashier, for the staff.

        :param str code: The code of the error (see `const.ERROR_CODES`).
        :param str description: The message sent by Kashier.
        :return: What the error means, with its code and Kashier's message.
        :rtype: str
        """
        code = str(code or "")
        if entry := const.ERROR_CODES.get(code):
            message = self.env._("%(explanation)s (Kashier code %(code)s)", explanation=str(entry[1]), code=code)
            if description:
                message = self.env._("%(message)s Kashier's message: %(description)s",
                                     message=message, description=description)
            return message
        if code:
            return self.env._("Kashier refused the request: %(description)s (Kashier code %(code)s)",
                              description=description or self.env._("no details given"), code=code)
        return description or self.env._("Kashier refused the request.")

    def _kashier_cf_get_customer_error_message(self, code):
        """Explain an error returned by Kashier, for the customer: card and bank errors as they are,
        the others as a neutral message with the code to give to the merchant.
        """
        code = str(code or "")
        kind, explanation = const.ERROR_CODES.get(code, (None, None))
        if kind == const.ERROR_CUSTOMER:
            return str(explanation)
        if code:
            return self.env._(
                "The payment couldn't be processed. Please try again later or choose another payment "
                "method (error %(code)s).",
                code=code,
            )
        return self.env._(
            "The payment couldn't be processed. Please try again later or choose another payment method.",
        )

    # === BUSINESS METHODS - SETUP === #

    @api.model
    def _kashier_cf_setup_journals(self, companies=None):
        """Give the Kashier provider of each company its own "Kashier" bank journal.

        Companies without a chart of accounts are skipped; they get the journal when a chart is
        installed (see `account.chart.template._post_load_data`).
        """
        domain = [("code", "=", const.PROVIDER_CODE)]
        if companies is not None:
            domain.append(("company_id", "in", companies.ids))
        for provider in self.sudo().with_context(active_test=False).search(domain):
            if not provider.company_id.chart_template:
                continue
            journal = provider._kashier_cf_get_or_create_journal()
            if journal and provider.journal_id != journal:
                provider.journal_id = journal

    def _kashier_cf_get_or_create_journal(self):
        """Return the company's "Kashier" journal, created if needed (empty if the code is taken by
        another kind of journal).
        """
        self.ensure_one()
        Journal = self.env["account.journal"].sudo().with_context(lang="en_US")
        company = self.company_id
        journal = Journal.search([("company_id", "=", company.id), ("code", "=", const.JOURNAL_CODE)], limit=1)
        if journal:
            if journal.type != "bank":
                _logger.warning("Journal %s of company %s isn't a bank journal: Kashier payments keep the "
                                "provider's journal.", const.JOURNAL_CODE, company.name)
                return Journal
            return journal
        journal = Journal.with_company(company).create({
            "name": const.JOURNAL_NAME,
            "code": const.JOURNAL_CODE,
            "type": "bank",
            "company_id": company.id,
        })
        translations = {
            lang_code: const.JOURNAL_NAME_TRANSLATIONS[lang_code.split("_")[0]]
            for lang_code, _name in self.env["res.lang"].get_installed()
            if lang_code.split("_")[0] in const.JOURNAL_NAME_TRANSLATIONS
        }
        if translations:
            journal.update_field_translations("name", translations)
        _logger.info("Created the Kashier journal of company %s.", company.name)
        return journal
