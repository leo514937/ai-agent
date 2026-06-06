from . import dependencies_core as _dependencies_core
from .dependencies_core import *# noqa: F401,F403,F405
import sys as _sys

_sys.modules[__name__] = _dependencies_core
