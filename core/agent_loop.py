import json

from core.llm_interface import ask_orion
from core.intent_registry import get_tool

def run_agent_loop(user_input):
    context = user_input
    scratchpad = ""

    for step_count in range(10):
        llm_response = ask_orion(context + "\n" + scratchpad, mode="agent")

        try:
            data = json.loads(llm_response)
        except:
            return "Agent failed to parse response."
        
        if data.get("done"):
            return data.get("message", "Task completed.")
        
        step = data.get("next_step")
        if not step:
            return "Agent did not return next_step."
        
        tool = get_tool(step["intent"])
        if not tool:
            return f"Tool '{step['intent']}' not found."
        
        risk = tool.get("risk_level", "safe")
        if risk != "safe":
            confirm = input(f"Approve step {step}? (yes/no): ")
            if confirm.lower() != "yes":
                return "Execution stopped."
            
        result = tool["handler"](step.get("arguments", {}))
        scratchpad += f"\nStep {step_count+1}: {step}\nObservation: {result}\n"
        context += f"\nObservation: {result}"

        return "Agent stopped after reacting step limit."