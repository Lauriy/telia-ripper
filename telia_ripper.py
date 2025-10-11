import os
import subprocess
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()

YTDLP_PATH = os.getenv("YTDLP_PATH")
MP4DECRYPT_PATH = os.getenv("MP4DECRYPT_PATH")
FFMPEG_PATH = os.getenv("FFMPEG_PATH")
API_BASE_URL = "https://api.teliatv.ee"


def safe_delete_file(filepath):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            print(f"Deleted: {filepath}")
    except OSError as e:
        print(f"Warning: Could not delete {filepath}: {e}")


def extract_content_info(url):
    parsed = urlparse(url)
    path_parts = parsed.path.strip("/").split("/")
    content_id = path_parts[-2]
    title = path_parts[-1]

    return content_id, title


def check_files_exist(title):
    return os.path.exists(f"{title}.mp4") and os.path.exists(f"{title}.m4a")


def check_dec_files_exist(title):
    return os.path.exists(f"{title}-dec.mp4") and os.path.exists(f"{title}-dec.m4a")


def check_final_file_exists(title):
    return os.path.exists(f"{title}-final.mp4")


def decrypt_files(title, key):
    result_video = subprocess.run(
        [MP4DECRYPT_PATH, "--key", key, f"{title}.mp4", f"{title}-dec.mp4"]
    )
    if result_video.returncode != 0:
        raise Exception("Failed to decrypt video file")

    result_audio = subprocess.run(
        [MP4DECRYPT_PATH, "--key", key, f"{title}.m4a", f"{title}-dec.m4a"]
    )
    if result_audio.returncode != 0:
        raise Exception("Failed to decrypt audio file")

    if check_dec_files_exist(title):
        print("Decryption successful, deleting original encrypted files...")
        safe_delete_file(f"{title}.mp4")
        safe_delete_file(f"{title}.m4a")
    else:
        raise Exception("Decrypted files not found after decryption")


def mix_files(title):
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
        ]
    )

    if result.returncode != 0:
        raise Exception("Failed to mix video and audio files")

    if check_final_file_exists(title):
        print("Mixing successful, deleting decrypted files...")
        safe_delete_file(f"{title}-dec.mp4")
        safe_delete_file(f"{title}-dec.m4a")
    else:
        raise Exception("Final file not found after mixing")


def get_decryption_key(content_id: str, pssh: str) -> str:
    print("\nGetting decryption key...")

    headers = {
        "Content-Type": "application/json",
    }

    payload = {
        "license": f"https://api.teliatv.ee/dtv-api/3.0/et/drm-license/widevine/vod_asset/{content_id}",
        "headers": f"Cookie: PHPSESSID={os.getenv('SESSION_ID')}",
        "pssh": pssh,
        "buildInfo": "google/sdk_gphone_x86/generic_x86:8.1.0/OSM1.180201.037/6739391:userdebug/dev-keys",
        "proxy": "",
        "cache": True,
    }

    try:
        response = httpx.post(
            "http://108.181.133.95:8080/wv", headers=headers, json=payload
        )
        response.raise_for_status()

        response_content = response.text
        print(f"\nResponse content: {response_content}")

        if "SUCCESS" not in response_content:
            raise ValueError("Invalid response format: 'SUCCESS' not found")

        import re

        match = re.search(
            r'<li style="font-family:\'Courier\'">(.*?)</li>', response_content
        )
        if match:
            key = match.group(1).strip()
            print(f"\nGot key: {key}")

            if ":" not in key or len(key.split(":")) != 2:
                raise ValueError(
                    "Key format is invalid, must be in the form part1:part2"
                )

            return key
        else:
            raise ValueError("Key not found in response")

    except httpx.RequestError as req_err:
        print(f"Request error: {req_err}")
        raise
    except ValueError as val_err:
        print(f"Value error: {val_err}")
        raise
    except Exception as e:
        print(f"Error getting key: {e}")
        raise


