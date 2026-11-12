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
    'name': "Fawry Payments",
    'summary': "Accept Fawry in Egypt: cards with 3-D Secure, Fawry reference codes, mobile wallets, "
               "myFawry, valU and more, through FawryPay Express Checkout or the server-to-server APIs",
    'description': "Payment provider for Fawry (FawryPay). Choose FawryPay Express Checkout, where customers pay "
                   "on Fawry's hosted checkout in a full page, a pop-up or a side panel, or the Server-to-Server "
                   "APIs, where cards are saved on Fawry's secure card page and charged with 3-D Secure, and "
                   "Fawry reference codes, wallet QR codes and myFawry payments are shown on your website. "
                   "Includes saved cards, refunds, payment notifications and Arabic.",
    'version': '20.0.1.0.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'author': "mediafish",
    'website': "https://www.mediafish.agency",
    'license': 'OPL-1',
    'price': 99.0,
    'currency': 'USD',
    'support': 'info@codefish.com.eg',
    'depends': ['payment'],
    'data': [
        # Templates first: the provider record refers to them.
        'views/payment_fawry_templates.xml',
        'views/payment_provider_views.xml',
        'views/payment_transaction_views.xml',
        'views/payment_token_views.xml',
        'data/payment_provider_data.xml',
        'data/payment_method_data.xml',
        'data/ir_cron_data.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'payment_fawry_cf/static/src/**/*',
        ],
    },
    'images': ['static/description/banner.png'],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
}
