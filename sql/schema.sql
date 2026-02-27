CREATE TABLE IF NOT EXISTS admins (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL,
  clearance TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sessions (
  id UUID PRIMARY KEY,
  admin_id UUID REFERENCES admins(id) ON DELETE CASCADE,
  ip_address TEXT,
  user_agent TEXT,
  login_time TIMESTAMP DEFAULT NOW(),
  logout_time TIMESTAMP,
  is_suspicious BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS activity_logs (
  id UUID PRIMARY KEY,
  admin_id UUID REFERENCES admins(id) ON DELETE CASCADE,
  type TEXT,
  ip_address TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);
