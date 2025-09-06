import os
import json
import openai
from config import MODEL_ID

openai.api_key = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("MODEL_ID", MODEL_ID)

def call_llm(prompt, data):
    """Call the LLM with a structured prompt and return parsed JSON dict."""
    prompt = f"{prompt}\n\nData:\n{json.dumps(data, indent=1)}"
    resp = openai.chat.completions.create(
        model=os.getenv("MODEL_ID", MODEL_ID),
        messages=[{"role": "user", "content": prompt}],
    )
    content = resp.choices[0].message.content or ""

    # Strip accidental code fences if any
    cleaned = content.replace("```json", "").replace("```", "").strip()

    # Parse JSON safely
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Fall back: try to extract JSON substring if model added extra text
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start:end+1])
            except Exception:
                pass
        raise RuntimeError(f"LLM did not return valid JSON: {e}\nRaw:\n{content}")
    
def call_llm_text_output(prompt):
    resp = openai.chat.completions.create(
        model=os.getenv("MODEL_ID", MODEL_ID),
        messages=[{"role": "user", "content": prompt}],
    )
    content = resp.choices[0].message.content or ""
    return content

def call_llm_with_web_tool(PROMPT,news_item):
    resp = openai.chat.completions.create(
        model=os.getenv("MODEL_ID", "gpt-5"),   # fallback to gpt-5
        messages=[
            {
                "role": "system",
                "content": (PROMPT)
            },
            {
                "role": "user",
                "content": json.dumps(news_item)
            }
        ],
        tools=[{"type": "browse_web"}],  # enable browsing tool
    )
    
    content = resp.choices[0].message.get("content", "")
    return content

    