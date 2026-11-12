-- disable the Fawry payment provider
UPDATE payment_provider
    SET fawry_merchant_code = NULL,
        fawry_secure_key = NULL;
