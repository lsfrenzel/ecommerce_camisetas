/* JS global da loja — pequeno e sem dependências além de Alpine/HTMX. */
(function () {
  "use strict";
  var root = document.documentElement;
  var KEY = "theme";

  function systemPrefersDark() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }
  function stored() {
    try { return localStorage.getItem(KEY) || "system"; } catch (e) { return "system"; }
  }
  function apply(pref, animate) {
    var dark = pref === "dark" || (pref === "system" && systemPrefersDark());
    if (animate) {
      root.classList.add("theme-transition");
      window.setTimeout(function () { root.classList.remove("theme-transition"); }, 400);
    }
    root.classList.toggle("dark", dark);
    root.dataset.themePref = pref;
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", dark ? "#101010" : "#F7F5F0");
    document.querySelectorAll("[data-theme-label]").forEach(function (el) {
      el.textContent = dark ? "Tema claro" : "Tema escuro";
    });
    document.querySelectorAll("[data-theme-toggle]").forEach(function (el) {
      el.setAttribute("aria-pressed", dark ? "true" : "false");
    });
  }
  window.StoreTheme = {
    toggle: function () {
      var next = root.classList.contains("dark") ? "light" : "dark";
      try { localStorage.setItem(KEY, next); } catch (e) {}
      apply(next, true);
    },
    set: function (pref) {
      try { localStorage.setItem(KEY, pref); } catch (e) {}
      apply(pref, true);
    },
  };
  apply(stored(), false);
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
      if (stored() === "system") apply("system", true);
    });
  }
  document.addEventListener("click", function (ev) {
    var t = ev.target.closest("[data-theme-toggle]");
    if (t) { ev.preventDefault(); window.StoreTheme.toggle(); }
  });

  // CSRF para requisições HTMX.
  document.addEventListener("htmx:configRequest", function (ev) {
    var token = document.querySelector('meta[name="csrf-token"]');
    if (token) ev.detail.headers["X-CSRFToken"] = token.getAttribute("content");
  });

  // Atualiza o contador do carrinho após ações HTMX.
  document.addEventListener("cart:updated", function (ev) {
    var count = ev.detail && typeof ev.detail.count !== "undefined" ? ev.detail.count : null;
    if (count === null) return;
    document.querySelectorAll("[data-cart-count]").forEach(function (el) {
      el.textContent = count;
      el.classList.toggle("hidden", Number(count) === 0);
      el.classList.remove("animate-rise"); void el.offsetWidth; el.classList.add("animate-rise");
    });
  });

  // Auto-fecha mensagens.
  window.setTimeout(function () {
    document.querySelectorAll("[data-autodismiss]").forEach(function (el) {
      el.style.transition = "opacity .4s"; el.style.opacity = "0";
      window.setTimeout(function () { el.remove(); }, 450);
    });
  }, 6000);

  // Máscaras simples (CEP, CPF, telefone).
  function mask(value, pattern) {
    var d = value.replace(/\D/g, ""), out = "", i = 0;
    for (var p = 0; p < pattern.length && i < d.length; p++) {
      out += pattern[p] === "9" ? d[i++] : pattern[p];
    }
    return out;
  }
  document.addEventListener("input", function (ev) {
    var el = ev.target;
    if (!el.dataset || !el.dataset.mask) return;
    var m = el.dataset.mask;
    if (m === "phone") m = el.value.replace(/\D/g, "").length > 10 ? "(99) 99999-9999" : "(99) 9999-99999";
    el.value = mask(el.value, m);
  });

  // Autopreenchimento de endereço via ViaCEP (somente leitura de dados públicos).
  window.lookupCep = function (input) {
    var cep = (input.value || "").replace(/\D/g, "");
    if (cep.length !== 8) return;
    var form = input.form;
    fetch("https://viacep.com.br/ws/" + cep + "/json/")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || d.erro || !form) return;
        var set = function (name, val) {
          var f = form.querySelector('[name$="' + name + '"]');
          if (f && val && !f.value) { f.value = val; f.dispatchEvent(new Event("change")); }
        };
        set("street", d.logradouro); set("neighborhood", d.bairro); set("city", d.localidade); set("state", d.uf);
        var num = form.querySelector('[name$="number"]'); if (num) num.focus();
      })
      .catch(function () {});
  };
})();
