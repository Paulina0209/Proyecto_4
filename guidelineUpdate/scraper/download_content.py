"""
Descarga el contenido fuente de un modulo, segun su tipo:

  - CPG estatico (tiene article_pdf): descarga el PDF del articulo.
  - Living guideline (tiene subpages, sin article_pdf): recorre el
    arbol de subpages solo para juntar el HTML crudo de cada
    seccion (content/footnotes tal cual los tiene ESMO) y lo guarda
    concatenado en un unico archivo -- sin armar ninguna estructura
    propia ni diagrama.

En los dos casos, ademas descarga cualquier archivo adjunto (slide
set en .pptx, etc.) que Kontent.ai tenga asociado al item.

process() devuelve el Path del documento que se usa para comparar
contra las reglas actuales (ver rule_agent.load_new_document_text/
load_new_document_images): si hay un slide set (.pptx) entre los
adjuntos descargados, ES ese el que se devuelve -- el HTML/PDF
tambien queda guardado en disco, pero no es lo que se le pasa al
LLM. Si no hay pptx, se devuelve el HTML/PDF como antes.

Guarda todo versionado por fecha en:
    guidelineUpdates/<module_id>/documents/<fecha>_full.pdf
    guidelineUpdates/<module_id>/documents/<fecha>_content.html
    guidelineUpdates/<module_id>/documents/<fecha>_<nombre_archivo>.pptx

Uso:
    python downloadContent.py cpg_uveal_melanoma esmo_uveal_melanoma
    python downloadContent.py esmo_oncogene_addicted_non_small_cell_lung_cancer_ esmo_nsclc_metastatic_oncogene_addicted
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import render_html
from ..agent import pptx_text
from ..state import state_manager

ESMO_API_URL = "https://kontent.cdn.aws.esmo.org/rest/items"
OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "updates"

CONTENT_DEPTH = "6"

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)


def build_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": BROWSER_USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
        "Origin": "https://www.esmo.org",
        "Referer": "https://www.esmo.org/",
    })
    return session


def fetch_item(session, codename, depth="2"):

    params = {
        "system.codename": codename,
        "depth": depth,
    }

    response = session.get(ESMO_API_URL, params=params, timeout=60)
    response.raise_for_status()
    return response.json()


def fetch_subpage_manual(session, codename, seen):
    """
    Fallback: pide UNA seccion por codename (depth alto no hace
    falta aca, ya vamos codename por codename) y arma su nodo del
    arbol recursivamente via su propio "subpages". Se usa solo si
    LIVING_GUIDELINE_DEPTH no alcanzo para resolver todo desde el
    item raiz.
    """

    if codename in seen:
        return {"codename": codename, "note": "ya visitado, evitando ciclo"}

    seen.add(codename)

    raw = fetch_item(session, codename, depth="1")
    items = raw.get("items", [])

    if not items:
        return {"codename": codename, "error": "no encontrado"}

    return build_section_node(items[0], raw.get("modular_content", {}), session, seen)


def build_section_node(item, modular_content, session, seen):
    """Convierte un item de Kontent.ai (seccion de living guideline)
    en un nodo simple: titulo, contenido, diagrama y sub-secciones."""

    item_codename = item.get("system", {}).get("codename")

    if item_codename in seen:
        # Sin esto, dos secciones que se referencian entre si (o
        # una que se referencia a si misma) recursionan infinito
        # ANTES de llegar siquiera al fallback -- que es donde
        # esta el unico chequeo de "seen" en esta version.
        return {"codename": item_codename, "note": "ya visitado, evitando ciclo"}

    seen.add(item_codename)

    elements = item.get("elements", {})

    def text_value(name):
        el = elements.get(name, {})
        return el.get("value") if isinstance(el, dict) else None

    subpage_codenames = text_value("subpages") or []
    if not isinstance(subpage_codenames, list):
        subpage_codenames = []

    children = []
    for child_codename in subpage_codenames:

        child_item = modular_content.get(child_codename)

        if child_item is not None:

            child_type = child_item.get("elements", {}).get("type", {}).get("value") or []
            if any(t.get("codename") == "slideset" for t in child_type if isinstance(t, dict)):
                # Es el PPTX complementario (ej. "Download the Slide
                # Set"), no contenido clinico -- lo dejamos afuera
                # del arbol para no meterlo en el HTML como si fuera
                # una seccion real de la guia.
                continue

            # Ya vino resuelto en la respuesta (dentro del depth
            # pedido) -- lo procesamos directo, sin otro request.
            children.append(
                build_section_node(child_item, modular_content, session, seen)
            )
        else:
            # No vino resuelto -- el depth no alcanzo para este
            # nivel. Fallback: pedirlo aparte.
            children.append(fetch_subpage_manual(session, child_codename, seen))

    return {
        "codename": item.get("system", {}).get("codename"),
        "title": text_value("title"),
        "content_html": text_value("content"),
        "diagram_json": text_value("diagram__diagram"),
        "footnotes_html": text_value("footnotes"),
        "last_modified": item.get("system", {}).get("last_modified"),
        "subpages": children,
    }


def _is_cloudflare_challenge(html):
    """
    True si el HTML es la pagina de verificacion de Cloudflare
    ('Just a moment...') en vez del contenido real. Sin esto, un
    challenge sin resolver se guarda como si fuera exito.
    """

    if not html:
        return False

    markers = ("Just a moment", "challenges.cloudflare.com", "cf-please-wait")
    return any(marker in html for marker in markers)


def fetch_html_with_browser(article_url):
    """
    Devuelve el HTML ya renderizado de la pagina del articulo,
    usando un navegador real -- 'requests' plano da 403 en
    annalsofoncology.org/esmoopen.com incluso en la pagina de
    lectura normal. No garantiza pasar un challenge de Cloudflare
    real (un headless suele detectarse como tal); por eso se
    verifica el resultado antes de darlo por bueno. Devuelve None
    si falla, sin imprimir nada -- el resultado lo reporta el
    llamador.
    """

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(user_agent=BROWSER_USER_AGENT)
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = context.new_page()

        try:
            page.goto(article_url, wait_until="domcontentloaded", timeout=60000)

            html = page.content()
            for _ in range(3):
                if not _is_cloudflare_challenge(html):
                    break
                page.wait_for_timeout(5000)
                html = page.content()

            return None if _is_cloudflare_challenge(html) else html

        except Exception:
            return None

        finally:
            browser.close()


def download_pdf_with_browser(article_url, pdf_url, out_path):
    """
    Fallback con navegador real (Playwright). Requiere:

        pip install playwright
        playwright install chromium

    IMPORTANTE: pdf_url dispara una descarga de archivo, no una
    navegacion normal -- page.goto(pdf_url) por si solo lanza
    net::ERR_ABORTED siempre que el servidor responda con
    Content-Disposition de descarga. Por eso el goto va envuelto
    en page.expect_download() (la forma correcta de capturar una
    descarga disparada por el navegador) en vez de leer la
    response del goto directo.

    No garantiza pasar TODO tipo de anti-bot. Devuelve True/False
    sin imprimir nada -- el resultado lo reporta el llamador.
    """

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=BROWSER_USER_AGENT)
        page = context.new_page()

        try:
            if article_url:
                page.goto(article_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)

            with page.expect_download(timeout=60000) as download_info:
                try:
                    page.goto(pdf_url, wait_until="domcontentloaded", timeout=60000)
                except Exception:
                    # Puede pasar aunque la descarga si se haya
                    # disparado -- se confirma con download_info.value.
                    pass

            download_info.value.save_as(out_path)
            return True

        except Exception:
            return False

        finally:
            browser.close()


def slugify(text):
    """Nombre de archivo seguro a partir de un display_name arbitrario."""

    text = re.sub(r"[^\w\-. ]", "", text or "archivo")
    text = re.sub(r"\s+", "_", text.strip())
    return text[:80] or "archivo"


def download_file_assets(session, modular_content, module_id, date_str):
    """
    Busca items tipo 'file' en modular_content (slide sets .pptx,
    hojas de referencias .ris, etc.) y descarga cada uno. Kontent.ai
    ya resuelve estos items sin importar en que nivel del arbol
    esten referenciados -- alcanza con recorrer modular_content
    plano, no hace falta bajar por subpages/related_tools a mano.

    Para los .pptx, ademas extrae el texto a un .txt aparte -- es
    lo que le permite a review.py detectarlo como snapshot diffeable
    cuando la unica actualizacion disponible es el slide set (sin
    HTML nuevo todavia).
    """

    saved = []

    for item_codename, item in modular_content.items():

        if item.get("system", {}).get("type") != "file":
            continue

        elements = item.get("elements", {})
        raw_field = elements.get("cldfil__file", {}).get("value")

        if not raw_field:
            continue

        try:
            assets = json.loads(raw_field)
        except (json.JSONDecodeError, TypeError):
            continue

        for asset in assets:

            url = asset.get("secure_url") or asset.get("url")
            if not url:
                continue

            display_name = asset.get("display_name") or item_codename
            suffix = Path(url).suffix or (
                f".{asset['format']}" if asset.get("format") else ""
            )

            out_dir = OUTPUT_ROOT / module_id / "documents"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{date_str}_{slugify(display_name)}{suffix}"

            try:
                response = session.get(url, timeout=180)
                response.raise_for_status()
            except requests.RequestException as error:
                print(f"  ERROR al descargar adjunto {display_name}: {error}")
                continue

            out_path.write_bytes(response.content)
            print(f"  Guardado en: {out_path}")
            saved.append(out_path)

            if suffix.lower() == ".pptx":
                text = pptx_text.extract_pptx_text(out_path)
                if text:
                    text_path = out_dir / f"{date_str}_slides.txt"
                    text_path.write_text(text, encoding="utf-8")
                    print(f"  Texto extraido: {text_path.name}")

    return saved


def download_cpg_pdf(session, codename, module_id, elements):
    """
    Guarda el contenido de un CPG estatico: HTML del articulo
    (fuente principal, con respaldo de navegador real si 'requests'
    da 403) y PDF (mejor esfuerzo, no bloquea el resultado si
    falla -- el HTML ya guardado sirve como fuente).

    Devuelve el Path del documento disponible (HTML si existe,
    si no PDF), o None si no se pudo obtener ninguno.
    """

    pdf_url = elements.get("article_pdf", {}).get("value")
    article_url = elements.get("article_url", {}).get("value")

    if not article_url and not pdf_url:
        print(f"ERROR: {module_id} ({codename}) no tiene article_url ni article_pdf.")
        return None

    last_update = elements.get("last_update", {}).get("value") or datetime.now(timezone.utc).isoformat()
    date_str = last_update[:10]

    out_dir = OUTPUT_ROOT / module_id / "documents"
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{date_str}_full.html"
    pdf_path = out_dir / f"{date_str}_full.pdf"

    def best_available():
        if html_path.exists():
            return html_path
        if pdf_path.exists():
            return pdf_path
        return None

    if html_path.exists() and pdf_path.exists():
        print(f"Ya existen {html_path.name} y {pdf_path.name} -- no se vuelve a descargar.")
        return best_available()

    print(f"Descargando contenido: {module_id}")

    article_session = requests.Session()
    article_session.headers.update({
        "User-Agent": BROWSER_USER_AGENT,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
    })

    if article_url and not html_path.exists():

        html_text = None

        try:
            html_response = article_session.get(article_url, timeout=60)
            html_response.raise_for_status()
            html_text = html_response.text

        except requests.RequestException as error:
            print(f"  HTML bloqueado por requests ({error}) -- probando con navegador...")

            try:
                html_text = fetch_html_with_browser(article_url)
            except ImportError:
                print(
                    "  Playwright no esta instalado (pip install playwright && "
                    "playwright install chromium) -- no se pudo intentar el fallback de HTML."
                )
            except Exception as browser_error:
                print(f"  ERROR con navegador al descargar HTML: {browser_error}")

        if html_text:
            html_path.write_text(html_text, encoding="utf-8")
            print(f"  Guardado: {html_path.name}")
        else:
            print("  No se pudo obtener el HTML del articulo (ni con requests ni con navegador).")

    elif html_path.exists():
        print(f"  Ya existe {html_path.name}.")

    if not pdf_url or pdf_path.exists():
        if pdf_path.exists():
            print(f"  Ya existe {pdf_path.name}.")
        return best_available()

    article_session.headers["Referer"] = article_url or pdf_url
    article_session.headers["Accept"] = "application/pdf,*/*"

    pdf_saved = False

    try:
        pdf_response = article_session.get(pdf_url, timeout=120)
        if pdf_response.status_code == 200:
            pdf_response.raise_for_status()
            pdf_path.write_bytes(pdf_response.content)
            pdf_saved = True
    except requests.RequestException:
        pass

    if pdf_saved:
        print(f"  Guardado: {pdf_path.name}")
        return best_available()

    try:
        pdf_saved = download_pdf_with_browser(article_url, pdf_url, pdf_path)
    except ImportError:
        pdf_saved = False
        print(
            "  Playwright no esta instalado (pip install playwright && "
            "playwright install chromium) -- no se pudo intentar el fallback de PDF."
        )
    except Exception as browser_error:
        pdf_saved = False
        print(f"  ERROR con navegador al descargar PDF: {browser_error}")

    if pdf_saved:
        print(f"  Guardado: {pdf_path.name}")
    else:
        print(
            "  PDF no descargado -- el HTML ya guardado (si lo hay) sirve como "
            "fuente. Descarga manual del PDF si lo quieres igual:\n"
            f"    {pdf_url}"
        )

    return best_available()


def download_living_guideline_html(session, codename, module_id, raw_item, session_for_fallback):
    """
    Guarda el contenido de una living guideline como HTML crudo --
    sin armar el arbol diffable (_tree.json) ni ninguna estructura
    propia, solo el content_html/footnotes_html tal cual los tiene
    ESMO, seccion por seccion, en el orden del arbol de subpages
    (necesitamos recorrer subpages igual para juntar el contenido,
    pero no se persiste como estructura -- solo se usa para leer).
    """

    items = raw_item.get("items", [])
    modular_content = raw_item.get("modular_content", {})

    if not items:
        print(f"ERROR: no se encontro el item raiz {codename} ({module_id}).")
        return None

    root_item = items[0]
    elements = root_item.get("elements", {})

    last_update = elements.get("last_update", {}).get("value") or datetime.now(timezone.utc).isoformat()
    date_str = last_update[:10]

    out_dir = OUTPUT_ROOT / module_id / "documents"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date_str}_content.html"

    if out_path.exists():
        print(f"Ya existe {out_path.name} -- no se vuelve a descargar.")
        return out_path

    print(f"Descargando contenido: {module_id}")

    seen = set()
    tree = build_section_node(root_item, modular_content, session_for_fallback, seen)

    html_content = render_html.render_raw_living_guideline_html(tree, module_id, date_str)

    out_path.write_text(html_content, encoding="utf-8")

    print(f"  Guardado en: {out_path}")

    return out_path


def process(codename, module_id):

    session = build_session()

    try:
        raw = fetch_item(session, codename, depth=CONTENT_DEPTH)
    except requests.RequestException as error:
        print(f"ERROR al pedir {module_id} ({codename}): {error}")
        return None

    items = raw.get("items", [])
    if not items:
        print(f"ERROR: no se encontro el item {codename} ({module_id}).")
        return None

    elements = items[0].get("elements", {})
    modular_content = raw.get("modular_content", {})

    last_update = elements.get("last_update", {}).get("value") or datetime.now(timezone.utc).isoformat()
    date_str = last_update[:10]

    document_path = None

    if elements.get("article_pdf", {}).get("value"):
        document_path = download_cpg_pdf(session, codename, module_id, elements)
    elif "subpages" in elements:
        document_path = download_living_guideline_html(session, codename, module_id, raw, session)
    else:
        print(f"ERROR: {module_id} ({codename}) no tiene article_pdf ni subpages -- tipo desconocido.")
        return None

    saved_assets = download_file_assets(session, modular_content, module_id, date_str)

    pptx_path = next((p for p in saved_assets if p.suffix.lower() == ".pptx"), None)

    if pptx_path is not None:
        # El slide set se prefiere sobre el HTML/PDF como documento
        # para comparar -- el HTML/PDF igual queda guardado en disco
        # (document_path arriba), solo no es lo que se le pasa al LLM.
        print(f"  Usando el slide set como documento a comparar: {pptx_path.name}")
        return pptx_path

    return document_path

if __name__ == "__main__":

    if len(sys.argv) < 2:
        print(
            "Uso: python -m guidelineUpdate.scraper.download_content <module_id1> [<module_id2> ...]\n"
            "Ejemplo: python -m guidelineUpdate.scraper.download_content esmo_uveal_melanoma"
        )
        sys.exit(1)

    module_ids = sys.argv[1:]

    for module_id in module_ids:
        state = state_manager.load_state(module_id)

        if not state:
            print(f"ERROR: {module_id} no tiene estado guardado. Corre esmo.py primero.")
            continue

        codename = state.get("source", {}).get("codename")

        if not codename:
            print(f"ERROR: {module_id} no tiene codename resuelto en su estado.")
            continue

        try:
            process(codename, module_id)
        except Exception as error:
            print(f"ERROR inesperado procesando {module_id} ({codename}): {error}")