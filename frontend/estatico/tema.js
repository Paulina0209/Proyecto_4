/* Aplica el tema guardado antes de pintar (evita el parpadeo). Sin dependencias; el almacenamiento puede no estar disponible. */
(function () {
  try {
    var t = window.localStorage.getItem("copiloto-tema");
    if (t === "dark" || t === "light") document.documentElement.setAttribute("data-theme", t);
  } catch (e) { /* sin almacenamiento: se usa el tema del sistema */ }
})();
