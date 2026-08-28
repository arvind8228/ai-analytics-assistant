import json
import random
from bisect import bisect_left
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from faker import Faker


# Project paths

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = PROJECT_ROOT / "config" / "project_settings.json"


# Load project settings

with open(SETTINGS_PATH, "r") as file:
    settings = json.load(file)


RANDOM_SEED = settings["random_seed"]

NUM_CUSTOMERS = settings["dataset_size"]["customers"]
NUM_STORES = settings["dataset_size"]["stores"]
NUM_CATEGORIES = settings["dataset_size"]["categories"]
NUM_PRODUCTS = settings["dataset_size"]["products"]
NUM_ORDERS = settings["dataset_size"]["orders"]
NUM_PROMOTIONS = settings["dataset_size"]["promotions"]


DATA_START_DATE = datetime.strptime(
    settings["date_range"]["start_date"],
    "%Y-%m-%d"
).date()

DATA_END_DATE = datetime.strptime(
    settings["date_range"]["end_date"],
    "%Y-%m-%d"
).date()

ANALYSIS_REFERENCE_DATE = datetime.strptime(
    settings["date_range"]["analysis_reference_date"],
    "%Y-%m-%d"
).date()


CANCELLED_ORDER_RATE = settings[
    "generation_rules"
]["cancelled_order_rate"]

PROMOTION_USAGE_RATE = settings[
    "generation_rules"
]["promotion_usage_rate"]

RETURN_ITEM_RATE = settings[
    "generation_rules"
]["return_item_rate"]

MIN_ITEMS_PER_ORDER = settings[
    "generation_rules"
]["min_items_per_order"]

MAX_ITEMS_PER_ORDER = settings[
    "generation_rules"
]["max_items_per_order"]

MIN_ITEM_QUANTITY = settings[
    "generation_rules"
]["min_item_quantity"]

MAX_ITEM_QUANTITY = settings[
    "generation_rules"
]["max_item_quantity"]


# Set reproducible random seeds

random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)
Faker.seed(RANDOM_SEED)

fake = Faker("en_IN")


def generate_categories():
    category_names = [
        "Electronics",
        "Home",
        "Kitchen",
        "Fashion",
        "Beauty",
        "Sports",
        "Books",
        "Accessories"
    ]

    return pd.DataFrame({
        "category_id": range(
            1,
            NUM_CATEGORIES + 1
        ),
        "category_name": category_names
    })


def generate_stores():
    store_locations = [
        (
            "Bengaluru Central",
            "Bengaluru",
            "South"
        ),
        (
            "Chennai City",
            "Chennai",
            "South"
        ),
        (
            "Mumbai Central",
            "Mumbai",
            "West"
        ),
        (
            "Pune City",
            "Pune",
            "West"
        ),
        (
            "Delhi Central",
            "Delhi",
            "North"
        ),
        (
            "Kolkata City",
            "Kolkata",
            "East"
        )
    ]

    stores = []

    for store_id, (name, city, region) in enumerate(
        store_locations,
        start=1
    ):
        stores.append({
            "store_id": store_id,
            "store_name": name,
            "city": city,
            "region": region,
            "opened_date": fake.date_between(
                start_date=date(2018, 1, 1),
                end_date=date(2024, 12, 31)
            )
        })

    return pd.DataFrame(stores)


def generate_customers():
    customer_locations = [
        ("Bengaluru", "South"),
        ("Chennai", "South"),
        ("Hyderabad", "South"),
        ("Mumbai", "West"),
        ("Pune", "West"),
        ("Ahmedabad", "West"),
        ("Delhi", "North"),
        ("Jaipur", "North"),
        ("Kolkata", "East")
    ]

    location_weights = [
        0.18,
        0.10,
        0.12,
        0.16,
        0.09,
        0.07,
        0.14,
        0.06,
        0.08
    ]

    customers = []

    for customer_id in range(
        1,
        NUM_CUSTOMERS + 1
    ):
        city, region = random.choices(
            customer_locations,
            weights=location_weights,
            k=1
        )[0]

        customers.append({
            "customer_id": customer_id,
            "customer_name": fake.name(),
            "city": city,
            "region": region,
            "signup_date": fake.date_between(
                start_date=DATA_START_DATE,
                end_date=DATA_END_DATE
            )
        })

    return pd.DataFrame(customers)


