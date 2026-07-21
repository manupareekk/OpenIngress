# Contributing

Thanks for taking a look at OpenIngress.

## Development

1. Copy env templates: `cp backend/.env.example backend/.env` and `cp frontend/.env.example frontend/.env`
2. Set `LLM_API_KEY` in `backend/.env`
3. Run `make install` (venv, pip, **Playwright Chromium**, npm)
4. Start backend: `make backend` → `:5055`
5. Start frontend: `make frontend` → `:5175`
6. Tests: `make test`

Auth is disabled by default for local OSS (`AUTH_DISABLED=1` / `VITE_AUTH_DISABLED=1`).

## Scope

Please keep pull requests focused. Small, behaviorally clear changes are much easier to review and merge than broad refactors.

## Pull Requests

- Describe the user-facing or API-facing behavior change.
- Include setup notes if the change depends on specific environment variables.
- Add or update tests when you touch shared behavior.
- Avoid mixing unrelated cleanup into the same pull request.

## Issues

Bug reports are most helpful when they include:

- expected behavior
- actual behavior
- reproduction steps
- relevant logs or screenshots
- environment details

## Questions

If you are unsure whether a change fits the project direction, open an issue before investing heavily in implementation.
