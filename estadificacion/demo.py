"""Demo end-to-end de EST-01/EST-02/EST-03: expediente mock -> estadificación.

Ejecútalo con:

    python -m estadificacion.demo

No requiere ninguna llave de API ni proveedor externo: el sistema de
estadificación aplicable sale del catálogo versionado en
`estadificacion/staging_systems.py` y cada componente se traza hasta la fila
exacta de `datos_clinicos_estructurados` en `historia_clinica_mock`.
"""

from historia_clinica_mock.db import crear_conexion
from historia_clinica_mock.repository import obtener_paciente
from historia_clinica_mock.seed import sembrar_datos_sinteticos

from estadificacion.builder import proponer_estadificacion
from estadificacion.confirmacion import (
    confirmar_estadificacion,
    crear_conexion as crear_conexion_confirmaciones,
    obtener_estadificacion_vigente,
)
from estadificacion.incompleta import analizar_estadificacion_incompleta


def _mostrar_propuesta(titulo: str, conn, paciente_id: int):
    print("=" * 74)
    print(titulo)
    print("=" * 74)

    paciente = obtener_paciente(conn, paciente_id)
    if paciente is not None:
        print(f"Diagnóstico principal: {paciente.diagnostico_principal}")
        print(f"Estadio registrado en el expediente: {paciente.estadio or 'N/D'}")

    propuesta = proponer_estadificacion(conn, paciente_id)
    print()
    print(f"*** {propuesta.disclaimer} ***")
    print()

    if propuesta.sistema_id:
        print(f"Sistema aplicado: {propuesta.sistema_id} {propuesta.sistema_nombre} (v{propuesta.sistema_version})")
        print(f"Fuente: {propuesta.sistema_fuente}")
        print(f"Alcance: {propuesta.nota_alcance}")
    else:
        print("Sistema aplicado: ninguno.")
    print()

    if propuesta.componentes:
        print("Componentes propuestos:")
        for componente in propuesta.componentes:
            print(f"  {componente.codigo} = {componente.valor}")
            print(f"      criterio: {componente.criterio_aplicado}")
            print(f"      fundamento: {componente.fundamento}")
            print(f"      trazabilidad: {', '.join(componente.fuente_ids)}")
    else:
        print("Componentes propuestos: ninguno.")

    print()
    if propuesta.datos_faltantes:
        print(f"Datos faltantes para completar la estadificación: {', '.join(propuesta.datos_faltantes)}")

    print(f"Estadio global propuesto: {propuesta.estadio_global or 'no determinado'}")
    print(f"Fundamento: {propuesta.fundamento_global}")

    analisis = analizar_estadificacion_incompleta(propuesta)
    print()
    print("--- EST-03: análisis de completitud ---")
    print(f"Estadificación completa: {'sí' if analisis.estadificacion_completa else 'no'}")
    print(f"Estadio confirmado: {'sí' if analisis.estadio_confirmado else 'no'}")
    print(f"Componentes determinados: {', '.join(analisis.componentes_determinados) or 'ninguno'}")
    if analisis.componentes_indeterminados:
        print("Componentes indeterminados:")
        for comp in analisis.componentes_indeterminados:
            print(f"  {comp.codigo} ({comp.motivo})")
            print(f"      información requerida: {comp.informacion_requerida}")
    if analisis.estadios_posibles:
        print(f"Estadios posibles: {', '.join(analisis.estadios_posibles)}")
    if analisis.rango_legible:
        print(f"Rango: {analisis.rango_legible}")
    print(f"Mensaje: {analisis.mensaje}")
    print()
    return propuesta


def _mostrar_confirmacion(titulo: str, conn_confirmaciones, paciente_id: int, propuesta, **kwargs) -> None:
    print("--- EST-02: ajuste manual de estadificación ---")
    print(titulo)

    confirmacion = confirmar_estadificacion(
        conn_confirmaciones, paciente_id, propuesta_sistema=propuesta, **kwargs
    )
    print(f"Estadio confirmado por el médico: {confirmacion.estadio_confirmado} (autor: {confirmacion.autor})")
    print(f"Sugerencia del sistema al momento de confirmar: {confirmacion.estadio_sugerido_por_sistema or 'ninguna'}")
    print(f"¿Difiere de la sugerencia?: {'sí' if confirmacion.difiere_de_sugerencia else 'no'}")
    if confirmacion.justificacion:
        print(f"Justificación registrada: {confirmacion.justificacion}")

    vigente = obtener_estadificacion_vigente(conn_confirmaciones, paciente_id, propuesta)
    print(f"Estadio vigente para el paciente: {vigente.estadio} (fuente: {vigente.fuente})")
    print()


def main() -> None:
    conn = crear_conexion()
    ids = sembrar_datos_sinteticos(conn)
    conn_confirmaciones = crear_conexion_confirmaciones()

    propuesta_maria = _mostrar_propuesta(
        "DEMO A: María (cáncer de mama TNBC) — cT2 N0 cM0",
        conn,
        ids["paciente_maria"],
    )
    _mostrar_confirmacion(
        "El médico revisa la propuesta (IIA) y la confirma tal cual.",
        conn_confirmaciones,
        ids["paciente_maria"],
        propuesta_maria,
        estadio_confirmado="IIA",
        autor="dra. Ríos",
    )

    propuesta_diana = _mostrar_propuesta(
        "DEMO B: Diana (NSCLC temprano) — cT1 N0 cM0",
        conn,
        ids["paciente_diana"],
    )
    _mostrar_confirmacion(
        "El médico revisa la propuesta (I) y la ajusta tras junta multidisciplinaria.",
        conn_confirmaciones,
        ids["paciente_diana"],
        propuesta_diana,
        estadio_confirmado="IB",
        autor="dr. Salazar",
        justificacion="Hallazgo intraoperatorio de mayor tamaño tumoral no reflejado en el estudio preoperatorio.",
    )
    _mostrar_propuesta(
        "DEMO C: Roberto (NSCLC metastásico) — cM1",
        conn,
        ids["paciente_roberto"],
    )
    _mostrar_propuesta(
        "DEMO D: Patricia (RCC) — sin T/N/M estructurado en el expediente",
        conn,
        ids["paciente_patricia"],
    )
    propuesta_laura = _mostrar_propuesta(
        "DEMO E: Laura (melanoma) — T y N documentados, estudio de extensión (M) pendiente",
        conn,
        ids["paciente_laura"],
    )
    _mostrar_confirmacion(
        "El sistema no propuso un estadio global (M pendiente); el médico confirma "
        "IIB con base en el estudio de extensión ya revisado en consulta.",
        conn_confirmaciones,
        ids["paciente_laura"],
        propuesta_laura,
        estadio_confirmado="IIB",
        autor="dra. Gómez",
    )

    conn.close()
    conn_confirmaciones.close()


if __name__ == "__main__":
    main()
