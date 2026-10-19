"""NFR-03 — Accesibilidad (WCAG 2.1 AA).

Capa reutilizable para que cualquier superficie que genere el sistema (HTML,
PDF) pueda comprobarse contra WCAG 2.1 AA y para que una regresión rompa una
prueba:

    contraste        razones de contraste (1.4.3, 1.4.11) y tokens CSS
    auditoria_html   auditor estático de HTML/CSS por criterio WCAG
    pdf              comprobaciones de accesibilidad de un PDF generado

Ver ``docs/accesibilidad.md`` para el alcance, la declaración de conformidad
y lo que estas comprobaciones automáticas NO pueden decidir.
"""
