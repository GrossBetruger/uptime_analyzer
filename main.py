import pandas as pd 
import requests
import re
import plotly.express as px
from base64 import b64decode
import os
import psycopg
import subprocess
import tempfile
from typing import Optional
import getpass
import time
import socket
import uuid
from contextlib import contextmanager
from io import StringIO
from datetime import datetime
from pathlib import Path


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
        if not line:
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
    backup_path = Path("backups") / f"backup_{datetime.now().strftime('%Y-%m-%d-%H:%M:%S')}.sql"
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

 

def main():
    logs_url = decode_url("WVVoU01HTkViM1pNZWswd1RHcFZNVXhxU1hsT1V6UjVUWHBGTmsxNlFYZE5Remx6WWpKa2VrTm5QVDBLCg==")
    logs_remote = read_logs("http://34.55.225.231:3000/logs")
    # logs_local = read_logs("backup-2025-11-04-15:43.txt")
    # logs = pd.concat([logs_remote, logs_local])
    logs = logs_remote
    logs.sort_values(by="readable_timestamp", inplace=True)
    fig = px.scatter(logs, x="readable_timestamp", y="status", color="user")
    fig.show()

    for user in logs["user"].unique():
        user_logs = logs[logs["user"] == user]
        user_logs["is_offline"] = user_logs["status"] == "offline"
        user_logs["accumulated-disconnects"] = user_logs["is_offline"].cumsum(skipna=True)
        fig = px.scatter(user_logs, x="readable_timestamp", y="accumulated-disconnects", color="user")
        fig.show()

        # s: a pandas Series with a DatetimeIndex
        value = "offline"
        cond = user_logs["status"].eq(value).fillna(False)

        # label contiguous runs of True/False
        grp = (cond != cond.shift()).cumsum()

        # length of the current True-streak at each time (0 when not value)
        running_streak = cond.groupby(grp).cumsum().astype(int)
        # print(json.dumps(running_streak.to_list(), indent=4))
        counts = running_streak.value_counts().drop(0)
        if counts.empty:
            continue
        fig = px.bar(counts, x=counts.index, y=counts.values)
        x_label = "זמן ניתוק בשניות"
        y_label = "מספר ניתוקים"
        fig.update_layout(xaxis_title=x_label, yaxis_title=y_label)
        fig.show()


if __name__ == "__main__":
    import sys
    # Check if we should use temp container
        # Use temporary Docker container
    df = query_uptime_logs_with_temp_container()
    csv_backup_path = Path("backups") / f"backup_{datetime.now().strftime('%Y-%m-%d-%H:%M:%S')}.csv"
    df.to_csv(csv_backup_path, index=False)
    print(f"CSV backup saved to {csv_backup_path}") 
    print(f"\nQuery completed successfully!")
    print(f"Retrieved {len(df)} rows")
    print(f"\nFirst few rows:")
    print(df.head())
  