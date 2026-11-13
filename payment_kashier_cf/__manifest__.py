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
    'summary': "Accept Kashier in Egypt: cards (Visa, Mastercard, Meeza), wallets, "
               "installments and valU on Kashier's hosted payment page, with saved cards, refunds "
               "and manual capture",
    'description': "Payment provider for Kashier. Customers pay on Kashier's hosted payment page: cards "
                   "with 3-D Secure, or every method enabled on the Kashier account "
                   "(mobile wallets, bank installments, valU and other buy-now-pay-later brands). "
                   "Payments are confirmed from Kashier's API, never from the browser alone. Includes "
                   "saved cards (also charged again without the customer, for subscriptions and "
                   "invoices), full and partial refunds, authorize and capture, payment notifications, "
                   "a status check every 15 minutes, a typed client of Kashier's API, and Arabic.",
    'version': '20.0.1.0.0',
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
    ],
    'assets': {
        'web.assets_frontend': [
            'payment_kashier_cf/static/src/**/*',
        ],
    },
    'images': [
        'static/description/banner.png',
        'static/description/screenshot_checkout.png',
        'static/description/screenshot_kashier_page.png',
        'static/description/screenshot_kashier_page_arabic.png',
        'static/description/screenshot_portal_arabic.png',
        'static/description/screenshot_saved_card.png',
        'static/description/screenshot_refunds.png',
        'static/description/screenshot_refund_refused.png',
        'static/description/screenshot_transaction.png',
        'static/description/screenshot_configuration.png',
    ],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
}
