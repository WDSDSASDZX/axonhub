import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Python AI gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8091)
    args = parser.parse_args()
    uvicorn.run("axonhub.app:create_app", factory=True, host=args.host, port=args.port)
