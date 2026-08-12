# Clinical matrix - ESMO cutaneous melanoma

## 1. Module identification

| Field | Value |
|---|---|
| Module | `esmo_cutaneous_melanoma` |
| Guideline | *Cutaneous melanoma: ESMO Clinical Practice Guideline for diagnosis, treatment and follow-up* |
| Organization | ESMO |
| DOI | `10.1016/j.annonc.2024.11.006` |
| Available online | 14 November 2024 |
| Journal issue | Volume 36, Issue 1, 2025 |
| Drug audited | Pembrolizumab |
| Status | Computable draft; clinical validation pending |

## 2. Scope

### Included

- Confirmed invasive cutaneous melanoma.
- Acral cutaneous melanoma when documented as a cutaneous primary.
- Completely resected AJCC8 stage IIB-IIC disease.
- Completely resected stage III disease.
- Selected resected stage IV disease with no evidence of disease.
- Resectable stage III disease with pathologically proven, clinically or radiologically detectable nodal metastasis.
- Resectable or unresectable in-transit metastases.
- Unresectable stage III and metastatic stage IV disease.

### Excluded or routed elsewhere

- Uveal melanoma.
- Mucosal melanoma.
- Non-melanoma skin cancer.
- Melanoma in situ as a pembrolizumab treatment pathway.
- Active melanoma brain metastases, which require the dedicated specialized pathway.

## 3. Temporal applicability

The source became available online on **14 November 2024**. Records before that date must be reviewed against the guideline version in force on the prescription date. The current module therefore does not retrospectively impose the 2024 update on earlier 2024 prescriptions.

## 4. Evidence model

Every rule preserves:

- ESMO native level of evidence.
- ESMO native grade of recommendation.
- ESMO-MCBS v1.1 when explicitly reported.
- Whether the statement is drug-specific, class-level, protocol-context, scope-only or interpretive.
- Regulatory status exactly as reported by the source.

The ESMO-MCBS is not used as a replacement for the level of evidence or recommendation grade.

## 5. Main pembrolizumab pathways

### 5.1 Adjuvant stage IIB-IIC

For completely resected stage IIB-IIC disease, pembrolizumab for 12 months is a positive pathway. The recommendation is `[I, A]` with ESMO-MCBS v1.1 score `A`. Benefit-risk discussion must acknowledge the recurrence-free survival benefit and the absence of mature overall-survival data.

### 5.2 Adjuvant resected stage III

Pembrolizumab is a positive adjuvant option after complete resection of stage III melanoma. The recommendation is `[I, A]` with ESMO-MCBS v1.1 score `A`. The treatment should start within 12 weeks of complete resection. AJCC8 stage IIIA with sentinel-node tumour burden below 1 mm is treated as an explicit negative boundary `[I, D]`.

### 5.3 Neoadjuvant plus adjuvant sequence

For resectable stage III melanoma with pathologically proven, clinically or radiologically detectable nodal metastasis, neoadjuvant plus adjuvant pembrolizumab is recommended `[II, A]`. The guide reports that this neoadjuvant use was not EMA or FDA approved at the time of writing.

The SWOG S1801 protocol context is preserved separately:

- Three preoperative doses.
- Surgery.
- Fifteen postoperative doses.
- Pembrolizumab 200 mg every three weeks.

These cycle counts are protocol context, not a universal stand-alone dosing rule.

### 5.4 In-transit metastases

For resectable in-transit metastases, neoadjuvant plus adjuvant pembrolizumab may be evaluated `[II, A]`. For unresectable satellite or in-transit metastases, anti-PD-1-based systemic therapy is a class-level recommendation `[I, A]`. The latter is not mislabeled as a drug-specific pembrolizumab statement.

### 5.5 Resected stage IV with no evidence of disease

After complete local treatment of resectable stage IV melanoma, adjuvant anti-PD-1 therapy is supported `[I, A]`. This is modeled as a **class-level** rule with pembrolizumab as a candidate class member.

### 5.6 Unresectable stage III or stage IV

Pembrolizumab monotherapy is a recommended first-line option `[I, A]`, ESMO-MCBS v1.1 `A/4`, independent of BRAF and PD-L1 status. BRAF testing remains a separate mandatory diagnostic requirement for stage III-IV disease.

