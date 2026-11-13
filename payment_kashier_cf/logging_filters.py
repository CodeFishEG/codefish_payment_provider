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
"""Mask Kashier's card token, signature and the access tokens in Odoo's HTTP access log.

Kashier returns the customer to `/payment/kashier_cf/return/<tx>/<access token>?...&cardDataToken=...
&signature=...`. Odoo logs every request line, so without this filter the log would keep a reusable card
token next to the access token of the transaction.
"""

import logging
import re

_ROUTE = "/payment/kashier_cf/"
_QUERY_SECRET = re.compile(r"(?<=[?&])(signature|cardDataToken|maskedCard)=[^&\s\"]*")
_PATH_TOKEN = re.compile(r"(/payment/kashier_cf/return/\d+/)[^/?\s\"]+")


def mask(text):
    """Return the text with Kashier's secrets and the route access tokens masked."""
    if not isinstance(text, str) or _ROUTE not in text:
        return text
    return _PATH_TOKEN.sub(r"\1***", _QUERY_SECRET.sub(r"\1=***", text))


class KashierAccessLogFilter(logging.Filter):

    def filter(self, record):
        if isinstance(record.msg, str) and _ROUTE in record.msg:
            record.msg = mask(record.msg)
            for attribute in ("colored_message", "http_request_line"):
                if hasattr(record, attribute):
                    setattr(record, attribute, mask(getattr(record, attribute)))
        return True


def install():
    logger = logging.getLogger("odoo.http.server")
    if not any(isinstance(existing, KashierAccessLogFilter) for existing in logger.filters):
        logger.addFilter(KashierAccessLogFilter())


install()
