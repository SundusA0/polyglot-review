# Independent, blinded response-quality review

**Review instructions:** Each case contains a fictional company policy,
the employee's actual question, and two anonymized model responses.
Assess **each answer against the user's question**, using the policy only as
a source of truth. Do not assume every policy fact must appear in an answer.
The responses are not labeled by prompt version and judge scores are hidden.

**Rating rubric:** Completeness 5 = fully addresses all question parts;
4 = adequately answers with a minor omission; 3 = partially answers;
2 = major gaps; 1 = fails to answer. For each response, record whether any
missing information would materially affect this employee (`yes`, `no`,
`unsure`), and its potential severity (`none`, `low`, `medium`, `high`).
Judge relevance separately from whether the response reproduces every
fact in the policy. Record your proficiency in the case language.

**Record scores in** [`reviewer_ratings_template.csv`](reviewer_ratings_template.csv).
The template is unfilled; no outside ratings have been collected.

## Case 01 — English

**Employee question**

> How many vacation days do I get each month, and can I roll over the ones I don't use?

**Fictional policy**

> Full-time employees accrue 1.25 days of paid time off (PTO) per month, for a total of 15 days per year. Up to 5 unused PTO days may be carried over into the next calendar year, and carried-over days must be used by March 31.

**Answer A**

> Full-time employees accrue 1.25 days of paid time off per month, for a total of 15 days per year. You may carry over up to 5 unused paid time off days into the next calendar year. Please remember that any carried-over days must be used by March 31.

**Answer B**

> Full-time employees accrue 1.25 days of paid time off per month. Up to 5 unused paid time off days may be carried over into the next calendar year. Any carried-over days must be used by March 31.

---

## Case 02 — Spanish

**Employee question**

> ¿Cuántos días libres acumulo cada mes y puedo guardar los que no use?

**Fictional policy**

> Los empleados a tiempo completo acumulan 1,25 días de vacaciones pagadas al mes, es decir, 15 días al año. Se pueden traspasar hasta 5 días de vacaciones pagadas no utilizados al siguiente año natural, y los días traspasados deben utilizarse antes del 31 de marzo.

**Answer A**

> Los empleados a tiempo completo acumulan 1,25 días de vacaciones pagadas al mes. Se pueden traspasar hasta 5 días de vacaciones pagadas no utilizados al siguiente año natural. Los días traspasados deben utilizarse antes del 31 de marzo.

**Answer B**

> ¡Hola! Como empleado a tiempo completo, acumulas 1,25 días de vacaciones pagadas al mes, lo que equivale a 15 días al año. Sí puedes guardar días no utilizados, ya que se permite traspasar hasta 5 días de vacaciones pagadas al siguiente año natural. Ten en cuenta que estos días traspasados deben utilizarse antes del 31 de marzo. ¡Estamos aquí para ayudarte si tienes más dudas!

---

## Case 03 — German

**Employee question**

> Wie viele freie Tage bekomme ich pro Monat, und kann ich nicht genutzte Tage mitnehmen?

**Fictional policy**

> Vollzeitbeschäftigte sammeln 1,25 Tage bezahlten Urlaub pro Monat an, insgesamt 15 Tage pro Jahr. Bis zu 5 nicht genutzte Urlaubstage können in das nächste Kalenderjahr übertragen werden; übertragene Tage müssen bis zum 31. März genommen werden.

**Answer A**

> Vollzeitbeschäftigte sammeln 1,25 Tage bezahlten Urlaub pro Monat an, was insgesamt 15 Tage pro Jahr ergibt. Sie können bis zu 5 nicht genutzte Urlaubstage in das nächste Kalenderjahr übertragen. Bitte beachten Sie, dass diese übertragenen Tage bis zum 31. März genommen werden müssen.

**Answer B**

> Vollzeitbeschäftigte sammeln 1,25 Tage bezahlten Urlaub pro Monat an. Bis zu 5 nicht genutzte Urlaubstage können in das nächste Kalenderjahr übertragen werden. Übertragene Tage müssen bis zum 31. März genommen werden.

---

## Case 04 — French

**Employee question**

> Quand est-ce que je reçois ma paie, et quand dois-je soumettre mes heures?

**Fictional policy**

> Les employés sont payés toutes les deux semaines, le vendredi. Les feuilles de temps doivent être soumises avant 17 h le lundi précédant le jour de paie. Les paiements par dépôt direct sont disponibles le jour de paie; les chèques papier peuvent prendre jusqu'à 3 jours ouvrables.

**Answer A**

> Les employés sont payés toutes les deux semaines, le vendredi. Les paiements par dépôt direct sont disponibles le jour de paie. Les feuilles de temps doivent être soumises avant 17 h le lundi précédant le jour de paie.

**Answer B**

> Les employés sont payés toutes les deux semaines, le vendredi. Vous devez soumettre vos feuilles de temps avant 17 h le lundi précédant le jour de paie. Le dépôt direct est disponible le jour de paie, tandis que les chèques papier peuvent prendre jusqu'à 3 jours ouvrables. N'hésitez pas à nous contacter si vous avez d'autres questions!

---

## Case 05 — Spanish

**Employee question**

> ¿Cuándo me pagan y cuándo tengo que enviar mis horas?

**Fictional policy**

> Los empleados cobran cada dos semanas, los viernes. Las hojas de horas deben enviarse antes de las 5:00 p. m. del lunes anterior al día de pago. Los pagos por depósito directo están disponibles el día de pago; los cheques en papel pueden tardar hasta 3 días hábiles en llegar.

**Answer A**

> Los empleados cobran cada dos semanas, los viernes. Las hojas de horas deben enviarse antes de las 5:00 p. m. del lunes anterior al día de pago. Los pagos por depósito directo están disponibles el mismo día de pago, mientras que los cheques en papel pueden tardar hasta 3 días hábiles en llegar. ¡Por favor, asegúrese de enviar su información a tiempo!

**Answer B**

> Los empleados cobran cada dos semanas, los viernes. Las hojas de horas deben enviarse antes de las 5:00 p. m. del lunes anterior al día de pago. Los pagos por depósito directo están disponibles el día de pago.

---
