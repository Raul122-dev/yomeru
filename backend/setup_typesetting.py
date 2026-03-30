#!/usr/bin/env python3
"""
yomeru — typesetting pipeline setup
Installs and verifies all Stage 2-4 dependencies.

Run once before using the typesetting pipeline:
    python backend/setup_typesetting.py

Optional flags:
    --cpu          force CPU-only (default: auto-detect CUDA/MPS)
    --skip-ocr     skip manga-ocr (large model, only needed for Japanese)
    --check-only   just check what's installed, don't install anything
"""
import argparse
import importlib
import subprocess
import sys
from pathlib import Path

# ── helpers ───────────────────────────────────────────────────────────────────
def run(cmd: str, check: bool = True) -> int:
    print(f"\n$ {cmd}")
    result = subprocess.run(cmd, shell=True)
    if check and result.returncode != 0:
        print(f"  ✗ command failed (exit {result.returncode})")
    return result.returncode

def pip(*packages: str) -> None:
    run(f"{sys.executable} -m pip install {' '.join(packages)} --break-system-packages -q")

def check_import(module: str, friendly_name: str = "") -> bool:
    name = friendly_name or module
    try:
        importlib.import_module(module)
        print(f"  ✓ {name}")
        return True
    except ImportError:
        print(f"  ✗ {name} — not installed")
        return False

def detect_device() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            mem  = torch.cuda.get_device_properties(0).total_memory // (1024**3)
            print(f"  ✓ CUDA GPU: {name} ({mem}GB VRAM)")
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            print("  ✓ Apple MPS")
            return "mps"
    except ImportError:
        pass
    print("  ⚠ CPU only (no CUDA/MPS found)")
    return "cpu"

def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print('─' * 60)

# ── steps ─────────────────────────────────────────────────────────────────────


def _needs_blackwell_torch() -> bool:
    """Detect if GPU needs PyTorch nightly (sm_120 Blackwell / RTX 50xx series)."""
    try:
        import torch
        if not torch.cuda.is_available():
            return False
        cap = torch.cuda.get_device_capability(0)
        return cap[0] >= 12   # sm_120 = compute capability 12.0
    except Exception:
        return False

def install_torch(device: str) -> None:
    section("1 / PyTorch")
    try:
        import torch
        print(f"  ✓ torch {torch.__version__} already installed")
        return
    except ImportError:
        pass

    if device == "cuda":
        # Check for Blackwell (sm_120, RTX 50xx) — needs nightly + CUDA 12.8
        blackwell = _needs_blackwell_torch()
        if blackwell:
            print("  RTX 50xx detected (sm_120) — installing PyTorch nightly with CUDA 12.8…")
            pip("--pre", "torch", "torchvision",
                "--index-url https://download.pytorch.org/whl/nightly/cu128")
        else:
            print("  Installing PyTorch with CUDA 12.1 support…")
            pip("torch", "torchvision",
                "--index-url https://download.pytorch.org/whl/cu121")
    elif device == "mps":
        print("  Installing PyTorch for Apple Silicon…")
        pip("torch", "torchvision")
    else:
        print("  Installing PyTorch CPU-only…")
        pip("torch", "torchvision",
            "--index-url https://download.pytorch.org/whl/cpu")


def install_iopaint() -> None:
    section("2 / IOPaint (LaMa inpainting)")
    # numpy >=2 required by opencv-python-headless and iopaint
    try:
        import numpy as np
        if tuple(int(x) for x in np.__version__.split(".")[:2]) < (2, 0):
            print("  Upgrading numpy to >=2.0 (required by opencv + iopaint)…")
            pip("numpy>=2.0")
    except ImportError:
        pip("numpy>=2.0")

    try:
        import iopaint  # noqa
        print("  ✓ iopaint already installed")
    except ImportError:
        pip("iopaint")

    # verify LaMa model is accessible (downloads on first use)
    print("  Pre-downloading LaMa model weights…")
    try:
        from iopaint.model_manager import ModelManager  # noqa
        print("  ✓ LaMa model manager accessible")
        print("  ℹ  Model weights download automatically on first inpaint call")
    except Exception as e:
        print(f"  ⚠ iopaint model manager check failed: {e}")
        print("  ℹ  This is usually fine — weights download on first use")


def install_ocr(skip_manga_ocr: bool) -> None:
    section("3 / OCR engines")

    # easyocr — multilingual
    try:
        import easyocr  # noqa
        print("  ✓ easyocr already installed")
    except ImportError:
        pip("easyocr")

    # manga-ocr — Japanese-specific
    if skip_manga_ocr:
        print("  ⏭ manga-ocr skipped (--skip-ocr)")
        return

    try:
        import manga_ocr  # noqa
        print("  ✓ manga-ocr already installed")
    except ImportError:
        pip("manga-ocr")


