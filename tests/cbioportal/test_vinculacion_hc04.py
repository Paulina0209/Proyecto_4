"""Pacientes de cBioPortal en HC-04: episodio, biopsias por muestra y
biomarcadores accionables pendientes de confirmación."""

from cbioportal import importar_paciente
from historia_clinica.biopsias_biomarcadores import (
    PENDIENTE_CONFIRMACION,
    biomarcadores_clave,
    biopsias_de_paciente,
    confirmar_biomarcador,
    episodios_de_paciente,
)
from tx_clinica.patient_facts import construir_facts_paciente

from .conftest import ESTUDIO


def test_crea_el_episodio_y_una_biopsia_por_muestra(conn, fuente):
    r = importar_paciente(conn, fuente, ESTUDIO, "P-0000036")

    (episodio,) = episodios_de_paciente(conn, r.paciente_id)
    assert (episodio.descripcion, episodio.tipo_cancer, episodio.origen) == ("Lung Adenocarcinoma", "NSCLC", "cbioportal")
    (biopsia,) = biopsias_de_paciente(conn, r.paciente_id)
    assert (biopsia.episodio_id, biopsia.muestra_externa) == (episodio.id, "P-0000036-T01-IM3")
    assert biopsia.diagnostico_histologico == "Lung Adenocarcinoma"


def test_la_fusion_alk_queda_pendiente_y_no_llega_a_tx_sin_confirmar(conn, fuente):
    r = importar_paciente(conn, fuente, ESTUDIO, "P-0000036")

    (clave,) = biomarcadores_clave(conn, r.paciente_id)
    assert (clave.biomarcador, clave.relevancia, clave.variante) == ("ALK", PENDIENTE_CONFIRMACION, "EML4-ALK")
    assert clave.biopsia_id == biopsias_de_paciente(conn, r.paciente_id)[0].id
    assert "alk_status" not in construir_facts_paciente(conn, r.paciente_id)

    confirmar_biomarcador(conn, r.paciente_id, clave.biomarcador_id, "dra.ruiz", "reordenado")
    assert construir_facts_paciente(conn, r.paciente_id)["alk_status"] == "rearranged"


def test_una_variante_no_sensibilizante_no_se_destaca(conn, fuente):
    r = importar_paciente(conn, fuente, ESTUDIO, "P-0000036")

    assert all(b.biomarcador != "EGFR" for b in biomarcadores_clave(conn, r.paciente_id))  # EGFR V834L


def test_con_dos_primarios_no_se_vincula_nada(conn, fuente):
    r = importar_paciente(conn, fuente, ESTUDIO, "P-0000012")

    assert r.sincronizacion.exito
    assert episodios_de_paciente(conn, r.paciente_id) == []
    assert biopsias_de_paciente(conn, r.paciente_id) == []


def test_reimportar_no_duplica(conn, fuente):
    importar_paciente(conn, fuente, ESTUDIO, "P-0000036")
    r = importar_paciente(conn, fuente, ESTUDIO, "P-0000036")

    assert len(episodios_de_paciente(conn, r.paciente_id)) == 1
    assert len(biopsias_de_paciente(conn, r.paciente_id)) == 1
    assert len(biomarcadores_clave(conn, r.paciente_id)) == 1


def test_un_fallo_de_hc04_no_deshace_la_importacion(conn, fuente, monkeypatch):
    import cbioportal.importador as importador

    def falla(*args, **kwargs):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(importador, "marcar_potencialmente_accionables", falla)
    r = importar_paciente(conn, fuente, ESTUDIO, "P-0000036")

    assert r.sincronizacion.exito
    biomarcadores = conn.execute("SELECT COUNT(*) FROM biomarcadores WHERE paciente_id = ?", (r.paciente_id,)).fetchone()[0]
    assert biomarcadores > 0  # la historia de HC-01 quedó importada
    assert episodios_de_paciente(conn, r.paciente_id) == []  # el rollback deshizo solo la parte de HC-04
