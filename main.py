from fastapi import FastAPI, HTTPException
import subprocess
import json
import os
import glob
import re

app = FastAPI()

@app.get("/transcript/{video_id}")
async def get_transcript_route(video_id: str): 
    """
    Lấy phụ đề bằng yt-dlp (bao gồm cả phụ đề tự động)
    """
    try:
        # Xóa các file cũ nếu có
        old_files = glob.glob(f'/tmp/{video_id}.*')
        for f in old_files:
            try:
                os.remove(f)
            except:
                pass
        
        # Dùng yt-dlp để lấy phụ đề
        # --write-auto-subs: Lấy phụ đề tự động
        # --sub-langs: Ưu tiên vi, fallback en
        # --convert-subs json: Convert sang JSON để dễ parse
        result = subprocess.run(
            [
                'yt-dlp',
                '--write-auto-subs',  # Bắt buộc có cái này!
                '--skip-download',
                '--sub-langs', 'vi,en',  # Bỏ .* để lấy chính xác
                '--convert-subs', 'json',
                '--output', f'/tmp/{video_id}',
                f'https://www.youtube.com/watch?v={video_id}'
            ],
            capture_output=True,
            text=True,
            timeout=45,
            cwd='/tmp'
        )
        
        print(f"yt-dlp stdout: {result.stdout}")
        print(f"yt-dlp stderr: {result.stderr}")
        
        if result.returncode != 0:
            error_msg = result.stderr.lower()
            
            if 'video unavailable' in error_msg or 'private video' in error_msg:
                raise HTTPException(status_code=404, detail="Video không tồn tại hoặc bị riêng tư")
            else:
                raise HTTPException(status_code=500, detail=f"Lỗi yt-dlp: {result.stderr[:300]}")
        
        # Tìm file phụ đề (ưu tiên .vi.json rồi đến .en.json)
        subtitle_files = glob.glob(f'/tmp/{video_id}.*.json')
        
        if not subtitle_files:
            raise HTTPException(
                status_code=404, 
                detail="Video này không có phụ đề tự động. yt-dlp đã chạy nhưng không tìm thấy file."
            )
        
        # Sắp xếp: ưu tiên .vi trước .en
        subtitle_file = sorted(
            subtitle_files, 
            key=lambda x: (
                '.vi.' not in x,  # vi lên đầu
                '.en.' not in x,  # en thứ 2
                x  # alphabet còn lại
            )
        )[0]
        
        print(f"Đang đọc file: {subtitle_file}")
        
        # Đọc file phụ đề
        with open(subtitle_file, 'r', encoding='utf-8') as f:
            subtitle_data = json.load(f)
        
        # Parse subtitle data
        full_transcript = ""
        
        # Format JSON3 (YouTube mới)
        if 'events' in subtitle_data:
            for event in subtitle_data['events']:
                if 'segs' in event:
                    for seg in event['segs']:
                        if 'utf8' in seg:
                            full_transcript += seg['utf8']
        # Format JSON cũ
        elif isinstance(subtitle_data, list):
            full_transcript = " ".join([item.get('text', '') for item in subtitle_data])
        else:
            raise HTTPException(status_code=500, detail="Format phụ đề không được hỗ trợ")
        
        # Dọn dẹp files
        for f in subtitle_files:
            try:
                os.remove(f)
            except:
                pass
        
        # Loại bỏ các ký tự xuống dòng thừa
        full_transcript = re.sub(r'\n+', ' ', full_transcript)
        full_transcript = full_transcript.strip()
        
        if not full_transcript:
            raise HTTPException(status_code=404, detail="Phụ đề rỗng sau khi parse")
        
        # Phát hiện ngôn ngữ từ tên file
        language = "vi" if ".vi." in subtitle_file else "en" if ".en." in subtitle_file else "unknown"
        
        return {
            "video_id": video_id,
            "transcript": full_transcript,
            "language": language,
            "length": len(full_transcript),
            "file_used": os.path.basename(subtitle_file)
        }
        
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout khi tải phụ đề (quá 45 giây)")
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Lỗi: {str(e)}")


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
            "raw_output": result.stdout,
            "has_error": result.returncode != 0,
            "error": result.stderr if result.returncode != 0 else None
        }
        
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    return {"message": "Transcript API is running with yt-dlp support for auto-generated captions."}