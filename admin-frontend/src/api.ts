export async function moderationFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/moderation${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    }
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}
