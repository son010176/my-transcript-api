from fastapi import FastAPI, HTTPException
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

# Khởi tạo app FastAPI
app = FastAPI()

@app.get("/transcript/{video_id}")
async def get_transcript(video_id: str):
    """
    Lấy nội dung phụ đề (transcript) từ một video YouTube.
    Ưu tiên tiếng Việt (vi), nếu không có sẽ lấy tiếng Anh (en).
    """
    try:
        # 1. Thử lấy phụ đề tiếng Việt
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['vi'])
    except (TranscriptsDisabled, NoTranscriptFound):
        try:
            # 2. Nếu không có tiếng Việt, thử lấy tiếng Anh
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
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