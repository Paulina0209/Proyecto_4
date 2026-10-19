"""Demo de NFR-01, NFR-02 y NFR-05 sobre la base real (copia), verificando cada criterio.

    python demo_operacion.py                 # las tres historias (~2 min)
    python demo_operacion.py --solo nfr01    # o nfr02, nfr05

Trabaja sobre COPIAS de ``data/copiloto.db`` y ``patients/db/pacientes.db``
(13.159 pacientes reales de cBioPortal) en una carpeta temporal: la base real
no se modifica. Con ``OPENAI_API_KEY`` en el ``.env`` mide también las notas y
resúmenes redactados por GPT; sin ella, los de reglas.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional

RAIZ = Path(__file__).resolve().parent
ANCHO = 78
_fallas: List[str] = []


def titulo(texto: str) -> None:
    print("\n" + "█" * ANCHO + f"\n  {texto}\n" + "█" * ANCHO)


def subtitulo(texto: str) -> None:
    print("\n" + "─" * ANCHO + f"\n{texto}\n" + "─" * ANCHO)


def verificar(condicion: bool, texto: str) -> None:
    print(f"  {'✔' if condicion else '✘'} {texto}")
    if not condicion:
        _fallas.append(texto)


def nota(texto: str) -> None:
    print(f"  ⓘ {texto}")


# ---------------------------------------------------------------------------


def demo_nfr01(carpeta: Path) -> None:
    import httpx

    from operacion.carga import ejecutar_carga, pacientes_de_muestra, servidor_local
    from operacion.rendimiento import copia_del_expediente, medir_funciones_ia, preparar_paciente
    from seguridad.tls import contexto_tls_cliente

    titulo("NFR-01 — Rendimiento: consultas < 2 s, notas < 10 s")

    subtitulo("AC1 — Médicos abriendo expedientes al mismo tiempo (API real por TLS, 13.159 pacientes)")
    with servidor_local(carpeta / "nfr01") as (url, cert, base):
        tls = contexto_tls_cliente(cert)
        pacientes = pacientes_de_muestra(base)
        for usuarios in (1, 10, 25):
            r = ejecutar_carga(url, pacientes, usuarios, 10, tls)
            print(r.a_texto())
            verificar(r.cumple, f"{usuarios} médico(s) a la vez: p95 {r.p95_ms:.0f} ms < 2000 ms y 0 errores")

        subtitulo("AC3 — Cada respuesta dice cuánto tardó, y la réplica lleva la cuenta por ruta")
        pid, onc = pacientes[0]
        r = httpx.get(f"{url}/pacientes/{pid}/resumen-360", params={"oncologo_id": onc}, verify=tls)
        print(f"    GET /pacientes/{pid}/resumen-360 -> Server-Timing: {r.headers.get('server-timing')}")
        verificar("server-timing" in r.headers, "Cabecera Server-Timing (visible en las herramientas del navegador)")
        rutas = httpx.get(f"{url}/salud/metricas", verify=tls).json()["rutas"]
        for ruta in rutas[:4]:
            print(f"    {ruta['ruta']:<48} {ruta['peticiones']:>4} pet · p95 {ruta['p95_ms']:>6.0f} ms · "
                  f"{'cumple' if ruta['cumple'] else 'NO cumple'}")
        verificar(all("/7" not in r["ruta"] for r in rutas), "Agrupado por plantilla de ruta, sin ids de pacientes")

    subtitulo("AC1 y AC2 — Funciones de IA sobre el paciente real P-0016350")
    with copia_del_expediente() as conn:
        paciente_id, consulta_id = preparar_paciente(conn)
        for medicion in medir_funciones_ia(conn, paciente_id, consulta_id, repeticiones=3):
            print(medicion.a_texto())
            verificar(medicion.cumple, f"{medicion.nombre}: p95 {medicion.p95_ms / 1000:.1f} s < {medicion.objetivo_ms / 1000:.0f} s")
    nota("Si GPT no responde en 8 s, el borrador por reglas llega igual antes de 10 s (operacion.presupuesto).")


def demo_nfr02(carpeta: Path) -> None:
    import httpx

    from operacion import monitor
    from operacion.carga import ejecutar_carga, pacientes_de_muestra, servidor_local
    from seguridad.tls import contexto_tls_cliente

    titulo("NFR-02 — Disponibilidad (SLA ≥ 99,5 %)")
    with servidor_local(carpeta / "nfr02") as (url, cert, base):
        tls = contexto_tls_cliente(cert)

        subtitulo("AC1 — Sondas para el balanceador")
        r = httpx.get(f"{url}/salud/vivo", verify=tls)
        print(f"    GET /salud/vivo  -> {r.status_code} {r.json()}")
        r = httpx.get(f"{url}/salud/listo", verify=tls)
        print(f"    GET /salud/listo -> {r.status_code} estado={r.json()['estado']}")
        for v in r.json()["verificaciones"]:
            print(f"        {v['nombre']:<20} {v['estado']:<10} {v['detalle']}")
        verificar(r.status_code == 200, "La réplica está lista para atender")
        verificar(any(v["estado"] == "degradado" and not v["critica"] for v in r.json()["verificaciones"]),
                  "Sin PACS configurado queda 'degradado', pero no sale de servicio (dependencia externa)")

        subtitulo("AC2 — Bajo carga no hay caídas por la base de datos")
        resultado = ejecutar_carga(url, pacientes_de_muestra(base), 25, 10, tls)
        print(resultado.a_texto())
        verificar(resultado.errores == 0, f"{resultado.peticiones} peticiones de 25 médicos a la vez, 0 errores")
        nota("Antes de NFR-02 esta misma carga devolvía 500 en ~80 % de las peticiones (SQLite entre hilos).")

        subtitulo("AC3 — Disponibilidad medida desde afuera, contra el SLA")
        conn = monitor.conectar(carpeta / "disponibilidad.db")
        oculta = base.with_name("pacientes.db.fuera")
        print("    Sondeo cada 0,2 s; a la mitad se simula una falla: la base de pacientes deja de estar disponible.")
        for i in range(30):
            if i == 12:
                for _ in range(50):
                    try:
                        base.rename(oculta)
                        break
                    except PermissionError:
                        time.sleep(0.1)
            if i == 18:
                oculta.rename(base)
            sondeo = monitor.sondear(f"{url}/salud/listo", cert)
            monitor.guardar(conn, sondeo)
            if i in (11, 12, 18):
                print(f"      sondeo {i:>2}: {'disponible' if sondeo.disponible else 'CAÍDO'} {sondeo.detalle or ''}")
            time.sleep(0.2)
        hasta = monitor.datetime.now(monitor.timezone.utc)
        informe = monitor.calcular(monitor.leer(conn, hasta - monitor.timedelta(minutes=10), hasta), 0.2)
        conn.close()
        print(f"    Ventana observada: {informe.minutos_observados * 60:.1f} s · caído {informe.minutos_caido * 60:.1f} s "
              f"· disponibilidad {informe.disponibilidad:.1f} %")
        for incidente in informe.incidentes:
            print(f"    Incidente: {incidente.inicio[11:19]} -> {incidente.fin[11:19]} "
                  f"({incidente.minutos * 60:.1f} s): {incidente.detalle}")
        verificar(len(informe.incidentes) == 1, "La caída aparece como un incidente con inicio, fin, duración y causa")
        verificar(not informe.cumple, "En una ventana tan corta, esa caída rompe el 99,5 %: el monitor lo detecta")
        mensual = 100 * (1 - informe.minutos_caido / (30 * 24 * 60))
        print(f"    La misma caída en un mes completo: {mensual:.5f} % (presupuesto del SLA: 3 h 39 min al mes)")
        nota("En operación: python -m operacion.monitor vigilar https://<servidor>/salud/listo --ca <cert> "
             "y python -m operacion.monitor informe --dias 30. 99,5 % = 3 h 39 min de caída al mes como máximo.")


def demo_nfr05(carpeta: Path) -> None:
    import collections
    import threading

    import httpx

    from frontend.sesiones import AlmacenSesionesSQLite
    from operacion.carga import ejecutar_carga, pacientes_de_muestra, servidor_local
    from seguridad.tls import contexto_tls_cliente

    titulo("NFR-05 — Escalabilidad horizontal")

    subtitulo("AC1 — Varios procesos atienden la misma API (python -m seguridad.servidor_tls --workers 2)")
    resultados = {}
    for workers in (1, 2):
        with servidor_local(carpeta / f"nfr05_{workers}", workers=workers) as (url, cert, base):
            tls = contexto_tls_cliente(cert)
            resultados[workers] = ejecutar_carga(url, pacientes_de_muestra(base), 50, 10, tls, workers)
            print(resultados[workers].a_texto())
            if workers == 2:
                instancias = collections.Counter()
                cerrojo = threading.Lock()

                def sondear_varias():
                    for _ in range(10):
                        with httpx.Client(verify=tls) as cliente:  # conexión nueva cada vez
                            instancia = cliente.get(f"{url}/salud/vivo").json()["instancia"]
                        with cerrojo:
                            instancias[instancia] += 1

                hilos = [threading.Thread(target=sondear_varias) for _ in range(10)]
                for h in hilos:
                    h.start()
                for h in hilos:
                    h.join()
                print(f"    100 conexiones simultáneas, respuestas por proceso: {dict(instancias)}")
                verificar(len(instancias) == 2, "Los dos procesos reciben peticiones")

    subtitulo("AC2 — Más procesos, más capacidad")
    uno, dos = resultados[1].peticiones_por_segundo, resultados[2].peticiones_por_segundo
    print(f"    50 médicos a la vez: {uno:.0f} pet/s con 1 proceso -> {dos:.0f} pet/s con 2 ({(dos / uno - 1) * 100:+.0f} %)")
    verificar(dos > uno, "La capacidad crece al agregar procesos, sin errores")
    nota("El límite siguiente es SQLite (un escritor a la vez): ver docs/escalabilidad.md.")

    subtitulo("AC3 — Las réplicas no guardan estado propio: la sesión es compartida")
    replica_a = AlmacenSesionesSQLite(carpeta / "sesiones.db")
    replica_b = AlmacenSesionesSQLite(carpeta / "sesiones.db")
    token = replica_a.abrir(usuario_id=7)
    print(f"    La réplica A abre la sesión del usuario 7; la réplica B la reconoce: usuario {replica_b.resolver(token)}")
    verificar(replica_b.resolver(token) == 7, "Cualquier réplica atiende a cualquier usuario")
    replica_b.cerrar(token)
    verificar(replica_a.resolver(token) is None, "Cerrar sesión en una réplica la cierra en todas")


DEMOS = {"nfr01": demo_nfr01, "nfr02": demo_nfr02, "nfr05": demo_nfr05}


def main(argv: Optional[List[str]] = None) -> int:
    for flujo in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError):
            flujo.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(RAIZ))
    os.chdir(RAIZ)
    p = argparse.ArgumentParser(prog="python demo_operacion.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--solo", nargs="+", choices=list(DEMOS), help="Correr solo estas historias.")
    args = p.parse_args(argv)

    _fallas.clear()
    with tempfile.TemporaryDirectory(prefix="copiloto_demo_operacion_", ignore_cleanup_errors=True) as tmp:
        for clave in args.solo or DEMOS:
            DEMOS[clave](Path(tmp))
    titulo("FIN" + (f" — {len(_fallas)} verificación(es) fallida(s)" if _fallas else " — todos los criterios verificados"))
    for falla in _fallas:
        print(f"  ✘ {falla}")
    return len(_fallas)


if __name__ == "__main__":
    sys.exit(main())
