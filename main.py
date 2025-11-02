from fastapi import FastAPI, HTTPException
import subprocess
import json
import re

app = FastAPI()

@app.get("/transcript/{video_id}")
async def get_transcript_route(video_id: str): 
    """
    Lấy phụ đề bằng yt-dlp (vượt qua các hạn chế của API)
    """
    try:
        # Dùng yt-dlp để lấy phụ đề
        # --write-auto-subs: Lấy cả phụ đề tự động
        # --skip-download: Không tải video
        # --sub-langs: Ưu tiên tiếng Việt, fallback sang tiếng Anh
        result = subprocess.run(
            [
                'yt-dlp',
                '--write-auto-subs',
                '--write-subs',
                '--skip-download',
                '--sub-langs', 'vi.*,en.*',
                '--convert-subs', 'json',
                '--output', '/tmp/%(id)s.%(ext)s',
                '--print', 'after_move:filepath',
                f'https://www.youtube.com/watch?v={video_id}'
            ],
            capture_output=True,
            text=True,
            timeout=45,
            cwd='/tmp'
        )
        
        if result.returncode != 0:
            error_msg = result.stderr.lower()
            
            if 'no suitable formats' in error_msg or 'video unavailable' in error_msg:
                raise HTTPException(status_code=404, detail="Video không tồn tại hoặc bị hạn chế")
            elif 'subtitles' in error_msg or 'no subtitles' in error_msg:
                raise HTTPException(status_code=404, detail="Video này không có phụ đề")
            else:
                raise HTTPException(status_code=500, detail=f"Lỗi yt-dlp: {result.stderr[:200]}")
        
        # Tìm file phụ đề vừa tải (ưu tiên .vi.json, sau đó .en.json)
        import os
        import glob
        
        subtitle_files = []
        for pattern in [f'/tmp/{video_id}.vi*.json', f'/tmp/{video_id}.en*.json', f'/tmp/{video_id}.*.json']:
            subtitle_files.extend(glob.glob(pattern))
        
        if not subtitle_files:
            raise HTTPException(status_code=404, detail="Không tìm thấy file phụ đề sau khi tải")
        
        # Đọc file phụ đề đầu tiên (ưu tiên tiếng Việt)
        subtitle_file = sorted(subtitle_files, key=lambda x: ('vi' not in x, x))[0]
        
        with open(subtitle_file, 'r', encoding='utf-8') as f:
            subtitle_data = json.load(f)
        
        # Xử lý format JSON3 của YouTube
        full_transcript = ""
        if 'events' in subtitle_data:
            # Format JSON3
            for event in subtitle_data['events']:
                if 'segs' in event:
                    for seg in event['segs']:
                        if 'utf8' in seg:
                            full_transcript += seg['utf8'] + " "
        else:
            # Format JSON cũ
            full_transcript = " ".join([item.get('text', '') for item in subtitle_data])
        
        # Dọn dẹp files tạm
        for f in subtitle_files:
            try:
                os.remove(f)
            except:
                pass
        
        if not full_transcript.strip():
            raise HTTPException(status_code=404, detail="Phụ đề rỗng")
        
        return {
            "video_id": video_id,
            "transcript": full_transcript.strip(),
            "length": len(full_transcript)
        }
        
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout khi tải phụ đề (quá 45 giây)")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi không xác định: {str(e)}")


@app.get("/debug/{video_id}")
async def debug_transcripts(video_id: str):
    """Kiểm tra phụ đề có sẵn bằng yt-dlp"""
    try:
        result = subprocess.run(
            [
                'yt-dlp',
                '--list-subs',
                f'https://www.youtube.com/watch?v={video_id}'
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        return {
            "video_id": video_id,
            "available_subtitles": result.stdout,
            "stderr": result.stderr if result.returncode != 0 else None
        }
        
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    return {"message": "Transcript API is running with yt-dlp."}