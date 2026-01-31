# ePaper Google Calendar (toy project)

Goal: show Google Calendar events on a Waveshare 7.5" e-paper (Raspberry Pi).

This repo currently mirrors `cal_google.py` from the device.

## Files
- `cal_google.py`: main script
- `requirements.txt`: minimal deps
- `requirements-freeze.txt`: full `pip freeze` snapshot from the Pi (for reference)

## Setup (Raspberry Pi)
From the repo folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

### Google OAuth config
Create:
- `credentials/oauth_config.json`

Format:
```json
{
  "client_id": "YOUR_CLIENT_ID",
  "client_secret": "YOUR_CLIENT_SECRET"
}
```

Then run once to generate `credentials/token.json`:
```bash
python3 cal_google.py
```

## Notes
- E-paper driver used in code: `waveshare_epd.epd7in5b_V2`
- **Do not commit** `credentials/`, `oauth_config.json`, or `token.json` (repo `.gitignore` blocks these).
