from fastapi import FastAPI, HTTPException
from youtube_transcript_api import YouTubeTranscriptApi 
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound, NoTranscriptAvailable

app = FastAPI()

@app.get("/transcript/{video_id}")
async def get_transcript_route(video_id: str): 
    """
    Lấy nội dung phụ đề từ video YouTube.
    Hỗ trợ cả phụ đề gốc và phụ đề dịch tự động.
    """
    transcript_list = None
    used_method = ""
    
    try:
        transcript_list_obj = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # Thử các cách theo thứ tự ưu tiên
        methods = [
            # 1. Phụ đề tiếng Việt gốc
            lambda: (transcript_list_obj.find_transcript(['vi']).fetch(), "Phụ đề Việt gốc"),
            
            # 2. Dịch tự động sang tiếng Việt từ phụ đề có sẵn
            lambda: (transcript_list_obj.find_generated_transcript(['en', 'ko', 'ja', 'zh-Hans', 'zh-Hant', 'es', 'fr']).translate('vi').fetch(), "Dịch tự động sang Việt"),
            
            # 3. Phụ đề tiếng Anh gốc
            lambda: (transcript_list_obj.find_transcript(['en']).fetch(), "Phụ đề Anh gốc"),
            
            # 4. Phụ đề tự động tiếng Anh
            lambda: (transcript_list_obj.find_generated_transcript(['en']).fetch(), "Phụ đề Anh tự động"),
            
            # 5. Bất kỳ phụ đề manual nào
            lambda: (next(iter(transcript_list_obj)).fetch(), "Phụ đề manual bất kỳ"),
        ]
        
        for method in methods:
            try:
                transcript_list, used_method = method()
                print(f"✓ Thành công: {used_method}")
                break
            except (NoTranscriptFound, NoTranscriptAvailable, StopIteration):
                continue
            except Exception as e:
                print(f"✗ Lỗi: {str(e)}")
                continue
        
        if not transcript_list:
            raise HTTPException(
                status_code=404,
                detail="Video này không có phụ đề nào khả dụng hoặc phụ đề đã bị tắt."
            )
                        
    except TranscriptsDisabled:
        raise HTTPException(
            status_code=404, 
            detail="Phụ đề của video này đã bị tắt."
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi: {str(e)}")
    
    # Nối các đoạn text lại
    full_transcript = " ".join([item['text'] for item in transcript_list])
    
    return {
        "video_id": video_id, 
        "transcript": full_transcript,
        "method": used_method,
        "length": len(full_transcript)
    }


@app.get("/debug/{video_id}")
async def debug_transcripts(video_id: str):
    """Kiểm tra tất cả phụ đề có sẵn của video"""
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        manual_transcripts = []
        generated_transcripts = []
        
        # Lấy thông tin về tất cả phụ đề
        try:
            for transcript in transcript_list:
                info = {
                    "language": transcript.language,
                    "language_code": transcript.language_code,
                    "is_generated": transcript.is_generated,
                    "is_translatable": transcript.is_translatable,
                }
                
                if transcript.is_translatable:
                    # Lấy 10 ngôn ngữ dịch đầu tiên
                    info["can_translate_to"] = list(transcript.translation_languages.keys())[:10]
                
                if transcript.is_generated:
                    generated_transcripts.append(info)
                else:
                    manual_transcripts.append(info)
        except Exception as e:
            return {
                "video_id": video_id,
                "error": "Không thể lặp qua danh sách transcript",
                "raw_error": str(e)
            }
        
        return {
            "video_id": video_id,
            "has_transcripts": len(manual_transcripts) > 0 or len(generated_transcripts) > 0,
            "manual_transcripts": manual_transcripts,
            "generated_transcripts": generated_transcripts,
            "total": len(manual_transcripts) + len(generated_transcripts)
        }
        
    except TranscriptsDisabled:
        return {
            "video_id": video_id,
            "error": "Phụ đề đã bị tắt bởi chủ video"
        }
    except Exception as e:
        return {
            "video_id": video_id,
            "error": str(e),
            "type": type(e).__name__
        }


@app.get("/")
async def root():
    return {"message": "Transcript API is running."}