"""ADM-01 — Gestión de usuarios, roles y permisos.

El backlog no trae criterios de aceptación para ADM-01; estos son los que se
propusieron, y cada clase de pruebas es uno:

    AC1: un administrador crea, edita, cambia de rol y desactiva usuarios, y
         el cambio se refleja en el login y en los permisos (SEC-01).
    AC2: quien no es administrador no puede gestionar usuarios; el intento
         se deniega y queda registrado.
    AC3: nunca se pierde el acceso administrativo ni se borra el rastro:
         salvaguardas del último administrador, baja lógica, auditoría.
"""
from datetime import datetime, timezone

import pytest

from administracion import usuarios as adm
from administracion.usuarios import (
    ErrorValidacion,
    OperacionNoPermitidaError,
    PermisoDenegadoError,
    UsuarioDuplicadoError,
    UsuarioNoEncontradoError,
)
from auditoria.models import TipoAccion
from seguridad.autenticacion import autenticar, registrar_usuario
from seguridad.autorizacion import Accion, verificar_permiso
from seguridad.models import Rol, Usuario

AHORA = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
CLAVE = "Cl1nic@2026"


@pytest.fixture(autouse=True)
def _hash_rapido(monkeypatch):
    """PBKDF2 con 200 000 iteraciones por usuario haría lenta la suite; el
    algoritmo es el mismo con menos iteraciones."""
    monkeypatch.setattr("seguridad.autenticacion._ITERACIONES_PBKDF2", 1_000)


@pytest.fixture
def conn():
    conexion = adm.crear_conexion(":memory:")
    yield conexion
    conexion.close()


@pytest.fixture
def admin(conn):
    creado = adm.crear_primer_administrador(conn, "admin.sistema", "Adm1n-Inicial", "Administrador del Sistema", ahora=AHORA)
    return Usuario(creado.id, creado.nombre_usuario, creado.rol, creado.activo)


def _crear(conn, admin, nombre="dra.gomez", rol=Rol.ONCOLOGO, correo="dra.gomez@hospital.org", completo="Dra. Ana Gómez"):
    return adm.crear_usuario(conn, admin, nombre, CLAVE, rol, completo, correo, ahora=AHORA)


def _como_usuario(u):
    return Usuario(u.id, u.nombre_usuario, u.rol, u.activo)


# --------------------------------------------------------------------------
# AC1 — el administrador gestiona usuarios y roles
# --------------------------------------------------------------------------


