from pathlib import Path


def _default_factory(opts):
    import yt_dlp

    return yt_dlp.YoutubeDL(opts)


def download_video(video_id: str, output_dir: Path, downloader_factory=None) -> Path:
    factory = downloader_factory or _default_factory
    output_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "best",
        "outtmpl": str(output_dir / "video.%(ext)s"),
    }
    url = f"https://www.youtube.com/watch?v={video_id}"

    with factory(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return Path(ydl.prepare_filename(info))
