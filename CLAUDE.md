# CLAUDE.md

Video stream ripper for Telia TV and Go3 (Widevine DRM).

## Setup
```bash
uv venv && uv sync
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
uv run ruff check . --fix --unsafe-fixes && uv run ruff format .  # lint
uv run ty check                                                    # type check
python telia_ripper.py                                             # run
```

## Flow
1. Detect service from URL -> get stream info from API
2. Extract PSSH from MPD (or use env fallback)
3. Download encrypted -> get key from CDRM Project API -> decrypt -> mux
4. Non-DRM streams: download + mux directly

## Files
`{title}.mp4/.m4a` -> `{title}-dec.mp4/.m4a` -> `{title}-final.mp4`
