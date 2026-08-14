import { S3Client, PutObjectCommand } from "@aws-sdk/client-s3";
import { Upload } from "@aws-sdk/lib-storage";

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

/** Bytes sent so far out of the total, for an upload progress bar. */
export interface UploadProgress {
  loaded: number;
  total: number;
}

// 8 MB parts, four in flight: enough to saturate a home connection without
// holding much of the file in memory at once.
const MULTIPART_PART_SIZE = 8 * 1024 * 1024;
const MULTIPART_CONCURRENCY = 4;

/**
 * Upload a media file, in parts, reporting progress.
 *
 * `uploadToS3` reads the whole file into one PutObject, which is fine for a
 * photo and hopeless for a 90-minute video: it would buffer gigabytes in the
 * tab and give the user no feedback for minutes. `Upload` splits the file and
 * retries individual parts. Files smaller than one part still go up as a
 * single PutObject, so this is not a regression for short clips.
 */
export async function uploadMediaToS3(
  file: File,
  bucket: string,
  key: string,
  onProgress?: (progress: UploadProgress) => void,
): Promise<S3UploadResult> {
  const upload = new Upload({
    client: s3Client,
    params: {
      Bucket: bucket,
      Key: key,
      Body: file,
      ContentType: file.type || "application/octet-stream",
    },
    partSize: MULTIPART_PART_SIZE,
    queueSize: MULTIPART_CONCURRENCY,
    leavePartsOnError: false,
  });

  if (onProgress) {
    upload.on("httpUploadProgress", ({ loaded, total }) => {
      onProgress({ loaded: loaded ?? 0, total: total ?? file.size });
    });
  }

  try {
    await upload.done();
  } catch (err) {
    // A storage-side size cap is the one failure a user can act on, and the
    // raw SDK error doesn't say so.
    const message = err instanceof Error ? err.message : String(err);
    if (/EntityTooLarge|exceeded the maximum|413/i.test(message)) {
      throw new Error(
        `The storage service rejected this file as too large (${(
          file.size /
          1024 /
          1024
        ).toFixed(0)} MB). Its upload size limit needs raising.`,
      );
    }
    throw err;
  }

  const publicEndpoint = import.meta.env.VITE_S3_PUBLIC_BUCKETS_ENDPOINT;
  return { bucket, key, url: `${publicEndpoint}/${bucket}/${key}` };
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

export function getPublicImageUrl(
  bucket: string | undefined | null,
  key: string | undefined | null,
): string | null {
  if (!bucket || !key) return null;
  const publicEndpoint = import.meta.env.VITE_S3_PUBLIC_BUCKETS_ENDPOINT;
  if (!publicEndpoint) return null;
  return `${publicEndpoint}/${bucket}/${key}`;
}

