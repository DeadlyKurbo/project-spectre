import jwt from "jsonwebtoken";

function getSecret() {
  const secret = process.env.JWT_SECRET;

  if (!secret) {
    throw new Error("JWT_SECRET is not configured");
  }

  return secret;
}

export function authenticate(req, res, next) {
  const header = req.headers.authorization;

  if (!header?.startsWith("Bearer ")) {
    return res.status(401).json({ error: "No token" });
  }

  const token = header.split(" ")[1];

  try {
    const decoded = jwt.verify(token, getSecret());
    req.user = decoded;
    return next();
  } catch {
    return res.status(403).json({ error: "Invalid token" });
  }
}

export function requireDirector(req, res, next) {
  if (req.user.role !== "Director") {
    return res.status(403).json({ error: "Director only" });
  }

  return next();
}
