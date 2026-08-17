import datetime
import os

from .scraper.search_update import ESMOScraper
from .scraper import download_content
from .agent import rule_agent
from .state import state_manager


def _build_llm_client():
    api_key = os.environ.get("LLM_API_KEY")

    if not api_key:
        print("LLM_API_KEY no configurada -- usando RuleBasedLLMClient (no genera propuestas).")
        return rule_agent.RuleBasedLLMClient()

    return rule_agent.LangGraphLLMClient(api_key=api_key)


def _append_history_entry(module_id, *, previous_version, new_version, previous_date,
                           new_date, detected_at, source_document, proposal_dir):

    history_path = rule_agent.OUTPUT_ROOT / module_id / "history.md"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    entry = (
        f"## {datetime.date.today().isoformat()} - {module_id}\n\n"
        f"- Version anterior: {previous_version or 'desconocida'}\n"
        f"- Version nueva: {new_version}\n"
        f"- Fecha anterior (last_known_update): {previous_date or 'sin sincronizar'}\n"
        f"- Fecha nueva (last_update): {new_date}\n"
        f"- Detectado: {detected_at or 'desconocido'}\n"
        f"- Documento fuente: {source_document or 'no descargado'}\n"
        f"- Propuesta: {proposal_dir or 'sin propuesta computable -- requiere revision manual del documento'}\n"
        f"- Estado de revision: pending_clinical_review\n\n"
    )

    with history_path.open("a", encoding="utf-8") as file:
        file.write(entry)


def run():
    scraper = ESMOScraper()
    updates = scraper.check_updates()

    if not updates:
        print("Sin actualizaciones.")
        return

    llm_client = _build_llm_client()
    using_stub = isinstance(llm_client, rule_agent.RuleBasedLLMClient)

    for update in updates:
        module_id = update["module_id"]
        codename = update["codename"]

        print(f"Procesando {module_id}...")

        previous_state = state_manager.load_state(module_id) or {}
        previous_version = previous_state.get("source", {}).get("version")
        previous_date = previous_state.get("sync", {}).get("last_known_update")
        detected_at = previous_state.get("sync", {}).get("last_checked_at")

        document_path = download_content.process(codename, module_id)

        if document_path is None:
            print(f"  No se pudo descargar el documento nuevo de {module_id} -- se reintenta en el proximo run.")
            _append_history_entry(
                module_id,
                previous_version=previous_version,
                new_version=update.get("version"),
                previous_date=previous_date,
                new_date=update.get("last_update"),
                detected_at=detected_at,
                source_document=None,
                proposal_dir=None,
            )
            continue

        current_context = rule_agent.load_module_rule_context(module_id)

        if current_context is None:
            print(f"  No se encontro guidelines/ para {module_id} -- no se puede generar propuesta.")
            continue

        new_text = rule_agent.load_new_document_text(document_path)
        new_images = rule_agent.load_new_document_images(document_path)

        result = llm_client.draft_rule_change(current_context, new_text, module_id, new_images)

        proposal_dir = None

        if result and result.get("proposed_files"):
            proposal_dir = rule_agent.write_proposed_rule_folder(
                module_id, result["proposed_files"], result.get("draft", "")
            )
        elif result:
            print(f"  El borrador no incluyo cambios computables para {module_id} -- revisar manualmente.")
        else:
            print(f"  Sin propuesta automatica para {module_id}.")

        _append_history_entry(
            module_id,
            previous_version=previous_version,
            new_version=update.get("version"),
            previous_date=previous_date,
            new_date=update.get("last_update"),
            detected_at=detected_at,
            source_document=str(document_path),
            proposal_dir=str(proposal_dir) if proposal_dir else None,
        )

        if using_stub:
            print(f"  {module_id} descargado pero NO marcado como procesado (sin API key real) -- se reintentara en el proximo run.")
        else:
            state_manager.mark_processed(module_id, update.get("last_update"), update.get("id"))
            print(f"  {module_id} procesado.")


if __name__ == "__main__":
    run()