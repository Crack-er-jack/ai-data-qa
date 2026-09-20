"""Groq LLM provider with JSON structured output."""

from __future__ import annotations

import json
from typing import Any

from groq import Groq

from src.errors import LlmError
from src.llm.schemas import AnalysisPlan
from src.settings import Settings, get_settings

PLAN_JSON_INSTRUCTIONS = """
Return ONLY valid JSON with this schema:
{
  "intent": "metric|comparison|trend|breakdown|lookup|follow_up|multi_question|clarification|unsupported",
  "clarification_needed": boolean,
  "clarification_question": string or null,
  "cannot_answer": boolean,
  "cannot_answer_reason": string or null,
  "required_tables": [string],
  "sql_requests": [{"sql": "SELECT ...", "purpose": "why this query"}],
  "expected_result_shape": "scalar|grouped|time_series|tabular|unknown",
  "visualization": "kpi|bar|line|histogram|table|none",
  "explanation": "short interpretation without inventing numbers",
  "metric": string or null,
  "filters": {"column": "value"},
  "grouping": string or null,
  "time_period": string or null
}

Rules:
- DuckDB is the only source of numerical truth. Never invent metrics, totals, or rankings.
- Generate DuckDB SQL that answers the question using only listed tables/columns.
- Use candidate relationships for joins when analysis spans tables.
- Prefer explicit joins. Qualify column names when more than one table is used.
- For follow-ups, reuse previous metric/filters/grouping/time period unless the user changes them.
- If several independent questions are asked, emit up to 3 sql_requests.
- Dependent analysis may use CTEs or subqueries in one statement.
- If the data cannot answer the question, set cannot_answer=true and do not invent SQL.
- If the question is ambiguous, set clarification_needed=true and ask one concise question.
- SQL must be a single read-only SELECT or WITH statement.
- Do not use INSERT, UPDATE, DELETE, DROP, CREATE, ATTACH, COPY, or file-read functions.
- explanation must not include fabricated numbers; numbers will be filled from DuckDB.
""".strip()


class GroqProvider:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.groq_api_key:
            raise LlmError("GROQ_API_KEY is not configured.")
        if self.settings.llm_provider != "groq":
            raise LlmError(f"Unsupported LLM_PROVIDER '{self.settings.llm_provider}'. Use groq.")
        self.client = Groq(api_key=self.settings.groq_api_key)
        self.model = self.settings.llm_model

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=self.settings.llm_temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            raise LlmError(f"LLM request failed: {exc}") from exc

        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise LlmError("LLM returned an empty response.")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LlmError(f"LLM returned invalid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise LlmError("LLM JSON root must be an object.")
        return parsed

    def plan(self, context: str, question: str, repair: str | None = None) -> AnalysisPlan:
        user = f"Analytical context:\n{context}\n\nUser question:\n{question}"
        if repair:
            user += (
                "\n\nThe previous SQL failed. Return a corrected plan with valid SQL.\n"
                f"Error:\n{repair}"
            )
        raw = self.complete_json(PLAN_JSON_INSTRUCTIONS, user)
        try:
            return AnalysisPlan.from_raw(raw)
        except Exception as exc:
            raise LlmError(f"LLM plan failed validation: {exc}") from exc
