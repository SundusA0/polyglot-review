# Review of five automatically flagged omissions

> **Status: human review pending.** These are factual-coverage alerts from the
> deterministic scorer, **not** five confirmed failures to answer the user.
> Preliminary triage notes below are editorial hypotheses, not validated reviewer labels.

## Evaluation protocol

- 36 fictional HR questions across six languages; 36 model answers for each prompt version.
- The heuristic flags a response if its text is missing a reference key fact; that alone does not establish that the user needed the fact.
- Review question and policy first. Assign **relevance** as `essential`, `conditional`, `supplementary`, or `not relevant`.
- Assign **severity** as `high` (would likely mislead or materially impair user), `medium` (could matter in common contexts), `low` (minor useful detail), or `none` (answer meets question).
- Record a brief evidence-based rationale, reviewer, and review date. Do not equate an LLM judge score with a complete human quality evaluation.

## Triage overview

| Case | Missing reference fact(s) | v2 judge | v3 judge | Preliminary interpretation | Human relevance | Human severity |
| --- | --- | ---: | ---: | --- | --- | --- |
| [`pto_accrual-en`](#case-pto_accrual-en) | 15 | 5/5 | 5/5 | Supplemental annual total; the question asks about monthly accrual and carryover. | Pending | Pending |
| [`pto_accrual-es`](#case-pto_accrual-es) | 15 | 5/5 | 5/5 | Supplemental annual total; the question asks about monthly accrual and carryover. | Pending | Pending |
| [`pto_accrual-de`](#case-pto_accrual-de) | 15 | 5/5 | 5/5 | Supplemental annual total; the question asks about monthly accrual and carryover. | Pending | Pending |
| [`pay_schedule-fr`](#case-pay_schedule-fr) | 3 | 5/5 | 5/5 | Paper-cheque delay may matter for employees using cheques; user did not specify payment method. | Pending | Pending |
| [`pay_schedule-es`](#case-pay_schedule-es) | 3 | 5/5 | 4/5 | Paper-cheque delay may matter for employees using cheques; user did not specify payment method. | Pending | Pending |

## Detailed source evidence

Exact texts below come from [`data/live_responses.csv`](../data/live_responses.csv) and
[`data/cases.csv`](../data/cases.csv). Generated from immutable source rows; no fabricated judge remarks.

<a id="case-pto_accrual-en"></a>
### 1. `pto_accrual-en`

**User question**

> How many vacation days do I get each month, and can I roll over the ones I don't use?

**Fictional policy context**

> Full-time employees accrue 1.25 days of paid time off (PTO) per month, for a total of 15 days per year. Up to 5 unused PTO days may be carried over into the next calendar year, and carried-over days must be used by March 31.

**v2 — glossary-grounded output (verbatim)**

> Full-time employees accrue 1.25 days of paid time off per month, for a total of 15 days per year. You may carry over up to 5 unused paid time off days into the next calendar year. Please remember that any carried-over days must be used by March 31.

**v2 judge: 5/5**

> The assistant answer accurately and completely reflects all the facts from the policy context regarding PTO accrual, carry-over limits, and the deadline.

**v3 — stricter output (verbatim)**

> Full-time employees accrue 1.25 days of paid time off per month. Up to 5 unused paid time off days may be carried over into the next calendar year. Any carried-over days must be used by March 31.

**v3 judge: 5/5**

> The assistant answer is fully supported by the policy context, accurately stating the monthly accrual rate, the carry-over limit, and the March 31 deadline.

**Deterministic checker — missing reference facts:** `15`

**Preliminary triage (not validated):** Supplemental annual total; the question asks about monthly accrual and carryover.

**Human review:**
- Relevance (`essential` / `conditional` / `supplementary` / `not relevant`): **Pending**
- Severity (`high` / `medium` / `low` / `none`): **Pending**
- Required to answer this specific question? **Pending**
- Rationale and alternative interpretations: **Pending**
- Reviewer / date: **Pending**

---

<a id="case-pto_accrual-es"></a>
### 2. `pto_accrual-es`

**User question**

> ¿Cuántos días libres acumulo cada mes y puedo guardar los que no use?

**Fictional policy context**

> Los empleados a tiempo completo acumulan 1,25 días de vacaciones pagadas al mes, es decir, 15 días al año. Se pueden traspasar hasta 5 días de vacaciones pagadas no utilizados al siguiente año natural, y los días traspasados deben utilizarse antes del 31 de marzo.

**v2 — glossary-grounded output (verbatim)**

> ¡Hola! Como empleado a tiempo completo, acumulas 1,25 días de vacaciones pagadas al mes, lo que equivale a 15 días al año. Sí puedes guardar días no utilizados, ya que se permite traspasar hasta 5 días de vacaciones pagadas al siguiente año natural. Ten en cuenta que estos días traspasados deben utilizarse antes del 31 de marzo. ¡Estamos aquí para ayudarte si tienes más dudas!

**v2 judge: 5/5**

> La respuesta del asistente es totalmente precisa, está escrita en español y contiene todos los hechos de la política sin incluir ninguna información inventada.

**v3 — stricter output (verbatim)**

> Los empleados a tiempo completo acumulan 1,25 días de vacaciones pagadas al mes. Se pueden traspasar hasta 5 días de vacaciones pagadas no utilizados al siguiente año natural. Los días traspasados deben utilizarse antes del 31 de marzo.

**v3 judge: 5/5**

> La respuesta del asistente es completamente precisa, está respaldada por el contexto de la política y responde correctamente a la pregunta en español.

**Deterministic checker — missing reference facts:** `15`

**Preliminary triage (not validated):** Supplemental annual total; the question asks about monthly accrual and carryover.

**Human review:**
- Relevance (`essential` / `conditional` / `supplementary` / `not relevant`): **Pending**
- Severity (`high` / `medium` / `low` / `none`): **Pending**
- Required to answer this specific question? **Pending**
- Rationale and alternative interpretations: **Pending**
- Reviewer / date: **Pending**

---

<a id="case-pto_accrual-de"></a>
### 3. `pto_accrual-de`

**User question**

> Wie viele freie Tage bekomme ich pro Monat, und kann ich nicht genutzte Tage mitnehmen?

**Fictional policy context**

> Vollzeitbeschäftigte sammeln 1,25 Tage bezahlten Urlaub pro Monat an, insgesamt 15 Tage pro Jahr. Bis zu 5 nicht genutzte Urlaubstage können in das nächste Kalenderjahr übertragen werden; übertragene Tage müssen bis zum 31. März genommen werden.

**v2 — glossary-grounded output (verbatim)**

> Vollzeitbeschäftigte sammeln 1,25 Tage bezahlten Urlaub pro Monat an, was insgesamt 15 Tage pro Jahr ergibt. Sie können bis zu 5 nicht genutzte Urlaubstage in das nächste Kalenderjahr übertragen. Bitte beachten Sie, dass diese übertragenen Tage bis zum 31. März genommen werden müssen.

**v2 judge: 5/5**

> Die Antwort ist sachlich vollkommen korrekt, enthält keine unbelegten Behauptungen, lässt keine wesentlichen Fakten aus und ist auf Deutsch verfasst.

**v3 — stricter output (verbatim)**

> Vollzeitbeschäftigte sammeln 1,25 Tage bezahlten Urlaub pro Monat an. Bis zu 5 nicht genutzte Urlaubstage können in das nächste Kalenderjahr übertragen werden. Übertragene Tage müssen bis zum 31. März genommen werden.

**v3 judge: 5/5**

> Die Antwort ist sachlich völlig korrekt, wird vollständig durch den Kontext gestützt und enthält alle wichtigen Fakten in der geforderten Sprache.

**Deterministic checker — missing reference facts:** `15`

**Preliminary triage (not validated):** Supplemental annual total; the question asks about monthly accrual and carryover.

**Human review:**
- Relevance (`essential` / `conditional` / `supplementary` / `not relevant`): **Pending**
- Severity (`high` / `medium` / `low` / `none`): **Pending**
- Required to answer this specific question? **Pending**
- Rationale and alternative interpretations: **Pending**
- Reviewer / date: **Pending**

---

<a id="case-pay_schedule-fr"></a>
### 4. `pay_schedule-fr`

**User question**

> Quand est-ce que je reçois ma paie, et quand dois-je soumettre mes heures?

**Fictional policy context**

> Les employés sont payés toutes les deux semaines, le vendredi. Les feuilles de temps doivent être soumises avant 17 h le lundi précédant le jour de paie. Les paiements par dépôt direct sont disponibles le jour de paie; les chèques papier peuvent prendre jusqu'à 3 jours ouvrables.

**v2 — glossary-grounded output (verbatim)**

> Les employés sont payés toutes les deux semaines, le vendredi. Vous devez soumettre vos feuilles de temps avant 17 h le lundi précédant le jour de paie. Le dépôt direct est disponible le jour de paie, tandis que les chèques papier peuvent prendre jusqu'à 3 jours ouvrables. N'hésitez pas à nous contacter si vous avez d'autres questions!

**v2 judge: 5/5**

> La réponse de l'assistant est factuellement exacte, entièrement soutenue par le contexte de la politique, répond à toutes les questions posées et est rédigée en français.

**v3 — stricter output (verbatim)**

> Les employés sont payés toutes les deux semaines, le vendredi. Les paiements par dépôt direct sont disponibles le jour de paie. Les feuilles de temps doivent être soumises avant 17 h le lundi précédant le jour de paie.

**v3 judge: 5/5**

> La réponse de l'assistant est factuellement exacte, entièrement soutenue par le contexte de la politique, et rédigée dans la langue demandée.

**Deterministic checker — missing reference facts:** `3`

**Preliminary triage (not validated):** Paper-cheque delay may matter for employees using cheques; user did not specify payment method.

**Human review:**
- Relevance (`essential` / `conditional` / `supplementary` / `not relevant`): **Pending**
- Severity (`high` / `medium` / `low` / `none`): **Pending**
- Required to answer this specific question? **Pending**
- Rationale and alternative interpretations: **Pending**
- Reviewer / date: **Pending**

---

<a id="case-pay_schedule-es"></a>
### 5. `pay_schedule-es`

**User question**

> ¿Cuándo me pagan y cuándo tengo que enviar mis horas?

**Fictional policy context**

> Los empleados cobran cada dos semanas, los viernes. Las hojas de horas deben enviarse antes de las 5:00 p. m. del lunes anterior al día de pago. Los pagos por depósito directo están disponibles el día de pago; los cheques en papel pueden tardar hasta 3 días hábiles en llegar.

**v2 — glossary-grounded output (verbatim)**

> Los empleados cobran cada dos semanas, los viernes. Las hojas de horas deben enviarse antes de las 5:00 p. m. del lunes anterior al día de pago. Los pagos por depósito directo están disponibles el mismo día de pago, mientras que los cheques en papel pueden tardar hasta 3 días hábiles en llegar. ¡Por favor, asegúrese de enviar su información a tiempo!

**v2 judge: 5/5**

> La respuesta del asistente es completamente precisa, está respaldada por la política y se encuentra en el idioma correcto.

**v3 — stricter output (verbatim)**

> Los empleados cobran cada dos semanas, los viernes. Las hojas de horas deben enviarse antes de las 5:00 p. m. del lunes anterior al día de pago. Los pagos por depósito directo están disponibles el día de pago.

**v3 judge: 4/5**

> Todas las afirmaciones del asistente son correctas y están respaldadas por la política, pero omite un detalle menor sobre los cheques en papel.

**Deterministic checker — missing reference facts:** `3`

**Preliminary triage (not validated):** Paper-cheque delay may matter for employees using cheques; user did not specify payment method.

**Human review:**
- Relevance (`essential` / `conditional` / `supplementary` / `not relevant`): **Pending**
- Severity (`high` / `medium` / `low` / `none`): **Pending**
- Required to answer this specific question? **Pending**
- Rationale and alternative interpretations: **Pending**
- Reviewer / date: **Pending**

---
