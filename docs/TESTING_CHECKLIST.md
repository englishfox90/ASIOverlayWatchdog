# Testing Checklist for ASIOverlayWatchDog v2.0

## Pre-Build Testing (Source)

### 1. Logger Functionality
- [ ] Run application from source: `python main.py`
- [ ] Verify log directory created at `%APPDATA%\ASIOverlayWatchDog\logs`
- [ ] Check `watchdog.log` file exists and is being written
- [ ] Navigate to Logs tab
- [ ] Verify footer shows correct log directory path
- [ ] Click "Open Log Folder" button - Windows Explorer should open
- [ ] Generate several log messages by starting/stopping capture
- [ ] Click "Save Logs..." and save to Desktop
- [ ] Verify saved file contains all log entries with timestamps

### 2. Directory Watch Mode
- [ ] Switch to "Directory Watch" mode
- [ ] Select a watch directory with test images
- [ ] Select an output directory
- [ ] Click "Start Watching"
- [ ] Add a new image to watch directory
- [ ] Verify processed image appears in output directory
- [ ] Check Logs tab for processing messages
- [ ] Verify image counter increments
- [ ] Stop watching

### 3. Camera Capture Mode (Requires ZWO Camera)
- [ ] Connect ZWO ASI camera via USB
- [ ] Switch to "ZWO Camera Capture" mode
- [ ] Click "Detect Cameras" - camera should appear
- [ ] Select camera from dropdown
- [ ] Adjust exposure to 100ms
- [ ] Click "Start Capture"
- [ ] Verify live preview updates in header
- [ ] Verify RGB histogram updates
- [ ] Check image counter increments
- [ ] Verify processed images saved to output directory
- [ ] Stop capture

### 4. Output Modes

#### File Mode (Default)
- [ ] Settings tab → Output Mode → File
- [ ] Start capture (camera or watch mode)
- [ ] Verify images saved to configured output directory

#### Webserver Mode
- [ ] Settings tab → Output Mode → Webserver
- [ ] Configure IP: 127.0.0.1, Port: 8080
- [ ] Click "Apply" then "Start Webserver"
- [ ] Verify green status: "Server Running"
- [ ] Click "Copy URL" button
- [ ] Open browser and paste URL
- [ ] Verify latest image displays
- [ ] Try /status endpoint (should show JSON)
- [ ] Stop webserver

#### RTSP Mode (Requires ffmpeg)
- [ ] Verify ffmpeg installed: `ffmpeg -version` in PowerShell
- [ ] Settings tab → Output Mode → RTSP Stream
- [ ] Configure IP: 127.0.0.1, Port: 8554
- [ ] Click "Apply" then "Start RTSP"
- [ ] Verify green status: "Server Running"
- [ ] Click "Copy URL" button
- [ ] Open VLC Media Player → Media → Open Network Stream
- [ ] Paste URL and play
- [ ] Verify live H.264 stream displays
- [ ] Stop RTSP server

#### RTSP Without ffmpeg
- [ ] Temporarily rename `ffmpeg.exe` to test detection
- [ ] Restart application
- [ ] Settings tab → Output Mode → RTSP Stream
- [ ] Verify "Start RTSP" button is DISABLED
- [ ] Hover over button - tooltip should say "ffmpeg not found"
- [ ] Restore `ffmpeg.exe`

### 5. Overlay System
- [ ] Overlay tab → Click "+" to add overlay
- [ ] Set text: `{CAMERA} - {EXPOSURE}ms @ ISO{GAIN}`
- [ ] Position: Bottom-Left
- [ ] Font size: 32
- [ ] Color: Yellow
- [ ] Enable background
- [ ] Verify preview updates on right side
- [ ] Capture image (camera or watch mode)
- [ ] Open processed image - verify overlay text rendered correctly
- [ ] Test all tokens: {CAMERA}, {EXPOSURE}, {GAIN}, {TEMP}, {RES}, {FILENAME}, {SESSION}, {DATETIME}

### 6. Command Line Options

#### Auto-Start
- [ ] Close application
- [ ] Run: `python main.py --auto-start`
- [ ] Check Logs: Should see "Auto-start: Starting camera capture..."
- [ ] Verify camera starts automatically after 3-second delay
- [ ] Verify images being captured
- [ ] Close application