class TestAC1AdministradorGestionaUsuarios:
    def test_crear_un_usuario_le_permite_iniciar_sesion_con_su_rol(self, conn, admin):
        creado = _crear(conn, admin)

        assert creado.rol == Rol.ONCOLOGO and creado.activo is True
        assert creado.nombre_completo == "Dra. Ana Gómez" and creado.correo == "dra.gomez@hospital.org"
        assert creado.creado_por == admin.id
        resultado = autenticar(conn, "dra.gomez", CLAVE, ahora=AHORA)
        assert resultado.exito is True and resultado.usuario.rol == Rol.ONCOLOGO

    def test_la_contrasena_no_se_guarda_en_claro_ni_se_expone(self, conn, admin):
        creado = _crear(conn, admin)
        fila = conn.execute("SELECT hash_contrasena FROM usuarios WHERE id = ?", (creado.id,)).fetchone()
        assert CLAVE not in fila["hash_contrasena"]
        assert not hasattr(creado, "hash_contrasena") and not hasattr(creado, "sal")

    def test_cambiar_de_rol_cambia_los_permisos_efectivos(self, conn, admin):
        enfermero = _crear(conn, admin, "enf.paez", Rol.ENFERMERIA, "enf.paez@hospital.org", "Enf. Luis Páez")
        antes = verificar_permiso(_como_usuario(enfermero), Accion.CONFIRMAR_TRATAMIENTO)
        assert antes.permitido is False

        cambiado = adm.asignar_rol(conn, admin, enfermero.id, "oncologo", "Terminó la especialización", ahora=AHORA)

        assert cambiado.rol == Rol.ONCOLOGO
        relogin = autenticar(conn, "enf.paez", CLAVE, ahora=AHORA).usuario
        assert verificar_permiso(relogin, Accion.CONFIRMAR_TRATAMIENTO).permitido is True

    def test_desactivar_impide_iniciar_sesion_y_operar(self, conn, admin):
        onco = _crear(conn, admin)
        desactivado = adm.desactivar_usuario(conn, admin, onco.id, "Dejó la institución", ahora=AHORA)

        assert desactivado.activo is False
        assert desactivado.motivo_desactivacion == "Dejó la institución"
        assert desactivado.desactivado_en == AHORA.isoformat()
        assert autenticar(conn, "dra.gomez", CLAVE, ahora=AHORA).exito is False
        assert verificar_permiso(_como_usuario(desactivado), Accion.VER_EXPEDIENTE).permitido is False

    def test_reactivar_devuelve_el_acceso(self, conn, admin):
        onco = _crear(conn, admin)
        adm.desactivar_usuario(conn, admin, onco.id, "Licencia", ahora=AHORA)
        reactivado = adm.reactivar_usuario(conn, admin, onco.id, ahora=AHORA)
        assert reactivado.activo is True and reactivado.motivo_desactivacion is None
        assert autenticar(conn, "dra.gomez", CLAVE, ahora=AHORA).exito is True

    def test_editar_nombre_y_correo_y_borrar_el_correo(self, conn, admin):
        onco = _crear(conn, admin)
        editado = adm.actualizar_usuario(conn, admin, onco.id, nombre_completo="Ana María Gómez", correo="ana@hospital.org", ahora=AHORA)
        assert (editado.nombre_completo, editado.correo) == ("Ana María Gómez", "ana@hospital.org")
        sin_correo = adm.actualizar_usuario(conn, admin, onco.id, correo="", ahora=AHORA)
        assert sin_correo.correo is None and sin_correo.nombre_completo == "Ana María Gómez"
        assert adm.obtener_usuario(conn, admin, onco.id).nombre_usuario == "dra.gomez"  # el login no cambia

    def test_listar_con_filtros(self, conn, admin):
        _crear(conn, admin)
        enf = _crear(conn, admin, "enf.paez", Rol.ENFERMERIA, "enf.paez@hospital.org", "Enf. Luis Páez")
        adm.desactivar_usuario(conn, admin, enf.id, "Renuncia", ahora=AHORA)

        assert [u.nombre_usuario for u in adm.listar_usuarios(conn, admin)] == ["admin.sistema", "dra.gomez", "enf.paez"]
        assert [u.nombre_usuario for u in adm.listar_usuarios(conn, admin, rol="enfermeria")] == ["enf.paez"]
        assert [u.nombre_usuario for u in adm.listar_usuarios(conn, admin, activo=False)] == ["enf.paez"]
        assert [u.nombre_usuario for u in adm.listar_usuarios(conn, admin, texto="GÓMEZ".lower())] == ["dra.gomez"]
        assert adm.listar_usuarios(conn, admin, texto="100%") == []  # los comodines del LIKE se escapan

    def test_restablecer_contrasena_levanta_el_bloqueo(self, conn, admin):
        onco = _crear(conn, admin)
        for _ in range(5):
            autenticar(conn, "dra.gomez", "incorrecta", ahora=AHORA)
        assert autenticar(conn, "dra.gomez", CLAVE, ahora=AHORA).cuenta_bloqueada is True
        assert adm.obtener_usuario(conn, admin, onco.id, ahora=AHORA).bloqueado is True

        adm.restablecer_contrasena(conn, admin, onco.id, "Nueva-Clave-77", ahora=AHORA)

        assert autenticar(conn, "dra.gomez", CLAVE, ahora=AHORA).exito is False  # la vieja ya no sirve
        assert autenticar(conn, "dra.gomez", "Nueva-Clave-77", ahora=AHORA).exito is True
        assert adm.obtener_usuario(conn, admin, onco.id, ahora=AHORA).bloqueado is False

    def test_matriz_de_permisos_es_la_misma_de_sec01(self, conn, admin):
        matriz = adm.matriz_de_permisos(conn, admin)
        assert Accion.CONFIRMAR_TRATAMIENTO in matriz[Rol.ONCOLOGO]
        assert Accion.CONFIRMAR_TRATAMIENTO not in matriz[Rol.ENFERMERIA]
        assert matriz[Rol.ADMINISTRADOR] == (Accion.GESTIONAR_USUARIOS,)  # sin acceso clínico

    def test_el_administrador_de_sistema_no_tiene_acceso_clinico(self, admin):
        for accion in (Accion.VER_EXPEDIENTE, Accion.CONFIRMAR_TRATAMIENTO, Accion.EXPORTAR_EXPEDIENTE):
            assert verificar_permiso(admin, accion).permitido is False


