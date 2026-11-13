import { browser } from '@web/core/browser/browser';
import { registry } from '@web/core/registry';
import { Interaction } from '@web/public/interaction';

/**
 * The InstaPay transfer details: copy buttons for the amount, the reference and the receiving
 * accounts, so customers paste them in their bank or wallet app.
 */
export class InstapayPaymentInstructions extends Interaction {
    static selector = '.o_instapay_cf_instructions';
    dynamicContent = {
        '.o_instapay_cf_copy': { 't-on-click': this.copyValue },
    };

    async copyValue(ev) {
        const button = ev.currentTarget;
        try {
            await this.waitFor(browser.navigator.clipboard.writeText(button.dataset.copy));
        } catch {
            return;  // The browser refused; the value stays selectable by hand.
        }
        const copyLabel = button.querySelector('.o_instapay_cf_copy_label');
        const copiedLabel = button.querySelector('.o_instapay_cf_copied_label');
        copyLabel.classList.add('d-none');
        copiedLabel.classList.remove('d-none');
        this.waitForTimeout(() => {
            copyLabel.classList.remove('d-none');
            copiedLabel.classList.add('d-none');
        }, 2000);
    }
}

registry
    .category('public.interactions')
    .add('payment_instapay_cf.payment_instructions', InstapayPaymentInstructions);
