# Decision tree - ESMO cutaneous melanoma

## 1. Entry and scope

```text
Confirmed melanoma?
 |
 +-- No ------------------------------> outside_scope
 |
 +-- Unknown -------------------------> not_evaluable
 |
 +-- Yes
      |
      +-- Primary site cutaneous/acral cutaneous?
           |
           +-- Uveal or mucosal ------> route_to_other_module
           |
           +-- Unknown ---------------> not_evaluable
           |
           +-- Cutaneous
                |
                +-- Invasive disease?
                     |
                     +-- No ----------> outside pembrolizumab pathway
                     |
                     +-- Yes ---------> temporal applicability
```

## 2. Temporal applicability

```text
Prescription date compared with 14-Nov-2024
 |
 +-- Before publication -------------> historical guideline version required
 |
 +-- Uncertain -----------------------> clinical review
 |
 +-- On/after publication -----------> clinical setting
```

## 3. Clinical setting

```text
Clinical setting
 |
 +-- Completely resected stage IIB-IIC
 |     |
 |     +-- Age >=12
 |     +-- NED
 |     +-- ICI eligible
 |             |
 |             +--> pembrolizumab adjuvant for 12 months
 |                  [I, A; MCBS v1.1 A]
 |
 +-- Completely resected stage III
 |     |
 |     +-- Started within 12 weeks?
 |     |      |
 |     |      +-- No ----------------> clinical review
 |     |
 |     +-- Stage IIIA?
 |            |
 |            +-- SLN burden <1 mm --> generally not recommended [I, D]
 |            |
 |            +-- SLN burden >=1 mm -> pembrolizumab adjuvant
 |                                      [I, A; MCBS v1.1 A]
 |     |
 |     +-- Stage IIIB-IIID ----------> pembrolizumab adjuvant
 |                                      [I, A; MCBS v1.1 A]
 |
 +-- Resectable stage III with clinically/radiologically detectable LN disease
 |     |
 |     +-- Pathologically proven?
 |     |      |
 |     |      +-- No ----------------> clinical review
 |     |
 |     +-- Planned postoperative pembrolizumab?
 |            |
 |            +-- No ----------------> sequence incomplete; review
 |            |
 |            +-- Yes ---------------> neoadjuvant pembrolizumab
 |                                      -> surgery
 |                                      -> adjuvant pembrolizumab
 |                                      [II, A]
 |
 +-- In-transit metastases
 |     |
 |     +-- Resectable ---------------> consider neoadjuvant + adjuvant
 |     |                                pembrolizumab [II, A]
 |     |
 |     +-- Unresectable -------------> anti-PD-1 class option [I, A]
 |
 +-- Resectable stage IV rendered NED
 |     |
 |     +--> adjuvant anti-PD-1 class option [I, A]
 |          pembrolizumab is a candidate class member
 |
 +-- Unresectable stage III or metastatic stage IV
       |
       +--> advanced systemic therapy pathway
```

## 4. Advanced systemic therapy

```text
Unresectable stage III / metastatic stage IV
 |
 +-- Active brain metastases? -------> dedicated brain-metastasis review
 |
 +-- ICI suitability
 |     |
 |     +-- Immediate contraindication -> reassess when resolved
 |     +-- Absolute contraindication --> multidisciplinary review
 |     +-- Eligible -------------------> treatment line
 |
 +-- First line
 |     |
 |     +-- Anti-PD-1 naive ----------> pembrolizumab monotherapy
 |                                      [I, A; MCBS v1.1 A/4]
 |                                      independent of BRAF and PD-L1
 |
 +-- Second line
 |     |
 |     +-- Anti-PD-1 naive ----------> pembrolizumab monotherapy
 |     |                                [I, A; MCBS v1.1 A/4]
 |     |
 |     +-- Progressed on anti-PD-1 --> other strategy / expert review
 |
 +-- Third or later line
       |
       +-- ICI not used in immediate prior line
              |
              +--> ICI-class rechallenge may be considered [IV, B]
                   drug-specific pembrolizumab support is not inferred
```

## 5. Continuation checkpoints

```text
Stage IIB-IIC adjuvant pembrolizumab
 |
 +-- Reaches 12 months -------------> planned completion advisory

SWOG S1801 protocol context
 |
 +-- 3 preoperative doses ----------> surgery timing advisory
 |
 +-- Surgery
 |
 +-- 15 postoperative doses --------> planned completion advisory

Any pembrolizumab setting
 |
 +-- Progression or recurrence ------> treatment reassessment
 |
 +-- Toxicity -----------------------> specialist review
```

## 6. Prescription comparison

```text
Applicable clinical rule
 |
 +-- Compare rule regimen/class with normalized prescription
       |
       +-- Match --------------------> supports prescription
       |
       +-- Explicit negative rule ---> potential deviation
       |
       +-- Missing critical fact ----> not evaluable
       |
       +-- Boundary or class-level ambiguity
                                      -> clinical review
```

## 7. Governance notes

- The decision tree preserves drug-specific and class-level recommendations separately.
- The ESMO-MCBS does not determine rule applicability.
- A class-level anti-PD-1 recommendation does not become a drug-specific pembrolizumab recommendation without an interpretation note.
- Active melanoma brain metastases are not evaluated by the general pembrolizumab monotherapy branch.
- The current generic engine evaluates rule files independently. A production orchestrator must enforce the order shown above.
- The derived knowledge base should remain private until permission and licensing questions are resolved.
