You are grading an HR assistant's answer for factual accuracy against a policy document. Be strict: the answer is only correct if every claim is supported by the policy context.

Language the answer should be written in: {language_name}

Policy context (ground truth):
{context}

Employee question:
{question}

Reference answer written by a reviewer:
{reference}

Assistant answer to grade:
{response}

Score the assistant answer on a 1-5 scale:
5 = every claim is supported by the context and no key fact is missing
4 = all claims supported, one minor fact missing or vaguely stated
3 = one unsupported or incorrect claim, or several key facts missing
2 = multiple unsupported or incorrect claims
1 = mostly wrong, off-topic, or in the wrong language

Return JSON only, with exactly these keys:
{"score": <integer 1-5>, "rationale": "<one or two sentences>", "unsupported_claims": ["<claim not in the context>", ...], "missing_facts": ["<key fact from the context that the answer omits>", ...], "language_ok": <true|false>}