class TestValidaciones:
    def test_todos_los_errores_salen_juntos(self, conn, admin):
        with pytest.raises(ErrorValidacion) as exc:
            adm.crear_usuario(conn, admin, "Mal Nombre!", "corta", "medico", "A", "no-es-correo", ahora=AHORA)
        campos = {c for c, _ in exc.value.errores}
        assert campos == {"nombre_usuario", "rol", "nombre_completo", "correo", "contrasena"}
        assert adm.listar_usuarios(conn, admin) != [] and len(adm.listar_usuarios(conn, admin)) == 1  # no se creó nada

    @pytest.mark.parametrize("clave", ["corta1", "soloLetrasLargas", "12345678901", "xdra.gomezx1234"])
    def test_politica_de_contrasena(self, conn, admin, clave):
        with pytest.raises(ErrorValidacion) as exc:
            adm.crear_usuario(conn, admin, "dra.gomez", clave, Rol.ONCOLOGO, "Dra. Ana Gómez", ahora=AHORA)
        assert any(c == "contrasena" for c, _ in exc.value.errores)

    def test_usuario_duplicado_sin_distinguir_mayusculas(self, conn, admin):
        _crear(conn, admin)
        registrar_usuario(conn, "Legado.Mixto", CLAVE, Rol.AUDITOR)  # alta antigua con mayúsculas
        with pytest.raises(UsuarioDuplicadoError):
            _crear(conn, admin, correo="otro@hospital.org")
        with pytest.raises(UsuarioDuplicadoError):
            adm.crear_usuario(conn, admin, "legado.mixto", CLAVE, Rol.AUDITOR, "Alguien Más", ahora=AHORA)

    def test_correo_duplicado(self, conn, admin):
        _crear(conn, admin)
        with pytest.raises(UsuarioDuplicadoError) as exc:
            _crear(conn, admin, nombre="otra.dra", correo="DRA.GOMEZ@hospital.org")
        assert exc.value.errores[0][0] == "correo"
        otra = _crear(conn, admin, nombre="otra.dra", correo="otra@hospital.org", completo="Otra Doctora")
        with pytest.raises(UsuarioDuplicadoError):
            adm.actualizar_usuario(conn, admin, otra.id, correo="dra.gomez@hospital.org", ahora=AHORA)

    def test_motivo_obligatorio_para_cambiar_rol_y_desactivar(self, conn, admin):
        onco = _crear(conn, admin)
        with pytest.raises(ErrorValidacion):
            adm.asignar_rol(conn, admin, onco.id, Rol.AUDITOR, "  ", ahora=AHORA)
        with pytest.raises(ErrorValidacion):
            adm.desactivar_usuario(conn, admin, onco.id, "", ahora=AHORA)
        assert adm.obtener_usuario(conn, admin, onco.id).rol == Rol.ONCOLOGO

    def test_rol_desconocido_y_mismo_rol(self, conn, admin):
        onco = _crear(conn, admin)
        with pytest.raises(ErrorValidacion):
            adm.asignar_rol(conn, admin, onco.id, "superusuario", "x", ahora=AHORA)
        with pytest.raises(ErrorValidacion, match="ya tiene"):
            adm.asignar_rol(conn, admin, onco.id, Rol.ONCOLOGO, "x", ahora=AHORA)

    def test_actualizar_sin_cambios_y_usuario_inexistente(self, conn, admin):
        onco = _crear(conn, admin)
        with pytest.raises(ErrorValidacion):
            adm.actualizar_usuario(conn, admin, onco.id, ahora=AHORA)
        with pytest.raises(UsuarioNoEncontradoError):
            adm.obtener_usuario(conn, admin, 999)
        with pytest.raises(UsuarioNoEncontradoError):
            adm.desactivar_usuario(conn, admin, 999, "x", ahora=AHORA)

    def test_desactivar_dos_veces_y_reactivar_un_activo(self, conn, admin):
        onco = _crear(conn, admin)
        adm.desactivar_usuario(conn, admin, onco.id, "x", ahora=AHORA)
        with pytest.raises(ErrorValidacion):
            adm.desactivar_usuario(conn, admin, onco.id, "x", ahora=AHORA)
        adm.reactivar_usuario(conn, admin, onco.id, ahora=AHORA)
        with pytest.raises(ErrorValidacion):
            adm.reactivar_usuario(conn, admin, onco.id, ahora=AHORA)

    def test_usuario_de_sec01_sin_perfil_tambien_se_gestiona(self, conn, admin):
        antiguo = registrar_usuario(conn, "enf.antiguo", CLAVE, Rol.ENFERMERIA)  # sin perfil
        vista = adm.obtener_usuario(conn, admin, antiguo.id)
        assert vista.nombre_completo is None
        adm.actualizar_usuario(conn, admin, antiguo.id, nombre_completo="Enfermero Antiguo", ahora=AHORA)
        adm.desactivar_usuario(conn, admin, antiguo.id, "Renuncia", ahora=AHORA)
        assert adm.obtener_usuario(conn, admin, antiguo.id).nombre_completo == "Enfermero Antiguo"


