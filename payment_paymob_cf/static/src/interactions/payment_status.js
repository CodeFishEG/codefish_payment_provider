import { patch } from '@web/core/utils/patch';

import { PaymentStatus } from '@payment/interactions/payment_status';

patch(PaymentStatus, {

    /**
     * Send customers to the landing page as soon as a Paymob payment is pending: that page shows
     * the kiosk reference to pay, or that the payment is being confirmed, and updates itself.
     *
     * @override method from `@payment/interactions/payment_status`
     * @param {string} providerCode - The code of the provider handling the transaction.
     * @returns {Set<string>} - Set of transaction's final states.
     */
    getFinalStates(providerCode) {
        const finalStates = super.getFinalStates(...arguments);
        if (providerCode === 'paymob_cf') {
            finalStates.add('pending');
        }
        return finalStates;
    },

});
