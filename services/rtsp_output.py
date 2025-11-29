"""
RTSP streaming server using ffmpeg as a bridge.
Receives frames via stdin pipe and streams via RTSP for viewers like VLC or NINA.
"""

import os
import subprocess
import threading
import time
import numpy as np
from PIL import Image
from .logger import app_logger


class RTSPStreamServer:
    """Manages RTSP streaming via ffmpeg subprocess."""
    
    def __init__(self, host='0.0.0.0', port=8554, stream_name='asiwatchdog', fps=1.0):
        """
        Initialize RTSP server.
        
        Args:
            host: Interface to bind to (0.0.0.0 for all interfaces)
            port: RTSP port to listen on
            stream_name: Stream name in URL (rtsp://host:port/stream_name)
            fps: Frames per second for the stream
        """
        self.host = host
        self.port = port
        self.stream_name = stream_name
        self.fps = fps
        self.process = None
        self.running = False
        self.last_frame = None
        self.frame_size = None  # (width, height)
        self.frame_thread = None
        self.frame_lock = threading.Lock()
    
    def start(self):
        """Start the RTSP server via ffmpeg."""
        if self.running:
            app_logger.warning("RTSP server already running")
            return False
        
        try:
            # Check if ffmpeg is available
            if not self._check_ffmpeg():
                app_logger.warning("ffmpeg not found in PATH. RTSP streaming requires ffmpeg.")
                app_logger.info("To enable RTSP: Download ffmpeg from https://ffmpeg.org/download.html")
                app_logger.info("After installing, add ffmpeg.exe to your system PATH and restart the app.")
                return False
            
            # Start with a placeholder frame size (will be updated on first frame)
            self.frame_size = (1920, 1080)
            
            # Build ffmpeg command
            cmd = self._build_ffmpeg_command()
            
            # Start ffmpeg process
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=10**8
            )
            
            self.running = True
            
            # Start frame sender thread
            self.frame_thread = threading.Thread(target=self._frame_sender_loop, daemon=True)
            self.frame_thread.start()
            
            rtsp_url = self.get_url()
            app_logger.info(f"RTSP server started: {rtsp_url}")
            app_logger.info(f"  - Stream at {self.fps} FPS")
            app_logger.info(f"  - Connect with VLC, NINA, or other RTSP client")
            return True
            
        except FileNotFoundError:
            app_logger.error("ffmpeg executable not found in PATH")
            return False
        except Exception as e:
            app_logger.error(f"Failed to start RTSP server: {e}")
            return False
    
    def _check_ffmpeg(self):
        """Check if ffmpeg is available."""
        try:
            result = subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except:
            return False
    
    def _build_ffmpeg_command(self):
        """Build the ffmpeg command for RTSP streaming."""
        width, height = self.frame_size
        
        # ffmpeg command:
        # - Read raw BGR24 frames from stdin
        # - Encode to H.264
        # - Stream via RTSP
        cmd = [
            'ffmpeg',
            '-f', 'rawvideo',
            '-pixel_format', 'bgr24',
            '-video_size', f'{width}x{height}',
            '-framerate', str(self.fps),
            '-i', 'pipe:0',  # Read from stdin
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-tune', 'zerolatency',
            '-pix_fmt', 'yuv420p',
            '-g', '30',  # GOP size
            '-f', 'rtsp',
            f'rtsp://{self.host}:{self.port}/{self.stream_name}'
        ]
        
        return cmd
    
    def _frame_sender_loop(self):
        """Background thread that sends frames to ffmpeg at regular intervals."""
        frame_interval = 1.0 / self.fps
        
        try:
            while self.running and self.process and self.process.poll() is None:
                if self.last_frame is not None:
                    try:
                        with self.frame_lock:
                            frame_bytes = self.last_frame
                        
                        self.process.stdin.write(frame_bytes)
                        self.process.stdin.flush()
                        app_logger.debug(f"Sent frame to RTSP ({len(frame_bytes)} bytes)")
                    except BrokenPipeError:
                        app_logger.error("RTSP ffmpeg pipe broken")
                        break
                    except Exception as e:
                        app_logger.error(f"Error sending frame to RTSP: {e}")
                
                time.sleep(frame_interval)
        except Exception as e:
            app_logger.error(f"RTSP frame sender error: {e}")
        finally:
            app_logger.debug("RTSP frame sender thread stopped")
    
    def stop(self):
        """Stop the RTSP server."""
        if not self.running:
            return
        
        try:
            app_logger.info("Stopping RTSP server...")
            self.running = False
            
            # Wait for frame thread
            if self.frame_thread:
                self.frame_thread.join(timeout=2.0)
            
            # Terminate ffmpeg
            if self.process:
                try:
                    self.process.stdin.close()
                except:
                    pass
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            
            app_logger.info("RTSP server stopped")
        except Exception as e:
            app_logger.error(f"Error stopping RTSP server: {e}")
    
    def update_image(self, image_input, metadata=None):
        """
        Update the stream with a new frame.
        
        Args:
            image_input: PIL Image object or path to image file
            metadata: Optional dict with image metadata (unused for RTSP)
        """
        if not self.running:
            return
        
        try:
            # Load image if path provided
            if isinstance(image_input, str):
                img = Image.open(image_input)
            else:
                img = image_input
            
            # Convert to RGB if needed
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Check if frame size changed (restart ffmpeg if needed)
            new_size = (img.width, img.height)
            if new_size != self.frame_size:
                app_logger.info(f"RTSP frame size changed: {self.frame_size} -> {new_size}")
                self.frame_size = new_size
                self._restart_ffmpeg()
            
            # Convert PIL Image to numpy array (RGB -> BGR for ffmpeg)
            img_np = np.array(img)
            img_bgr = img_np[:, :, ::-1]  # RGB to BGR
            
            # Store frame bytes for sender thread
            with self.frame_lock:
                self.last_frame = img_bgr.tobytes()
            
            app_logger.debug(f"RTSP frame updated: {new_size}")
            
        except Exception as e:
            app_logger.error(f"Error updating RTSP frame: {e}")
    
    def _restart_ffmpeg(self):
        """Restart ffmpeg with new frame size."""
        try:
            # Stop current process
            was_running = self.running
            if self.process:
                self.process.terminate()
                self.process.wait(timeout=2)
            
            # Start new process with updated frame size
            if was_running:
                cmd = self._build_ffmpeg_command()
                self.process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=10**8
                )
                app_logger.info("RTSP ffmpeg restarted with new frame size")
        except Exception as e:
            app_logger.error(f"Error restarting RTSP ffmpeg: {e}")
    
    def get_url(self):
        """Get the RTSP stream URL."""
        if self.running:
            return f"rtsp://{self.host}:{self.port}/{self.stream_name}"
        return None