Pembrolizumab also appears as a second-line option `[I, A]`, ESMO-MCBS v1.1 `A/4`. The computable rule restricts routine support to anti-PD-1-naive patients, because immediate pembrolizumab reuse after progression on prior anti-PD-1 therapy is not represented as routine second-line care.

## 6. Important review boundaries

- Historical prescription before 14 November 2024.
- Uveal or mucosal primary.
- Non-invasive or in-situ disease.
- Stage IIIA with sentinel-node burden below 1 mm.
- Neoadjuvant pembrolizumab without a planned adjuvant phase.
- Neoadjuvant use without the guide-defined nodal or in-transit population.
- Missing BRAF V600 testing in stage III-IV disease.
- Immediate or absolute ICI contraindication.
- Active melanoma brain metastases.
- Pembrolizumab plus lenvatinib after anti-PD-1 progression.
- Pembrolizumab plus talimogene laherparepvec.
- Immediate pembrolizumab reuse after anti-PD-1 progression.
- Adjuvant start beyond 12 weeks after complete resection.
- Stage IIB-IIC use below 12 years.
- Stage I or IIA adjuvant use, where the guide has no positive pembrolizumab pathway.

## 7. Variable matrix

| Variable | Purpose | Typical values |
|---|---|---|
| `guideline_temporal_applicability` | Select the historically applicable source version | `applicable`, `not_yet_published`, `uncertain` |
| `melanoma_primary_site` | Separate cutaneous from uveal and mucosal disease | `cutaneous`, `acral_cutaneous`, `uveal`, `mucosal` |
| `stage_group` | AJCC8 stage routing | `IIB`, `IIC`, `IIIA`-`IIID`, `IV` |
| `disease_setting` | Distinguish resected, neoadjuvant and advanced settings | `resectable_stage_III`, `resectable_stage_IV_NED`, `unresectable_stage_III`, `metastatic_stage_IV` |
| `sentinel_node_tumor_burden_mm` | Identify the stage IIIA below-1-mm negative boundary | Numeric |
| `weeks_since_complete_resection` | Evaluate the 12-week start window | Numeric |
| `clinically_or_radiologically_detectable_ln_metastasis` | Neoadjuvant population criterion | `yes`, `no` |
| `pathologically_proven_ln_metastasis` | Neoadjuvant population criterion | `yes`, `no` |
| `braf_testing_completed` | Mandatory stage III-IV molecular work-up | `yes`, `no` |
| `braf_v600_status` | Treatment sequencing context | `V600E`, `V600K`, `wild_type` |
| `ici_suitability` | Route temporary and absolute contraindications | `eligible`, `immediate_contraindication`, `absolute_contraindication` |
| `brain_metastasis_status` | Route active brain metastatic disease | `none`, `treated_stable`, `asymptomatic_active`, `symptomatic_*`, `leptomeningeal` |
| `prior_anti_pd1_exposure` | Distinguish anti-PD-1-naive from previously exposed disease | `yes`, `no` |
| `progression_on_prior_anti_pd1` | Identify post-anti-PD-1 progression | `yes`, `no` |
| `prescribed_antineoplastic_drugs` | Compare the actual prescription with supported regimens | List of normalized drug names |

## 8. Rule catalogue

