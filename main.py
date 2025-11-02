from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import subprocess
import json
import os
import glob
import shutil
import stat
import tempfile
from typing import Optional

app = FastAPI()

# --- Configurable paths ---
# Cookie file that might be mounted into the container (read-only)
COOKIE_FILE_PATH = '/etc/secrets/cookies.txt'
# Temporary cookie jar path (writable)
COOKIE_JAR_PATH = '/tmp/yt-dlp-cookies.txt'
# Temporary output dir base
TMP_DIR = '/tmp'

# User-Agent to mimic a real browser (helps bypass some bot checks)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def prepare_cookie_file() -> Optional[str]:
    """
    If COOKIE_FILE_PATH exists, copy it to COOKIE_JAR_PATH (writable) and return that path.
    If it doesn't exist or copy fails, return None.
    This solves the issue where the original cookie file is mounted read-only but yt-dlp
    expects to be able to dump cookie updates to the same file.
    """
    try:
        if os.path.exists(COOKIE_FILE_PATH):
            # copy to tmp location (overwrite)
            shutil.copy2(COOKIE_FILE_PATH, COOKIE_JAR_PATH)
            # ensure writable by owner
            try:
                os.chmod(COOKIE_JAR_PATH, stat.S_IRUSR | stat.S_IWUSR)
            except Exception:
                pass
            return COOKIE_JAR_PATH
    except Exception:
        # best-effort: if anything fails, return None and run without cookies
        return None
    return None


def cleanup_cookie_file(path: Optional[str]):
    """
    Remove the temporary cookie jar if it exists and is the expected tmp path.
    """
    try:
        if path and path.startswith('/tmp') and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def run_subprocess(args, timeout=45):
    """
    Run subprocess with safe defaults and return (returncode, stdout, stderr).
    """
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=TMP_DIR
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        return 124, "", f"Timeout after {timeout}s"
    except Exception as e:
        return 255, "", str(e)


@app.get("/")
async def root():
    return {
        "message": "Transcript API (yt-dlp wrapper)",
        "version": "2025-11-02",
        "status": "ready"
    }


@app.get("/debug/{video_id}")
async def debug_list_subs(video_id: str):
    """
    Debug route: run yt-dlp --list-subs for the given video id and return stdout/stderr.
    """
    cookie_path = prepare_cookie_file()
    try:
        cmd = [
            "yt-dlp",
            "--no-check-certificates",
            "--user-agent", DEFAULT_USER_AGENT,
            "--list-subs",
            "--skip-download",
            "--sub-langs", "vi,en",
            f"https://www.youtube.com/watch?v={video_id}"
        ]
        if cookie_path:
            cmd = ["yt-dlp", "--no-check-certificates", "--user-agent", DEFAULT_USER_AGENT, "--list-subs", "--skip-download", "--sub-langs", "vi,en", "--cookies", cookie_path, f"https://www.youtube.com/watch?v={video_id}"]
        rc, out, err = run_subprocess(cmd, timeout=30)
        return JSONResponse(
            status_code=200 if rc == 0 else 200,
            content={
                "video_id": video_id,
                "success": rc == 0,
                "returncode": rc,
                "stdout": out,
                "stderr": err
            }
        )
    finally:
        cleanup_cookie_file(cookie_path)


@app.get("/transcript/{video_id}")
async def get_transcript(video_id: str):
    """
    Main route: ask yt-dlp to download automatic subtitles (if available),
    collect subtitle file(s) and return them in JSON.
    This is a reasonably robust approach: we let yt-dlp write subtitle files to /tmp,
    then we search for files that match the video_id prefix and return contents.
    """
    cookie_path = prepare_cookie_file()
    tmp_prefix = os.path.join(TMP_DIR, video_id)
    try:
        # Build base command
        cmd = [
            "yt-dlp",
            "--no-check-certificates",
            "--user-agent", DEFAULT_USER_AGENT,
            "--write-auto-subs",  # automatic captions
            "--skip-download",
            "--sub-langs", "vi,en",
            "--sub-format", "json3/sbv/vtt/srt",
            "--output", f"{tmp_prefix}.%(ext)s",
            f"https://www.youtube.com/watch?v={video_id}"
        ]
        if cookie_path:
            # replace with cookies param pointing to writable copy
            # note: yt-dlp supports --cookies <file>; there is no --cookiejar option
            # (the previous code used --cookiejar and caused "no such option" error)
            # so we only pass --cookies <file>
            # We construct cmd explicitly to ensure ordering/overrides are clean.
            cmd = [
                "yt-dlp",
                "--no-check-certificates",
                "--user-agent", DEFAULT_USER_AGENT,
                "--cookies", cookie_path,
                "--write-auto-subs",
                "--skip-download",
                "--sub-langs", "vi,en",
                "--sub-format", "json3/sbv/vtt/srt",
                "--output", f"{tmp_prefix}.%(ext)s",
                f"https://www.youtube.com/watch?v={video_id}"
            ]

        rc, out, err = run_subprocess(cmd, timeout=45)

        if rc != 0:
            # Return the yt-dlp stderr for debugging
            raise HTTPException(status_code=500, detail=f"yt-dlp failed. returncode={rc}. stderr: {err}")

        # Find subtitle files created by yt-dlp
        candidates = []
        for ext in ("json3", "json", "vtt", "srt", "sbv", "ttml"):
            candidates.extend(glob.glob(f"{tmp_prefix}*.{ext}"))
        # yt-dlp sometimes appends language codes, e.g. video_id.en.vtt or video_id.vi.json3
        candidates.extend(glob.glob(f"{tmp_prefix}*.*"))

        # filter unique and existing
        candidates = sorted(set(candidates))
        subtitle_results = []

        for p in candidates:
            # skip info json files, keep subtitle-like files
            if p.endswith(".info.json"):
                continue
            # read file
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    data = fh.read()
                # try to interpret json3 (json lines) if possible
                parsed = None
                if p.endswith(".json") or p.endswith(".json3"):
                    try:
                        # json3 from yt-dlp can be either a JSON array or NDJSON lines
                        parsed = json.loads(data)
                    except Exception:
                        # try NDJSON: split lines and parse each
                        items = []
                        for line in data.splitlines():
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                items.append(json.loads(line))
                            except Exception:
                                # keep raw line if JSON parsing fails
                                items.append({"raw": line})
                        parsed = items
                    subtitle_results.append({
                        "path": os.path.basename(p),
                        "ext": os.path.splitext(p)[1].lstrip("."),
                        "raw": parsed
                    })
                else:
                    # plain subtitle text formats
                    subtitle_results.append({
                        "path": os.path.basename(p),
                        "ext": os.path.splitext(p)[1].lstrip("."),
                        "raw": data
                    })
            except Exception as e:
                # ignore files we can't read
                continue

        if not subtitle_results:
            # no subtitle files found
            raise HTTPException(status_code=404, detail="No subtitle files found by yt-dlp after download.")

        # Optionally: you could convert subtitle file contents to a single transcript text here.
        return JSONResponse(
            status_code=200,
            content={
                "video_id": video_id,
                "success": True,
                "files": subtitle_results,
            }
        )
    finally:
        # cleanup cookie and temporary subtitle files (best-effort)
        try:
            cleanup_cookie_file(cookie_path)
        except Exception:
            pass
        # remove transient files created by yt-dlp matching the prefix
        try:
            for f in glob.glob(f"{tmp_prefix}*"):
                # be conservative: only delete files under /tmp
                if f.startswith("/tmp") and os.path.exists(f):
                    os.remove(f)
        except Exception:
            pass

