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
    'name': "Paymob Payments",
    'summary': "Accept Paymob in Egypt, Saudi Arabia, the UAE, Oman and Pakistan: cards, wallets, "
               "kiosk, valU and other installments, Apple Pay, with Paymob's hosted checkout or an "
               "embedded card form, saved cards, refunds and manual capture",
    'description': "Payment provider for Paymob. Choose Paymob Checkout, where customers pay on Paymob's "
                   "hosted page in a full page, a pop-up or a side panel, or the Embedded checkout, "
                   "where the card form opens on your website and saved cards, manual capture and "
                   "merchant-initiated charges use Paymob's server APIs. Includes every Paymob country, "
                   "saved cards, full and partial refunds, authorize and capture, payment split with "
                   "connected merchants, bank installments, Apple Pay with a guided set-up, Paymob's "
                   "response codes explained, test data for administrators, payment notifications and "
                   "status checks, and Arabic.",
    'version': '20.0.1.1.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'author': "mediafish",
    'website': "https://www.mediafish.agency",
    'license': 'OPL-1',
    'price': 99.0,
    'currency': 'USD',
    'support': 'info@codefish.com.eg',
    # account_payment: the provider gets its own "Paymob" bank journal (website_sale needs it too).
    'depends': ['payment', 'account_payment'],
    'data': [
        'security/ir.access.csv',
        # Templates before the data: the provider record refers to them.
        'views/payment_paymob_templates.xml',
        'views/payment_provider_views.xml',
        'views/payment_transaction_views.xml',
        'views/payment_token_views.xml',
        'data/payment_provider_data.xml',
        'data/payment_method_data.xml',
        'data/ir_cron_data.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'payment_paymob_cf/static/src/**/*',
        ],
    },
    'images': ['static/description/banner.png'],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
}
