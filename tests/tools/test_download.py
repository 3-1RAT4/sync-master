from pathlib import Path

from sync_master.tools.download import download_video


class FakeYoutubeDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download=True):
        return {"id": "v1", "ext": "mp4", "url": url}

    def prepare_filename(self, info):
        return self.opts["outtmpl"].replace("%(ext)s", info["ext"])


def test_download_video_returns_path_to_downloaded_file(tmp_path):
    def fake_factory(opts):
        return FakeYoutubeDL(opts)

    result = download_video("v1", tmp_path, downloader_factory=fake_factory)

    assert result == tmp_path / "video.mp4"


def test_download_video_passes_correct_url(tmp_path):
    captured_urls = []

    class CapturingYoutubeDL(FakeYoutubeDL):
        def extract_info(self, url, download=True):
            captured_urls.append(url)
            return super().extract_info(url, download)

    download_video("v1", tmp_path, downloader_factory=lambda opts: CapturingYoutubeDL(opts))

    assert captured_urls == ["https://www.youtube.com/watch?v=v1"]