@app.get("/metadata/{video_id}")
async def get_video_metadata(video_id: str):
    """
    Lấy metadata (tiêu đề, thumbnail, thời lượng) của video từ yt-dlp.
    """
    # CHÚ Ý: Đảm bảo các biến YTDLP_PATH, COOKIE_FILE_PATH, ... 
    # đã được định nghĩa ở đầu file main.py của bạn.
    
    # Tạo một đường dẫn tạm duy nhất cho cookiejar để tránh xung đột
    # nếu /metadata và /transcript được gọi cùng lúc
    tmp_cookie_jar = os.path.join(tempfile.gettempdir(), f'cookiejar_meta_{video_id}_{os.getpid()}.txt')
    
    # Sao chép cookie file từ secret sang /tmp/ (để yt-dlp có thể ghi)
    cookie_to_use = None
    try:
        if os.path.exists(COOKIE_FILE_PATH):
            shutil.copy2(COOKIE_FILE_PATH, tmp_cookie_jar)
            os.chmod(tmp_cookie_jar, stat.S_IRUSR | stat.S_IWUSR)
            cookie_to_use = tmp_cookie_jar
    except Exception as e:
        print(f"WARNING: Không thể sao chép cookie cho metadata: {e}")
        # Nếu không copy được, thử dùng file gốc (có thể bị read-only)
        if os.path.exists(COOKIE_FILE_PATH):
            cookie_to_use = COOKIE_FILE_PATH
    
    cmd = [
        YTDLP_PATH,
        '--no-check-certificates',
        '--user-agent', DEFAULT_USER_AGENT,
        '--print-json',  # Yêu cầu in metadata ra JSON
        '--skip-download', # Không tải video
        f'https://www.youtube.com/watch?v={video_id}'
    ]
    
    # Chỉ thêm cờ --cookies nếu chúng ta có file cookie
    if cookie_to_use:
        cmd.extend(['--cookies', cookie_to_use])

    try:
        # Chạy yt-dlp
        rc, out, err = run_subprocess(cmd, timeout=15) # Timeout ngắn hơn cho metadata

        if rc != 0:
            print(f"YT-DLP Metadata Error Stderr: {err}")
            if "sign in to confirm" in err.lower():
                raise HTTPException(status_code=403, detail="YouTube chặn lấy metadata. Cookie có thể hết hạn.")
            raise HTTPException(status_code=500, detail=f"Lỗi khi lấy metadata: {err[:200]}")

        # Parse JSON output
        metadata = json.loads(out)
        
        # Chỉ lấy các trường cần thiết
        return {
            "success": True,
            "metadata": {
                "title": metadata.get('title'),
                "thumbnail": metadata.get('thumbnail'),
                "duration_string": metadata.get('duration_string'),
                "uploader": metadata.get('uploader'),
                "upload_date": metadata.get('upload_date'),
                "view_count": metadata.get('view_count')
            }
        }

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout khi lấy metadata.")
    except json.JSONDecodeError:
        print(f"YT-DLP Metadata Raw Output: {out}")
        raise HTTPException(status_code=500, detail="Lỗi khi phân tích JSON metadata từ yt-dlp.")
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Lỗi server khi lấy metadata: {str(e)}")
    finally:
        # Dọn dẹp file cookie TẠM
        if tmp_cookie_jar and os.path.exists(tmp_cookie_jar):
            try:
                os.remove(tmp_cookie_jar)
            except Exception:
                pass