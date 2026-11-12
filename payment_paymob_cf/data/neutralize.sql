-- disable the Paymob payment provider
UPDATE payment_provider
    SET paymob_cf_secret_key = NULL,
        paymob_cf_public_key = NULL,
        paymob_cf_api_key = NULL,
        paymob_cf_hmac_secret = NULL;
