# CLAUDE.md

Video stream ripper for Telia TV and Go3 (Widevine DRM).

## Setup
```bash
uv venv && uv sync
```

Decryption needs a Widevine L3 `.wvd` device blob at `WVD_PATH`. See README.md for how to extract one from a rooted Android phone.

## .env
```
URL=https://teliatv.ee/... or https://go3.tv/...
SESSION_ID=<Telia PHPSESSID>
GO3_SESSION_ID=<Go3 JSESSIONID>
WVD_PATH=.wvd/device.wvd  # pywidevine device blob (gitignored)
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
2. Parse PSSH from MPD: prefer inline `<cenc:pssh>`, else build a v0 Widevine PSSH from `cenc:default_KID` on the `mp4protection` ContentProtection (Telia's MPDs omit the inline element)
3. Download encrypted -> get key via local pywidevine + .wvd -> decrypt -> mux
4. Non-DRM streams: download + mux directly

## Telia gotchas
- License POST needs `x-axdrm-message: bWluZ2l0b2tlbg==` (base64 of literal "mingitoken" — Axinom DRM hardcoded placeholder).
- Telia's MPDs omit inline `<cenc:pssh>` and only set `cenc:default_KID` on the mp4protection element. The KID is enough to build a working Widevine PSSH via `pywidevine.PSSH.new()`.

## Files
`{title}.mp4/.m4a` -> `{title}-dec.mp4/.m4a` -> `{title}-final.mp4`
