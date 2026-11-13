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
    'description': "Payment provider for Kashier. Every Kashier method is its own payment method: cards (Visa, "
                   "Mastercard, Meeza, 3-D Secure), Apple Pay, mobile wallets, InstaPay, Basata kiosk codes, bank "
                   "installments, valU, Souhoola, Contact, Aman, Forsa, Octo, MoGo and TRU; the methods the Kashier "
                   "account doesn't accept are hidden. Each method runs on Kashier's page, on Kashier's page shown "
                   "inside the checkout, or server side (wallet requests, Basata codes and InstaPay QR codes shown "
                   "by Odoo; cards always stay on Kashier's page). Apple Pay can also be a button on the payment "
                   "step. Payments are confirmed from Kashier's API, never from the browser alone. Includes saved "
                   "cards (also charged again without the customer, for subscriptions and invoices), refunds, "
                   "authorize and capture, payment notifications, a status check every 15 minutes, a typed client "
                   "of Kashier's API, and Arabic.",
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
