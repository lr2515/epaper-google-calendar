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


def _to_rfc3339_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def get_google_calendar_events_range(
    start: datetime, end: datetime
) -> list[tuple[datetime, str]]:
    """Return flat list of (start_datetime_local, title) between [start, end)."""
    creds = get_google_credentials(interactive=False)
    service = build("calendar", "v3", credentials=creds)

    time_min = _to_rfc3339_z(start)
    time_max = _to_rfc3339_z(end)

    items: list[tuple[datetime, str]] = []

    calendar_list = service.calendarList().list().execute()
    for cal in calendar_list.get("items", []):
        cal_id = cal["id"]
        events = (
            service.events()
            .list(
                calendarId=cal_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        for event in events.get("items", []):
            title = (event.get("summary") or "No Title").strip()

            # dateTime => timed event; date => all-day
            start_raw = event.get("start", {}).get("dateTime")
            if start_raw:
                try:
                    dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00")).astimezone()
                except Exception:
                    continue
                label = f"{dt.strftime('%H:%M')} {title}"
                items.append((dt, label))
            else:
                date_raw = event.get("start", {}).get("date")
                if not date_raw:
                    continue
                # Treat all-day as local midnight
                try:
                    dt = datetime.fromisoformat(date_raw).replace(tzinfo=timezone.utc).astimezone()
                except Exception:
                    continue
                label = f"(종일) {title}"
                items.append((dt, label))

    # de-dupe and sort
    uniq = list({(d.isoformat(), t): (d, t) for d, t in items}.values())
    uniq.sort(key=lambda x: x[0])
    return uniq


def get_google_calendar_events(year: int, month: int) -> dict[int, list[str]]:
    start = datetime(year, month, 1, tzinfo=timezone.utc).astimezone()
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc).astimezone()
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc).astimezone()

    events_by_day: dict[int, list[str]] = {}
    for dt, label in get_google_calendar_events_range(start, end):
        day = dt.day
        title = label[:18]
        events_by_day.setdefault(day, [])
        if title not in events_by_day[day]:
            events_by_day[day].append(title)

    return events_by_day




def auth_device_flow():
    """Headless OAuth using OAuth 2.0 Device Authorization Grant.

    This avoids redirect_uri/local browser issues on Raspberry Pi.
    """
    os.makedirs(CREDENTIALS_DIR, exist_ok=True)
    config_path = os.path.join(CREDENTIALS_DIR, 'oauth_config.json')
    if not os.path.exists(config_path):
        raise FileNotFoundError(f'Missing {config_path}')

    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    client_id = config['client_id']
    client_secret = config['client_secret']

    device_code_url = 'https://oauth2.googleapis.com/device/code'
    token_url = 'https://oauth2.googleapis.com/token'

    r = requests.post(
        device_code_url,
        data={
            'client_id': client_id,
            'scope': ' '.join(SCOPES),
        },
        timeout=20,
    )
    r.raise_for_status()
    dc = r.json()

    verification_url = dc.get('verification_url') or dc.get('verification_uri')
    user_code = dc['user_code']
    device_code = dc['device_code']
    interval = int(dc.get('interval', 5))
    expires_in = int(dc.get('expires_in', 1800))

    print('\n[Google OAuth - Device Flow]')
    print('Open this URL on your phone/PC:')
    print(verification_url)
    print('Enter this code:')
    print(user_code)
    print('\nWaiting for authorization...')

    import time
    deadline = time.time() + expires_in
    last_err = None

    while time.time() < deadline:
        tr = requests.post(
            token_url,
            data={
                'client_id': client_id,
                'client_secret': client_secret,
                'device_code': device_code,
                'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
            },
            timeout=20,
        )

        if tr.status_code == 200:
            tok = tr.json()
            token_json = {
                'client_id': client_id,
                'client_secret': client_secret,
                'token_uri': token_url,
                'scopes': SCOPES,
                'token': tok.get('access_token'),
                'refresh_token': tok.get('refresh_token'),
            }
            out_path = os.path.join(CREDENTIALS_DIR, 'token.json')
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(token_json, f, ensure_ascii=False, indent=2)
            print(f'\nAuth OK. Wrote: {out_path}')
            return

        try:
            err = tr.json().get('error')
        except Exception:
            err = tr.text
        last_err = err

        if err == 'authorization_pending':
            time.sleep(interval)
            continue
        if err == 'slow_down':
            interval += 2
            time.sleep(interval)
            continue
        raise RuntimeError(f'OAuth failed: {err} ({tr.text})')

    raise RuntimeError(f'OAuth timed out. Last error: {last_err}')
