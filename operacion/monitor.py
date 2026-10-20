"""NFR-02 — Disponibilidad medida contra el SLA (≥ 99,5 %).

Como institución, quiero alta disponibilidad del sistema (SLA ≥ 99,5 %), para
que esté accesible durante el horario clínico.

Un 99,5 % mensual deja 3 h 39 min de caída al mes (el *presupuesto de error*).
Para saber si se cumple hay que medirlo desde afuera, como lo vería un médico:

    python -m operacion.monitor vigilar https://copiloto.hospital/salud/listo --ca cert.pem
    python -m operacion.monitor informe --dias 30

``vigilar`` consulta la sonda cada ``--intervalo`` segundos y guarda cada
resultado en una base propia (``data/disponibilidad.db``). Un sondeo cuenta
como disponible si responde 200 antes de ``--tiempo-maximo`` (un sistema que
tarda más de lo que el médico espera tampoco está disponible para él).

``informe`` calcula, para una ventana:

    - la disponibilidad (tiempo disponible / tiempo observado, ponderando cada
      sondeo por el intervalo hasta el siguiente);
    - el presupuesto de error consumido y el que queda;
    - los incidentes (caídas seguidas agrupadas, con inicio, fin y duración).

El horario clínico se puede acotar con ``--horario 07:00-19:00`` para medir el
SLA solo en las horas que importan.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, time as hora, timedelta, timezone
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

OBJETIVO_SLA = 99.5
RUTA_POR_DEFECTO = Path(__file__).resolve().parent.parent / "data" / "disponibilidad.db"
#: Un hueco mayor que esto entre dos sondeos no se cuenta (el monitor estaba apagado).
HUECO_MAXIMO_FACTOR = 3

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS sondeos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    disponible INTEGER NOT NULL,
    ms REAL,
    detalle TEXT
);
CREATE INDEX IF NOT EXISTS idx_sondeos_fecha ON sondeos (fecha);
"""


@dataclass(frozen=True)
class Sondeo:
    fecha: datetime
    disponible: bool
    ms: Optional[float] = None
    detalle: Optional[str] = None


@dataclass(frozen=True)
class Incidente:
    inicio: str
    fin: str
    minutos: float
    detalle: Optional[str]


@dataclass(frozen=True)
class InformeDisponibilidad:
    desde: str
    hasta: str
    sondeos: int
    minutos_observados: float
    minutos_caido: float
    disponibilidad: float
    objetivo: float
    incidentes: Tuple[Incidente, ...] = field(default_factory=tuple)

    @property
    def cumple(self) -> bool:
        return self.disponibilidad >= self.objetivo

    @property
    def presupuesto_minutos(self) -> float:
        """Minutos de caída que admite el objetivo en el tiempo observado."""
        return self.minutos_observados * (100 - self.objetivo) / 100

    @property
    def presupuesto_restante_minutos(self) -> float:
        return self.presupuesto_minutos - self.minutos_caido

    def a_dict(self) -> dict:
        return asdict(self) | {
            "cumple": self.cumple,
            "presupuesto_minutos": round(self.presupuesto_minutos, 1),
            "presupuesto_restante_minutos": round(self.presupuesto_restante_minutos, 1),
        }

    def a_texto(self) -> str:
        lineas = [
            f"Disponibilidad del {self.desde[:16]} al {self.hasta[:16]} ({self.sondeos} sondeos)",
            f"  Disponibilidad: {self.disponibilidad:.3f} %  (objetivo {self.objetivo} %)  -> "
            + ("CUMPLE" if self.cumple else "NO CUMPLE"),
            f"  Tiempo observado: {self.minutos_observados / 60:.1f} h; caído: {self.minutos_caido:.1f} min",
            f"  Presupuesto de error: {self.presupuesto_minutos:.1f} min; queda {self.presupuesto_restante_minutos:.1f} min",
        ]
        if self.incidentes:
            lineas.append(f"  Incidentes ({len(self.incidentes)}):")
            lineas += [f"    {i.inicio[:19]} -> {i.fin[:19]}  {i.minutos:.1f} min  {i.detalle or ''}" for i in self.incidentes]
        return "\n".join(lineas)


# ---------------------------------------------------------------------------
# Almacén
# ---------------------------------------------------------------------------


