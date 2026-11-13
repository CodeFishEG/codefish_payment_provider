-- disable the Kashier payment provider
UPDATE payment_provider
    SET kashier_cf_merchant_id = NULL,
        kashier_cf_payment_api_key = NULL,
        kashier_cf_secret_key = NULL;
