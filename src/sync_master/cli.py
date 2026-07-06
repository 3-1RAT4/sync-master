from pathlib import Path

import typer

from sync_master.runner import perform_run
from sync_master.state import LockHeldError

app = typer.Typer()

CONFIG_DIR = Path.home() / ".config" / "sync-master"


@app.command()
def run(dry_run: bool = False) -> None:
    """Fetch sources, diff state, and run the agent over pending videos."""
    try:
        perform_run(CONFIG_DIR, dry_run=dry_run)
    except LockHeldError:
        typer.echo("Another sync-master run is already in progress. Skipping.")
        raise typer.Exit(code=1)


@app.command()
def bootstrap() -> None:
    """Scaffold ~/.config/sync-master and validate credentials."""
    from sync_master.bootstrap import run_bootstrap

    run_bootstrap(CONFIG_DIR)


@app.command()
def spotify_login() -> None:
    """Run the one-time Spotify OAuth flow (opens a browser) and save the refresh token."""
    from dotenv import load_dotenv, set_key
    from spotipy.oauth2 import SpotifyOAuth

    credentials_path = CONFIG_DIR / "credentials.env"
    load_dotenv(credentials_path)

    auth_manager = SpotifyOAuth(scope="playlist-modify-public playlist-modify-private")
    token_info = auth_manager.get_access_token(as_dict=True)

    set_key(str(credentials_path), "SPOTIFY_REFRESH_TOKEN", token_info["refresh_token"])
    typer.echo(f"Saved Spotify refresh token to {credentials_path}")


if __name__ == "__main__":
    app()
