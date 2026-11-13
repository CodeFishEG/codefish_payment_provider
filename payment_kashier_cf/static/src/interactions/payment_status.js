import { patch } from '@web/core/utils/patch';

import { PaymentStatus } from '@payment/interactions/payment_status';

patch(PaymentStatus, {

    /**
     * Send customers to the landing page as soon as a Kashier payment is pending: its outcome is
     * being confirmed with Kashier, and the order page shows it.
     *
     * @override method from `@payment/interactions/payment_status`
     * @param {string} providerCode - The code of the provider handling the transaction.
     * @returns {Set<string>} - Set of transaction's final states.
     */
    getFinalStates(providerCode) {
        const finalStates = super.getFinalStates(...arguments);
        if (providerCode === 'kashier_cf') {
            finalStates.add('pending');
        }
        return finalStates;
    },

});
