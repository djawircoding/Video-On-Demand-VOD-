from django.db import models, transaction
import subprocess
import os
from django.conf import settings
from datetime import datetime
from django.core.exceptions import ValidationError

class Video(models.Model):
    MAX_VIDEO_SIZE_MB = 100  # Maximum video size in MB
    
    caption = models.CharField(max_length=100)
    video = models.FileField(upload_to='video/%y')
    processed_video = models.FileField(upload_to='processed/%y', null=True, blank=True)

    def clean(self):
        if self.video:
            # Check file size
            if self.video.size > self.MAX_VIDEO_SIZE_MB * 1024 * 1024:
                raise ValidationError(f'Video size cannot exceed {self.MAX_VIDEO_SIZE_MB}MB')
            
            # Get video duration using FFprobe
            ffprobe_path = os.path.join(os.path.dirname(r'C:\Users\asus\OneDrive\Documents\Django\ffmpeg\ffmpeg.exe'), 'ffprobe.exe')
            if os.path.exists(ffprobe_path):
                try:
                    cmd = [
                        ffprobe_path,
                        '-v', 'error',
                        '-show_entries', 'format=duration',
                        '-of', 'default=noprint_wrappers=1:nokey=1',
                        self.video.path
                    ]
                    duration = float(subprocess.check_output(cmd, text=True).strip())
                    
                    if duration > 600:  # 10 minutes
                        raise ValidationError('Video duration cannot exceed 10 minutes')
                except (subprocess.SubprocessError, ValueError, OSError) as e:
                    print(f"Warning: Could not check video duration: {e}")
                    # Continue without duration check if FFprobe fails

    def __str__(self):
        return self.caption

    def save(self, *args, **kwargs):
        if self._state.adding:  # Only process new videos
            self.clean()  # Validate before processing
            with transaction.atomic():
                super().save(*args, **kwargs)
                
                if self.video and not self.processed_video:
                    try:
                        input_path = self.video.path
                        year = datetime.now().strftime('%y')
                        output_dir = os.path.join(settings.MEDIA_ROOT, 'processed', year)
                        os.makedirs(output_dir, exist_ok=True)
                        
                        # Create a directory for the HLS segments
                        base_name = os.path.splitext(os.path.basename(self.video.name))[0]
                        stream_dir = os.path.join(output_dir, f"stream_{base_name}")
                        os.makedirs(stream_dir, exist_ok=True)
                        
                        # Set up HLS playlist and segment paths
                        playlist_name = "playlist.m3u8"
                        segment_pattern = "segment_%03d.ts"
                        output_playlist = os.path.join(stream_dir, playlist_name)
                        output_segment = os.path.join(stream_dir, segment_pattern)
                        
                        # Get FFmpeg executable path
                        ffmpeg_path = r'C:\Users\asus\OneDrive\Documents\Django\ffmpeg\ffmpeg.exe'
                        if not os.path.exists(ffmpeg_path):
                            raise Exception(f"FFmpeg not found at {ffmpeg_path}")
                        
                        print(f"Using FFmpeg from: {ffmpeg_path}")
                        
                        # FFmpeg command with optimized settings for lower CPU usage
                        ffmpeg_cmd = [
                            ffmpeg_path,
                            '-i', input_path,
                            '-threads', '2',            # Limit number of threads
                            '-c:v', 'libx264',          # Use H.264 codec
                            '-preset', 'veryfast',      # Use fastest encoding preset
                            '-profile:v', 'baseline',   # Use simpler profile
                            '-level', '3.0',            # Set compatibility level
                            '-maxrate', '2000k',        # Limit bitrate
                            '-bufsize', '4000k',        # Buffer size for rate control
                            '-crf', '27',               # Slightly reduce quality for better performance
                            '-c:a', 'aac',              # Audio codec
                            '-b:a', '128k',             # Lower audio bitrate
                            '-ac', '2',                 # Stereo audio
                            '-ar', '44100',             # Standard audio sample rate
                            '-hls_time', '6',           # Longer segments for less processing
                            '-hls_list_size', '0',      # Keep all segments
                            '-hls_flags', 'independent_segments',
                            '-hls_segment_type', 'mpegts',
                            '-hls_segment_filename', output_segment,
                            '-f', 'hls',
                            '-y',
                            output_playlist
                        ]
                        
                        print(f"Running FFmpeg command: {' '.join(ffmpeg_cmd)}")
                        
                        # Run FFmpeg with lowered priority
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        
                        process = subprocess.Popen(
                            ffmpeg_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.BELOW_NORMAL_PRIORITY_CLASS,  # Lower priority
                            startupinfo=startupinfo
                        )
                        
                        try:
                            print("FFmpeg process started...")
                            stdout, stderr = process.communicate(timeout=300)
                            print(f"FFmpeg output: {stdout}")
                            print(f"FFmpeg error output: {stderr}")
                            
                            if process.returncode == 0:
                                print("FFmpeg process completed successfully")
                                # Save the path relative to MEDIA_ROOT
                                relative_path = os.path.join('processed', year, f"stream_{base_name}", playlist_name)
                                self.processed_video.name = relative_path
                                super().save(update_fields=['processed_video'])
                            else:
                                print(f"FFmpeg Error: Process returned {process.returncode}")
                                print(f"Error details: {stderr}")
                                if os.path.exists(stream_dir):
                                    import shutil
                                    shutil.rmtree(stream_dir)
                        except subprocess.TimeoutExpired:
                            print("FFmpeg process timed out, killing process...")
                            process.kill()
                            if os.path.exists(stream_dir):
                                import shutil
                                shutil.rmtree(stream_dir)
                            
                    except Exception as e:
                        print(f"Error processing video: {str(e)}")
                        if 'stream_dir' in locals() and os.path.exists(stream_dir):
                            import shutil
                            shutil.rmtree(stream_dir)
                        raise
        else:
            super().save(*args, **kwargs)