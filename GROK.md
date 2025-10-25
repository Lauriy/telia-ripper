# GROK.md

This file provides guidance to Grok CLI when working with code in this repository.

## Project Overview

This is a tool for downloading and decrypting video streams from Telia TV and Go3. The main script `telia_ripper.py` handles the complete workflow of extracting content info from URLs, downloading DASH streams, obtaining decryption keys, and producing final MP4 files.

The tool supports:
- Telia TV (Widevine DRM)
- Go3 (Widevine DRM via MPD extraction)

## Environment Setup

The project uses `uv` for Python environment and dependency management:

```bash
# Create virtual environment
uv venv

# Install dependencies
uv sync

# Activate virtual environment (required for all operations)
# Windows: .venv\Scripts\activate
# Unix: source .venv/bin/activate
```

Required environment variables in `.env`:
- `URL`: Content URL (Telia or Go3 format)
- `SESSION_ID`: PHP session ID for Telia authentication
- `GO3_SESSION_ID`: JSESSIONID for Go3 authentication
- `PSSH`: Protection System Specific Header (fallback for manual capture)
- `YTDLP_PATH`: Path to yt-dlp executable
- `MP4DECRYPT_PATH`: Path to mp4decrypt executable
- `FFMPEG_PATH`: Path to ffmpeg executable

## Development Notes

This tool was developed on Windows and uses Windows-specific commands for file operations. The code should work cross-platform, but some debugging used PowerShell scripts.

## Development Commands

```bash
# Lint and auto-fix code issues
ruff check . --fix --unsafe-fixes

# Format code
ruff format .

# Run the main script
python telia_ripper.py
```

## Architecture

### Core Workflow (main function)
1. Detect service (Telia or Go3) from URL
2. Extract content ID and title from URL
3. Get stream information from API (Telia: direct API, Go3: playlist API)
4. Determine if content is DRM-protected
5. For DRM DASH: Extract PSSH from MPD → get decryption key → download → decrypt → mix
6. For non-DRM: Download directly to final file

### Key Functions
- `detect_service()`: Identifies Telia vs Go3 from URL
- `extract_content_info()`: Parses URLs to extract content ID and title
- `get_stream_info()`: Fetches stream URLs (Telia API or Go3 playlist)
- `get_pssh_from_mpd()`: Extracts Widevine PSSH from DASH MPD (follows redirects)
- `get_stream_formats()`: Uses yt-dlp to analyze DASH formats
- `get_decryption_key()`: Gets Widevine keys from CDM service
- `decrypt_files()`: Uses mp4decrypt for decryption
- `mix_files()`: Combines video/audio with ffmpeg

### External Dependencies
- **yt-dlp**: Downloads both DASH (DRM) and HLS (non-DRM) streams
- **mp4decrypt**: Decrypts Widevine-protected content (DRM only)
- **ffmpeg**: Mixes video and audio files (DRM only)
- **CDM service**: External Widevine key server at `108.181.133.95:8080` (DRM only)

### API Integration
- **Telia**: Uses `https://api.teliatv.ee` API with PHPSESSID
- **Go3**: Uses `https://go3.tv` playlist API with JSESSIONID, extracts from JSON response
- Supports Widevine DRM for both services (PSSH from MPD)
- Supports DASH streams with Estonian/English audio tracks

### File Management
For DRM content, the script creates temporary files during processing:
- `{title}.mp4` / `{title}.m4a`: Encrypted downloads
- `{title}-dec.mp4` / `{title}-dec.m4a`: Decrypted files  
- `{title}-final.mp4`: Final output

For non-DRM content:
- `{title}-final.mp4`: Direct download (no intermediate files)

Files are automatically cleaned up after each processing step.