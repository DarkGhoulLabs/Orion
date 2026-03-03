INTENT_REGISTRY = {}

def register_intent(intent_name, handler_function):
    #print(f"REGISTERING INTENT: {intent_name}")
    INTENT_REGISTRY[intent_name] = handler_function

def get_handler(intent_name):
    return INTENT_REGISTRY.get(intent_name)