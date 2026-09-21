import os
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
os.environ['HF_HUB_OFFLINE'] = '1'
from PyInstaller.utils.hooks import collect_all, copy_metadata

datas, binaries, hiddenimports = [('runtime/llama', 'runtime/llama'), ('screen_translator/assets', 'screen_translator/assets'), ('THIRD_PARTY.md', '.')], [], []
for package in ('paddleocr', 'paddlex', 'paddle'):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
for package in ('nvidia.cuda_runtime', 'nvidia.cublas', 'nvidia.cudnn', 'nvidia.cufft', 'nvidia.curand', 'nvidia.cusolver', 'nvidia.cusparse', 'nvidia.nvjitlink'):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
for package in (
    'paddleocr',
    'paddlex',
    'paddlepaddle-gpu',
    'PySide6',
    'shiboken6',
    'opencv-contrib-python',
    'requests',
    # PaddleX checks this optional PDF reader through distribution metadata
    # while constructing its image batch sampler, even for screenshot input.
    'pypdfium2',
    # Required by PaddleX OCR post-processing and recognition predictors.
    'pyclipper',
    'python-bidi',
):
    datas += copy_metadata(package, recursive=True)
# copy_metadata(..., recursive=True) above keeps runtime dependency checks
# deterministic without leaking every package installed in the build venv.
a = Analysis(['run.py'], pathex=['.'], binaries=binaries, datas=datas, hiddenimports=hiddenimports, excludes=['tkinter', 'matplotlib', 'IPython', 'pytest'])
# Qt on Windows 11 uses the OS ICU API. A Poppler ICU found on PATH has
# version-suffixed exports and must never shadow Windows' icuuc.dll.
a.binaries = [entry for entry in a.binaries if os.path.basename(entry[0]).lower() not in ('icuuc.dll', 'icudt78.dll')]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ScreenTranslator', icon='screen_translator/assets/app-icon.ico', debug=False, strip=False, upx=False, console=os.environ.get('ST_DEBUG_CONSOLE') == '1')
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ScreenTranslator')
