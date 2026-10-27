"""Tests del cargador de skills (tx_clinica/skills.py) y de la skill real del repositorio.

Cubre la validación contra la especificación agentskills.io, la divulgación progresiva
(catálogo → cuerpo → recursos) y que ningún recurso pueda leerse fuera de la carpeta de
la skill.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tx_clinica import skills
from tx_clinica.skills import (
    RecursoNoDisponible,
    SkillInvalida,
    SkillNoEncontrada,
    activar,
    cargar_skill,
    catalogo_para_prompt,
    descubrir_skills,
    leer_recurso,
)

RAIZ_REPO = Path(__file__).resolve().parents[2]
SKILLS_DEL_REPO = RAIZ_REPO / "skills"


def _escribir_skill(raiz: Path, nombre: str = "mi-skill", *, frontmatter: str | None = None, cuerpo: str = "# Pasos\n\n1. Haz algo.\n") -> Path:
    carpeta = raiz / nombre
    carpeta.mkdir(parents=True, exist_ok=True)
    if frontmatter is None:
        frontmatter = f"name: {nombre}\ndescription: Hace algo útil. Úsala cuando se pida algo útil."
    (carpeta / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{cuerpo}", encoding="utf-8")
    return carpeta


# ---------------------------------------------------------------------------
# La skill real del repositorio
# ---------------------------------------------------------------------------
class TestSkillDelRepositorio:
    def test_es_valida_segun_la_especificacion(self):
        skill = cargar_skill(SKILLS_DEL_REPO / "ruta-recomendacion-guias")
        assert skill.nombre == "ruta-recomendacion-guias"
        assert 0 < len(skill.descripcion) <= 1024
        assert skill.cuerpo.count("\n") + 1 <= 500

    def test_la_descripcion_dice_que_hace_y_cuando_usarla(self):
        descripcion = cargar_skill(SKILLS_DEL_REPO / "ruta-recomendacion-guias").descripcion.lower()
        assert "recomendación de tratamiento" in descripcion
        assert "úsalo" in descripcion or "úsala" in descripcion

    def test_se_descubre_y_cumple_las_requeridas(self):
        encontradas = descubrir_skills(SKILLS_DEL_REPO, requeridas=skills.SKILLS_REQUERIDAS)
        assert set(skills.SKILLS_REQUERIDAS) <= set(encontradas)

    def test_trae_su_archivo_de_referencia(self):
        skill = cargar_skill(SKILLS_DEL_REPO / "ruta-recomendacion-guias")
        assert "references/registro-de-decision.md" in skill.recursos()

    def test_el_cuerpo_manda_a_cargar_la_referencia_que_existe(self):
        skill = cargar_skill(SKILLS_DEL_REPO / "ruta-recomendacion-guias")
        for recurso in skill.recursos():
            assert recurso in skill.cuerpo, f"el cuerpo no menciona {recurso}: quedaría huérfano"
        # Y la ruta que menciona se puede leer de verdad.
        assert "tipo_decision" in leer_recurso(skill.nombre, "references/registro-de-decision.md", {skill.nombre: skill})

    def test_los_archivos_de_la_skill_usan_lf(self):
        """El frontmatter YAML y los diffs se llevan mejor con LF; evita sorpresas entre sistemas."""
        for archivo in (SKILLS_DEL_REPO / "ruta-recomendacion-guias").rglob("*.md"):
            assert b"\r\n" not in archivo.read_bytes(), archivo


# ---------------------------------------------------------------------------
# Validación (estricta, a propósito)
# ---------------------------------------------------------------------------
class TestValidacion:
    def test_skill_minima_valida(self, tmp_path):
        skill = cargar_skill(_escribir_skill(tmp_path))
        assert skill.nombre == "mi-skill"
        assert skill.cuerpo.startswith("# Pasos")
        assert skill.recursos() == []

    def test_acepta_campos_opcionales(self, tmp_path):
        carpeta = _escribir_skill(
            tmp_path,
            frontmatter=(
                "name: mi-skill\ndescription: Hace algo. Úsala cuando haga falta.\nlicense: MIT\n"
                "compatibility: Necesita tools de tx_clinica.\nmetadata:\n  version: \"1.0\"\nallowed-tools: Read"
            ),
        )
        skill = cargar_skill(carpeta)
        assert skill.licencia == "MIT"
        assert skill.metadata == {"version": "1.0"}
        assert skill.herramientas_permitidas == "Read"

    def test_falta_skill_md(self, tmp_path):
        (tmp_path / "vacia").mkdir()
        with pytest.raises(SkillInvalida, match="falta SKILL.md"):
            cargar_skill(tmp_path / "vacia")

    @pytest.mark.parametrize(
        "contenido, mensaje",
        [
            ("# Sin frontmatter\n", "empezar con frontmatter"),
            ("---\nname: mi-skill\ndescription: x\n# sin cierre\n", "no está cerrado"),
            ("---\n: : :\n  - [\n---\ncuerpo\n", "YAML"),
            ("---\n- uno\n- dos\n---\ncuerpo\n", "mapa YAML"),
        ],
    )
    def test_frontmatter_malformado(self, tmp_path, contenido, mensaje):
        carpeta = tmp_path / "mi-skill"
        carpeta.mkdir()
        (carpeta / "SKILL.md").write_text(contenido, encoding="utf-8")
        with pytest.raises(SkillInvalida, match=mensaje):
            cargar_skill(carpeta)

    @pytest.mark.parametrize(
        "nombre_en_frontmatter",
        ["Mi-Skill", "mi--skill", "-mi-skill", "mi-skill-", "mi_skill", "mi skill", "x" * 65, "otra-cosa"],
    )
    def test_nombre_invalido_o_distinto_de_la_carpeta(self, tmp_path, nombre_en_frontmatter):
        carpeta = _escribir_skill(
            tmp_path, "mi-skill", frontmatter=f"name: {nombre_en_frontmatter}\ndescription: Hace algo. Úsala siempre."
        )
        with pytest.raises(SkillInvalida):
            cargar_skill(carpeta)

    @pytest.mark.parametrize("descripcion", ["", "   ", "x" * 1025])
    def test_descripcion_vacia_o_demasiado_larga(self, tmp_path, descripcion):
        carpeta = _escribir_skill(tmp_path, frontmatter=f"name: mi-skill\ndescription: \"{descripcion}\"")
        with pytest.raises(SkillInvalida, match="description"):
            cargar_skill(carpeta)

    def test_descripcion_de_1024_exactos_es_valida(self, tmp_path):
        carpeta = _escribir_skill(tmp_path, frontmatter=f"name: mi-skill\ndescription: \"{'x' * 1024}\"")
        assert len(cargar_skill(carpeta).descripcion) == 1024

    def test_falta_descripcion(self, tmp_path):
        carpeta = _escribir_skill(tmp_path, frontmatter="name: mi-skill")
        with pytest.raises(SkillInvalida, match="description"):
            cargar_skill(carpeta)

    def test_campo_desconocido(self, tmp_path):
        carpeta = _escribir_skill(tmp_path, frontmatter="name: mi-skill\ndescription: Hace algo. Úsala.\nautor: yo")
        with pytest.raises(SkillInvalida, match="autor"):
            cargar_skill(carpeta)

    def test_metadata_debe_ser_texto_a_texto(self, tmp_path):
        carpeta = _escribir_skill(
            tmp_path, frontmatter="name: mi-skill\ndescription: Hace algo. Úsala.\nmetadata:\n  version: 1.0"
        )
        with pytest.raises(SkillInvalida, match="metadata"):
            cargar_skill(carpeta)

    def test_compatibilidad_demasiado_larga(self, tmp_path):
        carpeta = _escribir_skill(
            tmp_path, frontmatter=f"name: mi-skill\ndescription: Hace algo. Úsala.\ncompatibility: \"{'c' * 501}\""
        )
        with pytest.raises(SkillInvalida, match="compatibility"):
            cargar_skill(carpeta)

    def test_cuerpo_vacio(self, tmp_path):
        with pytest.raises(SkillInvalida, match="no tiene instrucciones"):
            cargar_skill(_escribir_skill(tmp_path, cuerpo="\n\n"))

    def test_cuerpo_demasiado_largo(self, tmp_path):
        with pytest.raises(SkillInvalida, match="demasiado largo"):
            cargar_skill(_escribir_skill(tmp_path, cuerpo="línea\n" * 501))

    def test_el_error_dice_de_que_skill_se_trata(self, tmp_path):
        carpeta = _escribir_skill(tmp_path, "otra-skill", frontmatter="name: otra-skill")
        with pytest.raises(SkillInvalida, match="^otra-skill:"):
            cargar_skill(carpeta)

    def test_acepta_saltos_de_linea_de_windows(self, tmp_path):
        carpeta = tmp_path / "mi-skill"
        carpeta.mkdir()
        (carpeta / "SKILL.md").write_bytes(
            b"---\r\nname: mi-skill\r\ndescription: Hace algo. Usala cuando haga falta.\r\n---\r\n# Pasos\r\n\r\n1. Algo.\r\n"
        )
        skill = cargar_skill(carpeta)
        assert "\r" not in skill.cuerpo and skill.cuerpo.startswith("# Pasos")


# ---------------------------------------------------------------------------
# Descubrimiento
# ---------------------------------------------------------------------------
class TestDescubrimiento:
    def test_encuentra_varias_y_ignora_carpetas_sin_skill_md(self, tmp_path):
        _escribir_skill(tmp_path, "skill-a")
        _escribir_skill(tmp_path, "skill-b")
        (tmp_path / "notas").mkdir()
        assert list(descubrir_skills(tmp_path)) == ["skill-a", "skill-b"]

    def test_carpeta_inexistente_da_catalogo_vacio(self, tmp_path):
        assert descubrir_skills(tmp_path / "no-existe") == {}

    def test_falla_si_falta_una_requerida(self, tmp_path):
        _escribir_skill(tmp_path, "skill-a")
        with pytest.raises(SkillInvalida, match="faltan skills requeridas.*ruta-recomendacion-guias"):
            descubrir_skills(tmp_path, requeridas=("ruta-recomendacion-guias",))

    def test_una_skill_mal_formada_no_se_ignora_en_silencio(self, tmp_path):
        _escribir_skill(tmp_path, "skill-a")
        _escribir_skill(tmp_path, "skill-b", frontmatter="name: skill-b")
        with pytest.raises(SkillInvalida, match="skill-b"):
            descubrir_skills(tmp_path)

    def test_la_variable_de_entorno_cambia_la_carpeta(self, tmp_path, monkeypatch):
        _escribir_skill(tmp_path, "solo-esta")
        monkeypatch.setenv("COPILOTO_SKILLS_DIR", str(tmp_path))
        skills.limpiar_cache()
        try:
            assert list(skills.skills_disponibles()) == ["solo-esta"]
        finally:
            monkeypatch.delenv("COPILOTO_SKILLS_DIR")
            skills.limpiar_cache()
        assert "ruta-recomendacion-guias" in skills.skills_disponibles()


# ---------------------------------------------------------------------------
# Divulgación progresiva: catálogo -> cuerpo -> recursos
# ---------------------------------------------------------------------------
class TestDivulgacionProgresiva:
    @pytest.fixture
    def con_recursos(self, tmp_path):
        carpeta = _escribir_skill(tmp_path, cuerpo="# Pasos\n\nLee references/detalle.md cuando haga falta.\n")
        (carpeta / "references").mkdir()
        (carpeta / "references" / "detalle.md").write_text("# Detalle\nmucho texto\n", encoding="utf-8")
        (carpeta / "scripts").mkdir()
        (carpeta / "scripts" / "hola.py").write_text("print('hola')\n", encoding="utf-8")
        return {"mi-skill": cargar_skill(carpeta)}

    def test_el_catalogo_trae_nombre_y_descripcion_pero_no_el_cuerpo(self, con_recursos):
        catalogo = catalogo_para_prompt(con_recursos)
        assert "mi-skill: Hace algo útil." in catalogo
        assert "# Pasos" not in catalogo and "Haz algo" not in catalogo
        assert catalogo.startswith("<skills_disponibles>") and catalogo.endswith("</skills_disponibles>")

    def test_el_catalogo_vacio_lo_dice(self):
        assert "no hay skills" in catalogo_para_prompt({})

    def test_activar_devuelve_el_cuerpo_sin_frontmatter_y_lista_los_recursos(self, con_recursos):
        contenido = activar("mi-skill", con_recursos)
        assert contenido.startswith('<skill_content name="mi-skill">')
        assert contenido.endswith("</skill_content>")
        assert "# Pasos" in contenido
        assert "description:" not in contenido and "---" not in contenido
        assert "<archivo>references/detalle.md</archivo>" in contenido
        assert "<archivo>scripts/hola.py</archivo>" in contenido
        # Los recursos se listan, no se vuelcan: el contenido llega solo si se piden.
        assert "mucho texto" not in contenido

    def test_activar_una_skill_sin_recursos_no_inventa_la_lista(self, tmp_path):
        una = {"mi-skill": cargar_skill(_escribir_skill(tmp_path))}
        assert "skill_resources" not in activar("mi-skill", una)

    def test_activar_desconocida(self, con_recursos):
        with pytest.raises(SkillNoEncontrada):
            activar("no-existe", con_recursos)

    def test_leer_un_recurso(self, con_recursos):
        contenido = leer_recurso("mi-skill", "references/detalle.md", con_recursos)
        assert "mucho texto" in contenido and contenido.startswith('<skill_resource skill="mi-skill"')

    def test_leer_recurso_acepta_barra_invertida_y_punto_inicial(self, con_recursos):
        assert "mucho texto" in leer_recurso("mi-skill", "references\\detalle.md", con_recursos)
        assert "mucho texto" in leer_recurso("mi-skill", "./references/detalle.md", con_recursos)

    @pytest.mark.parametrize(
        "ruta",
        [
            "",
            "SKILL.md",  # el cuerpo ya se entrega al activar; solo se leen recursos
            "../otra/SKILL.md",
            "references/../SKILL.md",
            "references/../../etc/passwd",
            "/etc/passwd",
            "C:\\Windows\\win.ini",
            "otra-carpeta/detalle.md",
        ],
    )
    def test_rutas_no_permitidas(self, con_recursos, ruta):
        with pytest.raises(RecursoNoDisponible):
            leer_recurso("mi-skill", ruta, con_recursos)

    def test_recurso_inexistente(self, con_recursos):
        with pytest.raises(RecursoNoDisponible, match="No existe"):
            leer_recurso("mi-skill", "references/no-esta.md", con_recursos)

    @pytest.mark.skipif(os.name == "nt", reason="los enlaces simbólicos necesitan permisos especiales en Windows")
    def test_un_enlace_que_apunta_fuera_de_la_skill_se_rechaza(self, tmp_path, con_recursos):
        secreto = tmp_path / "secreto.txt"
        secreto.write_text("no debe salir", encoding="utf-8")
        enlace = con_recursos["mi-skill"].carpeta / "references" / "enlace.md"
        enlace.symlink_to(secreto)
        with pytest.raises(RecursoNoDisponible, match="sale de la carpeta"):
            leer_recurso("mi-skill", "references/enlace.md", con_recursos)

    def test_un_archivo_binario_no_se_entrega(self, con_recursos):
        (con_recursos["mi-skill"].carpeta / "assets").mkdir()
        (con_recursos["mi-skill"].carpeta / "assets" / "foto.bin").write_bytes(b"\xff\xfe\x00\x80\x81")
        with pytest.raises(RecursoNoDisponible, match="no es un archivo de texto"):
            leer_recurso("mi-skill", "assets/foto.bin", con_recursos)

    def test_un_recurso_enorme_no_se_entrega(self, con_recursos):
        (con_recursos["mi-skill"].carpeta / "references" / "grande.md").write_text(
            "x" * (skills.MAX_BYTES_RECURSO + 1), encoding="utf-8"
        )
        with pytest.raises(RecursoNoDisponible, match="demasiado grande"):
            leer_recurso("mi-skill", "references/grande.md", con_recursos)

    def test_recurso_de_skill_desconocida(self, con_recursos):
        with pytest.raises(SkillNoEncontrada):
            leer_recurso("no-existe", "references/detalle.md", con_recursos)
