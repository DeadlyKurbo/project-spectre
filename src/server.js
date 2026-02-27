import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import { globalLimiter } from "./middleware/rateLimiters.js";
import authRoutes from "./routes/authRoutes.js";
import directorRoutes from "./routes/directorRoutes.js";

dotenv.config();

const app = express();
const port = process.env.PORT || 3000;

app.set("trust proxy", 1);
app.use(cors());
app.use(express.json({ limit: "1mb" }));
app.use(globalLimiter);

app.get("/api/health", (_req, res) => {
  res.json({
    status: "ok",
    service: "project-spectre-security-api",
    serverTime: new Date().toISOString(),
  });
});

app.use("/api", authRoutes);
app.use("/api/director", directorRoutes);

app.use((err, _req, res, _next) => {
  console.error(err);
  res.status(500).json({ error: "Internal server error" });
});

app.listen(port, () => {
  console.log(`Security API listening on port ${port}`);
});
