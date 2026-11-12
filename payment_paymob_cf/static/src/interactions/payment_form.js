import { loadJS } from '@web/core/assets';
import { _t } from '@web/core/l10n/translation';
import { rpc } from '@web/core/network/rpc';
import { patch } from '@web/core/utils/patch';

import { PaymentForm } from '@payment/interactions/payment_form';

// How often the state of the payment is checked while Paymob Checkout is open.
const CHECKOUT_POLL_DELAY = 5000;

patch(PaymentForm.prototype, {

    // #=== DOM MANIPULATION ===#

    /**
     * Choose the payment flow of the selected Paymob payment method.
     *
     * Paymob's embedded card form, and Paymob Checkout shown in a pop-up or a side panel, are
     * processed on the page (direct flow). Paymob Checkout in a full page is a redirection.
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
        if (providerCode !== 'paymob_cf') {
            await super._prepareInlineForm(...arguments);
            return;
        }
        if (flow === 'token') {
            return;  // Saved cards are confirmed on Paymob Checkout.
        }
        const values = this._paymobCfGetInlineFormValues();
        const isDirect = values.flow === 'pixel'
            || (values.flow === 'hosted' && ['popup', 'side_page'].includes(values.display_mode));
        this._setPaymentFlow(isDirect ? 'direct' : 'redirect');
    },

    // #=== PAYMENT FLOW ===#

    /**
     * Show Paymob's embedded card form, or Paymob Checkout in a pop-up or a side panel.
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
        if (providerCode !== 'paymob_cf') {
            await super._processDirectFlow(...arguments);
            return;
        }
        if (processingValues.paymob_cf_error) {  // Paymob refused the payment intention.
            this._displayErrorDialog(_t("Payment processing failed"), processingValues.paymob_cf_error);
            this._enableButton();
            return;
        }
        if (processingValues.paymob_cf_pixel) {
            await this._paymobCfOpenPixel(processingValues.paymob_cf_pixel);
        } else if (processingValues.paymob_cf_checkout) {
            this._paymobCfOpenCheckout(processingValues.reference, processingValues.paymob_cf_checkout);
        }
    },

    /**
     * Send the customer to Paymob Checkout to confirm the payment with a saved card.
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
        const redirectUrl = processingValues.paymob_cf_redirect_url;
        if (providerCode === 'paymob_cf' && redirectUrl?.startsWith('https://')) {
            // Navigate the top window: the bank's pages refuse to be shown in a frame.
            window.top.location = redirectUrl;
        } else {
            return super._processTokenFlow(...arguments);
        }
    },

    /**
     * Build the panel that shows Paymob's checkout or card form over the page.
     *
     * @private
     * @param {string} displayMode - `popup` or `side_page`.
     * @param {Function} onClose - Called when the customer closes the panel.
     * @return {object} The overlay, the body of the panel and a function closing the panel.
     */
    _paymobCfCreatePanel(displayMode, onClose) {
        const overlay = document.createElement('div');
        overlay.className = `o_paymob_cf_checkout o_paymob_cf_checkout_${displayMode}`;
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-label', _t("Secure payment"));
        const panel = document.createElement('div');
        panel.className = 'o_paymob_cf_checkout_panel';
        const header = document.createElement('div');
        header.className = 'o_paymob_cf_checkout_header';
        const title = document.createElement('span');
        const lockIcon = document.createElement('i');
        lockIcon.className = 'oi me-2';
        lockIcon.dataset.icon = 'lock';
        lockIcon.setAttribute('aria-hidden', 'true');
        title.append(lockIcon, _t("Secure payment"));
        const closeButton = document.createElement('button');
        closeButton.type = 'button';
        closeButton.className = 'btn-close';
        closeButton.setAttribute('aria-label', _t("Close"));
        header.append(title, closeButton);
        const body = document.createElement('div');
        body.className = 'o_paymob_cf_checkout_body';
        panel.append(header, body);
        overlay.append(panel);

        const onKeydown = (ev) => {
            if (ev.key === 'Escape') {
                close();
            }
        };
        const close = () => {
            overlay.remove();
            document.removeEventListener('keydown', onKeydown);
            onClose?.();
        };
        closeButton.addEventListener('click', close);
        document.addEventListener('keydown', onKeydown);
        document.body.append(overlay);
        closeButton.focus();
        return { overlay, body, close };
    },

    /**
     * Show Paymob Checkout in a pop-up or a side panel.
     *
     * When the payment ends, Paymob sends the frame to Odoo's return route, which takes the whole
     * window to the payment status page. As the browser may block that navigation, the state of
     * the payment is also checked while the checkout is open, and once more when it is closed.
     *
     * While the checkout is open, only a final state ends it: a pending payment may still wait for
     * the customer in the checkout (wallet PIN and OTP). Once the customer closes the checkout, a
     * pending payment (such as a kiosk reference to pay) is shown on the payment status page.
     *
     * @private
     * @param {string} reference - The reference of the transaction.
     * @param {object} values - The checkout URL, the display mode and the access token.
     * @return {void}
     */
    _paymobCfOpenCheckout(reference, values) {
        let isOpen = true;
        const checkState = async () => {
            let state = 'draft';
            try {
                ({ state } = await this.waitFor(rpc('/payment/paymob_cf/poll', {
                    reference: reference,
                    access_token: values.access_token,
                }, { silent: true })));
            } catch {
                // Network hiccup: try again later.
            }
            const waitingStates = isOpen ? ['draft', 'pending'] : ['draft'];
            if (!waitingStates.includes(state)) {
                window.location = '/payment/status';
                return;
            }
            if (isOpen) {
                this.waitForTimeout(checkState, CHECKOUT_POLL_DELAY);
            }
        };
        const { body } = this._paymobCfCreatePanel(values.display_mode, () => {
            isOpen = false;
            checkState();  // The customer may close the checkout after paying.
        });
        const frame = document.createElement('iframe');
        frame.className = 'o_paymob_cf_checkout_frame';
        frame.title = _t("Secure payment");
        frame.src = values.checkout_url;
        frame.allow = 'payment';
        body.append(frame);
        this.waitForTimeout(checkState, CHECKOUT_POLL_DELAY);
        // Let customers choose another method if they close the checkout without paying.
        this._enableButton();
    },

    /**
     * Show Paymob's card form in a pop-up and let Paymob process the card.
     *
     * The card data stay in Paymob's form. Once Paymob has processed the payment, the customer is
     * sent to Odoo's completion route, which checks the result with Paymob.
     *
     * @private
     * @param {object} values - The keys of the payment intention and the options of the form.
     * @return {void}
     */
    async _paymobCfOpenPixel(values) {
        const { body, close } = this._paymobCfCreatePanel('popup', () => this._enableButton());
        const container = document.createElement('div');
        container.id = `o_paymob_cf_pixel_${Date.now()}`;
        container.className = 'o_paymob_cf_pixel';
        body.append(container);
        try {
            await this.waitFor(loadJS(values.script_url));
        } catch {
            close();
            this._displayErrorDialog(
                _t("Payment processing failed"),
                _t("The secure card form couldn't be loaded. Please try again or choose another payment method."),
            );
            return;
        }
        const isRtl = document.documentElement.dir === 'rtl';
        new window.Pixel({
            publicKey: values.public_key,
            clientSecret: values.client_secret,
            paymentMethods: values.payment_methods,
            elementId: container.id,
            disablePay: false,
            showSaveCard: false,
            forceSaveCard: values.force_save_card,
            afterPaymentComplete: () => {
                window.location = values.complete_url;
            },
            customStyle: {
                Width_of_Container: '100%',
                Container_Padding: '0',
                Direction: isRtl ? 'rtl' : 'ltr',
                Label_Text: {
                    cardLabel: _t("Card details"),
                    savedCardsLabel: _t("Saved cards"),
                    saveCardConsentLabel: _t("Save the card"),
                    cardEndingLabel: _t("Ending in"),
                },
                Placeholder_Text: {
                    holderName: _t("Name on the card"),
                    cardNumber: _t("Card number"),
                    expiryDate: _t("MM / YY"),
                    securityCode: _t("Security code (CVV)"),
                },
                Error_Text: {
                    cardNumber: {
                        required: _t("Enter the card number"),
                        invalid: _t("The card number isn't valid"),
                    },
                    expiryDate: {
                        required: _t("Enter the expiry date"),
                        invalid: _t("The expiry date isn't valid"),
                    },
                    securityCode: _t("Enter the security code (CVV)"),
                    holderName: _t("Enter the name on the card"),
                },
                Button_Text: {
                    viewSavedCardsBtn: _t("View saved cards"),
                    addNewCardBtn: _t("Add a new card"),
                    payBtn: _t("Pay"),
                },
                Hint_Text: {
                    saveCardConsentHint: _t("The card will be saved for your next payments."),
                    cvvModalTitle: _t("Security code (CVV)"),
                    cvvVisaMastercardQuestion: _t("Visa or Mastercard?"),
                    cvvVisaMastercardHint: _t("The 3 digits on the back of the card."),
                    cvvAmexQuestion: _t("American Express?"),
                    cvvAmexHint: _t("The 4 digits on the front of the card, above the number."),
                },
            },
        });
    },

    // #=== GETTERS ===#

    /**
     * Return the values of the inline form of the selected Paymob payment method.
     *
     * @private
     * @return {object} The flow and the display mode of the payment method.
     */
    _paymobCfGetInlineFormValues() {
        const radio = this.el.querySelector('input[name="o_payment_radio"]:checked');
        const inlineFormValues = this._getInlineForm(radio)?.querySelector(
            '[name="o_paymob_cf_inline_form"]'
        )?.dataset.paymobCfInlineFormValues;
        return inlineFormValues ? JSON.parse(inlineFormValues) : {};
    },

});
