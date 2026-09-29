"""CFG-01 — Configuración de guías clínicas institucionales."""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from auditoria.models import TipoAccion
from auditoria.registro_acceso import obtener_eventos_de_usuario
from configuracion.guias_institucionales import (
    ProtocoloInterno,
    buscar_evidencia_institucional,
    configuracion_en_fecha,
    configurar_guias,
    crear_conexion,
    historial_configuracion,
    modulos_habilitados,
    obtener_configuracion_vigente,
)
from evidencia_clinica import EvidenceSearchService
from seguridad.models import Rol, Usuario

ADMIN_CLINICO = Usuario(id=1, nombre_usuario="adm.clinico", rol=Rol.ADMINISTRADOR_CLINICO, activo=True)
ONCOLOGA = Usuario(id=2, nombre_usuario="dra.gomez", rol=Rol.ONCOLOGO, activo=True)
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
#: sclc_pembrolizumab_review no aparece: es un borrador sin contenido cuyo
#: metadata.yaml no declara `organization` en la raíz, así que el catálogo
#: de EV-01 no lo asocia a ninguna organización.
MODULOS_ESMO = {
    "breast_early_tnbc", "breast_metastatic_tnbc", "cutaneous_melanoma", "nsclc_early_locally_advanced",
    "nsclc_metastatic_non_oncogene", "nsclc_metastatic_oncogene_addicted",
    "renal_cell_carcinoma_advanced_metastatic", "renal_cell_carcinoma_localized_adjuvant",
    "uveal_melanoma",
}


@pytest.fixture
def conn():
    connection = crear_conexion()
    yield connection
    connection.close()


def _configurar(conn, organizaciones=("ESMO",), usuario=ADMIN_CLINICO, motivo="Acta del comité 2026-09", **kw):
    return configurar_guias(conn, usuario, organizaciones, motivo, ahora=kw.pop("ahora", T0), **kw)


# --- Configuración por defecto ---


def test_sin_configurar_se_usan_todas_las_guias_disponibles(conn):
    configuracion = obtener_configuracion_vigente(conn)

    assert configuracion.es_por_defecto_del_sistema
    assert configuracion.version is None
    assert configuracion.organizaciones == ("ESMO",)  # NCCN no tiene módulos computables hoy
    assert set(configuracion.modulos_habilitados) == MODULOS_ESMO
    assert configuracion.advertencias


# --- El administrador clínico elige las guías por defecto ---


def test_administrador_clinico_configura_las_guias_por_defecto(conn):
    resultado = _configurar(conn, ["esmo"])

    assert resultado.exito
    vigente = obtener_configuracion_vigente(conn)
    assert not vigente.es_por_defecto_del_sistema
    assert vigente.version == 1
    assert vigente.organizaciones == ("ESMO",)
    assert vigente.configurado_por == ADMIN_CLINICO.id
    assert vigente.motivo == "Acta del comité 2026-09"
    assert set(modulos_habilitados(conn)) == MODULOS_ESMO


def test_guia_conjunta_esmo_euracan_pertenece_a_esmo(conn):
    _configurar(conn, ["ESMO"])

    assert "uveal_melanoma" in modulos_habilitados(conn)


def test_orden_de_prioridad_y_advertencia_por_organizacion_sin_modulos(conn):
    resultado = _configurar(conn, ["NCCN", "ESMO"])

    assert resultado.exito
    assert resultado.configuracion.organizaciones == ("NCCN", "ESMO")
    assert any("NCCN" in a and "no tiene módulos" in a for a in resultado.advertencias)
    assert set(resultado.configuracion.modulos_habilitados) == MODULOS_ESMO


def test_protocolo_interno_propio(conn):
    protocolo = ProtocoloInterno("Protocolo institucional de mama v3", "DOC-ONC-017")

    resultado = _configurar(conn, ["ESMO"], protocolo_interno=protocolo)

    assert resultado.exito
    assert obtener_configuracion_vigente(conn).protocolo_interno == protocolo
    assert any("protocolo interno" in a for a in resultado.advertencias)


def test_configuracion_sin_modulos_computables_exige_confirmacion(conn):
    protocolo = ProtocoloInterno("Protocolo propio", "DOC-1")

    sin_confirmar = _configurar(conn, ["NCCN"])
    solo_protocolo = _configurar(conn, [], protocolo_interno=protocolo)
    confirmado = _configurar(conn, ["NCCN"], confirmar_sin_modulos=True)

    assert not sin_confirmar.exito and "ningún módulo" in sin_confirmar.motivo_rechazo
    assert not solo_protocolo.exito
    assert confirmado.exito
    assert modulos_habilitados(conn) == ()