#### Auto-Stop
- [ ] Run: `python main.py --auto-start --auto-stop 15`
- [ ] Verify camera starts automatically
- [ ] Wait 15 seconds
- [ ] Check Logs: Should see "Auto-stop: Stopping camera capture"
- [ ] Verify capture stopped
- [ ] Application should remain open

#### Headless (Experimental)
- [ ] Run: `python main.py --auto-start --headless`
- [ ] Verify no GUI window appears (check Task Manager for process)
- [ ] Check log file for capture activity
- [ ] Press Ctrl+C to stop

### 7. Cleanup System
- [ ] Settings tab → Enable cleanup
- [ ] Set max size to 1 GB
- [ ] Fill output directory with > 1GB of test images
- [ ] Start capture
- [ ] Verify cleanup triggers and deletes oldest files
- [ ] Verify folders NOT deleted (only files)
- [ ] Check Logs for cleanup messages

### 8. Error Handling

#### Missing DLL
- [ ] Rename `ASICamera2.dll` temporarily
- [ ] Switch to Camera mode
- [ ] Click "Detect Cameras"
- [ ] Verify error message: "SDK file not found"
- [ ] Check Logs tab for error
- [ ] Restore `ASICamera2.dll`

#### No Cameras
- [ ] Disconnect ZWO camera
- [ ] Click "Detect Cameras"
- [ ] Verify error: "No cameras detected. Check USB connection."
- [ ] Reconnect camera

#### Invalid Output Directory
- [ ] Settings tab → Set output directory to invalid path (e.g., `Z:\invalid`)
- [ ] Start capture
- [ ] Verify error logged
- [ ] Set valid path

### 9. Window State Persistence
- [ ] Resize main window to 1200x900
- [ ] Move window to custom position
- [ ] Close application
- [ ] Reopen application
- [ ] Verify window size and position restored

### 10. Discord Integration (Optional)
- [ ] Settings tab → Discord Webhooks
- [ ] Enable Discord alerts
- [ ] Enter valid webhook URL
- [ ] Enable "Post startup/shutdown messages"
- [ ] Enable "Post errors"
- [ ] Close and reopen application
- [ ] Verify startup message in Discord channel
- [ ] Trigger an error (e.g., invalid path)
- [ ] Verify error alert in Discord
- [ ] Close application
- [ ] Verify shutdown message in Discord

---

## Build Testing (PyInstaller Executable)

### 1. Build Process
- [ ] Activate venv: `.\venv\Scripts\Activate.ps1`
- [ ] Clean previous build: Delete `dist/` and `build/` folders
- [ ] Run: `pyinstaller --clean ASIOverlayWatchDog.spec`
- [ ] Verify no build errors
- [ ] Check output: `dist/ASIOverlayWatchDog/ASIOverlayWatchDog.exe` exists
- [ ] Verify file size ~50-80MB

### 2. Executable Launch
- [ ] Navigate to `dist/ASIOverlayWatchDog/`
- [ ] Double-click `ASIOverlayWatchDog.exe`
- [ ] Verify NO CONSOLE WINDOW appears (windowed app)
- [ ] Verify GUI launches normally
- [ ] Check Task Manager - only one process running

### 3. Log Directory (Executable)
- [ ] Check `%APPDATA%\ASIOverlayWatchDog\logs` exists
- [ ] Verify `watchdog.log` created
- [ ] Logs tab → Verify footer shows correct APPDATA path
- [ ] Click "Open Log Folder" - verify correct location opens

### 4. Config Persistence (Executable)
- [ ] Check `dist/ASIOverlayWatchDog/config.json` created
- [ ] Make settings changes (output directory, overlays, etc.)
- [ ] Close executable
- [ ] Reopen executable
- [ ] Verify all settings restored from config.json

### 5. Camera Capture (Executable)
- [ ] Ensure `ASICamera2.dll` in `dist/ASIOverlayWatchDog/`
- [ ] Connect ZWO camera
- [ ] Detect cameras
- [ ] Start capture
- [ ] Verify images saved
- [ ] Stop capture

### 6. Output Modes (Executable)
- [ ] Test File mode - verify saves work
- [ ] Test Webserver mode - verify http://127.0.0.1:8080/latest works
- [ ] Test RTSP mode (if ffmpeg in PATH) - verify VLC can play stream
- [ ] Stop all servers