| Rule ID | File | Purpose | Audit effect | Statement scope | Native evidence | Source |
|---|---|---|---|---|---|---|
| `ESMO-MEL-CUT-ELIG-001` | `eligibility.yaml` | Case eligible for the invasive cutaneous melanoma module | `none` | `scope_definition` | No explicit grade | p. 10 |
| `ESMO-MEL-CUT-NEO-001` | `neoadjuvant.yaml` | Neoadjuvant plus adjuvant pembrolizumab for resectable stage III with detectable nodal metastasis | `supports_prescription` | `drug_specific` | II/A | pp. 16 and 18 |
| `ESMO-MEL-CUT-NEO-002` | `neoadjuvant.yaml` | Neoadjuvant plus adjuvant pembrolizumab for resectable in-transit metastases | `supports_prescription` | `drug_specific` | II/A | pp. 15 and 17 |
| `ESMO-MEL-CUT-ADJ-001` | `adjuvant.yaml` | Pembrolizumab adjuvant for completely resected stage IIB-IIC melanoma | `supports_prescription` | `drug_specific` | I/A; MCBS 1.1:A | pp. 12-13 and 17 |
| `ESMO-MEL-CUT-ADJ-002` | `adjuvant.yaml` | Pembrolizumab adjuvant for completely resected stage III melanoma | `supports_prescription` | `drug_specific` | I/A; MCBS 1.1:A | pp. 14 and 17-18 |
| `ESMO-MEL-CUT-ADJ-003` | `adjuvant.yaml` | Adjuvant anti-PD-1 after complete treatment of resectable stage IV melanoma | `supports_prescription` | `class_level` | I/A | pp. 18 and 22 |
| `ESMO-MEL-CUT-ADJ-004` | `adjuvant.yaml` | Adjuvant continuation after neoadjuvant pembrolizumab and surgery | `supports_prescription` | `drug_specific` | II/A | pp. 16 and 18 |
| `ESMO-MEL-CUT-MET-001` | `unresectable_metastatic.yaml` | First-line pembrolizumab monotherapy for unresectable stage III or stage IV melanoma | `supports_prescription` | `drug_specific` | I/A; MCBS 1.1:A/4 | pp. 18 and 22-23 |
| `ESMO-MEL-CUT-MET-002` | `unresectable_metastatic.yaml` | Second-line pembrolizumab for an anti-PD-1-naive patient | `supports_prescription` | `drug_specific` | I/A; MCBS 1.1:A/4 | p. 23 |
| `ESMO-MEL-CUT-MET-003` | `unresectable_metastatic.yaml` | Anti-PD-1-based systemic therapy for unresectable satellite or in-transit metastases | `supports_prescription` | `class_level` | I/A | pp. 15 and 17 |
| `ESMO-MEL-CUT-MET-004` | `unresectable_metastatic.yaml` | Third-line ICI-class rechallenge requires individualized review | `requires_clinical_review` | `class_level` | IV/B | p. 24 |
| `ESMO-MEL-CUT-CONT-001` | `continuation.yaml` | Review planned completion at 12 months for stage IIB-IIC adjuvant pembrolizumab | `advisory` | `drug_specific` | I/A; MCBS 1.1:A | p. 17 |
| `ESMO-MEL-CUT-CONT-002` | `continuation.yaml` | Surgery checkpoint after three neoadjuvant pembrolizumab doses in the SWOG S1801 sequence | `advisory` | `protocol_context` | II/A | pp. 16 and 18 |
| `ESMO-MEL-CUT-CONT-003` | `continuation.yaml` | Review planned completion after fifteen postoperative doses in the SWOG S1801 sequence | `advisory` | `protocol_context` | II/A | pp. 16 and 18 |
| `ESMO-MEL-CUT-CONT-004` | `continuation.yaml` | Progression or recurrence during pembrolizumab requires treatment reassessment | `requires_clinical_review` | `clinical_boundary` | No explicit grade | pp. 21-24 |
| `ESMO-MEL-CUT-CONT-005` | `continuation.yaml` | Pembrolizumab interruption for toxicity requires specialist review | `requires_clinical_review` | `clinical_boundary` | No explicit grade | pp. 12-24 |
| `ESMO-MEL-CUT-EXC-000` | `exclusions.yaml` | Historical guideline version required before 14 November 2024 | `requires_clinical_review` | `temporal_governance` | No explicit grade | p. 10 |
| `ESMO-MEL-CUT-EXC-001` | `exclusions.yaml` | Non-cutaneous melanoma is outside this module | `outside_scope` | `scope_definition` | No explicit grade | p. 10 |
| `ESMO-MEL-CUT-EXC-002` | `exclusions.yaml` | Melanoma in situ or non-invasive disease is outside the pembrolizumab treatment pathway | `requires_clinical_review` | `scope_definition` | No explicit grade | pp. 10 and 12 |
| `ESMO-MEL-CUT-EXC-003` | `exclusions.yaml` | Adjuvant systemic treatment is generally not recommended for AJCC8 stage IIIA with sentinel-node burden below 1 mm | `potential_deviation` | `class_level` | I/D | p. 18 |
| `ESMO-MEL-CUT-EXC-004` | `exclusions.yaml` | Neoadjuvant pembrolizumab without a planned adjuvant phase does not match the recommended sequence | `requires_clinical_review` | `regimen_sequence` | II/A | p. 18 |
| `ESMO-MEL-CUT-EXC-005` | `exclusions.yaml` | Neoadjuvant pembrolizumab outside pathologically proven clinically detectable nodal disease requires review | `requires_clinical_review` | `population_boundary` | II/A | p. 18 |
| `ESMO-MEL-CUT-EXC-006` | `exclusions.yaml` | BRAF V600 testing missing in stage III or IV melanoma | `requires_clinical_review` | `diagnostic_requirement` | I/A | p. 11 |
| `ESMO-MEL-CUT-EXC-007` | `exclusions.yaml` | Immediate contraindication to ICI requires reassessment before pembrolizumab | `requires_clinical_review` | `figure_footnote` | No explicit grade | p. 19 |
| `ESMO-MEL-CUT-EXC-008` | `exclusions.yaml` | Absolute contraindication to ICI requires multidisciplinary review | `requires_clinical_review` | `figure_footnote` | No explicit grade | p. 19 |
| `ESMO-MEL-CUT-EXC-009` | `exclusions.yaml` | Active melanoma brain metastases require the dedicated brain-metastasis pathway | `requires_clinical_review` | `specialized_pathway` | No explicit grade | pp. 23-24 |
| `ESMO-MEL-CUT-EXC-010` | `exclusions.yaml` | Pembrolizumab plus lenvatinib after anti-PD-1 progression is not approved as reported by the guide | `requires_clinical_review` | `narrative_evidence` | No explicit grade | pp. 21 and 24 |
| `ESMO-MEL-CUT-EXC-011` | `exclusions.yaml` | Pembrolizumab combined with T-VEC requires review because no additional clinical benefit was reported | `requires_clinical_review` | `narrative_evidence` | No explicit grade | p. 18 |
| `ESMO-MEL-CUT-EXC-012` | `exclusions.yaml` | Immediate pembrolizumab reuse after anti-PD-1 progression is not routine second-line care | `requires_clinical_review` | `sequencing_interpretation` | No explicit grade | pp. 21-24 |
| `ESMO-MEL-CUT-EXC-013` | `exclusions.yaml` | Adjuvant pembrolizumab initiated more than 12 weeks after complete resection requires review | `requires_clinical_review` | `timing_requirement` | I/A | pp. 17-18 |
| `ESMO-MEL-CUT-EXC-014` | `exclusions.yaml` | Stage IIB-IIC adjuvant pembrolizumab below age 12 requires review | `requires_clinical_review` | `trial_and_regulatory_boundary` | No explicit grade | p. 12 |
| `ESMO-MEL-CUT-EXC-015` | `exclusions.yaml` | Adjuvant pembrolizumab in stage I or IIA is outside the positive pembrolizumab recommendations in this guide | `requires_clinical_review` | `absence_of_positive_recommendation` | No explicit grade | pp. 13 and 17 |

## 9. Validation status

### Completed

- YAML syntax validation.
- Unique rule identifiers.
- Synthetic cases for all positive pathways and major boundaries.
- Preservation of native ESMO evidence.
- Tests that BRAF and PD-L1 are not incorrectly used as pembrolizumab eligibility thresholds.
- Tests that missing values are not silently converted to negative values.

### Pending

- Specialist review of each rule antecedent and conclusion.
- Verification against the exact local data fields available from the oncology centre.
- Validation of drug normalization and prescription matching.
- Historical guideline selection for prescriptions before 14 November 2024.
- Clinical validation against the expert gold standard.
- Permission review before any public distribution of the derived knowledge base.

## 10. Interpretation rule

A positive rule means that the clinical facts match a supported ESMO pathway. It does not by itself prove that the actual prescription is concordant until the regimen comparator confirms that the prescribed drug or sequence matches the rule conclusion.

A review rule is not automatically a deviation. Only explicit negative recommendations, such as the AJCC8 stage IIIA sentinel-node burden below 1 mm boundary, are marked as potential deviation before expert adjudication.
