/* Handles Supabase email-confirmation redirects.
   Supabase puts the session tokens in the URL fragment (#access_token=...),
   which never reaches the server, so we read it here and exchange it for a
   Django session over a CSRF-protected POST. */
(function () {
  "use strict";

  const status = document.getElementById("callback-status");
  const params = new URLSearchParams(window.location.hash.slice(1));
  // Remove tokens from the address bar / history immediately.
  history.replaceState(null, "", window.location.pathname);

  function fail(message) {
    status.innerHTML = "";
    const p = document.createElement("p");
    p.textContent = message;
    status.appendChild(p);
    document.getElementById("callback-actions").hidden = false;
  }

  if (params.get("error")) {
    fail(params.get("error_description") || "This link is invalid or has expired.");
    return;
  }

  const accessToken = params.get("access_token");
  if (!accessToken) {
    fail("This link is invalid or has expired. Please log in or request a new confirmation email.");
    return;
  }

  const csrf = document.querySelector("[name=csrfmiddlewaretoken]").value;
  fetch(document.body.dataset.sessionUrl, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
    body: JSON.stringify({
      access_token: accessToken,
      refresh_token: params.get("refresh_token"),
      expires_at: params.get("expires_at"),
    }),
  })
    .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
    .then(({ ok, data }) => {
      if (ok && data.redirect) window.location.replace(data.redirect);
      else fail(data.error || "We couldn't sign you in with this link.");
    })
    .catch(() => fail("Network error. Please check your connection and try again."));
})();
