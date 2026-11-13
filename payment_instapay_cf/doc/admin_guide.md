# InstaPay Payments: administrator guide

How to set up and run the **InstaPay Payments** module (`payment_instapay_cf`) on Odoo 20. For the daily tasks of
your team and what customers see, read the [user guide](user_guide.md).

## Contents

- [How it works](#how-it-works)
- [Before you start](#before-you-start)
- [1. Install the module](#1-install-the-module)
- [2. Add your receiving accounts](#2-add-your-receiving-accounts)
- [3. Set the review time and the reviewers](#3-set-the-review-time-and-the-reviewers)
- [4. Reminders and cancellation](#4-reminders-and-cancellation)
- [5. Publish](#5-publish)
- [Settings reference](#settings-reference)
- [Accounting](#accounting)
- [Payment statuses](#payment-statuses)
- [Emails](#emails)
- [Security](#security)
- [Limits](#limits)
- [Troubleshooting](#troubleshooting)

## How it works

InstaPay, Egypt's instant payment network, has no API for shops. The money goes straight from the customer's bank
or wallet to your account, and your team confirms each payment by hand:

1. At checkout, the customer chooses **InstaPay**. The order waits for the transfer.
2. The confirmation page and an email show the amount, the order reference and your receiving accounts: your
   InstaPay payment link and QR code, your mobile wallets and your bank accounts, each with a Copy button.
3. The customer sends the money from the InstaPay app (or their bank or wallet app), then uploads a screenshot of
   the receipt on the payment page, with the reference number shown on it.
4. The receipt reaches your team as a review activity, due by the date the customer was given: 2 working days by
   default.
5. A reviewer finds the transfer in the statement of the receiving account and confirms the payment. Odoo then
   confirms the order, posts the payment and reconciles the invoice, as for any online payment. Or the reviewer
   rejects the receipt with a reason, and the customer is asked for a new one.
6. Payments with no receipt get a reminder, then are cancelled after a few days.

## Before you start

- An InstaPay account for your business (the app gives a **payment link** and a **QR code** in your profile), and/or
  mobile wallets and bank accounts in EGP where customers may send the money.
- Accounting set up for the company (a chart of accounts), so that the module can create its journal.
- A working schedule for the company with your working days (in Egypt usually Sunday to Thursday) and, if you use
  it, the Egyptian public holidays (`l10n_eg_cf_hr_holidays` fills them in for you).
- The scheduled actions running: Odoo applies each decision of a reviewer through the payment processing cron, and
  sends the reminders through the hourly InstaPay cron. On a server started with `--max-cron-threads=0`, nothing
  is confirmed until a cron runs.

## 1. Install the module

1. Add the `codefish_payment_provider` folder to `addons_path` and restart Odoo.
2. Turn on developer mode, open **Apps › Update Apps List**, search for **InstaPay Payments** and click
   **Activate**.

The module creates, for each company with a chart of accounts:

- the **InstaPay** provider (**Invoicing › Configuration › Payment Providers**), unpublished;
- the **InstaPay** payment method;
- a bank journal **InstaPay** (code `INSTA`) in EGP, the default journal of the payments;
- the **InstaPay Reviewers** role, with the users who are account managers, set as the reviewers of the provider.

## 2. Add your receiving accounts

Open the provider, tab **Receiving Accounts**, and add one line per place where money may land. Customers see them
in this order (drag the handle to reorder).

| Type | Fields | What customers see |
|---|---|---|
| InstaPay | Payment Link, QR Code, Mobile Number, InstaPay Address | An **Open InstaPay** button on phones, the QR code on computers, the number with Copy |
| Mobile Wallet | Wallet (Vodafone Cash, e& cash, Orange Cash, WE Pay, bank wallet, other), Wallet Number | The wallet and its number with Copy |
| Bank Account | Bank, Account Number and/or IBAN | The bank, the number and the IBAN with Copy |

For every line, also fill in:

- **Beneficiary Name**: the name InstaPay shows the payer, so that they know they're paying the right account;
- **Journal**: the bank or cash journal of this account in Odoo. Payments received there are posted in this journal,
  so they match its bank statement. Leave it empty to use the **InstaPay** journal. It must be in EGP;
- **Note for Customers** (optional).

To get the payment link and the QR code: in the InstaPay app, open your profile, **Share** your payment link (it
looks like `https://ipn.eg/S/yourname/instapay/AbC123`) and export your QR code as an image. Paste the link and
upload the image. Without an image, the module draws a QR code from the link.

The module checks what you enter: the link must start with `https://ipn.eg/S/`, mobile numbers must be Egyptian
mobile numbers (010, 011, 012, 015), the IBAN must be a valid Egyptian IBAN (`EG` + 27 digits). Recent versions of
the InstaPay app don't let payers type an InstaPay address by hand: give at least the link or the QR code.

## 3. Set the review time and the reviewers

In the **InstaPay** group of the **Configuration** tab:

- **Review Time (Working Days)**: 2 by default (48 working hours). Each receipt gets a deadline counted in working
  time on the **Working Schedule**: a receipt sent on Thursday at 15:00, on a Sunday-to-Thursday 9:00–17:00
  schedule, is due on Monday at 15:00. Public holidays (global time off of the schedule) are skipped. The customer
  sees the date: "*Your company* will confirm your payment by Monday 16 November".
- **Working Schedule**: empty uses the company's. A warning shows when the schedule works on Fridays, or when the
  company has no time zone. Without a schedule or a time zone, whole days are added, Fridays and Saturdays skipped.
- **Reviewer** or **Reviewers Role**: who gets the review activity of each receipt. Add or remove reviewers in the
  role (**Discuss › Configuration › Roles**) rather than on the provider. Reviewers need the **Invoicing**
  access (Billing or Accountant).
- **Require the Transfer Reference**: on by default. The reference number of the receipt is the best way to find
  the transfer in a statement and to detect a receipt used twice.

The review time is counted in hours: review days × the schedule's average hours per day. On a schedule with
shorter days (Ramadan hours, half days), the deadline is still a good estimate, not an exact day count.

## 4. Reminders and cancellation

- **Reminder After (Days)**: 1 by default. A customer who chose InstaPay but sent no receipt gets one reminder.
- **Cancel After (Days)**: 3 by default. The payment is then cancelled and the customer gets an email with a link
  to pay again. 0 never cancels.

Both count from the checkout, or from the last rejected receipt. A payment with a receipt waiting for review is
never reminded or cancelled. The cron **InstaPay: remind and cancel unpaid payments** runs every hour.

## 5. Publish

Click the **Unpublished** button of the provider to publish it. Odoo refuses to publish it without at least one
active receiving account. InstaPay accepts EGP only, and isn't offered for saving payment methods.

The provider's **Maximum Amount** is 70,000 EGP, the InstaPay limit per transfer. Customers with larger orders see
the payment method only if you raise it; the payment page then tells them to send several transfers and upload
each receipt.

## Settings reference

| Setting | Default | Notes |
|---|---|---|
| Receiving Accounts | — | At least one to publish |
| Review Time (Working Days) | 2 | 1 to 10 |
| Working Schedule | Company's | Holidays skipped |
| Reviewer / Reviewers Role | InstaPay Reviewers | Gets the review activities |
| Require the Transfer Reference | On | |
| Reminder After (Days) | 1 | 0: no reminder; must be before the cancellation |
| Cancel After (Days) | 3 | 0: never |
| Email the Customers | On | Off: no InstaPay email at all |
| Maximum Amount | 70,000 | InstaPay's limit per transfer |

## Accounting

- A confirmed payment creates an `account.payment` in the journal of the account where the reviewer found the money
  ("Received In"), with its **manual** incoming payment method, or in the **InstaPay** journal when the account has
  no journal. The payment date is the date received, and its memo is the InstaPay reference.
- The screenshots are attached to the payment.
- Entries: debit the outstanding receipts account of the journal, credit the customer's receivable; Odoo reconciles
  the invoice. Reconcile the outstanding receipts with the bank statement of the account as usual.
- InstaPay fees are paid by the sender: you receive the full amount.
- Refunds: InstaPay transfers can't be reversed. Make a credit note, send the money back from your app, and register
  the outgoing payment with the reference of that transfer.
- Overpayments: confirm the amount received (it may be higher than due); handle the difference as a customer credit
  or a refund.

## Payment statuses

| InstaPay status | Payment state | Meaning |
|---|---|---|
| Waiting for the transfer | Pending | No receipt yet |
| Receipt to review | Pending | At least one receipt waits for a reviewer |
| Receipt rejected | Pending | All receipts rejected; the customer may send a new one |
| Confirmed | Confirmed | A reviewer confirmed the payment |
| Cancelled | Cancelled | Cancelled by the customer ("Pay another way"), by your team, or after the delay |

A cancelled payment can still be confirmed if the money arrives late: add the receipt from the transaction
(**Add Receipt**) and confirm it.

The core **Mark as Confirmed** action is blocked for InstaPay: the receipt review is the only way to confirm.

## Emails

Sent to the customer, in their language, without Odoo's email layout:

| Email | When |
|---|---|
| How to pay with InstaPay | The order waits for the transfer |
| We received your receipt | The customer uploaded a receipt (with the date of the review) |
| We couldn't confirm your transfer | A receipt was rejected (with the reason and the message) |
| Reminder | After **Reminder After (Days)** without a receipt |
| Payment confirmed | Confirmed, when no sales order sends its own confirmation |
| Payment cancelled | Cancelled by your team or after the delay (with a Pay again link) |

The templates are in **Settings › Technical › Email Templates** (search "InstaPay").

## Security

- **Screenshots** are checked and re-encoded before they are saved: only PNG and JPEG images, at most 10 MB and
  10,000 pixels a side, are accepted; the stored copy is at most 2,560 pixels, without metadata (location, phone
  model) or anything hidden after the image. SVG, PDF, HTML, GIF, WEBP and HEIC files are refused.
- **The payment page** (`/payment/instapay_cf/pay/<id>/<token>`) is protected by a token tied to the payment, the
  customer and the database secret. Anyone with the link can see the payment details and send a receipt, so it is
  only sent to the customer (confirmation page and emails). The page is never cached or indexed.
- **Uploads** are limited to 10 receipts per payment, one every 30 seconds, and refused once the payment is
  confirmed or cancelled.
- **Evidence** can't be changed: the screenshot and the details declared with it are read-only once saved, and
  accepted receipts can't be deleted. A reference can be accepted only once per company.
- **Access**: Billing and Accountant users review receipts; Read-only accountants see them; portal and public users
  have no access to the models (the pages use the token).
- **Fraud**: receipts and SMS can be faked. The confirmation asks the reviewer to tick "I found this transfer in the
  statement of the receiving account", and shows warnings for a screenshot or reference already sent for another
  payment, an amount that differs, and a transfer dated before the order or in the future.

## Limits

- InstaPay's own limits (Central Bank of Egypt, 2024): 70,000 EGP per transfer, 120,000 per day, 400,000 per month
  per payer.
- The payment link and the QR code of an InstaPay account are fixed: they don't carry the amount or the order. The
  customer types the amount; the reference number of the receipt links the transfer to the order.

## Troubleshooting

| Problem | Check |
|---|---|
| InstaPay isn't offered at checkout | Published, at least one active receiving account, currency EGP, amount ≤ Maximum Amount, the customer's country allowed |
| Nobody gets the review activities | **Reviewer** or the users of the **Reviewers Role**; the warning on the provider |
| The review date is wrong | The company's time zone, the **Working Schedule** (Friday warning), its public holidays |
| A confirmed receipt doesn't confirm the order | The scheduled action **Payment: Run Processing** must run; check the transaction's chatter |
| "The journal … has no incoming payment method" | Add a manual incoming payment method in the journal's Incoming Payments tab |
| A customer's screenshot is refused | It must be a PNG or JPEG image of at most 10 MB; ask for a screenshot (not a photo of the screen) |
| No email | **Email the Customers**, the customer's email address, the outgoing mail server |

InstaPay and IPN are trademarks of Egyptian Banks Company (EBC). This module is not affiliated with or endorsed by
EBC or InstaPay; their names and logos are used only to show that the payment method is accepted.
