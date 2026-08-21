import shutil
from pathlib import Path

REQUIRED_CREDENTIAL_KEYS = [
    "YOUTUBE_OAUTH_CLIENT_ID",
    "YOUTUBE_OAUTH_CLIENT_SECRET",
    "LLM_API_KEY",
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
    "DATABASE_URL",
]
REQUIRED_EXTERNAL_TOOLS = ["yt-dlp", "ffmpeg"]

CREDENTIALS_TEMPLATE = """# Fill in the values below
# Google Cloud OAuth Client (needed to list/fetch your own playlists,
# including private ones) - see docs/setup.md
YOUTUBE_OAUTH_CLIENT_ID=
YOUTUBE_OAUTH_CLIENT_SECRET=
# Obtained automatically by `sync-master youtube-login` - don't fill in by hand
YOUTUBE_OAUTH_REFRESH_TOKEN=
LLM_API_KEY=
# Spotify app (Developer Dashboard) - the redirect URI below must also be
# added to the app's settings there, exactly as written
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8080/callback
# Optional: only needed for speaker diarization (the "diarization" extra)
HUGGINGFACE_TOKEN=
# Optional: the web UI's read-only role (see docs/web-ui.md). When set,
# downloaded videos grant it read access so the UI can stream them - Postgres
# large objects have their own ACLs and table grants don't cover them.
WEB_READONLY_ROLE=
# Postgres connection string - see docker-compose.yml for a local dev instance
DATABASE_URL=postgresql+psycopg2://sync_master:changeme@localhost:5432/mydb
"""

LLM_YAML_TEMPLATE = """provider: deepseek
model: deepseek-chat
base_url: https://api.deepseek.com
"""

SETTINGS_YAML_TEMPLATE = f"""output_base_dir: {Path.home() / "sync-master-output"}
"""


def scaffold_config_dir(config_dir: Path) -> None:
    (config_dir / "logs").mkdir(parents=True, exist_ok=True)

    defaults = {
        "spotify_overrides.json": "{}",
        "credentials.env": CREDENTIALS_TEMPLATE,
        "llm.yaml": LLM_YAML_TEMPLATE,
        "settings.yaml": SETTINGS_YAML_TEMPLATE,
    }
    for filename, content in defaults.items():
        path = config_dir / filename
        if not path.exists():
            path.write_text(content)


def check_database_connection(database_url: str | None) -> str | None:
    """Returns None if the connection succeeds, or an error message otherwise."""
    if not database_url:
        return "DATABASE_URL is not set"

    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import SQLAlchemyError

    try:
        engine = create_engine(database_url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
    except SQLAlchemyError as exc:
        return str(exc)
    return None


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

    if "DATABASE_URL" not in missing:
        from dotenv import dotenv_values

        database_url = dotenv_values(config_dir / "credentials.env").get("DATABASE_URL")
        db_error = check_database_connection(database_url)
        if db_error:
            typer.echo(f"Could not connect to DATABASE_URL: {db_error}")
            typer.echo("Start Postgres (e.g. `docker compose up -d postgres`) and run `alembic upgrade head`.")
        else:
            typer.echo("Database connection: ok")

    typer.echo(
        "Run `sync-master youtube-login` to complete the one-time YouTube OAuth "
        "authorization (needed to list and fetch your own playlists, including "
        "private ones)."
    )
    typer.echo(
        "For Spotify playlist sync, run `sync-master spotify-login` to complete "
        "the one-time OAuth authorization (requires playlist-modify scope; make "
        "sure SPOTIFY_REDIRECT_URI is also registered in your Spotify app's "
        "dashboard settings)."
    )

    typer.echo("Add this line to your crontab to run sync-master automatically:")
    typer.echo(f"  {crontab_line()}")
