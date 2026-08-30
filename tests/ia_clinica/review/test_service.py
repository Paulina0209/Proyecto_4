"""Pruebas de aceptación de IA-03 — Revisión y aprobación de notas clínicas."""

from datetime import datetime, timezone

import pytest

from ia_clinica.review.models import (
    EstadoNota,
    NotaYaAprobadaError,
    RevisionNoEncontradaError,
    RevisionYaExisteError,
)
from ia_clinica.review.service import aprobar_nota, editar_seccion, iniciar_revision, obtener_revision

AHORA = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# AC1 — Dado que existe un borrador generado por IA, cuando lo reviso,
# puedo modificar manualmente su contenido antes de aprobarlo.
# ---------------------------------------------------------------------------
class TestModificacionManual:
    def test_puedo_editar_una_seccion_del_borrador(self, conn, borrador_ia):
        iniciar_revision(conn, borrador_ia, ahora=AHORA)

        revision = editar_seccion(
            conn,
            nota_id=borrador_ia.consult_id,
            seccion_key="A",
            nuevo_contenido="Impresión corregida por el oncólogo.",
            autor="dr. Pérez",
            ahora=AHORA,
        )

        assert revision.contenido_actual["A"] == "Impresión corregida por el oncólogo."
        # El resto de secciones no editadas queda intacto.
        assert revision.contenido_actual["S"] == borrador_ia.get_section("S").content

    def test_el_borrador_original_de_ia_02_nunca_se_modifica(self, conn, borrador_ia):
        contenido_original_seccion_a = borrador_ia.get_section("A").content
        iniciar_revision(conn, borrador_ia, ahora=AHORA)

        editar_seccion(conn, borrador_ia.consult_id, "A", "texto nuevo", autor="dr. Pérez", ahora=AHORA)

        assert borrador_ia.get_section("A").content == contenido_original_seccion_a

        revision = obtener_revision(conn, borrador_ia.consult_id)
        assert revision.contenido_ia_original["A"] == contenido_original_seccion_a


# ---------------------------------------------------------------------------
# AC2 — Dado que hago cambios sobre el borrador, cuando guardo los
# cambios, el sistema conserva la versión modificada para su revisión
# posterior.
# ---------------------------------------------------------------------------
class TestPersistenciaDeCambios:
    def test_la_edicion_guardada_se_puede_recuperar_despues(self, conn, borrador_ia):
        iniciar_revision(conn, borrador_ia, ahora=AHORA)
        editar_seccion(conn, borrador_ia.consult_id, "A", "versión editada", autor="dr. Pérez", ahora=AHORA)

        revision_recuperada = obtener_revision(conn, borrador_ia.consult_id)

        assert revision_recuperada.contenido_actual["A"] == "versión editada"
        assert revision_recuperada.fue_editada()
        assert len(revision_recuperada.historial_ediciones) == 1
        edicion = revision_recuperada.historial_ediciones[0]
        assert edicion.autor == "dr. Pérez"
        assert edicion.contenido_nuevo == "versión editada"

    def test_varias_ediciones_se_acumulan_en_el_historial(self, conn, borrador_ia):
        iniciar_revision(conn, borrador_ia, ahora=AHORA)
        editar_seccion(conn, borrador_ia.consult_id, "A", "primer cambio", autor="dr. Pérez", ahora=AHORA)
        editar_seccion(conn, borrador_ia.consult_id, "A", "segundo cambio", autor="dr. Pérez", ahora=AHORA)

        revision = obtener_revision(conn, borrador_ia.consult_id)

        assert len(revision.historial_ediciones) == 2
        assert revision.contenido_actual["A"] == "segundo cambio"


# ---------------------------------------------------------------------------
# AC3 — Dado que una nota aún no ha sido aprobada, cuando cierro sesión o
# abandono el proceso de edición, permanece identificada como "borrador no
# confirmado".
# ---------------------------------------------------------------------------
class TestPermaneceComoBorradorSinAprobacion:
    def test_recien_iniciada_una_revision_queda_como_borrador(self, conn, borrador_ia):
        revision = iniciar_revision(conn, borrador_ia, ahora=AHORA)

        assert revision.estado is EstadoNota.DRAFT
        assert not revision.es_nota_oficial()
        assert revision.etiqueta_estado().startswith("BORRADOR NO CONFIRMADO")

    def test_una_conexion_nueva_sigue_viendo_el_estado_borrador(self, conn, borrador_ia, tmp_path):
        # Simula "cerrar sesión": se usa un archivo real (no :memory:, que
        # desaparece con la conexión) y se abre una conexión NUEVA para
        # leer el estado, en vez de reutilizar el objeto Python original.
        from ia_clinica.review import store as store_module

        ruta_db = str(tmp_path / "revisiones.db")
        conn_sesion_1 = store_module.crear_conexion(ruta_db)
        iniciar_revision(conn_sesion_1, borrador_ia, ahora=AHORA)
        editar_seccion(conn_sesion_1, borrador_ia.consult_id, "A", "cambio antes de cerrar sesión", autor="dr. Pérez", ahora=AHORA)
        conn_sesion_1.close()

        conn_sesion_2 = store_module.crear_conexion(ruta_db)
        revision = obtener_revision(conn_sesion_2, borrador_ia.consult_id)

        assert not revision.es_nota_oficial()
        assert revision.estado is EstadoNota.DRAFT
        assert revision.contenido_actual["A"] == "cambio antes de cerrar sesión"
        conn_sesion_2.close()


