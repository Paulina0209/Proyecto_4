"""ADM-02 — Métricas de uso del sistema para la dirección médica.

Criterios de aceptación propuestos (el backlog no trae ninguno), de los que se desprenden estas pruebas:

    AC1  Las cifras del tablero (adopción, tiempo ahorrado estimado, alertas y aceptación de las
         recomendaciones de IA) son correctas, comparables con el periodo anterior, y un dato que no
         se puede leer se informa como "no disponible", nunca como cero.
    AC2  Solo el director médico las consulta; todo intento queda en la auditoría (AUD-01) y, sin
         traza, no se entregan datos.
    AC3  Son agregados de la institución: ningún dato por persona, la aceptación de IA se presenta
         con cuidado (nota, distribución, supresión en grupos pequeños) y no sirve para evaluar a
         médicos individuales.
"""
from __future__ import annotations

import dataclasses
import inspect
import json
import sqlite3
from datetime import date, datetime, timezone

import pytest

from administracion import metricas_uso as met
from administracion import usuarios as adm
from administracion.metricas_uso import Coeficiente, FuentesMetricas, Parametros, consultar_metricas
from auditoria.models import TipoAccion
from seguridad.autorizacion import Accion, verificar_permiso
from seguridad.models import Rol, Usuario
from tests.administracion.conftest import AHORA, RAIZ

# Días de referencia (periodo por defecto 2026-09-18..2026-10-17; anterior 2026-08-19..2026-09-17).
EN = "2026-10-01"
EN2 = "2026-09-25"
ANTES = "2026-09-01"
ANTES2 = "2026-08-25"
MUY_ANTES = "2026-07-01"


def _consultar(mundo, **kw):
    return consultar_metricas(mundo.fuentes(), mundo.director, ahora=AHORA, **kw)


@pytest.fixture()
def equipo(mundo):
    mundo.equipo(5, 5)
    return mundo


# ============================================================================
# AC1 — Las cifras son correctas
# ============================================================================


