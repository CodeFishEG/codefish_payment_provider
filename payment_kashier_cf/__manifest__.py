#################################################################################
# Author      : mediafish(<https://www.mediafish.agency>)
# Copyright(c): 2010-Present mediafish
# All Rights Reserved.
#
#
#
# This program is copyright property of the author mentioned above.
# You can`t redistribute it and/or modify it.
#
#
# You should have received a copy of the License along with this program.
# If not, see <https://www.mediafish.agency/license.html/>
#################################################################################
{
    'name': "Kashier Payments",
    'summary': "Every Kashier payment method in Egypt (cards, Apple Pay, mobile wallets, InstaPay, Basata, "
               "bank installments, valU and other buy-now-pay-later), each on Kashier's page, inside the "
               "checkout or run by Odoo's server, with saved cards, refunds and manual capture",
    'description': """
Kashier payments for Odoo 20 (Egypt)
====================================

Payment methods
---------------
- Every Kashier method is its own payment method: cards (Visa, Mastercard, Meeza) with 3-D Secure, Apple Pay,
  mobile wallets, InstaPay, Basata, bank installments, valU, Souhoola, Contact, Aman, Forsa, Octo, MoGo and TRU.
- The methods your Kashier account doesn't accept are hidden at checkout ("Sync Kashier Methods" button and a
  daily check); a notice lists the methods another payment provider shows instead.
- Cards in EGP, USD, GBP and EUR; the other methods in Egyptian pounds.

How each method runs (chosen per method)
----------------------------------------
- Kashier page: the customer pays on Kashier's secure page and comes back.
- Kashier page inside the checkout: the same page shown in the payment step, 3-D Secure included.
- Server side, for wallets, Basata and InstaPay: Odoo's own page sends the wallet request, shows the Basata code
  (also emailed to the customer) or the InstaPay QR code, and waits for the result. Cards always stay on Kashier's
  page: card details never reach Odoo.
- Apple Pay button on the payment step (beta), with the domain file served by Odoo.

After the payment
-----------------
- Full and partial refunds from Odoo for cards, Apple Pay, wallets and bank installments.
- Authorize, then capture or void card payments.
- Saved cards: paid again with the security code, or charged without the customer for invoices and
  subscriptions; deleting a card in the customer portal deletes it at Kashier.
- Bank installments wait until Kashier completes them.

Reliability and security
------------------------
- Every payment is confirmed from Kashier's API with the Secret Key; Kashier's signed redirects and notifications
  only trigger that check; the amount and the currency are verified.
- Status from Kashier's notifications, the customer's return and a check every 15 minutes, plus a "Check Kashier
  Status" button for the staff.
- A request that moves money is never sent twice: an unanswered refund, capture, void or charge waits for
  Kashier's answer. Late payments are still recorded, and the staff are alerted once on the order or the invoice.
- Test Connection button, a Kashier bank journal per company, several companies or databases on one Kashier
  account, keys and card tokens masked in the logs.
- Customer pages and emails name your company, never Odoo. English and Arabic.
- Includes a typed client of Kashier's API, generated from Kashier's API document.
""",
    'version': '20.0.1.1.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'author': "mediafish",
    'website': "https://www.mediafish.agency",
    'license': 'OPL-1',
    'price': 99.0,
    'currency': 'USD',
    'support': 'info@codefish.com.eg',
    # account_payment: the provider gets its own "Kashier" bank journal (website_sale needs it too).
    'depends': ['payment', 'account_payment'],
    'data': [
        # Templates before the data: the provider record refers to them.
        'views/payment_kashier_templates.xml',
        'views/payment_provider_views.xml',
        'views/payment_transaction_views.xml',
        'views/payment_token_views.xml',
        'data/payment_provider_data.xml',
        'data/payment_method_data.xml',
        'data/ir_cron_data.xml',
        'data/mail_template_data.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'payment_kashier_cf/static/src/**/*',
        ],
    },
    'images': [
        'static/description/banner.png',
        'static/description/screenshot_methods.png',
        'static/description/screenshot_embedded.png',
        'static/description/screenshot_basata_code.png',
        'static/description/screenshot_kashier_integration.png',
        'static/description/screenshot_kashier_page.png',
        'static/description/screenshot_kashier_page_arabic.png',
        'static/description/screenshot_portal_arabic.png',
        'static/description/screenshot_saved_card.png',
        'static/description/screenshot_refunds.png',
        'static/description/screenshot_refund_refused.png',
        'static/description/screenshot_transaction.png',
        'static/description/screenshot_kashier_settings.png',
    ],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
}
