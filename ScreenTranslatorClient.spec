"""Client edition: capture and render here, run the models on another device.

Everything that makes the full package multi-gigabyte — PaddleOCR, PaddlePaddle,
the CUDA runtime libraries and the llama.cpp server — is deliberately absent.
What stays is what the capturing device genuinely needs: Qt for the overlay,
OpenCV and NumPy for compositing and inpainting, and requests for the tailnet
transport.  ``screen_translator.capabilities`` reports the absence so the
application says so instead of failing part-way through a capture.
"""

import os

from PyInstaller.utils.hooks import copy_metadata

datas = [('screen_translator/assets', 'screen_translator/assets'), ('THIRD_PARTY.md', '.')]
binaries = []
hiddenimports = []
for package in ('PySide6', 'shiboken6', 'opencv-contrib-python', 'requests', 'numpy'):
    datas += copy_metadata(package, recursive=True)

# Excluding these is the whole point of this edition. If an import of one of
# them ever becomes unconditional, this build fails loudly at analysis time
# rather than shipping a client that silently regained a gigabyte.
EXCLUDED_RUNTIMES = [
    'paddle',
    'paddleocr',
    'paddlex',
    'paddle2onnx',
    'nvidia',
    'scipy',
    'pandas',
    'tkinter',
    'matplotlib',
    'IPython',
    'pytest',
]

a = Analysis(
    ['run.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=EXCLUDED_RUNTIMES,
)
# Qt on Windows 11 uses the OS ICU API; a Poppler ICU found on PATH has
# version-suffixed exports and must never shadow Windows' icuuc.dll.
a.binaries = [
    entry for entry in a.binaries
    if os.path.basename(entry[0]).lower() not in ('icuuc.dll', 'icudt78.dll')
]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ScreenTranslator',
    icon='screen_translator/assets/app-icon.ico',
    debug=False,
    strip=False,
    upx=False,
    console=os.environ.get('ST_DEBUG_CONSOLE') == '1',
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ScreenTranslatorClient')
