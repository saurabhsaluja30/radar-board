import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, getAuthToken, setAuthToken, setSignedOutHandler } from "@/lib/api";

const Ctx = createContext({});
export const useAuth = () => useContext(Ctx);
const processed = new Set();

function extractSessionId(s) {
  const m = s && s.match(/[?#&]session_id=([^&#]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [membership, setMembership] = useState(null);
  const [loading, setLoading] = useState(true);

  const clear = () => {
    setUser(null);
    setMembership(null);
    setAuthToken(null);
  };

  const refresh = useCallback(async () => {
    try {
      const res = await api("/auth/me");
      setUser(res.user);
      setMembership(res.membership);
    } catch {
      clear();
    }
  }, []);

  const setToken = useCallback(async (t) => {
    setAuthToken(t);
    await refresh();
  }, [refresh]);

  useEffect(() => {
    (async () => {
      try {
        const sid = extractSessionId(window.location.hash) || extractSessionId(window.location.search);
        if (sid && !processed.has(sid)) {
          processed.add(sid);
          window.history.replaceState(null, "", window.location.pathname);
          const res = await api("/auth/session", { method: "POST", body: { session_id: sid }, auth: false });
          await setToken(res.token);
          return;
        }
        if (getAuthToken()) await refresh();
      } finally {
        setLoading(false);
      }
    })();
  }, [refresh, setToken]);

  useEffect(() => {
    setSignedOutHandler((msg) => {
      clear();
      window.alert(msg);
    });
    return () => setSignedOutHandler(null);
  }, []);

  const post = useCallback(async (path, body) => {
    const res = await api(path, { method: "POST", body, auth: false });
    await setToken(res.token);
  }, [setToken]);

  const value = useMemo(() => ({
    user,
    membership,
    loading,
    isMember: !!membership?.is_active,
    refresh,
    setToken,
    login: (email, password) => post("/auth/login", { email, password }),
    adminLogin: (email, password) => post("/auth/admin/login", { email, password }),
    register: (payload) => post("/auth/register", payload),
    googleLogin: () => {
      const redirect = window.location.origin + "/";
      window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirect)}`;
    },
    logout: async () => {
      try {
        await api("/auth/logout", { method: "POST" });
      } catch {}
      clear();
    },
  }), [user, membership, loading, refresh, setToken, post]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
