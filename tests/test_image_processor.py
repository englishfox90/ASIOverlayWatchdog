"""
Worker-integration tests for ui/controllers/image_processor.py.

The roof-safety confirmation FSM itself is unit-tested in test_ascom_safety.py
(RoofSafetyFSM). Here we assert the WIRING through the image-processing worker:
- ML enabled + safety enabled routes confirmed results through the FSM,
- the fail-safe still runs when ML is DISABLED but the safety file is enabled,
- a hard inference failure routes an UNSAFE verdict,
- a genuine write failure escalates via the worker's operator-visible channels.
"""
import pytest

# A QApplication is needed before constructing the QThread-derived worker.
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PIL import Image
from services.notifications import ERROR
from ui.controllers.image_processor import ImageProcessorWorker, ImageProcessingTask


@pytest.fixture(scope="module")
def _qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def worker(_qapp):
    return ImageProcessorWorker()


class _NotifierStub:
    """Captures NotificationEvents instead of delivering them."""

    def __init__(self):
        self.events = []

    def notify(self, event):
        self.events.append(event)


def _ascom(tmp_path, **over):
    cfg = {'enabled': True, 'file_path': str(tmp_path / 'roof.txt'),
           'min_confidence': 0.7, 'heartbeat_seconds': 0}
    cfg.update(over)
    return cfg


def _base_config(tmp_path, ml_models):
    return {
        'output_dir': str(tmp_path),
        'output_format': 'PNG',
        'resize_percent': 100,
        'auto_stretch': {'enabled': False},
        'overlays': [],
        'dev_mode': {'enabled': False},
        'ml_contribution': {'enabled': False},
        'meteor': {},
        'sharpening': {},
        'allsky_overlay': {},
        'weather': {},
        'ml_models': ml_models,
    }


def test_ml_disabled_but_ascom_enabled_writes_unsafe(worker, tmp_path):
    # Item 2: even with ML disabled, an enabled safety file must not freeze at a
    # stale OPEN — the fail-safe routes UNSAFE through the FSM.
    writes = []
    worker._safety_fsm._writer = lambda ml, cfg: (writes.append(dict(ml)), True)[1]
    worker._main_window = None

    cfg = _base_config(tmp_path, {
        'enabled': False,
        'ascom_safety_file': _ascom(tmp_path),
    })
    worker._process_task(ImageProcessingTask(
        Image.new('RGB', (32, 32), (40, 40, 40)), {'FILENAME': 'x.png'}, cfg))

    assert len(writes) == 1
    assert writes[0]['roof_status'] == 'N/A'  # UNSAFE baseline


def test_inference_exception_writes_unsafe(worker, monkeypatch, tmp_path):
    # A hard inference failure (model blind) must route an UNSAFE verdict.
    monkeypatch.setattr('ui.controllers.image_processor.get_ml_service',
                        lambda: (_ for _ in ()).throw(RuntimeError("blind")))
    writes = []
    worker._safety_fsm._writer = lambda ml, cfg: (writes.append(dict(ml)), True)[1]
    worker._main_window = None

    cfg = _base_config(tmp_path, {
        'enabled': True,
        'ascom_safety_file': _ascom(tmp_path),
    })
    worker._process_task(ImageProcessingTask(
        Image.new('RGB', (32, 32), (40, 40, 40)), {'FILENAME': 'x.png'}, cfg))

    assert len(writes) == 1
    assert writes[0]['roof_status'] == 'N/A'


def test_confident_open_via_worker_routes_through_fsm(worker, tmp_path, monkeypatch):
    # ML produces a confident Open: it must go through the FSM (which, per
    # Policy A, writes UNSAFE first and does NOT certify SAFE on one frame).
    writes = []
    worker._safety_fsm._writer = lambda ml, cfg: (writes.append(dict(ml)), True)[1]
    worker._main_window = None

    class _Svc:
        def is_available(self):
            return True

        def initialize(self):
            return True

        def get_last_results(self):
            return {'roof_status': 'Open', 'roof_confidence': 0.95}

    monkeypatch.setattr('ui.controllers.image_processor.get_ml_service', lambda: _Svc())
    monkeypatch.setattr('ui.controllers.image_processor.analyze_image_for_tokens',
                        lambda arr, config=None: {'ROOF_STATUS': 'Open'})

    cfg = _base_config(tmp_path, {
        'enabled': True,
        'ascom_safety_file': _ascom(tmp_path),
    })
    worker._process_task(ImageProcessingTask(
        Image.new('RGB', (32, 32), (40, 40, 40)), {'FILENAME': 'x.png'}, cfg))

    # First confident-Open frame writes the UNSAFE baseline, NOT SAFE/OPEN.
    assert len(writes) == 1
    assert writes[0]['roof_status'] != 'Open'
    assert worker._safety_fsm._confirmed_safe is False


def test_genuine_write_failure_escalates_via_worker(worker, monkeypatch, tmp_path):
    captured = []
    notifier = _NotifierStub()
    monkeypatch.setattr('services.posthog_service.capture_error',
                        lambda exc, context=None: captured.append(context))
    worker._main_window = type('MW', (), {'config': {}, 'notifier': notifier})()
    worker._safety_fsm._writer = lambda ml, cfg: False  # genuine failure

    worker._safety_fsm.update({'roof_status': 'Closed', 'roof_confidence': 0.9},
                              _ascom(tmp_path))

    assert len(notifier.events) == 1
    assert notifier.events[0].type == ERROR
    assert 'stale' in notifier.events[0].body
    assert captured == ['ascom_safety_write']


