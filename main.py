from fastapi import FastAPI, HTTPException
from youtube_transcript_api import YouTubeTranscriptApi 
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

app = FastAPI()

@app.get("/transcript/{video_id}")
async def get_transcript_route(video_id: str): 
    """
    Lấy nội dung phụ đề từ video YouTube.
    Tương thích với cả phiên bản cũ và mới của youtube-transcript-api
    """
    transcript_list = None
    
    try:
        # Thử phương thức của phiên bản mới (v0.6.0+)
        if hasattr(YouTubeTranscriptApi, 'get_transcript'):
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['vi'])
        # Nếu không có, dùng phương thức của phiên bản cũ
        elif hasattr(YouTubeTranscriptApi, 'list_transcripts'):
            transcript_obj = YouTubeTranscriptApi.list_transcripts(video_id)
            transcript = transcript_obj.find_transcript(['vi'])
            transcript_list = transcript.fetch()
        else:
            raise HTTPException(status_code=500, detail="Phiên bản thư viện không được hỗ trợ")
            
    except (TranscriptsDisabled, NoTranscriptFound):
        try:
            # Thử lấy phụ đề tiếng Anh
            if hasattr(YouTubeTranscriptApi, 'get_transcript'):
                transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
            elif hasattr(YouTubeTranscriptApi, 'list_transcripts'):
                transcript_obj = YouTubeTranscriptApi.list_transcripts(video_id)
                transcript = transcript_obj.find_transcript(['en'])
                transcript_list = transcript.fetch()
                
        except (TranscriptsDisabled, NoTranscriptFound):
            raise HTTPException(
                status_code=404, 
                detail="Video này không có phụ đề (tiếng Việt hoặc tiếng Anh) hoặc phụ đề đã bị tắt."
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Lỗi khi lấy phụ đề Anh: {str(e)}")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi lấy phụ đề Việt: {str(e)}")
    
    if not transcript_list:
        raise HTTPException(status_code=500, detail="Không thể lấy transcript")
    
    # Nối các đoạn text lại
    full_transcript = " ".join([item['text'] for item in transcript_list])
    
    return {"video_id": video_id, "transcript": full_transcript}

@app.get("/")
async def root():
    return {"message": "Transcript API is running."}