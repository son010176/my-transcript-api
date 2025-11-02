from fastapi import FastAPI, HTTPException
from youtube_transcript_api import YouTubeTranscriptApi 
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

app = FastAPI()

@app.get("/transcript/{video_id}")
async def get_transcript_route(video_id: str): 
    """
    Lấy nội dung phụ đề từ video YouTube.
    Hỗ trợ cả phụ đề gốc và phụ đề dịch tự động.
    """
    transcript_list = None
    
    try:
        # Sử dụng phương thức list_transcripts để có thể translate
        transcript_list_obj = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # Bước 1: Thử tìm phụ đề tiếng Việt gốc
        try:
            transcript = transcript_list_obj.find_transcript(['vi'])
            transcript_list = transcript.fetch()
            print(f"✓ Tìm thấy phụ đề tiếng Việt gốc")
        except NoTranscriptFound:
            # Bước 2: Nếu không có phụ đề Việt gốc, thử dịch tự động sang tiếng Việt
            try:
                # Lấy bất kỳ transcript nào có thể dịch được
                transcript = transcript_list_obj.find_generated_transcript(['en', 'ko', 'ja', 'zh-Hans', 'zh-Hant'])
                # Dịch sang tiếng Việt
                translated = transcript.translate('vi')
                transcript_list = translated.fetch()
                print(f"✓ Đã dịch tự động từ {transcript.language_code} sang tiếng Việt")
            except:
                # Bước 3: Thử lấy phụ đề tiếng Anh gốc
                try:
                    transcript = transcript_list_obj.find_transcript(['en'])
                    transcript_list = transcript.fetch()
                    print(f"✓ Tìm thấy phụ đề tiếng Anh gốc")
                except NoTranscriptFound:
                    # Bước 4: Lấy bất kỳ transcript nào có sẵn
                    try:
                        transcript = transcript_list_obj.find_generated_transcript(['en'])
                        transcript_list = transcript.fetch()
                        print(f"✓ Tìm thấy phụ đề tự động tiếng Anh")
                    except:
                        raise HTTPException(
                            status_code=404, 
                            detail="Video này không có phụ đề nào khả dụng."
                        )
                        
    except TranscriptsDisabled:
        raise HTTPException(
            status_code=404, 
            detail="Phụ đề của video này đã bị tắt."
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi không xác định: {str(e)}")
    
    if not transcript_list:
        raise HTTPException(status_code=500, detail="Không thể lấy transcript")
    
    # Nối các đoạn text lại
    full_transcript = " ".join([item['text'] for item in transcript_list])
    
    return {
        "video_id": video_id, 
        "transcript": full_transcript,
        "length": len(full_transcript)
    }

@app.get("/")
async def root():
    return {"message": "Transcript API is running."}


# Endpoint debug để xem video có phụ đề gì
@app.get("/debug/{video_id}")
async def debug_transcripts(video_id: str):
    """Kiểm tra tất cả phụ đề có sẵn của video"""
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        available = []
        for transcript in transcript_list:
            available.append({
                "language": transcript.language,
                "language_code": transcript.language_code,
                "is_generated": transcript.is_generated,
                "is_translatable": transcript.is_translatable,
                "translation_languages": list(transcript.translation_languages.keys())[:10] if transcript.is_translatable else []
            })
        
        return {
            "video_id": video_id,
            "available_transcripts": available
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))