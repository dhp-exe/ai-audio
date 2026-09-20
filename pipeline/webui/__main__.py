import argparse

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser(description="Audio AI pipeline web client")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    uvicorn.run("pipeline.webui.app:app", host=a.host, port=a.port, log_level="info")


if __name__ == "__main__":
    main()
