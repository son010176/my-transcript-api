from fastapi import FastAPI, HTTPException
# SỬA LỖI: Import hàm get_transcript trực tiếp từ thư viện
from youtube_transcript_api import get_transcript 
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

# Khởi tạo app FastAPI
app = FastAPI()

# SỬA LỖI: Đổi tên hàm route thành 'get_transcript_route' 
# để không bị trùng với tên hàm 'get_transcript' đã import
@app.get("/transcript/{video_id}")
async def get_transcript_route(video_id: str): 
    """
    Lấy nội dung phụ đề (transcript) từ một video YouTube.
    Ưu tiên tiếng Việt (vi), nếu không có sẽ lấy tiếng Anh (en).
    """
    try:
        # 1. Thử lấy phụ đề tiếng Việt
        # SỬA LỖI: Gọi hàm get_transcript() đã import
        transcript_list = get_transcript(video_id, languages=['vi'])
    except (TranscriptsDisabled, NoTranscriptFound):
        try:
            # 2. Nếu không có tiếng Việt, thử lấy tiếng Anh
            # SỬA LỖI: Gọi hàm get_transcript() đã import
            transcript_list = get_transcript(video_id, languages=['en'])
        except (TranscriptsDisabled, NoTranscriptFound):
            # 3. Nếu không có cả hai, báo lỗi 404
            raise HTTPException(
                status_code=404, 
                detail="Video này không có phụ đề (tiếng Việt hoặc tiếng Anh) hoặc phụ đề đã bị tắt."
            )
        except Exception as e:
            # Lỗi khác khi lấy phụ đề Anh
            raise HTTPException(status_code=500, detail=f"Lỗi máy chủ khi lấy phụ đề Anh: {str(e)}")
    except Exception as e:
        # Lỗi khác khi lấy phụ đề Việt
        raise HTTPException(status_code=500, detail=f"Lỗi máy chủ khi lấy phụ đề Việt: {str(e)}")

    # Nối tất cả các đoạn text lại thành một chuỗi dài
    full_transcript = " ".join([item['text'] for item in transcript_list])
    
    return {"video_id": video_id, "transcript": full_transcript}

@app.get("/")
async def root():
    return {"message": "Transcript API is running."}
