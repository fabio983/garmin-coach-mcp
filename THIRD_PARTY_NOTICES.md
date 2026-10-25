# Third-party software

garmin-coach-mcp is released under the [MIT License](LICENSE). It builds on the following open-source
projects, each distributed under its own license. Many thanks to their authors and maintainers.

## Direct dependencies (installed in the Docker image)

| Project | Used for | License |
|---|---|---|
| [garmin-connect-personal-api-python](https://github.com/garmin/connect-personal-api-python) by Garmin Ltd. or its subsidiaries | Official Garmin Connect Personal API client: read-only data source (activity search, original FIT download, planned workout link) | Apache-2.0 |
| [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) by Ron Klinkien (cyberjunky) | Optional community module, active only with `ENABLE_GARMINCONNECT=true`: write access (structured workouts, calendar), per-lap grade-adjusted pace, shoes | MIT |
| [fitdecode](https://github.com/polyvertex/fitdecode) by Jean-Charles Lefebvre (polyvertex) | Parsing of the original FIT files (laps, per-second records, running dynamics) | MIT |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) by Anthropic, PBC and contributors | MCP server (FastMCP, streamable HTTP transport) | MIT |
| [Uvicorn](https://github.com/encode/uvicorn) by Encode OSS Ltd. | ASGI web server | BSD-3-Clause |

garmin-connect-personal-api-python is used unmodified, as a dependency installed from PyPI; its Apache-2.0
license text is included in the package distribution.

## Notable transitive dependencies

Installed automatically by the packages above.

| Project | Pulled in by | License |
|---|---|---|
| [curl_cffi](https://github.com/lexiforest/curl_cffi) | python-garminconnect | MIT |
| [Requests](https://github.com/psf/requests) | garmin-connect-personal-api-python, python-garminconnect | Apache-2.0 |
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

## Test fixtures

| File | Source | License |
|---|---|---|
| `tests/sample_run.fit` | `garmin-fenix-5-run.fit` from the [fitdecode](https://github.com/polyvertex/fitdecode) test suite | MIT |

## Trademarks

Garmin, Garmin Connect and Forerunner are trademarks of Garmin Ltd. or its subsidiaries.
Claude is a trademark of Anthropic, PBC. This project is not affiliated with, endorsed by or
sponsored by Garmin or Anthropic.

The full license texts are included in each package's distribution and in its repository.
