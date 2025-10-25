import glob
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()

YTDLP_PATH = os.getenv("YTDLP_PATH")
MP4DECRYPT_PATH = os.getenv("MP4DECRYPT_PATH")
FFMPEG_PATH = os.getenv("FFMPEG_PATH")
API_BASE_URL = "https://api.teliatv.ee"
GO3_API_BASE_URL = "https://go3.tv"


def safe_delete_file(filepath) -> None:
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except OSError:
        pass


def detect_service(url) -> str:
    parsed = urlparse(url)
    if "go3.tv" in parsed.netloc:
        return "go3"
    if "teliatv.ee" in parsed.netloc:
        return "telia"
    msg = f"Unsupported service: {parsed.netloc}"
    raise ValueError(msg)


def extract_content_info(url):
    service = detect_service(url)
    parsed = urlparse(url)
    path_parts = parsed.path.strip("/").split("/")

    if service == "go3":
        # Format: /watch/title,vod-1022921
        last_part = path_parts[-1]
        title, vod_id = last_part.split(",")
        content_id = vod_id.split("-")[1]  # Remove 'vod-'
    elif service == "telia":
        # Assume format: /watch/title/id
        content_id = path_parts[-2]
        title = path_parts[-1]
    else:
        msg = f"Unsupported service: {service}"
        raise ValueError(msg)

    return content_id, title, service


def check_files_exist(title):
    return os.path.exists(f"{title}.mp4") and os.path.exists(f"{title}.m4a")


def check_dec_files_exist(title):
    return os.path.exists(f"{title}-dec.mp4") and os.path.exists(f"{title}-dec.m4a")


def check_final_file_exists(title):
    return os.path.exists(f"{title}-final.mp4")


def decrypt_files(title, key) -> None:
    result_video = subprocess.run(
        [MP4DECRYPT_PATH, "--key", key, f"{title}.mp4", f"{title}-dec.mp4"],
        check=False,
    )
    if result_video.returncode != 0:
        msg = "Failed to decrypt video file"
        raise Exception(msg)

    result_audio = subprocess.run(
        [MP4DECRYPT_PATH, "--key", key, f"{title}.m4a", f"{title}-dec.m4a"],
        check=False,
    )
    if result_audio.returncode != 0:
        msg = "Failed to decrypt audio file"
        raise Exception(msg)

    if check_dec_files_exist(title):
        safe_delete_file(f"{title}.mp4")
        safe_delete_file(f"{title}.m4a")
    else:
        msg = "Decrypted files not found after decryption"
        raise Exception(msg)


def mix_files(title) -> None:
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
        raise Exception(msg)

    if check_final_file_exists(title):
        safe_delete_file(f"{title}-dec.mp4")
        safe_delete_file(f"{title}-dec.m4a")
    else:
        msg = "Final file not found after mixing"
        raise Exception(msg)


def get_pssh_from_mpd(stream_url: str) -> str:
    headers = {"Cookie": f"JSESSIONID={os.getenv('GO3_SESSION_ID')}"}
    response = httpx.get(stream_url, headers=headers)
    if response.status_code == 302:
        location = response.headers.get("Location")
        if location:
            response = httpx.get(location, headers=headers)

    if response.status_code != 200:
        return None

    mpd_content = response.text

    root = ET.fromstring(mpd_content)

    # Find Widevine ContentProtection
    widevine_scheme = "urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"
    for cp in root.iter("{urn:mpeg:dash:schema:mpd:2011}ContentProtection"):
        if cp.get("schemeIdUri") == widevine_scheme:
            # Find cenc:pssh
            for pssh_elem in cp.iter("{urn:mpeg:cenc:2013}pssh"):
                return pssh_elem.text

    return None


