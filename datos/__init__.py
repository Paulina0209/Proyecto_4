"""Las dos capas de datos del copiloto.

    data/cbioportal/            CAPA BASE: lo que viene de cBioPortal, tal cual.
        copiloto.db             Nadie la modifica; se reconstruye con
        pacientes.db            ``python -m datos base`` (necesita internet).

    data/copiloto.db            CAPA DE TRABAJO: la que usa el sistema (API,
    patients/db/pacientes.db    interfaz, agente, demos). Es una copia de la base
    data/usuarios.db            más el escenario de ``datos.escenario``: usuarios,
                                pacientes repartidos entre oncólogos,
                                consentimientos en todos sus estados, etc.

    python -m datos preparar     arma lo que falte (la primera vez respalda lo que había)
    python -m datos reiniciar    descarta los cambios: vuelve a base + escenario
    python -m datos estado       qué hay en cada capa y qué casos cubre el escenario

Ver docs/datos.md.
"""
