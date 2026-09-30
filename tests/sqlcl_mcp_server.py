import os
import oracledb
from mcp.server.fastmcp import FastMCP

# Initialize Oracle Instant Client
oracledb.init_oracle_client(
    lib_dir=r"C:\Users\pavan.maccha\Downloads\instantclient-basic-windows.x64-19.10.0.0.0dbru\instantclient_19_10"
)

mcp = FastMCP("sqlcl-mcp-server")

# Connection defaults (override via environment variables)
ORACLE_USER = os.environ.get("ORACLE_USER", "apps")
ORACLE_PASSWORD = os.environ.get("ORACLE_PASSWORD", "apps")
ORACLE_DSN = os.environ.get(
    "ORACLE_DSN",
    "(DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=cendb.centroid.com)(PORT=1541))(CONNECT_DATA=(SERVICE_NAME=EBS122)))",
)


def _get_connection():
    return oracledb.connect(user=ORACLE_USER, password=ORACLE_PASSWORD, dsn=ORACLE_DSN)


@mcp.tool()
def run_sql_query(sql: str) -> str:
    """Run a SELECT SQL query against the Oracle database and return results as formatted text."""
    sql_stripped = sql.strip().rstrip(";")
    upper = sql_stripped.upper()
    if not upper.startswith("SELECT") and not upper.startswith("WITH"):
        return "Error: Only SELECT / WITH queries are allowed. Use run_plsql for other operations."

    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_stripped)
        columns = [col[0] for col in cur.description]
        rows = cur.fetchmany(500)

        if not rows:
            return "Query returned 0 rows."

        col_widths = [len(c) for c in columns]
        for row in rows:
            for i, val in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(val) if val is not None else "NULL"))

        header = " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(columns))
        separator = "-+-".join("-" * w for w in col_widths)
        data_lines = []
        for row in rows:
            line = " | ".join(
                str(val if val is not None else "NULL").ljust(col_widths[i])
                for i, val in enumerate(row)
            )
            data_lines.append(line)

        result = f"{header}\n{separator}\n" + "\n".join(data_lines)
        result += f"\n\n({len(rows)} row{'s' if len(rows) != 1 else ''} returned)"
        if len(rows) == 500:
            result += "\n(Results truncated at 500 rows)"
        return result
    except Exception as e:
        return f"Error: {e}"
    finally:
        conn.close()


@mcp.tool()
def run_plsql(plsql_block: str) -> str:
    """Execute a PL/SQL block against the Oracle database. Returns DBMS_OUTPUT lines if any."""
    conn = _get_connection()
    try:
        cur = conn.cursor()
        # Enable DBMS_OUTPUT capture
        cur.callproc("DBMS_OUTPUT.ENABLE", [1000000])
        cur.execute(plsql_block)
        conn.commit()

        # Fetch DBMS_OUTPUT lines
        output_lines = []
        status_var = cur.var(int)
        line_var = cur.var(str)
        while True:
            cur.callproc("DBMS_OUTPUT.GET_LINE", [line_var, status_var])
            if status_var.getvalue() != 0:
                break
            output_lines.append(line_var.getvalue())

        if output_lines:
            return "\n".join(output_lines)
        return "PL/SQL block executed successfully."
    except Exception as e:
        conn.rollback()
        return f"Error: {e}"
    finally:
        conn.close()


