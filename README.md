# Uptime Analyzer

A Python tool for analyzing uptime logs from PostgreSQL databases. This tool fetches database backups, queries uptime data, generates visualizations, and creates CSV backups.

## Features

- **Backup Management**: Fetch PostgreSQL dumps from remote servers and save them locally
- **Docker Integration**: Automatically manages temporary PostgreSQL containers for data processing
- **Data Analysis**: Query and analyze uptime logs with custom SQL queries
- **Visualizations**: Generate interactive plots showing:
  - Overall uptime status over time
  - Per-user disconnect patterns
  - Offline duration distributions
- **CSV Export**: Save query results as CSV files for further analysis

## Requirements

- Python 3.13+
- Docker (for temporary PostgreSQL containers)
- `uv` package manager (recommended) or `pip`

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd uptime_analyzer
```

2. Install dependencies using `uv`:
```bash
uv sync
```

Or using `pip`:
```bash
pip install -e .
```

## Usage

### Backup Command

Fetch a PostgreSQL dump, restore it to a temporary container, query the data, and save as CSV:

```bash
uv run python main.py backup
```

Options:
- `--backup-url` / `-u`: URL to fetch the PostgreSQL dump from (default: `http://34.55.225.231:3000/backup`)
- `--query` / `-q`: SQL query to execute on uptime_logs table (default: `SELECT * FROM uptime_logs ORDER BY iso_timestamp`)
- `--port` / `-p`: Host port to bind to (default: random available port)
- `--output-dir` / `-o`: Directory to save CSV backup (default: `backups`)

Example:
```bash
uv run python main.py backup --backup-url http://example.com/backup --output-dir my_backups
```

### Plots Command

Generate visualizations from uptime logs:

```bash
uv run python main.py plots
```

Options:
- `--logs-url` / `-u`: URL or path to the logs file (default: `http://34.55.225.231:3000/logs`)

Example:
```bash
uv run python main.py plots --logs-url logs.txt
```

The plots command generates:
1. Overall status scatter plot showing online/offline status over time
2. Per-user accumulated disconnects plot
3. Offline duration distribution bar chart (in Hebrew)

## Project Structure

```
uptime_analyzer/
├── main.py           # Main application with CLI commands
├── pyproject.toml    # Project dependencies and metadata
├── backup.sh         # Shell script for running backups
├── plots.sh          # Shell script for generating plots
├── backups/          # Directory for saved backups (SQL and CSV)
└── README.md         # This file
```

## Dependencies

- `pandas`: Data manipulation and analysis
- `plotly`: Interactive visualizations
- `requests`: HTTP requests for fetching backups and logs
- `psycopg`: PostgreSQL database adapter
- `typer`: CLI framework

## How It Works

### Backup Process

1. Fetches a PostgreSQL dump from the specified URL
2. Starts a temporary Docker PostgreSQL container
3. Restores the dump to the temporary database
4. Executes the specified SQL query
5. Saves results as CSV and the original dump as SQL
6. Cleans up the temporary container and database

### Visualization Process

1. Reads logs from URL or local file
2. Parses log entries to extract timestamp, user, ISP, and status
3. Generates interactive plots using Plotly
4. Displays plots in browser

## Configuration

Default settings can be modified in `main.py`:
- `DEFAULT_DB_PASSWORD`: Default PostgreSQL password for local connections
- `DOCKER_DB_PASSWORD`: Password for temporary Docker containers

## Notes

- The tool automatically manages Docker containers and cleans them up after use
- Backups are saved with timestamps in the format `backup_YYYY-MM-DD-HH:MM:SS.{sql|csv}`
- The tool requires Docker to be installed and running for the backup functionality