def get_decryption_key(content_id: str, pssh: str, service: str) -> str:
    headers = {
        "Content-Type": "application/json",
    }

    if service == "telia":
        license_url = f"https://api.teliatv.ee/dtv-api/3.0/et/drm-license/widevine/vod_asset/{content_id}"
        session_cookie = f"PHPSESSID={os.getenv('SESSION_ID')}"
    elif service == "go3":
        license_url = f"https://go3.tv/api/products/{content_id}/drm/widevine?platform=BROWSER&type=MOVIE&tenant=OM_EE"
        session_cookie = f"JSESSIONID={os.getenv('GO3_SESSION_ID')}"
    else:
        msg = f"Unsupported service: {service}"
        raise ValueError(msg)

    payload = {
        "license": license_url,
        "headers": f"Cookie: {session_cookie}",
        "pssh": pssh,
        "buildInfo": "google/sdk_gphone_x86/generic_x86:8.1.0/OSM1.180201.037/6739391:userdebug/dev-keys",
        "proxy": "",
        "cache": True,
    }

    try:
        response = httpx.post(
            "http://108.181.133.95:8080/wv",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()

        response_content = response.text

        if "SUCCESS" not in response_content:
            msg = "Invalid response format: 'SUCCESS' not found"
            raise ValueError(msg)

        match = re.search(
            r'<li style="font-family:\'Courier\'">(.*?)</li>',
            response_content,
        )
        if match:
            key = match.group(1).strip()

            if ":" not in key or len(key.split(":")) != 2:
                msg = "Key format is invalid, must be in the form part1:part2"
                raise ValueError(
                    msg,
                )

            return key
        msg = "Key not found in response"
        raise ValueError(msg)

    except httpx.RequestError:
        raise
    except ValueError:
        raise
    except Exception:
        raise


def get_stream_info(content_id, service):
    if service == "telia":
        headers = {"Cookie": f"PHPSESSID={os.getenv('SESSION_ID')}"}

        response = httpx.post(
            f"{API_BASE_URL}/dtv-api/3.0/et/assets/{content_id}/play",
            headers=headers,
        )

        if response.status_code != httpx.codes.OK:
            msg = f"Failed to get stream info: {response.status_code}"
            raise Exception(msg)

        data = response.json()
        streams = data["playable"]["streams"]
        drm_info = data["playable"].get("drm")

        # Prefer DASH stream for DRM content, fall back to HLS
        dash_stream = next(
            (stream for stream in streams if stream["type"] == "multiformat_dash"),
            None,
        )

        if dash_stream:
            return dash_stream["sources"][0], "dash", drm_info is not None

        # Look for HLS stream
        hls_stream = next(
            (stream for stream in streams if stream["type"] == "hls"),
            None,
        )

        if hls_stream:
            return hls_stream["sources"][0], "hls", drm_info is not None

        msg = "No supported stream found (DASH or HLS)"
        raise Exception(msg)
    if service == "go3":
        # Fetch play response from Go3 API
        headers = {"Cookie": f"JSESSIONID={os.getenv('GO3_SESSION_ID')}"}
        playlist_url = f"https://go3.tv/api/products/{content_id}/videos/playlist?platform=BROWSER&videoType=MOVIE&lang=ET&tenant=OM_EE"
        response = httpx.get(playlist_url, headers=headers)
        if response.status_code != 200:
            msg = f"Failed to fetch playlist: {response.status_code}"
            raise Exception(msg)
        data = response.json()
        # Assuming the response has the same structure as play response
        # Extract DASH stream
        dash_sources = data["sources"].get("DASH")
        if dash_sources:
            stream_url = dash_sources[0]["src"]
            if stream_url.startswith("//"):
                stream_url = "https:" + stream_url
            drm_info = data.get("drm")
            has_drm = drm_info is not None
            return stream_url, "dash", has_drm
        # Fallback to SS
        ss_sources = data["sources"].get("SS")
        if ss_sources:
            stream_url = ss_sources[0]["src"]
            if stream_url.startswith("//"):
                stream_url = "https:" + stream_url
            drm_info = data.get("drm")
            has_drm = drm_info is not None
            return stream_url, "ss", has_drm
        msg = "No supported stream found for Go3 (DASH or SS)"
        raise Exception(msg)
    msg = f"Unsupported service: {service}"
    raise ValueError(msg)


def get_stream_formats(stream_url):
    args = [YTDLP_PATH, "-F", "--allow-u"]
    if "ism/manifest" in stream_url:
        args.extend(["--no-check-certificate"])
    args.append(stream_url)

    result = subprocess.run(args, check=False, capture_output=True, text=True)

    if result.returncode != 0:
        msg = f"Failed to get formats: {result.stderr}"
        raise Exception(msg)

    lines = result.stdout.split("\n")
    video_formats = []
    audio_est = None
    audio_eng = None

    for line in lines:
        if not line or "ID" in line or "-" * 20 in line:
            continue

        parts = line.split()
        if not parts:
            continue

        format_id = parts[0]

        # Check if this is a video format
        if "video only" in line:
            try:
                # Extract bitrate from TBR column
                tbr = line.split("|")[1].strip().split("k")[0]
                bitrate = int(tbr)
                video_formats.append((bitrate, format_id))
            except (ValueError, IndexError):
                continue
        elif "audio only" in line and (
            "audio_est=" in format_id or "[et]" in line or "[est]" in line
        ):
            audio_est = format_id
        elif "audio only" in line and (
            "audio_eng=" in format_id or "[en]" in line or "[eng]" in line
        ):
            audio_eng = format_id

    if not video_formats:
        msg = "Could not find video formats"
        raise ValueError(msg)

    # if not audio_est:
    #     print("No Estonian audio found!")
    #     raise ValueError("Estonian audio track not available")

    best_video = max(video_formats)[1]

    return best_video, audio_est or audio_eng


def main() -> None:
    url = os.getenv("URL")
    if not url:
        msg = "URL environment variable is not set"
        raise ValueError(msg)

    content_id, title, service = extract_content_info(url)

    if check_final_file_exists(title):
        return

    stream_url, stream_type, has_drm = get_stream_info(content_id, service)

    if has_drm and stream_type == "dash":
        pssh = get_pssh_from_mpd(stream_url)
        if pssh is None:
            if service == "go3":
                pssh = os.getenv("PSSH")
                if pssh:
                    pass
                else:
                    has_drm = False
            else:
                has_drm = False

    if has_drm and not check_files_exist(title):
        # DRM content - download encrypted files
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
            raise Exception(msg)

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
            raise Exception(msg)

        if not check_files_exist(title):
            msg = "Failed to download video and audio files"
            raise Exception(msg)

        if has_drm:
            if stream_type == "dash":
                pssh = get_pssh_from_mpd(stream_url)
            else:
                pssh = os.getenv("PSSH")
                if not pssh:
                    msg = "PSSH required for non-DASH DRM"
                    raise ValueError(msg)
        else:
            pssh = None  # Not needed for non-DRM

        key = get_decryption_key(content_id, pssh, service)
        decrypt_files(title, key)
        mix_files(title)

    elif not has_drm and not check_final_file_exists(title):
        # Non-DRM content - download and merge
        result = subprocess.run(
            [
                YTDLP_PATH,
                "--allow-u",
                stream_url,
                "-o",
                f"{title}-temp.%(ext)s",
            ],
            check=False,
        )

        if result.returncode != 0:
            msg = "Failed to download video"
            raise Exception(msg)

        # Merge the downloaded video and audio files
        video_files = glob.glob(f"{title}-temp.f*.mp4")
        audio_files = glob.glob(f"{title}-temp.faudio*.mp4")

        if not video_files or not audio_files:
            # Try with the -final naming that was already used
            video_files = glob.glob(f"{title}-final.f*.mp4")
            audio_files = glob.glob(f"{title}-final.faudio*.mp4")

        if not video_files or not audio_files:
            msg = "Could not find downloaded video or audio files"
            raise Exception(msg)

        video_file = video_files[0]
        audio_file = audio_files[0]

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
            raise Exception(msg)

        # Clean up the separate files
        safe_delete_file(video_file)
        safe_delete_file(audio_file)

        if not check_final_file_exists(title):
            msg = "Final file not found after merge"
            raise Exception(msg)


if __name__ == "__main__":
    main()