@mcp.tool()
def describe_table(table_name: str, owner: str = "") -> str:
    """Describe an Oracle table or view — shows columns, data types, and nullable info."""
    conn = _get_connection()
    try:
        cur = conn.cursor()
        if owner:
            cur.execute(
                """SELECT column_name, data_type, data_length, data_precision, data_scale, nullable
                   FROM all_tab_columns
                   WHERE table_name = UPPER(:1) AND owner = UPPER(:2)
                   ORDER BY column_id""",
                [table_name, owner],
            )
        else:
            cur.execute(
                """SELECT column_name, data_type, data_length, data_precision, data_scale, nullable
                   FROM all_tab_columns
                   WHERE table_name = UPPER(:1)
                   ORDER BY column_id""",
                [table_name],
            )
        rows = cur.fetchall()
        if not rows:
            return f"Table '{table_name}' not found."

        lines = [f"Table: {table_name.upper()}", ""]
        lines.append(f"{'COLUMN_NAME':<30} {'DATA_TYPE':<15} {'LENGTH':<8} {'PRECISION':<10} {'SCALE':<6} {'NULL?'}")
        lines.append("-" * 85)
        for r in rows:
            col, dtype, dlen, prec, scale, nullable = r
            lines.append(
                f"{col:<30} {dtype:<15} {str(dlen or ''):<8} {str(prec or ''):<10} {str(scale or ''):<6} {'Y' if nullable == 'Y' else 'N'}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"
    finally:
        conn.close()


@mcp.tool()
def list_tables(owner: str = "", name_pattern: str = "%") -> str:
    """List tables in the Oracle database. Optionally filter by owner and name pattern (SQL LIKE)."""
    conn = _get_connection()
    try:
        cur = conn.cursor()
        if owner:
            cur.execute(
                """SELECT owner, table_name, num_rows
                   FROM all_tables
                   WHERE owner = UPPER(:1) AND table_name LIKE UPPER(:2)
                   ORDER BY owner, table_name
                   FETCH FIRST 200 ROWS ONLY""",
                [owner, name_pattern],
            )
        else:
            cur.execute(
                """SELECT owner, table_name, num_rows
                   FROM all_tables
                   WHERE table_name LIKE UPPER(:1)
                   ORDER BY owner, table_name
                   FETCH FIRST 200 ROWS ONLY""",
                [name_pattern],
            )
        rows = cur.fetchall()
        if not rows:
            return "No tables found."

        lines = [f"{'OWNER':<20} {'TABLE_NAME':<40} {'NUM_ROWS':<12}"]
        lines.append("-" * 72)
        for r in rows:
            lines.append(f"{r[0]:<20} {r[1]:<40} {str(r[2] or 'N/A'):<12}")
        lines.append(f"\n({len(rows)} table{'s' if len(rows) != 1 else ''} found)")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"
    finally:
        conn.close()


@mcp.tool()
def list_schemas() -> str:
    """List all database schemas (users) in the Oracle database."""
    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT username, account_status, default_tablespace
               FROM all_users
               JOIN dba_users USING (username)
               ORDER BY username
               FETCH FIRST 200 ROWS ONLY"""
        )
        rows = cur.fetchall()
        if not rows:
            # Fallback if no DBA access
            cur.execute("SELECT username FROM all_users ORDER BY username FETCH FIRST 200 ROWS ONLY")
            rows = cur.fetchall()
            lines = [f"{'USERNAME':<30}"]
            lines.append("-" * 30)
            for r in rows:
                lines.append(f"{r[0]:<30}")
            lines.append(f"\n({len(rows)} schema{'s' if len(rows) != 1 else ''} found)")
            return "\n".join(lines)

        lines = [f"{'USERNAME':<30} {'STATUS':<20} {'TABLESPACE':<20}"]
        lines.append("-" * 70)
        for r in rows:
            lines.append(f"{r[0]:<30} {r[1]:<20} {r[2]:<20}")
        lines.append(f"\n({len(rows)} schema{'s' if len(rows) != 1 else ''} found)")
        return "\n".join(lines)
    except Exception:
        # Fallback without DBA views
        try:
            cur = conn.cursor()
            cur.execute("SELECT username FROM all_users ORDER BY username FETCH FIRST 200 ROWS ONLY")
            rows = cur.fetchall()
            lines = [f"{'USERNAME':<30}"]
            lines.append("-" * 30)
            for r in rows:
                lines.append(f"{r[0]:<30}")
            lines.append(f"\n({len(rows)} schema{'s' if len(rows) != 1 else ''} found)")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"
    finally:
        conn.close()


if __name__ == "__main__":
    mcp.run(transport="stdio")
