# Contributing

Thanks for taking the time to contribute.

## Development setup

- **Python**: create a venv and install `requirements.txt`
- **Dashboard**: `cd dashboard && npm install`

## Guidelines

- Keep secrets out of git. Never commit `config/settings.py`, `.env`, tokens, or account identifiers.
- Prefer small, focused pull requests with a clear description and test plan.
- Match existing coding style and keep changes easy to review.

## Testing (basic)

- Run the agent scripts locally to ensure they start without errors.
- Start the dashboard and confirm it can load the latest `snapshot_signals.json` output.

