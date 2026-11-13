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
    'name': "InstaPay Payments",
    'summary': "Accept InstaPay transfers in Egypt: your customers pay to your InstaPay account, "
               "mobile wallet or bank account, upload the receipt, and your accountant confirms "
               "the payment",
    'description': "Payment provider for InstaPay (Egypt), which has no merchant API. Customers see "
                   "your receiving accounts (InstaPay link and QR, mobile number, mobile wallets, "
                   "bank account and IBAN), send the exact amount, then upload a screenshot of the "
                   "receipt. Your accountants review each receipt within your working days, with "
                   "duplicate and amount checks, and confirm or reject it; the order and the "
                   "invoice follow. Includes reminders and cancellation of unpaid payments, "
                   "customer emails, a journal per receiving account, and Arabic.",
    'version': '20.0.1.0.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'author': "mediafish",
    'website': "https://www.mediafish.agency",
    'license': 'OPL-1',
    'price': 99.0,
    'currency': 'USD',
    'support': 'info@codefish.com.eg',
    # account_payment: InstaPay payments are posted in the journals of the receiving accounts.
    # resource: the working schedule counts the review time.
    'depends': ['payment', 'account_payment', 'mail', 'resource'],
    'data': [
        'security/ir.access.csv',
        'data/mail_activity_type_data.xml',
        # Templates before the data: the provider record and the emails refer to them.
        'views/payment_instapay_templates.xml',
        'views/email_templates.xml',
        'views/portal_templates.xml',
        'wizard/payment_instapay_review_wizard_views.xml',
        'views/payment_instapay_account_views.xml',
        'views/payment_instapay_receipt_views.xml',
        'views/payment_provider_views.xml',
        'views/payment_transaction_views.xml',
        'views/menus.xml',
        'data/payment_provider_data.xml',
        'data/payment_method_data.xml',
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'payment_instapay_cf/static/src/**/*',
        ],
    },
    'images': ['static/description/banner.png'],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
}
