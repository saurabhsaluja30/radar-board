"""Read backend settings for tests: the process environment first, then the backend .env file.

The .env is looked up at /app/backend/.env (the hosted container) and then next to this repo's backend code, so
the suites run both on the platform and on a developer machine.
"""
import os

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def env_value(key: str):
    if os.environ.get(key):
        return os.environ[key]
    for path in ("/app/backend/.env", os.path.join(_HERE, ".env")):
        if os.path.exists(path):
            with open(path) as fh:
                for line in fh:
                    if line.startswith(key + "="):
                        return line.split("=", 1)[1].strip().strip('"')
    return None
