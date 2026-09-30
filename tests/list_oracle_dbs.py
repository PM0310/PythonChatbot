import oracledb

oracledb.init_oracle_client(
    lib_dir=r"C:\Users\pavan.maccha\Downloads\instantclient-basic-windows.x64-19.10.0.0.0dbru\instantclient_19_10"
)

conn = oracledb.connect(
    user="apps", password="apps",
    dsn="(DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=cendb.centroid.com)(PORT=1541))(CONNECT_DATA=(SERVICE_NAME=EBS122)))"
)
cur = conn.cursor()

print("=== Current Database ===")
cur.execute("SELECT ora_database_name FROM dual")
print(f"  Database: {cur.fetchone()[0]}")

print("\n=== Instance Info ===")
try:
    cur.execute("SELECT instance_name, host_name, version, status FROM v$instance")
    row = cur.fetchone()
    if row:
        print(f"  Instance: {row[0]}")
        print(f"  Host:     {row[1]}")
        print(f"  Version:  {row[2]}")
        print(f"  Status:   {row[3]}")
except Exception as e:
    print(f"  (No access to v$instance: {e})")

print("\n=== Database Info ===")
try:
    cur.execute("SELECT name, open_mode, log_mode FROM v$database")
    row = cur.fetchone()
    if row:
        print(f"  DB Name:   {row[0]}")
        print(f"  Open Mode: {row[1]}")
        print(f"  Log Mode:  {row[2]}")
except Exception as e:
    print(f"  (No access to v$database: {e})")

print("\n=== Database Links ===")
cur.execute("SELECT db_link, host, owner FROM all_db_links ORDER BY db_link")
rows = cur.fetchall()
if rows:
    for r in rows:
        print(f"  {r[0]} -> Host: {r[1]}, Owner: {r[2]}")
else:
    print("  None found")

print("\n=== Pluggable Databases (PDBs) ===")
try:
    cur.execute("SELECT name, open_mode FROM v$pdbs")
    rows = cur.fetchall()
    if rows:
        for r in rows:
            print(f"  PDB: {r[0]}, Mode: {r[1]}")
    else:
        print("  No PDBs (not a CDB)")
except Exception as e:
    print(f"  Not a Container DB or no access: {e}")

cur.close()
conn.close()
