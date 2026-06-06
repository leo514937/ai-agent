from . import settings_impl as _settings_impl
from .settings_impl import *# noqa: F401,F403,F405
import sys as _sys

_sys.modules[__name__] = _settings_impl
