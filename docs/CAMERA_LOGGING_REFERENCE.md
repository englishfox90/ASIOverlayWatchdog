# Camera Logging Quick Reference

## Quick Log Search Patterns

When troubleshooting camera issues, search for these patterns in `watchdog.log`:

### Finding Specific Events

| Search Term | What It Shows |
|------------|---------------|
| `===` | Major section headers (detection, connection, capture start) |
| `✓` | All successful operations |
| `✗` | All errors and failures |
| `⚠` | Warnings and advisory messages |
| `⏸` | Off-peak mode / camera disconnected for schedule |
| `▶` | Active mode / camera reconnecting for schedule |
| `reconnect` | All reconnection attempts and results |
| `schedule` | Schedule window transitions |
| `CRITICAL` | Fatal errors requiring manual intervention |

### Common Issue Patterns

#### Camera Disconnected
```log
✗ ERROR in capture loop: Camera disconnected
Consecutive errors: 1/5
Initiating reconnection attempt 1/5...
```
**Next steps:** Check USB cable, verify camera power, check USB drivers

#### Reconnection Failed
```log
✗ Reconnection attempt failed: USB device not found
Using exponential backoff: waiting 4s before retry 2/5...
```
**Next steps:** Camera may be physically disconnected, check hardware

#### Max Reconnection Attempts
```log
✗ CRITICAL: Maximum reconnection attempts (5) reached
Camera appears to be disconnected or unresponsive
Troubleshooting: 1) Check USB cable, 2) Check camera power, 3) Check USB drivers, 4) Restart application
```
**Next steps:** Manual intervention required - check hardware and restart app

#### Detection Timeout
```log
✗ Camera detection timed out after 10 seconds
Possible causes: 1) Camera in use by another app, 2) USB driver issue, 3) Camera hardware problem
```
**Next steps:** Close other apps using camera, verify USB drivers

#### No Cameras Detected
```log
⚠ No cameras detected by SDK
Check: 1) USB cable connected, 2) Camera powered, 3) USB drivers installed
```
**Next steps:** Verify physical connections and camera power

### Schedule Verification

#### Entering Off-Peak Mode
```log
⏸ Outside scheduled capture window (17:00 - 09:00)
Entering off-peak mode: disconnecting camera to reduce hardware load...
✓ Camera disconnected for off-peak hours (reducing hardware load)
```

#### Entering Active Capture Window
```log
▶ Entered scheduled capture window (17:00 - 09:00)
Transitioning to active capture mode: reconnecting camera...
✓ Camera reconnected successfully for scheduled captures
```

## Healthy Capture Session Example

```log
[2025-12-22 17:00:00] INFO     === Starting Camera Capture ===
[2025-12-22 17:00:00] INFO     Selected camera: ASI676MC (ID: 12345678)
[2025-12-22 17:00:00] INFO     Camera settings: Exposure=1000ms, Gain=100, WB(R=75, B=99)
[2025-12-22 17:00:00] INFO     Scheduled capture enabled: 17:00 - 09:00
[2025-12-22 17:00:01] INFO     === Connecting to Camera (Index: 0) ===
[2025-12-22 17:00:01] INFO     ✓ Connected to camera: ASI676MC
[2025-12-22 17:00:01] INFO     ✓ Camera connection successful
[2025-12-22 17:00:02] INFO     ✓ Camera capture started successfully
[2025-12-22 17:00:02] INFO     === Capture Loop Started ===
[2025-12-22 17:00:07] INFO     Captured frame: ASI676MC_20251222_170007.png
[2025-12-22 17:00:12] INFO     Captured frame: ASI676MC_20251222_170012.png
```

## Problem Capture Session Example

