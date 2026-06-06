# NetTrap

NetTrap is a desktop honeypot monitor built with PyQt6. It runs fake SSH and HTTP services, stores activity in SQLite and JSONL, and provides a GUI for live monitoring, session analysis, analytics, map visualization, settings, and export.

Platform note: NetTrap is primarily intended and tested for Windows desktop use (including the packaged release flow). Linux support is possible from source but is not the primary target in this repository.

## Key Features

- PyQt6 desktop UI with Dashboard, Live Map, Sessions, Analytics, Alerts, Settings, and Export views
- Fake SSH honeypot (Paramiko) — captures password and public key auth attempts with key metadata
- Fake HTTP honeypot (aiohttp) — realistic login decoy pages, 30+ scanned paths covered, captures form and JSON credentials across 19 common field name variants
- All unknown GET paths redirect to the login page instead of returning 404, keeping bots engaged
- AI Threat Analyst — connect your OpenAI, Google Gemini, or Anthropic Claude API key in Settings and get a per-session analysis (actor type, intent, severity, recommendations) with one click in the Sessions view
- Automatic alert engine — fires on brute force (10+ auth attempts), rapid fire (5+ attempts in 30 s), path scanning (15+ distinct HTTP paths), and credential stuffing (same password from 3+ IPs); all visible in the Alerts view
- SQLite storage (WAL mode) for sessions/events/alerts
- JSONL append-only event logs for audit-friendly raw capture
- GeoIP enrichment with Leaflet map markers in `QWebEngineView`
- Runtime controls for Start All / Stop All, service bind host/port, and service fingerprints
- JSON and CSV export with date/service filters

## Screenshots
<img width="1395" height="928" alt="1" src="https://github.com/user-attachments/assets/bbee9e5a-f5b9-4f74-9537-9b3e8baf148d" />


## GeoIP Database (`GeoLite2-City.mmdb`)

NetTrap uses MaxMind GeoLite2 City for IP geolocation enrichment.

- Default path: `data/GeoLite2-City.mmdb`
- You can change this in `config.yaml` or in **Settings -> GeoIP**
- If missing, NetTrap still runs, but geo-enrichment and map location markers are limited/unavailable

## Configuration (`config.yaml`)

`config.yaml` controls service, GUI, storage, and export defaults.

Important notes:

- If `config.yaml` is missing, NetTrap recreates it from built-in defaults.
- Default bind host is `0.0.0.0` (all interfaces). Use `127.0.0.1` for local-only testing.
- Default ports are `2222` (SSH) and `8080` (HTTP) to avoid conflicts with system services. Port-forward your router's external 22/80 to these ports to catch real internet traffic.

Main sections:

- `services.ssh`: enabled, host, port, banner
- `services.http`: enabled, host, port, `server_header`, page profile, proxy header trust options
- `database.path`: SQLite DB path
- `logging.json_dir`: JSONL log directory
- `geoip.database_path`: GeoLite2 DB path
- `gui`: refresh rate and feed size
- `export`: default format and output directory
- `ai`: enabled, provider (`openai` / `gemini` / `claude`), api_key, model (leave blank for provider default)

## Runtime / Packaged File Behavior

At runtime, NetTrap creates and uses local data paths (not source-controlled artifacts):

- `data/nettrap.db`
- `data/logs/*.jsonl`
- `data/ssh_host_key`
- `data/GeoLite2-City.mmdb` (if installed)
- `exports/*`

When packaged, the executable still uses external runtime files (config/database/logs) so settings and captured data persist between launches.

## Run From Source

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Start the app:

```bash
python main.py
```

## Build Windows Release

Use PyInstaller from the project root:

```bash
pyinstaller NetTrap.spec --clean
```

Build output:

- `dist/NetTrap/NetTrap.exe`

## External Traffic Reality Check

Running NetTrap locally does **not** automatically attract internet traffic.

To capture real external activity, the honeypot must be reachable from outside your local machine/network, for example by:

- Router port forwarding to the NetTrap host
- Public cloud/VPS deployment
- Public reverse tunnel setup (configured correctly for incoming traffic)

Without real exposure, you will mostly see local or lab-generated traffic.

## Safety Notes

- Use only on systems and networks you own or are authorized to monitor.
- Do not place production credentials in test login fields.
- Prefer non-privileged ports during development where possible.
- Exposing honeypot ports publicly increases operational risk; isolate the host and monitor it.

## License

MIT. See [LICENSE](LICENSE).
