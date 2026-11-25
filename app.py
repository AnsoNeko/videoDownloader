from __future__ import annotations

import os
import base64
import re
import shutil
from functools import lru_cache
import subprocess
import sys
import threading
import traceback
import uuid
import webbrowser
import json
import tempfile
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

from platform_support import PLATFORMS, detect_cookie_platform, extract_first_url, infer_platform_key, normalize_supported_url, validate_url

def normalize_fs_path(path: Path | str) -> Path:
    raw = str(path)
    if raw.startswith("\\\\?\\"):
        raw = raw[4:]
    return Path(os.path.normpath(raw))


if getattr(sys, "frozen", False):
    RESOURCE_DIR = normalize_fs_path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    APP_DIR = normalize_fs_path(Path(sys.executable).resolve().parent)
else:
    RESOURCE_DIR = normalize_fs_path(Path(__file__).resolve().parent)
    APP_DIR = RESOURCE_DIR

BASE_DIR = RESOURCE_DIR
VENDOR_DIR = RESOURCE_DIR / "vendor"
BUNDLED_TOOLS_DIR = RESOURCE_DIR / "tools"
LOCAL_TOOLS_DIR = APP_DIR / "tools"
TOOLS_DIR = LOCAL_TOOLS_DIR if LOCAL_TOOLS_DIR.exists() else BUNDLED_TOOLS_DIR
FFMPEG_DIR = TOOLS_DIR / "ffmpeg"
FFMPEG_BIN_DIR = FFMPEG_DIR / "bin"
FFMPEG_EXE = FFMPEG_BIN_DIR / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
BGUTIL_PROVIDER_DIR = TOOLS_DIR / "bgutil-ytdlp-pot-provider" / "server"
BGUTIL_PROVIDER_SCRIPT = BGUTIL_PROVIDER_DIR / "build" / "generate_once.js"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

from flask import Flask, jsonify, render_template, request
from jinja2 import FileSystemLoader

try:
    import yt_dlp
    from chinese_extractors import extract_platform_info
except ImportError:  # pragma: no cover
    yt_dlp = None

try:
    import websocket
except ImportError:  # pragma: no cover
    websocket = None


DOWNLOADS_DIR = APP_DIR / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)
RUNTIME_DIR = APP_DIR / ".runtime"
RUNTIME_DIR.mkdir(exist_ok=True)
AUTH_DIR = APP_DIR / ".auth"
AUTH_DIR.mkdir(exist_ok=True)
ERROR_LOG_PATH = RUNTIME_DIR / "download-errors.log"
SETTINGS_PATH = RUNTIME_DIR / "settings.json"
SETTINGS_LOCK = threading.Lock()
COOKIES_LOCK = threading.Lock()
DIRECTORY_PICKER_LOCK = threading.Lock()
COOKIE_FILE_CANDIDATES = (
    APP_DIR / "cookies.txt",
    RESOURCE_DIR / "cookies.txt",
)
BROWSER_COOKIE_CANDIDATES = (
    ("edge", None, None, None),
    ("chrome", None, None, None),
    ("firefox", None, None, None),
)
COOKIE_ERROR_MARKERS = (
    "sign in",
    "confirm you're not a bot",
    "confirm you’re not a bot",
    "cookies-from-browser",
    "use --cookies",
    "authentication",
    "login required",
    "private",
    "members only",
    "premium",
    "age-restricted",
    "age restricted",
    "not a bot",
    "fresh cookies",
    "please log in",
    "未登录",
    "请登录",
    "登录失效",
    "cookie 已失效",
    "http error 401",
    "unauthorized",
)
LOGIN_URLS = {
    "youtube": "https://accounts.google.com/ServiceLogin?service=youtube",
    "x": "https://x.com/i/flow/login",
    "instagram": "https://www.instagram.com/accounts/login/",
    "bilibili": "https://passport.bilibili.com/login",
    "douyin": "https://www.douyin.com/",
    "xiaohongshu": "https://www.xiaohongshu.com/",
}
COOKIE_EXPORT_URLS = {
    "youtube": ["https://www.youtube.com/", "https://accounts.google.com/"],
    "x": ["https://x.com/", "https://twitter.com/"],
    "instagram": ["https://www.instagram.com/"],
    "bilibili": ["https://www.bilibili.com/", "https://passport.bilibili.com/"],
    "douyin": ["https://www.douyin.com/"],
    "xiaohongshu": ["https://www.xiaohongshu.com/"],
}
MANAGED_DEBUG_PORT = 9333
BROWSER_EXECUTABLE_CANDIDATES = {
    "chrome": (
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ),
    "edge": (
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
    ),
}

app = Flask(
    __name__,
    template_folder=str(RESOURCE_DIR / "templates"),
    static_folder=str(RESOURCE_DIR / "static"),
)
app.jinja_loader = FileSystemLoader(str((RESOURCE_DIR / "templates").resolve()))
DOWNLOAD_JOBS: dict[str, dict[str, Any]] = {}
DOWNLOAD_JOBS_LOCK = threading.Lock()
MANAGED_AUTH_PROCESS: dict[str, Any] = {"pid": None, "browser": None, "platform": None, "debug_port": None}


