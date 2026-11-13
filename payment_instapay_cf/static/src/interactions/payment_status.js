import { patch } from '@web/core/utils/patch';

import { PaymentStatus } from '@payment/interactions/payment_status';

patch(PaymentStatus, {

    /**
     * Send customers to the landing page as soon as an InstaPay payment waits for the transfer:
     * that page shows where to send the money and how to upload the receipt.
     *
     * @override method from `@payment/interactions/payment_status`
     * @param {string} providerCode - The code of the provider handling the transaction.
     * @returns {Set<string>} - Set of transaction's final states.
     */
    getFinalStates(providerCode) {
        const finalStates = super.getFinalStates(...arguments);
        if (providerCode === 'instapay_cf') {
            finalStates.add('pending');
        }
        return finalStates;
    },

});