# ---------------------------------------------------------------------------
# AC4 — Dado que estoy satisfecho con el contenido de la nota, cuando
# realizo explícitamente la acción de aprobación, el sistema cambia su
# estado de borrador a nota aprobada.
# ---------------------------------------------------------------------------
class TestAprobacionExplicita:
    def test_aprobar_cambia_el_estado_a_approved(self, conn, borrador_ia):
        iniciar_revision(conn, borrador_ia, ahora=AHORA)

        revision = aprobar_nota(conn, borrador_ia.consult_id, aprobado_por="dra. Ríos", ahora=AHORA)

        assert revision.estado is EstadoNota.APPROVED
        assert revision.es_nota_oficial()
        assert revision.aprobacion is not None
        assert revision.aprobacion.aprobado_por == "dra. Ríos"

    def test_no_existe_ninguna_transicion_automatica_a_approved(self, conn, borrador_ia):
        # Ni iniciar la revisión ni guardar ediciones cambian el estado.
        iniciar_revision(conn, borrador_ia, ahora=AHORA)
        editar_seccion(conn, borrador_ia.consult_id, "A", "cambio", autor="dr. Pérez", ahora=AHORA)

        revision = obtener_revision(conn, borrador_ia.consult_id)
        assert revision.estado is EstadoNota.DRAFT

    def test_aprobar_exige_un_identificador_no_vacio_del_medico(self, conn, borrador_ia):
        iniciar_revision(conn, borrador_ia, ahora=AHORA)

        with pytest.raises(ValueError):
            aprobar_nota(conn, borrador_ia.consult_id, aprobado_por="   ", ahora=AHORA)

    def test_no_se_puede_volver_a_aprobar_una_nota_ya_aprobada(self, conn, borrador_ia):
        iniciar_revision(conn, borrador_ia, ahora=AHORA)
        aprobar_nota(conn, borrador_ia.consult_id, aprobado_por="dra. Ríos", ahora=AHORA)

        with pytest.raises(NotaYaAprobadaError):
            aprobar_nota(conn, borrador_ia.consult_id, aprobado_por="otro medico", ahora=AHORA)

    def test_no_se_puede_editar_una_nota_ya_aprobada(self, conn, borrador_ia):
        iniciar_revision(conn, borrador_ia, ahora=AHORA)
        aprobar_nota(conn, borrador_ia.consult_id, aprobado_por="dra. Ríos", ahora=AHORA)

        with pytest.raises(NotaYaAprobadaError):
            editar_seccion(conn, borrador_ia.consult_id, "A", "cambio tardío", autor="alguien", ahora=AHORA)


# ---------------------------------------------------------------------------
# AC5 — Dado que una nota permanece en estado de borrador, cuando se
# consulta su estado, no puede presentarse como una nota clínica oficial.
# ---------------------------------------------------------------------------
class TestNoOficialMientrasEsBorrador:
    def test_es_nota_oficial_es_false_mientras_no_se_apruebe(self, conn, borrador_ia):
        revision = iniciar_revision(conn, borrador_ia, ahora=AHORA)
        assert revision.es_nota_oficial() is False

        editar_seccion(conn, borrador_ia.consult_id, "A", "cambio", autor="dr. Pérez", ahora=AHORA)
        revision = obtener_revision(conn, borrador_ia.consult_id)
        assert revision.es_nota_oficial() is False

    def test_es_nota_oficial_es_true_solo_tras_aprobar(self, conn, borrador_ia):
        iniciar_revision(conn, borrador_ia, ahora=AHORA)
        revision = aprobar_nota(conn, borrador_ia.consult_id, aprobado_por="dra. Ríos", ahora=AHORA)
        assert revision.es_nota_oficial() is True


# ---------------------------------------------------------------------------
# Regla de negocio adicional: ninguna nota adquiere estado oficial "por
# accidente" — no hay setter directo de estado, y regenerar un borrador
# para una consulta con revisión existente no debe pisarla en silencio.
# ---------------------------------------------------------------------------
class TestIntegridadDelFlujo:
    def test_no_existe_ningun_setter_directo_de_estado_en_el_snapshot(self, conn, borrador_ia):
        revision = iniciar_revision(conn, borrador_ia, ahora=AHORA)
        assert not hasattr(revision, "set_estado")
        assert not hasattr(revision, "aprobar")
        assert not hasattr(revision, "confirmar")

    def test_iniciar_revision_dos_veces_para_la_misma_consulta_falla(self, conn, borrador_ia):
        iniciar_revision(conn, borrador_ia, ahora=AHORA)
        with pytest.raises(RevisionYaExisteError):
            iniciar_revision(conn, borrador_ia, ahora=AHORA)

    def test_consultar_una_revision_inexistente_falla_explicitamente(self, conn):
        with pytest.raises(RevisionNoEncontradaError):
            obtener_revision(conn, "consulta-que-no-existe")
