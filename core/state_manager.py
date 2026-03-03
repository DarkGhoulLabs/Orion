PENDING_ACTION = None

def set_pending(action_data):
    global PENDING_ACTION
    #print("DEBUG: setting pending action->")
    PENDING_ACTION = action_data

def get_pending():
    #print("DEBUG: getting pending action->")
    return PENDING_ACTION

def clear_pending():
    global PENDING_ACTION
    #print("DEBUG: clearing pending action")
    PENDING_ACTION = None