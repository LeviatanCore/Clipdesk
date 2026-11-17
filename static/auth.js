const TOKEN_KEY = "leviatan_access_token";

function authBase() {
  return (window.__LEVIATAN_AUTH_URL__ || "http://127.0.0.1:8790").replace(/\/$/, "");
}

function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch (_e) {
    return null;
  }
}

function setToken(token) {
  if (!token) {
    clearToken();
    return;
  }
  localStorage.setItem(TOKEN_KEY, token);
}

function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

function callbackUri() {
  return `${window.location.origin}/auth/callback`;
}

function googleLoginUrl() {
  const url = new URL(`${authBase()}/auth/google`);
  url.searchParams.set("app", "clipdesk");
  url.searchParams.set("redirect_uri", callbackUri());
  return url.toString();
}

function devLoginUrl() {
  const url = new URL(`${authBase()}/auth/dev-login`);
  url.searchParams.set("app", "clipdesk");
  url.searchParams.set("redirect_uri", callbackUri());
  return url.toString();
}

async function fetchAuthConfig() {
  try {
    const res = await fetch(`${authBase()}/api/config`);
    if (!res.ok) return { google: false, devLogin: false };
    return await res.json();
  } catch (_e) {
    return { google: false, devLogin: false, offline: true };
  }
}

async function fetchSession() {
  const token = getToken();
  if (!token) return null;
  const res = await fetch(`${authBase()}/api/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 401) {
    clearToken();
    return null;
  }
  if (!res.ok) return null;
  return res.json();
}

function renderAccount(root, { user, entitlements, authConfig }) {
  if (!root) return;
  root.innerHTML = "";

  if (!user) {
    const wrap = document.createElement("div");
    wrap.className = "account";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "account-btn";
    btn.textContent = "Iniciar sesión";
    const menu = document.createElement("div");
    menu.className = "account-menu";
    menu.hidden = true;

    const note = document.createElement("p");
    note.className = "account-note";
    note.textContent = "Cuenta Leviatan (opcional). Los videos quedan solo en tu PC.";
    menu.appendChild(note);

    if (authConfig?.google) {
      const a = document.createElement("a");
      a.className = "account-action primary";
      a.href = googleLoginUrl();
      a.textContent = "Continuar con Google";
      menu.appendChild(a);
    } else {
      const warn = document.createElement("p");
      warn.className = "account-warn";
      warn.textContent = "Google OAuth aún no está configurado en leviatan-auth.";
      menu.appendChild(warn);
    }

    if (authConfig?.devLogin) {
      const a = document.createElement("a");
      a.className = "account-action";
      a.href = devLoginUrl();
      a.textContent = "Dev sign-in";
      menu.appendChild(a);
    }

    if (authConfig?.offline) {
      const err = document.createElement("p");
      err.className = "account-warn";
      err.textContent = "Auth offline (:8790).";
      menu.appendChild(err);
    }

    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
    });
    document.addEventListener("click", () => {
      menu.hidden = true;
    });
    menu.addEventListener("click", (e) => e.stopPropagation());

    wrap.appendChild(btn);
    wrap.appendChild(menu);
    root.appendChild(wrap);
    return;
  }

  const plan = entitlements?.plan || user.plan || "free";
  const wrap = document.createElement("div");
  wrap.className = "account";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "account-chip";
  if (user.picture) {
    const img = document.createElement("img");
    img.src = user.picture;
    img.alt = "";
    img.width = 28;
    img.height = 28;
    btn.appendChild(img);
  }
  const label = document.createElement("span");
  label.className = "account-chip-text";
  label.innerHTML = `<strong>${escapeHtml(user.name || user.email)}</strong><em class="${plan === "pro" ? "pro" : ""}">${escapeHtml(plan)}</em>`;
  btn.appendChild(label);

  const menu = document.createElement("div");
  menu.className = "account-menu";
  menu.hidden = true;
  menu.innerHTML = `
    <p class="account-email">${escapeHtml(user.email)}</p>
    <p class="account-note">Solo prefs y plan en la nube — nunca tus descargas.</p>
  `;
  const out = document.createElement("button");
  out.type = "button";
  out.className = "account-action danger";
  out.textContent = "Cerrar sesión";
  out.addEventListener("click", () => {
    clearToken();
    window.location.reload();
  });
  menu.appendChild(out);

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    menu.hidden = !menu.hidden;
  });
  document.addEventListener("click", () => {
    menu.hidden = true;
  });
  menu.addEventListener("click", (e) => e.stopPropagation());

  wrap.appendChild(btn);
  wrap.appendChild(menu);
  root.appendChild(wrap);
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function bootAccount() {
  const root = document.querySelector("#account-root");
  if (!root) return;
  const [authConfig, session] = await Promise.all([fetchAuthConfig(), fetchSession()]);
  renderAccount(root, {
    user: session?.user || null,
    entitlements: session?.entitlements || null,
    authConfig,
  });
}

window.LeviatanAuth = {
  TOKEN_KEY,
  getToken,
  setToken,
  clearToken,
  googleLoginUrl,
  devLoginUrl,
  fetchAuthConfig,
  fetchSession,
  bootAccount,
};
