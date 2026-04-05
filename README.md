# ROM Library

A self-hosted web app to manage your ROM collection. Built for the AYN Thor but works with any Android-based handheld.

Paste a download URL, hit enter, done. Files land in the right folder automatically.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![License](https://img.shields.io/badge/license-MIT-blue)

---

## What it does

- **Quick download** — paste a direct URL to any ROM file and it downloads in the background
- **Bulk import** — paste 50 URLs at once, all start downloading simultaneously
- **Auto-detection** — figures out the console from the file extension (`.iso` → PSP/PS1/PS2, `.nds` → DS, etc.)
- **Metadata** — optional IGDB integration pulls cover art, genre, year and description automatically
- **File scanner** — point it at an existing folder and it imports everything it finds
- **Organized folders** — files go into `~/roms/<Console>/` ready to copy to the device

## Supported consoles

| Console | Extensions |
|---------|-----------|
| PSP | `.iso` `.cso` `.pbp` |
| PS Vita | `.vpk` `.pkg` |
| Nintendo DS | `.nds` |
| Nintendo 3DS | `.3ds` `.cia` `.cxi` |
| GBA / GBC / GB | `.gba` `.gbc` `.gb` |
| NES / SNES | `.nes` `.sfc` `.smc` |
| N64 | `.z64` `.n64` `.v64` |
| PS1 | `.bin` `.cue` |
| PS2 | `.iso` |
| GameCube / Wii | `.iso` `.gcm` `.wbfs` |
| Mega Drive | `.md` `.smd` |
| Game Gear | `.gg` |

## Requirements

- Python 3.10+
- Linux / macOS (tested on Ubuntu 24.04)

## Setup

```bash
git clone https://github.com/danimap27/rom-library
cd rom-library
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run.py
```

Open `http://localhost:8083`

### Run as a systemd service

```bash
sudo cp rom-library.service /etc/systemd/system/
sudo systemctl enable --now rom-library
```

Edit `rom-library.service` to point `WorkingDirectory` at your install path.

## Cover art via IGDB (optional)

Create a `.env` file in the project root:

```
IGDB_CLIENT_ID=your_client_id
IGDB_CLIENT_SECRET=your_client_secret
```

Get free credentials at [dev.twitch.tv/console/apps](https://dev.twitch.tv/console/apps). When enabled, adding a game automatically searches IGDB for cover, genre, year and description.

## ROM folder structure

```
~/roms/
├── PSP/
├── PSVita/
├── NintendoDS/
├── Nintendo3DS/
├── GBA/
├── NES/
├── SNES/
└── ...
```

## Cloudflare Tunnel

To expose the app outside your LAN, add this to your tunnel config:

```yaml
- hostname: roms.yourdomain.com
  service: http://localhost:8083
```

## License

MIT
