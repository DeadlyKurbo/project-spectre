import { S3Client } from "@aws-sdk/client-s3";

function requireEnv(name) {
  const value = process.env[name];

  if (!value) {
    throw new Error(`${name} is not configured`);
  }

  return value;
}

let s3Client;

export function getS3Client() {
  if (!s3Client) {
    s3Client = new S3Client({
      endpoint: requireEnv("SPACES_ENDPOINT"),
      region: "us-east-1",
      credentials: {
        accessKeyId: requireEnv("SPACES_KEY"),
        secretAccessKey: requireEnv("SPACES_SECRET"),
      },
    });
  }

  return s3Client;
}
