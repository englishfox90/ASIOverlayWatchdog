"""
Camera enumeration for ZWO ASI cameras.

Extracted from camera_connection.py (which sits at the file-size cap). Operates
on a CameraConnection instance — do not import directly from other modules; call
through CameraConnection.detect_cameras().
"""
import time
import concurrent.futures
from typing import Any, Dict, List


def detect_cameras(conn) -> List[Dict[str, Any]]:
    """Detect connected ZWO cameras. Returns dicts with 'index' and 'name'.

    Mutates conn.cameras with the result. Bounded SDK calls so a wedged USB
    device can't hang detection.
    """
    conn.log("=== Starting Camera Detection ===")

    if not conn.asi:
        conn.log("SDK not initialized, initializing now...")
        if not conn.initialize_sdk():
            conn.log("Camera detection failed: SDK initialization failed")
            return []

    try:
        conn.log("Querying SDK for number of connected cameras...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            try:
                num_cameras = ex.submit(conn.asi.get_num_cameras).result(timeout=10.0)
            except concurrent.futures.TimeoutError:
                conn.log("⚠ get_num_cameras() timed out (10s) — SDK wedged, aborting detection")
                return []
        conn.cameras = []

        if num_cameras == 0:
            conn.log("⚠ No ZWO cameras detected by SDK")
            conn.log("Check: 1) USB cable connected, 2) Camera powered, 3) USB drivers installed")
            return []

        conn.log(f"✓ Found {num_cameras} ZWO camera(s) connected")
        conn.log("Enumerating camera details...")

        # Snapshot list_cameras() once — calling it per-iteration races against
        # the driver still binding after a hot-plug / disable-enable cycle,
        # producing "list index out of range" on the just-appeared camera.
        # If the list is shorter than num_cameras, retry a few times to let
        # the SDK converge.
        camera_list = []
        for poll_attempt in range(3):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                try:
                    camera_list = list(ex.submit(conn.asi.list_cameras).result(timeout=10.0))
                except concurrent.futures.TimeoutError:
                    conn.log("⚠ list_cameras() timed out (10s) — SDK wedged, aborting detection")
                    return []
            if len(camera_list) >= num_cameras:
                break
            conn.log(
                f"  ⚠ Enumeration race: get_num_cameras={num_cameras} but "
                f"list_cameras returned {len(camera_list)} — retrying in 1s "
                f"({poll_attempt + 1}/3)"
            )
            time.sleep(1.0)

        # If we still disagree after retries, trust list_cameras() — it's the
        # one that returns actual names we can use.
        for i, name in enumerate(camera_list):
            conn.cameras.append({'index': i, 'name': name})
            conn.log(f"  ✓ Camera {i}: {name}")

        if len(camera_list) != num_cameras:
            conn.log(
                f"  ⚠ Enumeration still inconsistent after retries: "
                f"num_cameras={num_cameras}, enumerated={len(camera_list)}"
            )

        conn.log(f"Camera detection complete: {len(conn.cameras)} camera(s) enumerated")
        return conn.cameras

    except Exception as e:
        conn.log(f"ERROR during camera detection: {e}")
        import traceback
        conn.log(f"Stack trace: {traceback.format_exc()}")
        return []


def log_invalid_id_diagnostics(conn, camera_index: int) -> None:
    """Log diagnostic context for an 'Invalid ID' open failure."""
    conn.log("=== Diagnostic Information ===")
    conn.log(f"Attempted camera index: {camera_index}")
    conn.log("This error typically occurs when:")
    conn.log("  1. Camera was not properly closed by another process")
    conn.log("  2. SDK is in an inconsistent state")
    conn.log("  3. Camera index changed (hot plug event)")
    conn.log("Recommended action: Try stopping/restarting the application")

    try:
        num_cameras = conn.asi.get_num_cameras()
        conn.log(f"Current SDK state: {num_cameras} camera(s) reported by SDK")
        for idx, name in enumerate(conn.asi.list_cameras()):
            conn.log(f"  Camera {idx}: {name}")
    except Exception as diag_err:
        conn.log(f"  Could not query camera list for diagnostics: {diag_err}")
