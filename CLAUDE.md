# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a tool for downloading and decrypting Telia video streams. The main script `telia_ripper.py` handles the complete workflow of extracting content info from URLs, downloading DASH streams, obtaining decryption keys, and producing final MP4 files.

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
- `URL`: Telia TV content URL
- `SESSION_ID`: PHP session ID for authentication
- `PSSH`: Protection System Specific Header (captured from browser)
- `YTDLP_PATH`: Path to yt-dlp executable
- `MP4DECRYPT_PATH`: Path to mp4decrypt executable
- `FFMPEG_PATH`: Path to ffmpeg executable

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

### Core Workflow (main function in telia_ripper.py:251)
1. Extract content ID and title from URL
2. Get stream information from Telia API (supports both DASH and HLS)
3. Determine if content is DRM-protected
4. For DRM content: Download encrypted files → decrypt → mix
5. For non-DRM content: Download directly to final file

### Key Functions
- `extract_content_info()`: Parses Telia URLs to extract content ID and title
- `get_stream_info()`: Calls Telia API and returns stream URL, type (dash/hls), and DRM status
- `get_stream_formats()`: Uses yt-dlp to analyze DASH stream formats (DRM content only)
- `get_decryption_key()`: Communicates with CDM service for Widevine keys (DRM content only)
- `decrypt_files()`: Uses mp4decrypt to decrypt downloaded content (DRM content only)
- `mix_files()`: Combines video/audio using ffmpeg (DRM content only)

### External Dependencies
- **yt-dlp**: Downloads both DASH (DRM) and HLS (non-DRM) streams
- **mp4decrypt**: Decrypts Widevine-protected content (DRM only)
- **ffmpeg**: Mixes video and audio files (DRM only)
- **CDM service**: External Widevine key server at `108.181.133.95:8080` (DRM only)

### API Integration
- Uses Telia TV API (`https://api.teliatv.ee`) for stream information
- Requires valid PHP session for authentication
- Supports both DRM-protected DASH streams and unprotected HLS streams
- Supports Estonian and English audio tracks

### File Management
For DRM content, the script creates temporary files during processing:
- `{title}.mp4` / `{title}.m4a`: Encrypted downloads
- `{title}-dec.mp4` / `{title}-dec.m4a`: Decrypted files  
- `{title}-final.mp4`: Final output

For non-DRM content:
- `{title}-final.mp4`: Direct download (no intermediate files)

Files are automatically cleaned up after each processing step.