import contextlib
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from defusedxml.ElementTree import fromstring as parse_xml
from dotenv import load_dotenv

load_dotenv(override=True)

YTDLP_PATH = os.environ.get("YTDLP_PATH", "yt-dlp")
MP4DECRYPT_PATH = os.environ.get("MP4DECRYPT_PATH", "mp4decrypt")
FFMPEG_PATH = os.environ.get("FFMPEG_PATH", "ffmpeg")
API_BASE_URL = "https://api.teliatv.ee"
GO3_API_BASE_URL = "https://go3.tv"
CDRM_API_URL = "https://cdrm-project.com/api/decrypt"

# Service identifiers
SERVICE_TELIA = "telia"
SERVICE_GO3 = "go3"

# Stream types
STREAM_DASH = "dash"
STREAM_HLS = "hls"
STREAM_SS = "ss"

# Session cookie/env names
TELIA_COOKIE_NAME = "PHPSESSID"
TELIA_SESSION_ENV = "SESSION_ID"
GO3_COOKIE_NAME = "JSESSIONID"
GO3_SESSION_ENV = "GO3_SESSION_ID"

# Widevine / MPD XML constants
WIDEVINE_SCHEME_URI = "urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"
MPD_NS = "{urn:mpeg:dash:schema:mpd:2011}"
CENC_NS = "{urn:mpeg:cenc:2013}"


class RipperError(Exception): ...


def safe_delete_file(filepath: str) -> None:
    with contextlib.suppress(OSError):
        Path(filepath).unlink(missing_ok=True)


def detect_service(url: str) -> str:
    parsed = urlparse(url)
    if "go3.tv" in parsed.netloc:
        return SERVICE_GO3
    if "teliatv.ee" in parsed.netloc:
        return SERVICE_TELIA
    msg = f"Unsupported service: {parsed.netloc}"
    raise ValueError(msg)


def extract_content_info(url: str) -> tuple[str, str, str]:
    service = detect_service(url)
    parsed = urlparse(url)
    path_parts = parsed.path.strip("/").split("/")

    if service == SERVICE_GO3:
        last_part = path_parts[-1]
        title, vod_id = last_part.split(",")
        content_id = vod_id.split("-")[1]
    elif service == SERVICE_TELIA:
        content_id = path_parts[-2]
        title = path_parts[-1]
    else:
        msg = f"Unsupported service: {service}"
        raise ValueError(msg)

    return content_id, title, service


def check_files_exist(title: str) -> bool:
    return Path(f"{title}.mp4").exists() and Path(f"{title}.m4a").exists()


def check_dec_files_exist(title: str) -> bool:
    return Path(f"{title}-dec.mp4").exists() and Path(f"{title}-dec.m4a").exists()


def check_final_file_exists(title: str) -> bool:
    return Path(f"{title}-final.mp4").exists()


def decrypt_files(title: str, key: str) -> None:
    result_video = subprocess.run(
        [MP4DECRYPT_PATH, "--key", key, f"{title}.mp4", f"{title}-dec.mp4"],
        check=False,
    )
    if result_video.returncode != 0:
        msg = "Failed to decrypt video file"
        raise RipperError(msg)

    result_audio = subprocess.run(
        [MP4DECRYPT_PATH, "--key", key, f"{title}.m4a", f"{title}-dec.m4a"],
        check=False,
    )
    if result_audio.returncode != 0:
        msg = "Failed to decrypt audio file"
        raise RipperError(msg)

    if check_dec_files_exist(title):
        safe_delete_file(f"{title}.mp4")
        safe_delete_file(f"{title}.m4a")
    else:
        msg = "Decrypted files not found after decryption"
        raise RipperError(msg)


def mix_files(title: str) -> None:
    result = subprocess.run(
        [
            FFMPEG_PATH,
            "-i",
            f"{title}-dec.mp4",
            "-i",
            f"{title}-dec.m4a",
            "-c",
            "copy",
            f"{title}-final.mp4",
        ],
        check=False,
    )

    if result.returncode != 0:
        msg = "Failed to mix video and audio files"
        raise RipperError(msg)

    if check_final_file_exists(title):
        safe_delete_file(f"{title}-dec.mp4")
        safe_delete_file(f"{title}-dec.m4a")
    else:
        msg = "Final file not found after mixing"
        raise RipperError(msg)


def get_pssh_from_mpd(stream_url: str, service: str) -> str | None:
    if service == SERVICE_GO3:
        session = os.environ.get(GO3_SESSION_ENV, "")
        headers = {"Cookie": f"{GO3_COOKIE_NAME}={session}"}
    else:
        session = os.environ.get(TELIA_SESSION_ENV, "")
        headers = {"Cookie": f"{TELIA_COOKIE_NAME}={session}"}
    response = httpx.get(stream_url, headers=headers)
    if response.status_code == httpx.codes.FOUND:
        location = response.headers.get("Location")
        if location:
            response = httpx.get(location, headers=headers)

    if response.status_code != httpx.codes.OK:
        return None

    root = parse_xml(response.text)

    for cp in root.iter(f"{MPD_NS}ContentProtection"):
        if cp.get("schemeIdUri") == WIDEVINE_SCHEME_URI:
            for pssh_elem in cp.iter(f"{CENC_NS}pssh"):
                return pssh_elem.text

    return None


