import pandas as pd 
import requests
import re
import plotly.express as px
from base64 import b64decode
import os
import psycopg
import subprocess
from typing import Optional
import time
import socket
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import typer
from copy import deepcopy
from IPython import embed

def decode_url(url: str) -> str:
    for _ in range(3): 
        url = b64decode(url).decode("utf-8")
    return url

def read_logs(url: str) -> pd.DataFrame:
    """
    Read logs from a URL and return a pandas DataFrame.
    """
    if os.path.exists(url):
        text = open(url).read()
    else:
        text = requests.get(url).text
    # response = requests.get(url)
    records = []
    for line in text.split("\n"):
        original = deepcopy(line)
        if not line or line == " ":
            continue
        timestamp = line.split(" ")[0]
        msg = line[len(timestamp) + 1:]
        readable_timestamp = msg.split(" ")[0]
        msg = msg[len(readable_timestamp) + 1:]
        user = msg.split(" ")[0]
        msg = msg[len(user) + 1:]
        ip = msg.split(" ")[0]
        msg = msg[len(ip) + 1:]
        isp = re.search("(.+?) (online|offline)", msg).group(1)
        status = re.search("(.+?) (online|offline)", msg).group(2)
        record = {"timestamp": timestamp, "readable_timestamp": readable_timestamp, "user": user, "isp": isp, "status": status  }
        records.append(record)
    return pd.DataFrame(records)


# Default password for local PostgreSQL (only used locally)
# Update this to match your local PostgreSQL password
DEFAULT_DB_PASSWORD = "password"

# Default password for temporary Docker PostgreSQL container
DOCKER_DB_PASSWORD = "postgres"

