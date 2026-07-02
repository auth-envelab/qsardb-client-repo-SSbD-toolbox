from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from qsardb_client.archive import ArchiveDownloadError, ArchiveDownloader


def mock_client(status_code: int = 200, content: bytes = b"qdb-bytes") -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=content, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_download_url_writes_response_bytes_to_destination_dir(tmp_path: Path) -> None:
    client = mock_client(content=b"archive-content")
    downloader = ArchiveDownloader(client=client)

    output_path = downloader.download_url(
        "https://example.invalid/files/archive.qdb",
        tmp_path,
    )

    assert output_path == tmp_path / "archive.qdb"
    assert output_path.read_bytes() == b"archive-content"


def test_destination_dir_is_created_if_absent(tmp_path: Path) -> None:
    client = mock_client()
    destination_dir = tmp_path / "nested" / "downloads"

    output_path = ArchiveDownloader(client=client).download_url(
        "https://example.invalid/archive.qdb",
        destination_dir,
    )

    assert destination_dir.is_dir()
    assert output_path.exists()


def test_inferred_filename_from_url_path_works(tmp_path: Path) -> None:
    client = mock_client()

    output_path = ArchiveDownloader(client=client).download_url(
        "https://example.invalid/path/to/test-archive.qdb?download=1",
        tmp_path,
    )

    assert output_path.name == "test-archive.qdb"


def test_explicit_filename_works(tmp_path: Path) -> None:
    client = mock_client()

    output_path = ArchiveDownloader(client=client).download_url(
        "https://example.invalid/path/to/original.qdb",
        tmp_path,
        filename="renamed.qdb",
    )

    assert output_path == tmp_path / "renamed.qdb"


@pytest.mark.parametrize(
    "filename",
    ["", ".", "..", "nested/archive.qdb", "nested\\archive.qdb", "/tmp/archive.qdb"],
)
def test_unsafe_filename_is_rejected(tmp_path: Path, filename: str) -> None:
    client = mock_client()

    with pytest.raises(ArchiveDownloadError):
        ArchiveDownloader(client=client).download_url(
            "https://example.invalid/archive.qdb",
            tmp_path,
            filename=filename,
        )


def test_existing_file_with_overwrite_false_raises(tmp_path: Path) -> None:
    client = mock_client()
    output_path = tmp_path / "archive.qdb"
    output_path.write_bytes(b"existing")

    with pytest.raises(ArchiveDownloadError, match="already exists"):
        ArchiveDownloader(client=client).download_url(
            "https://example.invalid/archive.qdb",
            tmp_path,
        )

    assert output_path.read_bytes() == b"existing"


def test_existing_file_with_overwrite_true_is_replaced(tmp_path: Path) -> None:
    client = mock_client(content=b"replacement")
    output_path = tmp_path / "archive.qdb"
    output_path.write_bytes(b"existing")

    result_path = ArchiveDownloader(client=client).download_url(
        "https://example.invalid/archive.qdb",
        tmp_path,
        overwrite=True,
    )

    assert result_path == output_path
    assert output_path.read_bytes() == b"replacement"


def test_http_404_raises_archive_download_error(tmp_path: Path) -> None:
    client = mock_client(status_code=404, content=b"not found")

    with pytest.raises(ArchiveDownloadError, match="HTTP 404"):
        ArchiveDownloader(client=client).download_url(
            "https://example.invalid/missing.qdb",
            tmp_path,
        )


def test_injected_client_is_used_without_live_network(tmp_path: Path) -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, content=b"from-injected-client", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    output_path = ArchiveDownloader(client=client).download_url(
        "https://example.invalid/direct/archive.qdb",
        tmp_path,
    )

    assert seen_urls == ["https://example.invalid/direct/archive.qdb"]
    assert output_path.read_bytes() == b"from-injected-client"
