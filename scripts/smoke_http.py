"""Check fixed HTTP routes without credentials or GitHub traffic."""
import json
import sys
import urllib.error
import urllib.request


def main(base):
    with urllib.request.urlopen(base + "/healthz") as response:
        assert json.load(response)["status"] == "alive"
    with urllib.request.urlopen(base + "/") as response:
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert b'<html lang="en">' in response.read()
    with urllib.request.urlopen(base + "/api/dataset?mode=SAMPLE") as response:
        assert json.load(response)["Info"][0]["Mode"] == "SAMPLE"
    for path in ("/admin", "/admin/.secrets/key", "/.secrets", "/.env", "/.env.example", "/.git",
                 "/.git/config", "/Dockerfile", "/scripts/server.py", "/data/dataset.json",
                 "/../.env", "/%2e%2e/.env", "/%252e%252e/.env", "//etc/passwd"):
        try:
            urllib.request.urlopen(base + path)
        except urllib.error.HTTPError as error:
            assert error.code == 404, (path, error.code)
        else:
            raise AssertionError(f"Unexpected public route: {path}")
    print("PASS: health, SAMPLE, headers, secret paths and traversal")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080")
