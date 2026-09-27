# Third-party software

garmin-coach-mcp is released under the [MIT License](LICENSE). It builds on the following open-source
projects, each distributed under its own license. Many thanks to their authors and maintainers.

## Direct dependencies (installed in the Docker image)

| Project | Used for | License |
|---|---|---|
| [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) by Ron Klinkien (cyberjunky) | Garmin Connect login and API access (activities, FIT download, workouts, calendar) | MIT |
| [fitdecode](https://github.com/polyvertex/fitdecode) by Jean-Charles Lefebvre (polyvertex) | Parsing of the original FIT files (laps, per-second records, running dynamics) | MIT |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) by Anthropic, PBC and contributors | MCP server (FastMCP, streamable HTTP transport) | MIT |
| [Uvicorn](https://github.com/encode/uvicorn) by Encode OSS Ltd. | ASGI web server | BSD-3-Clause |

## Notable transitive dependencies

Installed automatically by the packages above.

| Project | Pulled in by | License |
|---|---|---|
| [curl_cffi](https://github.com/lexiforest/curl_cffi) | python-garminconnect | MIT |
| [Requests](https://github.com/psf/requests) | python-garminconnect | Apache-2.0 |
| [ua-generator](https://github.com/iamdual/ua-generator) | python-garminconnect | Apache-2.0 |
| [Pydantic](https://github.com/pydantic/pydantic) | MCP Python SDK | MIT |
| [Starlette](https://github.com/encode/starlette) | MCP Python SDK | BSD-3-Clause |

## Used on the client side (not bundled)

| Project | Used for | License |
|---|---|---|
| [mcp-remote](https://github.com/geelen/mcp-remote) by Glen Maddern (geelen) | Bridge between Claude Desktop and the remote MCP server (run via `npx`) | MIT |
| [Node.js](https://nodejs.org) | Runtime for `npx` / mcp-remote | MIT |

## Runtime

| Project | Used for | License |
|---|---|---|
| [Python](https://www.python.org) (`python:3.12-slim` Docker image) | Runtime | PSF License (image also contains Debian packages under their own licenses) |
| [SQLite](https://sqlite.org) | Local database | Public domain |

## Trademarks

Garmin, Garmin Connect and Forerunner are trademarks of Garmin Ltd. or its subsidiaries.
Claude is a trademark of Anthropic, PBC. This project is not affiliated with, endorsed by or
sponsored by Garmin or Anthropic.

The full license texts are included in each package's distribution and in its repository.
