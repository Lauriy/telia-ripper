# GROK.md

Video stream ripper for Telia TV and Go3 (Widevine DRM).

## Setup
```bash
uv venv && uv sync
# Windows: .venv\Scripts\activate
```

## .env
```
URL=https://teliatv.ee/... or https://go3.tv/...
SESSION_ID=<Telia PHPSESSID>
GO3_SESSION_ID=<Go3 JSESSIONID>
PSSH=<fallback if not in MPD>
YTDLP_PATH=...
MP4DECRYPT_PATH=...
FFMPEG_PATH=...
```

## Commands
```bash
ruff check . --fix --unsafe-fixes && ruff format .
python telia_ripper.py
```

## Flow
1. Detect service from URL → get stream info from API
2. Extract PSSH from MPD (or use env fallback)
3. Download encrypted → get key from CDM → decrypt → mux

## Files
`{title}.mp4/.m4a` → `{title}-dec.mp4/.m4a` → `{title}-final.mp4`