def detect_ffmpeg() -> Path | None:
    if FFMPEG_EXE.exists():
        return FFMPEG_EXE

    candidate_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for path in os.environ.get("PATH", "").split(os.pathsep):
        if not path:
            continue
        candidate = Path(path) / candidate_name
        if os.access(candidate, os.X_OK):
            return candidate
    return None


def dependency_state() -> dict[str, Any]:
    ffmpeg_path = detect_ffmpeg()
    cookie_file = detect_cookie_file()
    managed_session = detect_managed_browser_session()
    browser_executable = detect_browser_executable()
    return {
        "download_dir": str(get_download_directory()),
        "default_download_dir": str(DOWNLOADS_DIR),
        "directory_picker_available": os.name == "nt",
        "yt_dlp_installed": yt_dlp is not None,
        "yt_dlp_version": yt_dlp.version.__version__ if yt_dlp else None,
        "js_runtimes": detect_js_runtimes(),
        "youtube_ejs_found": youtube_ejs_available(),
        "ffmpeg_found": ffmpeg_path is not None,
        "ffmpeg_path": str(ffmpeg_path) if ffmpeg_path else None,
        "bgutil_provider_ready": BGUTIL_PROVIDER_SCRIPT.exists(),
        "bgutil_provider_path": str(BGUTIL_PROVIDER_SCRIPT) if BGUTIL_PROVIDER_SCRIPT.exists() else None,
        "cookie_file_found": cookie_file is not None,
        "cookie_file_path": str(cookie_file) if cookie_file else None,
        "platforms": PLATFORMS,
        "saved_cookies": saved_cookie_state(),
        "managed_browser_session_found": managed_session is not None,
        "managed_browser_name": managed_session[0] if managed_session else None,
        "managed_browser_profile": str(managed_session[1]) if managed_session else None,
        "managed_auth_pid": MANAGED_AUTH_PROCESS.get("pid"),
        "login_browser_available": browser_executable is not None,
        "login_browser_name": browser_executable[0] if browser_executable else None,
    }


def get_download_directory() -> Path:
    with SETTINGS_LOCK:
        try:
            value = json.loads(SETTINGS_PATH.read_text(encoding="utf-8")).get("download_dir")
            if isinstance(value, str) and value.strip() and Path(value).is_absolute():
                return Path(value)
        except (OSError, ValueError, AttributeError):
            pass
    return DOWNLOADS_DIR


def validate_download_directory(value: Any) -> Path:
    if not isinstance(value, str):
        raise ValueError("下载目录必须是文件夹路径。")
    raw = os.path.expandvars(value.strip())
    try:
        directory = Path(raw).expanduser() if raw else DOWNLOADS_DIR
    except (OSError, ValueError, RuntimeError) as exc:
        raise ValueError("无法识别下载目录，请输入完整的文件夹路径。") from exc
    if not directory.is_absolute():
        raise ValueError("请输入完整的下载目录路径，例如 D:\\Videos。")
    try:
        directory = directory.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        # Test the actual write rather than relying on Windows permission bits.
        with tempfile.TemporaryFile(dir=directory):
            pass
    except (OSError, ValueError) as exc:
        raise ValueError(f"下载目录不可用，请选择可写的文件夹：{exc}") from exc
    return directory


def save_download_directory(directory: Path) -> None:
    with SETTINGS_LOCK:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=RUNTIME_DIR, delete=False) as fh:
                temporary = Path(fh.name)
                json.dump({"download_dir": str(directory)}, fh, ensure_ascii=False)
            os.replace(temporary, SETTINGS_PATH)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def choose_download_directory(initial: str) -> str | None:
    if os.name != "nt":
        raise RuntimeError("当前系统不支持文件夹选择窗口，请手动输入完整路径。")
    script = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '选择视频下载文件夹'
