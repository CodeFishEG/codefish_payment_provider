import { browser } from '@web/core/browser/browser';
import { rpc } from '@web/core/network/rpc';
import { registry } from '@web/core/registry';
import { Interaction } from '@web/public/interaction';

// Check every 5 seconds for 10 minutes, then every 30 seconds.
const FAST_POLL_DELAY = 5000;
const SLOW_POLL_DELAY = 30000;
const FAST_POLL_DURATION = 10 * 60 * 1000;

/**
 * The instructions of a pending Paymob payment (kiosk reference, or a payment being confirmed).
 *
 * The page reloads once Paymob confirms or cancels the payment, so that it shows the new status.
 */
export class PaymobPaymentInstructions extends Interaction {
    static selector = '.o_paymob_cf_instructions';
    dynamicContent = {
        '.o_paymob_cf_copy': { 't-on-click': this.copyReference },
    };

    setup() {
        this.startTime = Date.now();
    }

    start() {
        this.schedulePoll();
    }

    schedulePoll() {
        const elapsed = Date.now() - this.startTime;
        this.waitForTimeout(
            () => this.poll(), elapsed < FAST_POLL_DURATION ? FAST_POLL_DELAY : SLOW_POLL_DELAY
        );
    }

    async poll() {
        if (document.hidden) {  // Don't check while the customer is on another tab.
            this.schedulePoll();
            return;
        }
        let state;
        try {
            ({ state } = await this.waitFor(rpc('/payment/paymob_cf/poll', {
                reference: this.el.dataset.reference,
                access_token: this.el.dataset.accessToken,
            }, { silent: true })));
        } catch {
            state = 'pending';  // Network hiccup: try again later.
        }
        if (state === 'pending' || state === 'draft') {
            this.schedulePoll();
        } else {
            browser.location.reload();
        }
    }

    async copyReference(ev) {
        const button = ev.currentTarget;
        try {
            await this.waitFor(browser.navigator.clipboard.writeText(button.dataset.copy));
        } catch {
            return;  // The browser refused; the code stays selectable by hand.
        }
        button.querySelector('.o_paymob_cf_copy_label').classList.add('d-none');
        button.querySelector('.o_paymob_cf_copied_label').classList.remove('d-none');
        this.waitForTimeout(() => {
            button.querySelector('.o_paymob_cf_copy_label').classList.remove('d-none');
            button.querySelector('.o_paymob_cf_copied_label').classList.add('d-none');
        }, 2000);
    }
}

registry
    .category('public.interactions')
    .add('payment_paymob_cf.payment_instructions', PaymobPaymentInstructions);
