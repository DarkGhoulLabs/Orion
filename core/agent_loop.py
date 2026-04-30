import json

from core.llm_interface import ask_orion
from core.intent_registry import get_tool
from core.argument_validator import validate_arguments

def run_agent_loop(user_input):
    context = user_input
    scratchpad = ""

    max_steps = 5
    for step_count in range(max_steps):
        llm_response = ask_orion(context + "\n" + scratchpad, mode="agent")

        try:
            data = json.loads(llm_response)
        except Exception:
            print("Agent JSON parse error (debug):", llm_response)
            print("RETRYING AGENT STEP...")
            retry_prompt = (context + "\n" + scratchpad + "\nReturn ONLY valid JSON. No text.").strip()
            llm_response = ask_orion(retry_prompt, mode="agent")
            try:
                data = json.loads(llm_response)
            except Exception:
                print("Agent JSON parse error after retry (debug):", llm_response)
                return "Agent failed due to invalid response."

        if data.get("done"):
            return data.get("message", "Task completed.")

        step = data.get("next_step")
        if not isinstance(step, dict):
            return "Agent did not return next_step."

        intent = step.get("intent")
        arguments = step.get("arguments", {})
        if not isinstance(intent, str) or not intent:
            return "Agent returned invalid intent."

        tool = get_tool(intent)
        if not tool:
            return f"Tool '{intent}' not found."

        validation = validate_arguments(intent, arguments if isinstance(arguments, dict) else arguments)
        if not validation["success"]:
            return f"Invalid arguments: {validation['error']}"

        call_args = dict(validation["arguments"])
        if intent in {"list_files", "change_directory", "delete_file"}:
            call_args["action"] = intent

        risk = tool.get("risk_level", "safe")
        if risk != "safe":
            confirm = input(f"Approve step {step}? (yes/no): ")
            if confirm.lower() != "yes":
                return "Execution stopped."

        result = tool["handler"](call_args)
        print(f"Step {step_count + 1} executed: {intent}")

        scratchpad += f"\nStep {step_count + 1}: {step}\nObservation: {result}\n"
        context += f"\nObservation: {result}"

    return "Agent stopped after reaching step limit."