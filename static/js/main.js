/* Apartment Finder — progressive enhancements. Every page works without JS;
   these behaviours only improve the experience. */
(function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  /* ---------- Mobile navigation ---------- */
  function initNav() {
    const nav = $(".nav");
    const toggle = $(".nav-toggle");
    if (!nav || !toggle) return;
    toggle.addEventListener("click", () => {
      const open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
    });
  }

  /* ---------- Dropdown menus ---------- */
  function initDropdowns() {
    $$("[data-dropdown]").forEach((button) => {
      const menu = document.getElementById(button.dataset.dropdown);
      if (!menu) return;
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        const open = menu.classList.toggle("open");
        button.setAttribute("aria-expanded", String(open));
      });
      document.addEventListener("click", (event) => {
        if (!menu.contains(event.target)) {
          menu.classList.remove("open");
          button.setAttribute("aria-expanded", "false");
        }
      });
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") menu.classList.remove("open");
      });
    });
  }

  /* ---------- Flash messages ---------- */
  function initAlerts() {
    $$(".messages .alert").forEach((alert, index) => {
      const close = () => {
        alert.style.transition = "opacity .2s, transform .2s";
        alert.style.opacity = "0";
        alert.style.transform = "translateY(-6px)";
        setTimeout(() => alert.remove(), 200);
      };
      $(".alert-close", alert)?.addEventListener("click", close);
      if (!alert.classList.contains("alert-error")) setTimeout(close, 5000 + index * 600);
    });
  }

  /* ---------- Confirmations & loading states ---------- */
  function initForms() {
    document.addEventListener("submit", (event) => {
      const form = event.target;
      const submitter = event.submitter;
      const message = submitter?.dataset.confirm || form.dataset.confirm;
      if (message && !window.confirm(message)) {
        event.preventDefault();
        return;
      }
      if (form.dataset.noLoading !== undefined || form.method.toLowerCase() === "get") return;
      const button = submitter || $("[type=submit]", form);
      if (button) {
        // Defer so the button's name/value is still submitted.
        setTimeout(() => {
          button.classList.add("is-loading");
          button.setAttribute("aria-busy", "true");
        }, 0);
      }
    });

    // Auto-submit selects (e.g. sort order).
    $$("[data-autosubmit]").forEach((el) => el.addEventListener("change", () => el.form.submit()));
  }

  /* ---------- Password visibility ---------- */
  function initPasswordToggles() {
    $$("input[type=password]").forEach((input) => {
      const wrap = document.createElement("div");
      wrap.className = "password-wrap";
      input.parentNode.insertBefore(wrap, input);
      wrap.appendChild(input);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "password-toggle";
      button.setAttribute("aria-label", "Show password");
      button.innerHTML = eyeIcon(false);
      button.addEventListener("click", () => {
        const show = input.type === "password";
        input.type = show ? "text" : "password";
        button.innerHTML = eyeIcon(show);
        button.setAttribute("aria-label", show ? "Hide password" : "Show password");
      });
      wrap.appendChild(button);
    });
  }

  function eyeIcon(crossed) {
    const base = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">';
    return crossed
      ? base + '<path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.53 13.53 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/><line x1="2" x2="22" y1="2" y2="22"/></svg>'
      : base + '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>';
  }

  /* ---------- Search filters drawer (mobile) ---------- */
  function initFilterDrawer() {
    const panel = $("#filters");
    if (!panel) return;
    $$("[data-filters-toggle]").forEach((btn) =>
      btn.addEventListener("click", () => {
        panel.classList.toggle("open");
        document.body.style.overflow = panel.classList.contains("open") ? "hidden" : "";
      })
    );
  }

  /* ---------- Image upload previews + client-side validation ---------- */
  const MAX_BYTES = 5 * 1024 * 1024;
  const ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp"];

  function initImagePreviews() {
    $$("input[type=file][data-preview]").forEach((input) => {
      const target = document.getElementById(input.dataset.previewTarget || "") || createPreviewGrid(input);
      input.addEventListener("change", () => renderPreviews(input, target));

      const zone = input.closest(".dropzone");
      if (zone) {
        ["dragenter", "dragover"].forEach((type) =>
          zone.addEventListener(type, (e) => { e.preventDefault(); zone.classList.add("dragover"); })
        );
        ["dragleave", "drop"].forEach((type) =>
          zone.addEventListener(type, () => zone.classList.remove("dragover"))
        );
        zone.addEventListener("drop", (e) => {
          e.preventDefault();
          if (e.dataTransfer?.files?.length) {
            input.files = e.dataTransfer.files;
            input.dispatchEvent(new Event("change"));
          }
        });
      }
    });
  }

  function createPreviewGrid(input) {
    const grid = document.createElement("div");
    grid.className = "preview-grid";
    (input.closest(".dropzone") || input).insertAdjacentElement("afterend", grid);
    return grid;
  }

  function renderPreviews(input, grid) {
    grid.innerHTML = "";
    const avatar = document.getElementById("avatar-preview");
    Array.from(input.files).forEach((file) => {
      const problem = !ALLOWED_TYPES.includes(file.type)
        ? "Unsupported type"
        : file.size > MAX_BYTES ? "Larger than 5 MB" : "";
      const figure = document.createElement("figure");
      if (problem) figure.classList.add("invalid");
      const caption = document.createElement("figcaption");
      caption.textContent = problem || file.name;
      if (!problem) {
        const img = document.createElement("img");
        img.alt = "";
        img.src = URL.createObjectURL(file);
        img.onload = () => URL.revokeObjectURL(img.src);
        figure.appendChild(img);
        if (avatar && input.dataset.preview === "avatar") avatar.innerHTML = `<img src="${URL.createObjectURL(file)}" alt="">`;
      }
      figure.appendChild(caption);
      grid.appendChild(figure);
    });
  }

  /* ---------- Toggle hidden inline forms (e.g. "Replace image") ---------- */
  function initToggles() {
    $$("[data-toggle]").forEach((btn) =>
      btn.addEventListener("click", () => document.getElementById(btn.dataset.toggle)?.classList.toggle("open"))
    );
  }

  /* ---------- Gallery lightbox ---------- */
  function initGallery() {
    const lightbox = $("#lightbox");
    const items = $$("[data-gallery-index]");
    if (!lightbox || !items.length) return;

    const images = JSON.parse($("#gallery-data").textContent);
    const img = $(".lightbox-stage img", lightbox);
    const caption = $(".lightbox-caption", lightbox);
    const counter = $(".lightbox-counter", lightbox);
    const thumbs = $(".lightbox-thumbs", lightbox);
    let current = 0;
    let lastFocus = null;

    images.forEach((image, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("aria-label", `Show image ${index + 1}`);
      button.innerHTML = `<img src="${image.url}" alt="" loading="lazy">`;
      button.addEventListener("click", () => show(index));
      thumbs.appendChild(button);
    });

    function show(index) {
      current = (index + images.length) % images.length;
      img.src = images[current].url;
      img.alt = images[current].caption || `Apartment photo ${current + 1}`;
      caption.textContent = images[current].caption || "";
      counter.textContent = `${current + 1} / ${images.length}`;
      $$("button", thumbs).forEach((b, i) => b.classList.toggle("active", i === current));
      thumbs.children[current]?.scrollIntoView({ block: "nearest", inline: "center" });
    }

    function open(index) {
      lastFocus = document.activeElement;
      lightbox.classList.add("open");
      lightbox.setAttribute("aria-hidden", "false");
      document.body.style.overflow = "hidden";
      show(index);
      $(".lightbox-close", lightbox).focus();
    }

    function close() {
      lightbox.classList.remove("open");
      lightbox.setAttribute("aria-hidden", "true");
      document.body.style.overflow = "";
      lastFocus?.focus();
    }

    items.forEach((item) => item.addEventListener("click", () => open(Number(item.dataset.galleryIndex))));
    $$("[data-open-gallery]").forEach((b) => b.addEventListener("click", () => open(0)));
    $(".lightbox-prev", lightbox).addEventListener("click", () => show(current - 1));
    $(".lightbox-next", lightbox).addEventListener("click", () => show(current + 1));
    $(".lightbox-close", lightbox).addEventListener("click", close);
    lightbox.addEventListener("click", (e) => { if (e.target === lightbox || e.target.classList.contains("lightbox-stage")) close(); });
    document.addEventListener("keydown", (e) => {
      if (!lightbox.classList.contains("open")) return;
      if (e.key === "Escape") close();
      if (e.key === "ArrowLeft") show(current - 1);
      if (e.key === "ArrowRight") show(current + 1);
    });

    // Swipe support on touch screens.
    let startX = null;
    lightbox.addEventListener("touchstart", (e) => { startX = e.touches[0].clientX; }, { passive: true });
    lightbox.addEventListener("touchend", (e) => {
      if (startX === null) return;
      const delta = e.changedTouches[0].clientX - startX;
      if (Math.abs(delta) > 50) show(current + (delta < 0 ? 1 : -1));
      startX = null;
    });
  }

  /* ---------- Save / unsave apartments without a page reload ---------- */
  function initSaveButtons() {
    document.addEventListener("submit", async (event) => {
      const form = event.target.closest(".save-form");
      if (!form) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      const button = $(".save-btn", form);
      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: { "X-Requested-With": "fetch" },
          credentials: "same-origin",
        });
        if (!response.ok) throw new Error(String(response.status));
        const { saved } = await response.json();
        button.classList.toggle("saved", saved);
        button.setAttribute("aria-pressed", String(saved));
      } catch (error) {
        form.submit(); // fall back to a normal request
      }
    }, true);
  }

  document.addEventListener("DOMContentLoaded", () => {
    initSaveButtons();
    initNav();
    initDropdowns();
    initAlerts();
    initForms();
    initPasswordToggles();
    initFilterDrawer();
    initImagePreviews();
    initToggles();
    initGallery();
  });
})();