def conectar(ruta: Path = RUTA_POR_DEFECTO) -> sqlite3.Connection:
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(ruta))
    conn.executescript(_ESQUEMA)
    return conn


def guardar(conn: sqlite3.Connection, sondeo: Sondeo) -> None:
    conn.execute(
        "INSERT INTO sondeos (fecha, disponible, ms, detalle) VALUES (?, ?, ?, ?)",
        (sondeo.fecha.isoformat(), int(sondeo.disponible), sondeo.ms, sondeo.detalle),
    )
    conn.commit()


def leer(conn: sqlite3.Connection, desde: datetime, hasta: datetime) -> List[Sondeo]:
    filas = conn.execute(
        "SELECT fecha, disponible, ms, detalle FROM sondeos WHERE fecha >= ? AND fecha <= ? ORDER BY fecha",
        (desde.isoformat(), hasta.isoformat()),
    ).fetchall()
    return [Sondeo(datetime.fromisoformat(f), bool(d), m, det) for f, d, m, det in filas]


# ---------------------------------------------------------------------------
# Cálculo
# ---------------------------------------------------------------------------


def _en_horario(momento: datetime, horario: Optional[Tuple[hora, hora]]) -> bool:
    if horario is None:
        return True
    local = momento.astimezone().time()
    return horario[0] <= local < horario[1]


def calcular(
    sondeos: Sequence[Sondeo],
    intervalo_s: float,
    objetivo: float = OBJETIVO_SLA,
    horario: Optional[Tuple[hora, hora]] = None,
) -> InformeDisponibilidad:
    """Disponibilidad ponderada por tiempo.

    Cada sondeo representa el tramo hasta el siguiente (el último, un
    intervalo). Un tramo mayor que ``HUECO_MAXIMO_FACTOR`` intervalos se recorta
    a un intervalo: si el monitor estuvo apagado, ese tiempo no se observó y no
    se cuenta ni a favor ni en contra.
    """
    sondeos = sorted((s for s in sondeos if _en_horario(s.fecha, horario)), key=lambda s: s.fecha)
    if not sondeos:
        ahora = datetime.now(timezone.utc).isoformat()
        return InformeDisponibilidad(ahora, ahora, 0, 0.0, 0.0, 100.0, objetivo)

    observado = caido = 0.0
    incidentes: List[Incidente] = []
    inicio_caida: Optional[Sondeo] = None
    fin_caida: Optional[datetime] = None
    minutos_caida = 0.0
    for actual, siguiente in zip(sondeos, list(sondeos[1:]) + [None]):
        tramo = intervalo_s if siguiente is None else (siguiente.fecha - actual.fecha).total_seconds()
        if tramo > intervalo_s * HUECO_MAXIMO_FACTOR or tramo <= 0:
            tramo = intervalo_s
        observado += tramo
        if not actual.disponible:
            caido += tramo
            if inicio_caida is None:
                inicio_caida, minutos_caida = actual, 0.0
            minutos_caida += tramo / 60
            fin_caida = actual.fecha + timedelta(seconds=tramo)
        elif inicio_caida is not None:
            incidentes.append(Incidente(inicio_caida.fecha.isoformat(), fin_caida.isoformat(), round(minutos_caida, 3), inicio_caida.detalle))
            inicio_caida = None
    if inicio_caida is not None:
        incidentes.append(Incidente(inicio_caida.fecha.isoformat(), fin_caida.isoformat(), round(minutos_caida, 3), inicio_caida.detalle))

    return InformeDisponibilidad(
        desde=sondeos[0].fecha.isoformat(),
        hasta=(sondeos[-1].fecha + timedelta(seconds=intervalo_s)).isoformat(),
        sondeos=len(sondeos),
        minutos_observados=round(observado / 60, 2),
        minutos_caido=round(caido / 60, 2),
        disponibilidad=round(100 * (observado - caido) / observado, 4),
        objetivo=objetivo,
        incidentes=tuple(incidentes),
    )


# ---------------------------------------------------------------------------
# Sondeo
# ---------------------------------------------------------------------------


