response_data = response.json()

# Extract the message object
message = response_data.get("message", {})
content = message.get("content", "")
tool_calls = message.get("tool_calls", [])

print("--- Response Details ---")
if content:
    print(f"Assistant: {content}")

if tool_calls:
    print("\nThe model wants to call a tool:")
    for tool in tool_calls:
        func_name = tool['function']['name']
        func_args = tool['function']['arguments']
        print(f" -> Function to run: {func_name}")
        print(f" -> Arguments provided: {func_args}")
