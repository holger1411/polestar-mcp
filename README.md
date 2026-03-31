# Polestar MCP Server

An MCP (Model Context Protocol) server that exposes Polestar 2 vehicle data to AI assistants like Claude. Query your car's battery status, vehicle info, and health data through natural conversation.

> **Disclaimer:** This project uses an unofficial, reverse-engineered API and is not affiliated with or endorsed by Polestar. Use at your own risk. The API may change or break at any time.

## Features

- **Battery & Charging Status** — Current charge level, charging state, estimated range, time to full charge
- **Vehicle Information** — Model details, VIN, registration number, software version, performance package
- **Vehicle Health** — Fluid levels, tire pressure warnings, service alerts

## Prerequisites

- Python 3.10+
- A Polestar account with a registered vehicle
- Claude Desktop (or any MCP-compatible client)

## Installation

```bash
# Clone the repository
git clone https://github.com/holger1411/polestar-mcp.git
cd polestar-mcp

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Configuration

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your Polestar account credentials:

```
POLESTAR_USERNAME=your-email@example.com
POLESTAR_PASSWORD=your-password
POLESTAR_VIN=              # Optional: specify VIN if you have multiple vehicles
POLESTAR_LOG_LEVEL=INFO    # Optional: DEBUG, INFO, WARNING, ERROR
```

### Claude Desktop Setup

Add the following to your Claude Desktop configuration (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "polestar-mcp-server": {
      "command": "/path/to/your/venv/bin/python",
      "args": ["-m", "polestar_mcp_server"],
      "env": {
        "POLESTAR_USERNAME": "YOUR_EMAIL",
        "POLESTAR_PASSWORD": "YOUR_PASSWORD",
        "POLESTAR_VIN": "",
        "POLESTAR_LOG_LEVEL": "INFO",
        "PYTHONPATH": "/path/to/polestar-mcp/src"
      }
    }
  }
}
```

## Available Tools

| Tool | Description |
|------|-------------|
| `polestar_get_status` | Current battery level, charging state, range, and odometer reading |
| `polestar_get_vehicle_info` | Static vehicle details (model, VIN, registration, specs) |
| `polestar_get_health` | Vehicle health data (fluid levels, tire warnings, service alerts) |

## Architecture

- **Async-first** — All API calls use `httpx.AsyncClient` for non-blocking I/O
- **OIDC/PKCE Authentication** — Secure OAuth flow against Polestar's identity provider
- **Smart Caching** — TTL-based caching (battery: 3 min, health: 30 min, vehicle info: 24 h)
- **Automatic Token Refresh** — Handles expired tokens and re-authentication transparently
- **Retry Logic** — Handles rate limits (429) and transient server errors (5xx)

## Dashboard

A standalone HTML dashboard (`polestar-dashboard.html`) is included as a visual prototype. It is a static mockup and does not connect to the API.

## License

[MIT](LICENSE)

## Acknowledgments

- Built with [MCP (Model Context Protocol)](https://modelcontextprotocol.io)
- Inspired by [pypolestar](https://github.com/leeyuentuen/pypolestar)
