# telia-ripper

Personal-use ripper for Telia TV and Go3 video streams (Widevine L3 DRM). Downloads + decrypts the streams of paid subscription content (e.g. for offline viewing on flights).

## Setup

```shell
uv venv
uv sync
```

Make sure your `.venv` is activated for everything below.

## Configure

Fill in `.env`:

```
URL=https://teliatv.ee/... or https://go3.tv/...
SESSION_ID=<Telia PHPSESSID cookie value>
GO3_SESSION_ID=<Go3 JSESSIONID cookie value>
PSSH=<optional fallback if MPD doesn't carry one>
WVD_PATH=.wvd/device.wvd
YTDLP_PATH=path/to/yt-dlp
MP4DECRYPT_PATH=path/to/mp4decrypt
FFMPEG_PATH=path/to/ffmpeg
```

You also need a Widevine `.wvd` device blob at `WVD_PATH`. See **Getting a .wvd** below.

To grab the PSSH from a Telia/Go3 player page, paste this into DevTools console *before* clicking play:

```javascript
const orig = MediaKeySession.prototype.generateRequest;
MediaKeySession.prototype.generateRequest = function (initDataType, initData) {
    if (initData instanceof ArrayBuffer) {
        const arr = new Uint8Array(initData);
        const b64 = btoa(String.fromCharCode.apply(null, arr));
        console.log("initData (base64):", b64);
    }
    return orig.call(this, initDataType, initData);
};
```

## Run

```shell
python telia_ripper.py
```

## Lint / type-check

```shell
uv run ruff check . --fix --unsafe-fixes && uv run ruff format .
uv run ty check
```

## Getting a .wvd (Widevine device blob)

`telia-ripper` uses [`pywidevine`](https://github.com/devine-dl/pywidevine) locally to negotiate licenses with Telia/Go3 license servers. That requires a provisioned Widevine L3 device blob (`.wvd`) extracted from a real Android phone you own. There are no public ones, and dumping requires root.

### Pick the right phone

An old phone (~2014–2018, ARMv7) is ideal:

- **Hardware Widevine (L1)** on flagships lives in TrustZone and is not extractable without firmware exploits.
- **Software Widevine (L3)** is what we want — accessible once you have root.
- Older Widevine library versions tend to be more cleanly hookable than newer ones.

Confirmed working: **OnePlus One (`bacon`)** running LineageOS 18.1 (Android 11). Other rooted Snapdragon-era phones with `/vendor/lib/mediadrm/libwvdrmengine.so` should work similarly.

### Extraction outline

1. **Get root.** Either Magisk-rooted stock, or a `userdebug` LineageOS build (in which case `adb root` is enough — no Magisk needed).

2. **Sort out USB drivers (Windows-only headache).** Some old phones' fastboot interfaces (`USB\VID_18D1&PID_D00D` for OnePlus) lack a Google-signed INF entry. Path that worked:
   - `winget install Google.PlatformTools` for `adb`/`fastboot`.
   - `winget install ClockworkMod.UniversalADBDriver` for ADB-mode.
   - `winget install akeo.ie.Zadig` then run Zadig and force-install **WinUSB** on the bootloader interface to fix fastboot mode.
   - On Linux/macOS: just plug it in.

3. **Get tooling.**
   ```shell
   uv tool install frida-tools keydive
   ```

4. **Push frida-server to the phone.** Match the version to your installed `frida` package, then run as root with `setsid` so it survives `adb shell` exiting:
   ```shell
   # Download from https://github.com/frida/frida/releases (frida-server-X.Y.Z-android-arm.xz for ARMv7)
   adb push frida-server /data/local/tmp/frida-server
   adb shell "chmod 755 /data/local/tmp/frida-server"
   adb shell "setenforce 0"   # SELinux permissive (root required)
   adb shell "setsid /data/local/tmp/frida-server </dev/null >/dev/null 2>&1 &"
   ```

5. **Run [KeyDive](https://github.com/hyugogirubato/KeyDive).** It auto-installs the Kaltura DRM test app, hooks the Widevine HAL service, and captures the keybox / RSA private key when the device reads its provisioning data:
   ```shell
   keydive -o ./device -w -a player
   ```
   Output is a `.wvd` plus `client_id.bin` + `private_key.pem`. Copy the `.wvd` to `.wvd/device.wvd` (already gitignored).

### Caveats encountered on the OnePlus One

- LineageOS 18.1 on OPO uses an older HAL service name (`android.hardware.drm@1.0-service`, no `.widevine` suffix) and the legacy `libwvdrmengine.so`. KeyDive's built-in vendor table doesn't include this combo. Patch in (in your installed `keydive/drm/__init__.py`):
  ```python
  Vendor('android.hardware.drm@1.0-service', 30, (11, '1.0'), 'libwvdrmengine.so')
  ```
- **Frida 17.x's `enumerateExports()` / `enumerateSymbols()` returns nothing** on this lib (likely a parser quirk on the ANDROID_REL relocations or unusual segment layout). Workaround: pull the lib (`adb pull /vendor/lib/mediadrm/libwvdrmengine.so`), parse `readelf -W --dyn-syms` output into a Ghidra-style XML mapping `ENTRY_POINT="0x..." NAME="..."` for every FUNC symbol, and pass it via `keydive --symbols path/to/symbols.xml`. Use `IMAGE_BASE="0x8000"` in the XML — that's the lib's first LOAD `VirtAddr`, and KeyDive computes `address - IMAGE_BASE` to get the offset added to Frida's `library.base`.

If your phone is newer and KeyDive's auto-detection works out of the box, ignore both caveats.

### Validate

```python
from pywidevine.device import Device
d = Device.load(".wvd/device.wvd")
print(d.type, d.system_id, d.security_level)
# DeviceTypes.ANDROID  4445  3
```

### A note on Widevine version compatibility

Old phones produce old Widevine blobs. The OPO yields **v5.0.0-android**. Many DRM services reject CDMs older than ~v15. Telia and Go3 accept the v5.0.0 blob at the time of writing, but other services may not. Symptom of rejection: HTTP 4xx/5xx from the license server, or an empty key list. If that happens, you'll need to extract from a phone with a newer (~v15+) Widevine library.

### Don't share your .wvd

The `.wvd` is bound to your phone's identity. Sharing it makes it traceable if it ends up doing high-volume bad things, and may get the device blob revoked. Keep it local. `.wvd/` is already in `.gitignore`.

## How it works (flow)

1. Detect service from URL → fetch stream metadata from Telia/Go3 API.
2. Parse PSSH from the MPD manifest (or use env fallback).
3. Download encrypted streams via `yt-dlp` (separately: video, audio).
4. Build a Widevine license challenge locally with `pywidevine` + your `.wvd`, POST it to the license URL using your session cookie, parse the response, extract the content key.
5. `mp4decrypt` decrypts each track → `ffmpeg` muxes them into the final `{title}-final.mp4`.

For non-DRM streams, the download just flows through `yt-dlp` + `ffmpeg` directly.
