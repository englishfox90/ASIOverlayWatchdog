"""
Test web server functionality
"""
import pytest
import requests
import time
import io
import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services.web_output import WebOutputServer, ImageHTTPHandler
from PIL import Image


class TestWebServerBasic:
    """Test basic web server functionality"""
    
    def test_server_starts_and_stops(self):
        """Test server can start and stop cleanly"""
        server = WebOutputServer(host='127.0.0.1', port=18080)
        
        assert server.start() == True
        assert server.running == True
        
        server.stop()
        assert server.running == False
    
    def test_server_reports_correct_url(self):
        """Test server returns correct URL"""
        server = WebOutputServer(host='127.0.0.1', port=18081, image_path='/latest')
        server.start()
        
        try:
            url = server.get_url()
            assert '127.0.0.1' in url
            assert '18081' in url
            assert '/latest' in url
        finally:
            server.stop()
    
    def test_server_port_conflict_detection(self):
        """Test server handles port conflict gracefully"""
        server1 = WebOutputServer(host='127.0.0.1', port=18082)
        server1.start()
        
        try:
            server2 = WebOutputServer(host='127.0.0.1', port=18082)
            # Server may or may not start depending on OS
            # The important thing is it doesn't crash
            result = server2.start()
            # Just verify it returns a boolean
            assert isinstance(result, bool)
            if result:
                server2.stop()
        finally:
            server1.stop()


@pytest.mark.requires_network
class TestWebServerImage:
    """Test image serving functionality"""
    
    def test_serve_image(self, sample_image):
        """Test that server serves image correctly"""
        server = WebOutputServer(host='127.0.0.1', port=18083, image_path='/image')
        server.start()
        
        try:
            # Convert image to bytes
            img_bytes = io.BytesIO()
            sample_image.save(img_bytes, format='JPEG')
            img_data = img_bytes.getvalue()
            
            # Update server with image
            server.update_image("test.jpg", img_data, content_type='image/jpeg')
            
            # Give server time to process
            time.sleep(0.2)
            
            # Fetch image via HTTP
            response = requests.get(f"http://127.0.0.1:18083/image", timeout=5)
            
            assert response.status_code == 200
            assert 'image/jpeg' in response.headers.get('Content-Type', '')
            assert len(response.content) > 0
            
        finally:
            server.stop()
    
    def test_serve_png_image(self, sample_image):
        """Test PNG image serving"""
        server = WebOutputServer(host='127.0.0.1', port=18084)
        server.start()
        
        try:
            img_bytes = io.BytesIO()
            sample_image.save(img_bytes, format='PNG')
            img_data = img_bytes.getvalue()
            
            server.update_image("test.png", img_data, content_type='image/png')
            time.sleep(0.2)
            
            response = requests.get(server.get_url(), timeout=5)
            
            assert response.status_code == 200
            assert 'image/png' in response.headers.get('Content-Type', '')
            
        finally:
            server.stop()
    
    def test_404_when_no_image(self):
        """Test 404 response when no image available"""
        server = WebOutputServer(host='127.0.0.1', port=18085)
        server.start()
        
        try:
            # Reset handler state
            ImageHTTPHandler.latest_image_data = None
            
            time.sleep(0.2)
            response = requests.get(server.get_url(), timeout=5)
            
            assert response.status_code == 404
            
        finally:
            server.stop()
    
    def test_etag_caching(self, sample_image):
        """Test ETag-based caching works"""
        server = WebOutputServer(host='127.0.0.1', port=18086)
        server.start()
        
        try:
            img_bytes = io.BytesIO()
            sample_image.save(img_bytes, format='JPEG')
            server.update_image("test.jpg", img_bytes.getvalue())
            time.sleep(0.2)
            
            # First request - should get image
            response1 = requests.get(server.get_url(), timeout=5)
            assert response1.status_code == 200
            etag = response1.headers.get('ETag')
            assert etag is not None
            
            # Second request with ETag - should get 304
            response2 = requests.get(
                server.get_url(),
                headers={'If-None-Match': etag},
                timeout=5
            )
            assert response2.status_code == 304
            
        finally:
            server.stop()


@pytest.mark.requires_network
class TestWebServerStatus:
    """Test status endpoint functionality"""
    
    def test_status_endpoint(self):
        """Test status endpoint returns valid JSON"""
        server = WebOutputServer(host='127.0.0.1', port=18087, status_path='/status')
        server.start()
        
        try:
            time.sleep(0.2)
            response = requests.get(server.get_status_url(), timeout=5)
            
            assert response.status_code == 200
            data = response.json()
            
            assert 'status' in data
            assert data['status'] == 'running'
            assert 'uptime_seconds' in data
            
        finally:
            server.stop()
    
    def test_status_tracks_image_count(self, sample_image):
        """Test status endpoint tracks served images"""
        server = WebOutputServer(host='127.0.0.1', port=18088, status_path='/status')
        server.start()
        
        try:
            img_bytes = io.BytesIO()
            sample_image.save(img_bytes, format='JPEG')
            
            # Update image multiple times
            for i in range(3):
                server.update_image(f"test_{i}.jpg", img_bytes.getvalue())
            
            time.sleep(0.2)
            response = requests.get(server.get_status_url(), timeout=5)
            data = response.json()
            
            assert data['images_served'] >= 3
            
        finally:
            server.stop()
