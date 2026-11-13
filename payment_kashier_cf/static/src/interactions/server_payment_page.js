import { browser } from '@web/core/browser/browser';
import { _t } from '@web/core/l10n/translation';
import { rpc } from '@web/core/network/rpc';
import { registry } from '@web/core/registry';
import { Interaction } from '@web/public/interaction';

// Check every 5 seconds for 2 minutes, then every 15 seconds.
const FAST_POLL_DELAY = 5000;
const SLOW_POLL_DELAY = 15000;
const FAST_POLL_DURATION = 2 * 60 * 1000;

/**
 * The page of a payment Odoo asks Kashier for without Kashier's page: the customer enters a mobile number
 * (wallet request, Basata code) or gets an InstaPay QR, then waits here for the result.
 */
export class KashierServerPaymentPage extends Interaction {
    static selector = '.o_kashier_cf_server_page';
    dynamicContent = {
        '.o_kashier_cf_start_form': { 't-on-submit': this.onSubmit },
    };

    setup() {
        this.startTime = Date.now();
        this.busy = false;
        this.data = this.el.dataset;
    }

    start() {
        if (this.data.state !== 'pending') {
            return;
        }
        if (this.data.kind === 'basata') {
            // The code is on the page: the customer pays later at a kiosk, nothing to wait for here.
            this.startCountdown(this.data.expiresAt);
        } else {
            this.startWaiting(this.data.expiresAt);
        }
    }

    // #=== START ===#

    async onSubmit(ev) {
        ev.preventDefault();
        if (this.busy) {
            return;
        }
        const form = ev.currentTarget;
        const input = form.querySelector('input[name="value"]');
        // InstaPay: the QR button sends nothing, the request button sends the address.
        const sendsAddress = ev.submitter?.classList.contains('o_kashier_cf_request');
        const value = this.data.kind === 'instapay' && !sendsAddress ? '' : (input?.value || '');
        this.busy = true;
        this.setButtons(form, true);
        this.showError('');
        let result;
        try {
            result = await this.waitFor(rpc(this.data.startUrl, {
                tx_id: parseInt(this.data.txId),
                access_token: this.data.accessToken,
                value: value,
            }));
        } catch {
            result = { ok: false, can_retry: true, message: _t("The payment couldn't be started. Try again.") };
        }
        this.busy = false;
        if (!result.ok) {
            this.showError(result.message);
            this.setButtons(form, !result.can_retry);
            if (result.final) {
                browser.location.assign(result.status_url);
            }
            return;
        }
        form.classList.add('d-none');
        if (this.data.kind === 'basata' && result.code) {
            const block = this.el.querySelector('.o_kashier_cf_code_block');
            block.querySelector('.o_kashier_cf_code').textContent = result.code;
            block.classList.remove('d-none');
            this.startCountdown(result.expires_at);
            return;
        }
        if (result.qr_data_uri) {
            const qr = this.el.querySelector('.o_kashier_cf_qr');
            qr.src = result.qr_data_uri;
            qr.classList.remove('d-none');
        }
        this.startWaiting(result.expires_at);
    }

    // #=== WAITING ===#

    startWaiting(expiresAt) {
        this.el.querySelector('.o_kashier_cf_waiting')?.classList.remove('d-none');
        this.startCountdown(expiresAt);
        this.schedulePoll();
    }

    startCountdown(expiresAt) {
        if (!expiresAt) {
            return;
        }
        const end = new Date(`${expiresAt.replace(' ', 'T')}Z`).getTime();
        const tick = () => {
            const left = Math.max(0, Math.round((end - Date.now()) / 1000));
            const text = `${String(Math.floor(left / 60)).padStart(2, '0')}:${String(left % 60).padStart(2, '0')}`;
            for (const el of this.el.querySelectorAll('.o_kashier_cf_countdown')) {
                el.textContent = text;
            }
            if (left > 0) {
                this.waitForTimeout(tick, 1000);
            }
        };
        tick();
    }

    schedulePoll() {
        const elapsed = Date.now() - this.startTime;
        this.waitForTimeout(() => this.poll(), elapsed < FAST_POLL_DURATION ? FAST_POLL_DELAY : SLOW_POLL_DELAY);
    }

    async poll() {
        if (document.hidden) {
            this.schedulePoll();
            return;
        }
        let result;
        try {
            result = await this.waitFor(rpc(this.data.pollUrl, {
                tx_id: parseInt(this.data.txId),
                access_token: this.data.accessToken,
            }, { silent: true }));
        } catch {
            this.schedulePoll();  // Network hiccup: check again later.
            return;
        }
        if (['draft', 'pending'].includes(result.state)) {
            this.schedulePoll();
        } else {
            browser.location.assign(result.status_url);
        }
    }

    // #=== HELPERS ===#

    setButtons(form, disabled) {
        for (const button of form.querySelectorAll('button')) {
            button.disabled = disabled;
        }
    }

    showError(message) {
        const error = this.el.querySelector('.o_kashier_cf_error');
        if (!error) {
            return;
        }
        error.textContent = message || '';
        error.classList.toggle('d-none', !message);
    }
}

registry
    .category('public.interactions')
    .add('payment_kashier_cf.server_payment_page', KashierServerPaymentPage);