def install_detector() -> None:
    section("4 / Text detectors")

    # transformers + timm — needed for ogkalu/comic-text-and-bubble-detector
    packages_needed = []
    for pkg in ["transformers", "timm", "accelerate"]:
        try:
            importlib.import_module(pkg)
            print(f"  ✓ {pkg} already installed")
        except ImportError:
            packages_needed.append(pkg)

    if packages_needed:
        pip(*packages_needed)

    # pre-download ogkalu/comic-text-and-bubble-detector
    print("\n  Pre-downloading ogkalu/comic-text-and-bubble-detector…")
    print("  (this is a ~300MB RT-DETR model, first time only)")
    try:
        from transformers import AutoImageProcessor, AutoModelForObjectDetection  # noqa
        _ = AutoImageProcessor.from_pretrained("ogkalu/comic-text-and-bubble-detector")
        _ = AutoModelForObjectDetection.from_pretrained("ogkalu/comic-text-and-bubble-detector")
        print("  ✓ ogkalu detector downloaded and cached")
    except Exception as e:
        print(f"  ✗ ogkalu detector download failed: {e}")
        print("  ℹ  Check internet connection or HuggingFace access")

    # comic-text-detector (dmMaze) — requires manual model download
    section("4b / comic-text-detector (dmMaze) — manual setup")
    ctd_model_dir = Path(__file__).parent / "models" / "ctd"
    ctd_model_path = ctd_model_dir / "comictextdetector.pt"

    if ctd_model_path.exists():
        print(f"  ✓ comictextdetector.pt found at {ctd_model_path}")
    else:
        print(f"  ⚠ comictextdetector.pt not found")
        print(f"  → Download from:")
        print(f"    https://github.com/zyddnys/manga-image-translator/releases/tag/beta-0.2.1")
        print(f"    File: comictextdetector.pt  (~50MB)")
        print(f"  → Place at: {ctd_model_path}")
        ctd_model_dir.mkdir(parents=True, exist_ok=True)
        print(f"  ℹ  Directory created: {ctd_model_dir}")
        print(f"  ℹ  yomeru will use ogkalu detector until this is placed")


def verify_all(skip_manga_ocr: bool) -> bool:
    section("Verification")
    results = {
        "torch":          check_import("torch",         "PyTorch"),
        "iopaint":        check_import("iopaint",       "IOPaint (LaMa)"),
        "easyocr":        check_import("easyocr",       "EasyOCR"),
        "transformers":   check_import("transformers",  "Transformers"),
        "timm":           check_import("timm",          "timm"),
        "cv2":            check_import("cv2",           "OpenCV"),
        "PIL":            check_import("PIL",           "Pillow"),
    }
    if not skip_manga_ocr:
        results["manga_ocr"] = check_import("manga_ocr", "manga-ocr")

    passed = all(results.values())

    print()
    if passed:
        print("  ✓ All checks passed — typesetting pipeline is ready")
    else:
        missing = [k for k, v in results.items() if not v]
        print(f"  ✗ Missing: {', '.join(missing)}")
        print("  → Re-run this script or install manually")
    return passed


def write_status(device: str, skip_manga_ocr: bool) -> None:
    """Write a status file that the backend reads to know what's available."""
    status_path = Path(__file__).parent / "typesetting_status.json"
    import json
    ctd_available = (Path(__file__).parent / "models" / "ctd" / "comictextdetector.pt").exists()

    try:
        import torch
        torch_ok = True
    except ImportError:
        torch_ok = False

    status = {
        "device": device,
        "torch": torch_ok,
        "detectors": {
            "ogkalu": True,    # always try — downloads on first use
            "ctd":    ctd_available,
        },
        "ocr": {
            "easyocr":   True,
            "manga_ocr": not skip_manga_ocr,
        },
        "inpainter": "lama",
    }
    status_path.write_text(json.dumps(status, indent=2))
    print(f"\n  Status written → {status_path}")


# ── main ──────────────────────────────────────────────────────────────────────

