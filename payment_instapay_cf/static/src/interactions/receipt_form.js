import { _t } from '@web/core/l10n/translation';
import { registry } from '@web/core/registry';
import { Interaction } from '@web/public/interaction';

/**
 * The form sending the screenshot of an InstaPay transfer: it previews the screenshot, checks
 * its type and size before uploading, and sends the form once.
 */
export class InstapayReceiptForm extends Interaction {
    static selector = '.o_instapay_cf_receipt_form';
    dynamicContent = {
        _root: { 't-on-submit': this.onSubmit },
        'input[name="receipt"]': { 't-on-change': this.onFileChange },
    };

    setup() {
        this.previewUrl = null;
        this.submitting = false;
        this.maxSize = parseInt(this.el.dataset.maxSize || '0', 10);
    }

    destroy() {
        this.revokePreview();
    }

    get fileInput() {
        return this.el.querySelector('input[name="receipt"]');
    }

    onFileChange() {
        const file = this.fileInput.files[0];
        const preview = this.el.querySelector('.o_instapay_cf_preview');
        this.showError('');
        this.revokePreview();
        preview.classList.add('d-none');
        if (!file) {
            return;
        }
        const error = this.checkFile(file);
        if (error) {
            this.showError(error);
            return;
        }
        this.previewUrl = URL.createObjectURL(file);
        preview.src = this.previewUrl;
        preview.classList.remove('d-none');
    }

    onSubmit(ev) {
        if (this.submitting) {
            ev.preventDefault();
            return;
        }
        const file = this.fileInput.files[0];
        const error = file
            ? this.checkFile(file)
            : _t("Add the screenshot of the success screen of your transfer.");
        if (error) {
            ev.preventDefault();
            this.showError(error);
            return;
        }
        this.submitting = true;
        const button = this.el.querySelector('.o_instapay_cf_submit');
        button.querySelector('.o_instapay_cf_submit_label').classList.add('d-none');
        button.querySelector('.o_instapay_cf_submit_busy').classList.remove('d-none');
        button.setAttribute('aria-disabled', 'true');
        button.classList.add('disabled');
    }

    checkFile(file) {
        const acceptedTypes = (this.fileInput.accept || '').split(',').filter(Boolean);
        if (file.type && acceptedTypes.length && !acceptedTypes.includes(file.type)) {
            return _t("The screenshot must be a PNG or JPEG image.");
        }
        if (this.maxSize && file.size > this.maxSize) {
            return _t("The screenshot is too large: send an image of at most 10 MB.");
        }
        return '';
    }

    showError(message) {
        const alert = this.el.querySelector('.o_instapay_cf_form_error');
        alert.textContent = message;
        alert.classList.toggle('d-none', !message);
    }

    revokePreview() {
        if (this.previewUrl) {
            URL.revokeObjectURL(this.previewUrl);
            this.previewUrl = null;
        }
    }
}

/**
 * "Pay another way": asks before cancelling the InstaPay payment.
 */
export class InstapayCancelForm extends Interaction {
    static selector = '.o_instapay_cf_cancel_form';
    dynamicContent = {
        _root: { 't-on-submit': this.onSubmit },
    };

    onSubmit(ev) {
        const confirmed = window.confirm(_t(
            "Cancel this InstaPay payment to pay another way? Don't send money for it afterwards."
        ));
        if (!confirmed) {
            ev.preventDefault();
        }
    }
}

registry
    .category('public.interactions')
    .add('payment_instapay_cf.receipt_form', InstapayReceiptForm)
    .add('payment_instapay_cf.cancel_form', InstapayCancelForm);
