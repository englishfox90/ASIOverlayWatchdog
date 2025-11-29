# Output Mode Feature

ASIOverlayWatchDog now supports three output modes for maximum flexibility in your imaging workflow.

## Output Modes

### 1. File Mode (Default)
**Save processed images to disk**

- Traditional file-based output
- Saves images to configured output directory
- Supports PNG (lossless) and JPEG formats
- Configurable filename patterns with tokens
- Perfect for archiving and offline processing

**Use Case**: Standard image capture and archiving workflow

---

### 2. Web Server Mode
**Serve latest image via HTTP**

Runs an HTTP server that serves the most recently processed image. Perfect for integration with NINA, web dashboards, or remote monitoring.

**Endpoints:**
- `/latest` - Latest processed image (PNG format)
- `/status` - Server status and metadata (JSON)

**Configuration:**
- **Host**: Interface to bind (0.0.0.0 for all, 127.0.0.1 for localhost only)
- **Port**: HTTP port (default 8080)
- **Image Path**: URL path for image endpoint (default /latest)

**Example URLs:**
```
http://localhost:8080/latest          # Latest image
http://localhost:8080/status          # Server status JSON
http://192.168.1.100:8080/latest      # From other devices on network
```

**Use Case**: 
- NINA integration for live all-sky monitoring
- Web dashboards displaying current sky conditions
- Remote monitoring from mobile devices
- Integration with automation systems

