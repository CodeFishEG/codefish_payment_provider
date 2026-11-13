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
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from werkzeug.exceptions import Forbidden

from odoo import fields, http
from odoo.http import request
from odoo.tools import BinaryBytes

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_instapay_cf import const
from odoo.addons.payment_instapay_cf import utils as instapay_utils

_logger = get_payment_logger(__name__)

# The headers of the pages showing the payment: never cached, indexed or leaked as referrer.
PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
}


class InstapayController(http.Controller):
    _process_url = "/payment/instapay_cf/process"
    _pay_url = "/payment/instapay_cf/pay"
    _receipt_url = "/payment/instapay_cf/receipt"
    _cancel_url = "/payment/instapay_cf/cancel"

    @http.route(_process_url, type="http", auth="public", methods=["POST"], csrf=False)
    def instapay_cf_process(self, reference=None, access_token=None, **_kwargs):
        """Put the payment on hold until the transfer: the customer chose InstaPay at checkout.

        The form is posted by the payment form without CSRF token; the access token proves it
        comes from the checkout of this payment.
        """
        tx_sudo = request.env["payment.transaction"].sudo()._search_by_reference(
            const.PROVIDER_CODE, {"reference": reference},
        )
        if not tx_sudo or not self._instapay_cf_check_token(tx_sudo, access_token):
            raise Forbidden
        tx_sudo._record({"reference": tx_sudo.reference, const.EVENT_KEY: const.EVENT_CHECKOUT})
        return request.redirect("/payment/status")

    @http.route(
        f"{_pay_url}/<int:tx_id>/<string:access_token>",
        type="http",
        auth="public",
        methods=["GET"],
        website=True,
        sitemap=False,
    )
    def instapay_cf_pay_page(self, tx_id, access_token, receipt=None, cancelled=None, **_kwargs):
        """Show where to send the money and the form to send the receipt."""
        tx_sudo = self._instapay_cf_get_transaction(tx_id, access_token)
        flash = False
        if receipt == "sent":
            flash = "receipt_sent"
        elif cancelled:
            flash = "cancelled"
        return self._instapay_cf_render_pay_page(tx_sudo, flash=flash)

    @http.route(
        f"{_receipt_url}/<int:tx_id>/<string:access_token>",
        type="http",
        auth="public",
        methods=["POST"],
        website=True,
        sitemap=False,
        max_content_length=const.RECEIPT_MAX_REQUEST_SIZE,
    )
    def instapay_cf_receipt(self, tx_id, access_token, **post):
        """Receive the screenshot of the transfer and the details the customer declares."""
        tx_sudo = self._instapay_cf_get_transaction(tx_id, access_token)
        env = request.env
        form = {
            key: post.get(key) or ""
            for key in (
                "transfer_reference", "amount_sent", "transferred_at", "sender_name", "account_id",
            )
        }

        def fail(message, status=400):
            return self._instapay_cf_render_pay_page(
                tx_sudo, error=message, form_values=form, status=status,
            )

        if tx_sudo.state != "pending" or tx_sudo._instapay_cf_has_pending_event():
            return fail(env._(
                "This payment no longer waits for a receipt. Please contact %(company)s.",
                company=tx_sudo.company_id.name,
            ), status=409)

        provider = tx_sudo.provider_id
        reference = instapay_utils.normalize_reference(form["transfer_reference"])
        if form["transfer_reference"] and not reference:
            return fail(env._(
                "The reference has letters and digits only: copy it from the receipt (12 digits "
                "on most receipts).",
            ))
        if provider.instapay_cf_require_reference and not reference:
            return fail(env._("Enter the reference number shown on the receipt."))

        amount = instapay_utils.parse_amount(form["amount_sent"])
        if amount is None or not 0 < amount <= const.MAX_AMOUNT_SENT:
            return fail(env._("Enter the amount you sent, e.g. 1500 or 1500.50."))

        transferred_at = False
        if form["transferred_at"]:
            transferred_at = self._instapay_cf_parse_local_datetime(
                form["transferred_at"], tx_sudo.company_id,
            )
            if not transferred_at:
                return fail(env._("Enter the date and time shown on the receipt."))

        accounts = provider._instapay_cf_get_accounts()
        account = accounts[:1] if len(accounts) == 1 else accounts.browse()
        if form["account_id"]:
            account_id = int(form["account_id"]) if form["account_id"].isdigit() else 0
            account = accounts.filtered(lambda a: a.id == account_id)
            if not account:
                return fail(env._("Choose where you sent the money."))

        upload = request.httprequest.files.get("receipt")
        raw = upload.read(const.RECEIPT_MAX_FILE_SIZE + 1) if upload else b""
        if not raw:
            return fail(env._("Add the screenshot of the success screen of your transfer."))
        try:
            clean, extension, sha256 = instapay_utils.sanitize_receipt(raw)
        except instapay_utils.ReceiptError as error:
            messages = {
                "type": env._("The screenshot must be a PNG or JPEG image."),
                "size": env._("The screenshot is too large: send an image of at most 10 MB."),
                "unreadable": env._(
                    "This file can't be read. Take a new screenshot and send it again.",
                ),
            }
            return fail(messages[error.code], status=413 if error.code == "size" else 400)

        if not tx_sudo.try_lock_for_update(allow_referencing=True):
            return fail(env._("Your payment is being updated. Please try again in a moment."), 409)
        if tx_sudo.state != "pending":
            return fail(env._(
                "This payment no longer waits for a receipt. Please contact %(company)s.",
                company=tx_sudo.company_id.name,
            ), status=409)
        receipts = tx_sudo.instapay_cf_receipt_ids
        if len(receipts) >= const.MAX_RECEIPTS_PER_TX:
            return fail(env._(
                "You sent many receipts for this payment. Please contact %(company)s.",
                company=tx_sudo.company_id.name,
            ), status=429)
        last_sent = max(receipts.mapped("submitted_at"), default=False)
        if last_sent and fields.Datetime.now() - last_sent < timedelta(
            seconds=const.MIN_SECONDS_BETWEEN_RECEIPTS,
        ):
            return fail(env._("Please wait a few seconds before sending another receipt."), 429)
        if sha256 in receipts.mapped("image_sha256"):
            return fail(env._("You already sent this screenshot for this payment."), 409)

        filename = f"{tx_sudo.reference}-receipt-{len(receipts) + 1}.{extension}"
        env["payment.instapay.receipt"].sudo().with_context(instapay_cf_image_clean=True).create({
            "transaction_id": tx_sudo.id,
            "source": "customer",
            "image": BinaryBytes(clean),
            "image_filename": filename,
            "image_sha256": sha256,
            "transfer_reference": reference or False,
            "amount_sent": amount,
            "transferred_at": transferred_at,
            "sender_name": instapay_utils.clean_text(
                form["sender_name"], const.MAX_SENDER_NAME_LENGTH,
            ) or False,
            "account_id": account.id or False,
        })
        _logger.info("Received an InstaPay receipt for transaction %s.", tx_sudo.reference)
        return request.redirect(f"{tx_sudo._instapay_cf_get_page_path()}?receipt=sent", code=303)

    @http.route(
        f"{_cancel_url}/<int:tx_id>/<string:access_token>",
        type="http",
        auth="public",
        methods=["POST"],
        website=True,
        sitemap=False,
    )
    def instapay_cf_cancel(self, tx_id, access_token, **_kwargs):
        """Cancel the payment at the customer's request, to pay another way. Only while no
        receipt waits for review.
        """
        tx_sudo = self._instapay_cf_get_transaction(tx_id, access_token)
        values = tx_sudo._instapay_cf_get_instructions_values()
        if values["can_cancel"] and not tx_sudo._instapay_cf_has_pending_event():
            tx_sudo._record({
                "reference": tx_sudo.reference,
                const.EVENT_KEY: const.EVENT_CANCEL_BY_CUSTOMER,
            })
            request.env["payment.transaction"].sudo()._run_processing()
        return request.redirect(f"{tx_sudo._instapay_cf_get_page_path()}?cancelled=1", code=303)

    # === HELPERS === #

    @staticmethod
    def _instapay_cf_check_token(tx_sudo, access_token):
        return bool(access_token) and payment_utils.check_access_token(
            access_token, const.PROVIDER_CODE, tx_sudo.id, tx_sudo.reference, tx_sudo.partner_id.id,
        )

    def _instapay_cf_get_transaction(self, tx_id, access_token):
        """Return the InstaPay transaction matching the id, if the access token is valid.

        :raise Forbidden: If the transaction doesn't exist or the token is wrong; both give the
                          same answer.
        """
        tx_sudo = request.env["payment.transaction"].sudo().browse(tx_id).exists()
        if (
            not tx_sudo
            or tx_sudo.provider_code != const.PROVIDER_CODE
            or not self._instapay_cf_check_token(tx_sudo, access_token)
        ):
            raise Forbidden
        return tx_sudo

    @staticmethod
    def _instapay_cf_parse_local_datetime(value, company):
        """Return a `datetime-local` value typed in the company's timezone as naive UTC, or
        False.
        """
        text = instapay_utils.to_ascii_digits(value).strip()
        for pattern in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
            try:
                local = datetime.strptime(text, pattern)
            except ValueError:
                continue
            tz = ZoneInfo(company.tz or "UTC")
            return local.replace(tzinfo=tz).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        return False

    def _instapay_cf_render_pay_page(self, tx_sudo, error=None, form_values=None, flash=False,
                                     status=200):
        tz = ZoneInfo(tx_sudo.company_id.tz or "UTC")
        now_local = datetime.now(tz).strftime("%Y-%m-%dT%H:%M")
        form = {
            "transfer_reference": "",
            "amount_sent": tx_sudo._instapay_cf_amount_to_copy(tx_sudo.amount),
            "transferred_at": now_local,
            "sender_name": "",
            "account_id": "",
            **(form_values or {}),
        }
        token = tx_sudo._instapay_cf_get_access_token()
        values = tx_sudo._instapay_cf_get_instructions_values(on_pay_page=True)
        response = request.render("payment_instapay_cf.pay_page", {
            "values": values,
            "tx": tx_sudo,
            "form": form,
            "error": error,
            "flash": flash,
            "receipt_url": f"{self._receipt_url}/{tx_sudo.id}/{token}",
            "cancel_url": f"{self._cancel_url}/{tx_sudo.id}/{token}",
            "accept": instapay_utils.receipt_accept(),
            "max_size": const.RECEIPT_MAX_FILE_SIZE,
            "now_local": now_local,
        }, status=status)
        for header, value in PAGE_HEADERS.items():
            response.headers[header] = value
        return response
