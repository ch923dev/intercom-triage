# Snippets

Reference implementations referenced by `tasks.md`. These are **not** wired into
the running app — they're starting points that get ported into `backend/app/`
as their respective tasks land.

| Snippet              | Used by  | Status                          |
|----------------------|----------|---------------------------------|
| `models.py`          | T006     | Ported → `backend/app/models.py` (T006 done) |
| `prompt_builder.py`  | T013     | Pending — ids need `int` (plan §12), ORM-row imports |

Keep these around as a quick reference while iterating on the production
versions; once a snippet's production version stabilizes, the snippet can be
deleted.