def get_decryption_key(
    content_id: str,
    pssh: str,
    service: str,
    retries: int = 3,
) -> str:
    headers = {
        "Content-Type": "application/json",
    }

    if service == SERVICE_TELIA:
        license_url = (
            f"{API_BASE_URL}/dtv-api/3.0/et/drm-license/widevine/vod_asset/{content_id}"
        )
        session = os.environ.get(TELIA_SESSION_ENV, "")
        session_cookie = f"{TELIA_COOKIE_NAME}={session}"
    elif service == SERVICE_GO3:
        license_url = (
            f"{GO3_API_BASE_URL}/api/products/{content_id}"
            f"/drm/widevine?platform=BROWSER&type=MOVIE&tenant=OM_EE"
        )
        session = os.environ.get(GO3_SESSION_ENV, "")
        session_cookie = f"{GO3_COOKIE_NAME}={session}"
    else:
        msg = f"Unsupported service: {service}"
        raise ValueError(msg)

    payload = {
        "pssh": pssh,
        "licurl": license_url,
        "headers": str({"Cookie": session_cookie}),
    }

    last_error: httpx.RequestError | ValueError = ValueError("No attempts made")
    for attempt in range(retries):
        try:
            response = httpx.post(
                CDRM_API_URL,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

            data = response.json()
            message: str = data.get("message", "")

            if not message:
                msg = "Empty response from CDRM"
                raise ValueError(msg)  # noqa: TRY301

            for raw_line in message.strip().split("\n"):
                stripped = raw_line.strip()
                if ":" in stripped and len(stripped.split(":")) == 2:  # noqa: PLR2004
                    return stripped

            msg = f"No valid key found in response: {message}"
            raise ValueError(msg)  # noqa: TRY301

        except (httpx.RequestError, ValueError) as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(2)
            continue

    raise last_error


def get_stream_info(content_id: str, service: str) -> tuple[str, str, bool]:
    if service == SERVICE_TELIA:
        return _get_telia_stream_info(content_id)
    if service == SERVICE_GO3:
        return _get_go3_stream_info(content_id)
    msg = f"Unsupported service: {service}"
    raise ValueError(msg)


def _get_telia_stream_info(content_id: str) -> tuple[str, str, bool]:
    headers = {"Cookie": f"{TELIA_COOKIE_NAME}={os.environ.get(TELIA_SESSION_ENV, '')}"}

    response = httpx.post(
        f"{API_BASE_URL}/dtv-api/3.0/et/assets/{content_id}/play",
        headers=headers,
    )

    if response.status_code != httpx.codes.OK:
        msg = f"Failed to get stream info: {response.status_code}"
        raise RipperError(msg)

    data = response.json()
    streams = data["playable"]["streams"]
    drm_info = data["playable"].get("drm")

    dash_stream = next(
        (s for s in streams if s["type"] == "multiformat_dash"),
        None,
    )
    if dash_stream:
        return dash_stream["sources"][0], STREAM_DASH, drm_info is not None

    hls_stream = next(
        (s for s in streams if s["type"] == "hls"),
        None,
    )
    if hls_stream:
        return hls_stream["sources"][0], STREAM_HLS, drm_info is not None

    msg = "No supported stream found (DASH or HLS)"
    raise RipperError(msg)


def _get_go3_stream_info(content_id: str) -> tuple[str, str, bool]:
    headers = {"Cookie": f"{GO3_COOKIE_NAME}={os.environ.get(GO3_SESSION_ENV, '')}"}
    playlist_url = (
        f"{GO3_API_BASE_URL}/api/products/{content_id}/videos/playlist"
        f"?platform=BROWSER&videoType=MOVIE&lang=ET&tenant=OM_EE"
    )
    response = httpx.get(playlist_url, headers=headers)
    if response.status_code != httpx.codes.OK:
        msg = f"Failed to fetch playlist: {response.status_code}"
        raise RipperError(msg)

    data = response.json()

    for source_type, stream_type in [("DASH", STREAM_DASH), ("SS", STREAM_SS)]:
        sources = data["sources"].get(source_type)
        if sources:
            stream_url = sources[0]["src"]
            if stream_url.startswith("//"):
                stream_url = "https:" + stream_url
            has_drm = data.get("drm") is not None
            return stream_url, stream_type, has_drm

    msg = "No supported stream found for Go3 (DASH or SS)"
    raise RipperError(msg)


def _is_estonian_audio(format_id: str, line: str) -> bool:
    return "audio_est=" in format_id or "[et]" in line or "[est]" in line


def _is_english_audio(format_id: str, line: str) -> bool:
    return "audio_eng=" in format_id or "[en]" in line or "[eng]" in line


def _parse_video_bitrate(line: str) -> int | None:
    try:
        tbr = line.split("|")[1].strip().split("k")[0]
        return int(tbr)
    except (ValueError, IndexError):
        return None


def _parse_format_list(
    output: str,
) -> tuple[list[tuple[int, str]], str | None, str | None]:
    video_formats: list[tuple[int, str]] = []
    audio_est = None
    audio_eng = None

    for line in output.split("\n"):
        if not line or "ID" in line or "-" * 20 in line:
            continue

        parts = line.split()
        if not parts:
            continue

        format_id = parts[0]

        if "video only" in line:
            bitrate = _parse_video_bitrate(line)
            if bitrate is not None:
                video_formats.append((bitrate, format_id))
        elif "audio only" in line and _is_estonian_audio(format_id, line):
            audio_est = format_id
        elif "audio only" in line and _is_english_audio(format_id, line):
            audio_eng = format_id

    return video_formats, audio_est, audio_eng


def get_stream_formats(stream_url: str) -> tuple[str, str]:
    args: list[str] = [YTDLP_PATH, "-F", "--allow-u"]
    if "ism/manifest" in stream_url:
        args.append("--no-check-certificate")
    args.append(stream_url)

    result = subprocess.run(args, check=False, capture_output=True, text=True)

    if result.returncode != 0:
        msg = f"Failed to get formats: {result.stderr}"
        raise RipperError(msg)

    video_formats, audio_est, audio_eng = _parse_format_list(result.stdout)

    if not video_formats:
        msg = "Could not find video formats"
        raise ValueError(msg)

    best_video = max(video_formats)[1]
    audio = audio_est or audio_eng
    if not audio:
        msg = "Could not find audio format"
        raise ValueError(msg)

    return best_video, audio


def _download_drm_content(
    title: str,
    stream_url: str,
    content_id: str,
    pssh: str,
    service: str,
) -> None:
    if not check_files_exist(title):
        video_format, audio_format = get_stream_formats(stream_url)

        result_video = subprocess.run(
            [
                YTDLP_PATH,
                "--allow-u",
                "-f",
                video_format,
                stream_url,
                "-o",
                f"{title}.mp4",
            ],
            check=False,
        )
        if result_video.returncode != 0:
            msg = "Failed to download video"
            raise RipperError(msg)

        result_audio = subprocess.run(
            [
                YTDLP_PATH,
                "--allow-u",
                "-f",
                audio_format,
                stream_url,
                "-o",
                f"./{title}.m4a",
            ],
            check=False,
        )
        if result_audio.returncode != 0:
            msg = "Failed to download audio"
            raise RipperError(msg)

        if not check_files_exist(title):
            msg = "Failed to download video and audio files"
            raise RipperError(msg)

    if not check_dec_files_exist(title):
        key = get_decryption_key(content_id, pssh, service)
        decrypt_files(title, key)

    if not check_final_file_exists(title):
        mix_files(title)


def _download_non_drm_content(title: str, stream_url: str) -> None:
    result = subprocess.run(
        [
            YTDLP_PATH,
            "--allow-u",
            "-f",
            "bv*+ba[language=et]/bv*+ba[language=est]"
            "/bv*+ba[language=en]/bv*+ba[language=eng]"
            "/bv*+ba[language!=rus]/bv*+ba",
            stream_url,
            "-o",
            f"{title}-temp.%(ext)s",
        ],
        check=False,
    )

    if result.returncode != 0:
        msg = "Failed to download video"
        raise RipperError(msg)

    cwd = Path()
    video_files = list(cwd.glob(f"{title}-temp.fvideo*.mp4"))
    if not video_files:
        video_files = list(cwd.glob(f"{title}-temp.f*.mp4"))

    audio_files = list(cwd.glob(f"{title}-temp.faudio*.m4a"))
    if not audio_files:
        audio_files = list(cwd.glob(f"{title}-temp.faudio*.mp4"))

    if not video_files or not audio_files:
        msg = "Could not find downloaded video or audio files"
        raise RipperError(msg)

    video_file = str(video_files[0])
    audio_file = str(audio_files[0])

    result = subprocess.run(
        [
            FFMPEG_PATH,
            "-i",
            video_file,
            "-i",
            audio_file,
            "-c",
            "copy",
            f"{title}-final.mp4",
        ],
        check=False,
    )

    if result.returncode != 0:
        msg = "Failed to merge video and audio files"
        raise RipperError(msg)

    safe_delete_file(video_file)
    safe_delete_file(audio_file)

    if not check_final_file_exists(title):
        msg = "Final file not found after merge"
        raise RipperError(msg)


def main() -> None:
    url = os.environ.get("URL")
    if not url:
        msg = "URL environment variable is not set"
        raise ValueError(msg)

    content_id, title, service = extract_content_info(url)

    if check_final_file_exists(title):
        return

    stream_url, stream_type, has_drm = get_stream_info(content_id, service)

    pssh: str | None = None
    if has_drm and stream_type == STREAM_DASH:
        pssh = get_pssh_from_mpd(stream_url, service)
        if pssh is None:
            pssh = os.environ.get("PSSH")
            if not pssh:
                has_drm = False

    if has_drm and pssh:
        _download_drm_content(title, stream_url, content_id, pssh, service)
    elif not check_final_file_exists(title):
        _download_non_drm_content(title, stream_url)


if __name__ == "__main__":
    main()
