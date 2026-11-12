import { _t } from '@web/core/l10n/translation';
import { rpc, RPCError } from '@web/core/network/rpc';
import { patch } from '@web/core/utils/patch';

import { PaymentForm } from '@payment/interactions/payment_form';

// Egyptian mobile numbers, as Fawry expects them once normalized (01xxxxxxxxx).
const EG_MOBILE_REGEX = /^01[0125]\d{8}$/;

patch(PaymentForm.prototype, {

    start() {
        super.start(...arguments);
        // Switch between the two wallet options (payment request or QR code).
        this.addListener(this.el, 'change', (ev) => {
            if (ev.target.name === 'o_fawry_wallet_mode') {
                this._fawryToggleWalletMode(ev.target);
            }
        });
    },

    // #=== DOM MANIPULATION ===#

    /**
     * Choose the payment flow of the selected Fawry payment method.
     *
     * Fawry reference codes, wallets and myFawry (server-to-server integration), and Fawry's
     * checkout shown in a pop-up or a side panel, are processed on the page (direct flow). The
     * other methods redirect the customer to Fawry.
     *
     * @override method from @payment/interactions/payment_form
     * @private
     * @param {number} providerId - The id of the selected payment option's provider.
     * @param {string} providerCode - The code of the selected payment option's provider.
     * @param {number} paymentOptionId - The id of the selected payment option.
     * @param {string} paymentMethodCode - The code of the selected payment method, if any.
     * @param {string} flow - The online payment flow of the selected payment option.
     * @return {void}
     */
    async _prepareInlineForm(providerId, providerCode, paymentOptionId, paymentMethodCode, flow) {
        if (providerCode !== 'fawry') {
            await super._prepareInlineForm(...arguments);
            return;
        }
        if (flow === 'token') {
            return;  // Saved cards are charged by the server.
        }
        const values = this._fawryGetInlineFormValues();
        const isDirect = values.flow === 's2s_charge'
            || (values.flow === 'hosted' && ['popup', 'side_page'].includes(values.display_mode));
        this._setPaymentFlow(isDirect ? 'direct' : 'redirect');
    },

    /**
     * Show the wallet number input or the QR code hint, depending on the chosen wallet option.
     *
     * @private
     * @param {HTMLInputElement} modeInput - The checked wallet option.
     * @return {void}
     */
    _fawryToggleWalletMode(modeInput) {
        const walletForm = modeInput.closest('[name="o_fawry_wallet"]');
        const isRequest = modeInput.value === 'request';
        walletForm.querySelector('[name="o_fawry_wallet_request"]').classList.toggle(
            'd-none', !isRequest
        );
        walletForm.querySelector('[name="o_fawry_wallet_qr"]').classList.toggle(
            'd-none', isRequest
        );
        if (isRequest) {
            walletForm.querySelector('[name="o_fawry_wallet_number"]').focus();
        }
    },

    // #=== PAYMENT FLOW ===#

    /**
     * Check the wallet number before creating the transaction.
     *
     * @override method from @payment/interactions/payment_form
     * @private
     * @param {string} providerCode - The code of the selected payment option's provider.
     * @param {number} paymentOptionId - The id of the selected payment option.
     * @param {string} paymentMethodCode - The code of the selected payment method, if any.
     * @param {string} flow - The payment flow of the selected payment option.
     * @return {void}
     */
    async _initiatePaymentFlow(providerCode, paymentOptionId, paymentMethodCode, flow) {
        if (providerCode === 'fawry' && flow === 'direct') {
            const walletNumber = this._fawryGetWalletNumber();
            if (walletNumber !== null && !EG_MOBILE_REGEX.test(walletNumber)) {
                this._displayErrorDialog(
                    _t("Invalid wallet number"),
                    _t("Enter the mobile number of your wallet, such as 01012345678."),
                );
                this._enableButton();
                return;
            }
        }
        await super._initiatePaymentFlow(...arguments);
    },

    /**
     * Process the Fawry payments made on the page.
     *
     * @override method from @payment/interactions/payment_form
     * @private
     * @param {string} providerCode - The code of the selected payment option's provider.
     * @param {number} paymentOptionId - The id of the selected payment option.
     * @param {string} paymentMethodCode - The code of the selected payment method, if any.
     * @param {object} processingValues - The processing values of the transaction.
     * @return {void}
     */
    async _processDirectFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
        if (providerCode !== 'fawry') {
            await super._processDirectFlow(...arguments);
            return;
        }
        if (processingValues.fawry_checkout) {
            this._fawryOpenCheckout(processingValues.fawry_checkout);
            return;
        }
        try {
            const result = await this.waitFor(rpc('/payment/fawry/charge', {
                'reference': processingValues.reference,
                'access_token': processingValues.fawry_access_token,
                'wallet_number': this._fawryGetWalletNumber(),
            }));
            if (result.error) {  // Fawry rejected the charge.
                this._displayErrorDialog(_t("Payment processing failed"), result.error);
                this._enableButton();
                return;
            }
            window.location = result.redirect_url;
        } catch (error) {
            if (error instanceof RPCError) {
                this._displayErrorDialog(_t("Payment processing failed"), error.data.message);
                this._enableButton();
            } else {
                return Promise.reject(error);
            }
        }
    },

    /**
     * Send the customer to their bank to authenticate the payment with a saved card.
     *
     * @override method from @payment/interactions/payment_form
     * @private
     * @param {string} providerCode - The code of the selected payment option's provider.
     * @param {number} paymentOptionId - The id of the selected payment option.
     * @param {string} paymentMethodCode - The code of the selected payment method, if any.
     * @param {object} processingValues - The processing values of the transaction.
     * @return {void}
     */
    _processTokenFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
        const redirectUrl = processingValues.fawry_redirect_url;
        if (providerCode === 'fawry' && redirectUrl && redirectUrl.startsWith('https://')) {
            // Navigate the top window: the bank's pages refuse to be shown in a frame.
            window.top.location = redirectUrl;
        } else {
            return super._processTokenFlow(...arguments);
        }
    },

    /**
     * Show Fawry's checkout in a pop-up or a side panel.
     *
     * The checkout session is created by the server. Fawry's page posts the result of the
     * payment to the window that shows it; the customer is then sent to Odoo's return route,
     * which checks the result with Fawry. Like Fawry's own library, Apple devices get the
     * checkout in a full page instead, and Fawry redirects them to the same route.
     *
     * @private
     * @param {object} values - The checkout URL and the display options.
     * @return {void}
     */
    _fawryOpenCheckout(values) {
        const isAppleDevice = /Mac OS|iPhone|iPad/.test(navigator.userAgent)
            || navigator.vendor?.includes('Apple');
        if (isAppleDevice) {
            window.location = values.redirect_url;
            return;
        }

        const overlay = document.createElement('div');
        overlay.className = `o_fawry_checkout o_fawry_checkout_${values.display_mode}`;
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-label', _t("FawryPay secure checkout"));
        const panel = document.createElement('div');
        panel.className = 'o_fawry_checkout_panel';
        const header = document.createElement('div');
        header.className = 'o_fawry_checkout_header';
        const title = document.createElement('span');
        title.className = 'o_fawry_checkout_title';
        const lockIcon = document.createElement('i');
        lockIcon.className = 'oi me-2';
        lockIcon.dataset.icon = 'lock';
        lockIcon.setAttribute('aria-hidden', 'true');
        title.append(lockIcon, _t("FawryPay secure checkout"));
        const closeButton = document.createElement('button');
        closeButton.type = 'button';
        closeButton.className = 'btn-close';
        closeButton.setAttribute('aria-label', _t("Close"));
        header.append(title, closeButton);
        const frame = document.createElement('iframe');
        frame.className = 'o_fawry_checkout_frame';
        frame.title = _t("FawryPay secure checkout");
        frame.src = values.checkout_url;
        frame.allow = 'payment';
        panel.append(header, frame);
        overlay.append(panel);

        const close = () => {
            overlay.remove();
            window.removeEventListener('message', onMessage);
            document.removeEventListener('keydown', onKeydown);
        };
        const onMessage = (ev) => {
            if (ev.origin !== values.origin || !ev.data || typeof ev.data !== 'object') {
                return;  // Only Fawry's checkout reports the result of the payment.
            }
            close();
            const returnUrl = new URL(values.return_url);
            for (const [key, value] of Object.entries(ev.data)) {
                if (value !== null && typeof value !== 'object') {
                    returnUrl.searchParams.set(key, value);
                }
            }
            window.location = returnUrl.href;
        };
        const onKeydown = (ev) => {
            if (ev.key === 'Escape') {
                close();
            }
        };
        closeButton.addEventListener('click', close);
        window.addEventListener('message', onMessage);
        document.addEventListener('keydown', onKeydown);
        document.body.append(overlay);
        closeButton.focus();
        // Let customers choose another method if they close the checkout without paying.
        this._enableButton();
    },

    // #=== GETTERS ===#

    /**
     * Return the values of the inline form of the selected Fawry payment method.
     *
     * @private
     * @return {object} The flow and the display mode of the payment method.
     */
    _fawryGetInlineFormValues() {
        const radio = this.el.querySelector('input[name="o_payment_radio"]:checked');
        const inlineFormValues = this._getInlineForm(radio)?.querySelector(
            '[name="o_fawry_inline_form"]'
        )?.dataset.fawryInlineFormValues;
        return inlineFormValues ? JSON.parse(inlineFormValues) : {};
    },

    /**
     * Return the wallet number entered by the customer, if they asked for a payment request.
     *
     * @private
     * @return {string|null} The normalized number, or null if no request was asked for.
     */
    _fawryGetWalletNumber() {
        const radio = this.el.querySelector('input[name="o_payment_radio"]:checked');
        const walletForm = this._getInlineForm(radio)?.querySelector('[name="o_fawry_wallet"]');
        const mode = walletForm?.querySelector('input[name="o_fawry_wallet_mode"]:checked');
        if (!walletForm || mode?.value !== 'request') {
            return null;
        }
        const rawNumber = walletForm.querySelector('[name="o_fawry_wallet_number"]').value;
        let number = rawNumber.replace(/[^\d+]/g, '');
        if (number.startsWith('+20')) {
            number = '0' + number.slice(3);
        } else if (number.startsWith('0020')) {
            number = '0' + number.slice(4);
        }
        return number;
    },

});