class TestAdopcion:
    def test_cuenta_usuarios_clinicos_activos_y_compara_con_el_periodo_anterior(self, equipo):
        m = equipo
        for u in (m.oncologos[0], m.oncologos[1], m.enfermeras[0]):
            m.acceso(u, EN)
        for u in (m.oncologos[0], m.enfermeras[0], m.enfermeras[1], m.enfermeras[2]):
            m.acceso(u, ANTES)
        m.acceso(m.oncologos[4], MUY_ANTES)  # fuera de ambos periodos: no cuenta en ninguno
        r = _consultar(m).adopcion
        assert r.disponible
        assert (r.usuarios_activos, r.usuarios_elegibles) == (3, 10)
        assert r.tasa_adopcion == pytest.approx(0.3)
        assert r.tasa_adopcion_periodo_anterior == pytest.approx(0.4)

    def test_un_usuario_que_entra_muchas_veces_cuenta_una_sola_vez(self, equipo):
        equipo.acceso(equipo.oncologos[0], EN, veces=7)
        equipo.acceso(equipo.oncologos[0], EN2, veces=3)
        r = _consultar(equipo).adopcion
        assert r.usuarios_activos == 1
        assert dict(r.acciones_por_tipo)["ver"] == 10

    def test_solo_cuentan_oncologia_y_enfermeria_activas(self, equipo):
        m = equipo
        m.acceso(m.auditor, EN, veces=2)
        m.acceso(m.oncologos[0], EN)
        r = _consultar(m).adopcion
        assert (r.usuarios_activos, r.usuarios_elegibles) == (1, 10)
        assert r.eventos_no_atribuibles == 2  # el auditor mira expedientes, pero no es adopción clínica

    def test_una_cuenta_dada_de_baja_sale_del_denominador_y_del_numerador(self, equipo):
        m = equipo
        m.acceso(m.oncologos[2], EN, veces=3)
        m.acceso(m.oncologos[0], EN)
        adm.desactivar_usuario(m.usuarios, m.admin, m.oncologos[2].id, "Renuncia")
        r = _consultar(m).adopcion
        assert (r.usuarios_activos, r.usuarios_elegibles) == (1, 9)
        assert r.tasa_adopcion == pytest.approx(1 / 9, abs=1e-4)  # nunca supera 100 %
        assert r.eventos_no_atribuibles == 3

    def test_ver_el_tablero_no_cuenta_como_uso_del_sistema(self, equipo):
        m = equipo
        m.acceso(m.oncologos[0], EN)
        antes = _consultar(m).adopcion
        for _ in range(3):
            _consultar(m)  # el director consulta (y eso queda en AUD-01)
        despues = _consultar(m).adopcion
        assert despues.usuarios_activos == antes.usuarios_activos == 1
        assert despues.acciones_por_tipo == antes.acciones_por_tipo
        assert "consultar_metricas" not in dict(despues.acciones_por_tipo)
        assert despues.eventos_no_atribuibles == 0

    def test_pacientes_atendidos_son_pacientes_distintos_y_acciones_por_tipo(self, equipo):
        m = equipo
        m.acceso(m.oncologos[0], EN, paciente=1, veces=2)
        m.acceso(m.oncologos[1], EN, paciente=2)
        m.acceso(m.enfermeras[0], EN, TipoAccion.EDITAR, paciente=2)
        m.acceso(m.oncologos[0], EN, TipoAccion.EXPORTAR, paciente=3)
        r = _consultar(m).adopcion
        assert r.pacientes_atendidos == 3
        assert dict(r.acciones_por_tipo) == {"ver": 3, "editar": 1, "exportar": 1}

    def test_desglose_por_rol_solo_en_grupos_de_tamano_suficiente(self, equipo):
        m = equipo
        m.acceso(m.oncologos[0], EN)
        m.acceso(m.oncologos[1], EN)
        por_rol = {r.rol: r for r in _consultar(m).adopcion.por_rol}
        assert (por_rol["oncologo"].usuarios_activos, por_rol["oncologo"].usuarios_elegibles) == (2, 5)
        assert por_rol["oncologo"].tasa_adopcion == pytest.approx(0.4)
        assert por_rol["enfermeria"].usuarios_activos == 0 and not por_rol["enfermeria"].suprimido

    def test_grupos_pequenos_no_se_desglosan(self, mundo):
        mundo.equipo(oncologos=3, enfermeria=2)
        mundo.acceso(mundo.oncologos[0], EN)
        r = _consultar(mundo).adopcion
        assert r.usuarios_activos == 1  # el total institucional sí se muestra
        for rol in r.por_rol:
            assert rol.suprimido and rol.usuarios_activos is None and rol.usuarios_elegibles is None and rol.tasa_adopcion is None

    def test_sin_clinicos_la_tasa_no_se_inventa(self, mundo):
        mundo.director = mundo.usuario("direccion.medica", Rol.DIRECTOR_MEDICO)
        r = _consultar(mundo).adopcion
        assert r.usuarios_elegibles == 0 and r.tasa_adopcion is None

    def test_uso_de_funciones_de_ia_en_el_periodo_y_el_anterior(self, equipo):
        m = equipo
        m.nota_aprobada(EN, 3)
        m.nota_aprobada(ANTES, 1)
        m.decision(m.oncologos[0], EN)
        m.estadificacion("onco.01", EN)
        m.estadificacion("onco.01", EN, disponible=0)  # sin sugerencia: no es "con sugerencia"
        uso = {f.clave: f for f in _consultar(m).adopcion.uso_funciones_ia}
        assert (uso["notas_ia_aprobadas"].total, uso["notas_ia_aprobadas"].total_periodo_anterior) == (3, 1)
        assert uso["decisiones_tratamiento"].total == 1
        assert uso["estadificaciones_con_sugerencia"].total == 1


class TestAlertas:
    def test_cuenta_alertas_revision_conflictos_y_sincronizaciones(self, equipo):
        m = equipo
        m.alerta(EN, "critica", "activa")
        m.alerta(EN, "critica", "revisada")
        m.alerta(EN2, "alta", "revisada")
        m.alerta(ANTES, "critica", "activa")       # periodo anterior
        m.alerta(MUY_ANTES, "critica", "activa")   # fuera de ambos (pero sigue pendiente hoy)
        m.conflicto(EN, "pendiente")
        m.conflicto(EN2, "resuelto")
        m.sincronizacion(EN)
        m.sincronizacion(EN, "fallida")
        m.sincronizacion(ANTES)
        a = _consultar(m).alertas
        assert a.disponible
        assert (a.generadas, a.generadas_periodo_anterior) == (3, 1)
        assert dict(a.por_severidad) == {"alta": 1, "critica": 2}
        assert a.revisadas == 2
        assert a.pendientes_actuales == 3  # "hoy": todas las activas, de cualquier fecha
        assert (a.conflictos_detectados, a.conflictos_pendientes_actuales) == (2, 1)
        assert (a.sincronizaciones_exitosas, a.sincronizaciones_fallidas) == (1, 1)

    def test_cero_alertas_con_fuente_conectada_es_un_cero_real(self, equipo):
        a = _consultar(equipo).alertas
        assert a.disponible and a.generadas == 0 and a.pendientes_actuales == 0