def generate_products():
    category_price_ranges = {
        1: (500, 50000),
        2: (300, 15000),
        3: (200, 10000),
        4: (300, 8000),
        5: (150, 5000),
        6: (300, 15000),
        7: (100, 2000),
        8: (150, 7500)
    }

    products = []

    for product_id in range(
        1,
        NUM_PRODUCTS + 1
    ):
        category_id = random.randint(
            1,
            NUM_CATEGORIES
        )

        min_price, max_price = (
            category_price_ranges[
                category_id
            ]
        )

        list_price = round(
            random.uniform(
                min_price,
                max_price
            ),
            2
        )

        cost_price = round(
            list_price
            * random.uniform(
                0.45,
                0.75
            ),
            2
        )

        products.append({
            "product_id": product_id,
            "product_name":
                f"Product {product_id:03d}",
            "category_id": category_id,
            "list_price": list_price,
            "cost_price": cost_price,
            "is_active":
                random.random() > 0.05
        })

    return pd.DataFrame(products)


def generate_promotions():
    promotions = []

    for promotion_id in range(
        1,
        NUM_PROMOTIONS + 1
    ):
        start_date = fake.date_between(
            start_date=DATA_START_DATE,
            end_date=date(2026, 6, 30)
        )

        duration_days = random.randint(
            7,
            30
        )

        end_date = min(
            start_date
            + timedelta(
                days=duration_days
            ),
            DATA_END_DATE
        )

        discount_type = random.choice([
            "percentage",
            "fixed"
        ])

        if discount_type == "percentage":
            discount_value = random.choice([
                5,
                10,
                15,
                20,
                25
            ])
        else:
            discount_value = random.choice([
                100,
                250,
                500,
                750
            ])

        promotions.append({
            "promotion_id":
                promotion_id,
            "promotion_name":
                f"Promotion {promotion_id:02d}",
            "discount_type":
                discount_type,
            "discount_value":
                discount_value,
            "start_date":
                start_date,
            "end_date":
                end_date
        })

    return pd.DataFrame(promotions)


def generate_orders(
    customers_df,
    stores_df
):
    order_random = random.Random(
        RANDOM_SEED + 1
    )

    order_rng = np.random.default_rng(
        RANDOM_SEED + 1
    )

    # Give customers different buying activity levels
    customer_order_weights = (
        order_rng.lognormal(
            mean=0.0,
            sigma=0.9,
            size=NUM_CUSTOMERS
        )
    )

    customer_probabilities = (
        customer_order_weights
        / customer_order_weights.sum()
    )

    selected_customer_ids = (
        order_rng.choice(
            np.arange(
                1,
                NUM_CUSTOMERS + 1
            ),
            size=NUM_ORDERS,
            p=customer_probabilities
        )
    )

    all_order_dates = [
        timestamp.date()
        for timestamp in pd.date_range(
            DATA_START_DATE,
            DATA_END_DATE,
            freq="D"
        )
    ]

    date_weights = []

    for order_date in all_order_dates:
        weight = 1.0

        # Mild end-of-year seasonality
        if order_date.month in [
            10,
            11,
            12
        ]:
            weight *= 1.35

        # Slightly more weekend activity
        if order_date.weekday() >= 5:
            weight *= 1.10

        date_weights.append(weight)

    customer_signup = (
        customers_df
        .set_index(
            "customer_id"
        )["signup_date"]
        .to_dict()
    )

    customer_region = (
        customers_df
        .set_index(
            "customer_id"
        )["region"]
        .to_dict()
    )

    stores_by_region = (
        stores_df
        .groupby(
            "region"
        )["store_id"]
        .apply(list)
        .to_dict()
    )

    all_store_ids = (
        stores_df[
            "store_id"
        ].tolist()
    )

    orders = []

    for order_id, customer_id in enumerate(
        selected_customer_ids,
        start=1
    ):
        customer_id = int(
            customer_id
        )

        signup_date = (
            customer_signup[
                customer_id
            ]
        )

        start_index = bisect_left(
            all_order_dates,
            signup_date
        )

        eligible_dates = (
            all_order_dates[
                start_index:
            ]
        )

        eligible_weights = (
            date_weights[
                start_index:
            ]
        )

        order_date = (
            order_random.choices(
                eligible_dates,
                weights=eligible_weights,
                k=1
            )[0]
        )

        region = (
            customer_region[
                customer_id
            ]
        )

        regional_stores = (
            stores_by_region.get(
                region,
                []
            )
        )

        # Most customers shop in their own region
        if (
            regional_stores
            and order_random.random()
            < 0.85
        ):
            store_id = (
                order_random.choice(
                    regional_stores
                )
            )
        else:
            store_id = (
                order_random.choice(
                    all_store_ids
                )
            )

        if (
            order_random.random()
            < CANCELLED_ORDER_RATE
        ):
            order_status = "cancelled"
        else:
            order_status = "completed"

        orders.append({
            "order_id": order_id,
            "customer_id":
                customer_id,
            "store_id":
                store_id,
            "order_date":
                order_date,
            "order_status":
                order_status
        })

    return pd.DataFrame(orders)


