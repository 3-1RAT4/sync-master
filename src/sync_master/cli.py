import os
from pathlib import Path

import typer

from sync_master.runner import perform_run
from sync_master.state import LockHeldError

app = typer.Typer()

CONFIG_DIR = Path.home() / ".config" / "sync-master"


@app.command()
def run(dry_run: bool = False) -> None:
    """Sync the vault with YouTube: place every playlist and video, then run
    the flagged playlists' actions. --dry-run writes nothing, not even notes."""
    try:
        report = perform_run(CONFIG_DIR, dry_run=dry_run)
    except LockHeldError as exc:
        typer.echo(f"Another sync-master run is already in progress ({exc}). Skipping.")
        raise typer.Exit(code=1)

    verb = "would create" if dry_run else "created"
    typer.echo(
        f"{report.playlists} playlists, {report.videos} videos - "
        f"{verb} {report.created} folders, moved {report.moved}"
    )

    if not report.processed:
        typer.echo("No new or pending videos to process.")
        return

    for entry in report.processed:
        typer.echo(f"{entry['title']} [{entry['folder_path']}] -> {', '.join(entry['actions'])}")
        for call in entry["call_log"]:
            typer.echo(f"    {call}")


@app.command()
def bootstrap() -> None:
    """Scaffold ~/.config/sync-master and validate credentials, tools and the vault."""
    from sync_master.bootstrap import run_bootstrap

    run_bootstrap(CONFIG_DIR)


@app.command()
def youtube_login() -> None:
    """Run the one-time YouTube OAuth flow (opens a browser) and save the refresh token."""
    from dotenv import load_dotenv, set_key

    from sync_master.youtube_auth import run_oauth_login_flow

    credentials_path = CONFIG_DIR / "credentials.env"
    load_dotenv(credentials_path)

    client_id = os.environ.get("YOUTUBE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        typer.echo("Set YOUTUBE_OAUTH_CLIENT_ID and YOUTUBE_OAUTH_CLIENT_SECRET in credentials.env first.")
        raise typer.Exit(code=1)

    refresh_token = run_oauth_login_flow(client_id, client_secret)

    set_key(str(credentials_path), "YOUTUBE_OAUTH_REFRESH_TOKEN", refresh_token)
    typer.echo(f"Saved YouTube refresh token to {credentials_path}")


@app.command()
def spotify_login() -> None:
    """Run the one-time Spotify OAuth flow (opens a browser) and cache the token."""
    from dotenv import load_dotenv

    from sync_master.spotify_auth import CACHE_PATH, build_oauth_manager

    credentials_path = CONFIG_DIR / "credentials.env"
    load_dotenv(credentials_path)

    if not os.environ.get("SPOTIFY_CLIENT_ID") or not os.environ.get("SPOTIFY_CLIENT_SECRET"):
        typer.echo("Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in credentials.env first.")
        raise typer.Exit(code=1)

    auth_manager = build_oauth_manager()
    auth_manager.get_access_token(as_dict=True)
    typer.echo(f"Spotify authorization cached at {CACHE_PATH}")


if __name__ == "__main__":
    app()
