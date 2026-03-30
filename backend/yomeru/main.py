"""Entry point when installed via pip install ."""
import sys
import os
from pathlib import Path

# when installed as a package, static files live next to this file
os.environ.setdefault("YOMERU_STATIC", str(Path(__file__).parent / "static"))


def main():
    import uvicorn
    from yomeru.core.config import PORT
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    print(f"\n  yomeru  →  http://localhost:{port}")
    print(f"  docs    →  http://localhost:{port}/api/docs\n")
    uvicorn.run("yomeru.app:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
