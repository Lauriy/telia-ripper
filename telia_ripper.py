import os
import subprocess
from urllib.parse import urlparse
import httpx
from dotenv import load_dotenv
import re

load_dotenv()

YTDLP_PATH = os.getenv("YTDLP_PATH")
MP4DECRYPT_PATH = os.getenv("MP4DECRYPT_PATH")
FFMPEG_PATH = os.getenv("FFMPEG_PATH")
API_BASE_URL = "https://api.teliatv.ee"


def extract_content_info(url):
    parsed = urlparse(url)
    path_parts = parsed.path.strip("/").split("/")
    content_id = path_parts[-2]
    title = path_parts[-1]

    return content_id, title


def check_files_exist(title):
    return os.path.exists(f"{title}.mp4") and os.path.exists(f"{title}.m4a")


def decrypt_files(title, key):
    subprocess.run([MP4DECRYPT_PATH, "--key", key, f"{title}.mp4", f"{title}-dec.mp4"])
    subprocess.run([MP4DECRYPT_PATH, "--key", key, f"{title}.m4a", f"{title}-dec.m4a"])


def mix_files(title):
    subprocess.run(
        [
            FFMPEG_PATH,
            "-i",
            f"{title}-dec.mp4",
            "-i",
            f"{title}-dec.m4a",
            "-c",
            "copy",
            f"{title}-final.mp4",
        ]
    )


def get_decryption_key(content_id):
    headers = {"Cookie": f"session={os.getenv('KEYSDB_SESSION')}"}

    payload = {
        "license_url": f"{API_BASE_URL}/dtv-api/3.0/et/drm-license/widevine/vod_asset/{content_id}",
        "headers": f"Cookie: PHPSESSID={os.getenv('SESSION_ID')};",
        "pssh": os.getenv("PSSH"),
        "buildInfo": "",
        "proxy": "",
        "force": False,
    }

    response = httpx.post("https://keysdb.net/wv", json=payload, headers=headers)

    if response.status_code != httpx.codes.OK:
        print(f"Response content: {response.text}")
        raise Exception(f"Failed to get key: {response.status_code}")

    content = response.text
    key_match = re.search(r"Key: ([0-9a-f]+:[0-9a-f]+)", content)
    if not key_match:
        raise Exception("Could not find key in response")

    return key_match.group(1)


def get_stream_url(content_id):
    headers = {"Cookie": f"PHPSESSID={os.getenv('SESSION_ID')}"}

    response = httpx.post(
        f"{API_BASE_URL}/dtv-api/3.0/et/assets/{content_id}/play", headers=headers
    )

    if response.status_code != httpx.codes.OK:
        raise Exception(f"Failed to get stream info: {response.status_code}")

    return response.json()["playable"]["streams"][1]["sources"][0]


def get_stream_formats(stream_url):
    result = subprocess.run(
        [YTDLP_PATH, "-F", "--allow-u", stream_url], capture_output=True, text=True
    )

    if result.returncode != 0:
        raise Exception(f"Failed to get formats: {result.stderr}")

    lines = result.stdout.split("\n")
    video_formats = []
    audio_est = None

    for line in lines:
        if not line or "ID" in line or "-" * 20 in line:
            continue

        parts = line.split()
        if not parts:
            continue

        format_id = parts[0]

        if format_id.startswith("video="):
            try:
                bitrate = int(format_id.split("=")[1])
                video_formats.append((bitrate, format_id))
            except ValueError:
                continue
        elif format_id.startswith("audio_est="):
            audio_est = format_id

    if not video_formats or not audio_est:
        raise ValueError("Could not find required video and audio formats")

    best_video = max(video_formats)[1]
    
    return best_video, audio_est


def main():
    url = os.getenv("URL")
    if not url:
        raise ValueError("URL environment variable is not set")

    content_id, title = extract_content_info(url)
    print(f"Content ID: {content_id}, Title: {title}")

    if not check_files_exist(title):
        stream_url = get_stream_url(content_id)
        video_format, audio_format = get_stream_formats(stream_url)
        print("\nSelected formats:")
        print(f"Video: {video_format}")
        print(f"Audio: {audio_format}")

        subprocess.run(
            [
                YTDLP_PATH,
                "--allow-u",
                "-f",
                video_format,
                stream_url,
                "-o",
                f"{title}.mp4",
            ]
        )

        subprocess.run(
            [
                YTDLP_PATH,
                "--allow-u",
                "-f",
                audio_format,
                stream_url,
                "-o",
                f"{title}.m4a",
            ]
        )

    key = get_decryption_key(content_id)
    decrypt_files(title, key)
    mix_files(title)


if __name__ == "__main__":
    main()
