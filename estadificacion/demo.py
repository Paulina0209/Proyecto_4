"""Demo end-to-end de EST-01: expediente mock -> propuesta de estadificación.

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


def _mostrar_propuesta(titulo: str, conn, paciente_id: int) -> None:
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
    print()


def main() -> None:
    conn = crear_conexion()
    ids = sembrar_datos_sinteticos(conn)

    _mostrar_propuesta(
        "DEMO A: María (cáncer de mama TNBC) — cT2 N0 cM0",
        conn,
        ids["paciente_maria"],
    )
    _mostrar_propuesta(
        "DEMO B: Diana (NSCLC temprano) — cT1 N0 cM0",
        conn,
        ids["paciente_diana"],
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

    conn.close()


if __name__ == "__main__":
    main()
