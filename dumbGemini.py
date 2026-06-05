
import json
import requests

OLLAMA_API = "http://localhost:11434/api/chat"


def web_search(query: str):
    response = requests.get(
        "https://api.duckduckgo.com/", params={"q": query, "format": "json"}
    )
    data = response.json()
    return data.get("AbstractText", "No results found.")


# Define tools
tools = [
    {
        "type": "function",
        "function": {
            "name": "web_search",  # The model needs to match this exactly
            "description": "Search the web for live information",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
]

payload = {
    "model": "llama3.2",
    "messages": [{"role": "user", "content": "Search the web for news headlines summary"}],
    "tools": tools,
    "stream": False,
}

response = requests.post(OLLAMA_API, json=payload)
response_data = response.json()

message = response_data.get("message", {})
content = message.get("content", "").strip()
tool_calls = message.get("tool_calls", [])

print("--- Response Details ---")

# --- CASE 1: The model used native Ollama tool calling ---
if tool_calls:
    print("\n[Native Tool Call Detected]")
    for tool in tool_calls:
        func_name = tool["function"]["name"]
        func_args = tool["function"]["arguments"]

        if func_name == "web_search":
            args = (
                json.loads(func_args) if isinstance(func_args, str) else func_args
            )
            query = args.get("query")
            print(f" -> Executing web_search for: {query}")
            print(f" -> Result: {web_search(query)}")

# --- CASE 2: The model typed out text JSON instead of using the API hook ---
elif content.startswith("{") and "query" in content:
    print("\n[Text-Based Tool Call Detected (Fallback Triggered)]")
    try:
        # Try to parse the text response the model gave you
        text_tool = json.loads(content)
        # Handle both "query" or nested parameters
        params = text_tool.get("parameters", text_tool)
        query_value = (
            params.get("query")
            if isinstance(params, dict)
            else params.get("query", {}).get("value")
        )

        if query_value:
            print(f" -> Parsed Query from text: {query_value}")
            print(f" -> Result: {web_search(query_value)}")
        else:
            print(f" -> Could not extract query from: {content}")
    except json.JSONDecodeError:
        print(f"Assistant wrote text that looked like JSON but couldn't be parsed: {content}")

# --- CASE 3: Standard Chat Response ---
elif content:
    print(f"Assistant: {content}")