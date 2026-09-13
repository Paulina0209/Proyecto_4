"""Ruta compartida a guidelines/, usada por varias tools.

Antes vivía en agent.py, calculada como parent.parent porque agent.py
estaba directo en tx_clinica/. Ahora este archivo vive un nivel más
adentro (tx_clinica/tools/), así que sube un nivel más para llegar a la
raíz del repo.
"""

from __future__ import annotations

from pathlib import Path

GUIDELINES_ROOT = Path(__file__).resolve().parent.parent.parent / "guidelines"
