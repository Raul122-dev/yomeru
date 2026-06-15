"""Entry point: python -m yomeru"""
import sys
import uvicorn

from yomeru.core.config import PORT


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    print(f"\n  yomeru  →  http://localhost:{port}/ui")
    print(f"  api     →  http://localhost:{port}/api/docs\n")
    uvicorn.run("yomeru.app:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
