"""Cliente de consola de la API de pacientes: búsqueda y filtros, resumen
360 del paciente, laboratorios (HC-02) y biopsias y biomarcadores (HC-04).

    uvicorn patients.api:app          # en una terminal
    python -m patients.demo           # en otra

Los pacientes son los registrados y los importados de cBioPortal (ver
docs/cbioportal.md). Los laboratorios, biopsias y biomarcadores se guardan
en el expediente clínico, que es lo que también lee TX-01.
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
    "laboratorio_critico": "Laboratorio crítico",
    "conflicto_laboratorio": "Conflicto de laboratorio",
    "biomarcador_pendiente": "Biomarcador por confirmar",
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

def _llamar(metodo: str, ruta: str, params: Optional[dict] = None, json: Optional[dict] = None):
    """Petición a la API como ONCOLOGO_DEMO; None si no hay conexión (ya
    avisa en pantalla)."""
    try:
        return requests.request(
            metodo,
            f"{BASE_URL}{ruta}",
            params={"oncologo_id": ONCOLOGO_DEMO, **(params or {})},
            json=json,
            timeout=30,
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
    if response.status_code not in (200, 201):
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

    # HC-04: información molecular clave para decidir tratamiento.
    clave = d.get("biomarcadores_clave") or []
    if clave:
        print("\n  BIOMARCADORES CLAVE")
        for b in clave:
            estado = "★" if b["confirmado"] else "? por confirmar"
            terapia = f" → {b['terapia']}" if b["terapia"] else ""
            print(f"    {estado} {b['biomarcador']}: {b['resultado']}{terapia}")

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
    print("(También puede abrirse desde la lista de pacientes o los resultados de búsqueda.)")
    _ofrecer_abrir_360()


# ---------------------------------------------------------------------------
# HC-02 · Laboratorios
# ---------------------------------------------------------------------------

def _marca_punto(p: dict) -> str:
    if p["en_conflicto"]:
        return "⚠ en conflicto"
    if p["critico"]:
        return "‼ crítico"
    return "↑↓ fuera de rango" if p["alterado"] else ""


def _barra(valor: Optional[float], maximo: float, ancho: int = 24) -> str:
    if valor is None or maximo <= 0:
        return ""
    return "█" * max(1, round(ancho * valor / maximo))


def mostrar_tendencia(t: dict) -> None:
    print(f"\n  Tendencia de {t['prueba']}")
    for advertencia in t["advertencias"]:
        print(f"  ⚠ {advertencia}")
    if not t["series"]:
        print("  Sin resultados para este marcador.")
        return
    for serie in t["series"]:
        puntos = serie["puntos"]
        maximo = max((p["valor_numerico"] or 0) for p in puntos)
        print(f"\n  Unidad: {serie['unidad'] or 'sin unidad'}")
        for p in puntos:
            momento = (p["fecha_hora"] or p["fecha"]).replace("T", " ")
            print(f"    {momento:<16}  {p['valor']:>8}  {_barra(p['valor_numerico'], maximo):<24}  {_marca_punto(p)}")


def _registrar_laboratorio(paciente_id: int) -> None:
    print("\n  Registrar resultado (doble validación: identificación y nombre de la orden)")
    datos = {
        "identificacion": pedir("  Identificación del paciente en la orden: "),
        "nombre": pedir("  Nombre del paciente en la orden: "),
        "prueba": pedir("  Prueba (p. ej. Potasio, Hemoglobina, CEA): "),
        "valor": pedir("  Valor: "),
        "unidad": pedir("  Unidad (p. ej. mmol/L): ") or None,
        "fecha": _pedir_fecha("  Fecha de la toma (YYYY-MM-DD, Enter = hoy): ") or date.today().isoformat(),
    }
    hora = pedir("  Hora de la toma (HH:MM, Enter si no se sabe): ")
    if hora:
        datos["hora"] = hora
    rango = pedir("  Rango de referencia (bajo-alto, Enter si no viene): ")
    if rango:
        datos["rango_referencia"] = rango

    r = _datos_o_error(_llamar("POST", f"/pacientes/{paciente_id}/laboratorios", json=datos))
    if r is None:
        return
    print(f"\n  ✔ Resultado guardado (laboratorio #{r['laboratorio_id']}).")
    if r["alerta"]:
        print(f"  ‼ VALOR CRÍTICO: {r['alerta']['limite_superado']}. Quedó como alerta en el resumen 360.")
    for c in r["conflictos"]:
        print(f"  ⚠ CONFLICTO: ya había un resultado del mismo momento con otro valor "
              f"({c['valor_a']} y {c['valor_b']}). Ninguno se sobrescribió; revíselo en la opción 6.")


def flujo_laboratorios() -> None:
    print("\n=== Laboratorios (HC-02) ===")
    paciente_id = _pedir_id("Id del paciente (Enter para volver): ")
    if paciente_id is None:
        return
    while True:
        marcadores = _datos_o_error(_llamar("GET", f"/pacientes/{paciente_id}/laboratorios/marcadores"))
        if marcadores is None:
            return
        print(f"\n  {len(marcadores)} marcador(es), el medido más recientemente primero")
        for i, m in enumerate(marcadores, 1):
            print(f"  {i:>3}. {_recortar(m['prueba'], 28):<28} {m['cantidad']:>3} resultado(s) · último "
                  f"{m['ultimo_valor']} {m['unidad'] or ''} ({m['ultima_fecha']})")
        print("\n  N° = ver tendencia · R = registrar resultado · Enter = volver")
        opcion = pedir("  Opción: ").lower()
        if not opcion:
            return
        if opcion == "r":
            _registrar_laboratorio(paciente_id)
        elif opcion.isdigit() and 1 <= int(opcion) <= len(marcadores):
            prueba = marcadores[int(opcion) - 1]["prueba"]
            tendencia = _datos_o_error(_llamar("GET", f"/pacientes/{paciente_id}/laboratorios/tendencia",
                                               {"prueba": prueba}))
            if tendencia:
                mostrar_tendencia(tendencia)
        else:
            print("  Opción inválida.")


def flujo_alertas_conflictos() -> None:
    print("\n=== Alertas críticas y conflictos de laboratorio (HC-02) ===")
    paciente_id = _pedir_id("Id del paciente (Enter para volver): ")
    if paciente_id is None:
        return
    while True:
        alertas = _datos_o_error(_llamar("GET", f"/pacientes/{paciente_id}/alertas-laboratorio"))
        conflictos = _datos_o_error(_llamar("GET", f"/pacientes/{paciente_id}/conflictos-laboratorio"))
        if alertas is None or conflictos is None:
            return
        print(f"\n  ALERTAS CRÍTICAS ACTIVAS ({len(alertas)})")
        for a in alertas:
            print(f"    A{a['id']}  {a['fecha']}  {a['prueba']} {a['valor']} {a['unidad'] or ''} · {a['limite_superado']}")
        print(f"\n  CONFLICTOS PENDIENTES ({len(conflictos)})")
        for c in conflictos:
            print(f"    C{c['id']}  {c['momento'].replace('T', ' ')}  {c['prueba']}: "
                  f"A = {c['valor_a']} {c['unidad_a'] or ''} · B = {c['valor_b']} {c['unidad_b'] or ''}")
        if not alertas and not conflictos:
            print("\n  Nada pendiente de revisión.")
            return

        opcion = pedir("\n  A<n> = marcar alerta revisada · C<n> = resolver conflicto · Enter = volver: ").upper()
        if not opcion:
            return
        if opcion[0] == "A" and opcion[1:].isdigit():
            quien = pedir("  Revisada por: ")
            r = _datos_o_error(_llamar("POST", f"/pacientes/{paciente_id}/alertas-laboratorio/{opcion[1:]}/revisar",
                                       json={"revisada_por": quien}))
            if r:
                print("  ✔ Alerta revisada.")
        elif opcion[0] == "C" and opcion[1:].isdigit():
            print("  1. Válido A   2. Válido B   3. Ambos válidos   4. Ninguno válido")
            resolucion = {"1": "valido_a", "2": "valido_b", "3": "ambos_validos", "4": "ninguno_valido"}.get(pedir("  Resolución: "))
            if resolucion is None:
                print("  Opción inválida.")
                continue
            cuerpo = {"resolucion": resolucion, "resuelto_por": pedir("  Resuelto por: "), "nota": pedir("  Nota (opcional): ") or None}
            r = _datos_o_error(_llamar("POST", f"/pacientes/{paciente_id}/conflictos-laboratorio/{opcion[1:]}/resolver",
                                       json=cuerpo))
            if r:
                print("  ✔ Conflicto resuelto. Los dos resultados se conservan en el expediente.")
        else:
            print("  Opción inválida.")


# ---------------------------------------------------------------------------
# HC-04 · Biopsias y biomarcadores
# ---------------------------------------------------------------------------

ETIQUETAS_RELEVANCIA = {
    "accionable_confirmado": "★ accionable",
    "pendiente_confirmacion": "? pendiente de confirmar",
    "informativo": "informativo",
    "descartado": "descartado",
}


def _mostrar_biomarcadores(biomarcadores: list) -> None:
    print(f"\n  BIOMARCADORES ({len(biomarcadores)})")
    if not biomarcadores:
        print("    —")
    for b in biomarcadores:
        print(f"    #{b['biomarcador_id']:<4} {b['fecha']}  {b['biomarcador']}: {b['resultado']}")
        linea = f"          {ETIQUETAS_RELEVANCIA.get(b['relevancia'], b['relevancia'])}"
        if b["terapia_asociada"]:
            linea += f" · {b['terapia_asociada']}"
        if b["variable_tx"] and b["relevancia"] != "pendiente_confirmacion":
            linea += f" · TX-01: {b['variable_tx']}={b['valor_tx']}"
        print(linea)


def _registrar_episodio_y_biopsia(paciente_id: int) -> None:
    episodios = _datos_o_error(_llamar("GET", f"/pacientes/{paciente_id}/episodios")) or []
    episodio_id = None
    if not episodios or pedir("  ¿Registrar un episodio diagnóstico nuevo? (s/N): ").lower() == "s":
        cuerpo = {
            "descripcion": pedir("  Diagnóstico: "),
            "tipo_cancer": pedir("  Tipo de cáncer (NSCLC, breast, melanoma...): ") or None,
            "fecha_diagnostico": _pedir_fecha("  Fecha del diagnóstico (YYYY-MM-DD, opcional): "),
        }
        episodio = _datos_o_error(_llamar("POST", f"/pacientes/{paciente_id}/episodios", json=cuerpo))
        if episodio is None:
            return
        episodio_id = episodio["id"]
    elif len(episodios) > 1:
        for e in episodios:
            print(f"    {e['id']}. {e['descripcion']} ({e['tipo_cancer'] or 'tipo sin indicar'})")
        episodio_id = _pedir_id("  Episodio de la biopsia: ")
    cuerpo = {
        "fecha": _pedir_fecha("  Fecha de la biopsia (YYYY-MM-DD, Enter = hoy): ") or date.today().isoformat(),
        "sitio": pedir("  Sitio: "),
        "procedimiento": pedir("  Procedimiento: "),
        "diagnostico_histologico": pedir("  Diagnóstico histológico (opcional): ") or None,
        "episodio_id": episodio_id,
    }
    biopsia = _datos_o_error(_llamar("POST", f"/pacientes/{paciente_id}/biopsias", json=cuerpo))
    if biopsia:
        print(f"  ✔ Biopsia #{biopsia['id']} vinculada al episodio {biopsia['episodio_id']}.")


def _registrar_biomarcador(paciente_id: int) -> None:
    biopsias = _datos_o_error(_llamar("GET", f"/pacientes/{paciente_id}/biopsias")) or []
    if not biopsias:
        print("  Primero registre la biopsia (opción B).")
        return
    for b in biopsias:
        print(f"    {b['id']}. {b['fecha']} · {b['sitio']} · {b['procedimiento']}")
    biopsia_id = _pedir_id("  Biopsia: ")
    if biopsia_id is None:
        return
    print("  Estados según el biomarcador: detectada/no_detectada (EGFR, BRAF, KRAS, MET), "
          "reordenado/no_reordenado (ALK, ROS1, RET, NTRK), positivo/negativo/equivoco (HER2, RE, RP), "
          "cuantificado (PD-L1 TPS).")
    cuerpo = {"biopsia_id": biopsia_id, "biomarcador": pedir("  Biomarcador: "), "estado": pedir("  Estado: "),
              "metodo": pedir("  Método (NGS, PCR, IHC, FISH, 22C3...): ")}
    variante = pedir("  Variante (si se detectó, p. ej. L858R): ")
    valor = pedir("  Valor (% para PD-L1 o receptores, opcional): ")
    ihc = pedir("  Puntaje IHC (HER2: 0, 1+, 2+, 3+; opcional): ")
    ish = pedir("  ISH (amplificado / no_amplificado; opcional): ")
    if variante:
        cuerpo["variante"] = variante
    if valor:
        cuerpo["valor"] = valor
    if ihc:
        cuerpo["ihc_score"] = ihc
    if ish:
        cuerpo["ish"] = ish
    cuerpo["confirmacion"] = pedir("  Vuelva a escribir el resultado clave (el estado, o el valor en PD-L1): ")
    r = _datos_o_error(_llamar("POST", f"/pacientes/{paciente_id}/biomarcadores", json=cuerpo))
    if r:
        print(f"  ✔ Guardado como {ETIQUETAS_RELEVANCIA.get(r['relevancia'], r['relevancia'])}"
              + (f". TX-01 recibe {r['variable_tx']}={r['valor_tx']}." if r["variable_tx"] else "."))


def flujo_biomarcadores() -> None:
    print("\n=== Biopsias y biomarcadores (HC-04) ===")
    paciente_id = _pedir_id("Id del paciente (Enter para volver): ")
    if paciente_id is None:
        return
    while True:
        biopsias = _datos_o_error(_llamar("GET", f"/pacientes/{paciente_id}/biopsias"))
        biomarcadores = _datos_o_error(_llamar("GET", f"/pacientes/{paciente_id}/biomarcadores"))
        if biopsias is None or biomarcadores is None:
            return
        print(f"\n  BIOPSIAS ({len(biopsias)})")
        for b in biopsias:
            print(f"    #{b['id']:<4} {b['fecha']}  {b['sitio']} · {b['procedimiento']} (episodio {b['episodio_id']})")
        _mostrar_biomarcadores(biomarcadores)

        opcion = pedir("\n  B = registrar biopsia · M = registrar biomarcador · C<n> = confirmar · "
                       "D<n> = descartar · Enter = volver: ").upper()
        if not opcion:
            return
        if opcion == "B":
            _registrar_episodio_y_biopsia(paciente_id)
        elif opcion == "M":
            _registrar_biomarcador(paciente_id)
        elif opcion[0] in "CD" and opcion[1:].isdigit():
            ruta = f"/pacientes/{paciente_id}/biomarcadores/{opcion[1:]}"
            if opcion[0] == "C":
                cuerpo = {"confirmado_por": pedir("  Confirmado por: "),
                          "confirmacion": pedir("  Escriba el resultado que confirma (p. ej. reordenado): ")}
                r = _datos_o_error(_llamar("POST", f"{ruta}/confirmar", json=cuerpo))
            else:
                r = _datos_o_error(_llamar("POST", f"{ruta}/descartar", json={"revisado_por": pedir("  Revisado por: ")}))
            if r:
                print(f"  ✔ Ahora: {ETIQUETAS_RELEVANCIA.get(r['relevancia'], r['relevancia'])}.")
        else:
            print("  Opción inválida.")


# ---------------------------------------------------------------------------
# Menú principal
# ---------------------------------------------------------------------------

OPCIONES_MENU = {
    "1": ("Ver todos mis pacientes", flujo_listar_pacientes),
    "2": ("Buscar paciente por nombre", busqueda_por_nombre),
    "3": ("Buscar con filtros (uno o varios)", busqueda_con_filtros),
    "4": ("Abrir resumen 360 de un paciente", flujo_resumen_360),
    "5": ("Laboratorios: tendencias y registro (HC-02)", flujo_laboratorios),
    "6": ("Alertas críticas y conflictos de laboratorio (HC-02)", flujo_alertas_conflictos),
    "7": ("Biopsias y biomarcadores (HC-04)", flujo_biomarcadores),
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
