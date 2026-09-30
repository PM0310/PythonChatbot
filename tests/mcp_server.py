from mcp.server.fastmcp import FastMCP

mcp = FastMCP("local-python-tools")


@mcp.tool()
def add_numbers(a: float, b: float) -> float:
    """Add two numbers and return the sum."""
    return a + b


@mcp.tool()
def format_sales_order(order_id: str, customer: str, amount: float) -> str:
    """Create a simple sales order summary line."""
    return f"SalesOrder {order_id}: customer={customer}, amount={amount:.2f}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
