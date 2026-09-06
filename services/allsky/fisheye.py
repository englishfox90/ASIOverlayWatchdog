"""
Fisheye lens model for all-sky camera projection.

Models equidistant-style fisheye lenses with polynomial radial correction:
    r = a1·θ + a3·θ³ + a5·θ⁵

Plus 3 orientation parameters (optical axis alt/az offset, roll).
Provides altaz_to_pixel() and radec_to_pixel() with refraction support.
"""
import json
import os
import numpy as np
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional, Tuple

from .coords import radec_to_altaz, atmospheric_refraction


@dataclass
class FisheyeModel:
    """
    Fisheye lens calibration model.

    Projection: r_px = a1·θ + a3·θ³ + a5·θ⁵
    where θ is the angle from the optical axis in radians.

    Attributes:
        cx, cy       : Optical centre (pixels)
        a1           : Linear radial coefficient (px/rad)
        a3           : Cubic radial coefficient (px/rad³)
        a5           : Quintic radial coefficient (px/rad⁵)
        roll         : Camera roll (radians, + = counter-clockwise)
        axis_alt     : True altitude of optical axis (degrees)
        axis_az      : True azimuth of optical axis (degrees)
        east_left    : True = east is on the LEFT in the image (standard FITS/astronomical
                       convention, used by NINA, ASICAP, SharpCap when saving FITS).
                       False = east is on the RIGHT (normal photo/JPEG convention, used by
                       some webcam-based all-sky cameras that do not flip the image).
                       Detected automatically during calibration — no need to set manually.
        rms_residual : Calibration RMS residual (pixels)
        n_matches    : Number of matched stars used for calibration
        calibrated_at: ISO 8601 UTC timestamp of calibration
        provenance   : What vouched for the model's orientation BASIN
                       (model_admission stamps it on admission).
                       'guided' = solved from user-identified anchor stars
                       (guided_calibration), or admitted as the same basin
                       as such a model; outranks the measured pole.
                       'pole' = admitted while a trusted measured pole
                       confirmed it, or admitted as the same basin as such
                       a model; locks mirror/scale/basin until a fresh
                       trusted pole says otherwise.
                       '' = automatic fit admitted with no pole, or a
                       legacy file: no authority over its replacement.
    """
    cx: float = 960.0
    cy: float = 540.0
    a1: float = 800.0     # Rough initial guess: ~800 px for 180° FOV on 1080p sensor
    a3: float = 0.0
    a5: float = 0.0
    roll: float = 0.0
    axis_alt: float = 90.0
    axis_az: float = 0.0
    east_left: bool = True   # FITS convention (east=LEFT) — auto-detected at calibration
    rms_residual: float = 0.0
    n_matches: int = 0
    n_images: int = 1
    span_minutes: float = 0.0
    calibrated_at: str = ""
    image_width: int = 0   # width of image used for calibration (px); 0 = unknown
    image_height: int = 0  # height of image used for calibration (px); 0 = unknown
    provenance: str = ""   # 'guided' | 'pole' | '' (see class doc)

    def is_valid(self) -> bool:
        """True if model has been successfully calibrated."""
        return self.n_matches >= 5 and self.a1 > 0

    # ------------------------------------------------------------------
    # Core projection: (alt, az) degrees → pixel (x, y)
    # ------------------------------------------------------------------

    def altaz_to_pixel(
        self,
        alt_deg: float,
        az_deg: float,
    ) -> Optional[Tuple[float, float]]:
        """
        Project AltAz sky position to pixel coordinates.
        Returns None if position is below horizon or outside image model.
        """
        if alt_deg < -0.5:
            return None

        # --- Rotate into camera frame ---
        # Convert AltAz to unit vector in horizon frame (East, North, Up)
        alt_r = np.radians(alt_deg)
        az_r = np.radians(az_deg)
        vx =  np.cos(alt_r) * np.sin(az_r)   # East
        vy =  np.cos(alt_r) * np.cos(az_r)   # North
        vz =  np.sin(alt_r)                   # Up

        # Rotate sky vector by camera orientation (axis_alt, axis_az, roll)
        axis_alt_r = np.radians(self.axis_alt)
        axis_az_r  = np.radians(self.axis_az)
        roll_r     = self.roll

        # Step 1: rotate so optical axis points to zenith (alt=90, az=0)
        # Rotation about azimuth axis
        ca, sa = np.cos(-axis_az_r), np.sin(-axis_az_r)
        vx2 = ca * vx - sa * vy
        vy2 = sa * vx + ca * vy
        vz2 = vz

        # Rotation about tilt axis (to align axis_alt with zenith)
        tilt = np.radians(90.0 - self.axis_alt)
        ct, st = np.cos(-tilt), np.sin(-tilt)
        vx3 = vx2
        vy3 = ct * vy2 - st * vz2
        vz3 = st * vy2 + ct * vz2

        # Step 2: apply camera roll
        cr, sr = np.cos(-roll_r), np.sin(-roll_r)
        vx4 = cr * vx3 - sr * vy3
        vy4 = sr * vx3 + cr * vy3
        vz4 = vz3

        # θ = angle from camera boresight (vz4 axis)
        r_xy = np.sqrt(vx4**2 + vy4**2)
        theta = np.arctan2(r_xy, vz4)  # [0, π]

        # Polynomial radial projection
        t2 = theta * theta
        r_px = self.a1 * theta + self.a3 * t2 * theta + self.a5 * t2 * t2 * theta

        if r_px < 0:
            return None

        # Azimuth angle in camera plane.
        # east_left=True  → FITS convention (NINA, ASICAP, SharpCap FITS): east is LEFT
        # east_left=False → normal photo convention (JPEG all-sky cameras): east is RIGHT
        phi = np.arctan2(vx4, vy4)
        east_sign = -1.0 if self.east_left else 1.0

        px = self.cx + east_sign * r_px * np.sin(phi)
        py = self.cy - r_px * np.cos(phi)

        return float(px), float(py)

    def radec_to_pixel(
        self,
        ra_deg: float,
        dec_deg: float,
        lat_deg: float,
        lon_deg: float,
        dt: datetime,
    ) -> Optional[Tuple[float, float]]:
        """
        Convert RA/Dec (J2000) to pixel coordinates for a given observer and time.
        Returns None if below horizon or outside image.
        """
        alt, az = radec_to_altaz(ra_deg, dec_deg, lat_deg, lon_deg, dt,
                                 refraction=True)
        alt = float(alt)
        az = float(az)
        return self.altaz_to_pixel(alt, az)

    # ------------------------------------------------------------------
    # Vectorised version for bulk projection
    # ------------------------------------------------------------------

    def altaz_array_to_pixels(
        self,
        alt_deg: np.ndarray,
        az_deg: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Vectorised projection of arrays of (alt, az) → (px, py).
        Returns (px, py, visible) where visible is a boolean mask.
        """
        alt_r = np.radians(alt_deg)
        az_r  = np.radians(az_deg)
        vx = np.cos(alt_r) * np.sin(az_r)
        vy = np.cos(alt_r) * np.cos(az_r)
        vz = np.sin(alt_r)

        # Orientation rotations (same as scalar version)
        aa_r = np.radians(self.axis_az)
        ca, sa = np.cos(-aa_r), np.sin(-aa_r)
        vx2 = ca * vx - sa * vy
        vy2 = sa * vx + ca * vy
        vz2 = vz

        tilt = np.radians(90.0 - self.axis_alt)
        ct, st = np.cos(-tilt), np.sin(-tilt)
        vx3 = vx2
        vy3 = ct * vy2 - st * vz2
        vz3 = st * vy2 + ct * vz2

        roll_r = self.roll
        cr, sr = np.cos(-roll_r), np.sin(-roll_r)
        vx4 = cr * vx3 - sr * vy3
        vy4 = sr * vx3 + cr * vy3
        vz4 = vz3

        r_xy = np.sqrt(vx4**2 + vy4**2)
        theta = np.arctan2(r_xy, vz4)
        t2 = theta * theta
        r_px = self.a1 * theta + self.a3 * t2 * theta + self.a5 * t2 * t2 * theta

        phi = np.arctan2(vx4, vy4)
        east_sign = -1.0 if self.east_left else 1.0
        px = self.cx + east_sign * r_px * np.sin(phi)
        py = self.cy - r_px * np.cos(phi)

        visible = (alt_deg >= -0.5) & (r_px >= 0)
        return px, py, visible

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Save model to JSON file."""
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls, path: str) -> 'FisheyeModel':
        """Load model from JSON file. Raises FileNotFoundError if missing."""
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def try_load(cls, path: str) -> Optional['FisheyeModel']:
        """Load model from JSON, returning None on any error."""
        try:
            return cls.load(path)
        except Exception:
            return None

    def __repr__(self) -> str:
        return (f"FisheyeModel(cx={self.cx:.1f}, cy={self.cy:.1f}, "
                f"a1={self.a1:.1f}, a3={self.a3:.4f}, a5={self.a5:.6f}, "
                f"rms={self.rms_residual:.2f}px, n={self.n_matches})")
