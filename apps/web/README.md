# Progress Construction Web

Next.js App Router frontend for the Progress Construction AI workflow.

## Development

From the repository root:

```powershell
npm install
npm run dev:web
```

The Backend-for-Frontend route handlers keep the FastAPI access token in an HTTP-only cookie. `API_SERVER_URL` is server-only and defaults to `http://localhost:8000/api/v1`.

## Checks

```powershell
npm run lint:web
npm run typecheck:web
npm run build:web
```