def sondear(url: str, ca: Optional[str] = None, tiempo_maximo_s: float = 5.0, cliente=None) -> Sondeo:
    """Un sondeo: disponible si responde 200 antes de ``tiempo_maximo_s``."""
    import httpx

    from seguridad.tls import contexto_tls_cliente

    momento = datetime.now(timezone.utc)
    inicio = time.perf_counter()
    try:
        if cliente is not None:
            respuesta = cliente.get(url, timeout=tiempo_maximo_s)
        else:
            verificar = contexto_tls_cliente(ca) if url.startswith("https://") else True
            respuesta = httpx.get(url, timeout=tiempo_maximo_s, verify=verificar)
    except Exception as exc:  # red, TLS, tiempo agotado
        return Sondeo(momento, False, None, f"{type(exc).__name__}: {str(exc)[:120]}")
    ms = round((time.perf_counter() - inicio) * 1000, 1)
    if respuesta.status_code != 200:
        try:
            fallas = [v["nombre"] for v in respuesta.json().get("verificaciones", []) if v.get("estado") == "falla"]
        except (ValueError, AttributeError):
            fallas = []
        return Sondeo(momento, False, ms, f"HTTP {respuesta.status_code}" + (f": {', '.join(fallas)}" if fallas else ""))
    if ms > tiempo_maximo_s * 1000:
        return Sondeo(momento, False, ms, f"respondió en {ms:.0f} ms")
    return Sondeo(momento, True, ms)


def vigilar(
    url: str,
    conn: sqlite3.Connection,
    intervalo_s: float,
    ca: Optional[str] = None,
    tiempo_maximo_s: float = 5.0,
    veces: Optional[int] = None,
    dormir: Callable[[float], None] = time.sleep,
    al_sondear: Optional[Callable[[Sondeo], None]] = None,
) -> int:
    hechos = 0
    while veces is None or hechos < veces:
        sondeo = sondear(url, ca, tiempo_maximo_s)
        guardar(conn, sondeo)
        if al_sondear:
            al_sondear(sondeo)
        hechos += 1
        if veces is None or hechos < veces:
            dormir(intervalo_s)
    return hechos


def _horario(texto: Optional[str]) -> Optional[Tuple[hora, hora]]:
    if not texto:
        return None
    inicio, fin = texto.split("-")
    return hora.fromisoformat(inicio), hora.fromisoformat(fin)


def main(argv: Optional[Sequence[str]] = None) -> int:
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    p = argparse.ArgumentParser(prog="python -m operacion.monitor", description="Disponibilidad contra el SLA (NFR-02).")
    p.add_argument("--base", type=Path, default=RUTA_POR_DEFECTO, help="Dónde se guardan los sondeos.")
    sub = p.add_subparsers(dest="comando", required=True)
    v = sub.add_parser("vigilar", help="Sondea la URL periódicamente.")
    v.add_argument("url")
    v.add_argument("--intervalo", type=float, default=30.0, help="Segundos entre sondeos (por defecto 30).")
    v.add_argument("--ca", help="Certificado en el que confiar (p. ej. el autofirmado de certs/).")
    v.add_argument("--tiempo-maximo", type=float, default=5.0)
    v.add_argument("--veces", type=int, help="Número de sondeos (por defecto, sin fin).")
    i = sub.add_parser("informe", help="Disponibilidad de una ventana.")
    i.add_argument("--dias", type=float, default=30.0)
    i.add_argument("--intervalo", type=float, default=30.0, help="El mismo intervalo con el que se vigiló.")
    i.add_argument("--objetivo", type=float, default=OBJETIVO_SLA)
    i.add_argument("--horario", help="Solo este horario local, p. ej. 07:00-19:00.")
    i.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    conn = conectar(args.base)
    try:
        if args.comando == "vigilar":
            def mostrar(s: Sondeo) -> None:
                print(f"{s.fecha.astimezone():%Y-%m-%d %H:%M:%S}  {'OK ' if s.disponible else 'CAÍDO'}  "
                      f"{'' if s.ms is None else f'{s.ms:.0f} ms'}  {s.detalle or ''}", flush=True)
            try:
                vigilar(args.url, conn, args.intervalo, args.ca, args.tiempo_maximo, args.veces, al_sondear=mostrar)
            except KeyboardInterrupt:
                pass
            return 0
        hasta = datetime.now(timezone.utc)
        informe = calcular(leer(conn, hasta - timedelta(days=args.dias), hasta), args.intervalo, args.objetivo, _horario(args.horario))
        print(json.dumps(informe.a_dict(), ensure_ascii=False, indent=2) if args.json else informe.a_texto())
        return 0 if informe.cumple else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
