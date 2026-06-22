#!/usr/bin/env python3
"""Background QThread that runs AI pre-labelling without freezing the GUI.

Used by both the labeling tab (one frame) and the review tab (the filtered set).
Writes an `ai_suggestion` block into each calibration JSON; never touches human
labels. Emits progress so the caller can drive a bar and re-enable its button.
"""
import json
from datetime import datetime

from PySide6.QtCore import QThread, Signal

from services.logger import app_logger
from ml.ai_labeler import label_lum_frame, build_context_from_cal


class AiLabelWorker(QThread):
    """Runs label_lum_frame over a list of jobs on a worker thread.

    Each job is a dict: {'cal_path': str, 'lum_path': str, 'timestamp': str}.
    """

    progress = Signal(int, int, str)   # done_count, total, message
    completed = Signal(int, int, str)  # labelled, failed, last_error ("" if none)

    def __init__(self, jobs: list, use_hints: bool = False, model: str | None = None, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.use_hints = use_hints
        self.model = model
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        total = len(self.jobs)
        labelled = failed = 0
        last_error = ""

        for i, job in enumerate(self.jobs):
            if self._cancel:
                break
            ts = job.get("timestamp", "?")
            try:
                with open(job["cal_path"], "r") as f:
                    cal = json.load(f)

                context = build_context_from_cal(cal) if self.use_hints else None
                result = label_lum_frame(job["lum_path"], context, model=self.model)
                result["suggested_at"] = datetime.now().isoformat()
                result["hints_used"] = bool(self.use_hints)
                cal["ai_suggestion"] = result

                with open(job["cal_path"], "w") as f:
                    json.dump(cal, f, indent=2)

                labelled += 1
                roof = "OPEN" if result["roof_open"] else "CLOSED"
                self.progress.emit(i + 1, total, f"{ts}: roof {roof}")
            except Exception as e:
                failed += 1
                last_error = str(e)
                app_logger.warning(f"AI label failed for {ts}: {e}")
                self.progress.emit(i + 1, total, f"{ts}: ERROR {e}")

        self.completed.emit(labelled, failed, last_error)