def enrich_logs(logs: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich logs with daily statistics.
    """
    logs["date"] = pd.to_datetime(logs["readable_timestamp"], errors="coerce", utc=True).dt.date
    return logs

@contextmanager
def temp_postgres_container(
    password: str = DOCKER_DB_PASSWORD,
    port: Optional[int] = None,
    image: str = "postgres:15-alpine"
):
    """
    Context manager that starts a temporary PostgreSQL Docker container
    and cleans it up when done.
    
    Args:
        password: PostgreSQL password (default: DOCKER_DB_PASSWORD)
        port: Host port to bind to (default: random available port)
        image: Docker image to use (default: postgres:15-alpine)
        
    Yields:
        dict with keys: host, port, user, password, container_id
        
    Example:
        with temp_postgres_container() as db_config:
            # Use db_config['host'], db_config['port'], etc.
            pass
    """
    # Find an available port if not specified
    if port is None:
        sock = socket.socket()
        sock.bind(('', 0))
        port = sock.getsockname()[1]
        sock.close()
    
    container_name = f"uptime_postgres_{uuid.uuid4().hex[:8]}"
    container_id = None
    
    try:
        # Check if Docker is available
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise RuntimeError("Docker is not available. Please install Docker and ensure it's running.")
        
        # Start PostgreSQL container
        print(f"Starting PostgreSQL container '{container_name}' on port {port}...")
        cmd = [
            "docker", "run",
            "-d",  # Detached mode
            "--name", container_name,
            "-e", f"POSTGRES_PASSWORD={password}",
            "-e", "POSTGRES_USER=postgres",
            "-p", f"{port}:5432",
            image
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Failed to start container: {result.stderr}")
        
        container_id = result.stdout.strip()
        print(f"Container started: {container_id[:12]}")
        
        # Wait for PostgreSQL to be ready
        print("Waiting for PostgreSQL to be ready...")
        max_retries = 30
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                with psycopg.connect(
                    host="localhost",
                    port=port,
                    user="postgres",
                    password=password,
                    connect_timeout=2
                ) as conn:
                    conn.execute("SELECT 1")
                    print("PostgreSQL is ready!")
                    break
            except (psycopg.OperationalError, psycopg.InterfaceError):
                retry_count += 1
                if retry_count >= max_retries:
                    raise RuntimeError("PostgreSQL container failed to become ready")
                time.sleep(1)
        
        # Yield connection info
        yield {
            "host": "localhost",
            "port": port,
            "user": "postgres",
            "password": password,
            "container_id": container_id,
            "container_name": container_name
        }
    
    finally:
        # Cleanup: stop and remove container
        if container_name:
            print(f"Stopping and removing container '{container_name}'...")
            try:
                # Stop container
                subprocess.run(
                    ["docker", "stop", container_name],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                # Remove container
                subprocess.run(
                    ["docker", "rm", container_name],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                print("Container cleaned up successfully")
            except Exception as e:
                print(f"Warning: Failed to clean up container: {e}")


def query_uptime_logs_with_temp_container(
    backup_url: str = "http://34.55.225.231:3000/backup",
    query: str = "SELECT * FROM uptime_logs",
    **kwargs
) -> pd.DataFrame:
    """
    Query uptime logs from backup using a temporary PostgreSQL Docker container.
    
    This function automatically starts a temporary PostgreSQL container, runs
    query_uptime_logs_from_backup, and cleans up the container when done.
    
    Args:
        backup_url: URL to fetch the PostgreSQL dump from
        query: SQL query to execute on uptime_logs table
        **kwargs: Additional arguments passed to temp_postgres_container
        
    Returns:
        pandas DataFrame with query results
    """
    with temp_postgres_container(**kwargs) as db_config:
        return query_uptime_logs_from_backup(
            backup_url=backup_url,
            db_host=db_config["host"],
            db_port=db_config["port"],
            db_user=db_config["user"],
            db_password=db_config["password"],
            container_name=db_config["container_name"],
            query=query
        )

def query_uptime_logs_from_backup(
    backup_url: str = "http://34.55.225.231:3000/backup",
    db_host: str = "localhost",
    db_port: int = 5432,
    db_user: Optional[str] = None,
    db_password: Optional[str] = None,
    temp_db_name: Optional[str] = None,
    container_name: Optional[str] = None,
    query: str = "SELECT * FROM uptime_logs ORDER BY iso_timestamp"
) -> pd.DataFrame:
    """
    Fetch PostgreSQL dump from URL, restore it to a temporary database,
    and query the uptime_logs table.
    
    Args:
        backup_url: URL to fetch the PostgreSQL dump from
        db_host: PostgreSQL host (default: localhost)
        db_port: PostgreSQL port (default: 5432)
        db_user: PostgreSQL user (default: postgres)
        db_password: PostgreSQL password (optional, defaults to DEFAULT_DB_PASSWORD for local use)
        temp_db_name: Temporary database name (auto-generated if None)
        container_name: Docker container name (if using temp_postgres_container)
        query: SQL query to execute on uptime_logs table
        
    Returns:
        pandas DataFrame with query results
    """
    db_user = db_user or "postgres"
    db_password = db_password or DEFAULT_DB_PASSWORD
    temp_db_name = temp_db_name or f"uptime_temp_{uuid.uuid4().hex[:8]}"
    
    backup_response = requests.get(backup_url)
    backup_content = backup_response.content
    backup_text = backup_response.text

    Path.mkdir(Path("backups"), exist_ok=True)
    backup_path = Path("backups") / f"backup_{datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}.sql"
    with open(backup_path, "w") as f:
        f.write(backup_text)
    print(f"Backup saved to {backup_path}")

    with psycopg.connect(
        host=db_host,
        port=db_port,
        user=db_user,
        password=db_password,
        dbname="postgres"
    ) as conn:
        conn.autocommit = True
        conn.execute(f"CREATE DATABASE {temp_db_name}")
    
    subprocess.run(
        ["docker", "exec", "-i", container_name, "psql", "-U", db_user, "-d", temp_db_name],
        input=backup_content,
        capture_output=True,
        check=True
    )
    
    with psycopg.connect(
        host=db_host,
        port=db_port,
        user=db_user,
        password=db_password,
        dbname=temp_db_name
    ) as conn:
        df = pd.read_sql_query(query, conn)
    
    with psycopg.connect(
        host=db_host,
        port=db_port,
        user=db_user,
        password=db_password,
        dbname="postgres"
    ) as conn:
        conn.autocommit = True
        conn.execute(f"DROP DATABASE {temp_db_name}")
    
    return df

 

app = typer.Typer(help="Uptime Analyzer - Analyze uptime logs and generate backups")


@app.command()
def backup(
    backup_url: str = typer.Option(
        "http://34.55.225.231:3000/backup",
        "--backup-url",
        "-u",
        help="URL to fetch the PostgreSQL dump from"
    ),
    query: str = typer.Option(
        "SELECT * FROM uptime_logs ORDER BY iso_timestamp",
        "--query",
        "-q",
        help="SQL query to execute on uptime_logs table"
    ),
    port: Optional[int] = typer.Option(
        None,
        "--port",
        "-p",
        help="Host port to bind to (default: random available port)"
    ),
    output_dir: str = typer.Option(
        "backups",
        "--output-dir",
        "-o",
        help="Directory to save CSV backup"
    )
):
    """
    Backup uptime logs from a PostgreSQL database dump.
    
    This command fetches a PostgreSQL dump from the specified URL, restores it
    to a temporary Docker container, queries the data, and saves it as a CSV file.
    """
    df = query_uptime_logs_with_temp_container(
        backup_url=backup_url,
        query=query,
        port=port
    )
    
    Path.mkdir(Path(output_dir), exist_ok=True)
    csv_backup_path = Path(output_dir) / f"backup_{datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}.csv"
    df.to_csv(csv_backup_path, index=False)
    print(f"CSV backup saved to {csv_backup_path}") 
    print(f"\nQuery completed successfully!")
    print(f"Retrieved {len(df)} rows")
    print(f"\nLast few rows:")
    print(df.tail())

def user_daily_stats(logs: pd.DataFrame, user: str) -> pd.DataFrame:
    """
    Calculate daily statistics for a given user.
    """
    logs = logs[logs["user"] == user]
    return logs.groupby("date").describe()


@app.command()
def plots(
    logs_url: str = typer.Option(
        "http://34.55.225.231:3000/logs",
        "--logs-url",
        "-u",
        help="URL or path to the logs file"
    )
):
    """
    Generate plots from uptime logs.
    
    This command reads logs from the specified URL or file and generates
    visualization plots showing uptime status, disconnects, and offline durations.
    """
    logs = read_logs(logs_url)
    logs = enrich_logs(logs)
    logs.sort_values(by="readable_timestamp", inplace=True)
    test_users = ["OrenK", "Drier", "2025-11-18T17:28:23+02:00"]
    # embed()
    logs = logs[~logs["user"].isin(test_users)]
    # Overall status plot
    fig = px.scatter(logs, x="readable_timestamp", y="status", color="user")
    fig.show()

    # Per-user plots
    for user in logs["user"].unique():
        user_stats = user_daily_stats(logs, user)
        user_logs = logs[logs["user"] == user].copy()
        user_logs["is_offline"] = user_logs["status"] == "offline"
        user_logs["accumulated-disconnects"] = user_logs["is_offline"].cumsum(skipna=True)
        
        # Accumulated disconnects plot
        fig = px.scatter(user_logs, x="readable_timestamp", y="accumulated-disconnects", color="user")
        fig.show()

        # Offline duration distribution
        value = "offline"
        cond = user_logs["status"].eq(value).fillna(False)

        # label contiguous runs of True/False
        grp = (cond != cond.shift()).cumsum()

        # length of the current True-streak at each time (0 when not value)
        running_streak = cond.groupby(grp).cumsum().astype(int)
        counts = running_streak.value_counts().drop(0)
        if counts.empty:
            continue
        fig = px.bar(counts, x=counts.index, y=counts.values)
        x_label = "זמן ניתוק בשניות"
        y_label = "מספר ניתוקים"
        fig.update_layout(xaxis_title=x_label, yaxis_title=y_label, title=f"{user} :ניתוקים של")
        fig.show()


@app.command()
def user_counts(
    logs_url: str = typer.Option(
        "http://34.55.225.231:3000/logs",
        "--logs-url",
        "-u",
        help="URL or path to the logs file"
    )
):
    """
    Count rows per user and display sorted by count.
    
    This command reads logs and shows how many log entries each user has,
    sorted from highest to lowest count.
    """
    logs = read_logs(logs_url)
    counts = logs["user"].value_counts().sort_values(ascending=False)
    print("\nUser row counts (sorted by count):\n")
    print(counts.to_string())
    print(f"\nTotal rows: {len(logs)}")
    print(f"Total users: {len(counts)}")


def calculate_stats(df: pd.DataFrame) -> dict:
    """Calculate offline/online statistics for a dataframe."""
    total = len(df)
    if total == 0:
        return {"total": 0, "offline": 0, "offline_pct": 0.0, "online_pct": 0.0, 
                "normalized_offline_pct": 0.0, "normalized_online_pct": 0.0}
    offline = (df["status"] == "offline").sum()
    offline_pct = (offline / total) * 100
    online_pct = 100 - offline_pct
    
    # Normalized: calculate per-user offline percentage, then average across users
    # This gives each user equal weight regardless of row count
    user_stats = df.groupby("user").agg(
        user_total=("status", "count"),
        user_offline=("status", lambda x: (x == "offline").sum())
    )
    user_stats["user_offline_pct"] = (user_stats["user_offline"] / user_stats["user_total"]) * 100
    normalized_offline_pct = user_stats["user_offline_pct"].mean()
    normalized_online_pct = 100 - normalized_offline_pct
    
    return {
        "total": total, 
        "offline": offline, 
        "offline_pct": offline_pct, 
        "online_pct": online_pct,
        "normalized_offline_pct": normalized_offline_pct,
        "normalized_online_pct": normalized_online_pct
    }


@app.command()
def monthly_stats(
    logs_url: str = typer.Option(
        "http://34.55.225.231:3000/logs",
        "--logs-url",
        "-u",
        help="URL or path to the logs file"
    ),
    exclude_test_users: bool = typer.Option(
        True,
        "--exclude-test-users/--include-test-users",
        "-e/-i",
        help="Exclude test users (OrenK, Drier)"
    ),
    rush_start: int = typer.Option(
        20,
        "--rush-start",
        help="Rush hour start time (24h format, default: 20)"
    ),
    rush_end: int = typer.Option(
        23,
        "--rush-end",
        help="Rush hour end time (24h format, default: 23)"
    )
):
    """
    Show monthly statistics with user counts and row counts.
    
    For each month, displays: number of rows, unique users, offline count,
    and offline ratio. Also shows rush hours (20:00-23:00) statistics.
    Similar to offline_ratio.sh but broken down by month.
    """
    logs = read_logs(logs_url)
    
    # Exclude test users if requested
    test_users = ["OrenK", "Drier", "2025-11-18T17:28:23+02:00"]
    if exclude_test_users:
        logs = logs[~logs["user"].isin(test_users)]
    
    # Extract hour and month directly from ISO string (e.g., "2025-11-18T17:28:23+02:00")
    # The hour in the string is already in local time, so we can extract it directly
    logs["local_hour"] = logs["readable_timestamp"].str.extract(r"T(\d{2}):")[0].astype(int)
    logs["month"] = logs["readable_timestamp"].str[:7]  # "2025-11" format
    
    # Parse timestamp to UTC for date range display
    logs["parsed_timestamp"] = pd.to_datetime(logs["readable_timestamp"], errors="coerce", utc=True)
    
    # Filter for rush hours (20:00 to 23:00 means hours 20, 21, 22)
    logs["is_rush_hour"] = (logs["local_hour"] >= rush_start) & (logs["local_hour"] < rush_end)
    
    print("\n" + "=" * 70)
    print(f"Monthly Statistics (Rush Hours: {rush_start:02d}:00-{rush_end:02d}:00 local time)")
    print("=" * 70)
    
    for month in sorted(logs["month"].unique()):
        month_logs = logs[logs["month"] == month]
        rush_logs = month_logs[month_logs["is_rush_hour"]]
        
        all_stats = calculate_stats(month_logs)
        rush_stats = calculate_stats(rush_logs)
        
        print(f"\n{month}:")
        print(f"  ALL DAY:")
        print(f"    Total rows:           {all_stats['total']:,}")
        print(f"    Unique users:         {month_logs['user'].nunique()}")
        print(f"    Offline:              {all_stats['offline']:,}")
        print(f"    Offline percent:      {all_stats['offline_pct']:.2f}%")
        print(f"    Online percent:       {all_stats['online_pct']:.2f}%")
        print(f"    Normalized offline:   {all_stats['normalized_offline_pct']:.2f}%  (per-user avg)")
        print(f"    Normalized online:    {all_stats['normalized_online_pct']:.2f}%  (per-user avg)")
        print(f"  RUSH HOURS ({rush_start:02d}:00-{rush_end:02d}:00):")
        print(f"    Total rows:           {rush_stats['total']:,}")
        print(f"    Unique users:         {rush_logs['user'].nunique()}")
        print(f"    Offline:              {rush_stats['offline']:,}")
        print(f"    Offline percent:      {rush_stats['offline_pct']:.2f}%")
        print(f"    Online percent:       {rush_stats['online_pct']:.2f}%")
        print(f"    Normalized offline:   {rush_stats['normalized_offline_pct']:.2f}%  (per-user avg)")
        print(f"    Normalized online:    {rush_stats['normalized_online_pct']:.2f}%  (per-user avg)")
    
    # Also show per-user breakdown per month
    print("\n" + "=" * 70)
    print("Per-User Row Counts by Month (All Day)")
    print("=" * 70)
    
    user_monthly = logs.groupby(["month", "user"]).size().unstack(fill_value=0)
    print(f"\n{user_monthly.to_string()}")
    
    print("\n" + "=" * 70)
    print("Per-User Row Counts by Month (Rush Hours Only)")
    print("=" * 70)
    
    rush_only = logs[logs["is_rush_hour"]]
    if len(rush_only) > 0:
        user_monthly_rush = rush_only.groupby(["month", "user"]).size().unstack(fill_value=0)
        print(f"\n{user_monthly_rush.to_string()}")
    else:
        print("\nNo rush hour data available.")
    
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Total rows:        {len(logs):,}")
    print(f"Rush hour rows:    {len(rush_only):,}")
    print(f"Total users:       {logs['user'].nunique()}")
    print(f"Date range:        {logs['parsed_timestamp'].min()} to {logs['parsed_timestamp'].max()}")


if __name__ == "__main__":
    app()
  
