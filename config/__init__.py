import os
import sys

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in [_ROOT_DIR, os.path.join(_ROOT_DIR, "core"), os.path.join(_ROOT_DIR, "services"), os.path.join(_ROOT_DIR, "config")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from .config import *
