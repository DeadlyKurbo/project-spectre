import { Router } from "express";
import bcrypt from "bcrypt";
import multer from "multer";
import { v4 as uuidv4 } from "uuid";
import { PutObjectCommand } from "@aws-sdk/client-s3";
import { pool } from "../db.js";
import { getS3Client } from "../lib/s3.js";
import { requireDirectorPassword } from "../middleware/directorAuth.js";

const router = Router();

const allowedMimeTypes = new Set(["image/jpeg", "image/png", "image/webp"]);
const upload = multer({
  storage: multer.memoryStorage(),
  limits: {
    fileSize: 2 * 1024 * 1024,
  },
  fileFilter: (_req, file, cb) => {
    if (!allowedMimeTypes.has(file.mimetype)) {
      return cb(new Error("Only JPG, PNG, and WEBP images are allowed"));
    }

    return cb(null, true);
  },
});

function getBucket() {
  const bucket = process.env.SPACES_BUCKET;

  if (!bucket) {
    throw new Error("SPACES_BUCKET is not configured");
  }

  return bucket;
}

function validatePasswordComplexity(password) {
  if (typeof password !== "string" || password.length < 12) {
    return "Password must be at least 12 characters long";
  }

  const checks = [/[A-Z]/, /[a-z]/, /\d/, /[^A-Za-z0-9]/];
  const valid = checks.every((pattern) => pattern.test(password));

  if (!valid) {
    return "Password must include uppercase, lowercase, number, and symbol";
  }

  return null;
}

function safeFileExtension(mimetype) {
  if (mimetype === "image/jpeg") return "jpg";
  if (mimetype === "image/png") return "png";
  if (mimetype === "image/webp") return "webp";
  return "bin";
}

router.get("/exists", async (_req, res, next) => {
  try {
    const result = await pool.query("SELECT COUNT(*)::int AS count FROM operators");
    return res.json({ exists: result.rows[0].count > 0 });
  } catch (err) {
    return next(err);
  }
});

router.post("/register", requireDirectorPassword, upload.single("image"), async (req, res, next) => {
  try {
    const { username, password, codename, clearanceLevel } = req.body;

    if (!username || !password || !codename || !clearanceLevel) {
      return res.status(400).json({ error: "Missing required fields" });
    }

    const passwordValidationError = validatePasswordComplexity(password);

    if (passwordValidationError) {
      return res.status(400).json({ error: passwordValidationError });
    }

    const hasExisting = await pool.query("SELECT id FROM operators WHERE username = $1", [username]);
    if (hasExisting.rowCount > 0) {
      return res.status(409).json({ error: "Username already exists" });
    }

    const hashed = await bcrypt.hash(password, 12);
    const id = uuidv4();

    let imageUrl = null;

    if (req.file) {
      const extension = safeFileExtension(req.file.mimetype);
      const fileKey = `operators/${id}-${Date.now()}.${extension}`;
      const bucket = getBucket();

      const s3 = getS3Client();

      await s3.send(
        new PutObjectCommand({
          Bucket: bucket,
          Key: fileKey,
          Body: req.file.buffer,
          ContentType: req.file.mimetype,
        }),
      );

      const endpoint = process.env.SPACES_ENDPOINT;
      imageUrl = `${endpoint}/${bucket}/${fileKey}`;
    }

    await pool.query(
      `INSERT INTO operators (id, username, password_hash, codename, clearance_level, profile_image_url)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [id, username, hashed, codename, clearanceLevel, imageUrl],
    );

    await pool.query(
      `INSERT INTO activity_logs (id, admin_id, type, ip_address)
       VALUES ($1, NULL, $2, $3)`,
      [uuidv4(), "operator_registration", req.socket.remoteAddress || "unknown"],
    );

    return res.status(201).json({ success: true, operatorId: id });
  } catch (err) {
    return next(err);
  }
});

export default router;