class TestTiempoAhorrado:
    def _sembrar(self, m):
        m.nota_aprobada(EN, 6)
        m.nota_aprobada(ANTES, 3)
        for _ in range(4):
            m.sincronizacion(EN)
        m.sincronizacion(EN, "fallida")  # una sincronización fallida no ahorra tiempo
        m.sincronizacion(ANTES)
        for _ in range(3):
            m.decision(m.oncologos[0], EN)
        m.estadificacion("onco.01", EN)
        m.estadificacion("onco.01", EN2)
        m.estadificacion("onco.01", EN, disponible=0)

    def test_es_una_estimacion_en_rango_a_partir_de_eventos_reales(self, equipo):
        self._sembrar(equipo)
        t = _consultar(equipo).tiempo_ahorrado
        assert t.disponible and t.es_estimacion and not t.subestimado
        # notas 6×(5–12) + sync 4×(3–10) + decisiones 3×(2–8) + estadificaciones 2×(2–6), en horas.
        assert t.horas_min == pytest.approx((6 * 5 + 4 * 3 + 3 * 2 + 2 * 2) / 60, abs=0.05)
        assert t.horas_max == pytest.approx((6 * 12 + 4 * 10 + 3 * 8 + 2 * 6) / 60, abs=0.05)
        assert t.horas_min < t.horas_max
        assert t.horas_min_periodo_anterior == pytest.approx((3 * 5 + 1 * 3) / 60, abs=0.05)
        assert "no medición" in t.nota

    def test_cada_componente_muestra_sus_eventos_y_su_supuesto(self, equipo):
        self._sembrar(equipo)
        comps = {c.clave: c for c in _consultar(equipo).tiempo_ahorrado.componentes}
        assert comps["notas_ia_aprobadas"].eventos == 6
        assert comps["sincronizaciones_exitosas"].eventos == 4
        assert comps["decisiones_tratamiento"].eventos == 3
        assert comps["estadificaciones_con_sugerencia"].eventos == 2
        assert comps["notas_ia_aprobadas"].minutos_min_por_evento == 5
        assert all("sin medir" in c.origen_supuesto for c in comps.values())

    def test_los_supuestos_son_sustituibles(self, equipo):
        self._sembrar(equipo)
        uno_a_uno = {k: Coeficiente(k, k, 60, 60, "estudio propio") for k in met._CLAVES_COEFICIENTES}
        t = consultar_metricas(equipo.fuentes(), equipo.director, ahora=AHORA, coeficientes=uno_a_uno).tiempo_ahorrado
        assert t.horas_min == t.horas_max == 15.0  # 6 + 4 + 3 + 2 eventos, una hora cada uno

    def test_si_falta_una_fuente_se_suma_lo_que_hay_y_se_avisa_la_subestimacion(self, equipo):
        solo_notas = sqlite3.connect(":memory:")
        solo_notas.executescript((RAIZ / "ia_clinica/review/schema.sql").read_text(encoding="utf-8"))
        solo_notas.execute(
            "INSERT INTO revision_notas (nota_id, paciente_ref, contenido_ia_original, contenido_actual, estado, creado_en, aprobado_por, aprobado_en) "
            "VALUES ('a','P','{}','{}','APPROVED','2026-10-01T10:00:00+00:00','x','2026-10-01T10:00:00+00:00')")
        fuentes = FuentesMetricas(equipo.usuarios, [solo_notas])
        t = consultar_metricas(fuentes, equipo.director, ahora=AHORA).tiempo_ahorrado
        assert t.disponible and t.subestimado
        comps = {c.clave: c for c in t.componentes}
        assert comps["notas_ia_aprobadas"].disponible and comps["notas_ia_aprobadas"].eventos == 1
        assert not comps["decisiones_tratamiento"].disponible and comps["decisiones_tratamiento"].eventos is None
        assert t.horas_min == pytest.approx(5 / 60, abs=0.05)

    def test_sin_ninguna_fuente_no_hay_estimacion_en_vez_de_cero(self, equipo):
        t = consultar_metricas(equipo.fuentes(con_expediente=False), equipo.director, ahora=AHORA).tiempo_ahorrado
        assert not t.disponible and t.horas_min is None and t.horas_max is None and t.motivo


