"""Calendar/weather rendering helpers.

This file is intentionally small and pragmatic (toy project).

Google OAuth:
- Put credentials/oauth_config.json (client_id/client_secret)
- Run: python pi_calendar.py auth
- This generates credentials/token.json

Weather:
- Set env OPENWEATHER_API_KEY
- Uses Seoul (37.5665, 126.9780)

E-paper:
- Expects Waveshare library present at ./lib/waveshare_epd
- Expects Font at ./pic/Font.ttc
"""

from __future__ import annotations

import calendar as py_calendar
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests
from PIL import Image, ImageDraw, ImageFont

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


logging.basicConfig(level=logging.INFO)

# Local paths (repo-relative)
BASEDIR = os.path.dirname(os.path.realpath(__file__))
PICDIR = os.path.join(BASEDIR, "pic")
LIBDIR = os.path.join(BASEDIR, "lib")
CREDENTIALS_DIR = os.path.join(BASEDIR, "credentials")

if os.path.exists(LIBDIR):
    sys.path.append(LIBDIR)

from waveshare_epd import epd7in5b_V2  # type: ignore

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

SEOUL_LAT = 37.5665
SEOUL_LON = 126.9780


def _font(path: str, size: int):
    return ImageFont.truetype(path, size)


def _epd_init():
    epd = epd7in5b_V2.EPD()
    epd.init()
    epd.Clear()
    return epd


