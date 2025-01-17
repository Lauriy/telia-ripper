import os
import subprocess
from urllib.parse import urlparse
import httpx
from dotenv import load_dotenv
import json

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


def get_decryption_key(content_id, pssh):
    print("\nGetting decryption key...")

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    payload = {
        "PSSH": pssh,
        "License URL": f"{API_BASE_URL}/dtv-api/3.0/et/drm-license/widevine/vod_asset/{content_id}",
        "Headers": "",
        "JSON": "",
        "Cookies": f'{{"PHPSESSID": "{os.getenv("SESSION_ID")}"}}',
        "Data": "",
        "Proxy": "",
    }

    try:
        response = httpx.post(
            "https://cdrm-project.com/", json=payload, headers=headers
        )
        print(f"\nResponse status code: {response.status_code}")
        print("\nResponse content:")
        print(response.text)

        if response.status_code == httpx.codes.OK:
            print("\nParsing response as JSON...")
            data = response.json()
            print(f"Parsed JSON: {json.dumps(data, indent=2)}")

            if "Message" not in data:
                print("No Message field in response")
                print(f"Response data: {data}")
                raise Exception("Invalid response format")

            key = data["Message"].strip()
            if not key:
                print("Empty key in response")
                raise Exception("Empty key received")

            if "error" in key.lower() or "not found" in key.lower():
                print(f"Error in key response: {key}")
                raise Exception(f"Key server error: {key}")

            print(f"\nGot key: {key}")
            return key
        else:
            print(f"Error response from key server: {response.status_code}")
            print(f"Response content: {response.text}")
            raise Exception(f"Key server error: {response.status_code}")
    except Exception as e:
        print(f"Error getting key: {e}")
        raise

    raise Exception("Failed to get decryption key")


def get_stream_url(content_id):
    headers = {"Cookie": f"PHPSESSID={os.getenv('SESSION_ID')}"}

    response = httpx.post(
        f"{API_BASE_URL}/dtv-api/3.0/et/assets/{content_id}/play", headers=headers
    )

    if response.status_code != httpx.codes.OK:
        raise Exception(f"Failed to get stream info: {response.status_code}")

    data = response.json()
    streams = data["playable"]["streams"]

    # Find the DASH stream
    dash_stream = next(
        (stream for stream in streams if stream["type"] == "multiformat_dash"), None
    )

    if not dash_stream:
        raise Exception("No DASH stream found")

    return dash_stream["sources"][0]


def get_stream_formats(stream_url):
    print(f"\nGetting formats for stream URL: {stream_url}")
    
    args = [YTDLP_PATH, "-F", "--allow-u"]
    if "ism/manifest" in stream_url:
        args.extend(["--no-check-certificate"])
    args.append(stream_url)
    
    result = subprocess.run(args, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Error output: {result.stderr}")
        raise Exception(f"Failed to get formats: {result.stderr}")

    print(f"\nyt-dlp output:\n{result.stdout}")

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
        print(f"Processing format: {format_id} - {line}")

        # Check if this is a video format
        if "video only" in line:
            try:
                # Extract bitrate from TBR column
                tbr = line.split("|")[1].strip().split("k")[0]
                bitrate = int(tbr)
                video_formats.append((bitrate, format_id))
                print(f"Found video format: {format_id} with bitrate {bitrate}")
            except (ValueError, IndexError):
                continue
        elif "audio only" in line and ("audio_est=" in format_id or "[et]" in line or "[est]" in line):
            audio_est = format_id
            print(f"Found Estonian audio: {format_id}")

    if not video_formats:
        print("No video formats found!")
        raise ValueError("Could not find video formats")
        
    if not audio_est:
        print("No Estonian audio found!")
        raise ValueError("Estonian audio track not available")

    best_video = max(video_formats)[1]
    print(f"\nSelected formats:")
    print(f"Video: {best_video}")
    print(f"Audio: {audio_est}")
    
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

    if not check_files_exist(title):
        raise Exception("Failed to download video and audio files")

    key = get_decryption_key(content_id, os.getenv("PSSH"))
    decrypt_files(title, key)
    mix_files(title)


if __name__ == "__main__":
    main()