class TestAceptacionIA:
    def _decisiones_tx(self, m, aceptadas=18, modificadas=4, confirmadas_como_sugeridas=2, rechazadas=6, dia=EN):
        i = 0
        for _ in range(aceptadas):
            m.decision(m.oncologos[i % 5], dia, "accept", "FOLFOX", "FOLFOX"); i += 1
        for _ in range(modificadas):
            m.decision(m.oncologos[i % 5], dia, "modify", "FOLFOX", "FOLFIRI"); i += 1
        for _ in range(confirmadas_como_sugeridas):  # "modificó" pero el régimen final es el sugerido
            m.decision(m.oncologos[i % 5], dia, "modify", "FOLFOX", "FOLFOX"); i += 1
        for _ in range(rechazadas):
            m.decision(m.oncologos[i % 5], dia, "reject", "FOLFOX", None); i += 1

    def test_tratamiento_distribucion_y_tasa(self, equipo):
        self._decisiones_tx(equipo)
        tx = {d.dominio: d for d in _consultar(equipo).aceptacion_ia.dominios}["TX"]
        assert tx.disponible and not tx.suprimida
        assert tx.total == 30
        assert {c[0]: c[2] for c in tx.categorias} == {"aceptadas": 20, "modificadas": 4, "rechazadas": 6}
        assert tx.tasa_aceptacion == pytest.approx(20 / 30, abs=1e-3)

    def test_estadificacion_solo_cuenta_cuando_habia_sugerencia(self, equipo):
        m = equipo
        for i in range(24):
            m.estadificacion(f"onco.{i % 5 + 1:02d}", EN, difiere=0)
        for i in range(6):
            m.estadificacion(f"onco.{i % 5 + 1:02d}", EN, difiere=1)
        for i in range(10):
            m.estadificacion(f"onco.{i % 5 + 1:02d}", EN, difiere=0, disponible=0)  # nada con qué comparar
        est = {d.dominio: d for d in _consultar(m).aceptacion_ia.dominios}["EST"]
        assert est.total == 30
        assert {c[0]: c[2] for c in est.categorias} == {"coinciden": 24, "difieren": 6}
        assert est.tasa_aceptacion == pytest.approx(0.8)

    def test_decisiones_fuera_del_periodo_no_cuentan(self, equipo):
        self._decisiones_tx(equipo, dia=ANTES)  # periodo anterior
        tx = {d.dominio: d for d in _consultar(equipo).aceptacion_ia.dominios}["TX"]
        assert tx.suprimida and tx.total is None

    def test_diagnostico_se_declara_sin_comparacion(self, equipo):
        ac = _consultar(equipo).aceptacion_ia
        assert any("DX-03" in x for x in ac.dominios_sin_comparacion)
        assert {d.dominio for d in ac.dominios} == {"TX", "EST"}

    def test_los_umbrales_son_configurables(self, equipo):
        for i in range(3):
            equipo.decision(equipo.oncologos[i], EN)
        laxo = consultar_metricas(equipo.fuentes(), equipo.director, ahora=AHORA, parametros=Parametros(min_medicos_tasa=3, min_decisiones_tasa=3))
        tx = {d.dominio: d for d in laxo.aceptacion_ia.dominios}["TX"]
        assert not tx.suprimida and tx.total == 3 and tx.tasa_aceptacion == 1.0


class TestDatoNoDisponibleNoEsCero:
    def test_sin_expediente_conectado_nada_se_informa_como_cero(self, equipo):
        m = consultar_metricas(equipo.fuentes(con_expediente=False), equipo.director, ahora=AHORA)
        assert not m.alertas.disponible and m.alertas.generadas is None and m.alertas.pendientes_actuales is None
        assert not m.aceptacion_ia.disponible and all(not d.disponible for d in m.aceptacion_ia.dominios)
        assert all(f.total is None for f in m.adopcion.uso_funciones_ia)
        assert {"alertas_laboratorio", "decisiones_tratamiento", "revision_notas"} <= set(m.fuentes_no_disponibles)
        assert m.a_dict()["alertas"]["generadas"] is None  # null en el JSON, no 0

    def test_con_expediente_conectado_y_sin_eventos_si_es_cero(self, equipo):
        m = _consultar(equipo)
        assert m.alertas.generadas == 0
        assert all(f.total == 0 for f in m.adopcion.uso_funciones_ia)
        assert m.fuentes_no_disponibles == ()


