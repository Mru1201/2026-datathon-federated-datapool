# AWO MCP Server

MCP (Model Context Protocol) server that exposes processed AWO facility data to AI assistants like Claude Desktop.

## Overview

This MCP server provides a standardized interface between AI assistants and AWO organizational data. It enables natural language queries about AWO facilities, services, and statistics.

**Data Source:** Processed AWO datasets (facilities, addresses, services, providers)

**Status:** ✅ Production-ready

---

## Architecture

```text
User
  │
Claude Desktop
  │
MCP Server (this repo)
  │
Processed AWO Data (CSV)
```

---

## Features

### Available Tools

| Tool                         | Description                        | Example                                   |
| ---------------------------- | ---------------------------------- | ----------------------------------------- |
| `count_facilities(city)`     | Count facilities in a city         | "How many AWO facilities are in Berlin?"  |
| `search_facilities(city)`    | List all facilities in a city      | "Show me all AWO facilities in Berlin"    |
| `get_facility_details(name)` | Get detailed info about a facility | "Tell me about AWO Sozialstation Wedding" |
| `search_services(query)`     | Search for services by keyword     | "Find addiction services"                 |
| `generate_statistics()`      | Get data statistics                | "Show me statistics about AWO facilities" |
| `check_completeness()`       | Check data quality                 | "Check data completeness for AWO records" |
| `detect_duplicates()`        | Find duplicate records             | "Are there duplicates in the AWO data?"   |
| `compare_facilities(f1, f2)` | Compare two facilities             | "Compare AWO Mitte and AWO Spree-Wuhle"   |

---

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/awo-mcp-production.git
cd awo-mcp-production
```

### 2. Create and Activate Conda Environment

```bash
conda create -n awo-mcp python=3.11
conda activate awo-mcp
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Verify Data Files

Ensure the following CSV files exist in the `data/` directory:

* `einrichtungSchema.csv` - Facilities
* `adresseSchema.csv` - Addresses
* `angebotSchema.csv` - Services
* `traegerSchema.csv` - Providers

---

## Running the Server

Start the MCP server:

```bash
python server.py
```

The server will start and wait for MCP requests. Leave this terminal running.

---

## Connecting to Claude Desktop

### Step 1: Install Claude Desktop

Download from [Claude Desktop](https://claude.ai/download).

> **Note:** No Claude subscription is required for MCP server integration.

### Step 2: Configure MCP Server

1. Open Claude Desktop.
2. Go to **Settings → Developer → Local MCP Servers → Edit Config**.
3. Add the following configuration:

```json
{
  "mcpServers": {
    "awo": {
      "command": "C:\\Users\\<YOUR_USERNAME>\\miniconda3\\envs\\awo-mcp\\python.exe",
      "args": [
        "D:\\path\\to\\awo-mcp-production\\server.py"
      ]
    }
  }
}
```

### Step 3: Restart Claude Desktop

Save the configuration and restart Claude Desktop completely.

The MCP server should appear under **Settings → Developer → Local MCP Servers** with a green status.

---

## Example Queries

Once connected, try asking Claude:

### Count Facilities

> "How many AWO facilities are in Berlin?"

### Search by City

> "Show me all AWO facilities in Berlin with their addresses"

### Get Facility Details

> "Tell me about AWO Sozialstation Wedding"

### Search Services

> "Find AWO services related to addiction counseling"

### Get Statistics

> "Show me statistics about AWO facilities"

### Data Quality

> "Check data completeness for AWO records"

### Find Duplicates

> "Are there any duplicates in the AWO datasets?"

### Compare Facilities

> "Compare AWO Mitte and AWO Spree-Wuhle"

---

## Data Overview

The server uses four CSV datasets:

| Dataset                 | Description             | Count |
| ----------------------- | ----------------------- | ----- |
| `einrichtungSchema.csv` | AWO facilities          | 168   |
| `adresseSchema.csv`     | Addresses               | 108   |
| `angebotSchema.csv`     | Services                | 99    |
| `traegerSchema.csv`     | Providers/Organizations | 4     |

---

## File Structure

```text
awo-mcp-production/
├── data/                      # CSV datasets
│   ├── einrichtungSchema.csv
│   ├── adresseSchema.csv
│   ├── angebotSchema.csv
│   └── traegerSchema.csv
├── src/                       # Core modules
│   ├── data_loader.py
│   └── data_repository.py
├── server.py                  # MCP server
├── requirements.txt
└── README.md
```

---

## Testing

### Test the Server

```bash
python -c "from server import mcp; print('✅ Server loaded successfully')"
```

### Run the Client (Optional)

If you have `client.py` for interactive testing:

```bash
python client.py
```

---

## Deployment

### Local Development

* Run `python server.py` directly.
* Connect Claude Desktop to the local server.

### Cloud Deployment

* Deploy to a cloud VM or container.
* Configure Claude Desktop to use a remote endpoint when supported.

---
## Demo with Claude Desktop

Here a video of the demo with Claude Desktop:

![AWO MCP Demo with Claude Desktop](assets/awo_mcp_claude_demo.gif)

## Troubleshooting

### Server Not Showing in Claude Desktop

* Check the JSON syntax in the configuration file.
* Make sure there are no trailing commas.
* Verify that the Python path exists.
* Check Claude logs at:

```text
%APPDATA%\Claude\logs\mcp*.log
```

### Server Fails to Start

* Ensure all dependencies are installed.
* Verify the `data/` folder exists with the required CSV files.
* Run the server manually to see any errors:

```bash
python server.py
```

---

---

## Federated Welfare Directory MCP Server

A second MCP server in this repo (`federated_server.py`) that queries the [Föderierter Datenpool](https://sosuse.correlaid.org) — a federated pool of German welfare data from Caritas, AWO, DHS, Sozialplattform, and Destatis (~37,000 facilities).

Unlike the AWO server which reads local CSV files, this server queries a live public SPARQL endpoint and requires no local data files.

### Install dependencies

```bash
pip install -r requirements.txt
```

### Connect to Claude Code

```bash
claude mcp add federated-welfare python3 /path/to/awo-mcp-production/federated_server.py
```

### Connect to Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "federated-welfare": {
      "command": "python3",
      "args": ["/path/to/awo-mcp-production/federated_server.py"]
    }
  }
}
```

Restart Claude Desktop after saving.

### Example queries

**Find facilities by city**
> "How many welfare facilities are in Berlin?"
> "Show me welfare facilities in Hamburg"

**Get facility details**
> "Tell me about AWO Pflegegesellschaft"
> "Find facilities in postal code 10115"

**Search services**
> "Find services related to Suchtberatung"
> "What services are available for Senioren?"
> "Find services for Kinder und Jugendliche"

**Compare facilities**
> "Compare AWO Mitte and Caritas Berlin"

**Providers and statistics**
> "List all provider organisations in the directory"
> "Give me statistics about the welfare directory"

### Configuration

Copy `.env.example` to `.env` to override defaults:

```
SPARQL_ENDPOINT=https://sosuse.correlaid.org/directory/sparql
CACHE_TTL=300
LOG_LEVEL=INFO
```

---

## License

MIT License

---

## Contributing

1. Fork the repository.
2. Create a feature branch.
3. Commit your changes.
4. Push to the branch.
5. Open a Pull Request.

---
