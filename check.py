import sqlite3
conn = sqlite3.connect("fact.db")   # change filename if yours is named differently

print("--- Mulberry 2022 ---")
for r in conn.execute("SELECT crop, measure, period, value_num FROM fact_generic WHERE sector='Mulberry' AND period LIKE '2022%'"):
    print(r)

print("--- Period spelling check ---")
for r in conn.execute("SELECT DISTINCT period FROM fact_generic WHERE sector IN ('Honey','Mushroom','Cereal Crops') ORDER BY period"):
    print(r)

print("--- Ecological Belt ---")
for r in conn.execute("SELECT * FROM fact_generic WHERE sector='Ecological Belt'"):
    print(r)

print("--- Honey crops ---")
for r in conn.execute("SELECT DISTINCT crop FROM fact_generic WHERE sector='Honey'"):
    print(r)