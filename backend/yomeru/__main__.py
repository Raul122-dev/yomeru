"""Entry point: python -m yomeru"""
import sys
import uvicorn

from yomeru.config.server import DATA_DIR, HOST, PORT


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    print(f"\n  yomeru  →  http://localhost:{port}/ui")
    print(f"  api     →  http://localhost:{port}/api/docs")
    print(f"  data    →  {DATA_DIR}\n")
    uvicorn.run("yomeru.app:app", host=HOST, port=port)


if __name__ == "__main__":
    main()
