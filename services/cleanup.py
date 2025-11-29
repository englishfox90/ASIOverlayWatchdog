"""
Cleanup module for managing watch directory size
"""
import os
import shutil
from pathlib import Path


def get_directory_size(directory):
    """
    Calculate total size of directory in bytes.
    """
    total_size = 0
    try:
        for dirpath, dirnames, filenames in os.walk(directory):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                if os.path.exists(filepath):
                    total_size += os.path.getsize(filepath)
    except Exception as e:
        print(f"Error calculating directory size: {e}")
    
    return total_size


def get_all_files_with_mtime(directory):
    """
    Get all files in directory with their modification times.
    Returns list of (filepath, mtime) tuples.
    """
    files = []
    try:
        for dirpath, dirnames, filenames in os.walk(directory):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                if os.path.exists(filepath):
                    mtime = os.path.getmtime(filepath)
                    size = os.path.getsize(filepath)
                    files.append((filepath, mtime, size))
    except Exception as e:
        print(f"Error getting files: {e}")
    
    return files


def get_session_folders(directory):
    """
    Get immediate subdirectories (session folders) with their modification times.
    Returns list of (folder_path, mtime, size) tuples.
    """
    folders = []
    try:
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            if os.path.isdir(item_path):
                mtime = os.path.getmtime(item_path)
                size = get_directory_size(item_path)
                folders.append((item_path, mtime, size))
    except Exception as e:
        print(f"Error getting session folders: {e}")
    
    return folders


def remove_empty_directories(directory):
    """
    Remove empty subdirectories, leaving only directories with files.
    Returns number of directories removed.
    """
    deleted_count = 0
    try:
        for dirpath, dirnames, filenames in os.walk(directory, topdown=False):
            # Skip the root directory
            if dirpath == directory:
                continue
            
            # Check if directory is empty
            if not os.listdir(dirpath):
                try:
                    os.rmdir(dirpath)
                    deleted_count += 1
                    print(f"Removed empty directory: {dirpath}")
                except Exception as e:
                    print(f"Error removing empty directory {dirpath}: {e}")
    except Exception as e:
        print(f"Error scanning for empty directories: {e}")
    
    return deleted_count


def delete_oldest_files(directory, max_size_bytes):
    """
    Delete oldest files until directory is under max_size_bytes.
    Does NOT remove folders to avoid interfering with active captures.
    Returns number of files deleted.
    """
    deleted_count = 0
    current_size = get_directory_size(directory)
    
    if current_size <= max_size_bytes:
        return 0
    
    # Get all files sorted by modification time (oldest first)
    files = get_all_files_with_mtime(directory)
    files.sort(key=lambda x: x[1])  # Sort by mtime
    
    for filepath, mtime, size in files:
        if current_size <= max_size_bytes:
            break
        
        try:
            os.remove(filepath)
            current_size -= size
            deleted_count += 1
            print(f"Deleted file: {filepath}")
        except Exception as e:
            print(f"Error deleting {filepath}: {e}")
    
    return deleted_count


def delete_oldest_sessions(directory, max_size_bytes):
    """
    Delete files in oldest session folders until directory is under max_size_bytes.
    Keeps folder structure intact but deletes files within old sessions.
    Always keeps the latest (most recent) session folder untouched.
    Returns number of files deleted.
    """
    deleted_count = 0
    current_size = get_directory_size(directory)
    
    # Get session folders sorted by modification time (oldest first)
    folders = get_session_folders(directory)
    folders.sort(key=lambda x: x[1])  # Sort by mtime
    
    if len(folders) == 0:
        return 0
    
    # Keep at least the latest folder untouched
    if len(folders) == 1:
        return 0
    
    # Process all but the latest folder
    folders_to_consider = folders[:-1]  # Exclude the newest folder
    
    for folder_path, mtime, folder_size in folders_to_consider:
        if current_size <= max_size_bytes:
            break
        
        # Delete files within this session folder instead of the entire folder
        try:
            for root, dirs, files in os.walk(folder_path):
                for filename in files:
                    if current_size <= max_size_bytes:
                        break
                    
                    filepath = os.path.join(root, filename)
                    try:
                        file_size = os.path.getsize(filepath)
                        os.remove(filepath)
                        current_size -= file_size
                        deleted_count += 1
                        print(f"Deleted file in old session: {filepath}")
                    except Exception as e:
                        print(f"Error deleting {filepath}: {e}")
        except Exception as e:
            print(f"Error processing folder {folder_path}: {e}")
    
    return deleted_count


def run_cleanup(config):
    """
    Run cleanup based on configuration.
    
    Returns: (success: bool, message: str)
    """
    try:
        if not config.get('cleanup_enabled', False):
            return True, "Cleanup not enabled"
        
        watch_dir = config.get('watch_directory', '')
        if not watch_dir or not os.path.exists(watch_dir):
            return False, "Watch directory not valid"
        
        max_size_gb = config.get('cleanup_max_size_gb', 50)
        max_size_bytes = max_size_gb * 1024 * 1024 * 1024
        
        strategy = config.get('cleanup_strategy', 'Delete oldest files in watch directory')
        
        current_size = get_directory_size(watch_dir)
        current_size_gb = current_size / (1024 * 1024 * 1024)
        
        if current_size <= max_size_bytes:
            return True, f"Current size ({current_size_gb:.2f} GB) is under limit ({max_size_gb} GB)"
        
        print(f"Running cleanup: current size {current_size_gb:.2f} GB exceeds {max_size_gb} GB")
        
        if strategy == "Delete oldest files in watch directory":
            deleted = delete_oldest_files(watch_dir, max_size_bytes)
            return True, f"Deleted {deleted} old files (folders preserved)"
        
        elif strategy == "Delete oldest session folders":
            deleted = delete_oldest_sessions(watch_dir, max_size_bytes)
            return True, f"Deleted {deleted} files from old sessions (kept latest session intact)"
        
        else:
            return False, f"Unknown cleanup strategy: {strategy}"
    
    except Exception as e:
        return False, f"Cleanup error: {e}"
