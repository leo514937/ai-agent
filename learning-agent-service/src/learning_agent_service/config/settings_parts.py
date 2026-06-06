from . import settings_core as _settings_core
from .settings_core import *# noqa: F401,F403,F405
import sys as _sys

_sys.modules[__name__] = _settings_core
