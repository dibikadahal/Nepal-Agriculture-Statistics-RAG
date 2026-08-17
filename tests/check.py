import sqlite3
conn = sqlite3.connect("data/fact.db")   # change filename if yours is named differently

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

print("--- Crop counts per sector (catches silent drops) ---")
for r in conn.execute("SELECT sector, crop, COUNT(*) FROM fact_generic GROUP BY sector, crop ORDER BY sector, crop"):
    print(r)

print("--- Period spacing variants ---")
for r in conn.execute("SELECT DISTINCT period FROM fact_generic WHERE period LIKE '%78/79%'"):
    print(repr(r[0]))