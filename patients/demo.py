"""Cliente de consola de la API de pacientes: búsqueda y filtros, y
resumen 360 del paciente.

    uvicorn patients.api:app          # en una terminal
    python -m patients.demo           # en otra

La API carga datos de prueba al arrancar si no hay pacientes, así que
todo se puede probar sin registrar nada.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime
from typing import Optional

import requests

# 127.0.0.1 y no "localhost": en Windows, "localhost" intenta primero IPv6
# (::1) y uvicorn solo escucha en IPv4, así que cada petición tardaría ~2 s.
BASE_URL = "http://127.0.0.1:8000"

# TODO(SEC-01): mientras no haya autenticación real, la demo actúa como
# este oncólogo. La API solo le devuelve SUS pacientes.
ONCOLOGO_DEMO = 1

ETIQUETAS_ESTADO = {
    "en_tratamiento": "En tratamiento",
    "en_seguimiento": "En seguimiento",
    "suspendido": "Suspendido",
    "finalizado": "Finalizado",
}

ETIQUETAS_ALERTA = {
    "interaccion": "Interacción",
    "estudio_pendiente": "Estudio pendiente",
}

CAMPOS_360_LEGIBLES = {
    "diagnostico_principal": "diagnóstico principal",
    "estadio": "estadio",
    "tratamiento_mas_reciente": "tratamiento más reciente",
}

# Máximo de entradas por lista de acceso rápido en el 360: evita
# sobrecargar la pantalla.
MAX_ACCESO_RAPIDO = 3

# El máximo que acepta la API por página.
TAMANO_MAXIMO_PAGINA = 100


# ---------------------------------------------------------------------------
# Entrada por consola
# ---------------------------------------------------------------------------

def pedir(msg: str) -> str:
    return input(msg).strip()


def _pedir_id(msg: str) -> Optional[int]:
    valor = input(msg).strip()
    if not valor:
        return None
    if not valor.isdigit():
        print("  El id debe ser un número.")
        return None
    return int(valor)


def _pedir_fecha(msg: str) -> Optional[str]:
    while True:
        valor = input(msg).strip()
        if not valor:
            return None
        try:
            datetime.strptime(valor, "%Y-%m-%d")
            return valor
        except ValueError:
            print("  Fecha inválida. Use el formato YYYY-MM-DD.")


def _elegir_estado() -> Optional[str]:
    print("Estado del tratamiento:")
    print("  0. (cualquiera: quitar el filtro)")
    opciones = list(ETIQUETAS_ESTADO.items())
    for i, (_, etiqueta) in enumerate(opciones, 1):
        print(f"  {i}. {etiqueta}")

    while True:
        valor = input("Opción: ").strip() or "0"
        if valor.isdigit() and 0 <= int(valor) <= len(opciones):
            return opciones[int(valor) - 1][0] if int(valor) else None
        print("  Opción inválida, intente de nuevo.")


def _recortar(texto: str, ancho: int) -> str:
    return texto if len(texto) <= ancho else texto[: ancho - 1] + "…"


# ---------------------------------------------------------------------------
# Llamadas a la API
# ---------------------------------------------------------------------------

def _llamar(metodo: str, ruta: str, params: Optional[dict] = None):
    """Petición a la API como ONCOLOGO_DEMO; None si no hay conexión (ya
    avisa en pantalla)."""
    try:
        return requests.request(
            metodo,
            f"{BASE_URL}{ruta}",
            params={"oncologo_id": ONCOLOGO_DEMO, **(params or {})},
            timeout=10,
        )
    except requests.ConnectionError:
        print("\n✘ No se pudo conectar con la API.")
        print(f"  Verifique que el backend esté corriendo en {BASE_URL}")
        return None


def _mostrar_errores_api(response) -> None:
    try:
        detalle = response.json().get("detail")
    except ValueError:
        detalle = response.text

    if isinstance(detalle, dict) and "errores" in detalle:
        for error in detalle["errores"]:
            print(f"  ✘ {error['campo']}: {error['mensaje']}")
    else:
        print(f"  ✘ ({response.status_code}) {detalle}")


def _datos_o_error(response):
    """El JSON de la respuesta, o None (mostrando el error) si falló o no
    hubo conexión."""
    if response is None:
        return None
    if response.status_code != 200:
        _mostrar_errores_api(response)
        return None
    return response.json()


# ---------------------------------------------------------------------------
# Mis pacientes
# ---------------------------------------------------------------------------

def _edad(fecha_nacimiento: Optional[str]) -> str:
    if not fecha_nacimiento:
        return "—"
    nacimiento = date.fromisoformat(fecha_nacimiento)
    hoy = date.today()
    return str(hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day)))


def flujo_listar_pacientes() -> None:
    """Todos los pacientes del oncólogo (solo los suyos)."""
    print("\n=== Mis pacientes ===")

    pacientes = _datos_o_error(_llamar("GET", "/pacientes"))
    if pacientes is None:
        return
    if not pacientes:
        print("\n  Aún no tienes pacientes registrados.")
        return

    print(f"\n  {len(pacientes)} paciente(s), más recientes primero\n")
    print(f"  {'ID':>4}  {'Nombre':<24} {'Identificación':<26} {'Edad':>4}")
    print(f"  {'─' * 4}  {'─' * 24} {'─' * 26} {'─' * 4}")
    for p in pacientes:
        identificacion = f"{p['tipo_identificacion']} {p['numero_identificacion']}"
        print(
            f"  {p['id']:>4}  {_recortar(p['nombre_completo'], 24):<24} "
            f"{_recortar(identificacion, 26):<26} {_edad(p['fecha_nacimiento']):>4}"
        )

    _ofrecer_abrir_360()


# ---------------------------------------------------------------------------
# Búsqueda y filtros
# ---------------------------------------------------------------------------

def buscar_api(**filtros) -> Optional[dict]:
    params = {k: v for k, v in filtros.items() if v not in (None, "")}
    return _datos_o_error(_llamar("GET", "/pacientes/buscar", params))


def mostrar_resultados(resultado: dict) -> None:
    if resultado["filtros_aplicados"]:
        chips = " · ".join(f"{k}={v}" for k, v in resultado["filtros_aplicados"].items())
        print(f"  Filtros: {chips}")

    # Con cero resultados se muestra el mensaje de la API, nunca una tabla
    # vacía sin explicación.
    if resultado["total"] == 0:
        print(f"\n  ⓘ {resultado['mensaje']}")
        return

    print(
        f"\n  {resultado['total']} paciente(s) · "
        f"página {resultado['pagina']} de {resultado['total_paginas']}\n"
    )
    print(f"  {'ID':>4}  {'Nombre':<24} {'Diagnóstico':<34} {'Estado':<15} Últ. consulta")
    print(f"  {'─' * 4}  {'─' * 24} {'─' * 34} {'─' * 15} {'─' * 13}")

    for p in resultado["items"]:
        diagnostico = p["diagnosticos"][0] if p["diagnosticos"] else "—"
        estado = ETIQUETAS_ESTADO.get(p["estado_tratamiento"], "—")
        print(
            f"  {p['id']:>4}  {_recortar(p['nombre_completo'], 24):<24} "
            f"{_recortar(diagnostico, 34):<34} {estado:<15} "
            f"{p['fecha_ultima_consulta'] or '—'}"
        )


def _ofrecer_abrir_360() -> None:
    """Abrir la historia de un paciente desde una lista de resultados."""
    while True:
        paciente_id = _pedir_id("\nId para abrir su resumen 360 (Enter para volver): ")
        if paciente_id is None:
            return
        _abrir_y_mostrar_360(paciente_id)


def busqueda_por_nombre() -> None:
    """No hace falta el nombre exacto: basta una parte del nombre o del
    apellido, sin tildes ni mayúsculas y en cualquier orden."""
    print("\n=== Buscar paciente por nombre ===")
    print("Puede escribir solo una parte del nombre o del apellido (sin tildes ni mayúsculas).")

    while True:
        texto = pedir("\nNombre (Enter para volver): ")
        if not texto:
            return

        resultado = buscar_api(nombre=texto, tamano_pagina=TAMANO_MAXIMO_PAGINA)
        if resultado is None:
            return
        print()
        mostrar_resultados(resultado)

        if resultado["total"]:
            paciente_id = _pedir_id("\nId para abrir su resumen 360 (Enter para otra búsqueda): ")
            if paciente_id is not None:
                _abrir_y_mostrar_360(paciente_id)


# (clave del parámetro de la API, etiqueta para el menú)
_FILTROS = (
    ("nombre", "Nombre (o parte del nombre)"),
    ("diagnostico", "Diagnóstico (o parte del diagnóstico)"),
    ("estado_tratamiento", "Estado del tratamiento"),
    ("ultima_consulta_desde", "Última consulta desde"),
    ("ultima_consulta_hasta", "Última consulta hasta"),
)


def _pedir_valor_filtro(clave: str) -> Optional[str]:
    """Nuevo valor para un filtro; None (Enter) lo quita."""
    if clave == "estado_tratamiento":
        return _elegir_estado()
    if clave.startswith("ultima_consulta"):
        return _pedir_fecha("Fecha (YYYY-MM-DD, Enter para quitar el filtro): ")
    return pedir("Texto a buscar (Enter para quitar el filtro): ") or None


def _mostrar_valor_filtro(clave: str, valor: str) -> str:
    return ETIQUETAS_ESTADO.get(valor, valor) if clave == "estado_tratamiento" else valor


def _buscar_paginado(filtros: dict) -> None:
    pagina = 1
    while True:
        resultado = buscar_api(**filtros, pagina=pagina, tamano_pagina=5)
        if resultado is None:
            return

        print()
        mostrar_resultados(resultado)

        if resultado["total_paginas"] <= 1:
            break

        opcion = pedir("\n[s]iguiente · [a]nterior · Enter para seguir: ").lower()
        if opcion == "s" and pagina < resultado["total_paginas"]:
            pagina += 1
        elif opcion == "a" and pagina > 1:
            pagina -= 1
        elif not opcion:
            break

    if resultado["total"]:
        paciente_id = _pedir_id("\nId para abrir su resumen 360 (Enter para volver a los filtros): ")
        if paciente_id is not None:
            _abrir_y_mostrar_360(paciente_id)


def busqueda_con_filtros() -> None:
    """Se activan solo los filtros que se quieran (uno o varios) y se busca
    cuando se quiera; los filtros se mantienen para ir afinando."""
    filtros: dict[str, str] = {}

    while True:
        print("\n=== Buscar con filtros ===")
        print("Active uno o varios filtros y luego elija B para buscar.\n")
        for i, (clave, etiqueta) in enumerate(_FILTROS, 1):
            valor = filtros.get(clave)
            activo = f"  → {_mostrar_valor_filtro(clave, valor)}" if valor else ""
            print(f"  {i}. {etiqueta}{activo}")
        print("\n  B. Buscar con los filtros activos" + ("" if filtros else " (sin filtros: todos)"))
        print("  L. Limpiar filtros")
        print("  0. Volver")

        opcion = input("\nOpción: ").strip().lower()
        if opcion in ("0", ""):
            return
        if opcion == "b":
            _buscar_paginado(filtros)
        elif opcion == "l":
            filtros.clear()
        elif opcion.isdigit() and 1 <= int(opcion) <= len(_FILTROS):
            clave = _FILTROS[int(opcion) - 1][0]
            valor = _pedir_valor_filtro(clave)
            if valor:
                filtros[clave] = valor
            else:
                filtros.pop(clave, None)
        else:
            print("  Opción inválida, intente de nuevo.")


# ---------------------------------------------------------------------------
# Resumen 360
# ---------------------------------------------------------------------------

def mostrar_resumen_360(d: dict) -> None:
    linea = "═" * 72
    sin_dato = "⚠ sin registrar"

    print(f"\n{linea}")
    print(f"  RESUMEN 360 · {d['nombre']}   (id {d['paciente_id']})")
    print(linea)

    # El hueco se señala arriba, antes que nada.
    if d["informacion_incompleta"]:
        faltan = ", ".join(CAMPOS_360_LEGIBLES.get(c, c) for c in d["campos_faltantes"])
        print(f"  ⚠ INFORMACIÓN FALTANTE: {faltan}")
        print(f"  {'─' * 70}")

    # Lo esencial, en la misma pantalla.
    t = d["tratamiento_mas_reciente"]
    if t:
        partes = [t["regimen"], ETIQUETAS_ESTADO.get(t["estado"], t["estado"])]
        if t["fecha_inicio"]:
            partes.append(f"desde {t['fecha_inicio']}")
        tratamiento = " · ".join(p for p in partes if p)
    else:
        tratamiento = sin_dato
    print(f"  Diagnóstico   {d['diagnostico_principal'] or sin_dato}")
    print(f"  Estadio       {d['estadio'] or sin_dato}")
    print(f"  Tratamiento   {tratamiento}")

    alertas = d["alertas_activas"]
    print(f"\n  ALERTAS ACTIVAS ({len(alertas)})")
    if not alertas:
        print("    Sin alertas activas.")
    for a in alertas:
        tipo = ETIQUETAS_ALERTA.get(a["tipo"], a["tipo"])
        print(f"    [{a['severidad'].upper():<5}] {tipo} · {a['fecha']}")
        print(f"            {a['descripcion']}")

    print("\n  ACCESO RÁPIDO")
    for etiqueta, clave in (
        ("Laboratorios", "labs_recientes"),
        ("Imágenes", "imagenes_recientes"),
        ("Notas", "notas_recientes"),
    ):
        entradas = d[clave]
        print(f"    {etiqueta} ({len(entradas)})")
        if not entradas:
            print("      —")
        for e in entradas[:MAX_ACCESO_RAPIDO]:
            titulo = f"{e['titulo']}: " if e.get("titulo") else ""
            print(f"      {e['fecha']}  {titulo}{e['resumen']}")
        if len(entradas) > MAX_ACCESO_RAPIDO:
            print(f"      … y {len(entradas) - MAX_ACCESO_RAPIDO} más")

    print(linea)


def _abrir_y_mostrar_360(paciente_id: int) -> bool:
    resumen = _datos_o_error(_llamar("GET", f"/pacientes/{paciente_id}/resumen-360"))
    if resumen is None:
        return False
    mostrar_resumen_360(resumen)
    return True


def flujo_resumen_360() -> None:
    print("\n=== Resumen 360 del paciente ===")
    print(
        "Datos de prueba: 1 = historia completa · 2 = sin diagnóstico, estadio ni "
        "tratamiento · 7 = sin estadio"
    )
    print("(También puede abrirse desde la lista de pacientes o los resultados de búsqueda.)")
    _ofrecer_abrir_360()


# ---------------------------------------------------------------------------
# Menú principal
# ---------------------------------------------------------------------------

OPCIONES_MENU = {
    "1": ("Ver todos mis pacientes", flujo_listar_pacientes),
    "2": ("Buscar paciente por nombre", busqueda_por_nombre),
    "3": ("Buscar con filtros (uno o varios)", busqueda_con_filtros),
    "4": ("Abrir resumen 360 de un paciente", flujo_resumen_360),
}


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    if os.name == "nt":
        os.system("")  # activa las secuencias ANSI en la consola de Windows

    while True:
        print("\n=== Copiloto oncológico · Pacientes (demo) ===")
        print(f"API: {BASE_URL} · Oncólogo autenticado (demo): {ONCOLOGO_DEMO}\n")
        for clave, (etiqueta, _) in OPCIONES_MENU.items():
            print(f"  {clave}. {etiqueta}")
        print("  0. Salir")

        opcion = input("\nOpción: ").strip()
        if opcion == "0":
            return
        if opcion not in OPCIONES_MENU:
            print("  Opción inválida, intente de nuevo.")
            continue

        try:
            OPCIONES_MENU[opcion][1]()
        except (KeyboardInterrupt, EOFError):
            print("\n  (cancelado)")


if __name__ == "__main__":
    main()
