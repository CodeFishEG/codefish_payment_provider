# Fawry Payments: administrator guide

How to set up and run the **Fawry Payments** module (`payment_fawry_cf`) on Odoo 20. For the daily tasks of
your team and what customers see, read the [user guide](user_guide.md).

## Contents

- [Before you start](#before-you-start)
- [1. Install the module](#1-install-the-module)
- [2. Enter your credentials](#2-enter-your-credentials)
- [3. Choose the integration and the display](#3-choose-the-integration-and-the-display)
- [4. Give the notification URL to Fawry](#4-give-the-notification-url-to-fawry)
- [5. Turn on your payment methods](#5-turn-on-your-payment-methods)
- [6. Check the payment journal](#6-check-the-payment-journal)
- [7. Test](#7-test)
- [8. Go live](#8-go-live)
- [Settings reference](#settings-reference)
- [Accounting](#accounting)
- [Payment statuses](#payment-statuses)
- [Security](#security)
- [Troubleshooting](#troubleshooting)

## Before you start

- A Fawry merchant account. Fawry first gives a **test (staging)** merchant code and secure key, then the
  **live** ones. Ask Fawry which APIs your account has: FawryPay Express Checkout, the server-to-server APIs, or
  both.
- Your Odoo website reachable from the internet over **HTTPS**, so that Fawry can bring customers back and send
  its notifications.
- Prices in **Egyptian pounds (EGP)** on the website pricelist: Fawry accepts EGP only.
- The **Invoicing** app (installed with eCommerce) with a chart of accounts, for the Fawry Pay journal.
- The **Administration / Settings** access right.

## 1. Install the module

In **Apps**, search for **Fawry Payments** and click **Activate**. The installation:

- adds the **Fawry** payment provider, in test mode and unpublished;
- adds the payment methods and turns on Card, Pay at Fawry and Mobile Wallet;
- creates, in each company, the **Fawry Pay** bank journal (in Arabic "مدفوعات فورى") in EGP and sets it as the
  provider's payment journal;
- adds the scheduled action **Fawry: check pending payments**, which runs every 15 minutes.

## 2. Enter your credentials

1. Open **Invoicing › Configuration › Payment Providers** (or **Website › Configuration › Payment Providers**)
   and click **Fawry**.
2. In the **Configuration** tab, enter the **Merchant Code** and the **Secure Key** of your test account. Leave
   **Live** unticked.
3. Click **Test Connection**. Odoo asks Fawry to check the credentials and shows "Connection successful", or
   Fawry's reason for refusing them.

![The Configuration tab with the Server-to-Server integration](../static/description/screenshot_configuration.png)

## 3. Choose the integration and the display

| Setting | Choices |
|---|---|
| **Fawry Integration** | *FawryPay Express Checkout*: every method is paid on FawryPay's hosted checkout. *Server-to-Server APIs*: Odoo creates reference codes, wallet requests, QR codes and myFawry payments itself and shows them on your website; cards are entered on Fawry's secure card page and can be saved. |
| **Checkout Display** | *Full page*, *Pop-up window* or *Side panel*, wherever FawryPay's checkout is used. iPhone, iPad and Mac always get the full page, as Fawry requires. |
| **Payment Expiry (Hours)** | How long a reference code, wallet request or QR code can be paid. 48 by default. |
| **Allow Saving Payment Methods** | Server-to-Server only: customers can save their cards. |

| | FawryPay Express Checkout | Server-to-Server APIs |
|---|---|---|
| Card | On FawryPay's checkout | On Fawry's secure card page, then 3-D Secure |
| Pay at Fawry | The code is shown on FawryPay's checkout | The code is shown on your website |
| Mobile Wallet | On FawryPay's checkout | Request to the wallet, or QR code, on your website |
| myFawry | On FawryPay's checkout | QR code and app link on your website |
| Fawry Yellow Card, valU, Forsa, Souhoola, FawryPay | On FawryPay's checkout | On FawryPay's checkout |
| Saved cards | No | Yes |

You can switch the integration at any time; payments already started keep working.

![The Configuration tab with FawryPay Express Checkout](../static/description/screenshot_configuration_express.png)

## 4. Give the notification URL to Fawry

Copy the **Notification URL** shown on the provider (it ends with `/payment/fawry/webhook`) and send it to Fawry
for your test and live accounts. Fawry calls it when a payment changes, for example when a reference code is
paid at an outlet. Odoo also sends it with every payment.

## 5. Turn on your payment methods

In the **Payment Methods** tab, turn on the methods Fawry enabled on your account and drag them in the order you
want. The card brands (Visa, Mastercard, Meeza) belong to the Card method. Methods that are not enabled at Fawry
would be refused at payment time. Methods other than cards are offered to customers whose address is in Egypt.

![The payment methods of the provider](../static/description/screenshot_payment_methods.png)

## 6. Check the payment journal

In the **Configuration** tab, **Payment Journal** shows **Fawry Pay**. Keep it, so that the money collected by
Fawry is followed apart from your other banks, or choose another bank journal. See [Accounting](#accounting).

## 7. Test

While the provider is unpublished, its methods show on your website only to your own team, signed in with their
Odoo user: place a few test orders that way. To let a customer test too, click the **Unpublished** button at the
top of the provider. In test mode, Odoo shows a warning sign next to each method and Fawry takes no real money.

| To test | Use |
|---|---|
| Visa card | 4508 7500 1574 1019, expiry 01/39, CVV 100 |
| Mastercard | 5123 4500 0000 0008, expiry 01/39, CVV 100 |
| 3-D Secure | On Fawry's test bank page, keep "Authentication Successful" and click **Submit** |
| Pay at Fawry | Pay the reference code on Fawry's test outlet page (Fawry's developer portal, "Pay order") |

These are Fawry's published test data and may change; Fawry's developer portal has the current list. Fawry's
card page refuses `localhost` return addresses: test on a public address, or on `http://127.0.0.1:<port>` with
`web.base.url` set to it.

## 8. Go live

1. Tick **Live** (this also publishes the provider) and replace the merchant code and the secure key with your
   live ones, then save.
2. Click **Test Connection** again.
3. Make sure Fawry has the notification URL of your live website.
4. Place one small real order and refund it from Odoo.

## Settings reference

| Setting | What it does |
|---|---|
| **Live** | Unticked: Fawry's test (staging) environment, no real money. Ticked: production. |
| **Merchant Code** | The account number Fawry gave you. Test and live accounts have different codes. |
| **Secure Key** | Signs every request sent to Fawry and checks Fawry's answers. Visible and editable by administrators only. |
| **Fawry Integration** | FawryPay Express Checkout or Server-to-Server APIs. |
| **Checkout Display** | Full page, pop-up window or side panel, for FawryPay's checkout. |
| **Payment Expiry (Hours)** | How long reference codes, wallet requests and QR codes stay payable. Default 48. |
| **Notification URL** | Read-only. The address Fawry calls when a payment changes; give it to Fawry. |
| **Allow Saving Payment Methods** | Server-to-Server only: customers add, choose and remove their saved cards on the website (see the [user guide](user_guide.md#saved-cards-add-choose-remove)). |
| **Payment Journal** | Where paid orders are posted. Fawry Pay by default. |
| **Currencies** | Egyptian pound (EGP) only. |
| **Restrictions** tab | Odoo's usual limits: maximum amount, countries, websites. |
| **Messages** tab | The texts shown to customers, for example the message of a pending payment. |

**Several companies.** Each company has its own Fawry provider, with its own credentials, and its own Fawry Pay
journal. A company created later gets its journal when its chart of accounts is installed.

**Languages.** The module is translated into Arabic, for every Arabic language installed in Odoo. Fawry's pages
open in Arabic or English, following the customer's language.

## Accounting

| Journal field | Value |
|---|---|
| Name | Fawry Pay (in Arabic "مدفوعات فورى") |
| Type | Bank |
| Short code | FAWRY (payments are numbered PFAWRY/<year>/00001, …) |
| Currency | EGP |
| Incoming payment method | Fawry, linked to the Fawry provider |
| Bank account | Its own account in your chart of accounts |

- When Fawry confirms a payment, Odoo posts a customer payment in Fawry Pay and reconciles it with the invoice,
  as for any online payment.
- The balance of Fawry Pay is the money Fawry collected for you and has not transferred yet. When Fawry settles
  it to your bank account, record an internal transfer from Fawry Pay to that bank, and Fawry's commission as a
  bank fee.
- If a journal with the code FAWRY already exists, it is used instead of creating another one. Reinstalling the
  module never creates a second journal.
- Uninstalling the module keeps the journal and its entries; the provider is unpublished and its credentials
  removed.

![The Fawry Pay journal](../static/description/screenshot_journal.png)

## Payment statuses

| At Fawry | Transaction in Odoo | What happens |
|---|---|---|
| New, Unpaid | Pending | The customer still has to pay: the code, QR code or request is shown with the deadline. The order waits. |
| Paid | Confirmed | The order is confirmed and the payment posted in Fawry Pay. |
| Expired | Canceled | "The payment expired before it was made." |
| Canceled | Canceled | "The payment was canceled at Fawry." |
| Failed | Error | "The payment was declined", with Fawry's reason. |
| Authorized | Pending | Waits until Fawry collects the payment. |
| Refunded, Partially refunded | Confirmed | The payment stays confirmed; each refund is its own transaction. |

Odoo learns the status, from fastest to slowest, from:

1. the answer Fawry signs when the customer comes back to your website;
2. the waiting page, which asks every few seconds while the customer looks at it;
3. Fawry's notification to the notification URL, checked against Fawry's signature;
4. the scheduled action, every 15 minutes, for pending payments of the last 10 days;
5. the **Check Fawry Status** button on the transaction.

Notifications are never trusted alone: Odoo asks Fawry for the status before recording it.

## Security

- **No card numbers in Odoo.** Cards are typed on Fawry's pages only. With the Server-to-Server integration, Odoo
  uses Fawry's card tokenization page, which Fawry requires from merchants without PCI-DSS certification, and
  keeps only Fawry's token, the last four digits and the expiry date.
- **3-D Secure** on every card payment, saved cards included. Saved cards can't be charged without the customer,
  so they can't be used for automatic charges such as subscriptions.
- **Signed requests.** Every request to Fawry is signed with your secure key, and Fawry's answers, returns and
  notifications are checked against Fawry's signature.
- **Protected pages.** Payment pages and status checks are tied to the payment by a secret token.
- **Restricted credentials.** Only administrators see the secure key. It never appears in the logs.
- **Safe copies.** A neutralized copy of the database (for testing) has no Fawry credentials, so it can never
  take real payments.

## Troubleshooting

| Problem | What to check |
|---|---|
| The Fawry methods don't show at checkout | The provider is published and the methods are on; the website pricelist is in EGP; for methods other than cards, the customer's address is in Egypt; the provider belongs to the website's company and its Restrictions allow the order. |
| "Fawry rejected the credentials" | The merchant code and secure key, without spaces. Test credentials work only with **Live** unticked, live ones only with **Live** ticked. |
| Paid at Fawry, but the order still waits | Click **Check Fawry Status**. If it happens often: Fawry has your notification URL, the website is reachable over HTTPS, and the scheduled action **Fawry: check pending payments** is active (Settings › Technical › Scheduled Actions, developer mode). |
| Customers can't save cards | Server-to-Server integration, **Allow Saving Payment Methods** ticked, customer signed in. |
| A customer's saved card is no longer listed | Fawry no longer has it, or it expired: Odoo checks the cards with Fawry when it shows them (at most every 10 minutes) and stops offering those. The customer adds the card again. |
| The pop-up opens as a full page | Expected on iPhone, iPad and Mac. |
| A refund is refused | Odoo shows Fawry's reason and records nothing. Check the amount left to refund, and ask Fawry whether the method used can be refunded on your account. |
| Another currency | Not possible: Fawry processes EGP only. |

Support: [info@codefish.com.eg](mailto:info@codefish.com.eg). Send your Odoo version, the integration you use
and, for a payment issue, the transaction reference. Never send your secure key by email.
