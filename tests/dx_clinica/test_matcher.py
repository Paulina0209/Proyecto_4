from dx_clinica.matcher import coincide_sin_negacion


def test_coincide_con_mencion_positiva():
    assert coincide_sin_negacion(
        "Impresión diagnóstica: sospecha de progresión de enfermedad pulmonar metastásica.",
        ("progresión",),
    )


def test_no_coincide_cuando_la_mencion_esta_negada():
    assert not coincide_sin_negacion(
        "reducción del tamaño tumoral respecto al estudio previo, sin hallazgos de progresión.",
        ("progresión",),
    )


def test_no_coincide_si_ninguna_palabra_clave_aparece():
    assert not coincide_sin_negacion("El paciente refiere dolor abdominal leve.", ("progresión", "disnea"))


def test_coincide_si_alguna_de_varias_palabras_clave_aparece():
    assert coincide_sin_negacion("Se palpa adenopatía axilar izquierda.", ("adenopatía", "disnea"))


def test_no_es_sensible_a_mayusculas():
    assert coincide_sin_negacion("SOSPECHA DE PROGRESIÓN evidente.", ("progresión",))


def test_negacion_con_no_tambien_se_detecta():
    assert not coincide_sin_negacion("no se observa fiebre en el paciente.", ("fiebre",))
