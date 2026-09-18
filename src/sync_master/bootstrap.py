import shutil
from pathlib import Path

REQUIRED_CREDENTIAL_KEYS = [
    "YOUTUBE_OAUTH_CLIENT_ID",
    "YOUTUBE_OAUTH_CLIENT_SECRET",
    "LLM_API_KEY",
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
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
"""

LLM_YAML_TEMPLATE = """provider: deepseek
model: deepseek-chat
base_url: https://api.deepseek.com
"""

SETTINGS_YAML_TEMPLATE = f"""# The Obsidian vault sync-master writes into (everything lands under
# SYNC_MASTER/VIDEOS/YOUTUBE/ inside it).
vault_dir: {Path.home() / "Documents" / "Obsidian Vault"}
# Scratch space for downloads while they're being transcribed; safe to clean out.
output_base_dir: {Path.home() / "sync-master-output"}
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


def check_vault(vault_dir: str | None) -> str | None:
    """Returns None if vault_dir is an Obsidian vault we can write into, or
    an error message otherwise."""
    if not vault_dir:
        return "vault_dir is not set in settings.yaml"
    path = Path(vault_dir).expanduser()
    if not path.is_dir():
        return f"{path} does not exist"
    if not (path / ".obsidian").is_dir():
        return f"{path} has no .obsidian/ folder - is it really an Obsidian vault?"
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

    import yaml

    settings = yaml.safe_load((config_dir / "settings.yaml").read_text()) or {}
    vault_error = check_vault(settings.get("vault_dir"))
    if vault_error:
        typer.echo(f"Vault: {vault_error}")
        typer.echo("Set vault_dir in settings.yaml to your Obsidian vault's root folder.")
    else:
        typer.echo(f"Vault: {settings['vault_dir']} ok")

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