**NINA Setup:**
1. Go to Settings → Output Mode
2. Select "🌐 Web Server"
3. Configure host (use 0.0.0.0 to allow network access)
4. Set port (8080 or custom)
5. Click "✓ Apply All Settings"
6. Note the URL shown in status (e.g., http://0.0.0.0:8080/latest)
7. In NINA: Add "Image Viewer" → Set URL to server address

---

### 3. RTSP Stream Mode
**Stream via RTSP protocol**

Streams processed images via RTSP for viewing in VLC, OBS, NINA, or any RTSP-compatible viewer. Uses ffmpeg to bridge frames to RTSP.

**Configuration:**
- **Host**: Interface to bind (0.0.0.0 for all)
- **Port**: RTSP port (default 8554)
- **Stream Name**: Stream identifier in URL (default: asiwatchdog)
- **FPS**: Frame rate for stream (0.1 to 30 fps, default 1.0)

**Example URL:**
```
rtsp://localhost:8554/asiwatchdog
rtsp://192.168.1.100:8554/asiwatchdog
```

**Use Case:**
- NINA RTSP viewer for live monitoring
- VLC playback of all-sky stream
- OBS streaming/recording
- IP camera viewers
- Multi-monitor observatory setups

**Requirements:**
- **ffmpeg** must be installed and in PATH
- Download from: https://ffmpeg.org/download.html
- Windows users: Add ffmpeg.exe to PATH environment variable

**VLC Playback:**
1. Open VLC Media Player
2. Media → Open Network Stream
3. Enter: `rtsp://localhost:8554/asiwatchdog`
4. Click Play

**OBS Studio:**
1. Add Source → Media Source
2. Uncheck "Local File"
3. Input: `rtsp://localhost:8554/asiwatchdog`
4. Click OK

**Troubleshooting:**
- "ffmpeg not found" error → Install ffmpeg and add to PATH
- Port conflict → Change RTSP port in settings
- Black screen → Check FPS setting (try 1.0 for slow captures)
- Frame size changes → Server automatically restarts ffmpeg

---

## Configuration

### Changing Output Mode

1. Open **Settings** tab
2. Locate **Output Mode** card at top
3. Select desired mode:
   - 💾 **Save to File** - Traditional file saving
   - 🌐 **Web Server** - HTTP server
   - 📡 **RTSP Stream** - RTSP streaming
4. Configure mode-specific settings (shown when selected)
5. Click **✓ Apply All Settings**
6. Status will show active URL when server running

### Mode-Specific Settings

Settings panels are shown/hidden automatically based on selected mode:

**File Mode:**
- No additional settings (uses standard output directory)

**Web Server:**
- Host, Port, Image Path

**RTSP Stream:**
- Host, Port, Stream Name, FPS

### Persistence

Output mode settings are saved to `config.json` and restored on app restart. If a server mode was active, you need to re-apply settings after restart to start the server.

---

## Integration Examples

### NINA Image Viewer
```
1. Settings → Output Mode → Web Server
2. Host: 0.0.0.0, Port: 8080
3. Apply Settings
4. NINA → Image Viewer → URL: http://<your-pc-ip>:8080/latest
5. Set refresh interval (e.g., 5 seconds)
```

### Web Dashboard
```html
<img src="http://192.168.1.100:8080/latest" 
     alt="All Sky" 
     onload="setTimeout(() => this.src = this.src.split('?')[0] + '?' + Date.now(), 5000)">
```

### ffmpeg Recording from RTSP
```bash
ffmpeg -i rtsp://localhost:8554/asiwatchdog -c copy output.mp4
```

---

## Technical Details

### Web Server
- Built on Python `http.server` module
- Runs in daemon thread (non-blocking)
- Serves images from memory (no disk reads)
- PNG format for lossless quality
- Status endpoint returns JSON with uptime, image count, metadata

### RTSP Stream
- Uses ffmpeg subprocess as RTSP bridge
- Pipes BGR24 raw frames via stdin
- H.264 encoding with ultrafast preset
- Automatically handles frame size changes
- Low latency with zerolatency tuning

### Performance
- **Web Server**: Minimal overhead, serves from memory
- **RTSP**: ~1-5% CPU for encoding (depends on resolution/fps)
- **File Mode**: Zero overhead (just disk writes)

### Compatibility
- **Web Server**: Works with any HTTP client (browsers, NINA, curl, wget)
- **RTSP**: Compatible with VLC, ffmpeg, NINA, OBS, IP camera viewers
- **File Mode**: Standard image files (PNG/JPEG)

---

## Troubleshooting

### Web Server Issues

**"Port already in use"**
- Another application is using the port
- Try a different port (e.g., 8081, 8082, etc.)
- Check with: `netstat -ano | findstr :8080` (Windows)

**"Connection refused" from other devices**
- Host must be `0.0.0.0` (not `127.0.0.1`)
- Check firewall rules (allow port 8080)
- Verify network connectivity

**404 errors**
- Check image path matches URL (default `/latest`)
- Server may not have processed any images yet
- Check logs for errors

### RTSP Stream Issues

**"ffmpeg not found"**
- Install ffmpeg from https://ffmpeg.org/download.html
- Add ffmpeg to PATH environment variable
- Restart ASIOverlayWatchDog after installing

**Black screen / No frames**
- Wait for first image to be processed
- Check FPS setting (lower for slow captures)
- Verify stream URL is correct
- Check logs for ffmpeg errors

**Stream stuttering**
- FPS too high for capture rate
- Lower FPS to match image capture interval
- Network bandwidth issues (lower resolution or FPS)

**"Port already in use"**
- Try different RTSP port (e.g., 8555, 8554, etc.)
- Check if another RTSP server is running

---

## Best Practices

1. **File Mode**: Use for archiving, post-processing pipelines
2. **Web Server**: Use for dashboards, remote viewing, NINA integration
3. **RTSP**: Use for live streaming, recording, multi-monitor setups
4. **Hybrid**: File mode always saves to disk, servers serve latest in addition
5. **Network**: Use 0.0.0.0 for LAN access, 127.0.0.1 for localhost only
6. **Firewall**: Allow configured ports through Windows Firewall
7. **FPS**: Match RTSP FPS to capture interval for smooth playback
8. **Resolution**: Lower resize_percent in Processing settings to reduce bandwidth

---

## Feature Roadmap

Future enhancements under consideration:
- Simultaneous file + server modes
- WebSocket push for zero-latency updates
- HLS streaming for broader compatibility
- Multiple concurrent streams
- Authentication for web/RTSP endpoints
- Bandwidth throttling
- Image compression options for web mode
