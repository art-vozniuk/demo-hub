import pytest
from unittest.mock import AsyncMock


@pytest.fixture
def mock_s3_client(mocker):
    client = mocker.MagicMock()
    client.download_file = AsyncMock(return_value=b"fake-image-data")
    client.upload_file = AsyncMock(return_value="https://example.com/result.png")
    client.download_file_to_disc = AsyncMock(return_value="/tmp/model.onnx")
    return client
