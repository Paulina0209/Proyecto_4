"""``python -m frontend`` = la demostración con datos sintéticos (ver ``frontend.demo``).
Con los datos reales (cBioPortal + usuarios del escenario): ``python -m frontend.real``."""
import sys

from frontend.demo import main

if __name__ == "__main__":
    sys.exit(main())
