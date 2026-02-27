import { Router } from "express";
import { pool } from "../db.js";
import { authenticate, requireDirector } from "../middleware/auth.js";

const router = Router();

router.get("/suspicious", authenticate, requireDirector, async (req, res, next) => {
  try {
    const result = await pool.query(
      `SELECT
         s.*,
         a.name,
         EXTRACT(EPOCH FROM (COALESCE(s.logout_time, NOW()) - s.login_time)) AS session_duration_seconds
       FROM sessions s
       JOIN admins a ON a.id = s.admin_id
       WHERE s.is_suspicious = TRUE
       ORDER BY s.login_time DESC`,
    );

    return res.json(result.rows);
  } catch (err) {
    return next(err);
  }
});

export default router;
