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
