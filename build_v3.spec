# -*- mode: python ; coding: utf-8 -*-
"""v3 build: drag-drop support, portrait page fixes, filename sanitization."""

a = Analysis(
    ['pdf_splitter/main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['PIL', 'PIL.Image', 'customtkinter'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'easyocr', 'torch', 'torchvision', 'torchaudio',
        'opencv_python_headless', 'cv2',
        'scipy', 'scipy.special', 'scipy.spatial', 'scipy.stats',
        'scipy.linalg', 'scipy.sparse', 'scipy.io',
        'scikit_image', 'skimage',
        'sympy',
        'numpy', 'numpy.core', 'numpy.lib', 'numpy.linalg',
        'networkx', 'imageio', 'tifffile',
        'lazy_loader', 'shapely', 'shapely.libs',
        'pyclipper', 'python_bidi',
        'jinja2', 'markupsafe',
        'mpmath', 'ninja', 'fsspec', 'filelock',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PDF拆分器_v3',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