# ---------------------------------------------------------------------------
# Deferred frame construction (reprocess rebuilds on the worker thread)
# ---------------------------------------------------------------------------

def test_frame_factory_runs_on_worker_and_result_is_processed(worker, tmp_path):
    worker._main_window = None
    calls = []

    def factory():
        calls.append(1)
        return Image.new('RGB', (16, 12), (40, 50, 60)), {'FILENAME': 'rebuilt.png'}

    task = ImageProcessingTask(None, {'FILENAME': 'stale.png'}, _base_config(tmp_path, {'enabled': False}),
                               frame_factory=factory)
    saved = []
    worker.processing_complete.connect(lambda p, o, m, path, d: saved.append((m, path)))

    worker._process_task(task)

    assert calls == [1]
    assert task.frame_factory is None  # consumed, not retained
    assert saved and saved[0][0]['FILENAME'] == 'rebuilt.png'
    assert saved[0][1].endswith('rebuilt.png')


def test_frame_factory_returning_nothing_skips_the_frame(worker, tmp_path):
    worker._main_window = None
    task = ImageProcessingTask(None, {}, _base_config(tmp_path, {'enabled': False}),
                               frame_factory=lambda: (None, None))
    errors, done = [], []
    worker.error_occurred.connect(errors.append)
    worker.processing_complete.connect(lambda *a: done.append(a))

    worker._process_task(task)

    assert errors == [] and done == []


def test_task_takes_ownership_of_the_image_without_copying():
    img = Image.new('RGB', (4, 4))
    assert ImageProcessingTask(img, {}, {}).img is img


# ---------------------------------------------------------------------------
# Preview downscale — the LANCZOS resize belongs on the worker, not the GUI
# thread. Only the GUI preview slot shrinks; every full-res consumer keeps its
# pixels.
# ---------------------------------------------------------------------------

def test_gui_preview_is_capped_while_output_and_dispatch_stay_full_res(worker, tmp_path):
    from services.preview_scaling import PREVIEW_MAX_PX

    worker._main_window = None
    big = Image.new('RGB', (2628, 2628), (30, 40, 50))
    results = []
    worker.processing_complete.connect(
        lambda preview, out, meta, path, dispatch: results.append((preview, out, dispatch)))

    worker._process_task(ImageProcessingTask(
        big, {'FILENAME': 'big.png'}, _base_config(tmp_path, {'enabled': False})))

    assert results, "processing_complete did not fire"
    preview, output, dispatch = results[0]
    assert max(preview.size) == PREVIEW_MAX_PX
    assert output.size == (2628, 2628), "output image must keep full resolution"
    assert dispatch.size == (2628, 2628), "web/Library dispatch must keep full resolution"


def test_timelapse_and_detection_frames_are_not_downscaled_by_the_preview_cap(worker, tmp_path):
    worker._main_window = None
    big = Image.new('RGB', (2628, 2628), (30, 40, 50))
    cfg = _base_config(tmp_path, {'enabled': False})
    cfg['meteor'] = {'enabled': True, 'detection_long_side': 1280}

    timelapse, detection = [], []
    worker.timelapse_ready.connect(lambda clean, overlaid: timelapse.append((clean, overlaid)))
    worker.detection_frame_ready.connect(lambda det, full: detection.append((det, full)))

    worker._process_task(ImageProcessingTask(big, {'FILENAME': 'big.png'}, cfg))

    assert timelapse and detection
    clean, overlaid = timelapse[0]
    assert clean.size == (2628, 2628) and overlaid.size == (2628, 2628)
    det_frame, full_clean = detection[0]
    assert max(det_frame.size) == 1280  # its own detection scale, untouched
    assert full_clean.size == (2628, 2628)


def test_saved_file_keeps_full_resolution(worker, tmp_path):
    worker._main_window = None
    big = Image.new('RGB', (2628, 2628), (30, 40, 50))
    paths = []
    worker.processing_complete.connect(lambda p, o, m, path, d: paths.append(path))

    worker._process_task(ImageProcessingTask(
        big, {'FILENAME': 'big.png'}, _base_config(tmp_path, {'enabled': False})))

    assert Image.open(paths[0]).size == (2628, 2628)


def test_small_frame_reaches_the_preview_untouched(worker, tmp_path):
    worker._main_window = None
    small = Image.new('RGB', (640, 480), (30, 40, 50))
    results = []
    worker.processing_complete.connect(lambda p, o, m, path, d: results.append((p, o)))

    worker._process_task(ImageProcessingTask(
        small, {'FILENAME': 'small.png'}, _base_config(tmp_path, {'enabled': False})))

    preview, output = results[0]
    assert preview.size == (640, 480) and output.size == (640, 480)


def test_worker_reuses_one_overlay_image_cache_across_frames(worker, tmp_path):
    """The worker must hand the SAME cache dict to add_overlays every frame —
    a per-frame dict would re-decode the user's logo on every capture."""
    seen = []
    import ui.controllers.image_processor as ip

    def _spy(img, overlays, metadata, image_cache=None, weather_service=None):
        seen.append(image_cache)
        return img

    original = ip.add_overlays
    ip.add_overlays = _spy
    try:
        worker._main_window = None
        cfg = _base_config(tmp_path, {'enabled': False})
        for _ in range(2):
            worker._process_task(ImageProcessingTask(
                Image.new('RGB', (32, 32)), {'FILENAME': 'x.png'}, cfg))
    finally:
        ip.add_overlays = original

    assert len(seen) == 2
    assert seen[0] is not None and seen[0] is seen[1]
    assert seen[0] is worker._overlay_image_cache
