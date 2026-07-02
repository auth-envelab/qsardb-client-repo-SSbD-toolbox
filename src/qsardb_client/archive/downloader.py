"""Direct URL downloader for QsarDB archive files."""

from __future__ import annotations

import posixpath
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import TracebackType
from urllib.parse import unquote, urlparse

import httpx


class ArchiveDownloadError(Exception):
    """Base exception for archive download failures."""


class ArchiveDownloader:
    def __init__(
        self,
        *,
        timeout: float | httpx.Timeout = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.timeout = timeout
        self._client = client
        self._owns_client = client is None

    def download_url(
        self,
        url: str,
        destination_dir: str | Path,
        *,
        filename: str | None = None,
        overwrite: bool = False,
    ) -> Path:
        output_dir = Path(destination_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        resolved_dir = output_dir.resolve()

        output_name = filename if filename is not None else self._filename_from_url(url)
        self._validate_filename(output_name)

        output_path = (resolved_dir / output_name).resolve()
        if output_path.parent != resolved_dir:
            raise ArchiveDownloadError("Refusing to write outside destination_dir.")

        if output_path.exists() and not overwrite:
            raise ArchiveDownloadError(f"Target file already exists: {output_path}")

        try:
            response = self._get_client().get(url)
        except httpx.HTTPError as exc:
            raise ArchiveDownloadError(f"Archive download failed: {exc}") from exc

        if response.status_code != 200:
            raise ArchiveDownloadError(
                f"Archive download failed with HTTP {response.status_code} for {url}"
            )

        output_path.write_bytes(response.content)
        return output_path

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "ArchiveDownloader":
        self._get_client()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def _filename_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        name = unquote(posixpath.basename(parsed.path))
        self._validate_filename(name)
        return name

    def _validate_filename(self, filename: str) -> None:
        if filename in {"", ".", ".."}:
            raise ArchiveDownloadError("Archive filename must be a simple file name.")
        if "/" in filename or "\\" in filename:
            raise ArchiveDownloadError("Archive filename must not contain path separators.")
        if (
            Path(filename).is_absolute()
            or PureWindowsPath(filename).is_absolute()
            or PurePosixPath(filename).is_absolute()
        ):
            raise ArchiveDownloadError("Archive filename must not be an absolute path.")
