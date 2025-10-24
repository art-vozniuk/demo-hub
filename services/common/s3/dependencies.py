from typing import Annotated
from fastapi import Depends
from .client import S3Client

s3_client = S3Client()


def get_s3_client() -> S3Client:
    return s3_client


S3Dep = Annotated[S3Client, Depends(get_s3_client)]
