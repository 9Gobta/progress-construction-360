# Progress Construction API

Modular FastAPI application for authentication, projects, future capture processing and AI results.

## Commands

```powershell
python -m pip install -e ".[dev]"
python -m alembic -c alembic.ini upgrade head
python -m uvicorn progress_api.main:app --reload --reload-dir src
python -m pytest
python -m ruff check src tests
```

Run commands from this directory after activating the repository virtual environment.
