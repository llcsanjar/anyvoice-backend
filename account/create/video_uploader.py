# backend/account/create/video_uploader.py

import os
import subprocess
import json
from typing import List, Dict
import asyncio
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, File, Form, UploadFile
from bson import ObjectId
import datetime
import string
import random
import base64
import shutil
from menu.menu import client, notifications_collection, users_collection, followers_collection, videos_collection, videos_fs, \
users_fs
from home.home import encrypt_data, serialize_notification, broadcast_notification
from dotenv import load_dotenv

router = APIRouter()

load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

# Конфигуратсия барои HLS
HLS_STORAGE_PATH = os.getenv("HLS_STORAGE_PATH", "hls_videos")
UPLOAD_TEMP_PATH = os.getenv("UPLOAD_TEMP_PATH", "temp_uploads")

# Эҷоди директорияҳо агар вуҷуд надошта бошанд
os.makedirs(HLS_STORAGE_PATH, exist_ok=True)
os.makedirs(UPLOAD_TEMP_PATH, exist_ok=True)

print(f"✅ HLS Storage Path: {os.path.abspath(HLS_STORAGE_PATH)}")
print(f"✅ Upload Temp Path: {os.path.abspath(UPLOAD_TEMP_PATH)}")

# Барои нигоҳдории прогресси видеоҳо
upload_progress: Dict[str, float] = {}
cancelled_uploads: set = set()
processing_status: Dict = {}

@router.websocket("/ws/upload-progress-for-video/{upload_id}")
async def websocket_upload_progress(websocket: WebSocket, upload_id: str):
    await websocket.accept()
    try:
        if not upload_id:
            await websocket.send_text("0")
            return

        last_progress = -1
        idle_counter = 0

        while True:
            progress = upload_progress.get(upload_id, 0)

            if progress != last_progress or idle_counter >= 10:
                await websocket.send_text(json.dumps({
                    "type": "progress",
                    "value": float(f"{progress:.2f}")
                }))
                last_progress = progress
                idle_counter = 0
            else:
                # ⬇ send ping to keep connection alive
                await websocket.send_text(json.dumps({
                    "type": "ping"
                }))
                idle_counter += 1

            if progress >= 100 or upload_id in cancelled_uploads:
                break

            await asyncio.sleep(.1)  # every 0.1 second, lightweight

    except WebSocketDisconnect:
        print(f"🔌 WebSocket disconnected: {upload_id}")
    except Exception as e:
        print(f"❌ WebSocket error for {upload_id}: {str(e)}")
    finally:
        try:
            await websocket.close()
        except:
            pass

# Сифатҳои дастгиришаванда
SUPPORTED_QUALITIES = [
    {'name': '360p', 'height': 360, 'bitrate': '800k'},
    {'name': '480p', 'height': 480, 'bitrate': '1500k'},
    {'name': '720p', 'height': 720, 'bitrate': '2500k'}
]

def check_ffmpeg():
    """Санҷиши насб будани ffmpeg"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("✅ FFmpeg is installed")
            return True
        else:
            print("❌ FFmpeg is not installed or not in PATH")
            return False
    except Exception as e:
        print(f"❌ FFmpeg check failed: {e}")
        return False

# Санҷиши ffmpeg дар вақти боркунии модул
FFMPEG_AVAILABLE = check_ffmpeg()

def allowed_video_file(filename: str) -> bool:
    """Санҷиши формати видео"""
    ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm', 'm4v', 'mpg', 'mpeg', 'wmv', 'flv'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_video_info(input_path: str) -> dict:
    """Гирифтани маълумот дар бораи видео (андоза ва давомнокӣ)"""
    if not os.path.exists(input_path):
        print(f"❌ Video file not found: {input_path}")
        return {'width': 1920, 'height': 1080, 'duration': 0, 'bitrate': 0}
    
    cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,duration,bit_rate',
        '-of', 'json', input_path
    ]
    try:
        print(f"🔍 Getting video info for: {input_path}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            print(f"❌ ffprobe error: {result.stderr}")
            return {'width': 1920, 'height': 1080, 'duration': 0, 'bitrate': 0}
        
        data = json.loads(result.stdout)
        stream = data['streams'][0]
        
        info = {
            'width': int(stream.get('width', 1920)),
            'height': int(stream.get('height', 1080)),
            'duration': float(stream.get('duration', 0)),
            'bitrate': int(stream.get('bit_rate', 0))
        }
        print(f"✅ Video info: {info}")
        return info
        
    except Exception as e:
        print(f"❌ Error getting video info: {e}")
        return {'width': 1920, 'height': 1080, 'duration': 0, 'bitrate': 0}

def calculate_scale_params(original_width: int, original_height: int, target_height: int) -> str:
    """Ҳисоб кардани параметрҳои scale барои нигоҳ доштани таносуби аслӣ"""
    if original_height <= target_height:
        return "scale=-2:-2"
    return f"scale=-2:{target_height}"

def format_duration(seconds: int) -> str:
    """Формат кардани давомнокӣ ба HH:MM:SS ё MM:SS"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours:02}:{minutes:02}:{secs:02}"
    else:
        return f"{minutes:02}:{secs:02}"

