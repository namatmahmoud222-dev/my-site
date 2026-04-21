from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from pytube import YouTube
import os
from pathlib import Path
import shutil
from datetime import datetime
import json

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Logging file
LOG_FILE = Path("security_logs.json")

# Initialize log file if it doesn't exist
if not LOG_FILE.exists():
    with open(LOG_FILE, 'w') as f:
        json.dump([], f)

def get_client_ip(request: Request) -> str:
    """Extract client IP from request headers"""
    if "x-forwarded-for" in request.headers:
        return request.headers["x-forwarded-for"].split(",")[0].strip()
    if "x-real-ip" in request.headers:
        return request.headers["x-real-ip"]
    return request.client.host if request.client else "Unknown"

def log_access(request: Request, endpoint: str, status: str = "accessed"):
    """Log user access information"""
    try:
        ip = get_client_ip(request)
        user_agent = request.headers.get("user-agent", "Unknown")
        timestamp = datetime.now().isoformat()
        
        log_entry = {
            "timestamp": timestamp,
            "ip_address": ip,
            "endpoint": endpoint,
            "user_agent": user_agent,
            "status": status
        }
        
        # Read existing logs with timeout
        try:
            with open(LOG_FILE, 'r') as f:
                logs = json.load(f)
        except (json.JSONDecodeError, IOError):
            logs = []
        
        # Append new log (max 10000 entries to avoid huge file)
        logs.append(log_entry)
        if len(logs) > 10000:
            logs = logs[-10000:]
        
        # Write back (atomic write)
        with open(LOG_FILE, 'w') as f:
            json.dump(logs, f, indent=2)
        
        print(f"📝 Logged: {ip} accessed {endpoint}")
    except Exception as e:
        print(f"❌ Logging error: {e}")

# Middleware to log all requests
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests"""
    log_access(request, request.url.path, "request")
    response = await call_next(request)
    return response

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
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Error: index.html not found</h1><p>Make sure index.html is in the root directory</p>",
            status_code=500
        )

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
        
        print(f"🎵 Downloading: {url}")
        
        # Download using pytube
        yt = YouTube(url)
        stream = yt.streams.filter(only_audio=True).first()
        
        if not stream:
            raise Exception("No audio stream available")
        
        # Download to downloads folder
        output_path = stream.download(output_path=str(DOWNLOAD_DIR))
        audio_file = Path(output_path) / stream.default_filename
        
        title = yt.title
        # Sanitize filename to remove special characters
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
        mp3_filename = f"{safe_title}.mp3"
        mp3_path = DOWNLOAD_DIR / mp3_filename
        
        print(f"✅ Downloaded: {audio_file}")
        print(f"   Converting to MP3...")
        
        # Use ffmpeg to convert to mp3
        import subprocess
        subprocess.run([
            'ffmpeg', '-i', str(audio_file), '-q:a', '0', '-map', 'a',
            str(mp3_path), '-y'
        ], capture_output=True, check=True)
        
        # Delete original file
        if audio_file.exists():
            audio_file.unlink()
        
        print(f"✅ MP3 Created: {mp3_path}")
        print(f"   File size: {mp3_path.stat().st_size / 1024 / 1024:.2f} MB")
        
        return DownloadResponse(
            message=f"Successfully downloaded: {title}",
            filename=mp3_filename,
            status="success"
        )
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error downloading video: {str(e)}")

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

@app.get("/logs/{access_key}")
async def view_logs(access_key: str):
    """
    View security logs. 
    Access key: Change this to your secret key!
    """
    # Security: Use a secret access key
    SECRET_KEY = "ilovelujain17"
    
    if access_key != SECRET_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized access")
    
    try:
        with open(LOG_FILE, 'r') as f:
            logs = json.load(f)
        
        return {
            "total_entries": len(logs),
            "logs": logs
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading logs: {str(e)}")

@app.get("/logs-html/{access_key}")
async def view_logs_html(access_key: str):
    """
    View security logs in HTML format.
    """
    SECRET_KEY = "ilovelujain17"
    
    if access_key != SECRET_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized access")
    
    try:
        with open(LOG_FILE, 'r') as f:
            logs = json.load(f)
        
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Security Logs</title>
            <style>
                body { font-family: Arial; margin: 20px; background: #f5f5f5; }
                table { width: 100%; border-collapse: collapse; background: white; }
                th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
                th { background: #333; color: white; }
                tr:hover { background: #f9f9f9; }
                .container { max-width: 1200px; margin: 0 auto; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🔒 Security Logs</h1>
                <p>Total entries: <strong>""" + str(len(logs)) + """</strong></p>
                <table>
                    <tr>
                        <th>Timestamp</th>
                        <th>IP Address</th>
                        <th>Endpoint</th>
                        <th>User Agent</th>
                        <th>Status</th>
                    </tr>
        """
        
        for log in reversed(logs[-100:]):  # Show last 100 entries
            html_content += f"""
                    <tr>
                        <td>{log.get('timestamp', 'N/A')}</td>
                        <td><strong>{log.get('ip_address', 'Unknown')}</strong></td>
                        <td>{log.get('endpoint', 'N/A')}</td>
                        <td style="font-size: 12px; max-width: 300px; overflow: auto;">{log.get('user_agent', 'Unknown')}</td>
                        <td>{log.get('status', 'N/A')}</td>
                    </tr>
            """
        
        html_content += """
                </table>
            </div>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html_content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading logs: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