def auth():
    # Prefer device flow for headless Raspberry Pi
    auth_device_flow()


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

            max_w = cell_width - 8

            def _clean_event(t: str) -> str:
                t = (t or "").replace("(종일)", "").strip()
                # remove leading time like '17:00 '
                t = re.sub(r"^\d{1,2}:\d{2}\s*", "", t)
                return t.strip()

            def _truncate(draw_obj, font_obj, text: str, width: int) -> str:
                if not text:
                    return ""
                # fast path
                try:
                    if draw_obj.textlength(text, font=font_obj) <= width:
                        return text
                except Exception:
                    pass
                ell = "…"
                lo, hi = 0, len(text)
                best = ""
                while lo <= hi:
                    mid = (lo + hi) // 2
                    cand = text[:mid] + ell
                    try:
                        ok = draw_obj.textlength(cand, font=font_obj) <= width
                    except Exception:
                        # fallback: rough char count
                        ok = len(cand) <= max(1, width // 7)
                    if ok:
                        best = cand
                        lo = mid + 1
                    else:
                        hi = mid - 1
                return best or ell

            lines = []
            for t in texts:
                ct = _clean_event(t)
                if not ct:
                    continue
                lines.append(_truncate(draw_black, font_schedule, ct, max_w))
                if len(lines) >= 3:
                    break

            for i, line in enumerate(lines):
                draw_black.text((x0, y0 + i * 14), line, font=font_schedule, fill=0)

    epd.display(epd.getbuffer(Himage), epd.getbuffer(Rimage))
    epd.sleep()


def _openweather_forecast_5d_3h():
    """Free forecast API (5 days / 3-hour steps)."""
    api_key = os.environ.get("OPENWEATHER_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENWEATHER_API_KEY env var")

    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {
        "lat": SEOUL_LAT,
        "lon": SEOUL_LON,
        "appid": api_key,
        "units": "metric",
        "lang": "kr",
    }
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def render_weather_week():
    """Render a simple 5-day forecast (free tier)."""
    logging.info("Render weather week (5-day forecast)")
    data = _openweather_forecast_5d_3h()
    rows = data.get("list", [])

    # Group into local dates
    by_date: dict[str, list[dict]] = {}
    for r in rows:
        dt = datetime.fromtimestamp(r["dt"], tz=timezone.utc).astimezone()
        k = dt.strftime("%m/%d(%a)")
        by_date.setdefault(k, []).append(r)

    # Keep first 5 dates
    dates = list(by_date.keys())[:5]

    epd = _epd_init()
    font_path = os.path.join(PICDIR, "Font.ttc")
    font_title = _font(font_path, 26)
    font_line = _font(font_path, 18)

    Himage = Image.new("1", (epd.width, epd.height), 255)
    draw = ImageDraw.Draw(Himage)

    draw.text((20, 10), "서울 5일 예보", font=font_title, fill=0)

    y = 55
    for k in dates:
        day_rows = by_date[k]
        temps = [x.get("main", {}).get("temp") for x in day_rows]
        temps = [t for t in temps if isinstance(t, (int, float))]
        tmin = min(temps) if temps else None
        tmax = max(temps) if temps else None

        # pick most frequent description
        descs = [((x.get("weather") or [{}])[0].get("description") or "") for x in day_rows]
        descs = [d for d in descs if d]
        w = max(set(descs), key=descs.count) if descs else ""

        if tmin is None or tmax is None:
            line = f"{k}  {w}"
        else:
            line = f"{k}  {tmin:.0f}~{tmax:.0f}°C  {w}"

        draw.text((20, y), line[:40], font=font_line, fill=0)
        y += 28

    epd.display(epd.getbuffer(Himage), epd.getbuffer(Himage))
    epd.sleep()


def render_weather_hourly(day: str = "today"):
    """Render hourly forecast using free 5d/3h endpoint (shows 3-hour steps)."""
    logging.info("Render weather hourly: %s", day)
    data = _openweather_forecast_5d_3h()
    rows = data.get("list", [])

    now = datetime.now().astimezone()
    start = now.replace(minute=0, second=0, microsecond=0)
    if day == "tomorrow":
        start = (start + timedelta(days=1)).replace(hour=0)
    end = start + timedelta(hours=24)

    pts = []
    for r in rows:
        t = datetime.fromtimestamp(r["dt"], tz=timezone.utc).astimezone()
        if not (start <= t < end):
            continue
        temp = r.get("main", {}).get("temp")
        w = (r.get("weather") or [{}])[0].get("description", "")
        pts.append((t, temp, w))

    # already 3-hour steps; show first 8
    pts = pts[:8]

    epd = _epd_init()
    font_path = os.path.join(PICDIR, "Font.ttc")
    font_title = _font(font_path, 26)
    font_line = _font(font_path, 18)

    Himage = Image.new("1", (epd.width, epd.height), 255)
    draw = ImageDraw.Draw(Himage)

    title = "서울 오늘 시간별(3시간)" if day == "today" else "서울 내일 시간별(3시간)"
    draw.text((20, 10), title, font=font_title, fill=0)

    y = 60
    for t, temp, w in pts:
        if not isinstance(temp, (int, float)):
            continue
        line = f"{t.strftime('%H:%M')}  {temp:.0f}°C  {w}"
        draw.text((20, y), line[:40], font=font_line, fill=0)
        y += 30

    epd.display(epd.getbuffer(Himage), epd.getbuffer(Himage))
    epd.sleep()


def render_week(which: str = "this"):
    """Render a simple agenda for this week (Mon-Sun) or next week."""
    now = datetime.now().astimezone()
    # Monday 00:00 local
    this_monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start = this_monday if which == "this" else (this_monday + timedelta(days=7))
    end = start + timedelta(days=7)

    logging.info("Render week agenda: %s (%s..%s)", which, start.date(), end.date())

    try:
        items = get_google_calendar_events_range(start, end)
    except Exception as e:
        logging.error("Google Calendar fetch failed: %s", e)
        items = []

    epd = _epd_init()
    font_path = os.path.join(PICDIR, "Font.ttc")
    font_title = _font(font_path, 26)
    font_day = _font(font_path, 20)
    font_line = _font(font_path, 16)

    Himage = Image.new("1", (epd.width, epd.height), 255)
    draw = ImageDraw.Draw(Himage)

    title = "이번주 일정" if which == "this" else "다음주 일정"
    draw.text((20, 8), f"{title} ({start.strftime('%m/%d')}~{(end - timedelta(days=1)).strftime('%m/%d')})", font=font_title, fill=0)

    y = 50
    max_y = epd.height - 10

    # Group by date
    by_date: dict[str, list[str]] = {}
    for dt, label in items:
        k = dt.strftime("%m/%d(%a)")
        by_date.setdefault(k, [])
        by_date[k].append(label)

    # Ensure all days appear even if empty
    days = [(start + timedelta(days=i)).strftime("%m/%d(%a)") for i in range(7)]

    for d in days:
        if y >= max_y:
            break
        draw.text((20, y), d, font=font_day, fill=0)
        y += 24
        lines = by_date.get(d) or ["(일정 없음)"]
        for line in lines[:4]:
            if y >= max_y:
                break
            draw.text((40, y), line[:44], font=font_line, fill=0)
            y += 20
        y += 6

    epd.display(epd.getbuffer(Himage), epd.getbuffer(Himage))
    epd.sleep()




def render_week_with_weather(which: str = "this"):
    """Render rolling 7-day agenda + weather on 7.5" 800x480 (B/W/R).

    - Left: schedule
    - Right: weather (narrower column)

    Colors
    - Black: grid + most text
    - Red: title + today's row

    Text rules
    - Remove '(종일)', '(일정 없음)', '(예보 없음)' (display blank instead)
    - Weekday: Korean (일,월,화,수,목,금,토)
    """

    now = datetime.now().astimezone()
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = today0 if which == "this" else (today0 + timedelta(days=7))
    end = start + timedelta(days=7)

    logging.info("Render 7d+weather: %s (%s..%s)", which, start.date(), end.date())

    # Events
    try:
        items = get_google_calendar_events_range(start, end)
    except Exception as e:
        logging.error("Google Calendar fetch failed: %s", e)
        items = []

    events_by_date: dict[date, list[str]] = {}
    for dt, label in items:
        d = dt.date()
        events_by_date.setdefault(d, []).append(label)

    # Weather (best-effort)
    weather_by_date: dict[date, tuple[int | None, int | None, str]] = {}
    try:
        data = _openweather_forecast_5d_3h()
        rows = data.get("list", [])
        tmp: dict[date, list[dict]] = {}
        for r in rows:
            dt = datetime.fromtimestamp(r["dt"], tz=timezone.utc).astimezone()
            tmp.setdefault(dt.date(), []).append(r)

        for i in range(7):
            d = (start + timedelta(days=i)).date()
            day_rows = tmp.get(d) or []
            temps = [x.get("main", {}).get("temp") for x in day_rows]
            temps = [t for t in temps if isinstance(t, (int, float))]
            tmin = int(min(temps)) if temps else None
            tmax = int(max(temps)) if temps else None

            descs = [((x.get("weather") or [{}])[0].get("description") or "") for x in day_rows]
            descs = [dsc for dsc in descs if dsc]
            desc = (max(set(descs), key=descs.count) if descs else "")
            weather_by_date[d] = (tmin, tmax, desc)
    except Exception as e:
        logging.warning("Weather fetch failed: %s", e)

    epd = _epd_init()
    W, H = epd.width, epd.height

    font_path = os.path.join(PICDIR, "Font.ttc")
    font_title = _font(font_path, 30)
    font_col = _font(font_path, 24)
    font_day = _font(font_path, 24)
    font_event = _font(font_path, 24)
    font_weather = _font(font_path, 24)

    # Two buffers: black + red
    Himage = Image.new("1", (W, H), 255)  # black layer
    Rimage = Image.new("1", (W, H), 255)  # red layer
    draw = ImageDraw.Draw(Himage)
    draw_r = ImageDraw.Draw(Rimage)

    # Layout constants
    margin = 10
    title_h = 52
    split_x = int(W * 0.72)  # make weather column narrower
    content_top = margin + title_h

    # Outer border (black)
    draw.rectangle((0, 0, W - 1, H - 1), outline=0, width=2)

    # Title (red)
    title = "7일" if which == "this" else "다음 7일"
    draw_r.text(
        (margin, margin),
        f"{title} 일정 + 날씨  ({start.strftime('%m/%d')}~{(end - timedelta(days=1)).strftime('%m/%d')})",
        font=font_title,
        fill=0,
    )
    draw.line((0, content_top, W, content_top), fill=0, width=2)

    # Vertical split line
    draw.line((split_x, content_top, split_x, H), fill=0, width=2)

    # Column headers (black)
    draw.text((margin, content_top + 10), "세부일정", font=font_col, fill=0)
    draw.text((split_x + margin, content_top + 10), "날씨", font=font_col, fill=0)
    header_line_y = content_top + 44
    draw.line((0, header_line_y, W, header_line_y), fill=0, width=1)

    row_top = header_line_y
    row_h = (H - row_top - margin) // 7

    kor_days = ["월", "화", "수", "목", "금", "토", "일"]
    today_date = now.date()

    for i in range(7):
        y0 = row_top + i * row_h
        y1 = row_top + (i + 1) * row_h
        draw.line((0, y1, W, y1), fill=0, width=1)

        d = (start + timedelta(days=i)).date()
        is_today = (d == today_date)

        # weekday in Korean
        wd = kor_days[d.weekday()]
        day_str = f"{d.strftime('%m/%d')}({wd})"

        pen = draw_r if is_today else draw

        # Left: date + 1 event line
        pen.text((margin, y0 + 3), day_str, font=font_day, fill=0)

        ev_lines = events_by_date.get(d) or [""]
        ev = (ev_lines[0] or "").replace("(종일)", "").replace("(일정 없음)", "").strip()
        pen.text((margin + 135, y0 + 3), ev[:32], font=font_event, fill=0)

        # Right: weather
        tmin, tmax, desc = weather_by_date.get(d, (None, None, ""))
        if tmin is None and tmax is None and not desc:
            wline = ""  # remove '(예보 없음)'
        else:
            if tmin is None or tmax is None:
                wline = f"{desc}".strip()
            else:
                wline = f"{tmin}~{tmax}°C {desc}".strip()
        wline = wline.replace("(예보 없음)", "").strip()

        pen.text((split_x + margin, y0 + 3), wline[:18], font=font_weather, fill=0)

    epd.display(epd.getbuffer(Himage), epd.getbuffer(Rimage))
    epd.sleep()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "cmd",
        choices=["auth", "month", "week", "week-next", "week-weather", "week-next-weather"],
        help="auth | month | week | week-next | week-weather | week-next-weather",
    )
    ap.add_argument("--year", type=int)
    ap.add_argument("--month", type=int)
    args = ap.parse_args()

    if args.cmd == "auth":
        auth()
    elif args.cmd == "month":
        render_month(args.year, args.month)
    elif args.cmd == "week":
        render_week("this")
    elif args.cmd == "week-next":
        render_week("next")
    elif args.cmd == "week-weather":
        render_week_with_weather("this")
    elif args.cmd == "week-next-weather":
        render_week_with_weather("next")
