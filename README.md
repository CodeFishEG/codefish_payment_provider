# codefish_payment_provider

Payment providers for Odoo 20.0, built by codefish, the software development division of mediafish. The
repository holds four modules:

- **Fawry Payments** connects Odoo to Fawry (FawryPay), the Egyptian payment network: cards with 3-D Secure, Fawry
  reference codes paid in cash, mobile wallets, myFawry and Fawry's installment partners.
- **Paymob Payments** connects Odoo to Paymob in Egypt, Saudi Arabia, the UAE, Oman and Pakistan: cards, wallets,
  kiosk payments, bank installments and buy-now-pay-later brands, Apple Pay and Google Pay.
- **InstaPay Payments** takes payments by InstaPay, mobile wallet or bank transfer in Egypt, without any API: the
  customer sends the money and uploads the receipt, and the accounting team confirms it within 2 working days.
- **Kashier Payments** connects Odoo to Kashier, the Egyptian payment gateway: customers pay on Kashier's hosted
  page with Visa, Mastercard and Meeza cards, mobile wallets, instalments and buy-now-pay-later brands such as valU.

## Contents

- [Modules](#modules)
- [Requirements](#requirements)
- [Installation](#installation)
- [Fawry Payments](#fawry-payments-payment_fawry_cf)
- [Paymob Payments](#paymob-payments-payment_paymob_cf)
- [InstaPay Payments](#instapay-payments-payment_instapay_cf)
- [Kashier Payments](#kashier-payments-payment_kashier_cf)
- [Development](#development)
- [Licence](#licence)

## Modules

| Technical name | Name | What it does | Licence | Depends on |
|---|---|---|---|---|
| [`payment_fawry_cf`](payment_fawry_cf) | Fawry Payments | Fawry payment provider: FawryPay Express Checkout or the server-to-server APIs, saved cards, refunds, reference codes and wallet QR codes shown on the website | OPL-1 (paid) | `payment`, `account_payment` |
| [`payment_paymob_cf`](payment_paymob_cf) | Paymob Payments | Paymob payment provider for five countries: Paymob Checkout or an embedded card form, saved cards, MOTO charges, authorize and capture, refunds, payment split, kiosk references shown on the website | OPL-1 (paid) | `payment`, `account_payment` |
| [`payment_instapay_cf`](payment_instapay_cf) | InstaPay Payments | Manual InstaPay, mobile wallet and bank transfer payments: payment details with copy buttons, link and QR code, receipt upload, review by the accountants within working days, reminders and cancellation | OPL-1 (paid) | `payment`, `account_payment`, `mail`, `resource` |
| [`payment_kashier_cf`](payment_kashier_cf) | Kashier Payments | Kashier payment provider: Kashier's hosted payment page for cards or every method of the account, saved cards (also charged without the customer), refunds, authorize and capture, status always read from Kashier's API | OPL-1 (paid) | `payment`, `account_payment` |

## Requirements

- Odoo 20.0, Community or Enterprise. Module versions follow `20.0.x.y.z`.
- Python 3.12 to 3.14 and PostgreSQL 16 or later, as set in Odoo's own `odoo/release.py`.
- Fawry Payments: a Fawry merchant account (merchant code and secure key). Fawry gives a test (staging) account
  first.
- Paymob Payments: a Paymob account (secret, public and API keys, HMAC secret, integration IDs), in test mode
  first.
- InstaPay Payments: an InstaPay account for the business (payment link and QR code from the app) and/or mobile
  wallets and bank accounts in EGP. No API key: InstaPay has no merchant API.
- Kashier Payments: a Kashier merchant account (Merchant ID, Payment API Key and Secret Key), in test mode first.
- The Odoo server must be reachable from the internet over HTTPS in production, so that the payment providers can
  send their notifications and redirect customers back.

## Installation

1. Clone the repository on branch `20.0`:

   ```bash
   git clone --branch 20.0 git@github.com:CodeFishEG/codefish_payment_provider.git
   ```

2. Add the clone folder (the repository root, which holds the module folders) to `addons_path`:

   ```ini
   [options]
   addons_path = /path/to/odoo/addons,
       /path/to/codefish_payment_provider
   ```

3. Restart the Odoo server, turn on developer mode, then open **Apps › Update Apps List**.
4. In **Apps**, remove the **Apps** filter, search for **Fawry Payments** (`payment_fawry_cf`), **Paymob
   Payments** (`payment_paymob_cf`), **InstaPay Payments** (`payment_instapay_cf`) or **Kashier Payments**
   (`payment_kashier_cf`) and click **Activate**.

From the command line:

```bash
python odoo-bin module install -c <config> -d <database> payment_fawry_cf
```

## Fawry Payments (`payment_fawry_cf`)

Guides, with screenshots:

- [Administrator guide](payment_fawry_cf/doc/admin_guide.md): set-up step by step, settings, accounting, payment
  statuses, security, troubleshooting.
- [User guide](payment_fawry_cf/doc/user_guide.md): what customers see, and the daily tasks of the team (checking,
  canceling and refunding payments, payment links, saved cards).

The Apps store page (`static/description/index.html`) holds the same guides.

### Integration types

The provider has two integration types, chosen in its **Configuration** tab.

| | FawryPay Express Checkout | Server-to-Server APIs |
|---|---|---|
| Card | Fawry's hosted checkout (3-D Secure by Fawry) | Fawry's secure card page, then a 3-D Secure charge of the card token by Odoo |
| Pay at Fawry | Fawry's hosted checkout shows the reference code | Odoo creates the reference code and shows it on the website |
| Mobile wallet | Hosted checkout | Odoo sends a request to the customer's wallet, or shows a QR code |
| myFawry | Hosted checkout | Odoo shows the QR code and the myFawry app link |
| Fawry Yellow Card, valU, Forsa, Souhoola, FawryPay (all methods) | Hosted checkout | Hosted checkout |
| Saved cards | No (Fawry's checkout doesn't return the card) | Yes, at checkout or from **My payment methods** |

Fawry's hosted checkout opens in a **full page**, a **pop-up window** or a **side panel** (setting **Checkout
Display**). Odoo's server creates the checkout session in every case; the pop-up and the side panel show Fawry's
page in a frame and read the result that page posts back. iPhone, iPad and Mac always get the full page, as
Fawry's own library does.

The server-to-server integration keeps the shop out of PCI-DSS scope: card numbers are entered on Fawry's
Web Client Card Tokenization page, as Fawry requires from merchants that are not PCI-DSS certified, and Odoo
only stores Fawry's card token. Fawry asks the customer to confirm every card payment with their bank
(3-D Secure), so saved cards are not charged without the customer (for example by subscriptions).

### Payment methods

| Code | Name | Logo | Default |
|---|---|---|---|
| `card` | Card, with the brands Visa, Mastercard and Meeza | Odoo's card logos | active |
| `pay_at_fawry` | Pay at Fawry (reference code) | module | active |
| `mobile_wallet_eg` | Mobile Wallet | Odoo's wallet logo | active |
| `myfawry` | myFawry | module | |
| `fawry_yellow_card` | Fawry Yellow Card | module | |
| `valu`, `forsa`, `souhoola` | valU, Forsa, Souhoola | Odoo's logos | |
| `fawry` | FawryPay (every method of the account, chosen on Fawry's checkout) | Fawry logo | |

Methods other than card are limited to Egypt and EGP. Turn on the methods Fawry enabled on your account.

### Accounting journal

Installing the module creates, in each company, a bank journal named **Fawry Pay** (in Arabic
"مدفوعات فورى"), code `FAWRY`, in **EGP**, with its own bank account, and sets it as the **Payment Journal**
of the company's Fawry provider. Payments received through Fawry are posted in it, apart from your other
bank journals.

- A company without a chart of accounts gets the journal when its chart is installed (for example a company
  created later).
- The journal is found again by its code: reinstalling the module doesn't create a second one, and a journal
  you already named `FAWRY` is reused.
- The Arabic name is set for the Arabic languages installed when the journal is created.
- Uninstalling the module keeps the journal and its entries.

### Configuration

| Field | Use |
|---|---|
| Merchant Code, Secure Key | From Fawry. **Test Connection** checks them against Fawry. |
| Fawry Integration | FawryPay Express Checkout or Server-to-Server APIs. |
| Checkout Display | Full page, pop-up window or side panel, for Fawry's hosted checkout. |
| Payment Expiry (Hours) | How long a reference code, wallet request or QR code stays payable (default 48). |
| Notification URL | Give it to Fawry; Odoo also sends it with every payment. |
| Live | Off: Fawry's staging environment. On: production. |
| Payment Journal | Fawry Pay, created by the module (see above); you can choose another bank journal. |

The provider accepts EGP only.

### How payments stay in sync

- **Notifications.** Fawry's server notifications (V2) are checked against their `messageSignature` and
  recorded.
- **Returns.** When the customer comes back from Fawry, a charge response signed by Fawry is recorded as is;
  otherwise Odoo asks Fawry for the payment status (Get Payment Status V2).
- **Waiting page.** A pending payment shows its instructions (reference code with a copy button, QR code,
  myFawry link, amount, deadline). The page checks the payment every few seconds and reloads once Fawry confirms
  or cancels it.
- **Background check.** The scheduled action **Fawry: check pending payments** runs every 15 minutes for pending
  Fawry payments of the last 10 days.
- On a transaction, **Check Fawry Status** fetches the status, and **Cancel Fawry Payment** cancels an unpaid
  reference code or wallet request at Fawry.

Refunds (full and partial) use Fawry's refund API. A card entered for a single payment is deleted at Fawry once
the payment is over; removing a saved card in Odoo deletes it at Fawry too.

### Saved cards

With the Server-to-Server integration and **Allow Saving Payment Methods**, signed-in customers:

- add a card while paying (**Save my payment details**) or from **My Account › Payment Methods**, on Fawry's
  card page;
- choose a saved card, or a new one, at checkout, on portal invoices and orders and on payment links; every
  payment is confirmed with 3-D Secure;
- remove a card: it is deleted at Fawry too.

Each card shows its last four digits and expiry date. Whenever the cards are shown (`_prepare_payment_form_values`),
Odoo lists the customer's cards at Fawry (List Card Tokens, at most every 10 minutes per card) and archives the
ones Fawry no longer has or that expired, without deleting them at Fawry again. Nothing changes when Fawry can't be
reached. Cards found at Fawry but unknown to Odoo are never imported: the customer may have entered them for a
single payment, and the Fawry customer profile is the partner id, which isn't unique across databases.

### Bank installments and payment split

- **Bank installments** (Server-to-Server APIs): after the card is entered, or a saved card is chosen, the
  customer chooses between paying in full and the installment plans of their bank that Fawry activated on the
  account (Get Installment Plans, filtered by card prefix, amount, dates and products). The card token is then
  charged with `installmentPlanId`, signed before the return URL.
- **Payment split**: each charge item carries `accounts` with the share of every sub-account that applies to it
  (all items or selected products) and the rest for the merchant's own account. Set on the provider's
  Payment Split tab (model `payment.fawry.split.account`).

Both are turned on and off on the Fawry provider (**Bank Installments**, **Payment Split**).

### Fawry error codes

`const.ERROR_CODES` explains every Fawry error code (Fawry's Error Codes page, the APIs' status codes, and codes
met on staging such as `8000453` and `9985`). Fawry's errors are raised as `FawryError`, which keeps the code;
customers get the explanation of card and bank errors, or a neutral message with the code for errors about the
merchant's account; staff see the explanation in the transaction's Fawry tab.

### Usage

- **Website:** the methods appear at the payment step of the shop, on invoices in the customer portal and on
  payment links.
- **Customers:** cards are added, chosen and removed from **My Account › Payment Methods** and at checkout
  (server-to-server integration, see [Saved cards](#saved-cards)).
- **Back office:** **Invoicing › Configuration › Payment Providers › Fawry**; transactions are in **Invoicing ›
  Configuration › Payment Transactions** (developer mode).

### Testing on Fawry's staging

Use Fawry's staging test cards (CVV 100, expiry 01/39): Visa 4508 7500 1574 1019, Mastercard
5123 4500 0000 0008. Pay staging reference codes at Fawry's Integration POS Emulator
(https://developer.fawrystaging.com/public/pay-order/). In test mode, administrators open it from Odoo:
**POS Emulator** on the provider, **Pay at POS Emulator** on a pending reference-code transaction, or the "Test
mode" box of the confirmation page. These lead to `/payment/fawry/pos_emulator/<tx id>`, a page for
administrators only that gives the code to copy and updates by itself once Fawry has the payment. Fawry's
firewall refuses forms posted from other sites, so the code can't be filled in for you. Fawry's card page
refuses `localhost` return URLs: run the server on `http://127.0.0.1:<port>` and set `web.base.url` to it.

## Paymob Payments (`payment_paymob_cf`)

Guides, with screenshots:

- [Administrator guide](payment_paymob_cf/doc/admin_guide.md): set-up step by step, integrations, saved cards,
  capture, payment split, settings, accounting, statuses, response codes, security, troubleshooting.
- [User guide](payment_paymob_cf/doc/user_guide.md): what customers see, and the daily tasks of the team.

The Apps store page (`static/description/index.html`) holds the same guides.

The module is independent of Odoo's own basic connector (`payment_paymob`, provider code `paymob`): it has its own
provider code (`paymob_cf`), fields, payment methods and routes, and never renames anything in the Paymob account.

### Integration types

| | Paymob Checkout (`hosted`) | Embedded checkout (`embedded`) |
|---|---|---|
| Cards, Apple Pay, Google Pay | Paymob's Unified Checkout | Paymob's card form (Pixel, `paymob-pixel@1.2.10`) in a pop-up on the payment page |
| Wallets, kiosk, installments, BNPL | Unified Checkout | Unified Checkout |
| Display of Unified Checkout | Full page, pop-up or side panel (iframe) | Same |
| Saved cards | No | Yes: TOKEN callback; customer-present payments reopen Checkout with `card_tokens`; offline charges use the MOTO integration and `payments/pay` |
| Manual capture | Auth integration | Auth integration |

Each payment creates a payment intention (`POST /v1/intention/`, secret key) with the integration IDs of the chosen
method, the order lines as items, the billing data, a unique `special_reference` (reference + database code),
`notification_url`, `redirection_url` and, with payment split, `split_amounts`.

### Countries and methods

One platform per country (`accept`, `ksa`, `uae`, `oman`, `pakistan` `.paymob.com`), test and live alike: the keys
and integration IDs decide the mode. The provider's country sets the currency (EGP, SAR, AED, OMR, PKR). 22
primary methods (with country and currency limits) and 6 card brands; each method holds its Paymob integration ID,
filled by **Sync Integrations** (`GET /api/ecommerce/integrations`, by gateway type).

### Apple Pay

Paymob's "Apple Pay [All regions]": Egypt, Saudi Arabia, the UAE and Oman, live integrations only, full and
partial refunds. The provider's **Apple Pay** tab holds the steps for the administrator and **Activate Apple Pay**
(`action_paymob_cf_activate_apple_pay`), which checks the country, the live mode and the Apple Pay integration
(fetched from Paymob when missing) and, for the embedded checkout, the domain file, then turns the method on.

- Paymob Checkout: no Apple set-up; Apple Pay always opens Paymob Checkout in a full page (no frame).
- Embedded checkout (Pixel `apple-pay`): the merchant verifies the website's domain with their Apple Merchant ID and
  sends Paymob their two certificates. The domain file uploaded on the provider is served at
  `/.well-known/apple-developer-merchantid-domain-association`. That route shadows the one of Odoo's
  `payment_stripe` (modules are routed alphabetically) and serves Stripe's file when no Paymob file is set.
- The payment form hides Apple Pay when `ApplePaySession.canMakePayments()` is false (other browsers, no HTTPS).

### How payments stay in sync

- Webhook `/payment/paymob_cf/webhook`: TRANSACTION and TOKEN callbacks, checked with HMAC-SHA512 (the documented
  field order), matched by the order Paymob signs (refunds, captures and voids by their own transaction ID).
- Return routes (`/return`, `/return_frame` for the pop-up and side panel, `/complete` for the card form): the
  status is fetched with the transaction inquiry API (Bearer token, cached 50 minutes); a signed redirection is
  used only when Paymob can't be reached.
- The waiting page polls `/payment/paymob_cf/poll`; a cron checks pending payments every 15 minutes; **Check
  Paymob Status** on the transaction.

### Refunds, capture, void, errors

Refunds (`void_refund/refund`, full or partial), captures (`capture`, partial) and voids (`void_refund/void`) are
sent by Odoo and recorded on their own transactions. `const.ERROR_CODES` explains the bank response codes, Paymob's
risk declines and API errors, with a customer message and a staff message.

### Verified against Paymob

Built from Paymob's documentation and tested with mocked API calls (the HMAC strings against Paymob's documented
examples), then checked on 2026-11-12 with an Egyptian test account (card, wallet and kiosk integrations), on a
local server:

- **Test Connection** and **Sync Integrations** (the integrations list and its fields);
- Paymob Checkout in a full page and in a pop-up: card with 3-D Secure, mobile wallet (PIN and OTP) and kiosk
  (reference in `data.bill_reference`), the order confirmed, a partial refund;
- the HMAC of the redirection, signed over `order` (not `order_id`), with Paymob's real values;
- the status inquiry by merchant order, and **Check Paymob Status**;
- the embedded card form with 3-D Secure and **Save my payment details**: the card is saved (fetched with
  `order_card_tokens` when the card token callback can't reach Odoo), then paid again on Paymob Checkout with its
  CVV and 3-D Secure.

Found and fixed while checking: a browser may refuse to take the checkout frame back to the website (Chrome blocks a
public page from opening a private address), so the pop-up and the side panel also ask Odoo for the payment's state;
`order_card_tokens` answers with card token callbacks (`{"type": "TOKEN", "obj": {...}}`).

### Not yet verified against Paymob

- the callbacks themselves (transaction and card token) reaching a public website, with their HMAC;
- capture and void (an Auth integration), charges with `payments/pay` (a MOTO integration) and saving a card without
  paying (a Verification integration): the test account has none of them;
- the side panel (the same frame as the pop-up), the other countries and the amount format of OMR (3 decimals), the
  `split_amounts` rules, installments, Apple Pay and Google Pay (live only).

## InstaPay Payments (`payment_instapay_cf`)

Guides:

- [Administrator guide](payment_instapay_cf/doc/admin_guide.md): how it works, receiving accounts, review time and
  reviewers, reminders, settings, accounting, statuses, emails, security, limits, troubleshooting.
- [User guide](payment_instapay_cf/doc/user_guide.md): what customers see, and how the team reviews, confirms and
  rejects receipts.

InstaPay, Egypt's instant payment network, has no merchant API. The module turns it into a payment method with a
manual confirmation:

1. At checkout the customer chooses InstaPay; the transaction waits (`pending`).
2. The confirmation page, the portal and an email show the amount, the reference and the receiving accounts
   (`payment.instapay.account`): InstaPay link and QR code, mobile wallets, bank accounts and IBANs, with Copy
   buttons.
3. On a tokenized page (`/payment/instapay_cf/pay/<tx>/<token>`), the customer uploads the screenshot of the
   transfer with its reference. The image is checked and re-encoded (PNG or JPEG only, metadata removed).
4. A receipt (`payment.instapay.receipt`) gets a review activity for the reviewer user or role, due after the review
   time counted in working time on the company's working schedule, public holidays skipped (`plan_hours`).
5. In the review wizard, an accountant confirms (after finding the credit in the statement of the receiving account)
   or rejects with a reason. The decision is recorded with `tx._record()`; the order, the payment (in the journal of
   the receiving account, memo = InstaPay reference) and the invoice follow through Odoo's payment engine.
6. An hourly cron reminds customers who sent no receipt, then cancels their payment after N days.

Warnings flag a screenshot or reference sent for another payment, an amount that differs and a transfer dated
outside the order's time; a reference can be accepted once per company. Customer emails are sent without Odoo's
email layout and name the company.

## Kashier Payments (`payment_kashier_cf`)

Guides, with screenshots:

- [Administrator guide](payment_kashier_cf/doc/admin_guide.md): how it works, the three keys, options,
  notifications, testing in Kashier's test mode, saved cards, capture, refunds, statuses, unknown outcomes,
  accounting, several companies or databases, security, troubleshooting.
- [User guide](payment_kashier_cf/doc/user_guide.md): what customers see, and the daily tasks of the team
  (following, refunding, capturing and voiding payments, saved cards, alerts and activities).

Customers always pay on Kashier's hosted payment page (`payments.kashier.io`), in the same window: there is no
embedded or pop-up mode. Card numbers never reach Odoo. Provider code `kashier_cf`; three credentials: Merchant ID,
Payment API Key (sessions, `Kashier-Hash` signatures, and the signatures Kashier puts on redirects and webhooks) and
Secret Key (status, refunds, captures, voids). Test and live keys work only on Kashier's test and live hosts, chosen
by the provider's **Live** flag.

### Payment methods

| Code | Name | Kashier's page | Odoo features |
|---|---|---|---|
| `card`, brands `visa`, `mastercard`, `meeza` | Card | `allowedMethods: card`, 3-D Secure | Saved cards, manual capture (full only), partial refunds |
| `kashier` | Kashier | Every method of the merchant account, or the provider's **Kashier Methods** (`allowedMethods`, e.g. `wallet, bnpl[valu]`) | Partial refunds |

Currencies: EGP, USD, GBP, EUR (Meeza: EGP). Once paid, the transaction's payment method becomes the card brand
Kashier reports, or `kashier` for the other methods. Manual capture needs the `kashier` method off (core rule).

### Payment flow

- **Session.** `_get_specific_rendering_values` creates a payment session (`POST /v3/payment/sessions`, Secret Key
  and Payment API Key) with `order` (the cleaned reference, a 6-character code of the database taken from
  `database.uuid`, and a nonce), `merchantRedirect` (`/payment/kashier_cf/return/<tx>/<access token>`),
  `serverWebhook` (`/payment/kashier_cf/webhook`), `expireAt`, `maxFailureAttempts`, `display` (`ar` or `en`, from
  the partner's language), and `manualCapture` / `saveCard` when they apply. The generic redirect form sends the
  customer to the session URL, accepted only on `payments.kashier.io`.
- **Saved card, customer present** (`online_token`): a session with `retrieveSavedCard`; the payment form patch
  sends the top window there, where Kashier asks for the CVC and 3-D Secure.
- **Saved card, customer away** (`offline`): `POST /v3/orders` on Kashier's FEP host with `interactionSource:
  RECURRING`, no 3-D Secure, signed with `Kashier-Hash`. Meeza cards are refused before sending
  (`const.MIT_REFUSED_BRANDS`). Cards are saved during a paid checkout only: the provider is left out of
  validation (`_find_available_providers`).
- **Deleting a card** (portal, or **Delete at Kashier** on the token): `DELETE /v3/cards/tokens/{token}`. Other
  archiving keeps the card at Kashier (context key `const.DELETE_AT_KASHIER`).

### How payments stay in sync

- Redirects and webhooks are signed by Kashier, but Kashier's session documents expose the key that signs them, so
  their content is never recorded: they only trigger `_kashier_cf_sync_from_provider`. It reads the session
  (`GET /v3/payment/sessions/{id}/payment`) and the orders (`GET /v3/payment/orders?search=<order>`) with the Secret
  Key, keeps those of this merchant and this order, and queues a snapshot with `tx._record()`. `_apply_updates`
  maps it, after checking the amount and the currency.
- Webhook (`x-kashier-signature`, HMAC-SHA256 of the `signatureKeys` with the Payment API Key): HTTP 403 for a bad
  signature; 503 when Kashier can't be reached or the order belongs to this database but isn't committed yet, so
  that Kashier retries; 200 otherwise, also for orders of other databases.
- The return always checks; webhooks check at most once every 10 seconds per payment. Neither checks while an
  answer waits for processing or is being applied (`FOR UPDATE NOWAIT`).
- The cron **Kashier: check unfinished payments** (15 minutes) takes drafts with a session (2 days), pending (10
  days) and authorized (32 days) payments, cancelled ones within their 48-hour late window
  (`kashier_cf_late_check_until`) and unknown outcomes; 200 per run, with `_commit_progress`.
- **Check Kashier Status** on the transaction (`action_kashier_cf_sync`).

### Refunds, capture, void, errors

- Refunds, captures (full only) and voids: `PUT /v3/orders/{orderId}` on the FEP host, `apiOperation` `REFUND`,
  `CAPTURE` or `VOID`. The refund of a payment captured later targets its capture. Once money has moved, only the
  child transaction is written, so that a serialization failure can't replay the request; the root is reconciled
  by the next check.
- Requests that move money get a 45-second timeout, the others 15 seconds. A read timeout, a lost connection or a
  5xx answer is an unknown outcome (`KashierError.unknown_outcome`): never resent; the transaction waits as pending
  (`kashier_cf_outcome_unknown`), the cron is triggered 2 minutes later, and after `const.UNKNOWN_OUTCOME_HOURS` (2)
  the transaction goes into error with a message to check Kashier's dashboard.
- A charge without the customer that succeeds after Odoo marked it failed is not revived (staff get an activity); a
  cancelled online payment found paid later is confirmed.
- Refunds made in Kashier's dashboard (refund legs no child claims) are noted once on the documents
  (`kashier_cf_noted_legs`); staff alerts (note + To-Do activity) are sent once per payment and kind
  (`kashier_cf_alerted`).
- `const.ERROR_CODES` explains Kashier's response codes (card schemes, 3-D Secure, gateway, `k_*`) and the HTTP-level
  errors found by `utils.classify_error`, each as a customer, merchant or unknown-outcome error: customers get the
  explanation of card and bank errors and a neutral message with the code otherwise; staff see the code, the
  explanation and Kashier's message in the transaction's **Kashier** tab.
- The payment logger redacts Kashier's keys, signatures and card tokens (`const.SENSITIVE_KEYS`), and
  `logging_filters.py` masks the card token, the signature, the masked card and the access token in the HTTP access
  log line of the return route.

### Checked in Kashier's test mode

Tested with mocked API calls (signatures against Kashier's documented examples), then checked on 2026-11-13 with a
Kashier test account, on a local server with demo data:

- a card payment with 3-D Secure (test card 5123 4500 0000 0008, expiry 12/30, CVC 100, then the successful answer
  of the 3-D Secure test page);
- a decline (expiry 04/27, code 54): the customer stays on Kashier's page and can retry up to the attempts setting;
  when the page expires, the payment shows the reason ("The card has expired.");
- an outcome decided later (expiry 05/37, code CC first);
- 3-D Secure left unfinished: cancelled when the page validity ends;
- the Kashier method and the portal in Arabic, with card, wallet, instalments and buy-now-pay-later on Kashier's
  page;
- a saved card paid again (Kashier asks only for the CVC);
- refunds: a fully refunded order stays `CAPTURED` at Kashier, with its refund lines.

### API client

`kashier_api.py` is a typed client of Kashier's API (TypedDicts and `KashierClient`, one method per operation, each
calling `payment.provider._send_api_request`). It is generated from Kashier's OpenAPI document by
[`tools/kashier_openapi/`](tools/kashier_openapi/README.md), a standard-library-only generator pinned by
`spec.lock.json`; `generate.py --check` fails when the committed client is out of date.

## Development

### Repository layout

```
codefish_payment_provider/
├── LICENSE, COPYRIGHT            OPL-1 (paid modules)
├── README.md
├── .github/assets/               logos of the README footer
├── payment_fawry_cf/
│   ├── __manifest__.py, __init__.py (post_init_hook / uninstall_hook)
│   ├── const.py                  endpoints, method and status mappings, error codes
│   ├── exceptions.py             FawryError (an error returned by Fawry, with its code)
│   ├── utils.py                  signatures, amounts, phone numbers, languages, card brands
│   ├── controllers/main.py       return, card page, installment plans, webhook, charge and poll routes,
│   │                             POS Emulator page (test mode, administrators)
│   ├── controllers/portal.py     checks the saved cards with Fawry before the payment forms show them
│   ├── models/                   payment.provider, payment.transaction, payment.token,
│   │                             payment.fawry.split.account (payment split sub-accounts)
│   ├── security/ir.access.csv    access to the split sub-accounts
│   ├── views/                    provider/transaction/token forms, inline forms, payment instructions
│   ├── data/                     provider, payment methods, cron, neutralize.sql
│   ├── static/src/               payment form patch, status patch, instructions interaction, SCSS
│   ├── static/img/               logos of the Fawry-specific payment methods
│   ├── static/description/       Apps store page (index.html), banner, icons, screenshots
│   ├── doc/                      administrator and user guides
│   ├── i18n/                     payment_fawry_cf.pot, ar.po
│   └── tests/
├── payment_paymob_cf/
│   ├── __manifest__.py, __init__.py (post_init_hook / uninstall_hook)
│   ├── const.py                  countries, endpoints, gateway types, HMAC fields, response codes
│   ├── exceptions.py             PaymobError (an error returned by Paymob, with its code)
│   ├── utils.py                  HMAC strings, redirection parsing, declines, error classification, cards
│   ├── controllers/main.py       return, frame return, card form completion, webhook and poll routes
│   ├── controllers/portal.py     leaves out expired saved cards
│   ├── models/                   payment.provider, payment.transaction, payment.token, payment.method,
│   │                             payment.paymob.split.merchant (payment split)
│   ├── security/ir.access.csv    access to the connected merchants
│   ├── views/                    provider (with Test Data tab), method, transaction, token forms, templates
│   ├── data/                     provider, payment methods, cron, neutralize.sql
│   ├── static/src/               payment form patch (checkout frame, Pixel), status patch, instructions
│   ├── static/img/               logos of the methods Odoo has no logo for
│   ├── static/description/       Apps store page, banner, icons, screenshots
│   ├── doc/                      administrator and user guides
│   ├── i18n/                     payment_paymob_cf.pot, ar.po
│   └── tests/
├── payment_instapay_cf/
│   ├── __manifest__.py, __init__.py (post_init_hook / uninstall_hook)
│   ├── const.py                  events, limits, patterns, wallets, rejection reasons
│   ├── utils.py                  digits, mobile numbers, IBAN check, InstaPay links, image sanitizing
│   ├── controllers/main.py       checkout, payment page, receipt upload and "pay another way" routes
│   ├── models/                   payment.provider, payment.transaction, account.move,
│   │                             payment.instapay.account (receiving accounts),
│   │                             payment.instapay.receipt (screenshots to review)
│   ├── wizard/                   payment.instapay.review.wizard (confirm, reject, cancel)
│   ├── security/ir.access.csv    accountants review, read-only accountants read, company rules
│   ├── views/                    provider, account, receipt, transaction views, menu, templates, emails
│   ├── data/                     provider, payment method, activity type, emails, cron, neutralize.sql
│   ├── static/src/               copy buttons, receipt form, status patch, SCSS
│   ├── static/img/               InstaPay logo and icon
│   ├── static/description/       Apps store page, banner, icons, screenshots
│   ├── doc/                      administrator and user guides
│   ├── i18n/                     payment_instapay_cf.pot, ar.po
│   └── tests/
├── payment_kashier_cf/
│   ├── __manifest__.py, __init__.py (post_init_hook / uninstall_hook)
│   ├── const.py                  hosts, methods, session and order statuses, delays, error codes, journal
│   ├── exceptions.py             KashierError (code, Kashier's message, unknown outcome)
│   ├── utils.py                  signatures, amounts, order references, checkout URL check, error classification
│   ├── kashier_api.py            typed client of Kashier's API, generated by tools/kashier_openapi
│   ├── logging_filters.py        masks card tokens, signatures and access tokens in the HTTP access log
│   ├── controllers/main.py       return and webhook routes
│   ├── controllers/portal.py     deletes the card at Kashier when the customer deletes it
│   ├── models/                   payment.provider, payment.transaction, payment.token,
│   │                             account.chart.template (journal of companies set up later)
│   ├── views/                    provider, transaction and token forms, checkout hint
│   ├── data/                     provider, payment methods, cron, neutralize.sql
│   ├── static/src/               payment form patch (saved cards), status patch
│   ├── static/img/               Kashier logo
│   ├── static/description/       Apps store page, banner, icons, screenshots
│   ├── doc/                      administrator and user guides
│   ├── i18n/                     payment_kashier_cf.pot, ar.po
│   └── tests/
└── tools/
    └── kashier_openapi/          generator of payment_kashier_cf/kashier_api.py (see its README)
```

### Conventions

- Every Python file starts with the mediafish header.
- Each module stands alone (no shared base), so that a customer never has to buy both.
- Manifest: `20.0.x.y.z`, author `mediafish`, licence `OPL-1`.
- Odoo 20 payment engine: provider data is queued with `tx._record()` and processed by the payment cron;
  transactions are only written with `payment_safe_write=True`.

### Tests

```bash
cd /path/to/odoo
python odoo-bin -c odoo-server.conf -d odoo20_payment_fawry_cf_test -i payment_fawry_cf \
    --test-tags /payment_fawry_cf --stop-after-init --http-port=8099
python odoo-bin db -c odoo-server.conf drop odoo20_payment_fawry_cf_test

python odoo-bin -c odoo-server.conf -d odoo20_payment_paymob_cf_test -i payment_paymob_cf \
    --test-tags /payment_paymob_cf --stop-after-init --http-port=8099
python odoo-bin db -c odoo-server.conf drop odoo20_payment_paymob_cf_test

python odoo-bin -c odoo-server.conf -d odoo20_payment_instapay_cf_test -i payment_instapay_cf \
    --test-tags /payment_instapay_cf --stop-after-init --http-port=8099
python odoo-bin db -c odoo-server.conf drop odoo20_payment_instapay_cf_test

python odoo-bin -c odoo-server.conf -d odoo20_payment_kashier_cf_test -i payment_kashier_cf \
    --test-tags /payment_kashier_cf --stop-after-init --http-port=8099
python odoo-bin db -c odoo-server.conf drop odoo20_payment_kashier_cf_test

# The generator of the Kashier client, from the repository root (no Odoo needed):
python3 -I -m unittest discover -s tools/kashier_openapi/tests
python3 -I tools/kashier_openapi/generate.py --check
```

The tests mock Fawry's API: they check every signature against an independent implementation, the state
mapping, refunds, saved cards, bank installments, payment split, error codes, the routes (signatures, access
tokens), the waiting page and the POS Emulator page. The Paymob tests check the HMAC strings against Paymob's
documented examples, the intention payloads, every route (HMAC, access tokens), the state mapping, saved cards,
MOTO charges, refunds, captures, voids, payment split, response codes and the journal. The InstaPay tests check the
text and IBAN helpers, the image sanitizing (formats, truncated files, metadata, sizes), the review deadline on a
Sunday-to-Thursday schedule with a public holiday, the receiving accounts, the events, the review wizard, the routes
(access tokens, CSRF, upload limits) and the reminder and cancellation cron. The Kashier tests mock Kashier's API:
they check the signatures against Kashier's documented examples, the error classification, the log masking, the
session payloads (card, Kashier method, Arabic, saved cards, manual capture), the state mapping (paid, declined,
still on the page, unknown and late outcomes, amount mismatch, staff alerted once), refunds, captures and voids
(refused, unknown outcome), saved cards (customer present, without the customer, Meeza, deletion), the journal, the
cron and the routes (access token, signed, unsigned and badly signed notifications, unknown orders, Kashier
unreachable). Run them also with `website_sale`,
`sale_management` and `l10n_eg_cf` installed.

### Translations

`i18n/ar.po` holds the Arabic texts. To refresh it, install the module in a database where `l10n_eg_cf`
(`codefish_localization`) is installed, then run:

```bash
python odoo-bin i18n export -c <config> -d <database> payment_fawry_cf -l pot ar_EG
```

Use `payment_paymob_cf`, `payment_instapay_cf` and `payment_kashier_cf` the same way for the other modules.
InstaPay is written "إنستاباي" in Arabic, Kashier "كاشير".

## Licence

`payment_fawry_cf`, `payment_paymob_cf`, `payment_instapay_cf` and `payment_kashier_cf` are licensed under the Odoo Proprietary License v1.0 (OPL-1): see [`LICENSE`](LICENSE) and
[`COPYRIGHT`](COPYRIGHT). Copyright (c) 2010-Present mediafish (https://www.mediafish.agency).

Fawry, FawryPay, myFawry, Paymob, InstaPay, IPN, Kashier and the names and logos of the payment methods are
trademarks of their owners and are used only to show which payment methods are accepted. The modules are not
affiliated with or endorsed by these companies.

<p align="center">
  <img src=".github/assets/codefish_logo_orange.png" alt="codefish" height="72">
  &nbsp;&nbsp;&nbsp;
  <a href="https://www.mediafish.agency"><img src=".github/assets/mediafish_logo_red.png" alt="mediafish" height="72"></a>
</p>
