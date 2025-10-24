import { S3Client, PutObjectCommand } from "@aws-sdk/client-s3";

const s3Config = {
  region: import.meta.env.VITE_S3_REGION || "us-east-1",
  endpoint: import.meta.env.VITE_S3_ENDPOINT,
  credentials: {
    accessKeyId: import.meta.env.VITE_S3_ACCESS_KEY_ID || "",
    secretAccessKey: import.meta.env.VITE_S3_ACCESS_KEY_SECRET || "",
  },
  forcePathStyle: true,
};

const s3Client = new S3Client(s3Config);

export interface S3UploadResult {
  bucket: string;
  key: string;
  url: string;
}

export async function uploadToS3(
  file: File,
  bucket: string,
  key: string
): Promise<S3UploadResult> {
  const arrayBuffer = await file.arrayBuffer();
  const buffer = new Uint8Array(arrayBuffer);

  const command = new PutObjectCommand({
    Bucket: bucket,
    Key: key,
    Body: buffer,
    ContentType: file.type,
  });

  await s3Client.send(command);

  const publicEndpoint = import.meta.env.VITE_S3_PUBLIC_BUCKETS_ENDPOINT;
  const url = `${publicEndpoint}/${bucket}/${key}`;

  return {
    bucket,
    key,
    url,
  };
}

export interface ParsedS3Url {
  bucket: string;
  key: string;
}

export function parseS3Url(url: string): ParsedS3Url {
  const publicEndpoint = import.meta.env.VITE_S3_PUBLIC_BUCKETS_ENDPOINT;
  
  if (url.startsWith(publicEndpoint)) {
    const path = url.substring(publicEndpoint.length);
    const parts = path.split("/").filter(Boolean);
    
    if (parts.length < 2) {
      throw new Error(`Invalid S3 URL format: ${url}`);
    }
    
    const bucket = parts[0];
    const key = parts.slice(1).join("/");
    
    return { bucket, key };
  }
  
  const urlObj = new URL(url);
  const pathParts = urlObj.pathname.split("/").filter(Boolean);
  
  if (pathParts.length < 2) {
    throw new Error(`Invalid S3 URL format: ${url}`);
  }
  
  const bucket = pathParts[0];
  const key = pathParts.slice(1).join("/");
  
  return { bucket, key };
}

export function getFileExtension(filename: string): string {
  const parts = filename.split(".");
  return parts.length > 1 ? parts[parts.length - 1] : "jpg";
}

