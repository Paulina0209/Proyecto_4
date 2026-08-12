# Árbol de decisión — ESMO RCC avanzado/metastásico

```text
INICIO
  |
  +-- ¿La versión ESMO del 22-05-2024 aplica a la fecha?
  |      +-- NO / anterior --> recuperar versión histórica --> revisión
  |
  +-- ¿RCC e histopatología confirmados?
  |      +-- NO / desconocido --> no evaluable
  |
  +-- ¿Enfermedad avanzada o metastásica activa?
  |      |
  |      +-- localizada/locorregional --> módulo localizado/adyuvante
  |      +-- M1 NED --> módulo localizado/adyuvante
  |      +-- SÍ
  |
  +-- CLASIFICAR HISTOLOGÍA
         |
         +-- CLEAR-CELL
         |      |
         |      +-- primera línea
         |      |      +-- pembrolizumab + lenvatinib --> respaldado [I,A; MCBS 4]
         |      |      +-- pembrolizumab + axitinib --> respaldado [I,A; MCBS 4]
         |      |      +-- pembrolizumab solo --> revisión
         |      |
         |      +-- después de progresión con PD-1
         |             +-- nuevo PD-(L)1 --> posible desviación [I,D]
         |
         +-- PAPILAR
         |      |
         |      +-- primera línea
         |      |      +-- pembrolizumab solo --> alternativa [III,B]
         |      |      +-- pembrolizumab + lenvatinib --> alternativa [III,B]
         |      |
         |      +-- línea posterior y pembrolizumab no usado
         |             +-- pembrolizumab --> opción cautelosa [IV,C]
         |
         +-- CROMÓFOBO
         |      +-- pembrolizumab + lenvatinib --> puede utilizarse [III,C]
         |
         +-- SARCOMATOIDE PREDOMINANTE
         |      +-- pembrolizumab + axitinib --> opción ICI preferida [III,A]
         |      +-- pembrolizumab + lenvatinib --> opción ICI preferida [III,A]
         |
         +-- CONDUCTOS COLECTORES / SMARCB1 / FH DEFICIENTE
         |      +-- otra estrategia histológica --> revisión clínica
         |
         +-- DESCONOCIDA
                +-- solicitar histología --> no evaluable/revisión

LÍMITES TRANSVERSALES
  |
  +-- ICI contraindicada o no disponible --> revisión clínica
  +-- 24 meses de ICI --> considerar finalización [IV,B]
  +-- CT con intervalo >4 meses --> aviso de seguimiento [IV,B]
  +-- progresión durante tratamiento --> revisión; no suspender automáticamente
  +-- toxicidad --> revisión clínica
```

## Nota técnica

El motor actual reconoce condiciones y produce trazabilidad por regla. La orquestación completa deberá evaluar primero la elegibilidad, después la histología y la línea terapéutica, y finalmente comparar el régimen prescrito.