def generate_order_items(
    orders_df,
    products_df,
    promotions_df
):
    items_random = random.Random(
        RANDOM_SEED + 2
    )

    items_rng = np.random.default_rng(
        RANDOM_SEED + 2
    )

    active_products = (
        products_df[
            products_df["is_active"]
            == True
        ].copy()
    )

    active_product_ids = (
        active_products[
            "product_id"
        ].to_numpy()
    )

    product_prices = (
        products_df
        .set_index(
            "product_id"
        )["list_price"]
        .to_dict()
    )

    # Give some products more demand than others
    product_weights = (
        items_rng.lognormal(
            mean=0.0,
            sigma=0.8,
            size=len(
                active_product_ids
            )
        )
    )

    product_probabilities = (
        product_weights
        / product_weights.sum()
    )

    promotion_records = (
        promotions_df
        .to_dict(
            "records"
        )
    )

    order_items = []
    order_item_id = 1

    for order in orders_df.itertuples(
        index=False
    ):
        num_items = (
            items_random.randint(
                MIN_ITEMS_PER_ORDER,
                MAX_ITEMS_PER_ORDER
            )
        )

        selected_products = (
            items_rng.choice(
                active_product_ids,
                size=num_items,
                replace=False,
                p=product_probabilities
            )
        )

        for product_id in selected_products:
            product_id = int(
                product_id
            )

            quantity = (
                items_random.randint(
                    MIN_ITEM_QUANTITY,
                    MAX_ITEM_QUANTITY
                )
            )

            unit_price = round(
                float(
                    product_prices[
                        product_id
                    ]
                ),
                2
            )

            promotion_id = None
            discount_amount = 0.0

            eligible_promotions = [
                promotion
                for promotion
                in promotion_records
                if (
                    promotion["start_date"]
                    <= order.order_date
                    <= promotion["end_date"]
                )
            ]

            if (
                eligible_promotions
                and items_random.random()
                < PROMOTION_USAGE_RATE
            ):
                promotion = (
                    items_random.choice(
                        eligible_promotions
                    )
                )

                promotion_id = (
                    promotion[
                        "promotion_id"
                    ]
                )

                line_value = (
                    unit_price
                    * quantity
                )

                if (
                    promotion[
                        "discount_type"
                    ]
                    == "percentage"
                ):
                    discount_amount = round(
                        line_value
                        * float(
                            promotion[
                                "discount_value"
                            ]
                        )
                        / 100,
                        2
                    )
                else:
                    discount_amount = round(
                        min(
                            float(
                                promotion[
                                    "discount_value"
                                ]
                            ),
                            line_value * 0.50
                        ),
                        2
                    )

            order_items.append({
                "order_item_id":
                    order_item_id,
                "order_id":
                    order.order_id,
                "product_id":
                    product_id,
                "promotion_id":
                    promotion_id,
                "quantity":
                    quantity,
                "unit_price":
                    unit_price,
                "discount_amount":
                    discount_amount
            })

            order_item_id += 1

    return pd.DataFrame(
        order_items
    )


