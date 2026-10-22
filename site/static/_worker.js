const COOKIE_SESSION = "gl_session";
const COOKIE_STATE = "gl_oauth_state";

function parseCookies(req) {
  const raw = req.headers.get("Cookie") || "";
  const out = {};
  for (const part of raw.split(";")) {
    const idx = part.indexOf("=");
    if (idx > 0) out[part.slice(0, idx).trim()] = decodeURIComponent(part.slice(idx + 1).trim());
  }
  return out;
}

async function hmacHex(secret, msg) {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(msg));
  return Array.from(new Uint8Array(sig)).map(b => b.toString(16).padStart(2, "0")).join("");
}

async function makeSessionToken(secret, sub) {
  const sig = await hmacHex(secret, sub);
  return `${sub}.${sig}`;
}

async function verifySessionToken(secret, token) {
  if (!token || !token.includes(".")) return null;
  const idx = token.lastIndexOf(".");
  const sub = token.slice(0, idx);
  const sig = token.slice(idx + 1);
  const expected = await hmacHex(secret, sub);
  return sig === expected ? sub : null;
}

function redirect(loc, headers = []) {
  const h = new Headers({ Location: loc, "Cache-Control": "no-store" });
  for (const [k, v] of headers) h.append(k, v);
  return new Response(null, { status: 302, headers: h });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    const secret = env.SESSION_SECRET || env.GOOGLE_CLIENT_SECRET || "goallit-fallback-secret";

    if (path === "/api/auth/google" && request.method === "GET") {
      const nl = url.searchParams.get("newsletter") === "1" ? "1" : "0";
      if (!env.GOOGLE_CLIENT_ID) {
        return redirect("/signup/?status=pending_config");
      }
      const rand = crypto.randomUUID().replace(/-/g, "");
      const redirectUri = `${url.origin}/api/auth/callback/google`;
      const authUrl = new URL("https://accounts.google.com/o/oauth2/v2/auth");
      authUrl.searchParams.set("client_id", env.GOOGLE_CLIENT_ID);
      authUrl.searchParams.set("redirect_uri", redirectUri);
      authUrl.searchParams.set("response_type", "code");
      authUrl.searchParams.set("scope", "openid email profile");
      authUrl.searchParams.set("state", rand);
      authUrl.searchParams.set("prompt", "select_account");
      return redirect(authUrl.toString(), [
        ["Set-Cookie", `${COOKIE_STATE}=${rand}.${nl}; Path=/api/auth; HttpOnly; Secure; SameSite=Lax; Max-Age=600`]
      ]);
    }

    if (path === "/api/auth/callback/google" && request.method === "GET") {
      const code = url.searchParams.get("code");
      const state = url.searchParams.get("state");
      const cookies = parseCookies(request);
      const saved = cookies[COOKIE_STATE] || "";
      const [savedState, savedNl] = saved.split(".");
      if (!code || !state || !savedState || state !== savedState) {
        return redirect("/signup/?status=invalid_state");
      }
      const nl = savedNl === "0" ? 0 : 1;
      const redirectUri = `${url.origin}/api/auth/callback/google`;
      const tokenRes = await fetch("https://oauth2.googleapis.com/token", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          code,
          client_id: env.GOOGLE_CLIENT_ID || "",
          client_secret: env.GOOGLE_CLIENT_SECRET || "",
          redirect_uri: redirectUri,
          grant_type: "authorization_code"
        })
      });
      if (!tokenRes.ok) return redirect("/signup/?status=token_error");
      const tokens = await tokenRes.json();
      const userRes = await fetch("https://openidconnect.googleapis.com/v1/userinfo", {
        headers: { Authorization: `Bearer ${tokens.access_token}` }
      });
      if (!userRes.ok) return redirect("/signup/?status=userinfo_error");
      const user = await userRes.json();
      const sub = String(user.sub || "");
      const email = String(user.email || "");
      const name = String(user.name || "");
      if (!sub || !email) return redirect("/signup/?status=missing_email");

      if (env.DB) {
        await env.DB.prepare(
          `INSERT INTO members (google_sub, email, name, newsletter_opt_in, created_at)
           VALUES (?1, ?2, ?3, ?4, ?5)
           ON CONFLICT(google_sub) DO UPDATE SET
             email = excluded.email,
             name = excluded.name,
             newsletter_opt_in = excluded.newsletter_opt_in`
        ).bind(sub, email, name, nl, new Date().toISOString()).run();
      }
      const sess = await makeSessionToken(secret, sub);
      return redirect(`/signup/?welcome=1&newsletter=${nl}`, [
        ["Set-Cookie", `${COOKIE_STATE}=; Path=/api/auth; HttpOnly; Secure; SameSite=Lax; Max-Age=0`],
        ["Set-Cookie", `${COOKIE_SESSION}=${encodeURIComponent(sess)}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000`]
      ]);
    }

    if (path === "/api/auth/me" && request.method === "GET") {
      const cookies = parseCookies(request);
      const sub = await verifySessionToken(secret, cookies[COOKIE_SESSION]);
      if (!sub || !env.DB) {
        return new Response(JSON.stringify({ ok: true, member: null }), {
          headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" }
        });
      }
      const row = await env.DB.prepare(
        "SELECT email, name, newsletter_opt_in, created_at FROM members WHERE google_sub = ?1"
      ).bind(sub).first();
      return new Response(JSON.stringify({ ok: true, member: row || null }), {
        headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" }
      });
    }

    if (path === "/api/auth/newsletter" && request.method === "POST") {
      const cookies = parseCookies(request);
      const sub = await verifySessionToken(secret, cookies[COOKIE_SESSION]);
      if (!sub || !env.DB) return redirect("/signup/");
      const formData = await request.formData();
      const nl = formData.get("newsletter") === "1" ? 1 : 0;
      await env.DB.prepare("UPDATE members SET newsletter_opt_in = ?1 WHERE google_sub = ?2").bind(nl, sub).run();
      return redirect(`/signup/?welcome=1&newsletter=${nl}`);
    }

    if (path === "/api/auth/logout") {
      return redirect("/signup/?logged_out=1", [
        ["Set-Cookie", `${COOKIE_SESSION}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`]
      ]);
    }

    return new Response("Not Found", { status: 404 });
  }
};