def get_stream_info(content_id):
    headers = {"Cookie": f"PHPSESSID={os.getenv('SESSION_ID')}"}

    response = httpx.post(
        f"{API_BASE_URL}/dtv-api/3.0/et/assets/{content_id}/play", headers=headers
    )

    if response.status_code != httpx.codes.OK:
        raise Exception(f"Failed to get stream info: {response.status_code}")

    data = response.json()
    streams = data["playable"]["streams"]
    drm_info = data["playable"].get("drm")

    # Prefer DASH stream for DRM content, fall back to HLS
    dash_stream = next(
        (stream for stream in streams if stream["type"] == "multiformat_dash"), None
    )

    if dash_stream:
        return dash_stream["sources"][0], "dash", drm_info is not None

    # Look for HLS stream
    hls_stream = next((stream for stream in streams if stream["type"] == "hls"), None)

    if hls_stream:
        return hls_stream["sources"][0], "hls", drm_info is not None

    raise Exception("No supported stream found (DASH or HLS)")


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
    audio_eng = None

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
        elif "audio only" in line and (
            "audio_est=" in format_id or "[et]" in line or "[est]" in line
        ):
            audio_est = format_id
            print(f"Found Estonian audio: {format_id}")
        elif "audio only" in line and (
            "audio_eng=" in format_id or "[en]" in line or "[eng]" in line
        ):
            audio_eng = format_id
            print(f"Found English audio: {format_id}")

    if not video_formats:
        print("No video formats found!")
        raise ValueError("Could not find video formats")

    # if not audio_est:
    #     print("No Estonian audio found!")
    #     raise ValueError("Estonian audio track not available")

    best_video = max(video_formats)[1]
    print("\nSelected formats:")
    print(f"Video: {best_video}")
    print(f"Audio: {audio_est or audio_eng}")

    return best_video, audio_est or audio_eng


def main():
    url = os.getenv("URL")
    if not url:
        raise ValueError("URL environment variable is not set")

    content_id, title = extract_content_info(url)
    print(f"Content ID: {content_id}, Title: {title}")

    if check_final_file_exists(title):
        print(
            f"Final file {title}-final.mp4 already exists, skipping download and processing"
        )
        return

    stream_url, stream_type, has_drm = get_stream_info(content_id)
    print(f"Stream type: {stream_type}, DRM protected: {has_drm}")

    if has_drm and not check_files_exist(title):
        # DRM content - download encrypted files
        video_format, audio_format = get_stream_formats(stream_url)
        print("\nSelected formats:")
        print(f"Video: {video_format}")
        print(f"Audio: {audio_format}")

        print("Downloading video...")
        result_video = subprocess.run(
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

        if result_video.returncode != 0:
            raise Exception("Failed to download video")

        print("Downloading audio...")
        result_audio = subprocess.run(
            [
                YTDLP_PATH,
                "--allow-u",
                "-f",
                audio_format,
                stream_url,
                "-o",
                f"./{title}.m4a",
            ]
        )

        if result_audio.returncode != 0:
            raise Exception("Failed to download audio")

        if not check_files_exist(title):
            raise Exception("Failed to download video and audio files")

        key = get_decryption_key(content_id, os.getenv("PSSH"))
        decrypt_files(title, key)
        mix_files(title)

    elif not has_drm and not check_final_file_exists(title):
        # Non-DRM content - download and merge
        print("Downloading non-DRM content...")
        result = subprocess.run(
            [
                YTDLP_PATH,
                "--allow-u",
                stream_url,
                "-o",
                f"{title}-temp.%(ext)s",
            ]
        )

        if result.returncode != 0:
            raise Exception("Failed to download video")

        # Merge the downloaded video and audio files
        import glob
        video_files = glob.glob(f"{title}-temp.f*.mp4")
        audio_files = glob.glob(f"{title}-temp.faudio*.mp4")
        
        if not video_files or not audio_files:
            # Try with the -final naming that was already used
            video_files = glob.glob(f"{title}-final.f*.mp4") 
            audio_files = glob.glob(f"{title}-final.faudio*.mp4")
        
        if not video_files or not audio_files:
            raise Exception("Could not find downloaded video or audio files")
        
        video_file = video_files[0]
        audio_file = audio_files[0]
        
        print(f"Merging {video_file} and {audio_file}...")
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
            ]
        )
        
        if result.returncode != 0:
            raise Exception("Failed to merge video and audio files")
        
        # Clean up the separate files
        safe_delete_file(video_file)
        safe_delete_file(audio_file)

        if not check_final_file_exists(title):
            raise Exception("Final file not found after merge")

    print(f"\nProcess completed successfully! Final file: {title}-final.mp4")


if __name__ == "__main__":
    main()
