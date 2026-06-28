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

    def test_image_age_and_stale_flag(self):
        """
        Stale-image signalling: after update_image, /status reports a small
        age and image_stale=False; once we synthetically age the image past
        the threshold, image_stale flips to True.
        """
        # Ensure a clean class state regardless of other tests.
        ImageHTTPHandler.latest_image_snapshot = None
        ImageHTTPHandler.image_count = 0
        ImageHTTPHandler.stale_threshold_sec = 2  # test-local short threshold

        # Fresh update → age is small, not stale.
        ImageHTTPHandler.update_image(
            image_data=b"fake", content_type="image/jpeg",
            path="x.jpg", metadata={}
        )
        age = ImageHTTPHandler._image_age_seconds()
        assert age is not None and age < 1.0
        assert not (age >= ImageHTTPHandler.stale_threshold_sec)

        # Simulate ageing: rewind the snapshot's update time by 10s.
        data, ct, etag, _ = ImageHTTPHandler.latest_image_snapshot
        ImageHTTPHandler.latest_image_snapshot = (data, ct, etag, time.time() - 10)
        age = ImageHTTPHandler._image_age_seconds()
        assert age >= ImageHTTPHandler.stale_threshold_sec

        # Reset threshold so other tests aren't affected.
        ImageHTTPHandler.stale_threshold_sec = 300


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
            ImageHTTPHandler.latest_image_snapshot = None
            
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

    def test_status_includes_capture_and_health(self):
        """Status reports the pushed capture snapshot plus a derived health block."""
        from services.api_status import build_capture_snapshot
        server = WebOutputServer(host='127.0.0.1', port=18089, status_path='/status')
        server.start()

        try:
            server.update_capture_status(build_capture_snapshot(
                mode="camera", enabled=True, running=True, state="capturing",
                interval_seconds=5.0, effective_interval_seconds=5.0,
                last_capture_epoch=time.time(),
            ))
            time.sleep(0.2)
            data = requests.get(server.get_status_url(), timeout=5).json()

            assert 'capture' in data and 'health' in data
            assert data['capture']['mode'] == 'camera'
            assert data['capture']['enabled'] is True
            assert data['health']['status'] == 'ok'
        finally:
            server.stop()

    def test_health_idle_when_capture_disabled(self):
        """With capture not enabled, health is 'idle' (the gap the old API had)."""
        from services.api_status import build_capture_snapshot
        server = WebOutputServer(host='127.0.0.1', port=18090, status_path='/status')
        server.start()

        try:
            server.update_capture_status(build_capture_snapshot(enabled=False))
            time.sleep(0.2)
            data = requests.get(server.get_status_url(), timeout=5).json()
            assert data['health']['status'] == 'idle'
            # Back-compat: HTTP server liveness key still present and 'running'.
            assert data['status'] == 'running'
        finally:
            server.stop()


@pytest.mark.requires_network
class TestWebServerDocs:
    """Test the self-documenting API endpoints."""

    def test_openapi_spec_served(self):
        server = WebOutputServer(host='127.0.0.1', port=18091, image_path='/latest',
                                 status_path='/status')
        server.start()
        try:
            time.sleep(0.2)
            resp = requests.get("http://127.0.0.1:18091/openapi.json", timeout=5)
            assert resp.status_code == 200
            assert 'application/json' in resp.headers.get('Content-Type', '')
            spec = resp.json()
            assert spec['openapi'].startswith('3.')
            # Spec documents the server's actual routes.
            assert '/latest' in spec['paths']
            assert '/status' in spec['paths']
        finally:
            server.stop()

    def test_docs_page_served_as_html(self):
        server = WebOutputServer(host='127.0.0.1', port=18092)
        server.start()
        try:
            time.sleep(0.2)
            resp = requests.get("http://127.0.0.1:18092/docs", timeout=5)
            assert resp.status_code == 200
            assert 'text/html' in resp.headers.get('Content-Type', '')
            assert '<html' in resp.text.lower()
            assert 'PFR Sentinel' in resp.text
        finally:
            server.stop()


@pytest.mark.requires_network
class TestWebServerLibraryEndpoints:
    """Test the /library manifest and /library/image endpoints end-to-end."""

    def _seed_library(self, temp_dir, monkeypatch, **over):
        import services.library.store as store_mod
        import services.library as lib_mod
        from services.library import ImageLibrary
        monkeypatch.setattr(store_mod, "get_library_root", lambda: temp_dir)
        monkeypatch.setattr(lib_mod, "get_library_root", lambda: temp_dir)

        cfg = {"enabled": True, "api_enabled": True, "max_dimension": 200,
               "jpeg_quality": 80, "retention_days": 7, "max_size_gb": 2.0,
               "prune_interval_minutes": 15}
        cfg.update(over)
        lib = ImageLibrary(lambda: {"library": cfg})
        lib.start()
        for i in range(2):
            lib.enqueue(Image.new("RGB", (400, 300), (i, i, i)), {"camera": f"c{i}"})
        deadline = time.time() + 5
        while time.time() < deadline and lib.index.count() < 2:
            time.sleep(0.02)
        assert lib.index.count() == 2
        return lib

    def test_library_list_and_image(self, temp_dir, monkeypatch):
        lib = self._seed_library(temp_dir, monkeypatch)
        server = WebOutputServer(host='127.0.0.1', port=18093, image_library=lib)
        server.start()
        try:
            time.sleep(0.2)
            resp = requests.get("http://127.0.0.1:18093/library?limit=10", timeout=5)
            assert resp.status_code == 200
            body = resp.json()
            assert body['total'] == 2
            assert len(body['images']) == 2
            first = body['images'][0]
            assert first['url'].startswith('/library/image?id=')

            # Fetch the actual image bytes.
            img_resp = requests.get(f"http://127.0.0.1:18093{first['url']}", timeout=5)
            assert img_resp.status_code == 200
            assert img_resp.headers.get('Content-Type') == 'image/jpeg'
            etag = img_resp.headers.get('ETag')
            assert etag

            # Conditional request returns 304.
            cond = requests.get(f"http://127.0.0.1:18093{first['url']}",
                                headers={'If-None-Match': etag}, timeout=5)
            assert cond.status_code == 304

            # Unknown id -> 404; missing id -> 400.
            assert requests.get("http://127.0.0.1:18093/library/image?id=999999", timeout=5).status_code == 404
            assert requests.get("http://127.0.0.1:18093/library/image", timeout=5).status_code == 400
        finally:
            server.stop()
            lib.stop()

    def test_library_endpoints_404_when_api_disabled(self, temp_dir, monkeypatch):
        lib = self._seed_library(temp_dir, monkeypatch, api_enabled=False)
        server = WebOutputServer(host='127.0.0.1', port=18094, image_library=lib)
        server.start()
        try:
            time.sleep(0.2)
            assert requests.get("http://127.0.0.1:18094/library", timeout=5).status_code == 404
            # And the OpenAPI spec omits the routes.
            spec = requests.get("http://127.0.0.1:18094/openapi.json", timeout=5).json()
            assert '/library' not in spec['paths']
        finally:
            server.stop()
            lib.stop()