class TestPeriodoYSerieSemanal:
    def test_por_defecto_son_los_ultimos_30_dias_y_el_anterior_de_igual_duracion(self, equipo):
        p = _consultar(equipo).periodo
        assert (p.desde, p.hasta, p.dias) == ("2026-09-18", "2026-10-17", 30)
        assert (p.desde_anterior, p.hasta_anterior) == ("2026-08-19", "2026-09-17")

    def test_periodo_personalizado(self, equipo):
        p = _consultar(equipo, desde=date(2026, 10, 1), hasta=date(2026, 10, 10)).periodo
        assert (p.dias, p.desde_anterior, p.hasta_anterior) == (10, "2026-09-21", "2026-09-30")

    @pytest.mark.parametrize("desde,hasta", [
        (date(2026, 10, 10), date(2026, 10, 1)),   # al revés
        (date(2025, 1, 1), date(2026, 10, 1)),     # más de 400 días
        (date(2026, 10, 1), date(2026, 10, 30)),   # futuro
    ])
    def test_periodos_invalidos_se_rechazan(self, equipo, desde, hasta):
        with pytest.raises(adm.ErrorValidacion):
            _consultar(equipo, desde=desde, hasta=hasta)

    def test_semanas_cubren_el_periodo_y_suman_el_total(self, equipo):
        m = equipo
        for dia in ("2026-09-18", "2026-09-30", "2026-10-10", "2026-10-17"):
            m.alerta(dia)
            m.nota_aprobada(dia)
        res = _consultar(m)
        s = res.semanas
        assert len(s) == 5 and [x.parcial for x in s] == [False] * 4 + [True]
        assert s[0].inicio == "2026-09-18" and s[-1].fin == "2026-10-17"
        assert sum(x.alertas_generadas for x in s) == res.alertas.generadas == 4
        assert sum(x.horas_ahorradas_min for x in s) == pytest.approx(res.tiempo_ahorrado.horas_min, abs=0.3)
        for a, b in zip(s, s[1:]):  # contiguas, sin huecos ni solapes
            assert (date.fromisoformat(b.inicio) - date.fromisoformat(a.fin)).days == 1

    def test_usuarios_activos_por_semana_se_cuentan_distintos(self, equipo):
        m = equipo
        m.acceso(m.oncologos[0], "2026-09-18")
        m.acceso(m.oncologos[0], "2026-09-20")
        m.acceso(m.oncologos[1], "2026-09-21")
        m.acceso(m.oncologos[0], "2026-09-26")
        s = _consultar(m).semanas
        assert [x.usuarios_activos for x in s[:3]] == [2, 1, 0]  # onco.01 entra dos veces la primera semana y cuenta una sola


