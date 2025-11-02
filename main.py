from fastapi import FastAPI, HTTPException
import subprocess
import json
import os
import glob
import re

app = FastAPI()

def run_ytdlp_with_options(video_id: str, extra_args: list = None):
    """
    Chạy yt-dlp với các options bypass bot detection
    """
    base_args = [
        'yt-dlp',
        '--no-check-certificates',
        '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        '--extractor-args', 'youtube:player_client=android,web',
        '--write-auto-subs',
        '--skip-download',
        '--sub-langs', 'vi,en',
        # SỬA LỖI: Đổi từ --convert-subs 'json' sang --sub-format 'json3'
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
        
        # Chạy yt-dlp
        result = run_ytdlp_with_options(video_id)
        
        print(f"=== YT-DLP OUTPUT ===")
        print(f"Return code: {result.returncode}")
        print(f"Stdout: {result.stdout[:500]}")
        print(f"Stderr: {result.stderr[:500]}")
        
        if result.returncode != 0:
            error_msg = result.stderr.lower()
            
            if 'sign in to confirm' in error_msg or 'bot' in error_msg:
                raise HTTPException(
                    status_code=403, 
                    detail="YouTube chặn request từ server. Video có thể bị hạn chế vùng hoặc yêu cầu đăng nhập."
                )
            elif 'video unavailable' in error_msg or 'private video' in error_msg:
                raise HTTPException(status_code=404, detail="Video không tồn tại, bị xóa hoặc riêng tư")
            elif 'no subtitles' in error_msg or 'no automatic captions' in error_msg:
                raise HTTPException(status_code=404, detail="Video này không có phụ đề tự động")
            else:
                raise HTTPException(status_code=500, detail=f"Lỗi yt-dlp: {result.stderr[:200]}")
        
        # Tìm file phụ đề
        # SỬA LỖI: Tìm file .json3 thay vì .json
        subtitle_files = glob.glob(f'/tmp/{video_id}.*.json3')
        
        if not subtitle_files:
            # Thử tìm với pattern khác
            # SỬA LỖI: Tìm file .json3 thay vì .json
            subtitle_files = glob.glob(f'/tmp/{video_id}*.json3')
        
        if not subtitle_files:
            raise HTTPException(
                status_code=404, 
                detail="yt-dlp chạy thành công nhưng không tìm thấy file phụ đề. Video có thể không có CC."
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
        # Format JSON cũ (Dự phòng, mặc dù json3 thường dùng 'events')
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
        # Đã đồng bộ các tham số bypass bot
        result = subprocess.run(
            [
                'yt-dlp',
                '--no-check-certificates',
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                '--extractor-args', 'youtube:player_client=android,web',
                '--list-subs',
                f'https://www.youtube.com/watch?v={video_id}'
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        return {
            "video_id": video_id,
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr if result.returncode != 0 else None
        }
        
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    return {
        "message": "Transcript API with anti-bot bypass", 
        "version": "2.1", # Cập nhật version
        "status": "ready"
    }