
CREATE TABLE IF NOT EXISTS customers (
    customer_id INTEGER PRIMARY KEY,
    customer_name VARCHAR(100) NOT NULL,
    city VARCHAR(100) NOT NULL,
    region VARCHAR(50) NOT NULL,
    signup_date DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS stores (
    store_id INTEGER PRIMARY KEY,
    store_name VARCHAR(100) NOT NULL,
    city VARCHAR(100) NOT NULL,
    region VARCHAR(50) NOT NULL,
    opened_date DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    category_id INTEGER PRIMARY KEY,
    category_name VARCHAR(100) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS promotions (
    promotion_id INTEGER PRIMARY KEY,
    promotion_name VARCHAR(100) NOT NULL,
    discount_type VARCHAR(20) NOT NULL,
    discount_value NUMERIC(10, 2) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,

    CHECK (discount_type IN ('percentage', 'fixed')),
    CHECK (
        (discount_type = 'percentage' AND discount_value BETWEEN 0 AND 100)
        OR
        (discount_type = 'fixed' AND discount_value >= 0)
    ),
    CHECK (end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS products (
    product_id INTEGER PRIMARY KEY,
    product_name VARCHAR(150) NOT NULL,
    category_id INTEGER NOT NULL,
    list_price NUMERIC(10, 2) NOT NULL,
    cost_price NUMERIC(10, 2) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    FOREIGN KEY (category_id)
        REFERENCES categories(category_id),

    CHECK (list_price >= 0),
    CHECK (cost_price >= 0)
);

CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    store_id INTEGER NOT NULL,
    order_date DATE NOT NULL,
    order_status VARCHAR(20) NOT NULL,

    FOREIGN KEY (customer_id)
        REFERENCES customers(customer_id),

    FOREIGN KEY (store_id)
        REFERENCES stores(store_id),

    CHECK (order_status IN ('completed', 'cancelled'))
);

CREATE TABLE IF NOT EXISTS order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    promotion_id INTEGER,
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(10, 2) NOT NULL,
    discount_amount NUMERIC(10, 2) NOT NULL DEFAULT 0,

    FOREIGN KEY (order_id)
        REFERENCES orders(order_id),

    FOREIGN KEY (product_id)
        REFERENCES products(product_id),

    FOREIGN KEY (promotion_id)
        REFERENCES promotions(promotion_id),

    CHECK (quantity > 0),
    CHECK (unit_price >= 0),
    CHECK (discount_amount >= 0)
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    payment_date DATE NOT NULL,
    payment_method VARCHAR(30) NOT NULL,
    payment_status VARCHAR(30) NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,

    FOREIGN KEY (order_id)
        REFERENCES orders(order_id),

    CHECK (payment_method IN ('card', 'upi', 'wallet', 'bank_transfer')),
    CHECK (
        payment_status IN (
            'paid',
            'failed',
            'refunded',
            'partially_refunded'
        )
    ),
    CHECK (amount >= 0)
);

CREATE TABLE IF NOT EXISTS returns (
    return_id INTEGER PRIMARY KEY,
    order_item_id INTEGER NOT NULL,
    return_date DATE NOT NULL,
    return_quantity INTEGER NOT NULL,
    refund_amount NUMERIC(10, 2) NOT NULL,
    return_reason VARCHAR(100),

    FOREIGN KEY (order_item_id)
        REFERENCES order_items(order_item_id),

    CHECK (return_quantity > 0),
    CHECK (refund_amount >= 0)
);
