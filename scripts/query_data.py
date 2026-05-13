"""Utility script to query and display captured market data."""
from __future__ import annotations

import sys
from pathlib import Path

# Albion envia precios en unidades de 1/10000 silver
SILVER_DIVISOR = 10000

import click

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from albion_capture.core.config import load_config
from albion_capture.core.database import create_db_engine


def get_engine(config_path=None):
    cfg = load_config(config_path)
    return create_db_engine(cfg.database)


@click.group()
@click.option("--config", "-c", default=None, type=click.Path(exists=True))
@click.pass_context
def cli(ctx, config):
    ctx.ensure_object(dict)
    ctx.obj["config"] = config


@cli.command()
@click.option("--limit", "-n", default=50, help="Number of orders to show")
@click.option("--item", "-i", default=None, help="Filter by item (e.g. T4_BAG)")
@click.option("--type", "-t", "auction_type", default=None, type=click.Choice(["offer", "request"]))
@click.pass_context
def orders(ctx, limit, item, auction_type):
    """Show captured market orders."""
    engine = get_engine(ctx.obj["config"])

    where_clauses = []
    params = {"limit": limit}

    if item:
        where_clauses.append("item_albion_id ILIKE :item")
        params["item"] = f"%{item}%"
    if auction_type:
        where_clauses.append("auction_type = :auction_type")
        params["auction_type"] = auction_type

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    query = text(f"""
        SELECT item_albion_id, auction_type, quality_level, enchantment_level,
               unit_price_silver, amount, expires_at, captured_at
        FROM market_orders
        {where_sql}
        ORDER BY captured_at DESC
        LIMIT :limit
    """)

    with engine.connect() as conn:
        rows = conn.execute(query, params).fetchall()

    if not rows:
        click.echo("No orders found.")
        return

    # Header
    click.echo(f"\n{'Item':<35} {'Type':<8} {'Q':>2} {'E':>2} {'Price (silver)':>14} {'Qty':>6} {'Expires':<20} {'Captured':<20}")
    click.echo("-" * 130)

    for r in rows:
        price_silver = r[4] / SILVER_DIVISOR
        price_str = f"{price_silver:,.2f}"
        exp = str(r[6])[:19] if r[6] else "N/A"
        cap = str(r[7])[:19] if r[7] else "N/A"
        click.echo(f"{r[0]:<35} {r[1]:<8} {r[2]:>2} {r[3]:>2} {price_str:>14} {r[5]:>6} {exp:<20} {cap:<20}")

    click.echo(f"\nTotal: {len(rows)} orders shown")
    engine.dispose()


@cli.command()
@click.pass_context
def summary(ctx):
    """Show summary statistics of captured data."""
    engine = get_engine(ctx.obj["config"])

    with engine.connect() as conn:
        # Orders summary
        result = conn.execute(text("""
            SELECT
                item_albion_id,
                auction_type,
                COUNT(*) as count,
                MIN(unit_price_silver) as min_price,
                MAX(unit_price_silver) as max_price,
                AVG(unit_price_silver)::BIGINT as avg_price,
                SUM(amount) as total_qty,
                MAX(captured_at) as last_captured
            FROM market_orders
            GROUP BY item_albion_id, auction_type
            ORDER BY count DESC
        """)).fetchall()

        if result:
            click.echo(f"\n{'='*100}")
            click.echo("MARKET ORDERS SUMMARY")
            click.echo(f"{'='*100}")
            click.echo(f"{'Item':<35} {'Type':<8} {'Count':>6} {'Min (silver)':>14} {'Max (silver)':>14} {'Avg (silver)':>14} {'Total Qty':>10}")
            click.echo("-" * 106)
            for r in result:
                min_s = r[3] / SILVER_DIVISOR
                max_s = r[4] / SILVER_DIVISOR
                avg_s = r[5] / SILVER_DIVISOR
                click.echo(f"{r[0]:<35} {r[1]:<8} {r[2]:>6} {min_s:>14,.2f} {max_s:>14,.2f} {avg_s:>14,.2f} {r[6]:>10,}")
            click.echo()

        # Total counts
        total_orders = conn.execute(text("SELECT COUNT(*) FROM market_orders")).scalar()
        total_trades = conn.execute(text("SELECT COUNT(*) FROM market_trades")).scalar()
        total_gold = conn.execute(text("SELECT COUNT(*) FROM gold_prices")).scalar()
        total_sessions = conn.execute(text("SELECT COUNT(*) FROM capture_sessions")).scalar()

        click.echo(f"Total orders:   {total_orders:,}")
        click.echo(f"Total trades:   {total_trades:,}")
        click.echo(f"Total gold:     {total_gold:,}")
        click.echo(f"Sessions:       {total_sessions:,}")

        # Unique items
        unique_items = conn.execute(text("SELECT COUNT(DISTINCT item_albion_id) FROM market_orders")).scalar()
        click.echo(f"Unique items:   {unique_items:,}")

        # Date range
        date_range = conn.execute(text("""
            SELECT MIN(captured_at), MAX(captured_at) FROM market_orders
        """)).fetchone()
        if date_range and date_range[0]:
            click.echo(f"Date range:     {str(date_range[0])[:19]} -> {str(date_range[1])[:19]}")

    engine.dispose()


