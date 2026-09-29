"""Configuración raíz de pytest.

Asegura que los paquetes de primer nivel del repositorio (por ejemplo
``ia_clinica`` y ``guidelines``) sean importables durante las pruebas sin
necesidad de instalar el proyecto como paquete.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Las pruebas nunca tocan la base real del copiloto (data/copiloto.db): la
# API de pacientes y el agente de tratamiento la abrirían por defecto.
import os
import tempfile

os.environ["COPILOTO_EXPEDIENTE_DB"] = str(Path(tempfile.mkdtemp(prefix="copiloto_tests_")) / "expediente.db")
