import { Router } from "express";
import bcrypt from "bcrypt";
import jwt from "jsonwebtoken";
import { v4 as uuidv4 } from "uuid";
import { pool } from "../db.js";
import { authenticate } from "../middleware/auth.js";
import { loginLimiter } from "../middleware/rateLimiters.js";

const router = Router();
function getJwtSecret() {
  const secret = process.env.JWT_SECRET;

  if (!secret) {
    throw new Error("JWT_SECRET is not configured");
  }

  return secret;
}

// Compared against when the email is unknown, so a miss takes as long as a
// wrong password and response times don't reveal which admin emails exist.
const DUMMY_PASSWORD_HASH = bcrypt.hashSync("not-a-real-password", 10);

function resolveClientIp(req) {
  // req.ip honours "trust proxy" (see server.js); the first X-Forwarded-For
  // entry is whatever the client chose to send.
  return req.ip || req.socket.remoteAddress || "unknown";
}

router.post("/login", loginLimiter, async (req, res, next) => {
  try {
    const { email, password } = req.body ?? {};

    if (typeof email !== "string" || typeof password !== "string" || !email || !password) {
      return res.status(400).json({ error: "Email and password are required" });
    }
    if (email.length > 254 || password.length > 1024) {
      return res.status(400).json({ error: "Invalid credentials" });
    }

    const result = await pool.query("SELECT * FROM admins WHERE email = $1", [email]);
    const admin = result.rows[0];

    const valid = await bcrypt.compare(password, admin ? admin.password_hash : DUMMY_PASSWORD_HASH);

    if (!admin || !valid) {
      return res.status(401).json({ error: "Invalid credentials" });
    }

    const ip = resolveClientIp(req);
    const userAgent = req.headers["user-agent"] || "unknown";

    const ipCheck = await pool.query(
      "SELECT DISTINCT ip_address FROM sessions WHERE admin_id = $1",
      [admin.id],
    );

    const knownIPs = ipCheck.rows.map((r) => r.ip_address);
    const isSuspicious = !knownIPs.includes(ip);

    const sessionId = uuidv4();

    await pool.query(
      `INSERT INTO sessions
       (id, admin_id, ip_address, user_agent, is_suspicious)
       VALUES ($1, $2, $3, $4, $5)`,
      [sessionId, admin.id, ip, userAgent, isSuspicious],
    );

    await pool.query(
      `INSERT INTO activity_logs (id, admin_id, type, ip_address)
       VALUES ($1, $2, $3, $4)`,
      [uuidv4(), admin.id, "login", ip],
    );

    const token = jwt.sign(
      {
        id: admin.id,
        role: admin.role,
        sessionId,
      },
      getJwtSecret(),
      { expiresIn: "8h", algorithm: "HS256" },
    );

    return res.json({ token, suspicious: isSuspicious });
  } catch (err) {
    return next(err);
  }
});

router.post("/logout", authenticate, async (req, res, next) => {
  try {
    await pool.query("UPDATE sessions SET logout_time = NOW() WHERE id = $1", [req.user.sessionId]);

    await pool.query(
      `INSERT INTO activity_logs (id, admin_id, type, ip_address)
       VALUES ($1, $2, $3, $4)`,
      [uuidv4(), req.user.id, "logout", resolveClientIp(req)],
    );

    return res.json({ success: true });
  } catch (err) {
    return next(err);
  }
});

export default router;
