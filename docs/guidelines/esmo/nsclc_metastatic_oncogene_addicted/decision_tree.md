# Árbol de decisión clínico: NSCLC metastásico oncogén-adicto

```text
NSCLC confirmado, avanzado/metastásico/recurrente
  |
  +-- ¿Panel molecular completo disponible?
       |
       +-- No / incompleto -> completar NGS multiplex (preferido)
       |                       (EGFR, ALK, ROS1, BRAF, RET, MET, HER2, NTRK, KRAS G12C)
       |
       +-- Sí
            |
            +-- EGFR mutación sensibilizante (ex19del / L858R)
            |    |
            |    +-- Primera línea
            |    |    +-- Osimertinib preferido (esp. con metástasis SNC)
            |    |    +-- Alternativas monoterapia: erlotinib, gefitinib, afatinib, dacomitinib
            |    |    +-- Opciones: TKI + antiangiogénico (erlotinib-bev/ram)
            |    |    +-- Opción no EMA: gefitinib + carboplatino-pemetrexed
            |    |
            |    +-- Progresión moderada con beneficio clínico continuo
            |    |    +-- Continuar EGFR TKI
            |    |
            |    +-- Progresión sobre TKI 1G/2G
            |    |    +-- Testear T790M (plasma y/o rebiopsia)
            |    |         +-- T790M+ -> Osimertinib (2ª línea)
            |    |         +-- T790M- -> Quimioterapia doblete platino
            |    |
            |    +-- Progresión sobre osimertinib
            |         +-- NGS si es factible (identificar mecanismo)
            |         +-- Quimioterapia doblete platino (estándar)
            |         +-- Considerar ensayo clínico
            |         +-- PS 0-1, sin contraindicación ICI: considerar atezo-bev-pac-carbo
            |         +-- Solo tras fallo TKI + quimio: ICI monoterapia puede considerarse
            |
            +-- EGFR mutación no común (no exón20, sensibilizante mayor)
            |    +-- Afatinib u osimertinib
            |
            +-- ALK reordenado
            |    +-- Primera línea: alectinib, brigatinib o lorlatinib (preferidos)
            |    +-- Progresión/intolerancia a crizotinib: alectinib (preferido), brigatinib o ceritinib
            |    +-- Progresión sobre TKI de 2ª generación: lorlatinib
            |    +-- Progresión sobre lorlatinib:
            |         +-- Quimioterapia platino-pemetrexed
            |         +-- Considerar atezo-bev-pac-carbo
            |
            +-- ROS1 reordenado
            |    +-- Primera línea: crizotinib o entrectinib
            |    |    (entrectinib preferido si hay metástasis cerebrales; repotrectinib si disponible)
            |    +-- Progresión tras crizotinib:
            |         +-- TKI de nueva generación si disponible
            |         +-- o quimioterapia basada en platino (2ª línea)
            |
            +-- BRAF V600 mutado
            |    +-- Dabrafenib + trametinib
            |    +-- Progresión:
            |         +-- Sin historia tabáquica -> quimio platino +/- inmunoterapia
            |         +-- Con historia tabáquica -> inmunoterapia +/- quimio (guía no oncogén-adicta)
            |
            +-- RET fusión positivo
            |    +-- Primera línea: selpercatinib o pralsetinib
            |
            +-- MET exón14 skipping / amplificación alta
            |    +-- Capmatinib o tepotinib (1ª o 2ª línea; no aprobado EMA)
            |    +-- Si no disponible: quimioterapia platino +/- ICI
            |
            +-- HER2 mutación exón20
            |    +-- Primera línea: quimioterapia platino +/- ICI
            |    +-- Tras primera línea: trastuzumab-deruxtecan (si disponible, no EMA)
            |
            +-- NTRK fusión
            |    +-- Primera línea: quimioterapia platino +/- ICI
            |    +-- Sin opciones satisfactorias: larotrectinib o entrectinib
            |
            +-- KRAS G12C mutado
            |    +-- Primera línea: seguir algoritmo NSCLC no oncogén-adicto
            |    +-- Progresión sobre ICI monoterapia 1ª línea: quimio platino
            |    +-- Fallo de terapia previa: sotorasib o adagrasib (adagrasib no EMA)
            |
            +-- EGFR exón20 inserción
                 +-- Primera línea: quimioterapia doblete platino
                 +-- Fallo de terapia previa: amivantamab o mobocertinib (mobocertinib no EMA)

Notas transversales (aplican a cualquier rama):
  - PS 2 o edad avanzada: no excluir por sí solos el uso de TKI si hay driver [III/II, A]
  - Enfermedad oligometastásica u oligoprogresiva: considerar terapia ablativa local + ensayo clínico
  - Seguimiento cada 8-12 semanas si hay opción de siguiente línea [IV, A]
  - Cuidados paliativos tempranos en paralelo al tratamiento oncológico [I, A]
```
