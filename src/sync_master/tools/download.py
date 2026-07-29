from pathlib import Path

from sync_master.tools.naming import sanitize_filename


def _default_factory(opts):
    import yt_dlp

    return yt_dlp.YoutubeDL(opts)


def download_video(video_id: str, output_dir: Path, title: str | None = None, downloader_factory=None) -> Path:
    factory = downloader_factory or _default_factory
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = sanitize_filename(title) if title else "video"
    opts = {
        "format": "best",
        "outtmpl": str(output_dir / f"{base_name}.%(ext)s"),
    }
    url = f"https://www.youtube.com/watch?v={video_id}"

    with factory(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return Path(ydl.prepare_filename(info))
