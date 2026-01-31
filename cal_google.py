# -*- coding:utf-8 -*-
import sys
import os
import calendar

picdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic')
libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'lib')
if os.path.exists(libdir):
    sys.path.append(libdir)

import logging
from datetime import datetime
from waveshare_epd import epd7in5b_V2
import time
from PIL import Image, ImageDraw, ImageFont

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import json


# Google Calendar API 설정
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
CREDENTIALS_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'credentials')


def get_google_credentials():
    """OAuth2 인증 처리 및 credentials 반환"""
    token_path = os.path.join(CREDENTIALS_DIR, 'token.json')
    config_path = os.path.join(CREDENTIALS_DIR, 'oauth_config.json')

    creds = None

    # 저장된 토큰이 있으면 로드
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    # 유효한 credentials가 없으면 새로 인증
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # oauth_config.json에서 client_id, client_secret 읽기
            if not os.path.exists(config_path):
                raise FileNotFoundError(
                    f"OAuth 설정 파일이 없습니다: {config_path}\n"
                    "다음 형식으로 생성해주세요:\n"
                    '{"client_id": "YOUR_CLIENT_ID", "client_secret": "YOUR_CLIENT_SECRET"}'
                )

            with open(config_path, 'r') as f:
                config = json.load(f)

            client_config = {
                "installed": {
                    "client_id": config['client_id'],
                    "client_secret": config['client_secret'],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"]
                }
            }

            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            creds = flow.run_local_server(port=0)

        # 토큰 저장
        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    return creds


def get_google_calendar_events(year, month):
    """Google Calendar에서 해당 월의 일정을 가져옴"""
    try:
        creds = get_google_credentials()
        service = build('calendar', 'v3', credentials=creds)

        # 해당 월의 시작/끝 날짜
        start_date = f"{year}-{month:02d}-01T00:00:00Z"
        if month == 12:
            end_date = f"{year+1}-01-01T00:00:00Z"
        else:
            end_date = f"{year}-{month+1:02d}-01T00:00:00Z"

        events_by_day = {}

        # 모든 캘린더 목록 가져오기
        calendar_list = service.calendarList().list().execute()

        for cal in calendar_list.get('items', []):
            cal_id = cal['id']
            events = service.events().list(
                calendarId=cal_id,
                timeMin=start_date,
                timeMax=end_date,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            for event in events.get('items', []):
                start = event['start'].get('dateTime', event['start'].get('date'))
                day = int(start[8:10])  # YYYY-MM-DD에서 일 추출
                title = event.get('summary', 'No Title')[:15]  # 15자로 제한

                if day not in events_by_day:
                    events_by_day[day] = []
                if title not in events_by_day[day]:  # 중복 방지
                    events_by_day[day].append(title)

        return events_by_day

    except FileNotFoundError as e:
        logging.warning(f"OAuth 설정 파일 오류: {e}")
        return {}
    except Exception as e:
        logging.error(f"Google Calendar 일정 가져오기 실패: {e}")
        return {}

logging.basicConfig(level=logging.DEBUG)

# 현재 날짜 기준으로 연도와 월 설정
now = datetime.now()
YEAR = now.year
MONTH = now.month
WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토']

try:
    logging.info(f"Calendar Demo - {YEAR}년 {MONTH}월")

    epd = epd7in5b_V2.EPD()
    logging.info("init and Clear")
    epd.init()
    epd.Clear()

    font_weekday = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 18)
    font_day = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 20)
    font_schedule = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 12)

    Himage = Image.new('1', (epd.width, epd.height), 255)
    Rimage = Image.new('1', (epd.width, epd.height), 255)

    draw_black = ImageDraw.Draw(Himage)
    draw_red = ImageDraw.Draw(Rimage)

    margin_x = 20
    margin_y = 5
    cell_width = (epd.width - 2 * margin_x) // 7
    cell_height = 87
    weekday_height = 25

    weekday_y = margin_y
    for i, day in enumerate(WEEKDAYS):
        x = margin_x + i * cell_width + (cell_width - draw_black.textbbox((0, 0), day, font=font_weekday)[2]) // 2
        if i == 0 or i == 6:  # 일요일, 토요일 빨간색
            draw_red.text((x, weekday_y), day, font=font_weekday, fill=0)
        else:
            draw_black.text((x, weekday_y), day, font=font_weekday, fill=0)

    line_y = weekday_y + weekday_height
    draw_black.line((margin_x, line_y, epd.width - margin_x, line_y), fill=0, width=2)

    cal = calendar.Calendar(firstweekday=6)
    month_days = cal.monthdayscalendar(YEAR, MONTH)

    start_y = line_y + 2
    for week_num, week in enumerate(month_days):
        for day_num, day in enumerate(week):
            if day != 0:
                day_str = str(day)

                # 날짜를 셀 왼쪽 상단에 배치 (스케줄 공간 확보)
                x = margin_x + day_num * cell_width + 3
                y = start_y + week_num * cell_height + 2

                if day_num == 0 or day_num == 6:  # 일요일, 토요일 빨간색
                    draw_red.text((x, y), day_str, font=font_day, fill=0)
                else:
                    draw_black.text((x, y), day_str, font=font_day, fill=0)

    grid_start_y = line_y
    grid_end_y = line_y + len(month_days) * cell_height

    for i in range(8):
        x = margin_x + i * cell_width
        draw_black.line((x, grid_start_y, x, grid_end_y), fill=0)

    for i in range(len(month_days) + 1):
        y = line_y + i * cell_height
        draw_black.line((margin_x, y, epd.width - margin_x, y), fill=0)

    # Google Calendar에서 일정 가져오기
    schedules = get_google_calendar_events(YEAR, MONTH)

    # 스케줄 그리기
    for day, texts in schedules.items():
        for week_num, week in enumerate(month_days):
            if day in week:
                day_num = week.index(day)
                x = margin_x + day_num * cell_width + 3
                y = line_y + week_num * cell_height + 24
                for i, text in enumerate(texts[:3]):  # 최대 3개까지 표시
                    draw_black.text((x, y + i * 14), text, font=font_schedule, fill=0)
                break

    logging.info("Displaying calendar...")
    epd.display(epd.getbuffer(Himage), epd.getbuffer(Rimage))
    time.sleep(2)

    logging.info("Goto Sleep...")
    epd.sleep()

except IOError as e:
    logging.info(e)

except KeyboardInterrupt:
    logging.info("ctrl + c:")
    epd7in5b_V2.epdconfig.module_exit(cleanup=True)
    exit()