def process_video_to_hls(input_path: str, video_id: str, post_hls_dir: str, upload_id: str, video_index: int, total_videos: int):
    """Табдил додани видео ба HLS бо се сифат"""
    try:
        print(f"🎬 Starting HLS processing for video: {video_id}")
        print(f"📁 Input path: {input_path}")
        print(f"📁 Output dir: {post_hls_dir}")
        
        # Эҷоди директория барои ин видео
        video_hls_dir = os.path.join(post_hls_dir, video_id)
        os.makedirs(video_hls_dir, exist_ok=True)
        print(f"✅ Created video HLS dir: {video_hls_dir}")
        
        # Гирфтани маълумоти видео
        video_info = get_video_info(input_path)
        original_width = video_info['width']
        original_height = video_info['height']
        duration = video_info['duration']
        
        if duration == 0:
            print(f"⚠️ Warning: Could not determine video duration")
            duration = 60
        
        # Муайян кардани самти видео
        is_vertical = original_height > original_width
        
        # Табдили давомнокӣ ба сонияҳо
        duration_seconds = int(duration)
        video_duration = format_duration(duration_seconds)
        
        processing_status[video_id] = {
            'status': 'processing',
            'progress': 0,
            'duration': duration,
            'orientation': 'vertical' if is_vertical else 'horizontal',
            'original_width': original_width,
            'original_height': original_height,
            'qualities': {}
        }
        
        # Эҷоди файли мастер
        master_playlist = "#EXTM3U\n#EXT-X-VERSION:3\n"
        
        # Ҳисобкунии вазни ҳар як сифат
        # 4% барои коркарди видео (аз 96% то 100%)
        quality_weights = {
            '360p': (0, 33),    # 0% → 33% аз 4%
            '480p': (33, 66),   # 33% → 66% аз 4%
            '720p': (66, 100)   # 66% → 100% аз 4%
        }
        
        # Табдил ба ҳар сифат
        for idx, quality in enumerate(SUPPORTED_QUALITIES):
            quality_dir = os.path.join(video_hls_dir, quality['name'])
            os.makedirs(quality_dir, exist_ok=True)
            
            playlist_path = os.path.join(quality_dir, 'playlist.m3u8')
            
            # Ҳисоб кардани scale filter
            scale_filter = calculate_scale_params(original_width, original_height, quality['height'])
            
            cmd = [
                'ffmpeg', '-i', input_path,
                '-c:v', 'libx264',
                '-c:a', 'aac',
                '-b:v', quality['bitrate'],
                '-maxrate', quality['bitrate'],
                '-bufsize', str(int(quality['bitrate'].replace('k', '')) * 2) + 'k',
                '-vf', scale_filter,
                '-hls_time', '6',
                '-hls_list_size', '0',
                '-hls_segment_filename', os.path.join(quality_dir, 'segment_%03d.ts'),
                '-hls_flags', 'independent_segments',
                '-f', 'hls',
                '-y',
                playlist_path
            ]
            
            print(f"🎬 Processing quality {quality['name']}...")
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            start, end = quality_weights[quality['name']]
            
            # Хондани stderr барои прогресс
            for line in process.stderr:
                if "time=" in line:
                    try:
                        time_str = line.split("time=")[1].split()[0]
                        h, m, s = time_str.split(':')
                        current_time = int(h) * 3600 + int(m) * 60 + float(s)
                        if duration > 0:
                            quality_progress = (current_time / duration) * 100
                            progress_in_quality = (quality_progress / 100) * (end - start)
                            mapped_progress = start + progress_in_quality
                            
                            # Ҳисобкунии прогресси умумӣ
                            # 96% + прогресси видео (макс 4% барои ҳар видео)
                            base_progress = 96.0 + (video_index * 4.0 / total_videos)
                            total_progress = base_progress + (mapped_progress * 4.0 / (total_videos * 100))
                            
                            upload_progress[upload_id] = min(total_progress, 99.9)
                            processing_status[video_id]['qualities'][quality['name']] = quality_progress
                    except:
                        pass
            
            process.wait()
            
            if process.returncode != 0:
                raise Exception(f"FFmpeg failed for quality {quality['name']}")

            print(f"✅ Completed quality {quality['name']}")
            
            # Муайян кардани андозаи ниҳоӣ барои мастер плейлист
            calculated_width = int((quality['height'] / original_height) * original_width) if original_height > 0 else quality['height']
            resolution = f"{calculated_width}x{quality['height']}"
            
            master_playlist += f"\n#EXT-X-STREAM-INF:BANDWIDTH={int(quality['bitrate'].replace('k',''))*1000},RESOLUTION={resolution}\n"
            master_playlist += f"{quality['name']}/playlist.m3u8\n"
        
        # Навиштани мастер плейлист
        master_path = os.path.join(video_hls_dir, 'master.m3u8')
        with open(master_path, 'w') as f:
            f.write(master_playlist)

        print(f"✅ Created master playlist: {master_path}")

        # Сохтани thumbnail аз видеои аввал
        thumbnail_cmd = [
            'ffmpeg',
            '-i', input_path,
            '-ss', '00:00:01',
            '-vframes', '1',
            '-f', 'image2pipe',
            '-vcodec', 'mjpeg',
            'pipe:1'
        ]

        print(f"🎬 Creating thumbnail...")
        result = subprocess.run(thumbnail_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        thumbnail_id = None

        if result.returncode == 0 and result.stdout:
            try:
                thumbnail_id = videos_fs.put(result.stdout, filename=f"{video_id}_thumbnail.jpg")
                print(f"✅ Thumbnail saved to DB: {thumbnail_id}")
            except Exception as e:
                print(f"❌ Failed to save thumbnail to DB: {e}")

        processing_status[video_id]['status'] = 'completed'
        processing_status[video_id]['progress'] = 100
        processing_status[video_id]['duration_formatted'] = video_duration
        processing_status[video_id]['thumbnail_id'] = str(thumbnail_id) if thumbnail_id else None
        processing_status[video_id]['master_url'] = f"/hls/{os.path.basename(post_hls_dir)}/{video_id}/master.m3u8"
        
        print(f"✅ HLS processing completed for video: {video_id}")
        return True
        
    except Exception as e:
        print(f"❌ Error processing video {video_id}: {e}")
        import traceback
        traceback.print_exc()
        processing_status[video_id]['status'] = 'error'
        processing_status[video_id]['error'] = str(e)
        raise

@router.post("/check-link-video")
async def check_link_video(link_data: dict):
    client.admin.command('ping')

    link = link_data.get("link")
    requester_id = link_data.get("user_id")

    if not link:
        raise HTTPException(status_code=400, detail="Link is required")

    video = videos_collection.find_one({"Link": link})
    if not video:
        raise HTTPException(status_code=406, detail="Link is wrong")

    if requester_id and ObjectId.is_valid(requester_id):
        block_list = video.get("BlockUsersList", [])
        block_object_ids = [
            ObjectId(uid) for uid in block_list if ObjectId.is_valid(str(uid))
        ]
        if ObjectId(requester_id) in block_object_ids:
            raise HTTPException(status_code=403, detail="Access denied: You are blocked from viewing this post")

    video_id = str(video["_id"])
    video_user_id = str(video["UserId"])
    visibility = video.get("Visibility", "public").lower()

    user_info = users_collection.find_one({'_id': ObjectId(video_user_id)})
    if not user_info:
        raise HTTPException(status_code=405, detail="User not found")

    username = user_info['Username']
    display = user_info.get('Display', '')

    profile_image_id = user_info.get("ProfileImageId")
    avatar_base64 = ''
    if profile_image_id:
        try:
            file_avatar = users_fs.get(ObjectId(profile_image_id))
            avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
        except Exception as e:
            pass

    return {
        "exists": True,
        "video_id": video_id,
        "user_id": video_user_id,
        "avatar": avatar_base64,
        "username": username,
        "display": display,
        "video_user_id": video_user_id,
        "visibility": visibility
    }

@router.get("/post-video/{post_id}")
async def get_post(post_id: str):
    post = videos_collection.find_one({"_id": ObjectId(post_id)})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    title = post['Title']
    description = post['Description']
    decrypted_visibility = post['Visibility'].encode()
    decrypted_link = post['Link']

    first_video_base64 = ''
    thumbnail_id = post.get("ThumbnailId")
    if thumbnail_id:
        try:
            first_video_data = videos_fs.get(thumbnail_id).read()
            first_video_base64 = base64.b64encode(first_video_data).decode()
        except:
            pass

    video_ids = post.get("VideoIds", [])
    if not video_ids:
        raise HTTPException(status_code=404, detail="No videos found for this post")

    videos_data = [str(video_id) for video_id in video_ids]
    video_names = post.get("VideoNames", [])
    block_users_list = [str(uid) for uid in post.get("BlockUsersList", [])]

    return {
        "title": title,
        "description": description,
        "visibility": decrypted_visibility,
        "allow_comments": post.get("AllowComments", False),
        "advertisement_checkbox": post.get("AdvertisementCheckbox", False),
        "advertisement_count": post.get("AdvertisementCount", False),
        "collaboration_accounts": [str(uid) for uid in post.get("CollaborationAccounts", [])],
        "videos_data": videos_data,
        "first_video_base64": first_video_base64,
        "link": decrypted_link,
        "video_names": video_names,
        "video_ids": str(video_ids),
        "block_users_list": block_users_list,
    }

@router.post("/save_post_video")
async def save_post_video(
    videos: List[UploadFile] = File(...),
    user_id: str = Form(...),
    title: str = Form(""),
    description: str = Form(""),
    allow_comments: bool = Form(False),
    advertisement_count: float = Form(0),
    advertisement_checkbox: bool = Form(False),
    visibility: str = Form("public"),
    collaboration_accounts: str = Form("[]"),
    upload_id: str = Form(...),
    thumbnail: UploadFile = File(None),
):
    print(f"📥 Received upload request: upload_id={upload_id}, user_id={user_id}")
    
    client.admin.command("ping")

    if not upload_id:
        raise HTTPException(status_code=400, detail="Missing upload_id")

    if not videos:
        raise HTTPException(status_code=400, detail="No video data provided")

    if not FFMPEG_AVAILABLE:
        raise HTTPException(status_code=500, detail="FFmpeg is not installed on the server")

    upload_progress[upload_id] = 95.0
    cancelled_uploads.discard(upload_id)

    # =====================================================
    # 🔹 USER CHECK
    # =====================================================
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # =====================================================
    # 🔹 PARSE COLLABORATION ACCOUNTS
    # =====================================================
    try:
        collaboration_accounts_list = json.loads(collaboration_accounts) if collaboration_accounts else []
    except:
        collaboration_accounts_list = []

    # =====================================================
    # 🔹 ADVERTISEMENT LOGIC
    # =====================================================
    ad_count = 0

    if advertisement_checkbox and advertisement_count > 0:
        amount = advertisement_count / 100

        if user.get("Balance", 0) < amount:
            raise HTTPException(status_code=408, detail="Insufficient balance")

        users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$inc": {"Balance": -amount}}
        )

        users_collection.update_one(
            {"Username": "sanjar"},
            {"$inc": {"Balance": amount}}
        )

        ad_count = advertisement_count

    # =====================================================
    # 🔹 FILE SIZE AND FORMAT CHECK
    # =====================================================
    MAX_SIZE = 500 * 1024 * 1024  # 500MB per video

    for video in videos:
        if not allowed_video_file(video.filename):
            raise HTTPException(
                status_code=400,
                detail=f"Video {video.filename} has invalid format"
            )

        total_size = video.size

        if total_size > MAX_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"Video {video.filename} exceeds 500MB limit"
            )

    # =====================================================
    # 🔹 UNIQUE LINK
    # =====================================================
    characters = string.ascii_letters + string.digits
    while True:
        unique_link = ''.join(random.choice(characters) for _ in range(11))
        if not videos_collection.find_one({
            "Link": f"{unique_link}"
        }):
            break

    post_link = f"{unique_link}"

    # =====================================================
    # 🔹 VIDEO UPLOAD AND PROCESSING
    # =====================================================
    saved_video_ids = []
    video_names = []
    hls_videos_metadata = []
    total_videos = len(videos)

    # Эҷоди ID муваққатӣ барои пост
    temp_post_id = str(ObjectId())
    post_hls_dir = os.path.join(HLS_STORAGE_PATH, temp_post_id)
    os.makedirs(post_hls_dir, exist_ok=True)
    print(f"📁 Created post HLS directory: {post_hls_dir}")

    for idx, video in enumerate(videos):
        if not video:
            continue

        # Санҷиши бекоркунӣ
        if upload_id in cancelled_uploads:
            if os.path.exists(post_hls_dir):
                shutil.rmtree(post_hls_dir)
            upload_progress.pop(upload_id, None)
            cancelled_uploads.discard(upload_id)
            raise HTTPException(status_code=400, detail="Upload cancelled")

        video_names.append(video.filename)
        
        # Эҷоди ID барои видео
        video_id = str(ObjectId())
        saved_video_ids.append(video_id)
        
        print(f"📹 Processing video {idx+1}/{total_videos}: {video.filename} (ID: {video_id})")

        # Навсозии прогресс - Оғози боргузорӣ (95% - 96%)
        upload_progress[upload_id] = 95.0 + (idx / total_videos) * 1.0
        
        # Захираи муваққатии видео
        temp_video_path = os.path.join(UPLOAD_TEMP_PATH, f"{video_id}_{video.filename}")
        
        uploaded_size = 0
        total_size = video.size

        print(f"📊 Video size: {total_size / (1024*1024):.2f} MB")

        chunk_size = 1024 * 1024  # 1MB chunk
        
        with open(temp_video_path, "wb") as f:
            while True:
                chunk = await video.read(chunk_size)
                if not chunk:
                    break
                
                f.write(chunk)
                uploaded_size += len(chunk)
                
                # Навсозии прогресс дар вақти боргузорӣ (95% - 96%)
                if total_size > 0:
                    upload_progress[upload_id] = 95.0 + (idx / total_videos) * 1.0 + (uploaded_size / total_size) * (1.0 / total_videos)
                
                await asyncio.sleep(0)
        
        print(f"✅ Video saved to temp file: {temp_video_path}")
        
        # Навсозии прогресс - Оғози коркард (96%)
        upload_progress[upload_id] = 96.0 + (idx / total_videos) * 4.0
        
        try:
            # Коркарди видео ба HLS
            await asyncio.to_thread(
                process_video_to_hls,
                temp_video_path,
                video_id,
                post_hls_dir,
                upload_id,
                idx,
                total_videos
            )

            # Нест кардани файли муваққатӣ
            if os.path.exists(temp_video_path):
                os.remove(temp_video_path)
                print(f"🗑️ Removed temp file: {temp_video_path}")
            
            # Санҷиши натиҷаи коркард
            if video_id in processing_status and processing_status[video_id]['status'] == 'completed':
                video_meta = {
                    'video_id': video_id,
                    'master_url': f"/hls/{temp_post_id}/{video_id}/master.m3u8",
                    'duration': processing_status[video_id]['duration_formatted'],
                    'orientation': processing_status[video_id]['orientation'],
                    'thumbnail_id': processing_status[video_id].get('thumbnail_id'),
                    'qualities': ['360p', '480p', '720p']
                }
                hls_videos_metadata.append(video_meta)
                print(f"✅ Video {idx+1} processed successfully")
            else:
                raise Exception(f"Video processing failed for {video.filename}")
                
        except Exception as e:
            print(f"❌ Failed to process video {video.filename}: {e}")
            if os.path.exists(temp_video_path):
                os.remove(temp_video_path)
            if os.path.exists(post_hls_dir):
                shutil.rmtree(post_hls_dir)
            raise HTTPException(status_code=500, detail=f"Failed to process video {video.filename}: {str(e)}")

    upload_progress[upload_id] = 99.0

    # =====================================================
    # 🔹 THUMBNAIL UPLOAD
    # =====================================================
    thumbnail_id = None
    if thumbnail:
        content = await thumbnail.read()
        thumbnail_id = videos_fs.put(content, filename=thumbnail.filename)
        print(f"✅ Thumbnail uploaded: {thumbnail_id}")

    upload_progress[upload_id] = 99.5

    # =====================================================
    # 🔹 SAVE POST METADATA TO MONGODB
    # =====================================================
    
    video_duration = None
    if len(hls_videos_metadata) == 1:
        video_duration = hls_videos_metadata[0]['duration']
    
    post_doc = {
        "UserId": ObjectId(user_id),
        "VideoIds": saved_video_ids,
        "VideoNames": video_names,
        "HLSVideos": hls_videos_metadata,
        "HLSStoragePath": post_hls_dir,
        "Title": title or datetime.datetime.now(datetime.timezone.utc).strftime("%d/%m/%Y"),
        "Description": description,
        "AllowComments": allow_comments,
        "Visibility": visibility,
        "AdvertisementCheckbox": advertisement_checkbox,
        "AdvertisementCount": int(ad_count),
        "CollaborationAccounts": [],
        "Link": post_link,
        "UploadAt": datetime.datetime.now(datetime.timezone.utc),
        "CountSupport": 0,
        "CountComment": 0,
        "CountShare": 0,
        "CountSave": 0,
        "CountView": 0,
        "VideoDuration": video_duration,
        "VideoCount": len(saved_video_ids)
    }

    if thumbnail_id:
        post_doc["ThumbnailId"] = thumbnail_id

    post_id = videos_collection.insert_one(post_doc).inserted_id
    print(f"✅ Post saved to MongoDB with ID: {post_id}")

    # Навсозии папка бо ID-и пост
    final_post_hls_dir = os.path.join(HLS_STORAGE_PATH, str(post_id))
    if os.path.exists(post_hls_dir):
        shutil.move(post_hls_dir, final_post_hls_dir)
        post_hls_dir = final_post_hls_dir
        print(f"📁 Renamed post HLS directory to: {final_post_hls_dir}")
        
        for video_meta in hls_videos_metadata:
            video_meta['master_url'] = f"/hls/{post_id}/{video_meta['video_id']}/master.m3u8"
        
        videos_collection.update_one(
            {"_id": post_id},
            {"$set": {"HLSVideos": hls_videos_metadata, "HLSStoragePath": str(final_post_hls_dir)}}
        )

    users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$inc": {"CountPosts": 1, "CountVideos": 1}}
    )

    upload_progress[upload_id] = 99.9

    # =====================================================
    # 🔹 COLLABORATION NOTIFICATIONS
    # =====================================================
    encrypted_collaboration_message = encrypt_data(
        f"@{user.get('Username')} invited you to a new collaboration. View post: https://www.anyvoice.world/video/{post_link}",
        ENCRYPTION_KEY
    )

    encrypted_collaboration_type = encrypt_data("collaboration", ENCRYPTION_KEY)

    for account_id in collaboration_accounts_list:
        if ObjectId.is_valid(account_id):
            notification_doc = {
                "NotificationFrom": ObjectId(user_id),
                "NotificationTo": ObjectId(account_id),
                "Message": encrypted_collaboration_message,
                "PostId": post_id,
                "IsRead": False,
                "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
                "Type": encrypted_collaboration_type,
                "status": "pending"
            }

            notifications_collection.insert_one(notification_doc)
            serialized_notification = serialize_notification(notification_doc)
            await broadcast_notification(str(account_id), "add", serialized_notification)

    # =====================================================
    # 🔹 FOLLOWER NOTIFICATIONS
    # =====================================================
    if visibility == "public":
        followers = followers_collection.find({"target_user_id": ObjectId(user_id)})

        encrypted_follower_message = encrypt_data(
            f"@{user.get('Username')} added a new post. View post: https://www.anyvoice.world/video/{post_link}",
            ENCRYPTION_KEY
        )

        encrypted_follower_type = encrypt_data("new_post", ENCRYPTION_KEY)

        for follower in followers:
            follower_id = follower["follower_id"]

            if follower_id != ObjectId(user_id):
                notification_doc = {
                    "NotificationFrom": ObjectId(user_id),
                    "NotificationTo": follower_id,
                    "Message": encrypted_follower_message,
                    "PostId": post_id,
                    "IsRead": False,
                    "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
                    "Type": encrypted_follower_type,
                    "status": "pending"
                }

                notifications_collection.insert_one(notification_doc)
                serialized_notification = serialize_notification(notification_doc)
                await broadcast_notification(str(follower_id), "add", serialized_notification)

    # =====================================================
    # 🔹 FINALIZE
    # =====================================================
    upload_progress[upload_id] = 100.0
    upload_progress.pop(upload_id, None)
    cancelled_uploads.discard(upload_id)

    print(f"✅ Upload completed successfully: post_id={post_id}")

    return {
        "status": "success",
        "message": "Post added successfully",
        "post_id": str(post_id),
        "post_link": unique_link
    }