def get_google_credentials(interactive: bool = False) -> Credentials:
    """Return credentials, optionally performing interactive auth."""
    os.makedirs(CREDENTIALS_DIR, exist_ok=True)
    token_path = os.path.join(CREDENTIALS_DIR, "token.json")
    config_path = os.path.join(CREDENTIALS_DIR, "oauth_config.json")

    creds: Credentials | None = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        return creds

    if not interactive:
        raise RuntimeError(
            "Google credentials missing/expired. Run 'python pi_calendar.py auth' to authorize once."
        )

    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"OAuth 설정 파일이 없습니다: {config_path}\n"
            "다음 형식으로 생성해주세요:\n"
            '{"client_id": "YOUR_CLIENT_ID", "client_secret": "YOUR_CLIENT_SECRET"}'
        )

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    client_config = {
        "installed": {
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    auth_url, _state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    print("\n[Google OAuth] Open this URL in your browser:\n")
    print(auth_url)
    print("\nPaste the authorization code here:")
    code = input("> ").strip()

    flow.fetch_token(code=code)
    creds = flow.credentials

    with open(token_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    return creds


def get_google_calendar_events(year: int, month: int) -> dict[int, list[str]]:
    creds = get_google_credentials(interactive=False)
    service = build("calendar", "v3", credentials=creds)

    start_date = f"{year}-{month:02d}-01T00:00:00Z"
    end_date = f"{year+1}-01-01T00:00:00Z" if month == 12 else f"{year}-{month+1:02d}-01T00:00:00Z"

    events_by_day: dict[int, list[str]] = {}

    calendar_list = service.calendarList().list().execute()
    for cal in calendar_list.get("items", []):
        cal_id = cal["id"]
        events = (
            service.events()
            .list(
                calendarId=cal_id,
                timeMin=start_date,
                timeMax=end_date,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        for event in events.get("items", []):
            start = event["start"].get("dateTime", event["start"].get("date"))
            day = int(start[8:10])
            title = event.get("summary", "No Title")[:18]

            events_by_day.setdefault(day, [])
            if title not in events_by_day[day]:
                events_by_day[day].append(title)

    return events_by_day


def auth():
    _ = get_google_credentials(interactive=True)
    print("Auth OK. token.json created.")


def render_month(year: int | None = None, month: int | None = None):
    now = datetime.now()
    year = year or now.year
    month = month or now.month

    logging.info("Render month %d-%02d", year, month)

    epd = _epd_init()

    # Fonts
    font_path = os.path.join(PICDIR, "Font.ttc")
    font_weekday = _font(font_path, 18)
    font_day = _font(font_path, 20)
    font_schedule = _font(font_path, 12)

    WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"]

    Himage = Image.new("1", (epd.width, epd.height), 255)
    Rimage = Image.new("1", (epd.width, epd.height), 255)
    draw_black = ImageDraw.Draw(Himage)
    draw_red = ImageDraw.Draw(Rimage)

    margin_x = 20
    margin_y = 5
    cell_width = (epd.width - 2 * margin_x) // 7
    cell_height = 87
    weekday_height = 25

    weekday_y = margin_y
    for i, dayname in enumerate(WEEKDAYS):
        x = margin_x + i * cell_width
        if i == 0 or i == 6:
            draw_red.text((x + 5, weekday_y), dayname, font=font_weekday, fill=0)
        else:
            draw_black.text((x + 5, weekday_y), dayname, font=font_weekday, fill=0)

    line_y = weekday_y + weekday_height
    draw_black.line((margin_x, line_y, epd.width - margin_x, line_y), fill=0, width=2)

    cal = py_calendar.Calendar(firstweekday=6)
    month_days = cal.monthdayscalendar(year, month)

    start_y = line_y + 2
    for week_num, week in enumerate(month_days):
        for day_num, day in enumerate(week):
            if day == 0:
                continue
            day_str = str(day)
            x = margin_x + day_num * cell_width + 3
            y = start_y + week_num * cell_height + 2
            if day_num == 0 or day_num == 6:
                draw_red.text((x, y), day_str, font=font_day, fill=0)
            else:
                draw_black.text((x, y), day_str, font=font_day, fill=0)

    # Grid
    grid_start_y = line_y
    grid_end_y = line_y + len(month_days) * cell_height
    for i in range(8):
        x = margin_x + i * cell_width
        draw_black.line((x, grid_start_y, x, grid_end_y), fill=0)
    for i in range(len(month_days) + 1):
        y = line_y + i * cell_height
        draw_black.line((margin_x, y, epd.width - margin_x, y), fill=0)

    # Events
    try:
        schedules = get_google_calendar_events(year, month)
    except Exception as e:
        logging.error("Google Calendar fetch failed: %s", e)
        schedules = {}

    for day, texts in schedules.items():
        # locate day cell
        for week_num, week in enumerate(month_days):
            if day not in week:
                continue
            day_num = week.index(day)
            x0 = margin_x + day_num * cell_width + 3
            y0 = start_y + week_num * cell_height + 28
            for i, t in enumerate(texts[:4]):
                draw_black.text((x0, y0 + i * 14), t, font=font_schedule, fill=0)

    epd.display(epd.getbuffer(Himage), epd.getbuffer(Rimage))
    epd.sleep()


def _openweather_onecall():
    api_key = os.environ.get("OPENWEATHER_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENWEATHER_API_KEY env var")

    # One Call 3.0 endpoint
    url = "https://api.openweathermap.org/data/3.0/onecall"
    params = {
        "lat": SEOUL_LAT,
        "lon": SEOUL_LON,
        "appid": api_key,
        "units": "metric",
        "lang": "kr",
        "exclude": "minutely",
    }
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def render_weather_week():
    logging.info("Render weather week")
    data = _openweather_onecall()
    daily = data.get("daily", [])[:7]

    epd = _epd_init()
    font_path = os.path.join(PICDIR, "Font.ttc")
    font_title = _font(font_path, 26)
    font_line = _font(font_path, 18)

    Himage = Image.new("1", (epd.width, epd.height), 255)
    draw = ImageDraw.Draw(Himage)

    draw.text((20, 10), "서울 이번주 날씨", font=font_title, fill=0)

    y = 55
    for d in daily:
        dt = datetime.fromtimestamp(d["dt"], tz=timezone.utc).astimezone()
        w = (d.get("weather") or [{}])[0].get("description", "")
        tmin = d.get("temp", {}).get("min")
        tmax = d.get("temp", {}).get("max")
        line = f"{dt.strftime('%a %m/%d')}  {tmin:.0f}~{tmax:.0f}°C  {w}"
        draw.text((20, y), line[:40], font=font_line, fill=0)
        y += 28

    epd.display(epd.getbuffer(Himage), epd.getbuffer(Himage))
    epd.sleep()


def render_weather_hourly(day: str = "today"):
    logging.info("Render weather hourly: %s", day)
    data = _openweather_onecall()
    hourly = data.get("hourly", [])

    # pick hours: today or tomorrow (local)
    now = datetime.now().astimezone()
    start = now.replace(minute=0, second=0, microsecond=0)
    if day == "tomorrow":
        start = (start + timedelta(days=1)).replace(hour=0)
    end = start + timedelta(hours=24)

    rows = []
    for h in hourly:
        t = datetime.fromtimestamp(h["dt"], tz=timezone.utc).astimezone()
        if not (start <= t < end):
            continue
        temp = h.get("temp")
        w = (h.get("weather") or [{}])[0].get("description", "")
        rows.append((t, temp, w))

    # show every 3 hours, first 8 rows
    rows = rows[::3][:8]

    epd = _epd_init()
    font_path = os.path.join(PICDIR, "Font.ttc")
    font_title = _font(font_path, 26)
    font_line = _font(font_path, 18)

    Himage = Image.new("1", (epd.width, epd.height), 255)
    draw = ImageDraw.Draw(Himage)

    title = "서울 오늘 시간별 날씨" if day == "today" else "서울 내일 시간별 날씨"
    draw.text((20, 10), title, font=font_title, fill=0)

    y = 60
    for t, temp, w in rows:
        line = f"{t.strftime('%H:%M')}  {temp:.0f}°C  {w}"
        draw.text((20, y), line[:40], font=font_line, fill=0)
        y += 30

    epd.display(epd.getbuffer(Himage), epd.getbuffer(Himage))
    epd.sleep()


def render_week(which: str = "this"):
    # Placeholder: will implement after OAuth token works reliably.
    raise NotImplementedError("week detail view not implemented yet")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["auth"], help="one-time auth")
    args = ap.parse_args()

    if args.cmd == "auth":
        auth()
