from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
import os
from pathlib import Path
import shutil

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directory to store downloaded MP3s
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

class YouTubeURL(BaseModel):
    url: str

class DownloadResponse(BaseModel):
    message: str
    filename: str
    status: str

def cleanup_file(filepath: str):
    """Clean up downloaded file after a delay"""
    if os.path.exists(filepath):
        os.remove(filepath)

@app.get("/")
async def root():
    """Serve the HTML interface"""
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.post("/download", response_model=DownloadResponse)
async def download_mp3(youtube_data: YouTubeURL, background_tasks: BackgroundTasks):
    """
    Download a YouTube video and convert it to MP3.
    
    Example request:
    {
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    }
    """
    try:
        url = youtube_data.url
        
        # Validate URL
        if "youtube.com" not in url and "youtu.be" not in url:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL")
        
        # Configure yt-dlp options
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': str(DOWNLOAD_DIR / '%(title)s'),
            'quiet': False,
            'no_warnings': False,
            'progress_hooks': [progress_hook],
        }
        
        # Download and convert to MP3
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info['title']
        
        # Find the actual MP3 file that was created
        import time
        time.sleep(2)  # Wait a bit for file to finish writing
        
        mp3_files = list(DOWNLOAD_DIR.glob("*.mp3"))
        
        if not mp3_files:
            raise Exception(f"MP3 file not found after conversion. Check FFmpeg installation.")
        
        # Get the most recently modified file (should be the converted MP3)
        mp3_file = max(mp3_files, key=lambda p: p.stat().st_mtime)
        filename = mp3_file.name
        
        print(f"✅ MP3 Created: {mp3_file}")
        print(f"   Full path: {mp3_file.absolute()}")
        print(f"   File size: {mp3_file.stat().st_size / 1024 / 1024:.2f} MB")
        
        # Don't auto-delete - let user manage files
        # background_tasks.add_task(cleanup_file, str(mp3_file))
        
        return DownloadResponse(
            message=f"Successfully downloaded: {title}",
            filename=filename,
            status="success"
        )
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error downloading video: {str(e)}")

def progress_hook(d):
    """Progress hook for yt-dlp"""
    if d['status'] == 'downloading':
        percent = d.get('_percent_str', 'N/A')
        print(f"Downloading: {percent}")
    elif d['status'] == 'finished':
        print(f"Download finished, now converting to MP3...")
    elif d['status'] == 'error':
        print(f"Error: {d.get('_error_str', 'Unknown error')}")

@app.get("/download/{filename}")
async def get_mp3(filename: str):
    """
    Download the MP3 file.
    """
    # Decode URL-encoded filename
    from urllib.parse import unquote
    filename = unquote(filename)
    
    filepath = DOWNLOAD_DIR / filename
    
    print(f"Download request for: {filename}")
    print(f"Full path: {filepath}")
    print(f"Exists: {filepath.exists()}")
    
    if not filepath.exists():
        print(f"❌ File not found: {filepath}")
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    
    return FileResponse(
        path=filepath,
        media_type='audio/mpeg',
        filename=filename
    )

@app.get("/list")
async def list_downloads():
    """
    List all available MP3 files.
    """
    mp3_files = list(DOWNLOAD_DIR.glob("*.mp3"))
    return {
        "count": len(mp3_files),
        "files": [f.name for f in mp3_files]
    }

@app.delete("/cleanup")
async def cleanup_downloads():
    """
    Delete all downloaded files.
    """
    try:
        shutil.rmtree(DOWNLOAD_DIR)
        DOWNLOAD_DIR.mkdir(exist_ok=True)
        return {"message": "All files cleaned up", "status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error cleaning up: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