def generate_returns(
    orders_df,
    order_items_df
):
    returns_random = random.Random(
        RANDOM_SEED + 3
    )

    return_candidates = (
        order_items_df.merge(
            orders_df[
                [
                    "order_id",
                    "order_date",
                    "order_status"
                ]
            ],
            on="order_id",
            how="left"
        )
    )

    return_candidates = (
        return_candidates[
            (
                return_candidates[
                    "order_status"
                ]
                == "completed"
            )
            &
            (
                return_candidates[
                    "order_date"
                ]
                < DATA_END_DATE
            )
        ].copy()
    )

    returns = []
    return_id = 1

    for item in (
        return_candidates
        .itertuples(
            index=False
        )
    ):
        if (
            returns_random.random()
            < RETURN_ITEM_RATE
        ):
            return_quantity = (
                returns_random.randint(
                    1,
                    item.quantity
                )
            )

            line_value = (
                item.unit_price
                * item.quantity
            )

            net_line_value = (
                line_value
                - item.discount_amount
            )

            refund_amount = round(
                (
                    net_line_value
                    / item.quantity
                )
                * return_quantity,
                2
            )

            latest_return_date = min(
                item.order_date
                + timedelta(
                    days=30
                ),
                DATA_END_DATE
            )

            days_available = (
                latest_return_date
                - item.order_date
            ).days

            return_date = (
                item.order_date
                + timedelta(
                    days=(
                        returns_random.randint(
                            1,
                            days_available
                        )
                    )
                )
            )

            return_reason = (
                returns_random.choice([
                    "Damaged item",
                    "Wrong item",
                    "Changed mind",
                    "Size or fit issue",
                    "Not as expected"
                ])
            )

            returns.append({
                "return_id":
                    return_id,
                "order_item_id":
                    item.order_item_id,
                "return_date":
                    return_date,
                "return_quantity":
                    return_quantity,
                "refund_amount":
                    refund_amount,
                "return_reason":
                    return_reason
            })

            return_id += 1

    return pd.DataFrame(
        returns
    )


def generate_payments(
    orders_df,
    order_items_df,
    returns_df
):
    payments_random = random.Random(
        RANDOM_SEED + 4
    )

    order_items_with_value = (
        order_items_df.copy()
    )

    order_items_with_value[
        "net_item_value"
    ] = (
        order_items_with_value[
            "unit_price"
        ]
        * order_items_with_value[
            "quantity"
        ]
        - order_items_with_value[
            "discount_amount"
        ]
    )

    order_totals = (
        order_items_with_value
        .groupby(
            "order_id"
        )["net_item_value"]
        .sum()
        .to_dict()
    )

    refunds_by_order = (
        returns_df
        .merge(
            order_items_df[
                [
                    "order_item_id",
                    "order_id"
                ]
            ],
            on="order_item_id",
            how="left"
        )
        .groupby(
            "order_id"
        )["refund_amount"]
        .sum()
        .to_dict()
    )

    payment_methods = [
        "card",
        "upi",
        "wallet",
        "bank_transfer"
    ]

    payment_method_weights = [
        0.35,
        0.45,
        0.12,
        0.08
    ]

    payments = []

    for payment_id, order in enumerate(
        orders_df.itertuples(
            index=False
        ),
        start=1
    ):
        order_total = round(
            float(
                order_totals[
                    order.order_id
                ]
            ),
            2
        )

        refund_total = round(
            float(
                refunds_by_order.get(
                    order.order_id,
                    0
                )
            ),
            2
        )

        payment_method = (
            payments_random.choices(
                payment_methods,
                weights=payment_method_weights,
                k=1
            )[0]
        )

        if (
            order.order_status
            == "cancelled"
        ):
            payment_status = "failed"
            payment_amount = 0.0

        elif refund_total == 0:
            payment_status = "paid"
            payment_amount = order_total

        elif abs(
            refund_total
            - order_total
        ) < 0.01:
            payment_status = "refunded"
            payment_amount = order_total

        else:
            payment_status = (
                "partially_refunded"
            )
            payment_amount = order_total

        payments.append({
            "payment_id":
                payment_id,
            "order_id":
                order.order_id,
            "payment_date":
                order.order_date,
            "payment_method":
                payment_method,
            "payment_status":
                payment_status,
            "amount":
                payment_amount
        })

    return pd.DataFrame(
        payments
    )


def clean_value(value):
    if pd.isna(value):
        return None

    if isinstance(
        value,
        np.generic
    ):
        return value.item()

    return value


def insert_dataframe(
    cursor,
    table_name,
    dataframe
):
    columns = list(
        dataframe.columns
    )

    column_names = ", ".join(
        columns
    )

    placeholders = ", ".join(
        ["%s"] * len(columns)
    )

    query = f"""
        INSERT INTO {table_name}
        ({column_names})
        VALUES ({placeholders})
    """

    rows = [
        tuple(
            clean_value(value)
            for value in row
        )
        for row
        in dataframe.itertuples(
            index=False,
            name=None
        )
    ]

    cursor.executemany(
        query,
        rows
    )

    print(
        f"Loaded {len(rows):,} rows into {table_name}"
    )


