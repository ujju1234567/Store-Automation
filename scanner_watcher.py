"""
scanner_watcher.py - Ricoh fi-8170 Scanner Inbox Hot Folder Watcher
Monitors a local or network inbox folder (e.g. C:\\ScanInbox) for newly scanned 
PDF/TIFF/PNG files from the Ricoh scanner and queues them automatically into the app.
"""

import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class ScannerHotFolderHandler(FileSystemEventHandler):
    def __init__(self, callback_func):
        super().__init__()
        self.callback_func = callback_func

    def on_created(self, event):
        if event.is_directory:
            return
        ext = os.path.splitext(event.src_path)[1].lower()
        if ext in [".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"]:
            # Give scanner time to finish writing file
            time.sleep(1.0)
            self.callback_func(event.src_path)


def start_scanner_folder_watcher(folder_path: str, callback_func):
    """Starts watching the specified scanner folder in the background."""
    if not os.path.exists(folder_path):
        os.makedirs(folder_path, exist_ok=True)
        
    event_handler = ScannerHotFolderHandler(callback_func)
    observer = Observer()
    observer.schedule(event_handler, folder_path, recursive=False)
    observer.start()
    return observer
