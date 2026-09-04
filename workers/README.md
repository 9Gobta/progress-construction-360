# Background workers

Celery is configured in `apps/api/src/progress_api/worker.py` so API modules and workers share versioned domain code during the MVP. Task entry points are grouped here by processing domain as they are implemented:

- `video/`: validation, proxy and keyframe tasks
- `localization/`: relative path and floor-plan mapping
- `progress_ai/`: evidence inference and progress aggregation

These directories do not become separate network services until scaling or deployment ownership requires it.