# --------------------------------------------------------------------------
# AC2 — quien no es administrador no gestiona usuarios
# --------------------------------------------------------------------------


class TestAC2SoloElAdministradorGestionaUsuarios:
    OPERACIONES = [
        lambda c, a, objetivo: adm.crear_usuario(c, a, "intruso.nuevo", CLAVE, Rol.ADMINISTRADOR, "Intruso Nuevo", ahora=AHORA),
        lambda c, a, objetivo: adm.listar_usuarios(c, a),
        lambda c, a, objetivo: adm.obtener_usuario(c, a, objetivo),
        lambda c, a, objetivo: adm.actualizar_usuario(c, a, objetivo, nombre_completo="Otro Nombre", ahora=AHORA),
        lambda c, a, objetivo: adm.asignar_rol(c, a, objetivo, Rol.ADMINISTRADOR, "x", ahora=AHORA),
        lambda c, a, objetivo: adm.desactivar_usuario(c, a, objetivo, "x", ahora=AHORA),
        lambda c, a, objetivo: adm.reactivar_usuario(c, a, objetivo, ahora=AHORA),
        lambda c, a, objetivo: adm.restablecer_contrasena(c, a, objetivo, "Nueva-Clave-77", ahora=AHORA),
        lambda c, a, objetivo: adm.matriz_de_permisos(c, a),
        lambda c, a, objetivo: adm.eventos_de_administracion(c, a),
    ]

    @pytest.mark.parametrize("rol", [Rol.ONCOLOGO, Rol.ENFERMERIA, Rol.ADMINISTRATIVO, Rol.AUDITOR, Rol.ADMINISTRADOR_CLINICO])
    @pytest.mark.parametrize("operacion", range(10))
    def test_ningun_otro_rol_puede_hacer_ninguna_operacion(self, conn, admin, rol, operacion):
        objetivo = _crear(conn, admin, "enf.paez", Rol.ENFERMERIA, "enf.paez@hospital.org", "Enf. Luis Páez")
        intruso = _crear(conn, admin, "otro.usuario", rol, "otro@hospital.org", "Otro Usuario")
        antes = [(u.nombre_usuario, u.rol, u.activo) for u in adm.listar_usuarios(conn, admin)]

        with pytest.raises(PermisoDenegadoError, match="gestionar_usuarios"):
            self.OPERACIONES[operacion](conn, _como_usuario(intruso), objetivo.id)

        assert [(u.nombre_usuario, u.rol, u.activo) for u in adm.listar_usuarios(conn, admin)] == antes

    def test_el_intento_denegado_queda_auditado(self, conn, admin):
        enf = _crear(conn, admin, "enf.paez", Rol.ENFERMERIA, "enf.paez@hospital.org", "Enf. Luis Páez")
        with pytest.raises(PermisoDenegadoError):
            adm.asignar_rol(conn, _como_usuario(enf), enf.id, Rol.ADMINISTRADOR, "me ascendo", ahora=AHORA)

        denegado = [e for e in adm.eventos_de_administracion(conn, admin) if e.resultado == "denegado"]
        assert len(denegado) == 1
        assert denegado[0].actor_id == enf.id and denegado[0].operacion == "asignar_rol"
        assert denegado[0].objetivo_id == enf.id

    def test_un_administrador_desactivado_ya_no_puede_operar_aunque_conserve_el_objeto(self, conn, admin):
        segundo = _crear(conn, admin, "admin.dos", Rol.ADMINISTRADOR, "dos@hospital.org", "Segundo Administrador")
        adm.desactivar_usuario(conn, admin, segundo.id, "Cambio de funciones", ahora=AHORA)
        with pytest.raises(PermisoDenegadoError):
            adm.listar_usuarios(conn, _como_usuario(segundo))

    def test_un_objeto_usuario_con_rol_inflado_no_sirve(self, conn, admin):
        enf = _crear(conn, admin, "enf.paez", Rol.ENFERMERIA, "enf.paez@hospital.org", "Enf. Luis Páez")
        falso_admin = Usuario(enf.id, enf.nombre_usuario, Rol.ADMINISTRADOR, True)  # el rol real es otro
        with pytest.raises(PermisoDenegadoError):
            adm.listar_usuarios(conn, falso_admin)

    def test_un_actor_que_no_existe_se_deniega(self, conn, admin):
        with pytest.raises(PermisoDenegadoError, match="no existe"):
            adm.listar_usuarios(conn, Usuario(999, "fantasma", Rol.ADMINISTRADOR, True))


