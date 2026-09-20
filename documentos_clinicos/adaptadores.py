"""Traduce salidas concretas del repositorio al modelo genérico de DOC-02.

La historia de usuario permite exportar "el resumen del caso **o** el
expediente completo". Este módulo implementa ambos caminos, cada uno
traduciendo su fuente real a un :class:`~documentos_clinicos.pdf_export.DocumentoExportable`:

    - :func:`resumen_caso_a_documento_exportable`: a partir de un
      ``CaseSummary`` (resumen de caso para junta médica/interconsulta,
      `ia_clinica.summary`).
    - :func:`expediente_completo_a_documento_exportable`: directamente
      desde `historia_clinica_mock` — datos del paciente, todas sus
      consultas, laboratorios, imagenología, biomarcadores y
      comorbilidades.

`pdf_export.py` (el renderizador) no importa nada de este módulo ni al
revés en sentido inverso: la dependencia va siempre de aquí hacia allá.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from historia_clinica_mock.repository import (
    biomarcadores_de_paciente,
    comorbilidades_de_paciente,
    imagenologia_de_paciente,
    laboratorios_de_paciente,
    listar_consultas,
    obtener_paciente,
)
from historia_clinica_mock.adapters import PacienteNoEncontradoError

from documentos_clinicos.pdf_export import (
    BloqueTabla,
    BloqueTexto,
    DocumentoExportable,
    SeccionDocumento,
)
from ia_clinica.summary.models import CaseSummary


def resumen_caso_a_documento_exportable(resumen: CaseSummary) -> DocumentoExportable:
    """Traduce un ``CaseSummary`` (resumen de caso) a un documento exportable.

    Conserva el disclaimer de IA y, si el resumen tiene secciones
    marcadas como faltantes, lo agrega también como advertencia visible
    en el PDF exportado — el hecho de exportarlo a PDF no debe hacer que
    esa información desactualizada/incompleta se pierda de vista.
    """

    secciones = tuple(
        SeccionDocumento(titulo=seccion.label, bloques=(BloqueTexto(seccion.content),))
        for seccion in resumen.sections
    )

    advertencias = list(resumen.warnings)
    faltantes = resumen.secciones_faltantes()
    if faltantes:
        advertencias.insert(
            0,
            "Este resumen tiene secciones sin información suficiente en el "
            f"expediente: {', '.join(faltantes)}.",
        )

    return DocumentoExportable(
        titulo="Resumen de caso — Junta médica / interconsulta",
        paciente_ref=resumen.patient_ref,
        generado_en=resumen.generated_at,
        secciones=secciones,
        disclaimer=resumen.disclaimer,
        advertencias=tuple(advertencias),
    )


_DISCLAIMER_EXPEDIENTE = (
    "Documento generado automáticamente a partir del expediente clínico "
    "registrado en el sistema. Verifique la información con el expediente "
    "oficial antes de tomar decisiones clínicas a partir de este documento."
)


def expediente_completo_a_documento_exportable(
    conn: sqlite3.Connection, paciente_id: int, ahora: datetime | None = None
) -> DocumentoExportable:
    """Construye el documento exportable del expediente completo de un paciente.

    A diferencia del resumen de caso (redactado por un LLM sobre
    hallazgos no estructurados), este camino no interpreta ni resume
    nada: cada tabla es una copia directa de las filas reales de
    `historia_clinica_mock`, en el mismo espíritu de trazabilidad que el
    resto del proyecto.

    Lanza ``PacienteNoEncontradoError`` si el paciente no existe.
    """

    paciente = obtener_paciente(conn, paciente_id)
    if paciente is None:
        raise PacienteNoEncontradoError(f"No existe ningún paciente con id={paciente_id}.")

    secciones = []

    secciones.append(
        SeccionDocumento(
            titulo="Datos del paciente",
            bloques=(
                BloqueTabla(
                    encabezados=("Campo", "Valor"),
                    filas=(
                        ("Nombre", paciente.nombre),
                        ("Fecha de nacimiento", paciente.fecha_nacimiento),
                        ("Sexo", paciente.sexo),
                        ("Identificación", paciente.identificacion),
                        ("Diagnóstico principal", paciente.diagnostico_principal or "No registrado"),
                        ("Estadio", paciente.estadio or "No registrado"),
                    ),
                ),
            ),
        )
    )

    consultas = listar_consultas(conn, paciente_id)
    if consultas:
        secciones.append(
            SeccionDocumento(
                titulo="Consultas",
                bloques=tuple(
                    BloqueTexto(f"{consulta.fecha} — {consulta.motivo}\n{consulta.notas_libres}")
                    for consulta in consultas
                ),
            )
        )

    laboratorios = laboratorios_de_paciente(conn, paciente_id)
    if laboratorios:
        secciones.append(
            SeccionDocumento(
                titulo="Laboratorios",
                bloques=(
                    BloqueTabla(
                        encabezados=("Fecha", "Prueba", "Valor", "Unidad", "Referencia", "Alterado"),
                        filas=tuple(
                            (
                                lab.fecha,
                                lab.prueba,
                                lab.valor,
                                lab.unidad or "—",
                                lab.rango_referencia or "—",
                                "Sí" if lab.alterado else "No",
                            )
                            for lab in laboratorios
                        ),
                    ),
                ),
            )
        )

    imagenologia = imagenologia_de_paciente(conn, paciente_id)
    if imagenologia:
        secciones.append(
            SeccionDocumento(
                titulo="Imagenología",
                bloques=(
                    BloqueTabla(
                        encabezados=("Fecha", "Modalidad", "Región", "Hallazgos"),
                        filas=tuple(
                            (imagen.fecha, imagen.modalidad, imagen.region, imagen.hallazgos)
                            for imagen in imagenologia
                        ),
                    ),
                ),
            )
        )

    biomarcadores = biomarcadores_de_paciente(conn, paciente_id)
    if biomarcadores:
        secciones.append(
            SeccionDocumento(
                titulo="Biomarcadores",
                bloques=(
                    BloqueTabla(
                        encabezados=("Fecha", "Biomarcador", "Resultado"),
                        filas=tuple(
                            (biomarcador.fecha, biomarcador.biomarcador, biomarcador.resultado)
                            for biomarcador in biomarcadores
                        ),
                    ),
                ),
            )
        )

    comorbilidades = [
        c for c in comorbilidades_de_paciente(conn, paciente_id) if c.condicion != "ninguna_registrada"
    ]
    if comorbilidades:
        secciones.append(
            SeccionDocumento(
                titulo="Comorbilidades",
                bloques=(
                    BloqueTabla(
                        encabezados=("Fecha de registro", "Condición", "Severidad", "Contraindicación ICI"),
                        filas=tuple(
                            (
                                c.fecha_registro,
                                c.condicion,
                                c.severidad or "—",
                                c.tipo_contraindicacion_ici or "No",
                            )
                            for c in comorbilidades
                        ),
                    ),
                ),
            )
        )

    return DocumentoExportable(
        titulo="Expediente clínico completo",
        paciente_ref=f"paciente-{paciente.id}",
        generado_en=ahora or datetime.now(),
        secciones=tuple(secciones),
        disclaimer=_DISCLAIMER_EXPEDIENTE,
    )
