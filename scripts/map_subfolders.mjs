import fs from 'fs';
import { google } from 'googleapis';
import dotenv from 'dotenv';

// Load environment variables from a .env file when present
dotenv.config();

// Authenticate using service account credentials provided as a base64 string
const auth = new google.auth.GoogleAuth({
  credentials: JSON.parse(
    Buffer.from(process.env.GDRIVE_CREDS_BASE64 || '', 'base64').toString('utf-8') || '{}'
  ),
  scopes: ['https://www.googleapis.com/auth/drive.metadata.readonly'],
});

const drive = google.drive({ version: 'v3', auth });

export async function mapSubfolders() {
  const folderId = process.env.GDRIVE_FOLDER_ID;

  const res = await drive.files.list({
    q: `'${folderId}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false`,
    fields: 'files(id, name)',
  });

  const map = {};
  res.data.files.forEach((f) => {
    map[f.name.toLowerCase()] = f.id;
  });

  fs.writeFileSync('./folder_map.json', JSON.stringify(map, null, 2));
  console.log('\u2705 folder_map.json created:');
  console.log(map);
}

// Allow running as a standalone script
if (import.meta.url === `file://${process.argv[1]}`) {
  mapSubfolders().catch((err) => {
    console.error('Failed to map subfolders:', err.message);
    process.exit(1);
  });
}
