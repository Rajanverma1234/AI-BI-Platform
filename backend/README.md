# Backend

FastAPI service for the AI BI Platform. See the repository [README](../README.md)
for full setup instructions and [docs/architecture.md](../docs/architecture.md)
for the layering rules.

```bash
python -m venv .venv && ./.venv/Scripts/activate   # Windows
pip install -e ".[dev]"

uvicorn app.main:app --reload      # serve on :8000
alembic upgrade head               # apply migrations
pytest                             # tests
mypy                               # type check
ruff check .                       # lint
```
