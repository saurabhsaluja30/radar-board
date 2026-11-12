export const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const BASE = `${BACKEND_URL}/api`;
const TOKEN_KEY = "jobradar_token";

let authToken = localStorage.getItem(TOKEN_KEY);
let onSignedOutElsewhere = null;

export const getAuthToken = () => authToken;
export function setAuthToken(token) {
  authToken = token;
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}
export const setSignedOutHandler = (fn) => (onSignedOutElsewhere = fn);

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function parse(res, auth) {
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = (data && (data.detail || data.message)) || `Request failed (${res.status})`;
    const msg = typeof detail === "string" ? detail : "Request failed";
    if (res.status === 401 && auth && authToken && msg.includes("another device")) onSignedOutElsewhere?.(msg);
    throw new ApiError(msg, res.status);
  }
  return data;
}

export async function api(path, { method = "GET", body, auth = true, query } = {}) {
  let url = `${BASE}${path}`;
  if (query) {
    const qs = Object.entries(query)
      .filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join("&");
    if (qs) url += `?${qs}`;
  }
  const headers = { "Content-Type": "application/json" };
  if (auth && authToken) headers.Authorization = `Bearer ${authToken}`;
  const res = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined });
  return parse(res, auth);
}

export async function uploadForm(path, file, field = "file") {
  const form = new FormData();
  form.append(field, file, file.name);
  const headers = {};
  if (authToken) headers.Authorization = `Bearer ${authToken}`;
  const res = await fetch(`${BASE}${path}`, { method: "POST", headers, body: form });
  return parse(res, true);
}
