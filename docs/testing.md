# Tests

Run these from the repository root after setup. Replace `python` with `.\.venv\Scripts\python.exe` on Windows if your environment is not activated.

```powershell
python -m unittest discover -s tests -v
python scripts/verify_install.py
```

The default suite uses temporary directories and skips browser integration tests. The startup check opens an ephemeral HTTP server with a fresh temporary database and checks authenticated routes and frontend assets. Neither command needs a working Ollama model.

For browser coverage, install Chromium, ensure Node.js is on PATH for the fixture's JavaScript syntax check, and enable the opt-in suite:

```powershell
python -m playwright install chromium
$env:WORKHORSE_BROWSER_TESTS = '1'
python -m unittest discover -s tests -v
```

A successful [development scenario](../tests/test_development.py) means the host can run the code/edit/test loop against a real page with scripted model decisions. It does not measure a live model's reasoning, visual accuracy or performance. Use **Test model response** in the app and a representative workspace task to evaluate those on your machine.

The [maintenance tests](../maintenance/README.md) exercise installation conflicts and rollback separately. The [CI workflow](../.github/workflows/tests.yml) documents which checks run on each OS.

## Verified for this source snapshot

On 17 November 2026, all 52 application tests (including the five browser cases),
all four migration tests, and the temporary startup/HTTP check passed on Linux
with Python 3.12. Playwright 1.63 used Chromium Headless Shell 134 through the
test executable override. No Windows session or live Ollama model was used;
the workflow above lets maintainers run those checks on their own hardware.
