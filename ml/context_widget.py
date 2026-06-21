#!/usr/bin/env python3
"""Middle-column read-only data panel for the labeling tool.

Shows the auto-populated context, the live ML model predictions, and the AI
pre-label (with a manual-vs-AI comparison for validation). This is display only
— the editable form lives in LabelsWidget.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QTextEdit, QLabel, QPushButton,
)
from PySide6.QtCore import Signal

from .review_tab import to_bool


class ContextPanel(QWidget):
    """Read-only column: context, ML predictions, AI pre-label, classified mode."""

    ai_requested = Signal()  # user clicked "AI Suggest" for the current frame

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        context_group = QGroupBox("Auto-Populated Context (from APIs/sensors)")
        ctx_layout = QVBoxLayout(context_group)
        self.context_text = QTextEdit()
        self.context_text.setReadOnly(True)
        self.context_text.setStyleSheet("background: #2a2a2a; font-family: monospace;")
        ctx_layout.addWidget(self.context_text)
        layout.addWidget(context_group, 3)

        model_group = QGroupBox("🤖 ML Model Predictions")
        model_group.setStyleSheet("QGroupBox { font-weight: bold; color: #8b5cf6; }")
        model_layout = QVBoxLayout(model_group)
        self.model_text = QTextEdit()
        self.model_text.setReadOnly(True)
        self.model_text.setStyleSheet("background: #1e1b2e; font-family: monospace; border: 2px solid #8b5cf6;")
        model_layout.addWidget(self.model_text)
        layout.addWidget(model_group, 4)

        ai_group = QGroupBox("🌐 AI Pre-Label (OpenRouter)")
        ai_group.setStyleSheet("QGroupBox { font-weight: bold; color: #0EA5E9; }")
        ai_layout = QVBoxLayout(ai_group)
        self.ai_text = QTextEdit()
        self.ai_text.setReadOnly(True)
        self.ai_text.setStyleSheet("background: #0c1f2e; font-family: monospace; border: 2px solid #0EA5E9;")
        ai_layout.addWidget(self.ai_text)
        self.ai_button = QPushButton("🌐 AI Suggest (this frame)")
        self.ai_button.setStyleSheet("background: #0EA5E9; color: white; font-weight: bold; padding: 6px;")
        self.ai_button.clicked.connect(self.ai_requested)
        ai_layout.addWidget(self.ai_button)
        layout.addWidget(ai_group, 3)

        mode_group = QGroupBox("Classified Mode")
        mode_layout = QVBoxLayout(mode_group)
        self.mode_label = QLabel("")
        self.mode_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #f59e0b;")
        mode_layout.addWidget(self.mode_label)
        layout.addWidget(mode_group)

    def set_model_text(self, text: str):
        self.model_text.setText(text)

    def set_ai_busy(self, busy: bool):
        self.ai_button.setEnabled(not busy)
        self.ai_button.setText("⏳ Running AI…" if busy else "🌐 AI Suggest (this frame)")
        if busy:
            self.ai_text.setText("⏳ Calling OpenRouter…")

    def populate(self, cal: dict):
        """Refresh context, AI pre-label, and mode from calibration data."""
        self.context_text.setText("\n".join(self._context_lines(cal)))
        self.ai_text.setText(self._ai_text(cal))
        self.mode_label.setText(self._classify_mode(cal))

    # ── builders ──────────────────────────────────────────────────────────────

    def _context_lines(self, cal: dict) -> list:
        lines = []

        tc = cal.get('time_context', {})
        lines.append(f"Time: {tc.get('period', '?')} ({tc.get('detailed_period', '?')})")
        lines.append(f"  Daylight: {tc.get('is_daylight', '?')}, Astro Night: {tc.get('is_astronomical_night', '?')}")

        mc = cal.get('moon_context', {})
        if mc.get('available'):
            lines.append(f"Moon: {mc.get('phase_name', '?')} ({mc.get('illumination_pct', 0):.0f}%)")
            lines.append(f"  Moon up: {mc.get('moon_is_up', '?')}, Bright: {mc.get('is_bright_moon', '?')}")

        rs = cal.get('roof_state', {})
        if rs.get('available'):
            roof_str = "OPEN" if to_bool(rs.get('roof_open')) else "CLOSED"
            lines.append(f"Roof: {roof_str} (from {rs.get('source', '?')})")
        else:
            lines.append(f"Roof: Unknown ({rs.get('reason', 'no data')})")

        wc = cal.get('weather_context', {})
        if wc.get('available'):
            lines.append(f"Weather: {wc.get('condition', '?')} - {wc.get('description', '?')}")
            lines.append(f"  Clouds: {wc.get('cloud_coverage_pct', '?')}%, Humidity: {wc.get('humidity_pct', '?')}%")
            lines.append(f"  Clear: {wc.get('is_clear', '?')}")

        se = cal.get('seeing_estimate', {})
        if se.get('available'):
            lines.append(f"Seeing: {se.get('quality', '?')} (score: {se.get('overall_score', 0):.2f})")

        ml = cal.get('ml_prediction')
        if ml:
            ml_roof = "OPEN" if to_bool(ml.get('roof_open')) else "CLOSED"
            lines.append(f"ML Prediction: {ml_roof} ({ml.get('confidence', 0) * 100:.1f}% conf) [{ml.get('model_version', '?')}]")

        st = cal.get('stretch', {})
        lines.append(f"Image: median_lum={st.get('median_lum', 0):.4f}, dark_scene={st.get('is_dark_scene', '?')}")

        ca = cal.get('corner_analysis', {})
        lines.append(f"Corner ratio: {ca.get('corner_to_center_ratio', 0):.4f}")
        return lines

    def _ai_text(self, cal: dict) -> str:
        ai = cal.get('ai_suggestion')
        if not ai:
            return "No AI pre-label yet.\n\nRun:\n  python ml/ai_prelabel.py"

        hints = ai.get('hints_used')
        mode = "image-only" if hints is False else ("hinted" if hints else "legacy/hinted")
        roof = "OPEN" if ai.get('roof_open') else "CLOSED"
        sky = ai.get('sky_condition') or "—"

        lines = [
            f"━━━ AI ({mode}) ━━━",
            f"Roof:   {roof} ({ai.get('roof_confidence', 0) or 0:.0%})",
            f"Sky:    {sky} ({ai.get('sky_confidence', 0) or 0:.0%})",
            f"Clouds: {'Yes' if ai.get('clouds_visible') else 'No'}",
            f"Model:  {ai.get('model', '?')}",
        ]
        reasoning = ai.get('reasoning')
        if reasoning:
            lines.append(f'\n"{reasoning}"')

        labels = cal.get('labels', {})
        if labels.get('labeled_at'):
            lines.append("\nvs Manual label:")
            roof_match = bool(ai.get('roof_open')) == to_bool(labels.get('roof_open', False))
            lines.append(f"  Roof: {'✓' if roof_match else '✗ MISMATCH'}")
            lbl_sky = labels.get('sky_condition', '') or ''
            if ai.get('roof_open') and lbl_sky:
                sky_match = (ai.get('sky_condition') or '') == lbl_sky
                lines.append(f"  Sky:  {'✓' if sky_match else '✗'} (manual: {lbl_sky})")
        return "\n".join(lines)

    def _classify_mode(self, cal: dict) -> str:
        tc = cal.get('time_context', {})
        rs = cal.get('roof_state', {})
        ca = cal.get('corner_analysis', {})

        if tc.get('is_daylight'):
            time_period = 'day'
        elif tc.get('is_astronomical_night'):
            time_period = 'night'
        elif tc.get('period') == 'twilight':
            return 'twilight'
        else:
            hour = tc.get('hour', 12)
            time_period = 'night' if (hour >= 20 or hour < 6) else 'day'

        if rs.get('available') and rs.get('source') == 'nina_api':
            roof_open = to_bool(rs.get('roof_open', False))
        else:
            roof_open = ca.get('corner_to_center_ratio', 0.95) < 0.95

        return f"{time_period}_{'roof_open' if roof_open else 'roof_closed'}"
