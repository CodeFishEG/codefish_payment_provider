import { patch } from '@web/core/utils/patch';

import { PaymentForm } from '@payment/interactions/payment_form';

// Kashier's hosted payment page: the only place a saved-card payment is sent to.
const KASHIER_CHECKOUT_ORIGIN = 'https://payments.kashier.io';

patch(PaymentForm.prototype, {

    /**
     * Send the customer to Kashier's page to confirm a payment with a saved card (security code and
     * 3-D Secure happen there).
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

});
