"""El almacén de sesiones en memoria: expiración por inactividad y por duración máxima, y cierre."""
from __future__ import annotations

import hashlib

from frontend.sesiones import AlmacenSesiones


class Reloj:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _almacen(reloj, inactividad=100, maxima=1000):
    return AlmacenSesiones(inactividad_s=inactividad, duracion_maxima_s=maxima, reloj=reloj)


def test_un_token_abre_la_sesion_del_usuario_y_es_impredecible():
    reloj = Reloj()
    a = _almacen(reloj)
    t1, t2 = a.abrir(5), a.abrir(5)
    assert t1 != t2 and len(t1) >= 32
    assert a.resolver(t1) == 5 and a.resolver(t2) == 5


def test_sin_token_o_con_token_inventado_no_hay_sesion():
    a = _almacen(Reloj())
    assert a.resolver(None) is None and a.resolver("") is None and a.resolver("inventado") is None


def test_el_almacen_no_guarda_el_token_en_claro():
    a = _almacen(Reloj())
    token = a.abrir(1)
    guardado = repr(vars(a))
    assert token not in guardado and hashlib.sha256(token.encode()).hexdigest() in guardado


def test_la_inactividad_cierra_y_cada_uso_la_renueva():
    reloj = Reloj()
    a = _almacen(reloj, inactividad=100)
    token = a.abrir(1)
    reloj.t += 90
    assert a.resolver(token) == 1            # uso a los 90 s: renueva
    reloj.t += 90
    assert a.resolver(token) == 1            # 90 s después del último uso: sigue viva
    reloj.t += 101
    assert a.resolver(token) is None         # más de 100 s sin usarla: caducó


def test_la_duracion_maxima_cierra_aunque_se_use_sin_parar():
    reloj = Reloj()
    a = _almacen(reloj, inactividad=100, maxima=250)
    token = a.abrir(1)
    for _ in range(2):
        reloj.t += 90
        assert a.resolver(token) == 1
    reloj.t += 90                             # 270 s desde que se abrió
    assert a.resolver(token) is None


def test_cerrar_invalida_el_token_y_es_idempotente():
    a = _almacen(Reloj())
    token = a.abrir(1)
    a.cerrar(token)
    a.cerrar(token)
    a.cerrar(None)
    assert a.resolver(token) is None


def test_cerrar_de_usuario_cierra_todas_sus_sesiones_y_solo_las_suyas():
    a = _almacen(Reloj())
    mias = [a.abrir(1), a.abrir(1)]
    otra = a.abrir(2)
    a.cerrar_de_usuario(1)
    assert [a.resolver(t) for t in mias] == [None, None] and a.resolver(otra) == 2
