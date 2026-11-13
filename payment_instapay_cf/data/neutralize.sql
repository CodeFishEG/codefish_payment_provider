-- unpublish the InstaPay payment provider: copies of a database never show the real receiving accounts
UPDATE payment_provider
    SET is_published = false
    WHERE code = 'instapay_cf';
