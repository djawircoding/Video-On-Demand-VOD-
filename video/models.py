from django.db import models, transaction
import subprocess
import os
from django.conf import settings
from datetime import datetime
from django.core.exceptions import ValidationError
from django.forms import forms
from django.utils.translation import gettext_lazy as _
from pathlib import Path
import shutil

class VideoFileField(models.FileField):
    def __init__(self, *args, **kwargs):
        super(VideoFileField, self).__init__(*args, **kwargs)

    def clean(self, *args, **kwargs):
        data = super(VideoFileField, self).clean(*args, **kwargs)
        if data:
            ext = os.path.splitext(data.name)[1].lower()
            valid_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.webm']
            if ext not in valid_extensions:
                raise forms.ValidationError(_('Please upload a valid video file. Supported formats: MP4, MKV, AVI, MOV, WEBM'))
        return data

def validate_video_extension(value):
    ext = os.path.splitext(value.name)[1]
    valid_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.webm']
    if ext.lower() not in valid_extensions:
        raise ValidationError('Unsupported file format. Please upload a video file (MP4, MKV, AVI, MOV, or WEBM)')

class Video(models.Model):
    MAX_VIDEO_SIZE_MB = 100  # Maximum video size in MB
    
    caption = models.CharField(max_length=100)
    video = VideoFileField(
        upload_to='video/%y',
        validators=[validate_video_extension],
        help_text='Supported formats: MP4, MKV, AVI, MOV, WEBM',
        verbose_name='Video File'
    )
    processed_video = models.URLField(max_length=500, null=True, blank=True)  # Changed to URLField

    def clean(self):
        if self.video:
            # Check file size
            if self.video.size > self.MAX_VIDEO_SIZE_MB * 1024 * 1024:
                raise ValidationError(f'Video size cannot exceed {self.MAX_VIDEO_SIZE_MB}MB')
            
            if not os.path.exists(self.video.path):
                return  # Skip duration check if file doesn't exist yet

            # Get video duration using FFprobe
            try:
                cmd = [
                    'ffprobe',
                    '-v', 'error',
                    '-show_entries', 'format=duration',
                    '-of', 'default=noprint_wrappers=1:nokey=1',
                    str(self.video.path)
                ]
                duration = float(subprocess.check_output(cmd, text=True, stderr=subprocess.PIPE).strip())
                
                if duration > 600:  # 10 minutes
                    raise ValidationError('Video duration cannot exceed 10 minutes')
            except (subprocess.SubprocessError, ValueError, OSError) as e:
                print(f"Warning: Could not check video duration: {e}")

    def __str__(self):
        return self.caption

    def save(self, *args, **kwargs):
        if self._state.adding:  # Only process new videos
            self.clean()  # Validate before processing
            with transaction.atomic():
                super().save(*args, **kwargs)
                
                if self.video and not self.processed_video:
                    try:
                        # Ensure the video file exists
                        if not os.path.exists(self.video.path):
                            raise ValidationError("Video file not found")

                        # Create necessary directories in web folder
                        year = datetime.now().strftime('%y')
                        web_root = Path(settings.WEB_MEDIA_ROOT)
                        web_output_dir = web_root / 'processed' / year
                        web_output_dir.mkdir(parents=True, exist_ok=True)
                        
                        # Create a directory for the HLS segments
                        base_name = Path(self.video.name).stem
                        stream_dir = web_output_dir / f"stream_{base_name}"
                        stream_dir.mkdir(parents=True, exist_ok=True)
                        
                        # Set up HLS playlist and segment paths
                        playlist_name = "playlist.m3u8"
                        segment_pattern = "segment_%03d.ts"
                        output_playlist = stream_dir / playlist_name
                        output_segment = stream_dir / segment_pattern
                        
                        # FFmpeg command with optimized settings
                        ffmpeg_cmd = [
                            'ffmpeg',
                            '-y',  # Overwrite output files
                            '-i', str(self.video.path),
                            '-threads', '2',
                            '-c:v', 'libx264',
                            '-preset', 'veryfast',
                            '-profile:v', 'baseline',
                            '-level', '3.0',
                            '-maxrate', '2000k',
                            '-bufsize', '4000k',
                            '-crf', '27',
                            '-c:a', 'aac',
                            '-b:a', '128k',
                            '-ac', '2',
                            '-ar', '44100',
                            '-hls_time', '6',
                            '-hls_list_size', '0',
                            '-hls_flags', 'independent_segments',
                            '-hls_segment_type', 'mpegts',
                            '-hls_segment_filename', str(output_segment),
                            '-f', 'hls',
                            str(output_playlist)
                        ]
                        
                        print(f"Running FFmpeg command: {' '.join(ffmpeg_cmd)}")
                        
                        # Run FFmpeg process with proper error handling
                        process = subprocess.Popen(
                            ffmpeg_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            env={'PATH': os.environ.get('PATH', '')}
                        )
                        
                        try:
                            print("FFmpeg process started...")
                            stdout, stderr = process.communicate(timeout=300)
                            
                            if process.returncode == 0:
                                print("FFmpeg process completed successfully")
                                # Set the processed_video URL using the web media URL
                                relative_path = f'processed/{year}/stream_{base_name}/{playlist_name}'
                                self.processed_video = f"{settings.WEB_MEDIA_URL.rstrip('/')}/{relative_path}"
                                super().save(update_fields=['processed_video'])
                                
                                # Ensure web server can read the files
                                os.system(f'chmod -R 755 {stream_dir}')
                                
                            else:
                                print(f"FFmpeg Error: Process returned {process.returncode}")
                                print(f"Error details: {stderr}")
                                if stream_dir.exists():
                                    shutil.rmtree(stream_dir)
                                raise ValidationError(f"Video processing failed: {stderr}")
                                
                        except subprocess.TimeoutExpired:
                            print("FFmpeg process timed out, killing process...")
                            process.kill()
                            if stream_dir.exists():
                                shutil.rmtree(stream_dir)
                            raise ValidationError("Video processing timed out")
                            
                    except Exception as e:
                        print(f"Error processing video: {str(e)}")
                        stream_dir = web_output_dir / f"stream_{base_name}"
                        if stream_dir.exists():
                            shutil.rmtree(stream_dir)
                        raise ValidationError(f"Video processing error: {str(e)}")
        else:
            super().save(*args, **kwargs)