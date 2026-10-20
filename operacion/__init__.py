"""Operación del copiloto: rendimiento (NFR-01), disponibilidad (NFR-02) y
escalabilidad horizontal (NFR-05).

    - ``sqlite``: conexiones aptas para peticiones concurrentes (WAL).
    - ``latencia``: mide cada petición y la compara con los objetivos de NFR-01.
    - ``presupuesto``: la nota de IA-02 llega en menos de 10 s aunque el modelo tarde.
    - ``carga``: prueba de carga contra la API, con varios procesos si se pide.
    - ``salud``: sondas ``/salud/vivo`` y ``/salud/listo`` para el balanceador.
    - ``monitor``: mide la disponibilidad real contra el SLA del 99,5 %.

Ver docs/rendimiento.md, docs/disponibilidad.md y docs/escalabilidad.md.
"""
