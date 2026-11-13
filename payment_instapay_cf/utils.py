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
import hashlib
import io
import re
import unicodedata
import warnings
from urllib.parse import urlsplit

from PIL import Image, ImageSequence

from odoo.tools.image import IMAGE_MAX_RESOLUTION, image_fix_orientation

from odoo.addons.payment_instapay_cf import const

# Arabic-Indic (٠-٩) and Persian (۰-۹) digits, as typed on Arabic keyboards, to ASCII.
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


class ReceiptError(ValueError):
    """An uploaded receipt that can't be accepted; `code` says why (type, size, unreadable)."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def to_ascii_digits(value):
    """Return the text with Arabic-Indic and Persian digits replaced by ASCII digits.

    :param str value: The text, e.g. "٠١٠٠١٢٣٤٥٦٧".
    :rtype: str
    """
    return (value or "").translate(_DIGITS)


def normalize_mobile(value):
    """Return an Egyptian mobile number in the local format, or an empty string.

    :param str value: The number in any common format ("+20 100 123 4567", "0020...", "٠١٠...").
    :return: The number as "01xxxxxxxxx", or "" if it isn't an Egyptian mobile number.
    :rtype: str
    """
    digits = re.sub(r"[^\d+]", "", to_ascii_digits(value))
    for prefix in ("+20", "0020"):
        if digits.startswith(prefix):
            digits = "0" + digits[len(prefix):]
            break
    else:
        if digits.startswith("20") and len(digits) == 12:
            digits = "0" + digits[2:]
    return digits if re.match(const.EG_MOBILE_PATTERN, digits) else ""


def format_mobile(mobile):
    """Return a normalized mobile number grouped for reading: "010 0123 4567"."""
    return f"{mobile[:3]} {mobile[3:7]} {mobile[7:]}" if len(mobile) == 11 else mobile


def normalize_iban(value):
    """Return the IBAN in upper case, without spaces or separators."""
    return re.sub(r"[^A-Za-z0-9]", "", to_ascii_digits(value)).upper()


def is_valid_eg_iban(iban):
    """Return whether the normalized IBAN is an Egyptian IBAN with a valid check (ISO 13616).

    :param str iban: The IBAN, normalized with `normalize_iban`.
    :rtype: bool
    """
    if len(iban) != const.IBAN_LENGTH or not re.match(r"^EG\d{27}$", iban):
        return False
    rearranged = iban[4:] + iban[:4]
    number = "".join(str(int(char, 36)) for char in rearranged)
    return int(number) % 97 == 1


def format_iban(iban):
    """Return the IBAN in groups of four characters, as printed on bank documents."""
    return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))


def normalize_ipa(value):
    """Return an InstaPay address in lower case, or an empty string if it isn't one.

    :param str value: The address, e.g. "Shop@InstaPay".
    :rtype: str
    """
    ipa = (value or "").strip().lower()
    return ipa if re.match(const.IPA_PATTERN, ipa) else ""


def is_instapay_link(url):
    """Return whether the URL is an InstaPay payment link (https://ipn.eg/S/...).

    Look-alike hosts, other schemes, user info and ports are refused: fake payment links are a
    known fraud.

    :param str url: The URL.
    :rtype: bool
    """
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and (parts.hostname or "") in const.LINK_HOSTS
        and parts.port is None
        and not parts.username
        and not parts.password
        and parts.path.startswith(const.LINK_PATH_PREFIX)
        and len(parts.path) > len(const.LINK_PATH_PREFIX)
    )


def normalize_reference(value):
    """Return an InstaPay transfer reference in upper case, without spaces, or an empty string.

    :param str value: The reference as typed, e.g. "2246 6394 3247" or Arabic-Indic digits.
    :rtype: str
    """
    reference = re.sub(r"[\s\-]", "", to_ascii_digits(value)).upper()
    return reference if re.match(const.REFERENCE_PATTERN, reference) else ""


def clean_text(value, max_length):
    """Return the text without control characters, stripped and cut at `max_length`."""
    text = "".join(
        char for char in (value or "") if unicodedata.category(char)[0] != "C" or char == " "
    )
    return text.strip()[:max_length]


def parse_amount(value):
    """Return the amount typed by a customer as a float, or None.

    Accepts Arabic-Indic digits and the Arabic decimal (٫) and thousands (٬) separators.

    :param str value: The amount, e.g. "1,500.50" or "١٬٥٠٠٫٥".
    :rtype: float | None
    """
    text = to_ascii_digits(value).replace("٫", ".").replace("٬", "").replace(",", "").strip()
    if not re.match(r"^\d+(\.\d{1,2})?$", text):
        return None
    return float(text)


def receipt_accept():
    """Return the `accept` attribute of the screenshot input, e.g. "image/png,image/jpeg"."""
    return ",".join(const.RECEIPT_FORMATS.values())


def is_complete_image(raw, image_format):
    """Return whether the file holds the whole image, whatever follows it.

    Odoo lets Pillow load truncated images (`ImageFile.LOAD_TRUNCATED_IMAGES`, set by the
    reports), which fills the missing part in grey: a cut screenshot would reach the accountant
    unreadable instead of being refused.

    :param bytes raw: The file.
    :param str image_format: The format Pillow detected: PNG or JPEG.
    :rtype: bool
    """
    if image_format == "PNG":
        return b"IEND" in raw
    if image_format == "JPEG":
        # Markers can't appear inside the compressed data (0xFF is escaped there), so the image
        # ends with an end-of-image marker after its last scan.
        return raw.rfind(b"\xff\xd9") > raw.rfind(b"\xff\xda") > 0
    return False


def sanitize_image(raw, max_side, keep_png=True):
    """Decode an uploaded image and encode it again, to store only clean pixels.

    The image is decoded with a guard against decompression bombs, turned upright from its
    EXIF orientation and shrunk to `max_side`. Encoding it again drops the metadata (EXIF,
    location), the colour profile and anything hidden after the image data.

    :param bytes raw: The uploaded bytes.
    :param int max_side: The longest side of the stored image, in pixels.
    :param bool keep_png: Store PNG sources as PNG (screenshots stay sharp); JPEG otherwise.
    :return: The clean bytes and their file extension ("png" or "jpg").
    :rtype: tuple[bytes, str]
    :raise ReceiptError: If the file is empty, too large or not a PNG or JPEG image.
    """
    if not raw:
        raise ReceiptError("unreadable")
    if len(raw) > const.RECEIPT_MAX_FILE_SIZE:
        raise ReceiptError("size")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            image = Image.open(io.BytesIO(raw))
            if image.format not in const.RECEIPT_FORMATS:
                raise ReceiptError("type")
            if getattr(image, "is_animated", False) and image.n_frames > 1:
                raise ReceiptError("type")
            if not is_complete_image(raw, image.format):
                raise ReceiptError("unreadable")
            width, height = image.size  # Read from the header, before decoding the pixels.
            if (
                width * height > min(IMAGE_MAX_RESOLUTION, const.RECEIPT_MAX_PIXELS)
                or max(width, height) > const.RECEIPT_MAX_SIDE
            ):
                raise ReceiptError("size")
            if image.format == "JPEG":
                image.draft("RGB", (const.RECEIPT_STORED_MAX_SIDE, const.RECEIPT_STORED_MAX_SIDE))
            image.load()
        except ReceiptError:
            raise
        except (OSError, SyntaxError, ValueError, Image.DecompressionBombError,
                Image.DecompressionBombWarning, EOFError) as error:
            raise ReceiptError("unreadable") from error

    source_format = image.format
    image = next(ImageSequence.Iterator(image)).copy()
    image = image_fix_orientation(image)
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    if source_format == "PNG" and keep_png:
        if image.mode not in ("RGB", "RGBA", "L", "LA", "P"):
            image = image.convert("RGBA")
        image.save(output, format="PNG", optimize=True)
        return output.getvalue(), "png"
    if image.mode != "RGB":
        background = Image.new("RGB", image.size, (255, 255, 255))
        rgba = image.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    image.save(output, format="JPEG", quality=90, optimize=True)
    return output.getvalue(), "jpg"


def sanitize_receipt(raw):
    """Check and clean the screenshot of a transfer.

    :param bytes raw: The uploaded bytes.
    :return: The clean bytes, their file extension and the SHA-256 of the uploaded bytes.
    :rtype: tuple[bytes, str, str]
    :raise ReceiptError: If the file can't be accepted.
    """
    clean, extension = sanitize_image(raw, const.RECEIPT_STORED_MAX_SIDE)
    return clean, extension, hashlib.sha256(raw).hexdigest()