```log
[2025-12-22 18:30:15] INFO     Captured frame: ASI676MC_20251222_183015.png
[2025-12-22 18:30:20] ERROR    ✗ ERROR in capture loop: Camera disconnected
[2025-12-22 18:30:20] ERROR    Consecutive errors: 1/5
[2025-12-22 18:30:20] INFO     Initiating reconnection attempt 1/5...
[2025-12-22 18:30:20] INFO     Cleaning up existing camera connection...
[2025-12-22 18:30:21] ERROR    ✗ Reconnection attempt failed: USB device not found
[2025-12-22 18:30:21] INFO     Using exponential backoff: waiting 2s before retry 2/5...
[2025-12-22 18:30:23] ERROR    ✗ Reconnection attempt failed: USB device not found
[2025-12-22 18:30:23] INFO     Using exponential backoff: waiting 4s before retry 3/5...
```

## Monitoring During Unattended Operation

### What to Check After 24 Hours

1. **Search for `CRITICAL`** - Any fatal errors?
2. **Count `✗ ERROR in capture loop`** - How many disconnects?
3. **Count `✓ Camera reconnected successfully`** - Were reconnections successful?
4. **Search for schedule transitions** (`⏸` and `▶`) - Did schedule work correctly?
5. **Check last log timestamp** - Is capture still running?

### Healthy 24-Hour Run Indicators

- ✓ No CRITICAL errors
- ✓ Schedule transitions at correct times (if enabled)
- ✓ Steady capture rate (frames every interval seconds)
- ✓ Any disconnects were successfully recovered
- ✓ Last log entry is recent (within last interval)

### Problematic 24-Hour Run Indicators

- ✗ Multiple CRITICAL errors
- ✗ Schedule transitions at wrong times
- ✗ Long gaps between captures
- ✗ Reconnection attempts consistently failing
- ✗ Last log entry is hours old

## Log Analysis Commands

### PowerShell Commands

```powershell
# Count errors
Select-String -Path $env:LOCALAPPDATA\ASIOverlayWatchDog\Logs\watchdog.log -Pattern "ERROR" | Measure-Object

# Count successful reconnections
Select-String -Path $env:LOCALAPPDATA\ASIOverlayWatchDog\Logs\watchdog.log -Pattern "Camera reconnected successfully" | Measure-Object

# Find all schedule transitions
Select-String -Path $env:LOCALAPPDATA\ASIOverlayWatchDog\Logs\watchdog.log -Pattern "schedule"

# Find last 10 critical errors
Select-String -Path $env:LOCALAPPDATA\ASIOverlayWatchDog\Logs\watchdog.log -Pattern "CRITICAL" | Select-Object -Last 10

# View last 100 lines
Get-Content $env:LOCALAPPDATA\ASIOverlayWatchDog\Logs\watchdog.log -Tail 100
```

## Integration with Discord Alerts

Camera errors that trigger Discord alerts will have corresponding log entries:

**In Discord:**
```
❌ Error Alert
Camera error callback: Camera disconnected - failed to reconnect after multiple attempts
```

**In Logs:**
```log
[timestamp] ERROR    ✗ CRITICAL: Maximum reconnection attempts (5) reached
[timestamp] ERROR    Camera appears to be disconnected or unresponsive
[timestamp] INFO     Stopping capture loop. Manual intervention required.
```

## Tips for Long-Term Monitoring

1. **Set up log rotation** - Already configured for 7 days
2. **Monitor log file size** - Each day creates a new log file
3. **Create monitoring script** - Check for CRITICAL errors daily
4. **Review logs weekly** - Look for patterns in reconnections
5. **Keep old logs** - Useful for identifying intermittent issues

## Contact Support With

When reporting camera issues, provide:
1. Last 500 lines of log file before the issue
2. Any CRITICAL error messages
3. Camera model and ID from logs
4. Schedule configuration (if enabled)
5. USB connection type (USB 2.0, 3.0, hub, etc.)

Example extraction:
```powershell
Get-Content $env:LOCALAPPDATA\ASIOverlayWatchDog\Logs\watchdog.log -Tail 500 | Out-File camera_issue_logs.txt
```
