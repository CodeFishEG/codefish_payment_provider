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
from odoo.exceptions import ValidationError


class PaymobError(ValidationError):
    """An error returned by Paymob, with its code.

    The message explains the error to the staff; `code` and `description` keep what Paymob sent.
    The code is one of the keys of `const.ERROR_CODES` when the error is known, otherwise the HTTP
    status of the response.
    """

    def __init__(self, message, code=None, description=None):
        super().__init__(message)
        self.code = str(code) if code not in (None, "") else None
        self.description = description or ""
