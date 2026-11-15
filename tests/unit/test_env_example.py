"""The documented setup (copy .env.example to .env) must start the LangGraph server."""

from pathlib import Path

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"

# langgraph-api parses these as booleans at startup and refuses to start on an empty value.
BOOLEAN_SETTINGS = ("LANGSMITH_TRACING",)


def test_boolean_settings_in_env_example_are_not_blank():
    values = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    for key in BOOLEAN_SETTINGS:
        if key in values:
            assert values[key].lower() in ("true", "false"), f"{key} must be true or false in .env.example, not blank"
