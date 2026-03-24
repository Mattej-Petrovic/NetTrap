# NetTrap

NetTrap is a desktop honeypot monitor built with PyQt6. It runs fake SSH and HTTP services, stores activity in SQLite and JSONL, and provides a GUI for live monitoring, session analysis, analytics, map visualization, settings, and export.

Platform note: NetTrap is primarily intended and tested for Windows desktop use (including the packaged release flow). Linux support is possible from source but is not the primary target in this repository.

## Key Features

- PyQt6 desktop UI with Dashboard, Live Map, Sessions, Analytics, Settings, and Export views
- Fake SSH honeypot (Paramiko) with credential-attempt capture
- Fake HTTP honeypot (aiohttp) with realistic login decoy pages and request logging
- SQLite storage (WAL mode) for sessions/events/alerts
- JSONL append-only event logs for audit-friendly raw capture
- GeoIP enrichment with Leaflet map markers in `QWebEngineView`
- Runtime controls for Start All / Stop All, service bind host/port, and service fingerprints
- JSON and CSV export with date/service filters

## Screenshots
<img width="1395" height="928" alt="1" src="https://github.com/user-attachments/assets/bbee9e5a-f5b9-4f74-9537-9b3e8baf148d" />

<img width="1386" height="916" alt="2" src="https://github.com/user-attachments/assets/5cc5d47d-8212-4aba-accd-847edbb36fb8" />

<img width="1403" height="921" alt="3" src="https://github.com/user-attachments/assets/cc49ad69-07e9-4480-b239-c77a1ea182a1" />

<img width="1389" height="924" alt="4" src="https://github.com/user-attachments/assets/e5512305-e40b-446d-abd0-2b86efa1ca7f" />

<img width="1390" height="925" alt="5" src="https://github.com/user-attachments/assets/f39d71e3-7ba8-4735-8887-28005e7a0782" />

<img width="1388" height="921" alt="6" src="https://github.com/user-attachments/assets/ca00f3dd-2bb5-456f-8470-c2ed0285f15d" />


## GeoIP Database (`GeoLite2-City.mmdb`)

NetTrap uses MaxMind GeoLite2 City for IP geolocation enrichment.

- Default path: `data/GeoLite2-City.mmdb`
- You can change this in `config.yaml` or in **Settings -> GeoIP**
- If missing, NetTrap still runs, but geo-enrichment and map location markers are limited/unavailable

## Configuration (`config.yaml`)

`config.yaml` controls service, GUI, storage, and export defaults.

Important notes:

- If `config.yaml` is missing, NetTrap recreates it from built-in defaults.
- Default bind host is `127.0.0.1` (safe local default).
- Use `0.0.0.0` only when you intentionally want exposure on all interfaces.

Main sections:

- `services.ssh`: enabled, host, port, banner
- `services.http`: enabled, host, port, `server_header`, page profile, proxy header trust options
- `database.path`: SQLite DB path
- `logging.json_dir`: JSONL log directory
- `geoip.database_path`: GeoLite2 DB path
- `gui`: refresh rate and feed size
- `export`: default format and output directory

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
