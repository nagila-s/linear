export const SESSION_STORAGE_KEY = "linear_session_token";
export const SESSION_COOKIE_NAME = "linear_session";

export function getClientSessionToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(SESSION_STORAGE_KEY);
}

export function setClientSessionToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(SESSION_STORAGE_KEY, token);
}

export function clearClientSessionToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(SESSION_STORAGE_KEY);
}
