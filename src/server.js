import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import { globalLimiter } from "./middleware/rateLimiters.js";
import authRoutes from "./routes/authRoutes.js";
import directorRoutes from "./routes/directorRoutes.js";
import operatorRoutes from "./routes/operatorRoutes.js";

dotenv.config();

const app = express();
const port = process.env.PORT || 3000;

const corsOrigin = process.env.CORS_ORIGIN || "https://yourdomain.com";

app.set("trust proxy", 1);
app.use(
  cors({
    origin: corsOrigin,
    credentials: true,
  }),
);
app.use(express.json({ limit: "1mb" }));
app.use(express.static("static"));
app.use(globalLimiter);

app.get("/api/health", (_req, res) => {
  res.json({
    status: "ok",
    service: "project-spectre-security-api",
    serverTime: new Date().toISOString(),
  });
});

app.get("/director/register", (_req, res) => {
  res.sendFile("director/register.html", { root: "static" });
});

app.get("/director/security", (_req, res) => {
  res.sendFile("director/security.html", { root: "static" });
});

app.use("/api", authRoutes);
app.use("/api/director", directorRoutes);
app.use("/api/operator", operatorRoutes);

app.use((err, _req, res, _next) => {
  console.error(err);

  if (err?.name === "MulterError") {
    return res.status(400).json({ error: err.message });
  }

  if (err?.message?.includes("Only JPG, PNG, and WEBP images are allowed")) {
    return res.status(400).json({ error: err.message });
  }

  return res.status(500).json({ error: "Internal server error" });
});

app.listen(port, () => {
  console.log(`Security API listening on port ${port}`);
});
