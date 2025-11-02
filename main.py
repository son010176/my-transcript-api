from fastapi import FastAPI, HTTPException
from youtube_transcript_api import YouTubeTranscriptApi 
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

app = FastAPI()

@app.get("/transcript/{video_id}")
async def get_transcript_route(video_id: str): 
    try:
        # Thử lấy phụ đề tiếng Việt
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['vi'])
    except (TranscriptsDisabled, NoTranscriptFound):
        try:
            # Nếu không có tiếng Việt, thử lấy tiếng Anh
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
        except (TranscriptsDisabled, NoTranscriptFound):
            raise HTTPException(
                status_code=404, 
                detail="Video này không có phụ đề (tiếng Việt hoặc tiếng Anh) hoặc phụ đề đã bị tắt."
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Lỗi máy chủ khi lấy phụ đề Anh: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi máy chủ khi lấy phụ đề Việt: {str(e)}")

    full_transcript = " ".join([item['text'] for item in transcript_list])
    
    return {"video_id": video_id, "transcript": full_transcript}

@app.get("/")
async def root():
    return {"message": "Transcript API is running."}