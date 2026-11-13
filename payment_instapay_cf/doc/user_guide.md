# InstaPay Payments: user guide

What customers see when they pay with InstaPay, and how your team reviews their receipts. To set the module up,
read the [administrator guide](admin_guide.md).

## Contents

- [What customers see](#what-customers-see)
- [Review a receipt](#review-a-receipt)
- [Confirm a payment](#confirm-a-payment)
- [Reject a receipt](#reject-a-receipt)
- [A customer sent the receipt another way](#a-customer-sent-the-receipt-another-way)
- [Cancel a payment](#cancel-a-payment)
- [Late transfers](#late-transfers)
- [Answering customers](#answering-customers)

## What customers see

1. **Checkout.** The customer chooses **InstaPay**. The hint under it says that the company confirms the payment
   within the review time, after receiving the receipt.
2. **Payment details**, on the confirmation page, in the customer portal (order or invoice) and by email:
   - the exact amount and the order reference, each with a **Copy** button;
   - your receiving accounts: on a phone, an **Open InstaPay** button opens the app on your account; on a computer,
     the QR code is scanned with the phone; numbers and IBANs have Copy buttons;
   - a reminder that InstaPay fees are paid by the sender;
   - **Upload your receipt**, and on a computer a QR code to continue on the phone.
3. **Payment page.** The customer uploads a screenshot of the success screen and types the reference number shown
   on it. The amount and the date are filled in; they correct them if needed. With several receiving accounts, they
   say where they sent the money.
4. **After the upload:** "*Your company* will confirm your payment by Monday 16 November", and an email with the
   same date.
5. **Outcome:** an email when the payment is confirmed (or the order confirmation), when a receipt is rejected (with
   your message and a link to send a new one), or when the payment is cancelled (with a link to pay again).

Until they send a receipt, customers can choose **Pay another way**: the InstaPay payment is cancelled and they can
pay the order with another method.

Everything is shown in the customer's language, Arabic included, and names your company, never the software.

## Review a receipt

Each receipt gives the reviewer an activity **Review InstaPay receipt**, due on the date the customer was given.
Open it from the activity, or from **Invoicing › Customers › InstaPay Receipts**:

- the list opens on **To Review**, the most urgent first; overdue receipts are red;
- filters: Overdue, Possible Duplicates, Amount Mismatch, Added by Staff, Accepted, Rejected, My Activities;
- the kanban view shows the screenshots.

The receipt form shows the screenshot next to the details, the amount to pay and the order date. Warnings show at
the top:

| Warning | What to do |
|---|---|
| Review deadline is past | The customer was promised a confirmation by now: review it first |
| Same screenshot or reference sent for another payment | Most likely a receipt used twice: check both payments |
| Amount sent differs | Check the amount actually received |
| Transfer dated before the payment started, or in the future | Check the date in the statement |

**Never confirm from the screenshot or an SMS alone**: both can be faked. Open the bank, wallet or InstaPay app of
the account the customer sent the money to, and find the transfer: same amount, same date and time, and a reference
that wasn't used before.

## Confirm a payment

1. On the receipt, click **Confirm Payment**.
2. Check **Received In** (the account where you found the money), **Amount Received** and **Received On**.
3. Tick **I found this transfer in the statement of the receiving account** (and **I checked the warnings above**
   if there are warnings), then **Confirm Payment**.

Within a few seconds, the order is confirmed, the payment is posted in the journal of that account with the
InstaPay reference, and the invoice is paid. The screenshot is kept with the payment.

Odoo refuses to confirm when:

- the amount received is lower than the amount due: reject the receipt with the reason **Amount lower than
  expected**, so the customer sends the rest;
- the invoice or the order was already paid another way;
- the reference was already accepted for another payment.

## Reject a receipt

1. On the receipt, click **Reject Receipt**.
2. Choose the **Reason**. The **Message to the Customer** is filled in, in the customer's language; adapt it if
   needed.
3. Tick **Also cancel the payment** only when the customer must not send another receipt (for example a receipt
   used twice). Otherwise the payment keeps waiting.
4. Click **Reject Receipt**. The customer gets an email with the message and a link to send a new receipt.

## A customer sent the receipt another way

When a customer sends the screenshot by WhatsApp or email, open the payment (the **Payments** smart button of the
sales order, or **Transactions** on the InstaPay provider) and click **Add Receipt**. Upload the screenshot, fill
in the reference and the amount, and save. The receipt is marked **Added by Staff**; review it as any other.

## Cancel a payment

On the payment, click **Cancel Payment**, choose a reason and write a message for the customer. Receipts still to
review are rejected. The customer gets an email with a link to pay again.

## Late transfers

A payment cancelled after the delay can still be confirmed if the money arrives: open the payment, click **Add
Receipt**, then confirm the receipt.

## Answering customers

| The customer says | Answer |
|---|---|
| "I can't type your InstaPay address" | Recent versions of the app don't allow it: use the Open InstaPay button (phone) or scan the QR code |
| "The amount isn't in the link" | The link and the QR code open your account; the customer types the amount shown on the page |
| "My upload is refused" | Send a screenshot (PNG or JPEG, at most 10 MB) of the success screen, not a photo or a PDF |
| "I sent more than 70,000 EGP" | InstaPay allows 70,000 per transfer: several transfers, one receipt each |
| "When will you confirm?" | By the date shown after the upload and in the email |
| "I want my money back" | InstaPay transfers can't be reversed: make a credit note and send the money back from your app |
