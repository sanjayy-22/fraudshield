"""Clean the DataCo Supply Chain Dataset for FraudShield pipeline.

Input : raw DataCoSupplyChainDataset.csv (180 519 rows × 53 columns)
Output: cleaned_dataco.csv  — ready for feature engineering / model training

Cleaning steps
──────────────
1. Drop columns that are useless or contain PII
   - Product Description  (100 % NaN)
   - Product Status       (single constant value 0)
   - Customer Email       (all masked 'XXXXXXXXX')
   - Customer Password    (all masked 'XXXXXXXXX')
   - Customer Street      (PII, not useful for fraud detection)
   - Order Zipcode        (86.2 % missing)
   - Product Image        (URL, not useful for modelling)

2. Parse dates
   - 'order date (DateOrders)'    → datetime  → rename 'order_date'
   - 'shipping date (DateOrders)' → datetime  → rename 'shipping_date'

3. Handle missing values
   - Customer Lname   (8 NaN)     → fill with 'Unknown'
   - Customer Zipcode (3 NaN)     → fill with 0, cast to int

4. Create target / derived columns
   - is_fraud: 1 if Order Status == 'SUSPECTED_FRAUD', else 0
   - shipping_delay_days: (shipping_date − order_date).days
   - order_hour: hour extracted from order_date
   - is_late: 1 if Delivery Status == 'Late delivery'

5. Rename columns to snake_case for consistency

6. Drop redundant / leaking columns
   - 'Order Customer Id'  (duplicate of Customer Id)
   - 'Product Category Id' (duplicate of Category Id)
   - 'Sales per customer'  (identical to Order Item Total — leakage)

7. Reorder and export
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import numpy as np

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ─────────────────────────────────────────── paths
# Raw file location: --raw argument, else $DATACO_RAW, else ./DataCoSupplyChainDataset.csv
RAW_PATH = Path(os.environ.get("DATACO_RAW", "DataCoSupplyChainDataset.csv"))
OUT_DIR = Path(__file__).resolve().parent
OUT_PATH = OUT_DIR / "cleaned_dataco.csv"


def clean(path: Path = RAW_PATH) -> pd.DataFrame:
    print(f"Reading {path} ...")
    df = pd.read_csv(path, encoding="latin-1")
    print(f"  Raw shape: {df.shape}")

    # ── 1. Drop useless / PII / mostly-null columns ──────────────────────
    drop_cols = [
        "Product Description",   # 100 % NaN
        "Product Status",        # single value (0)
        "Customer Email",        # masked 'XXXXXXXXX'
        "Customer Password",     # masked 'XXXXXXXXX'
        "Customer Street",       # PII
        "Order Zipcode",         # 86.2 % missing
        "Product Image",         # URL string, not useful
    ]
    df.drop(columns=[c for c in drop_cols if c in df.columns], inplace=True)
    print(f"  After dropping useless/PII columns: {df.shape}")

    # ── 2. Parse dates ───────────────────────────────────────────────────
    df["order_date"] = pd.to_datetime(
        df["order date (DateOrders)"], format="%m/%d/%Y %H:%M"
    )
    df["shipping_date"] = pd.to_datetime(
        df["shipping date (DateOrders)"], format="%m/%d/%Y %H:%M"
    )
    df.drop(columns=["order date (DateOrders)", "shipping date (DateOrders)"], inplace=True)

    # ── 3. Handle missing values ─────────────────────────────────────────
    df["Customer Lname"] = df["Customer Lname"].fillna("Unknown")
    df["Customer Zipcode"] = df["Customer Zipcode"].fillna(0).astype(int)
    remaining_null = df.isnull().sum()
    remaining_null = remaining_null[remaining_null > 0]
    if len(remaining_null):
        print(f"  Remaining nulls:\n{remaining_null.to_string()}")
    else:
        print("  No remaining nulls ✓")

    # ── 4. Create target & derived columns ───────────────────────────────
    df["is_fraud"] = (df["Order Status"] == "SUSPECTED_FRAUD").astype(int)
    df["shipping_delay_days"] = (df["shipping_date"] - df["order_date"]).dt.days
    df["order_hour"] = df["order_date"].dt.hour
    df["is_late"] = (df["Delivery Status"] == "Late delivery").astype(int)

    fraud_n = df["is_fraud"].sum()
    fraud_pct = df["is_fraud"].mean() * 100
    print(f"  Fraud label: {fraud_n} rows ({fraud_pct:.2f}%)")

    # ── 5. Rename to snake_case ──────────────────────────────────────────
    rename_map = {
        "Type": "payment_type",
        "Days for shipping (real)": "days_shipping_real",
        "Days for shipment (scheduled)": "days_shipment_scheduled",
        "Benefit per order": "benefit_per_order",
        "Sales per customer": "sales_per_customer",
        "Delivery Status": "delivery_status",
        "Late_delivery_risk": "late_delivery_risk",
        "Category Id": "category_id",
        "Category Name": "category_name",
        "Customer City": "customer_city",
        "Customer Country": "customer_country",
        "Customer Fname": "customer_fname",
        "Customer Id": "customer_id",
        "Customer Lname": "customer_lname",
        "Customer Segment": "customer_segment",
        "Customer State": "customer_state",
        "Customer Zipcode": "customer_zipcode",
        "Department Id": "department_id",
        "Department Name": "department_name",
        "Latitude": "latitude",
        "Longitude": "longitude",
        "Market": "market",
        "Order City": "order_city",
        "Order Country": "order_country",
        "Order Customer Id": "order_customer_id",
        "Order Id": "order_id",
        "Order Item Cardprod Id": "order_item_cardprod_id",
        "Order Item Discount": "order_item_discount",
        "Order Item Discount Rate": "order_item_discount_rate",
        "Order Item Id": "order_item_id",
        "Order Item Product Price": "order_item_product_price",
        "Order Item Profit Ratio": "order_item_profit_ratio",
        "Order Item Quantity": "order_item_quantity",
        "Sales": "sales",
        "Order Item Total": "order_item_total",
        "Order Profit Per Order": "order_profit_per_order",
        "Order Region": "order_region",
        "Order State": "order_state",
        "Order Status": "order_status",
        "Product Card Id": "product_card_id",
        "Product Category Id": "product_category_id",
        "Product Name": "product_name",
        "Product Price": "product_price",
        "Shipping Mode": "shipping_mode",
    }
    df.rename(columns=rename_map, inplace=True)

    # ── 6. Drop redundant / leaking columns ──────────────────────────────
    redundant = [
        "order_customer_id",    # duplicate of customer_id
        "product_category_id",  # duplicate of category_id
        "sales_per_customer",   # identical to order_item_total (data leak)
    ]
    df.drop(columns=[c for c in redundant if c in df.columns], inplace=True)
    print(f"  After dropping redundant columns: {df.shape}")

    # ── 7. Sort by order date, reset index ───────────────────────────────
    df.sort_values("order_date", kind="stable", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # ── Final summary ────────────────────────────────────────────────────
    print(f"\n{'='*55}")
    print(f"  Cleaned shape   : {df.shape}")
    print(f"  Date range      : {df['order_date'].min()} → {df['order_date'].max()}")
    print(f"  Fraud (is_fraud): {df['is_fraud'].sum()} / {len(df)} ({df['is_fraud'].mean()*100:.2f}%)")
    print(f"  Columns         : {list(df.columns)}")
    print(f"  Dtypes:\n{df.dtypes.to_string()}")
    print(f"{'='*55}")

    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", type=Path, default=RAW_PATH, help="path to DataCoSupplyChainDataset.csv")
    ap.add_argument("--out", type=Path, default=OUT_PATH, help="where to write cleaned_dataco.csv")
    args = ap.parse_args()
    OUT_PATH = args.out
    df = clean(args.raw)
    df.to_csv(OUT_PATH, index=False)
    print(f"\n✓ Saved cleaned dataset to {OUT_PATH}")
    print(f"  {len(df)} rows × {len(df.columns)} columns")
