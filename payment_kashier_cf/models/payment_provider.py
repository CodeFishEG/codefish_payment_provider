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

from odoo.addons.payment import utils as payment_utils
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
    kashier_cf_account_methods = fields.Json(
        string="Kashier Account Methods",
        help="The methods the Kashier account accepts, as Kashier last listed them, with the Merchant ID and "
        "the mode (test or live) they were listed for.",
        readonly=True,
        copy=False,
    )
    kashier_cf_account_methods_date = fields.Datetime(string="Kashier Methods Checked On", readonly=True, copy=False)
    kashier_cf_account_methods_display = fields.Char(
        string="Accepted by your Kashier Account", compute="_compute_kashier_cf_account_methods_display",
    )
    kashier_cf_shadowed_methods = fields.Char(
        string="Kashier Methods Shown by Another Provider", compute="_compute_kashier_cf_shadowed_methods",
    )
    kashier_cf_apple_pay_domain_file = fields.Binary(
        string="Kashier Apple Pay Domain File",
        help="The file apple-developer-merchantid-domain-association that Kashier gives when it registers "
        "your shop's domain for Apple Pay. Needed for the Apple Pay button on the payment step only.",
        attachment=True,
        copy=False,
    )
    kashier_cf_apple_pay_domain_filename = fields.Char(string="Kashier Apple Pay Domain File Name", copy=False)
    kashier_cf_apple_pay_domain_url = fields.Char(
        string="Kashier Apple Pay Domain File URL",
        help="Where Apple reads the domain file. Open it to check it shows a long line of text.",
        compute="_compute_kashier_cf_apple_pay_domain_url",
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

    def _compute_kashier_cf_apple_pay_domain_url(self):
        for provider in self:
            provider.kashier_cf_apple_pay_domain_url = provider._kashier_cf_url(const.APPLE_PAY_DOMAIN_FILE_URL)

    @api.depends("kashier_cf_account_methods", "kashier_cf_merchant_id", "is_live")
    def _compute_kashier_cf_account_methods_display(self):
        for provider in self:
            data = provider._kashier_cf_current_account_methods()
            if data is None:
                provider.kashier_cf_account_methods_display = self.env._(
                    "Not checked yet: every active method is offered.",
                )
                continue
            names = list(data.get("methods") or [])
            if data.get("bnpl"):
                names.append(self.env._("buy now, pay later: %s", ", ".join(data["bnpl"])))
            provider.kashier_cf_account_methods_display = ", ".join(names) or self.env._("No method.")

    @api.depends("payment_method_ids.active", "sequence", "company_id")
    def _compute_kashier_cf_shadowed_methods(self):
        """Active Kashier methods that customers see from another provider: Odoo shows a method once, from
        the provider with the lowest sequence (e.g. our Paymob module's valU before Kashier's).
        """
        for provider in self:
            if provider.code != const.PROVIDER_CODE or not provider.id:
                provider.kashier_cf_shadowed_methods = False
                continue
            others = self.sudo().search([
                ("id", "!=", provider.id), ("company_id", "=", provider.company_id.id),
                ("is_published", "=", True), ("sequence", "<", provider.sequence),
            ])
            shadowed = provider.primary_payment_method_ids.filtered(lambda pm: pm.active and any(
                pm.code in other.primary_payment_method_ids.filtered("active").mapped("code") for other in others
            ))
            provider.kashier_cf_shadowed_methods = ", ".join(shadowed.mapped("name")) or False

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

    @api.constrains("kashier_cf_apple_pay_domain_file")
    def _check_kashier_cf_apple_pay_domain_file(self):
        for provider in self.filtered("kashier_cf_apple_pay_domain_file"):
            domain_file = provider.kashier_cf_apple_pay_domain_file
            if domain_file.size > const.APPLE_PAY_DOMAIN_FILE_MAX_SIZE or b"\0" in domain_file.content:
                raise ValidationError(self.env._(
                    "This isn't Apple's domain file. Upload the file apple-developer-merchantid-domain-association "
                    "as Kashier gave it, without renaming or opening it.",
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
        resync = bool({"kashier_cf_merchant_id", "is_live"} & set(vals)) and any(
            p.code == const.PROVIDER_CODE for p in self
        )
        if resync:
            # The accepted methods depend on the account and the mode: list them again, in the background
            # (no request to Kashier while saving a form).
            vals = {**vals, "kashier_cf_account_methods": False, "kashier_cf_account_methods_date": False}
        result = super().write(vals)
        if resync:
            self.env.ref("payment_kashier_cf.cron_sync_account_methods")._trigger()
        return result

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

    def _find_available_payment_methods(self, *args, report=None, **kwargs):
        """Override of `payment` to hide the Kashier methods the merchant account doesn't accept.

        Called on every available provider: only Kashier's methods are filtered. Nothing is hidden while
        the account's methods are unknown or were listed for another Merchant ID or mode.
        """
        methods = super()._find_available_payment_methods(*args, report=report, **kwargs)
        refused = methods.filtered(
            lambda pm: pm.provider_id.code == const.PROVIDER_CODE and not pm.provider_id._kashier_cf_accepts(pm),
        )
        if refused:
            payment_utils.add_to_report(
                report, refused, available=False, reason=self.env._("Not accepted by the Kashier account"),
            )
        return methods - refused

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

    # === BUSINESS METHODS - ACCOUNT METHODS === #

    def action_kashier_cf_sync_account_methods(self):
        """List again the methods the Kashier account accepts."""
        self.ensure_one()
        if not self.kashier_cf_merchant_id:
            raise UserError(self.env._("Enter the Kashier Merchant ID first."))
        if not self._kashier_cf_sync_account_methods():
            raise UserError(self.env._("Kashier didn't answer. Try again in a moment."))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": self.env._("Accepted by your Kashier account: %s", self.kashier_cf_account_methods_display),
                "next": {"type": "ir.actions.act_window_close"},
                "sticky": False,
            },
        }

    def _kashier_cf_sync_account_methods(self):
        """Ask Kashier which methods the account accepts and keep the answer with its Merchant ID and mode.

        :return: Whether Kashier answered.
        :rtype: bool
        """
        self.ensure_one()
        merchant_id = (self.kashier_cf_merchant_id or "").strip()
        if not merchant_id:
            return False
        try:
            answer = self._kashier_cf_client().get_merchant_payment_methods(merchant_id) or {}
        except KashierError as error:
            _logger.warning("Kashier didn't list the methods of the account: %s", error)
            return False
        methods, bnpl = kashier_utils.parse_account_methods(answer)
        self.sudo().write({
            "kashier_cf_account_methods": {
                "mid": merchant_id, "mode": self._kashier_cf_mode(), "methods": methods, "bnpl": bnpl,
            },
            "kashier_cf_account_methods_date": fields.Datetime.now(),
        })
        return True

    @api.model
    def _cron_kashier_cf_sync_account_methods(self):
        for provider in self.search([("code", "=", const.PROVIDER_CODE), ("kashier_cf_merchant_id", "!=", False)]):
            provider._kashier_cf_sync_account_methods()

    def _kashier_cf_current_account_methods(self):
        """The account's methods when they were listed for the current Merchant ID and mode, else None."""
        self.ensure_one()
        data = self.kashier_cf_account_methods
        if not isinstance(data, dict):
            return None
        if data.get("mid") != (self.kashier_cf_merchant_id or "").strip() or data.get("mode") != self._kashier_cf_mode():
            return None
        return data

    def _kashier_cf_accepts(self, payment_method):
        """Whether the merchant account accepts the method (True while unknown)."""
        self.ensure_one()
        data = self._kashier_cf_current_account_methods()
        if data is None:
            return True
        spec = payment_method._kashier_cf_spec()
        if not spec.get("account"):
            return True
        listed = data.get("bnpl" if spec.get("bnpl") else "methods") or []
        return spec["account"] in listed

    # === BUSINESS METHODS - APPLE PAY === #

    def _kashier_cf_get_apple_pay_domain_file(self, host):
        """Return Kashier's Apple Pay domain file for the website on the given host.

        :param str host: The host of the request, e.g. `shop.example.com`.
        :return: The content of the file, or None if no Kashier provider has one.
        :rtype: bytes | None
        """
        providers = self.sudo().search([("code", "=", const.PROVIDER_CODE)]).filtered("kashier_cf_apple_pay_domain_file")
        if not providers:
            return None
        if len(providers) > 1 and "website_id" in providers._fields:
            host = (host or "").lower()

            def rank(provider):
                website = provider.website_id
                if not website:
                    return 1
                domain = (website.domain or "").lower().split("://")[-1].split("/")[0]
                return 0 if domain == host else 2

            providers = providers.sorted(rank)
        return providers[0].kashier_cf_apple_pay_domain_file.content

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
