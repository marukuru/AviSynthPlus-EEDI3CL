#!/usr/bin/env python3
"""Resolve all plugin symbols immediately: unresolved template regressions fail here."""
import ctypes
import os
from pathlib import Path
import sys
library = ctypes.CDLL(str(Path(sys.argv[1]).resolve()), mode=os.RTLD_NOW | os.RTLD_LOCAL)
assert library.avisynth_c_plugin_init
print('EEDI3CL loads with immediate symbol resolution')
