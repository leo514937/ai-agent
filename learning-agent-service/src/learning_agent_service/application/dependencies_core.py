from . import dependencies_impl as _dependencies_impl
from .dependencies_impl import *# noqa: F401,F403,F405
import sys as _sys

_sys.modules[__name__] = _dependencies_impl
