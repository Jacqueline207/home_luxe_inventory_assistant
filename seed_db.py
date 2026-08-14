"""

creating inventory.db and fake retail data for Home Luxe (a small fictional home_goods retail store)

run this file before running agent

it can delete and rebuild the database

"""

import os
import random
import sqlite3
from datetime import date, timedelta


#creating an absolute file in the same folder
DATABASE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inventory.db")

#i decided to name the small retail business store "Home Luxe"

PRODUCTS = [
    #including the stock keeping unit, name, category, unit cost, price, supplier, lead time days (the total number of days for newly purchased inventory to arrive), and safety stock (the extra amount of items kept to prevent against running out)
    ("HL-CANDLE-01", "Cedar Soy Candle 8oz",     "Home Fragrance", 6.40,  18.00, "Northwind Supply", 7,  12),
    ("HL-CANDLE-02", "Fig & Vetiver Candle 8oz", "Home Fragrance", 6.90,  19.00, "Northwind Supply", 7,  12),
    ("HL-MUG-01",    "Stoneware Mug, Sand",      "Kitchen",        4.10,  14.00, "Kiln & Co",        14, 20),
    ("HL-MUG-02",    "Stoneware Mug, Slate",     "Kitchen",        4.10,  14.00, "Kiln & Co",        14, 20),
    ("HL-TOWEL-01",  "Waffle Tea Towel 2-pack",  "Kitchen",        5.25,  16.00, "Linen Row",        10, 15),
    ("HL-THROW-01",  "Merino Throw Blanket",     "Textiles",      38.00, 110.00, "Linen Row",        21, 6),
    ("HL-THROW-02",  "Plum Throw Pillow",     "Textiles",          8.00,  55.00, "Kiln & Co",         7, 15),
    ("HL-VASE-01",   "Ribbed Ceramic Vase",      "Decor",         12.75,  38.00, "Kiln & Co",        14, 8),
    ("HL-FRAME-01",  "Oak Photo Frame 5x7",      "Decor",          7.80,  24.00, "Timber Goods",     12, 10),
    ("HL-SOAP-01",   "Olive Oil Bar Soap",       "Bath",           2.30,   9.00, "Northwind Supply", 7,  30),
    ("HL-DIFF-01",   "Reed Diffuser, Linen",     "Home Fragrance", 9.50,  28.00, "Northwind Supply", 7,  10),
    ("HL-BOARD-01",  "Acacia Serving Board",     "Kitchen",       15.00,  46.00, "Timber Goods",     12, 6),
    ("HL-PLANT-01",  "Terracotta Planter 6in",   "Decor",          5.60,  18.00, "Kiln & Co",        14, 12),
]

#mixing the stock levels
ON_HAND = {
    "HL-CANDLE-01": 42, "HL-CANDLE-02": 9,  "HL-MUG-01": 6,   "HL-MUG-02": 55,
    "HL-TOWEL-01": 13,  "HL-THROW-01": 2,   "HL-VASE-01": 21,  "HL-FRAME-01": 4,
    "HL-SOAP-01": 88,   "HL-DIFF-01": 7,    "HL-BOARD-01": 5,  "HL-PLANT-01": 30,
    "HL-THROW-02": 14,
}

#conn to connect to database and cur for cursor (to execute sql against the database)
def main() -> None:
    if os.path.exists(DATABASE_PATH):
        os.remove(DATABASE_PATH)

    conn = sqlite3.connect(DATABASE_PATH)
    cur = conn.cursor()

    #using real for real number
    cur.executescript(
        """
        CREATE TABLE products (
            stock_keeping_unit          TEXT PRIMARY KEY,
            name                        TEXT NOT NULL,
            category                    TEXT NOT NULL,
            unit_cost                   REAL NOT NULL,
            price                       REAL NOT NULL,
            supplier                    TEXT NOT NULL,
            lead_time_days              INTEGER NOT NULL,
            safety_stock                INTEGER NOT NULL 
        );

        CREATE TABLE inventory (
            stock_keeping_unit          TEXT PRIMARY KEY REFERENCES products(stock_keeping_unit),
            on_hand                     INTEGER NOT NULL,
            on_order                    INTEGER NOT NULL DEFAULT 0,
            last_counted                TEXT NOT NULL
        );

        CREATE TABLE sales (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_keeping_unit      TEXT NOT NULL REFERENCES products(stock_keeping_unit),
            sold_on                 TEXT NOT NULL,
            units                   INTEGER NOT NULL
        );

        CREATE TABLE purchase_orders (
            id                        INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_keeping_unit        TEXT NOT NULL REFERENCES products(stock_keeping_unit),
            supplier                  TEXT NOT NULL,
            units                     INTEGER NOT NULL,
            unit_cost                 REAL NOT NULL,
            total_cost                REAL NOT NULL,
            status                    TEXT NOT NULL,
            created_at                TEXT NOT NULL,
            approved_by               TEXT
        );
        """
    )

    #using ? as the placeholder for the values in the products table
    cur.executemany(
        "INSERT INTO products VALUES (?,?,?,?,?,?,?,?)",
        PRODUCTS,
    )

    today = date.today()

    #creating a list of values that will be inserted into the inventory table
    '''For every product in PRODUCTS, get its stock keeping, look up how many units
    are in ON_HAND, set its on-order amount to 0, record today's date, and create a tuple containing those four value'''
    cur.executemany(
        "INSERT INTO inventory (stock_keeping_unit, on_hand, on_order, last_counted) VALUES (?,?,?,?)",
        [(stock_keeping_unit, ON_HAND[stock_keeping_unit], 0, today.isoformat()) for stock_keeping_unit, *_ in PRODUCTS],
    )

    #fake data sales (two months)
    random.seed(42)
    rows = []
    for stock_keeping_unit, *_ in PRODUCTS:
        #setting the typical sales rate (average number of units the product is expected to sell per day)
        base = random.uniform(0.4, 3.5)
        for d in range(60):
            day = today - timedelta(days=d +1)
            #randomness
            units = max(0, int(random.gauss(base, base * 0.6)))
            if units:
                rows.append((stock_keeping_unit, day.isoformat(), units))
    cur.executemany("INSERT INTO sales (stock_keeping_unit, sold_on, units) VALUES (?,?,?)", rows)

    conn.commit()
    conn.close()

    print(f"Created {DATABASE_PATH}")
    print(f" {len(PRODUCTS)}, products, {len(rows)} synthetic sales rows, 0 purchase orders.")

if __name__ == "__main__":
    main()


        
