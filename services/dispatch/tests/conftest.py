import pytest
from unittest.mock import AsyncMock


@pytest.fixture
def mock_s3_client(mocker):
    client = mocker.MagicMock()
    client.download_file = AsyncMock(return_value=b"fake-image-bytes")
    client.upload_file = AsyncMock(return_value="https://example.com/result.png")
    return client
