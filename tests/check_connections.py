import sqlite3

db_path = r"C:\Users\pavan.maccha\AppData\Roaming\Code\User\globalStorage\state.vscdb"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Search for oracle sql developer connection data - try all tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("Tables:", tables)

for table in tables:
    cur.execute(f"SELECT * FROM [{table}] WHERE value LIKE '%CenDb%' OR key LIKE '%CenDb%' OR key LIKE '%sql-developer%connection%'")
    rows = cur.fetchall()
    if rows:
        print(f"\n=== {table}: {len(rows)} matches ===")
        for r in rows:
            print(f"  Key: {r[0]}")
            text = str(r[1])[:600] if len(str(r[1])) > 600 else str(r[1])
            print(f"  Val: {text}")

conn.close()
