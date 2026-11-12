import { patch } from '@web/core/utils/patch';

import { PaymentStatus } from '@payment/interactions/payment_status';

patch(PaymentStatus, {

    /**
     * Send customers to the landing page as soon as a Fawry payment is pending: that page shows
     * them how to pay (reference code, QR code or myFawry link) and updates itself once paid.
     *
     * @override method from `@payment/interactions/payment_status`
     * @param {string} providerCode - The code of the provider handling the transaction.
     * @returns {Set<string>} - Set of transaction's final states.
     */
    getFinalStates(providerCode) {
        const finalStates = super.getFinalStates(...arguments);
        if (providerCode === 'fawry') {
            finalStates.add('pending');
        }
        return finalStates;
    },

});
