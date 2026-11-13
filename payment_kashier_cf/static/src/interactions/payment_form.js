import { loadJS } from '@web/core/assets';
import { _t } from '@web/core/l10n/translation';
import { rpc } from '@web/core/network/rpc';
import { patch } from '@web/core/utils/patch';

import { PaymentForm } from '@payment/interactions/payment_form';

// Kashier's hosted payment page: the only origin whose page is embedded or opened for a saved card.
const KASHIER_CHECKOUT_ORIGIN = 'https://payments.kashier.io';
// Messages of Kashier's embedded page meaning that the customer is done (paid, failed or redirected).
const KASHIER_DONE_MESSAGES = ['paymentSuccess', 'success', 'failure', 'urlRedirection'];
// While Kashier's page is shown in the checkout, the payment is also checked every few seconds.
const EMBED_POLL_DELAY = 5000;

/**
 * Return whether the browser can pay with Apple Pay (Safari, or a browser on iOS 16+, on a secure page).
 *
 * @return {boolean}
 */
function canUseApplePay() {
    try {
        return Boolean(window.ApplePaySession?.canMakePayments());
    } catch {
        return false;
    }
}

patch(PaymentForm.prototype, {

    // #=== INTERACTION LIFECYCLE ===#

    /**
     * Leave Kashier's Apple Pay out on browsers that can't use it.
     *
     * @override method from @payment/interactions/payment_form
     */
    async willStart() {
        if (!canUseApplePay()) {
            const radios = this.el.querySelectorAll(
                'input[name="o_payment_radio"][data-provider-code="kashier_cf"][data-payment-method-code="apple_pay"]'
            );
            for (const radio of radios) {
                radio.checked = false;
                radio.closest('[name="o_payment_option"]')?.classList.add('d-none');
            }
        }
        await super.willStart(...arguments);
    },

    // #=== DOM MANIPULATION ===#

    /**
     * Use the direct flow for Kashier's Apple Pay button; every other Kashier integration is a redirect
     * (to Kashier's page, to Odoo's own page for server-side payments, or Kashier's page embedded here).
     *
     * @override method from @payment/interactions/payment_form
     */
    async _prepareInlineForm(providerId, providerCode, paymentOptionId, paymentMethodCode, flow) {
        if (providerCode !== 'kashier_cf') {
            await super._prepareInlineForm(...arguments);
            return;
        }
        if (flow === 'token') {
            return;
        }
        const radio = this.el.querySelector('input[name="o_payment_radio"]:checked');
        const integration = radio?.dataset.kashierCfIntegration;
        this._setPaymentFlow(integration === 'apple_pay_button' ? 'direct' : 'redirect');
    },

    /**
     * Remove Kashier's embedded page or Apple Pay button when another payment option is chosen.
     *
     * @override method from @payment/interactions/payment_form
     */
    _collapseInlineForms() {
        this._kashierCfTeardown();
        super._collapseInlineForms(...arguments);
    },

    // #=== PAYMENT FLOW ===#

    /**
     * Show Kashier's page inside the checkout instead of leaving the shop.
     *
     * @override method from @payment/interactions/payment_form
     */
    async _processRedirectFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
        if (providerCode === 'kashier_cf' && processingValues.kashier_cf_embed_url) {
            this._kashierCfEmbed(processingValues);
            return;
        }
        return super._processRedirectFlow(...arguments);
    },

    /**
     * Show Kashier's Apple Pay button.
     *
     * @override method from @payment/interactions/payment_form
     */
    async _processDirectFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
        if (providerCode !== 'kashier_cf') {
            await super._processDirectFlow(...arguments);
            return;
        }
        await this._kashierCfShowApplePay(processingValues);
    },

    /**
     * Send the customer to Kashier's page to confirm a payment with a saved card (security code and 3-D
     * Secure happen there).
     *
     * @override method from @payment/interactions/payment_form
     */
    _processTokenFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
        const redirectUrl = processingValues.kashier_cf_redirect_url;
        let isKashierPage = false;
        try {
            isKashierPage = new URL(redirectUrl).origin === KASHIER_CHECKOUT_ORIGIN;
        } catch {
            isKashierPage = false;
        }
        if (providerCode === 'kashier_cf' && isKashierPage) {
            // Navigate the top window: the bank's pages refuse to be shown in a frame.
            window.top.location = redirectUrl;
        } else {
            return super._processTokenFlow(...arguments);
        }
    },

    // #=== KASHIER ===#

    /**
     * The container of the checked Kashier payment option, shown and emptied.
     *
     * @private
     * @return {HTMLElement|null}
     */
    _kashierCfContainer() {
        const radio = this.el.querySelector('input[name="o_payment_radio"]:checked');
        const container = radio && this._getInlineForm(radio)?.querySelector('.o_kashier_cf_container');
        if (container) {
            container.replaceChildren();
            container.classList.remove('d-none');
        }
        return container || null;
    },

    /**
     * Embed Kashier's page. Kashier sends the customer to Odoo's return route when the payment is done;
     * its messages and a regular check of the payment are fallbacks.
     *
     * @private
     * @param {object} values - The processing values of the transaction.
     */
    _kashierCfEmbed(values) {
        const container = this._kashierCfContainer();
        if (!container) {
            window.location = values.kashier_cf_embed_url;  // No room in the form: open Kashier's page.
            return;
        }
        const frame = document.createElement('iframe');
        frame.className = 'o_kashier_cf_frame w-100 border rounded';
        frame.style.minHeight = '680px';
        frame.title = _t("Secure payment");
        frame.allow = 'payment';
        frame.src = values.kashier_cf_embed_url;
        container.append(frame);
        const state = { active: true };
        this._kashierCfState = state;
        const finish = () => {
            if (state.active) {
                state.active = false;
                window.location = values.kashier_cf_return_url;
            }
        };
        const onMessage = (ev) => {
            if (ev.origin !== KASHIER_CHECKOUT_ORIGIN || ev.source !== frame.contentWindow) {
                return;
            }
            const message = ev.data?.message;
            if (KASHIER_DONE_MESSAGES.includes(message)) {
                finish();
            } else if (message === 'closeIframe') {
                this._kashierCfTeardown();
                this._showInputs();
                this._enableButton();
            }
        };
        window.addEventListener('message', onMessage);
        state.removeListener = () => window.removeEventListener('message', onMessage);
        const poll = async () => {
            if (!state.active) {
                return;
            }
            try {
                const result = await this.waitFor(rpc(values.kashier_cf_poll_url, {
                    tx_id: values.kashier_cf_tx_id,
                    access_token: values.kashier_cf_access_token,
                }, { silent: true }));
                if (result.final) {
                    state.active = false;
                    window.location = result.status_url;
                    return;
                }
            } catch {
                // Network hiccup: check again later.
            }
            this.waitForTimeout(poll, EMBED_POLL_DELAY);
        };
        this.waitForTimeout(poll, EMBED_POLL_DELAY);
        this._hideInputs();
        this._enableButton();
    },

    /**
     * Show Kashier's Apple Pay button for the payment session of the transaction.
     *
     * @private
     * @param {object} values - The processing values of the transaction.
     */
    async _kashierCfShowApplePay(values) {
        const container = this._kashierCfContainer();
        if (!values.kashier_cf_session_id || !container) {
            this._enableButton();
            return;
        }
        const button = document.createElement('div');
        button.id = 'kashier-sdk-id';
        container.append(button);
        const fail = () => {
            this._kashierCfTeardown();
            this._displayErrorDialog(
                _t("Payment processing failed"),
                _t("Apple Pay isn't available right now. Choose another payment method."),
            );
            this._showInputs();
            this._enableButton();
        };
        try {
            await this.waitFor(loadJS(values.kashier_cf_sdk_url));
        } catch {
            fail();
            return;
        }
        if (!window.kashierSDK?.load) {
            fail();
            return;
        }
        this._kashierCfState = { active: true };
        window.kashierSDK.load({
            data: { mode: values.kashier_cf_mode, sessionId: values.kashier_cf_session_id },
            locale: values.kashier_cf_locale,
            onSuccess: () => {
                window.location = values.kashier_cf_return_url;
            },
            onFailure: fail,
        });
        this._hideInputs();
        this._enableButton();
    },

    /**
     * Remove Kashier's embedded page or Apple Pay button, and stop checking the payment.
     *
     * @private
     */
    _kashierCfTeardown() {
        const state = this._kashierCfState;
        if (state) {
            state.active = false;
            state.removeListener?.();
            this._kashierCfState = null;
        }
        for (const container of this.el.querySelectorAll('.o_kashier_cf_container')) {
            container.replaceChildren();
            container.classList.add('d-none');
        }
    },

});
