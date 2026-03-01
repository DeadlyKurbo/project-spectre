export function requireDirectorPassword(req, res, next) {
  const provided = req.headers["x-director-password"];
  const expected = process.env.DIRECTOR_MASTER_PASSWORD;

  if (!expected) {
    return res.status(500).json({ error: "Director password is not configured" });
  }

  if (provided !== expected) {
    return res.status(401).json({ error: "Unauthorized" });
  }

  return next();
}