### 7. Command Line (Executable)
- [ ] Open PowerShell in `dist/ASIOverlayWatchDog/`
- [ ] Run: `.\ASIOverlayWatchDog.exe --auto-start --auto-stop 10`
- [ ] Verify camera starts automatically
- [ ] Wait 10 seconds
- [ ] Verify capture stops
- [ ] Close application

### 8. Error Recovery (Executable)
- [ ] Force crash (e.g., delete config.json while running)
- [ ] Verify application doesn't hang
- [ ] Check logs for error messages
- [ ] Restart and verify recovery

### 9. Resource Cleanup (Executable)
- [ ] Start camera capture
- [ ] Start webserver
- [ ] Start RTSP server (if ffmpeg available)
- [ ] Close application using window X button
- [ ] Check Task Manager - no lingering processes
- [ ] Verify all servers stopped (ports released)

### 10. Multi-Day Log Rotation (Long-term)
- [ ] Run executable for several days
- [ ] Check log directory daily
- [ ] Verify new `watchdog.log.YYYY-MM-DD` files created daily
- [ ] After 8 days, verify oldest log deleted (only 7 days kept)

---

## Distribution Testing

### 1. Clean Installation Test
- [ ] Copy `dist/ASIOverlayWatchDog/` folder to test machine (no Python installed)
- [ ] Copy `ASICamera2.dll` to folder
- [ ] Run executable
- [ ] Verify works without Python runtime
- [ ] Test basic capture functionality

### 2. Network Isolation Test
- [ ] Disconnect from internet
- [ ] Run executable
- [ ] Verify all features work offline (except Discord)
- [ ] Reconnect internet

### 3. User Account Test
- [ ] Create new Windows user account
- [ ] Copy executable folder
- [ ] Run as new user
- [ ] Verify `%APPDATA%\ASIOverlayWatchDog\logs` created for new user
- [ ] Verify separate config.json created

---

## Performance Testing

### 1. Memory Leak Test
- [ ] Start camera capture (1-second exposure)
- [ ] Let run for 30 minutes
- [ ] Monitor memory usage in Task Manager
- [ ] Memory should stabilize (~100-200MB), not continuously grow
- [ ] Stop capture

### 2. Long-Running Stability
- [ ] Start camera capture
- [ ] Enable auto-exposure
- [ ] Let run overnight (8+ hours)
- [ ] Check logs next day for errors
- [ ] Verify capture still running
- [ ] Stop capture

### 3. High Frame Rate Test
- [ ] Set exposure to minimum (0.032ms)
- [ ] Start capture
- [ ] Monitor CPU usage (should be <50% on modern CPU)
- [ ] Let run for 5 minutes
- [ ] Verify no dropped frames or errors
- [ ] Stop capture

---

## Edge Cases

### 1. Disk Full Scenario
- [ ] Create small virtual disk (1GB)
- [ ] Set output directory to virtual disk
- [ ] Disable cleanup
- [ ] Start capture until disk full
- [ ] Verify error logged gracefully
- [ ] Verify application doesn't crash

### 2. Rapid Mode Switching
- [ ] Switch between Directory Watch and Camera modes rapidly (10 times)
- [ ] Verify no crashes or race conditions
- [ ] Check logs for errors

### 3. Simultaneous Operations
- [ ] Start camera capture
- [ ] Enable webserver
- [ ] Enable RTSP server
- [ ] Open browser to webserver
- [ ] Open VLC to RTSP stream
- [ ] Verify all work simultaneously
- [ ] Stop all

### 4. Unicode Paths
- [ ] Create folder with unicode name: `测试_Тест_🌙`
- [ ] Set as output directory
- [ ] Capture image
- [ ] Verify saves correctly
- [ ] Verify logs show path correctly

---

## Regression Testing (After Future Updates)

- [ ] Re-run entire Source testing section
- [ ] Re-run entire Executable testing section
- [ ] Verify no features broken
- [ ] Test new features specifically

---

## Sign-Off

**Tested by:** _________________  
**Date:** _________________  
**Version:** 2.0.0  
**Build:** _________________  

**Issues Found:** _________________  
**Status:** ☐ Pass  ☐ Pass with issues  ☐ Fail  

**Notes:**
