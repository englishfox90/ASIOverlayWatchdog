"""
Image library file storage.

Owns the on-disk layout of the library: a root directory under the app-data
folder, one subfolder per local capture date, and JPEG files named by
timestamp. The SQLite index (``index.py``) is the canonical record; filenames
exist for human inspection and collision-free writes only.
"""
import os
import uuid

from ..app_config import get_app_data_dir

LIBRARY_SUBFOLDER = "Library"
DB_FILENAME = "library.db"


def get_library_root():
    """Canonical library directory: ``%LOCALAPPDATA%\\PFRSentinel\\Library``."""
    root = os.path.join(get_app_data_dir(), LIBRARY_SUBFOLDER)
    os.makedirs(root, exist_ok=True)
    return root


class LibraryStore:
    """Reads and writes library JPEG files under a date-partitioned root.

    Paths are stored in the index *relative* to ``root`` so the library folder
    can be moved without rewriting the database.
    """

    def __init__(self, root=None):
        self.root = root or get_library_root()
        os.makedirs(self.root, exist_ok=True)

    @property
    def db_path(self):
        return os.path.join(self.root, DB_FILENAME)

    def abs_path(self, rel_path):
        """Absolute path for an index-stored relative path."""
        return os.path.join(self.root, rel_path)

    def write(self, jpeg_bytes, captured_at):
        """Write ``jpeg_bytes`` into the dated folder for ``captured_at``.

        Args:
            jpeg_bytes: Encoded JPEG payload.
            captured_at: ``datetime`` in the PC's local time.

        Returns:
            Tuple ``(rel_path, size_bytes)``.
        """
        date_folder = captured_at.strftime("%Y-%m-%d")
        folder_abs = os.path.join(self.root, date_folder)
        os.makedirs(folder_abs, exist_ok=True)

        filename = f"{captured_at.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
        rel_path = os.path.join(date_folder, filename)
        abs_path = os.path.join(self.root, rel_path)

        with open(abs_path, "wb") as f:
            f.write(jpeg_bytes)

        return rel_path, len(jpeg_bytes)

    def delete(self, rel_path):
        """Delete a stored file and prune its date folder if it becomes empty.

        Missing files are ignored — the index is the source of truth and a gone
        file just means the row is stale.
        """
        abs_path = self.abs_path(rel_path)
        try:
            os.remove(abs_path)
        except FileNotFoundError:
            pass

        # Best-effort: remove the date folder once it holds no more images.
        folder = os.path.dirname(abs_path)
        if folder and folder != self.root:
            try:
                if not os.listdir(folder):
                    os.rmdir(folder)
            except OSError:
                pass

    def exists(self, rel_path):
        return os.path.exists(self.abs_path(rel_path))