$dialog.ShowNewFolderButton = $true
$dialog.SelectedPath = $env:VIDEO_FETCHER_INITIAL_DIRECTORY
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
try {
    if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
        [Console]::Write($dialog.SelectedPath)
    }
} finally {
    $dialog.Dispose()
    $owner.Dispose()
}
'''
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    environment = dict(os.environ, VIDEO_FETCHER_INITIAL_DIRECTORY=initial)
    with DIRECTORY_PICKER_LOCK:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-EncodedCommand", encoded],
            capture_output=True, encoding="utf-8", errors="replace", env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    if result.returncode != 0:
        raise RuntimeError("无法打开文件夹选择窗口，请手动输入完整路径。")
    return result.stdout.strip().lstrip("\ufeff") or None


def update_job(job_id: str, **changes: Any) -> None:
    with DOWNLOAD_JOBS_LOCK:
        job = DOWNLOAD_JOBS.get(job_id)
        if job is None:
            return
        job.update(changes)


def get_job(job_id: str) -> dict[str, Any] | None:
    with DOWNLOAD_JOBS_LOCK:
        job = DOWNLOAD_JOBS.get(job_id)
        if job is None:
            return None
        return dict(job)


def require_yt_dlp() -> None:
    if yt_dlp is None:
        raise RuntimeError("未检测到 yt-dlp，请先安装项目依赖。")


def detect_cookie_file() -> Path | None:
    for candidate in COOKIE_FILE_CANDIDATES:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def detect_browser_executable() -> tuple[str, Path] | None:
    for browser_name, candidates in BROWSER_EXECUTABLE_CANDIDATES.items():
        for candidate in candidates:
            if candidate and candidate.exists():
                return browser_name, candidate
    return None


def get_managed_profile_root(browser_name: str) -> Path:
    return AUTH_DIR / f"{browser_name}-profile"


def detect_managed_browser_session() -> tuple[str, Path] | None:
    for browser_name in BROWSER_EXECUTABLE_CANDIDATES:
        profile_root = get_managed_profile_root(browser_name)
        if profile_root.exists():
            cookie_db = next(profile_root.rglob("Cookies"), None)
            if cookie_db is not None:
                return browser_name, cookie_db.parent.parent
    return None


def is_youtube_url(url: str) -> bool:
    return infer_platform_key(url) == "youtube"


def apply_youtube_extractor_args(opts: dict[str, Any], url: str) -> dict[str, Any]:
    if not is_youtube_url(url):
        return opts
    # Let yt-dlp choose current clients; forcing mweb requires a PO-token provider.
    runtimes = detect_js_runtimes()
    if not runtimes:
        raise RuntimeError("YouTube 下载需要 Deno >= 2.3 或 Node.js >= 22，请安装后重启程序。")
    if not youtube_ejs_available():
        raise RuntimeError("缺少 YouTube 解题组件，请运行 update_dependencies.ps1 后重启程序。")
    opts["js_runtimes"] = runtimes
    return opts


def youtube_ejs_available() -> bool:
    try:
        import yt_dlp_ejs
        return bool(yt_dlp_ejs)
    except ImportError:
        return False


@lru_cache(maxsize=16)
def supported_js_runtime(path: str, minimum: tuple[int, ...]) -> bool:
    try:
        result = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", result.stdout)
        return result.returncode == 0 and match is not None and tuple(map(int, match.groups())) >= minimum
    except (OSError, subprocess.SubprocessError):
        return False


def detect_js_runtimes() -> dict[str, dict[str, str]]:
    for name, minimum in (("deno", (2, 3, 0)), ("node", (22, 0, 0))):
        executable = name + (".exe" if os.name == "nt" else "")
        candidates = [root / name / executable for root in (LOCAL_TOOLS_DIR, BUNDLED_TOOLS_DIR)]
        system_path = shutil.which(name)
        if system_path:
            candidates.append(Path(system_path))
        for candidate in candidates:
            if candidate.is_file() and supported_js_runtime(str(candidate), minimum):
                return {name: {"path": str(candidate)}}
    return {}


def launch_managed_login(url: str) -> tuple[str, str]:
    platform_key = infer_platform_key(url)
    if platform_key is None:
        raise ValueError("当前链接暂不支持自动打开登录页。")

    browser = detect_browser_executable()
    if browser is None:
        webbrowser.open(LOGIN_URLS[platform_key])
        return platform_key, "default"

    browser_name, browser_path = browser
    profile_root = get_managed_profile_root(browser_name)
    profile_root.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [
            str(browser_path),
            f"--user-data-dir={profile_root}",
            "--no-first-run",
            "--disable-background-mode",
            f"--remote-debugging-port={MANAGED_DEBUG_PORT}",
            f"--remote-allow-origins=http://127.0.0.1:{MANAGED_DEBUG_PORT}",
            LOGIN_URLS[platform_key],
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    MANAGED_AUTH_PROCESS.update(
        {
            "pid": process.pid,
            "browser": browser_name,
            "platform": platform_key,
            "debug_port": MANAGED_DEBUG_PORT,
        }
    )
    return platform_key, browser_name


def export_managed_cookies_to_file() -> Path:
    if websocket is None:
        raise RuntimeError("当前环境缺少 websocket 模块，无法从专用登录窗口导出 cookies。")

    debug_port = MANAGED_AUTH_PROCESS.get("debug_port") or MANAGED_DEBUG_PORT
    platform_key = MANAGED_AUTH_PROCESS.get("platform")
    targets_url = f"http://127.0.0.1:{debug_port}/json/list"
    try:
        with urllib.request.urlopen(targets_url, timeout=5) as response:
            targets = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("无法连接专用登录窗口的调试接口，请确认登录窗口仍然打开。") from exc

    websocket_url = None
    fallback_target_url = None
    preferred_urls = COOKIE_EXPORT_URLS.get(platform_key, [])
    for preferred in preferred_urls:
        for target in targets:
            if target.get("type") != "page":
                continue
            if preferred in (target.get("url") or ""):
                websocket_url = target.get("webSocketDebuggerUrl")
                break
        if websocket_url:
            break

    if not websocket_url:
        for target in targets:
            if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                websocket_url = target.get("webSocketDebuggerUrl")
                fallback_target_url = target.get("url") or ""
                break

    if not websocket_url:
        raise RuntimeError("专用登录窗口未返回可用的调试地址。")

    ws = websocket.create_connection(websocket_url, timeout=5)
    try:
        ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
        while True:
            message = json.loads(ws.recv())
            if message.get("id") == 1:
                break

        payload = {}
        ws.send(json.dumps({"id": 2, "method": "Network.getAllCookies"}))
        while True:
            message = json.loads(ws.recv())
            if message.get("id") == 2:
                payload = message
                break

        cookies = payload.get("result", {}).get("cookies", [])
        if not cookies:
            ws.send(
                json.dumps(
                    {
                        "id": 3,
                        "method": "Network.getCookies",
                        "params": {"urls": preferred_urls or ([fallback_target_url] if fallback_target_url else [])},
                    }
                )
            )
            while True:
                message = json.loads(ws.recv())
                if message.get("id") == 3:
                    payload = message
                    break
    finally:
        ws.close()

    cookies = payload.get("result", {}).get("cookies", [])
    if not cookies:
        raise RuntimeError("未能从专用登录窗口导出 cookies，请确认已经在目标平台完成登录。")

    lines = ["# Netscape HTTP Cookie File"]
    for item in cookies:
        domain = item.get("domain") or ""
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        path = item.get("path") or "/"
        secure = "TRUE" if item.get("secure") else "FALSE"
        raw_expires = item.get("expires", 0) or 0
        try:
            expires_value = int(raw_expires)
        except (TypeError, ValueError):
            expires_value = 0
        if expires_value < 0:
            expires_value = 0
        expires = str(expires_value)
        name = item.get("name") or ""
        value = item.get("value") or ""
        lines.append("\t".join([domain, include_subdomains, path, secure, expires, name, value]))
    save_platform_cookies(platform_key, "\n".join(lines) + "\n")
    return platform_cookie_path(platform_key)


def finish_managed_login() -> bool:
    pid = MANAGED_AUTH_PROCESS.get("pid")
    if not pid:
        return False

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass

    MANAGED_AUTH_PROCESS.update({"pid": None, "browser": None, "platform": None})
    return True


def is_cookie_related_error(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in COOKIE_ERROR_MARKERS)


def is_cookie_copy_error(message: str) -> bool:
    return "could not copy chrome cookie database" in message.lower()


def is_unavailable_format_error(message: str) -> bool:
    lowered = message.lower()
    return "requested format is not available" in lowered


def ydl_base_opts() -> dict[str, Any]:
    state = dependency_state()
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "noplaylist": True,
        "color": "never",
        "cookiefile": None,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
    }
    if state["ffmpeg_path"]:
        opts["ffmpeg_location"] = str(Path(state["ffmpeg_path"]).parent)
    if state["ffmpeg_found"]:
        opts["merge_output_format"] = "mp4"
    opts["cachedir"] = str(RUNTIME_DIR / "yt-dlp-cache")
    return opts


def parse_browser_cookie_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def cookie_domains_for_url(url: str) -> list[str]:
    platform = infer_platform_key(url)
    if platform == "youtube":
        return [".youtube.com", ".google.com"]
    if platform == "x":
        return [".x.com", ".twitter.com"]
    return [PLATFORMS[platform]["cookie_domain"]] if platform else []


def cookie_domain_for_url(url: str) -> str:
    domains = cookie_domains_for_url(url)
    return domains[0] if domains else ""


def normalize_cookie_text(cookie_text: str, url: str) -> str:
    if not isinstance(cookie_text, str):
        raise ValueError("Cookie 必须是文本。")
    # Keep trailing tab separators: Netscape files can end with an empty value.
    text = cookie_text.lstrip("\ufeff").strip(" \r\n")
    if not text:
        return ""
    if "\t" in text or text.startswith("#"):
        entries = ["# Netscape HTTP Cookie File"]
        domains = [domain.lstrip(".") for domain in cookie_domains_for_url(url)]
        for line in text.splitlines():
            if not line.strip() or (line.startswith("#") and not line.startswith("#HttpOnly_")):
                continue
            fields = line.removeprefix("#HttpOnly_").split("\t")
            if (len(fields) != 7 or fields[1] not in {"TRUE", "FALSE"}
                    or fields[3] not in {"TRUE", "FALSE"} or not fields[4].isdigit()
                    or any(char.isspace() for char in fields[5])
                    or fields[0].startswith(".") != (fields[1] == "TRUE")
                    or not fields[2].startswith("/")):
                raise ValueError("Cookie 文件格式不正确，请重新导出 Netscape 格式的 cookies.txt。")
            if not fields[5]:
                # Some browser exports include nameless entries. They cannot
                # identify a session cookie and must not reject the valid ones.
                continue
            host = fields[0].lstrip(".").lower()
            if any(host == domain or host.endswith("." + domain) for domain in domains):
                entries.append(line)
        if len(entries) == 1:
            raise ValueError("Cookie 中没有当前平台的有效条目，请导出对应网站的 Cookie。")
        return "\n".join(entries) + "\n"

    raw = text
    if raw.lower().startswith("cookie:"):
        raw = raw.split(":", 1)[1].strip()

    domains = [cookie_domain_for_url(url)]
    if not domains[0]:
        return "# Netscape HTTP Cookie File\n" + text + ("\n" if not text.endswith("\n") else "")

    entries = ["# Netscape HTTP Cookie File"]
    if "\n" in raw or "\r" in raw:
        raise ValueError("请只粘贴 Cookie 请求头的值，或完整 Netscape Cookie 文件。")
    for part in raw.split(";"):
        item = part.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError("Cookie 格式不正确，请使用 name=value; name2=value2 或 Netscape 文件。")
        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        if any(char.isspace() for char in name):
            raise ValueError("Cookie 名称不正确，请重新复制 Cookie 请求头的值。")
        for domain in domains:
            entries.append("\t".join([domain, "TRUE", "/", "TRUE", "0", name, value]))
    if len(entries) == 1:
        raise ValueError("Cookie 内容为空。")
    return "\n".join(entries) + "\n"


def platform_cookie_path(platform: str) -> Path:
    if platform not in PLATFORMS:
        raise ValueError("请选择支持的平台。")
    return AUTH_DIR / "cookies" / f"{platform}.txt"


def saved_cookie_state() -> dict[str, bool]:
    return {key: platform_cookie_path(key).is_file() for key in PLATFORMS}


def save_platform_cookies(platform: str, text: str) -> None:
    path = platform_cookie_path(platform)
    normalized = normalize_cookie_text(text, "https://www." + PLATFORMS[platform]["domains"][0] + "/")
    if not normalized:
        raise ValueError("请先粘贴或导入 Cookie。")
    with COOKIES_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as fh:
                temporary = Path(fh.name)
                fh.write(normalized)
            os.replace(temporary, path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)


def resolve_cookie_text(url: str, text: str, use_saved: bool = True) -> str:
    if not isinstance(text, str):
        raise ValueError("Cookie 必须是文本。")
    if text.strip():
        return normalize_cookie_text(text, url)
    if not use_saved:
        return ""
    platform = infer_platform_key(url)
    if platform:
        with COOKIES_LOCK:
            path = platform_cookie_path(platform)
            if path.is_file():
                return normalize_cookie_text(path.read_text(encoding="utf-8-sig"), url)
    cookie_file = detect_cookie_file()
    if cookie_file:
        # Legacy combined files are read only as Netscape files with explicit domains.
        # A raw global Cookie header cannot safely be assigned to multiple platforms.
        content = cookie_file.read_text(encoding="utf-8-sig")
        if "\t" in content:
            try:
                return normalize_cookie_text(content, url)
            except ValueError:
                pass
    return ""


def request_cookie_text(payload: dict, url: str) -> str:
    text = payload.get("cookies_text", "")
    platform = payload.get("cookie_platform")
    detected = detect_cookie_platform(text, url)
    if text and detected["platform"] and detected["platform"] != infer_platform_key(url):
        raise ValueError("Cookie 所属平台与视频链接不一致，请使用对应平台的 Cookie。")
    if text and platform is not None and platform != infer_platform_key(url):
        raise ValueError("Cookie 平台与视频链接不一致，请选择对应平台的 Cookie。")
    return resolve_cookie_text(url, text, parse_browser_cookie_flag(payload.get("use_saved_cookies", True)))


def extract_with_auto_cookies(
    url: str,
    download: bool,
    extra_opts: dict[str, Any] | None = None,
    use_browser_cookies: bool = True,
    cookie_text: str = "",
    use_saved_cookies: bool = True,
) -> dict[str, Any]:
    opts = ydl_base_opts()
    if extra_opts:
        opts.update(extra_opts)
    opts = apply_youtube_extractor_args(opts, url)

    # Explicit cookies keep their original domain scopes and never enter HTTP headers.
    text = resolve_cookie_text(url, cookie_text, use_saved_cookies)
    if text:
        normalized = normalize_cookie_text(text, url)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as fh:
            fh.write(normalized)
            temp_cookie_path = fh.name
        try:
            with yt_dlp.YoutubeDL({**opts, "cookiefile": temp_cookie_path}) as ydl:
                return extract_platform_info(ydl, url, download)
        finally:
            Path(temp_cookie_path).unlink(missing_ok=True)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return extract_platform_info(ydl, url, download)
    except Exception as exc:
        if not (is_youtube_url(url) and use_browser_cookies and is_cookie_related_error(str(exc))):
            raise
        original_exc = exc

    browsers = list(BROWSER_COOKIE_CANDIDATES)
    managed_session = detect_managed_browser_session()
    if managed_session:
        name, profile = managed_session
        browsers.insert(0, (name, str(profile), None, None))
    for browser in browsers:
        try:
            with yt_dlp.YoutubeDL({**opts, "cookiesfrombrowser": browser}) as ydl:
                return extract_platform_info(ydl, url, download)
        except Exception as exc:
            # Missing/locked browser databases must not replace the real YouTube error.
            if is_cookie_related_error(str(exc)):
                original_exc = exc
    raise original_exc


def extract_info_for_preview(url: str, use_browser_cookies: bool, cookie_text: str) -> dict[str, Any]:
    return extract_with_auto_cookies(
        url, download=False,
        extra_opts={"skip_download": True, "ignoreerrors": False, "format": None},
        use_browser_cookies=use_browser_cookies, cookie_text=cookie_text, use_saved_cookies=False,
    )


def pick_download_format(selected_format: str) -> str:
    state = dependency_state()
    if selected_format:
        return selected_format
    if state["ffmpeg_found"]:
        return "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b"
    return "b[ext=mp4]/b"


def build_download_format_candidates(url: str, selected_format: str) -> list[str | None]:
    state = dependency_state()
    candidates: list[str | None] = []
    if selected_format:
        candidates.append(selected_format)

    if is_youtube_url(url):
        candidates.append("bv*+ba/b" if state["ffmpeg_found"] else "b[ext=mp4]/b")
    elif state["ffmpeg_found"]:
        candidates.extend(
            [
                "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b",
                "bv*+ba/b",
                "bestvideo+bestaudio/best",
                "best",
                None,
            ]
        )
    else:
        candidates.extend(
            [
                "b[ext=mp4]/b",
                "best",
                None,
            ]
        )

    seen: set[str] = set()
    seen_none = False
    ordered: list[str | None] = []
    for item in candidates:
        if item is None:
            if not seen_none:
                ordered.append(None)
                seen_none = True
            continue
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def resolve_downloaded_path(info: dict[str, Any], ydl: Any | None = None) -> Path:
    # After merging, requested_downloads may still name deleted component streams.
    candidates = [info.get("filepath"), info.get("_filename")]
    candidates.extend(item.get("filepath") for item in info.get("requested_downloads") or [])
    if ydl is not None:
        candidates.append(ydl.prepare_filename(info))
    for filepath in candidates:
        if filepath and Path(filepath).is_file():
            return Path(filepath)
    raise ValueError("下载未生成最终文件，请检查合并日志后重试。")


def clean_error_text(message: str) -> str:
    message = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", message)
    return re.sub(r"([?&](?:uifid|verifyFp|fp|msToken|a_bogus|x-secsdk-web-signature|xsec_token)=)[^&\s]+",
                  r"\1[redacted]", message, flags=re.IGNORECASE)


def readable_download_error(exc: Exception, url: str) -> str:
    message = clean_error_text(str(exc))
    platform = infer_platform_key(extract_first_url(url)) if isinstance(url, str) else None
    label = PLATFORMS.get(platform, {}).get("label", "平台")
    if platform == "douyin" and "设备签名" in message:
        return message
    if (re.search(r"HTTP(?: Error)?\s+(?:403|412|418|429)\b", message, re.IGNORECASE)
            or any(marker in message.lower() for marker in ("captcha", "验证码", "风控", "验证页"))):
        return f"{label} 返回访问限制或验证要求，请在浏览器完成验证或稍后重试。详情：" + message
    if is_cookie_related_error(message):
        return f"{label} 要求新的 Cookie 或登录验证，请在 Cookie 区粘贴该平台的 Cookie / cookies.txt 后重试。详情：" + message
    if platform == "xiaohongshu" and any(marker in message.lower() for marker in ("initial state", "no video formats", "404", "461")):
        return "小红书未返回可访问的视频。请复制带 xsec_token 的完整分享链接，并更新小红书 Cookie 后重试。详情：" + message
    return message


def log_download_error(url: str, fmt: str, exc: Exception) -> None:
    with ERROR_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write("=== download error ===\n")
        fh.write(f"url: {clean_error_text(url)}\n")
        fh.write(f"format: {fmt or '<default>'}\n")
        fh.write(f"error: {clean_error_text(str(exc))}\n")
        fh.write(clean_error_text(traceback.format_exc()))
        fh.write("\n")


def simplify_formats(info: dict[str, Any], *, platform: str | None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for fmt in info.get("formats", []):
        format_id = fmt.get("format_id")
        ext = fmt.get("ext")
        vcodec = fmt.get("vcodec")
        acodec = fmt.get("acodec")
        if not format_id or not ext:
            continue
        if ext not in {"mp4", "webm", "m4a"}:
            continue
        label = fmt.get("format_note") or fmt.get("resolution") or ext
        key = f"{format_id}:{ext}:{label}"
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "format_id": format_id,
                "ext": ext,
                "label": label,
                "filesize": fmt.get("filesize") or fmt.get("filesize_approx"),
                "video": vcodec != "none",
                "audio": acodec != "none",
            }
        )
    return items if platform == "youtube" else items[:18]


def build_progress_hook(job_id: str):
    def hook(data: dict[str, Any]) -> None:
        status = data.get("status")
        if status == "downloading":
            total_bytes = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            downloaded_bytes = data.get("downloaded_bytes") or 0
            percent = 0.0
            if total_bytes:
                percent = min(100.0, max(0.0, downloaded_bytes * 100.0 / total_bytes))
            update_job(
                job_id,
                status="downloading",
                progress=round(percent, 1),
                downloaded_bytes=downloaded_bytes,
                total_bytes=total_bytes,
                speed=data.get("speed"),
                eta=data.get("eta"),
                stage="正在下载视频数据...",
            )
        elif status == "finished":
            update_job(
                job_id,
                status="processing",
                progress=100.0,
                stage="下载完成，正在合并或整理文件...",
            )

    return hook


def run_download_job(job_id: str, url: str, fmt: str, use_browser_cookies: bool, cookie_text: str, download_dir: Path | None = None, use_saved_cookies: bool = True) -> None:
    try:
        download_dir = download_dir if download_dir is not None else get_download_directory()
        final_paths: list[str] = []

        def capture_final_path(filename: str) -> None:
            final_paths.append(filename)

        base_opts = {
            "post_hooks": [capture_final_path],
            "outtmpl": str(download_dir).replace("%", "%%") + "/%(title).80B [%(id)s].%(ext)s",
            "restrictfilenames": False,
            "windowsfilenames": True,
            "progress_hooks": [build_progress_hook(job_id)],
        }
        last_exc: Exception | None = None
        info: dict[str, Any] | None = None
        format_candidates = build_download_format_candidates(url, fmt)
        for index, candidate in enumerate(format_candidates):
            try:
                if index > 0:
                    if fmt:
                        stage = f"所选格式当前不可用，正在尝试兼容格式 {index + 1}/{len(format_candidates)}..."
                    else:
                        stage = f"默认格式当前不可用，正在尝试兼容格式 {index + 1}/{len(format_candidates)}..."
                    update_job(job_id, stage=stage, error=None)

                opts = dict(base_opts)
                if candidate:
                    opts["format"] = candidate
                info = extract_with_auto_cookies(
                    url,
                    download=True,
                    extra_opts=opts,
                    use_browser_cookies=use_browser_cookies,
                    cookie_text=cookie_text,
                    use_saved_cookies=use_saved_cookies,
                )
                break
            except Exception as exc:
                last_exc = exc
                if not is_unavailable_format_error(str(exc)):
                    raise

        if info is None:
            assert last_exc is not None
            raise last_exc
        final_path = resolve_downloaded_path({**info, "filepath": final_paths[-1]} if final_paths else info)
        update_job(
            job_id,
            status="completed",
            progress=100.0,
            stage="下载完成",
            file_name=final_path.name,
            download_dir=str(download_dir),
            error=None,
        )
    except Exception as exc:
        log_download_error(url, fmt, exc)
        update_job(job_id, status="failed", stage="下载失败", error=readable_download_error(exc, url))


@app.get("/")
def index() -> str:
    return render_template("index.html", state=dependency_state())


@app.get("/api/state")
def api_state():
    return jsonify(dependency_state())


@app.post("/api/cookies")
def api_save_cookies():
    payload = request.get_json(silent=True) or {}
    try:
        text = payload.get("cookies_text", "")
        detected = detect_cookie_platform(text, payload.get("url", ""))
        platform = (detected["platform"] if len(detected["candidates"]) == 1
                    else payload.get("platform", "") or detected["platform"])
        if not platform:
            raise ValueError("无法唯一识别 Cookie 平台，请选择所属平台，或先粘贴对应视频链接。")
        if detected["candidates"] and platform not in detected["candidates"]:
            raise ValueError("所选平台与 Cookie 中的域名不一致，请选择对应平台。")
        save_platform_cookies(platform, text)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except (TypeError, OSError):
        return jsonify({"ok": False, "error": "保存失败，请确认已选择平台、Cookie 格式正确且程序目录可写。"}), 400
    return jsonify({"ok": True, "platform": platform, "saved_cookies": saved_cookie_state()})


@app.post("/api/cookies/detect")
def api_detect_cookies():
    payload = request.get_json(silent=True) or {}
    try:
        detected = detect_cookie_platform(payload.get("cookies_text", ""), payload.get("url", ""))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, **detected})


@app.delete("/api/cookies/<platform>")
def api_delete_cookies(platform: str):
    try:
        with COOKIES_LOCK:
            platform_cookie_path(platform).unlink(missing_ok=True)
    except (ValueError, OSError):
        return jsonify({"ok": False, "error": "清除失败，请确认平台和程序目录权限。"}), 400
    return jsonify({"ok": True, "saved_cookies": saved_cookie_state()})


@app.post("/api/settings")
def api_settings():
    payload = request.get_json(silent=True) or {}
    try:
        directory = validate_download_directory(payload.get("download_dir", ""))
        save_download_directory(directory)
    except (ValueError, OSError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "download_dir": str(directory)})


@app.post("/api/download-directory/choose")
def api_choose_download_directory():
    payload = request.get_json(silent=True) or {}
    initial = payload.get("download_dir")
    if not isinstance(initial, str) or not Path(initial).is_dir():
        initial = str(get_download_directory())
    try:
        selected = choose_download_directory(initial)
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "cancelled": selected is None, "download_dir": selected})


@app.get("/api/download/<job_id>")
def api_download_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        return jsonify({"ok": False, "error": "下载任务不存在"}), 404
    return jsonify({"ok": True, "job": job})


@app.post("/api/auth/start")
def api_auth_start():
    payload = request.get_json(silent=True) or {}
    try:
        url = validate_url(payload.get("url", ""))
        platform_key, browser_name = launch_managed_login(url)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    browser_label = PLATFORMS[platform_key]["label"]
    if browser_name == "default":
        message = f"已打开 {browser_label} 登录页。登录完成后回到工具重试下载。"
    else:
        message = (
            f"已使用专用 {browser_name} 登录窗口打开 {browser_label} 登录页。"
            "请在该窗口登录，完成后关闭这个登录窗口，再回到工具解析或下载。"
        )
    return jsonify({"ok": True, "message": message, "platform": platform_key, "browser": browser_name})


@app.post("/api/auth/finish")
def api_auth_finish():
    exported_path: str | None = None
    try:
        exported = export_managed_cookies_to_file()
        exported_path = str(exported)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    finished = finish_managed_login()
    if finished:
        return jsonify(
            {
                "ok": True,
                "message": f"已导出登录 cookies 到 {exported_path}，并结束专用登录浏览器进程。请等待几秒后重新解析或下载。",
            }
        )
    return jsonify({"ok": True, "message": f"已导出登录 cookies 到 {exported_path}。"})


@app.post("/api/info")
def api_info():
    payload = request.get_json(silent=True) or {}
    try:
        require_yt_dlp()
        url = validate_url(payload.get("url", ""))
        use_browser_cookies = parse_browser_cookie_flag(payload.get("use_browser_cookies"))
        cookie_text = request_cookie_text(payload, url)
        info = extract_info_for_preview(url, use_browser_cookies, cookie_text)
    except Exception as exc:
        return jsonify({"ok": False, "error": readable_download_error(exc, payload.get("url", ""))}), 400

    platform = infer_platform_key(url)
    return jsonify(
        {
            "ok": True,
            "info": {
                "title": info.get("title"),
                "uploader": info.get("uploader"),
                "duration": info.get("duration"),
                "thumbnail": info.get("thumbnail"),
                "webpage_url": info.get("webpage_url"),
                "platform": platform,
                "formats": simplify_formats(info, platform=platform),
            },
        }
    )


@app.post("/api/download")
def api_download():
    payload = request.get_json(silent=True) or {}
    try:
        require_yt_dlp()
        url = validate_url(payload.get("url", ""))
        fmt = (payload.get("format_id") or "").strip()
        use_browser_cookies = parse_browser_cookie_flag(payload.get("use_browser_cookies"))
        cookie_text = request_cookie_text(payload, url)
        directory = validate_download_directory(payload.get("download_dir", str(get_download_directory())))
        save_download_directory(directory)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    job_id = uuid.uuid4().hex
    with DOWNLOAD_JOBS_LOCK:
        DOWNLOAD_JOBS[job_id] = {
            "id": job_id,
            "status": "queued",
            "progress": 0.0,
            "stage": "任务已创建，准备开始下载...",
            "file_name": None,
            "download_dir": str(directory),
            "error": None,
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "speed": None,
            "eta": None,
            "use_browser_cookies": use_browser_cookies,
        }

    worker = threading.Thread(
        target=run_download_job,
        args=(job_id, url, fmt, use_browser_cookies, cookie_text, directory),
        kwargs={"use_saved_cookies": False},
        daemon=True,
    )
    worker.start()

    return jsonify({"ok": True, "job_id": job_id, "message": "已开始下载", "download_dir": str(directory)})


if __name__ == "__main__":
    template_path = (RESOURCE_DIR / "templates" / "index.html").resolve()
    managed_session = detect_managed_browser_session()
    print(f"[startup] RESOURCE_DIR={RESOURCE_DIR}")
    print(f"[startup] template_folder={app.template_folder}")
    print(f"[startup] template_exists={template_path.exists()} path={template_path}")
    print(f"[startup] managed_session={managed_session}")
    app.run(debug=True, use_reloader=False, host="127.0.0.1", port=5000)

