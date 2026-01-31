"""HTTP server to render calendar/weather to the e-paper display.

Run (on Pi):
  python3 -m venv --system-site-packages .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  uvicorn pi_calendar_server:app --host 0.0.0.0 --port 8088

This server assumes Google OAuth token already exists at:
  ./credentials/token.json

Use `python pi_calendar.py auth` once to generate it.
"""

from __future__ import annotations

import os
from fastapi import FastAPI, HTTPException

import pi_calendar

app = FastAPI(title="pi-calendar", version="0.1.0")


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/render/month")
def render_month(month: int | None = None, year: int | None = None):
    try:
        pi_calendar.render_month(year=year, month=month)
        return {"ok": True, "mode": "month", "year": year, "month": month}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/render/week")
def render_week(which: str = "this"):
    if which not in ("this", "next"):
        raise HTTPException(status_code=400, detail="which must be 'this' or 'next'")
    try:
        pi_calendar.render_week(which=which)
        return {"ok": True, "mode": "week", "which": which}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/render/weather/week")
def render_weather_week():
    try:
        pi_calendar.render_weather_week()
        return {"ok": True, "mode": "weather_week"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/render/weather/hourly")
def render_weather_hourly(day: str = "today"):
    if day not in ("today", "tomorrow"):
        raise HTTPException(status_code=400, detail="day must be 'today' or 'tomorrow'")
    try:
        pi_calendar.render_weather_hourly(day=day)
        return {"ok": True, "mode": "weather_hourly", "day": day}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
