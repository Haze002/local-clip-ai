from pathlib import Path

import PySide6
from PyInstaller.utils.hooks import collect_all


repository_root = Path(SPEC).resolve().parent.parent
source_root = repository_root / "src"
portable_tools_root = repository_root / ".local-data" / "tools"
datas = [
    (
        str(source_root / "local_clip_ai" / "app" / "qml" / "Main.qml"),
        "local_clip_ai/app/qml",
    ),
    (str(repository_root / "README.md"), "."),
    (str(repository_root / "docs" / "WINDOWS_BETA.md"), "docs"),
    (
        str(portable_tools_root / "ffmpeg" / "bin"),
        "bundled_tools/ffmpeg/bin",
    ),
    (
        str(portable_tools_root / "ffmpeg" / "presets"),
        "bundled_tools/ffmpeg/presets",
    ),
    (
        str(portable_tools_root / "ffmpeg" / "LICENSE.txt"),
        "bundled_tools/ffmpeg",
    ),
    (
        str(portable_tools_root / "ffmpeg" / "install.json"),
        "bundled_tools/ffmpeg",
    ),
    (
        str(portable_tools_root / "yt-dlp" / "yt-dlp.exe"),
        "bundled_tools/yt-dlp",
    ),
    (
        str(portable_tools_root / "yt-dlp" / "install.json"),
        "bundled_tools/yt-dlp",
    ),
]
binaries = []
pyside6_root = Path(PySide6.__file__).resolve().parent
for multimedia_plugin in (pyside6_root / "plugins" / "multimedia").glob("*.dll"):
    binaries.append((str(multimedia_plugin), "PySide6/plugins/multimedia"))
for runtime_pattern in ("av*.dll", "sw*.dll"):
    for multimedia_runtime in pyside6_root.glob(runtime_pattern):
        binaries.append((str(multimedia_runtime), "PySide6"))
hidden_imports = [
    "keyring.backends.Windows",
    "local_clip_ai.cli",
    "local_clip_ai.app.media_smoke",
    "nvidia.cublas",
    "nvidia.cuda_nvrtc",
    "nvidia.cudnn",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
]

for package_name in (
    "ctranslate2",
    "fastembed",
    "faster_whisper",
    "keyring",
    "nvidia.cublas",
    "nvidia.cuda_nvrtc",
    "nvidia.cudnn",
    "onnxruntime",
    "tokenizers",
):
    package_datas, package_binaries, package_hidden_imports = collect_all(package_name)
    datas += package_datas
    binaries += package_binaries
    hidden_imports += package_hidden_imports

analysis = Analysis(
    [str(repository_root / "packaging" / "windows_entry.py")],
    pathex=[str(source_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "pandas",
        "scipy",
        "tkinter",
        "torch",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="LocalClipAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LocalClipAI",
)
