"""
Albion Kill History
Nécessite : Python 3.10+
"""
import sys
import os

if sys.platform == "win32":
    sys.path.insert(0, os.path.dirname(__file__))

from gui.app import AlbionKillboardApp

if __name__ == "__main__":
    app = AlbionKillboardApp()
    app.mainloop()