class TestCoeficientes:
    def test_los_incluidos_son_validos_y_estan_marcados_como_supuestos(self):
        coef = met.cargar_coeficientes()
        assert set(coef) == set(met._CLAVES_COEFICIENTES)
        assert all(0 <= c.minutos_min <= c.minutos_max for c in coef.values())
        assert all("sin medir" in c.origen for c in coef.values())

    def _yaml(self, tmp_path, cuerpo):
        ruta = tmp_path / "c.yaml"
        ruta.write_text(cuerpo, encoding="utf-8")
        return ruta

    _BASE = "coeficientes:\n" + "".join(f"  {k}:\n    minutos_min: 1\n    minutos_max: 2\n" for k in met._CLAVES_COEFICIENTES)

    def test_un_archivo_propio_se_acepta(self, tmp_path):
        assert met.cargar_coeficientes(self._yaml(tmp_path, self._BASE))["notas_ia_aprobadas"].minutos_max == 2

    def test_la_variable_de_entorno_apunta_al_archivo_de_la_institucion(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COPILOTO_COEFICIENTES_TIEMPO", str(self._yaml(tmp_path, self._BASE)))
        assert met.cargar_coeficientes()["decisiones_tratamiento"].minutos_min == 1

    @pytest.mark.parametrize("cuerpo", [
        "coeficientes:\n  notas_ia_aprobadas:\n    minutos_min: -1\n    minutos_max: 2\n",
        _BASE.replace("minutos_min: 1\n    minutos_max: 2", "minutos_min: 9\n    minutos_max: 2", 1),
        "coeficientes:\n  notas_ia_aprobadas:\n    minutos_min: 1\n    minutos_max: 2\n",
        _BASE + "  inventado:\n    minutos_min: 1\n    minutos_max: 2\n",
        "otra_cosa: 1\n",
        "coeficientes: [1, 2",
    ])
    def test_supuestos_absurdos_o_incompletos_fallan_en_voz_alta(self, tmp_path, cuerpo):
        with pytest.raises(met.ErrorMetricas):
            met.cargar_coeficientes(self._yaml(tmp_path, cuerpo))

    def test_archivo_inexistente(self, tmp_path):
        with pytest.raises(met.ErrorMetricas):
            met.cargar_coeficientes(tmp_path / "no_existe.yaml")


class TestFuentes:
    def test_una_misma_base_pasada_dos_veces_cuenta_una_sola_vez(self, equipo):
        equipo.decision(equipo.oncologos[0], EN)
        duplicada = sqlite3.connect(str(equipo.ruta_expediente))
        fuentes = FuentesMetricas(equipo.usuarios, [equipo.expediente, duplicada])
        uso = {f.clave: f for f in consultar_metricas(fuentes, equipo.director, ahora=AHORA).adopcion.uso_funciones_ia}
        assert uso["decisiones_tratamiento"].total == 1
        duplicada.close()

    def test_las_metricas_suman_entre_bases(self, equipo):
        equipo.acceso(equipo.oncologos[0], EN)  # en la base de accesos
        adm_audit = equipo.usuarios  # y los eventos de la base de usuarios también cuentan
        from auditoria.registro_acceso import registrar_acceso
        registrar_acceso(adm_audit, equipo.oncologos[1].id, TipoAccion.VER, paciente_id=9,
                         ahora=datetime(2026, 10, 2, 9, tzinfo=timezone.utc))
        assert _consultar(equipo).adopcion.usuarios_activos == 2

    def test_abrir_solo_lectura_impide_escribir(self, equipo):
        ro = met.abrir_solo_lectura(equipo.ruta_expediente)
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("DELETE FROM revision_notas")
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("INSERT INTO alertas_laboratorio (paciente_id, laboratorio_id, prueba, valor, limite_superado, fecha) VALUES (1,1,'a','b','c','2026-10-01')")
        ro.close()

    def test_consultar_sobre_conexiones_de_solo_lectura_no_toca_las_bases_clinicas(self, equipo):
        equipo.acceso(equipo.oncologos[0], EN)
        equipo.alerta(EN)
        antes = (equipo.ruta_accesos.read_bytes(), equipo.ruta_expediente.read_bytes())
        ro = [met.abrir_solo_lectura(equipo.ruta_accesos), met.abrir_solo_lectura(equipo.ruta_expediente)]
        m = consultar_metricas(FuentesMetricas(equipo.usuarios, ro), equipo.director, ahora=AHORA)
        assert m.alertas.generadas == 1 and m.adopcion.usuarios_activos == 1
        assert (equipo.ruta_accesos.read_bytes(), equipo.ruta_expediente.read_bytes()) == antes
        for c in ro:
            c.close()


# ============================================================================
# AC2 — Solo el director médico; todo queda auditado
# ============================================================================


def _eventos_metricas(mundo):
    filas = mundo.usuarios.execute(
        "SELECT usuario_id, detalle FROM eventos_acceso WHERE accion = ? ORDER BY id", (TipoAccion.CONSULTAR_METRICAS.value,)).fetchall()
    return [(f[0], json.loads(f[1])) for f in filas]


class TestPermisos:
    def test_solo_el_director_medico_tiene_el_permiso(self):
        con_permiso = {r for r in Rol if verificar_permiso(Usuario(1, "x", r, True), Accion.VER_METRICAS_USO).permitido}
        assert con_permiso == {Rol.DIRECTOR_MEDICO}

    def test_el_director_no_tiene_acceso_clinico_a_expedientes(self):
        director = Usuario(1, "x", Rol.DIRECTOR_MEDICO, True)
        for accion in (Accion.VER_EXPEDIENTE, Accion.EDITAR_EXPEDIENTE, Accion.EXPORTAR_EXPEDIENTE, Accion.CONFIRMAR_TRATAMIENTO,
                       Accion.GESTIONAR_USUARIOS):
            assert not verificar_permiso(director, accion).permitido

    def test_el_director_consulta_y_queda_auditado_sin_los_datos(self, equipo):
        _consultar(equipo, via="panel")
        (uid, detalle), = _eventos_metricas(equipo)
        assert uid == equipo.director.id
        assert detalle == {"operacion": "consultar_metricas", "resultado": "ok", "desde": "2026-09-18", "hasta": "2026-10-17", "via": "panel"}

    @pytest.mark.parametrize("rol", [Rol.ONCOLOGO, Rol.ENFERMERIA, Rol.ADMINISTRATIVO, Rol.AUDITOR, Rol.ADMINISTRADOR_CLINICO, Rol.ADMINISTRADOR])
    def test_cualquier_otro_rol_es_denegado_y_el_intento_queda_auditado(self, mundo, rol):
        mundo.equipo(1, 1)
        intruso = mundo.usuario(f"intruso.{rol.value}", rol)
        with pytest.raises(adm.PermisoDenegadoError):
            consultar_metricas(mundo.fuentes(), intruso, ahora=AHORA)
        (uid, detalle), = _eventos_metricas(mundo)
        assert uid == intruso.id and detalle["resultado"] == "denegado" and rol.value in detalle["motivo"]

    def test_un_director_desactivado_no_consulta(self, equipo):
        adm.desactivar_usuario(equipo.usuarios, equipo.admin, equipo.director.id, "Licencia")
        with pytest.raises(adm.PermisoDenegadoError):
            _consultar(equipo)
        assert _eventos_metricas(equipo)[-1][1]["resultado"] == "denegado"

    def test_el_actor_se_relee_de_la_base_un_director_degradado_ya_no_puede(self, equipo):
        antiguo = equipo.director  # conserva el objeto Usuario con rol director_medico
        adm.asignar_rol(equipo.usuarios, equipo.admin, antiguo.id, "auditor", "Cambio de funciones")
        with pytest.raises(adm.PermisoDenegadoError):
            consultar_metricas(equipo.fuentes(), antiguo, ahora=AHORA)

    def test_un_usuario_inexistente_es_denegado(self, equipo):
        with pytest.raises(adm.PermisoDenegadoError):
            consultar_metricas(equipo.fuentes(), Usuario(9999, "fantasma", Rol.DIRECTOR_MEDICO, True), ahora=AHORA)
        assert _eventos_metricas(equipo)[-1][0] == 9999

    def test_si_la_traza_no_se_puede_escribir_no_se_entregan_datos(self, equipo):
        equipo.usuarios.execute(
            "CREATE TRIGGER sin_traza BEFORE INSERT ON eventos_acceso WHEN NEW.accion = 'consultar_metricas' "
            "BEGIN SELECT RAISE(ABORT, 'no se puede auditar'); END")
        equipo.usuarios.commit()
        with pytest.raises(sqlite3.Error):
            _consultar(equipo)

    def test_un_periodo_invalido_no_deja_una_consulta_exitosa_en_la_auditoria(self, equipo):
        with pytest.raises(adm.ErrorValidacion):
            _consultar(equipo, desde=date(2026, 10, 10), hasta=date(2026, 10, 1))
        assert [d["resultado"] for _, d in _eventos_metricas(equipo)] == []


# ============================================================================
# AC3 — Agregados de la institución; nada por persona; aceptación con cuidado
# ============================================================================

_CAMPOS_DE_PERSONA = {"usuario_id", "autor", "autor_id", "oncologo_id", "medico", "medico_id", "nombre", "nombre_usuario", "persona", "correo"}


def _campos(tipo, vistos=None):
    """Todos los nombres de campo de los dataclasses de salida, recursivamente."""
    vistos = vistos if vistos is not None else set()
    if tipo in vistos or not dataclasses.is_dataclass(tipo):
        return set()
    vistos.add(tipo)
    nombres = set()
    for f in dataclasses.fields(tipo):
        nombres.add(f.name)
        for arg in _tipos_en(f.type):
            nombres |= _campos(arg, vistos)
    return nombres


def _tipos_en(anotacion):
    import typing
    if isinstance(anotacion, str):
        anotacion = eval(anotacion, vars(met))  # noqa: S307 - anotaciones del propio módulo
    salida = [anotacion]
    for a in getattr(anotacion, "__args__", ()) or ():
        salida += _tipos_en(a)
    return salida


class TestSoloAgregados:
    def test_ninguna_estructura_de_salida_tiene_campos_de_persona(self):
        assert not (_campos(met.MetricasUso) & _CAMPOS_DE_PERSONA)

    def test_no_existe_forma_de_pedir_las_cifras_de_una_persona(self):
        parametros = set(inspect.signature(consultar_metricas).parameters)
        assert parametros == {"fuentes", "actor", "desde", "hasta", "via", "ahora", "parametros", "coeficientes"}

    def test_ni_el_json_ni_el_panel_contienen_nombres_ni_ids_de_usuario(self, equipo):
        from administracion.panel_metricas import renderizar_panel
        m = equipo
        for u in m.oncologos + m.enfermeras:
            m.acceso(u, EN)
        for i in range(30):
            m.decision(m.oncologos[i % 5], EN)
            m.estadificacion(m.nombres[m.oncologos[i % 5].id], EN)
        res = _consultar(m)
        texto = json.dumps(res.a_dict(), ensure_ascii=False) + renderizar_panel(res)
        for nombre in m.nombres.values():
            assert nombre not in texto
        for nombre in ("Persona onco", "Persona enf"):
            assert nombre not in texto
        assert "oncologo_id" not in texto and "autor" not in texto.replace("autoriz", "")

    def test_el_json_serializa_sin_perder_estructura(self, equipo):
        d = _consultar(equipo).a_dict()
        assert set(d) == {"generado_en", "periodo", "adopcion", "tiempo_ahorrado", "alertas", "aceptacion_ia", "semanas", "fuentes_no_disponibles"}
        json.dumps(d)  # no lanza


class TestAceptacionConCuidado:
    def _tx(self, m, medicos: int, decisiones: int):
        for i in range(decisiones):
            m.decision(m.oncologos[i % medicos], EN, "accept" if i % 3 else "reject", "FOLFOX", "FOLFOX" if i % 3 else None)

    def test_siempre_trae_la_nota_de_interpretacion(self, equipo):
        nota = _consultar(equipo).aceptacion_ia.nota_interpretacion
        assert "tasa baja no es negativa" in nota and "No es una medida del desempeño de ningún médico" in nota

    def test_pocos_medicos_se_suprime_aunque_haya_muchas_decisiones(self, equipo):
        self._tx(equipo, medicos=4, decisiones=60)  # 4 < 5 médicos
        tx = {d.dominio: d for d in _consultar(equipo).aceptacion_ia.dominios}["TX"]
        assert tx.suprimida and tx.disponible

    def test_un_solo_medico_muy_activo_se_suprime(self, equipo):
        self._tx(equipo, medicos=1, decisiones=100)
        tx = {d.dominio: d for d in _consultar(equipo).aceptacion_ia.dominios}["TX"]
        assert tx.suprimida

    def test_pocas_decisiones_se_suprime_aunque_haya_muchos_medicos(self, equipo):
        self._tx(equipo, medicos=5, decisiones=29)
        assert {d.dominio: d for d in _consultar(equipo).aceptacion_ia.dominios}["TX"].suprimida

    def test_en_el_umbral_justo_se_muestra(self, equipo):
        self._tx(equipo, medicos=5, decisiones=30)
        assert not {d.dominio: d for d in _consultar(equipo).aceptacion_ia.dominios}["TX"].suprimida

    def test_suprimida_no_deja_ninguna_cifra_que_permita_reconstruirla(self, equipo):
        self._tx(equipo, medicos=2, decisiones=20)
        tx = {d.dominio: d for d in _consultar(equipo).aceptacion_ia.dominios}["TX"]
        assert tx.suprimida and tx.total is None and tx.categorias == () and tx.tasa_aceptacion is None
        assert tx.motivo and "personas concretas" in tx.motivo

    def test_la_supresion_de_estadificacion_cuenta_autores_distintos(self, equipo):
        for i in range(40):
            equipo.estadificacion("onco.01" if i % 2 else "onco.02", EN)  # 40 casos, solo 2 autores
        est = {d.dominio: d for d in _consultar(equipo).aceptacion_ia.dominios}["EST"]
        assert est.suprimida

    def test_se_presenta_como_distribucion_nunca_como_un_unico_numero(self, equipo):
        self._tx(equipo, medicos=5, decisiones=30)
        tx = {d.dominio: d for d in _consultar(equipo).aceptacion_ia.dominios}["TX"]
        assert len(tx.categorias) >= 2 and sum(c[2] for c in tx.categorias) == tx.total
