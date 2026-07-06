import shutil
from pathlib import Path

REQUIRED_CREDENTIAL_KEYS = ["YOUTUBE_API_KEY", "LLM_API_KEY"]
REQUIRED_EXTERNAL_TOOLS = ["yt-dlp", "ffmpeg"]

CREDENTIALS_TEMPLATE = """# Fill in the values below
YOUTUBE_API_KEY=
LLM_API_KEY=
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REFRESH_TOKEN=
"""

LLM_YAML_TEMPLATE = """provider: deepseek
model: deepseek-chat
base_url: https://api.deepseek.com
"""


def scaffold_config_dir(config_dir: Path) -> None:
    (config_dir / "sources").mkdir(parents=True, exist_ok=True)
    (config_dir / "logs").mkdir(parents=True, exist_ok=True)

    defaults = {
        "state.json": '{"videos": {}}',
        "spotify_overrides.json": "{}",
        "credentials.env": CREDENTIALS_TEMPLATE,
        "llm.yaml": LLM_YAML_TEMPLATE,
    }
    for filename, content in defaults.items():
        path = config_dir / filename
        if not path.exists():
            path.write_text(content)


def check_missing_credentials(credentials_path: Path) -> list[str]:
    from dotenv import dotenv_values

    values = dotenv_values(credentials_path)
    return [key for key in REQUIRED_CREDENTIAL_KEYS if not values.get(key)]


def check_external_tools(which_fn=shutil.which) -> dict[str, bool]:
    return {tool: which_fn(tool) is not None for tool in REQUIRED_EXTERNAL_TOOLS}


def crontab_line(interval_minutes: int = 15) -> str:
    return f"*/{interval_minutes} * * * * sync-master run"


def run_bootstrap(config_dir: Path) -> None:
    import typer

    scaffold_config_dir(config_dir)
    typer.echo(f"Scaffolded config at {config_dir}")

    tools = check_external_tools()
    for tool, available in tools.items():
        status = "found" if available else "MISSING - please install"
        typer.echo(f"  {tool}: {status}")

    missing = check_missing_credentials(config_dir / "credentials.env")
    if missing:
        typer.echo(f"Missing credentials in {config_dir / 'credentials.env'}: {', '.join(missing)}")
        typer.echo("Please edit that file and re-run bootstrap.")

    typer.echo(
        "For Spotify playlist sync, run `sync-master spotify-login` to complete "
        "the one-time OAuth authorization (requires playlist-modify scope)."
    )

    typer.echo("Add this line to your crontab to run sync-master automatically:")
    typer.echo(f"  {crontab_line()}")
