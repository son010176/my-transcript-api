from fastapi import FastAPI, HTTPException
import subprocess
import json
import os
import glob
import re

app = FastAPI()

# ĐỊNH NGHĨA ĐƯỜNG DẪN COOKIE (KHỚP VỚI PATH TRÊN RENDER)
COOKIE_FILE_PATH = '/etc/secrets/cookies.txt'
# ĐỊNH NGHĨA ĐƯỜNG DẪN GHI COOKIE TẠM (TRONG THƯ MỤC /tmp/ CÓ THỂ GHI)
COOKIE_JAR_PATH = '/tmp/yt-dlp-cookies.txt'

def run_ytdlp_with_options(video_id: str, extra_args: list = None):
    """
    Chạy yt-dlp với các options bypass bot detection
    """
    base_args = [
        'yt-dlp',
        '--no-check-certificates',
        '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        
        # SỬA LỖI #2: Xóa cờ --extractor-args 'youtube:player_client=android,web' vì nó xung đột với --cookies
        
        # SỬA LỖI #1:
        # --cookies: Đọc cookie từ file bí mật (Read-only)
        '--cookies', COOKIE_FILE_PATH,
        # --cookiejar: Ghi cookie mới vào file tạm (Writable)
        '--cookiejar', COOKIE_JAR_PATH, 
        
        '--write-auto-subs',
        '--skip-download',
        '--sub-langs', 'vi,en',
        '--sub-format', 'json3', 
        '--output', f'/tmp/{video_id}',
        f'https://www.youtube.com/watch?v={video_id}'
    ]
    
    if extra_args:
        base_args.extend(extra_args)
    
    return subprocess.run(
        base_args,
        capture_output=True,
        text=True,
        timeout=45,
        cwd='/tmp'
    )


@app.get("/transcript/{video_id}")
async def get_transcript_route(video_id: str): 
    """
    Lấy phụ đề bằng yt-dlp với bypass bot detection
    """
    try:
        # Xóa các file cũ
        old_files = glob.glob(f'/tmp/{video_id}.*')
        for f in old_files:
            try:
                os.remove(f)
            except:
                pass
        
        # Xóa file cookiejar cũ nếu có
        if os.path.exists(COOKIE_JAR_PATH):
            try:
                os.remove(COOKIE_JAR_PATH)
            except:
                pass

        # Chạy yt-dlp
        result = run_ytdlp_with_options(video_id)
        
        print(f"=== YT-DLP OUTPUT ===")
        print(f"Return code: {result.returncode}")
        print(f"Stdout: {result.stdout[:500]}")
        print(f"Stderr: {result.stderr[:500]}")
        
        if result.returncode != 0:
            error_msg = result.stderr.lower()
            
            # Lỗi OSError (Read-only) sẽ không còn, nhưng ta vẫn bắt lỗi cookie
            if 'sign in to confirm' in error_msg or 'bot' in error_msg or 'authentication' in error_msg:
                raise HTTPException(
                    status_code=403, 
                    detail="YouTube chặn request. File cookie có thể đã hết hạn hoặc không hợp lệ."
                )
            elif 'video unavailable' in error_msg or 'private video' in error_msg:
                raise HTTPException(status_code=404, detail="Video không tồn tại, bị xóa hoặc riêng tư")
            elif 'no subtitles' in error_msg or 'no automatic captions' in error_msg:
                # Bắt lỗi này sau khi debug
                if 'c0xppyWRqHs has no automatic captions' in result.stdout:
                     raise HTTPException(status_code=404, detail="Video này không có phụ đề (kể cả tự động).")
                raise HTTPException(status_code=404, detail="Video này không có phụ đề tự động (vi/en).")
            else:
                raise HTTPException(status_code=500, detail=f"Lỗi yt-dlp: {result.stderr[:200]}")
        
        # Đã bắt lỗi 'no automatic captions' ở trên, 
        # nhưng nếu stdout không có mà stderr cũng không báo, ta kiểm tra file
        
        # Tìm file phụ đề
        subtitle_files = glob.glob(f'/tmp/{video_id}.*.json3')
        
        if not subtitle_files:
            subtitle_files = glob.glob(f'/tmp/{video_id}*.json3')
        
        if not subtitle_files:
            raise HTTPException(
                status_code=404, 
                detail="yt-dlp chạy thành công nhưng không tìm thấy file phụ đề. Video có thể không có CC (vi/en)."
            )
        
        # Ưu tiên .vi.json3 trước .en.json3
        subtitle_file = sorted(
            subtitle_files, 
            key=lambda x: ('.vi.' not in x, '.en.' not in x, x)
        )[0]
        
        print(f"Đọc file: {subtitle_file}")
        
        # Đọc và parse
        with open(subtitle_file, 'r', encoding='utf-8') as f:
            subtitle_data = json.load(f)
        
        full_transcript = ""
        
        # Format JSON3 (YouTube)
        if 'events' in subtitle_data:
            for event in subtitle_data['events']:
                if 'segs' in event:
                    for seg in event['segs']:
                        if 'utf8' in seg:
                            full_transcript += seg['utf8']
        elif isinstance(subtitle_data, list):
            full_transcript = " ".join([item.get('text', '') for item in subtitle_data])
        else:
            raise HTTPException(status_code=500, detail="Format phụ đề không nhận dạng được (không phải json3)")
        
        # Cleanup
        for f in subtitle_files:
            try:
                os.remove(f)
            except:
                pass
        
        # Normalize text
        full_transcript = re.sub(r'\n+', ' ', full_transcript).strip()
        
        if not full_transcript:
            raise HTTPException(status_code=404, detail="Phụ đề rỗng")
        
        language = "vi" if ".vi." in subtitle_file else "en" if ".en." in subtitle_file else "unknown"
        
        return {
            "video_id": video_id,
            "transcript": full_transcript,
            "language": language,
            "length": len(full_transcript)
        }
        
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout (quá 45 giây)")
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Lỗi: {str(e)}")


@app.get("/debug/{video_id}")
async def debug_transcripts(video_id: str):
    """Debug: xem phụ đề có sẵn"""
    try:
        result = subprocess.run(
            [
                'yt-dlp',
                '--no-check-certificates',
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                
                # SỬA LỖI #2: Xóa cờ --extractor-args
                
                # SỬA LỖI #1:
                '--cookies', COOKIE_FILE_PATH,
                '--cookiejar', COOKIE_JAR_PATH,
                
                '--list-subs',
                f'https://www.youtube.com/watch?v={video_id}'
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # Lỗi `OSError` sẽ không còn nữa vì `yt-dlp` sẽ không crash.
        # Nó sẽ thoát với code 0 (nếu thành công) hoặc 1 (nếu có lỗi logic như không có sub).
        
        return {
            "video_id": video_id,
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr if result.returncode != 0 else None
        }
        
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout")
    except Exception as e:
        # Bắt các lỗi khác (ví dụ: subprocess không chạy được)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    return {
        "message": "Transcript API with anti-bot bypass and cookie support", 
        "version": "3.1", # Cập nhật version
        "status": "ready"
    }