@cli.command()
@click.pass_context
def history(ctx):
    """Show captured market history/trades."""
    engine = get_engine(ctx.obj["config"])

    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT item_albion_id, city_id, quality_level, timescale,
                   item_amount, silver_amount, avg_price, timestamp
            FROM market_trades
            ORDER BY captured_at DESC
            LIMIT 50
        """)).fetchall()

    if not result:
        click.echo("No trade history found.")
        return

    timescale_names = {0: "24h", 1: "7d", 2: "4w"}

    click.echo(f"\n{'Item':<35} {'City':>5} {'Q':>2} {'Period':<6} {'Qty':>10} {'Silver':>14} {'Avg Price':>12} {'Timestamp':<20}")
    click.echo("-" * 120)

    for r in result:
        ts_name = timescale_names.get(r[3], str(r[3]))
        click.echo(f"{r[0]:<35} {r[1]:>5} {r[2]:>2} {ts_name:<6} {r[4]:>10,} {r[5]:>14,} {r[6]:>12,} {str(r[7])[:19]:<20}")

    click.echo(f"\nTotal: {len(result)} entries shown")
    engine.dispose()


@cli.command()
@click.pass_context
def gold(ctx):
    """Show captured gold prices."""
    engine = get_engine(ctx.obj["config"])

    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT price, timestamp, captured_at
            FROM gold_prices
            ORDER BY timestamp DESC
            LIMIT 50
        """)).fetchall()

    if not result:
        click.echo("No gold prices found.")
        return

    click.echo(f"\n{'Price':>10} {'Timestamp':<25} {'Captured':<25}")
    click.echo("-" * 65)

    for r in result:
        click.echo(f"{r[0]:>10,} {str(r[1])[:19]:<25} {str(r[2])[:19]:<25}")

    click.echo(f"\nTotal: {len(result)} prices shown")
    engine.dispose()


@cli.command()
@click.pass_context
def sessions(ctx):
    """Show capture sessions."""
    engine = get_engine(ctx.obj["config"])

    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, city_name, city_id, local_port, status,
                   started_at, last_heartbeat, packets_captured, orders_extracted
            FROM capture_sessions
            ORDER BY started_at DESC
            LIMIT 20
        """)).fetchall()

    if not result:
        click.echo("No sessions found.")
        return

    click.echo(f"\n{'ID':>4} {'City':<15} {'Port':>6} {'Status':<10} {'Started':<20} {'Last HB':<20} {'Packets':>10} {'Orders':>8}")
    click.echo("-" * 105)

    for r in result:
        click.echo(
            f"{r[0]:>4} {r[1]:<15} {r[3]:>6} {r[4]:<10} "
            f"{str(r[5])[:19]:<20} {str(r[6])[:19]:<20} "
            f"{r[7] or 0:>10,} {r[8] or 0:>8,}"
        )

    engine.dispose()


if __name__ == "__main__":
    cli()
