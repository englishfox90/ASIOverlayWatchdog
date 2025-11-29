"""
Web server for serving latest processed image via HTTP.
Provides endpoints for NINA and other remote applications to fetch latest frame.
"""

import os
import io
import json
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from .logger import app_logger


class ImageHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for serving images and status."""
    
    # Class-level variables shared between all handler instances
    latest_image_path = None
    latest_image_data = None
    latest_image_content_type = 'image/jpeg'  # Default to JPEG
    latest_metadata = {}
    server_start_time = None
    image_count = 0
    
    def log_message(self, format, *args):
        """Override to use our logger instead of stderr."""
        app_logger.info(f"HTTP {self.address_string()} - {format % args}")
    
    def do_GET(self):
        """Handle GET requests."""
        config_path = self.server.config_path
        status_path = self.server.status_path
        
        # Parse URL to strip query parameters (e.g., ?t=1764384123178)
        parsed_url = urlparse(self.path)
        clean_path = parsed_url.path
        query_params = parse_qs(parsed_url.query)
        
        # Debug logging to diagnose path matching issues
        app_logger.debug(f"Request: original='{self.path}', clean='{clean_path}', config='{config_path}', status='{status_path}'")
        if query_params:
            app_logger.debug(f"Query params: {query_params}")
        
        if clean_path == config_path:
            self._serve_image()
        elif clean_path == status_path:
            self._serve_status()
        else:
            self.send_error(404, f"Path not found. Available: {config_path}, {status_path}")
    
    def do_OPTIONS(self):
        """Handle OPTIONS requests for CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()
    
    def _serve_image(self):
        """Serve the latest processed image."""
        if not self.latest_image_data:
            self.send_error(404, "No image available yet")
            return
        
        try:
            self.send_response(200)
            self.send_header("Content-Type", self.latest_image_content_type)
            self.send_header("Content-Length", len(self.latest_image_data))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            # CORS headers for cross-origin requests (portals, web apps)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            self.wfile.write(self.latest_image_data)
            app_logger.debug(f"Served image: {len(self.latest_image_data)} bytes ({self.latest_image_content_type})")
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as e:
            # Client disconnected - this is normal, don't log as error
            app_logger.debug(f"Client disconnected during image transfer: {e.__class__.__name__}")
        except Exception as e:
            app_logger.error(f"Error serving image: {e}")
    
    def _serve_status(self):
        """Serve server status as JSON."""
        uptime = 0
        if self.server_start_time:
            uptime = int(time.time() - self.server_start_time)
        
        status = {
            "server": "ASI Overlay WatchDog HTTP Server",
            "status": "running",
            "uptime_seconds": uptime,
            "images_served": self.image_count,
            "latest_image": self.latest_image_path or "None",
            "metadata": self.latest_metadata,
            "timestamp": datetime.now().isoformat()
        }
        
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache")
            # CORS headers for cross-origin requests
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            self.wfile.write(json.dumps(status, indent=2).encode('utf-8'))
        except Exception as e:
            app_logger.error(f"Error serving status: {e}")


class WebOutputServer:
    """Manages HTTP server for serving latest processed images."""
    
    def __init__(self, host='0.0.0.0', port=8080, image_path='/latest', status_path='/status'):
        """
        Initialize web server.
        
        Args:
            host: Interface to bind to (0.0.0.0 for all interfaces)
            port: Port to listen on
            image_path: URL path for image endpoint
            status_path: URL path for status endpoint
        """
        self.host = host
        self.port = port
        self.image_path = image_path
        self.status_path = status_path
        self.server = None
        self.server_thread = None
        self.running = False
    
    def start(self):
        """Start the HTTP server in a background thread."""
        if self.running:
            app_logger.warning("Web server already running")
            return False
        
        try:
            # Create server
            self.server = HTTPServer((self.host, self.port), ImageHTTPHandler)
            self.server.config_path = self.image_path
            self.server.status_path = self.status_path
            
            # Set class variables
            ImageHTTPHandler.server_start_time = time.time()
            ImageHTTPHandler.image_count = 0
            
            # Start in daemon thread
            self.server_thread = threading.Thread(target=self._run_server, daemon=True)
            self.server_thread.start()
            self.running = True
            
            # Get actual address (useful if port was 0 for auto-assign)
            actual_port = self.server.server_port
            app_logger.info(f"Web server started on http://{self.host}:{actual_port}")
            app_logger.info(f"  - Image endpoint: http://{self.host}:{actual_port}{self.image_path}")
            app_logger.info(f"  - Status endpoint: http://{self.host}:{actual_port}{self.status_path}")
            return True
            
        except OSError as e:
            if "Address already in use" in str(e):
                app_logger.error(f"Port {self.port} already in use. Choose a different port.")
            else:
                app_logger.error(f"Failed to start web server: {e}")
            return False
        except Exception as e:
            app_logger.error(f"Unexpected error starting web server: {e}")
            return False
    
    def _run_server(self):
        """Run the HTTP server (called in background thread)."""
        try:
            app_logger.debug("Web server thread started")
            self.server.serve_forever()
        except Exception as e:
            app_logger.error(f"Web server error: {e}")
        finally:
            app_logger.debug("Web server thread stopped")
    
    def stop(self):
        """Stop the HTTP server."""
        if not self.running:
            return
        
        try:
            app_logger.info("Stopping web server...")
            self.running = False
            if self.server:
                self.server.shutdown()
                self.server.server_close()
            if self.server_thread:
                self.server_thread.join(timeout=2.0)
            app_logger.info("Web server stopped")
        except Exception as e:
            app_logger.error(f"Error stopping web server: {e}")
    
    def update_image(self, image_path, image_data_bytes, metadata=None, content_type='image/jpeg'):
        """
        Update the latest image to serve.
        
        Args:
            image_path: Path to the saved image file (for reference)
            image_data_bytes: Image data as bytes (JPEG or PNG)
            metadata: Optional dict with image metadata
            content_type: MIME type (default: 'image/jpeg')
        """
        if not self.running:
            return
        
        try:
            ImageHTTPHandler.latest_image_path = image_path
            ImageHTTPHandler.latest_image_data = image_data_bytes
            ImageHTTPHandler.latest_image_content_type = content_type
            ImageHTTPHandler.latest_metadata = metadata or {}
            ImageHTTPHandler.image_count += 1
            app_logger.debug(f"Web server updated with new image: {os.path.basename(image_path)} ({len(image_data_bytes)} bytes, {content_type})")
        except Exception as e:
            app_logger.error(f"Error updating web server image: {e}")
    
    def get_url(self):
        """Get the full URL for the image endpoint."""
        if self.running and self.server:
            actual_port = self.server.server_port
            return f"http://{self.host}:{actual_port}{self.image_path}"
        return None
    
    def get_status_url(self):
        """Get the full URL for the status endpoint."""
        if self.running and self.server:
            actual_port = self.server.server_port
            return f"http://{self.host}:{actual_port}{self.status_path}"
        return None
