#!/usr/bin/env python3
"""Quick check of local_life_agent mock data."""
import json

# shops
with open('local_life_agent/mock_data/shops.json', 'r', encoding='utf-8-sig') as f:
    shops = json.load(f)
print(f"shops.json: {len(shops)} shops")
print(f"  Keys: {list(shops[0].keys())}")
print(f"  First: {shops[0]['shop_id']} - {shops[0]['shop_name']}")
print(f"  Last:  {shops[-1]['shop_id']} - {shops[-1]['shop_name']}")
cats = set(s.get('category','') for s in shops)
print(f"  Categories: {cats}")

# coupons
with open('local_life_agent/mock_data/coupons.json', 'r', encoding='utf-8-sig') as f:
    coupons = json.load(f)
print(f"\ncoupons.json: {len(coupons)} coupons")
shop_ids = set(c['shop_id'] for c in coupons)
print(f"  Unique shop_ids: {len(shop_ids)}")
print(f"  Keys: {list(coupons[0].keys())}")

# distance_eta
with open('local_life_agent/mock_data/distance_eta.json', 'r', encoding='utf-8-sig') as f:
    eta = json.load(f)
print(f"\ndistance_eta.json: {len(eta)} entries")
print(f"  Keys: {list(eta[0].keys())}")

print("\n=== MySQL Data Check ===")
import mysql.connector
conn = mysql.connector.connect(host='localhost', port=3306, database='hmdp', user='root', password='123456')
c = conn.cursor()
c.execute("SELECT COUNT(*) FROM tb_shop")
print(f"  tb_shop: {c.fetchone()[0]} rows")
c.execute("SELECT COUNT(*) FROM tb_voucher")
print(f"  tb_voucher: {c.fetchone()[0]} rows")
c.execute("SELECT COUNT(*) FROM tb_shop_type")
print(f"  tb_shop_type: {c.fetchone()[0]} rows")
conn.close()
