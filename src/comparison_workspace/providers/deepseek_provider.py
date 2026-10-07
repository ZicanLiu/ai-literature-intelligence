"""DeepSeek Responses contract: explicit JSON Schema, stateless, text inputs only."""
from .openai_provider import INSTRUCTIONS, OpenAIProvider
from ..domain.models import ExtractionOutput


class DeepSeekProvider(OpenAIProvider):
    provider_id = "deepseek"
    display_name = "DeepSeek"
    base_url = "https://api.deepseek.com"
    DEFAULT_REASONING_EFFORT = {"extraction": "none", "analysis": "high"}

    def __init__(self, *, reasoning_effort=None, **kwargs):
        super().__init__(**kwargs)
        if reasoning_effort not in {None, "none", "low", "high", "max"}:
            raise ValueError("Unsupported DeepSeek reasoning effort")
        self.reasoning_effort = reasoning_effort

    def reasoning_effort_for(self, stage):
        return self.reasoning_effort if self.reasoning_effort is not None else self.DEFAULT_REASONING_EFFORT[stage]

    def _request(self, client, payload, schema):
        stage = "extraction" if schema is ExtractionOutput else "analysis"
        # DeepSeek documents text.format with name/schema, not responses.parse or store.
        options = dict(
            model=self.model, instructions=INSTRUCTIONS, input=payload,
            text={"format": {"type": "json_schema", "name": schema.__name__,
                             "schema": schema.model_json_schema()}},
            max_output_tokens=12000, reasoning={"effort": self.reasoning_effort_for(stage)})
        request = client.responses.create
        self._begin_send("generation")
        return request(**options)

    def _parse_output(self, response, schema):
        return schema.model_validate_json(response.output_text)
