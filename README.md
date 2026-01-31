# ePaper Google Calendar (toy project)

Goal: show Google Calendar events on Waveshare 7.5" e-paper (Raspberry Pi).

## Files
- `cal_google.py`: main script (pulled from Pi)

## Setup (high level)
1. Install deps (Pillow, Google API client libs).
2. Create `credentials/oauth_config.json` with your Google OAuth client id/secret.
3. Run `cal_google.py` once to generate `credentials/token.json`.

> Do **not** commit credentials or token files.
