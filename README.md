# codefish_payment_provider

Payment providers for Odoo 20.0, built by codefish, the software development division of mediafish. The
repository currently holds one module, **Fawry Payments**, which connects Odoo to Fawry (FawryPay), the Egyptian
payment network: cards with 3-D Secure, Fawry reference codes paid in cash, mobile wallets, myFawry and Fawry's
installment partners.

## Contents

- [Modules](#modules)
- [Requirements](#requirements)
- [Installation](#installation)
- [Fawry Payments](#fawry-payments-payment_fawry_cf)
- [Development](#development)
- [Licence](#licence)

## Modules

| Technical name | Name | What it does | Licence | Depends on |
|---|---|---|---|---|
| [`payment_fawry_cf`](payment_fawry_cf) | Fawry Payments | Fawry payment provider: FawryPay Express Checkout or the server-to-server APIs, saved cards, refunds, reference codes and wallet QR codes shown on the website | OPL-1 (paid) | `payment`, `account_payment` |

## Requirements

- Odoo 20.0, Community or Enterprise. Module versions follow `20.0.x.y.z`.
- Python 3.12 to 3.14 and PostgreSQL 16 or later, as set in Odoo's own `odoo/release.py`.
- A Fawry merchant account (merchant code and secure key). Fawry gives a test (staging) account first.
- The Odoo server must be reachable from the internet over HTTPS in production, so that Fawry can send its
  payment notifications and redirect customers back.

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
4. In **Apps**, remove the **Apps** filter, search for **Fawry Payments** (`payment_fawry_cf`) and click
   **Activate**.

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

### Usage

- **Website:** the methods appear at the payment step of the shop, on invoices in the customer portal and on
  payment links.
- **Customers:** cards are added, chosen and removed from **My Account › Payment Methods** and at checkout
  (server-to-server integration, see [Saved cards](#saved-cards)).
- **Back office:** **Invoicing › Configuration › Payment Providers › Fawry**; transactions are in **Invoicing ›
  Configuration › Payment Transactions** (developer mode).

### Testing on Fawry's staging

Use Fawry's staging test cards (CVV 100, expiry 01/39): Visa 4508 7500 1574 1019, Mastercard
5123 4500 0000 0008. Pay staging reference codes at Fawry's POS emulator
(https://developer.fawrystaging.com/public/pay-order/). Fawry's card page refuses `localhost` return URLs: run
the server on `http://127.0.0.1:<port>` and set `web.base.url` to it.

## Development

### Repository layout

```
codefish_payment_provider/
├── LICENSE, COPYRIGHT            OPL-1 (paid module)
├── README.md
├── .github/assets/               logos of the README footer
└── payment_fawry_cf/
    ├── __manifest__.py, __init__.py (post_init_hook / uninstall_hook)
    ├── const.py                  endpoints, method and status mappings
    ├── utils.py                  signatures, amounts, phone numbers, languages, card brands
    ├── controllers/main.py       return, card page, webhook, charge and poll routes
    ├── controllers/portal.py     checks the saved cards with Fawry before the payment forms show them
    ├── models/                   payment.provider, payment.transaction, payment.token
    ├── views/                    provider/transaction/token forms, inline forms, payment instructions
    ├── data/                     provider, payment methods, cron, neutralize.sql
    ├── static/src/               payment form patch, status patch, instructions interaction, SCSS
    ├── static/img/               logos of the Fawry-specific payment methods
    ├── static/description/       Apps store page (index.html), banner, icons, screenshots
    ├── doc/                      administrator and user guides
    ├── i18n/                     payment_fawry_cf.pot, ar.po
    └── tests/
```

### Conventions

- Every Python file starts with the mediafish header.
- Manifest: `20.0.x.y.z`, author `mediafish`, licence `OPL-1`.
- Odoo 20 payment engine: provider data is queued with `tx._record()` and processed by the payment cron;
  transactions are only written with `payment_safe_write=True`.

### Tests

```bash
cd /path/to/odoo
python odoo-bin -c odoo-server.conf -d odoo20_payment_fawry_cf_test -i payment_fawry_cf \
    --test-tags /payment_fawry_cf --stop-after-init --http-port=8099
python odoo-bin db -c odoo-server.conf drop odoo20_payment_fawry_cf_test
```

The tests mock Fawry's API: they check every signature against an independent implementation, the state
mapping, refunds, saved cards, the routes (signatures, access tokens) and the waiting page.

### Translations

`i18n/ar.po` holds the Arabic texts. To refresh it, install the module in a database where `l10n_eg_cf`
(`codefish_localization`) is installed, then run:

```bash
python odoo-bin i18n export -c <config> -d <database> payment_fawry_cf -l pot ar_EG
```

## Licence

`payment_fawry_cf` is licensed under the Odoo Proprietary License v1.0 (OPL-1): see [`LICENSE`](LICENSE) and
[`COPYRIGHT`](COPYRIGHT). Copyright (c) 2010-Present mediafish (https://www.mediafish.agency).

Fawry, FawryPay, myFawry and the names and logos of the payment methods are trademarks of their owners and are
used only to show which payment methods are accepted.

<p align="center">
  <img src=".github/assets/codefish_logo_orange.png" alt="codefish" height="72">
  &nbsp;&nbsp;&nbsp;
  <a href="https://www.mediafish.agency"><img src=".github/assets/mediafish_logo_red.png" alt="mediafish" height="72"></a>
</p>
