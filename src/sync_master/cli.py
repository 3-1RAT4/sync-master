import os
from pathlib import Path

import typer

from sync_master.db.repository import LockHeldError
from sync_master.runner import perform_run

app = typer.Typer()

CONFIG_DIR = Path.home() / ".config" / "sync-master"


@app.command()
def run(dry_run: bool = False) -> None:
    """Discover flagged playlists, diff state, and dispatch actions for pending videos."""
    run_log: list = []
    try:
        perform_run(CONFIG_DIR, dry_run=dry_run, run_log=run_log)
    except LockHeldError:
        typer.echo("Another sync-master run is already in progress. Skipping.")
        raise typer.Exit(code=1)

    if not run_log:
        typer.echo("No new or pending videos to process.")
        return

    for entry in run_log:
        typer.echo(f"{entry['title']} [{entry['folder_path']}] -> {', '.join(entry['actions'])}")
        for call in entry["call_log"]:
            typer.echo(f"    {call}")


@app.command()
def export_vault(
    vault: Path | None = typer.Option(None, help="Obsidian vault root (default: vault_dir in settings.yaml)."),
    dry_run: bool = typer.Option(False, help="Print the tree that would be written; write nothing."),
    from_db: bool = typer.Option(
        False,
        help="Take playlists, videos and their order from the catalog in Postgres instead of asking "
        "YouTube. No token needed; order is the order videos were first catalogued.",
    ),
) -> None:
    """Lay the catalog out in an Obsidian vault: a note per video, plus the
    stored mp4 / transcript / summary for videos the pipeline has processed."""
    from dotenv import load_dotenv

    from sync_master.config import load_settings
    from sync_master.db.engine import get_session
    from sync_master.vault_export import VAULT_SUBDIR, catalog_items, catalog_playlists
    from sync_master.vault_export import export_vault as run_export

    load_dotenv(CONFIG_DIR / "credentials.env")
    settings = load_settings(CONFIG_DIR / "settings.yaml")
    vault_dir = vault or (Path(settings["vault_dir"]).expanduser() if settings.get("vault_dir") else None)
    if vault_dir is None:
        typer.echo("No vault given: pass --vault PATH or set vault_dir in settings.yaml.")
        raise typer.Exit(code=1)
    if not vault_dir.is_dir():
        typer.echo(f"Vault directory does not exist: {vault_dir}")
        raise typer.Exit(code=1)

    typer.echo(f"{'Would write' if dry_run else 'Writing'} to {vault_dir / VAULT_SUBDIR}\n")
    session = get_session()
    try:
        if from_db:
            stats = run_export(
                vault_dir,
                session,
                None,
                dry_run=dry_run,
                fetch_playlists_fn=lambda _client: catalog_playlists(session),
                fetch_items_fn=lambda playlist_id, youtube_client=None: catalog_items(session, playlist_id),
                log=typer.echo,
            )
        else:
            from sync_master.youtube_auth import build_oauth_client

            stats = run_export(vault_dir, session, build_oauth_client(), dry_run=dry_run, log=typer.echo)
    finally:
        session.close()

    typer.echo(
        f"\n{stats.playlists} playlists, {stats.notes} notes, "
        f"{stats.videos} videos ({stats.video_bytes / 1e6:.0f} MB), "
        f"{stats.transcripts} transcripts, {stats.summaries} summaries"
        + (" - dry run, nothing written" if dry_run else "")
    )


@app.command()
def bootstrap() -> None:
    """Scaffold ~/.config/sync-master and validate credentials."""
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
def migrate_legacy() -> None:
    """One-time import of an existing state.json + output directory into Postgres."""
    from sync_master.legacy_migration import run_legacy_migration

    counts = run_legacy_migration(CONFIG_DIR)
    typer.echo("Migrated legacy state into Postgres:")
    for key, value in counts.items():
        typer.echo(f"  {key}: {value}")


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