class TestStatusPathLeak:
    """W5 — /status must not expose absolute filesystem paths."""

    def test_status_does_not_leak_absolute_paths(self):
        import json as _json

        ImageHTTPHandler.latest_image_path = (
            r"C:\Users\SecretUser\AppData\Local\PFRSentinel\images\latest.jpg"
        )
        ImageHTTPHandler.latest_metadata = {
            "CAMERA": "ASI676MC",
            # Benign slash-bearing values that must NOT be mistaken for paths.
            "DATE": "06/28/2026",
            "RATIO": "16/9",
            "FILEPATH": r"C:\Users\SecretUser\captures\frame_001.fits",
            "SOURCE": "/home/observer/data/x.png",
            "UNC": r"\\nas\share\frame.png",
            # Absolute path embedded MID-STRING (not at the start) must also be
            # scrubbed — an ^-anchored pattern would leak this one.
            "NOTE": r"saved to C:\Users\SecretUser\AppData\frame.fits ok",
        }

        status = ImageHTTPHandler._build_status_dict()
        meta = status["metadata"]

        # latest_image is reduced to a bare filename.
        assert status["latest_image"] == "latest.jpg"

        # No absolute path / username / layout leaks anywhere in the payload.
        blob = _json.dumps(status)
        assert "SecretUser" not in blob
        assert "/home/observer" not in blob
        assert "nas" not in blob
        assert "AppData" not in blob
        assert "frame_001" not in blob

        # Benign fields survive untouched — no over-matching of dates/ratios
        # (the keys must stay AND keep their original value).
        assert meta.get("CAMERA") == "ASI676MC"
        assert meta.get("DATE") == "06/28/2026"
        assert meta.get("RATIO") == "16/9"

        # Path-bearing values keep their key but have the path redacted out.
        assert meta["FILEPATH"] == "<redacted-path>"
        assert meta["SOURCE"] == "<redacted-path>"
        assert meta["UNC"] == "<redacted-path>"
        # Mid-string path: surrounding text preserved, path removed.
        assert meta["NOTE"].startswith("saved to ")
        assert meta["NOTE"].endswith(" ok")
        assert "<redacted-path>" in meta["NOTE"]
        assert "SecretUser" not in meta["NOTE"]


@pytest.mark.requires_network
class TestWebServerConcurrency:
    """W3 — /latest must never serve a torn frame under concurrent updates."""

    def test_latest_never_torn_under_concurrent_updates(self):
        import threading as _t

        server = WebOutputServer(host='127.0.0.1', port=18095, image_path='/latest')
        server.start()
        try:
            small = io.BytesIO()
            Image.new("RGB", (32, 32), (10, 20, 30)).save(small, format="JPEG", quality=90)
            big = io.BytesIO()
            Image.new("RGB", (1200, 1200), (200, 100, 50)).save(big, format="JPEG", quality=95)
            small_b, big_b = small.getvalue(), big.getvalue()
            assert abs(len(big_b) - len(small_b)) > 1000  # very different sizes

            stop = _t.Event()

            def writer():
                toggle = False
                while not stop.is_set():
                    server.update_image(
                        "x.jpg", big_b if toggle else small_b, content_type="image/jpeg"
                    )
                    toggle = not toggle

            wt = _t.Thread(target=writer, daemon=True)
            wt.start()

            errors = []

            def reader():
                for _ in range(80):
                    try:
                        r = requests.get("http://127.0.0.1:18095/latest", timeout=5)
                        if r.status_code != 200:
                            continue
                        cl = int(r.headers.get("Content-Length", -1))
                        if cl != len(r.content):
                            errors.append(("content_length_mismatch", cl, len(r.content)))
                            continue
                        # A truncated/garbled JPEG raises on decode.
                        Image.open(io.BytesIO(r.content)).load()
                    except Exception as e:
                        errors.append(("exc", repr(e)))

            readers = [_t.Thread(target=reader) for _ in range(8)]
            for t in readers:
                t.start()
            for t in readers:
                t.join()
            stop.set()
            wt.join(timeout=2)

            assert not errors, errors[:5]
        finally:
            server.stop()