def process_video_to_hls_update(input_path: str, video_id: str, post_hls_dir: str, upload_id: str, 
                                video_index: int, total_videos: int, base_progress: float, total_progress_range: float):
    """Табдил додани видео ба HLS барои update бо се сифат"""
    try:
        print(f"🎬 Starting HLS processing for video: {video_id}")
        print(f"📁 Input path: {input_path}")
        print(f"📁 Output dir: {post_hls_dir}")
        
        # Эҷоди директория барои ин видео
        video_hls_dir = os.path.join(post_hls_dir, video_id)
        os.makedirs(video_hls_dir, exist_ok=True)
        print(f"✅ Created video HLS dir: {video_hls_dir}")
        
        # Гирфтани маълумоти видео
        video_info = get_video_info(input_path)
        original_width = video_info['width']
        original_height = video_info['height']
        duration = video_info['duration']
        
        if duration == 0:
            print(f"⚠️ Warning: Could not determine video duration")
            duration = 60
        
        # Муайян кардани самти видео
        is_vertical = original_height > original_width
        
        # Табдили давомнокӣ ба сонияҳо
        duration_seconds = int(duration)
        video_duration = format_duration(duration_seconds)
        
        processing_status[video_id] = {
            'status': 'processing',
            'progress': 0,
            'duration': duration,
            'orientation': 'vertical' if is_vertical else 'horizontal',
            'original_width': original_width,
            'original_height': original_height,
            'qualities': {}
        }
        
        # Эҷоди файли мастер
        master_playlist = "#EXTM3U\n#EXT-X-VERSION:3\n"
        
        # Ҳисобкунии вазни ҳар як сифат
        quality_weights = {
            '360p': (0, 33),    # 0% → 33%
            '480p': (33, 66),   # 33% → 66%
            '720p': (66, 100)   # 66% → 100%
        }
        
        # Табдил ба ҳар сифат
        for idx, quality in enumerate(SUPPORTED_QUALITIES):
            quality_dir = os.path.join(video_hls_dir, quality['name'])
            os.makedirs(quality_dir, exist_ok=True)
            
            playlist_path = os.path.join(quality_dir, 'playlist.m3u8')
            
            # Ҳисоб кардани scale filter
            scale_filter = calculate_scale_params(original_width, original_height, quality['height'])
            
            cmd = [
                'ffmpeg', '-i', input_path,
                '-c:v', 'libx264',
                '-c:a', 'aac',
                '-b:v', quality['bitrate'],
                '-maxrate', quality['bitrate'],
                '-bufsize', str(int(quality['bitrate'].replace('k', '')) * 2) + 'k',
                '-vf', scale_filter,
                '-hls_time', '6',
                '-hls_list_size', '0',
                '-hls_segment_filename', os.path.join(quality_dir, 'segment_%03d.ts'),
                '-hls_flags', 'independent_segments',
                '-f', 'hls',
                '-y',
                playlist_path
            ]
            
            print(f"🎬 Processing quality {quality['name']}...")
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            start, end = quality_weights[quality['name']]
            
            # Хондани stderr барои прогресс
            for line in process.stderr:
                if "time=" in line:
                    try:
                        time_str = line.split("time=")[1].split()[0]
                        h, m, s = time_str.split(':')
                        current_time = int(h) * 3600 + int(m) * 60 + float(s)
                        if duration > 0:
                            quality_progress = (current_time / duration) * 100
                            progress_in_quality = (quality_progress / 100) * (end - start)
                            mapped_progress = start + progress_in_quality
                            
                            # Ҳисобкунии прогресси умумӣ
                            video_progress_offset = (video_index * total_progress_range / total_videos)
                            progress_in_video = (mapped_progress * total_progress_range / (total_videos * 100))
                            total_progress = base_progress + video_progress_offset + progress_in_video
                            
                            upload_progress[upload_id] = min(total_progress, 99.9)
                            processing_status[video_id]['qualities'][quality['name']] = quality_progress
                    except:
                        pass
            
            process.wait()
            
            if process.returncode != 0:
                raise Exception(f"FFmpeg failed for quality {quality['name']}")

            print(f"✅ Completed quality {quality['name']}")
            
            # Муайян кардани андозаи ниҳоӣ барои мастер плейлист
            calculated_width = int((quality['height'] / original_height) * original_width) if original_height > 0 else quality['height']
            resolution = f"{calculated_width}x{quality['height']}"
            
            master_playlist += f"\n#EXT-X-STREAM-INF:BANDWIDTH={int(quality['bitrate'].replace('k',''))*1000},RESOLUTION={resolution}\n"
            master_playlist += f"{quality['name']}/playlist.m3u8\n"
        
        # Навиштани мастер плейлист
        master_path = os.path.join(video_hls_dir, 'master.m3u8')
        with open(master_path, 'w') as f:
            f.write(master_playlist)

        print(f"✅ Created master playlist: {master_path}")

        # Сохтани thumbnail аз видеои аввал
        thumbnail_cmd = [
            'ffmpeg',
            '-i', input_path,
            '-ss', '00:00:01',
            '-vframes', '1',
            '-f', 'image2pipe',
            '-vcodec', 'mjpeg',
            'pipe:1'
        ]

        print(f"🎬 Creating thumbnail...")
        result = subprocess.run(thumbnail_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        thumbnail_id = None

        if result.returncode == 0 and result.stdout:
            try:
                thumbnail_id = videos_fs.put(result.stdout, filename=f"{video_id}_thumbnail.jpg")
                print(f"✅ Thumbnail saved to DB: {thumbnail_id}")
            except Exception as e:
                print(f"❌ Failed to save thumbnail to DB: {e}")

        processing_status[video_id]['status'] = 'completed'
        processing_status[video_id]['progress'] = 100
        processing_status[video_id]['duration_formatted'] = video_duration
        processing_status[video_id]['thumbnail_id'] = str(thumbnail_id) if thumbnail_id else None
        processing_status[video_id]['master_url'] = f"/hls/{os.path.basename(post_hls_dir)}/{video_id}/master.m3u8"
        
        print(f"✅ HLS processing completed for video: {video_id}")
        return True
        
    except Exception as e:
        print(f"❌ Error processing video {video_id}: {e}")
        import traceback
        traceback.print_exc()
        processing_status[video_id]['status'] = 'error'
        processing_status[video_id]['error'] = str(e)
        raise

@router.post("/update_post_video")
async def update_post_video(
    videos: List[UploadFile] = File(None),
    user_id: str = Form(None),
    post_id: str = Form(...),
    title: str = Form(""),
    description: str = Form(""),
    allow_comments: bool = Form(False),
    advertisement_count: float = Form(0),
    advertisement_checkbox: bool = Form(False),
    visibility: str = Form("public"),
    collaboration_accounts: str = Form("[]"),
    upload_id: str = Form(...),
    link: str = Form(...),
    thumbnail: UploadFile = File(None),
    deleted_videos: str = Form("[]")
):
    client.admin.command("ping")

    if not upload_id or not post_id:
        raise HTTPException(status_code=400, detail="Missing upload_id or post_id")

    upload_progress[upload_id] = 95.0  # Аз 95% оғоз мешавад
    cancelled_uploads.discard(upload_id)

    post = videos_collection.find_one({"_id": ObjectId(post_id)})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    original_post = post.copy()
    updated_fields = {}

    post_owner_id = str(post["UserId"])
    current_hls_videos = post.get("HLSVideos", [])
    current_video_names = post.get("VideoNames", [])
    current_video_ids = post.get("VideoIds", [])

    # =====================================================
    # 🔥 1️⃣ DELETE SELECTED VIDEOS
    # =====================================================
    deleted_video_ids = json.loads(deleted_videos) if deleted_videos else []
    
    remaining_hls_videos = []
    remaining_video_names = []
    remaining_video_ids = []

    for idx, vid_meta in enumerate(current_hls_videos):
        video_id = vid_meta.get('video_id')
        if video_id in deleted_video_ids:
            video_dir = os.path.join(HLS_STORAGE_PATH, str(post_id), video_id)
            if os.path.exists(video_dir):
                shutil.rmtree(video_dir)
        else:
            remaining_hls_videos.append(vid_meta)
            if idx < len(current_video_names):
                remaining_video_names.append(current_video_names[idx])
            if idx < len(current_video_ids):
                remaining_video_ids.append(current_video_ids[idx])

    # Навсозии прогресс баъди ҳазфи видеоҳо
    upload_progress[upload_id] = 95.5

    # =====================================================
    # 🔥 2️⃣ UPLOAD AND PROCESS NEW VIDEOS
    # =====================================================
    new_hls_videos = []
    new_video_names = []
    new_video_ids = []

    if videos:
        total_new_videos = len(videos)
        existing_count = len(remaining_hls_videos)

        for idx, video in enumerate(videos):
            if not video:
                continue

            if not allowed_video_file(video.filename):
                raise HTTPException(
                    status_code=400,
                    detail=f"Video {video.filename} has invalid format"
                )

            MAX_SIZE = 500 * 1024 * 1024  # 500MB per video
            total_size = video.size

            if total_size > MAX_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=f"Video {video.filename} exceeds 500MB limit"
                )

            if upload_id in cancelled_uploads:
                for vid_meta in new_hls_videos:
                    video_dir = os.path.join(HLS_STORAGE_PATH, str(post_id), vid_meta['video_id'])
                    if os.path.exists(video_dir):
                        shutil.rmtree(video_dir)
                
                videos_collection.update_one(
                    {"_id": ObjectId(post_id)},
                    {"$set": original_post}
                )
                
                upload_progress.pop(upload_id, None)
                cancelled_uploads.discard(upload_id)
                raise HTTPException(status_code=400, detail="Upload cancelled")

            new_video_names.append(video.filename)
            video_id = str(ObjectId())
            new_video_ids.append(video_id)
            
            # Прогресс барои боргузорӣ (95.5% - 96.5%)
            upload_progress[upload_id] = 95.5 + (idx / total_new_videos) * 1.0
            
            temp_video_path = os.path.join(UPLOAD_TEMP_PATH, f"update_{video_id}_{video.filename}")

            total_size = video.size

            chunk_size = 1024 * 1024
            
            with open(temp_video_path, "wb") as f:
                uploaded_size = 0
                while True:
                    chunk = await video.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    uploaded_size += len(chunk)
                    
                    # Навсозии прогресс ҳангоми боргузорӣ
                    if total_size > 0:
                        upload_progress[upload_id] = 95.5 + (idx / total_new_videos) * 1.0 + (uploaded_size / total_size) * (1.0 / total_new_videos)
                    
                    await asyncio.sleep(0)
            
            # Прогресс барои коркард (96.5% - 99%)
            upload_progress[upload_id] = 96.5 + (idx / total_new_videos) * 2.5
            
            try:
                await asyncio.to_thread(
                    process_video_to_hls_update,
                    temp_video_path,
                    video_id,
                    os.path.join(HLS_STORAGE_PATH, str(post_id)),
                    upload_id,
                    idx,
                    total_new_videos,
                    96.5,  # Прогресси ибтидоӣ барои коркард
                    2.5    # Фоизи умумии коркард
                )

                if os.path.exists(temp_video_path):
                    os.remove(temp_video_path)
                
                if video_id in processing_status and processing_status[video_id]['status'] == 'completed':
                    video_meta = {
                        'video_id': video_id,
                        'master_url': processing_status[video_id]['master_url'],
                        'duration': processing_status[video_id]['duration_formatted'],
                        'orientation': processing_status[video_id]['orientation'],
                        'thumbnail_id': processing_status[video_id].get('thumbnail_id'),
                        'qualities': ['360p', '480p', '720p']
                    }
                    new_hls_videos.append(video_meta)
                    
            except Exception as e:
                print(f"Error processing video: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to process video {video.filename}")

    # =====================================================
    # 🔥 3️⃣ FINAL VIDEO LIST
    # =====================================================
    final_hls_videos = remaining_hls_videos + new_hls_videos
    final_video_names = remaining_video_names + new_video_names
    final_video_ids = remaining_video_ids + new_video_ids

    if not final_hls_videos:
        raise HTTPException(status_code=400, detail="At least one video must remain")

    updated_fields["HLSVideos"] = final_hls_videos
    updated_fields["VideoNames"] = final_video_names
    updated_fields["VideoIds"] = final_video_ids
    updated_fields["VideoCount"] = len(final_hls_videos)

    if len(final_hls_videos) == 1:
        updated_fields["VideoDuration"] = final_hls_videos[0]['duration']
    else:
        updated_fields["VideoDuration"] = None

    upload_progress[upload_id] = 99.0

    # =====================================================
    # 🔹 BASIC FIELD UPDATES
    # =====================================================
    new_title = title.strip() or datetime.datetime.now(datetime.timezone.utc).strftime("%d/%m/%Y")
    if new_title != post.get("Title"):
        updated_fields["Title"] = new_title

    if description != post.get("Description", ""):
        updated_fields["Description"] = description

    if visibility != post.get("Visibility"):
        updated_fields["Visibility"] = visibility

    if allow_comments != post.get("AllowComments"):
        updated_fields["AllowComments"] = allow_comments

    # =====================================================
    # 🔹 ADVERTISEMENT UPDATE
    # =====================================================
    old_ad_count = int(post.get("AdvertisementCount", 0))
    new_ad_count = int(advertisement_count) if advertisement_checkbox else 0
    
    count_difference = new_ad_count - old_ad_count
    
    if count_difference > 0 and advertisement_checkbox:
        amount = count_difference / 100
        from_user = users_collection.find_one({"_id": ObjectId(post_owner_id)})

        if not from_user:
            raise HTTPException(status_code=404, detail="User not found")

        if from_user.get("Balance", 0) < amount:
            raise HTTPException(status_code=408, detail="Insufficient balance")

        users_collection.update_one(
            {"_id": ObjectId(post_owner_id)},
            {"$inc": {"Balance": -amount}}
        )

        users_collection.update_one(
            {"Username": "sanjar"},
            {"$inc": {"Balance": amount}}
        )

    updated_fields["AdvertisementCount"] = new_ad_count
    updated_fields["AdvertisementCheckbox"] = advertisement_checkbox

    upload_progress[upload_id] = 99.3

    # =====================================================
    # 🔹 THUMBNAIL UPDATE
    # =====================================================
    if thumbnail:
        content = await thumbnail.read()
        thumbnail_id = videos_fs.put(content, filename=thumbnail.filename)
        if thumbnail_id:
            updated_fields["ThumbnailId"] = thumbnail_id

    upload_progress[upload_id] = 99.5

    # =====================================================
    # 🔹 COLLABORATION UPDATE
    # =====================================================
    try:
        collaboration_accounts_list = json.loads(collaboration_accounts)
    except:
        collaboration_accounts_list = []

    current_collaborators = [str(x) for x in post.get("CollaborationAccounts", [])]
    new_collaborators = [
        acc for acc in collaboration_accounts_list
        if acc not in current_collaborators and ObjectId.is_valid(acc)
    ]

    if new_collaborators:
        user_data = users_collection.find_one({"_id": ObjectId(post_owner_id)})
        username = user_data.get("Username")

        encrypted_message = encrypt_data(
            f"@{username} invited you to a new collaboration. View post: https://www.anyvoice.world/video/{link}",
            ENCRYPTION_KEY
        )

        encrypted_type = encrypt_data("collaboration", ENCRYPTION_KEY)

        for account_id in new_collaborators:
            notification_doc = {
                "NotificationFrom": ObjectId(post_owner_id),
                "NotificationTo": ObjectId(account_id),
                "Message": encrypted_message,
                "PostId": ObjectId(post_id),
                "IsRead": False,
                "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
                "Type": encrypted_type,
                "status": "pending"
            }

            notifications_collection.insert_one(notification_doc)
            serialized_notification = serialize_notification(notification_doc)
            await broadcast_notification(str(account_id), "add", serialized_notification)

    updated_fields["CollaborationAccounts"] = [ObjectId(acc) for acc in collaboration_accounts_list if ObjectId.is_valid(acc)]
    updated_fields["UpdateAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00')

    upload_progress[upload_id] = 99.8

    # Навсозии MongoDB
    videos_collection.update_one(
        {"_id": ObjectId(post_id)},
        {"$set": updated_fields}
    )

    upload_progress[upload_id] = 100.0
    upload_progress.pop(upload_id, None)
    cancelled_uploads.discard(upload_id)

    return {
        "status": "success",
        "message": "Post updated successfully",
        "post_id": str(post_id),
        "deleted_videos_count": len(deleted_video_ids)
    }

@router.get("/hls/{post_id}/{video_id}/{filename:path}")
async def serve_hls(post_id: str, video_id: str, filename: str):
    """Сервер кардани файлҳои HLS"""
    from fastapi.responses import FileResponse
    
    file_path = os.path.join(HLS_STORAGE_PATH, post_id, video_id, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(file_path)

@router.delete("/delete_video/{post_id}")
async def delete_video_post(post_id: str, user_id: str):
    """Нест кардани видео пост"""
    client.admin.command("ping")
    
    post = videos_collection.find_one({"_id": ObjectId(post_id)})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    if str(post["UserId"]) != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this post")
    
    hls_path = post.get("HLSStoragePath")
    if hls_path and os.path.exists(hls_path):
        shutil.rmtree(hls_path)
    
    thumbnail_id = post.get("ThumbnailId")
    if thumbnail_id:
        try:
            videos_fs.delete(ObjectId(thumbnail_id))
        except:
            pass
    
    videos_collection.delete_one({"_id": ObjectId(post_id)})
    
    users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$inc": {"CountPosts": -1, "CountVideos": -post.get("VideoCount", 1)}}
    )
    
    return {"status": "success", "message": "Post deleted successfully"}
