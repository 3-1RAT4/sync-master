from pathlib import Path

from sync_master.tools.naming import sanitize_filename


_TEMP_SUFFIXES = {".part", ".ytdl", ".temp"}


def _default_factory(opts):
    import yt_dlp

    return yt_dlp.YoutubeDL(opts)


def download_video(video_id: str, output_dir: Path, title: str | None = None, downloader_factory=None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = sanitize_filename(title) if title else "video"

    # A file from an earlier run means no re-download - but not yt-dlp's own
    # in-progress leftovers (.part, .ytdl), which a failed attempt leaves behind.
    existing = [p for p in output_dir.glob(f"{base_name}.*") if p.suffix not in _TEMP_SUFFIXES]
    if existing:
        return existing[0]

    factory = downloader_factory or _default_factory
    opts = {
        # YouTube hardly serves combined video+audio any more; "best" alone
        # collapses to a 360p leftover that then 403s. Take the best video and
        # best audio streams and let ffmpeg merge them - h264/aac in mp4 first,
        # since the vault names the file .mp4 and plays it in Obsidian.
        "format": "bv*[vcodec^=avc1][ext=mp4]+ba[ext=m4a]/bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": str(output_dir / f"{base_name}.%(ext)s"),
    }
    url = f"https://www.youtube.com/watch?v={video_id}"

    with factory(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return Path(ydl.prepare_filename(info))