def _download_lama() -> None:
    section("LaMa checkpoint download")
    from pathlib import Path
    import shutil

    model_path = Path(__file__).parent / "models" / "lama" / "big-lama.pt"
    if model_path.exists():
        size_mb = model_path.stat().st_size // (1024*1024)
        print(f"  ✓ already exists ({size_mb}MB) at {model_path}")
        return

    model_path.parent.mkdir(parents=True, exist_ok=True)

    # Try mirrors in order using hf_hub_download (handles tokens + redirects)
    mirrors = [
        ("okaris/simple-lama",          "big-lama.pt"),
        ("fashn-ai/LaMa",               "big-lama.pt"),
        ("xingren23/comfyflow-models",   "inpaint/big-lama.pt"),
    ]

    for repo, filename in mirrors:
        try:
            from huggingface_hub import hf_hub_download
            print(f"  Trying {repo}/{filename}…")
            tmp = hf_hub_download(
                repo_id=repo,
                filename=filename,
                local_dir=str(model_path.parent),
            )
            # hf_hub_download may save with different name, move if needed
            tmp_path = Path(tmp)
            if tmp_path != model_path:
                shutil.move(str(tmp_path), str(model_path))
            size_mb = model_path.stat().st_size // (1024*1024)
            print(f"  ✓ Downloaded ({size_mb}MB) → {model_path}")
            return
        except Exception as e:
            print(f"  ✗ {repo}: {e}")

    print("\n  All mirrors failed. Download manually:")
    print("  Option 1 (browser):")
    print("    https://huggingface.co/okaris/simple-lama/resolve/main/big-lama.pt")
    print(f"    Save to: {model_path}")
    print("  Option 2 (CLI if you have HF token):")
    print(f"    huggingface-cli download okaris/simple-lama big-lama.pt --local-dir {model_path.parent}")



def _download_fonts() -> None:
    section("Comic/Manga fonts")
    from pathlib import Path
    fonts_dir = Path(__file__).parent / "assets" / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)

    # Bangers — Bold comic font (Google Fonts, OFL license)
    # Used for: action speech, shouting, SFX
    _dl_font(fonts_dir, "Bangers-Regular.ttf",
        "https://fonts.gstatic.com/s/bangers/v24/FeVQS0BTqb0h60ACL5la2bxii28wYQ.woff2",
        note="Google Fonts OFL - Bold comic font for action/SFX")

    # Anime Ace — Comic speech font (Blambot, free personal use)
    # User must download manually (not redistributable via URL)
    ace_path = fonts_dir / "AnimeAce.ttf"
    if not ace_path.exists():
        print("  ℹ  AnimeAce font (free, used in many scanlations):")
        print("     1. Go to: https://www.dafont.com/anime-ace.font")
        print(f"    2. Download and place AnimeAce.ttf in: {fonts_dir}")

    installed = [f.name for f in fonts_dir.iterdir() if f.suffix == ".ttf"]
    if installed:
        print(f"  ✓ Installed fonts: {', '.join(installed)}")
    else:
        print("  ⚠ No custom fonts installed — using system fallback fonts")
        print("     Download AnimeAce.ttf and place it in backend/assets/fonts/")


def _dl_font(fonts_dir, filename: str, url: str, note: str = "") -> None:
    path = fonts_dir / filename
    if path.exists():
        print(f"  ✓ {filename} already exists")
        return
    try:
        import urllib.request, urllib.error
        print(f"  Downloading {filename}…")
        if note:
            print(f"  ({note})")
        # woff2 → need to convert; skip if not supported
        if url.endswith(".woff2"):
            print(f"  ℹ  {filename}: download manually from Google Fonts")
            print(f"     Search 'Bangers Google Fonts' and download the TTF")
            print(f"     Place at: {path}")
            return
        urllib.request.urlretrieve(url, str(path))
        print(f"  ✓ {filename} downloaded")
    except Exception as e:
        print(f"  ✗ {filename}: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="yomeru typesetting setup")
    parser.add_argument("--cpu",        action="store_true", help="Force CPU mode")
    parser.add_argument("--skip-ocr",   action="store_true", help="Skip manga-ocr (large model)")
    parser.add_argument("--check-only",    action="store_true", help="Only verify, don't install")
    parser.add_argument("--download-lama", action="store_true", help="Download LaMa checkpoint (~200MB)")
    args = parser.parse_args()

    print("\n  yomeru — typesetting pipeline setup")

    section("Device detection")
    device = "cpu" if args.cpu else detect_device()

    if args.check_only:
        verify_all(args.skip_ocr)
        return

    install_torch(device)
    install_iopaint()
    install_ocr(args.skip_ocr)
    install_detector()

    if args.download_lama:
        _download_lama()
    _download_fonts()

    ok = verify_all(args.skip_ocr)
    write_status(device, args.skip_ocr)

    print("\n" + ("=" * 60))
    if ok:
        print("  Setup complete. You can now use the typesetting pipeline.")
        if not (Path(__file__).parent / "models" / "ctd" / "comictextdetector.pt").exists():
            print("  Note: Download comictextdetector.pt for the CTD detector (optional).")
    else:
        print("  Setup incomplete. See errors above.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()