def load_database(
    customers_df,
    stores_df,
    categories_df,
    promotions_df,
    products_df,
    orders_df,
    order_items_df,
    payments_df,
    returns_df
):
    with psycopg.connect(
        dbname="ai_analytics"
    ) as conn:

        with conn.cursor() as cur:

            # Clear existing rows before rebuilding
            cur.execute("""
                TRUNCATE TABLE
                    returns,
                    payments,
                    order_items,
                    orders,
                    products,
                    promotions,
                    categories,
                    stores,
                    customers
                CASCADE;
            """)

            insert_dataframe(
                cur,
                "customers",
                customers_df
            )

            insert_dataframe(
                cur,
                "stores",
                stores_df
            )

            insert_dataframe(
                cur,
                "categories",
                categories_df
            )

            insert_dataframe(
                cur,
                "promotions",
                promotions_df
            )

            insert_dataframe(
                cur,
                "products",
                products_df
            )

            insert_dataframe(
                cur,
                "orders",
                orders_df
            )

            insert_dataframe(
                cur,
                "order_items",
                order_items_df
            )

            insert_dataframe(
                cur,
                "payments",
                payments_df
            )

            insert_dataframe(
                cur,
                "returns",
                returns_df
            )


def validate_database(
    expected_counts
):
    all_checks_passed = True

    with psycopg.connect(
        dbname="ai_analytics"
    ) as conn:

        with conn.cursor() as cur:

            print()
            print("Database validation")

            for (
                table_name,
                expected_count
            ) in expected_counts.items():

                cur.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {table_name};
                    """
                )

                actual_count = (
                    cur.fetchone()[0]
                )

                passed = (
                    actual_count
                    == expected_count
                )

                print(
                    f"{table_name}: "
                    f"{actual_count:,} "
                    f"- {passed}"
                )

                if not passed:
                    all_checks_passed = False


            # Orders cannot happen before signup

            cur.execute("""
                SELECT COUNT(*)
                FROM orders o
                JOIN customers c
                    ON o.customer_id
                    = c.customer_id
                WHERE o.order_date
                    < c.signup_date;
            """)

            invalid_order_dates = (
                cur.fetchone()[0]
            )

            print(
                "Orders before signup:",
                invalid_order_dates
            )

            if invalid_order_dates != 0:
                all_checks_passed = False


            # Cancelled orders must have failed zero-value payments

            cur.execute("""
                SELECT COUNT(*)
                FROM orders o
                JOIN payments p
                    ON o.order_id
                    = p.order_id
                WHERE o.order_status
                    = 'cancelled'
                  AND (
                      p.payment_status
                        <> 'failed'
                      OR p.amount <> 0
                  );
            """)

            invalid_cancelled_payments = (
                cur.fetchone()[0]
            )

            print(
                "Invalid cancelled payments:",
                invalid_cancelled_payments
            )

            if (
                invalid_cancelled_payments
                != 0
            ):
                all_checks_passed = False


            # Returned quantity cannot exceed purchased quantity

            cur.execute("""
                SELECT COUNT(*)
                FROM returns r
                JOIN order_items oi
                    ON r.order_item_id
                    = oi.order_item_id
                WHERE r.return_quantity
                    > oi.quantity;
            """)

            invalid_return_quantities = (
                cur.fetchone()[0]
            )

            print(
                "Invalid return quantities:",
                invalid_return_quantities
            )

            if (
                invalid_return_quantities
                != 0
            ):
                all_checks_passed = False


            # Returns must belong to completed orders

            cur.execute("""
                SELECT COUNT(*)
                FROM returns r
                JOIN order_items oi
                    ON r.order_item_id
                    = oi.order_item_id
                JOIN orders o
                    ON oi.order_id
                    = o.order_id
                WHERE o.order_status
                    <> 'completed';
            """)

            invalid_return_orders = (
                cur.fetchone()[0]
            )

            print(
                "Returns from invalid orders:",
                invalid_return_orders
            )

            if invalid_return_orders != 0:
                all_checks_passed = False


            # Return date must be after order date

            cur.execute("""
                SELECT COUNT(*)
                FROM returns r
                JOIN order_items oi
                    ON r.order_item_id
                    = oi.order_item_id
                JOIN orders o
                    ON oi.order_id
                    = o.order_id
                WHERE r.return_date
                    <= o.order_date;
            """)

            invalid_return_dates = (
                cur.fetchone()[0]
            )

            print(
                "Invalid return dates:",
                invalid_return_dates
            )

            if invalid_return_dates != 0:
                all_checks_passed = False


            # Promotions must be active on order date

            cur.execute("""
                SELECT COUNT(*)
                FROM order_items oi
                JOIN orders o
                    ON oi.order_id
                    = o.order_id
                JOIN promotions p
                    ON oi.promotion_id
                    = p.promotion_id
                WHERE oi.promotion_id
                    IS NOT NULL
                  AND (
                      o.order_date
                        < p.start_date
                      OR
                      o.order_date
                        > p.end_date
                  );
            """)

            invalid_promotions = (
                cur.fetchone()[0]
            )

            print(
                "Invalid promotion dates:",
                invalid_promotions
            )

            if invalid_promotions != 0:
                all_checks_passed = False


    print()
    print(
        "All database checks passed:",
        all_checks_passed
    )

    return all_checks_passed


def main():
    print("Project settings loaded")
    print(
        "Random seed:",
        RANDOM_SEED
    )
    print(
        "Customers:",
        NUM_CUSTOMERS
    )
    print(
        "Orders:",
        NUM_ORDERS
    )
    print(
        "Data period:",
        DATA_START_DATE,
        "to",
        DATA_END_DATE
    )
    print(
        "Analysis reference date:",
        ANALYSIS_REFERENCE_DATE
    )


    categories_df = (
        generate_categories()
    )

    stores_df = (
        generate_stores()
    )

    customers_df = (
        generate_customers()
    )

    products_df = (
        generate_products()
    )

    promotions_df = (
        generate_promotions()
    )


    print()
    print(
        "Parent tables generated"
    )

    print(
        "Customers:",
        len(customers_df)
    )

    print(
        "Stores:",
        len(stores_df)
    )

    print(
        "Categories:",
        len(categories_df)
    )

    print(
        "Products:",
        len(products_df)
    )

    print(
        "Promotions:",
        len(promotions_df)
    )


    orders_df = generate_orders(
        customers_df,
        stores_df
    )

    order_items_df = (
        generate_order_items(
            orders_df,
            products_df,
            promotions_df
        )
    )


    print()
    print(
        "Transaction tables generated"
    )

    print(
        "Orders:",
        len(orders_df)
    )

    print(
        "Order items:",
        len(order_items_df)
    )

    print(
        "Completed orders:",
        (
            orders_df[
                "order_status"
            ]
            == "completed"
        ).sum()
    )

    print(
        "Cancelled orders:",
        (
            orders_df[
                "order_status"
            ]
            == "cancelled"
        ).sum()
    )

    print(
        "Customers with orders:",
        orders_df[
            "customer_id"
        ].nunique()
    )


    returns_df = (
        generate_returns(
            orders_df,
            order_items_df
        )
    )

    payments_df = (
        generate_payments(
            orders_df,
            order_items_df,
            returns_df
        )
    )


    print()
    print(
        "Returns and payments generated"
    )

    print(
        "Returns:",
        len(returns_df)
    )

    print(
        "Payments:",
        len(payments_df)
    )

    print()
    print(
        "Payment status"
    )

    print(
        payments_df[
            "payment_status"
        ].value_counts()
    )


    print()
    print(
        "Loading data into PostgreSQL"
    )

    load_database(
        customers_df,
        stores_df,
        categories_df,
        promotions_df,
        products_df,
        orders_df,
        order_items_df,
        payments_df,
        returns_df
    )


    expected_counts = {
        "customers":
            len(customers_df),

        "stores":
            len(stores_df),

        "categories":
            len(categories_df),

        "promotions":
            len(promotions_df),

        "products":
            len(products_df),

        "orders":
            len(orders_df),

        "order_items":
            len(order_items_df),

        "payments":
            len(payments_df),

        "returns":
            len(returns_df)
    }


    validation_passed = (
        validate_database(
            expected_counts
        )
    )

    if not validation_passed:
        raise RuntimeError(
            "Database validation failed."
        )


if __name__ == "__main__":
    main()