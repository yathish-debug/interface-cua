SYSTEM_PROMPT = """You are an automation agent driving a real web application \
through its accessibility tree. You cannot see pixels — you see a list of \
interactive elements (each with a ref like "e2", a role, and a name) plus the \
page's visible text.

Each turn you receive the current screen. Do ONE thing by calling exactly one \
tool. Then you will see the resulting screen and continue.

Rules:
- Read VISIBLE TEXT to understand state (balances, error messages, confirmations).
- To act on a control, use its ref from INTERACTIVE ELEMENTS.
- Type into a field, then click the button that submits it. Do not assume a \
click worked — confirm from the next observation.
- When the goal's success condition is clearly met, call `finish` with \
success=true and put any data the goal asked you to read into `outputs`.
- If you are blocked and cannot make progress (needed control missing, a hard \
error, or you're going in circles), call `finish` with success=false and \
explain why in `reason`. Do not guess wildly.
- Never invent data. Only report values you can actually read on screen.
"""

TOOLS = [
    {
        "name": "click",
        "description": "Click an interactive element by its ref.",
        "input_schema": {
            "type": "object",
            "properties": {"ref": {"type": "string"}},
            "required": ["ref"],
        },
    },
    {
        "name": "type",
        "description": "Clear a field and type text into it, by its ref.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["ref", "text"],
        },
    },
    {
        "name": "finish",
        "description": "Signal the goal is complete or you are giving up.",
        "input_schema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "outputs": {"type": "object", "description": "Data the goal asked to read."},
                "reason": {"type": "string"},
            },
            "required": ["success", "reason"],
        },
    },
]