@pytest.mark.parametrize(
    "organizaciones, kw, texto",
    [
        (["ESMOO"], {}, "no reconocida"),
        (["ESMO", "esmo"], {}, "repetida"),
        ([], {}, "al menos una"),
        (["ESMO"], {"motivo": "  "}, "motivo"),
        (["ESMO"], {"protocolo_interno": ProtocoloInterno("Solo nombre", " ")}, "protocolo interno"),
    ],
)
def test_configuraciones_invalidas_se_rechazan(conn, organizaciones, kw, texto):
    resultado = _configurar(conn, organizaciones, **kw)

    assert not resultado.exito
    assert texto in resultado.motivo_rechazo
    assert obtener_configuracion_vigente(conn).es_por_defecto_del_sistema


# --- Control de acceso (SEC-01) ---


def test_solo_el_administrador_clinico_puede_configurar(conn):
    resultado = _configurar(conn, ["NCCN", "ESMO"], usuario=ONCOLOGA)

    assert not resultado.exito
    assert "administrador_clinico" in resultado.motivo_rechazo
    assert obtener_configuracion_vigente(conn).es_por_defecto_del_sistema


def test_administrador_inactivo_no_puede_configurar(conn):
    inactivo = Usuario(id=3, nombre_usuario="x", rol=Rol.ADMINISTRADOR_CLINICO, activo=False)

    assert not _configurar(conn, usuario=inactivo).exito


# --- Versionado y trazabilidad ---


def test_cada_cambio_es_una_version_nueva_y_se_conserva_el_historial(conn):
    _configurar(conn, ["ESMO"], ahora=T0)
    _configurar(conn, ["NCCN", "ESMO"], motivo="Adopción de NCCN como referencia principal",
                ahora=T0 + timedelta(days=30))

    historial = historial_configuracion(conn)

    assert [c.version for c in historial] == [2, 1]
    assert historial[0].organizaciones == ("NCCN", "ESMO")
    assert historial[1].organizaciones == ("ESMO",)


def test_configuracion_vigente_en_una_fecha_pasada(conn):
    _configurar(conn, ["ESMO"], ahora=T0)
    _configurar(conn, ["NCCN", "ESMO"], ahora=T0 + timedelta(days=30))

    assert configuracion_en_fecha(conn, T0 - timedelta(days=1)) is None
    assert configuracion_en_fecha(conn, T0 + timedelta(days=10)).version == 1
    assert configuracion_en_fecha(conn, T0 + timedelta(days=40)).version == 2


def test_la_configuracion_no_se_puede_editar_ni_borrar(conn):
    _configurar(conn)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE configuracion_guias_institucionales SET organizaciones_json = '[]'")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM configuracion_guias_institucionales")


def test_cambios_e_intentos_denegados_quedan_en_la_auditoria(conn):
    _configurar(conn, ["ESMO"])
    _configurar(conn, ["NCCN"], usuario=ONCOLOGA)

    eventos_admin = obtener_eventos_de_usuario(conn, ADMIN_CLINICO.id)
    eventos_oncologa = obtener_eventos_de_usuario(conn, ONCOLOGA.id)

    assert [e.accion for e in eventos_admin] == [TipoAccion.CONFIGURAR_GUIAS]
    assert "v1: ESMO" in eventos_admin[0].detalle and "Acta del comité" in eventos_admin[0].detalle
    assert eventos_oncologa[0].detalle.startswith("DENEGADO")


# --- Integración con EV-01 ---


def test_ev01_busca_solo_en_las_guias_institucionales(conn):
    servicio = EvidenceSearchService(Path(__file__).resolve().parents[2])
    sin_filtro = servicio.search("cáncer de mama triple negativo")

    _configurar(conn, ["ESMO"])
    con_esmo = buscar_evidencia_institucional(conn, "cáncer de mama triple negativo", servicio)
    _configurar(conn, ["NCCN"], confirmar_sin_modulos=True)
    con_nccn = buscar_evidencia_institucional(conn, "cáncer de mama triple negativo", servicio)

    assert [r.document.module_id for r in con_esmo] == [r.document.module_id for r in sin_filtro]
    assert con_nccn == []


def test_ev01_sin_organizaciones_se_comporta_como_antes():
    servicio = EvidenceSearchService(Path(__file__).resolve().parents[2])

    assert servicio.search("melanoma") == servicio.search("melanoma", organizations=None)
