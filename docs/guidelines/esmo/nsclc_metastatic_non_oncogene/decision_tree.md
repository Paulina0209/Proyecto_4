# Árbol de decisión clínico

```text
NSCLC confirmado
  |
  +-- ¿Avanzado, metastásico o recurrente?
       |
       +-- No -> fuera del módulo
       |
       +-- Sí
            |
            +-- ¿Ruta molecular no dependiente de oncogén?
                 |
                 +-- No -> otro módulo
                 +-- Incompleta -> información insuficiente
                 |
                 +-- Sí
                      |
                      +-- Primera línea
                      |    |
                      |    +-- ECOG 0-1
                      |    |    |
                      |    |    +-- PD-L1 >=50
                      |    |    |    +-- Monoterapia respaldada
                      |    |    |    +-- Combinación según histología
                      |    |    |    +-- Si se requiere reducción rápida:
                      |    |    |         preferencia contextual por combinación
                      |    |    |
                      |    |    +-- PD-L1 <50
                      |    |         +-- Monoterapia no recomendada
                      |    |         +-- Combinación según histología
                      |    |
                      |    +-- ECOG 2
                      |    |    +-- PD-L1 >=50: monoterapia puede considerarse
                      |    |    +-- Quimio-ICI: revisión, no respaldo automático
                      |    |
                      |    +-- ECOG 3-4
                      |         +-- Pembrolizumab: posible desviación
                      |
                      +-- Segunda línea o posterior
                           |
                           +-- Sin ICI previa, ECOG 0-2, PD-L1 >=1
                           |    +-- Pembrolizumab monoterapia respaldada
                           |
                           +-- ICI previa
                                +-- Beneficio sustancial y suspensión no debida
                                |   a progresión/toxicidad grave:
                                |   reexposición puede considerarse
                                |
                                +-- Otros escenarios:
                                    revisión clínica
```
