# Streamlit Community Cloud Deploy

## Entrypoint
- Main file: `meta_dashboard_app.py`

## Required files
- `requirements.txt`
- `runtime.txt`
- `.streamlit/config.toml`

## Secrets
Create `.streamlit/secrets.toml` locally or paste the same values into Streamlit Community Cloud Secrets:

```toml
GEMINI_API_KEY = "your-gemini-api-key"
GEMINI_MODEL = "gemini-2.5-flash"
WEBHOOK_URL = "optional"
SLACK_BOT_TOKEN = "optional"
SLACK_CHANNEL_ID = "optional"
```

## Notes
- Do not commit `.streamlit/secrets.toml`.
- This app reads secrets from environment variables or `.streamlit/secrets.toml`.
- The app expects `meta_ads_dashboard.db` and `dashboard_assets/` to exist in the repository root.
