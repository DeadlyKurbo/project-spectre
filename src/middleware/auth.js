import jwt from "jsonwebtoken";
import { pool } from "../db.js";

function getSecret() {
  const secret = process.env.JWT_SECRET;

  if (!secret) {
    throw new Error("JWT_SECRET is not configured");
  }

  return secret;
}

export async function authenticate(req, res, next) {
  const header = req.headers.authorization;

  if (!header?.startsWith("Bearer ")) {
    return res.status(401).json({ error: "No token" });
  }

  const token = header.split(" ")[1];

  let decoded;
  try {
    decoded = jwt.verify(token, getSecret(), { algorithms: ["HS256"] });
  } catch {
    return res.status(403).json({ error: "Invalid token" });
  }

  try {
    // A token outlives its session unless we check: logging out (or an admin
    // being deleted) must cut it off.
    const session = await pool.query(
      `SELECT s.logout_time, a.role
         FROM sessions s
         JOIN admins a ON a.id = s.admin_id
        WHERE s.id = $1 AND s.admin_id = $2`,
      [decoded.sessionId, decoded.id],
    );
    const row = session.rows[0];
    if (!row || row.logout_time) {
      return res.status(401).json({ error: "Session ended" });
    }
    req.user = { ...decoded, role: row.role };
    return next();
  } catch (err) {
    return next(err);
  }
}

export function requireDirector(req, res, next) {
  if (req.user.role !== "Director") {
    return res.status(403).json({ error: "Director only" });
  }

  return next();
}