# --------------------------------------------------------------------------
# AC3 — salvaguardas y auditoría
# --------------------------------------------------------------------------


class TestAC3SalvaguardasYAuditoria:
    def test_primer_administrador_solo_si_no_hay_ninguno(self, conn, admin):
        with pytest.raises(OperacionNoPermitidaError):
            adm.crear_primer_administrador(conn, "otro.admin", "Adm1n-Inicial", "Otro Administrador")

    def test_nadie_cambia_su_propio_rol_ni_se_desactiva(self, conn, admin):
        _crear(conn, admin, "admin.dos", Rol.ADMINISTRADOR, "dos@hospital.org", "Segundo Administrador")
        with pytest.raises(OperacionNoPermitidaError, match="propio rol"):
            adm.asignar_rol(conn, admin, admin.id, Rol.AUDITOR, "x", ahora=AHORA)
        with pytest.raises(OperacionNoPermitidaError, match="propia cuenta"):
            adm.desactivar_usuario(conn, admin, admin.id, "x", ahora=AHORA)

    def test_siempre_queda_al_menos_un_administrador_activo(self, conn, admin):
        segundo = _crear(conn, admin, "admin.dos", Rol.ADMINISTRADOR, "dos@hospital.org", "Segundo Administrador")
        # El segundo quita al primero: queda uno.
        adm.desactivar_usuario(conn, _como_usuario(segundo), admin.id, "Rotación", ahora=AHORA)
        assert adm._administradores_activos(conn) == 1
        # Ahora el segundo es el último: nadie puede quitarlo (ni él mismo).
        with pytest.raises(OperacionNoPermitidaError):
            adm.desactivar_usuario(conn, _como_usuario(segundo), segundo.id, "x", ahora=AHORA)
        assert adm._administradores_activos(conn) == 1

    def test_defensa_en_profundidad_ultimo_administrador(self, conn, admin):
        """Aunque otro actor lo intentara, la regla mira el conteo real."""
        conn.execute("UPDATE usuarios SET rol = 'administrador' WHERE id = ?", (admin.id,))
        assert adm._administradores_activos(conn) == 1

    def test_no_se_ofrece_borrar_usuarios(self):
        publicas = {n for n in dir(adm) if not n.startswith("_")}
        assert not {n for n in publicas if n.startswith(("borrar", "eliminar", "delete"))}

    def test_baja_logica_conserva_el_usuario_y_su_auditoria(self, conn, admin):
        onco = _crear(conn, admin)
        adm.desactivar_usuario(conn, admin, onco.id, "Renuncia", ahora=AHORA)
        assert conn.execute("SELECT COUNT(*) FROM usuarios WHERE id = ?", (onco.id,)).fetchone()[0] == 1
        assert len(adm.eventos_de_administracion(conn, admin, usuario_id=onco.id)) == 2  # alta y baja

    def test_cada_operacion_queda_en_auditoria_con_quien_que_y_sobre_quien(self, conn, admin):
        onco = _crear(conn, admin)
        adm.actualizar_usuario(conn, admin, onco.id, nombre_completo="Ana María Gómez", ahora=AHORA)
        adm.asignar_rol(conn, admin, onco.id, Rol.AUDITOR, "Pasa a auditoría", ahora=AHORA)
        adm.restablecer_contrasena(conn, admin, onco.id, "Nueva-Clave-77", ahora=AHORA)
        adm.desactivar_usuario(conn, admin, onco.id, "Renuncia", ahora=AHORA)
        adm.reactivar_usuario(conn, admin, onco.id, ahora=AHORA)

        eventos = adm.eventos_de_administracion(conn, admin, usuario_id=onco.id)
        assert [e.operacion for e in reversed(eventos)] == [
            "crear_usuario", "actualizar_usuario", "asignar_rol", "restablecer_contrasena",
            "desactivar_usuario", "reactivar_usuario",
        ]
        assert all(e.actor_id == admin.id and e.resultado == "ok" and e.fecha == AHORA.isoformat() for e in eventos)
        rol_evento = next(e for e in eventos if e.operacion == "asignar_rol")
        assert (rol_evento.detalle["rol_anterior"], rol_evento.detalle["rol_nuevo"]) == ("oncologo", "auditor")
        assert rol_evento.detalle["motivo"] == "Pasa a auditoría"
        fila = conn.execute("SELECT accion FROM eventos_acceso ORDER BY id DESC LIMIT 1").fetchone()
        assert fila["accion"] == TipoAccion.GESTIONAR_USUARIOS.value

    def test_la_auditoria_nunca_guarda_contrasenas_ni_hashes(self, conn, admin):
        onco = _crear(conn, admin)
        adm.restablecer_contrasena(conn, admin, onco.id, "Nueva-Clave-77", ahora=AHORA)
        hash_actual = conn.execute("SELECT hash_contrasena FROM usuarios WHERE id = ?", (onco.id,)).fetchone()[0]
        volcado = " ".join(str(f["detalle"]) for f in conn.execute("SELECT detalle FROM eventos_acceso"))
        for secreto in (CLAVE, "Nueva-Clave-77", "Adm1n-Inicial", hash_actual):
            assert secreto not in volcado

    def test_si_falla_la_auditoria_se_deshace_el_cambio(self, conn, admin, monkeypatch):
        onco = _crear(conn, admin)

        def falla(*a, **k):
            raise RuntimeError("auditoría caída")

        monkeypatch.setattr(adm, "registrar_acceso", falla)
        with pytest.raises(RuntimeError):
            adm.asignar_rol(conn, admin, onco.id, Rol.AUDITOR, "x", ahora=AHORA)
        monkeypatch.undo()
        assert adm.obtener_usuario(conn, admin, onco.id).rol == Rol.ONCOLOGO

    def test_si_falla_la_auditoria_del_alta_no_queda_el_usuario(self, conn, admin, monkeypatch):
        def falla(*a, **k):
            raise RuntimeError("auditoría caída")

        monkeypatch.setattr(adm, "registrar_acceso", falla)
        with pytest.raises(RuntimeError):
            _crear(conn, admin)
        monkeypatch.undo()
        assert [u.nombre_usuario for u in adm.listar_usuarios(conn, admin)] == ["admin.sistema"]
